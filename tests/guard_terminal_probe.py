"""Whether a terminal can attach to a --read-only container through the runner's Podman client.

The guarded terminal tests start a --read-only container with a terminal, as an
interactive session does. The runtime image's Podman 4.3.1 client gets a
read-only /dev for such a container from Podman 4.9 and 5 servers. crun 1.14
attaches the terminal there, but crun 1.27 (with Podman 5.8) replaces
/dev/console to attach it, and the container fails before the test checks
anything. The managed launcher runs with the host's own client and is not
affected.

The probe measures the failure itself, once per image: it starts a --read-only
container with a terminal. The terminal tests skip only when that container
fails, the same container starts without a terminal, and its /dev is read-only.
The skip reason carries the engine's error. Any other outcome of a failed
terminal start raises: a broken probe never turns into a skip.
"""
import functools
import os
import pty
import subprocess


def _run(image, *options, entrypoint='true', arguments=(), terminal=False):
    command = ['podman', 'run', '--rm', '--network=none', '--read-only', *options, '--entrypoint', entrypoint,
               image, *arguments]
    if not terminal:
        return subprocess.run(command, capture_output=True, text=True, timeout=120)
    # The client runs on a pseudo-terminal, as the terminal tests run it.
    master, slave = pty.openpty()
    try:
        return subprocess.run(command, stdin=slave, stdout=slave, stderr=subprocess.PIPE, text=True, timeout=120)
    finally:
        os.close(slave)
        os.close(master)


def _read_only_dev(image):
    result = _run(image, entrypoint='cat', arguments=('/proc/mounts',))
    if result.returncode:
        raise RuntimeError('terminal probe: the container does not start without a terminal either: '
                           + result.stdout + result.stderr)
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) >= 4 and fields[1] == '/dev':
            return 'ro' in fields[3].split(',')
    raise RuntimeError('terminal probe found no /dev mount:\n' + result.stdout)


@functools.lru_cache(maxsize=None)
def terminal_skip_reason(image):
    """None when a terminal attaches to a --read-only container of image; otherwise the reason to skip."""
    result = _run(image, '--tty', terminal=True)
    if not result.returncode:
        return None
    error = ' '.join(result.stderr.split())[-300:] or 'exit status ' + str(result.returncode)
    if not _read_only_dev(image):
        raise RuntimeError('terminal probe: a terminal does not attach although /dev is writable: ' + error)
    return ("a terminal does not attach to a --read-only container through the runner's Podman client, which "
            'gets a read-only /dev from this engine (' + error + '); check terminal attach with an interactive '
            'session instead (AGENTS.md, Testing Guidelines)')
