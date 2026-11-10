"""Credential-free maximum-stream fixture, executed behind the real guard."""
import concurrent.futures
import http.client
import socket
import ssl
import time


def tunnel():
    raw = socket.create_connection(('127.0.0.1', 18080), 5)
    raw.settimeout(8)
    raw.sendall(b'CONNECT localhost.localdomain:8443 HTTP/1.1\r\n\r\n')
    response = b''
    while not response.endswith(b'\r\n\r\n'):
        part = raw.recv(1)
        assert part, response
        response += part
    assert b'200' in response, response
    return raw


stalled = []
try:
    started = time.monotonic()
    for _ in range(64):
        raw = tunnel()
        raw.sendall(b'\x16\x03\x03\x00\x20\x01')
        stalled.append(raw)
    assert time.monotonic() - started < 8, 'inspection phase did not overlap'
    print('network-ready', flush=True)
    input()
finally:
    for raw in stalled:
        raw.close()
time.sleep(.5)

context = ssl.create_default_context(cafile='cert.pem')
connections = []
try:
    for _ in range(64):
        connections.append(context.wrap_socket(tunnel(), server_hostname='localhost.localdomain'))
    print('matching-ready', flush=True)
    input()

    def exchange(secure):
        secure.sendall(b'GET /stream HTTP/1.1\r\nHost: localhost.localdomain\r\nConnection: close\r\n\r\n')
        response = http.client.HTTPResponse(secure)
        response.begin()
        assert response.status == 200
        assert response.read() == b'abc'

    with concurrent.futures.ThreadPoolExecutor(max_workers=64) as executor:
        list(executor.map(exchange, connections))
finally:
    for secure in connections:
        secure.close()
print('proxy-budget-64-streams-ok', flush=True)
