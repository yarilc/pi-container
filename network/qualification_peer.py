"""Disposable dual-stack TCP/UDP positive-control endpoint. No external forwarding."""
import socket
import threading


def tcp(server):
    while True:
        peer, _ = server.accept()
        with peer:
            peer.settimeout(2)
            if peer.recv(64) == b'qualification-control':
                peer.sendall(b'qualification-positive')


def udp(server):
    while True:
        data, target = server.recvfrom(64)
        if data == b'qualification-control':
            server.sendto(b'qualification-positive', target)


for family, address in ((socket.AF_INET, '0.0.0.0'), (socket.AF_INET6, '::')):
    for kind, serve in ((socket.SOCK_STREAM, tcp), (socket.SOCK_DGRAM, udp)):
        server = socket.socket(family, kind)
        if family == socket.AF_INET6:
            server.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        server.bind((address, 8443 if kind == socket.SOCK_STREAM else 8053))
        if kind == socket.SOCK_STREAM:
            server.listen(8)
        threading.Thread(target=serve, args=(server,), daemon=True).start()
print('qualification-peer-ready', flush=True)
threading.Event().wait()
