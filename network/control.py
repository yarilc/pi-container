"""Host-side restricted-network preflight and immutable snapshot creation."""
import argparse
import hashlib
import stat
import json
import os
from pathlib import Path
import re
import sys
import ipaddress

# Isolated Python ignores PYTHONPATH and the script directory. Only import
# helpers from the installation selected by this script's physical location.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from policy import PolicyError, canonical, load, overlaps, revision, selected, trusted_path
import agent_profile
from revisions import GUARD_REQUIRED_ABI, GUARD_REVISION, TLS_ENFORCEMENT

GUARD = 'sandbox-egress-guard'


def fixed_qualification_input(value, command, mode, workspace):
    """Exact fixed gate input: one IPv4 fixture address, plus one IPv6 address only with host IPv6."""
    try:
        budgets = value.get('budgets') if isinstance(value, dict) else None
        return not (not isinstance(value, dict) or
                set(value) != {'schema', 'token', 'addresses', 'ipv6', 'workspace', 'provider', 'tls', 'agent', 'budgets'} or
                value['agent'] != command or not isinstance(budgets, dict) or
                set(budgets) != {'capabilities', 'no_new_privs', 'enforced', 'memory', 'nano_cpus', 'pids', 'timeout'} or
                # Enforced budgets: a sorted, duplicate-free subset of the agent controllers.
                not isinstance(budgets['enforced'], list) or
                budgets['enforced'] != sorted(set(budgets['enforced'])) or
                not set(budgets['enforced']) <= {'cpu', 'memory', 'pids'} or
                any(type(budgets[key]) is not int for key in ('memory', 'nano_cpus', 'pids', 'timeout')) or
                budgets['capabilities'] != [] or budgets['no_new_privs'] is not True or
                type(value['schema']) is not int or value['schema'] != 1 or
                not isinstance(value['token'], str) or not re.fullmatch(r'[a-f0-9]{32}', value['token']) or
                type(value['provider']) is not bool or type(value['tls']) is not bool or type(value['ipv6']) is not bool or
                value['provider'] != (mode == 'provider') or (value['tls'] and not value['provider']) or
                value['workspace'] != workspace or not Path(workspace).is_absolute() or
                # One IPv4 fixture address, plus one IPv6 address only when the host has IPv6.
                not isinstance(value['addresses'], list) or len(value['addresses']) != (2 if value['ipv6'] else 1) or
                not all(isinstance(address, str) for address in value['addresses']) or
                [ipaddress.ip_address(address).version for address in value['addresses']] != ([4, 6] if value['ipv6'] else [4]))
    except (KeyError, TypeError, ValueError):
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=('preflight', 'snapshot', 'qualification-input'))
    parser.add_argument('--installation', required=True)
    parser.add_argument('--writable', action='append', default=[])
    parser.add_argument('--mount-target', action='append', default=[])
    parser.add_argument('--policy')
    parser.add_argument('--profile')
    parser.add_argument('--proxy-image')
    parser.add_argument('--runtime')
    parser.add_argument('--session')
    parser.add_argument('--input')
    parser.add_argument('--workspace')
    parser.add_argument('--mode')
    args = parser.parse_args()
    for writable in args.writable:
        resolved = Path(writable).resolve()
        if any(resolved == Path(root) or Path(root) in resolved.parents for root in ('/proc', '/sys', '/dev')):
            raise PolicyError('host process, namespace and device trees cannot be restricted workspace/state binds')
    installation = trusted_path(args.installation, args.writable, directory=True)
    profile = agent_profile.load(installation / agent_profile.PROFILE, writable=args.writable)
    for name in (profile.wrapper, 'network/control.py', 'network/policy.py', 'network/agent_profile.py', 'network/session.py',
                 'network/revisions.py', 'network/relay.py', 'network/mux.py', 'network/resolv.conf', agent_profile.POLICY):
        trusted_path(installation / name, args.writable)
    for optional in ('setup/diagnostics.py', 'setup/toolchains.py'):
        if (installation / optional).exists() or (installation / optional).is_symlink():
            trusted_path(installation / optional, args.writable)
    for target in args.mount_target:
        target = Path(target)
        if not target.is_absolute() or '..' in target.parts:
            raise PolicyError('invalid effective mount target')
        if any(overlaps(target, Path(root)) for root in ('/tmp', '/run', '/var/tmp')):
            raise PolicyError('host bind overlaps a reserved private IPC hierarchy')
    guard = trusted_path(installation / 'network/bin' / GUARD, args.writable)
    manifest = trusted_path(installation / 'network/bin' / (GUARD + '.sha256'), args.writable)
    identity = hashlib.sha256(guard.read_bytes()).hexdigest()
    if manifest.read_text() != identity + '  ' + GUARD + '\n':
        raise PolicyError('native bootstrap digest mismatch')
    if not guard.stat().st_mode & stat.S_IXUSR or guard.read_bytes()[:6] != b'\x7fELF\x02\x01':
        raise PolicyError('native bootstrap must be an executable static x86_64 ELF')
    # ELF64 little-endian native x86_64, no interpreter or dynamic segment.
    import struct
    data = guard.read_bytes()
    if len(data) < 64 or struct.unpack_from('<H', data, 18)[0] != 62:
        raise PolicyError('native bootstrap architecture mismatch')
    offset = struct.unpack_from('<Q', data, 32)[0]
    size, count = struct.unpack_from('<HH', data, 54)
    if size != 56 or offset + size * count > len(data):
        raise PolicyError('native bootstrap ELF layout invalid')
    if any(struct.unpack_from('<I', data, offset + i * size)[0] in (2, 3) for i in range(count)):
        raise PolicyError('native bootstrap must not have dynamic loading or an interpreter')
    guard_identity = {'sha256': identity, 'revision': GUARD_REVISION,
                      'required_abi': GUARD_REQUIRED_ABI, 'filter': 'native-x86_64-v1', 'protocol': 1,
                      'tls_enforcement': TLS_ENFORCEMENT}
    for name in ('platform_check.py', 'qualify.py', 'qualification_records.py', 'qualification_probe.py',
                 'qualification_runtime.py', 'qualification_peer.py', 'qualification_proxy.py'):
        trusted_path(installation / 'network' / name, args.writable)
    if args.operation == 'qualification-input':
        from policy import unique_object
        input_path = trusted_path(args.input or '', args.writable)
        data = input_path.read_bytes()
        if len(data) > 65536:
            raise PolicyError('oversized qualification input')
        value = json.loads(data, object_pairs_hook=unique_object)
        if not fixed_qualification_input(value, profile.command, args.mode, args.workspace):
            raise PolicyError('invalid fixed qualification input')
        if value['tls']:
            trusted_path(input_path.parent / 'cert.pem', args.writable)
            trusted_path(input_path.parent / 'key.pem', args.writable)
        print(value['token'], int(value['tls']))
        return
    if not args.policy:
        return
    trusted_path(installation / 'network/proxy_hardening.py', args.writable)
    policy_path = trusted_path(args.policy, args.writable)
    value = load(policy_path, profile.policy_rules())
    selected(value, args.profile)
    if not re.fullmatch(r'(?:(?:sha256:)?[a-f0-9]{64}|[A-Za-z0-9./:_-]+@sha256:[a-f0-9]{64})', args.proxy_image or ''):
        raise PolicyError(profile.env('EGRESS_IMAGE') + ' must be an immutable image ID or digest')
    runtime = trusted_path(args.runtime or '', args.writable, directory=True)
    info = runtime.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise PolicyError('network runtime directory must be caller owned and mode 0700')
    if args.operation == 'snapshot':
        session = Path(args.session).resolve(strict=True)
        if session.parent != runtime or session.stat().st_uid != os.getuid() or session.stat().st_mode & 0o077:
            raise PolicyError('invalid private network session directory')
        for name in ('config', 'transport', 'logs'):
            (session / name).mkdir(mode=0o700)
        with (session / 'config/policy.json').open('xb') as output:
            output.write(canonical(value))
        (session / 'config/policy.json').chmod(0o400)
        (session / 'config/manifest.json').write_text(json.dumps(guard_identity | {
            'policy': revision(value), 'profile': args.profile, 'session': session.name}, sort_keys=True) + '\n')
        (session / 'config/manifest.json').chmod(0o400)
        print(revision(value))


if __name__ == '__main__':
    try:
        main()
    except (PolicyError, OSError, ValueError) as error:
        # Paths can be operator supplied; never echo policy/request contents.
        print(agent_profile.message_prefix() + 'network policy preflight failed: ' +
              (str(error) if isinstance(error, PolicyError) else 'input inaccessible or invalid'), file=sys.stderr)
        sys.exit(1)
