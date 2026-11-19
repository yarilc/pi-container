## 1. Baseline

- [x] 1.1 Record the current image ID and the reported versions (Pi 0.80.8, OpenSpec 1.16.0). Run `./test-wrapper.sh` and the pin tests on the unchanged tree, and keep the results as the baseline for the old-test gate.
- [x] 1.2 Create a disposable copy of a 0.80.8 state directory (`.pi`, `.agents`) with a session, settings and a trust-free project, for the state check in 3.6.

## 2. Pins and policy

- [x] 2.1 Set `.version` to `1.5.2` and `OPENSPEC_VERSION=2.0.0` in `Containerfile`. Leave the base digest unchanged.
- [x] 2.2 Set `tested.cli` in `agent/policies/default.json` to `1.5.2`, with the measurement notes and dates. Keep the revision unless 3.3 finds a changed host.
- [x] 2.3 Update every test that asserts `0.80.8` or `1.16.0` (`tests/test_image_pins.py`, `tests/test_network_runtime.py`, `tests/test_runtime.py` and others found with `git grep`).

## 3. Build and measure

- [x] 3.1 Rebuild with `PI_CONTAINER_NETWORK=unrestricted PI_CONTAINER_MAINTENANCE=1 ./pi-container.sh --container-build`. The image must report `pi --version` 1.5.2 and `openspec --version` 2.0.0.
- [x] 3.2 Check the controls. `PI_OFFLINE`, `PI_SKIP_VERSION_CHECK` and `PI_TELEMETRY` must still exist and still suppress the startup requests measured on 0.80.8. Also check whether 1.5.2 has any tool-approval prompt; if it does, pause for the YOLO decision.
- [x] 3.3 Run the static endpoint inventory of 1.5.2 (including `pi-ai`, `pi-mcp` and `pi-codemode`) and the logging-proxy runs for the four profiles with dummy keys, with and without the restricted controls. Compare with the 0.80.8 tables. If a required host changed, stop and agree on a `network-egress` delta and a new revision.
- [x] 3.4 Under the guard, run a codemode script and `pi mcp list` with a user-level `mcp.json` that names a host outside the profile. Record the results, including whether an MCP OAuth callback listener can bind.
- [x] 3.5 Check project trust in print mode:
  - project `.agents/skills` is skipped by default;
  - it loads with `--approve`;
  - `~/.pi/agent/trust.json` is written to persistent state.
- [x] 3.6 Start 1.5.2 against the 0.80.8 state copy from 1.2. Record any migration, warning or error.

## 4. Skills and suites

- [x] 4.1 Regenerate `.agents/skills/openspec-*` with the image's OpenSpec 2.0.0: run `openspec update` in shell mode on the checkout. Review the diff, and keep the previous skill set only where 2.0 refuses to overwrite edited files.
- [x] 4.2 Run `./test-wrapper.sh`, `./test.sh` and every credential-free runtime suite. Classify any failing old test with the gate and resolve it.
- [x] 4.3 Run the offline OpenSpec round trip from the reference change in shell mode.
- [x] 4.4 Run `bash ../sandbox-container/tools/shellcheck.sh .` and `git diff --check`. Known shared-file findings stay as recorded; this change adds none.

## 5. Record

- [x] 5.1 Update the version-specific statements:
  - `README.md`, `docs/setup.md` and `docs/network-contract.md`: the measured version, the tool-approval statement, project trust, the MCP note and the Azure and extension API notes;
  - the help text in `agent/launcher.sh`, if it is affected.
- [x] 5.2 Add a dated entry to `docs/validation.md`. It records:
  - the version rule and the reported versions;
  - the full measurement tables and diffs;
  - the codemode, MCP, trust and state results;
  - the skill regeneration and the suite results.
- [x] 5.3 Add a `CHANGELOG.md` entry.
- [x] 5.4 Run `openspec validate pin-pi-1-5-2 --strict`, then commit on `main`.

## Workflow follow-up

- The operator pushes `main`. The next launch asks for `--container-build`, and the operator reruns `--container-setup` on the three hosts.
- Archive with `/opsx:archive pin-pi-1-5-2`. Sync specs only if a delta was added.
- Real-key checks go to the deferred authenticated pass.
