"""The capture lane (capture_lane/, the Jukebox plan's phase 4, PR 4.1).

Driven over a fake account-B Spotify, a fake clock and a fake FIFO reader,
with the REAL AudioShapeRecorder writing into a temp shapes directory. One
test reads a real FIFO (os.mkfifo) written by a thread, the way the hidden
player's governor writes it. Nothing here reaches Spotify or a speaker.
"""
from __future__ import annotations

import asyncio
import json
import os
import struct
import threading
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from capture_lane import lane as lane_mod
from capture_lane import pcm
from capture_lane.app import ROUTES, create_app
from capture_lane.lane import Busy, Job, Lane, LaneDeps, sample_window, song_start_from
from capture_lane.spotify import CaptureGateway, NoDevice

URI = "spotify:track:lanetest000000000000001"
DEV = "dev-capture-1"
ACCOUNT_B = "user-b"
MAIN = "user-main"
RATE = 44100


# ── the fakes ───────────────────────────────────────────────────────────────

class Clock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    async def sleep(self, s: float) -> None:
        self.t += max(0.0, s)
        await asyncio.sleep(0)


class FakeSpotify:
    """Account B's player: a song plays from the moment `play` lands."""

    def __init__(self, clock: Clock, *, me_id=ACCOUNT_B, devices=None, duration_ms=20_000):
        self.clock = clock
        self.me_id = me_id
        self._devices = devices if devices is not None else [
            {"id": DEV, "name": "Serenity Capture", "volume_percent": 100, "is_restricted": False}]
        self.duration_ms = duration_ms
        self.calls: list[tuple] = []
        self.started_at = None
        self.uri = None
        self.stall_at_s = None       # progress freezes this many seconds in
        self.takeover_at_s = None    # another song starts this many seconds in
        self.pause_at_s = None       # someone pauses it this many seconds in
        self.never_starts = False
        self.pause_raises = False

    def me(self):
        self.calls.append(("me",))
        return {"id": self.me_id}

    def devices(self):
        self.calls.append(("devices",))
        return list(self._devices)

    def play(self, device_id, uri):
        self.calls.append(("play", device_id, uri))
        if not self.never_starts:
            self.started_at = self.clock()
            self.uri = uri

    def pause(self, device_id):
        self.calls.append(("pause", device_id))
        if self.pause_raises:
            raise RuntimeError("spotify said no")

    def full_volume(self, device_id):
        self.calls.append(("full_volume", device_id))

    def playback(self):
        if self.started_at is None:
            return None
        el = self.clock() - self.started_at
        uri = self.uri
        playing = True
        if self.takeover_at_s is not None and el >= self.takeover_at_s:
            uri = "spotify:track:someoneelse00000000000"
        if self.pause_at_s is not None and el >= self.pause_at_s:
            playing = False
        if self.stall_at_s is not None and el >= self.stall_at_s:
            el = self.stall_at_s
        progress = int(min(el, self.duration_ms / 1000) * 1000)
        return {"is_playing": playing, "progress_ms": progress,
                "item": {"uri": uri, "duration_ms": self.duration_ms},
                "device": {"id": DEV, "name": "Serenity Capture"}}

    def control_calls(self):
        return [c for c in self.calls if c[0] in ("play", "pause", "full_volume")]


class FakeReader:
    """The FIFO: steady from `origin`, noise as audio, nothing missing."""

    def __init__(self, clock: Clock, *, origin_offset_s=-3.0, steady_after_s=1.0, drift=0.0,
                 error=None):
        self.clock = clock
        self.origin_offset_s = origin_offset_s
        self.steady_after_s = steady_after_s
        self.drift = drift
        self.error = error
        self.overflowed = False
        self.started = None
        self.stopped = False
        self.windows: list[tuple[int, int]] = []

    def start(self):
        self.started = self.clock()

    def stop(self):
        self.stopped = True

    def origin(self):
        if self.started is None or self.error:
            return None
        if self.clock() - self.started < self.steady_after_s:
            return None
        return self.started + self.origin_offset_s

    def drift_ms(self):
        return self.drift

    def mono(self, start=0, end=None):
        self.windows.append((start, end))
        n = max(0, int(end) - int(start))
        rng = np.random.default_rng(7)
        return (rng.standard_normal(n).astype(np.float32) * 0.1)


