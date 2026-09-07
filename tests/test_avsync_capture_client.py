"""THE KIOSK A/V-SYNC CLIENT: the microphone it refuses to fake, and the
session it refuses to guess through.

`tests/test_avsync_kiosk_e2e.py` proves the NUMBER. This file proves the
things around it that would each turn a good number into a bad one without
anybody noticing: a microphone bound to the wrong card, a stream that died
and kept sending silence, a measurement started when the server had already
said it had nothing to measure against, and a `hello` that claims a capture
timestamp this client does not have.

No hardware: `arecord` is a fake process feeding a real `asyncio`
StreamReader, and the server is a stub speaking the wire in
`spectra/api/av_sync.py`'s own words."""
from __future__ import annotations

import asyncio
import json
import struct

import pytest

from spectra.capture_client.avsync_audio import (SAMPLE_BYTES, ArecordSource,
                                                 AudioUnavailable,
                                                 list_capture_cards,
                                                 parse_arecord_l,
                                                 probe_device, resolve_device)
from spectra.capture_client.avsync_reduce import SILENCE_FLOOR_DB
from spectra.capture_client.avsync_session import (SOURCE, AvSyncKioskClient,
                                                   MeasurementFailed,
                                                   video_message)
from spectra.capture_client.camera import (BaseCamera, CameraLock,
                                           CameraUnavailable)

LISTING = """**** List of CAPTURE Hardware Devices ****
card 1: reSpeaker [ReSpeaker 4 Mic Array], device 0: USB Audio [USB Audio]
card 2: BRIO [Logitech BRIO], device 0: USB Audio [USB Audio]
"""
TWO_MICS = """card 1: MicA [Some USB Mic], device 0: USB Audio [USB Audio]
card 3: MicB [Other USB Mic], device 0: USB Audio [USB Audio]
"""


def runner(text, code=0):
    return lambda args, timeout=5.0: (code, text)


# ── 1. bound by NAME, never by card index ─────────────────────────────────

def test_the_brio_resolves_to_a_name_not_a_number():
    """USB enumeration order is not a promise about anything, so nothing
    this client opens may be addressed by card index."""
    assert resolve_device("BRIO", run=runner(LISTING)) == \
        "plughw:CARD=BRIO,DEV=0"
    # case-insensitive, and the long name works too
    assert resolve_device("logitech", run=runner(LISTING)) == \
        "plughw:CARD=BRIO,DEV=0"
    assert "2" not in resolve_device("BRIO", run=runner(LISTING))


def test_an_explicit_alsa_device_is_passed_through_untouched():
    assert resolve_device("hw:2,0", run=runner(LISTING)) == "hw:2,0"
    assert resolve_device("default", run=runner(LISTING)) == "default"


def test_a_name_that_is_not_there_is_refused_with_what_is():
    with pytest.raises(AudioUnavailable) as exc:
        resolve_device("BRIO", run=runner(TWO_MICS))
    assert "BRIO" in str(exc.value)
    assert "MicA" in str(exc.value) and "MicB" in str(exc.value)


def test_an_ambiguous_name_is_refused_rather_than_resolved_to_the_first():
    with pytest.raises(AudioUnavailable) as exc:
        resolve_device("Mic", run=runner(TWO_MICS))
    assert "more than one" in str(exc.value)
    assert "MicA" in str(exc.value) and "MicB" in str(exc.value)


def test_a_machine_with_no_capture_device_at_all_says_so():
    with pytest.raises(AudioUnavailable) as exc:
        resolve_device("BRIO", run=runner("**** List of CAPTURE Hardware Devices ****\n"))
    assert "no ALSA capture device" in str(exc.value)


def test_naming_nothing_is_itself_a_refusal():
    with pytest.raises(AudioUnavailable):
        resolve_device("", run=runner(LISTING))


def test_the_listing_is_parsed_from_alsas_own_answer():
    cards = parse_arecord_l(LISTING)
    assert [c.card_id for c in cards] == ["reSpeaker", "BRIO"]
    assert cards[1].card_name == "Logitech BRIO"
    assert cards[1].alsa_device == "plughw:CARD=BRIO,DEV=0"
    assert list_capture_cards(run=runner("garbage")) == []


