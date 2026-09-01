"""Regression proof for the tv-mapper cold-load failure (VENDOR.md #29).

THE DEFECT, as it appeared in his room on 2026-09-01: `tv-mapper` is stored
`active: true` with a real effect, and after every SPECTRA restart it came up
DARK.  Deterministic across restarts.  Nothing above INFO said so — the only
traces were the `fx.virtuals` state table printing `tv-mapper False False
False` and a liveness gap reading "not active — effect restore failed
silently at config load", which was itself a guess and was WRONG about the
cause.

THE ACTUAL CAUSE is load ORDER, not any one effect's schema:

  * `Virtuals.create_from_config` restored a stored effect by calling
    `set_effect()`, which unconditionally did `self.active = True` — even for
    a virtual whose stored `active` is FALSE, which the loop then immediately
    set back to False two statements later.
  * On its own that round-trip is a no-op.  On a DEVICE virtual it is not:
    activating registers segments on the backing device, and
    `Device.add_segments_batch` deactivates every EXTERNAL virtual streaming
    to a device whose own device-virtual is activating.
  * His `tv-mapper` (config index 14) is exactly such an external virtual,
    over `tv-backlight` + both sconces.  `sconce-kitchen-left` (index 22) and
    `sconce-kitchen-right` (index 27) are device virtuals stored
    `active: false` WITH a stored `singleColor` effect, so they load AFTER
    tv-mapper, flicker active for the length of one restore, evict it, and go
    back down.  Nothing ever brings tv-mapper back.

    Live evidence, his journal, 2026-09-01 06:44:31,919:
        fx.devices — Device sconce-kitchen-left: Device virtual
        'sconce-kitchen-left' activating - deactivating external virtuals:
        {'tv-mapper'}

HOW IT BECAME LIVE: a device virtual with NO stored `effect` key never
enters the restore branch, so it never activated and never evicted anything.
His three now hold `singleColor` at `#000000` brightness 0.0 — literally
`room_mapping.MAP_EFFECT_TYPE` + `BLACK` — with `pixelRange`/`pixelPattern`
in their stored `effects` history, lamps that exist nowhere else.
`activate_for_capture` writes an effect and raises the active flag through
`fx_seam`, and both facade routes `save_config()`: a capture run PERSISTS a
stored effect onto a device virtual that had none, arming the eviction on
every cold start after it. Genuine residue of his own runs, not corruption —
so nothing in his config was rewritten; the load path is what was wrong.

THE LYING REPAIR (captain's addendum 1): the evicted virtual still HOLDS an
effect object — it just runs no render thread.  A same-type effects PUT
therefore takes `_effects_put`'s in-place `active_effect.update_config()`
branch, which never touches `virtual.active`, and returns success: the
executor log fills with glide writes, the operator watches the repair "work",
and the fixture stays dark.  A TYPE-SWITCH write took the `set_effect()`
branch instead, which activates — which is why only a type switch ever
appeared to fix it.  That asymmetry was the bug's own best clue.

Cold start is proven in a FRESH INTERPRETER (subprocess), per
tests/test_light_mode_cold_start.py's precedent: config load order is exactly
the kind of thing a warm pytest process cannot speak to honestly.  Every
device here is a vendored dummy — his room is never touched.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


# ── the stored-config shape, his room's ordering, on dummy devices ─────────

def _device(did, pixels):
    return {"id": did, "type": "dummy",
            "config": {"name": did, "pixel_count": pixels}}


def _virtual(vid, is_device, segments, active, effect_type):
    entry = {
        "id": vid,
        "is_device": is_device,
        "auto_generated": False,
        "config": {"name": vid,
                   "mapping": "span" if is_device else "copy",
                   "rows": 1,
                   "transition_mode": "Add",
                   "transition_time": 0.4},
        "segments": segments,
        "active": active,
    }
    if effect_type:
        entry["effect"] = {"type": effect_type, "config": {}}
        entry["effects"] = {effect_type: {"type": effect_type, "config": {}}}
        entry["last_effect"] = effect_type
    return entry


def write_room_shaped_config(config_dir: Path) -> dict:
    """His `storage/spectra/fx-live/config.json` shape, minimally:

        idx 0  tv-backlight  device virtual, stored effect, active: false
        idx 1  tv-mapper     EXTERNAL copy-mapped virtual, active: TRUE
        idx 2  sconce        device virtual, stored effect, active: false
                             ^ loads AFTER tv-mapper — this is the whole bug

    Note tv-backlight loads BEFORE tv-mapper, so its own restore cannot
    evict anything: order, not device identity, is what decides.
    """
    config_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "configuration_version": "2.3.6",
        "devices": [_device("tv-backlight", 60), _device("sconce", 30)],
        "virtuals": [
            _virtual("tv-backlight", "tv-backlight",
                     [["tv-backlight", 0, 59, False, 0]], False, "singleColor"),
            _virtual("tv-mapper", False,
                     [["tv-backlight", 0, 59, False, 0],
                      ["sconce", 0, 29, False, 0]], True, "singleColor"),
            _virtual("sconce", "sconce",
                     [["sconce", 0, 29, False, 0]], False, "singleColor"),
        ],
        "audio": {}, "scenes": {}, "user_presets": {},
    }
    (config_dir / "config.json").write_text(json.dumps(config))
    return config


# ── the cold-start driver, run in a fresh interpreter ──────────────────────

_COLD_START = r'''
import asyncio, json, logging, os, sys
# INFO so the device layer's own eviction line ("deactivating external
# virtuals") is observable — without it that assertion would be vacuous.
logging.basicConfig(level=logging.INFO, format="%%(levelname)s %%(name)s %%(message)s")
sys.path.insert(0, os.getcwd())
from fx import headless
from fx.host import FxHost

config_dir = %(config_dir)r

async def main():
    headless.silence_audio()
    host = FxHost(config_dir)
    await host.start()
    v = host.virtuals.get("tv-mapper")
    result = {
        "active": bool(v.active),
        "has_effect": v.active_effect is not None,
        "effect_type": getattr(v.active_effect, "type", None),
        "restore_failures": dict(
            getattr(host.virtuals, "restore_failures", {})),
    }
    %(extra)s
    await host.shutdown()
    return result

out = asyncio.run(main())
sys.stdout.write("RESULT " + json.dumps(out) + "\n")
sys.stdout.flush(); sys.stderr.flush()
os._exit(0)
'''


def _cold_start(config_dir: Path, extra: str = "pass"):
    """Load the config in a genuinely fresh interpreter and report the end
    state of tv-mapper. `os._exit` per AGENTS.md: fx's TemporalEffect spawns
    non-daemon threads a harness never joins."""
    script = _COLD_START % {"config_dir": str(config_dir), "extra": extra}
    proc = subprocess.run([sys.executable, "-c", script],
                          cwd=REPO, capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    line = next(ln for ln in proc.stdout.splitlines()
                if ln.startswith("RESULT "))
    return json.loads(line[len("RESULT "):]), proc.stderr


# ── 1. the fix: the stored effect actually drives, from a cold start ───────

def test_cold_start_leaves_the_external_virtual_actually_driving(tmp_path):
    """THE headline regression. Before the fix this came back active=False,
    every single time, with nothing above INFO to explain it."""
    write_room_shaped_config(tmp_path / "fx")
    result, _ = _cold_start(tmp_path / "fx")

    assert result["active"] is True, (
        "tv-mapper is stored active:true and must be actually driving after "
        f"a cold load, got {result}")
    assert result["has_effect"] is True
    assert result["effect_type"] == "singleColor"
    assert result["restore_failures"] == {}


def test_a_stored_inactive_device_virtual_stays_inactive_and_keeps_its_effect(
        tmp_path):
    """The fix must not silently start something his config says is off:
    the sconce keeps its restored effect object and stays inactive, exactly
    the end state the old code reached — minus the transient activation that
    evicted its neighbour."""
    write_room_shaped_config(tmp_path / "fx")
    extra = ('s = host.virtuals.get("sconce");'
             ' result["sconce_active"] = bool(s.active);'
             ' result["sconce_effect"] = getattr(s.active_effect, "type", None)')
    result, _ = _cold_start(tmp_path / "fx", extra=extra)

    assert result["sconce_active"] is False
    assert result["sconce_effect"] == "singleColor"


def test_no_external_virtual_is_evicted_during_the_load(tmp_path):
    """Directly assert the eviction itself is gone, by its own log line —
    the sentence in his journal that named the cause."""
    write_room_shaped_config(tmp_path / "fx")
    _, stderr = _cold_start(tmp_path / "fx")
    assert "deactivating external virtuals" not in stderr, stderr


# ── 2. loudness: a restore that does not take must SHOUT, by name ──────────

def test_a_restore_that_does_not_take_is_reported_loudly_and_by_name(tmp_path):
    """The audit is the catch-all: whatever future shape stops a stored
    effect from driving, reading the end state back names it.  Driven here
    by a config whose stored effect type does not exist, which no
    per-virtual handler upstream can pre-empt."""
    config_dir = tmp_path / "fx"
    config = write_room_shaped_config(config_dir)
    config["virtuals"][1]["effect"]["type"] = "no-such-effect-type"
    (config_dir / "config.json").write_text(json.dumps(config))

    result, stderr = _cold_start(config_dir)

    assert "tv-mapper" in result["restore_failures"], result
    assert "ERROR" in stderr or "EFFECT RESTORE FAILED" in stderr, stderr
    assert "EFFECT RESTORE FAILED" in stderr, stderr
    assert "tv-mapper" in stderr
    assert "no-such-effect-type" in stderr, (
        "the log must name the STORED EFFECT TYPE, not just the virtual")


def test_the_audit_catches_an_eviction_even_if_one_is_reintroduced(tmp_path):
    """The audit must not depend on knowing HOW a virtual was stopped. Evict
    tv-mapper by hand, after the load, and prove the same check names it —
    so a future regression of this class cannot be silent even if the
    specific set_effect fix is bypassed."""
    write_room_shaped_config(tmp_path / "fx")
    extra = (
        'host.virtuals.get("tv-mapper").deactivate();'
        ' host.virtuals._audit_restored_effects(host.config["virtuals"]);'
        ' result["audit_after_manual_eviction"] = dict('
        '     host.virtuals.restore_failures)')
    result, stderr = _cold_start(tmp_path / "fx", extra=extra)

    named = result["audit_after_manual_eviction"]
    assert "tv-mapper" in named, named
    assert "NOT ACTIVE" in named["tv-mapper"], named
    assert "EFFECT RESTORE FAILED" in stderr and "tv-mapper" in stderr


# ── 3. the lying repair (captain's addendum 1) ────────────────────────────

_LYING_REPAIR = r'''
import asyncio, json, os, sys
sys.path.insert(0, os.getcwd())
from fx import headless
from fx.host import FxHost
from fx import facade

async def main():
    headless.silence_audio()
    host = FxHost(%(config_dir)r)
    await host.start()
    v = host.virtuals.get("tv-mapper")

    # Put the room in the exact post-defect state: the virtual holds a real
    # effect instance and runs no render thread. This is what an evicted
    # virtual looked like, and what a same-type write used to be told
    # "success" against.
    v.deactivate()
    assert v.active is False and v.active_effect is not None

    # A GLIDE write of a non-colour param: literally what his executor's
    # recent_writes showed landing on tv-mapper while it was dark. This is
    # the branch that never touches virtual.active — `use_tween` ->
    # effect.start_param_transitions(). (A colour-key write happens to take
    # the set_effect branch and self-repairs; that is not the reported
    # shape and would make this proof vacuous.)
    resp = await facade._effects_put(
        host, "tv-mapper",
        {"type": "singleColor", "config": {"brightness": 0.5},
         "transition_ms": 200},
    )
    body = resp.json()
    out = {
        "status_code": resp.status_code,
        "payload_status": body.get("status"),
        "active_after": bool(v.active),
        "repaired_and_verified": bool(v.active) and v.active_effect is not None,
        "reason": str(body.get("payload", "")),
    }
    await host.shutdown()
    return out

out = asyncio.run(main())
sys.stdout.write("RESULT " + json.dumps(out) + "\n")
sys.stdout.flush(); sys.stderr.flush()
os._exit(0)
'''


def _lying_repair(config_dir: Path):
    script = _LYING_REPAIR % {"config_dir": str(config_dir)}
    proc = subprocess.run([sys.executable, "-c", script],
                          cwd=REPO, capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    line = next(ln for ln in proc.stdout.splitlines()
                if ln.startswith("RESULT "))
    return json.loads(line[len("RESULT "):]), proc.stderr


def test_a_same_type_write_to_a_dead_virtual_never_reports_a_silent_success(
        tmp_path):
    """Captain's addendum 1: 'a repair that lies is worse than a failure that
    is loud'.  A same-type write against a virtual with no render thread must
    NOT come back a bare success while the fixture stays dark.  Either it
    repaired and VERIFIED by reading the instance back, or it refused loudly
    — never the third thing, which is what shipped.
    """
    write_room_shaped_config(tmp_path / "fx")
    result, stderr = _lying_repair(tmp_path / "fx")

    reported_success = (result["status_code"] == 200
                        and result["payload_status"] == "success")

    if reported_success:
        # Success is only allowed if the write VERIFIABLY took: the virtual
        # is actually driving now, read back from the live instance.
        assert result["repaired_and_verified"], (
            "the write reported success while tv-mapper was still not "
            f"driving — this is the lying repair: {result}")
        assert result["active_after"] is True, result
        # And an honest repair announces that it had to happen.
        assert "NOT ACTIVE" in stderr, (
            "a silent repair is still a report the operator cannot audit; "
            f"stderr had no notice: {stderr[-2000:]}")
    else:
        # A refusal is equally acceptable — but it must name the virtual.
        assert "tv-mapper" in result["reason"], result


def test_the_lying_repair_shape_is_red_against_the_unguarded_write(tmp_path):
    """A proof bar that cannot fail on the defect it was written for is
    decoration (AGENTS.md's own standing rule).  Drive the SAME scenario with
    the verification removed and prove it comes out as the lie: 200/success,
    virtual still not driving.
    """
    write_room_shaped_config(tmp_path / "fx")
    script = _LYING_REPAIR % {"config_dir": str(tmp_path / "fx")}
    # Neuter exactly the guard under test, nothing else.
    script = script.replace(
        "from fx import facade",
        "from fx import facade\n"
        "facade._verify_effect_took = lambda *a, **k: (True, '')",
    )
    proc = subprocess.run([sys.executable, "-c", script],
                          cwd=REPO, capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    line = next(ln for ln in proc.stdout.splitlines()
                if ln.startswith("RESULT "))
    result = json.loads(line[len("RESULT "):])

    assert result["status_code"] == 200 and result["payload_status"] == "success"
    assert result["active_after"] is False, (
        "the unguarded write is supposed to reproduce the lie — if this "
        "assertion fails the guarded test above is no longer proving "
        f"anything: {result}")
