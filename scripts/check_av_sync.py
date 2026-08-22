#!/usr/bin/env python
"""Executable spec + the "PROVE IT PRODUCES A NUMBER" demonstration for the
phone audio/visual-offset instrument — offline, no phone, no lights, no
live storage: a simulated room with KNOWN latencies is pushed through the
REAL session/correlator code (spectra/services/av_sync_session.py,
av_sync_correlate.py, av_sync_pattern.py, av_sync_audio_ref.py) behind
fake seams (a fake audio hub, a fake fx_seam, a fake phone), and the
recovered number is printed next to the truth, with its confidence
statement.

    .venv/bin/python scripts/check_av_sync.py            # the demo + assertions
    .venv/bin/python scripts/check_av_sync.py --sweep    # several rooms / phones

The simulated room (SimRoom) models, with named numbers, exactly the
terms the real measurement has to contend with:
  * light path  : write → photons after LIGHT_LATENCY_S, rise over RISE_S
  * audio path  : server hub stamps a block INPUT_LATENCY_S after the
                  samples existed; the phone hears it AUDIO_PATH_S after
                  the hub's own (true) sample time; room noise added
  * phone       : its own clock offset vs the server (seconds of it),
                  a camera at FPS with full-frame exposure INTEGRATION
                  (the edge is seen ~half a frame late), frame-time
                  jitter, sensor noise; a mic envelope at ~86 Hz hops
  * nothing is cheated: the session maps clocks only from its own
                  ping/pong, the pattern edges come from the real driver
                  against the fake seam, the phone streams are generated
                  from the physical model and fed as the real WebSocket
                  messages would arrive.

TRUTH for the headline number: av_offset = LIGHT_LATENCY − AUDIO_PATH
(seen from the phone); the expected MEASURED value additionally carries
the three systematics the arithmetic cannot remove and the statement
names: +½ frame (exposure integration → the edge is seen late → lights
look later), +½ rise time (the edge is timed at its 50 % crossing) and
+INPUT_LATENCY (the hub stamps the reference sound late → the phone's
audio lag reads SMALLER → lights look LATER), i.e.
    expected_measured = truth + 0.5/FPS + RISE_S/2 + INPUT_LATENCY_S
and this script asserts the measurement lands within the tolerance it
itself reports (±sigma, plus a fixed margin for the exposure/half-frame
modelling) — not just "close".

tests/test_av_sync_session.py imports SimRoom from here (the established
importlib pattern) so the spec and the test share ONE simulator.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spectra import config as scfg  # noqa: E402
from spectra.services import av_sync_session as sess_mod  # noqa: E402
from spectra.services.av_sync_audio_ref import AudioReference  # noqa: E402
from spectra.services.av_sync_pattern import PatternDriver  # noqa: E402
from spectra.services.av_sync_session import Session  # noqa: E402


# ── a controllable clock ───────────────────────────────────────────────────

class FakeTime:
    def __init__(self, start: float = 1000.0) -> None:
        self.t = start

    def now(self) -> float:
        return self.t

    async def sleep(self, d: float) -> None:
        self.t += max(0.0, float(d))
        await asyncio.sleep(0)


# ── fake seams ─────────────────────────────────────────────────────────────

class FakeSub:
    def __init__(self) -> None:
        self.queue: list = []

    def drain(self):
        out, self.queue = self.queue, []
        return out

    def stats(self):
        return {"queued_blocks": len(self.queue)}


class FakeHub:
    sample_rate = 44100

    def __init__(self) -> None:
        self.subs: list[FakeSub] = []

    def subscribe(self, name, *, max_blocks=256):
        s = FakeSub()
        self.subs.append(s)
        return s


class FakeSeam:
    """Stands in for fx_seam: a live virtuals map + a write log with the
    FakeTime stamp of every write (what a real facade write would land
    on the next render frame)."""

    def __init__(self, ft: FakeTime, virtuals: dict) -> None:
        self.ft = ft
        self.virtuals = virtuals
        self.writes: list[tuple[float, list[dict], int]] = []

    async def get_virtuals(self):
        return {vid: {"active": v["active"], "effect": dict(v["effect"])}
                for vid, v in self.virtuals.items()}

    async def apply_writes(self, writes, *, transition_ms=0):
        self.writes.append((self.ft.now(), [dict(w) for w in writes], transition_ms))
        for w in writes:
            v = self.virtuals.get(w["virtual_id"])
            if v is not None:
                v["effect"] = {"type": w["effect_type"], "config": dict(w["config"])}


# ── the simulated room + phone ─────────────────────────────────────────────

@dataclass
class SimRoom:
    light_latency_s: float = 0.060      # write → photons
    rise_s: float = 0.020               # light rise time (10-90 %)
    audio_path_s: float = 0.380         # hub sample time → phone ear
    input_latency_s: float = 0.020      # hub stamps a block this late
    phone_clock_offset_s: float = 5000.123   # phone perf clock − server clock
    fps: float = 30.0
    frame_jitter_s: float = 0.002
    sensor_noise: float = 3.0           # luminance counts (0-255)
    mic_noise_db: float = 3.0
    rtt_s: float = 0.012                # phone↔server ping RTT
    seed: int = 3
    env_rate_hz: float = 86.0           # phone envelope hop ≈ 11.6 ms
    rng: np.random.Generator = field(init=False)

    def __post_init__(self) -> None:
        self.rng = np.random.default_rng(self.seed)

    @property
    def truth_av_offset_ms(self) -> float:
        return (self.light_latency_s - self.audio_path_s) * 1000.0

    @property
    def expected_measured_ms(self) -> float:
        """truth + the three named systematics the arithmetic can't see."""
        return (self.truth_av_offset_ms + 500.0 / self.fps + 500.0 * self.rise_s
                + self.input_latency_s * 1000.0)

    # clocks
    def phone_ms(self, t_server: float) -> float:
        return (t_server + self.phone_clock_offset_s) * 1000.0

    # ── synthetic audio: a "song" envelope on the server clock ────────────
    def make_song_env(self, t0: float, t1: float) -> tuple[np.ndarray, np.ndarray]:
        """(t_true, dB) — the true log-energy of the monitor audio at the
        hub's sample times (server clock, BEFORE input latency)."""
        rate = self.env_rate_hz
        n = int((t1 - t0) * rate)
        t = t0 + np.arange(n) / rate
        env = np.full(n, -45.0)
        onsets = np.sort(self.rng.choice(n, size=max(8, int(3.0 * (t1 - t0))), replace=False))
        for o in onsets:
            L = min(n - o, int(0.35 * rate))
            env[o:o + L] = np.maximum(env[o:o + L], -12 - 30 * np.arange(L) / max(1, L))
        env += self.rng.normal(0, 0.7, n)
        return t, env

    def hub_blocks(self, t_true: np.ndarray, env_db: np.ndarray):
        """Fake hub blocks: (stamp, block) where the block's RMS encodes the
        envelope and the stamp is input_latency late + half a block
        (the hub stamps at callback entry ≈ block end)."""
        out = []
        n = 512
        for t, db in zip(t_true, env_db):
            amp = 10 ** (db / 20.0)
            block = (self.rng.normal(0, 1, n) * amp).astype(np.float32)
            stamp = t + self.input_latency_s + 0.5 * n / 44100.0
            out.append((stamp, block))
        return out

    def phone_audio_messages(self, t_true: np.ndarray, env_db: np.ndarray, batch: int = 8):
        """The phone's `audio` messages: the same envelope, heard
        audio_path_s later, noisier, on the phone clock."""
        msgs = []
        heard = env_db + self.rng.normal(0, self.mic_noise_db, env_db.size) - 18.0
        hop_ms = 1000.0 / self.env_rate_hz
        for i in range(0, t_true.size, batch):
            t0_server = t_true[i] + self.audio_path_s
            msgs.append({"type": "audio", "t0_ms": self.phone_ms(t0_server), "hop_ms": hop_ms,
                         "v": [float(x) for x in heard[i:i + batch]]})
        return msgs

    # ── synthetic video: luminance of the pattern as the camera sees it ───
    def phone_video_messages(self, edges: list[tuple[float, int]], t0: float, t1: float,
                             batch: int = 4, with_grid: bool = True):
        frames = np.arange(t0, t1, 1.0 / self.fps)
        frames = frames + self.rng.uniform(-self.frame_jitter_s, self.frame_jitter_s, frames.size)
        sub = np.linspace(0, 1.0 / self.fps, 8)   # full-frame exposure integration

        def state_at(ts: np.ndarray) -> np.ndarray:
            tt = ts - self.light_latency_s
            v = np.zeros_like(tt)
            for i, (et, s) in enumerate(edges):
                nxt = edges[i + 1][0] if i + 1 < len(edges) else t1 + 10
                # linear rise over rise_s
                frac = np.clip((tt - et) / max(1e-6, self.rise_s), 0, 1)
                sel = (tt >= et) & (tt < nxt)
                prev = edges[i - 1][1] if i > 0 else 0
                v[sel] = prev + (s - prev) * frac[sel]
            return v

        lum = np.array([state_at(f - 1.0 / self.fps + sub).mean() for f in frames])
        # the light fills ~1/4 of the frame: the mean is diluted, region 5 sees it fully
        mean_lum = 30 + 40 * lum + self.rng.normal(0, self.sensor_noise, lum.size)
        msgs = []
        for i in range(0, frames.size, batch):
            ts = frames[i:i + batch]
            chunk = mean_lum[i:i + batch]
            grid = None
            if with_grid:
                grid = []
                for k in range(ts.size):
                    g = [float(30 + self.rng.normal(0, self.sensor_noise)) for _ in range(16)]
                    g[5] = float(20 + 160 * lum[i + k] + self.rng.normal(0, self.sensor_noise))
                    grid.append(g)
            msgs.append({"type": "video", "t_ms": [self.phone_ms(t) for t in ts],
                         "lum": [float(x) for x in chunk], **({"grid": grid} if grid else {})})
        return msgs


