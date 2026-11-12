"""Session-owned CONNECT proxy. Only this process can resolve upstreams."""
import asyncio
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import sys
import time

from mux import Channel, IDLE_TIMEOUT as STREAM_IDLE, MAX_DATA, OPEN_OK, OPEN_ERR, StreamClosed, ProtocolError, bridge, bounded
from policy import PolicyError, hostname, load, public_address, revision, selected
from revisions import GUARD_REQUIRED_ABI, GUARD_REVISION, TLS_ENFORCEMENT as ENFORCEMENT
from tls_client_hello import ClientHello, ServerHello, TLSRejected, STORAGE, INSPECTION_TIMEOUT, NO_RETRY, RETRY


MAX_HEADER = 8192
MAX_CONNECTIONS = 64
IDLE_TIMEOUT = 300
MAX_LIFETIME = 12 * 60 * 60


class Rejected(Exception):
    def __init__(self, reason, host='', port=0):
        self.reason, self.host, self.port = reason, host, port


def authority(request):
    try:
        lines = request.decode('ascii').split('\r\n')
        first = lines[0].split(' ')
        if len(first) != 3 or first[0] != 'CONNECT' or first[2] not in ('HTTP/1.0', 'HTTP/1.1'):
            raise ValueError()
        raw_host, raw_port = first[1].split(':')
        host = hostname(raw_host)
        if not re.fullmatch(r'[1-9][0-9]{0,4}', raw_port):
            raise ValueError()
        port = int(raw_port)
        if port > 65535 or not request.endswith(b'\r\n\r\n'):
            raise ValueError()
        for line in lines[1:-2]:
            key, value = line.split(':', 1)
            if not re.fullmatch(r'[A-Za-z0-9-]+', key) or any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise ValueError()
            if key.lower() in ('content-length', 'transfer-encoding', 'upgrade', 'proxy-authorization'):
                raise ValueError()
        return host, port
    except (ValueError, PolicyError, UnicodeError):
        raise Rejected('invalid-request') from None


def resolve(host, port, exception=None):
    try:
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    except OSError:
        raise Rejected('dns-failure', host, port) from None
    addresses = []
    for family, kind, proto, _, address in records:
        ip = ipaddress.ip_address(address[0])
        if family not in (socket.AF_INET, socket.AF_INET6) or (
                str(ip) not in exception if exception else not public_address(str(ip))):
            raise Rejected('unsafe-address', host, port)
        item = (family, kind, proto, address)
        if item not in addresses:
            addresses.append(item)
    if not addresses:
        raise Rejected('dns-failure', host, port)
    return addresses


class Audit:
    def __init__(self, path, session):
        self.path, self.session = Path(path), session
        self.size_limit = 1024 * 1024

    def record(self, reason, host='', port=0):
        # Only normalized hostnames reach this point. Never use raw request data.
        if self.path.exists() and self.path.stat().st_size >= self.size_limit:
            return
        entry = json.dumps({'session': self.session, 'reason': reason,
                            'host': host[:253], 'port': port, 'time': int(time.time())}) + '\n'
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'a') as log:
            log.write(entry)