def make(tmp_path, monkeypatch, *, spotify=None, reader=None, clock=None, who=None,
         main=MAIN, complete=None, governor=None, analyze_ok=True):
    import services.audio_analyzer as aa
    clock = clock or Clock()
    d = tmp_path / "audio_shapes"
    d.mkdir(exist_ok=True)
    monkeypatch.setattr(aa, "AUDIO_SHAPES_DIR", d)
    monkeypatch.setattr(aa, "_audio_shape_index", {})
    sp = spotify or FakeSpotify(clock)
    rd = reader or FakeReader(clock)
    analysed = []
    complete = complete if complete is not None else set()
    gov = governor or (lambda: {"seq": 4, "dropped_total_ms": 0, "offset_ms": 500})

    async def analyze(meta, pcm_, rate):
        analysed.append((meta, len(pcm_), rate))
        return analyze_ok

    def write_sidecar(meta, npz_path):
        npz_path.with_suffix(".json").write_text(meta.model_dump_json(indent=2))

    async def to_thread(fn, *a, **k):
        return fn(*a, **k)

    deps = LaneDeps(
        gateway=sp,
        signed_in_user=lambda: (who if who is not None else
                                {"user_id": ACCOUNT_B, "checked_not_main": True}) or None,
        main_user=lambda: main,
        open_reader=lambda: rd,
        governor=gov,
        shape_complete=lambda uri: uri in complete,
        make_recorder=lambda job: aa.AudioShapeRecorder(job.uri, job.title, job.artist,
                                                        job.duration_ms, genres=job.genres),
        save_shape=lambda rec: rec.save(),
        detect_anchors=lambda meta, path: [],
        write_sidecar=write_sidecar,
        wav_and_analyze=analyze,
        clock=clock,
        wall_ms=lambda: int(clock() * 1000),
        sleep=clock.sleep,
        to_thread=to_thread,
    )
    return Lane(deps), sp, rd, clock, d, analysed


def job(duration_ms=20_000):
    return Job(uri=URI, title="Lane Song", artist="Lane Artist", duration_ms=duration_ms,
               genres=["test"])


def run(lane, j):
    async def go():
        lane.learn(j)
        return await lane.wait()
    return asyncio.run(go())


# ── the arithmetic ──────────────────────────────────────────────────────────

def test_mono_is_the_channel_mean():
    raw = struct.pack("<4h", 16384, 0, -32768, -32768)
    out = pcm.to_mono_float(raw + b"\x01")        # a stray odd byte is ignored
    assert out.dtype == np.float32
    assert out.tolist() == pytest.approx([0.25, -1.0])


def test_origin_skips_the_opening_burst_and_late_reads():
    # 1.5 s of backlog arrives at once at t=10, then a steady flow whose
    # sample 0 "arrived" at 10.6 — plus a late read that must not move it
    reads = [(10.0, int(1.5 * RATE))]
    t, n = 10.0, int(1.5 * RATE)
    for i in range(200):
        t += 0.02
        n += int(0.02 * RATE)
        reads.append((t + (0.3 if i == 50 else 0.0), n))
    # every steady read says sample 0's notional arrival was 8.5 (the backlog
    # was 1.5 s of audio already held); the one late read says 8.8
    assert pcm.origin_from(reads) == pytest.approx(8.5)
    assert pcm.origin_from(reads[:20]) is None     # still inside the warm-up


