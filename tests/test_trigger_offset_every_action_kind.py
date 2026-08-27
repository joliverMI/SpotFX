"""SpectraTrigger.trigger_offset_ms is honoured on EVERY action kind
(2026-08-27, fm/flare-preview-offsets-everywhere) — the gap this closes,
and the composition rule that makes closing it safe.

THE GAP: #172 (2026-08-21) wired the trigger-level offset for `fire_scene`
alone, and the field's own model docstring then had to say the other three
action kinds "still ignore it". A field that stores, validates, round-trips
and displays a number nothing reads is a trap — and it was scoped that way
against an ask that wasn't ("do events like flares and scene changes carry
an offset value... they need to", models/trigger.py). Nothing about an
OFFSET is action-kind specific: unlike a LEAD, which must know what payoff
it is aligning and how long that payoff takes to arrive, an offset only
RELOCATES the moment, so it composes with an instant apply
(select_color_set, fire_scene_update) exactly as it does with a crossfade.

THE COMPOSITION: on a `fire_response` trigger the trigger-level offset ADDS
to the fired band's own FlareKind.trigger_offset_ms. That is legal because
both are OFFSET family (docs/SPECTRA_TIMING_CONVENTIONS.md's master table:
same unit, same sign, same meaning of "later") — it is only the
oppositely-signed LEAD family that must never be added to either. They are
independent corrections to the same moment: the trigger's own offset is a
property of THIS MARK IN THIS SONG, the kind's of THE SCENE'S OWN FLARE.
Every assertion below also pins the no-op guarantee at the untouched
default of 0, which is what makes this provably inert against everything
currently on his disk.
"""
from __future__ import annotations

import asyncio

from spectra.models.trigger import (FireResponseAction, FireSceneAction,
                                    FireSceneUpdateAction,
                                    SelectColorSetAction, SpectraTrigger)
from spectra.services.trigger_engine import TriggerEngine


def _engine(trig, *, lead=0, band_offset=0):
    fired: list[tuple] = []

    async def fire_scene(scene_id, color_set_id, intensity):
        fired.append(("scene", scene_id))

    async def fire_response(event_class, intensity, gap_ms=None):
        fired.append(("response", event_class))

    async def select_color_set(set_id):
        fired.append(("color_set", set_id))

    async def fire_scene_update(intensity):
        fired.append(("update", intensity))

    return TriggerEngine(
        list_triggers=lambda uri: [trig],
        fire_scene=fire_scene,
        fire_response=fire_response,
        select_color_set=select_color_set,
        fire_scene_update=fire_scene_update,
        scene_change_mode=lambda: "full",
        render_intensity=lambda raw: raw,
        sequencer_enabled=lambda: False,
        lead_ms=lambda t: lead,
        response_offset_ms=lambda a: band_offset,
    ), fired


def _first_fire_at(engine, start=0, stop=8000, step=200):
    hits: list[int] = []

    async def run():
        await engine.on_track_state("song:uniform-offset")
        for pos in range(start, stop + 1, step):
            if await engine.tick(pos):
                hits.append(pos)
    asyncio.run(run())
    return hits


def _select_color_set_trig(offset):
    return SpectraTrigger(timestamp_ms=5000, trigger_offset_ms=offset,
                          action=SelectColorSetAction(set_id="set-1"))


def _update_trig(offset):
    return SpectraTrigger(timestamp_ms=5000, trigger_offset_ms=offset,
                          action=FireSceneUpdateAction(intensity=0.5))


def _response_trig(offset):
    return SpectraTrigger(timestamp_ms=5000, trigger_offset_ms=offset,
                          action=FireResponseAction(event_class="flare",
                                                    intensity=0.5))


def _scene_trig(offset):
    return SpectraTrigger(timestamp_ms=5000, trigger_offset_ms=offset,
                          action=FireSceneAction(scene_id="s1", intensity=0.5))


# ═══ 1. the three previously-inert kinds now honour it, both extremes ══════

def test_select_color_set_honours_a_negative_offset():
    eng, fired = _engine(_select_color_set_trig(-600))
    assert _first_fire_at(eng) == [4400]
    assert fired == [("color_set", "set-1")]


