"""Credential-free checks executed only through the installed sandbox wrapper."""
import os
from pathlib import Path
import socket
import subprocess
import sys


def hardening(memory, nano_cpus, pids, enforced=('cpu', 'memory', 'pids'), root=Path('/sys/fs/cgroup')):
    # Every mode: no capabilities or privilege gains, and the enforced budgets
    # are effective in this container's own (private) cgroup v2 namespace; a
    # budget whose controller the engine does not delegate must be absent.
    status = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines())
    for name in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb'):
        assert int(status[name], 16) == 0, 'agent capabilities are not dropped'
    assert int(status['NoNewPrivs']) == 1, 'no-new-privileges is not set'
    assert Path('/proc/self/cgroup').read_text() == '0::/\n', 'unsupported cgroup namespace'
    budgets(memory, nano_cpus, pids, enforced, root)


def budgets(memory, nano_cpus, pids, enforced, root):
    def limit(name):
        path = root / name
        return path.read_text().split() if path.exists() else None
    for name, label, expected in (('memory', 'memory', memory), ('pids', 'process', pids)):
        value = limit(name + '.max')
        if name in enforced:
            assert value and value[0] != 'max' and int(value[0]) == expected, label + ' budget is not effective'
        else:
            assert value in (None, ['max']), 'unenforced ' + label + ' budget is present'
            print('agent ' + label + ' budget not enforced: cgroup controller ' + name +
                  ' is not delegated to the rootless engine', file=sys.stderr)
    cpu = limit('cpu.max')
    if 'cpu' in enforced:
        assert cpu and len(cpu) == 2 and cpu[0] != 'max' and \
            int(cpu[0]) * 10**9 == nano_cpus * int(cpu[1]), 'CPU budget is not effective'
    else:
        assert cpu is None or cpu[0] == 'max', 'unenforced CPU budget is present'
        print('agent CPU budget not enforced: cgroup controller cpu is not delegated to the rootless engine',
              file=sys.stderr)


def main(mode, trust_ca, home, config_env, command, memory, nano_cpus, pids, enforced):
    # Agent values are supplied by host setup from the protected profile.
    assert os.environ['HOME'] == home
    hardening(memory, nano_cpus, pids, enforced)
    assert os.access(os.environ[config_env], os.W_OK)
    subprocess.run([command, '--version'], check=True, stdout=subprocess.DEVNULL, timeout=15)
    for name in ('SSL_CERT_FILE', 'REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE', 'NODE_EXTRA_CA_CERTS'):
        if trust_ca:
            assert os.environ[name] == home + '/ca/bundle.pem'
            assert os.path.isfile(os.environ[name]) and not os.access(os.environ[name], os.W_OK)
        else:
            assert name not in os.environ
    if mode != 'unrestricted':
        assert os.listdir('/sys/class/net') == ['lo']
        try:
            test = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        except PermissionError:
            pass
        else:
            test.close()
            raise RuntimeError('Unix socket creation escaped the enforced guard')
        try:
            test = socket.create_connection(('1.1.1.1', 443), timeout=1)
        except OSError:
            pass
        else:
            test.close()
            raise RuntimeError('direct outbound connection escaped the restricted network')
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen(1)
        left, right = socket.socketpair()
        left.close()
        right.close()
    if mode == 'provider':
        assert os.environ['HTTPS_PROXY'] == 'http://127.0.0.1:18080'
        with socket.create_connection(('127.0.0.1', 18080), timeout=5) as proxy:
            proxy.settimeout(5)
            proxy.sendall(b'CONNECT setup-denied.invalid:443 HTTP/1.1\r\nHost: setup-denied.invalid:443\r\n\r\n')
            response = proxy.recv(1024)
            assert response.startswith(b'HTTP/1.1 502'), 'proxy deny-path check failed'
    print('SANDBOX_SETUP_SMOKE_OK')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2] == '1', *sys.argv[3:6], *map(int, sys.argv[6:9]),
         tuple(name for name in sys.argv[9].split(',') if name))
