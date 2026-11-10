# Spec Delta

## MODIFIED Requirements

### Requirement: Pi has no approval layer to bypass

`PI_CONTAINER_YOLO` SHALL be a validated boolean (`0`, `1`, `true`, `false`, `yes`, `no`), checked before engine queries, as in the other wrappers. Pi 0.80.8 runs its tools without approval prompts, so an enabled value SHALL print one stderr warning that it has no effect yet, a disabled value SHALL be silent, and neither SHALL change the engine arguments. Help, README and `AGENTS.md` SHALL state that the container is the only boundary around Pi's tools.

#### Scenario: YOLO variable set
- **WHEN** `PI_CONTAINER_YOLO=1` (or `true` or `yes`) is set
- **THEN** one warning states that Pi has no tool-approval layer and the setting has no effect yet, and the engine arguments equal those of the same launch without the variable

#### Scenario: YOLO disabled by the managed launcher
- **WHEN** a managed launch exports `PI_CONTAINER_YOLO=0`
- **THEN** no YOLO warning is printed and the engine arguments are unchanged

#### Scenario: Invalid YOLO value
- **WHEN** `PI_CONTAINER_YOLO` is set to another value, such as `2` or `on`
- **THEN** the wrapper exits with status 1 naming the variable and its accepted values, before engine queries or state creation

#### Scenario: Project-file trust is separate
- **WHEN** a reader looks up Pi's `--approve` option in the help or README
- **THEN** it is described as trust in project-local files, not as tool approval or YOLO

## ADDED Requirements

### Requirement: Build-only image refresh
`--container-build` used alone SHALL build the runtime image and exit without creating a container. It SHALL require the exact `PI_CONTAINER_MAINTENANCE=1`, an explicit network mode, a verified engine and the selected image name, and SHALL use the same build arguments, Bun selection and `build-inputs-hash` label as a launch that builds. Combined with a launch, it SHALL keep refreshing the image before starting the session.

#### Scenario: Build-only refresh
- **WHEN** `PI_CONTAINER_NETWORK=unrestricted PI_CONTAINER_MAINTENANCE=1 PI_CONTAINER_IMAGE=localhost/pi-container:setup-x pi-container.sh --container-build` runs
- **THEN** the image is built with Pi from `.version` and a matching staleness label, and the wrapper exits 0 without creating a container

#### Scenario: Build-only without maintenance
- **WHEN** `--container-build` is used alone without `PI_CONTAINER_MAINTENANCE=1`
- **THEN** the wrapper exits with status 1 naming the maintenance variable, without image operations