def test_select_color_set_honours_a_positive_offset():
    eng, fired = _engine(_select_color_set_trig(600))
    hits = _first_fire_at(eng)
    assert hits == [5600] and hits[0] > 5000
    assert fired == [("color_set", "set-1")]


def test_fire_scene_update_honours_a_negative_offset():
    eng, fired = _engine(_update_trig(-600))
    assert _first_fire_at(eng) == [4400]
    assert fired == [("update", 0.5)]


def test_fire_scene_update_honours_a_positive_offset():
    eng, _ = _engine(_update_trig(600))
    assert _first_fire_at(eng) == [5600]


def test_fire_response_honours_its_own_trigger_level_offset():
    """The kind's band offset is 0 here — this is purely the TRIGGER's own
    field, which #172 left inert on this action kind."""
    eng, fired = _engine(_response_trig(-600), band_offset=0)
    assert _first_fire_at(eng) == [4400]
    assert fired == [("response", "flare")]


# ═══ 2. zero stays byte-identical for every kind (the no-op guarantee) ═════

def test_zero_offset_is_a_no_op_on_every_action_kind():
    for trig in (_select_color_set_trig(0), _update_trig(0),
                 _response_trig(0), _scene_trig(0)):
        eng, fired = _engine(trig)
        assert _first_fire_at(eng) == [5000], f"{trig.action.kind} moved at offset 0"
        assert len(fired) == 1


# ═══ 3. fire_response: the two OFFSET sources ADD ══════════════════════════

def test_trigger_and_kind_offsets_add_on_a_fire_response_trigger():
    """-400 (this mark sits early) + -300 (this flare needs a head start)
    = -700: fire at the first tick at/after 4300."""
    eng, fired = _engine(_response_trig(-400), band_offset=-300)
    assert _first_fire_at(eng) == [4400]   # first 200ms tick > 4300
    assert fired == [("response", "flare")]


def test_opposite_signed_offsets_cancel_rather_than_one_winning():
    """An override rule would silently discard whichever he authored
    second. Adding honours both — here they cancel exactly."""
    eng, _ = _engine(_response_trig(-500), band_offset=500)
    assert _first_fire_at(eng) == [5000]


def test_either_source_at_zero_degrades_to_the_other():
    eng_kind_only, _ = _engine(_response_trig(0), band_offset=-600)
    eng_trig_only, _ = _engine(_response_trig(-600), band_offset=0)
    assert _first_fire_at(eng_kind_only) == _first_fire_at(eng_trig_only) == [4400]


# ═══ 4. composition with the oppositely-signed LEAD is unchanged ═══════════

def test_summed_offsets_compose_with_lead_in_each_systems_own_sign():
    """fire_at = timestamp + trigger_offset + kind_offset - lead
              = 5000 + (-400) + (-300) - 200 = 4100.
    The two offsets add (same family); the lead SUBTRACTS (opposite
    family) — never all three added under one sign."""
    eng, fired = _engine(_response_trig(-400), band_offset=-300, lead=200)

    async def run():
        await eng.on_track_state("song:composed-uniform")
        assert await eng.tick(4099) == []
        assert len(await eng.tick(4100)) == 1
    asyncio.run(run())
    assert fired == [("response", "flare")]


def test_lead_still_never_applies_to_an_instant_apply_kind():
    """A select_color_set trigger takes the offset but no lead — the
    production _default_lead_ms returns 0 for it, so the relocated target
    IS the fire moment. Proven through the real lead dispatcher, not an
    injected one."""
    trig = _select_color_set_trig(-600)
    fired: list[tuple] = []

    async def select_color_set(set_id):
        fired.append(("color_set", set_id))

    eng = TriggerEngine(
        list_triggers=lambda uri: [trig],
        select_color_set=select_color_set,
        scene_change_mode=lambda: "full",
        render_intensity=lambda raw: raw,
        sequencer_enabled=lambda: False,
    )
    assert eng._default_lead_ms(trig) == 0
    assert _first_fire_at(eng) == [4400]
    assert fired == [("color_set", "set-1")]
