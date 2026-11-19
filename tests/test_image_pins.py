"""Credential-free checks that the runtime image inputs are pinned (B05).

Same parsing as the claude-container reference. Pi has no network policy yet, so there is no tested-CLI cross-check until the Wave 3 network port.
"""
from pathlib import Path
import json
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ('@earendil-works/pi-coding-agent', '@fission-ai/openspec')
TOOLSET = ('bash', 'bubblewrap', 'bzip2', 'ca-certificates', 'coreutils', 'curl', 'diffutils',
           'file', 'findutils', 'gawk', 'git', 'grep', 'jq', 'less', 'nano', 'patch', 'podman',
           'procps', 'python3', 'ripgrep', 'sed', 'tar', 'unzip', 'util-linux', 'xz-utils', 'zip')
VERSION = re.compile(r'\d+\.\d+\.\d+')


def pins(recipe):
    """Return (base reference, {ARG name: default}, installed package specifiers)."""
    lines = recipe.replace('\\\n', ' ').splitlines()
    bases = [line.split()[1] for line in lines if line.startswith('FROM ')]
    if len(bases) != 1:
        raise ValueError('expected exactly one FROM line')
    args = dict(re.findall(r'^ARG ([A-Z_]+)=(\S+)$', recipe, re.MULTILINE))
    installs = []
    for line in lines:
        if 'npm install' in line or 'npm i ' in line:
            for command in line.split('&&'):
                if 'npm install' not in command and 'npm i ' not in command:
                    continue
                # Ignore shell syntax before the npm command, such as an if clause.
                marker = 'npm install' if 'npm install' in command else 'npm i '
                command = command[command.index(marker):]
                for token in command.split():
                    token = token.strip('"\'')
                    if token.startswith('@') or (not token.startswith('-') and '/' not in token
                                                 and token not in ('npm', 'install', 'i')):
                        for name, value in args.items():
                            token = token.replace('${' + name + '}', value).replace('$' + name, value)
                        installs.append(token)
    return bases[0], args, installs


def violations(recipe):
    found = []
    base, _, installs = pins(recipe)
    if not re.fullmatch(r'[a-z0-9./:-]+@sha256:[a-f0-9]{64}', base):
        found.append('base image is not pinned by digest: ' + base)
    seen = {}
    for spec in installs:
        name, _, version = spec.rpartition('@')
        if not name:
            found.append('unpinned package: ' + spec)
            continue
        if not VERSION.fullmatch(version) and version != '${PI_VERSION}':
            found.append('package is not pinned to an exact version: ' + spec)
        seen[name] = version
        if name not in PACKAGES:
            found.append('unexpected package is installed: ' + spec)
    for package in PACKAGES:
        if package not in seen:
            found.append('required package is not installed with a pinned version: ' + package)
    if re.search(r'curl[^\n]*\|\s*(ba)?sh', recipe):
        found.append('remote install script is piped to a shell')
    apt = re.search(r'apt-get\b[^&]*?\binstall\b[^&]*', recipe.replace('\\\n', ' '))
    listed = set(apt[0].split()) if apt else set()
    for tool in TOOLSET:
        if tool not in listed:
            found.append('toolset package is missing: ' + tool)
    return found


def cli_mismatch(version, tested_cli):
    """The Pi version in .version must equal the policy's tested CLI version."""
    tested = re.match(r'(\d+\.\d+\.\d+)\b', tested_cli)
    if tested and tested[1] == version:
        return None
    return f'.version {version or "(none)"} differs from policy tested.cli {tested_cli!r}'


SOURCES = '/etc/apt/sources.list.d/debian.sources'
BOOTSTRAP_CA = '/tmp/apt-bootstrap-ca.pem'
INSECURE_APT = re.compile(r'Verify-(?:Peer|Host)\s*[= ]\s*"?(?:false|no|0)\b'
                          r'|AllowInsecureRepositories|--allow-insecure|--allow-unauthenticated'
                          r'|trusted=yes|\[trusted', re.IGNORECASE)


