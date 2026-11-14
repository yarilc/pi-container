"""Strict protected qualification records and immutable enforcement identities."""
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import tempfile
from datetime import datetime, timezone

from policy import PolicyError, canonical, load, selected, trusted_path, unique_object
from proxy_hardening import MEMORY_LIMIT, PIDS_LIMIT
import agent_budgets
import agent_profile

REVISION = 'local-enforcement-v1'
CHECKS = ('ip4', 'ip6', 'dns-udp', 'unix-existing-late', 'pairs-files-descendants',
          'alternate-syscalls', 'both-state-modes', 'container-hardening')
PROVIDER_CHECKS = ('proxy-policy', 'proxy-budgets', 'tls-match', 'tls-mismatch-zero-bytes', 'proxy-loss')
GUARD = 'sandbox-egress-guard'
# Shared code plus the agent profile and provider policy. The wrapper name comes
# from the profile, so ``code_files`` binds the profile that selected it.
SHARED_CODE = ('network/control.py', 'network/platform_check.py', 'network/agent_profile.py', 'network/session.py',
               'network/policy.py', 'network/proxy_hardening.py', 'network/agent_budgets.py', 'network/qualify.py',
               'network/qualification_records.py', 'network/qualification_runtime.py',
               'network/qualification_probe.py', 'network/qualification_peer.py',
               'network/qualification_proxy.py', 'network/relay.py', 'network/mux.py',
               'network/resolv.conf', 'network/bin/' + GUARD, 'network/bin/' + GUARD + '.sha256',
               'setup/toolchains.py', agent_profile.PROFILE, agent_profile.POLICY)


def code_files(profile):
    return (profile.wrapper, *profile.install_files, *SHARED_CODE)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def decode(data):
    if len(data) > 65536:
        raise PolicyError('qualification record exceeds size limit')
    return json.loads(data, object_pairs_hook=unique_object)


STALE = ('missing or stale qualification for the current host, engine, code, policy '
         'or agent budgets/lifetime; rerun --container-qualify or --container-setup')


def expected_checks(provider):
    return list(CHECKS + (PROVIDER_CHECKS if provider else ()))


def ipv6_state(sysctl='/proc/sys/net/ipv6'):
    """Engine-host IPv6 state: present, or absent only when the kernel has no IPv6 stack."""
    # Runs inside the server-side identity probe container; keep it self-contained.
    import errno
    import os
    import socket
    present = os.path.isdir(sysctl)
    try:
        socket.socket(socket.AF_INET6, socket.SOCK_DGRAM).close()
    except OSError as error:
        if error.errno == errno.EAFNOSUPPORT and not present:
            return 'absent'
        raise RuntimeError('unverifiable IPv6 state') from None
    if not present:
        raise RuntimeError('unverifiable IPv6 state')
    return 'present'


def validate_security(security, ca_path):
    if (type(security) is not dict or set(security) != {'boot', 'seccomp', 'netavark', 'ca', 'ipv6'} or
            not isinstance(security['boot'], str) or not re.fullmatch(r'[a-f0-9-]{36}', security['boot']) or
            not all(isinstance(security[key], str) for key in ('seccomp', 'netavark', 'ca', 'ipv6')) or
            not re.fullmatch(r'[a-f0-9]{64}', security['seccomp']) or
            not re.fullmatch(r'[a-f0-9]{64}', security['netavark']) or
            (ca_path and not re.fullmatch(r'[a-f0-9]{64}', security['ca'])) or
            (not ca_path and security['ca'] != '') or
            security['ipv6'] not in ('present', 'absent')):
        raise PolicyError('unverifiable security identity')
    return security


def security_probe_args(profile, token, profile_path, ca_mount, candidate, runtime, script):
    """Engine arguments of the server-side security-identity probe container."""
    # An explicit /: the engine never creates or chowns an image WORKDIR missing
    # from the image layers (that chown fails for domain UIDs under keep-id).
    return ['podman', 'run', '--rm', '--pull=never', '--network=none', '--read-only', '--workdir', '/',
            '--label', profile.label('qualification') + '=' + token,
            '--cap-drop=all', '--security-opt=no-new-privileges', '--userns=keep-id', '--user', f'{os.getuid()}:{os.getgid()}',
            '--volume', profile_path + ':/qualification-seccomp:ro', *ca_mount,
            '--mount', 'type=bind,src=' + candidate + ',dst=/qualification-netavark,ro=true',
            '--entrypoint', 'python3', runtime, '-I', '-c', script]


def evidence_status(value, identity):
    if (type(value) is not dict or set(value) != {'schema', 'fingerprints'} or
            type(value['schema']) is not int or value['schema'] != 1 or
            not isinstance(value['fingerprints'], list) or len(value['fingerprints']) > 128 or
            any(not isinstance(item, str) or not re.fullmatch(r'[a-f0-9]{64}', item)
                for item in value['fingerprints'])):
        raise PolicyError('invalid protected release acceptance inventory')
    return 'release-measured' if digest(canonical(identity)) in value['fingerprints'] else 'locally-qualified'


