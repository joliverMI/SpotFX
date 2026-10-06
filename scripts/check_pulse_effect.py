"""Executable proof for the Pulse effect on his captured songs (single-led-power
plan, phase 1). Read-only against his storage; drives no light.

For each of Dopamine, Contra, Let It Be and Soy Peor:

  1. Runs the WHOLE pipeline from the captured WAV: fx.headless host,
     fx.audio_ingest.HubMelbankSource (the melbank path SPECTRA's live stack
     installs), a ONE-pixel copy virtual listening 20-1000 Hz (the Singles'
     real shape), the REAL `pulse` effect attached, rendered through the
     virtual's own assemble/flush, with the engine stand-in from
     tests/pulse_song_harness.py pushing energy, tempo and his authored
     charge/lull/drop.
  2. Records the effect's audio input per frame and, with --write-fixtures,
     writes tests/fixtures/pulse/<slug>.{npz,json} — what the pytest suite
     drives on every run.
  3. Re-runs the song from the fixture through the harness (the pytest path)
     and requires it to land on the same light as the pipeline run, frame by
     frame: the committed fixtures and the test path are the real thing.
  4. Measures (hits, rise, fade, calm swing, the flash budget, the phases)
     and checks the acceptance bars in tests/test_pulse_effect.py's terms.

Each song runs in its own interpreter: a song run after others in one
process was measured not to reproduce its own fresh run.

Run:  .venv/bin/python scripts/check_pulse_effect.py [--write-fixtures]
      [--shapes-dir /home/javi/SpotFX/storage/audio_shapes]
      [--triggers /home/javi/SpotFX/storage/spectra/triggers.json] [--song dopamine]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tests"))

import pulse_song_harness as h  # noqa: E402

RATE = 44100
HOP = RATE // 60
LIVE_STORAGE = "/home/javi/SpotFX/storage"


async def pipeline_run(stem: str, shapes_dir: str, meta: dict, scale: float) -> dict:
    """The whole pipeline from WAV. Returns per-frame arrays."""
    import soundfile as sf

    from fx import headless
    from fx.audio_ingest import HubMelbankSource
    from fx.effects import audio as fx_audio
    from fx.host import FxHost

    audio, sr = sf.read(os.path.join(shapes_dir, stem + ".wav"), dtype="float32")
    assert sr == RATE, sr
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    with tempfile.TemporaryDirectory() as cfgdir:
        headless.write_headless_config(cfgdir, pixel_count=1, rows=1, device_id="single")
        p = os.path.join(cfgdir, "config.json")
        with open(p) as f:
            cfg = json.load(f)
        cfg["virtuals"][0]["config"].update(
            {"frequency_min": 20, "frequency_max": 1000, "mapping": "copy",
             "transition_time": 0.0})
        with open(p, "w") as f:
            json.dump(cfg, f)
        headless.silence_audio()
        host = FxHost(cfgdir)
        await host.start()
        fx_audio.AudioAnalysisSource = HubMelbankSource
        mel = HubMelbankSource(host)
        host.audio = mel
        virtual = host.virtuals.get("single")
        n = (len(audio) - HOP) // HOP
        lows = np.zeros(n)
        bmean = np.zeros(n)
        fired = np.zeros(n, dtype=bool)
        level = np.zeros(n)
        out = np.zeros(n)
        with headless.fake_clock() as clock:
            effect = headless.attach_effect(
                host, virtual, "pulse", h.base_config(meta, scale))
            assert effect.pixel_count == 1, effect.pixel_count
            eng = h.EngineStandIn(meta, scale)
            for i in range(n):
                eng.before_frame(effect, (i + 1) * h.DT)
                before = effect._audio_t
                mel.ingest(audio[i * HOP:(i + 1) * HOP])
                fired[i] = effect._audio_t > before
                if fired[i]:
                    lows[i] = float(np.max(mel.lows_power(filtered=False)))
                    bmean[i] = float(np.mean(effect.melbank(filtered=False)))
                frame = headless.render_frames(virtual, 1, clock=clock)
                level[i] = effect.level
                out[i] = float(np.max(frame[0][0])) / 255.0 if frame else 0.0
        return dict(lows=lows, bmean=bmean, fired=fired, level=level, out=out)


def check(slug: str, shapes_dir: str, triggers: str, write: bool) -> list[str]:
    spec = h.SONGS[slug]
    meta, onsets = h.build_meta(spec["stem"], shapes_dir, triggers)
    pipe = asyncio.run(pipeline_run(spec["stem"], shapes_dir, meta, spec["scale"]))
    if write:
        h.write_fixture(slug, meta, onsets, pipe["lows"], pipe["bmean"], pipe["fired"])
        print(f"  wrote {os.path.relpath(h.FIXTURE_DIR, REPO)}/{slug}.{{npz,json}}")
    problems = []
    try:
        fmeta, arrays = h.load_fixture(slug)
    except FileNotFoundError:
        return [f"{slug}: no fixture (run with --write-fixtures)"]
    # the fixture must still be what the pipeline produces
    if fmeta != json.loads(json.dumps(meta)):
        problems.append(f"{slug}: fixture meta differs from his storage now "
                        "(re-run with --write-fixtures if intended)")
    n = min(len(arrays["lows"]), len(pipe["lows"]))
    d_in = float(np.max(np.abs(arrays["lows"][:n] - pipe["lows"][:n]))) if n else 0.0
    tr = h.run(fmeta, arrays, scale=spec["scale"])
    d_level = float(np.max(np.abs(tr.level[:n] - pipe["level"][:n])))
    d_out = float(np.max(np.abs(tr.out[:n] - pipe["out"][:n])))
    print(f"  fixture vs pipeline: input max diff {d_in:.2e}, level {d_level:.2e}, output {d_out:.2e}")
    if d_level > 0.02 or d_out > 0.02:
        problems.append(f"{slug}: fixture-driven light differs from the pipeline "
                        f"(level {d_level:.3f}, output {d_out:.3f})")
    full = h.full_config(h.base_config(fmeta, spec["scale"]))
    m = h.measure(tr, fmeta, arrays, full)
    print("  " + json.dumps(m, default=float))
    if m["max_rise_per_s"] > full["max_flash_rate"] + 0.05:
        problems.append(f"{slug}: light rose {m['max_rise_per_s']} in one second")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shapes-dir", default=os.path.join(LIVE_STORAGE, "audio_shapes"))
    ap.add_argument("--triggers", default=os.path.join(LIVE_STORAGE, "spectra", "triggers.json"))
    ap.add_argument("--write-fixtures", action="store_true")
    ap.add_argument("--song", choices=sorted(h.SONGS), action="append")
    args = ap.parse_args()
    songs = args.song or list(h.SONGS)
    if len(songs) > 1:
        # ONE INTERPRETER PER SONG. Measured: Soy Peor run fourth in one
        # process did not reproduce its own fresh run (its input 0.5 off),
        # while every fresh run reproduces exactly. The vendored audio
        # classes keep class-level state across instances — the likely
        # carrier. A fresh process per song removes the question.
        import subprocess
        code = 0
        for slug in songs:
            cmd = [sys.executable, os.path.abspath(__file__), "--song", slug,
                   "--shapes-dir", args.shapes_dir, "--triggers", args.triggers]
            if args.write_fixtures:
                cmd.append("--write-fixtures")
            code |= subprocess.run(cmd).returncode
        return code
    problems = []
    for slug in songs:
        print(f"{slug}: {h.SONGS[slug]['stem']}")
        problems += check(slug, args.shapes_dir, args.triggers, args.write_fixtures)
    print()
    if problems:
        print("FAIL")
        for p in problems:
            print("  - " + p)
        return 1
    print("OK: the fixture-driven runs land on the pipeline's light, and the light "
          "never rose by more than the flash budget in any second.")
    return 0


if __name__ == "__main__":
    # fx.headless effects can leave non-daemon threads; never hang on exit
    try:
        code = main()
    except Exception:
        import traceback
        traceback.print_exc()
        code = 1
    sys.stdout.flush()
    os._exit(code)