def transport_violations(recipe):
    """Return package-source transport violations (Debian over verified HTTPS only)."""
    text = recipe.replace('\\\n', ' ')
    found = []
    if re.search(r'http://deb\.debian\.org', text):
        found.append('plain-HTTP Debian source: http://deb.debian.org')
    for match in INSECURE_APT.finditer(text):
        found.append('apt TLS or signature verification disabled: ' + match[0])
    rewrite = re.search(r"sed -i '?s\|\^URIs: http://\|URIs: https://\|'? " + re.escape(SOURCES), text)
    update = re.search(r'apt-get\b[^&]*\bupdate\b', text)
    if not rewrite:
        found.append('Debian sources are not rewritten to HTTPS')
    elif update and update.start() < rewrite.start():
        found.append('Debian sources are rewritten to HTTPS only after apt-get update')
    # Bootstrap trust comes only from the pinned base's Node roots and is removed in the same step.
    bootstrap = re.search(r'rootCertificates[^&]*>\s*' + re.escape(BOOTSTRAP_CA), text)
    if not bootstrap or (rewrite and bootstrap.start() > rewrite.start()):
        found.append('bootstrap CA bundle is not exported from the base Node roots before the rewrite')
    for command in re.findall(r'apt-get\b[^&]*', text):
        if re.search(r'\b(update|install)\b', command) and 'Acquire::https::CAInfo=' + BOOTSTRAP_CA not in command:
            found.append('apt-get fetch without the bootstrap CA: ' + command.split(' -y')[0].strip())
    # The optional host CA arrives only as a build secret, never as a copied file.
    if not re.search(r'RUN --mount=type=secret,id=build-ca,required=false\b', text):
        found.append('optional build-ca secret mount is missing')
    for match in re.finditer(r'(?im)^(?:COPY|ADD)\b[^\n]*(?:\.pem|\.crt|ca-?bundle|certs?\b)', text):
        found.append('CA material copied into the image: ' + match[0])
    if 'build-ca' in text and not re.search(r'cat /run/secrets/build-ca >> ' + re.escape(BOOTSTRAP_CA), text):
        found.append('build-ca secret is not appended to the bootstrap CA bundle')
    steps = [line for line in text.splitlines() if BOOTSTRAP_CA in line]
    if not steps or len(steps) != 1 or 'rm -f ' + BOOTSTRAP_CA not in steps[0]:
        found.append('bootstrap CA bundle is not removed in the step that creates it')
    return found


def workdir_violations(recipe):
    """WORKDIR must name a directory created by an earlier build step, never by the engine at start."""
    text = recipe.replace('\\\n', ' ')
    found = []
    for match in re.finditer(r'(?m)^WORKDIR\s+(\S+)\s*$', text):
        path = match[1]
        before = text[:match.start()]
        created = any(re.search(r'\bmkdir\s+(?:-\S+\s+)*(?:\S+\s+)*' + re.escape(path) + r'(?=\s|$)', step)
                      for step in re.findall(r'(?m)^RUN\b.*$', before))
        if not created:
            found.append('WORKDIR is not created by a build step: ' + path)
    return found


