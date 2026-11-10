"""Word colours and imprints (lyrics plan step 4). spectra/services/lyric_events.py
is the binding statement; the Admiral's rulings are its section "HOW A WORD IS
WEIGHED", and each one is proven here:

  1. THE PLAN, pure: priority and tie rules, the 2 s window's edges, one imprint
     per word, the stronger word, once per phrase, the minimum gap, an event that
     cannot carry colour, weak matches and his own edits.
  2. ENERGY: the cut-off, momentary against held, the transition time.
  3. THE TRIGGER CLOCK, real engine and fake feed: the colour arrives on the word,
     exactly once, only in modes that react to music, and with the switch off the
     engine's output is the output of an engine without the feature.
  4. THE COLOUR PATHS, real response engine: a word's colour on a drop, a flare
     and an update through the existing jump, the scene's allowed list, the chooser
     avoiding the last used, 180 on every drop not imprinted, momentary and held
     colours with their releases, and every hold the room already has.
  5. THE STORE AND THE PAGE: off for every show, per show, and the API.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from spectra.models.lyric_labels import LyricEventSettings
from spectra.models.scene import (FlareBand, FlareKind, ResponseSpec, SceneDeviceConfig,
                                  SceneV2)
from spectra.models.trigger import (FireResponseAction, FireSceneAction,
                                    FireSceneUpdateAction, SelectColorSetAction,
                                    SpectraTrigger)
from spectra.services import lyric_events as le
from spectra.services.trigger_engine import TriggerEngine
from tests.test_drop_colour import CARDS, Rig, _scene, card_store  # noqa: F401

URI = "spotify:track:wordcolours"
TUNING = LyricEventSettings()


def _hit(ms=10_000, *, key=None, line=0, strength=0.9, his=False, sets=("red",), energy=0.3,
         emphasis=0.4, why_not=None, end_ms=None, phrase="red", first=None):
    first = first if first is not None else ms // 100
    return le.WordHit(key=key or f"{first}-{first}", first_word=first, last_word=first,
                      phrase=phrase, label="red", line=line, ms=float(ms),
                      end_ms=float(end_ms if end_ms is not None else ms + 300),
                      emphasis=emphasis, strength=strength, his=his, set_ids=tuple(sets),
                      set_names=tuple(s.title() for s in sets), energy=energy, why_not=why_not)


def _drop(ms, eid="d", can_carry=True):
    return le.EventMoment(eid, le.KIND_DROP, ms, "drop", can_carry,
                          None if can_carry else "off")


def _scene_event(ms, eid="s", can_carry=True):
    return le.EventMoment(eid, le.KIND_SCENE, ms, "scene change", can_carry,
                          None if can_carry else "its own colour")


def _flare(ms, eid="f", can_carry=True):
    return le.EventMoment(eid, le.KIND_FLARE, ms, "flare", can_carry,
                          None if can_carry else "no colour jump")


def _plan(hits, events=(), **tuning):
    return le.plan_words(hits, events, LyricEventSettings(**tuning))


def _only(actions):
    assert len(actions) == 1
    return actions[0]


# ── 1. the plan ─────────────────────────────────────────────────────────────


def test_a_word_with_no_event_near_it_fires_alone():
    a = _only(_plan([_hit()]))
    assert a.verdict == le.VERDICT_FIRE and a.event is None


def test_the_window_is_two_seconds_either_way_including_its_edge():
    for delta in (-2000, 2000):
        a = _only(_plan([_hit()], [_flare(10_000 + delta)]))
        assert a.verdict == le.VERDICT_IMPRINT, delta
    for delta in (-2001, 2001):
        a = _only(_plan([_hit()], [_flare(10_000 + delta)]))
        assert a.verdict == le.VERDICT_FIRE, delta


def test_the_window_is_on_a_slider():
    a = _only(_plan([_hit()], [_flare(11_500)], imprint_window_s=1.0))
    assert a.verdict == le.VERDICT_FIRE
    a = _only(_plan([_hit()], [_flare(11_500)], imprint_window_s=1.5))
    assert a.verdict == le.VERDICT_IMPRINT


def test_priority_is_drop_then_scene_change_or_update_then_flare():
    a = _only(_plan([_hit()], [_flare(10_100), _scene_event(10_900), _drop(11_800)]))
    assert a.event.kind == le.KIND_DROP
    a = _only(_plan([_hit()], [_flare(10_100), _scene_event(10_900)]))
    assert a.event.kind == le.KIND_SCENE


def test_the_nearest_wins_a_tie_within_a_kind():
    a = _only(_plan([_hit()], [_flare(10_800, "far"), _flare(10_100, "near")]))
    assert a.event.id == "near"
    a = _only(_plan([_hit()], [_flare(9_500, "before"), _flare(10_500, "after")]))
    assert a.event.id == "before", "exactly level goes to the earlier moment"


def test_a_scene_change_and_an_update_share_their_tier():
    update = le.EventMoment("u", le.KIND_SCENE, 10_200, "scene update")
    a = _only(_plan([_hit()], [_scene_event(10_900), update]))
    assert a.event.id == "u", "the nearer of the two"


def test_the_stronger_word_wins_an_event_and_the_loser_does_nothing():
    strong = _hit(10_000, strength=0.9, line=0, first=1)
    weak = _hit(11_000, strength=0.7, line=1, first=2)
    out = {a.hit.first_word: a for a in _plan([weak, strong], [_flare(10_500)], min_gap_s=0)}
    assert out[1].verdict == le.VERDICT_IMPRINT and out[1].event.id == "f"
    assert out[2].verdict == le.VERDICT_NOTHING and out[2].why == le.WHY_LOST
    assert out[2].blocked_by == "red"


def test_his_own_match_beats_any_guess_for_an_event():
    guess = _hit(10_000, strength=1.0, line=0, first=1)
    his = _hit(11_000, strength=1.0, his=True, line=1, first=2)
    out = {a.hit.first_word: a for a in _plan([guess, his], [_flare(10_500)], min_gap_s=0)}
    assert out[2].verdict == le.VERDICT_IMPRINT and out[1].why == le.WHY_LOST


def test_one_imprint_per_word_and_a_word_never_tries_its_second_choice():
    """The word lost the drop. It is near the flare too, and still does nothing."""
    winner = _hit(10_000, strength=0.9, line=0, first=1)
    loser = _hit(10_500, strength=0.7, line=1, first=2)
    out = {a.hit.first_word: a for a in _plan(
        [winner, loser], [_drop(10_200, "drop"), _flare(10_600, "flare")], min_gap_s=0)}
    assert out[1].event.id == "drop"
    assert out[2].verdict == le.VERDICT_NOTHING and out[2].why == le.WHY_LOST


def test_a_word_more_than_the_window_from_every_event_fires_alone():
    near = _hit(10_000, strength=0.9, line=0, first=1)
    far = _hit(13_000, strength=0.7, line=1, first=2)
    out = {a.hit.first_word: a for a in _plan([near, far], [_flare(10_500)], min_gap_s=0)}
    assert out[1].verdict == le.VERDICT_IMPRINT
    assert out[2].verdict == le.VERDICT_FIRE


def test_an_event_that_cannot_carry_colour_means_no_imprint_and_no_fire():
    a = _only(_plan([_hit()], [_drop(10_500, can_carry=False)]))
    assert a.verdict == le.VERDICT_NOTHING and a.why == le.WHY_CANNOT_CARRY


def test_a_colourless_event_stops_the_word_even_with_a_flare_beside_it():
    a = _only(_plan([_hit()], [_drop(10_500, can_carry=False), _flare(10_100)]))
    assert a.verdict == le.VERDICT_NOTHING and a.event.kind == le.KIND_DROP


def test_once_per_phrase_the_stronger_word_takes_it():
    weak = _hit(10_000, strength=0.7, line=3, first=1)
    strong = _hit(11_000, strength=0.9, line=3, first=2)
    out = {a.hit.first_word: a for a in _plan([weak, strong], min_gap_s=0)}
    assert out[2].verdict == le.VERDICT_FIRE
    assert out[1].verdict == le.VERDICT_NOTHING and out[1].why == le.WHY_PHRASE


def test_a_word_that_did_nothing_does_not_take_its_phrase():
    """Only a word that really did something counts against the next."""
    silenced = _hit(10_000, strength=0.9, line=3, first=1)
    other = _hit(11_000, strength=0.7, line=3, first=2)
    out = {a.hit.first_word: a for a in _plan(
        [silenced, other], [_drop(9_500, can_carry=False)],
        min_gap_s=0, imprint_window_s=1.0)}
    assert out[1].why == le.WHY_CANNOT_CARRY and out[2].verdict == le.VERDICT_FIRE


def test_the_minimum_gap_covers_fired_and_imprinted_words_alike():
    first = _hit(10_000, strength=0.9, line=0, first=1)
    second = _hit(15_000, strength=0.7, line=1, first=2)
    assert [a.verdict for a in _plan([first, second])] == [le.VERDICT_FIRE, le.VERDICT_NOTHING]
    out = _plan([first, second], [_flare(10_200)])
    assert out[0].verdict == le.VERDICT_IMPRINT and out[1].why == le.WHY_TOO_SOON


def test_the_gap_edge_and_slider():
    a = _hit(10_000, strength=0.9, line=0, first=1)
    b = _hit(18_000, strength=0.7, line=1, first=2)
    assert [x.verdict for x in _plan([a, b])] == [le.VERDICT_FIRE, le.VERDICT_FIRE], "8 s apart is allowed"
    b2 = _hit(17_999, strength=0.7, line=1, first=2)
    assert _plan([a, b2])[1].why == le.WHY_TOO_SOON
    assert _plan([a, b2], min_gap_s=7.0)[1].verdict == le.VERDICT_FIRE


def test_the_stronger_word_wins_the_gap_whichever_comes_first():
    early_weak = _hit(10_000, strength=0.65, line=0, first=1)
    later_strong = _hit(14_000, strength=0.95, line=1, first=2)
    out = {a.hit.first_word: a for a in _plan([early_weak, later_strong])}
    assert out[2].verdict == le.VERDICT_FIRE and out[1].why == le.WHY_TOO_SOON
    his = _hit(14_000, strength=0.0, his=True, line=1, first=2)
    out = {a.hit.first_word: a for a in _plan([early_weak, his])}
    assert out[2].verdict == le.VERDICT_FIRE, "his own match beats any guess"


def test_a_word_refused_earlier_stays_nothing_and_says_why():
    a = _only(_plan([_hit(why_not=le.WHY_WEAK)], [_flare(10_100)]))
    assert a.verdict == le.VERDICT_NOTHING and a.why == le.WHY_WEAK


def test_the_order_of_words_does_not_change_the_plan():
    hits = [_hit(10_000 + i * 3000, strength=0.6 + i * 0.05, line=i, first=i) for i in range(5)]
    events = [_flare(10_400), _drop(16_100)]
    forward = {a.hit.key: a.verdict for a in _plan(hits, events)}
    backward = {a.hit.key: a.verdict for a in _plan(list(reversed(hits)), list(reversed(events)))}
    assert forward == backward


# ── 2. energy ───────────────────────────────────────────────────────────────


def test_high_energy_is_momentary_low_energy_holds_with_one_cut_off():
    assert _only(_plan([_hit(energy=0.6)])).momentary is True
    assert _only(_plan([_hit(energy=0.4)])).momentary is False
    assert _only(_plan([_hit(energy=0.5)])).momentary is True, "at the cut-off is high"
    assert _only(_plan([_hit(energy=0.6)], energy_cutoff=0.7)).momentary is False


def test_energy_drives_the_transition_quick_when_loud_slow_when_quiet():
    assert le.transition_ms_for(0.0) == le.SLOW_TRANSITION_MS == 3000
    assert le.transition_ms_for(le.FAST_AT_ENERGY) == le.FAST_TRANSITION_MS == 150
    assert le.transition_ms_for(1.0) == 150
    assert le.transition_ms_for(0.2) > le.transition_ms_for(0.5) > 150


def test_an_unknown_energy_is_neutral():
    a = _only(_plan([_hit(energy=None)]))
    assert a.energy == 0.5 and a.momentary is True


def test_energy_rules_apply_only_to_words_firing_alone():
    a = _only(_plan([_hit(energy=0.9)], [_flare(10_100)]))
    assert a.verdict == le.VERDICT_IMPRINT
    assert a.transition_ms == 0 and a.momentary is False


def test_a_momentary_colour_holds_through_the_sung_words_within_bounds():
    assert le.moment_dwell_ms(_hit(end_ms=10_600)) == 600
    assert le.moment_dwell_ms(_hit(end_ms=10_100)) == le.MOMENT_HOLD_MIN_MS
    assert le.moment_dwell_ms(_hit(end_ms=40_000)) == le.MOMENT_HOLD_MAX_MS
    assert le.moment_fade_ms(1000) == 1500
    assert le.moment_fade_ms(10) == le.MOMENT_FADE_MIN_MS


# ── matches to hits ─────────────────────────────────────────────────────────


def _match(first, last, *, source="claude", confidence=0.9, label="red", ms=None, score=0.5,
           phrase="red"):
    return {"source": source, "confidence": confidence, "first_word": first, "last_word": last,
            "label": label, "ms": ms if ms is not None else first * 1000.0,
            "end_ms": (ms if ms is not None else first * 1000.0) + 500.0, "score": score,
            "phrase": phrase, "targets": []}


def _hits(matches, *, reach=None, threshold=0.6, energy=None):
    return le.hits_from_matches(
        matches, list(range(50)), threshold, energy or (lambda ms: 0.3),
        reach or (lambda m: [(f"set-{m['label']}", m["label"].title())]))


def test_a_weak_match_fires_nothing():
    [hit] = _hits([_match(1, 1, confidence=0.5)])
    assert hit.why_not == le.WHY_WEAK


def test_the_threshold_is_live_not_the_stored_reading():
    [hit] = _hits([_match(1, 1, confidence=0.7)], threshold=0.8)
    assert hit.why_not == le.WHY_WEAK


def test_a_match_reaching_only_an_effect_has_no_event_yet():
    [hit] = _hits([_match(1, 1)], reach=lambda m: [])
    assert hit.why_not == le.WHY_NO_COLOUR


def test_overlapping_matches_collapse_and_the_chooser_gets_the_strongest():
    [hit] = _hits([_match(1, 2, confidence=0.9, label="red"),
                   _match(2, 2, confidence=0.88, label="fire"),
                   _match(1, 1, confidence=0.7, label="dull")])
    assert set(hit.set_ids) == {"set-red", "set-fire"}, "within the tie, and not the weaker one"
    assert hit.strength == 0.9


def test_his_match_outranks_every_guess_on_the_same_words():
    [hit] = _hits([_match(1, 1, confidence=0.95, label="red"),
                   _match(1, 1, source="his", confidence=None, label="blue")])
    assert hit.set_ids == ("set-blue",) and hit.his and hit.label == "blue"


def test_energy_is_read_at_the_word():
    seen = []
    def energy(ms):
        seen.append(ms)
        return 0.8
    [hit] = _hits([_match(4, 4, ms=4321.0)], energy=energy)
    assert seen == [4321] and hit.energy == 0.8


# ── 3. the trigger clock ────────────────────────────────────────────────────


class Rec:
    def __init__(self):
        self.fires: list = []
        self.words: list = []
        self.imprints: list = []
        self.hold_released = 0

    async def fire_scene(self, scene_id, color_set_id, intensity):
        self.imprints.append(le.active())
        self.fires.append(("scene", scene_id, color_set_id))
        return {"scene_id": scene_id}

    async def fire_response(self, event_class, intensity, gap_ms=None, **_kw):
        self.imprints.append(le.active())
        self.fires.append(("response", event_class))

    async def fire_flare(self, intensity):
        self.imprints.append(le.active())
        self.fires.append(("analysed_flare",))

    async def fire_update(self, intensity):
        self.imprints.append(le.active())
        self.fires.append(("update",))

    async def select_colour(self, set_id):
        self.fires.append(("colour", set_id))

    async def analysed_color(self, selection, render, scene_id):
        self.fires.append(("analysed_colour", scene_id))

    async def drop_colour(self, selection, pool_scene_id, ramp_ms, moment, analysed):
        self.imprints.append(le.active())
        self.fires.append(("drop_colour", moment))
        return {"result": "jumped", "moment": moment}

    async def lyric_colour(self, action, ramp_ms):
        self.words.append((action.hit.phrase, ramp_ms, self.pos))
        return {"result": "jumped", "color_jump": {"picked_id": "red", "set_name": "Red"}}

    def lyric_pick(self, set_ids, scene_id, intensity):
        return {"set_id": set_ids[0], "rung": "full"}

    def release(self):
        self.hold_released += 1

    pos = 0


async def _noop(_uri):
    return None


class _Plan:
    def __init__(self, flares=(), scene_cues=()):
        self.flares = list(flares)
        self.scene_cues = list(scene_cues)


def _engine(triggers, rec, *, hits=(), enabled=True, mode="full", tuning=TUNING, pick=None,
            lyric_load=None, plan=None, **kw) -> TriggerEngine:
    words = le.SongWords(URI, "ok", hits=tuple(hits))
    return TriggerEngine(
        energy_for=lambda uri, t: 0.5,
        list_triggers=lambda uri: list(triggers),
        scene_change_mode=lambda: mode,
        fire_scene=rec.fire_scene, fire_response=rec.fire_response,
        fire_analysed_flare=rec.fire_flare, select_color_set=rec.select_colour,
        fire_scene_update=rec.fire_update, analysed_color=rec.analysed_color,
        drop_colour=rec.drop_colour, analysed_plan=lambda uri, stored: plan or _Plan(),
        render_intensity=lambda x: x, lead_ms=lambda t: 0,
        response_offset_ms=lambda a: 0, sequencer_enabled=lambda: False,
        drop_offset_ms=lambda: 0, select_scene=lambda i: "scene-1",
        transition_intensity=lambda: 0.5, auto_generate=_noop, auto_refresh=_noop,
        clock=lambda: 0.0,
        lyric_enabled=lambda uri: enabled, lyric_settings=lambda: tuning,
        lyric_words=lyric_load or (lambda uri: words), lyric_colour=rec.lyric_colour,
        lyric_pick=pick or rec.lyric_pick, lyric_release_hold=rec.release, **kw)


def _sweep(engine, rec, stop=20_000, step=200, *, load=True):
    async def run():
        await engine.on_track_state(URI)
        await engine.plan_analysed_flares(URI)
        if load:
            await engine.load_lyric_words(URI)
        for pos in range(0, stop + step, step):
            rec.pos = pos
            await engine.tick(pos)
    asyncio.run(run())


def _trig(ts, action, *, tid=None, source="authored"):
    return SpectraTrigger(**({"id": tid} if tid else {}), timestamp_ms=ts, source=source,
                          action=action)


def _scene_trig(ts, *, tid="s1", color_set_id=None):
    return _trig(ts, FireSceneAction(scene_id="scene-1", color_set_id=color_set_id, intensity=0.5),
                 tid=tid)


def _flare_trig(ts, *, tid="f1"):
    return _trig(ts, FireResponseAction(event_class="flare", intensity=0.5), tid=tid)


def _drop_trig(ts, *, tid="d1"):
    return _trig(ts, FireResponseAction(event_class="drop", intensity=0.5), tid=tid)


def test_a_lone_word_lands_on_the_word_its_transition_early():
    rec = Rec()
    hit = _hit(10_000, energy=0.4, end_ms=10_400)
    transition = le.transition_ms_for(0.4)
    _sweep(_engine([], rec, hits=[hit]), rec)
    assert len(rec.words) == 1
    phrase, ramp_ms, pos = rec.words[0]
    assert phrase == "red"
    assert 10_000 - transition <= pos < 10_000 - transition + 200, "fired its transition early"
    assert pos + ramp_ms == 10_000, "the ramp is what is left, so it lands on the word"


def test_a_late_tick_still_lands_on_the_word():
    rec = Rec()
    hit = _hit(10_000, energy=0.74)
    engine = _engine([], rec, hits=[hit])
    async def run():
        await engine.on_track_state(URI)
        await engine.load_lyric_words(URI)
        for pos in (9_000, 9_950):
            rec.pos = pos
            await engine.tick(pos)
    asyncio.run(run())
    [(_, ramp_ms, pos)] = rec.words
    assert pos == 9_950 and ramp_ms == 50


def test_a_word_fires_once_and_again_after_a_rewind():
    rec = Rec()
    engine = _engine([], rec, hits=[_hit(10_000, energy=0.74)])
    async def run():
        await engine.on_track_state(URI)
        await engine.load_lyric_words(URI)
        for pos in list(range(9_000, 11_000, 200)) + [9_000] + list(range(9_000, 11_000, 200)):
            rec.pos = pos
            await engine.tick(pos)
    asyncio.run(run())
    assert len(rec.words) == 2


def test_a_seek_over_a_word_does_not_land_it_late():
    rec = Rec()
    engine = _engine([], rec, hits=[_hit(10_000, energy=0.74)])
    async def run():
        await engine.on_track_state(URI)
        await engine.load_lyric_words(URI)
        for pos in (9_000, 15_000):
            rec.pos = pos
            await engine.tick(pos)
    asyncio.run(run())
    assert rec.words == []


@pytest.mark.parametrize("mode,fires", [
    ("full", True), ("triggers_only", True), ("analysed", True), ("transitions", False)])
def test_only_in_modes_that_react_to_music(mode, fires):
    rec = Rec()
    _sweep(_engine([], rec, hits=[_hit(10_000, energy=0.74)], mode=mode), rec)
    assert bool(rec.words) is fires


def _show():
    """A show with every kind of thing on it, for the off-switch proof."""
    return [
        _scene_trig(4_000, tid="s1"),
        _flare_trig(6_000),
        _trig(8_000, SelectColorSetAction(set_id="blue"), tid="c1"),
        _trig(10_000, FireSceneUpdateAction(intensity=0.5), tid="u1"),
        _drop_trig(12_000),
        _trig(14_000, FireSceneAction(intensity=0.5), tid="g1", source="generated"),
    ]


def test_with_the_switch_off_the_output_is_exactly_an_engine_without_the_feature():
    """The boundary: trigger and colour output identical with the feature off.
    An engine given nothing about word colours is the control, and the show has a
    word beside every event."""
    hits = [_hit(ms, line=i, first=ms // 100, energy=0.6) for i, ms in enumerate(
        (4_100, 6_100, 8_100, 10_100, 12_100, 14_100, 16_000))]
    control = Rec()
    control_engine = TriggerEngine(
        energy_for=lambda uri, t: 0.5, list_triggers=lambda uri: _show(),
        scene_change_mode=lambda: "full",
        fire_scene=control.fire_scene, fire_response=control.fire_response,
        fire_analysed_flare=control.fire_flare, select_color_set=control.select_colour,
        fire_scene_update=control.fire_update, analysed_color=control.analysed_color,
        drop_colour=control.drop_colour, analysed_plan=lambda uri, stored: _Plan(),
        render_intensity=lambda x: x, lead_ms=lambda t: 0, response_offset_ms=lambda a: 0,
        sequencer_enabled=lambda: False, drop_offset_ms=lambda: 0,
        select_scene=lambda i: "scene-1", transition_intensity=lambda: 0.5,
        auto_generate=_noop, auto_refresh=_noop, clock=lambda: 0.0)
    off = Rec()
    loaded = []
    off_engine = _engine(_show(), off, hits=hits, enabled=False,
                         lyric_load=lambda uri: loaded.append(uri))
    _sweep(control_engine, control, load=False)
    _sweep(off_engine, off, load=False)
    assert off.fires == control.fires
    assert control.fires, "the control really fired things"
    assert off.words == [] and off.imprints == [None] * len(off.imprints)
    assert loaded == [], "with the switch off the words are never even read"


def test_switching_a_show_off_mid_song_stops_it():
    rec = Rec()
    state = {"on": True}
    engine = _engine([], rec, hits=[_hit(10_000, energy=0.74), _hit(19_000, energy=0.74, line=1, first=190)])
    engine._lyric_on = lambda uri: state["on"]
    async def run():
        await engine.on_track_state(URI)
        await engine.load_lyric_words(URI)
        for pos in range(9_000, 20_000, 200):
            rec.pos = pos
            if pos >= 15_000:
                state["on"] = False
            await engine.tick(pos)
    asyncio.run(run())
    assert len(rec.words) == 1


def test_a_word_beside_a_scene_change_gives_it_its_colour():
    rec = Rec()
    _sweep(_engine([_scene_trig(10_500)], rec, hits=[_hit(10_000)]), rec)
    assert ("scene", "scene-1", "red") in rec.fires
    assert rec.words == [], "instead of firing alone"
    assert rec.hold_released == 2, "the song change, then the word that gave its colour"


def test_a_force_colour_pin_on_a_scene_fire_lands_no_imprint():
    rec = Rec()
    async def forced(scene_id, color_set_id, intensity):
        return {"scene_id": scene_id, "forced_color": "pin"}
    logged = []
    engine = _engine([_scene_trig(10_500)], rec, hits=[_hit(10_000)])
    engine._fire_scene = forced
    engine._log_lyric = lambda key, hit, pos, detail: logged.append(detail["result"])
    _sweep(engine, rec)
    assert logged == [le.RESULT_CANNOT_CARRY]


def test_turning_a_show_off_mid_song_lets_a_held_colour_go():
    rec = Rec()
    state = {"on": True}
    engine = _engine([], rec, hits=[_hit(10_000)])
    engine._lyric_on = lambda uri: state["on"]
    async def run():
        await engine.on_track_state(URI)
        await engine.load_lyric_words(URI)
        for pos in (0, 200):
            rec.pos = pos
            await engine.tick(pos)
        state["on"] = False
        await engine.tick(400)
    asyncio.run(run())
    assert rec.hold_released == 2 and engine._lyric_plan == [], "the song change, then off"


def test_a_scene_that_allows_none_of_the_words_sets_keeps_its_own_and_nothing_fires():
    rec = Rec()
    engine = _engine([_scene_trig(10_500)], rec, hits=[_hit(10_000)],
                     pick=lambda *_a: {"result": "scene_disallows"})
    _sweep(engine, rec)
    assert ("scene", "scene-1", None) in rec.fires
    assert rec.words == []


def test_a_generated_scene_change_keeps_its_analysed_colour_unless_imprinted():
    rec = Rec()
    trig = _trig(10_500, FireSceneAction(intensity=0.5), tid="g", source="generated")
    engine = _engine([trig], rec, hits=[_hit(10_000)])
    engine.song_untriggered = lambda: True
    _sweep(engine, rec)
    assert not any(f[0] == "analysed_colour" for f in rec.fires), "the word's colour stands"

    rec = Rec()
    engine = _engine([trig], rec, hits=[_hit(10_000)],
                     pick=lambda *_a: {"result": "scene_disallows"})
    engine.song_untriggered = lambda: True
    _sweep(engine, rec)
    assert any(f[0] == "analysed_colour" for f in rec.fires), "no imprint, so it stays"


def test_his_own_scene_colour_is_not_overridden():
    rec = Rec()
    _sweep(_engine([_scene_trig(10_500, color_set_id="blue")], rec, hits=[_hit(10_000)]), rec)
    assert ("scene", "scene-1", "blue") in rec.fires
    assert rec.words == [], "no imprint, and no fire beside his own colour"


def test_his_own_colour_trigger_keeps_a_word_from_firing_on_top_of_it():
    rec = Rec()
    _sweep(_engine([_trig(10_500, SelectColorSetAction(set_id="blue"), tid="c")], rec,
                   hits=[_hit(10_000)]), rec)
    assert ("colour", "blue") in rec.fires and rec.words == []


def test_a_word_rides_on_a_flare():
    rec = Rec()
    _sweep(_engine([_flare_trig(10_500)], rec, hits=[_hit(10_000)]), rec)
    assert ("response", "flare") in rec.fires
    [imprint] = [i for i in rec.imprints if i is not None]
    assert imprint.event.id == "f1" and imprint.set_ids == ("red",)


def test_a_word_rides_on_an_update():
    rec = Rec()
    _sweep(_engine([_trig(10_500, FireSceneUpdateAction(intensity=0.5), tid="u1")], rec,
                   hits=[_hit(10_000)]), rec)
    [imprint] = [i for i in rec.imprints if i is not None]
    assert imprint.event.id == "u1"


def test_a_pre_drop_fade_carries_the_word_only_when_it_lands():
    """A word imprinting on a drop whose colour fades across its pre-drop: the
    fade wears the word, and a fade that was held leaves the drop to try."""
    rec = Rec()
    engine = _engine([_drop_trig(10_500)], rec, hits=[_hit(10_000)])
    results = iter([{"result": "held", "held_for": "preview"}, {"result": "jumped"}])
    seen: list = []
    async def colour(selection, pool_scene_id, ramp_ms, moment, analysed):
        imprint = le.active()
        record = dict(next(results), moment=moment)
        seen.append((moment, imprint))
        if imprint is not None and record["result"] == "jumped":
            imprint.note_landed("red", "Red")
        return record
    engine._drop_colour = colour

    class Told:
        seq = None; key = "his:d1"; pre_target_ms = 9_000; drop_target_ms = 10_500
        plays = True; kind = "spike"; intensity = 0.5; fire_mode = "full"
    async def run():
        await engine.on_track_state(URI)
        await engine.load_lyric_words(URI)
        await engine.tick(0)
        engine._pre_drop_told["his:d1"] = Told()
        for pos in range(8_000, 11_000, 200):
            rec.pos = pos
            await engine.tick(pos)
    asyncio.run(run())
    assert [(m, i is not None) for m, i in seen] == [("pre_drop", True), ("drop", True)], (
        "a held fade leaves the word for the drop")
    assert sum(1 for f in rec.fires if f[0] == "response") == 1


def test_a_pre_drop_fade_that_lands_spends_the_word():
    rec = Rec()
    seen: list = []
    engine = _engine([_drop_trig(10_500)], rec, hits=[_hit(10_000)])
    async def colour(selection, pool_scene_id, ramp_ms, moment, analysed):
        imprint = le.active()
        if imprint is not None:
            imprint.note_landed("red", "Red")
            seen.append(moment)
        return {"result": "jumped", "moment": moment}
    engine._drop_colour = colour

    class Told:
        seq = None; key = "his:d1"; pre_target_ms = 9_000; drop_target_ms = 10_500
        plays = True; kind = "spike"; intensity = 0.5; fire_mode = "full"
    async def run():
        await engine.on_track_state(URI)
        await engine.load_lyric_words(URI)
        await engine.tick(0)
        engine._pre_drop_told["his:d1"] = Told()
        for pos in range(8_000, 11_000, 200):
            rec.pos = pos
            await engine.tick(pos)
    asyncio.run(run())
    assert seen == ["pre_drop"], "the drop does not take it again"


def test_a_word_rides_on_a_drop_trigger():
    rec = Rec()
    _sweep(_engine([_drop_trig(10_500)], rec, hits=[_hit(10_000)]), rec)
    assert ("drop_colour", "drop") in rec.fires
    assert rec.imprints[0] is not None and rec.imprints[0].event.id == "d1"


def test_a_word_beside_an_analysed_flare():
    class M:
        trigger_id, timestamp_ms, generator_key, snap_grid, snap_moved_ms = "af", 10_500, "k", None, None
        intensity = 0.5
    rec = Rec()
    _sweep(_engine([], rec, hits=[_hit(10_000)], plan=_Plan(flares=[M()])), rec)
    assert ("analysed_flare",) in rec.fires
    assert [i for i in rec.imprints if i is not None][0].event.id == "af"


def test_a_drop_shift_moves_the_word_into_or_out_of_its_window():
    """Measured against where the drop will really fire."""
    rec = Rec()
    engine = _engine([_drop_trig(12_400)], rec, hits=[_hit(10_000)])
    engine._drop_offset_ms = lambda: -500
    _sweep(engine, rec)
    assert rec.imprints and rec.imprints[0].event.ms == 11_900

    rec = Rec()
    engine = _engine([_drop_trig(12_100)], rec, hits=[_hit(10_000)])
    engine._drop_offset_ms = lambda: 0
    _sweep(engine, rec)
    assert not any(rec.imprints) and len(rec.words) == 1, "2.1 s is outside the window"


def test_an_event_held_by_a_protected_window_is_not_an_event():
    rec = Rec()
    window = type("W", (), {"key": "k", "source": "x", "start_ms": 0, "drop_ms": 0, "end_ms": 0})()
    engine = _engine([_trig(10_500, FireSceneAction(intensity=0.5), tid="g", source="generated")],
                     rec, hits=[_hit(10_000)])
    engine._window_for = lambda trig, target, windows, seq_meta, flare_ids: window
    _sweep(engine, rec)
    assert len(rec.words) == 1, "no event near it, so it fires alone"


def test_a_scene_change_the_gates_refused_lands_no_imprint():
    rec = Rec()
    async def refused(scene_id, color_set_id, intensity):
        rec.fires.append(("refused", color_set_id))
        return {"skipped": "disabled"}
    engine = _engine([_scene_trig(10_500)], rec, hits=[_hit(10_000)])
    engine._fire_scene = refused
    fired = []
    engine._log_lyric = lambda key, hit, pos, detail: fired.append((key, detail["result"]))
    _sweep(engine, rec)
    assert fired == [("lyric:imprint", le.RESULT_CANNOT_CARRY)]


def test_the_show_log_says_what_each_word_did():
    from spectra.services import fire_history
    rec = Rec()
    _sweep(_engine([_flare_trig(10_500)], rec,
                   hits=[_hit(10_000), _hit(19_000, line=1, first=190, energy=0.74)]), rec)
    entries = [e for e in fire_history.load_show_log() if e["bucket"] == "triggers"]
    by_key = {e["key"]: e for e in entries}
    imprint = by_key["lyric:imprint"]
    assert imprint["detail"]["event_kind"] == le.KIND_FLARE
    assert imprint["detail"]["phrase"] == "red" and imprint["uri"] == URI
    fired = by_key["lyric:fire"]
    assert fired["detail"]["momentary"] is True and fired["detail"]["set_name"] == "Red"
    assert fired["detail"]["result"] == "jumped"


def test_every_song_change_clears_the_plan_and_the_held_colour():
    rec = Rec()
    engine = _engine([], rec, hits=[_hit(10_000)])
    async def run():
        await engine.on_track_state(URI)
        await engine.load_lyric_words(URI)
        await engine.tick(0)
        await engine.on_track_state("spotify:track:other")
    asyncio.run(run())
    assert engine._lyric_words is None and engine._lyric_plan == []
    assert rec.hold_released >= 1


def test_the_events_the_page_shows_are_the_events_the_clock_fires():
    """The page builds the list for any song; the clock builds it from what it
    is about to fire. For a song with NO old (source=="authored") triggers the
    two must still agree exactly.

    Scoped to an all-"generated" show deliberately: song_event_moments now
    builds its candidates/mode from a song's non-authored triggers only (the
    Admiral: old triggers "shouldn't be part of any future work"), so once a
    show carries an authored row the preview and the clock are allowed to
    diverge on it — see song_event_moments's own docstring, and
    test_word_colours_are_the_same_with_or_without_his_old_triggers below for
    that divergence proven deliberate."""
    class M:
        trigger_id, timestamp_ms, generator_key, snap_grid, snap_moved_ms = "af", 7_000, "k", None, None
        intensity = 0.5
    triggers = [
        _trig(4_000, FireSceneAction(intensity=0.5), tid="s1", source="generated"),
        _trig(6_000, FireResponseAction(event_class="flare", intensity=0.5), tid="f1", source="generated"),
        _trig(8_000, SelectColorSetAction(set_id="blue"), tid="c1", source="generated"),
        _trig(10_000, FireSceneUpdateAction(intensity=0.5), tid="u1", source="generated"),
        _trig(12_000, FireResponseAction(event_class="drop", intensity=0.5), tid="d1", source="generated"),
        _trig(14_000, FireSceneAction(intensity=0.5), tid="g1", source="generated"),
    ]
    rec = Rec()
    engine = _engine(triggers, rec, hits=[_hit(1_000)], plan=_Plan(flares=[M()]))
    seen: list = []
    original = engine._lyric_event_moments
    def spy(*args, **kw):
        out = original(*args, **kw)
        seen.append(out)
        return out
    engine._lyric_event_moments = spy
    async def run():
        await engine.on_track_state(URI)
        await engine.plan_analysed_flares(URI)
        await engine.load_lyric_words(URI)
        rec.pos = 0
        await engine.tick(0)
    asyncio.run(run())
    from_page = engine.song_event_moments(URI)
    key = lambda e: (e.id, e.kind, e.ms, e.can_carry)
    assert sorted(map(key, seen[-1])) == sorted(map(key, from_page))
    assert {e.kind for e in from_page} == {le.KIND_DROP, le.KIND_SCENE, le.KIND_FLARE}


def test_word_colours_are_the_same_with_or_without_his_old_triggers():
    """The Admiral, verbatim: "i am done adding my own triggers. the
    analyzed triggers are better. we should only focus on the analyzed
    triggers... they shouldn't be part of any future work, including this."
    song_event_moments (word colours) must give the SAME moments for a song
    whether or not it also carries his old source=="authored" rows."""
    class M:
        trigger_id, timestamp_ms, generator_key, snap_grid, snap_moved_ms = "af", 7_000, "k", None, None
        intensity = 0.5
    generated_only = [
        _trig(14_000, FireSceneAction(intensity=0.5), tid="g1", source="generated"),
    ]
    # Deliberately no drop/lull/charge row here: drop-SEQUENCE DETECTION
    # (_drop_view) still reads the full stored list unchanged (scoped out of
    # this fix, see song_event_moments's own docstring), so adding one would
    # test that instead of the word-colour independence this test is for.
    with_old_triggers = generated_only + [
        _scene_trig(4_000, tid="s1"),
        _flare_trig(6_000, tid="f1"),
    ]
    rec = Rec()
    plan = _Plan(flares=[M()])
    bare = _engine(generated_only, rec, hits=[_hit(1_000)], plan=plan, mode="triggers_only")
    with_old = _engine(with_old_triggers, Rec(), hits=[_hit(1_000)], plan=plan, mode="triggers_only")

    key = lambda e: (e.id, e.kind, e.ms, e.can_carry)
    assert sorted(map(key, bare.song_event_moments(URI))) == \
        sorted(map(key, with_old.song_event_moments(URI)))


# ── 4. the colour paths, real response engine ───────────────────────────────


def _imprint(sets, kind=le.KIND_DROP, ms=10_000):
    return le.Imprint(hit=_hit(ms, sets=sets),
                      event=le.EventMoment("e", kind, ms, "drop"))


def _with(imprint, coro_fn):
    async def run():
        token = le.ACTIVE.set(imprint)
        try:
            return await coro_fn()
        finally:
            le.ACTIVE.reset(token)
    return asyncio.run(run())


def _flare_scene(*, accept=None, colour=True):
    kinds = [FlareKind(name="Colour Jump", type="drift_jump", jump="color_set")] if colour else [
        FlareKind(name="Bump", type="momentary", gain=1.2)]
    return SceneV2(name="Orbits", devices=[SceneDeviceConfig(
        target_kind="virtual", target="v1", effect_type="orbits")],
        flare_kinds=kinds,
        responses={"flare": ResponseSpec(bands=[FlareBand(
            intensity_min=0.0, intensity_max=1.0, kinds={kinds[0].name: 1.0})])},
        accept_all_sets=accept is None, accepted_set_ids=list(accept or []))


def test_an_imprinted_drop_takes_the_words_colour_and_not_180(card_store):
    rig = Rig()
    rig.fire(_scene())
    imprint = _imprint(("green",))
    record = _with(imprint, lambda: rig.responses.drop_color_change(0.7))
    assert record["color_jump"]["picked_id"] == "green"
    assert record["rung"] == "lyric_imprint" and imprint.landed and imprint.set_id == "green"
    assert rig.room[0].active_set_id == "green"
    assert rig.responses._drop_colour_claim_until is not None, "the drop's own jump stands down"


def test_a_drop_with_no_word_keeps_the_180_rule(card_store):
    rig = Rig()
    rig.fire(_scene())
    record = asyncio.run(rig.responses.drop_color_change(0.7))
    assert record["pick"]["in_band"] is True and record["color_jump"]["picked_id"] == "cyan"


def test_a_scene_that_disallows_the_word_keeps_the_180_rule_on_its_drop(card_store):
    rig = Rig()
    rig.fire(_scene(accept=["cyan", "blue"]))
    imprint = _imprint(("green",))
    record = _with(imprint, lambda: rig.responses.drop_color_change(0.7))
    assert record["color_jump"]["picked_id"] == "cyan", "the 180 rule stands"
    assert imprint.result == le.RESULT_SCENE_DISALLOWS and not imprint.landed


def test_a_room_hold_on_a_drop_lands_no_imprint(card_store):
    rig = Rig(deferral=lambda: "paused")
    rig.fire(_scene())
    imprint = _imprint(("green",))
    _with(imprint, lambda: rig.responses.drop_color_change(0.7))
    assert imprint.result is None, "reported as cannot carry by the trigger clock"
    assert rig.room[0].active_set_id == "red"


def test_a_flare_wears_the_word_on_its_own_jump(card_store):
    rig = Rig()
    rig.fire(_flare_scene())
    imprint = _imprint(("blue",), kind=le.KIND_FLARE)
    record = _with(imprint, lambda: rig.responses.on_event("flare", 0.7))
    assert record["color_jump"]["picked_id"] == "blue" and imprint.landed
    assert rig.room[0].active_set_id == "blue"


def test_a_flare_with_no_colour_jump_cannot_carry(card_store):
    rig = Rig()
    rig.fire(_flare_scene(colour=False))
    imprint = _imprint(("blue",), kind=le.KIND_FLARE)
    _with(imprint, lambda: rig.responses.on_event("flare", 0.7))
    assert imprint.result is None and rig.room[0].active_set_id == "red"


def test_a_flare_the_scene_disallows_jumps_as_it_would_have(card_store):
    rig = Rig()
    rig.fire(_flare_scene(accept=["cyan", "blue"]))
    imprint = _imprint(("green",), kind=le.KIND_FLARE)
    record = _with(imprint, lambda: rig.responses.on_event("flare", 0.7))
    assert imprint.result == le.RESULT_SCENE_DISALLOWS
    assert record["color_jump"]["rung"] != "lyric_imprint"


def test_an_update_wears_the_word_on_the_flare_band_it_fires(card_store):
    rig = Rig()
    rig.fire(_flare_scene())
    imprint = _imprint(("blue",), kind=le.KIND_SCENE)
    record = _with(imprint, lambda: rig.responses.on_update(0.4))
    assert record["color_jump"]["picked_id"] == "blue" and imprint.landed


def test_a_staggered_colour_jump_carries_the_word(card_store):
    rig = Rig()
    kinds = [FlareKind(name="Now", type="momentary", gain=1.2),
             FlareKind(name="Later", type="drift_jump", jump="color_set", trigger_offset_ms=200)]
    scene = SceneV2(name="Orbits", devices=[SceneDeviceConfig(
        target_kind="virtual", target="v1", effect_type="orbits")], flare_kinds=kinds,
        responses={"flare": ResponseSpec(bands=[FlareBand(
            intensity_min=0.0, intensity_max=1.0, kinds={"Now": 1.0, "Later": 1.0})])})
    rig.fire(scene)
    imprint = _imprint(("blue",), kind=le.KIND_FLARE)
    _with(imprint, lambda: rig.responses.on_event("flare", 0.7, anchor_relocated=True))
    assert imprint.result == le.RESULT_STAGGERED and rig.room[0].active_set_id == "red"
    [batch] = rig.responses._pending_kind_batches
    assert batch.lyric is imprint
    asyncio.run(rig.responses.run_kind_batch(batch))
    assert imprint.landed and rig.room[0].active_set_id == "blue"


def test_the_chooser_stays_inside_the_scenes_allowed_list(card_store):
    rig = Rig()
    scene = _scene(accept=["green"])
    rig.fire(scene)
    for _ in range(20):
        got = rig.responses.lyric_pick(("green", "blue", "cyan"), scene, 0.5)
        assert got["set_id"] == "green"


def test_nothing_allowed_means_nothing_fires(card_store):
    rig = Rig()
    scene = _scene(accept=["green"])
    rig.fire(scene)
    assert rig.responses.lyric_pick(("blue",), scene, 0.5) == {
        "result": le.RESULT_SCENE_DISALLOWS}


def test_the_chooser_avoids_the_last_used(card_store):
    rig = Rig()
    scene = _scene()
    rig.fire(scene)
    rig.responses._last_lyric_set_id = "green"
    for _ in range(20):
        assert rig.responses.lyric_pick(("green", "blue"), scene, 0.5)["set_id"] == "blue"
    assert rig.responses.lyric_pick(("green",), scene, 0.5)["set_id"] == "green", (
        "unless it is the only one")


def test_a_group_on_a_match_stands_for_its_members(card_store):
    rig = Rig()
    scene = _scene(accept=["green"])
    rig.fire(scene)
    assert rig.responses.lyric_pick(("pool",), scene, 0.5)["set_id"] == "green"


def test_the_chooser_keeps_the_colour_already_showing(card_store):
    rig = Rig()
    scene = _scene()
    rig.fire(scene)
    assert rig.responses.lyric_pick(("red",), scene, 0.5)["result"] == "kept_current"


def _solo(rig, sets=("green",), *, momentary, ramp_ms=400):
    return asyncio.run(rig.responses.lyric_color_change(
        sets, intensity=0.5, ramp_ms=ramp_ms, momentary=momentary, dwell_ms=300, fade_ms=600))


def test_a_held_word_moves_the_room_to_it(card_store):
    rig = Rig()
    rig.fire(_scene())
    record = _solo(rig, momentary=False)
    assert record["result"] == "jumped" and rig.room[0].active_set_id == "green"
    assert record["color_jump"]["ramp_ms"] == 400


def test_a_momentary_word_leaves_the_rooms_story_alone_and_fades_back(card_store):
    rig = Rig()
    rig.fire(_scene())
    record = _solo(rig, momentary=True)
    assert rig.room[0].active_set_id == "red", "no active set, no wheel"
    assert record["color_jump"]["ramp_ms"] == 400
    moment = record["moment"]
    assert moment.release_after_s == pytest.approx(0.7)
    released = asyncio.run(rig.responses.release_lyric_moment(moment))
    assert released == {"result": "released", "virtuals": 1, "fade_ms": 600}
    last = rig.executor.writes[-1]
    assert (last["kind"], last["virtual_id"], last["params"], last["duration_ms"]) == (
        "glide", "v1", {"gradient": "#ff0000"}, 600)


def test_a_scene_change_during_a_momentary_word_keeps_the_new_colours(card_store):
    rig = Rig()
    scene = _scene()
    rig.fire(scene)
    record = _solo(rig, momentary=True)
    rig.fire(scene)
    out = asyncio.run(rig.responses.release_lyric_moment(record["moment"]))
    assert out == {"result": "stale", "why": "scene_changed"}


def test_a_colour_change_during_a_momentary_word_keeps_it(card_store):
    rig = Rig()
    rig.fire(_scene())
    record = _solo(rig, momentary=True)
    rig.room[0] = rig.room[0].model_copy(update={"active_set_id": "blue"})
    out = asyncio.run(rig.responses.release_lyric_moment(record["moment"]))
    assert out == {"result": "stale", "why": "colour_changed"}


def test_the_rooms_own_holds_stop_a_word_and_are_named(card_store):
    rig = Rig(deferral=lambda: "dinner_party")
    rig.fire(_scene())
    record = _solo(rig, momentary=False)
    assert record == {**record, "result": "held", "held_for": "dinner_party"}
    assert rig.room[0].active_set_id == "red"


def test_force_colour_holds_a_word(card_store):
    from spectra.services.room_controls import RoomControlState
    rig = Rig(controls=RoomControlState(force_color_enabled=True, force_color_target_id="blue"))
    rig.fire(_scene())
    record = _solo(rig, momentary=False)
    assert record["result"] == "held" and rig.room[0].active_set_id == "red"


def test_a_2d_gradient_holds_a_word(card_store):
    from spectra.services.room_controls import RoomControlState
    rig = Rig(controls=RoomControlState(active_gradient_id="g1"))
    rig.fire(_scene())
    assert _solo(rig, momentary=False)["held_for"] == "gradient_drift"


def test_a_scene_that_disallows_a_word_stops_it_and_says_so(card_store):
    rig = Rig()
    rig.fire(_scene(accept=["blue"]))
    record = _solo(rig, ("green",), momentary=False)
    assert record["result"] == le.RESULT_SCENE_DISALLOWS
    assert rig.room[0].active_set_id == "red"


def test_a_held_word_holds_the_journey_until_a_scene_change(card_store):
    rig = Rig()
    scene = _scene()
    rig.fire(scene)
    rig.conductor.hold_for_lyric()
    assert asyncio.run(rig.conductor.tick())["journey"]["held_for"] == "lyric_word"
    rig.fire(scene)
    assert rig.conductor.lyric_hold is False, "a scene change ends it"


def test_the_next_matched_word_ends_the_hold(card_store):
    rig = Rig()
    rig.fire(_scene())
    rig.conductor.hold_for_lyric()
    rig.conductor.release_lyric_hold()
    assert asyncio.run(rig.conductor.tick())["journey"].get("held_for") != "lyric_word"


def _wired(monkeypatch, rig):
    from spectra.services import engine as engine_mod
    from spectra.services import house
    monkeypatch.setattr(engine_mod, "responses", rig.responses)
    monkeypatch.setattr(engine_mod, "conductor", rig.conductor)
    monkeypatch.setattr(engine_mod, "_response_gate", lambda *_a, **_k: None)
    monkeypatch.setattr(house, "scene_deferral", lambda: None)
    return engine_mod


def _action(energy, *, sets=("green",), momentary):
    return le.WordAction(_hit(10_000, sets=sets, energy=energy), le.VERDICT_FIRE, energy=energy,
                         momentary=momentary, transition_ms=500)


def test_the_choke_point_holds_a_low_energy_colour(monkeypatch, card_store):
    rig = Rig()
    rig.fire(_scene())
    engine_mod = _wired(monkeypatch, rig)
    record = asyncio.run(engine_mod.fire_lyric_colour_event(_action(0.2, momentary=False), 400))
    assert record["result"] == "jumped" and rig.conductor.lyric_hold is True


def test_the_choke_point_schedules_a_momentary_fade_and_ends_a_hold(monkeypatch, card_store):
    rig = Rig()
    rig.fire(_scene())
    rig.conductor.hold_for_lyric()
    engine_mod = _wired(monkeypatch, rig)
    scheduled: list = []
    monkeypatch.setattr(engine_mod, "_schedule_lyric_release", scheduled.append)
    asyncio.run(engine_mod.fire_lyric_colour_event(_action(0.8, momentary=True), 150))
    assert rig.conductor.lyric_hold is False and len(scheduled) == 1


@pytest.mark.parametrize("gate", ["preview", "absorb", "house_mode", "scene_change_mode"])
def test_the_choke_point_takes_every_gate_a_colour_change_does(monkeypatch, card_store, gate):
    from spectra.services import engine as engine_mod
    rig = Rig()
    rig.fire(_scene())
    _wired(monkeypatch, rig)
    monkeypatch.setattr(engine_mod, "_response_gate", lambda *_a, **_k: gate)
    record = asyncio.run(engine_mod.fire_lyric_colour_event(_action(0.2, momentary=False), 400))
    assert record == {"result": "held", "held_for": gate}
    assert rig.room[0].active_set_id == "red" and not rig.executor.writes


def test_a_house_mode_that_owns_the_colours_stops_a_word(monkeypatch, card_store):
    from spectra.services import engine as engine_mod
    from spectra.services import house
    rig = Rig()
    rig.fire(_scene())
    _wired(monkeypatch, rig)
    monkeypatch.setattr(house, "scene_deferral", lambda: "calm")
    record = asyncio.run(engine_mod.fire_lyric_colour_event(_action(0.2, momentary=False), 400))
    assert record["held_for"] == "house_mode"


# ── 5. the store and the page ───────────────────────────────────────────────


def test_every_show_is_off_by_default_and_the_defaults_are_his_first_guesses():
    assert le.enabled(URI) is False and le.enabled(None) is False
    assert le.shows_on() == []
    tuning = le.settings()
    assert (tuning.energy_cutoff, tuning.min_gap_s, tuning.imprint_window_s) == (0.5, 8.0, 2.0)


def test_the_switch_works_for_any_show_and_only_that_show():
    assert le.set_show(URI, True) is True
    assert le.enabled(URI) and not le.enabled("spotify:track:other")
    assert le.shows_on() == [URI]
    le.set_show(URI, False)
    assert not le.enabled(URI) and le.shows_on() == []


def test_settings_change_alone_and_refuse_out_of_range():
    le.update_settings(min_gap_s=12.0)
    tuning = le.settings()
    assert tuning.min_gap_s == 12.0 and tuning.energy_cutoff == 0.5
    with pytest.raises(ValueError):
        le.update_settings(energy_cutoff=2.0)


def test_an_unreadable_store_reads_as_off_and_refuses_to_be_overwritten():
    from spectra import config as scfg
    scfg.LYRIC_EVENTS_FILE.write_text("{nope")
    assert le.enabled(URI) is False and le.settings().min_gap_s == 8.0
    with pytest.raises(le.StoreUnreadable):
        le.set_show(URI, True)


def test_turning_a_show_on_needs_him_nothing_writes_the_file_by_itself():
    from spectra import config as scfg
    rec = Rec()
    _sweep(TriggerEngine(
        energy_for=lambda uri, t: 0.5, list_triggers=lambda uri: [],
        scene_change_mode=lambda: "full", analysed_plan=lambda uri, stored: _Plan(),
        render_intensity=lambda x: x, lead_ms=lambda t: 0, sequencer_enabled=lambda: False,
        auto_generate=_noop, auto_refresh=_noop), rec, load=False)
    assert not scfg.LYRIC_EVENTS_FILE.exists()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    return TestClient(create_app())


@pytest.fixture
def lyric_song(monkeypatch, tmp_path):
    """A word timeline, and one match of his, on disk."""
    from spectra import config as scfg
    from spectra.models.lyric_labels import TargetRef
    from spectra.services import analysis_reader, lyric_matches, trigger_engine as te
    from tests.lyric_song_world import URI as WORLD_URI, color_sets, isolate, song
    isolate(tmp_path, monkeypatch, scfg, analysis_reader)
    color_sets(scfg)
    song(scfg)
    lyric_matches.add(WORLD_URI, 1, 1, TargetRef(kind="color_set", id="red1"))
    monkeypatch.setattr(te.trigger_engine, "_list_triggers", lambda uri: [])
    monkeypatch.setattr(te.trigger_engine, "_analysed_plan", lambda uri, stored: _Plan())
    monkeypatch.setattr(te.trigger_engine, "_scene_change_mode", lambda: "full")
    monkeypatch.setattr(te.trigger_engine, "_drop_view", lambda uri, t: {})
    return WORLD_URI


def test_the_page_says_what_each_word_would_do(client, lyric_song):
    data = client.get("/api/testbed/lyric-events", params={"uri": lyric_song}).json()
    assert data["status"] == "ok" and data["enabled"] is False
    assert data["settings"] == {"energy_cutoff": 0.5, "min_gap_s": 8.0, "imprint_window_s": 2.0}
    [action] = data["actions"]
    assert action["verdict"] == le.VERDICT_FIRE and action["source"] == "his"
    assert action["set_names"] == ["Blood Red"]
    assert action["words"].startswith("Fires on its own")


def test_the_page_turns_a_show_on_and_tunes_it(client, lyric_song):
    res = client.put("/api/testbed/lyric-events/show",
                     json={"uri": lyric_song, "enabled": True})
    assert res.status_code == 200 and res.json()["enabled"] is True
    assert client.get("/api/testbed/lyric-events",
                      params={"uri": lyric_song}).json()["enabled"] is True
    assert client.put("/api/testbed/lyric-events/settings",
                      json={"min_gap_s": 3.0}).json()["min_gap_s"] == 3.0
    assert client.put("/api/testbed/lyric-events/settings",
                      json={"imprint_window_s": 99}).status_code == 422


def test_a_song_with_no_words_says_so(client):
    data = client.get("/api/testbed/lyric-events",
                      params={"uri": "spotify:track:none"}).json()
    assert data["status"] == "none" and data["actions"] == []


def test_the_labels_and_claude_modules_stay_out_of_the_shows_imports():
    """The show loads none of this until a switched-on show asks: a fresh
    interpreter importing the engine's modules never pulls in Claude."""
    import subprocess
    import sys
    import textwrap
    from spectra import config as scfg
    driver = textwrap.dedent('''
        import json, sys
        import spectra.services.engine
        import spectra.services.trigger_engine
        import spectra.services.scene_response
        names = ["lyric_reading", "color_meanings", "claude_text", "lyric_matches", "sung_labels"]
        print(json.dumps({n: f"spectra.services.{n}" in sys.modules for n in names}))
    ''')
    proc = subprocess.run([sys.executable, "-c", driver], cwd=str(scfg.REPO_ROOT),
                          capture_output=True, text=True, timeout=90)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert not any(json.loads(proc.stdout.strip().splitlines()[-1]).values())
