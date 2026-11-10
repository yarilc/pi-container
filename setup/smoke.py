"""Credential-free checks executed only through the installed sandbox wrapper."""
import os
from pathlib import Path
import socket
import subprocess
import sys


def hardening(memory, nano_cpus, pids):
    # Every mode: no capabilities or privilege gains, and the selected budgets
    # are effective in this container's own (private) cgroup v2 namespace.
    status = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines())
    for name in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb'):
        assert int(status[name], 16) == 0, 'agent capabilities are not dropped'
    assert int(status['NoNewPrivs']) == 1, 'no-new-privileges is not set'
    assert Path('/proc/self/cgroup').read_text() == '0::/\n', 'unsupported cgroup namespace'
    root = Path('/sys/fs/cgroup')
    assert int((root / 'memory.max').read_text()) == memory, 'memory budget is not effective'
    assert int((root / 'pids.max').read_text()) == pids, 'process budget is not effective'
    quota, period = (root / 'cpu.max').read_text().split()
    assert quota != 'max' and int(quota) * 10**9 == nano_cpus * int(period), 'CPU budget is not effective'


def main(mode, trust_ca, home, config_env, command, memory, nano_cpus, pids):
    # Agent values are supplied by host setup from the protected profile.
    assert os.environ['HOME'] == home
    hardening(memory, nano_cpus, pids)
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
    main(sys.argv[1], sys.argv[2] == '1', *sys.argv[3:6], *map(int, sys.argv[6:9]))
