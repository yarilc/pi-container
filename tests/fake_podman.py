#!/usr/bin/env python3
"""Shared fake Podman engine for the launcher tests.

Every call is appended to FAKE_LOG as a JSON list. FAKE_* variables select
responses and failures. An engine command this fake does not implement fails
with status 99, so a test never passes on an unexpected engine call.
"""
import json, os, pathlib, sys, time, signal
args = sys.argv[1:]
log = pathlib.Path(os.environ['FAKE_LOG'])
if os.environ.get('FAKE_UMASK_LOG'):
    mask = os.umask(0)
    os.umask(mask)
    with pathlib.Path(os.environ['FAKE_UMASK_LOG']).open('a') as f:
        f.write(json.dumps([args[0], mask]) + '\n')
with log.open('a') as f:
    f.write(json.dumps(args) + '\n')
state = pathlib.Path(str(log) + '.container')
# The session container engine: its fixed ID, and the budgets it was created with.
ENGINE_ID = 'e' * 64
engine_budgets = pathlib.Path(str(log) + '.engine-budgets')
command = args[0]


def requested_budgets(args):
    from decimal import Decimal
    flag = lambda name: next((a.split('=', 1)[1] for a in args if a.startswith(name + '=')), '0')
    # Requested rlimits as the inspect template lists them: [NAME=soft:hard,...].
    rlimits = ''.join('RLIMIT_' + args[i + 1].split('=', 1)[0].upper() + '=' + args[i + 1].split('=', 1)[1] + ','
                      for i, a in enumerate(args) if a == '--ulimit')
    return ' '.join((flag('--memory'), str(int(Decimal(flag('--cpus')) * 10**9)), flag('--pids-limit'),
                     '[' + rlimits + ']'))

# The created command as Podman reports it: .Path, then .Args. --init runs the
# entry program through the init program; --entrypoint replaces the image's.
INIT = ['/run/podman-init', '--']


def created_command(args, image_index, default_entry):
    options, command = args[:image_index], args[image_index + 1:]
    entry = [options[options.index('--entrypoint') + 1]] if '--entrypoint' in options else default_entry
    return (INIT if '--init' in options else []) + entry + command


def report_command(record, override):
    # inspect {{.Path}} or {{index .Args N}} of a created command record.
    reported = json.loads(os.environ[override]) if override in os.environ else \
        json.loads(record.read_text()) if record.exists() else []
    template = args[args.index('--format') + 1]
    if template == '{{.Path}}' and reported:
        print(reported[0])
        sys.exit(0)
    index = int(template[len('{{index .Args '):-2]) if template.startswith('{{index .Args ') else -1
    if 0 <= index < len(reported) - 1:
        print(reported[index + 1])
        sys.exit(0)
    print(f'Error: template: inspect:1:2: executing "inspect" at <{template[2:-2]}>: error calling index: '
          f'index out of range: {index}', file=sys.stderr)
    sys.exit(125)


agent_command = pathlib.Path(str(log) + '.command')
engine_command = pathlib.Path(str(log) + '.engine-command')
proxy_command = pathlib.Path(str(log) + '.proxy-command')
# The process rlimit fallback sets the limit inside each container: an engine
# that applies it at creation shares it across every container of the user.
if command in ('create', 'run') and any(a == '--ulimit' and args[i + 1].startswith('nproc')
                                        for i, a in enumerate(args[:-1])):
    print('fake podman: --ulimit nproc is refused', file=sys.stderr)
    sys.exit(98)

if command in os.environ.get('FAKE_STALL', '').split(',') and (command != 'ps' or '--filter' in args):
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    pathlib.Path(str(log) + '.stalled-' + command).write_text(str(os.getpid()))
    while True:
        time.sleep(0.05)
if command in os.environ.get('FAKE_FAIL', '').split(','):
    print('synthetic control failure: ' + command, file=sys.stderr)
    sys.exit(17)
