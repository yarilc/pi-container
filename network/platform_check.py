"""Protected restricted-platform eligibility; eligibility alone is not qualification."""
import argparse
import json
from pathlib import Path
import re
import sys
import http.client
import socket


class PlatformError(ValueError):
    pass


def validate_abi(value):
    if type(value) is not int or value < 3:
        raise PlatformError('usable Landlock ABI >= 3 is required')
    return value


def server_info(endpoint):
    if not endpoint.startswith('unix:///') or not endpoint[7:].strip('/'):
        raise PlatformError('absolute same-host Unix endpoint required')
    connection = http.client.HTTPConnection('localhost', timeout=5)
    try:
        connection.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.sock.settimeout(5)
        connection.sock.connect(endpoint[7:])
        connection.request('GET', '/v4.0.0/libpod/info')
        response = connection.getresponse()
        data = response.read(1048577)
        if response.status != 200 or len(data)>1048576:
            raise PlatformError('unverifiable raw server information')
        value = json.loads(data)
        host = value['host']; version = value['version']['Version']
        if not isinstance(host,dict) or not isinstance(version,str):
            raise PlatformError('invalid raw server information')
        return dict(host=host, server_version=version)
    finally:
        connection.close()


def server_version(value):
    # Stable numeric core, with optional package rebuild/vendor suffix. Never
    # interpret an rc/beta/dev build as the corresponding stable release.
    if not isinstance(value, str) or len(value)>128 or re.search(r'(?:alpha|beta|rc|dev|pre)', value, re.I):
        raise PlatformError('unverifiable Podman server version')
    match = re.fullmatch(r'(\d+)\.(\d+)(?:\.(\d+))?(?:-[0-9][A-Za-z0-9.+~_-]*|\+[A-Za-z0-9][A-Za-z0-9.+~_-]*)?', value)
    if not match:
        raise PlatformError('unverifiable Podman server version')
    version = tuple(int(part or 0) for part in match.groups())
    if version < (4, 9, 0):
        raise PlatformError('Podman server >= 4.9 is required')
    return version


def validate(host, version, backend, endpoint, engine):
    if engine != 'true linux true':
        raise PlatformError('verified Linux rootless same-host Unix service required')
    if not isinstance(endpoint, str) or not endpoint.startswith('unix:///') or not endpoint[7:].strip('/'):
        raise PlatformError('absolute same-host Unix endpoint required')
    if backend != 'netavark':
        raise PlatformError('rootless Netavark is required')
    server_version(version)
    if not isinstance(host, dict) or host.get('arch') not in ('amd64', 'x86_64'):
        raise PlatformError('Linux x86_64 is required')
    kernel = host.get('kernel')
    if not isinstance(kernel, str) or not kernel or len(kernel) > 256 or any(ord(c) < 32 or ord(c) == 127 for c in kernel):
        raise PlatformError('unverifiable host kernel')
    security = host.get('security')
    if not isinstance(security, dict) or security.get('seccompEnabled') is not True:
        raise PlatformError('standard OCI seccomp is required')
    if security.get('rootless', True) is not True:
        raise PlatformError('rootless engine required')
    if any(type(security.get(key)) is not bool for key in ('selinuxEnabled', 'apparmorEnabled')):
        raise PlatformError('unverifiable SELinux/AppArmor state')
    return dict(kernel=kernel, arch='x86_64', server=version, backend=backend,
                selinux=security['selinuxEnabled'], apparmor=security['apparmorEnabled'],
                seccomp=True)


def main():
    if len(sys.argv)==3 and sys.argv[1]=='--server-info':
        print(json.dumps(server_info(sys.argv[2]), sort_keys=True))
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server-version', required=True)
    parser.add_argument('--backend', required=True)
    parser.add_argument('--endpoint', required=True)
    parser.add_argument('--engine', required=True)
    args = parser.parse_args()
    data = sys.stdin.buffer.read(65537)
    if len(data) > 65536:
        raise PlatformError('oversized platform response')
    result = validate(json.loads(data), args.server_version, args.backend, args.endpoint, args.engine)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, TypeError, KeyError, OSError, http.client.HTTPException):
        prefix = 'sandbox-egress: '
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from agent_profile import message_prefix
            prefix = message_prefix(prefix)
        except ImportError:
            pass
        print(prefix + 'status=ineligible: ineligible restricted platform; require Linux x86_64, '
              'rootless same-host Unix Netavark/Podman >= 4.9 and standard OCI seccomp. '
              'Enabled SELinux/AppArmor is permitted but compatibility is not guaranteed. '
              'Usable Landlock ABI >= 3 and local enforcement qualification are additionally required.', file=sys.stderr)
        sys.exit(1)
