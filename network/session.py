"""Shared restricted-session helper for every wrapper.

Wrappers call fixed operations as separate processes (see network/README.md):

  prepare     preflight, platform check, guard probe, fixed qualification input
  start       policy snapshot, proxy create/start, readiness, effective hardening
  agent-args  restricted container options and the guard/relay entrypoint
  stop        bounded, ownership-confirmed proxy removal and diagnostics

Agent-specific names come from the protected agent profile. The wrapper owns
the session directory, its shutdown budget and the agent container.
"""
import argparse
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

NETWORK = Path(__file__).resolve().parent
sys.path.insert(0, str(NETWORK))
from policy import PolicyError  # noqa: E402
import agent_profile  # noqa: E402
from revisions import TLS_ENFORCEMENT as TLS  # noqa: E402

GUARD = 'sandbox-egress-guard'
EGRESS = '/opt/sandbox-egress'
TRANSPORT = '/run/sandbox-egress'
RELAY = ['/usr/bin/python3', '-I', EGRESS + '/relay.py']
PROBE = ['/usr/bin/python3', '-I', EGRESS + '/qualification_probe.py', 'probe']
PROXY_URL = 'http://127.0.0.1:18080'
LOCAL = 'localhost,127.0.0.1,::1'
PROXY_VARIABLES = ('HTTP_PROXY', 'HTTPS_PROXY', 'NO_PROXY', 'ALL_PROXY',
                   'http_proxy', 'https_proxy', 'no_proxy', 'all_proxy')
READY_SECONDS = 10
CHECK_SECONDS = 5
QUALIFICATION_TARGETS = ('/workspace', '/shared-state', '/isolated-home', '/worktree-parent')
IDENTITY = re.compile(r'[a-f0-9]{64}')
PYTHON = sys.executable or 'python3'

try:
    PROFILE = agent_profile.load()
except PolicyError as error:
    print('sandbox-egress: ' + str(error), file=sys.stderr)
    sys.exit(1)
PREFIX = PROFILE.message_prefix


class Exit(Exception):
    """Stop with an exact status; the message, if any, is already actionable."""

    def __init__(self, status, message=''):
        super().__init__(message)
        self.status = status
        self.message = message


def die(message):
    raise Exit(1, message)


def note(message):
    print(PREFIX + message, file=sys.stderr, flush=True)


def run(command, **kwargs):
    """Run a fixed command; a failure stops with that command's status."""
    result = subprocess.run([str(part) for part in command], **kwargs)
    if result.returncode:
        raise Exit(result.returncode)
    return result


def bounded(command, seconds, output):
    """Like ``timeout --signal=TERM --kill-after=1s``; returns the exit status."""
    process = subprocess.Popen([str(part) for part in command], stdout=output)
    try:
        return process.wait(seconds)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        return 124


def read(path):
    """Shell ``$(<file)`` semantics: trailing newlines removed."""
    return Path(path).read_text().rstrip('\n')


def control_command(installation, operation, args, *extra):
    command = [PYTHON, '-I', Path(installation) / 'network/control.py', operation,
               '--installation', installation]
    for path in args.writable:
        command += ['--writable', path]
    for target in args.mount_target:
        command += ['--mount-target', target]
    if args.policy:
        command += ['--policy', args.policy, '--profile', args.profile,
                    '--proxy-image', args.proxy_image, '--runtime', args.runtime]
    return command + list(extra)


def guard_digest(installation):
    return read(Path(installation) / 'network/bin' / (GUARD + '.sha256')).split(' ', 1)[0]