if args[0] == 'info':
    if args[-1] == '{{json .Host}}':
        print(os.environ.get('FAKE_PLATFORM',json.dumps({'kernel':'6.6.87.2-microsoft-standard-WSL2','arch':'amd64',
            'security':{'seccompEnabled':True,'selinuxEnabled':False,'apparmorEnabled':False}})))
        sys.exit(0)
    if args[-1] == '{{.Host.NetworkBackend}}':
        print(os.environ.get('FAKE_BACKEND', 'netavark'))
        sys.exit(0)
    if args[-1] == '{{.Host.CgroupControllers}}':
        print(os.environ.get('FAKE_CONTROLLERS', '[cpu memory pids]'))
        sys.exit(int(os.environ.get('FAKE_CONTROLLERS_STATUS', '0')))
    if args[-1] == '{{.Host.CgroupManager}}':
        if 'FAKE_CGROUP_MANAGER_RAW' in os.environ:
            sys.stdout.write(os.environ['FAKE_CGROUP_MANAGER_RAW'].encode().decode('unicode_escape'))
        else:
            print(os.environ.get('FAKE_CGROUP_MANAGER', 'systemd'))
        sys.exit(int(os.environ.get('FAKE_CGROUP_MANAGER_STATUS', '0')))
    if args[-1] == '{{.Host.Security.SECCOMPProfilePath}}':
        print(os.environ.get('FAKE_SECCOMP', ''))
        sys.exit(0)
    if args[-1] == '{{.Host.Kernel}}':
        # FAKE_KERNEL_RAW replaces the whole response (escapes allowed).
        if 'FAKE_KERNEL_RAW' in os.environ:
            sys.stdout.write(os.environ['FAKE_KERNEL_RAW'].encode().decode('unicode_escape'))
        else:
            print(os.environ.get('FAKE_KERNEL', '6.6.87.2-microsoft-standard-WSL2'))
        sys.exit(int(os.environ.get('FAKE_KERNEL_STATUS', '0')))
    sys.stdout.write(os.environ.get('FAKE_INFO_RAW', os.environ.get('FAKE_INFO', 'true linux false') + '\n'))
    sys.exit(int(os.environ.get('FAKE_INFO_STATUS', '0')))
elif args[0] == 'version':
    print(os.environ.get('FAKE_SERVER_VERSION', '4.9.3'))
elif args[:2] == ['image', 'exists']:
    if args[-1].endswith('-engine:latest') or args[-1] == os.environ.get('FAKE_ENGINE_IMAGE', '-'):
        sys.exit(int(os.environ.get('FAKE_ENGINE_IMAGE_STATUS', '0')))
    sys.exit(int(os.environ.get('FAKE_IMAGE_STATUS', '0')))
elif args[:2] == ['image', 'inspect']:
    if '[{{json .Config.Entrypoint}},{{json .Config.Cmd}}]' in args:
        # The proxy image's own program.
        print('[["python3","/opt/sandbox-egress/proxy.py"],null]')
        sys.exit(0)
    if any('build-inputs-hash' in a for a in args):
        print(os.environ.get('FAKE_LABEL_HASH', ''))
        sys.exit(int(os.environ.get('FAKE_LABEL_STATUS', '0')))
    if any('.Config.Env' in a for a in args):
        print(os.environ.get('FAKE_IMAGE_ENV', 'PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'))
    else:
        print('d' * 64)
elif args[0] == 'pull':
    sys.exit(int(os.environ.get('FAKE_PULL_STATUS', '0')))
elif args[0] == 'build':
    time.sleep(float(os.environ.get('FAKE_BUILD_DELAY', '0')))
    sys.exit(int(os.environ.get('FAKE_BUILD_STATUS', '0')))
elif args[0] == 'ps':
    if any('.Labels' in a for a in args):
        # Podman 6.2: `.Labels` is a string in ps templates, so indexing it fails.
        print('Error: template: ps:1:1: executing "ps" at <index .Labels>: error calling index: '
              'cannot index slice/array with type string', file=sys.stderr)
        sys.exit(125)
    if 'label=sandbox-engine.owner' in args:
        # Running engines from '<id> <owner>' lines (FAKE_ENGINES, escapes allowed).
        for line in os.environ.get('FAKE_ENGINES', '').encode().decode('unicode_escape').splitlines():
            if line.split():
                print(line.split()[0])
    elif '--filter' in args:
        print(os.environ.get('FAKE_RECOVERY_ID', 'a' * 64) if state.exists() else '')
    else:
        print(os.environ.get('FAKE_NAMES', ''))
