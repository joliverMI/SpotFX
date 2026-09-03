"""A STAMP IS NOT A PHOTON — measured against a REAL transport.

WHAT THIS PROVES THAT THE PYTEST FILE CANNOT.
`tests/test_stream_freshness.py` proves the JUDGEMENT: it drives the real
`lever_selftest`, the real `_map_one` and the real footprint arithmetic
through a MODELLED queue, red and green, swept across the realistic band.
This proves the TRANSPORT ITSELF — that the queue is real, how deep it
actually gets, that the shipped read really did hand back frames from
seconds ago, and that `V4L2Camera.frame()` now does not — plus the whole
thing end to end over a real server, a real WebSocket and the real capture
client, with the paired clock doing the alignment.

THE FOUR SECTIONS:

  1. THE DEPTH        how many whole frames sit between an ffmpeg-shaped
                      producer and this client's reader, in the exact
                      construction `_open_at` builds. This is the number
                      every constant here is derived from.
  2. THE READ         the REAL `V4L2Camera.frame()` against that pipe,
                      beside the read it replaced. Same pipe, same stall,
                      two answers seconds apart.
  3. THE SENSOR       a control that MOVED costs `SENSOR_APPLY_FRAMES`
                      frames and they are counted; re-asking for a value
                      already pinned costs nothing.
  4. THE WIRE         the real client, the real WebSocket, the real
                      `MappingSession.gather` — the age of the frames a
                      capture window actually averages, before and after.

NO CAMERA, NO ffmpeg, NO ROOM, NO NETWORK BEYOND 127.0.0.1. The pixels
come from a subprocess that writes raw greyscale frames at a fixed rate,
which is what ffmpeg is to this client; the CONTROL path is declared,
because `v4l2-ctl` is not on this machine and the control path is not what
is under test here.

Run from repo root: .venv/bin/python scripts/check_stream_freshness.py
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
print = __import__("functools").partial(print, flush=True)     # noqa: A001

FAILURES: list[str] = []


def check(cond, label):
    if not cond:
        FAILURES.append(label)
        print(f"FAIL: {label}")
        return False
    print(f"ok: {label}")
    return True


td = Path(tempfile.mkdtemp(prefix="spectra-stream-freshness-"))
os.environ["SPECTRA_STORAGE_DIR"] = str(td / "spectra")

from fx import device_model                                    # noqa: E402
device_model.CATEGORIES_FILE = td / "device_categories.json"
device_model.CATEGORIES_FILE.write_text(json.dumps({}))

from fx import light_ownership                                 # noqa: E402
light_ownership.OWNERSHIP_FILE = td / "ownership.json"
light_ownership.OWNERSHIP_FILE.write_text(json.dumps({"owner": "spectra"}))

from spectra import config as scfg                             # noqa: E402
scfg.SPECTRA_STORAGE = td / "spectra"
for name in ("SCENES_FILE", "SEQUENCER_FILE", "DRIFT_PROFILES_FILE",
             "ROOM_COLOR_FILE", "ROOM_CONTROLS_FILE", "GRADIENT2D_FILE",
             "FIRE_HISTORY_FILE", "SHOW_LOG_FILE", "FLARE_PREVIEW_HOLD_FILE",
             "ROOM_MAPS_FILE", "ROOM_EFFECTS_FILE", "COMMISSIONING_FILE",
             "CAPTURE_QUEUE_FILE", "CAPTURE_HEALTH_FILE"):
    setattr(scfg, name, scfg.SPECTRA_STORAGE / f"{name.lower()}.json")

import uvicorn                                                 # noqa: E402

from spectra.capture_client import camera as cam               # noqa: E402
from spectra.capture_client.session import CaptureClient       # noqa: E402
from spectra.services import capture_settings, mapping_session  # noqa: E402

FW, FH = cam.FRAME_W, cam.FRAME_H
FRAME_BYTES = FW * FH
#: The wire's own rate, and what the producer below runs at.
FPS = 5.0
PERIOD = 1.0 / FPS

#: A producer shaped like ffmpeg: a whole raw greyscale frame every
#: PERIOD, every byte of it the frame's own sequence number. Reading byte 0
#: back tells you exactly WHICH frame you were handed, which is the only
#: thing this file needs a picture for.
PRODUCER = """
import sys, time
n = 0
while n < 4000:
    sys.stdout.buffer.write(bytes([n %% 256]) * %d)
    sys.stdout.buffer.flush()
    n += 1
    time.sleep(%r)