class ImagePinTests(unittest.TestCase):
    def setUp(self):
        self.recipe = (ROOT / 'Containerfile').read_text()
        self.tested_cli = json.loads((ROOT / 'agent/policies/default.json').read_text())['tested']['cli']

    def test_shipped_recipe_is_pinned(self):
        self.assertEqual(violations(self.recipe), [])
        _, args, _ = pins(self.recipe)
        self.assertRegex((ROOT / '.version').read_text().strip(), VERSION)
        self.assertRegex(args['OPENSPEC_VERSION'], VERSION)

    def test_version_matches_policy_tested_cli(self):
        version = (ROOT / '.version').read_text().strip()
        self.assertEqual(cli_mismatch(version, self.tested_cli), None)
        message = cli_mismatch('1.5.3', self.tested_cli)
        self.assertIn('1.5.3', message)
        self.assertIn('1.5.2', message)

    def test_mutated_recipes_are_rejected(self):
        digest = re.search(r'@sha256:[a-f0-9]{64}', self.recipe)
        cases = {
            'tag-only base': self.recipe.replace(digest[0], '') if digest else self.recipe,
            'latest package': self.recipe.replace('"@fission-ai/openspec@${OPENSPEC_VERSION}"',
                                                  '@fission-ai/openspec@latest'),
            'unversioned package': self.recipe.replace('"@fission-ai/openspec@${OPENSPEC_VERSION}"',
                                                       '@fission-ai/openspec'),
            'version range': self.recipe.replace('ARG OPENSPEC_VERSION=2.0.0', 'ARG OPENSPEC_VERSION=^2.0.0'),
            'missing package': self.recipe.replace('"@fission-ai/openspec@${OPENSPEC_VERSION}" \\\n', ''),
            'remote installer': self.recipe.replace('RUN npm install --global --omit=dev \\\n',
                                                    'RUN curl -fsSL https://example.invalid/install.sh | bash \\\n'
                                                    '    && npm install --global --omit=dev \\\n'),
            'unexpected package': self.recipe.replace('"@fission-ai/openspec@${OPENSPEC_VERSION}" \\\n',
                                                      '"@fission-ai/openspec@${OPENSPEC_VERSION}" \\\n'
                                                      '        "bun@1.3.14" \\\n'),
            'missing toolset package': self.recipe.replace('        nano \\\n', ''),
        }
        for name, recipe in cases.items():
            with self.subTest(name=name):
                self.assertNotEqual(recipe, self.recipe)
                self.assertTrue(violations(recipe))

    def test_package_sources_use_verified_https(self):
        self.assertEqual(transport_violations(self.recipe), [])

    def test_insecure_transport_recipes_are_rejected(self):
        rewrite = "sed -i 's|^URIs: http://|URIs: https://|' " + SOURCES
        option = '-o Acquire::https::CAInfo=' + BOOTSTRAP_CA
        # Pi installs apt packages and npm packages in two RUN steps.
        cases = {
            'plain http restored': self.recipe.replace(rewrite, 'true'),
            'peer verification disabled': self.recipe.replace(option, option + ' -o Acquire::https::Verify-Peer=false', 1),
            'host verification disabled': self.recipe.replace(option, option + ' -o Acquire::https::Verify-Host=false', 1),
            'insecure repositories': self.recipe.replace(option, option + ' -o Acquire::AllowInsecureRepositories=true', 1),
            'rewrite after update': self.recipe.replace('    && ' + rewrite + ' \\\n', '').replace(
                '    && apt-get clean', '    && ' + rewrite + ' \\\n    && apt-get clean', 1),
            'literal http source': self.recipe.replace(rewrite, rewrite + ' && echo http://deb.debian.org/debian'),
            'fetch without bootstrap ca': self.recipe.replace(option + ' update', 'update', 1),
            'bootstrap ca kept': self.recipe.replace('    && rm -f ' + BOOTSTRAP_CA + ' \\\n', ''),
            'secret mount required': self.recipe.replace('id=build-ca,required=false', 'id=build-ca,required=true'),
            'secret not appended': self.recipe.replace('cat /run/secrets/build-ca >> ', 'true ', 1),
            'bundle copied': self.recipe.replace('ENTRYPOINT ["pi"]', 'COPY bundle.pem /etc/ssl/certs/host.pem\nENTRYPOINT ["pi"]'),
        }
        for name, recipe in cases.items():
            with self.subTest(name=name):
                self.assertNotEqual(recipe, self.recipe)
                self.assertTrue(transport_violations(recipe))

    def test_workdir_needs_no_engine_creation(self):
        # Pi declares no WORKDIR; a future one must be created by an earlier build step.
        self.assertEqual(workdir_violations(self.recipe), [])
        self.assertNotIn('WORKDIR', self.recipe)
        mutated = self.recipe.replace('ENTRYPOINT ["pi"]', 'WORKDIR /workspace\nENTRYPOINT ["pi"]')
        self.assertEqual(workdir_violations(mutated), ['WORKDIR is not created by a build step: /workspace'])
        created = self.recipe.replace('    && mkdir -m 1777 /pi-home', '    && mkdir -m 1777 /pi-home \\\n    && mkdir -p /workspace')
        self.assertNotEqual(created, self.recipe)
        self.assertEqual(workdir_violations(created.replace('ENTRYPOINT ["pi"]', 'WORKDIR /workspace\nENTRYPOINT ["pi"]')), [])



