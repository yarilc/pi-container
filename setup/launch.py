"""Load trusted defaults, then replace this process with the installed wrapper."""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from common import PROFILE, SetupError, agent_profile, load, protect_mounts, runtime_environment, trusted
except ValueError as error:
    # Invalid profile: there is no trustworthy wrapper name to report.
    print('sandbox-egress: invalid managed installation (' + str(error) + '); rerun --container-setup.', file=sys.stderr)
    sys.exit(1)


def main():
    release = Path(__file__).resolve().parents[1]
    wrapper = release / PROFILE.wrapper
    args = sys.argv[1:]
    launcher = None
    if len(args) >= 2 and args[0] == '--managed-launcher':
        launcher, args = args[1], args[2:]
    if '--container-help' in args or '--container-setup' in args:
        os.execv('/bin/bash', ['bash', str(wrapper), *args])
    if not launcher:
        raise SetupError('The managed launcher needs an update; rerun --container-setup.')
    actual_launcher = trusted(Path(launcher).absolute())
    if not actual_launcher.is_file():
        raise SetupError('The invoked managed launcher must be a protected file.')
    value = load(release / 'setup.json')
    if release.parent != trusted(value['installation']) / 'releases':
        raise SetupError('Managed release does not belong to its declared installation.')
    trusted(wrapper)
    # The profile imported above must be the protected one of this release.
    for name in (agent_profile.PROFILE, agent_profile.POLICY, 'network/agent_profile.py'):
        trusted(release / name)
    env = runtime_environment(value, release)
    protect_mounts(value, env, args, launcher=launcher)
    if value['worktree'] and '--container-qualify' not in args:
        args = ['--container-git-worktree', *args]
    os.execve('/bin/bash', ['bash', str(wrapper), *args], env)


if __name__ == '__main__':
    try:
        main()
    except (SetupError, OSError, ValueError):
        print(PROFILE.message_prefix + 'invalid or unsafe managed configuration; rerun --container-setup or use a different workspace.', file=sys.stderr)
        sys.exit(1)
