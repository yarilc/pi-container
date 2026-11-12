"""Interactive operator setup. Never invoked by an ordinary sandbox launch."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import uuid
import importlib.util

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import common  # noqa: F401  (validates the checkout's agent profile first)
except ValueError as error:
    print('sandbox-egress: setup incomplete: ' + str(error), file=sys.stderr)
    sys.exit(1)
from common import (BUDGETS, IMAGE_ID, MANIFEST, PROFILE, SetupError, absolute, defaults, endpoint_url, installation_directory,
                    load, overlap, prepare_state, private, protect_mounts, runtime_environment,
                    save, source_identity, trusted, validate, writable_mounts)


SOURCE = Path(__file__).resolve().parents[1]
platform_spec = importlib.util.spec_from_file_location('sandbox_platform', SOURCE / 'network/platform_check.py')
platform_rules = importlib.util.module_from_spec(platform_spec)
platform_spec.loader.exec_module(platform_rules)
RUNTIME_IMAGE = PROFILE.image('agent', 'latest')
TOOLCHAIN_IMAGE = PROFILE.image('toolchain', 'development')
PROXY_IMAGE = PROFILE.image('proxy', 'local')
PREFIX = PROFILE.message_prefix
NAME = PROFILE.display_name
GUARD = 'sandbox-egress-guard'
import agent_budgets  # noqa: E402  (protected network code beside common.py's path entry)
BUDGET_QUESTIONS = (
    ('memory_limit', 'Agent memory limit (integer with k, m or g unit)'),
    ('cpu_limit', 'Agent CPU limit (CPUs, up to 3 decimals)'),
    ('pids_limit', 'Agent process limit'),
    ('run_timeout', 'Session lifetime in seconds, 0 disables'),
)


def ask(label, default='', choices=None):
    while True:
        answer = input(f'{label} [{default}]: ').strip() or str(default)
        if choices is None or answer in choices:
            return answer
        print('Choose one of: ' + ', '.join(choices))


def yes(label, default=False):
    return ask(label + ' (yes/no)', 'yes' if default else 'no', ('yes', 'no')) == 'yes'


def path_question(label, default):
    while True:
        try:
            return absolute(ask(label, default))
        except SetupError as error:
            print(error)


def current_release(root):
    trusted(root, missing=True)
    pointer = root / 'current'
    if not pointer.exists() and not pointer.is_symlink():
        return None
    if not pointer.is_symlink():
        raise SetupError('Reserved current path is not a managed release symlink.')
    release = trusted(pointer)
    if release.parent != root.resolve() / 'releases' or not release.is_dir():
        raise SetupError('Current release points outside the managed releases directory.')
    return release


def residual_notice():
    """Disclose the foreign-credential channel of every provider profile."""
    print('Residual exfiltration: provider mode binds each tunnel to an approved host, but it cannot tell your')
    print('credentials from attacker-supplied ones. A prompt-injected agent can send workspace data to an allowed')
    print('host using a foreign API key or account. Allowed hosts: '
          + '; '.join(method + ': ' + ', '.join(item['hosts']) for method, item in PROFILE.auth.items()) + '.')
    print('Only offline mode removes this channel. See docs/network-contract.md (Residual exfiltration).')


def choose_network(default):
    """Ask for the network mode; provider mode requires an explicit acknowledgement each time."""
    while True:
        mode = ask('Network mode', default, ('offline', 'provider', 'unrestricted'))
        if mode != 'provider':
            return mode
        residual_notice()
        if yes('Acknowledge that allowed provider hosts can receive data sent with foreign credentials?'):
            return mode
        print('Provider mode not acknowledged; choose the network mode again.')


def questionnaire():
    print(NAME + ' sandbox setup — no host packages will be installed. Ctrl+C cancels.')
    print('Podman must already be installed. Setup uses host Python 3 and GNU coreutils.')
    ambient = sorted(k for k in os.environ if k.startswith(PROFILE.env_prefix + '_') or k in
                     (PROFILE.config_dir_env, PROFILE.approval_bypass_env, 'CONTAINER_HOST', 'CONTAINER_CONNECTION'))
    if ambient:
        print('Existing environment controls (values are not recorded): ' + ', '.join(ambient))
        print('Review choices below; setup checks use these choices. Explicit environment overrides apply on later launches.')
    source_preferences = SOURCE / 'setup.json'
    previous = load(source_preferences) if source_preferences.exists() else defaults()
    root = Path(path_question('Protected native installation directory', previous['installation']))
    old = current_release(root)
    previous = load(old / 'setup.json') if old else defaults(root)
    value = previous.copy()
    value['installation'] = str(root)
    print('offline: no external network; provider: approved CONNECT hosts with initial and retried TLS SNI binding; unrestricted: ordinary network access.')
    print('Provider mode rejects ECH/GREASE and unverifiable TLS names; encrypted Host/shared-service routing is not filtered.')
    value['network'] = choose_network(value['network'])
    default_auth = next(iter(PROFILE.auth))
    value['auth'] = 'none'
    if value['network'] != 'offline':
        print('; '.join(method + ' ' + item['description'] for method, item in PROFILE.auth.items())
              + '. No secret is requested here.')
        value['auth'] = ask('Authentication method', previous['auth'] if previous['auth'] != 'none' else default_auth, tuple(PROFILE.auth))
    print('shared exposes your selected host ' + NAME + ' credentials and shared ' + ', '.join(PROFILE.shared_dirs or ('no other'))
          + ' configuration. isolated starts a fresh private home; nothing is copied.')
    state = ask('State mode', 'isolated' if value['state_dir'] else 'shared', ('shared', 'isolated'))
    value['state_dir'] = value['config_dir'] = ''
    if state == 'isolated':
        value['state_dir'] = path_question('Private isolated state directory', previous['state_dir'] or str(Path.home() / '.local/share' / PROFILE.name / 'home'))
        if os.environ.get(PROFILE.config_dir_env) and not yes('A nonempty ' + PROFILE.config_dir_env + ' conflicts with isolation. Continue with isolated setup choices (unset it before normal launch)?'):
            raise SetupError('Choose shared state or unset ' + PROFILE.config_dir_env + ' and rerun setup.')
    else:
        selected = path_question('Shared ' + NAME + ' configuration directory', previous['config_dir'] or str(Path.home() / PROFILE.config_home))
        value['config_dir'] = selected
    print('Podman delegation gives the application host container/mount authority beyond this workspace.')
    value['podman'] = yes('Delegate the host Podman API to the application?', value['podman'])
    while value['podman'] and value['network'] != 'unrestricted':
        print('Delegation is incompatible with restricted networking. It cannot be enabled without an explicit network choice.')
        choice = ask('Resolve conflict', 'disable-delegation', ('disable-delegation', 'change-network'))
        if choice == 'disable-delegation':
            value['podman'] = False
        else:
            value['network'] = choose_network(value['network'])
            if value['network'] != 'offline' and value['auth'] == 'none':
                value['auth'] = ask('Authentication method', default_auth, tuple(PROFILE.auth))
    if value['network'] == 'offline':
        value['auth'] = 'none'
    print('Permission bypass skips ' + NAME + ' approvals; it does not change network enforcement or grant Podman.')
    value['yolo'] = yes('Enable ' + NAME + ' permission bypass (YOLO)?', value['yolo'])
    print('Worktree mode mounts the entire current directory parent read/write, including sibling projects.')
    value['worktree'] = yes('Use parent-directory worktree scope by default?', value['worktree'])
    print('Agent containers always run with memory, CPU and process budgets; they do not limit workspace or state storage.')
    print('Managed launches use these values unless the corresponding variable is exported; restricted changes require requalification.')
    for name, label in BUDGET_QUESTIONS:
        suffix = BUDGETS[name]
        while True:
            try:
                value[name] = agent_budgets.canonical(suffix, ask(label, value[name]))
                break
            except agent_budgets.BudgetError:
                print('Invalid value: use ' + agent_budgets.FORMATS[suffix] + '.')
    print('Host CA trust mounts only one read-only CA bundle and changes TLS trust.')
    value['trust_ca'] = yes('Trust a host CA bundle?', value['trust_ca'])
    value['ca_bundle'] = ''
    if value['trust_ca']:
        default_ca = next((str(p) for p in map(Path, ('/etc/ssl/certs/ca-certificates.crt', '/etc/pki/tls/certs/ca-bundle.crt')) if p.is_file()), '')
        value['ca_bundle'] = path_question('CA bundle file', previous['ca_bundle'] or default_ca)
    value['command'] = path_question('Managed launch command path', value['command'])
    needs_service = value['network'] != 'unrestricted' or value['podman']
    default_endpoint = value['endpoint'] if old else os.environ.get('CONTAINER_HOST') or ('default' if needs_service else 'local')
    print('The launch engine must be on this Linux host. Use default for the user socket, local for a local engine, or unix:///absolute/socket.')
    while True:
        value['endpoint'] = ask('Podman launch endpoint', default_endpoint)
        try:
            endpoint_url(value['endpoint'])
            if needs_service and value['endpoint'] == 'local':
                raise SetupError('This mode requires a same-host Unix service.')
            break
        except SetupError as error:
            print(error)
    value['delegation_socket'] = ''
    if value['podman'] and yes('Use a separate delegation socket?', bool(previous['delegation_socket'])):
        value['delegation_socket'] = path_question('Absolute delegation socket path', previous['delegation_socket'] or endpoint_url(value['endpoint'])[7:])
    if value['network'] == 'provider':
        value['runtime_dir'] = path_question('Private native egress runtime directory', value['runtime_dir'])
    return value, old


class Captured(str):
    """Captured standard output that also carries the command's standard error."""
    stderr = ''