TOOLCHAIN_CA = '/tmp/apk-bootstrap-ca.pem'


def toolchain_violations(recipe):
    """The guard toolchain keeps exact pins and takes the host CA only as an optional build secret."""
    text = recipe.replace('\\\n', ' ')
    found = []
    if not re.search(r'(?m)^FROM docker\.io/library/alpine@sha256:[a-f0-9]{64}$', recipe):
        found.append('toolchain base is not pinned by digest')
    for package in re.findall(r'apk add --no-cache ([^&\n]+)', text):
        for spec in package.split():
            if not re.fullmatch(r'[a-z0-9-]+=[0-9][A-Za-z0-9._-]*', spec):
                found.append('toolchain package is not pinned: ' + spec)
    if not re.search(r'RUN --mount=type=secret,id=build-ca,required=false\b', text):
        found.append('optional build-ca secret mount is missing')
    if not re.search(r'SSL_CERT_FILE=' + re.escape(TOOLCHAIN_CA) + r' apk add\b', text):
        found.append('apk does not verify against the bootstrap bundle')
    if 'rm -f ' + TOOLCHAIN_CA not in text or len([l for l in text.splitlines() if TOOLCHAIN_CA in l]) != 1:
        found.append('toolchain bootstrap bundle is not removed in the step that creates it')
    if INSECURE_APT.search(text) or re.search(r'--allow-untrusted|--no-check-certificate|http://', text):
        found.append('toolchain fetch verification weakened')
    if re.search(r'(?im)^(?:COPY|ADD)\b', recipe):
        found.append('toolchain recipe copies host files')
    return found


class ToolchainRecipeTests(unittest.TestCase):
    def test_toolchain_recipe_is_pinned_and_takes_ca_only_as_secret(self):
        recipe = (ROOT / 'network/guard-build.Containerfile').read_text()
        self.assertEqual(toolchain_violations(recipe), [])
        cases = {
            'unpinned package': recipe.replace('gcc=13.2.1_git20240309-r1', 'gcc'),
            'required secret': recipe.replace('required=false', 'required=true'),
            'bundle kept': recipe.replace('    && rm -f ' + TOOLCHAIN_CA, '    && true'),
            'no bootstrap trust': recipe.replace('SSL_CERT_FILE=' + TOOLCHAIN_CA + ' ', ''),
            'untrusted packages': recipe.replace('apk add --no-cache', 'apk add --allow-untrusted --no-cache'),
            'copied bundle': recipe.replace('ENV LC_ALL', 'COPY bundle.pem /etc/ssl/certs/host.pem\nENV LC_ALL'),
        }
        for name, mutated in cases.items():
            with self.subTest(name=name):
                self.assertNotEqual(mutated, recipe)
                self.assertTrue(toolchain_violations(mutated))
        ignore = (ROOT / 'network/.containerignore').read_text().splitlines()
        self.assertIn('!podman-build-secret*', ignore)


if __name__ == '__main__':
    unittest.main()
