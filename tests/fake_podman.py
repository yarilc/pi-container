#!/usr/bin/env python3
import hashlib, json, os, pathlib, signal, sys, time
args = sys.argv[1:]
with open(os.environ['FAKE_LOG'], 'a') as log:
    log.write(json.dumps(args) + '\n')
if args[0] == 'info':
    sys.stdout.write(os.environ['FAKE_INFO_RAW']) if 'FAKE_INFO_RAW' in os.environ else print(os.environ.get('FAKE_INFO', 'true linux false'))
    sys.exit(int(os.environ.get('FAKE_INFO_STATUS', '0')))
elif args[:2] == ['--remote', '--url']:
    sys.stdout.write(os.environ['FAKE_SOCKET_INFO_RAW']) if 'FAKE_SOCKET_INFO_RAW' in os.environ else print(os.environ.get('FAKE_SOCKET_INFO', 'true\n/host/podman.sock'))
    sys.exit(int(os.environ.get('FAKE_SOCKET_STATUS', '0')))
elif args[0] == 'ps':
    print(os.environ.get('FAKE_NAMES', ''))
    sys.exit(int(os.environ.get('FAKE_LIST_STATUS', '0')))
elif args[:2] == ['image', 'exists']:
    sys.exit(int(os.environ.get('FAKE_IMAGE_STATUS', '0')))
elif args[:2] == ['image', 'inspect']:
    root = pathlib.Path(os.environ['FAKE_ROOT'])
    inputs = b''.join((root / name).read_bytes() for name in ('Containerfile', '.containerignore', '.version'))
    inputs += ('INSTALL_PODMAN=' + ('1' if os.environ.get('PI_ENABLE_PODMAN') == '1' else '0') + '\n').encode()
    inputs += ('INSTALL_BUN=' + ('1' if os.environ.get('PI_ENABLE_BUN') else '0') + '\n').encode()
    inputs += ('BUN_VERSION=' + os.environ.get('PI_BUN_VERSION', 'bun-v1.3.14') + '\n').encode()
    print(os.environ.get('FAKE_LABEL_HASH', hashlib.sha256(inputs).hexdigest()))
    sys.exit(int(os.environ.get('FAKE_INSPECT_STATUS', '0')))
elif args[0] == 'build':
    if os.environ.get('FAKE_BUILD_READ_INPUT'):
        pathlib.Path(os.environ['FAKE_LOG'] + '.build-stdin').write_text(sys.stdin.read())
    sys.exit(int(os.environ.get('FAKE_BUILD_STATUS', '0')))
elif args[:2] == ['container', 'exists']:
    sys.exit(int(os.environ.get('FAKE_EXISTS_STATUS', '0')))
elif args[0] == 'create':
    calls = [json.loads(line) for line in pathlib.Path(os.environ['FAKE_LOG']).read_text().splitlines()]
    attempt = sum(c[0] == 'create' for c in calls)
    if attempt <= int(os.environ.get('FAKE_COLLISIONS', '0')):
        print('synthetic collision', file=sys.stderr)
        sys.exit(125)
    status = int(os.environ.get('FAKE_CREATE_STATUS', '0'))
    if status and not os.environ.get('FAKE_FAIL_WITH_CID'):
        print('synthetic create failure', file=sys.stderr)
        sys.exit(status)
    cid = 'a' * 64
    cidfile = pathlib.Path(args[args.index('--cidfile') + 1])
    mode = os.environ.get('FAKE_CREATE_MODE', '')
    def publish():
        cidfile.write_text(cid + '\0\n' if os.environ.get('FAKE_CID_NUL')
                           else os.environ.get('FAKE_CID_RAW', cid + '\n'))
    if mode == 'cid-on-term':
        def on_term(signum, frame):
            publish()
            sys.exit(42)
        signal.signal(signal.SIGTERM, on_term)
    elif os.environ.get('FAKE_CLIENT_IGNORE_TERM'):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    if mode not in ('stall', 'cid-on-term'):
        publish()
    if os.environ.get('FAKE_CREATE_BARRIER'):
        barrier = pathlib.Path(os.environ['FAKE_CREATE_BARRIER'])
        barrier.with_suffix('.pid').write_text(str(os.getpid()))
        barrier.with_suffix('.ready').touch()
        if mode:
            while True: time.sleep(0.01)
        while not barrier.with_suffix('.release').exists(): time.sleep(0.01)
    print(cid)
    sys.exit(status)
elif args[0] in ('kill', 'rm'):
    if os.environ.get('FAKE_CONTROL_STALL') == args[0]:
        if os.environ.get('FAKE_CONTROL_IGNORE_TERM'):
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
        while True: time.sleep(0.01)
    status = int(os.environ.get('FAKE_' + args[0].upper() + '_STATUS', '0'))
    if not status and os.environ.get('FAKE_SESSION'):
        if args[0] == 'rm' or not os.environ.get('FAKE_IGNORE_SIGNAL'):
            pathlib.Path(os.environ['FAKE_SESSION'] + '.done').touch()
    sys.exit(status)
elif args[0] in ('run', 'start'):
    if os.environ.get('FAKE_CLIENT_IGNORE_TERM'):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    print('mask:' + oct(os.umask(0)))
    pathlib.Path(os.environ['FAKE_LOG'] + '.env').write_text(json.dumps(dict(os.environ)))
    if os.environ.get('FAKE_ECHO_INPUT'):
        sys.stdout.write(sys.stdin.read())
    if os.environ.get('FAKE_SESSION'):
        session = pathlib.Path(os.environ['FAKE_SESSION'])
        session.with_suffix('.ready').touch()
        while not session.with_suffix('.done').exists(): time.sleep(0.01)
    sys.exit(int(os.environ.get('FAKE_EXIT', '0')))
else:
    print('UNEXPECTED podman command: ' + repr(args), file=sys.stderr)
    sys.exit(99)
