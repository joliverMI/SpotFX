#!/usr/bin/env python
"""THE LOAD-BEARING PROOF for the kiosk A/V-sync client: a simulated room
with a KNOWN offset, RAW MEDIA, this client's own reductions, and the REAL
server correlation — recovering the number, with the right SIGN.

    .venv/bin/python scripts/check_avsync_kiosk.py           # one room
    .venv/bin/python scripts/check_avsync_kiosk.py --sweep   # four

WHY IT IS SHAPED THIS WAY. `scripts/check_av_sync.py` already proves the
server half against a simulated PHONE — but it hands the session
pre-reduced numbers, so it proves nothing about a client that has to make
those numbers itself. The one failure that matters here is a reduction or a
timestamp that is subtly wrong: a sign flip, a hop length off by one, a
clock anchored to the wrong end of a read. Every one of those produces a
confident, plausible, WRONG number rather than an error. So this script
starts one step earlier:

    a physical room  →  16-bit PCM bytes + grey8 frame bytes
                     →  spectra/capture_client/avsync_audio.ArecordSource
                        (its REAL framing, its REAL SampleClock anchor,
                        fed through a real asyncio StreamReader from a
                        fake `arecord`)
                     →  spectra/capture_client/avsync_reduce.FrameReducer
                     →  the REAL wire messages
                        (AudioBatch.as_message / avsync_session.video_message)
                     →  the REAL spectra/services/av_sync_session.Session,
                        the REAL PatternDriver, the REAL AudioReference on
                        a fake hub, the REAL correlator

Nothing about the arithmetic is re-implemented here, and no part of the
client is stubbed except the two devices themselves (the microphone is a
fake `arecord` process; the camera is a frame generator). The server half's
simulator — the song envelope and the hub blocks that are its audio
REFERENCE — is imported from `check_av_sync.py` so both scripts share ONE
idea of what the room sounds like.

TRUTH AND EXPECTATION. The truth is `light_latency − audio_path`. The
measurement additionally carries five terms the arithmetic cannot see, three
of them the server already names and two of them this client's own:

    expected = truth
             + 0.5/fps          camera exposure integration (edge seen late)
             + rise/2           the edge is timed at its 50 % crossing
             + input_latency    the hub stamps the reference sound late
             + camera_pipeline  sensor→USB→ffmpeg→our read stamp (LATER)
             − mic_capture      ADC→ALSA→our read (the sound also looks LATE,
                                which makes the audio lag bigger and the
                                lights read relatively EARLIER)

The last two are the kiosk's own, they push in OPPOSITE directions, and the
server names both as bounded systematics (`SYSTEMATIC_NO_CAPTURE_TIME` /
`SYSTEMATIC_MIC_UNKNOWN`) because this client reports
`capture_time_available: false` and `latency_s: null` rather than inventing
either. This script asserts the measurement lands within its OWN stated
tolerance of that expectation — and, separately and more importantly, that
the SIGN is right in both directions.

No hardware, no network, no live storage, no room.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from spectra.capture_client.avsync_audio import (ArecordSource,  # noqa: E402
                                                 SAMPLE_BYTES)
from spectra.capture_client.avsync_reduce import FrameReducer  # noqa: E402
from spectra.capture_client.avsync_session import (AvSyncKioskClient,  # noqa: E402
                                                   video_message)
from spectra.capture_client.camera import CameraLock, SyntheticCamera  # noqa: E402
from spectra.services.av_sync_audio_ref import AudioReference  # noqa: E402
from spectra.services.av_sync_pattern import PatternDriver  # noqa: E402
from spectra.services.av_sync_session import Session  # noqa: E402

# ONE simulator for the server half — the song, the hub blocks, the fake
# seam and the fake clock all come from the phone spec rather than being
# written a second time here.
_SPEC = ROOT / "scripts" / "check_av_sync.py"
_spec = importlib.util.spec_from_file_location("check_av_sync", _SPEC)
sim = importlib.util.module_from_spec(_spec)
sys.modules["check_av_sync"] = sim
_spec.loader.exec_module(sim)


@dataclass
class KioskRoom(sim.SimRoom):
    """A room measured from a fixed camera with the microphone beside it.

    Everything `SimRoom` models is inherited; these are the terms that are
    the KIOSK's rather than a phone's."""
    #: photons → the moment `camera.frame()` hands the bytes back. Sensor,
    #: USB and ffmpeg. Makes the light look LATER.
    camera_pipeline_s: float = 0.045
    #: sound at the mic → present in a read `arecord` has completed. ADC,
    #: USB and one ALSA period. Makes the sound look LATER.
    mic_capture_latency_s: float = 0.018
    #: scheduler jitter on the reads, on top of each latency — what the
    #: SampleClock's min-anchor exists to keep out of the envelope.
    read_jitter_s: float = 0.004
    #: the grey8 frame this camera sends. Small on purpose: the instrument
    #: measures WHEN a region got brighter, never what is in it.
    frame_w: int = 64
    frame_h: int = 48
    #: which 4x4 grid cell the light fills — the region the correlator
    #: should choose over the diluted whole-frame mean.
    light_cell: int = 5
    background_lum: float = 30.0
    light_lum: float = 190.0

    @property
    def expected_measured_ms(self) -> float:
        """The phone's three named systematics plus the kiosk's own two."""
        return (super().expected_measured_ms
                + 1000.0 * (self.camera_pipeline_s
                            - self.mic_capture_latency_s))

    # ── raw microphone bytes ──────────────────────────────────────────────
    def mic_pcm(self, t_true: np.ndarray, env_db: np.ndarray,
                rate_hz: int, hop_samples: int,
                t_from: float, t_to: float) -> tuple:
        """(first-sample true server time, S16_LE bytes) for the microphone,
        hearing the same song `audio_path_s` later.

        Real samples, not an envelope: the client's own reduction is what
        turns them back into one, which is the half being proved."""
        n_hops = int((t_to - t_from) * rate_hz / hop_samples)
        hop_t = t_from + np.arange(n_hops) * hop_samples / rate_hz
        # the song's own envelope at the time this hop's sound LEFT the
        # speaker, plus the room's noise floor and the mic's own gain
        song_t = hop_t - self.audio_path_s
        db = np.interp(song_t, t_true, env_db, left=env_db[0],
                       right=env_db[-1])
        db = db + self.rng.normal(0, self.mic_noise_db, db.size) - 18.0
        amp = 10.0 ** (db / 20.0)
        block = self.rng.normal(0, 1.0, (n_hops, hop_samples))
        pcm = np.clip(block * amp[:, None] * 32767.0, -32768, 32767)
        return t_from, pcm.astype("<i2").tobytes()

    # ── raw camera frames ─────────────────────────────────────────────────
    def camera_frames(self, edges: list, t_from: float, t_to: float) -> list:
        """[(true photon-time of the frame's exposure END, grey8 bytes)] —
        the pattern as this camera would actually record it, integrated over
        a full-frame exposure and with the light filling ONE grid cell."""
        times = np.arange(t_from, t_to, 1.0 / self.fps)
        times = times + self.rng.uniform(-self.frame_jitter_s,
                                         self.frame_jitter_s, times.size)
        sub = np.linspace(0, 1.0 / self.fps, 8)

        def state_at(ts: np.ndarray) -> np.ndarray:
            tt = ts - self.light_latency_s
            v = np.zeros_like(tt)
            for i, (et, s) in enumerate(edges):
                nxt = edges[i + 1][0] if i + 1 < len(edges) else t_to + 10
                frac = np.clip((tt - et) / max(1e-6, self.rise_s), 0, 1)
                sel = (tt >= et) & (tt < nxt)
                prev = edges[i - 1][1] if i > 0 else 0
                v[sel] = prev + (s - prev) * frac[sel]
            return v

        lit = np.array([state_at(t - 1.0 / self.fps + sub).mean()
                        for t in times])
        w, h = self.frame_w, self.frame_h
        cw, ch = w // 4, h // 4
        gy, gx = divmod(self.light_cell, 4)
        out = []
        for t, level in zip(times, lit):
            img = np.full((h, w), self.background_lum, dtype=float)
            img[gy * ch:(gy + 1) * ch, gx * cw:(gx + 1) * cw] = (
                self.background_lum
                + (self.light_lum - self.background_lum) * level)
            img += self.rng.normal(0, self.sensor_noise, img.shape)
            out.append((float(t),
                        np.clip(img, 0, 255).astype(np.uint8).tobytes()))
        return out


# ── a fake `arecord`: a real StreamReader, no subprocess ───────────────────

class FakeArecord:
    """Everything `ArecordSource` uses of a process, and nothing else. The
    pixels of this proof are the BYTES: the reader is a real
    `asyncio.StreamReader`, so the client's own `readexactly` framing is
    what splits them into hops."""

    def __init__(self, pcm: bytes) -> None:
        self.stdout = asyncio.StreamReader()
        self.stdout.feed_data(pcm)
        self.stdout.feed_eof()
        self.stderr = None
        self.terminated = False

    def terminate(self) -> None:
        self.terminated = True

    async def wait(self) -> int:
        return 0


class SteppedClock:
    """The client's own monotonic clock, set by the caller — so a read's
    stamp is the room's arithmetic and not the wall clock's."""

    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


# ── the run ────────────────────────────────────────────────────────────────

async def run_kiosk_room(room: KioskRoom, *, duration_s: float = 12.0,
                         storage_dir: Path | None = None,
                         verbose: bool = True,
                         naive_audio_stamp: bool = False) -> dict:
    """`naive_audio_stamp` is the RED CONTROL, not an option: it stamps each
    batch of envelope at the moment the read RETURNED — the obvious
    implementation, and the one `avsync_reduce.SampleClock` exists to
    replace. It moves the answer by about a batch length plus the capture
    latency, in a direction nothing downstream can detect, which is exactly
    the failure this whole proof is written for."""
    ft = sim.FakeTime()
    if storage_dir is not None:
        from spectra import config as scfg
        scfg.AV_SYNC_MEASUREMENTS_FILE = storage_dir / "av_sync_measurements.json"
        scfg.AV_SYNC_PATTERN_FILE = storage_dir / "av_sync_pattern.json"
    hub = sim.FakeHub()
    seam = sim.FakeSeam(ft, {
        "crystal": {"active": True,
                    "effect": {"type": "blackhole", "config": {"brightness": 0.7}}},
        "strip": {"active": True, "effect": {"type": "orbits1d", "config": {}}},
    })
    driver = PatternDriver(get_virtuals=seam.get_virtuals,
                           apply_writes=seam.apply_writes,
                           clock=ft.now, sleep=ft.sleep)
    sent: list = []

    async def send(msg: dict) -> None:
        sent.append(msg)

    audio_ref = AudioReference(hub_getter=lambda: hub, clock=ft.now)
    sess = Session(send, audio_ref=audio_ref, pattern=driver, clock=ft.now,
                   show_writes=lambda: [])
    sess._audio_ref_started = audio_ref.start()
    await asyncio.sleep(0)

    # THE REAL CLIENT'S OWN HELLO — built by AvSyncKioskClient, not typed
    # out here, so what the server is told about this camera is what a
    # kiosk actually says.
    clock = SteppedClock(ft.now() + room.phone_clock_offset_s)
    camera = SyntheticCamera(lambda: bytes(room.frame_w * room.frame_h),
                             lock=CameraLock(source="sim:camera"),
                             capture_size=(room.frame_w, room.frame_h))
    camera.frame_size = (room.frame_w, room.frame_h)
    camera.fps = room.fps
    source = ArecordSource("plughw:CARD=SIM,DEV=0", clock=clock)
    client = AvSyncKioskClient("ws://sim/api/av-sync/ws", camera, source,
                               host="sim-kiosk", pose_name="the sim shelf",
                               clock=clock)
    await sess.handle(client.hello())

    # clock pairing, exactly as the wire does it
    for _ in range(6):
        await sess._ping()
        ping = [m for m in sent if m.get("type") == "ping"][-1]
        ft.t += room.rtt_s / 2
        clock.t = ft.now() + room.phone_clock_offset_s
        await sess.handle({"type": "pong", "seq": ping["seq"],
                           "t_phone_ms": clock.t * 1000.0})
        ft.t += room.rtt_s / 2
    assert sess.clockmap.ready, "the clock map never paired"

    # ── the song: the server's own reference, and the mic's raw bytes ─────
    t_song0 = ft.now() - 2.0
    t_song1 = ft.now() + duration_s + 8.0
    t_true, env = room.make_song_env(t_song0, t_song1)
    hub.subs[0].queue.extend(room.hub_blocks(t_true, env))
    await asyncio.sleep(0.03)          # let the audio-ref pump drain

    mic_from = t_song0 + room.audio_path_s
    t_first, pcm = room.mic_pcm(t_true, env, source.rate_hz,
                                source.hop_samples, mic_from,
                                t_song1 + room.audio_path_s)
    source._spawn = lambda: _fake_spawn(pcm)
    clock.t = (t_first + source.batch_bytes / SAMPLE_BYTES / source.rate_hz
               + room.mic_capture_latency_s + room.phone_clock_offset_s)
    await source.open()
    audio_msgs = []
    jitter = np.random.default_rng(room.seed + 1)
    while True:
        try:
            batch = await source.batch()
        except Exception:
            break
        msg = batch.as_message()
        if naive_audio_stamp:
            msg["t0_ms"] = clock.t * 1000.0
        audio_msgs.append(msg)
        # the NEXT read finishes one batch of samples later, plus the
        # capture latency, plus whatever the scheduler adds this time
        end_true = (t_first + (source.clock.samples + source.hop_samples
                               * source.batch_hops) / source.rate_hz)
        clock.t = (end_true + room.mic_capture_latency_s
                   + abs(jitter.normal(0, room.read_jitter_s))
                   + room.phone_clock_offset_s)
    for msg in audio_msgs:
        await sess.handle(msg)

    # ── the pattern, and the frames the camera really recorded ───────────
    await sess.start_measure(mode="pattern", duration_s=duration_s)
    run = driver.run
    for _ in range(20000):
        if run.done:
            break
        await asyncio.sleep(0)
    assert run.done and not run.aborted, "pattern did not finish"

    reducer = FrameReducer(room.frame_w, room.frame_h)
    frames = room.camera_frames(run.edges, run.started_at - 1.0,
                                run.finished_at + 1.0)
    pending, video_msgs = [], []
    for t_photon, data in frames:
        mean, grid = reducer.reduce(data)
        t_read_client = (t_photon + room.camera_pipeline_s
                         + room.phone_clock_offset_s)
        pending.append((t_read_client * 1000.0, mean, grid))
        if len(pending) >= 4:
            video_msgs.append(video_message(pending))
            pending = []
    if pending:
        video_msgs.append(video_message(pending))
    for msg in video_msgs:
        await sess.handle(msg)

    est = sess.estimate()
    sess.mode = "pattern"
    record = sess._record(est, final=True)
    await sess.close()

    result = {"estimate": est.as_dict(), "record": record,
              "truth_av_offset_ms": room.truth_av_offset_ms,
              "expected_measured_ms": room.expected_measured_ms,
              "audio_stats": source.stats(),
              "audio_messages": len(audio_msgs),
              "video_messages": len(video_msgs),
              "video_samples": sum(len(m["t_ms"]) for m in video_msgs),
              "hello": client.hello(),
              "reverted": (seam.virtuals["crystal"]["effect"]["type"] == "blackhole"
                           and seam.virtuals["strip"]["effect"]["type"] == "orbits1d")}
    if verbose:
        d = est.as_dict()
        print(f"  room: light {room.light_latency_s*1000:.0f} ms, audio path "
              f"{room.audio_path_s*1000:.0f} ms, camera pipeline "
              f"{room.camera_pipeline_s*1000:.0f} ms, mic capture "
              f"{room.mic_capture_latency_s*1000:.0f} ms, {room.fps:.0f} fps")
        print(f"  kiosk sent: {result['audio_messages']} audio messages "
              f"({source.stats()['hops']} hops, anchor spread "
              f"{source.stats()['anchor_spread_ms']} ms), "
              f"{result['video_samples']} video samples in "
              f"{result['video_messages']} messages")
        print(f"  TRUTH av_offset = {room.truth_av_offset_ms:+.1f} ms   "
              f"(expected measured incl. the five named systematics = "
              f"{room.expected_measured_ms:+.1f} ms)")
        print(f"  MEASURED        = {d['av_offset_ms']:+} ms ± "
              f"{d['sigma_ms']} ms   ok={d['ok']} region={d['light_region']}")
        print(f"    light lag {d['light_lag']['lag_ms']} ms (peak ratio "
              f"{d['light_lag']['peak_ratio']}), audio lag "
              f"{d['audio_lag']['lag_ms']} ms (peak ratio "
              f"{d['audio_lag']['peak_ratio']})")
        print(f"    source on the record: "
              f"{record['phone'].get('source')} / "
              f"{record['phone'].get('host')} / "
              f"{record['phone'].get('pose_name')}")
        print(f"    statement: {d['statement']}")
    return result


async def _fake_spawn(pcm: bytes):
    return FakeArecord(pcm)


def check(result: dict, room: KioskRoom, *, margin_ms: float = 14.0) -> None:
    est = result["estimate"]
    assert est["ok"], f"no number produced: {est['reason']} — {est['statement']}"
    err = abs(est["av_offset_ms"] - room.expected_measured_ms)
    tol = 2 * (est["sigma_ms"] or 0) + margin_ms
    assert err <= tol, (
        f"measured {est['av_offset_ms']} vs expected "
        f"{room.expected_measured_ms:.1f} (truth {room.truth_av_offset_ms:.1f}): "
        f"err {err:.1f} > tol {tol:.1f}")
    # THE SIGN, which is the outcome worse than no measurement at all.
    if room.expected_measured_ms < 0:
        assert est["av_offset_ms"] < 0 and "AHEAD" in est["statement"], est
    else:
        assert est["av_offset_ms"] > 0 and "BEHIND" in est["statement"], est
    assert result["reverted"], "the room was not put back after the pattern"
    # the record names the machine that measured it
    phone = result["record"]["phone"]
    assert phone.get("source") == "kiosk", phone
    assert phone.get("client_version") and phone.get("host"), phone
    # and the two kiosk systematics are NAMED, in the right directions
    terms = " ".join(t["term"] for t in result["estimate"]["systematics"])
    assert "camera pipeline" in terms and "microphone pipeline" in terms, terms


def red_controls(room: KioskRoom, result: dict, *,
                 storage_dir: Path | None = None) -> list:
    """A PROOF THAT CANNOT FAIL ON THE DEFECT IT WAS WRITTEN FOR IS
    DECORATION. Two deliberate corruptions, each of the exact shape this
    instrument exists to refuse, and `check()` has to go red on both.

      1. THE SIGN, flipped. A wrong-direction answer is the one outcome
         worse than no answer, and it looks perfectly plausible.
      2. THE AUDIO CLOCK, naive. Stamping the envelope at the read instead
         of the first sample it contains — a shift of about a batch length,
         invisible in every number the run reports."""
    out = []
    flipped = {**result, "estimate": {**result["estimate"]}}
    flipped["estimate"]["av_offset_ms"] = -result["estimate"]["av_offset_ms"]
    try:
        check(flipped, room)
        out.append(("sign flipped", False, "check() PASSED a flipped sign"))
    except AssertionError as exc:
        out.append(("sign flipped", True, str(exc).split("\n")[0][:120]))
    naive = asyncio.run(run_kiosk_room(room, storage_dir=storage_dir,
                                       verbose=False, naive_audio_stamp=True))
    try:
        check(naive, room)
        out.append(("audio stamped at the read", False,
                    f"check() PASSED a naive audio stamp "
                    f"({naive['estimate']['av_offset_ms']:+} ms)"))
    except AssertionError as exc:
        out.append(("audio stamped at the read", True,
                    f"{naive['estimate']['av_offset_ms']:+} ms — "
                    + str(exc).split("\n")[0][:100]))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep", action="store_true")
    args = ap.parse_args(argv)
    import tempfile
    rooms = [KioskRoom()]
    if args.sweep:
        rooms += [
            # lights genuinely BEHIND the sound: the sign must flip
            KioskRoom(light_latency_s=0.420, audio_path_s=0.040, fps=60,
                      seed=11),
            # a long snapcast-class audio path and a slow camera pipeline
            KioskRoom(light_latency_s=0.030, audio_path_s=0.900, fps=24,
                      camera_pipeline_s=0.090, sensor_noise=6, seed=5),
            # a badly-offset client clock and a noisy, jittery machine
            KioskRoom(phone_clock_offset_s=-86400.5, rtt_s=0.040,
                      read_jitter_s=0.020, mic_noise_db=6, seed=9),
        ]
    with tempfile.TemporaryDirectory() as td:
        for i, room in enumerate(rooms):
            print(f"\n=== simulated kiosk room {i + 1}/{len(rooms)} ===")
            result = asyncio.run(run_kiosk_room(room, storage_dir=Path(td)))
            check(result, room)
            print("  ✓ within its own stated tolerance; sign correct; "
                  "room reverted; the record names the kiosk")
            if i == 0:
                print("  red controls (both MUST go red):")
                for name, went_red, detail in red_controls(
                        room, result, storage_dir=Path(td)):
                    print(f"    {'RED ok' if went_red else 'NOT RED'}  "
                          f"{name}: {detail}")
                    assert went_red, (
                        f"the harness did not catch {name} — a proof that "
                        f"cannot fail on its own defect is decoration")
    print("\nKIOSK AV-SYNC SPEC OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
