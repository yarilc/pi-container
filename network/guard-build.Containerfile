FROM docker.io/library/alpine@sha256:c64c687cbea9300178b30c95835354e34c4e4febc4badfe27102879de0483b5e

# With host CA trust enabled, the selected bundle arrives as the optional build-ca
# secret (never stored in a layer) and is appended to Alpine's own roots so apk
# verifies on TLS-intercepting networks. The temporary bundle is removed in this step.
RUN --mount=type=secret,id=build-ca,required=false \
    cat /etc/ssl/certs/ca-certificates.crt > /tmp/apk-bootstrap-ca.pem \
    && if [ -s /run/secrets/build-ca ]; then cat /run/secrets/build-ca >> /tmp/apk-bootstrap-ca.pem; fi \
    && SSL_CERT_FILE=/tmp/apk-bootstrap-ca.pem apk add --no-cache gcc=13.2.1_git20240309-r1 musl-dev=1.2.5-r4 binutils=2.42-r1 \
    && rm -f /tmp/apk-bootstrap-ca.pem

ENV LC_ALL=C SOURCE_DATE_EPOCH=0
ENTRYPOINT ["gcc"]