def status(root, identity, writable):
    path = Path(root) / 'network/release_acceptance.json'
    if not path.exists() and not path.is_symlink():
        return 'locally-qualified'
    path = trusted_path(path, writable)
    with path.open('rb') as source:
        return evidence_status(decode(source.read(65537)), identity)


def fingerprint(root, env, run, platform, token):
    root = trusted_path(root, [], directory=True)
    profile = agent_profile.load(root / agent_profile.PROFILE, writable=[])
    host = decode(run(['podman', 'info', '--format', '{{json .Host}}']).encode())
    engine = run(['podman', 'info', '--format', '{{.Host.Security.Rootless}} {{.Host.OS}} {{.Host.ServiceIsRemote}}'])
    endpoint = env.get('CONTAINER_HOST', '')
    # Older clients discard newer server fields while formatting info. Query
    # the same verified Unix service directly; never assume its backend path.
    raw_server = decode(run(['python3','-I', str(root/'network/platform_check.py'),
                             '--server-info',endpoint], timeout=6).encode())
    authoritative_host = raw_server['host']
    if any(host.get(key)!=authoritative_host.get(key) for key in ('arch','kernel','networkBackend')):
        raise PolicyError('conflicting client/server platform evidence')
    host = authoritative_host
    server_version = run(['podman','version','--format','{{.Server.Version}}'])
    if raw_server['server_version'] != server_version:
        raise PolicyError('conflicting client/server version evidence')
    value = platform.validate(host, server_version,
                              run(['podman', 'info', '--format', '{{.Host.NetworkBackend}}']), endpoint, engine)
    engine_configuration = {name: host.get(name) for name in (
        'cgroupVersion', 'cgroupManager', 'cgroupControllers', 'ociRuntime')}
    if any(item is None for item in engine_configuration.values()):
        raise PolicyError('unverifiable engine/backend configuration')
    # Podman 5 reports the service socket as a unix:// URL; earlier releases report the bare path.
    socket = run(['podman', 'info', '--format', '{{.Host.RemoteSocket.Path}}']).removeprefix('unix://')
    if not socket.startswith('/') or '\n' in socket or '\r' in socket:
        raise PolicyError('unverifiable host socket identity')
    abi_output = run([str(root / 'network/bin' / GUARD), '--probe'])
    match = re.fullmatch(r'Landlock ABI (\d+); required >= 3; query-only, enforcement unverified', abi_output)
    if not match:
        raise PolicyError('unverifiable guard ABI probe')
    value['abi'] = platform.validate_abi(int(match[1]))
    runtime = run(['podman', 'image', 'inspect', '--format', '{{.Id}}',
                   env.get(profile.env('IMAGE')) or profile.image('agent', 'latest')])
    if not re.fullmatch(r'(?:sha256:)?[a-f0-9]{64}', runtime):
        raise PolicyError('unverifiable runtime image identity')
    selected_profile = env.get(profile.env('NETWORK_PROFILE'), '')
    mode = env.get(profile.env('NETWORK')) or 'offline'
    if mode not in ('offline', 'provider'):
        raise PolicyError('qualification requires offline or provider mode')
    policy_id, proxy = '', ''
    if mode == 'provider':
        policy = load(trusted_path(env.get(profile.env('NETWORK_POLICY'), ''), []), profile.policy_rules())
        selected(policy, selected_profile)
        policy_id = digest(canonical(policy))
        proxy = run(['podman', 'image', 'inspect', '--format', '{{.Id}}', env.get(profile.env('EGRESS_IMAGE'), '')])
        if not re.fullmatch(r'(?:sha256:)?[a-f0-9]{64}', proxy):
            raise PolicyError('unverifiable proxy image identity')
    # Read the server's profile at its real host path, including when the client
    # is itself in a container. Never hash a similarly named client-side file.
    profile_path = host['security'].get('seccompProfilePath')
    if not isinstance(profile_path, str) or not profile_path.startswith('/') or ':' in profile_path:
        raise PolicyError('unverifiable standard seccomp profile')
    ca_path = ''
    if env.get(profile.env('TRUST_HOST_CA'), '').lower() in ('1', 'true', 'yes'):
        ca_path = env.get(profile.env('CA_BUNDLE'), '')
        if not ca_path:
            ca_path = next((path for path in ('/etc/ssl/certs/ca-certificates.crt', '/etc/pki/tls/certs/ca-bundle.crt')
                            if Path(path).is_file()), '')
        if not Path(ca_path).is_file():
            raise PolicyError('unverifiable selected CA bundle')
        ca_path = str(Path(ca_path).resolve())
    security_probe = inspect.getsource(ipv6_state) + """
import hashlib,json
from pathlib import Path
print(json.dumps({'boot':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'ipv6':ipv6_state(),
'seccomp':hashlib.sha256(Path('/qualification-seccomp').read_bytes()).hexdigest(),
'netavark':hashlib.sha256(Path('/qualification-netavark').read_bytes()).hexdigest(),
'ca':hashlib.sha256(Path('/qualification-ca').read_bytes()).hexdigest() if Path('/qualification-ca').exists() else ''}))
"""
    ca_mount = ['--volume', ca_path + ':/qualification-ca:ro'] if ca_path else []
    backend_info = host.get('networkBackendInfo')
    if not isinstance(backend_info,dict) or backend_info.get('backend')!='netavark':
        raise PolicyError('unverifiable server Netavark identity')
    candidate = backend_info.get('path')
    if not isinstance(candidate,str) or not candidate.startswith('/') or any(c in candidate for c in ':,\n\r'):
        raise PolicyError('unverifiable server Netavark path')
    engine_configuration['networkBackendInfo'] = backend_info
    raw = run(security_probe_args(profile, token, profile_path, ca_mount, candidate, runtime, security_probe))
    # The IPv6 state is bound into the identity: a host that later boots with the
    # other state needs requalification.
    security = validate_security(decode(raw.encode()), ca_path)
    code = {name: digest(trusted_path(root / name, []).read_bytes()) for name in code_files(profile)}
    try:
        # Agent capability, budget and lifetime settings of the launch being qualified.
        # The enforced budgets follow the controllers the verified engine delegates.
        agent = agent_budgets.agent_hardening(env, profile, engine_configuration['cgroupControllers'])
        proxy_enforced = agent_budgets.enforced(engine_configuration['cgroupControllers'], 'proxy')
    except agent_budgets.ControllerError:
        raise PolicyError('unverifiable engine cgroup controllers') from None
    except agent_budgets.BudgetError as error:
        raise PolicyError('invalid ' + profile.env(str(error)) + ' agent budget or lifetime') from None
    identity = dict(revision=REVISION, platform=value, engine_configuration=engine_configuration,
                    endpoint=endpoint, host_socket=socket,
                    security=security, code=code, runtime=runtime, proxy=proxy,
                    mode=mode, profile=selected_profile if mode == 'provider' else '', policy=policy_id,
                    hardening=dict(capabilities=[], no_new_privs=True, pids=PIDS_LIMIT, memory=MEMORY_LIMIT,
                                   enforced=proxy_enforced, agent=agent))
    # Active LSM policy identity cannot generally be read by an unprivileged
    # operator. Rerun the gate each launch instead of caching unverifiable state.
    return identity, not (value['selinux'] or value['apparmor'])