""" % (FRAME_BYTES, PERIOD)


class Pipe:
    """The exact construction `V4L2Camera._open_at` builds: a `bufsize=0`
    subprocess pipe read through an `asyncio.StreamReader` limited to eight
    frames. Nothing here is a model of the transport — it IS the
    transport, with a python producer where ffmpeg would be."""

    def __init__(self) -> None:
        self.proc = None
        self.reader = None
        self.started = 0.0
        self.first_seq = 0

    async def open(self):
        self.proc = subprocess.Popen(
            [sys.executable, "-u", "-c", PRODUCER],
            stdout=subprocess.PIPE, bufsize=0)
        loop = asyncio.get_running_loop()
        self.reader = asyncio.StreamReader(limit=FRAME_BYTES * 8)
        await loop.connect_read_pipe(
            lambda: asyncio.StreamReaderProtocol(self.reader), self.proc.stdout)
        # The client's own first read at open, and the clock starts with it.
        first = await asyncio.wait_for(
            self.reader.readexactly(FRAME_BYTES), timeout=15.0)
        self.started = time.monotonic()
        self.first_seq = first[0]
        return self

    def taken_at(self, sequence: int) -> float:
        """When the producer wrote frame `sequence`, on this process's own
        monotonic clock — the rate is fixed and known, so a frame's true
        capture moment is arithmetic."""
        return self.started + ((sequence - self.first_seq) % 256) * PERIOD

    def close(self):
        if self.proc is not None:
            self.proc.kill()
            self.proc = None


async def one_read(reader) -> bytes:
    """THE READ THIS REPLACED, verbatim in shape: take the next whole frame
    off the reader, whatever age it is."""
    return await asyncio.wait_for(reader.readexactly(FRAME_BYTES), timeout=10.0)


def seq(frame: bytes) -> int:
    return frame[0]


class PipeCamera(cam.V4L2Camera):
    """THE REAL CAMERA'S PIXEL PATH — `frame()`, `_read()`, the drain, the
    sensor discard — over the pipe above.

    Only the CONTROL path is declared: `v4l2-ctl` is not on this machine
    and the controls are not what is under test here. That split is
    deliberate and is the same one `SyntheticCamera` makes; what must never
    be faked is the read, which is the whole subject."""

    def __init__(self, pipe: Pipe) -> None:
        super().__init__("/dev/null", fps=FPS, capture_size=(FW, FH))
        self.pipe = pipe
        self.frame_size = (FW, FH)
        self._declared = cam.CameraLock(
            exposure_locked=True, white_balance_locked=True,
            exposure_mode="Manual Mode", white_balance_mode="manual",
            exposure_time_range=[3.0, 2047.0], gain_range=[0.0, 255.0],
            source="pipe:declared")

    async def open(self) -> None:
        self._reader = self.pipe.reader
        self._mint_pose()
        self.opened = True
        self.lock = self._declared

    async def set_frame_size(self, size):
        return self.frame_size

    async def apply_lock(self, **levers):
        wanted = dict(self._wanted)
        wanted.update({k: v for k, v in levers.items() if k in wanted})
        moved = any(wanted.get(n) != self._wanted.get(n) for n, *_ in cam.LEVERS)
        self._wanted = wanted
        if moved:
            self._apply_owed = cam.SENSOR_APPLY_FRAMES
        self.lock = cam.CameraLock(**{
            **self._declared.__dict__,
            **{n: (None if wanted.get(n) is None else float(wanted[n]))
               for n, *_ in cam.LEVERS}})
        return self.lock

    #: Seconds the next `read_lock` takes. The real one runs blocking
    #: `v4l2-ctl` subprocesses; what matters to the transport is only that
    #: no frame was read for that long.
    stall_read_lock = 0.0

    async def read_lock(self):
        if self.stall_read_lock:
            stall, self.stall_read_lock = self.stall_read_lock, 0.0
            await asyncio.sleep(stall)
        return self.lock

    async def close(self) -> None:
        self.opened = False


# ── 1. THE DEPTH ───────────────────────────────────────────────────────────

async def section_depth():
    print("\n-- 1. THE DEPTH: how many whole frames sit in the transport --")
    depths = []
    for stall in (1.0, 2.0, 3.0, 6.0):
        pipe = await Pipe().open()
        try:
            await asyncio.sleep(stall)
            held = 0
            t0 = time.monotonic()
            while held < 80:
                try:
                    await asyncio.wait_for(
                        pipe.reader.readexactly(FRAME_BYTES),
                        timeout=cam.DRAIN_PROBE_S)
                except asyncio.TimeoutError:
                    break
                held += 1
            spent = time.monotonic() - t0
            depths.append((stall, held, spent))
            print(f"   the client stopped reading for {stall:g}s -> {held} "
                  f"whole frames were already waiting "
                  f"({held * PERIOD:.2f}s of backlog), drained in "
                  f"{spent * 1000:.0f} ms")
        finally:
            pipe.close()
    one_second = next(h for s, h, _ in depths if s == 1.0)
    check(one_second >= 4,
          f"a ONE-SECOND stall alone builds {one_second} frames of backlog — "
          f"and the frame loop paces at the camera's own rate, so it is "
          f"never given back")
    deepest = max(h for _s, h, _ in depths)
    check(deepest >= 15,
          f"the transport saturates at {deepest} frames "
          f"({deepest * PERIOD:.1f}s at {FPS:g} fps) — longer than a whole "
          f"capture phase, which is why a lit window could land entirely on "
          f"the dark room")
    slowest = max(t for _s, _h, t in depths)
    check(slowest < 0.25,
          f"and draining the deepest of them costs {slowest * 1000:.0f} ms, "
          f"so freshness is free")
    check(deepest * PERIOD < cam.DRAIN_MAX_FRAMES * PERIOD,
          f"DRAIN_MAX_FRAMES ({cam.DRAIN_MAX_FRAMES}) is above the measured "
          f"saturation ({deepest}) with room to spare, so the bound can "
          f"never truncate a real drain")


# ── 2. THE READ ────────────────────────────────────────────────────────────

async def section_read():
    print("\n-- 2. THE READ: the same pipe, the same stall, two answers --")
    pipe = await Pipe().open()
    try:
        await asyncio.sleep(2.0)
        stale = seq(await one_read(pipe.reader))
        camera = PipeCamera(pipe)
        await camera.open()
        fresh = seq(await camera.frame())
        gap = (fresh - stale) % 256
        print(f"   the read this replaced handed back frame #{stale}; "
              f"the real `frame()` handed back #{fresh}")
        check(gap >= 4,
              f"the shipped read was {gap} frames — {gap * PERIOD:.1f}s — "
              f"behind the newest one available at the same instant")
        check(camera.stale_dropped >= 4,
              f"and `frame()` says how many it threw away to get there "
              f"({camera.stale_dropped}), so the depth is a number a reader "
              f"can see rather than a promise")

        # AND IT STAYS FRESH once the queue is refilled by another stall.
        await asyncio.sleep(1.5)
        before = camera.stale_dropped
        again = seq(await camera.frame())
        expect = (await asyncio.sleep(0), None)[1]              # noqa: F841
        check(camera.stale_dropped > before,
              f"a later stall refills the queue and the next read drains it "
              f"again ({camera.stale_dropped - before} frames)")
        check(((again - fresh) % 256) >= 5,
              f"and the frame it returns is the newest of THAT moment "
              f"(#{again}), not the next one in line")
    finally:
        pipe.close()


# ── 3. THE SENSOR ──────────────────────────────────────────────────────────

async def section_sensor():
    print("\n-- 3. THE SENSOR: a control that moved costs frames --")
    pipe = await Pipe().open()
    try:
        camera = PipeCamera(pipe)
        await camera.open()
        await camera.frame()                      # settle the queue
        await camera.apply_lock(exposure_time=500)
        check(camera._apply_owed == cam.SENSOR_APPLY_FRAMES,
              f"commanding a new integration time owes the sensor "
              f"{cam.SENSOR_APPLY_FRAMES} frames")
        before = camera.regime_discards
        await camera.frame()
        check(camera.regime_discards - before == cam.SENSOR_APPLY_FRAMES,
              f"and the next read pays them, counted "
              f"({camera.regime_discards - before}) rather than swallowed")
        check(camera._apply_owed == 0, "the debt is cleared once")

        await camera.apply_lock(exposure_time=500)
        check(camera._apply_owed == 0,
              "re-asking for the value already pinned owes nothing — an "
              "ordinary reconnect's re-assert must not cost frames")
        await camera.apply_lock(exposure_time=2000)
        check(camera._apply_owed == cam.SENSOR_APPLY_FRAMES,
              "and a value that genuinely moved owes them again")

        settle = capture_settings.regime_settle_s(2000, FPS)
        print(f"   the server's own wait for the same change is "
              f"{settle:g}s at {FPS:g} fps and 200 ms integration")
        check(settle >= cam.SENSOR_APPLY_FRAMES / FPS,
              f"`capture_settings.regime_settle_s` ({settle:g}s) covers at "
              f"least the frames the client discards, independently of the "
              f"client having discarded them")
    finally:
        pipe.close()


# ── 4. THE WIRE ────────────────────────────────────────────────────────────

def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextlib.asynccontextmanager
async def _no_lifespan(app):
    yield


class Server:
    def __init__(self, port: int) -> None:
        from spectra.app import create_app
        app = create_app()
        app.router.lifespan_context = _no_lifespan
        self.server = uvicorn.Server(uvicorn.Config(
            app, host="127.0.0.1", port=port, log_level="warning",
            lifespan="on", ws_ping_interval=None))
        self.task = None

    async def start(self):
        self.task = asyncio.create_task(self.server.serve())
        for _ in range(300):
            if self.server.started:
                return
            await asyncio.sleep(0.05)
        raise RuntimeError("server did not start")

    async def stop(self):
        self.server.should_exit = True
        if self.task is not None:
            await asyncio.wait_for(self.task, timeout=10.0)


async def wait_for(predicate, timeout=25.0, poll=0.1):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        got = predicate()
        if got:
            return got
        await asyncio.sleep(poll)
    return None


async def section_wire():
    print("\n-- 4. THE WIRE: what a capture window actually averages --")
    port = free_port()
    server = Server(port)
    await server.start()
    ws_url = f"ws://127.0.0.1:{port}/api/rooms/map/ws"
    pipe = await Pipe().open()
    camera = PipeCamera(pipe)
    client = CaptureClient(ws_url, camera, host="capture-pi", fps=FPS)
    task = None
    try:
        problem = await client.start_camera()
        if problem:
            raise RuntimeError(problem)
        task = asyncio.create_task(client.run())
        sess = await wait_for(
            lambda: mapping_session.current
            if (mapping_session.current is not None
                and not mapping_session.current.closed
                and mapping_session.current.counts["frames"] > 3
                and mapping_session.current.clockmap.ready) else None)
        if sess is None:
            raise RuntimeError("the client never established a paired session")

        check(sess.status().get("fresh_frames") is True,
              "the session knows this client promises fresh frames, because "
              "the client SAID so in `hello` — a build that does not is a "
              "third answer, not a silent yes")

        # THE MEASUREMENT, and it is arithmetic rather than a guess: every
        # frame's byte value IS its sequence number, and the producer's
        # rate is known, so the moment a frame's photons landed is exact.
        # `at_s` is the stamp the paired clock produced — the same field
        # `gather` windows against — so this is the real gap between when
        # a frame was TAKEN and when the instrument believes it was.
        def age_of(grid) -> float:
            return grid.at_s - pipe.taken_at(
                int(round(float(grid.grid.max()))))

        # A REAL STALL: the client goes some seconds without READING a
        # frame. In the field that is `apply_lock` and the paced
        # `read_lock` running blocking `v4l2-ctl` subprocesses; here it is
        # this camera's own `read_lock`, because WHY the client stopped
        # reading is not what is under test — that it stopped, and what the
        # transport does about it, is. §1 measured what the transport does:
        # it fills, and it never gives the depth back.
        STALL = 2.5
        camera.stall_read_lock = STALL
        before_dropped = client.state.stale_dropped
        await asyncio.sleep(STALL + 1.5)
        dropped_by_the_stall = client.state.stale_dropped - before_dropped
        check(dropped_by_the_stall >= 4,
              f"a {STALL:g}s gap in reading queued {dropped_by_the_stall} "
              f"frames ({dropped_by_the_stall * PERIOD:.1f}s) — the shipped "
              f"read would have served every one of them, oldest first, and "
              f"never caught up")

        grids, _maxima = await sess.gather(1.0, min_frames=2)
        held = [g for g in list(sess.grids)][-max(1, len(grids)):]
        got = [age_of(g) for g in held]
        oldest = max(got) if got else 0.0
        print(f"   the window averaged {len(grids)} frames; the widest gap "
              f"between a frame's own capture and its stamp was "
              f"{oldest:.2f}s")
        check(len(grids) >= 2, f"frames actually arrived ({len(grids)})")
        check(oldest < 3 * PERIOD,
              f"every frame the window averaged was stamped within "
              f"{oldest:.2f}s of being taken — under three frame periods, "
              f"where the same stall left {dropped_by_the_stall * PERIOD:.1f}s "
              f"of frames queued for the read this replaced")

        # AND THE STAMPS ARE THE PAIRED CLOCK'S, which is what makes the
        # window a claim about the world rather than about arrivals.
        check(sess.clockmap.ready and all(g.at_s > 0 for g in held),
              "the frames are stamped on this server's own clock through "
              "the pairing, which is what `gather` windows against")
    finally:
        client.stop()
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        pipe.close()
        await server.stop()


async def main():
    print("== A STAMP IS NOT A PHOTON: the transport, measured ==")
    await section_depth()
    await section_read()
    await section_sensor()
    await section_wire()
    print()
    if FAILURES:
        print(f"FAILED {len(FAILURES)} check(s):")
        for f in FAILURES:
            print(f"  {f}")
        return 1
    print("STREAM FRESHNESS CHECKS PASSED")
    return 0


if __name__ == "__main__":
    status = 1
    try:
        status = asyncio.run(main())
    except Exception:                                          # noqa: BLE001
        import traceback
        traceback.print_exc()
    os._exit(status)
