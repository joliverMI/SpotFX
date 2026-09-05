"""ONE OBSERVATION OF THE SELF-TAKING NIGHT, IN A FRESH INTERPRETER.

Read as text and executed by `tests/test_selftake_dark_e2e.py` via
`python -c` — that file's docstring is the binding statement for what is
real here, what is substituted and why. This module is never imported: it
takes `[work_dir, mode]` on argv, prints one `RESULT <json>` line and exits
through `os._exit` (fx's TemporalEffect spawns non-daemon threads a
frame-stepped harness never joins).

MODES
  selftake          the armed, quiet, self-taking night — the thing proven
  ordinary          the same night with the SPECTRA side built UNQUIET, so
                    the stored effects restore and the engine goes live:
                    the red-first control
  restart_released  the real lifespan's light-relevant startup steps against
                    a RELEASED record
  restart_owned     the same steps against an OWNED record — that claim's
                    own control
"""
import asyncio
import json
import os
import pathlib
import sys
import time

WORK = pathlib.Path(sys.argv[1])
MODE = sys.argv[2]
QUIET = MODE != "ordinary"

sys.path.insert(0, os.getcwd())

# ── isolation, BEFORE spectra.config is imported ───────────────────────────
# SPECTRA_STORAGE_DIR moves the night stores, the take snapshot and
# FX_LIVE_CONFIG_DIR together; the two fixed repo-relative paths below do
# NOT move with it and are repointed by hand.
os.environ["SPECTRA_STORAGE_DIR"] = str(WORK / "storage")
os.environ["SPECTRA_NIGHT_SELF_TAKE"] = "1"
os.environ.pop("SPECTRA_HANDOVER_ARMED", None)

import numpy as np                                          # noqa: E402
from fx import device_model, headless                       # noqa: E402
from fx import light_ownership as lo                        # noqa: E402
from fx.devices.dummy import DummyDevice                    # noqa: E402

lo.OWNERSHIP_FILE = WORK / "ownership.json"
device_model.CATEGORIES_FILE = WORK / "device_categories.json"

# ── the instrument: every frame that reaches a device's transport ──────────
# `Device.update_pixels` is the sole caller of `flush()` on the live path and
# `_flush_timed` is the one place a frame leaves the render pipeline
# (fx/devices/__init__.py says so), so recording `flush` records the light.

PHASE = {"now": "before"}
FRAMES = []


def _record(self, data):
    arr = np.asarray(data)
    FRAMES.append({"phase": PHASE["now"], "device": self.id,
                   "max": float(arr.max()) if arr.size else 0.0,
                   "t": round(time.monotonic(), 4)})


DummyDevice.flush = _record

from spectra import config as scfg                          # noqa: E402
from spectra.services import (capture_queue, capture_runs,  # noqa: E402
                              engine, handover,
                              night_run, night_take, room_mapping)

SETTLE_S = 0.35
#: HOW LONG THE ROOM IS ALLOWED TO STILL BE LIT AFTER THE REVERT IS ISSUED.
#: A render pipeline has latency: a frame already assembled with the lamp's
#: pixels can reach a transport a moment after `close_hold()` returns, and
#: asserting the room is black the instant a write is ISSUED would be
#: asserting something physically false. So the drain is MEASURED and
#: bounded rather than labelled away — `lit_after_revert_ms` reports how far
#: past the revert the last lit frame actually landed, and
#: `lit_after_drain` counts anything past this bound, which must be zero.
#: (Found the honest way: an early build flipped the phase label before
#: awaiting the revert and one lamp frame landed on the far side of it,
#: which read as a stray light in the room and was a race in the ruler.)
REVERT_DRAIN_S = 0.25
LAMP_VID = "sconce"
VIRTUAL_IDS = ["tv-backlight", "sconce"]
WHITE = "#ffffff"

MEASURING = {"present": True, "locked": True, "session_id": "sess-e2e",
             "pose_id": "pose-e2e", "refusal": "", "unable": "",
             "native": True, "source": "native", "calibration_grade": True,
             "calibration_refusal": "", "aiming": True,
             "measured_by": "the capture client", "client": {}, "lever": {},
             "host": {"state": "present"}}

