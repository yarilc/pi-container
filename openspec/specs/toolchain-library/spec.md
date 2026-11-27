# toolchain-library Specification

## Purpose

Let the operator supply extra file toolchains and pinned container images to agent sessions from a host library shared by all wrappers, read-only and without host Podman delegation, network changes or session restarts (running image toolchains through the private session container engine).

## Requirements

### Requirement: Shared operator-managed library

The toolchain library SHALL be one host directory shared by all wrappers, `${XDG_DATA_HOME:-$HOME/.local/share}/sandbox-toolchains` unless `PI_CONTAINER_TOOLCHAINS_DIR` names another absolute path. It SHALL be caller-owned and private (`0700`), and SHALL NOT be, contain or lie inside the workspace, a state directory or the installation. Only the operator's `--container-toolchain` command SHALL change it.

#### Scenario: Default location

- **WHEN** neither `XDG_DATA_HOME` nor `PI_CONTAINER_TOOLCHAINS_DIR` is set
- **THEN** the library is `$HOME/.local/share/sandbox-toolchains` for every wrapper

#### Scenario: Unsafe library rejected

- **WHEN** the library is group- or world-accessible, owned by another user, or overlaps the workspace, a state directory or the installation
- **THEN** the session launch fails before any container or image operation, naming the library path
- **AND** the toolchain command fails the same way for an unsafe mode or owner, or an overlap with the installation or a state directory

### Requirement: Relocatable toolchains from pinned sources

A toolchain SHALL be described by a recipe with a name, a version, file sources, images, relative `PATH` entries, environment variables, required toolchains, notes for the agent, a check command and a default flag, and SHALL have at least one file source or one image. Each source SHALL be a subpath of an OCI image referenced by `@sha256:` digest, an HTTPS archive URL with its SHA-256, or a local archive file with its SHA-256. Sources SHALL be extracted in order into one toolchain root, each optionally limited to one subtree and placed at a relative directory of the root. An environment value SHALL be a path relative to the toolchain root or a literal. Names SHALL match `[a-z0-9][a-z0-9._-]{0,63}`. Recipes with the previous single-source schema SHALL remain valid.

#### Scenario: Image source without digest

- **WHEN** a recipe names an image by tag only
- **THEN** `add` fails without pulling or changing the library

#### Scenario: Archive checksum mismatch

- **WHEN** the SHA-256 of a downloaded or local archive differs from the recipe
- **THEN** `add` fails before extracting it, and the library is unchanged

#### Scenario: Unsafe archive content

- **WHEN** the source contains absolute paths, parent traversal, device nodes or links that resolve outside the toolchain root
- **THEN** `add` fails and the library is unchanged

#### Scenario: Literal environment value

- **WHEN** a recipe sets `GOCACHE` to the literal `/tmp/go-build` and `JAVA_HOME` to the toolchain root
- **THEN** `env.sh` exports `/tmp/go-build` and `/toolchains/<name>` respectively
- **AND** a value containing a newline or a NUL character is rejected

#### Scenario: Extracted permissions

- **WHEN** a toolchain is installed
- **THEN** its files belong to the caller, keep their executable bits, and have no setuid or setgid bit

#### Scenario: Several sources in one toolchain

- **WHEN** a recipe lists the compiler, package manager and standard library archives of one Rust release, each limited to its component subtree
- **THEN** `add` extracts them into one toolchain root and runs the check on the merged tree

#### Scenario: Two sources provide the same file

- **WHEN** two sources of one recipe would both create the same file in the toolchain root
- **THEN** `add` fails naming the file, and the library is unchanged

#### Scenario: Previous single-source recipe

- **WHEN** an operator adds a recipe written for the previous schema, with one `source` object and a local archive path
- **THEN** `add` installs it as before

#### Scenario: Image-only recipe

- **WHEN** an operator adds a recipe with one digest-pinned image and no file sources
- **THEN** `add` installs it as a toolchain without a toolchain root, `PATH` entries or environment

### Requirement: Toolchain command on the host

`--container-toolchain` SHALL be used alone with `add <recipe-or-name>`, `list`, `remove <name>` or `verify [<name>]`. It SHALL run on the host without starting a session. `add` SHALL pull a missing digest-pinned image and download archive URLs without any maintenance setting, SHALL copy a recipe's local images from the host engine, SHALL print each image and URL it fetches or copies, and SHALL never build an image. Changes SHALL be serialized by a library lock and applied atomically, so that a reader sees either the previous or the new toolchain and index, never a partial one.

#### Scenario: Pull without maintenance