elif args[0] == 'create':
    if os.environ.get('FAKE_NETWORK') and any(a.startswith('io.') and '.egress=' in a for a in args):
        # The proxy image follows EGRESS_SESSION=<token> and the options after it.
        image = next(i for i, a in enumerate(args) if a.startswith('EGRESS_SESSION=')) + 1
        while args[image].startswith('--'):
            image += 2
        proxy_command.write_text(json.dumps(created_command(args, image, ['python3', '/opt/sandbox-egress/proxy.py'])))
        pathlib.Path(args[args.index('--cidfile') + 1]).write_text('b' * 64 + '\n')
        print('b' * 64)
        sys.exit(0)
    collision = pathlib.Path(str(log) + '.collision')
    if os.environ.get('FAKE_COLLISION') and (not collision.exists() or os.environ.get('FAKE_ALWAYS_COLLIDE')):
        collision.touch()
        # FAKE_NAME_OWNER=self: the name holds this session's own container.
        pathlib.Path(str(log) + '.collision-token').write_text(args[args.index('--label') + 1].split('=', 1)[1])
        sys.exit(125)
    if os.environ.get('FAKE_CREATE_FAILURE'):
        print('create failed', file=sys.stderr)
        sys.exit(125)
    token = args[args.index('--label') + 1].split('=', 1)[1]
    state.write_text(token)
    pathlib.Path(str(log) + '.budgets').write_text(requested_budgets(args))
    # The image follows --env CONTAINER_NAME=<name>; the image's entrypoint is the agent's.
    image = next(i for i, a in enumerate(args) if a.startswith('CONTAINER_NAME=') and args[i - 1] == '--env') + 1
    agent_command.write_text(json.dumps(created_command(args, image, [os.environ.get('FAKE_IMAGE_ENTRYPOINT',
                                                                                   'image-entrypoint')])))
    # The private hosts file a session joined to its engine binds, for start to report.
    hosts = [a.rsplit(':', 2)[0] for a in args if a.endswith(':/etc/hosts:ro')]
    pathlib.Path(str(log) + '.hosts-source').write_text(hosts[0] if hosts else '')
    pause = os.environ.get('FAKE_CREATE_PAUSE')
    if pause != 'before':
        # FAKE_CID_CONTENT replaces the private creation record (escapes allowed).
        cid = os.environ.get('FAKE_CID_CONTENT', 'a' * 64 + '\\n').encode().decode('unicode_escape')
        pathlib.Path(args[args.index('--cidfile') + 1]).write_text(cid)
    if pause:
        pathlib.Path(str(log) + '.create-pid').write_text(str(os.getpid()))
        pathlib.Path(str(log) + '.creating').touch()
        while True:
            time.sleep(0.05)
    print('a' * 64)
    sys.exit(int(os.environ.get('FAKE_CREATED_STATUS', '0')))
elif args[:2] == ['run', '--detach']:
    # The session container engine.
    engine_budgets.write_text(requested_budgets(args))
    image = next(i for i, a in enumerate(args)
                 if a.endswith('-engine:latest') or a == os.environ.get('FAKE_ENGINE_IMAGE', '-'))
    engine_command.write_text(json.dumps(created_command(args, image, ['/usr/local/bin/sandbox-engine-start'])))
    if os.environ.get('FAKE_ENGINE_STATUS'):
        print('engine failed to start', file=sys.stderr)
        sys.exit(int(os.environ['FAKE_ENGINE_STATUS']))
    print(ENGINE_ID)
elif args[0] == 'exec' and ENGINE_ID in args[1:4]:
    # Launcher commands in the engine run as its user, never as its startup root
    # (support-nested-systemd-containers, design D4).
    if args[1:4] != ['--user', 'podman', ENGINE_ID]:
        print('fake podman: a command in the engine must run as --user podman', file=sys.stderr)
        sys.exit(97)
    inner = args[4:]
    if inner == ['grep', '^Max processes ', '/proc/1/limits']:
        # The startup program's limits (PID 1): the process limit it was given after
        # the port, or the user's own (FAKE_ENGINE_LIMIT='soft hard', or 'missing').
        started = json.loads(engine_command.read_text()) if engine_command.exists() else []
        limit = os.environ.get('FAKE_ENGINE_LIMIT', ' '.join([started[2]] * 2 if len(started) > 2 else ['63948'] * 2))
        if limit == 'missing':
            sys.exit(1)
        print('Max processes             ' + '                 '.join(limit.split()) + '                processes')
    elif inner == ['/usr/local/bin/sandbox-engine-cgroup']:
        # The engine's cgroup delegation state (FAKE_ENGINE_CGROUP, or 'fail').
        state = os.environ.get('FAKE_ENGINE_CGROUP', 'delegated')
        if state == 'fail':
            sys.exit(1)
        print(state)
    else:
        print(os.environ.get('FAKE_ENGINE_READY', 'true'))
elif args[0] == 'inspect' and args[-1] == ENGINE_ID and ('{{.Path}}' in args or '{{index .Args' in args[-2]):
    report_command(engine_command, 'FAKE_ENGINE_COMMAND')
elif args[0] == 'inspect' and args[-1] == ENGINE_ID:
    print(os.environ.get('FAKE_ENGINE_BUDGETS', engine_budgets.read_text() if engine_budgets.exists() else ''))
elif args[0] == 'inspect' and args[-1] == 'a' * 64 and ('{{.Path}}' in args or '{{index .Args' in args[-2]):
    report_command(agent_command, 'FAKE_AGENT_COMMAND')