TRIGGER = {"event": "sleep-window-start", "ts": "2026-09-05T01:12:00Z",
           "source": "home-assistant"}

EXEC_MODES = {}
NOTES = []
#: When the run's own revert LANDED (`close_hold()` returned). Everything
#: after it plus REVERT_DRAIN_S must be black.
REVERT = {"at": None}


def _executor_modes():
    """The two objects the show actually writes through — the drift
    conductor's and the response engine's — never a third copy of the
    answer."""
    return [engine.conductor.executor.mode, engine.responses.executor.mode]


def _sides_factory():
    """The REAL production sides with two departures, both named.

    open_audio=False: nothing offline may enumerate a host audio device.
    In `ordinary` mode the SPECTRA side is built UNQUIET regardless of what
    the take asked for — that is the control, and it opens exactly the two
    light sources the quiet take closes (stored effects restore, and
    `engine.go_live` points the conductor at the facade)."""
    real = handover.production_sides

    def sides(*, quiet=False):
        built = real(quiet=quiet)
        built[lo.SPECTRA] = handover.SpectraSide(
            config_dir=str(scfg.FX_LIVE_CONFIG_DIR), open_audio=False,
            quiet=quiet and QUIET)
        return built
    return sides


def _stub_the_two_network_touchpoints():
    """`release.release_room` reaches outside this process in exactly two
    places, and neither may reach his machine: the external LedFX virtuals
    list and `SpotEffectsSide.verify_quiesced`'s systemctl probe. Everything
    else about the release — the Hue fade (a no-op with no Hue device), the
    live-stack teardown, the read-back verification — is the production
    function, unchanged."""
    from spectra.services import ledfx_release

    async def _no_virtuals(*a, **kw):
        return {}

    async def _quiesced(self):
        return True

    ledfx_release.get_all_virtuals = _no_virtuals
    handover.SpotEffectsSide.verify_quiesced = _quiesced


async def _price(items, now=None):
    """A window the declared queue fits in. Priced-to-fit rather than
    re-deriving his 05:30 bound in a test — the bound itself is
    `tests/test_night_run.py`'s subject, not this file's."""
    return {"items": [{"name": getattr(i, "name", "item"), "seconds": 5.0}
                      for i in items],
            "total_seconds": 5.0 * max(1, len(items)),
            "window_seconds": 9999.0,
            "planned_end": time.time() + 9999,
            "planned_end_label": night_run.PLANNED_END_LABEL}


# ── the representative calibration item ────────────────────────────────────