def test_probe_never_opens_the_device_and_reports_either_way():
    ok = probe_device("BRIO", run=runner(LISTING))
    assert ok["ok"] and ok["device"] == "plughw:CARD=BRIO,DEV=0"
    assert len(ok["capture_devices"]) == 2
    bad = probe_device("BRIO", run=runner(TWO_MICS))
    assert not bad["ok"] and bad["capture_devices"]


# ── 2. the stream itself: framing, and the refusals ───────────────────────

class FakeArecord:
    """Everything `ArecordSource` uses of a process. Built INSIDE the loop
    (an `asyncio.StreamReader` binds to the running one), which is why the
    helpers below hand over a spawn coroutine rather than an object."""

    def __init__(self, pcm: bytes, *, eof: bool = True,
                 stderr: bytes = b"") -> None:
        self.stdout = asyncio.StreamReader()
        self.stdout.feed_data(pcm)
        if eof:
            self.stdout.feed_eof()
        self.stderr = asyncio.StreamReader()
        self.stderr.feed_data(stderr)
        self.stderr.feed_eof()
        self.terminated = False

    def terminate(self):
        self.terminated = True

    async def wait(self):
        return 0


def pcm_at(amp: float, samples: int) -> bytes:
    v = max(-32768, min(32767, int(amp * 32767)))
    return b"".join(struct.pack("<h", v if i % 2 == 0 else -v)
                    for i in range(samples))


class StepClock:
    def __init__(self, t=0.0):
        self.t = t

    def __call__(self):
        return self.t


