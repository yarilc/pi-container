"""Production proxy/relay inspection with controlled upstream byte counters."""
import asyncio
from pathlib import Path
import shutil
import ssl
import subprocess
import tempfile
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'network'))
# Helpers live beside this file; do not depend on the runner's start directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mux
import proxy
import relay
import tls_client_hello as tls
from test_tls_client_hello import CCS, EARLY, HRR, extension, message, record, records, server_hello, sni


def certificate(directory):
    """Self-signed P-256 certificate for allowed.test and alternate.test, or None."""
    if not shutil.which('openssl'):
        return None
    result = subprocess.run(['openssl', 'req', '-x509', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:P-256',
                             '-nodes', '-keyout', str(directory / 'key.pem'), '-out', str(directory / 'cert.pem'),
                             '-days', '1', '-subj', '/CN=allowed.test',
                             '-addext', 'subjectAltName=DNS:allowed.test,DNS:alternate.test'], capture_output=True)
    return directory / 'cert.pem' if result.returncode == 0 else None


def retrying_server(cert):
    """In-memory OpenSSL server that answers every TLS 1.3 ClientHello with a HelloRetryRequest."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, cert.parent / 'key.pem')
    # A supported group absent from the client's initial key share forces HRR.
    context.set_ecdh_curve('prime256v1')
    names = []
    context.sni_callback = lambda _socket, name, _context: names.append(name)
    incoming, outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
    return context.wrap_bio(incoming, outgoing, server_side=True), incoming, outgoing, names


def client_flight(cert, name, curve=None):
    context = ssl.create_default_context(cafile=cert)
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    if curve:
        context.set_ecdh_curve(curve)
    incoming, outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
    client = context.wrap_bio(incoming, outgoing, server_hostname=name)
    try:
        client.do_handshake()
    except ssl.SSLWantReadError:
        pass
    return client, incoming, outgoing, outgoing.read()


def step(endpoint):
    try:
        endpoint.do_handshake()
        return True
    except ssl.SSLWantReadError:
        return False


class TLSProxyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        asyncio.get_running_loop().set_debug(False)
        self.received = []
        self.scripts = []
        self.connections = []
        self.audit = []
        self.instance = proxy.Proxy({'destinations': [{'host': 'allowed.test', 'port': 443}]},
                                    type('Audit', (), {'record': lambda _, *args: self.audit.append(args)})())
        self.upstream = await asyncio.start_server(self.endpoint, '127.0.0.1', 0)
        self.server = await asyncio.start_server(self.instance.handle, '127.0.0.1', 0)
        self.original_connect = self.instance.connect
        self.instance.connect = self.connect
        reader, writer = await asyncio.open_connection('127.0.0.1', self.server.sockets[0].getsockname()[1])
        self.channel = await mux.Channel(reader, writer).start()
        self.relay = await asyncio.start_server(relay.Relay(self.channel).handle, '127.0.0.1', 0)

    async def endpoint(self, reader, writer):
        self.connections.append(writer)
        data = bytearray()
        self.received.append(data)
        script = self.scripts.pop(0) if self.scripts else None
        try:
            if script:
                await script(reader, writer, data)
                return
            while part := await reader.read(16384):
                data.extend(part)
                writer.write(part)
                await writer.drain()
        finally:
            writer.close()

    async def connect(self, host, port):
        if (host, port) not in self.instance.rules:
            raise proxy.Rejected('policy-denied', host, port)
        return await asyncio.open_connection('127.0.0.1', self.upstream.sockets[0].getsockname()[1])

    async def asyncTearDown(self):
        await self.channel.close()
        for writer in self.connections:
            writer.close()
            await writer.wait_closed()
        for server in (self.relay, self.server, self.upstream):
            server.close()
            await server.wait_closed()
        await asyncio.sleep(.01)
        self.assertEqual(self.instance.inspection_storage, 0)

    async def rejected(self, payload):
        stream = await self.channel.open(b'allowed.test:443')
        await stream.send(payload)
        await stream.eof()
        try:
            data = await asyncio.wait_for(stream.read(), 2)
        except mux.StreamClosed:
            data = b''
        self.assertEqual(data, b'')
        await stream.close()
        self.assertEqual(bytes(self.received[-1]), b'')
        self.assertFalse(self.channel.closed)

    async def accepted(self, payload):
        stream = await self.channel.open(b'allowed.test:443')
        for index in range(0, len(payload), 7):
            await stream.send(payload[index:index + 7])
        result = bytearray()
        while len(result) < len(payload):
            result.extend(await asyncio.wait_for(stream.read(), 2))
        self.assertEqual(result, payload)
        await stream.close()

    async def test_direct_mux_rejection_zero_upstream_bytes_and_reuse(self):
        for payload in (records(message(sni(b'other.test'))), b'not-tls', records(message(b'')),
                        records(message(sni() + extension(0xfe0d, b'grease'))), records(message(sni() * 2)),
                        records(message(sni(b'secret-token.test'))), records(message(sni(b'secret\n.test')))):
            await self.rejected(payload)
        await self.accepted(records(message()) + b'ordered-trailing-bytes')
        self.assertNotIn('other.test', repr(self.audit))
        self.assertNotIn('grease', repr(self.audit))
        self.assertNotIn('secret', repr(self.audit))
        self.assertIn('tls-identity', repr(self.audit))
        self.assertIn('tls-ech', repr(self.audit))

    async def test_actual_connect_relay_progress_and_exact_forwarding(self):
        reader, writer = await asyncio.open_connection('127.0.0.1', self.relay.sockets[0].getsockname()[1])
        writer.write(b'CONNECT allowed.test:443 HTTP/1.1\r\n\r\n')
        await writer.drain()
        response = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 2)
        self.assertIn(b'200', response)
        self.assertEqual(bytes(self.received[-1]), b'')
        wire = records(message(), 1)
        writer.write(wire)
        await writer.drain()
        self.assertEqual(await asyncio.wait_for(reader.readexactly(len(wire)), 2), wire)
        writer.close()
        await writer.wait_closed()

    async def test_absolute_timeout_overflow_and_concurrent_progress(self):
        with patch('proxy.INSPECTION_TIMEOUT', .08):
            stream = await self.channel.open(b'allowed.test:443')
            async def trickle():
                try:
                    for byte in records(message()):
                        await stream.send(bytes([byte]))
                        await asyncio.sleep(.02)
                except mux.StreamClosed:
                    pass
            sending = asyncio.create_task(trickle())
            await self.accepted(records(message()))
            try:
                await asyncio.wait_for(stream.read(), 1)
            except mux.StreamClosed:
                pass
            await sending
            await stream.close()
        self.assertIn('tls-timeout', repr(self.audit))
        await self.rejected(b'\x16\x03\x03\0\x04\x01\x01\0\0')
        self.assertIn('tls-overflow', repr(self.audit))

    async def test_channel_death_releases_inspection(self):
        streams = await asyncio.gather(*(self.channel.open(b'allowed.test:443') for _ in range(64)))
        await asyncio.sleep(.01)
        self.assertEqual(self.instance.inspection_storage, 64 * tls.STORAGE)
        await self.channel.close()
        for _ in range(100):
            if self.instance.inspection_storage == 0:
                break
            await asyncio.sleep(.01)
        self.assertEqual(self.instance.inspection_storage, 0)

    async def test_inspection_storage_limit_fails_closed(self):
        # Reserve the complete bounded session budget, then exercise overflow.
        self.instance.inspection_storage = tls.STORAGE * proxy.MAX_CONNECTIONS
        try:
            try:
                stream = await self.channel.open(b'allowed.test:443')
            except mux.StreamClosed:
                pass
            else:
                try:
                    await asyncio.wait_for(stream.read(), 2)
                except mux.StreamClosed:
                    pass
                await stream.close()
            self.assertEqual(bytes(self.received[-1]), b'')
            self.assertIn('tls-overflow', repr(self.audit))
        finally:
            self.instance.inspection_storage = 0

    # Retried ClientHello binding (TLS 1.3 HelloRetryRequest) --------------------

    def answering(self, first, response, then_echo=True):
        """Upstream that answers the first `first` bytes with `response`, then echoes."""
        async def script(reader, writer, data):
            while len(data) < first:
                part = await reader.read(16384)
                if not part:
                    return
                data.extend(part)
            for index in range(0, len(response), 3):
                writer.write(response[index:index + 3])
                await writer.drain()
            while part := await reader.read(16384):
                data.extend(part)
                if then_echo:
                    writer.write(part)
                    await writer.drain()
        return script

    async def read_exactly(self, stream, size):
        result = bytearray()
        while len(result) < size:
            part = await asyncio.wait_for(stream.read(), 2)
            self.assertTrue(part, 'stream ended early')
            result.extend(part)
        return bytes(result)

    async def closed(self, stream):
        try:
            while await asyncio.wait_for(stream.read(), 2):
                pass
        except mux.StreamClosed:
            pass
        await stream.close()

    async def test_retry_with_matching_name_is_forwarded_once_in_order(self):
        first = records(message(sni(b'Allowed.Test')))
        second = records(message(sni(b'allowed.test.')), 9)
        for early, middle in ((b'', CCS), (EARLY, CCS), (EARLY, b''), (b'', CCS + EARLY)):
            with self.subTest(early=bool(early), middle=len(middle)):
                self.scripts.append(self.answering(len(first), HRR))
                stream = await self.channel.open(b'allowed.test:443')
                await stream.send(first + early)
                self.assertEqual(await self.read_exactly(stream, len(HRR)), HRR)
                for index in range(0, len(middle + second), 11):
                    await stream.send((middle + second)[index:index + 11])
                flight = early + middle + second
                self.assertEqual(await self.read_exactly(stream, len(flight)), flight)
                await stream.send(b'\x17\x03\x03\0\x02ok')
                self.assertEqual(await self.read_exactly(stream, 7), b'\x17\x03\x03\0\x02ok')
                self.assertEqual(bytes(self.received[-1]), first + flight + b'\x17\x03\x03\0\x02ok')
                await stream.close()

    async def test_retry_with_another_identity_is_rejected_before_forwarding(self):
        first = records(message())
        cases = ((records(message(sni(b'other.test'))), 'tls-retry-identity'),
                 (CCS + records(message(b'')), 'tls-retry-identity'),
                 (records(message(sni() + extension(0xfe0d, b''))), 'tls-ech'),
                 (record(21, b'\x02\x28'), 'tls-malformed'),
                 (records(message() + b'\x01\0\0\0'), 'tls-malformed'),
                 (b'not-tls-at-all', 'tls-malformed'))
        for second, reason in cases:
            with self.subTest(reason=reason, second=second[:6]):
                self.audit.clear()
                self.scripts.append(self.answering(len(first), HRR))
                stream = await self.channel.open(b'allowed.test:443')
                await stream.send(first)
                self.assertEqual(await self.read_exactly(stream, len(HRR)), HRR)
                await stream.send(second)
                await self.closed(stream)
                await asyncio.sleep(.02)
                # Not one byte of the retried hello reached the upstream.
                self.assertEqual(bytes(self.received[-1]), first)
                self.assertEqual(self.audit, [(reason, 'allowed.test', 443)])
                self.assertNotIn('other.test', repr(self.audit))

    async def test_second_hello_sent_before_the_retry_is_held(self):
        first = records(message())
        other = records(message(sni(b'other.test')))
        self.scripts.append(self.answering(len(first), HRR))
        stream = await self.channel.open(b'allowed.test:443')
        await stream.send(first + CCS + other)
        self.assertEqual(await self.read_exactly(stream, len(HRR)), HRR)
        await self.closed(stream)
        await asyncio.sleep(.02)
        self.assertEqual(bytes(self.received[-1]), first)
        self.assertIn('tls-retry-identity', repr(self.audit))
        # The same pipelined flight with the authorized name is released after the retry.
        second = records(message())
        self.scripts.append(self.answering(len(first), HRR))
        stream = await self.channel.open(b'allowed.test:443')
        await stream.send(first + CCS + second)
        self.assertEqual(await self.read_exactly(stream, len(HRR) + len(CCS + second)), HRR + CCS + second)
        self.assertEqual(bytes(self.received[-1]), first + CCS + second)
        await stream.close()

    async def test_no_retry_releases_held_bytes_and_stays_opaque(self):
        first = records(message())
        flights = {
            'tls13': (server_hello(), EARLY + b'held-bytes', record(22, b'\x01' + b'x' * 40) + EARLY),
            'tls12': (server_hello(b'\x12' * 32) + record(22, b'\x0e\0\0\0'), b'',
                      record(22, b'\x10\0\0\x02xy') + CCS + record(22, b'\x01encrypted-finished')),
            'alert': (record(21, b'\x02\x28'), b'anything', b'more'),
        }
        for name, (response, held, later) in flights.items():
            with self.subTest(name):
                self.scripts.append(self.answering(len(first), response))
                stream = await self.channel.open(b'allowed.test:443')
                await stream.send(first + held)
                self.assertEqual(await self.read_exactly(stream, len(response) + len(held)), response + held)
                await stream.send(later)
                self.assertEqual(await self.read_exactly(stream, len(later)), later)
                self.assertEqual(bytes(self.received[-1]), first + held + later)
                await stream.close()

    async def test_retry_gate_deadline_eof_and_overflow(self):
        first = records(message())
        async def silent(reader, writer, data):
            while part := await reader.read(16384):
                data.extend(part)
        with patch('proxy.INSPECTION_TIMEOUT', .1):
            # The upstream never answers: held bytes are discarded at the deadline.
            self.scripts.append(silent)
            stream = await self.channel.open(b'allowed.test:443')
            await stream.send(first + CCS)
            await self.closed(stream)
            self.assertEqual(bytes(self.received[-1]), first)
            self.assertIn('tls-timeout', repr(self.audit))
            # A retry is answered, but the second hello never completes.
            self.audit.clear()
            self.scripts.append(self.answering(len(first), HRR))
            stream = await self.channel.open(b'allowed.test:443')
            await stream.send(first)
            self.assertEqual(await self.read_exactly(stream, len(HRR)), HRR)
            await stream.send(records(message())[:20])
            await self.closed(stream)
            self.assertEqual(bytes(self.received[-1]), first)
            self.assertIn('tls-timeout', repr(self.audit))
        # Premature end after the retry.
        self.audit.clear()
        self.scripts.append(self.answering(len(first), HRR))
        stream = await self.channel.open(b'allowed.test:443')
        await stream.send(first)
        self.assertEqual(await self.read_exactly(stream, len(HRR)), HRR)
        await stream.send(records(message())[:20])
        await stream.eof()
        await self.closed(stream)
        self.assertEqual(bytes(self.received[-1]), first)
        self.assertIn('tls-malformed', repr(self.audit))
        # Held bytes beyond the fixed buffer before the upstream decides.
        self.audit.clear()
        self.scripts.append(silent)
        stream = await self.channel.open(b'allowed.test:443')
        await stream.send(first)
        try:
            for _ in range(tls.MAX_WIRE // 16384 + 2):
                await stream.send(record(23, b'x' * 16384))
        except mux.StreamClosed:
            pass
        await self.closed(stream)
        self.assertEqual(bytes(self.received[-1]), first)
        self.assertIn('tls-overflow', repr(self.audit))

    async def test_concurrent_retry_failure_leaves_other_tunnels_working(self):
        first = records(message())
        self.scripts.extend([self.answering(len(first), HRR), self.answering(len(first), HRR)])
        bad = await self.channel.open(b'allowed.test:443')
        good = await self.channel.open(b'allowed.test:443')
        await asyncio.gather(bad.send(first), good.send(first))
        self.assertEqual(await self.read_exactly(bad, len(HRR)), HRR)
        self.assertEqual(await self.read_exactly(good, len(HRR)), HRR)
        await bad.send(records(message(sni(b'other.test'))))
        await self.closed(bad)
        second = CCS + records(message())
        await good.send(second)
        self.assertEqual(await self.read_exactly(good, len(second)), second)
        await self.accepted(records(message()) + b'third-tunnel')
        await good.close()
        self.assertFalse(self.channel.closed)
        for _ in range(100):
            if self.instance.inspection_storage == 0:
                break
            await asyncio.sleep(.01)
        self.assertEqual(self.instance.inspection_storage, 0)

    async def test_real_openssl_retry_binding(self):
        """A real OpenSSL server accepts a switched retried SNI; the proxy must not let it through."""
        with tempfile.TemporaryDirectory() as directory:
            cert = certificate(Path(directory))
            if cert is None:
                self.skipTest('openssl CLI unavailable for a controlled certificate')
            # Unfiltered positive control: OpenSSL answers a retried hello naming another host.
            server, s_in, s_out, names = retrying_server(cert)
            _, _, _, first = client_flight(cert, 'allowed.test')
            s_in.write(first)
            step(server)
            retry = s_out.read()
            self.assertEqual(retry[11:43], tls.HELLO_RETRY_RANDOM)
            _, _, _, switched = client_flight(cert, 'alternate.test', 'prime256v1')
            s_in.write(CCS + switched)
            step(server)
            self.assertEqual(s_out.read()[5], 2, 'control: server answered the switched hello')
            self.assertEqual(names, ['allowed.test', 'alternate.test'])

            async def serve(reader, writer, data):
                server, s_in, s_out, names = retrying_server(cert)
                done = False
                while not done:
                    part = await reader.read(16384)
                    if not part:
                        return
                    data.extend(part)
                    s_in.write(part)
                    done = step(server)
                    if out := s_out.read():
                        writer.write(out)
                        await writer.drain()
                if out := s_out.read():
                    writer.write(out)
                    await writer.drain()
                server.write(b'served:' + ','.join(names).encode())
                writer.write(s_out.read())
                await writer.drain()
                while part := await reader.read(16384):
                    data.extend(part)

            # Through the proxy: the genuine retried handshake completes with verification.
            self.scripts.append(serve)
            stream = await self.channel.open(b'allowed.test:443')
            client, c_in, c_out, flight = client_flight(cert, 'allowed.test')
            await stream.send(flight)
            plain = b''
            while not plain:
                c_in.write(await asyncio.wait_for(stream.read(), 2))
                if step(client) or c_out.pending:
                    if c_out.pending:
                        await stream.send(c_out.read())
                    try:
                        plain = client.read(1024)
                    except ssl.SSLWantReadError:
                        pass
            self.assertEqual(plain, b'served:allowed.test,allowed.test')
            self.assertTrue(client.getpeercert())
            await stream.close()

            # Through the proxy: the switched retried hello never reaches the server.
            self.audit.clear()
            self.scripts.append(serve)
            stream = await self.channel.open(b'allowed.test:443')
            await stream.send(first)
            response = bytearray()
            while len(response) < 5 or len(response) < 5 + int.from_bytes(response[3:5], 'big'):
                response.extend(await asyncio.wait_for(stream.read(), 2))
            self.assertEqual(bytes(response[11:43]), tls.HELLO_RETRY_RANDOM)
            await stream.send(CCS + switched)
            await self.closed(stream)
            await asyncio.sleep(.02)
            self.assertEqual(bytes(self.received[-1]), first)
            self.assertEqual(self.audit, [('tls-retry-identity', 'allowed.test', 443)])


if __name__ == '__main__':
    unittest.main()
