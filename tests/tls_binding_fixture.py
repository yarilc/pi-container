"""Controlled acceptance run inside the production guard and confined relay."""
import concurrent.futures
import http.client
import json
import socket
import ssl
import sys
import time

HOSTS = sys.argv[1].split(',') if len(sys.argv) > 1 else ['localhost.localdomain']
PORT = 8443 if HOSTS[0] == 'localhost.localdomain' else 443
CA = 'cert.pem' if len(sys.argv) > 1 else '/workspace/cert.pem'


def tunnel(host=HOSTS[0]):
    raw = socket.create_connection(('127.0.0.1', 18080), 5)
    raw.settimeout(15)
    raw.sendall(('CONNECT ' + host + ':' + str(PORT) + ' HTTP/1.1\r\n\r\n').encode())
    response = b''
    while not response.endswith(b'\r\n\r\n'):
        part = raw.recv(1)
        assert part, response
        response += part
    assert b'200' in response, response
    return raw


def get(path='/', host=HOSTS[0], version=None):
    context = ssl.create_default_context(cafile=CA)
    if version:
        context.minimum_version = context.maximum_version = version
    with tunnel(host) as raw:
        with context.wrap_socket(raw, server_hostname=host) as secure:
            secure.sendall(('GET ' + path + ' HTTP/1.1\r\nHost: ' + host + '\r\nConnection: close\r\n\r\n').encode())
            response = http.client.HTTPResponse(secure)
            response.begin()
            assert response.status == 200
            return response.read()


def vec(data, size=2):
    return len(data).to_bytes(size, 'big') + data


def ext(kind, value):
    return kind.to_bytes(2, 'big') + vec(value)


def hello(name=None, extensions=None):
    if name is None:
        name = HOSTS[0].encode()
    if extensions is None:
        extensions = ext(0, vec(b'\0' + vec(name)))
    body = b'\x03\x03' + b'r' * 32 + b'\0' + vec(b'\x13\x01') + b'\x01\0' + vec(extensions)
    return b'\x01' + len(body).to_bytes(3, 'big') + body


def framed(data, size=16384):
    return b''.join(b'\x16\x03\x03' + vec(data[i:i + size]) for i in range(0, len(data), size))


def reject(payload, fragment=False):
    with tunnel() as raw:
        if fragment:
            for index in range(0, len(payload), 3):
                try:
                    raw.sendall(payload[index:index + 3])
                except OSError:
                    break
        else:
            raw.sendall(payload)
        try:
            raw.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        try:
            assert raw.recv(1) == b''
        except ConnectionResetError:
            pass


def fragmented_verified_tls():
    context = ssl.create_default_context(cafile=CA)
    context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_3
    incoming, outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
    secure = context.wrap_bio(incoming, outgoing, server_side=False, server_hostname=HOSTS[0])
    try:
        secure.do_handshake()
    except ssl.SSLWantReadError:
        pass
    initial = outgoing.read()
    assert initial[0] == 22 and int.from_bytes(initial[3:5], 'big') == len(initial) - 5
    with tunnel() as raw:
        fragmented = framed(initial[5:], 7)
        for offset in range(0, len(fragmented), 13):
            raw.sendall(fragmented[offset:offset + 13])
        while True:
            try:
                secure.do_handshake()
                break
            except ssl.SSLWantReadError:
                if outgoing.pending:
                    raw.sendall(outgoing.read())
                received = raw.recv(16384)
                assert received
                incoming.write(received)
        if outgoing.pending:
            raw.sendall(outgoing.read())
        assert secure.getpeercert()
        secure.write(b'GET / HTTP/1.1\r\nHost: ' + HOSTS[0].encode() + b'\r\nConnection: close\r\n\r\n')
        raw.sendall(outgoing.read())
        plain = b''
        while b'controlled-production-proxy-ok' not in plain:
            try:
                plain += secure.read(16384)
            except ssl.SSLWantReadError:
                received = raw.recv(16384)
                assert received
                incoming.write(received)


def verified_resumption():
    context = ssl.create_default_context(cafile=CA)
    context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_2
    session = None
    for index in range(2):
        with tunnel() as raw:
            with context.wrap_socket(raw, server_hostname=HOSTS[0], session=session) as secure:
                secure.sendall(b'GET / HTTP/1.1\r\nHost: ' + HOSTS[0].encode() + b'\r\nConnection: close\r\n\r\n')
                response = http.client.HTTPResponse(secure)
                response.begin()
                assert response.read() == b'controlled-production-proxy-ok'
                if index:
                    assert secure.session_reused
                session = secure.session