class Proxy:
    def __init__(self, profile, audit):
        self.rules = {(d['host'], d['port']): d.get('addresses') for d in profile['destinations']}
        self.audit = audit
        self.active = 0
        self.dns_pending = 0
        self.inspection_storage = 0

    def reserve(self):
        if self.inspection_storage + STORAGE > STORAGE * MAX_CONNECTIONS:
            raise TLSRejected('tls-overflow')
        self.inspection_storage += STORAGE

    async def inspect(self, stream, writer, host):
        """Forward only the validated initial ClientHello; later bytes stay held in the parser."""
        parser = ClientHello(host)
        try:
            async with asyncio.timeout(INSPECTION_TIMEOUT):
                while not parser.done:
                    data = await stream.read()
                    if not data:
                        parser.finish()
                    parser.feed(data)
        except asyncio.TimeoutError:
            raise TLSRejected('tls-timeout') from None
        writer.write(parser.original())
        await asyncio.wait_for(writer.drain(), 30)
        return parser

    async def retry_gate(self, stream, reader, writer, parser):
        """Bind a TLS 1.3 retried ClientHello to the authorized host (RFC 8446 section 4.1.4).

        Client bytes after the initial ClientHello are held until the upstream's
        first handshake message shows whether it is a HelloRetryRequest. Upstream
        bytes are classified before they are relayed, so the client can never
        answer a retry the proxy has not seen. Without a retry, held bytes are
        forwarded unchanged and the tunnel continues opaquely.
        """
        observer = ServerHello()
        decided = asyncio.Event()
        state = {'reading': False, 'stop': False}

        async def upstream():
            while not state['stop']:
                state['reading'] = True
                data = await bounded(reader.read(MAX_DATA), STREAM_IDLE)
                state['reading'] = False
                if not data:
                    observer.eof()
                    decided.set()
                    return
                if observer.feed(data):
                    decided.set()
                await stream.send(data)

        relay = asyncio.create_task(upstream())
        decision = asyncio.create_task(decided.wait())
        waiter = None
        try:
            async with asyncio.timeout(INSPECTION_TIMEOUT):
                retrying = False
                while observer.decision != NO_RETRY and not (retrying and parser.done):
                    if observer.decision == RETRY and not retrying:
                        # Everything held so far must form the retried ClientHello.
                        retrying = True
                        parser.next_hello()
                        continue
                    if relay.done() and relay.exception():
                        raise relay.exception()
                    waiter = waiter or asyncio.create_task(stream.readable())
                    pending = {waiter} | {task for task in (relay, decision) if not task.done()}
                    await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                    if waiter.done():
                        waiter.result()
                        waiter = None
                        data = await stream.read()
                        if not data or (retrying and parser.done):
                            raise TLSRejected('tls-malformed')
                        if retrying:
                            parser.feed(data)
                        else:
                            parser.hold(data)
        except asyncio.TimeoutError:
            raise TLSRejected('tls-timeout') from None
        except TLSRejected as error:
            if str(error) == 'tls-identity':
                raise TLSRejected('tls-retry-identity') from None
            raise
        finally:
            for task in (waiter, decision):
                if task:
                    task.cancel()
            state['stop'] = True
            # A read can be cancelled without losing data; a relay send in flight completes.
            if state['reading']:
                relay.cancel()
            await asyncio.gather(relay, return_exceptions=True)
        writer.write(parser.held() if retrying else parser.surplus())
        await asyncio.wait_for(writer.drain(), 30)

    async def connect(self, host, port):
        if (host, port) not in self.rules:
            raise Rejected('policy-denied', host, port)
        loop = asyncio.get_running_loop()
        # A timeout cannot cancel getaddrinfo in a worker thread. Keep its slot
        # occupied until the worker actually returns, preventing queue growth.
        if self.dns_pending >= 16:
            raise Rejected('dns-unavailable', host, port)
        self.dns_pending += 1
        future = loop.run_in_executor(None, resolve, host, port, self.rules[(host, port)])
        def released(_):
            self.dns_pending -= 1
        future.add_done_callback(released)
        addresses = await asyncio.wait_for(asyncio.shield(future), 10)
        for family, kind, proto, address in addresses:
            try:
                # A kernel without the family (EAFNOSUPPORT, e.g. ipv6.disable=1)
                # moves on to the next validated address.
                upstream = socket.socket(family, kind, proto)
            except OSError:
                continue
            upstream.setblocking(False)
            try:
                # sock_connect receives a numeric sockaddr; never resolve again.
                await asyncio.wait_for(loop.sock_connect(upstream, address), 5)
                return await asyncio.open_connection(sock=upstream)
            except OSError:
                upstream.close()
            except BaseException:
                upstream.close()
                raise
        raise Rejected('upstream-unavailable', host, port)

    async def tunnel(self, stream, raw_authority):
        upstream_writer = None
        host, port = '', 0
        try:
            if not re.fullmatch(rb'[A-Za-z0-9.-]+:[1-9][0-9]{0,4}', raw_authority):
                raise Rejected('invalid-request')
            host, port = authority(b'CONNECT ' + raw_authority + b' HTTP/1.1\r\n\r\n')
            upstream_reader, upstream_writer = await self.connect(host, port)
            if stream.closed:
                return
            stream.opened = True
            await stream.channel.frame(OPEN_OK, stream.ident)
            self.reserve()
            try:
                parser = await self.inspect(stream, upstream_writer, host)
                await self.retry_gate(stream, upstream_reader, upstream_writer, parser)
            finally:
                parser = None
                self.inspection_storage -= STORAGE
            await bridge(stream, upstream_reader, upstream_writer)
        except TLSRejected as error:
            self.audit.record(str(error), host, port)
        except Rejected as error:
            self.audit.record(error.reason, error.host, error.port)
            if not stream.closed:
                reason = b'denied' if error.reason in ('policy-denied', 'invalid-request', 'unsafe-address') else b'unavailable'
                await stream.channel.frame(OPEN_ERR, stream.ident, reason)
        except (OSError, asyncio.TimeoutError):
            self.audit.record('connection-failure', host, port)
            if not stream.opened and not stream.closed:
                await stream.channel.frame(OPEN_ERR, stream.ident, b'unavailable')
        finally:
            if upstream_writer:
                upstream_writer.close()

    async def handle(self, reader, writer):
        # The proxy is session-owned. Only the single bootstrap channel is used;
        # no channel reconnect or protocol administration is supported.
        if self.active:
            writer.close()
            return
        self.active += 1
        channel = Channel(reader, writer, on_open=self.tunnel, audit=self.audit)
        try:
            await channel.start()
            await channel.receiver
        except (OSError, ProtocolError, asyncio.TimeoutError, asyncio.IncompleteReadError):
            self.audit.record('transport-unavailable')
        finally:
            await channel.close()
            # Do not accept a replacement channel after the bootstrap disconnects.



def validate_manifest(manifest, policy_identity, profile, session):
    if (manifest.get('policy') != policy_identity or manifest.get('profile') != profile or
            manifest.get('session') != session or manifest.get('protocol') != 1 or
            manifest.get('tls_enforcement') != ENFORCEMENT or
            manifest.get('revision') != GUARD_REVISION or manifest.get('required_abi') != GUARD_REQUIRED_ABI or
            manifest.get('filter') != 'native-x86_64-v1' or
            not re.fullmatch(r'[a-f0-9]{64}', manifest.get('sha256', ''))):
        raise ValueError('invalid protected session manifest')


async def main():
    policy = load('/config/policy.json')
    profile = selected(policy, os.environ['EGRESS_PROFILE'])
    manifest = json.loads(Path('/config/manifest.json').read_text())
    validate_manifest(manifest, revision(policy), os.environ['EGRESS_PROFILE'], os.environ['EGRESS_SESSION'])
    os.umask(0o077)
    proxy = Proxy(profile, Audit('/logs/denials.jsonl', os.environ['EGRESS_SESSION']))
    server = await asyncio.start_unix_server(proxy.handle, '/transport/proxy.sock', limit=MAX_HEADER)
    Path('/transport/ready').write_text(revision(policy) + ' guard=' + manifest['sha256'] + ' mux=1 tls=' + ENFORCEMENT + '\n')
    async with server:
        await server.serve_forever()


if __name__ == '__main__':
    asyncio.run(main())
