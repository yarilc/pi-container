"""Bounded inspection of plaintext TLS ClientHellos; never terminates TLS.

The initial ClientHello and, after a TLS 1.3 HelloRetryRequest, the retried
ClientHello are bound to the authorized host. TLS 1.2 renegotiation is
encrypted and therefore never visible here.
"""
from policy import PolicyError, hostname

MAX_HELLO = 64 * 1024
MAX_WIRE = 96 * 1024
MAX_RECORDS = 128
MAX_RECORD = 16 * 1024
# TLSCiphertext may carry up to 2^14 + 256 bytes (RFC 8446 section 5.2).
MAX_CIPHERTEXT = MAX_RECORD + 256
STORAGE = MAX_HELLO + MAX_WIRE
INSPECTION_TIMEOUT = 10
# RFC 9849 plus the retired ESNI/ECH draft name-hiding extensions.
HIDDEN_NAME_EXTENSIONS = (0xfe0d, 0xffce, 0xff02, 0xff03, 0xff04)
# RFC 8446 section 4.1.3: SHA-256("HelloRetryRequest") as ServerHello.random.
HELLO_RETRY_RANDOM = bytes.fromhex('cf21ad74e59a6111be1d8c021e65b891c2a211167abb8c5e079e09e2c8a8339c')
RETRY, NO_RETRY = 'retry', 'no-retry'


class TLSRejected(Exception):
    """Contains only a fixed reason code, never wire input."""


class Cursor:
    def __init__(self, data):
        self.data, self.pos = data, 0

    def take(self, count):
        end = self.pos + count
        if end > len(self.data):
            raise TLSRejected('tls-malformed')
        result = self.data[self.pos:end]
        self.pos = end
        return result

    def number(self, size):
        return int.from_bytes(self.take(size), 'big')

    def vector(self, size):
        return self.take(self.number(size))

    def end(self):
        if self.pos != len(self.data):
            raise TLSRejected('tls-malformed')


def validate(data, expected):
    cursor = Cursor(data)
    if cursor.number(2) != 0x0303:
        raise TLSRejected('tls-unsupported')
    cursor.take(32)
    if len(cursor.vector(1)) > 32:
        raise TLSRejected('tls-malformed')
    ciphers = cursor.vector(2)
    if not ciphers or len(ciphers) % 2:
        raise TLSRejected('tls-malformed')
    compression = cursor.vector(1)
    if not compression or 0 not in compression:
        raise TLSRejected('tls-malformed')
    extensions = Cursor(cursor.vector(2))
    cursor.end()
    # Fixed 8 KiB metadata rather than an attacker-sized Python set.
    seen = bytearray(8192)
    name = None
    versions = None
    while extensions.pos < len(extensions.data):
        kind = extensions.number(2)
        value = extensions.vector(2)
        slot, bit = divmod(kind, 8)
        if seen[slot] & (1 << bit):
            raise TLSRejected('tls-malformed')
        seen[slot] |= 1 << bit
        if kind in HIDDEN_NAME_EXTENSIONS:
            raise TLSRejected('tls-ech')
        if kind == 0:
            names = Cursor(value)
            entry = Cursor(names.vector(2))
            names.end()
            if entry.number(1) != 0:
                raise TLSRejected('tls-identity')
            encoded = entry.vector(2)
            entry.end()
            if not 0 < len(encoded) <= 254:
                raise TLSRejected('tls-identity')
            try:
                name = hostname(bytes(encoded).decode('ascii'))
            except (UnicodeError, PolicyError):
                raise TLSRejected('tls-identity') from None
        elif kind == 43:
            offered = Cursor(value)
            encoded = offered.vector(1)
            offered.end()
            if not encoded or len(encoded) % 2:
                raise TLSRejected('tls-malformed')
            versions = any(int.from_bytes(encoded[i:i + 2], 'big') in (0x0303, 0x0304)
                           for i in range(0, len(encoded), 2))
    if versions is False:
        raise TLSRejected('tls-unsupported')
    if name is None or name != expected:
        raise TLSRejected('tls-identity')


