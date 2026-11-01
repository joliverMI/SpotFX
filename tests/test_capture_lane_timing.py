"""The capture lane's clock, end to end on the REAL clock: a real FIFO fed the
way the hidden player's governor feeds it — a held backlog that bursts out
when the reader opens, then every sample 0.5 s after the player made it —
and a click at 2.0 s into the song. The stored shape must put the click at
2.0 s, which is the whole chain: the reader's steady origin, the governor's
reported hold, and the song's start from Spotify's progress.

A second run removes the hold from the lane's arithmetic (the governor
unreadable, so it subtracts nothing) and the click moves by that hold —
the test can tell a right answer from a wrong one.
"""
from __future__ import annotations

import asyncio
import os
import threading
import time

import numpy as np

from capture_lane.lane import Job, Lane, LaneDeps
from capture_lane.pcm import FifoReader

RATE = 44100
URI = "spotify:track:lanetiming0000000000001"
DEV = "dev-capture-1"
HOLD_S = 0.5
BACKLOG_S = 1.0
CLICK_AT_S = 2.0
DURATION_MS = 5000


class Player:
    """Account B's player on the real clock."""

    def __init__(self):
        self.started_at = None
        self.calls = []

    def me(self):
        return {"id": "user-b"}

    def devices(self):
        return [{"id": DEV, "name": "Serenity Capture", "volume_percent": 100}]

    def play(self, device_id, uri):
        self.calls.append(("play", device_id, uri))
        self.started_at = time.monotonic()

    def release(self, end_of_song=False):
        """CaptureGateway.release: it lets go of its own song (still playing
        here, on the hidden player), so it pauses it."""
        if self.started_at is not None:
            self.calls.append(("pause", DEV))
        return {"paused": self.started_at is not None, "why": "system_song"}

    def full_volume(self, device_id):
        pass

    def playback(self):
        if self.started_at is None:
            return None
        el = time.monotonic() - self.started_at
        return {"is_playing": True, "progress_ms": int(min(el, DURATION_MS / 1000) * 1000),
                "item": {"uri": URI}, "device": {"id": DEV}}


def governor_writer(path, player: Player, stop: threading.Event):
    fd = os.open(path, os.O_WRONLY)          # blocks until the lane's reader opens
    opened = time.monotonic()
    k = 0                                    # samples written so far
    rng = np.random.default_rng(3)
    try:
        while not stop.is_set():
            now = time.monotonic()
            # sample k was made by the player at made(k), released HOLD_S later
            due = int((now - HOLD_S - (opened - BACKLOG_S - HOLD_S)) * RATE)
            if due > k:
                n = due - k
                made = (opened - BACKLOG_S - HOLD_S) + (k + np.arange(n)) / RATE
                sig = rng.standard_normal(n) * 0.01
                if player.started_at is not None:
                    pos = made - player.started_at
                    sig[(pos >= CLICK_AT_S) & (pos < CLICK_AT_S + 0.02)] = 0.9
                s16 = (np.clip(sig, -1, 1) * 32767).astype("<i2")
                try:
                    os.write(fd, np.repeat(s16, 2).tobytes())
                except BrokenPipeError:
                    return
                k = due
            time.sleep(0.01)
    finally:
        os.close(fd)


def learn(tmp_path, monkeypatch, governor):
    import services.audio_analyzer as aa
    d = tmp_path / "audio_shapes"
    d.mkdir()
    monkeypatch.setattr(aa, "AUDIO_SHAPES_DIR", d)
    monkeypatch.setattr(aa, "_audio_shape_index", {})
    fifo = tmp_path / "capturefifo"
    os.mkfifo(fifo)
    player = Player()
    stop = threading.Event()
    w = threading.Thread(target=governor_writer, args=(str(fifo), player, stop), daemon=True)
    w.start()

    async def analyze(meta, pcm, rate):
        return True

    def sidecar(meta, npz):
        npz.with_suffix(".json").write_text(meta.model_dump_json())

    deps = LaneDeps(
        gateway=player,
        signed_in_user=lambda: {"user_id": "user-b", "checked_not_main": True},
        main_user=lambda: "user-main",
        open_reader=lambda: FifoReader(str(fifo)),
        governor=governor,
        shape_complete=lambda uri: False,
        make_recorder=lambda job: aa.AudioShapeRecorder(job.uri, job.title, job.artist,
                                                        job.duration_ms),
        save_shape=lambda rec: rec.save(),
        detect_anchors=lambda meta, npz: [],
        write_sidecar=sidecar,
        wav_and_analyze=analyze,
        min_capture_pct=0.8,
    )
    lane = Lane(deps)

    async def go():
        lane.learn(Job(uri=URI, title="Timing", artist="Lane", duration_ms=DURATION_MS))
        return await lane.wait()
    try:
        out = asyncio.run(go())
    finally:
        stop.set()
        w.join(timeout=3)
    assert out.status == "ok", (out.reason, out.detail)
    data = np.load(d / "Lane - Timing.npz")
    ts, rms = data["timestamps_ms"], data["rms_total"]
    return out, int(ts[int(np.argmax(rms))]), player


def test_the_click_lands_where_the_song_put_it(tmp_path, monkeypatch):
    out, click_ms, player = learn(
        tmp_path, monkeypatch, lambda: {"seq": 1, "dropped_total_ms": 0, "offset_ms": 500})
    assert out.head_ms == 0 and out.latency_ms == 500
    assert abs(click_ms - CLICK_AT_S * 1000) <= 30, click_ms
    assert player.calls[0] == ("play", DEV, URI) and ("pause", DEV) in player.calls


def test_without_the_hold_the_click_moves_by_it(tmp_path, monkeypatch):
    out, click_ms, _ = learn(tmp_path, monkeypatch, lambda: None)
    assert out.latency_ms == 0
    assert abs(click_ms - (CLICK_AT_S + HOLD_S) * 1000) <= 30, click_ms
