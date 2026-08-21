"""FLARE-KIND TRIGGER OFFSET on the FIRING PATH (his ask, 2026-08-21 —
"make the engine read the offset and work with the offset like we had in
spot FX"): trigger_engine.tick() now relocates a fire_response trigger's
target by the authored FlareKind.trigger_offset_ms of the band the active
scene would fire — the number the flare scrubbing-preview's drag writes —
using EXACTLY #172's target-then-lead composition (target = timestamp +
his_offset; fire_at = target - lead), so the preview's drawn mark and the
real show's fire agree by construction.

The record followed, stated per the task's own convention: tick()'s
pre-existing `fire_at = trig.timestamp_ms - lead_ms` (positive lead =
EARLIER — the SpotFX-descended rule AGENTS.md records) is untouched; his
offset (NEGATIVE = earlier) relocates the base target first, each system
acting in its own native sign against the shared base, never added or
subtracted from each other directly. Both extremes are proven here —
sections below fire a NEGATIVE offset strictly earlier than the zero
baseline AND a POSITIVE one strictly later (and never at the raw mark) —
because a one-sided test has repeatedly passed with the sign inverted.

Also proven here, because the relocation is what surfaced it: tick()'s
safety-net OR clause used to DOUBLE-FIRE any trigger fired more than one
tick early (once at fire_at, again when the nominal target itself crossed
the window) — reproduced red against pre-fix code. The new fired-keys
memory makes the module docstring's own "fires once per crossing" contract
explicit, and the stranded-target net keeps a LIVE-relocated target
(the active scene can change between ticks) late-but-never-dropped.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from spectra.models.scene import (FlareBand, FlareKind, ParamTarget,
                                  ResponseSpec, SceneDeviceConfig, SceneV2)
from spectra.models.trigger import (FireResponseAction, FireSceneAction,
                                    SpectraTrigger)
from spectra.services.scene_response import band_trigger_offset_ms
from spectra.services.trigger_engine import (RESPONSE_OFFSET_HORIZON_MS,
                                             LOOKAHEAD_HORIZON_MS,
                                             TriggerEngine)


def _response_trig(ts=5000, event_class="flare", intensity=0.5):
    return SpectraTrigger(timestamp_ms=ts, action=FireResponseAction(
        event_class=event_class, intensity=intensity))


def _engine(trig, *, offset, lead=0, fired=None):
    """A fresh engine per scenario (the check_triggers.py section-10
    discipline): injected fakes for everything tick() reaches, the offset
    under test injected the same way lead_ms already is."""
    fired = fired if fired is not None else []

    async def fire_scene(scene_id, color_set_id, intensity):
        fired.append(("scene", scene_id))

    async def fire_response(event_class, intensity, gap_ms=None):
        fired.append(("response", event_class))

    offset_fn = offset if callable(offset) else (lambda a: offset)
    return TriggerEngine(
        list_triggers=lambda uri: [trig],
        fire_scene=fire_scene,
        fire_response=fire_response,
        scene_change_mode=lambda: "full",
        render_intensity=lambda raw: raw,
        sequencer_enabled=lambda: False,
        lead_ms=lambda t: lead,
        response_offset_ms=offset_fn,
    ), fired


def _tick_through(engine, start=0, stop=7000, step=200):
    """Drive tick() at the production 200ms cadence; return the positions
    where a fire happened."""
    hits = []

    async def run():
        await engine.on_track_state("song:flare-offset")
        for pos in range(start, stop + 1, step):
            got = await engine.tick(pos)
            if got:
                hits.append(pos)
    asyncio.run(run())
    return hits


# ═══ 1. both extremes, against the zero baseline ═══════════════════════════

def test_zero_offset_is_byte_identical_to_pre_offset_behaviour():
    eng, fired = _engine(_response_trig(), offset=0)
    hits = _tick_through(eng)
    assert hits == [5000] and fired == [("response", "flare")]


def test_negative_offset_fires_earlier_than_the_zero_baseline():
    """HIS RULE: negative = fire EARLIER. -500 on a 5000ms mark fires at
    the first tick at/after 4500 — strictly earlier than the 5000 the zero
    baseline above fires at."""
    eng, fired = _engine(_response_trig(), offset=-500)
    hits = _tick_through(eng)
    assert hits == [4600] and fired == [("response", "flare")]
    assert hits[0] < 5000, "a negative offset must fire EARLIER than zero"


def test_positive_offset_fires_later_and_never_at_the_raw_mark():
    """HIS RULE, other extreme: positive = fire LATER — and critically the
    raw stored timestamp does NOT fire it (the safety net tracks the
    relocated target; firing at raw would silently discard the ask)."""
    eng, fired = _engine(_response_trig(), offset=500)
    hits = _tick_through(eng)
    assert hits == [5600] and fired == [("response", "flare")]
    assert hits[0] > 5000, "a positive offset must fire LATER than zero"


def test_offset_composes_with_lead_in_each_systems_own_sign():
    """#172's composition, reused verbatim for the kind offset: the two
    systems use OPPOSITE senses for "earlier" (lead: positive; his offset:
    negative) and compose against a shared base, never by naive
    addition — fire_at = 5000 + (-1000) - 300 = 3700."""
    eng, fired = _engine(_response_trig(), offset=-1000, lead=300)

    async def run():
        await eng.on_track_state("song:composed")
        assert await eng.tick(3699) == []
        got = await eng.tick(3700)
        assert len(got) == 1
    asyncio.run(run())
    assert fired == [("response", "flare")]


# ═══ 2. exactly-once (the pre-existing double-fire, fixed) ═════════════════

def test_early_fired_trigger_never_refires_at_its_nominal_mark():
    """Reproduced red against pre-fix code (fire_scene, injected lead 450,
    ticks at 4550 then 5100): the safety-net OR clause fired the trigger
    at fire_at AND AGAIN when the nominal target crossed the window,
    violating the module docstring's own "fires once per crossing". The
    fired-keys memory closes it for every action kind."""
    trig = SpectraTrigger(timestamp_ms=5000, action=FireSceneAction(
        scene_id="sc", intensity=0.5))
    eng, fired = _engine(trig, offset=0, lead=450)
    hits = _tick_through(eng, start=4000, stop=6000, step=200)
    assert hits == [4600], f"exactly one fire expected, got ticks {hits}"
    assert fired == [("scene", "sc")]


def test_live_offset_moving_forward_after_the_fire_never_refires():
    """The live-read hazard the fired-keys memory exists for: the active
    scene changes AFTER a fire and the new band's offset relocates the
    target FORWARD across the already-fired position — without the memory
    the crossing check would fire the same trigger a second time."""
    offset_now = {"value": 0}
    eng, fired = _engine(_response_trig(),
                         offset=lambda a: offset_now["value"])

    async def run():
        await eng.on_track_state("song:forward-jump")
        assert len(await eng.tick(5000)) == 1     # fired at the raw mark
        offset_now["value"] = 800                 # scene changed; target now 5800
        for pos in (5200, 5400, 5600, 5800, 6000):
            assert await eng.tick(pos) == [], \
                "the relocated target re-crossing an already-fired position " \
                "must not fire the trigger a second time"
    asyncio.run(run())
    assert len(fired) == 1


def test_rewind_rearms_the_fired_memory():
    """"Approaching the same moment again fires it again" (module
    docstring) — the fired-keys memory clears on a rewind exactly like the
    LOOKAHEAD pins."""
    eng, fired = _engine(_response_trig(), offset=0)

    async def run():
        await eng.on_track_state("song:rewind")
        assert len(await eng.tick(5000)) == 1
        assert await eng.tick(3000) == []          # rewind: silent rearm
        assert len(await eng.tick(5100)) == 1      # re-approach refires
    asyncio.run(run())
    assert len(fired) == 2


def test_an_edited_timestamp_is_a_fresh_key_and_fires_again():
    """The fired memory keys on (id, timestamp_ms), not id alone: nudging
    an already-fired trigger LATER in the live timeline builder still fires
    it at its new mark (today's authoring affordance), while an offset drag
    (timestamp unchanged) can never machine-gun re-fires."""
    trig = _response_trig(ts=5000)
    eng, fired = _engine(trig, offset=0)

    async def run():
        await eng.on_track_state("song:edited")
        assert len(await eng.tick(5000)) == 1
        trig.timestamp_ms = 6000                   # his edit, same trigger id
        assert len(await eng.tick(6000)) == 1
    asyncio.run(run())
    assert len(fired) == 2


# ═══ 3. stranded-target net (late, never dropped — never backfilled) ═══════

def test_target_stranded_behind_the_window_fires_late_not_never():
    """The active scene changing mid-approach can relocate the target from
    ahead of the playhead to behind it between two ticks — with no net the
    trigger would never fire at all. It fires on the next advancing tick
    instead (late per the new ask), once."""
    offset_now = {"value": 500}                    # target 5500, ahead
    eng, fired = _engine(_response_trig(),
                         offset=lambda a: offset_now["value"])

    async def run():
        await eng.on_track_state("song:stranded")
        assert await eng.tick(4800) == []
        assert await eng.tick(4900) == []          # approaching; target 5500
        offset_now["value"] = -500                 # scene changed; target 4500 — behind
        got = await eng.tick(4950)
        assert len(got) == 1, "a stranded target must fire late, not never"
        assert await eng.tick(5100) == [] and await eng.tick(5600) == [], \
            "the late fire is still exactly-once"
    asyncio.run(run())
    assert len(fired) == 1


def test_stranded_net_never_fires_while_playback_is_paused():
    offset_now = {"value": 500}
    eng, fired = _engine(_response_trig(),
                         offset=lambda a: offset_now["value"])

    async def run():
        await eng.on_track_state("song:paused")
        assert await eng.tick(4900) == []
        offset_now["value"] = -500                 # target strands at 4500
        assert await eng.tick(4900) == [], \
            "a paused poll (position not advancing) must never fire the net"
        assert len(await eng.tick(4950)) == 1      # resumes → fires once
    asyncio.run(run())
    assert len(fired) == 1


def test_stranded_net_never_backfills_a_passed_raw_mark():
    """A trigger whose RAW mark was already history when the song was
    picked up (mid-song anchor) stays history — the net only rescues a
    RELOCATED moment whose raw mark is still ahead."""
    eng, fired = _engine(_response_trig(ts=8000), offset=-500)
    hits = _tick_through(eng, start=10_000, stop=12_000, step=200)
    assert hits == [] and fired == []


# ═══ 4. band_trigger_offset_ms (the aggregation itself) ════════════════════

def _scene(kinds, band_kinds, event_class="flare", band=(0.0, 1.0)):
    lo, hi = band
    return SceneV2(
        name="Offset Probe",
        devices=[SceneDeviceConfig(target_kind="virtual", target="v1",
                                   effect_type="concentric", params={})],
        flare_kinds=kinds,
        responses={event_class: ResponseSpec(bands=[
            FlareBand(intensity_min=lo, intensity_max=hi, kinds=band_kinds)])})


def _kind(name, offset, type="momentary"):
    return FlareKind(name=name, type=type, trigger_offset_ms=offset,
                     params={"gradient_scale": ParamTarget(mode="absolute",
                                                           value=1.5)})


def test_single_kind_band_returns_that_kinds_offset():
    scene = _scene([_kind("Pulse", -400)], {"Pulse": 1.0})
    assert band_trigger_offset_ms(scene, "flare", 0.5) == -400


def test_multi_kind_band_earliest_nonzero_ask_wins():
    """min over the NONZERO offsets — the earliest explicitly-authored ask
    wins (mirroring the lead system's own documented max-lead rule), and a
    kind still at the untouched default 0 doesn't veto a sibling's ask."""
    scene = _scene([_kind("A", 0), _kind("B", -400)],
                   {"A": 1.0, "B": 1.0})
    assert band_trigger_offset_ms(scene, "flare", 0.5) == -400
    scene = _scene([_kind("A", 300), _kind("B", 0)],
                   {"A": 1.0, "B": 1.0})
    assert band_trigger_offset_ms(scene, "flare", 0.5) == 300
    scene = _scene([_kind("A", -500), _kind("B", 300)],
                   {"A": 1.0, "B": 1.0})
    assert band_trigger_offset_ms(scene, "flare", 0.5) == -500


def test_no_band_or_all_default_is_zero():
    scene = _scene([_kind("Pulse", -400)], {"Pulse": 1.0}, band=(0.5, 1.0))
    assert band_trigger_offset_ms(scene, "flare", 0.2) == 0, \
        "intensity outside every band selects nothing — offset 0"
    assert band_trigger_offset_ms(scene, "drop", 0.8) == 0, \
        "a class with no spec at all — offset 0"
    scene = _scene([_kind("A", 0), _kind("B", 0)], {"A": 1.0, "B": 1.0})
    assert band_trigger_offset_ms(scene, "flare", 0.5) == 0, \
        "every kind at the untouched default — byte-identical to pre-offset"


def test_a_drop_bands_authored_offset_is_honoured():
    """Unlike the lead's unconditional drop rule (lead=0 — an anchor-family
    policy), his explicit hand on the preview's marker applies to a drop
    band too: the preview honours the offset for any kind, and the firing
    path matching the preview is the point."""
    scene = _scene([_kind("Boom", -350)], {"Boom": 1.0}, event_class="drop")
    assert band_trigger_offset_ms(scene, "drop", 0.9) == -350


def test_default_peek_reads_the_active_scenes_band_at_render_intensity():
    """End-to-end through _default_response_offset_ms: the engine's own
    default resolves the band via the ACTIVE scene at the RENDER intensity
    — same reads as _response_switch_lead_ms — so tick() fires early with
    no offset injection at all."""
    scene = _scene([_kind("Pulse", -600)], {"Pulse": 1.0}, band=(0.4, 1.0))
    fired = []

    async def fire_response(event_class, intensity, gap_ms=None):
        fired.append(event_class)

    eng = TriggerEngine(
        list_triggers=lambda uri: [_response_trig(intensity=0.5)],
        fire_response=fire_response,
        scene_change_mode=lambda: "full",
        render_intensity=lambda raw: raw,
        sequencer_enabled=lambda: False,
        lead_ms=lambda t: 0,
    )
    eng._active_scene = lambda: scene   # the one production singleton read

    async def run():
        await eng.on_track_state("song:default-peek")
        assert await eng.tick(4300) == []
        assert len(await eng.tick(4400)) == 1, \
            "the real default peek relocated the fire to 4400 (5000 - 600)"
    asyncio.run(run())
    assert fired == ["flare"]


# ═══ 5. the peek window derivation stays pinned to the model clamp ═════════

def test_offset_horizon_covers_the_fields_own_model_clamp():
    """RESPONSE_OFFSET_HORIZON_MS is derived (the FlareKind field's own
    ±60_000 clamp + the lead horizon), not tuned — if the model clamp ever
    widens past it, a legal offset could relocate a target outside the
    peek window and silently never be read."""
    meta = FlareKind.model_fields["trigger_offset_ms"].metadata
    bounds = {type(m).__name__.lower(): getattr(m, "ge", getattr(m, "le", None))
              for m in meta}
    clamp = max(abs(v) for v in bounds.values() if v is not None)
    assert RESPONSE_OFFSET_HORIZON_MS >= clamp + LOOKAHEAD_HORIZON_MS