- **WHEN** `add` needs to pull a digest-pinned image and `PI_CONTAINER_MAINTENANCE` is unset
- **THEN** the command pulls the image, names it in its output, and installs the toolchain

#### Scenario: Fetch failure

- **WHEN** a pull or a download fails
- **THEN** `add` fails naming the image or URL, and the library is unchanged

#### Scenario: Concurrent changes

- **WHEN** two `--container-toolchain` commands change the library at the same time
- **THEN** they run one after the other and the index lists the result of both

#### Scenario: Replace and remove

- **WHEN** `add` installs a name that already exists, or `remove` deletes one
- **THEN** the old directory is replaced or removed only after the new state is complete, and the index is regenerated

#### Scenario: Required toolchains

- **WHEN** a recipe requires a toolchain that is not installed, or `remove` targets a toolchain that another one requires
- **THEN** the command fails naming the missing or dependent toolchain, and the library is unchanged

#### Scenario: Recipe image pulled into the store

- **WHEN** `add` installs a recipe that lists a digest-pinned image
- **THEN** the command pulls it into the library's image store without any maintenance setting, and names it in its output

### Requirement: Verified against the runtime image

Before accepting a toolchain, `add` SHALL run the recipe's check command with the toolchain's `env.sh` in the wrapper's runtime image, without network, with the session's identity and hardening, and with the working directory set to `/`, and SHALL fail if it fails. The manifest SHALL record the digest-pinned base image named by the installed `Containerfile`. For a recipe with images, the check SHALL run the same way with `CONTAINER_HOST` naming a temporary engine configured like a session's, without network, whose image store includes the new images. `verify` SHALL rerun the check and update that record.

#### Scenario: Incompatible toolchain

- **WHEN** the check command fails in the runtime image, for example because the toolchain needs a newer C library
- **THEN** `add` fails, shows the command output, and the library is unchanged

#### Scenario: Verified base recorded

- **WHEN** `add` succeeds
- **THEN** the manifest names the base image digest from the installed `Containerfile` and the verification date

#### Scenario: Check on a host with a domain UID

- **WHEN** `add` or `verify` runs as a caller whose UID cannot be used for an engine-side chown under `--userns=keep-id`, with a runtime image whose `WORKDIR` is missing from its layers
- **THEN** the check container starts in `/`, and the engine creates no working directory

#### Scenario: Image check without network

- **WHEN** `add` installs a recipe whose check command runs its image by digest through `podman run`
- **THEN** the check runs in the runtime image against a temporary engine without network, and `add` fails, leaving the library unchanged, if the image cannot run offline

### Requirement: Self-describing library for the agent

The library SHALL contain a generated `toolchains.md` and `index.json`, and each toolchain SHALL contain a manifest and an `env.sh`. `toolchains.md` SHALL state the usage rules: the toolchains are read-only, the agent must not install toolchains or system packages, and it should ask the operator for missing ones. It SHALL list each toolchain with its version, commands, environment, required toolchains, notes, `env.sh` usage and verified base, and each image with its exact reference and the command form that runs it through the session engine.

#### Scenario: One instruction is enough

- **WHEN** an agent is told only to read `/toolchains/toolchains.md`
- **THEN** that file gives it the installed toolchains and the exact command form `. /toolchains/<name>/env.sh && <command>`

#### Scenario: env.sh sets the toolchain environment

- **WHEN** a session runs `. /toolchains/<name>/env.sh`
- **THEN** that shell has the environment of each required toolchain, then the toolchain's own `PATH` entries first and its environment variables set

#### Scenario: Notes reach the agent

- **WHEN** a recipe has notes, such as setting `GOTMPDIR` under the workspace for `go test`
- **THEN** `toolchains.md` shows them in that toolchain's entry

#### Scenario: Images listed for the agent

- **WHEN** the library holds a toolchain with images
- **THEN** `toolchains.md` lists each image's pinned reference with an example `podman run` command, and states that images are available only in sessions with an engine

### Requirement: Read-only session mount with live updates

Every session SHALL mount the library at `/toolchains` read-only with `nosuid` and `nodev`, unless `PI_CONTAINER_TOOLCHAINS=0` is set. The launcher SHALL create the library privately when it is missing. A toolchain added or removed on the host SHALL become visible to running sessions without a restart. The mount SHALL add no network, IPC or socket access.

#### Scenario: Toolchain added during a session

- **WHEN** the operator adds a toolchain while a provider-mode session is running
- **THEN** the session can run its check command through `env.sh` without a restart, under the same network restrictions

#### Scenario: Library is read-only for the agent