def retried_switch_rejected():
    """After a real HelloRetryRequest, a retried hello naming another host never reaches the server."""
    random = bytes.fromhex('cf21ad74e59a6111be1d8c021e65b891c2a211167abb8c5e079e09e2c8a8339c')

    def flight(name, curve=None):
        context = ssl.create_default_context(cafile=CA)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        if curve:
            context.set_ecdh_curve(curve)
        outgoing = ssl.MemoryBIO()
        client = context.wrap_bio(ssl.MemoryBIO(), outgoing, server_hostname=name)
        try:
            client.do_handshake()
        except ssl.SSLWantReadError:
            pass
        return outgoing.read()

    with tunnel() as raw:
        raw.sendall(flight(HOSTS[0]))
        received = b''
        while len(received) < 5 or len(received) < 5 + int.from_bytes(received[3:5], 'big'):
            part = raw.recv(16384)
            assert part, 'no HelloRetryRequest'
            received += part
        assert received[11:43] == random, 'fixture did not send a HelloRetryRequest'
        raw.sendall(b'\x14\x03\x03\x00\x01\x01' + flight('alternate.test', 'prime256v1'))
        later = received[5 + int.from_bytes(received[3:5], 'big'):]
        while True:
            try:
                part = raw.recv(16384)
            except ConnectionResetError:
                part = b''
            if not part:
                break
            later += part
        while later[:6] == b'\x14\x03\x03\x00\x01\x01':
            later = later[6:]
        assert later == b'', 'server answered the switched retried hello'


fragmented_verified_tls()
verified_resumption()
assert get('/retry-switch-control') == b'retry-switch-control-serverhello'
retried_switch_rejected()
assert get('/alternate-control') == b'alternate-verified-control-ok'
for host in HOSTS:
    for version in (ssl.TLSVersion.TLSv1_2, ssl.TLSVersion.TLSv1_3):
        assert get(host=host, version=version) == b'controlled-production-proxy-ok'

before = len(json.loads(get('/counts')))
name = HOSTS[0].encode()
valid_sni = ext(0, vec(b'\0' + vec(name)))
bad = [framed(hello(b'alternate.test')), framed(hello(extensions=b'')),
       framed(hello(extensions=valid_sni * 2)),
       framed(hello(extensions=valid_sni + ext(0, vec(b'\0' + vec(b'alternate.test'))))),
       framed(hello(extensions=valid_sni + ext(0xfe0d, b'grease'))),
       framed(hello(extensions=ext(0, b'\0\x10short'))), b'not-a-TLS-record',
       framed(b'\x01\x01\0\0'),
       framed(hello(extensions=valid_sni + ext(21, b'p' * 512)), 1),
       framed(hello())[:-1]]
bad += [framed(hello(extensions=valid_sni + ext(kind, b'retired-draft')))
        for kind in (0xffce, 0xff02, 0xff03, 0xff04)]
for payload in bad:
    reject(payload, fragment=True)
# Absolute deadline: no bytes are sent after CONNECT.
started = time.monotonic()
with tunnel() as stalled:
    assert stalled.recv(1) == b''
assert 9 <= time.monotonic() - started < 14
# Wait for fixture worker threads to observe closed upstreams before counting.
time.sleep(.2)
after = json.loads(get('/counts'))
observed = after[before:-1]  # Exclude the counter query's own valid TLS request.
assert len(observed) == len(bad) + 1, observed
assert all(count == 0 for count in observed), observed
with tunnel() as partial:
    partial.sendall(b'\x16')
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as workers:
        pending = [workers.submit(reject, payload) for payload in bad[:3]]
        healthy = [workers.submit(get, '/stream') for _ in range(4)]
        for result in pending:
            result.result()
        assert all(result.result() == b'abc' for result in healthy)
    partial.shutdown(socket.SHUT_WR)
    assert partial.recv(1) == b''
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as workers:
    assert all(value == b'abc' for value in workers.map(lambda _: get('/stream'), range(8)))
print('tls-destination-binding-ok profiles=' + ','.join(HOSTS) + ' zero-byte-rejections=' + str(len(observed))
      + ' retried-switch-rejected=1')
