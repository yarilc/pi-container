"""Disposable TLS fixture entrypoint using the selected production proxy code."""
import asyncio
import json
from pathlib import Path
import socket
import ssl
import sys

sys.path.insert(0, '/opt/sandbox-egress')
import proxy

original_resolver = socket.getaddrinfo


def resolve(host, port, *args, **kwargs):
    # Exact fixture-only DNS mapping. Production resolution/address validation
    # still executes against the separate protected fixture policy.
    return original_resolver('127.0.0.1' if host == 'qualification.invalid' else host, port, *args, **kwargs)


socket.getaddrinfo = resolve


async def main():
    trust = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    trust.load_cert_chain('/qualification/cert.pem', '/qualification/key.pem')
    counts = []

    # TLS handshake buffering must be counted before SSL consumes ClientHello.
    # A blocking listener in an independent thread provides MSG_PEEK counters.
    import threading
    listener = socket.socket()
    listener.bind(('127.0.0.1', 8443)); listener.listen(8)

    def serve():
        while True:
            raw, _ = listener.accept()
            raw.settimeout(5)
            try:
                count = len(raw.recv(16384, socket.MSG_PEEK))
                counts.append(count)
                Path('/logs/qualification-counts.json').write_text(json.dumps(counts))
                if count:
                    with trust.wrap_socket(raw, server_side=True) as secure:
                        assert secure.recv(8192).startswith(b'GET / HTTP/1.1')
                        body = b'qualification-tls-positive'
                        secure.sendall(b'HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Length: '
                                       + str(len(body)).encode() + b'\r\n\r\n' + body)
            finally:
                raw.close()

    threading.Thread(target=serve, daemon=True).start()
    await proxy.main()


if __name__ == '__main__':
    asyncio.run(main())