elif args[0] == 'inspect':
    if '{{.HostConfig.Memory}}' in args[-2]:
        # Report the created configuration unless a test overrides it.
        budgets = pathlib.Path(str(log) + '.budgets')
        if 'FAKE_AGENT_BUDGETS' in os.environ:
            print(os.environ['FAKE_AGENT_BUDGETS'])
        elif budgets.exists():
            print(budgets.read_text())
        sys.exit(0)
    if os.environ.get('FAKE_NETWORK') and args[-1] == 'b' * 64 and args[-2] == '{{json .HostConfig}}':
        print(os.environ.get('FAKE_PROXY_CONFIG', '{"PidsLimit":128,"Memory":268435456}'))
        sys.exit(0)
    if os.environ.get('FAKE_NETWORK') and args[-1] == 'b' * 64 and args[-2] == '[{{json .Path}},{{json .Args}}]':
        reported = json.loads(proxy_command.read_text()) if proxy_command.exists() else ['']
        print(json.dumps([reported[0], reported[1:]]))
        sys.exit(0)
    owner = pathlib.Path(str(log) + '.collision-token')
    if os.environ.get('FAKE_NAME_OWNER') == 'self' and owner.exists() and args[-1] != 'a' * 64:
        print(owner.read_text())
    else:
        print(state.read_text() if state.exists() and args[-1] == 'a' * 64 else 'foreign-session')
elif args[:2] == ['container', 'inspect'] and 'sandbox-engine.owner' in args[-2]:
    # The owner label of a FAKE_ENGINES engine; other identities are gone.
    owners = {fields[0]: ' '.join(fields[1:]) for fields in
              (line.split() for line in os.environ.get('FAKE_ENGINES', '').encode().decode('unicode_escape').splitlines())
              if fields}
    if args[-1] not in owners:
        print('Error: no such container ' + args[-1], file=sys.stderr)
        sys.exit(125)
    print(owners[args[-1]])
elif args[0] == 'exec' and os.environ.get('FAKE_NETWORK'):
    print(os.environ.get('FAKE_PROXY_EFFECTIVE', '{"pids":128,"memory":268435456,"capabilities":[0,0,0,0,0],"no_new_privs":1,"seccomp":2,"nproc":[63948,63948]}'))
elif args[:2] == ['container', 'exists']:
    sys.exit(0 if os.environ.get('FAKE_COLLISION') else 1)
elif args[0] == 'kill':
    pid = pathlib.Path(str(log) + '.pid')
    if pid.exists():
        os.kill(int(pid.read_text()), signal.SIGTERM)
elif args[0] == 'rm':
    if os.environ.get('FAKE_NETWORK') and args[-1] == 'b' * 64:
        sys.exit(0)
    stale = [line.split()[0] for line in os.environ.get('FAKE_ENGINES', '').encode().decode('unicode_escape').splitlines()
             if line.split()]
    if args[-1] == ENGINE_ID or args[-1] in stale:
        sys.exit(0)
    assert args[-1] == 'a' * 64, 'refusing to remove unrelated identity'
    state.unlink(missing_ok=True)
    pid = pathlib.Path(str(log) + '.pid')
    if pid.exists():
        try:
            os.kill(int(pid.read_text()), signal.SIGKILL)
        except ProcessLookupError:
            pass
elif args[0] == 'start':
    if os.environ.get('FAKE_NETWORK') and args[-1] == 'b' * 64:
        sys.exit(0)
    source = pathlib.Path(str(log) + '.hosts-source')
    if source.exists() and source.read_text():
        pathlib.Path(str(log) + '.hosts').write_text(pathlib.Path(source.read_text()).read_text())
    if os.environ.get('FAKE_START_STDERR'):
        sys.stderr.write(os.environ['FAKE_START_STDERR'])
        sys.stderr.flush()
    time.sleep(float(os.environ.get('FAKE_START_DELAY', '0')))
    if os.environ.get('FAKE_WAIT'):
        for name in ('TERM', 'INT', 'HUP'):
            signal.signal(getattr(signal, 'SIG' + name),
                          signal.SIG_IGN if os.environ.get('FAKE_IGNORE_SIGNALS') else signal.SIG_DFL)
        pathlib.Path(str(log) + '.pid').write_text(str(os.getpid()))
        pathlib.Path(str(log) + '.started').touch()
        time.sleep(20)
    if not os.environ.get('FAKE_NO_STDIN'):
        print('stdin:' + sys.stdin.read())
    sys.exit(int(os.environ.get('FAKE_EXIT', '0')))
else:
    print('fake podman: unsupported command: ' + ' '.join(args), file=sys.stderr)
    sys.exit(99)
