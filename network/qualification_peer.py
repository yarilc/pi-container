"""Disposable TCP/UDP positive-control endpoint. No external forwarding.

The fixed argument selects ``dual`` (IPv4 and IPv6) or ``ipv4`` (hosts whose
kernel has no IPv6 stack).
"""
import socket
import sys
import threading

if sys.argv[1:] not in (['dual'], ['ipv4']):
    raise SystemExit('fixed peer family selection required: dual or ipv4')
FAMILIES = ((socket.AF_INET, '0.0.0.0'), (socket.AF_INET6, '::'))[:2 if sys.argv[1] == 'dual' else 1]


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


for family, address in FAMILIES:
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
