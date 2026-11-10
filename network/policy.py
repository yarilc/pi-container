"""Strict operator policy validation shared by launcher and trusted proxy."""
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import stat

# IANA special-purpose inventories reviewed 2026-11-06. Deny special-use
# ranges even where a Python release labels a globally routed exception public.
SPECIAL_NETWORKS = tuple(ipaddress.ip_network(value) for value in (
    '0.0.0.0/8', '10.0.0.0/8', '100.64.0.0/10', '127.0.0.0/8',
    '169.254.0.0/16', '172.16.0.0/12', '192.0.0.0/24', '192.0.2.0/24',
    '192.31.196.0/24', '192.52.193.0/24', '192.88.99.0/24', '192.168.0.0/16',
    '192.175.48.0/24', '198.18.0.0/15', '198.51.100.0/24', '203.0.113.0/24',
    '224.0.0.0/4', '240.0.0.0/4', '::/96', '::ffff:0:0/96',
    '64:ff9b::/96', '64:ff9b:1::/48', '100::/64', '100:0:0:1::/64',
    '2001::/23', '2001:db8::/32', '2002::/16', '2620:4f:8000::/48',
    '3fff::/20', '5f00::/16', 'fc00::/7', 'fe80::/10', 'ff00::/8',
))

class PolicyError(ValueError):
    pass


def fail(message):
    raise PolicyError(message)


def fields(value, required, optional=()):
    if not isinstance(value, dict) or set(value) - set(required) - set(optional) or set(required) - set(value):
        fail('invalid policy fields')


def hostname(value):
    if not isinstance(value, str) or not value.isascii():
        fail('hostname must be ASCII')
    value = value.lower()
    if value.endswith('.'):
        value = value[:-1]
    if len(value) > 253 or '.' not in value:
        fail('invalid hostname')
    if not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', p) for p in value.split('.')):
        fail('invalid hostname')
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return value
    fail('IP literals require an explicit local exception')


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            fail('duplicate JSON key')
        result[key] = value
    return result


def load(path, rules=None):
    data = Path(path).read_bytes()
    if len(data) > 65536:
        fail('policy exceeds 64 KiB')
    try:
        value = json.loads(data, object_pairs_hook=unique_object)
    except (ValueError, UnicodeError):
        fail('invalid policy JSON')
    validate(value, rules)
    return value


