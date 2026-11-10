"""Reclassify Podman 4.3's successful restart check without buffering prompts."""
import os
import re


PREFIXES = (b'ERRO[', b'\x1b[31mERRO\x1b[0m[')
SUFFIXES = (b'] Should restart: false\n', b'] Should restart: false\r\n')
RESTART = re.compile(rb'^(?:ERRO|\x1b\[31mERRO\x1b\[0m)\[[0-9]{1,20}\] Should restart: false\r?\n$')
KEY_VALUE = re.compile(rb'^time="[0-9T:.+Z-]{1,64}" level=error msg="Should restart: false"\r?\n$')
TIMESTAMP_BYTES = b'0123456789T:.+Z-'
KEY_VALUE_SUFFIXES = (b'" level=error msg="Should restart: false"\n',
                      b'" level=error msg="Should restart: false"\r\n')


def possible_prefix(data):
    for prefix in PREFIXES:
        if prefix.startswith(data):
            return True
        if not data.startswith(prefix):
            continue
        tail = data[len(prefix):]
        count = 0
        while count < len(tail) and 48 <= tail[count] <= 57:
            count += 1
        if count > 20:
            continue
        if count == len(tail):
            return True
        if count and any(suffix.startswith(tail[count:]) for suffix in SUFFIXES):
            return True
    prefix = b'time="'
    if prefix.startswith(data):
        return True
    if data.startswith(prefix):
        tail = data[len(prefix):]
        count = 0
        while count < len(tail) and tail[count] in TIMESTAMP_BYTES:
            count += 1
        if count <= 64:
            if count == len(tail):
                return True
            if count and any(suffix.startswith(tail[count:]) for suffix in KEY_VALUE_SUFFIXES):
                return True
    return False


class Diagnostics:
    def __init__(self):
        self.pending = bytearray()
        self.line_start = True

    def feed(self, chunk):
        output = bytearray()
        for byte in chunk:
            if not self.line_start:
                output.append(byte)
                self.line_start = byte == 10
                continue
            self.pending.append(byte)
            if RESTART.fullmatch(self.pending) or KEY_VALUE.fullmatch(self.pending):
                line = bytes(self.pending)
                if line.startswith(b'time="'):
                    line = line.replace(b' level=error ', b' level=info ', 1)
                elif line.startswith(b'\x1b'):
                    line = line.replace(b'\x1b[31mERRO', b'\x1b[36mINFO', 1)
                else:
                    line = b'INFO' + line[4:]
                output.extend(line)
                self.pending.clear()
            elif not possible_prefix(self.pending):
                output.extend(self.pending)
                self.pending.clear()
                self.line_start = byte == 10
        return bytes(output)

    def finish(self):
        return bytes(self.pending)


def write_all(data):
    data = memoryview(data)
    while data:
        data = data[os.write(1, data):]


def main():
    diagnostics = Diagnostics()
    while chunk := os.read(0, 16384):
        write_all(diagnostics.feed(chunk))
    write_all(diagnostics.finish())


if __name__ == '__main__':
    main()
