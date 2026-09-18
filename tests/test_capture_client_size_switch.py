"""A SIZE SWITCH MUST NEVER RACE THE CAMERA READER — and a held camera never
switches at all.

2026-09-18, the kiosk: Calibration One asked the native client for its
commission size and the frame loop died on
`RuntimeError: readexactly() called while another coroutine is already
waiting for incoming data`. The switch had replaced the pipe and was waiting
for its first frame while `newest_of`'s drain probe, finishing a read on the
OLD pipe, issued its next `readexactly` on the NEW one. Two readers, one
StreamReader.

These tests drive the REAL `V4L2Camera` read path (`frame()`, `_read`,
`newest_of`, `_open_at`, `set_frame_size`) over a reader that FAILS LOUDLY
on a second concurrent `readexactly`; only the process that would feed it
(`_start_pipe`) and the control tool (`_tool`) are replaced.
"""
from __future__ import annotations

import asyncio

import pytest

from spectra.capture_client import camera as cam


class StrictReader:
    """An `asyncio.StreamReader` that refuses — loudly, with its own error
    rather than asyncio's — a second `readexactly` while one is pending."""

    def __init__(self) -> None:
        self._inner = asyncio.StreamReader(limit=1 << 26)
        self.pending = 0
        self.violations = 0

    def feed(self, data: bytes) -> None:
        self._inner.feed_data(data)

    async def readexactly(self, n: int) -> bytes:
        if self.pending:
            self.violations += 1
            raise AssertionError("CONCURRENT readexactly on the camera pipe")
        self.pending += 1
        try:
            return await self._inner.readexactly(n)
        finally:
            self.pending -= 1


def _camera(monkeypatch, **kw) -> tuple[cam.V4L2Camera, list[StrictReader]]:
    monkeypatch.setattr(cam, "_tool",
                        lambda name: "ffmpeg" if name == "ffmpeg" else None)
    monkeypatch.setattr(cam, "SETTLE_BEFORE_LOCK_S", 0.0)
    camera = cam.V4L2Camera("/dev/null", fps=5.0, **kw)
    readers: list[StrictReader] = []

    async def start_pipe(_ffmpeg, _capture_size, _frame_bytes):
        r = StrictReader()
        readers.append(r)
        return r

    async def apply_lock(**levers):
        return camera.lock

    camera._start_pipe = start_pipe                    # type: ignore[method-assign]
    camera.apply_lock = apply_lock                     # type: ignore[method-assign]
    return camera, readers