def validate(value, rules=None):
    """Validate policy structure; ``rules`` adds the agent profile's host requirements.

    Trusted host-side code always passes the rules derived from the protected
    agent profile before creating a session snapshot. The proxy image has no
    profile and revalidates the snapshot's structure only.
    """
    fields(value, ('schema_version', 'revision', 'source_date', 'sources', 'tested', 'profiles'))
    if type(value['schema_version']) is not int or value['schema_version'] != 1:
        fail('unsupported policy schema')
    if not isinstance(value['revision'], str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', value['revision']):
        fail('invalid policy revision')
    if not isinstance(value['source_date'], str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value['source_date']):
        fail('invalid source date')
    if not isinstance(value['sources'], list) or not value['sources'] or any(
            not isinstance(s, str) or not s.startswith('https://') or len(s) > 500 for s in value['sources']):
        fail('invalid policy sources')
    fields(value['tested'], ('cli', 'node', 'authentication'))
    if any(not isinstance(s, str) or len(s) > 120 for s in value['tested'].values()):
        fail('invalid tested-version metadata')
    if not isinstance(value['profiles'], dict) or not value['profiles'] or len(value['profiles']) > 32:
        fail('invalid profiles')
    for name, profile in value['profiles'].items():
        if not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', name):
            fail('invalid profile name')
        fields(profile, ('authentication', 'destinations', 'disable_optional_traffic'))
        methods = rules['methods'] if rules is not None else None
        if not isinstance(profile['authentication'], str) or (
                profile['authentication'] != 'custom' and
                (profile['authentication'] not in methods if methods is not None else
                 not re.fullmatch(r'[a-z][a-z0-9]*(?:-[a-z0-9]+)*', profile['authentication']))):
            fail('invalid authentication method')
        if profile['disable_optional_traffic'] is not True:
            fail('optional traffic must be disabled')
        entries = profile['destinations']
        if not isinstance(entries, list) or not entries or len(entries) > 128:
            fail('invalid destinations')
        seen = set()
        for entry in entries:
            fields(entry, ('host', 'port'), ('addresses',))
            host = hostname(entry['host'])
            if type(entry['port']) is not int or not 1 <= entry['port'] <= 65535:
                fail('invalid destination port')
            # Non-443 ports require an explicit exact-address local exception.
            if entry['port'] != 443 and 'addresses' not in entry:
                fail('non-HTTPS port requires a local exception')
            key = (host, entry['port'])
            if key in seen:
                fail('duplicate normalized destination')
            seen.add(key)
            entry['host'] = host
            if 'addresses' in entry:
                addresses = entry['addresses']
                if not isinstance(addresses, list) or not addresses or len(addresses) > 8:
                    fail('invalid local exception addresses')
                try:
                    parsed = [ipaddress.ip_address(s) for s in addresses if isinstance(s, str)]
                except ValueError:
                    fail('invalid local exception address')
                if len(parsed) != len(addresses) or len(set(parsed)) != len(parsed):
                    fail('invalid local exception addresses')
                if any(p.is_multicast or p.is_unspecified or
                       (isinstance(p, ipaddress.IPv6Address) and p.ipv4_mapped) for p in parsed):
                    fail('unsafe local exception address')
                entry['addresses'] = [str(p) for p in parsed]
        if rules is None:
            continue
        https = {h for h, port in seen if port == 443}
        if profile['authentication'] != 'custom' and not methods[profile['authentication']] <= https:
            fail('profile lacks required authentication hosts')
        if name in rules['base_profiles']:
            method, hosts = rules['base_profiles'][name]
            if profile['authentication'] != method or seen != {(h, 443) for h in hosts}:
                fail(name + ' is an exact base profile; use a new profile for extensions')
            if any('addresses' in d for d in entries):
                fail('base profiles cannot add local address exceptions')


def selected(value, name):
    if name not in value['profiles']:
        fail('unknown selected network profile')
    return value['profiles'][name]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode() + b'\n'


def revision(value):
    return value['revision'] + ' ' + hashlib.sha256(canonical(value)).hexdigest()


def overlaps(left, right):
    return left == right or left in right.parents or right in left.parents


def trusted_path(path, writable=(), directory=False):
    path = Path(path)
    if not path.is_absolute():
        fail('trusted path must be absolute')
    resolved = path.resolve(strict=True)
    if directory != resolved.is_dir() or (not directory and not resolved.is_file()):
        fail('invalid trusted path type')
    # Check lexical ancestors as well as resolved ones, to reject writable aliases.
    for item in set((path, *path.parents, resolved, *resolved.parents)):
        info = item.stat()
        if info.st_uid not in (0, os.getuid()) or stat.S_IMODE(info.st_mode) & 0o022:
            fail('trusted path and ancestors must be caller/root owned and not group/other writable')
    for mount in writable:
        if overlaps(resolved, Path(mount).resolve()) or overlaps(path, Path(mount).absolute()):
            fail('trusted input overlaps an agent-writable mount')
    return resolved


def public_address(value):
    address = ipaddress.ip_address(value)
    if any(address.version == network.version and address in network for network in SPECIAL_NETWORKS):
        return False
    # ipaddress classifications vary across Python releases; be conservative.
    return (address.is_global and not address.is_multicast and not address.is_reserved
            and not address.is_loopback and not address.is_link_local
            and not address.is_unspecified and not address.is_private
            and not (isinstance(address, ipaddress.IPv6Address) and
                     (address.ipv4_mapped or address.sixtofour or address.teredo))
            and not (isinstance(address, ipaddress.IPv6Address) and
                     address in ipaddress.ip_network('64:ff9b::/96')))