async def _run_queue(items, *, label="", run=None, save=None, guard=None,
                     **kw):
    """WHAT A CAPTURE ITEM DOES TO THE LIGHTS, through the real machinery.

    The camera half is absent — none exists offline, and `capture_runs`' own
    gate refuses a calibration-grade run without a native capture session by
    design. THE LIGHT-DRIVING HALF IS PRODUCTION CODE, not a re-enactment of
    it: `room_mapping.MappingProgram` (the same program a real map run
    builds) over `flare_preview_hold.open_program_hold` (the same ONE hold),
    so the run's snapshot, its dark step, its emitter lamp and its revert
    are the real ones with the real constants.

    Between the dark step and the lamp it DRIVES THE SHOW: the drift
    conductor's own executor is handed the write a leg makes, at full white,
    on every virtual, and the response engine's is handed a glide. Under a
    quiet take those are still the RecordingExecutor and neither reaches a
    fixture; on the ordinary path they are the FacadeExecutor and the room
    lights up. That difference is the second half of what "quiet" means, and
    it is the half no existing proof measures with a pipeline underneath."""
    from spectra.services import flare_preview_hold

    EXEC_MODES["during_queue"] = _executor_modes()
    program = room_mapping.MappingProgram(list(VIRTUAL_IDS))
    ceiling = room_mapping.run_ceiling_s(30.0)

    # THE DARK STEP — and the hold's own snapshot, read through the real
    # `fx_seam.get_virtuals()` before anything is written. What that snapshot
    # holds is what the revert below restores, which is why it matters that
    # the take came up black.
    PHASE["now"] = "queue_dark"
    opened = await flare_preview_hold.open_program_hold(
        program, 0.0, step="dark",
        heartbeat_timeout_s=flare_preview_hold.HEARTBEAT_TIMEOUT_S,
        max_duration_s=ceiling)
    NOTES.append(f"hold dark step: held={opened.get('held')}")
    await asyncio.sleep(SETTLE_S)

    PHASE["now"] = "queue_engine_drive"
    for vid in VIRTUAL_IDS:
        await engine.conductor.executor.jump(
            vid, "singleColor",
            {"color": WHITE, "brightness": 1.0,
             "background_brightness": 1.0})
        await engine.responses.executor.glide(
            vid, "singleColor", {"brightness": 1.0}, 0)
    await asyncio.sleep(SETTLE_S)

    # THE EMITTER LAMP — one emitter, the rest of the room still black, the
    # real `_writes(lit=True)` payload.
    PHASE["now"] = "queue_lamp"
    program.select([LAMP_VID])
    await flare_preview_hold.open_program_hold(
        program, 0.0, step="lit",
        heartbeat_timeout_s=flare_preview_hold.HEARTBEAT_TIMEOUT_S,
        max_duration_s=ceiling)
    await asyncio.sleep(SETTLE_S)

    # THE REVERT — the real `close_hold()`, restoring the snapshot it took.
    PHASE["now"] = "queue_revert"
    reverted = await flare_preview_hold.close_hold()
    REVERT["at"] = time.monotonic()
    NOTES.append(f"hold close: {reverted}")
    await asyncio.sleep(SETTLE_S)

    PHASE["now"] = "queue_done"
    await asyncio.sleep(SETTLE_S)
    return run


def _wrap_give_back():
    """Label the frames the real give-back produces without changing what it
    does — `night_run` calls this through the module attribute, so the
    production function still runs."""
    real = night_take.give_back

    async def give_back(**kw):
        PHASE["now"] = "give_back"
        try:
            return await real(**kw)
        finally:
            PHASE["now"] = "after"
    night_take.give_back = give_back


# ── the night ──────────────────────────────────────────────────────────────

async def run_night() -> dict:
    headless.silence_audio()
    _stub_the_two_network_touchpoints()
    handover.production_sides = _sides_factory()
    night_run.price_items = _price
    capture_runs.session_view = lambda: dict(MEASURING)
    capture_queue.run_queue = _run_queue
    _wrap_give_back()

    lo._save(lo.OwnershipRecord(owner=lo.RELEASED))
    night_run.save_declaration(
        "self-take e2e", [{"kind": "map", "room_id": "e2e-room",
                           "label": "e2e emitter"}])

    EXEC_MODES["before"] = _executor_modes()
    PHASE["now"] = "take"
    run = await night_run.start(TRIGGER)

    took = bool((run.take or {}).get("self_taken"))
    owner_after_take = lo.load().owner
    blacked = list((run.take or {}).get("blacked_out") or [])
    if not took:
        NOTES.append(f"the take did not happen: {run.refusal} {run.detail}")

    # Wait for the night's own task — the queue, the give-back and the exit
    # report all run inside it.
    deadline = time.monotonic() + 120
    while night_run.running() and time.monotonic() < deadline:
        await asyncio.sleep(0.05)
    PHASE["now"] = "after"
    await asyncio.sleep(0.75)

    from spectra.services.live_host import live
    record = night_run.last_night() or {}
    take_block = record.get("take") or {}
    return {
        "mode": MODE,
        "took_the_room": took,
        "owner_after_take": owner_after_take,
        "blacked_out": blacked,
        "night_state": record.get("state"),
        "night_refusal": record.get("refusal"),
        "night_detail": record.get("detail"),
        "gave_back": bool(take_block.get("given_back")),
        "gave_back_to": take_block.get("given_back_to"),
        "announce": list(take_block.get("announce") or []),
        "owner_final": lo.load().owner,
        "holding_after": night_take.holding(),
        "live_active_after": bool(live.active),
        "lamp_virtual": LAMP_VID,
        "resumed": None,
    }