# ── the end-to-end run ─────────────────────────────────────────────────────

async def run_room(room: SimRoom, *, duration_s: float = 12.0, storage_dir: Path | None = None,
                   verbose: bool = True) -> dict:
    ft = FakeTime()
    if storage_dir is not None:
        scfg.AV_SYNC_MEASUREMENTS_FILE = storage_dir / "av_sync_measurements.json"
        scfg.AV_SYNC_PATTERN_FILE = storage_dir / "av_sync_pattern.json"
    hub = FakeHub()
    seam = FakeSeam(ft, {
        "crystal": {"active": True, "effect": {"type": "blackhole", "config": {"brightness": 0.7}}},
        "strip": {"active": True, "effect": {"type": "orbits1d", "config": {}}},
        "mask": {"active": False, "effect": {"type": "singleColor", "config": {}}},
    })
    driver = PatternDriver(get_virtuals=seam.get_virtuals, apply_writes=seam.apply_writes,
                           clock=ft.now, sleep=ft.sleep)
    sent: list[dict] = []

    async def send(msg: dict) -> None:
        sent.append(msg)

    audio_ref = AudioReference(hub_getter=lambda: hub, clock=ft.now)
    sess = Session(send, audio_ref=audio_ref, pattern=driver, clock=ft.now,
                   show_writes=lambda: [])
    # open without the real loop task (we drive the clock by hand): replicate open()
    sess._audio_ref_started = audio_ref.start()
    await asyncio.sleep(0)
    await sess.handle({"type": "hello", "user_agent": "sim-phone",
                       "audio": {"sample_rate": 48000, "hop_ms": 11.6, "latency_s": None},
                       "video": {"fps": room.fps, "capture_time_available": False,
                                 "width": 320, "height": 240},
                       "secure_context": True, "origin": "https://sim"})
    # clock pairing: server pings, phone pongs after rtt/2 each way
    for _ in range(6):
        await sess._ping()
        ping = [m for m in sent if m.get("type") == "ping"][-1]
        ft.t += room.rtt_s / 2
        t_phone_ms = room.phone_ms(ft.now())
        ft.t += room.rtt_s / 2
        await sess.handle({"type": "pong", "seq": ping["seq"], "t_phone_ms": t_phone_ms})
    assert sess.clockmap.ready
    # the song plays across the whole window
    t_song0 = ft.now() - 2.0
    t_song1 = ft.now() + duration_s + 6.0
    t_true, env = room.make_song_env(t_song0, t_song1)
    hub.subs[0].queue.extend(room.hub_blocks(t_true, env))
    await asyncio.sleep(0.03)          # let the audio-ref pump drain (real task, real sleep)
    for m in room.phone_audio_messages(t_true, env):
        await sess.handle(m)
    # start the pattern and let the driver run to completion on the fake clock
    await sess.start_measure(mode="pattern", duration_s=duration_s)
    run = driver.run
    for _ in range(20000):
        if run.done:
            break
        await asyncio.sleep(0)
    assert run.done and not run.aborted, "pattern did not finish"
    # the phone saw the pattern: feed its luminance
    for m in room.phone_video_messages(run.edges, run.started_at - 1.0, run.finished_at + 1.0):
        await sess.handle(m)
    # the final read (the settle task is real-time; take the read directly)
    # and persist it exactly the way the settle task would — the ONLY disk
    # write this feature makes, so its shape is part of the proof
    est = sess.estimate()
    sess.mode = "pattern"
    record = sess._record(est, final=True)
    await sess.close()
    result = {"estimate": est.as_dict(), "record": record,
              "truth_av_offset_ms": room.truth_av_offset_ms,
              "expected_measured_ms": room.expected_measured_ms,
              "pattern": run.as_dict(), "writes": len(seam.writes),
              "reverted": seam.virtuals["crystal"]["effect"]["type"] == "blackhole"
              and seam.virtuals["strip"]["effect"]["type"] == "orbits1d"
              and seam.virtuals["mask"]["effect"]["type"] == "singleColor",
              "pattern_file_cleared": not scfg.AV_SYNC_PATTERN_FILE.exists()
              if storage_dir is not None else None}
    if verbose:
        d = est.as_dict()
        print(f"  room: light {room.light_latency_s*1000:.0f} ms, audio path {room.audio_path_s*1000:.0f} ms, "
              f"hub input latency {room.input_latency_s*1000:.0f} ms, phone clock offset "
              f"{room.phone_clock_offset_s:.3f} s, camera {room.fps:.0f} fps")
        print(f"  TRUTH av_offset = {room.truth_av_offset_ms:+.1f} ms   (expected measured incl. named "
              f"systematics = {room.expected_measured_ms:+.1f} ms)")
        print(f"  MEASURED        = {d['av_offset_ms']:+} ms ± {d['sigma_ms']} ms (statistical)   "
              f"ok={d['ok']} region={d['light_region']}")
        print(f"    light lag {d['light_lag']['lag_ms']} ms (peak ratio {d['light_lag']['peak_ratio']}, "
              f"ambiguity {d['light_lag']['ambiguity']}), audio lag {d['audio_lag']['lag_ms']} ms "
              f"(peak ratio {d['audio_lag']['peak_ratio']}, ambiguity {d['audio_lag']['ambiguity']})")
        print(f"    clock: {d['clock']}")
        print(f"    systematic bound ±{d['systematic_bound_ms']} ms over {len(d['systematics'])} named terms")
        print(f"    statement: {d['statement']}")
        print(f"  pattern: {run.as_dict()['edge_count']} edges over {run.duration_s:.0f} s, "
              f"{len(seam.writes)} seam writes, room reverted = {result['reverted']}, "
              f"snapshot file cleared = {result['pattern_file_cleared']}")
    return result


