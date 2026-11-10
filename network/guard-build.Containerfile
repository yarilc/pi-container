FROM docker.io/library/alpine@sha256:c64c687cbea9300178b30c95835354e34c4e4febc4badfe27102879de0483b5e

RUN apk add --no-cache gcc=13.2.1_git20240309-r1 musl-dev=1.2.5-r4 binutils=2.42-r1

ENV LC_ALL=C SOURCE_DATE_EPOCH=0
ENTRYPOINT ["gcc"]