# ── the restart ────────────────────────────────────────────────────────────

async def run_restart(owner: str) -> dict:
    """THE FOUR LIGHT-RELEVANT STARTUP STEPS of `spectra/app.py`'s real
    lifespan, in its own order. `engine.start()`/`device_preview.start()`
    are deliberately not run — they open a bridge WebSocket to his live
    spot-effects process, and nothing offline may do that; what they would
    drive is the engine executor, which is reported here instead."""
    headless.silence_audio()
    _stub_the_two_network_touchpoints()
    from spectra.services import av_sync_pattern, flare_preview_hold

    lo._save(lo.OwnershipRecord(owner=owner))
    PHASE["now"] = "restart"
    await night_run.recover_orphaned_night()
    side = handover.SpectraSide(config_dir=str(scfg.FX_LIVE_CONFIG_DIR),
                                open_audio=False)
    resumed = await handover.resume_own_room(side=side)
    await flare_preview_hold.recover_stale_hold()
    await av_sync_pattern.recover_stale_pattern()
    await asyncio.sleep(0.75)

    from spectra.services.live_host import live
    EXEC_MODES["after_restart"] = _executor_modes()
    out = {"mode": MODE, "resumed": bool(resumed),
           "owner_final": lo.load().owner,
           "live_active_after": bool(live.active),
           "took_the_room": None, "night_state": None}
    PHASE["now"] = "after"
    if live.active:
        # Leave nothing driving on the way out; this is a throwaway record
        # but a render thread outliving the measurement is noise.
        await side.deactivate()
    return out


# ── the report ─────────────────────────────────────────────────────────────

def summarise(base: dict) -> dict:
    by_phase = {}
    for f in FRAMES:
        row = by_phase.setdefault(f["phase"], {"frames": 0, "non_black": 0,
                                               "max": 0.0, "devices": []})
        row["frames"] += 1
        row["max"] = max(row["max"], f["max"])
        if f["max"] > 0.0:
            row["non_black"] += 1
            if f["device"] not in row["devices"]:
                row["devices"].append(f["device"])
    lit = [f for f in FRAMES if f["max"] > 0.0]
    revert_at = REVERT["at"]
    after = [f for f in lit if revert_at is not None and f["t"] > revert_at]
    base.update({
        "revert_landed": revert_at is not None,
        "lit_after_revert_ms": (round((max(f["t"] for f in after) - revert_at)
                                      * 1000.0, 1) if after else None),
        "lit_after_drain": sum(
            1 for f in lit
            if revert_at is not None and f["t"] > revert_at + REVERT_DRAIN_S),
        "revert_drain_ms": REVERT_DRAIN_S * 1000.0,
        "lit_devices": sorted({f["device"] for f in lit}),
        "frames": len(FRAMES),
        "non_black_frames": len(lit),
        "by_phase": by_phase,
        "first_lit": lit[0] if lit else None,
        "lamp_lit_devices": sorted(
            by_phase.get("queue_lamp", {}).get("devices", [])),
        "executor_modes": EXEC_MODES,
        "notes": NOTES,
    })
    return base


async def main() -> dict:
    if MODE in ("selftake", "ordinary"):
        return await run_night()
    if MODE == "restart_released":
        return await run_restart(lo.RELEASED)
    if MODE == "restart_owned":
        return await run_restart(lo.SPECTRA)
    raise SystemExit(f"unknown mode {MODE!r}")


status = 0
try:
    result = summarise(asyncio.run(main()))
except BaseException as exc:                                # noqa: BLE001
    import traceback
    traceback.print_exc()
    result = summarise({"driver_error": f"{type(exc).__name__}: {exc}"})
    status = 1
sys.stdout.write("RESULT " + json.dumps(result) + "\n")
sys.stdout.flush()
sys.stderr.flush()
os._exit(status)