async def _until(pred, timeout: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not pred():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition never became true")
        await asyncio.sleep(0.005)


def _frame(size: tuple[int, int], value: int) -> bytes:
    return bytes([value]) * (size[0] * size[1])


# ── 1. the race, and its control ───────────────────────────────────────────

async def _switch_mid_read(camera, readers):
    """A frame read pending on the old pipe, then a switch to 640x360, then
    the OLD pipe delivers a frame — exactly the kiosk's interleaving."""
    old = (320, 180)
    new = (640, 360)
    reading = asyncio.create_task(camera.frame())
    await _until(lambda: readers[0].pending == 1)
    switching = asyncio.create_task(camera.set_frame_size(new))
    await _until(lambda: len(readers) == 2 and readers[1].pending == 1)
    readers[0].feed(_frame(old, 1))       # the old pipe's last frame
    await asyncio.sleep(0.05)
    readers[1].feed(_frame(new, 2))       # the new pipe's first frame (open)
    got_size = await asyncio.wait_for(switching, 2.0)
    readers[1].feed(_frame(new, 3))       # the frame the read comes back for
    data = await asyncio.wait_for(reading, 2.0)
    return got_size, data


def test_a_size_switch_mid_read_never_reads_the_pipe_twice(monkeypatch):
    camera, readers = _camera(monkeypatch, capture_size=(1920, 1080))

    # open() reads its first frame from readers[0]; feed that first.
    async def run():
        opening = asyncio.create_task(camera.open())
        await _until(lambda: readers and readers[0].pending == 1)
        readers[0].feed(_frame((320, 180), 0))
        await opening
        return await _switch_mid_read(camera, readers)

    got_size, data = asyncio.run(run())
    assert got_size == (640, 360)
    # THE PREEMPTED READ CAME BACK WITH THE NEW STREAM, never an error and
    # never the old pipe's frame labelled with the new size.
    assert data == _frame((640, 360), 3)
    assert camera.last_frame_size == (640, 360)
    assert [r.violations for r in readers] == [0, 0]


def test_without_ownership_the_same_interleaving_reads_the_pipe_twice(
        monkeypatch):
    """THE CONTROL: take the preemption away and the real read path races
    exactly as it did on the kiosk — which is what proves the test above is
    testing the ownership and not an accident of timing."""
    camera, readers = _camera(monkeypatch, capture_size=(1920, 1080))

    import contextlib

    @contextlib.asynccontextmanager
    async def no_ownership():
        yield

    camera._exclusive = no_ownership                   # type: ignore[method-assign]
    camera._require_owner = lambda: None               # type: ignore[method-assign]

    async def run():
        opening = asyncio.create_task(camera.open())
        await _until(lambda: readers and readers[0].pending == 1)
        readers[0].feed(_frame((320, 180), 0))
        await opening
        return await _switch_mid_read(camera, readers)

    with pytest.raises(AssertionError, match="CONCURRENT readexactly"):
        asyncio.run(run())
    assert readers[1].violations == 1


def test_a_pipe_read_without_owning_it_fails_here(monkeypatch):
    camera, _readers = _camera(monkeypatch)

    async def rogue():
        camera._reader = StrictReader()                # type: ignore[assignment]
        return await camera._read(True)

    with pytest.raises(RuntimeError, match="without owning it"):
        asyncio.run(rogue())


# ── 2. the held size ───────────────────────────────────────────────────────

def test_a_held_camera_serves_a_smaller_ask_by_downscale_and_never_reopens(
        monkeypatch):
    camera, readers = _camera(monkeypatch, capture_size=(1920, 1080),
                              hold_size=(1920, 1080))
    full = (1920, 1080)
    # A frame whose 6x6 blocks each average to a known value.
    rows = []
    for y in range(1080):
        rows.append(bytes(((x // 6) * 7 + (y // 6) * 3) % 256
                          for x in range(1920)))
    picture = b"".join(rows)

    async def run():
        opening = asyncio.create_task(camera.open())
        await _until(lambda: readers and readers[0].pending == 1)
        readers[0].feed(_frame(full, 0))
        await opening
        # THE PIPE CARRIES THE HELD SIZE FROM LAUNCH; the wire starts at the
        # map's own 320x180, served by downscale.
        assert camera.pipe_size == full
        assert camera.frame_size == (320, 180)
        assert "scale=1920:1080" in " ".join(camera._ffmpeg_args("ffmpeg"))
        pose = camera.pose_token

        got = await camera.set_frame_size((320, 180))
        readers[0].feed(picture)
        small = await camera.frame()
        size_small = camera.last_frame_size

        got_full = await camera.set_frame_size((1920, 1080))
        readers[0].feed(picture)
        big = await camera.frame()

        # Larger than held: nothing changes, still the held size.
        got_bigger = await camera.set_frame_size((3840, 2160))
        return got, small, size_small, got_full, big, got_bigger, pose

    got, small, size_small, got_full, big, got_bigger, pose = asyncio.run(run())
    assert got == (320, 180) and size_small == (320, 180)
    assert len(small) == 320 * 180
    expected = bytes(((x * 7 + y * 3) % 256)
                     for y in range(180) for x in range(320))
    assert small == expected
    assert got_full == (1920, 1080) and big == picture
    assert got_bigger == (1920, 1080)
    # NO REOPEN, EVER: one pipe for the whole life, the pose untouched.
    assert len(readers) == 1
    assert camera.pose_token == pose
    assert camera.describe()["held_frame_size"] == [1920, 1080]


def test_without_a_hold_a_switch_still_reopens_exactly_as_shipped(monkeypatch):
    camera, readers = _camera(monkeypatch, capture_size=(1920, 1080))

    async def run():
        opening = asyncio.create_task(camera.open())
        await _until(lambda: readers and readers[0].pending == 1)
        readers[0].feed(_frame((320, 180), 0))
        await opening
        assert camera.pipe_size == (320, 180)
        assert "scale=320:180" in " ".join(camera._ffmpeg_args("ffmpeg"))
        switching = asyncio.create_task(camera.set_frame_size((1920, 1080)))
        await _until(lambda: len(readers) == 2 and readers[1].pending == 1)
        readers[1].feed(_frame((1920, 1080), 0))
        return await switching

    assert asyncio.run(run()) == (1920, 1080)
    assert len(readers) == 2
    assert camera.describe()["held_frame_size"] is None


def _naive_area(data: bytes, src, dst) -> bytes:
    """Exact area average the slow way: upsample by q, box by p."""
    sw, sh = src
    dw, dh = dst
    pw, qw = cam._ratio(sw, dw)
    ph, qh = cam._ratio(sh, dh)
    out = bytearray()
    for r in range(dh):
        for c in range(dw):
            s = 0
            for vy in range(r * ph, (r + 1) * ph):
                for vx in range(c * pw, (c + 1) * pw):
                    s += data[(vy // qh) * sw + vx // qw]
            n = pw * ph
            out.append((s + n // 2) // n)
    return bytes(out)


@pytest.mark.parametrize("src,dst", [
    ((60, 36), (10, 6)),            # 6x, the map from 1080p in miniature
    ((60, 36), (40, 24)),           # 3/2, 1080p -> 720p in miniature
    ((32, 24), (32, 18)),           # 640x480 -> 640x360: height only, 4/3
    ((24, 12), (24, 12)),           # identity
])
def test_downscale_is_an_exact_area_average(src, dst):
    import random
    rng = random.Random(7)
    data = bytes(rng.randrange(256) for _ in range(src[0] * src[1]))
    assert cam.downscale_grey(data, src, dst) == _naive_area(data, src, dst)


def test_downscale_refuses_an_upscale():
    with pytest.raises(ValueError):
        cam.downscale_grey(bytes(4), (2, 2), (4, 4))


# ── 3. the read timeout ────────────────────────────────────────────────────

def test_the_read_timeout_is_derived_at_4_5_fps():
    # 222 ms a frame: three intervals are 0.67 s, so the 2 s floor governs,
    # plus the 1080p decode allowance.
    t = cam.frame_read_timeout_s(4.5, (1920, 1080))
    allowance = 1920 * 1080 / 1e6 * cam.DECODE_ALLOWANCE_S_PER_MPX
    assert 3 / 4.5 < cam.READ_TIMEOUT_FLOOR_S
    assert t == pytest.approx(cam.READ_TIMEOUT_FLOOR_S + allowance)


def test_the_read_timeout_is_derived_at_30_fps():
    assert cam.frame_read_timeout_s(30.0, (320, 180)) == pytest.approx(
        cam.READ_TIMEOUT_FLOOR_S
        + 320 * 180 / 1e6 * cam.DECODE_ALLOWANCE_S_PER_MPX)


def test_a_slow_stream_or_a_long_exposure_lengthens_it():
    # One frame every two seconds: three intervals, not the floor.
    assert cam.frame_read_timeout_s(0.5) == pytest.approx(6.0)
    # A sensor integrating 1.5 s cannot deliver faster than that, whatever
    # frame rate it reports.
    assert cam.frame_read_timeout_s(30.0, exposure_s=1.5) == pytest.approx(4.5)


def test_the_camera_uses_the_rate_the_device_reported():
    camera = cam.V4L2Camera("/dev/null", fps=5.0, capture_size=(1920, 1080))
    camera.sensor_fps = 0.5
    assert camera.read_timeout_s() == pytest.approx(
        cam.frame_read_timeout_s(0.5, (1920, 1080)))
    camera.sensor_fps = None
    assert camera.read_timeout_s() == pytest.approx(
        cam.frame_read_timeout_s(5.0, (1920, 1080)))


# ── 4. the launch option ───────────────────────────────────────────────────

def test_the_held_size_is_declared_in_the_environment_file():
    from spectra.capture_client import config
    env = config.from_environment({"SPECTRA_CAPTURE_FRAME_SIZE": "1920x1080"})
    assert env["frame_size"] == "1920x1080"
    assert "SPECTRA_CAPTURE_FRAME_SIZE" in config.env_help()


def test_a_held_size_off_the_ladder_refuses_at_startup(capsys, monkeypatch):
    from spectra.capture_client import __main__ as entry
    monkeypatch.delenv("SPECTRA_CAPTURE_FRAME_SIZE", raising=False)
    assert entry.main(["--url", "http://x", "--frame-size", "1000x1000"]) == 2
    assert "1920x1080" in capsys.readouterr().err


def test_the_held_size_reaches_the_camera(monkeypatch):
    from spectra.capture_client import __main__ as entry
    made = {}

    class Recorder(cam.V4L2Camera):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            made["hold"] = self.hold_size

    async def fake_run(_args, _base, _ws, camera):
        return 0

    monkeypatch.setattr(entry, "V4L2Camera", Recorder)
    monkeypatch.setattr(entry, "_run", fake_run)
    assert entry.main(["--url", "http://x", "--frame-size", "1920x1080"]) == 0
    assert made["hold"] == (1920, 1080)
    made.clear()
    monkeypatch.delenv("SPECTRA_CAPTURE_FRAME_SIZE", raising=False)
    assert entry.main(["--url", "http://x"]) == 0
    assert made["hold"] is None