def probe_guard(installation):
    """Query the guard ABI through pipes and relay the output to stderr.

    The guard exits 78 without writing when its stderr is not a terminal, file,
    pipe or null device (for example a journald socket), so never let it
    inherit the caller's descriptors.
    """
    result = subprocess.run([str(Path(installation) / 'network/bin' / GUARD), '--probe'],
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    sys.stderr.buffer.write(result.stdout + result.stderr)
    sys.stderr.flush()
    if result.returncode:
        raise Exit(result.returncode, f'sandbox egress guard probe failed (status {result.returncode}): '
                   'requires Landlock ABI >= 3 and ordinary standard I/O; '
                   'rerun from a terminal or see network/README.md')


def prepare(args):
    run(control_command(args.installation, 'preflight', args))
    platform = sys.stdin.buffer.read()
    run([PYTHON, '-I', Path(args.installation) / 'network/platform_check.py',
         '--server-version', args.server_version, '--backend', args.backend,
         '--endpoint', args.endpoint, '--engine', args.engine],
        input=platform, stdout=subprocess.DEVNULL)
    digest = guard_digest(args.installation)
    probe_guard(args.installation)
    record = [digest]
    if args.probe:
        output = run(control_command(args.installation, 'qualification-input', args,
                                     '--input', args.qualification_input or '',
                                     '--workspace', args.workspace, '--mode', args.mode),
                     stdout=subprocess.PIPE, text=True).stdout.rstrip('\n')
        fields = output.split(' ')
        if (len(fields) != 2 or not re.fullmatch(r'[a-f0-9]{32}', fields[0])
                or fields[1] not in ('0', '1')):
            die('invalid fixed qualification input')
        record += fields
    print(' '.join(record))


def start(args):
    # Own process group: the wrapper terminates this operation and every engine
    # client it started as one unit, then recovers ownership with ``stop``.
    os.setpgrp()
    session = Path(args.session)
    token = session.name
    policy_identity = run(control_command(args.installation, 'snapshot', args, '--session', session),
                          stdout=subprocess.PIPE, text=True).stdout.rstrip('\n')
    note(f'network profile={args.profile} policy={policy_identity}')
    note(f'egress session={token} diagnostics={session}/logs/denials.jsonl')
    fixture, command = [], []
    if args.probe:
        fixture += ['--label', PROFILE.label('qualification') + '=' + args.token]
        if args.tls:
            fixture += ['--entrypoint', 'python3',
                        '--volume', f'{Path(args.installation) / "network/qualification_proxy.py"}:/qualification-proxy.py:ro',
                        '--volume', f'{Path(args.qualification_input).parent}:/qualification:ro']
            command = ['-I', '/qualification-proxy.py']
    (session / 'proxy.pending').touch()
    with open(session / 'proxy.stdout', 'w') as output:
        run(['podman', 'create', '--name', PROFILE.state_name + '-' + token,
             '--cidfile', session / 'proxy.cid',
             '--label', PROFILE.label('egress') + '=' + token, '--read-only', '--read-only-tmpfs=false',
             '--userns=keep-id', '--user', f'{os.getuid()}:{os.getgid()}',
             '--cap-drop=all', '--security-opt=no-new-privileges',
             '--pids-limit=128', '--memory=256m',
             '--volume', f'{session}/config:/config:ro',
             '--volume', f'{session}/transport:/transport:rw',
             '--volume', f'{session}/logs:/logs:rw',
             '--env', 'EGRESS_PROFILE=' + args.profile, '--env', 'EGRESS_SESSION=' + token,
             *fixture, args.proxy_image, *command], stdout=output)
    proxy_id = read(session / 'proxy.stdout')
    if not IDENTITY.fullmatch(proxy_id):
        die('invalid egress proxy container ID')
    (session / 'proxy.id').write_text(proxy_id + '\n')
    (session / 'proxy.pending').unlink()
    with open(session / 'proxy.start', 'w') as output:
        run(['podman', 'start', proxy_id], stdout=output)
    deadline = time.monotonic() + READY_SECONDS
    while not (session / 'transport/ready').is_file() or not (session / 'transport/proxy.sock').is_socket():
        if time.monotonic() >= deadline:
            die('egress proxy unavailable: readiness deadline expired; check immutable image and policy')
        time.sleep(0.05)
    if read(session / 'transport/ready') != f'{policy_identity} guard={args.guard_digest} mux=1 tls={TLS}':
        die('egress proxy policy/bootstrap/protocol identity mismatch')
    # Bounded checks in the actual proxy cgroup; engine flags alone do not
    # prove that rootless controllers applied their limits.
    with open(session / 'proxy.config', 'w') as output:
        if bounded(['podman', 'inspect', '--type', 'container', '--format', '{{json .HostConfig}}', proxy_id],
                   CHECK_SECONDS, output):
            die('cannot inspect proxy resource budgets; agent not started')
    hardening = Path(args.installation) / 'network/proxy_hardening.py'
    with open(session / 'proxy.effective', 'w') as output:
        if bounded(['podman', 'exec', proxy_id, 'python3', '-I', '-c', hardening.read_text(), 'probe'],
                   CHECK_SECONDS, output):
            die('cannot verify effective proxy hardening; check rootless cgroup v2 memory/pids controllers '
                'and proxy image; agent not started')
    run([PYTHON, '-I', hardening, 'verify', session / 'proxy.config', session / 'proxy.effective'])
    print(policy_identity)


def agent_args(args):
    installation = Path(args.installation)
    options = []
    if args.probe:
        options += ['--label', PROFILE.label('qualification') + '=' + args.token,
                    '--volume', f'{args.qualification_input}:{EGRESS}/qualification.json:ro',
                    '--volume', f'{installation / "network/qualification_probe.py"}:{EGRESS}/qualification_probe.py:ro',
                    '--volume', f'{installation / "network/qualification_runtime.py"}:{EGRESS}/qualification_runtime.py:ro']
        for target in QUALIFICATION_TARGETS:
            options += ['--volume', f'{args.workspace}:{target}:rw']
        if args.tls:
            options += ['--volume', f'{Path(args.qualification_input).parent / "cert.pem"}:{EGRESS}/qualification-cert.pem:ro']
    options += ['--network=none', '--pid=private', '--ipc=private',
                '--cap-drop=all', '--security-opt=no-new-privileges',
                '--volume', f'{installation / "network/bin" / GUARD}:{EGRESS}/guard:ro',
                '--volume', f'{installation / "network/resolv.conf"}:/etc/resolv.conf:ro']
    for variable in PROXY_VARIABLES:
        options += ['--unsetenv', variable]
    application = PROBE if args.probe else args.command
    if not application:
        die('restricted sessions require an application command')
    if args.mode == 'provider':
        options += ['--volume', f'{args.session}/transport:{TRANSPORT}:ro',
                    '--volume', f'{installation / "network/relay.py"}:{EGRESS}/relay.py:ro',
                    '--volume', f'{installation / "network/mux.py"}:{EGRESS}/mux.py:ro']
        for variable in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
            options += ['--env', f'{variable}={PROXY_URL}']
        options += ['--env', 'NO_PROXY=' + LOCAL, '--env', 'no_proxy=' + LOCAL]
        command = ['--provider', '--', *RELAY, *application]
    else:
        command = ['--offline', '--', *application]
    options += ['--entrypoint', EGRESS + '/guard']
    note(f'guard={args.guard_digest} abi-min=3 filter=native-x86_64-v1 mux=1')
    records = [str(len(options)), *options, *command]
    if any('\0' in record for record in records):
        die('restricted arguments cannot contain NUL bytes')
    sys.stdout.write(''.join(record + '\0' for record in records))


def stop(args):
    session = Path(args.session)
    token = session.name
    deadline = time.monotonic() + max(0, args.deadline)
    state = {'proxy': ''}

    def warning(text):
        print(f'{PREFIX}cleanup {text} (container={args.container} proxy={state["proxy"] or "unknown"} '
              f'session={token}); inspect the Podman engine for remaining session containers', file=sys.stderr)

    def control(*command):
        # Same slicing as the wrapper's control(): reserve time for local clients.
        remaining = deadline - time.monotonic() - 2
        if remaining < 2:
            warning('deadline exhausted before ' + command[0])
            return None
        with open(os.devnull, 'w') as sink:
            capture = subprocess.PIPE if command[0] in ('ps', 'inspect') else sink
            process = subprocess.Popen(['podman', *command], stdout=capture, text=True)
            try:
                output, _ = process.communicate(timeout=min(2, remaining - 1))
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    output, _ = process.communicate(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    output, _ = process.communicate()
                warning(f'{command[0]} failed or timed out (status 124)')
                return None
        if process.returncode:
            warning(f'{command[0]} failed or timed out (status {process.returncode})')
            return None
        return (output or '').rstrip('\n')

    def recover():
        label = PROFILE.label('egress')
        candidate = ''
        for name in ('proxy.cid', 'proxy.stdout'):
            path = session / name
            if path.is_file() and path.stat().st_size:
                candidate = read(path)
                break
        if not IDENTITY.fullmatch(candidate):
            candidate = control('ps', '--all', '--no-trunc', '--filter', f'label={label}={token}',
                                '--format', '{{.ID}}')
            if candidate is None:
                return ''
        if not candidate:
            return ''
        if not IDENTITY.fullmatch(candidate):
            warning('invalid recovered proxy identity')
            return ''
        owner = control('inspect', '--type', 'container', '--format',
                        '{{index .Config.Labels "' + label + '"}}', candidate)
        if owner != token:
            warning('could not confirm recovered proxy ownership')
            return ''
        return candidate

    status = 0
    if (session / 'proxy.id').is_file():
        state['proxy'] = read(session / 'proxy.id')
    elif (session / 'proxy.pending').exists():
        state['proxy'] = recover()
    if state['proxy'] and control('rm', '--force', '--time', '0', '--ignore', state['proxy']) is None:
        status = 1
    denials = session / 'logs/denials.jsonl'
    if denials.is_file():
        print(PREFIX + 'recent protected egress diagnostics (sanitized)', file=sys.stderr)
        sys.stderr.write(''.join(denials.read_text(errors='replace').splitlines(keepends=True)[-20:]))
        sys.stderr.flush()
    if status:
        raise Exit(status)


def parser():
    root = argparse.ArgumentParser(prog='session.py', add_help=False)
    operations = root.add_subparsers(dest='operation', required=True)

    def network(command):
        command.add_argument('--installation', required=True)
        command.add_argument('--writable', action='append', default=[])
        command.add_argument('--mount-target', action='append', default=[])
        command.add_argument('--policy', default='')
        command.add_argument('--profile', default='')
        command.add_argument('--proxy-image', default='')
        command.add_argument('--runtime', default='')

    def probe(command):
        command.add_argument('--probe', action='store_true')
        command.add_argument('--qualification-input', default='')
        command.add_argument('--workspace', default='')
        command.add_argument('--token', default='')
        command.add_argument('--tls', action='store_true')

    command = operations.add_parser('prepare', add_help=False)
    network(command)
    probe(command)
    command.add_argument('--mode', required=True, choices=('offline', 'provider'))
    for name in ('--server-version', '--backend', '--endpoint', '--engine'):
        command.add_argument(name, required=True)

    command = operations.add_parser('start', add_help=False)
    network(command)
    probe(command)
    command.add_argument('--session', required=True)
    command.add_argument('--guard-digest', required=True)

    command = operations.add_parser('agent-args', add_help=False)
    probe(command)
    command.add_argument('--installation', required=True)
    command.add_argument('--mode', required=True, choices=('offline', 'provider'))
    command.add_argument('--session', required=True)
    command.add_argument('--guard-digest', required=True)

    command = operations.add_parser('stop', add_help=False)
    command.add_argument('--session', required=True)
    command.add_argument('--deadline', type=int, required=True)
    command.add_argument('--container', default='unknown')
    return root


def validate(args):
    if getattr(args, 'guard_digest', None) is not None and not IDENTITY.fullmatch(args.guard_digest):
        die('invalid guard identity')
    if args.operation in ('prepare', 'start') and (args.policy or args.operation == 'start'):
        if not all((args.policy, args.profile, args.proxy_image, args.runtime)):
            die('provider mode requires the policy, profile, proxy image and runtime directory')
    if getattr(args, 'probe', False) and args.operation != 'prepare' and not re.fullmatch(r'[a-f0-9]{32}', args.token):
        die('invalid fixed qualification input')
    if getattr(args, 'tls', False) and not args.probe:
        die('controlled TLS fixtures require the fixed qualification probe')


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    application = []
    if argv[:1] == ['agent-args']:
        # Everything after the first ``--`` is the application command, verbatim.
        if '--' not in argv:
            die('agent-args requires -- followed by the application command')
        split = argv.index('--')
        argv, application = argv[:split], argv[split + 1:]
    args = parser().parse_args(argv)
    if args.operation == 'agent-args':
        args.command = application
    validate(args)
    {'prepare': prepare, 'start': start, 'agent-args': agent_args, 'stop': stop}[args.operation](args)


if __name__ == '__main__':
    try:
        main()
    except Exit as error:
        if error.message:
            note(error.message)
        sys.exit(error.status)
    except (OSError, ValueError, KeyError) as error:
        note('restricted session operation failed: ' + type(error).__name__)
        sys.exit(1)
