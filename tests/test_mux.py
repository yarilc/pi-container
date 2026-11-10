"""Bounded transport, state-machine and cross-stream isolation tests."""
import asyncio
import os
from pathlib import Path
import random
import socket
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'network'))
import mux
import proxy
import relay
from unittest.mock import AsyncMock, MagicMock, patch


class MuxTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Avoid traceback/source inspection on the Windows bind for every task.
        asyncio.get_running_loop().set_debug(False)
        self.peers = []
        self.errors = []
        self.block = asyncio.Event()
        self.audit = type('Audit', (), {'record': lambda _, *args: self.errors.append(args)})()
        self.server = await asyncio.start_server(self.accept, '127.0.0.1', 0)
        reader, writer = await asyncio.open_connection('127.0.0.1', self.server.sockets[0].getsockname()[1])
        self.client = await mux.Channel(reader, writer).start()

    async def accept(self, reader, writer):
        channel = mux.Channel(reader, writer, on_open=self.echo, audit=self.audit)
        self.peers.append(channel)
        try:
            await channel.start()
            await channel.receiver
        except (mux.ProtocolError, asyncio.IncompleteReadError, OSError):
            pass
        finally:
            await channel.close()

    async def echo(self, stream, authority):
        stream.opened = True
        await stream.channel.frame(mux.OPEN_OK, stream.ident)
        if authority == b'blocked.test:443':
            await self.block.wait()
        while True:
            data = await stream.read()
            if not data:
                await stream.eof()
                return
            await stream.send(data)

    async def asyncTearDown(self):
        await self.client.close()
        for channel in self.peers:
            await channel.close()
        self.server.close()
        await self.server.wait_closed()

    async def test_more_than_concurrency_limit_sequential_requests(self):
        for index in range(80):
            stream = await self.client.open(b'allowed.test:443')
            value = str(index).encode()
            await stream.send(value)
            self.assertEqual(await stream.read(), value)
            await stream.eof()
            self.assertEqual(await stream.read(), b'')
            await stream.close()
        self.assertFalse(self.client.closed)
        self.assertEqual(self.client.queued, 0)
        self.assertEqual(self.client.streams, {})

    async def test_idle_before_first_open_preserves_channel(self):
        with patch.object(mux, 'IDLE_TIMEOUT', .1):
            # A fresh pair starts both receivers under the test deadline.
            await self.asyncTearDown()
            await self.asyncSetUp()
            await asyncio.sleep(.3)
            self.assertFalse(self.client.closed)
            self.assertFalse(self.peers[0].closed)
            stream = await self.client.open(b'allowed.test:443')
            await stream.send(b'resumed')
            self.assertEqual(await stream.read(), b'resumed')
            await stream.close()

    async def test_idle_between_opens_preserves_channel(self):
        with patch.object(mux, 'IDLE_TIMEOUT', .1):
            stream = await self.client.open(b'allowed.test:443')
            await stream.close()
            await asyncio.sleep(.3)
            self.assertFalse(self.client.closed)
            self.assertFalse(self.peers[0].closed)
            stream = await self.client.open(b'allowed.test:443')
            await stream.send(b'again')
            self.assertEqual(await stream.read(), b'again')
            await stream.close()

    async def wire_pair(self, server_side):
        left, right = socket.socketpair()
        left.setblocking(False)
        right.setblocking(False)
        reader, writer = await asyncio.open_connection(sock=left)
        raw_reader, raw_writer = await asyncio.open_connection(sock=right)
        channel = mux.Channel(reader, writer, on_open=self.echo if server_side else None)
        self.addAsyncCleanup(channel.close)
        self.addCleanup(raw_writer.close)
        raw_writer.write(mux.MAGIC)
        await channel.start()
        self.assertEqual(await raw_reader.readexactly(len(mux.MAGIC)), mux.MAGIC)
        return channel, raw_writer

    async def test_partial_frames_have_absolute_deadline_in_both_directions(self):
        for server_side in (False, True):
            for case in ('header', 'payload', 'trickle', 'shared-budget'):
                with self.subTest(server_side=server_side, case=case):
                    channel, writer = await self.wire_pair(server_side)
                    with patch.object(mux, 'FRAME_TIMEOUT', .2):
                        header = mux.HEADER.pack(mux.DATA, 1, 4)
                        writer.write(header[:1] if case != 'payload' else header + b'x')
                        await writer.drain()
                        started = asyncio.get_running_loop().time()
                        if case == 'trickle':
                            for byte in header[1:4]:
                                await asyncio.sleep(.04)
                                writer.write(bytes([byte]))
                                await writer.drain()
                        elif case == 'shared-budget':
                            await asyncio.sleep(.14)
                            writer.write(header[1:] + b'x')
                            await writer.drain()
                        await asyncio.wait_for(channel.receiver, .16 if case == 'shared-budget' else 1)
                        self.assertTrue(channel.closed)
                        self.assertLess(asyncio.get_running_loop().time() - started, .5)

    async def test_valid_fragmentation_in_both_directions(self):
        for server_side in (False, True):
            channel, writer = await self.wire_pair(server_side)
            channel.dispatch = AsyncMock()
            value = mux.HEADER.pack(mux.DATA, 1, 4) + b'data'
            with patch.object(mux, 'FRAME_TIMEOUT', 1):
                for byte in value:
                    writer.write(bytes([byte]))
                    await writer.drain()
                    await asyncio.sleep(.002)
                for _ in range(100):
                    if channel.dispatch.await_count:
                        break
                    await asyncio.sleep(.005)
                channel.dispatch.assert_awaited_once_with(mux.DATA, 1, b'data')
                self.assertFalse(channel.closed)
            await channel.close()

    async def test_idle_stream_expiry_preserves_channel_and_reuse(self):
        stream = await self.client.open(b'allowed.test:443')
        with patch.object(mux, 'IDLE_TIMEOUT', .1):
            # Wake the echo read once so its next read uses the test timeout.
            await stream.send(b'active')
            self.assertEqual(await stream.read(), b'active')
            await asyncio.wait_for(stream.remote_done.wait(), 2)
        self.assertFalse(self.client.closed)
        self.assertFalse(self.peers[0].closed)
        self.assertEqual(self.client.streams, {})
        following = await self.client.open(b'allowed.test:443')
        await following.send(b'next')
        self.assertEqual(await following.read(), b'next')
        await following.close()

    async def test_quiet_receiver_eof_and_cancellation_release_resources(self):
        for server_side in (False, True):
            for cancel in (False, True):
                channel, writer = await self.wire_pair(server_side)
                await asyncio.sleep(.01)
                if cancel:
                    channel.receiver.cancel()
                else:
                    writer.close()
                    await writer.wait_closed()
                await asyncio.wait_for(asyncio.gather(channel.receiver, return_exceptions=True), 2)
                self.assertTrue(channel.closed)
                self.assertTrue(channel.writer.is_closing())
                self.assertTrue(channel.control_sender.done())
                self.assertFalse(channel.streams)

    async def test_actual_relay_listener_survives_idle_and_stops_on_peer_loss(self):
        left, right = socket.socketpair()
        left.setblocking(False)
        right.setblocking(False)
        reader, writer = await asyncio.open_connection(sock=right)
        peer = mux.Channel(reader, writer, on_open=self.echo)
        self.addAsyncCleanup(peer.close)
        ready_read, ready_write = os.pipe()
        self.addCleanup(os.close, ready_read)
        servers = []
        start_server = asyncio.start_server

        async def ephemeral_server(handler, host, port, **kwargs):
            self.assertEqual((host, port), ('127.0.0.1', 18080))
            server = await start_server(handler, host, 0, **kwargs)
            servers.append(server)
            return server

        with patch.object(mux, 'IDLE_TIMEOUT', .1), patch.object(asyncio, 'start_server', ephemeral_server):
            running = asyncio.create_task(relay.run(left, ready_write))
            async def stop_relay():
                running.cancel()
                await asyncio.gather(running, return_exceptions=True)
            self.addAsyncCleanup(stop_relay)
            await peer.start()
            self.assertEqual(await asyncio.wait_for(asyncio.to_thread(os.read, ready_read, 1), 2), b'1')
            address = servers[0].sockets[0].getsockname()
            await asyncio.sleep(.3)
            self.assertFalse(running.done())
            client_reader, client_writer = await asyncio.open_connection(*address)
            self.addCleanup(client_writer.close)
            client_writer.write(b'CONNECT allowed.test:443 HTTP/1.1\r\n\r\n')
            await client_writer.drain()
            response = await asyncio.wait_for(client_reader.readuntil(b'\r\n\r\n'), 2)
            self.assertIn(b'200 Connection established', response)
            client_writer.write(b'relay-resumed')
            await client_writer.drain()
            self.assertEqual(await asyncio.wait_for(client_reader.readexactly(13), 2), b'relay-resumed')
            self.assertEqual(peer.last_id, 1)
            self.assertEqual(len(servers), 1)
            await peer.close()
            await asyncio.wait_for(running, 2)
            self.assertFalse(servers[0].is_serving())
            with self.assertRaises(ConnectionRefusedError):
                await asyncio.open_connection(*address)

    async def test_concurrent_streams_do_not_mix_data(self):
        async def exchange(index):
            stream = await self.client.open(b'allowed.test:443')
            payload = bytes([index]) * 16384
            await stream.send(payload)
            self.assertEqual(await stream.read(), payload)
            await stream.close()
        await asyncio.wait_for(asyncio.gather(*(exchange(i) for i in range(64))), 30)
        self.assertFalse(self.client.closed)

    async def test_backpressure_is_bounded_and_other_streams_progress(self):
        blocked = await self.client.open(b'blocked.test:443')
        sender = asyncio.create_task(blocked.send(b'x' * (mux.WINDOW + mux.MAX_DATA)))
        await asyncio.sleep(0.05)
        self.assertFalse(sender.done())
        self.assertLessEqual(self.peers[0].queued, mux.WINDOW)
        normal = await self.client.open(b'allowed.test:443')
        await normal.send(b'other-stream')
        self.assertEqual(await normal.read(), b'other-stream')
        await normal.close()
        sender.cancel()
        await asyncio.gather(sender, return_exceptions=True)
        await blocked.close()
        self.assertFalse(self.client.closed)

    async def test_channel_death_wakes_blocked_clients(self):
        stream = await self.client.open(b'blocked.test:443')
        pending = asyncio.create_task(stream.read())
        await self.peers[0].close()
        with self.assertRaises(mux.StreamClosed):
            await asyncio.wait_for(pending, 2)

    async def test_missing_close_ack_preserves_other_stream_and_delayed_ack_releases_slot(self):
        for server_side in (False, True):
            with self.subTest(server_side=server_side):
                await self.asyncTearDown()
                await self.asyncSetUp()
                first = await self.client.open(b'allowed.test:443')
                healthy = await self.client.open(b'allowed.test:443')
                local = self.peers[0] if server_side else self.client
                remote = self.client if server_side else self.peers[0]
                closing = local.streams[first.ident]
                original = remote.frame

                async def withhold(kind, ident, payload=b'', **kwargs):
                    if kind != mux.CLOSE or ident != first.ident:
                        await original(kind, ident, payload, **kwargs)

                started = asyncio.get_running_loop().time()
                with patch.object(remote, 'frame', withhold):
                    await asyncio.wait_for(closing.close(), 12)
                self.assertGreaterEqual(asyncio.get_running_loop().time() - started, 9.9)
                self.assertFalse(local.closed)
                self.assertIn(first.ident, local.streams)
                self.assertFalse(closing.buffer)
                await healthy.send(b'still-alive')
                self.assertEqual(await healthy.read(), b'still-alive')
                await original(mux.CLOSE, first.ident)
                await asyncio.wait_for(closing.remote_done.wait(), 2)
                self.assertNotIn(first.ident, local.streams)
                following = await self.client.open(b'allowed.test:443')
                await following.send(b'following')
                self.assertEqual(await following.read(), b'following')
                await asyncio.gather(healthy.close(), following.close())

    async def test_missing_acks_bound_capacity_and_concurrent_close_ownership(self):
        streams = [await self.client.open(b'allowed.test:443') for _ in range(mux.MAX_STREAMS)]
        original = self.peers[0].frame

        async def withhold(kind, ident, payload=b'', **kwargs):
            if kind != mux.CLOSE:
                await original(kind, ident, payload, **kwargs)

        with patch.object(self.peers[0], 'frame', withhold), patch.object(mux, 'CLOSE_TIMEOUT', .03):
            await asyncio.gather(*(s.close() for s in streams[:-1]), streams[0].close())
        self.assertEqual(len(self.client.streams), mux.MAX_STREAMS)
        self.assertFalse(self.client.closers)
        self.assertEqual(self.client.queued, 0)
        with self.assertRaises(mux.StreamClosed):
            await self.client.open(b'allowed.test:443')
        await streams[-1].send(b'capacity-exhausted-but-alive')
        self.assertEqual(await streams[-1].read(), b'capacity-exhausted-but-alive')
        await original(mux.CLOSE, streams[0].ident)
        await asyncio.wait_for(streams[0].remote_done.wait(), 1)
        new = await self.client.open(b'allowed.test:443')
        await asyncio.gather(new.close(), streams[-1].close())
        self.assertFalse(self.client.closed)

    async def test_closing_stream_validates_crossing_data_credit_and_eof(self):
        stream = await self.client.open(b'allowed.test:443')
        original = self.peers[0].frame

        async def withhold(kind, ident, payload=b'', **kwargs):
            if kind not in (mux.CLOSE, mux.WINDOW_UPDATE):
                await original(kind, ident, payload, **kwargs)

        with patch.object(self.peers[0], 'frame', withhold), patch.object(mux, 'CLOSE_TIMEOUT', .02):
            await stream.send(b'queued')
            async with asyncio.timeout(1):
                while not stream.buffer:
                    await asyncio.sleep(.001)
            await stream.close()
        await original(mux.WINDOW_UPDATE, stream.ident, struct.pack('!I', len(b'queued')))
        await original(mux.DATA, stream.ident, b'crossing')
        await original(mux.HALF_CLOSE, stream.ident)
        # The following terminal frame provides an ordered processing barrier.
        await original(mux.CLOSE, stream.ident)
        await asyncio.wait_for(stream.remote_done.wait(), 1)
        self.assertEqual(stream.receive_credit, mux.WINDOW - len(b'queuedcrossing'))
        self.assertEqual(stream.credit, mux.WINDOW)
        self.assertFalse(stream.buffer)
        self.assertEqual(self.client.queued, 0)
        self.assertFalse(self.client.closed)
        await original(mux.DATA, stream.ident, b'fully-retired')
        await asyncio.wait_for(self.client.receiver, 1)
        self.assertTrue(self.client.closed)

    async def test_retained_closing_state_rejects_invalid_transitions(self):
        for invalid in ('credit', 'after-eof', 'duplicate-response', 'over-receive-credit'):
            with self.subTest(invalid=invalid):
                await self.asyncTearDown()
                await self.asyncSetUp()
                stream = await self.client.open(b'allowed.test:443')
                original = self.peers[0].frame
                async def withhold(kind, ident, payload=b'', **kwargs):
                    if kind != mux.CLOSE:
                        await original(kind, ident, payload, **kwargs)
                with patch.object(self.peers[0], 'frame', withhold), patch.object(mux, 'CLOSE_TIMEOUT', .02):
                    await stream.close()
                if invalid == 'credit':
                    await original(mux.WINDOW_UPDATE, stream.ident, struct.pack('!I', 1))
                elif invalid == 'after-eof':
                    await original(mux.HALF_CLOSE, stream.ident)
                    await original(mux.DATA, stream.ident, b'x')
                elif invalid == 'duplicate-response':
                    await original(mux.OPEN_OK, stream.ident)
                else:
                    for _ in range(mux.WINDOW // mux.MAX_DATA + 1):
                        await original(mux.DATA, stream.ident, b'x' * mux.MAX_DATA)
                await asyncio.wait_for(self.client.receiver, 1)
                self.assertTrue(self.client.closed)
                self.assertEqual(self.client.queued, 0)

    async def test_control_burst_recovers_with_fixed_queue_and_no_enqueue_tasks(self):
        channel, writer = await self.wire_pair(True)
        await channel.write_lock.acquire()
        try:
            for ident in range(1, 70):
                value = b'allowed.test:443'
                writer.write(mux.HEADER.pack(mux.OPEN, ident, len(value)) + value +
                             mux.HEADER.pack(mux.CLOSE, ident, 0))
                await writer.drain()
            # Coalesced frames must reclaim cancelled workers as well as
            # tolerate queue pressure; no scheduling delay between requests.
            await asyncio.sleep(.05)
            self.assertFalse(channel.closed)
            self.assertEqual(channel.controls.qsize(), mux.MAX_STREAMS)
            self.assertLessEqual(len(channel.tasks), mux.MAX_STREAMS)
            self.assertLessEqual(len(channel.closers), mux.MAX_STREAMS)
        finally:
            channel.write_lock.release()
        for _ in range(200):
            if channel.last_id == 69 and channel.controls.empty():
                break
            await asyncio.sleep(.005)
        self.assertEqual(channel.last_id, 69)
        self.assertTrue(channel.controls.empty())
        self.assertFalse(channel.closed)

    async def test_shared_write_deadline_includes_lock_and_drain(self):
        for blocked_at in ('lock', 'drain', 'queue'):
            with self.subTest(blocked_at=blocked_at):
                channel, writer = await self.wire_pair(False)
                with patch.object(mux, 'WRITE_TIMEOUT', .05):
                    if blocked_at == 'queue':
                        channel.control_sender.cancel()
                        await asyncio.gather(channel.control_sender, return_exceptions=True)
                        for _ in range(mux.MAX_STREAMS):
                            await channel.queue_control(mux.CLOSE, 1)
                        operation = channel.queue_control(mux.CLOSE, 1)
                    elif blocked_at == 'lock':
                        await channel.write_lock.acquire()
                        operation = channel.frame(mux.CLOSE, 1)
                    else:
                        async def stalled():
                            await asyncio.Event().wait()
                        channel.writer.drain = stalled
                        operation = channel.frame(mux.CLOSE, 1)
                    with self.assertRaises(mux.StreamClosed):
                        await asyncio.wait_for(operation, 1)
                self.assertTrue(channel.closed)
                self.assertFalse(channel.streams)
                self.assertTrue(channel.controls.empty())
                if channel.write_lock.locked():
                    channel.write_lock.release()

    async def test_caller_cancel_during_close_does_not_drop_required_control(self):
        stream = await self.client.open(b'allowed.test:443')
        await self.client.write_lock.acquire()
        closing = asyncio.create_task(stream.close())
        await asyncio.sleep(.02)
        closing.cancel()
        await asyncio.gather(closing, return_exceptions=True)
        self.assertFalse(self.client.closed)
        self.assertEqual(len(self.client.closers), 1)
        self.client.write_lock.release()
        await asyncio.wait_for(stream.remote_done.wait(), 1)
        await asyncio.sleep(0)
        self.assertNotIn(stream.ident, self.client.streams)
        self.assertFalse(self.client.closed)

    async def test_close_cancellation_at_queue_and_drain_and_session_shutdown(self):
        for phase in ('queue', 'drain'):
            for shutdown in (False, True):
                with self.subTest(phase=phase, shutdown=shutdown):
                    await self.asyncTearDown()
                    await self.asyncSetUp()
                    retired = await self.client.open(b'allowed.test:443')
                    await retired.close()
                    stream = await self.client.open(b'allowed.test:443')
                    gate = asyncio.Event()
                    drain = self.client.writer.drain
                    async def paused():
                        await gate.wait()
                        await drain()
                    self.client.writer.drain = paused
                    if phase == 'queue':
                        for _ in range(mux.MAX_STREAMS + 1):
                            await self.client.queue_control(mux.CLOSE, retired.ident)
                            await asyncio.sleep(0)
                    closing = asyncio.create_task(stream.close())
                    await asyncio.sleep(.02)
                    closing.cancel()
                    await asyncio.gather(closing, return_exceptions=True)
                    self.assertLessEqual(len(self.client.closers), 1)
                    if shutdown:
                        await asyncio.wait_for(self.client.close(), 1)
                        self.assertTrue(all(t.done() for t in self.client.closers))
                        self.assertTrue(self.client.controls.empty())
                        self.assertFalse(self.client.streams)
                    else:
                        gate.set()
                        await asyncio.wait_for(stream.remote_done.wait(), 1)
                        self.assertNotIn(stream.ident, self.client.streams)
                        healthy = await self.client.open(b'allowed.test:443')
                        await healthy.send(b'cancel-recovered')
                        self.assertEqual(await healthy.read(), b'cancel-recovered')
                        await healthy.close()
                        self.assertFalse(self.client.closed)

    async def test_outstanding_open_response_can_cross_cancelled_open(self):
        channel, writer = await self.wire_pair(False)
        # A raw peer withholds OPEN_OK until local cancellation is complete.
        with patch.object(mux, 'CLOSE_TIMEOUT', .02):
            opening = asyncio.create_task(channel.open(b'allowed.test:443'))
            await asyncio.sleep(.01)
            opening.cancel()
            await asyncio.gather(opening, return_exceptions=True)
        stream = channel.streams[1]
        writer.write(mux.HEADER.pack(mux.OPEN_OK, 1, 0) +
                     mux.HEADER.pack(mux.DATA, 1, 1) + b'x' +
                     mux.HEADER.pack(mux.CLOSE, 1, 0))
        await writer.drain()
        await asyncio.wait_for(stream.remote_done.wait(), 1)
        self.assertTrue(stream.response_received)
        self.assertFalse(channel.closed)
        self.assertEqual(channel.queued, 0)

    async def test_relay_releases_socket_and_handler_when_close_is_cancelled(self):
        stream = MagicMock()
        stream.close = AsyncMock(side_effect=asyncio.CancelledError)
        channel = MagicMock(closed=False)
        channel.open = AsyncMock(return_value=stream)
        adapter = relay.Relay(channel)
        reader = asyncio.StreamReader()
        reader.feed_data(b'CONNECT allowed.test:443 HTTP/1.1\r\n\r\n')
        writer = MagicMock()
        writer.drain = AsyncMock()
        with patch.object(relay, 'bridge', AsyncMock(side_effect=asyncio.CancelledError)):
            with self.assertRaises(asyncio.CancelledError):
                await adapter.handle(reader, writer)
        self.assertEqual(adapter.active, 0)
        writer.close.assert_called_once()
        stream.close.assert_awaited_once()

    async def test_malformed_lengths_versions_and_ids_close_channel(self):
        rng = random.Random(9731)
        cases = [b'x' * len(mux.MAGIC),
                 mux.MAGIC + mux.HEADER.pack(mux.DATA, 1, mux.MAX_DATA + 1),
                 mux.MAGIC + mux.HEADER.pack(mux.OPEN, 0, 1) + b'x',
                 mux.MAGIC + mux.HEADER.pack(mux.OPEN, 1, mux.MAX_OPEN + 1),
                 mux.MAGIC + mux.HEADER.pack(mux.DATA, 1, 1) + b'x',
                 mux.MAGIC + mux.HEADER.pack(mux.OPEN, 3, 1) + b'x']
        cases += [mux.MAGIC + mux.HEADER.pack(rng.randint(8, 255), rng.randint(0, 100), rng.randint(0, 0xffffffff)) for _ in range(50)]
        for wire in cases:
            reader, writer = await asyncio.open_connection('127.0.0.1', self.server.sockets[0].getsockname()[1])
            writer.write(wire)
            await writer.drain()
            self.assertEqual(await reader.readexactly(len(mux.MAGIC)), mux.MAGIC)
            self.assertEqual(await asyncio.wait_for(reader.read(), 2), b'')
            writer.close()
            await writer.wait_closed()

    async def test_invalid_credit_duplicate_open_and_state(self):
        stream = await self.client.open(b'allowed.test:443')
        await self.client.frame(mux.WINDOW_UPDATE, stream.ident, struct.pack('!I', mux.WINDOW + 1))
        await asyncio.wait_for(self.client.receiver, 2)
        self.assertTrue(self.client.closed)
        self.assertEqual(self.peers[0].queued, 0)

    async def test_reused_ids_invalid_transitions_and_credit_are_rejected(self):
        authority = b'allowed.test:443'
        frame = lambda kind, ident=1, data=b'': mux.HEADER.pack(kind, ident, len(data)) + data
        cases = [frame(mux.OPEN, data=authority),
                 frame(mux.WINDOW_UPDATE, data=struct.pack('!I', 0)),
                 frame(mux.WINDOW_UPDATE, data=struct.pack('!I', 0xffffffff)),
                 frame(mux.HALF_CLOSE) * 2,
                 frame(mux.HALF_CLOSE) + frame(mux.DATA, data=b'x'),
                 frame(mux.DATA, ident=2, data=b'x'),
                 frame(mux.OPEN_OK),
                 frame(mux.CLOSE, data=b'secret')]
        for invalid in cases:
            reader, writer = await asyncio.open_connection('127.0.0.1', self.server.sockets[0].getsockname()[1])
            writer.write(mux.MAGIC)
            await writer.drain()
            await reader.readexactly(len(mux.MAGIC))
            writer.write(frame(mux.OPEN, data=authority))
            await writer.drain()
            self.assertEqual(await reader.readexactly(mux.HEADER.size), mux.HEADER.pack(mux.OPEN_OK, 1, 0))
            writer.write(invalid)
            await writer.drain()
            await asyncio.wait_for(reader.read(), 2)
            writer.close()
            await writer.wait_closed()
        self.assertNotIn('secret', repr(self.errors))

    async def test_active_stream_limit_and_cancel_preserve_channel(self):
        streams = [await self.client.open(b'blocked.test:443') for _ in range(mux.MAX_STREAMS)]
        with self.assertRaises(mux.StreamClosed):
            await self.client.open(b'allowed.test:443')
        await streams.pop().close()
        normal = await self.client.open(b'allowed.test:443')
        await normal.send(b'reused-capacity')
        self.assertEqual(await normal.read(), b'reused-capacity')
        await normal.close()
        await asyncio.gather(*(stream.close() for stream in streams))
        self.assertFalse(self.client.closed)

    async def test_proxy_reauthorizes_every_logical_open_and_redacts(self):
        instance = proxy.Proxy({'destinations': [{'host': 'allowed.test', 'port': 443}]}, self.audit)
        server = await asyncio.start_server(instance.handle, '127.0.0.1', 0)
        reader, writer = await asyncio.open_connection('127.0.0.1', server.sockets[0].getsockname()[1])
        client = await mux.Channel(reader, writer).start()
        try:
            with patch('proxy.resolve') as resolve:
                for authority in (b'allowed.test.evil.test:443', b'allowed.test:80', b'user:secret@allowed.test:443', b'allowed.test:443/path?secret'):
                    with self.assertRaises(mux.StreamClosed):
                        await client.open(authority)
                resolve.assert_not_called()
            self.assertNotIn('secret', repr(self.errors))
            self.assertFalse(client.closed)
        finally:
            await client.close()
            server.close()
            await server.wait_closed()
