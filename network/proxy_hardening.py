"""Fixed proxy cgroup probe and host-side verification; no application inputs."""
import json
from pathlib import Path
import sys


PIDS_LIMIT = 128
MEMORY_LIMIT = 256 * 1024 * 1024
PROCESS = ('cgroup', 'rlimit', 'none')


def process_rlimit(text):
    # Soft and hard 'Max processes' of a /proc/<pid>/limits table; None is unlimited.
    for line in text.splitlines():
        if line.startswith('Max processes '):
            return [None if value == 'unlimited' else int(value) for value in line.split()[2:4]]
    raise ValueError('missing process rlimit')


def probe():
    # Rootless Podman uses a private cgroup namespace on the supported v2 target.
    # Refuse unknown layouts instead of treating an ancestor's budget as ours.
    if Path('/proc/self/cgroup').read_text() != '0::/\n':
        raise ValueError('unsupported cgroup namespace')
    mounts = Path('/proc/self/mountinfo').read_text().splitlines()
    if not any(line.split()[4] == '/sys/fs/cgroup' and ' - cgroup2 ' in line for line in mounts):
        raise ValueError('missing cgroup v2 mount')
    root = Path('/sys/fs/cgroup')
    status = dict(line.split(':', 1) for line in Path('/proc/1/status').read_text().splitlines())

    def limit(name):
        # A missing interface (controller not delegated) or 'max' means no limit.
        path = root / name
        if not path.exists():
            return None
        value = path.read_text().strip()
        return None if value == 'max' else int(value)
    return {
        'pids': limit('pids.max'),
        'memory': limit('memory.max'),
        'capabilities': [int(status[key], 16) for key in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb')],
        'no_new_privs': int(status['NoNewPrivs']),
        'seccomp': int(status['Seccomp']),
        'nproc': process_rlimit(Path('/proc/1/limits').read_text()),
    }


def verify(config, effective, enforced=('memory', 'pids'), process=None):
    """Exact enforced budgets; budgets whose controller is not delegated must be absent.

    The process budget uses the pids cgroup, the process rlimit fallback (exactly
    one RLIMIT_NPROC entry at the budget, measured in the proxy) or nothing; an
    engine default process rlimit is not a budget and is otherwise accepted.
    """
    if process is None:
        process = 'cgroup' if 'pids' in enforced else 'none'
    if type(config) is not dict or type(effective) is not dict or not set(enforced) <= {'memory', 'pids'} or \
            process not in PROCESS or (process == 'cgroup') != ('pids' in enforced):
        raise ValueError('invalid hardening records')
    pids, memory = config.get('PidsLimit', 0), config.get('Memory', 0)
    if type(pids) is not int or type(memory) is not int:
        raise ValueError('proxy configured budgets differ')
    if (pids != PIDS_LIMIT if 'pids' in enforced else pids > 0) or \
            (memory != MEMORY_LIMIT if 'memory' in enforced else memory != 0):
        raise ValueError('proxy configured budgets differ')
    rlimits = config.get('Ulimits')
    rlimits = [] if rlimits is None else rlimits
    if type(rlimits) is not list or any(type(entry) is not dict for entry in rlimits):
        raise ValueError('proxy configured budgets differ')
    nproc = [entry for entry in rlimits if entry.get('Name') == 'RLIMIT_NPROC']
    if process == 'rlimit' and (len(nproc) != 1 or any(
            type(nproc[0].get(key)) is not int or nproc[0][key] != PIDS_LIMIT for key in ('Soft', 'Hard'))):
        raise ValueError('proxy configured budgets differ')
    measured = effective.get('nproc')
    if type(measured) is not list or len(measured) != 2 or \
            any(value is not None and type(value) is not int for value in measured) or \
            (process == 'rlimit' and measured != [PIDS_LIMIT, PIDS_LIMIT]):
        raise ValueError('proxy effective hardening differs')
    expected = dict(pids=PIDS_LIMIT if 'pids' in enforced else None,
                    memory=MEMORY_LIMIT if 'memory' in enforced else None,
                    capabilities=[0] * 5, no_new_privs=1, seccomp=2, nproc=measured)
    if effective != expected or any(type(effective.get(key)) is not int
                                    for key in ('no_new_privs', 'seccomp')):
        raise ValueError('proxy effective hardening differs')
    for key in ('pids', 'memory'):
        if expected[key] is not None and type(effective[key]) is not int:
            raise ValueError('proxy effective hardening differs')
    if any(type(value) is not int for value in effective['capabilities']):
        raise ValueError('invalid capabilities')


def read_record(path):
    data = Path(path).read_bytes()
    if len(data) > 65536:
        raise ValueError('oversized hardening response')
    return json.loads(data)


if __name__ == '__main__':
    try:
        if sys.argv[1:] == ['probe']:
            print(json.dumps(probe(), sort_keys=True))
        elif len(sys.argv) == 6 and sys.argv[1] == 'verify':
            enforced = tuple(name for name in sys.argv[4].split(',') if name)
            verify(read_record(sys.argv[2]), read_record(sys.argv[3]), enforced, sys.argv[5])
        else:
            raise ValueError('invalid operation')
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        prefix = 'sandbox-egress: '
        if '__file__' in globals():
            # Host-side verification names the wrapper; the in-proxy probe has no profile.
            try:
                sys.path.insert(0, str(Path(__file__).resolve().parent))
                from agent_profile import message_prefix
                prefix = message_prefix(prefix)
            except ImportError:
                pass
        print(prefix + 'proxy hardening unavailable or invalid; require effective '
              'cgroup v2 pids=128/memory=256MiB where delegated, or a process rlimit of 128 under the '
              'process rlimit fallback, zero capabilities, no-new-privileges and standard seccomp; '
              'inspect rootless controller delegation and the proxy image', file=sys.stderr)
        sys.exit(1)