def test_drift_is_zero_for_a_whole_stream_and_the_stall_for_a_broken_one():
    def stream(stall_after=None, stall_s=0.0):
        reads, t, n = [], 0.0, 0
        for i in range(400):
            t += 0.02
            if stall_after is not None and i == stall_after:
                t += stall_s                 # the clock moves, the samples don't
            n += int(0.02 * RATE)
            reads.append((t, n))
        return reads
    assert abs(pcm.drift_from(stream())) < 1.0
    assert pcm.drift_from(stream(stall_after=200, stall_s=0.4)) == pytest.approx(400, abs=5)
    assert pcm.drift_from(stream()[:60]) is None


def test_song_start_and_the_sample_window():
    assert song_start_from(100.0, 100.2, 5000) == pytest.approx(95.1)
    # reader steady from 10.0; the song's 0:00 played at 12.0; 0.5 s held
    n0, n_end, head = sample_window(10.0, 12.0, 0.5, 20_000)
    assert n0 == round(2.5 * RATE) and n_end == n0 + 20 * RATE and head == 0
    # a reader that started after the song did keeps what it heard, and says how late
    n0, n_end, head = sample_window(13.0, 12.0, 0.0, 20_000)
    assert n0 == 0 and head == 1000 and n_end == 19 * RATE


# ── the whole job ───────────────────────────────────────────────────────────

def test_a_song_is_learned_inaudibly_into_the_same_shape_files(tmp_path, monkeypatch):
    lane, sp, rd, clock, d, analysed = make(tmp_path, monkeypatch)
    out = run(lane, job())
    assert out.status == "ok", (out.reason, out.detail)
    assert out.played is True and out.head_ms == 0 and out.latency_ms == 500
    # exactly one play, on the hidden player, from the start; paused at the end
    assert [c for c in sp.control_calls() if c[0] == "play"] == [("play", DEV, URI)]
    assert ("pause", DEV) in sp.calls
    assert rd.stopped
    npz = d / "Lane Artist - Lane Song.npz"
    meta = json.loads(npz.with_suffix(".json").read_text())
    assert meta["captured_by"] == "capture_lane"
    assert meta["capture_complete"] is True and meta["spotify_uri"] == URI
    data = np.load(npz)
    ts = data["timestamps_ms"]
    assert ts[0] == 0 and ts[-1] >= 19_900
    assert len(analysed) == 1 and analysed[0][1] == 20 * RATE and analysed[0][2] == RATE
    assert lane.state == "idle"


def test_the_sample_window_is_cut_at_the_songs_own_start(tmp_path, monkeypatch):
    lane, sp, rd, clock, d, _ = make(tmp_path, monkeypatch)
    out = run(lane, job())
    assert out.status == "ok"
    start, end = rd.windows[-1]
    # origin = reader start - 3 s; the song started after the 1 s warm-up plus
    # the gateway's own reads; 0.5 s of governor hold on top
    assert end - start == 20 * RATE
    assert start == round((sp.started_at + 0.5 - (rd.started - 3.0)) * RATE)


@pytest.mark.parametrize("who,main,reason", [
    (False, MAIN, "not_signed_in"),
    ({"user_id": "someone-else", "checked_not_main": True}, MAIN, "wrong_account"),
    ({"user_id": ACCOUNT_B, "checked_not_main": True}, ACCOUNT_B, "wrong_account"),
    ({"user_id": ACCOUNT_B, "checked_not_main": None}, None, "cannot_check_account"),
])
def test_nothing_plays_unless_it_is_account_b_and_not_the_main_account(
        tmp_path, monkeypatch, who, main, reason):
    lane, sp, rd, *_ = make(tmp_path, monkeypatch, who=who, main=main)
    out = run(lane, job())
    assert out.status == "failed" and out.reason == reason
    assert out.played is False
    assert sp.control_calls() == []
    assert rd.started is None


def test_an_unchecked_sign_in_plays_once_the_main_account_reads_different(tmp_path, monkeypatch):
    lane, sp, *_ = make(tmp_path, monkeypatch,
                        who={"user_id": ACCOUNT_B, "checked_not_main": None}, main=MAIN)
    assert run(lane, job()).status == "ok"


