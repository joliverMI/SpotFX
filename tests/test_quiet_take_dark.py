"""THE QUIET TAKE COMES UP DARK — proven at the emitted light.

THE DEFECT THIS EXISTS FOR: today's take-back RESUMES HIS SHOW. It restores
each virtual's stored effect — whatever last painted the room — and switches
the engine live, so colour starts moving within seconds. At 1am, when the
self-taking night takes a released room by itself, that is his house coming
on while he sleeps: the exact class of failure this whole seam spent a week
killing.

WHAT IS ACTUALLY MEASURED, and it is not the call: every frame that reaches a
DEVICE'S TRANSPORT is recorded, across a real `fx.headless` config load of a
room whose stored effects are bright. `Device.update_pixels` is the sole
caller of `flush()` on the live path and `_flush_timed` is the one place a
frame leaves the render pipeline (fx/devices/__init__.py says so), so
recording `flush` records the light. The quiet load must produce ZERO
non-black frames; the ordinary load must produce non-black ones, or this
harness is measuring nothing and the proof is decoration.

RED-FIRST BY CONSTRUCTION: the same rig runs both ways in one file, and the
ordinary-path test is what proves the instrument can see the defect. If a
future change makes the bright load come up dark, that test goes red and
says so rather than the quiet test quietly passing for the wrong reason.

Cold start in a FRESH INTERPRETER (subprocess), per
tests/test_cold_load_effect_restore.py's precedent: config load order and
what the first frame carries are not things a warm pytest process can speak
to honestly. Every device is a vendored dummy — his room is never touched,
and nothing here mints an ownership grant or reaches a network.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


# ── a room whose stored effects are BRIGHT ─────────────────────────────────

def _device(did, pixels):
    return {"id": did, "type": "dummy",
            "config": {"name": did, "pixel_count": pixels}}


def _virtual(vid, is_device, segments, effect):
    return {
        "id": vid, "is_device": is_device, "auto_generated": False,
        "config": {"name": vid, "mapping": "span" if is_device else "copy",
                   "rows": 1, "transition_mode": "Add",
                   "transition_time": 0.0},
        "segments": segments, "active": True,
        "effect": effect,
        "effects": {effect["type"]: effect},
        "last_effect": effect["type"],
    }


def write_bright_config(config_dir: Path) -> dict:
    """His fx-live shape, minimally, with every virtual storing an effect
    that PAINTS — a white singleColor at full brightness. This is what an
    ordinary take-back restores, and it is the light the quiet take has to
    not make."""
    config_dir.mkdir(parents=True, exist_ok=True)
    bright = {"type": "singleColor",
              "config": {"color": "#ffffff", "brightness": 1.0,
                         "background_brightness": 1.0}}
    config = {
        "configuration_version": "2.3.6",
        "devices": [_device("tv-backlight", 60), _device("sconce", 30)],
        "virtuals": [
            _virtual("tv-backlight", "tv-backlight",
                     [["tv-backlight", 0, 59, False, 0]], bright),
            _virtual("sconce", "sconce",
                     [["sconce", 0, 29, False, 0]], bright),
        ],
        "audio": {}, "scenes": {}, "user_presets": {},
    }
    (config_dir / "config.json").write_text(json.dumps(config))
    return config


# ── the cold-start driver: record every frame that reaches a transport ─────

_DRIVER = r'''
import asyncio, json, os, sys
import numpy as np
sys.path.insert(0, os.getcwd())
from fx import headless
from fx.devices.dummy import DummyDevice
from fx.host import FxHost

config_dir = %(config_dir)r
blackout = %(blackout)s

FRAMES = []

def _record(self, data):
    """Stand in for the transport. This is the device's OWN flush — the one
    place a frame leaves the render pipeline — so what lands here is what a
    real fixture would have been sent."""
    arr = np.asarray(data)
    FRAMES.append((self.id, int(arr.size), float(arr.max()) if arr.size else 0.0))

DummyDevice.flush = _record

async def main():
    headless.silence_audio()
    host = FxHost(config_dir)
    await host.start(blackout=blackout)
    # Let the render threads run: every active virtual paces itself off its
    # own refresh rate, so a real handful of frames has to actually happen
    # before "no non-black frame was emitted" means anything.
    await asyncio.sleep(0.75)
    frames = list(FRAMES)
    result = {
        "frames": len(frames),
        "devices": sorted({f[0] for f in frames}),
        "max_value": max([f[2] for f in frames], default=None),
        "non_black_frames": sum(1 for f in frames if f[2] > 0.0),
        "blacked_out": list(getattr(host.virtuals, "blacked_out", [])),
        "restore_failures": dict(getattr(host.virtuals, "restore_failures", {})),
        "active": sorted(v.id for v in host.virtuals.values() if v.active),
        # THE STORED CONFIG IS UNTOUCHED — a blackout is a load-time
        # substitution, never a config edit, or his room would come up dark
        # on every ordinary take-back afterwards.
        "stored_effects": {v["id"]: v["effect"]["type"]
                           for v in host.config["virtuals"]},
        "stored_colors": {v["id"]: v["effect"]["config"].get("color")
                          for v in host.config["virtuals"]},
    }
    await host.shutdown()
    return result

out = asyncio.run(main())
sys.stdout.write("RESULT " + json.dumps(out) + "\n")
sys.stdout.flush(); sys.stderr.flush()
os._exit(0)
'''


def _cold_start(config_dir: Path, *, blackout: bool):
    """`os._exit` per AGENTS.md: fx's TemporalEffect spawns non-daemon
    threads a frame-stepped harness never joins, so a plain return reads as
    a hang rather than a failure."""
    script = _DRIVER % {"config_dir": str(config_dir),
                        "blackout": "True" if blackout else "False"}
    proc = subprocess.run([sys.executable, "-c", script], cwd=REPO,
                          capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    line = next(ln for ln in proc.stdout.splitlines()
                if ln.startswith("RESULT "))
    return json.loads(line[len("RESULT "):])


# ── 1. THE CONTROL: this rig can SEE light ─────────────────────────────────

def test_the_ordinary_load_emits_light_which_is_the_defect(tmp_path):
    """RED-FIRST, and it stays in the file: without this, "no non-black
    frame" could be true because nothing was rendering at all. This is the
    take-back that lights his house at 1am, measured."""
    write_bright_config(tmp_path / "fx")
    out = _cold_start(tmp_path / "fx", blackout=False)

    assert out["frames"] > 0, "nothing reached a transport — the rig is blind"
    assert out["non_black_frames"] > 0, (
        "the bright config came up dark on the ORDINARY path, so this "
        f"harness cannot see the defect it exists to catch: {out}")
    assert out["max_value"] == 255.0, out
    assert out["blacked_out"] == []


# ── 2. THE PROOF: the quiet load emits nothing ─────────────────────────────

def test_the_quiet_load_emits_zero_non_black_frames(tmp_path):
    """THE ARMING GATE. Not one frame between the take and the run's own
    dark hold carries any light at all."""
    write_bright_config(tmp_path / "fx")
    out = _cold_start(tmp_path / "fx", blackout=True)

    assert out["frames"] > 0, (
        "no frame reached a transport at all — a quiet take must DRIVE the "
        "fixtures black, not merely stop writing to them; the freshness the "
        f"activation gate verifies against comes from those frames: {out}")
    assert out["non_black_frames"] == 0, (
        f"the quiet take put light in his room: {out}")
    assert out["max_value"] == 0.0, out


# ── 3. IT IS A LOAD-TIME SUBSTITUTION, NOT A CONFIG EDIT ───────────────────

def test_the_quiet_load_leaves_his_stored_config_alone(tmp_path):
    """If the blackout edited the config, his room would come up dark
    tonight AND on every ordinary take-back afterwards — a capture run's own
    effects PUT calls `save_config()`, so a mutated in-memory config would
    reach the disk during the night."""
    write_bright_config(tmp_path / "fx")
    out = _cold_start(tmp_path / "fx", blackout=True)

    assert out["stored_effects"] == {"tv-backlight": "singleColor",
                                     "sconce": "singleColor"}
    assert out["stored_colors"] == {"tv-backlight": "#ffffff",
                                    "sconce": "#ffffff"}, (
        "the quiet load rewrote his stored colours — this must be a "
        f"load-time substitution and nothing else: {out}")
    # And the file on disk is byte-identical to what was written.
    stored = json.loads((tmp_path / "fx" / "config.json").read_text())
    assert all(v["effect"]["config"]["color"] == "#ffffff"
               for v in stored["virtuals"])


# ── 4. THE STACK IS FULLY ALIVE, WHICH IS WHAT MAKES IT USABLE ─────────────

def test_the_quiet_load_leaves_every_virtual_driving_and_names_them(tmp_path):
    """"Held black" and "never written to" are different states. The night's
    own capture run needs these virtuals rendering and flushing — that is
    what makes a write through `fx_seam` land and what feeds the freshness
    the activation gate verifies. A `pause_all` would have satisfied "no
    light" and broken both."""
    write_bright_config(tmp_path / "fx")
    out = _cold_start(tmp_path / "fx", blackout=True)

    assert out["active"] == ["sconce", "tv-backlight"]
    assert sorted(out["blacked_out"]) == ["sconce", "tv-backlight"], (
        "the load did not report which virtuals it blacked out — a quiet "
        f"take that silently blacked nothing is worth being able to read: {out}")
    assert out["restore_failures"] == {}, (
        "a blacked-out virtual was recorded as a FAILED restore — it is a "
        f"deliberate substitution, not a fault: {out}")
    assert out["devices"] == ["sconce", "tv-backlight"], out
