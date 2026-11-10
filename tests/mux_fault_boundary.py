"""Test-owned wire faults outside unmodified guard, relay and proxy processes."""
import os
from pathlib import Path
import select
import socket
import struct
import threading
import time

MAGIC = b'SANDBOX-EGRESS\x00\x01'
HEADER = struct.Struct('!BII')


class FaultBoundary:
    def __init__(self, directory, upstream, workspace, mode):
        self.workspace, self.mode = Path(workspace), mode
        self.upstream = upstream
        self.stop = threading.Event()
        self.read_gate = threading.Event()
        self.read_gate.set()
        self.connected = threading.Event()
        self.proxy_lock = threading.Lock()
        self.client_lock = threading.Lock()
        self.mapping, self.reverse = {}, {}
        self.next_id = 1
        self.errors, self.sockets, self.threads = [], [], []
        self.delayed = self.pressure = False
        self.injected = 0
        self.listener = socket.socket(socket.AF_UNIX)
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            self.listener.bind(f'/proc/self/fd/{descriptor}/proxy.sock')
        finally:
            os.close(descriptor)
        (Path(directory) / 'proxy.sock').chmod(0o700)
        self.listener.listen(1)
        self.listener.settimeout(.2)
        self.launch(self.accept)

    def launch(self, target):
        def guarded():
            try:
                target()
            except (OSError, EOFError):
                pass
            except Exception as error:
                self.errors.append(repr(error))
        worker = threading.Thread(target=guarded, daemon=True)
        self.threads.append(worker)
        worker.start()

    def read(self, connection, size):
        result = bytearray()
        while len(result) < size and not self.stop.is_set():
            if not select.select([connection], [], [], .2)[0]:
                continue
            data = connection.recv(size - len(result))
            if not data:
                raise EOFError()
            result.extend(data)
        if len(result) != size:
            raise EOFError()
        return bytes(result)

    def write(self, connection, data, on_pressure=None):
        remaining = memoryview(data)
        deadline = time.monotonic() + 25
        while remaining and not self.stop.is_set():
            if not select.select([], [connection], [], .2)[1]:
                if on_pressure:
                    on_pressure()
                if time.monotonic() > deadline:
                    raise TimeoutError('test boundary write stalled')
                continue
            try:
                sent = connection.send(remaining)
            except BlockingIOError:
                continue
            remaining = remaining[sent:]

    def accept(self):
        while not self.stop.is_set():
            try:
                self.client, _ = self.listener.accept()
                break
            except socket.timeout:
                continue
        else:
            return
        self.proxy = socket.socket(socket.AF_UNIX)
        descriptor = os.open(self.upstream, os.O_RDONLY | os.O_DIRECTORY)
        try:
            self.proxy.connect(f'/proc/self/fd/{descriptor}/proxy.sock')
        finally:
            os.close(descriptor)
        self.sockets.extend([self.client, self.proxy])
        for connection in self.sockets:
            connection.setblocking(False)
        assert self.read(self.client, len(MAGIC)) == MAGIC
        self.write(self.proxy, MAGIC)
        assert self.read(self.proxy, len(MAGIC)) == MAGIC
        self.write(self.client, MAGIC)
        self.connected.set()
        self.launch(self.from_proxy)
        if self.mode == 'pressure':
            self.launch(self.inject_pressure)
        while not self.stop.is_set():
            kind, ident, size = HEADER.unpack(self.read(self.client, HEADER.size))
            payload = self.read(self.client, size)
            with self.proxy_lock:
                if kind == 1:
                    self.mapping[ident] = self.next_id
                    self.reverse[self.next_id] = ident
                    self.next_id += 1
                self.write(self.proxy, HEADER.pack(kind, self.mapping[ident], size) + payload)

    def from_proxy(self):
        while not self.stop.is_set():
            self.read_gate.wait(.2)
            if not self.read_gate.is_set():
                continue
            kind, ident, size = HEADER.unpack(self.read(self.proxy, HEADER.size))
            payload = self.read(self.proxy, size)
            if ident not in self.reverse:
                continue  # Responses to test-injected, immediately closed IDs.
            frame = HEADER.pack(kind, self.reverse[ident], size) + payload
            if self.mode == 'ack' and kind == 6 and not self.delayed:
                self.delayed = True
                def release(held=frame):
                    if not self.stop.wait(11):
                        with self.client_lock:
                            self.write(self.client, held)
                        (self.workspace / 'fault-complete').touch()
                self.launch(release)
                continue
            with self.client_lock:
                self.write(self.client, frame)

    def inject_pressure(self):
        deadline = time.monotonic() + 60
        while not (self.workspace / 'fault-ready').exists():
            if self.stop.wait(.01):
                return
            assert time.monotonic() < deadline, 'application never reached controlled stream'
        self.read_gate.clear()
        try:
            # Stop consuming proxy output, then issue legal sequential closures
            # until pressure propagates through proxy control and socket queues.
            # IDs are translated so real relay IDs remain valid afterward.
            with self.proxy_lock:
                for _ in range(80000):
                    ident = self.next_id
                    self.next_id += 1
                    authority = b'unapproved.test:443'
                    frame = HEADER.pack(1, ident, len(authority)) + authority + HEADER.pack(6, ident, 0)
                    if not select.select([], [self.proxy], [], .2)[1]:
                        self.pressure = True
                        self.read_gate.set()
                    def resume():
                        self.pressure = True
                        self.read_gate.set()
                    self.write(self.proxy, frame, on_pressure=resume)
                    self.injected += 1
                    if self.pressure:
                        break
                    time.sleep(.0005)
                assert self.pressure, 'test did not reach shared transport backpressure'
        finally:
            self.read_gate.set()
        (self.workspace / 'fault-complete').touch()

    def close(self):
        self.stop.set()
        self.read_gate.set()
        self.listener.close()
        for connection in self.sockets:
            connection.close()
        for worker in self.threads:
            worker.join(2)
        assert not any(worker.is_alive() for worker in self.threads), 'test boundary worker leaked'