def stderr_excerpt(data, *, lines=5, width=2048):
    """Bounded, printable-only tail of untrusted command diagnostics."""
    if isinstance(data, bytes):
        data = data.decode('utf-8', errors='replace')
    kept = (''.join(char for char in line if char.isprintable()).strip() for line in (data or '').splitlines())
    return [line[:width] for line in [line for line in kept if line][-lines:]]


def print_excerpt(data):
    for line in stderr_excerpt(data):
        print(PREFIX + 'smoke: ' + line, file=sys.stderr)


def run(command, env, *, capture=False, input=None, timeout=20, terminal=False, cwd=None, excerpt=False):
    command = list(map(str, command))
    # Login retains its controlling terminal. Other operator commands receive
    # their own process group, so cancellation cannot kill the setup itself.
    grouped = not terminal
    process = None
    try:
        process = subprocess.Popen(command, env=env, start_new_session=grouped, cwd=cwd,
                                   stdin=subprocess.PIPE if input is not None else None,
                                   stdout=subprocess.PIPE if capture else None,
                                   stderr=subprocess.PIPE if capture else None)
        stdout, stderr = process.communicate(input.encode() if input is not None else None, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        stop_child(process, grouped)
        raise SetupError('Setup operation timed out; inspect owned resources before retrying.') from error
    except OSError as error:
        if process is not None:
            stop_child(process, grouped)
        raise SetupError('Required host command could not be executed.') from error
    except BaseException:
        if process is not None:
            stop_child(process, grouped)
        raise
    if process.returncode:
        if capture and '--container-qualify' in command and stderr:
            for line in stderr.decode(errors='replace').splitlines():
                if line.startswith(PREFIX + 'status='):
                    print(''.join(char for char in line[:2048] if char.isprintable()), file=sys.stderr)
        if capture and excerpt:
            print_excerpt(stderr)
        raise SetupError(f'Setup command failed (exit {process.returncode}): {command[0]} {command[1] if len(command) > 1 else ""}; check prerequisites and retry.')
    if not capture:
        return ''
    if not excerpt:
        return stdout.decode('utf-8')
    output = Captured(stdout.decode('utf-8'))
    output.stderr = stderr.decode('utf-8', errors='replace')
    return output


def stop_child(process, grouped):
    if not grouped and process.poll() is not None:
        return
    try:
        if grouped:
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
    except ProcessLookupError:
        pass
    try:
        process.communicate(timeout=25)  # Allow the wrapper's owned 20-second shutdown.
    except subprocess.TimeoutExpired:
        pass
    finally:
        # The leader may have exited before timeout, or descendants may close
        # the pipes in response to TERM without exiting. Finish the owned group
        # even when communicate() has already reaped the leader.
        try:
            if grouped:
                os.killpg(process.pid, signal.SIGKILL)
            elif process.poll() is None:
                process.kill()
        except ProcessLookupError:
            pass
    try:
        process.communicate(timeout=2)
    except subprocess.TimeoutExpired:
        # A descendant that escaped the group can still hold a pipe open.
        # Preserve the primary timeout/interruption and bound local teardown.
        for pipe in (process.stdin, process.stdout, process.stderr):
            if pipe is not None:
                pipe.close()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            print(PREFIX + 'setup child cleanup could not be confirmed.', file=sys.stderr)


def record(command, env):
    output = run(command, env, capture=True)
    line = output[:-1] if output.endswith('\n') else output
    if not line or '\n' in line or '\r' in line:
        raise SetupError('Invalid Podman response: exactly one record is required.')
    return line


def host_env(value):
    env = os.environ.copy()
    env.pop('CONTAINER_CONNECTION', None)
    env.pop(PROFILE.env('MAINTENANCE'), None)
    endpoint = endpoint_url(value['endpoint'])
    if endpoint:
        env['CONTAINER_HOST'] = endpoint
    else:
        env.pop('CONTAINER_HOST', None)
    return env


def verify_engine(env, restricted):
    try:
        output = record(['podman', 'info', '--format', '{{.Host.Security.Rootless}} {{.Host.OS}} {{.Host.ServiceIsRemote}}'], env)
    except SetupError as error:
        raise SetupError('Cannot verify Podman. Run podman info as this non-root user; check its service, /etc/subuid, /etc/subgid, newuidmap/newgidmap and rootless networking prerequisites. Setup does not install or repair them.') from error
    if output not in ('true linux false', 'true linux true'):
        raise SetupError('A verified Linux rootless Podman engine is required.')
    if output.endswith('true') and not env.get('CONTAINER_HOST', '').startswith('unix:///'):
        raise SetupError('Remote operation requires an explicit same-host Unix endpoint.')
    if restricted:
        if not output.endswith('true'):
            raise SetupError('Restricted mode requires the verified same-host Unix launch service.')
        backend = record(['podman', 'info', '--format', '{{.Host.NetworkBackend}}'], env)
        version = record(['podman', 'version', '--format', '{{.Server.Version}}'], env)
        host = json.loads(run(['podman', 'info', '--format', '{{json .Host}}'], env, capture=True))
        try:
            platform_rules.validate(host, version, backend, env.get('CONTAINER_HOST', ''), output)
        except platform_rules.PlatformError as error:
            raise SetupError('Unsupported restricted platform [status=ineligible]: ' + str(error) + '. No automatic fallback or security-policy change is allowed.') from error


def verify_socket(url, env):
    path = Path(url[7:])
    if not path.is_socket() or not os.access(path, os.R_OK | os.W_OK):
        raise SetupError('The selected Podman Unix socket is not accessible.')
    output = record(['podman', '--remote', '--url', url, 'info', '--format', '{{.Host.Security.Rootless}} {{.Host.RemoteSocket.Path}}'], env)
    rootless, separator, host_path = output.partition(' ')
    # Podman 5 reports the service socket as a unix:// URL; earlier releases report the bare path.
    host_path = host_path.removeprefix('unix://')
    if rootless != 'true' or not separator or not host_path.startswith('/'):
        raise SetupError('The exact Podman socket must serve a rootless engine and report an absolute host socket path.')


def manual_service(url):
    socket = Path(url[7:])
    print('No verified user service is available. In a host terminal, as the same non-root user:')
    print('  # The runtime directory must already be caller-owned, mode 0700, on native Linux storage.')
    print('  # If /run/user/<uid> is missing, ask the administrator to prepare a proper login runtime directory.')
    print('  install -d -m 0700 -- ' + shlex.quote(str(socket.parent)))
    print('  podman system service --time=0 ' + shlex.quote(url))
    print('Leave that foreground service running; rerun setup in another terminal with the same runtime directory.')


def prepare_service(value, changes):
    env = host_env(value)
    url = endpoint_url(value['endpoint'])
    if url:
        try:
            verify_socket(url, env)
        except SetupError:
            default_url = endpoint_url('default')
            manager = False
            if url == default_url and shutil.which('systemctl'):
                try:
                    run(['systemctl', '--user', 'show-environment'], env, capture=True)
                    manager = True
                except SetupError:
                    pass
            if manager and yes('Enable and start persistent systemd user podman.socket (no application delegation is implied)?'):
                # Track the attempted persistent change even if systemctl partly succeeds.
                changes.append('User podman.socket enable/start was requested; inspect systemctl --user status podman.socket.')
                run(['systemctl', '--user', 'enable', '--now', 'podman.socket'], env)
                verify_socket(url, env)
            else:
                manual_service(url)
                raise SetupError('Sandbox incomplete: start or select a working same-host Unix service, then rerun setup.')
    verify_engine(env, value['network'] != 'unrestricted')
    if value['podman']:
        verify_socket('unix://' + value['delegation_socket'] if value['delegation_socket'] else url, env)
    return env


def check_prerequisites():
    if os.getuid() == 0:
        raise SetupError('Run setup as the non-root user who will use this sandbox.')
    if not shutil.which('podman'):
        raise SetupError('Podman is required on the host. Install it and its rootless prerequisites before rerunning setup; setup installs no packages.')
    if os.environ.get('CONTAINER_CONNECTION'):
        raise SetupError('Named connections are unsupported; unset CONTAINER_CONNECTION and use a same-host Unix endpoint.')
    if os.environ.get('CONTAINER_HOST'):
        endpoint_url(os.environ['CONTAINER_HOST'])
    for name in ('bash', 'readlink', 'stat', 'timeout', 'sha256sum'):
        if not shutil.which(name):
            raise SetupError(f'Host prerequisite missing: {name}; complete host setup before continuing.')
    if 'GNU coreutils' not in run(['timeout', '--version'], os.environ.copy(), capture=True):
        raise SetupError('GNU timeout with kill-after support is required.')


def planned_paths(value):
    # Validate before asking for mutation consent. Missing directories are not created yet.
    root = installation_directory(value['installation'])
    trusted(value['command'], missing=True)
    if overlap(root, value['command']):
        raise SetupError('Place the managed command outside the installation root.')
    env = runtime_environment(value, root, overrides=False)
    protect_mounts(value, env)
    prepare_state(env)
    if value['network'] == 'provider':
        private(value['runtime_dir'])
    if value['trust_ca'] and (not Path(value['ca_bundle']).is_file() or not os.access(value['ca_bundle'], os.R_OK)):
        raise SetupError('The selected CA bundle must be a readable regular file.')
    for name in MANIFEST:
        path = SOURCE / name
        if path.is_symlink() or not path.is_file():
            raise SetupError('Installation input missing or symlinked: ' + name)
    return root


def image_identity(name, env):
    result = subprocess.run(['podman', 'image', 'exists', name], env=env, timeout=20,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if result.returncode == 1:
        return ''
    if result.returncode != 0:
        raise SetupError('Cannot inspect image; engine errors do not authorize a build.')
    identity = record(['podman', 'image', 'inspect', '--format', '{{.Id}}', name], env)
    if not IMAGE_ID.fullmatch(identity):
        raise SetupError('Image inspection did not return a full immutable image ID.')
    return identity


def build_image(release, recipe, tag, env, ca_bundle=''):
    # Pull the recipe's exact base before --pull=never builds. No pin substitutions.
    recipe_path = release / recipe
    bases = re.findall(r'^FROM\s+(\S+)', recipe_path.read_text(), re.MULTILINE)
    for base in bases:
        if not image_identity(base, env):
            run(['podman', 'pull', base], env, timeout=None)
    # The opted-in host CA bundle verifies build-time package fetches as a build
    # secret; it is mounted only for the RUN step and never stored in a layer.
    secret = ['--secret', 'id=build-ca,src=' + ca_bundle] if ca_bundle else []
    run(['podman', 'build', '--pull=never', *secret, '--tag', tag, '--file', recipe_path,
         recipe_path.parent], env, timeout=None)
    identity = image_identity(tag, env)
    if not identity:
        raise SetupError('Built image is unavailable after preparation.')
    return identity


def build_runtime(release, tag, env, ca_bundle=''):
    # A wrapper-built runtime keeps the agent's own build arguments and labels.
    if PROFILE.runtime_build == 'recipe':
        return build_image(release, 'Containerfile', tag, env, ca_bundle)
    # The build-only operation starts no session; the mode only admits it. The
    # wrapper receives the trust selection and bundle explicitly and passes the
    # bundle to its own build as a build secret; without trust it gets none.
    run(['bash', release / PROFILE.wrapper, '--container-build'],
        env | {PROFILE.env('NETWORK'): 'unrestricted', PROFILE.env('IMAGE'): tag,
               PROFILE.env('TRUST_HOST_CA'): '1' if ca_bundle else '0',
               PROFILE.env('CA_BUNDLE'): ca_bundle}, input='', timeout=None)
    identity = image_identity(tag, env)
    if not identity:
        raise SetupError('Built image is unavailable after preparation.')
    return identity


def copy_inputs(release):
    for name in MANIFEST:
        target = release / name
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        shutil.copyfile(SOURCE / name, target)
        target.chmod(0o700 if name.endswith('.sh') else 0o600 if name.endswith('default.json') else 0o644)


def dispatcher(root, *, legacy=False):
    # Only a shell-quoted, validated installation path is interpolated as code.
    return ('#!/usr/bin/env bash\nset -Eeuo pipefail\n'
            '# Managed by ' + PROFILE.name + ' setup.\n'
            'installation=' + shlex.quote(str(root)) + '\n'
            'for arg in "$@"; do\n'
            '    if [[ "$arg" == --container-help ]]; then\n'
            '        exec /bin/bash "$installation/current/' + PROFILE.wrapper + '" --container-help\n'
            '    fi\n'
            'done\n'
            'exec python3 -I "$installation/current/setup/launch.py" '
            + ('' if legacy else '--managed-launcher "${BASH_SOURCE[0]}" ')
            + '"$@"\n')


@contextmanager
def installation_lock(root):
    installation_directory(root, create=True)
    lock = root / '.setup.lock'
    try:
        lock.mkdir(mode=0o700)
    except FileExistsError as error:
        raise SetupError('Setup busy: .setup.lock exists. Check for a running setup; remove a stale empty lock only after confirming no setup is active.') from error
    try:
        yield
    finally:
        lock.rmdir()


def owned_command(command, root):
    if command.is_symlink():
        raise SetupError('Refusing a symlink at the managed command path; choose another path.')
    if command.exists() and (not command.is_file() or command.stat().st_uid != os.getuid()
                             or command.read_text() not in (dispatcher(root), dispatcher(root, legacy=True))):
        raise SetupError('An unrelated file occupies the command path; choose another path.')


def activate(root, release, command):
    owned_command(command, root)
    trusted(command.parent, missing=True)
    previous = current_release(root)
    previous_command = Path(load(previous / 'setup.json')['command']) if previous else None
    previous_exists = previous_command is not None and (previous_command.exists() or previous_command.is_symlink())
    if previous_exists:
        trusted(previous_command)
        owned_command(previous_command, root)
    retire = (previous_command is not None and previous_command.resolve() != command.resolve()
              and previous_exists)
    old = os.readlink(root / 'current') if (root / 'current').is_symlink() else None
    token = uuid.uuid4().hex
    pointer = root / ('.current.' + token)
    command_temp = command.parent / ('.' + PROFILE.name + '.' + token)
    command_backup = command.parent / ('.' + PROFILE.name + '.previous.' + token)
    changed = False
    published = False
    upgrade = command.exists() and command.read_text() == dispatcher(root, legacy=True)
    try:
        os.symlink(str(release.relative_to(root)), pointer)
        # Upgrade recognized legacy dispatchers so every launch identifies its
        # actual entry path. Unrelated command files are never overwritten.
        if not command.exists() or upgrade:
            old_umask = os.umask(0o077)
            try:
                command.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            finally:
                os.umask(old_umask)
            with command_temp.open('x') as output:
                output.write(dispatcher(root))
            command_temp.chmod(0o700)
        if upgrade:
            os.link(command, command_backup)
        os.replace(pointer, root / 'current')
        changed = True
        if command_temp.exists():
            if upgrade:
                owned_command(command, root)
                os.replace(command_temp, command)
            else:
                # A hard link publishes without overwriting a competing file.
                os.link(command_temp, command)
            published = True
        if retire:
            # Obsolete managed scripts must not remain host entry points that a
            # later workspace can overwrite. Do this only after publication;
            # failure rolls the new pointer/command back, preserving the old one.
            owned_command(previous_command, root)
            previous_command.unlink()
    except BaseException:
        if changed:
            if old is None:
                (root / 'current').unlink()
            else:
                if pointer.is_symlink():
                    pointer.unlink()
                os.symlink(old, pointer)
                os.replace(pointer, root / 'current')
        if published:
            if upgrade:
                os.replace(command_backup, command)
            else:
                command.unlink()
        raise
    finally:
        pointer.unlink(missing_ok=True)
        command_temp.unlink(missing_ok=True)
        command_backup.unlink(missing_ok=True)


def prepare_artifacts(value, previous, release, env, images, refresh, changes):
    maintenance = env | {PROFILE.env('MAINTENANCE'): '1'}
    candidate_tag = PROFILE.image('agent', 'setup-' + release.name)
    runtime = '' if refresh else images['runtime']
    if runtime:
        run(['podman', 'tag', runtime, candidate_tag], maintenance)
    else:
        changes.append('Runtime build requested; intermediate build images may remain under ' + candidate_tag)
        runtime = build_runtime(release, candidate_tag, maintenance,
                                value['ca_bundle'] if value['trust_ca'] else '')
    changes.append('Prepared runtime image tag: ' + candidate_tag)
    value['image'], value['image_id'] = candidate_tag, runtime
    if value['network'] == 'unrestricted':
        value['proxy_image'] = value['toolchain_image'] = value['guard_sources_sha256'] = ''
        return
    (release / 'network/bin').mkdir(mode=0o700)
    identity = source_identity(release)
    can_reuse_guard = (not refresh and previous and previous['guard_sources_sha256'] == identity
                       and images.get('guard_release'))
    if can_reuse_guard:
        old = Path(images['guard_release'])
        run(['python3', '-I', old / 'network/control.py', 'preflight', '--installation', old], env)
        for name in (GUARD, GUARD + '.sha256'):
            shutil.copyfile(old / 'network/bin' / name, release / 'network/bin' / name)
        (release / 'network/bin' / GUARD).chmod(0o500)
    else:
        toolchain = '' if refresh else images['toolchain']
        if not toolchain:
            changes.append('Toolchain build requested: ' + PROFILE.image('toolchain', 'setup-' + release.name))
            toolchain = build_image(release, 'network/guard-build.Containerfile',
                                    PROFILE.image('toolchain', 'setup-' + release.name), maintenance,
                                    value['ca_bundle'] if value['trust_ca'] else '')
        value['toolchain_image'] = toolchain
        run(['bash', release / 'network/build-guard.sh', release / 'network/bin'],
            maintenance | {'SANDBOX_GUARD_TOOLCHAIN': toolchain,
                           'SANDBOX_GUARD_SETUP_CIDFILE': str(release / 'network/bin' / ('.setup-guard.' + uuid.uuid4().hex))}, timeout=None)
    value['guard_sources_sha256'] = identity
    if value['network'] == 'provider':
        proxy = '' if refresh else images['proxy']
        if not proxy:
            changes.append('Proxy build requested: ' + PROFILE.image('proxy', 'setup-' + release.name))
            proxy = build_image(release, 'network/Containerfile',
                                PROFILE.image('proxy', 'setup-' + release.name), maintenance)
        value['proxy_image'] = proxy
    else:
        value['proxy_image'] = ''


@contextmanager
def scratch_workspace():
    # Setup containers never mount the caller's current directory, which may be
    # a refused sensitive workspace such as the home directory. The extra level
    # keeps the worktree-mode parent private too.
    # It lives under the caller's cache directory: bind sources must exist at
    # the same path for the engine, which a private /tmp may not provide.
    cache = Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache')
    cache.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.' + PROFILE.name + '-setup-', dir=cache) as base:
        workspace = Path(base) / 'workspace'
        workspace.mkdir(mode=0o700)
        yield workspace


def engine_enforced(env):
    # Budgets are enforced only for controllers the verified engine delegates.
    try:
        return agent_budgets.enforced(record(['podman', 'info', '--format', '{{.Host.CgroupControllers}}'], env))
    except agent_budgets.ControllerError:
        raise SetupError('The Podman engine reported an unverifiable cgroup controller list.') from None


def expected_budgets(value):
    record = agent_budgets.normalize({suffix: value[name] for name, suffix in BUDGETS.items()})
    return [str(record[key]) for key in ('memory', 'nano_cpus', 'pids')]


def smoke(value, release):
    with scratch_workspace() as workspace:
        smoke_in(value, release, workspace)


def smoke_in(value, release, workspace):
    env = runtime_environment(value, release, overrides=False)
    protect_mounts(value, env, workspace=workspace)
    if value['network'] != 'unrestricted':
        output = run(['bash', str(release / PROFILE.wrapper), '--container-qualify'],
                     env, capture=True, timeout=360, cwd=workspace)
        if output.splitlines().count('SANDBOX_QUALIFICATION_OK') != 1:
            raise SetupError('Installed sandbox qualification did not confirm readiness.')
        statuses=[line.split('=',1)[1] for line in output.splitlines()
                  if line.startswith('SANDBOX_QUALIFICATION_STATUS=')]
        if len(statuses)!=1 or statuses[0] not in ('locally-qualified','release-measured'):
            raise SetupError('Installed sandbox qualification status is invalid.')
        print('Sandbox qualification: ' + statuses[0])
        if statuses[0]=='locally-qualified':
            print('This installation passed local enforcement checks; its combination is not release-measured. SELinux/AppArmor compatibility is not guaranteed.')
    script = (release / 'setup/smoke.py').read_text()
    smoke_args = [value['network'], '1' if value['trust_ca'] else '0', PROFILE.home,
                  PROFILE.config_dir_env, PROFILE.command, *expected_budgets(value),
                  ','.join(engine_enforced(env))]
    program = ('set -Eeuo pipefail\npython3 - ' + ' '.join(map(shlex.quote, smoke_args))
               + " <<'SANDBOX_SETUP_SMOKE'\n" + script + '\nSANDBOX_SETUP_SMOKE\n')
    args = ['bash', str(release / PROFILE.wrapper), '--container-shell']
    if value['worktree']:
        args.append('--container-git-worktree')
    output = run(args, env, capture=True, input=program, timeout=90, cwd=workspace, excerpt=True)
    if output.splitlines().count('SANDBOX_SETUP_SMOKE_OK') != 1:
        print_excerpt(getattr(output, 'stderr', ''))
        raise SetupError('Installed sandbox smoke check did not confirm readiness.')


def authenticate(value, release):
    status = 'not applicable' if value['network'] == 'offline' else 'pending'
    if value['network'] == 'offline':
        return status
    command = shlex.quote(value['command'])
    method = value['auth']
    item = PROFILE.auth[method]
    if 'login_args' in item:
        login = item['login_args']
        # Empty login arguments: the agent has no login command, so sign-in
        # happens in its own interactive session.
        interactive = not login
        print('Existing shared account credentials may already be usable. Login is optional and runs inside the selected sandbox.')
        question = ('Run ' + NAME + ' ' + method + ' sign-in now? It opens ' + NAME + ' interactively; exit it when signed in.'
                    if interactive else 'Run ' + NAME + ' ' + method + ' login now?')
        if yes(question):
            try:
                # Inherit the terminal directly. Do not capture/log login output.
                args = ['bash', release / PROFILE.wrapper]
                if value['worktree']:
                    args.append('--container-git-worktree')
                with scratch_workspace() as workspace:
                    run([*args, *login], runtime_environment(value, release, overrides=False),
                        timeout=None, terminal=True, cwd=workspace)
                status = ('verified (' + NAME + ' ' + method + ' interactive sign-in session exited successfully; no model request tested)'
                          if interactive else 'verified (' + NAME + ' ' + method + ' login succeeded; no model request tested)')
            except (SetupError, KeyboardInterrupt):
                print('Login did not complete; the installed sandbox is still ready.')
        if status == 'pending':
            if interactive:
                print('Next authentication action: ' + command
                      + ' (sign in inside the interactive session, or reuse your selected existing account state).')
            else:
                print('Next authentication action: ' + command + ' ' + ' '.join(map(shlex.quote, login))
                      + ' (or reuse your selected existing account state).')
    if 'credential_env' in item:
        print('Authentication pending. Supply ' + item['credential_env']
              + ' using the existing runtime environment mechanism; no key is stored by setup.')
        if value['network'] == 'unrestricted':
            print('The current direct API-key forwarding mechanism is provider mode; select provider/' + method
                  + ' for environment-key forwarding, or configure ' + NAME + ' credentials explicitly.')
    return status


def path_guidance(command):
    directory = str(Path(command).parent)
    if directory not in os.environ.get('PATH', '').split(os.pathsep):
        print('The managed command directory is not on PATH. Use the absolute command or run:')
        print('  export PATH=' + shlex.quote(directory) + ':"$PATH"')
        print('For future terminals, add that export line to your shell startup file (for example ~/.bashrc for Bash). Setup does not edit it.')


def main():
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise SetupError('--container-setup requires an interactive terminal.')
    changes = []
    candidate = None
    activated = False
    try:
        check_prerequisites()
        value, old_release = questionnaire()
        previous = load(old_release / 'setup.json') if old_release else None
        root = planned_paths(value)
        owned_command(Path(value['command']), root)
        env = prepare_service(value, changes)
        images = {'runtime': image_identity(previous['image'] if previous else RUNTIME_IMAGE, env)}
        if value['network'] != 'unrestricted':
            images['toolchain'] = image_identity(previous['toolchain_image'] if previous and previous['toolchain_image'] else TOOLCHAIN_IMAGE, env)
            images['guard_release'] = str(old_release) if old_release else ''
        if value['network'] == 'provider':
            images['proxy'] = image_identity(previous['proxy_image'] if previous and previous['proxy_image'] else PROXY_IMAGE, env)
        print('\nSetup plan:')
        for key in ('network', 'auth', 'installation', 'command', 'state_dir', 'config_dir', 'endpoint',
                    'podman', 'yolo', 'worktree', 'memory_limit', 'cpu_limit', 'pids_limit',
                    'run_timeout', 'trust_ca', 'ca_bundle'):
            print(f'  {key}: {value[key]}')
        if previous and Path(previous['command']).resolve() != Path(value['command']).resolve():
            print('  retire previous managed command after successful activation: ' + previous['command'])
        if value['network'] == 'provider':
            print('  protected profile: ' + PROFILE.policy_profile(value['auth']))
            print('  private egress runtime: ' + value['runtime_dir'])
        for name in ('runtime', 'toolchain', 'proxy'):
            if name in images:
                print(f'  {name} image: ' + ('reuse inspected ' + images[name] if images[name] else 'prepare/build missing image'))
        # Budgets follow the controllers the engine delegates; no extra question.
        enforced = engine_enforced(env)
        print('  enforced agent budgets: ' + (', '.join(enforced) or 'none'))
        for controller, label in (('memory', 'memory'), ('cpu', 'CPU'), ('pids', 'process')):
            if controller not in enforced:
                print(f'  agent {label} budget not enforced: cgroup controller {controller} '
                      'is not delegated to the rootless engine')
        if value['network'] == 'provider':
            for controller, label in (('memory', 'memory'), ('pids', 'process')):
                if controller not in enforced:
                    print(f'  proxy {label} budget not enforced: cgroup controller {controller} '
                          'is not delegated to the rootless engine')
        path_guidance(value['command'])
        refresh = yes('Refresh prepared images and recompile the guard instead of reusing valid artifacts?')
        print('Missing/selected images will be prepared; restricted mode includes a static guard and manifest.')
        print('Host pulls, package acquisition inside build images and build RUN steps are OUTSIDE runtime network filtering, including offline mode.')
        print('No host packages, credential imports, recursive permission repairs or shell-profile edits are performed.')
        if not yes('Apply this installation and authorize the listed host image maintenance?'):
            raise SetupError('Setup cancelled before installation/image preparation.')
        with installation_lock(root):
            # Revalidate after consent/locking, before writing anything to managed paths.
            latest = current_release(root)
            if latest != old_release:
                raise SetupError('The current installation changed during review; rerun setup.')
            planned_paths(value)
            releases = root / 'releases'
            if releases.is_symlink():
                raise SetupError('Reserved releases path must not be a symlink.')
            private(releases, create=True)
            candidate = releases / uuid.uuid4().hex
            candidate.mkdir(mode=0o700)
            copy_inputs(candidate)
            saved_env = runtime_environment(value, candidate, overrides=False)
            for path, is_private in prepare_state(saved_env, create=True):
                changes.append('Prepared or reused ' + ('private' if is_private else 'shared')
                               + ' state directory: ' + str(path))
            if value['network'] == 'provider':
                private(value['runtime_dir'], create=True)
            prepare_artifacts(value, previous, candidate, env, images, refresh, changes)
            validate(value)
            save(candidate / 'setup.json', value)
            print('Checking the installed sandbox with no credentials or model request...')
            smoke(value, candidate)
            blocked = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM, signal.SIGHUP})
            try:
                activate(root, candidate, Path(value['command']))
                activated = True
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, blocked)
        print('Sandbox: ready')
        status = authenticate(value, candidate)
        print('Authentication: ' + status)
        print('Launch from a workspace: ' + shlex.quote(value['command']))
        print('Review/change setup: ' + shlex.quote(value['command']) + ' --container-setup')
        path_guidance(value['command'])
        print('No authenticated model request was performed.')
    finally:
        if candidate is not None and not activated:
            shutil.rmtree(candidate)
        if changes:
            print('Persistent preparation effects (shared images/state and user services are not removed automatically):')
            for change in changes:
                print('  ' + change)


if __name__ == '__main__':
    def interrupted(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print('\nSetup interrupted. Any last activated installation is preserved.', file=sys.stderr)
        sys.exit(130)
    except (SetupError, OSError, ValueError) as error:
        print(PREFIX + 'setup incomplete: ' + str(error), file=sys.stderr)
        sys.exit(1)