@pytest.mark.parametrize("devices,reason", [
    ([], "device_missing"),
    ([{"id": "phone", "name": "Javi's phone"}], "device_missing"),
    ([{"id": "a", "name": "Serenity Capture"}, {"id": "b", "name": "serenity capture"}],
     "device_ambiguous"),
    ([{"id": DEV, "name": "Serenity Capture", "is_restricted": True}], "device_restricted"),
])
def test_only_the_one_hidden_player_is_ever_used(tmp_path, monkeypatch, devices, reason):
    clock = Clock()
    sp = FakeSpotify(clock, devices=devices)
    lane, sp, rd, *_ = make(tmp_path, monkeypatch, spotify=sp, clock=clock)
    out = run(lane, job())
    assert out.reason == reason and out.played is False
    assert sp.control_calls() == []


def test_a_low_volume_on_the_hidden_player_is_raised_first(tmp_path, monkeypatch):
    clock = Clock()
    sp = FakeSpotify(clock, devices=[{"id": DEV, "name": "Serenity Capture", "volume_percent": 40}])
    lane, sp, *_ = make(tmp_path, monkeypatch, spotify=sp, clock=clock)
    assert run(lane, job()).status == "ok"
    names = [c[0] for c in sp.control_calls()]
    assert names.index("full_volume") < names.index("play")


def test_a_learned_song_is_never_captured_over(tmp_path, monkeypatch):
    lane, sp, rd, *_ = make(tmp_path, monkeypatch, complete={URI})
    out = run(lane, job())
    assert out.reason == "already_learned" and sp.control_calls() == []


def test_no_audio_on_the_pipe_means_nothing_plays(tmp_path, monkeypatch):
    clock = Clock()
    rd = FakeReader(clock, steady_after_s=1e9)
    lane, sp, rd, *_ = make(tmp_path, monkeypatch, reader=rd, clock=clock)
    out = run(lane, job())
    assert out.reason == "no_audio" and out.played is False
    assert [c for c in sp.control_calls() if c[0] == "play"] == []


@pytest.mark.parametrize("setup,reason", [
    ("takeover", "interrupted"),
    ("paused", "interrupted"),
    ("stall", "stalled"),
    ("never", "did_not_start"),
])
def test_trouble_mid_song_ends_the_job_and_pauses_the_player(tmp_path, monkeypatch, setup, reason):
    clock = Clock()
    sp = FakeSpotify(clock)
    if setup == "takeover":
        sp.takeover_at_s = 6
    elif setup == "paused":
        sp.pause_at_s = 6
    elif setup == "stall":
        sp.stall_at_s = 6
    elif setup == "never":
        sp.never_starts = True
    lane, sp, rd, clock, d, analysed = make(tmp_path, monkeypatch, spotify=sp, clock=clock)
    out = run(lane, job())
    assert out.status == "failed" and out.reason == reason
    assert ("pause", DEV) in sp.calls
    assert not list(d.glob("*.npz")) and analysed == []


def test_a_governor_drain_mid_song_fails_the_job(tmp_path, monkeypatch):
    seqs = iter([4, 4, 4, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5])
    lane, sp, *_ , d, _ = make(
        tmp_path, monkeypatch,
        governor=lambda: {"seq": next(seqs, 5), "dropped_total_ms": 120, "offset_ms": 500})
    out = run(lane, job())
    assert out.reason == "governor_drain" and ("pause", DEV) in sp.calls
    assert not list(d.glob("*.npz"))


def test_a_stream_missing_samples_fails_as_a_gap(tmp_path, monkeypatch):
    clock = Clock()
    rd = FakeReader(clock, drift=350.0)
    lane, sp, rd, clock, d, _ = make(tmp_path, monkeypatch, reader=rd, clock=clock)
    out = run(lane, job())
    assert out.reason == "gap" and not list(d.glob("*.npz"))


