# Tasks

## 1. Adopt sandbox-ref-12

- [x] 1.1 From claude-container, run `python3 -I tools/propagate.py
  ../pi-container sandbox-ref-10 sandbox-ref-12` (dry run). Verify that it
  lists 21 modified shared files, nothing added, removed or "not adopted",
  five documents including `CONTRIBUTING.md`, and `REFERENCE_COMMIT`
  `fd196c9`.
- [x] 1.2 Stash the change directory (`git stash -u`), run `--apply`, and
  restore the stash on the new branch. Verify:
  - Pi is on `adopt-sandbox-ref-12`;
  - the stash list is empty;
  - `git diff --name-only` lists only the shared files, the manifest and
    the five documents;
  - `python3 -m unittest tests.test_reference_copy tests.test_alignment`
    passes.

## 2. Wrapper test fixtures

- [x] 2.1 In `tests/test_wrapper.py`, copy `network/agent_budgets.py` into
  the fake installation. In `tests/fake_podman.py`, answer
  `{{.Host.CgroupControllers}}` from `FAKE_CONTROLLERS`, by default
  `[cpu memory pids]`. Verify that the full unit discovery passes on the
  adopted shared files.

## 3. Launcher

- [x] 3.1 Reduce a `unix://` host socket report to its pathname (design
  decision 4). Add wrapper tests:
  - `unix:///host/podman.sock` binds `/host/podman.sock`;
  - `unix://relative`, `unix://` and `unix:///` are rejected before image
    operations.

  Verify that they pass.
- [x] 3.2 Make budgets follow the delegated controllers (design decision 4):
  - the controller query after the build-only exit, and its validation;
  - `budget_args`, with `--pids-limit=-1` when `pids` is missing;
  - the notices;
  - the inspection for enforced and unenforced budgets;
  - the help text.

  Make the fake inspection derive values from the agent create when
  `FAKE_AGENT_BUDGETS` is unset. Add tests:
  - every subset of controllers;
  - an unverifiable list, rejected before state creation;
  - an unenforced budget present, and an enforced budget missing.

  Verify that they pass, together with the existing budget tests.
- [x] 3.3 Replace `--read-only-tmpfs=false` with the `/run/secrets`, `/dev`,
  `/dev/pts` and `/dev/shm` mounts. Update the existing assertions on
  `--read-only-tmpfs=false`. Add a test asserting the four mounts and the
  unchanged `/tmp`, `/var/tmp`, `/run`, home and npm-cache options:
  - in Pi and shell mode, with and without delegation;
  - in offline and provider mode;
  - on the provider proxy, the secrets mask and its budgets.

  Verify that they pass.
- [x] 3.4 Split the CA selection into `select_ca_bundle()`, called before any
  build (design decision 2). Pass the `build-ca` secret in
  `build_runtime_image()` (design decision 3) and add `!podman-build-secret*`
  to `.containerignore`. Add tests:
  - build-only refresh and launch build, each with and without trust,
    asserting the secret;
  - the `build-inputs-hash` label is identical with and without trust;
  - an invalid bundle stops a build-only refresh before any image
    operation.

  Verify that they pass, together with the existing CA and build-only tests.
- [x] 3.5 Run `bash -n pi-container.sh test-wrapper.sh test.sh
  tests/run-runtime.sh` and the full
  `python3 -m unittest discover -s tests -p test_wrapper.py`. Verify that
  both pass.

## 4. Runtime image recipe

- [x] 4.1 Port the HTTPS trust bootstrap into the first `RUN` of
  `Containerfile` (design decision 5). Port the transport, toolchain and
  workdir checks into `tests/test_image_pins.py`, adapt the mutations to
  Pi's recipe, and make the toolset regex accept `apt-get -o … install`.
  Verify that `python3 -m unittest tests.test_image_pins` passes and that
  each mutation is rejected.
- [x] 4.2 Build the image through the wrapper:
  `PI_CONTAINER_NETWORK=unrestricted PI_CONTAINER_MAINTENANCE=1
  PI_CONTAINER_IMAGE=localhost/pi-container:adopt-ref-11 ./pi-container.sh
  --container-build`. Verify:
  - every Debian `URIs:` line is `https://`;
  - `/tmp/apt-bootstrap-ca.pem` is absent and `ca-certificates` is
    installed;
  - `pi --version` matches `.version`, and OpenSpec is `1.16.0`;
  - the image has no `WORKDIR` (`/`);
  - the `build-inputs-hash` label equals the launcher's current hash, so a
    launch does not report the image as stale.

## 5. Documentation

- [x] 5.1 Update `README.md` and `AGENTS.md`:
  - conditional budget enforcement, with notices and the exhaustion risk;
  - the `/run/secrets` mask;
  - the `noexec` `/dev`, `/dev/pts` and read-only `/dev/shm`;
  - HTTPS-only image fetches on port 443;
  - the `build-ca` secret, including the build-only refresh.

  Verify that the documented paths and variables match the launcher and
  `--container-help`.

## 6. Validation and publication

- [x] 6.1 Run the full unit discovery on executable, private, native
  temporary storage. Verify that there are no failures, apart from known
  timing-sensitive tests that pass on a rerun, which are recorded as such.
- [x] 6.2 With the image from 4.2, run `bash tests/run-runtime.sh` with
  `--shared`, `--setup`, `--setup-runtime`, `--qualification`, `--guard`,
  `--network` and the default mode, and run `./test.sh`. Verify that every
  mode passes, or record it as unavailable on this host.
- [x] 6.3 Fill in the tool's validation-record template in
  `docs/validation.md` with the results of 6.1–6.2, the wrapper adaptations
  and the image ID. Record the operator setups as pending. Verify that every
  check is listed as passed, failed or unavailable.
- [x] 6.4 Verify that the SHA-256 of the five-wrapper parity table matches
  claude-container. Codex and OpenCode will match once they adopt
  `sandbox-ref-12`.
- [x] 6.5 Commit on `adopt-sandbox-ref-12` with the tool's message and the
  co-author trailer, merge it into `main` with `--no-ff`, and verify that
  `git log --oneline -3` shows the merge.

## Workflow follow-up

- The operator pushes Pi `main`, then runs `--container-setup` (refresh
  approved) and a session on this host, the Rocky Linux 9 lab host and the
  newer WSL host. The results are added to `docs/validation.md`.
- Sync the delta specs and archive this change after review.
- Still open: Bun in restricted modes. Qualification drops `PI_ENABLE_BUN`.
- Codex and OpenCode adopt `sandbox-ref-12` in their own changes.
