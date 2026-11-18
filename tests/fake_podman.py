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
command = args[0]
if command in os.environ.get('FAKE_STALL', '').split(',') and (command != 'ps' or '--filter' in args):
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    pathlib.Path(str(log) + '.stalled-' + command).write_text(str(os.getpid()))
    while True:
        time.sleep(0.05)
if command in os.environ.get('FAKE_FAIL', '').split(','):
    print('synthetic control failure: ' + command, file=sys.stderr)
    sys.exit(17)
if args[:2] == ['--remote', '--url']:
    sys.stdout.write(os.environ.get('FAKE_SOCKET_RAW',
                     os.environ.get('FAKE_SOCKET_ROOTLESS', 'true') + ' ' +
                     os.environ.get('FAKE_HOST_SOCKET', '/host/podman.sock') + '\n'))
    sys.exit(int(os.environ.get('FAKE_SOCKET_STATUS', '0')))
elif args[0] == 'info':
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
    sys.stdout.write(os.environ.get('FAKE_INFO_RAW', os.environ.get('FAKE_INFO', 'true linux false') + '\n'))
    sys.exit(int(os.environ.get('FAKE_INFO_STATUS', '0')))
elif args[0] == 'version':
    print(os.environ.get('FAKE_SERVER_VERSION', '4.9.3'))
elif args[:2] == ['image', 'exists']:
    sys.exit(int(os.environ.get('FAKE_IMAGE_STATUS', '0')))
elif args[:2] == ['image', 'inspect']:
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
    if '--filter' in args:
        print(os.environ.get('FAKE_RECOVERY_ID', 'a' * 64) if state.exists() else '')
    else:
        print(os.environ.get('FAKE_NAMES', ''))
elif args[0] == 'create':
    if os.environ.get('FAKE_NETWORK') and any(a.startswith('io.') and '.egress=' in a for a in args):
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
    from decimal import Decimal
    flag = lambda name: next((a.split('=', 1)[1] for a in args if a.startswith(name + '=')), '0')
    pathlib.Path(str(log) + '.budgets').write_text(' '.join((flag('--memory'),
        str(int(Decimal(flag('--cpus')) * 10**9)), flag('--pids-limit'))))
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
    owner = pathlib.Path(str(log) + '.collision-token')
    if os.environ.get('FAKE_NAME_OWNER') == 'self' and owner.exists() and args[-1] != 'a' * 64:
        print(owner.read_text())
    else:
        print(state.read_text() if state.exists() and args[-1] == 'a' * 64 else 'foreign-session')
elif args[0] == 'exec' and os.environ.get('FAKE_NETWORK'):
    print(os.environ.get('FAKE_PROXY_EFFECTIVE', '{"pids":128,"memory":268435456,"capabilities":[0,0,0,0,0],"no_new_privs":1,"seccomp":2}'))
elif args[:2] == ['container', 'exists']:
    sys.exit(0 if os.environ.get('FAKE_COLLISION') else 1)
elif args[0] == 'kill':
    pid = pathlib.Path(str(log) + '.pid')
    if pid.exists():
        os.kill(int(pid.read_text()), signal.SIGTERM)
elif args[0] == 'rm':
    if os.environ.get('FAKE_NETWORK') and args[-1] == 'b' * 64:
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