def test_a_song_learned_elsewhere_meanwhile_is_left_alone(tmp_path, monkeypatch):
    complete: set = set()
    lane, sp, rd, clock, d, _ = make(tmp_path, monkeypatch, complete=complete)

    async def go():
        lane.learn(job())
        while lane.state != "capturing":
            await asyncio.sleep(0)
        complete.add(URI)                  # the house learned it while it played
        return await lane.wait()
    out = asyncio.run(go())
    assert out.reason == "already_learned" and not list(d.glob("*.npz"))


def test_cancel_stops_it_and_pauses(tmp_path, monkeypatch):
    lane, sp, *_ , d, _ = make(tmp_path, monkeypatch)

    async def go():
        j = lane.learn(job())
        while lane.state != "capturing":
            await asyncio.sleep(0)
        assert lane.cancel("not-this-one") is False
        assert lane.cancel(j.job_id) is True
        return await lane.wait()
    out = asyncio.run(go())
    assert out.status == "cancelled" and ("pause", DEV) in sp.calls
    assert not list(d.glob("*.npz"))


def test_one_song_at_a_time(tmp_path, monkeypatch):
    lane, *_ = make(tmp_path, monkeypatch)

    async def go():
        lane.learn(job())
        with pytest.raises(Busy):
            lane.learn(job())
        await lane.wait()
        lane.learn(job())                  # free again once it ended
        await lane.wait()
    asyncio.run(go())
    assert len(lane.outcomes) == 2


def test_an_analysis_that_fails_keeps_the_shape_and_says_so(tmp_path, monkeypatch):
    lane, sp, rd, clock, d, _ = make(tmp_path, monkeypatch, analyze_ok=False)
    out = run(lane, job())
    assert out.status == "failed" and out.reason == "wav_librosa_failed"
    assert (d / "Lane Artist - Lane Song.npz").exists()


def test_a_pause_that_fails_is_reported(tmp_path, monkeypatch):
    clock = Clock()
    sp = FakeSpotify(clock)
    sp.takeover_at_s = 6
    sp.pause_raises = True
    lane, sp, *_ = make(tmp_path, monkeypatch, spotify=sp, clock=clock)
    out = run(lane, job())
    assert out.reason == "interrupted" and "pause failed" in out.detail


def test_outcomes_are_a_short_memory(tmp_path, monkeypatch):
    lane, *_ = make(tmp_path, monkeypatch, complete={URI})
    for _ in range(lane_mod.OUTCOMES_KEPT + 5):
        run(lane, job())
    assert len(lane.outcomes) == lane_mod.OUTCOMES_KEPT


# ── a real FIFO ─────────────────────────────────────────────────────────────

def test_the_reader_hears_a_real_fifo_and_its_clock_follows(tmp_path):
    path = tmp_path / "capturefifo"
    os.mkfifo(path, 0o666)
    reader = pcm.FifoReader(str(path), max_seconds=10)
    reader.start()
    tone = (np.sin(np.arange(RATE * 3) * 2 * np.pi * 440 / RATE) * 8000).astype("<i2")
    stereo = np.repeat(tone, 2).tobytes()
    began = []

    def write():
        fd = os.open(path, os.O_WRONLY)          # blocks until the reader opened
        began.append(time.monotonic())
        chunk = int(0.02 * RATE) * 4
        for i in range(0, len(stereo), chunk):
            os.write(fd, stereo[i:i + chunk])
            time.sleep(0.02)
        os.close(fd)
    w = threading.Thread(target=write)
    w.start()
    w.join(timeout=10)
    deadline = time.monotonic() + 3
    while reader.samples < len(tone) and time.monotonic() < deadline:
        time.sleep(0.05)
    reader.stop()
    assert reader.samples == len(tone)
    mono = reader.mono(0, 100)
    assert mono[1:10] == pytest.approx(tone[1:10] / 32768.0, abs=1e-4)
    origin = reader.origin()
    assert origin is not None and abs(origin - began[0]) < 0.25
    assert abs(reader.drift_ms()) < 100


