## ADDED Requirements

### Requirement: Host CA trust is disabled by default
The wrapper SHALL NOT mount any host certificate bundle and SHALL NOT set CA bundle environment variables unless host CA trust is enabled.

#### Scenario: Variable not set or disabled
- **WHEN** the wrapper starts with `PI_CONTAINER_TRUST_HOST_CA` unset, or set to `0`, `false` or `no`
- **THEN** the container has no host certificate mount and no `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`, `CURL_CA_BUNDLE` or `NODE_EXTRA_CA_CERTS` set by the wrapper

### Requirement: Host CA trust is enabled by an explicit flag
The wrapper SHALL enable host CA trust when `PI_CONTAINER_TRUST_HOST_CA` is `1`, `true` or `yes`, case-insensitively. Any other nonempty value SHALL fail before image operations or container creation, with a message naming the variable and the accepted values.

#### Scenario: Variable enabled
- **WHEN** the wrapper starts with `PI_CONTAINER_TRUST_HOST_CA=1`
- **THEN** host CA trust is enabled

#### Scenario: Invalid value
- **WHEN** the wrapper starts with `PI_CONTAINER_TRUST_HOST_CA=maybe`
- **THEN** it exits nonzero naming the variable and the accepted values, and no container starts

### Requirement: Bundle selection
When host CA trust is enabled, the wrapper SHALL use the file named by `PI_CONTAINER_CA_BUNDLE` if set. Otherwise it SHALL use the first existing file among `/etc/ssl/certs/ca-certificates.crt` and `/etc/pki/tls/certs/ca-bundle.crt`.

#### Scenario: Explicit bundle path
- **WHEN** trust is enabled and `PI_CONTAINER_CA_BUNDLE` names an existing file
- **THEN** that file is the bundle exposed to the container

#### Scenario: Explicit bundle path missing
- **WHEN** trust is enabled and `PI_CONTAINER_CA_BUNDLE` names a missing file
- **THEN** the wrapper exits nonzero naming the variable and the path, and no container starts

#### Scenario: No default bundle
- **WHEN** trust is enabled, `PI_CONTAINER_CA_BUNDLE` is unset and neither default path exists
- **THEN** the wrapper exits nonzero asking the user to set `PI_CONTAINER_CA_BUNDLE`

### Requirement: Read-only bundle mount
When host CA trust is enabled, the wrapper SHALL mount only the selected bundle file, read-only, at `/pi-home/ca/bundle.pem`. It SHALL NOT mount the host certificate directory or make the host trust store writable from the container. With an isolated state home, the wrapper SHALL create the private `ca` mount parent itself.

#### Scenario: Bundle mounted read-only
- **WHEN** host CA trust is enabled
- **THEN** the container sees the selected bundle at `/pi-home/ca/bundle.pem` read-only, and the image's own certificate directory remains in place

### Requirement: Tools use the mounted bundle
When host CA trust is enabled, the wrapper SHALL set `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`, `CURL_CA_BUNDLE` and `NODE_EXTRA_CA_CERTS` to `/pi-home/ca/bundle.pem`. Documentation SHALL record whether the installed Pi client (Node) honors that bundle.

#### Scenario: Environment variables set
- **WHEN** host CA trust is enabled
- **THEN** all four variables point at the mounted bundle path