class ClientHello:
    """Retains at most MAX_WIRE original bytes and MAX_HELLO handshake bytes.

    Fixed buffers avoid allocation from declared lengths and resizing/copy peaks.
    The caller reserves STORAGE before construction and owns the input chunk.
    The ClientHello must end at a record boundary; later records are surplus.
    In retry mode, ChangeCipherSpec and early-data records may precede the
    retried ClientHello (RFC 8446 sections 4.1.2, 4.2.10 and D.4).
    """
    def __init__(self, expected, retry=False):
        self.expected = expected
        self.retry = retry
        self.wire = bytearray(MAX_WIRE)
        self.hello = bytearray(MAX_HELLO)
        self.used = self.offset = self.filled = self.records = 0
        self.length = None
        self.done = False

    def feed(self, data):
        if self.done:
            raise TLSRejected('tls-malformed')
        if len(data) > MAX_WIRE - self.used:
            raise TLSRejected('tls-overflow')
        wire, hello = memoryview(self.wire), memoryview(self.hello)
        wire[self.used:self.used + len(data)] = data
        self.used += len(data)
        while self.used - self.offset >= 5:
            header = wire[self.offset:self.offset + 5]
            kind = header[0]
            skippable = self.retry and self.length is None and self.filled == 0 and kind in (20, 23)
            if (kind != 22 and not skippable) or int.from_bytes(header[1:3], 'big') not in (0x0301, 0x0302, 0x0303):
                raise TLSRejected('tls-malformed')
            size = int.from_bytes(header[3:5], 'big')
            if not 0 < size <= (MAX_CIPHERTEXT if kind == 23 else MAX_RECORD):
                raise TLSRejected('tls-malformed')
            if self.records >= MAX_RECORDS:
                raise TLSRejected('tls-overflow')
            end = self.offset + 5 + size
            if end > self.used:
                return False
            part = wire[self.offset + 5:end]
            self.records += 1
            self.offset = end
            if kind == 20 and bytes(part) != b'\x01':
                raise TLSRejected('tls-malformed')
            if kind != 22:
                continue
            while part:
                target = 4 if self.length is None else self.length
                count = min(len(part), target - self.filled)
                hello[self.filled:self.filled + count] = part[:count]
                self.filled += count
                part = part[count:]
                if self.filled < target:
                    break
                if self.length is None:
                    if hello[0] != 1:
                        raise TLSRejected('tls-malformed')
                    self.length = 4 + int.from_bytes(hello[1:4], 'big')
                    if self.length > MAX_HELLO:
                        raise TLSRejected('tls-overflow')
                    if self.length <= 4:
                        raise TLSRejected('tls-malformed')
                else:
                    if part:
                        # Further handshake bytes in the same record are never inspected.
                        raise TLSRejected('tls-malformed')
                    validate(hello[4:self.length], self.expected)
                    self.done = True
                    return True
        return False

    def finish(self):
        if not self.done:
            raise TLSRejected('tls-malformed')

    def original(self):
        """The validated records, ending with the ClientHello's last record."""
        if not self.done:
            raise TLSRejected('tls-malformed')
        return memoryview(self.wire)[:self.offset]

    def surplus(self):
        """Bytes received after the ClientHello's last record, not yet inspected."""
        if not self.done:
            raise TLSRejected('tls-malformed')
        return memoryview(self.wire)[self.offset:self.used]

    def hold(self, data):
        """Keep bytes after a validated ClientHello, unparsed, within MAX_WIRE."""
        if not self.done:
            raise TLSRejected('tls-malformed')
        if len(data) > MAX_WIRE - self.used:
            raise TLSRejected('tls-overflow')
        memoryview(self.wire)[self.used:self.used + len(data)] = data
        self.used += len(data)

    def next_hello(self):
        """Reuse the fixed buffers to inspect the surplus as a retried ClientHello.

        Returns True when the surplus already contains a complete ClientHello.
        """
        if not self.done:
            raise TLSRejected('tls-malformed')
        remaining = self.used - self.offset
        memoryview(self.wire)[:remaining] = bytes(memoryview(self.wire)[self.offset:self.used])
        self.used, self.offset, self.filled, self.records = remaining, 0, 0, 0
        self.length = None
        self.done = False
        self.retry = True
        return self.feed(b'')

    def held(self):
        """Every byte received so far, in original order."""
        return memoryview(self.wire)[:self.used]


class ServerHello:
    """Classifies the upstream's first handshake message with fixed storage.

    Only the handshake header, legacy_version and random are needed. Anything
    other than a handshake record first means no retry: the upstream is the
    authorized endpoint and there is no client identity to bind.
    """
    NEEDED = 4 + 2 + 32

    def __init__(self):
        self.header = bytearray(5)
        self.prefix = bytearray(self.NEEDED)
        self.header_filled = self.prefix_filled = self.remaining = 0
        self.decision = None

    def feed(self, data):
        view = memoryview(data)
        position = 0
        while self.decision is None and position < len(view):
            if self.remaining == 0:
                count = min(5 - self.header_filled, len(view) - position)
                self.header[self.header_filled:self.header_filled + count] = view[position:position + count]
                self.header_filled += count
                position += count
                if self.header_filled < 5:
                    break
                self.header_filled = 0
                self.remaining = int.from_bytes(self.header[3:5], 'big')
                if self.header[0] != 22 or not 0 < self.remaining <= MAX_RECORD:
                    self.decision = NO_RETRY
                continue
            count = min(self.remaining, self.NEEDED - self.prefix_filled, len(view) - position)
            self.prefix[self.prefix_filled:self.prefix_filled + count] = view[position:position + count]
            self.prefix_filled += count
            self.remaining -= count
            position += count
            if self.prefix[0] != 2:
                self.decision = NO_RETRY
            elif self.prefix_filled == self.NEEDED:
                self.decision = RETRY if bytes(self.prefix[6:]) == HELLO_RETRY_RANDOM else NO_RETRY
        return self.decision

    def eof(self):
        if self.decision is None:
            self.decision = NO_RETRY
        return self.decision
