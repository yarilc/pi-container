"""Guarded half of the existing/late Unix-socket bind acceptance control."""
import errno
import pathlib
import socket
import time
pathlib.Path('/workspace/guard-ready').touch()
deadline = time.monotonic() + 10
while not pathlib.Path('/workspace/late.sock').exists():
    assert time.monotonic() < deadline
    time.sleep(.02)
for root in ('/workspace', '/worktree-parent', '/shared-state', '/isolated-home'):
    for name in ('stream.sock', 'seq.sock', 'dgram.sock', 'alias.sock', 'hardlink.sock', 'late.sock'):
        assert pathlib.Path(root, name).exists()
        for kind in (socket.SOCK_STREAM, socket.SOCK_DGRAM, socket.SOCK_SEQPACKET):
            try:
                channel = socket.socket(socket.AF_UNIX, kind)
                channel.connect(root + '/' + name)
            except OSError as error:
                assert error.errno == errno.EPERM, error
            else:
                raise AssertionError('external Unix service reached')
print('all-bind-roots-denied')
