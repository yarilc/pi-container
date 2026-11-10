"""Credential-free assertions executed behind the production native guard."""
import array
import ctypes
import errno
import json
import mmap
import os
from pathlib import Path
import socket
import subprocess
import sys

libc = ctypes.CDLL(None, use_errno=True)


def denied(call, expected=errno.EPERM):
    try:
        call()
    except OSError as error:
        assert error.errno in (expected if isinstance(expected, tuple) else (expected,)), error
    else:
        raise AssertionError('operation unexpectedly allowed')


def syscall_denied(number, *args):
    assert libc.syscall(number, *args) == -1 and ctypes.get_errno() == errno.EPERM, (number, ctypes.get_errno())


for family in (socket.AF_UNIX, socket.AF_NETLINK, 40, 17, 16, 0x100000001):
    syscall_denied(41, ctypes.c_ulonglong(family), socket.SOCK_STREAM, 0)
for number in (425, 426, 427, 438, 0x40000000 | 41):
    syscall_denied(number, -1, 0, 0, 0, 0, 0)
# i386 getpid through int 0x80 must be denied regardless of its valid arguments.
with mmap.mmap(-1, 4096, prot=mmap.PROT_READ | mmap.PROT_WRITE | mmap.PROT_EXEC) as code:
    code.write(bytes.fromhex('b814000000cd80c3'))
    fn = ctypes.CFUNCTYPE(ctypes.c_int)(ctypes.addressof(ctypes.c_char.from_buffer(code)))
    assert fn() == -errno.EPERM
    del fn
for typ in (socket.SOCK_DGRAM, socket.SOCK_RAW, socket.SOCK_STREAM | 0x100):
    denied(lambda: socket.socketpair(socket.AF_UNIX, typ))
for typ in (socket.SOCK_STREAM, socket.SOCK_SEQPACKET):
    for flags in (0, socket.SOCK_CLOEXEC, socket.SOCK_NONBLOCK, socket.SOCK_CLOEXEC | socket.SOCK_NONBLOCK):
        a, b = socket.socketpair(socket.AF_UNIX, typ | flags)
        a.setblocking(True)
        b.setblocking(True)
        for target in ('/workspace/external.sock', '/workspace/alias.sock', '\0external-guard-test'):
            try:
                a.connect(target)
            except OSError as error:
                assert error.errno in (errno.EISCONN, errno.ECONNREFUSED, errno.EPROTOTYPE), error
            else:
                raise AssertionError('pair retargeted')
            for send in (lambda: a.sendto(b'explicit', target),
                         lambda: a.sendmsg([b'explicit'], [], 0, target)):
                try:
                    send()
                except OSError as error:
                    assert error.errno == errno.EISCONN, error
                else:
                    assert typ == socket.SOCK_SEQPACKET
                    assert b.recv(32) == b'explicit'
        unspec = ctypes.c_ushort(socket.AF_UNSPEC)
        assert libc.connect(a.fileno(), ctypes.byref(unspec), 2) == -1
        assert ctypes.get_errno() == errno.EINVAL
        try:
            a.listen()
        except OSError as error:
            assert error.errno == errno.EINVAL
        else:
            raise AssertionError('pair became listener')
        # A shared path must not publish even an already connected pair.
        denied(lambda: a.bind('/workspace/published.sock'), errno.EACCES)
        # Explicit recipient data may not escape after bind/autobind either.
        # Existing pairs may have inert private names, per the approved contract.
        a.bind('')
        private_left, private_right = socket.socketpair(socket.AF_UNIX, typ)
        private_path = f'/tmp/fixed-pair-{typ}-{flags}'
        private_left.bind(private_path)
        try:
            private_left.listen()
        except OSError as error:
            assert error.errno == errno.EINVAL
        else:
            raise AssertionError('named pair became listener')
        private_left.send(b'private-name')
        assert private_right.recv(32) == b'private-name'
        for publish in (lambda: os.rename(private_path, '/workspace/moved.sock'),
                        lambda: os.link(private_path, '/workspace/linked.sock')):
            denied(publish, (errno.EACCES, errno.EXDEV))
        private_left.close(); private_right.close()
        a.send(b'fixed-peer')
        assert b.recv(32) == b'fixed-peer'
        a.sendmsg([b'fd'], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array('i', [b.fileno()]))])
        data, ancillary, _, _ = b.recvmsg(16, socket.CMSG_SPACE(4))
        assert data == b'fd'
        for level, kind, value in ancillary:
            assert level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS
            passed = array.array('i'); passed.frombytes(value)
            for fd in passed:
                os.close(fd)
        a.shutdown(socket.SHUT_WR)
        try:
            a.connect('/workspace/external.sock')
        except OSError:
            pass
        else:
            raise AssertionError('shutdown pair retargeted')
        a.close(); b.close()
denied(lambda: os.link('/workspace/external.sock', '/workspace/linked-host.sock'), errno.EACCES)
denied(lambda: os.rename('/workspace/external.sock', '/workspace/renamed-host.sock'), errno.EACCES)
# Kernel int truncation must not authorize AF_UNIX through high argument bits.
fd = libc.syscall(41, ctypes.c_ulonglong((1 << 32) | socket.AF_INET), socket.SOCK_STREAM, 0)
assert fd >= 0, ctypes.get_errno()
os.close(fd)
# Descendants and threads retain the filter and no_new_privs cannot be unset.
import threading
errors = []
def thread_check():
    try:
        denied(lambda: socket.socket(socket.AF_UNIX))
    except BaseException as error:
        errors.append(error)
