"""Synthetic application run by the confined production relay in native tests."""
import concurrent.futures
import os
from pathlib import Path
import socket
import ssl
import subprocess

# The application's inherited data channel is closed by the relay exec branch.
for entry in Path('/proc/self/fd').iterdir():
    if int(entry.name) > 2:
        try:
            assert not os.readlink(entry).startswith('socket:'), entry
        except FileNotFoundError:
            pass


def request(path='/', verify=True, timeout='10'):
    command = ['curl', '--fail', '--silent', '--show-error', '--max-time', timeout,
               '--noproxy', '', '--proxy', 'http://127.0.0.1:18080']
    if verify:
        command += ['--cacert', '/workspace/cert.pem']
    return subprocess.run([*command, 'https://localhost.localdomain:8443' + path], capture_output=True, text=True)


for _ in range(80):
    result = request()
    assert result.returncode == 0 and result.stdout == 'controlled-production-proxy-ok', result.stderr
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as workers:
    for result in workers.map(lambda _: request('/stream'), range(8)):
        assert result.returncode == 0 and result.stdout == 'abc', result.stderr
large = request('/large')
assert large.returncode == 0 and large.stdout == 'large-frame-boundary-' * 65536, large.stderr
long_stream = request('/long-stream', timeout='30')
assert long_stream.returncode == 0 and long_stream.stdout == 'progress\n' * 75, long_stream.stderr
assert request(verify=False).returncode != 0
for target in ('https://unapproved.test/', 'https://localhost.localdomain:8444/', 'https://127.0.0.1:8443/'):
    result = subprocess.run(['curl', '--fail', '--silent', '--max-time', '3', '--noproxy', '',
                             '--proxy', 'http://127.0.0.1:18080', target], capture_output=True)
    assert result.returncode != 0
connection = socket.create_connection(('127.0.0.1', 18080), 3)
connection.sendall(b'CONNECT localhost.localdomain:8443 HTTP/1.1\r\n\r\n')
response = b''
while not response.endswith(b'\r\n\r\n'):
    part = connection.recv(1)
    assert part
    response += part
assert b'200' in response
context = ssl.create_default_context(cafile='/workspace/cert.pem')
with context.wrap_socket(connection, server_hostname='localhost.localdomain') as secure:
    secure.sendall(b'GET /websocket HTTP/1.1\r\nHost: localhost.localdomain\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n')
    response = b''
    while not response.endswith(b'\r\n\r\n'):
        response += secure.recv(1)
    assert b'101' in response
    assert secure.recv(4) == b'\x81\x02ok'
print('guarded-mux-tls-ok')
