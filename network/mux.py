"""Bounded v1 data-only multiplex transport shared by proxy and confined relay."""
import asyncio
import struct

MAGIC = b'SANDBOX-EGRESS\x00\x01'
HEADER = struct.Struct('!BII')
OPEN, OPEN_OK, OPEN_ERR, DATA, HALF_CLOSE, CLOSE, WINDOW_UPDATE = range(1, 8)
MAX_STREAMS = 64
MAX_DATA = 16 * 1024
MAX_OPEN = 8 * 1024
WINDOW = 256 * 1024
MAX_SESSION = MAX_STREAMS * WINDOW
IDLE_TIMEOUT = 300
WRITE_TIMEOUT = 30
FRAME_TIMEOUT = 10
CLOSE_TIMEOUT = 10


async def bounded(awaitable, timeout):
    async with asyncio.timeout(timeout):
        return await awaitable


class ProtocolError(Exception):
    """Never includes untrusted wire input."""


class StreamClosed(Exception):
    pass


class Stream:
    def __init__(self, channel, ident, opened=False):
        self.channel, self.ident = channel, ident
        self.opened = opened
        self.ready = asyncio.Event()
        self.changed = asyncio.Condition()
        self.buffer = bytearray()
        self.credit = WINDOW
        self.receive_credit = WINDOW
        self.remote_eof = self.local_eof = self.closed = False
        self.remote_closed = False
        self.response_received = False
        self.error = None
        self.close_sent = False
        self.remote_done = asyncio.Event()
        self.worker = None
        self.closer = None
        if opened:
            self.ready.set()

    async def wait_ready(self):
        await bounded(self.ready.wait(), 15)
        if self.error or self.closed:
            raise StreamClosed()

    async def send(self, data):
        view = memoryview(data)
        while view:
            async with self.changed:
                async with asyncio.timeout(IDLE_TIMEOUT):
                    await self.changed.wait_for(lambda: self.closed or self.credit > 0)
                if self.closed or self.local_eof or not self.opened:
                    raise StreamClosed()
                size = min(len(view), MAX_DATA, self.credit)
                self.credit -= size
            await self.channel.frame(DATA, self.ident, bytes(view[:size]))
            view = view[size:]

    async def readable(self):
        """Wait until read() would not block; consumes nothing, so it is safe to cancel."""
        async with self.changed:
            async with asyncio.timeout(IDLE_TIMEOUT):
                await self.changed.wait_for(lambda: self.closed or self.buffer or self.remote_eof)

    async def read(self):
        async with self.changed:
            async with asyncio.timeout(IDLE_TIMEOUT):
                await self.changed.wait_for(lambda: self.closed or self.buffer or self.remote_eof)
            if self.closed and not self.buffer and not self.remote_eof:
                raise StreamClosed()
            if not self.buffer:
                return b''
            data = bytes(self.buffer[:MAX_DATA])
            del self.buffer[:len(data)]
            self.channel.queued -= len(data)
            self.receive_credit += len(data)
        await self.channel.frame(WINDOW_UPDATE, self.ident, struct.pack('!I', len(data)))
        return data

    async def eof(self):
        if not self.closed and not self.local_eof:
            self.local_eof = True
            await self.channel.frame(HALF_CLOSE, self.ident)

    async def close(self):
        if self.remote_closed or self.channel.closed:
            await self.channel.end_stream(self)
            return
        # One channel-owned cleanup per outstanding stream survives caller
        # cancellation. It expires independently of the retained wire state.
        if self.closer is None:
            self.closer = asyncio.create_task(self.finish_close())
            self.channel.closers.add(self.closer)
            self.closer.add_done_callback(self.channel.closers.discard)
        await asyncio.shield(self.closer)

    async def finish_close(self):
        await self.channel.end_stream(self, remove=False)
        if self.worker and not self.worker.done():
            self.worker.cancel()
        try:
            if not self.close_sent:
                self.close_sent = True
                sent, deadline = await self.channel.queue_control(CLOSE, self.ident)
                try:
                    async with asyncio.timeout_at(deadline):
                        await sent.wait()
                except asyncio.TimeoutError:
                    await self.channel.close()
                    return
            try:
                await bounded(self.remote_done.wait(), CLOSE_TIMEOUT)
            except asyncio.TimeoutError:
                # Retain only bounded validation state, occupying its original
                # admission slot until acknowledgement or channel teardown.
                pass
        except StreamClosed:
            pass


