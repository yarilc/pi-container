## MODIFIED Requirements

### Requirement: Runtime image inputs are pinned

The recipe SHALL install the exact Pi version recorded in `.version` and an exact `@fission-ai/openspec` version, both recorded in the repository and installed from the npm registry. It SHALL reference the base image by digest. No floating tag, `latest` specifier, version range or remote install script SHALL select an image input. Sessions SHALL NOT change installed versions.

#### Scenario: Build uses recorded versions

- **WHEN** the image is built with `--container-build`
- **THEN** `pi --version` and `openspec --version` report exactly the recorded versions
- **AND** `bun` is not installed

#### Scenario: Unpinned input is rejected by tests

- **WHEN** the recipe uses a base without digest, an npm package without exact version or with `@latest`, a remote install script piped to a shell, or misses a toolset package
- **THEN** the credential-free unit suite fails

### Requirement: Version updates follow explicit maintenance

Documentation SHALL describe the update procedure:

- record the new Pi version in `.version`, or the new OpenSpec version or base digest in the recipe;
- rebuild explicitly with `--container-build`;
- rerun the credential-free and real-engine checks;
- record the tested versions with the date in the validation record.

#### Scenario: Maintainer updates Pi

- **WHEN** a maintainer follows the documented procedure to move to a new Pi release
- **THEN** the procedure requires the recorded version, an explicit rebuild, a rerun of the checks and a dated validation entry