- **WHEN** a process in the session tries to create, change or remove a file under `/toolchains`
- **THEN** the operation fails

#### Scenario: Mount disabled

- **WHEN** `PI_CONTAINER_TOOLCHAINS=0` is set
- **THEN** the session has no `/toolchains` mount and no toolchain environment

### Requirement: Default toolchain environment for new sessions

A new session SHALL receive, appended after the runtime image's `PATH`, the `PATH` entries of every default toolchain whose verified base matches the installed `Containerfile`, and its environment variables. Default entries SHALL NOT shadow commands of the runtime image. A toolchain verified on another base SHALL get no default environment, and the launcher SHALL print one warning naming it and `verify`.

#### Scenario: Default toolchain on PATH

- **WHEN** a default toolchain verified for the current base is installed and a session starts
- **THEN** its commands run by name and its environment variables are set

#### Scenario: Default toolchain does not replace the agent's runtime

- **WHEN** a default Node.js or Python toolchain is installed and a session starts
- **THEN** `node` and `python3` still resolve to the runtime image's versions, and the toolchain's versions are used through `env.sh` or by their full path

#### Scenario: Base changed since verification

- **WHEN** the installed `Containerfile` names a base different from a toolchain's verified base
- **THEN** that toolchain stays visible under `/toolchains` but gets no default environment, and the launcher warns once naming it and `verify`

### Requirement: Default toolchains do not conflict

`add` SHALL reject a default toolchain whose commands or environment variable names overlap with another default toolchain. A non-default toolchain SHALL be usable only through its `env.sh` or full paths.

#### Scenario: Conflicting defaults

- **WHEN** `add` installs a second default toolchain that also provides `java` or sets `JAVA_HOME`
- **THEN** it fails and names the conflicting toolchain; the recipe can set `default: false` and the toolchain is then used through `env.sh`

### Requirement: Untested security modules are documented

Documentation SHALL state that the toolchain library was not tested with SELinux or AppArmor enforcement, and that tools must be profiled by the operator on such hosts.

#### Scenario: Operator reads the toolchain documentation

- **WHEN** an operator reads the README toolchain section
- **THEN** it states that SELinux and AppArmor enforcement are untested for the library mount

### Requirement: Session variables are protected from toolchains
A toolchain SHALL NOT set a variable that the session or a wrapper owns. Profile variables are the running wrapper's prefix, configuration, approval-bypass and credential variables, and the agent variables its profile declares; every other protected variable is neutral and the same in every wrapper. `add` SHALL reject both. `launch-env` SHALL fail on a neutral variable in the index, and SHALL leave a profile variable out of the session with one warning naming the toolchain and the variable.

#### Scenario: Other session variables stay protected
- **WHEN** a recipe sets `HOME`, `PATH`, an `LD_` variable, a proxy or CA variable, the profile's configuration variable, or a variable with the wrapper's or the `SANDBOX_` prefix
- **THEN** `add` fails naming the variable as protected

#### Scenario: Agent variable in a recipe
- **WHEN** a recipe sets a variable that the profile declares as an agent variable, or one that starts with a declared agent prefix, for example `PI_OFFLINE` or `ANTHROPIC_BASE_URL` in Pi
- **THEN** `add` fails naming the variable as protected, and the library is unchanged

#### Scenario: XDG variable in a recipe
- **WHEN** a recipe sets `XDG_DATA_HOME`, `XDG_CONFIG_HOME`, `XDG_CACHE_HOME`, `XDG_STATE_HOME`, `XDG_RUNTIME_DIR` or another `XDG_` variable
- **THEN** `add` fails naming the variable as protected, and the library is unchanged

#### Scenario: Bus variable in a recipe
- **WHEN** a recipe sets `DBUS_SESSION_BUS_ADDRESS`
- **THEN** `add` fails naming the variable as protected in every wrapper, and the library is unchanged

#### Scenario: XDG variable in an existing index
- **WHEN** the library index lists a default toolchain with an `XDG_` variable
- **THEN** `launch-env` fails with an invalid-environment error, and the session does not start with that variable

#### Scenario: Another wrapper's variable in the shared index
- **WHEN** the shared index lists a default toolchain that sets a variable protected only by the current wrapper's profile, for example its credential or an agent variable, because another wrapper installed it
- **THEN** `launch-env` succeeds without that variable, still emits the toolchain's `PATH` entries and other variables, and prints one warning naming the toolchain and the variable

#### Scenario: Wrapper state location kept
- **WHEN** a wrapper places its state with XDG variables, and default toolchains are installed
- **THEN** new sessions keep the wrapper's XDG values

