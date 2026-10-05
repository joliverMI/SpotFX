"""A userspace link emulator: a TCP proxy that adds one-way delay, jitter and
a bandwidth cap in each direction, with a bounded queue so a slow link pushes
back on the sender (as a real path does) instead of buffering forever.

It shapes raw TCP, so HTTP and WebSocket traffic of BOTH systems under test
go through the identical model. It is an emulation, not his real link.

  python linkemu.py --listen 9201 --target 9110 --rtt-ms 80 --jitter-ms 15 --down-kbps 4000 --up-kbps 2000
"""
from __future__ import annotations

import argparse
import asyncio
import random
import socket

CHUNK = 4096
QUEUE_S = 0.30          # how much backlog (seconds of link time) the "router" holds


class Counter:
    def __init__(self) -> None:
        self.down = 0
        self.up = 0
        self.writers = []

    def close_all(self) -> None:
        """Drop every proxied connection (Server.wait_closed would wait for them forever)."""
        for w in self.writers:
            try:
                w.close()
            except Exception:
                pass
        self.writers.clear()


async def pump(reader, writer, *, delay_s: float, jitter_s: float, rate_bps: float,
               count) -> None:
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()
    link_free = loop.time()
    last_arrival = 0.0

    async def deliver() -> None:
        while True:
            item = await q.get()
            if item is None:
                break
            due, data = item
            wait = due - loop.time()
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                writer.write(data)
                await writer.drain()
            except Exception:
                break
        try:
            writer.close()
        except Exception:
            pass

    task = asyncio.create_task(deliver())
    try:
        while True:
            data = await reader.read(CHUNK)
            if not data:
                break
            count(len(data))
            now = loop.time()
            if rate_bps > 0:
                tx_done = max(now, link_free) + len(data) * 8.0 / rate_bps
                link_free = tx_done
            else:
                tx_done = now
            arrival = tx_done + delay_s + (abs(random.gauss(0.0, jitter_s)) if jitter_s else 0.0)
            arrival = max(arrival, last_arrival)       # TCP stays in order
            last_arrival = arrival
            q.put_nowait((arrival, data))
            backlog = link_free - now
            if backlog > QUEUE_S:                       # queue full: stop reading -> backpressure
                await asyncio.sleep(backlog - QUEUE_S)
    except Exception:
        pass
    finally:
        q.put_nowait(None)
        await task


async def serve(listen: int, target: int, rtt_ms: float, jitter_ms: float,
                down_kbps: float, up_kbps: float, counter: Counter | None = None):
    counter = counter or Counter()
    one_way = rtt_ms / 2000.0
    jit = jitter_ms / 1000.0

    async def handle(creader, cwriter) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 32 * 1024)
        sock.setblocking(False)
        try:
            await asyncio.get_running_loop().sock_connect(sock, ("127.0.0.1", target))
            sreader, swriter = await asyncio.open_connection(sock=sock)
        except Exception:
            cwriter.close()
            return

        counter.writers += [cwriter, swriter]

        def cd(n): counter.down += n
        def cu(n): counter.up += n
        await asyncio.gather(
            pump(sreader, cwriter, delay_s=one_way, jitter_s=jit,
                 rate_bps=down_kbps * 1000.0, count=cd),
            pump(creader, swriter, delay_s=one_way, jitter_s=jit,
                 rate_bps=up_kbps * 1000.0, count=cu),
        )

    server = await asyncio.start_server(handle, "127.0.0.1", listen)
    return server, counter


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen", type=int, required=True)
    ap.add_argument("--target", type=int, required=True)
    ap.add_argument("--rtt-ms", type=float, default=0)
    ap.add_argument("--jitter-ms", type=float, default=0)
    ap.add_argument("--down-kbps", type=float, default=0)
    ap.add_argument("--up-kbps", type=float, default=0)
    a = ap.parse_args()

    async def _main():
        server, _ = await serve(a.listen, a.target, a.rtt_ms, a.jitter_ms, a.down_kbps, a.up_kbps)
        async with server:
            await server.serve_forever()
    asyncio.run(_main())