def validate_report(value, identity):
    if (type(value) is not dict or set(value) != {'schema', 'identity', 'fingerprint', 'checks', 'reusable', 'measured_at'} or
            type(value['schema']) is not int or value['schema'] != 1 or
            canonical(value['identity']) != canonical(identity) or value['fingerprint'] != digest(canonical(identity)) or
            type(value['reusable']) is not bool or not isinstance(value['measured_at'], str) or
            not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00', value['measured_at']) or
            value['checks'] != {name: 'passed' for name in expected_checks(identity['mode'] == 'provider')}):
        raise PolicyError(STALE)
    try:
        datetime.fromisoformat(value['measured_at'])
    except ValueError:
        raise PolicyError('invalid qualification timestamp') from None
    return value


def report_path(root, identity, writable, missing=None):
    directory = Path(root) / 'qualification'
    if directory.is_symlink():
        raise PolicyError('qualification directory cannot be a symlink')
    directory = trusted_path(directory, writable, directory=True)
    path = directory / (digest(canonical(identity)) + '.json')
    if path.is_symlink():
        raise PolicyError('qualification report cannot be a symlink')
    if missing and not path.exists():
        raise PolicyError(missing)
    return trusted_path(path, writable)


def read(root, identity, writable):
    path = report_path(root, identity, writable, missing=STALE)
    if path.stat().st_mode & 0o077 or path.stat().st_uid != os.getuid():
        raise PolicyError('qualification report must be private and caller-owned')
    with path.open('rb') as source:
        return validate_report(decode(source.read(65537)), identity)


def publish(root, identity, reusable, writable):
    root = trusted_path(root, writable, directory=True)
    directory = Path(root) / 'qualification'
    if directory.is_symlink():
        raise PolicyError('qualification directory cannot be a symlink')
    if not directory.exists() and not directory.is_symlink():
        directory.mkdir(mode=0o700, exist_ok=True)
    trusted_path(directory, writable, directory=True)
    if directory.stat().st_mode & 0o077 or directory.stat().st_uid != os.getuid():
        raise PolicyError('qualification directory must be private and caller-owned')
    value = dict(schema=1, identity=identity, fingerprint=digest(canonical(identity)),
                 measured_at=datetime.now(timezone.utc).isoformat(timespec='seconds'),
                 checks={name: 'passed' for name in expected_checks(identity['mode'] == 'provider')}, reusable=reusable)
    validate_report(value, identity)
    destination = directory / (value['fingerprint'] + '.json')
    if destination.is_symlink():
        raise PolicyError('qualification report cannot be a symlink')
    if destination.exists():
        trusted_path(destination, writable)
        if destination.stat().st_mode & 0o077 or destination.stat().st_uid != os.getuid():
            raise PolicyError('unsafe existing qualification report; permissions are not repaired')
    descriptor, temporary = tempfile.mkstemp(prefix='.qualification-', dir=directory)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(canonical(value)); output.flush(); os.fsync(output.fileno())
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    read(root, identity, writable)