### Requirement: Pi session settings win over toolchain variables

The Pi launcher SHALL pass the default toolchain environment before its own session variables, so that the variables it sets itself keep their values even when a toolchain names them outside the protected set. In restricted sessions these include `PI_OFFLINE`, `PI_SKIP_VERSION_CHECK` and `PI_TELEMETRY`.

#### Scenario: Toolchain sets a Pi setting

- **WHEN** a default toolchain's index entry sets `PI_TELEMETRY=1` and a restricted session starts
- **THEN** the session still has `PI_TELEMETRY=0`, `PI_OFFLINE=1` and `PI_SKIP_VERSION_CHECK=1`

### Requirement: Agent variables are declared in the profile
The agent profile SHALL be able to declare the variables and variable prefixes that the agent reads, as an optional list. The profile loader SHALL reject an entry that is not a valid variable name or prefix, a duplicate, or an entry that names a neutral protected variable. A profile without the list SHALL keep the previous protection.

#### Scenario: Valid declaration
- **WHEN** a profile declares `PI_` and `GOOGLE_API_KEY`
- **THEN** the profile loads, and both are profile variables for the toolchain library

#### Scenario: Invalid declaration
- **WHEN** a profile declares an entry with a lowercase name, a space, a duplicate, or `PATH`
- **THEN** the profile loader fails naming the field

### Requirement: Archive downloads by the toolchain command

`add` SHALL download an archive source named by URL itself, only over HTTPS with certificate verification, following redirects only to HTTPS URLs. It SHALL trust the host CA bundle saved by setup when host CA trust is enabled, and the system trust otherwise. It SHALL verify the SHA-256 before extracting anything and SHALL keep no downloaded file after the command ends.

#### Scenario: Catalog recipe with archive URLs

- **WHEN** the operator adds a recipe whose sources are HTTPS archive URLs, without any local file or environment variable
- **THEN** `add` downloads and verifies the archives, installs the toolchain, and leaves no downloaded file behind

#### Scenario: Plain HTTP URL

- **WHEN** a recipe names an `http://` archive URL
- **THEN** `add` fails before any download, and the library is unchanged

#### Scenario: Redirect to plain HTTP

- **WHEN** the HTTPS server redirects the download to an `http://` URL
- **THEN** `add` fails without following it, and the library is unchanged

#### Scenario: Network that re-signs TLS

- **WHEN** setup saved a host CA bundle and the network re-signs TLS with that CA
- **THEN** the download verifies the server certificate against that bundle and succeeds

### Requirement: Release catalog of reviewed recipes

The protected release SHALL contain a catalog of reviewed recipes, shared by every wrapper. `add <name>`, with an argument that contains no `/` and does not end in `.json`, SHALL install the catalog recipe of that name; any other argument SHALL be read as a recipe file. Catalog recipes SHALL use only digest-pinned images and HTTPS archive URLs with SHA-256. `list` SHALL show the catalog recipes that are not installed.

#### Scenario: Toolchain by name

- **WHEN** the operator runs `--container-toolchain add java21`
- **THEN** the release's `java21` recipe is installed, with no recipe file and no environment variable

#### Scenario: Unknown name

- **WHEN** the operator runs `--container-toolchain add jav21`
- **THEN** the command fails naming the available catalog recipes, without fetching anything

#### Scenario: Installed copy without the checkout

- **WHEN** the Windows checkout was deleted after `--container-install` and the operator runs `pi-container --container-toolchain add go`
- **THEN** the catalog recipe from the installation in the machine is installed

#### Scenario: Available recipes listed

- **WHEN** the operator runs `--container-toolchain list` with only `java21` installed
- **THEN** the output lists `java21` as installed and the other catalog recipes as available

### Requirement: Operator recipes outside writable mounts

`add` SHALL refuse a recipe file inside a writable mount that a session started from the current directory would have: the workspace, widened to its parent by the saved worktree scope, and the state directories. The refusal SHALL name the recipe and happen before any fetch. Catalog recipes and local archive files SHALL NOT be subject to this check, because the release protects the former and the recipe pins the latter.

#### Scenario: Recipe written in the workspace

- **WHEN** the operator runs `--container-toolchain add tools/java.json` from a project directory that contains that file
- **THEN** `add` fails naming the recipe as inside the workspace, fetches nothing, and the library is unchanged

#### Scenario: Recipe kept by the operator

- **WHEN** the recipe is in `~/recipes` and the operator runs `add ~/recipes/java.json` from a project directory
- **THEN** `add` proceeds