def test_a_missing_fifo_is_an_error_not_a_hang(tmp_path):
    reader = pcm.FifoReader(str(tmp_path / "nope"))
    reader.start()
    reader.stop()
    assert reader.error and "can't open" in reader.error


def test_the_reader_refuses_to_grow_past_its_bound(tmp_path):
    path = tmp_path / "fifo"
    os.mkfifo(path)
    reader = pcm.FifoReader(str(path), max_seconds=0.05)
    reader.start()
    fd = os.open(path, os.O_WRONLY)
    try:
        for _ in range(20):
            try:
                os.write(fd, b"\x00" * 4096)
            except BrokenPipeError:
                break
            time.sleep(0.005)
    finally:
        os.close(fd)
    reader.stop()
    assert reader.overflowed and reader.samples <= int(0.05 * RATE)


# ── the gateway ─────────────────────────────────────────────────────────────

class _Sp:
    def __init__(self):
        self.calls = []

    def start_playback(self, **k):
        self.calls.append(("start_playback", k))

    def pause_playback(self, **k):
        self.calls.append(("pause_playback", k))

    def volume(self, v, **k):
        self.calls.append(("volume", v, k))


def test_the_gateway_never_plays_without_a_device():
    sp = _Sp()
    gw = CaptureGateway(sp)
    for call in (lambda: gw.play("", URI), lambda: gw.pause(""), lambda: gw.full_volume(None)):
        with pytest.raises(NoDevice):
            call()
    assert sp.calls == []
    gw.play(DEV, URI)
    assert sp.calls == [("start_playback", {"device_id": DEV, "uris": [URI], "position_ms": 0})]


def test_the_gateway_spaces_its_calls():
    sp = _Sp()
    gw = CaptureGateway(sp)
    t0 = time.monotonic()
    gw.pause(DEV)
    gw.pause(DEV)
    assert time.monotonic() - t0 >= 0.45


def test_the_capture_client_never_reads_or_writes_the_main_token(monkeypatch):
    """TOKEN_CACHE/MAIN_TOKEN_CACHE already point at `tmp_path` files via the
    autouse `_isolated_spotify_capture` conftest fixture. Drive the REAL
    spotipy auth manager (cache lookup + a token refresh) that
    `capture_client()` hands to every API call, with only the network POST
    stubbed, and prove it only ever touches the capture account's own
    token — reading its refresh token, writing its refreshed token back —
    while the main token file is never opened at all."""
    from spotipy.oauth2 import SpotifyOAuth

    from api import spotify_capture as cap
    from config import settings

    monkeypatch.setattr(settings, "spotipy_client_id", "client-id")
    monkeypatch.setattr(settings, "spotipy_client_secret", "client-secret")

    now = int(time.time())
    capture_token = {"access_token": "at-capture-old", "refresh_token": "rt-capture",
                     "expires_at": now - 10, "scope": cap.CAPTURE_SCOPES,
                     "token_type": "Bearer"}
    main_token = {"access_token": "at-main-old", "refresh_token": "rt-main",
                 "expires_at": now - 10, "scope": cap.CAPTURE_SCOPES,
                 "token_type": "Bearer"}
    cap.TOKEN_CACHE.write_text(json.dumps(capture_token))
    cap.MAIN_TOKEN_CACHE.write_text(json.dumps(main_token))
    main_before = cap.MAIN_TOKEN_CACHE.read_bytes()

    refreshed_with: list[str] = []

    def fake_refresh(self, refresh_token):
        refreshed_with.append(refresh_token)
        fresh = {"access_token": "at-capture-fresh", "refresh_token": refresh_token,
                 "expires_at": now + 3600, "scope": self.scope, "token_type": "Bearer"}
        self.cache_handler.save_token_to_cache(fresh)
        return fresh

    monkeypatch.setattr(SpotifyOAuth, "refresh_access_token", fake_refresh)

    real_open = open
    opened: list[str] = []

    def spying_open(path, *a, **k):
        p = str(path)
        opened.append(p)
        if p == str(cap.MAIN_TOKEN_CACHE):
            raise AssertionError("the capture client's auth manager opened the MAIN token cache")
        return real_open(path, *a, **k)

    with monkeypatch.context() as m:
        m.setattr("builtins.open", spying_open)
        client = cap.capture_client()
        access = client.auth_manager.get_access_token(as_dict=False)

    assert access == "at-capture-fresh"
    assert refreshed_with == ["rt-capture"], \
        "the refresh must use the capture account's own refresh token, never the main account's"
    assert str(cap.TOKEN_CACHE) in opened
    assert cap.MAIN_TOKEN_CACHE.read_bytes() == main_before, "the main token file is never written"
    saved = json.loads(cap.TOKEN_CACHE.read_text())
    assert saved["access_token"] == "at-capture-fresh" and saved["refresh_token"] == "rt-capture"