class PacedArecord(FakeArecord):
    """A microphone that keeps going, at roughly the rate a real one hands
    periods over — so a client loop that would spin through a finite buffer
    in a millisecond runs at the cadence it will run at on the kiosk."""

    def __init__(self, amp: float, batch_bytes: int, period_s: float) -> None:
        super().__init__(b"", eof=False)
        self._task = asyncio.get_running_loop().create_task(
            self._feed(pcm_at(amp, batch_bytes // SAMPLE_BYTES), period_s))

    async def _feed(self, chunk: bytes, period_s: float) -> None:
        try:
            while True:
                self.stdout.feed_data(chunk)
                await asyncio.sleep(period_s)
        except asyncio.CancelledError:
            pass

    def terminate(self):
        super().terminate()
        self._task.cancel()


def source_with(pcm: bytes, *, stderr: bytes = b"", **kw) -> ArecordSource:
    src = ArecordSource("plughw:CARD=TEST,DEV=0", clock=StepClock(1000.0),
                        **kw)
    src._spawn = lambda: _spawned(pcm, stderr)
    return src


def paced_source(amp: float = 0.3, period_s: float = 0.02) -> ArecordSource:
    src = ArecordSource("plughw:CARD=TEST,DEV=0", clock=StepClock(1000.0))
    src._spawn = lambda: _paced(src, amp, period_s)
    return src


async def _spawned(pcm: bytes, stderr: bytes = b""):
    return FakeArecord(pcm, stderr=stderr)


async def _paced(src, amp: float, period_s: float):
    return PacedArecord(amp, src.batch_bytes, period_s)


def test_a_batch_is_the_browsers_own_hop_and_batch_size():
    src = ArecordSource("x")
    assert src.hop_samples == 512 and src.batch_hops == 8
    assert src.hop_ms == pytest.approx(512000 / 48000)
    assert src.batch_bytes == 512 * 8 * SAMPLE_BYTES


def test_the_stream_is_framed_into_hops_and_reduced_to_one_number_each():
    src = source_with(pcm_at(0.5, 512 * 8 * 3))
    asyncio.run(_drive_batches(src, 3))
    assert src.hops == 24 and src.silent_hops == 0
    assert src.stats()["reads"] == 3


async def _drive_batches(src, n, collect=None):
    await src.open()
    out = []
    for _ in range(n):
        b = await src.batch()
        out.append(b)
        if collect is not None:
            collect.append(b)
    await src.close()
    return out


def test_a_full_scale_batch_reads_zero_dB_and_a_muted_one_is_counted():
    src = source_with(pcm_at(1.0, 512 * 8))
    batches = asyncio.run(_drive_batches(src, 1))
    assert all(abs(v) < 0.01 for v in batches[0].values)
    quiet = source_with(b"\x00\x00" * 512 * 8)
    b = asyncio.run(_drive_batches(quiet, 1))[0]
    assert b.values == [SILENCE_FLOOR_DB] * 8
    # "the mic was muted" is a FACT the run can report, not something a
    # human has to infer from a correlation that refused
    assert quiet.silent_hops == 8


def test_a_microphone_that_produces_nothing_is_a_named_refusal():
    src = ArecordSource("plughw:CARD=DEAD,DEV=0", clock=StepClock())
    src._spawn = lambda: _spawned(
        b"", b"arecord: main:830: audio open error")
    with pytest.raises(AudioUnavailable) as exc:
        asyncio.run(src.open())
    assert "DEAD" in str(exc.value) and "audio open error" in str(exc.value)


def test_a_stream_that_dies_mid_run_refuses_instead_of_sending_silence():
    """THE ONE THAT MATTERS. Silence is a valid envelope: a client that
    kept sending it would make a dead microphone look like a quiet room and
    send somebody to check the speakers."""
    src = source_with(pcm_at(0.4, 512 * 8))     # exactly one batch, then EOF

    async def go():
        await src.open()
        await src.batch()
        with pytest.raises(AudioUnavailable) as exc:
            await src.batch()
        assert "ended mid-measurement" in str(exc.value)
        await src.close()
    asyncio.run(go())


def test_the_arecord_command_asks_for_the_format_the_reduction_expects():
    args = ArecordSource("plughw:CARD=BRIO,DEV=0").arecord_args()
    assert "-D" in args and "plughw:CARD=BRIO,DEV=0" in args
    assert args[args.index("-f") + 1] == "S16_LE"
    assert args[args.index("-r") + 1] == "48000"
    assert args[args.index("-c") + 1] == "1"
    assert "-t" in args and args[args.index("-t") + 1] == "raw"


# ── 3. the session: what it tells the server, and what it refuses ─────────

class StubCamera(BaseCamera):
    fresh_frames = True

    def __init__(self, w=32, h=24, frames=None):
        super().__init__()
        self.frame_size = (w, h)
        self.capture_size = (w, h)
        self.fps = 30.0
        self.lock = CameraLock(source="stub", exposure_locked=True,
                               white_balance_locked=True)
        self._frames = frames
        self.opened_count = 0

    def describe(self):
        return {"kind": "stub", "fps": self.fps}

    async def open(self):
        self.opened_count += 1
        self._mint_pose()

    async def frame(self):
        if self._frames is not None:
            return self._frames.pop(0) if self._frames else None
        await asyncio.sleep(0.005)
        return bytes(self.frame_bytes)

    async def close(self):
        pass


class StubWS:
    """The server side of the wire, in `spectra/api/av_sync.py`'s own
    message names. It never correlates anything — this file is about what
    the client says and when it refuses."""

    def __init__(self, *, estimates, on_measure="done", done_estimate=None):
        self.sent: list = []
        self._out: asyncio.Queue = asyncio.Queue()
        self._estimates = list(estimates)
        self._on_measure = on_measure
        self._done = done_estimate or {"ok": True, "av_offset_ms": -12.0,
                                       "statement": "s"}
        self.hello: dict = {}
        self.pongs: list = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def __await__(self):
        async def me():
            return self
        return me().__await__()

    async def send(self, raw):
        msg = json.loads(raw)
        self.sent.append(msg)
        kind = msg.get("type")
        if kind == "hello":
            self.hello = msg
            await self._out.put({"type": "welcome", "session_id": "stub"})
            await self._out.put({"type": "ping", "seq": 1})
            for est in self._estimates:
                await self._out.put({"type": "estimate", **est})
        elif kind == "pong":
            self.pongs.append(msg)
        elif kind == "measure":
            if self._on_measure == "error":
                await self._out.put({"type": "error",
                                     "message": "pattern refused: released"})
            elif self._on_measure == "done":
                await self._out.put({"type": "measure_started",
                                     "mode": msg.get("mode")})
                await self._out.put({"type": "measure_done",
                                     "estimate": self._done,
                                     "measurement": {"id": "m1"}})

    def __aiter__(self):
        return self

    async def __anext__(self):
        return json.dumps(await self._out.get())


READY = {"ok": False, "reason": "no_data", "clock": {"ready": True,
                                                     "rtt_ms": 8.0}}
NOT_READY = {"ok": False, "reason": "clock", "clock": {"ready": False}}


def client_for(ws, camera=None, audio=None, **kw):
    return AvSyncKioskClient("ws://stub/api/av-sync/ws",
                             camera or StubCamera(),
                             audio if audio is not None else paced_source(),
                             host="kiosk-0", pose_name="the shelf",
                             connect=lambda _u: ws, **kw)


def test_hello_names_the_kiosk_and_claims_no_capture_timestamp():
    """A `capture_time_available: true` here would silently DELETE the
    server's 80 ms camera-pipeline systematic — the term that covers
    sensor→USB→ffmpeg→our stamp. Claiming a timestamp this client does not
    have is the quietest way to move the answer."""
    hello = client_for(StubWS(estimates=[])).hello()
    assert hello["source"] == SOURCE == "kiosk"
    assert hello["client_version"] and hello["host"] == "kiosk-0"
    assert hello["pose_name"] == "the shelf"
    assert hello["video"]["capture_time_available"] is False
    # and no invented microphone latency, so the server names that too
    assert hello["audio"]["latency_s"] is None
    # `secure_context` is a BROWSER fact and is deliberately absent: the
    # record must not carry a claim about a gate that never applied here
    assert "secure_context" not in hello
    assert hello["audio"]["sample_rate"] == 48000
    assert hello["video"]["grid"] == 4


def test_a_measurement_answers_pings_streams_both_signals_and_reports():
    ws = StubWS(estimates=[NOT_READY, READY])
    client = client_for(ws)

    async def go():
        await client.start_devices()
        try:
            return await client.run_measurements(duration_s=0.1, warmup_s=0.4)
        finally:
            await client.close_devices()
    runs = asyncio.run(go())
    assert len(runs) == 1 and runs[0]["estimate"]["ok"]
    kinds = [m["type"] for m in ws.sent]
    assert kinds[0] == "hello" and "pong" in kinds
    assert "audio" in kinds and "video" in kinds and "measure" in kinds
    # the wire shapes the server actually ingests
    audio = next(m for m in ws.sent if m["type"] == "audio")
    assert set(audio) == {"type", "t0_ms", "hop_ms", "v"} and len(audio["v"]) == 8
    video = next(m for m in ws.sent if m["type"] == "video")
    assert set(video) == {"type", "t_ms", "lum", "grid"}
    assert len(video["grid"][0]) == 16
    assert ws.pongs and ws.pongs[0]["seq"] == 1


def test_it_refuses_before_flashing_his_room_when_there_is_no_audio_reference():
    """The pattern turns every light in his room white. Starting one when
    the server has already said it cannot measure would cost him the room
    for twelve seconds and produce nothing."""
    ws = StubWS(estimates=[{"ok": False, "reason": "no_audio_ref",
                            "statement": "no server audio reference",
                            "clock": {"ready": True}}])
    client = client_for(ws)

    async def go():
        await client.start_devices()
        try:
            await client.run_measurements(duration_s=0.1, warmup_s=0.2)
        finally:
            await client.close_devices()
    with pytest.raises(MeasurementFailed) as exc:
        asyncio.run(go())
    assert "no server audio reference" in str(exc.value)
    assert not any(m["type"] == "measure" for m in ws.sent)


def test_a_clock_map_that_never_pairs_refuses_by_name():
    ws = StubWS(estimates=[NOT_READY])
    client = client_for(ws)

    async def go():
        await client.start_devices()
        try:
            await client.run_measurements(duration_s=0.1, warmup_s=0.1)
        finally:
            await client.close_devices()
    from spectra.capture_client import avsync_session as mod
    old = mod.CLOCK_READY_TIMEOUT_S
    mod.CLOCK_READY_TIMEOUT_S = 0.4
    try:
        with pytest.raises(MeasurementFailed) as exc:
            asyncio.run(go())
    finally:
        mod.CLOCK_READY_TIMEOUT_S = old
    assert "clock map never became ready" in str(exc.value)
    assert not any(m["type"] == "measure" for m in ws.sent)


def test_a_refused_estimate_is_carried_out_with_the_servers_own_words():
    ws = StubWS(estimates=[READY],
                done_estimate={"ok": False, "reason": "ambiguous",
                               "statement": "No measurement yet — two lags "
                                            "explain the data equally well."})
    client = client_for(ws)

    async def go():
        await client.start_devices()
        try:
            await client.run_measurements(duration_s=0.1, warmup_s=0.3)
        finally:
            await client.close_devices()
    with pytest.raises(MeasurementFailed) as exc:
        asyncio.run(go())
    assert "two lags explain the data equally well" in str(exc.value)
    assert exc.value.estimate["reason"] == "ambiguous"


def test_a_dead_microphone_ends_the_run_with_the_microphones_own_sentence():
    ws = StubWS(estimates=[READY])
    # one batch of audio and then the stream stops
    client = client_for(ws, audio=source_with(pcm_at(0.3, 512 * 8)))

    async def go():
        await client.start_devices()
        try:
            await client.run_measurements(duration_s=0.1, warmup_s=1.0)
        finally:
            await client.close_devices()
    with pytest.raises(AudioUnavailable) as exc:
        asyncio.run(go())
    assert "ended mid-measurement" in str(exc.value)


def test_a_dead_camera_ends_the_run_rather_than_relocking_mid_correlation():
    ws = StubWS(estimates=[READY])
    camera = StubCamera(frames=[bytes(32 * 24)] * 3)   # then None
    client = client_for(ws, camera=camera)

    async def go():
        await client.start_devices()
        try:
            await client.run_measurements(duration_s=0.1, warmup_s=1.0)
        finally:
            await client.close_devices()
    with pytest.raises(CameraUnavailable) as exc:
        asyncio.run(go())
    assert "stopped producing frames" in str(exc.value)
    assert camera.opened_count == 1          # never silently reopened


def test_start_devices_refuses_when_either_device_will_not_open():
    class DeadCamera(StubCamera):
        async def open(self):
            raise CameraUnavailable("/dev/video0 does not exist")
    client = client_for(StubWS(estimates=[]), camera=DeadCamera())
    with pytest.raises(CameraUnavailable):
        asyncio.run(client.start_devices())


# ── 4. the command line's own outcomes ────────────────────────────────────

def test_an_unreachable_spectra_is_exit_2_with_a_sentence(monkeypatch):
    """THE BRANCH THAT ONLY RUNS WHEN SOMETHING IS ALREADY WRONG, which is
    why it is pinned. `import websockets` does NOT give you
    `websockets.exceptions` — that attribute exists only once the submodule
    is imported by name — so the obvious spelling turns "SPECTRA is not
    answering" into an AttributeError at the one moment a person needs a
    sentence."""
    import asyncio as _asyncio

    from websockets.exceptions import InvalidURI

    from spectra.capture_client import __main__ as cli
    from spectra.capture_client import avsync_audio, avsync_session

    monkeypatch.setattr(cli, "V4L2Camera",
                        lambda *a, **k: StubCamera())
    monkeypatch.setattr(avsync_audio, "resolve_device",
                        lambda name: "plughw:CARD=TEST,DEV=0")
    monkeypatch.setattr(avsync_audio, "ArecordSource",
                        lambda *a, **k: paced_source())

    def refuse(_url):
        raise InvalidURI("ws://nowhere", "no such host")
    monkeypatch.setattr(avsync_session.websockets, "connect", refuse)

    class Args:
        audio_device = "BRIO"
        device = "/dev/video0"
        avsync_fps = 30.0
        input_format = ""
        host = "kiosk-0"
        pose_name = ""
        measure = True
        measure_mode = "pattern"
        measure_seconds = 1.0
        measure_runs = 1
    status, outcome = _asyncio.run(
        cli._run_avsync(Args(), "ws://nowhere/api/av-sync/ws"))
    assert status == 2
    assert "could not reach SPECTRA" in outcome["detail"]
    assert "ws://nowhere/api/av-sync/ws" in outcome["detail"]


def test_the_avsync_endpoint_is_derived_from_the_one_url():
    from spectra.capture_client.__main__ import _avsync_ws, _urls
    assert _avsync_ws("http://spectra:8000/spectra") == \
        "ws://spectra:8000/spectra/api/av-sync/ws"
    assert _avsync_ws("https://spectra/spectra/") == \
        "wss://spectra/spectra/api/av-sync/ws"
    # and the mapping endpoint on the same address is untouched
    assert _urls("http://spectra:8000/spectra")[1] == \
        "ws://spectra:8000/spectra/api/rooms/map/ws"


def test_the_video_message_builder_is_the_one_the_loop_uses():
    msg = video_message([(1.0, 2.0, [3.0] * 16), (2.0, 4.0, [5.0] * 16)])
    assert msg == {"type": "video", "t_ms": [1.0, 2.0], "lum": [2.0, 4.0],
                   "grid": [[3.0] * 16, [5.0] * 16]}