#### Scenario: Saved worktree scope

- **WHEN** setup saved the worktree scope and the recipe is in a sibling of the current project
- **THEN** `add` refuses it, because sessions started from the project mount the parent

#### Scenario: Local archive in the workspace

- **WHEN** a recipe kept outside the workspace names a local archive inside it
- **THEN** `add` accepts the archive if its SHA-256 matches the recipe

### Requirement: Image entries in recipes

Each image a recipe lists SHALL be an OCI reference pinned by `@sha256:` digest, or a local image named by its full image ID. The image ID SHALL be a `sha256:` value of 64 hexadecimal digits, together with the name the image gets in the store. A recipe without file sources SHALL declare no `PATH` entries, environment variables or default flag.

#### Scenario: Image named by tag only

- **WHEN** a recipe lists `docker.io/library/postgres:16` without a digest
- **THEN** `add` fails without pulling, and the library is unchanged

#### Scenario: Local image by ID

- **WHEN** a recipe lists a local image by its full image ID and a `localhost/` name
- **THEN** `add` copies that exact image from the host engine into the store under that name

#### Scenario: Local image missing or changed

- **WHEN** the host engine has no image with the recipe's image ID
- **THEN** `add` fails naming the ID, and the library is unchanged

#### Scenario: Image-only recipe with environment

- **WHEN** a recipe without file sources declares `PATH` entries, environment variables or `default: true`
- **THEN** `add` fails naming the field

### Requirement: Read-only image store in the library

The library SHALL keep recipe images in one image store inside it, written only by `--container-toolchain`. The command SHALL write the store through a helper container of the installed engine image, using the host's network and the host CA trust saved by setup. The store SHALL keep each image's registry digests. An image shared by several toolchains SHALL be stored once and kept until no toolchain lists it.

#### Scenario: Digests kept

- **WHEN** `add` pulls an image by the digest of a multi-platform index
- **THEN** both the index digest and the platform digest resolve to that image in a session engine

#### Scenario: Shared image

- **WHEN** two toolchains list the same image and one of them is removed
- **THEN** the image stays in the store until the other toolchain is removed too

#### Scenario: Helper container scope

- **WHEN** `add` writes the store
- **THEN** its helper container mounts only the store and, when host CA trust is enabled, the CA bundle, and no workspace, state or installation path

### Requirement: Image removal waits for idle engines

`remove`, or an `add` that replaces a toolchain, SHALL delete images from the store only while no session engine is running. Otherwise it SHALL fail naming the running sessions, and the library SHALL stay unchanged. A change that deletes no image SHALL proceed while engines run.

#### Scenario: Remove while a session engine runs

- **WHEN** the operator removes an image toolchain while a session with an engine is running
- **THEN** the command fails naming that session, and the toolchain and its images remain

#### Scenario: Remove with no engine running

- **WHEN** the operator removes an image toolchain and no session engine is running
- **THEN** the toolchain and the images no other toolchain lists are deleted, and the index is regenerated

#### Scenario: Add while a session engine runs

- **WHEN** the operator adds a new image toolchain while sessions with engines run
- **THEN** the command succeeds, and the running engines can use the new images

### Requirement: Windows drive paths from the Windows entry

When the toolchain command runs from the Windows entry, `add` SHALL translate a recipe path or a local archive path written as a Windows drive path to its drive mount in the machine distribution. It SHALL refuse UNC paths, paths inside a WSL distribution and drives the distribution does not mount, before any fetch.

#### Scenario: Recipe path from PowerShell

- **WHEN** the operator runs `pi-container --container-toolchain add C:\Work\recipes\java.json` from PowerShell
- **THEN** `add` reads `/mnt/c/Work/recipes/java.json` in the machine

#### Scenario: Windows archive path in a recipe

- **WHEN** a recipe added from the Windows entry names the local archive `C:\Downloads\node.tar.xz`
- **THEN** `add` reads `/mnt/c/Downloads/node.tar.xz`

#### Scenario: Network share

- **WHEN** the recipe path is `\\server\share\java.json`
- **THEN** `add` fails naming network paths as unsupported, and the library is unchanged

### Requirement: Windows library location is documented

Documentation SHALL state that on Windows the toolchain library lives inside the Podman machine's distribution, is shared by the wrappers that run in that machine, and is lost when the machine is recreated, after which the operator adds the toolchains again.

#### Scenario: Operator reads the Windows documentation

- **WHEN** an operator reads the README Windows section
- **THEN** it states where the library lives and that recreating the machine removes it