class Channel:
    def __init__(self, reader, writer, on_open=None, audit=None):
        self.reader, self.writer, self.on_open = reader, writer, on_open
        self.audit = audit
        self.streams = {}
        self.tasks = set()
        self.closers = set()
        self.last_id = 0
        self.next_id = 1
        self.closed = False
        self.queued = 0
        self.write_lock = asyncio.Lock()
        self.receiver = None
        self.control_sender = None
        self.controls = asyncio.Queue(maxsize=MAX_STREAMS)
        writer.transport.set_write_buffer_limits(high=65536, low=16384)

    async def start(self):
        try:
            self.writer.write(MAGIC)
            await bounded(self.writer.drain(), 10)
            received = await bounded(self.reader.readexactly(len(MAGIC)), 10)
            if received != MAGIC:
                raise ProtocolError()
            self.control_sender = asyncio.create_task(self.send_controls())
            self.receiver = asyncio.create_task(self.receive())
            return self
        except BaseException:
            self.writer.close()
            raise

    async def frame(self, kind, ident, payload=b'', *, deadline=None):
        if self.closed:
            raise StreamClosed()
        if deadline is None:
            deadline = asyncio.get_running_loop().time() + WRITE_TIMEOUT
        try:
            async with asyncio.timeout_at(deadline):
                async with self.write_lock:
                    if self.closed:
                        raise StreamClosed()
                    self.writer.write(HEADER.pack(kind, ident, len(payload)) + payload)
                    await self.writer.drain()
        except (OSError, asyncio.TimeoutError):
            await self.close()
            raise StreamClosed() from None

    async def queue_control(self, kind, ident):
        if self.closed:
            raise StreamClosed()
        deadline = asyncio.get_running_loop().time() + WRITE_TIMEOUT
        sent = asyncio.Event()
        try:
            async with asyncio.timeout_at(deadline):
                await self.controls.put((kind, ident, deadline, sent))
        except asyncio.TimeoutError:
            await self.close()
            raise StreamClosed() from None
        return sent, deadline

    async def send_controls(self):
        try:
            while True:
                kind, ident, deadline, sent = await self.controls.get()
                await self.frame(kind, ident, deadline=deadline)
                sent.set()
        except (OSError, asyncio.TimeoutError, StreamClosed):
            await self.close()

    async def open(self, authority):
        if (self.on_open or self.closed or len(self.streams) >= MAX_STREAMS or
                len(self.closers) >= MAX_STREAMS):
            raise StreamClosed()
        if not 0 < len(authority) <= MAX_OPEN or self.next_id > 0xffffffff:
            raise ProtocolError()
        ident = self.next_id
        self.next_id += 1
        stream = Stream(self, ident)
        self.streams[ident] = stream
        try:
            await self.frame(OPEN, ident, authority)
            await stream.wait_ready()
            return stream
        except BaseException:
            await stream.close()
            raise

    async def end_stream(self, stream, remove=True):
        async with stream.changed:
            stream.closed = True
            stream.ready.set()
            self.queued -= len(stream.buffer)
            stream.buffer.clear()
            stream.changed.notify_all()
        if remove:
            self.streams.pop(stream.ident, None)

    async def serve(self, stream, authority):
        try:
            async with asyncio.timeout(12 * 60 * 60):
                await self.on_open(stream, authority)
        except (OSError, StreamClosed, asyncio.TimeoutError):
            pass
        finally:
            await stream.close()

    async def dispatch(self, kind, ident, payload):
        if not ident:
            raise ProtocolError()
        if kind == OPEN:
            if not self.on_open or ident != self.last_id + 1 or len(self.streams) >= MAX_STREAMS:
                raise ProtocolError()
            if len(self.tasks) >= MAX_STREAMS or len(self.closers) >= MAX_STREAMS:
                raise ProtocolError()
            self.last_id = ident
            stream = Stream(self, ident)
            self.streams[ident] = stream
            task = asyncio.create_task(self.serve(stream, payload))
            stream.worker = task
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
            return
        stream = self.streams.get(ident)
        if stream is None:
            # CLOSE and returned credit may cross in flight. Only these two
            # idempotent terminal frames for a known retired ID are harmless.
            retired = ident <= (self.last_id if self.on_open else self.next_id - 1)
            if retired and kind in (CLOSE, WINDOW_UPDATE):
                return
            raise ProtocolError()
        acknowledge = False
        async with stream.changed:
            if kind in (OPEN_OK, OPEN_ERR):
                if self.on_open or stream.response_received:
                    raise ProtocolError()
                stream.response_received = True
                if kind == OPEN_OK:
                    stream.opened = True
                else:
                    if payload not in (b'denied', b'unavailable'):
                        raise ProtocolError()
                    stream.error = payload
                stream.ready.set()
            elif kind == DATA:
                if not stream.opened or stream.remote_eof or stream.remote_closed:
                    raise ProtocolError()
                if len(payload) > stream.receive_credit or self.queued + len(payload) > MAX_SESSION:
                    raise ProtocolError()
                stream.receive_credit -= len(payload)
                if not stream.closed:
                    stream.buffer.extend(payload)
                    self.queued += len(payload)
            elif kind == HALF_CLOSE:
                if not stream.opened or stream.remote_eof:
                    raise ProtocolError()
                stream.remote_eof = True
            elif kind == WINDOW_UPDATE:
                amount = struct.unpack('!I', payload)[0]
                if not stream.opened or amount == 0 or stream.credit + amount > WINDOW:
                    raise ProtocolError()
                stream.credit += amount
            elif kind == CLOSE:
                stream.remote_closed = True
                stream.closed = True
                stream.ready.set()
                stream.remote_done.set()
                if stream.close_sent:
                    self.streams.pop(ident, None)
                else:
                    stream.close_sent = True
                    acknowledge = True
                    self.streams.pop(ident, None)
                self.queued -= len(stream.buffer)
                stream.buffer.clear()
                if stream.worker and not stream.worker.done():
                    stream.worker.cancel()
            else:
                raise ProtocolError()
            stream.changed.notify_all()
        # The receiver itself provides bounded backpressure. Never wait for
        # queue space while holding a stream lock or spawn enqueue tasks.
        if stream.remote_closed and stream.worker:
            # Reclaim the cancelled worker before admitting another OPEN.
            # Buffered OPEN/CLOSE bursts must not turn cancellation latency
            # into an apparent violation of the outstanding-stream limit.
            await asyncio.gather(stream.worker, return_exceptions=True)
        if acknowledge:
            await self.queue_control(CLOSE, ident)

    async def receive(self):
        try:
            while True:
                # Quiet sessions retain their sole preconnected channel. Once a
                # frame starts, one absolute deadline bounds header and payload.
                first = await self.reader.readexactly(1)
                async with asyncio.timeout(FRAME_TIMEOUT):
                    raw = first + await self.reader.readexactly(HEADER.size - 1)
                    kind, ident, size = HEADER.unpack(raw)
                    limits = {OPEN: (1, MAX_OPEN), OPEN_OK: (0, 0), OPEN_ERR: (1, 11),
                              DATA: (1, MAX_DATA), HALF_CLOSE: (0, 0), CLOSE: (0, 0), WINDOW_UPDATE: (4, 4)}
                    if kind not in limits or not limits[kind][0] <= size <= limits[kind][1]:
                        raise ProtocolError()
                    payload = await self.reader.readexactly(size) if size else b''
                await self.dispatch(kind, ident, payload)
        except (ProtocolError, asyncio.IncompleteReadError, OSError, asyncio.TimeoutError, StreamClosed):
            if self.audit:
                self.audit.record('transport-closed')
        finally:
            await self.close()

    async def close(self):
        if self.closed:
            return
        self.closed = True
        self.writer.close()
        for stream in list(self.streams.values()):
            stream.remote_done.set()
            await self.end_stream(stream)
        current = asyncio.current_task()
        pending = self.tasks | self.closers
        for task in tuple(pending):
            if task is not current:
                task.cancel()
        if pending:
            await asyncio.gather(*(t for t in pending if t is not current), return_exceptions=True)
        if self.receiver and self.receiver is not current:
            self.receiver.cancel()
            await asyncio.gather(self.receiver, return_exceptions=True)
        if self.control_sender and self.control_sender is not current:
            self.control_sender.cancel()
            await asyncio.gather(self.control_sender, return_exceptions=True)
        while not self.controls.empty():
            self.controls.get_nowait()


async def bridge(stream, reader, writer):
    async def outgoing():
        while True:
            data = await bounded(reader.read(MAX_DATA), IDLE_TIMEOUT)
            if not data:
                await stream.eof()
                return
            await stream.send(data)

    async def incoming():
        while True:
            data = await stream.read()
            if not data:
                if writer.can_write_eof():
                    writer.write_eof()
                return
            writer.write(data)
            await bounded(writer.drain(), WRITE_TIMEOUT)

    tasks = [asyncio.create_task(outgoing()), asyncio.create_task(incoming())]
    try:
        await bounded(asyncio.gather(*tasks), 12 * 60 * 60)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