# ── the server ──────────────────────────────────────────────────────────────

def client(tmp_path, monkeypatch, **kw):
    lane, sp, rd, clock, d, _ = make(tmp_path, monkeypatch, **kw)
    return TestClient(create_app(lane=lane, key="k" * 20)), lane, sp


H = {"X-Capture-Lane-Key": "k" * 20}


def test_every_route_needs_the_key(tmp_path, monkeypatch):
    c, lane, sp = client(tmp_path, monkeypatch)
    with c:
        for method, path in ROUTES:
            r = c.request(method, path, json={})
            assert r.status_code == 401, (method, path)
            r = c.request(method, path, json={}, headers={"X-Capture-Lane-Key": "wrong"})
            assert r.status_code == 401
    assert sp.calls == []


def test_nothing_but_its_routes_answers(tmp_path, monkeypatch):
    c, *_ = client(tmp_path, monkeypatch)
    for path in ("/docs", "/openapi.json", "/redoc", "/api/jukebox/status"):
        assert c.get(path, headers=H).status_code == 404
    app_routes = {(m, r.path) for r in c.app.routes for m in getattr(r, "methods", ())}
    assert app_routes == set(ROUTES)


def test_learn_validates_and_reports(tmp_path, monkeypatch):
    c, lane, sp = client(tmp_path, monkeypatch, complete={URI})
    with c:
        _learn_checks(c)


def _learn_checks(c):
    assert c.post("/learn", json={"uri": "spotify:playlist:x", "duration_ms": 1}, headers=H).status_code == 400
    assert c.post("/learn", json={"uri": URI, "duration_ms": 0}, headers=H).status_code == 400
    assert c.post("/learn", json={"uri": URI}, headers=H).status_code == 400
    r = c.post("/learn", json={"uri": URI, "duration_ms": 20_000, "title": "T", "artist": "A",
                               "job_id": "j1"}, headers=H)
    assert r.status_code == 202 and r.json()["job_id"] == "j1"
    st = c.get("/status", headers=H).json()
    assert set(st) >= {"state", "job", "progress_ms", "outcomes", "sentences"}
    assert c.post("/cancel", json={"job_id": "nope"}, headers=H).json() == {"cancelled": False}


def test_the_lane_never_imports_spotfx_main():
    """Its own process: building the whole production lane must not pull in
    main.py (whose event loop runs the music) or start any capture stream."""
    import subprocess
    import sys
    code = ("import sys\n"
            "from capture_lane.app import create_app\n"
            "from capture_lane.lane import Lane, production_deps\n"
            "lane = Lane(production_deps())\n"
            "create_app(lane=lane, key='x' * 20)\n"
            "assert 'main' not in sys.modules, 'main.py was imported'\n"
            "from services.audio_shape_service import audio_shape_service as s\n"
            "assert s._capture is None\n"
            "print('ok')\n")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120,
                       cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert r.returncode == 0 and r.stdout.strip().endswith("ok"), r.stderr[-2000:]
