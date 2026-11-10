"""Confined loopback CONNECT adapter over the bootstrap's sole data descriptor."""
import asyncio
import os
import signal
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mux import Channel, MAX_STREAMS, ProtocolError, StreamClosed, bridge


class Relay:
    def __init__(self, channel):
        self.channel = channel
        self.active = 0

    async def handle(self, reader, writer):
        if self.active >= MAX_STREAMS or self.channel.closed:
            writer.close()
            return
        self.active += 1
        stream = None
        established = False
        try:
            request = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 10)
            if len(request) > 8192:
                raise ProtocolError()
            # The trusted proxy independently validates the exact authority.
            parts = request.split(b'\r\n', 1)[0].split(b' ')
            if len(parts) != 3 or parts[0] != b'CONNECT' or parts[2] not in (b'HTTP/1.0', b'HTTP/1.1'):
                raise ProtocolError()
            stream = await self.channel.open(parts[1])
            writer.write(b'HTTP/1.1 200 Connection established\r\n\r\n')
            await writer.drain()
            established = True
            await bridge(stream, reader, writer)
        except (ProtocolError, StreamClosed, OSError, asyncio.TimeoutError,
                asyncio.LimitOverrunError, asyncio.IncompleteReadError):
            if not established:
                writer.write(b'HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
                try:
                    await writer.drain()
                except OSError:
                    pass
        finally:
            writer.close()
            self.active -= 1
            if stream:
                await stream.close()


async def run(channel_socket, ready):
    reader, writer = await asyncio.open_connection(sock=channel_socket, limit=65536)
    channel = await Channel(reader, writer).start()
    relay = Relay(channel)
    server = await asyncio.start_server(relay.handle, '127.0.0.1', 18080, limit=8192, backlog=64)
    os.write(ready, b'1')
    os.close(ready)
    try:
        async with server:
            await channel.receiver
    finally:
        await channel.close()


if __name__ == '__main__':
    if len(sys.argv) < 2 or sys.argv[1][0] != '/':
        sys.exit('relay requires an absolute application path')
    channel_socket = socket.socket(fileno=3)
    channel_socket.setblocking(False)
    ready_read, ready_write = os.pipe2(os.O_CLOEXEC)
    pid = os.fork()
    if pid == 0:
        os.close(ready_read)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
        try:
            asyncio.run(run(channel_socket, ready_write))
        except (OSError, ProtocolError, StreamClosed, asyncio.TimeoutError, asyncio.IncompleteReadError):
            pass
        finally:
            os._exit(78)
    channel_socket.close()
    os.close(ready_write)
    # Bound pre-exec readiness and never execute the application if handshake/bind failed.
    import select
    available, _, _ = select.select([ready_read], [], [], 15)
    success = bool(available) and os.read(ready_read, 1) == b'1'
    os.close(ready_read)
    if not success:
        os.kill(pid, signal.SIGTERM)
        os.waitpid(pid, 0)
        sys.exit('relay preparation failed; restricted startup stopped')
    os.execv(sys.argv[1], sys.argv[1:])
