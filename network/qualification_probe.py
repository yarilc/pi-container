"""Fixed qualification program. All commands and code paths are protected inputs."""
import errno
import http.client
import json
import os
from pathlib import Path
import socket
import ssl
import sys
import time


config = json.loads(Path('/opt/sandbox-egress/qualification.json').read_text())


def external(allowed):
    for address in config['addresses']:
        family = socket.AF_INET6 if ':' in address else socket.AF_INET
        for kind, port in ((socket.SOCK_STREAM, 8443), (socket.SOCK_DGRAM, 8053)):
            with socket.socket(family, kind) as peer:
                peer.settimeout(2)
                if allowed:
                    peer.connect((address, port))
                    peer.sendall(b'qualification-control')
                    assert peer.recv(64) == b'qualification-positive'
                else:
                    try:
                        if kind == socket.SOCK_DGRAM:
                            peer.sendto(b'qualification-control', (address, port))
                        else:
                            peer.connect((address, port))
                    except OSError as error:
                        assert error.errno in (errno.ENETUNREACH, errno.EHOSTUNREACH), error
                    else:
                        raise AssertionError('external transport escaped')


def kernel_rejects_ipv6():
    # Hosts without a kernel IPv6 stack: IPv6 denial is evidenced by the kernel
    # refusing the family, never by a skipped check or an unrelated error.
    for kind in (socket.SOCK_STREAM, socket.SOCK_DGRAM):
        try:
            socket.socket(socket.AF_INET6, kind).close()
        except OSError as error:
            assert error.errno == errno.EAFNOSUPPORT, error
        else:
            raise AssertionError('IPv6 sockets exist on a host qualified without IPv6')


def unix_control(names):
    for name, kind in names:
        with socket.socket(socket.AF_UNIX, kind) as peer:
            peer.settimeout(2)
            peer.connect('/workspace/' + name)
            peer.sendall(b'qualification-positive')


def effective_budgets(budgets, cgroup=Path('/sys/fs/cgroup'), membership=Path('/proc/self/cgroup')):
    # Effective agent budgets in this container's private cgroup v2 namespace.
    # Enforced budgets must match exactly; a budget whose controller the engine
    # does not delegate must be absent (missing interface or 'max').
    assert membership.read_text() == '0::/\n', 'unsupported cgroup namespace'
    enforced = budgets['enforced']

    def limit(name):
        path = cgroup / name
        return path.read_text().split() if path.exists() else None
    memory, pids, cpu = limit('memory.max'), limit('pids.max'), limit('cpu.max')
    if 'memory' in enforced:
        assert memory and memory[0] != 'max' and int(memory[0]) == budgets['memory'], 'agent memory budget is not effective'
    else:
        assert memory in (None, ['max']), 'unenforced agent memory budget is present'
    if 'pids' in enforced:
        assert pids and pids[0] != 'max' and int(pids[0]) == budgets['pids'], 'agent process budget is not effective'
    else:
        assert pids in (None, ['max']), 'unenforced agent process budget is present'
    if 'cpu' in enforced:
        assert cpu and len(cpu) == 2 and cpu[0] != 'max' and \
            int(cpu[0]) * 10**9 == budgets['nano_cpus'] * int(cpu[1]), 'agent CPU budget is not effective'
    else:
        assert cpu is None or cpu[0] == 'max', 'unenforced agent CPU budget is present'


if sys.argv[1:] == ['control']:
    external(True)
    if not config['ipv6']:
        kernel_rejects_ipv6()
    unix_control((('external.sock', socket.SOCK_STREAM), ('seq.sock', socket.SOCK_SEQPACKET),
                  ('dgram.sock', socket.SOCK_DGRAM)))
    print('qualification-controls-ok', flush=True)
    sys.exit(0)

if sys.argv[1:] != ['probe']:
    raise RuntimeError('fixed qualification operation required')

status = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines())
assert all(int(status[name], 16) == 0 for name in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb'))
assert int(status['NoNewPrivs']) == 1 and int(status['Seccomp']) == 2
effective_budgets(config['budgets'])
assert os.listdir('/sys/class/net') == ['lo']
for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'NO_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'no_proxy', 'all_proxy'):
    os.environ.pop(key, None)
external(False)
if not config['ipv6']:
    kernel_rejects_ipv6()

# Broad syscall/IPC assertions use the production binary and contain no mocks.
exec(compile(Path('/opt/sandbox-egress/qualification_runtime.py').read_text(),
             '/opt/sandbox-egress/qualification_runtime.py', 'exec'))
Path('/workspace/guard-ready').touch()
deadline = time.monotonic() + 10
while not Path('/workspace/late.sock').exists():
    assert time.monotonic() < deadline, 'late Unix fixture unavailable'
    time.sleep(.02)
for root in ('/workspace', '/shared-state', '/isolated-home', '/worktree-parent'):
    for name in ('external.sock', 'alias.sock', 'hardlink.sock', 'seq.sock', 'dgram.sock', 'late.sock'):
        assert Path(root, name).exists(), (root, name)
        for kind in (socket.SOCK_STREAM, socket.SOCK_SEQPACKET, socket.SOCK_DGRAM):
            try:
                peer = socket.socket(socket.AF_UNIX, kind)
            except OSError as error:
                assert error.errno == errno.EPERM, error
            else:
                peer.close()
                raise AssertionError('external Unix socket creation escaped')

if config['provider']:
    raw = socket.create_connection(('127.0.0.1', 18080), 3)
    with raw:
        raw.sendall(b'CONNECT qualification-denied.invalid:443 HTTP/1.1\r\n\r\n')
        assert b'502' in raw.recv(1024)

if config['tls']:
    def tunnel():
        raw = socket.create_connection(('127.0.0.1', 18080), 3)
        raw.settimeout(4)
        raw.sendall(b'CONNECT qualification.invalid:8443 HTTP/1.1\r\n\r\n')
        response = b''
        while not response.endswith(b'\r\n\r\n'):
            part = raw.recv(1); assert part
            response += part
        assert b'200' in response
        return raw

    trust = ssl.create_default_context(cafile='/opt/sandbox-egress/qualification-cert.pem')
    with trust.wrap_socket(tunnel(), server_hostname='qualification.invalid') as secure:
        secure.sendall(b'GET / HTTP/1.1\r\nHost: qualification.invalid\r\nConnection: close\r\n\r\n')
        response = http.client.HTTPResponse(secure); response.begin()
        assert response.status == 200 and response.read() == b'qualification-tls-positive'
    outgoing = ssl.MemoryBIO()
    connection = trust.wrap_bio(ssl.MemoryBIO(), outgoing, server_side=False,
                               server_hostname='alternate.invalid')
    try:
        connection.do_handshake()
    except ssl.SSLWantReadError:
        pass
    with tunnel() as raw:
        raw.sendall(outgoing.read())
        try:
            assert raw.recv(1) == b''
        except ConnectionResetError:
            pass
    print('qualification-proxy-loss-ready', flush=True)
    assert sys.stdin.readline().strip() == 'proxy-removed'
    try:
        with socket.create_connection(('127.0.0.1', 18080), 3) as raw:
            raw.settimeout(3)
            raw.sendall(b'CONNECT qualification.invalid:8443 HTTP/1.1\r\n\r\n')
            response = raw.recv(1024)
            assert b'200' not in response
    except OSError as error:
        assert error.errno in (errno.ECONNREFUSED, errno.ECONNRESET, errno.EPIPE), error

Path('/workspace/qualification-owned').write_text('persistent')
assert Path('/workspace/qualification-owned').stat().st_uid == os.getuid()
print('qualification-probe-ok', flush=True)
