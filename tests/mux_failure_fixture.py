"""Credential-free TLS traffic across test-owned wire faults and production code."""
import socket
import ssl
import time
from pathlib import Path

context = ssl.create_default_context(cafile='/workspace/cert.pem')


def connect(path):
    connection = socket.create_connection(('127.0.0.1', 18080), 10)
    connection.settimeout(90)
    connection.sendall(b'CONNECT localhost.localdomain:8443 HTTP/1.1\r\n\r\n')
    header = b''
    while not header.endswith(b'\r\n\r\n'):
        chunk = connection.recv(1)
        assert chunk
        header += chunk
    assert b'200' in header, header
    secure = context.wrap_socket(connection, server_hostname='localhost.localdomain')
    secure.sendall(b'GET ' + path + b' HTTP/1.1\r\nHost: localhost.localdomain\r\nConnection: close\r\n\r\n')
    return secure


def response(secure):
    with secure:
        data = bytearray()
        while True:
            chunk = secure.recv(8192)
            if not chunk:
                break
            data.extend(chunk)
    return bytes(data)


assert b'controlled-production-proxy-ok' in response(connect(b'/'))
healthy = connect(b'/long-stream')
Path('/workspace/fault-ready').touch()
assert response(healthy).count(b'progress\n') == 75
deadline = time.monotonic() + 30
while not Path('/workspace/fault-complete').exists():
    assert time.monotonic() < deadline, 'wire fault did not finish'
    time.sleep(.05)
assert b'controlled-production-proxy-ok' in response(connect(b'/'))
print('guarded-mux-stream-failure-recovered', flush=True)