thread = threading.Thread(target=thread_check); thread.start(); thread.join()
assert not errors, errors
child_script = "import socket,errno;\ntry: socket.socket(socket.AF_UNIX)\nexcept OSError as e: assert e.errno==errno.EPERM\nelse: raise AssertionError('descendant escaped')"
child = subprocess.run([sys.executable, '-I', '-c', child_script], capture_output=True, text=True)
assert child.returncode == 0, child.stderr
assert libc.prctl(38, 0, 0, 0, 0) == -1
# A later all-ALLOW filter cannot weaken the inherited deny filter.
class Filter(ctypes.Structure):
    _fields_ = [('code', ctypes.c_ushort), ('jt', ctypes.c_ubyte), ('jf', ctypes.c_ubyte), ('k', ctypes.c_uint)]
class Program(ctypes.Structure):
    _fields_ = [('length', ctypes.c_ushort), ('filter', ctypes.POINTER(Filter))]
allow = (Filter * 1)(Filter(6, 0, 0, 0x7fff0000))
program = Program(1, allow)
assert libc.prctl(22, 2, ctypes.byref(program), 0, 0) == 0
syscall_denied(41, socket.AF_UNIX, socket.SOCK_STREAM, 0)
# Neither user/network namespaces nor a mount operation may remove the boundary.
namespace = subprocess.run(['unshare', '--user', '--map-root-user', '--net',
                            sys.executable, '-I', '-c', child_script], capture_output=True, text=True)
if namespace.returncode:
    assert 'unshare:' in namespace.stderr and 'Operation not permitted' in namespace.stderr, namespace.stderr
Path('/tmp/mount-target').mkdir()
assert libc.mount(b'/workspace', b'/tmp/mount-target', None, 4096, None) == -1
assert ctypes.get_errno() in (errno.EPERM, errno.EACCES)
# Own loopback remains functional with no external attachment.
with socket.socket() as server:
    server.bind(('127.0.0.1', 0)); server.listen()
    with socket.create_connection(server.getsockname()) as client:
        peer, _ = server.accept()
        with peer:
            client.sendall(b'loopback'); assert peer.recv(16) == b'loopback'
for family, target in ((socket.AF_INET, ('192.0.2.1', 443)),
                       (socket.AF_INET6, ('2001:db8::1', 443))):
    with socket.socket(family) as client:
        client.settimeout(1)
        try:
            client.connect(target)
        except OSError:
            pass
        else:
            raise AssertionError('direct route exists')
for target in ('1.1.1.1', '192.168.1.1', '169.254.169.254',
               'host.containers.internal', 'host.docker.internal'):
    try:
        socket.create_connection((target, 443), 1)
    except OSError:
        pass
    else:
        raise AssertionError('external/host route exists: ' + target)
for port in (53, 443):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        try:
            client.sendto(b'synthetic-datagram', ('192.0.2.1', port))
        except OSError as error:
            assert error.errno in (errno.ENETUNREACH, errno.EHOSTUNREACH), error
        else:
            raise AssertionError('external DNS/QUIC route exists')
with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as listener:
    listener.bind(('127.0.0.1', 0))
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        client.sendto(b'local-control', listener.getsockname())
        assert listener.recv(32) == b'local-control'
try:
    socket.getaddrinfo('unapproved.test', 443)
except socket.gaierror:
    pass
else:
    raise AssertionError('external DNS resolved an unapproved name')
# Ordinary cross-directory persistence must survive the REFER layer.
for folder in ('a', 'b'):
    Path('/workspace', folder).mkdir(exist_ok=True)
Path('/workspace/a/file').write_text('persistent')
os.rename('/workspace/a/file', '/workspace/b/file')
os.link('/workspace/b/file', '/workspace/a/link')
assert Path('/workspace/a/link').read_text() == 'persistent'
for command in (['node', '-e', "const r=require('child_process').spawnSync('/bin/sh',['-c','printf child-ok']);process.stdout.write(r.stdout);process.exit(r.status??1)"],
                ['python3', '-c', "import subprocess; print(subprocess.check_output(['/bin/sh','-c','printf child-ok']).decode())"],
                [AGENT, '--version']):  # AGENT is prepended by the test from the profile
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, (command[0], result.stderr)
git_root = '/workspace/git-project'
subprocess.run(['git', 'init', '-q', git_root], check=True)
Path(git_root, 'file').write_text('synthetic git state')
for args in (['add', 'file'], ['-c', 'user.name=Synthetic', '-c', 'user.email=synthetic@example.invalid', 'commit', '-qm', 'fixture'],
             ['worktree', 'add', '-qb', 'fixture-branch', '/workspace/linked-worktree']):
    subprocess.run(['git', '-C', git_root, *args], check=True, capture_output=True)
assert Path('/workspace/linked-worktree/file').read_text() == 'synthetic git state'
assert os.environ['XDG_RUNTIME_DIR'] == '/tmp/sandbox-runtime'
assert libc.prctl(39, 0, 0, 0, 0) == 1
print(json.dumps({'native_guard': 'passed', 'kernel': os.uname().release,
                  'pairs': ['stream', 'seqpacket'], 'new_unix_sockets': 'denied', 'connected_pair_autobind': 'allowed'}))
