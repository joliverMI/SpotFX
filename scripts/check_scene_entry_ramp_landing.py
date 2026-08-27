"""§84's MISSING INSTRUMENT, built offline (2026-08-27,
fm/flare-preview-offsets-everywhere).

WHAT WAS MISSING. docs/SPECTRA_SPEC.md §84 and spectra/services/
trigger_engine.py's own module docstring both name the same hole, in the
same words: "the underlying scene-entry ramp this all rides
(scene_compiler.fire_scene's transition_ms write) has no live instrument
today that observes it AT the moment of a real fire — rendered frame
averages sample too coarsely to catch a switching instant, and
executor.recent_writes never records a scene fire's own writes." Everything
about the lead system was therefore proven at the unit level (does the
right number come out of the right function) and at the frame level with
an INJECTED lead — never as the claim the feature actually makes: THE
MIDPOINT OF THE CROSSFADE LANDS ON THE TRIGGER MARK.

WHAT THIS MEASURES, and why it is a real instrument rather than the same
arithmetic restated. It runs the real production chain end to end —
TriggerEngine.tick() over a real position feed, its own _default_lead_ms,
scene_sequencer.fire_scene_by_id, scene_compiler.fire_scene,
fx_seam.apply_writes, fx/facade's _effects_put, Effect.
start_param_transitions — and then WATCHES THE RAMP with the same
mechanism the light itself is driven by: Effect._advance_tweens, stepped
once per rendered frame off the effect's own clock, through fx.headless's
real assemble/flush pipeline. It reports the wall-clock moment the ramp's
observed value crosses the halfway point of its own travel, and compares
that against the trigger's own timestamp_ms. Nothing here recomputes the
lead; the lead is whatever the engine decided, and the crossing is
whatever the renderer actually rendered.

THE ONE THING IT IS NOT: a room proof. His fixtures are not touched and
his room is not granted for this work. What an offline instrument CAN
settle is everything between "the engine decided" and "the frame carries
the value" — which is the whole of the mechanism §84 said was unobserved.
What it still cannot settle is the perceptual claim (does the beat FEEL
aligned in the room), which no instrument can, and the live transport
(SPECTRA's executor to real hardware), which needs the room.

Run from repo root: .venv/bin/python scripts/check_scene_entry_ramp_landing.py
Isolated: temp storage + temp categories, fx.headless dummy device,
silence_audio, deterministic fake clock — no LedFX I/O, no audio, no live
storage write, never a call to :8000/:8010.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FAILURES: list[str] = []


def check(cond, label):
    if not cond:
        FAILURES.append(label)
        print(f"FAIL: {label}")
        return False
    print(f"ok: {label}")
    return True


td = Path(tempfile.mkdtemp(prefix="spectra-ramp-landing-"))

from fx import device_model, facade, headless

device_model.CATEGORIES_FILE = td / "device_categories.json"
device_model.CATEGORIES_FILE.write_text(json.dumps({}))
device_model.refresh()

from spectra import config as scfg
scfg.SPECTRA_STORAGE = td / "spectra"
scfg.SCENES_FILE = scfg.SPECTRA_STORAGE / "scenes.json"
scfg.SEQUENCER_FILE = scfg.SPECTRA_STORAGE / "sequencer.json"
scfg.DRIFT_PROFILES_FILE = scfg.SPECTRA_STORAGE / "drift_profiles.json"
scfg.ROOM_COLOR_FILE = scfg.SPECTRA_STORAGE / "room_color.json"
scfg.ROOM_CONTROLS_FILE = scfg.SPECTRA_STORAGE / "room_controls.json"
scfg.GRADIENT2D_FILE = scfg.SPECTRA_STORAGE / "gradients2d.json"
scfg.FIRE_HISTORY_FILE = scfg.SPECTRA_STORAGE / "fire_history.json"
scfg.SHOW_LOG_FILE = scfg.SPECTRA_STORAGE / "show_log.json"
scfg.COLOR_SETS_FILE = td / "color_sets.json"

from fx import light_ownership as lo
lo.OWNERSHIP_FILE = td / "ownership.json"
lo.OWNERSHIP_FILE.parent.mkdir(parents=True, exist_ok=True)
lo.OWNERSHIP_FILE.write_text(json.dumps({"owner": "spectra"}))

from spectra.models.scene import SceneDeviceConfig, SceneV2
from spectra.models.sequencer import SelectorEntry, SequencerConfig
from spectra.models.trigger import FireSceneAction, SpectraTrigger
from spectra.services import (dwell, room_controls, scene_store,
                              sequencer_store)
from spectra.services.trigger_engine import TriggerEngine

VID = headless.DEFAULT_VIRTUAL_ID
# The observed param. `spin` is an ordinary registry-smooth numeric on
# radial with a wide legal range, so a 0.0 -> 1.0 travel is a clean,
# unambiguous ramp to watch: halfway is exactly 0.5, with no schema
# clamping, gamma, or colour-space curve between the tween and the value.
PARAM = "spin"
FROM_VALUE = 0.0
TO_VALUE = 1.0

TICK_MS = 200          # trigger_engine.TICK_S, the production cadence
FRAME_HZ = 60.0        # a real render loop's own frame rate
MARK_MS = 4000         # where the trigger sits in the song
CROSSFADE_MS = 1200    # authored SceneV2.entry_ramp_ms — a long, easily
                       # observed ramp; the arithmetic is identical at his
                       # own 200-300ms intensity-scaled defaults, this is
                       # simply resolvable at 60fps sampling.


def _scene(name: str) -> SceneV2:
    return SceneV2(
        name=name, entry_ramp_ms=CROSSFADE_MS,
        devices=[SceneDeviceConfig(id="d1", target_kind="virtual", target=VID,
                                   effect_type="radial",
                                   params={PARAM: TO_VALUE})])


async def _observe(trig: SpectraTrigger, *, uri: str, end_ms: int = 6000,
                   no_lead: bool = False) -> dict:
    """Drive the REAL engine over a position feed, rendering real frames
    between ticks, and sample the effect's own live config every frame.

    Song position and wall-clock advance 1:1 here (the deliberate
    simplification a real room does not get: no bridge, no xcorr, no audio
    latency — every one of those is a separate, separately-recorded
    quantity in docs/SPECTRA_TIMING_CONVENTIONS.md). That is what makes
    "where did the ramp cross half" and "where is the trigger mark"
    directly comparable on one axis."""
    # MINIMUM DWELL is process-global state (spectra/services/dwell.py,
    # deliberately so — one room, one current scene), and every observation
    # below is an independent "song". Without this reset the SECOND
    # observation in the same process is legitimately deferred by the FIRST
    # one's dwell floor and renders nothing at all — a real property of the
    # production choke point, not an artefact to route around, so it is
    # cleared explicitly per observation exactly as a song change would.
    dwell.reset()
    host = await headless.start_headless_host(str(td / f"host-{uri}"))
    facade.set_host(host)
    virtual = host.virtuals.get(VID)
    try:
        with headless.fake_clock() as clock:
            effect = headless.attach_effect(host, virtual, "radial",
                                            {PARAM: FROM_VALUE})
            engine = TriggerEngine(
                list_triggers=lambda _u: [trig],
                scene_change_mode=lambda: "full",
                sequencer_enabled=lambda: False,
                # no_lead is the negative control below — the ONLY thing it
                # changes is the lead the engine applies; every other part
                # of the chain (compile, seam, facade, tween, renderer) is
                # untouched, so a red here can only mean the lead.
                lead_ms=(lambda _t: 0) if no_lead else None)
            await engine.on_track_state(uri)

            frame_dt = 1.0 / FRAME_HZ
            wall_ms = 0.0
            next_tick_ms = 0.0
            fired_at_ms: float | None = None
            samples: list[tuple[float, float]] = []
            while wall_ms <= end_ms:
                if wall_ms >= next_tick_ms - 1e-9:
                    got = await engine.tick(int(round(next_tick_ms)))
                    if got and fired_at_ms is None:
                        fired_at_ms = next_tick_ms
                    next_tick_ms += TICK_MS
                headless.render_frames(virtual, 1, clock=clock, dt=frame_dt)
                wall_ms += frame_dt * 1000.0
                samples.append((wall_ms, float(effect.config.get(PARAM, FROM_VALUE))))
    finally:
        facade.set_host(None)
        await host.shutdown()

    half = (FROM_VALUE + TO_VALUE) / 2.0
    crossed_ms = next((t for t, v in samples if v >= half), None)
    settled_ms = next((t for t, v in samples if v >= TO_VALUE - 1e-6), None)
    started_ms = next((t for t, v in samples if v > FROM_VALUE + 1e-9), None)
    return {"fired_at_ms": fired_at_ms, "half_crossed_ms": crossed_ms,
            "started_ms": started_ms, "settled_ms": settled_ms,
            "final": samples[-1][1] if samples else None,
            "samples": samples}


def _report(title: str, obs: dict, *, expected_anchor_frac: float) -> None:
    frame_ms = 1000.0 / FRAME_HZ
    print(f"\n── {title} ──")
    print(f"  trigger mark          {MARK_MS} ms")
    print(f"  engine fired at       {obs['fired_at_ms']} ms "
          f"({(obs['fired_at_ms'] or 0) - MARK_MS:+.0f} ms vs the mark)")
    print(f"  ramp first moved      {obs['started_ms']} ms")
    print(f"  ramp crossed HALF     {obs['half_crossed_ms']} ms "
          f"({(obs['half_crossed_ms'] or 0) - MARK_MS:+.1f} ms vs the mark)")
    print(f"  ramp settled          {obs['settled_ms']} ms")

    check(obs["fired_at_ms"] is not None, f"{title}: the trigger actually fired")
    check(obs["final"] is not None and abs(obs["final"] - TO_VALUE) < 1e-6,
          f"{title}: the ramp reached its target value on the real renderer")
    if obs["half_crossed_ms"] is None:
        check(False, f"{title}: the ramp was observed crossing half-way")
        return
    # THE CLAIM. The engine fires at (mark - lead) where lead =
    # anchor_frac x crossfade; the ramp then travels linearly, so the
    # halfway point of the travel lands anchor_frac x crossfade after the
    # fire — i.e. ON the mark for the 0.5 midpoint rule. Tolerance is the
    # instrument's own resolution: one 200ms tick (the engine can only fire
    # on a tick boundary) plus one rendered frame (the sampler can only see
    # a value once a frame has advanced it).
    tolerance = TICK_MS + frame_ms
    delta = obs["half_crossed_ms"] - MARK_MS
    check(abs(delta) <= tolerance,
          f"{title}: the crossfade's own MIDPOINT lands on the trigger mark "
          f"({delta:+.1f} ms, tolerance +/-{tolerance:.1f} ms = one tick + one frame)")
    # And the direction the whole feature exists for: the ramp must have
    # STARTED before the mark, not at it — otherwise nothing was aligned,
    # the switch simply happened late.
    check(obs["started_ms"] is not None and obs["started_ms"] < MARK_MS,
          f"{title}: the ramp began BEFORE the mark (the lead actually engaged)")
    print(f"  anchor_frac in force  {expected_anchor_frac}")


def main() -> None:
    headless.silence_audio()
    room_controls.save_room_controls(room_controls.RoomControlState(
        global_transition_ms=0, scene_change_mode="full"))

    # ── 1. a trigger that NAMES its scene: the plain rule ──────────────────
    named = _scene("Ramp Landing (named)")
    scene_store.save(named)
    trig_named = SpectraTrigger(
        timestamp_ms=MARK_MS,
        action=FireSceneAction(scene_id=named.id, intensity=0.5))
    obs = asyncio.run(_observe(trig_named, uri="song:named"))
    _report("named scene_id", obs, expected_anchor_frac=0.5)

    # ── 2. the shape 100% of his real triggers actually have: scene_id
    # None, resolved by LOOKAHEAD's early pin. §84 exists because §82
    # shipped DEAD for him on exactly this shape — so the instrument has
    # to cover it, not just the resolvable one. ───────────────────────────
    sequencer_store.save_config(SequencerConfig(
        entries={named.id: SelectorEntry()}))
    trig_pinned = SpectraTrigger(
        timestamp_ms=MARK_MS,
        action=FireSceneAction(scene_id=None, intensity=0.5))
    obs2 = asyncio.run(_observe(trig_pinned, uri="song:pinned"))
    _report("unresolved scene_id (LOOKAHEAD pin)", obs2, expected_anchor_frac=0.5)

    # ── 3. HIS OWN OFFSET, on the same instrument: the mark moves and the
    # midpoint follows it, in his sign. This is the half of the system a
    # unit test can only assert about a returned number. ─────────────────
    offset_ms = -600
    trig_offset = SpectraTrigger(
        timestamp_ms=MARK_MS, trigger_offset_ms=offset_ms,
        action=FireSceneAction(scene_id=named.id, intensity=0.5))
    obs3 = asyncio.run(_observe(trig_offset, uri="song:offset"))
    frame_ms = 1000.0 / FRAME_HZ
    relocated = MARK_MS + offset_ms
    print(f"\n── authored offset {offset_ms:+d} ms (negative = EARLIER) ──")
    print(f"  relocated mark        {relocated} ms")
    print(f"  ramp crossed HALF     {obs3['half_crossed_ms']} ms "
          f"({(obs3['half_crossed_ms'] or 0) - relocated:+.1f} ms vs the relocated mark)")
    if obs3["half_crossed_ms"] is not None:
        check(abs(obs3["half_crossed_ms"] - relocated) <= TICK_MS + frame_ms,
              "authored offset: the midpoint lands on the RELOCATED mark")
        check(obs3["half_crossed_ms"] < obs["half_crossed_ms"],
              "authored offset: a NEGATIVE offset really renders EARLIER than "
              "the same trigger without one (his sign, observed not asserted)")
    else:
        check(False, "authored offset: the ramp was observed crossing half-way")

    # ── 4. NEGATIVE CONTROL. An instrument that cannot go red on the
    # thing it measures is decoration — so run the SAME observation with
    # the lead deliberately disabled and prove the miss is real and large.
    # This is what says the +16.7 ms above is the lead system working, not
    # the tolerance being generous. ───────────────────────────────────────
    obs4 = asyncio.run(_observe(trig_named, uri="song:no-lead", no_lead=True))
    miss = (obs4["half_crossed_ms"] or 0) - MARK_MS
    print(f"\n── NEGATIVE CONTROL: the same fire with NO lead ──")
    print(f"  ramp crossed HALF     {obs4['half_crossed_ms']} ms "
          f"({miss:+.1f} ms vs the mark)")
    check(obs4["half_crossed_ms"] is not None
          and abs(miss) > TICK_MS + frame_ms,
          "negative control: with no lead the midpoint MISSES the mark by "
          "more than the tolerance — the instrument can go red")
    check(obs4["started_ms"] is not None and obs4["started_ms"] >= MARK_MS,
          "negative control: with no lead the ramp only STARTS at the mark "
          "(the switch lands late, which is exactly what the lead exists "
          "to fix)")

    print()
    if FAILURES:
        raise SystemExit(f"{len(FAILURES)} check(s) FAILED: {FAILURES}")
    print("All scene-entry ramp landing checks passed "
          "(offline: fx.headless renderer, no room, no LedFX, no audio).")


if __name__ == "__main__":
    main()