def check(result: dict, room: SimRoom, *, margin_ms: float = 12.0) -> None:
    est = result["estimate"]
    assert est["ok"], f"no number produced: {est['reason']} — {est['statement']}"
    err = abs(est["av_offset_ms"] - room.expected_measured_ms)
    tol = 2 * (est["sigma_ms"] or 0) + margin_ms
    assert err <= tol, (f"measured {est['av_offset_ms']} vs expected {room.expected_measured_ms:.1f} "
                        f"(truth {room.truth_av_offset_ms:.1f}): err {err:.1f} > tol {tol:.1f}")
    assert result["reverted"], "room was not reverted after the pattern"
    if result["pattern_file_cleared"] is not None:
        assert result["pattern_file_cleared"], "pattern snapshot file left behind"
    # sign: lights ahead by design here → negative, statement says AHEAD
    if room.truth_av_offset_ms < 0:
        assert est["av_offset_ms"] < 0 and "AHEAD" in est["statement"]
    else:
        assert est["av_offset_ms"] > 0 and "BEHIND" in est["statement"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep", action="store_true")
    args = ap.parse_args(argv)
    import tempfile
    rooms = [SimRoom()]
    if args.sweep:
        rooms += [
            SimRoom(light_latency_s=0.150, audio_path_s=0.040, fps=60, seed=11),   # lights behind
            SimRoom(light_latency_s=0.030, audio_path_s=1.100, fps=24, sensor_noise=8, seed=5),
            SimRoom(phone_clock_offset_s=-86400.5, rtt_s=0.040, mic_noise_db=6, seed=9),
        ]
    with tempfile.TemporaryDirectory() as td:
        for i, room in enumerate(rooms):
            print(f"\n=== simulated room {i + 1}/{len(rooms)} ===")
            result = asyncio.run(run_room(room, storage_dir=Path(td)))
            check(result, room)
            print("  ✓ within its own stated tolerance; sign correct; room reverted")
        from spectra.services.av_sync_session import load_measurements
        recs = load_measurements(Path(td) / "av_sync_measurements.json")
        print(f"\nmeasurements file: {len(recs)} record(s) (numbers + statement only — "
              f"no media keys present: "
              f"{not any(k in r for r in recs for k in ('v', 'lum', 'data', 'audio_samples'))})")
    print("\nAV-SYNC SPEC OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
