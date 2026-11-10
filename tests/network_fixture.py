"""Credential-free topology fixture, never a production egress proxy."""
import http.server
import os
from pathlib import Path
import select
import socket
import socketserver
import ssl
import sys
import threading


def pipe(left, right):
    with left, right:
        while True:
            ready, _, _ = select.select([left, right], [], [], 10)
            if not ready:
                return
            for source in ready:
                data = source.recv(65536)
                if not data:
                    return
                (right if source is left else left).sendall(data)


class ThreadedUnix(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def serve(token):
    class Endpoint(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = token.encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    upstream = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Endpoint)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain('/fixture/cert.pem', '/fixture/key.pem')
    upstream.socket = context.wrap_socket(upstream.socket, server_side=True)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()

    class Proxy(socketserver.BaseRequestHandler):
        def handle(self):
            self.request.settimeout(5)
            request = b''
            while not request.endswith(b'\r\n\r\n') and len(request) < 4096:
                data = self.request.recv(1)
                if not data:
                    return
                request += data
            if request != b'CONNECT upstream.test:443 HTTP/1.1\r\n\r\n':
                self.request.sendall(b'HTTP/1.1 403 Forbidden\r\n\r\n')
                return
            # This is an exact, controlled loopback test exception only.
            connection = socket.create_connection(upstream.server_address, 5)
            self.request.sendall(b'HTTP/1.1 200 Connection established\r\n\r\n')
            pipe(self.request, connection)

    os.umask(0o077)
    proxy = ThreadedUnix('/transport/proxy.sock', Proxy)
    proxy.serve_forever()


def probe(token):
    class Relay(socketserver.BaseRequestHandler):
        def handle(self):
            connection = socket.socket(socket.AF_UNIX)
            connection.connect('/transport/proxy.sock')
            pipe(self.request, connection)

    class Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
        daemon_threads = True

    relay = Server(('127.0.0.1', 0), Relay)
    threading.Thread(target=relay.serve_forever, daemon=True).start()
    connection = socket.create_connection(relay.server_address, 5)
    connection.sendall(b'CONNECT upstream.test:443 HTTP/1.1\r\n\r\n')
    response = b''
    while not response.endswith(b'\r\n\r\n'):
        response += connection.recv(1)
    assert response.startswith(b'HTTP/1.1 200'), response
    context = ssl.create_default_context(cafile='/cert.pem')
    with context.wrap_socket(connection, server_hostname='upstream.test') as secure:
        secure.sendall(b'GET / HTTP/1.1\r\nHost: upstream.test\r\nConnection: close\r\n\r\n')
        body = b''
        while True:
            data = secure.recv(4096)
            if not data:
                break
            body += data
    assert body.endswith(token.encode()), body
    print('PASS verified TLS through loopback relay and read-only Unix socket')
    try:
        Path('/transport/proxy.sock').unlink()
    except OSError:
        pass
    else:
        raise AssertionError('read-only socket directory was mutable')
    # Positive loopback control distinguishes isolation from broken sockets.
    assert socket.create_connection(relay.server_address, 1)
    assert os.listdir('/sys/class/net') == ['lo'], os.listdir('/sys/class/net')
    for host in ('1.1.1.1', '10.0.0.1', '169.254.169.254', '192.168.1.1',
                 'host.containers.internal', 'host.docker.internal',
                 '2606:4700:4700::1111', 'fe80::1'):
        try:
            connection = socket.create_connection((host, 443), 0.5)
        except OSError:
            pass
        else:
            connection.close()
            raise AssertionError('direct connection succeeded: ' + host)
    for family, address in ((socket.AF_INET, ('1.1.1.1', 53)),
                            (socket.AF_INET, ('1.1.1.1', 443)),
                            (socket.AF_INET6, ('2606:4700:4700::1111', 53))):
        with socket.socket(family, socket.SOCK_DGRAM) as udp:
            try:
                udp.sendto(b'credential-free DNS/UDP probe', address)
            except OSError:
                pass
            else:
                raise AssertionError('external UDP send succeeded')
    with socket.socket(socket.AF_UNIX) as denied:
        denied.connect('/transport/proxy.sock')
        denied.sendall(b'CONNECT forbidden.test:443 HTTP/1.1\r\n\r\n')
        assert denied.recv(1024).startswith(b'HTTP/1.1 403')
    print('PASS direct IPv4/IPv6, host aliases, LAN/metadata, DNS/UDP/QUIC denied')
    print('PASS own loopback available; only lo attached; socket replacement denied')


def ipc_probe(token):
    """Reproduce why IP isolation alone cannot isolate host filesystem IPC."""
    assert os.listdir('/sys/class/net') == ['lo']
    connection = socket.socket(socket.AF_UNIX)
    connection.connect('/workspace/proxy.sock')
    connection.sendall(b'CONNECT upstream.test:443 HTTP/1.1\r\n\r\n')
    response = b''
    while not response.endswith(b'\r\n\r\n'):
        response += connection.recv(1)
    assert response.startswith(b'HTTP/1.1 200'), response
    context = ssl.create_default_context(cafile='/cert.pem')
    with context.wrap_socket(connection, server_hostname='upstream.test') as secure:
        secure.sendall(b'GET / HTTP/1.1\r\nHost: upstream.test\r\nConnection: close\r\n\r\n')
        response = b''
        while True:
            data = secure.recv(4096)
            if not data:
                break
            response += data
    assert response.endswith(token.encode()), response
    print('DESIGN BLOCKER: unapproved workspace Unix socket reached external TLS service with only lo')


if __name__ == '__main__':
    {'serve': serve, 'probe': probe, 'ipc-probe': ipc_probe}[sys.argv[1]](sys.argv[2])
