"""WORD SHAPES — THE ENGINE CONTRACT (Word Shapes plan row W0.3, approved
by the Admiral 2026-11-15, defaults P1A/P2A/P3A). W0.1 (the shape library
and the told keys, `fx/effects/word_shapes.py` + `word_shape_keys.py`) is
proven by tests/test_word_shapes.py; this file proves everything BETWEEN a
sung word and that write:

  1. THE PLANNER, pure (`spectra/services/lyric_events.py`): a word that
     reaches a shape takes the shape branch, with his own rules — a drop
     inside the imprint window wins and the shape is skipped, a flare
     beside it does not, a shape takes its line and counts toward the
     shared minimum gap, the roll still decides whether it plays at all,
     and a word reaching BOTH a shape and colour sets is a shape.
  2. THE TIMING, one rule (`room_controls.word_shape_timing`): the form
     paces with Energy between his two numbers, the hold is the sung
     phrase clamped, the release is a multiple of the form.
  3. THE TRIGGER CLOCK (the real `TriggerEngine` over a position feed): the
     shape fires at `word − form` and the effect is told the time LEFT, so
     a late tick shortens the form instead of landing the shape late — the
     plan's clarity bar for this row, "complete on the word".
  4. THE EXECUTOR (the real `ResponseEngine`): the showing scene's Words
     section runs exactly as any class, the six told keys land on every
     live WORD_SHAPE_EFFECTS virtual and nowhere else, a flares-off
     virtual gets nothing, a colour kind pooled beside the shape fires too,
     and a scene with no Words band writes nothing and says so.
  5. THE GATES (`engine.fire_lyric_shape_event`): P3 A — a charge, lull or
     drop happening on the showing scene skips the shape, named.
  5b. THE COLOUR FALLBACK (W0.3 review, 2026-11-16): when nothing in the
     room could draw, a word that also reaches a colour set takes the
     colour path exactly as it would have, and a HOLD is deliberately not
     that case. His 57 switched-on songs are why this is a priority rather
     than a nicety: no existing word colour may disappear.
  6. THE EDGES: no trigger may name class `word`, the preview's three ruler
     marks, Sonic's reach, and a `responses["word"]` round-trip.

THE ROW'S OWN GATE, proven here and in tests/test_lyric_events.py's
switch-off proof: `WORD_SHAPE_EFFECTS` holds exactly the effects WAVE 1 has
wired and nothing else — EMPTY on W0.3, and from W1.6 onward the `WIRED`
tuple below, which each wave-1 row appends its own registry name to as it
lands. A scene with a Words band therefore writes to no fixture but those,
and the one proof that has to be edited to change that is this one. Every
test below that watches a real write monkeypatches the set to its own test
effect, which is also how anyone reading this can see at a glance which
effects a Words band can move.

THE PER-EFFECT MINIMUM FORM IS LIVE TOO, since W1.4: the Fish declares
2.0 s (`fx.device_model.WORD_SHAPE_FORM_MIN_S`), so a call to
`word_shape_timing` that names NO effects now answers with that floor — the
no-room fallback, deliberately — and every test here about the Energy-paced
form names the showing scene's own effects, exactly as every production
caller does.
"""
from __future__ import annotations

import asyncio
import json
from random import Random

import pytest

from fx import device_model
from fx.effects import word_shape_keys as wsk
from spectra.models.lyric_labels import LyricEventSettings
from spectra.models.scene import (FlareBand, FlareKind, ParamTarget, ResponseSpec,
                                  SceneDeviceConfig, SceneV2)
from spectra.services import lyric_events as le
from spectra.services import scene_response as sr
from spectra.services.room_controls import RoomControlState, word_shape_timing

URI = "spotify:track:wordshapes"
VID = "v1"
EFFECT = "orbits"
# An effect no Word Shapes row wires — the "not in the set" side of the
# membership gate. Squiggles draws no shape in any wave of the plan.
UNWIRED = "squiggles"
TUNING = LyricEventSettings()


def _run(coro):
    return asyncio.run(coro)


# ── the fixtures every section shares ───────────────────────────────────────


def _hit(ms=10_000, *, shape="heart", sets=(), energy=0.3, line=0, first=None,
         strength=0.9, end_ms=None, phrase="heart", pin=le.PIN_ALWAYS, his=False):
    first = first if first is not None else ms // 100
    return le.WordHit(
        key=f"{first}-{first}", first_word=first, last_word=first, phrase=phrase,
        label=phrase, line=line, ms=float(ms),
        end_ms=float(end_ms if end_ms is not None else ms + 900),
        emphasis=0.4, strength=strength, his=his, set_ids=tuple(sets),
        set_names=tuple(s.title() for s in sets), energy=energy,
        shape_id=shape, shape_name=None if shape is None else shape.title(),
        pin=pin, match_id="m1")


def _drop(ms, eid="d"):
    return le.EventMoment(eid, le.KIND_DROP, ms, "drop")


def _flare(ms, eid="f"):
    return le.EventMoment(eid, le.KIND_FLARE, ms, "flare")


def _plan(hits, events=(), **tuning):
    return le.plan_words(hits, events, LyricEventSettings(**tuning),
                         shape_timing=_room_timing())


def _room_timing(state: RoomControlState | None = None, effects=(EFFECT,)):
    """The showing scene's own timing, the way `engine.lyric_shape_timing`
    binds it to `conductor.virtuals` — named effects, never the global
    maximum."""
    st = state or RoomControlState()
    return lambda energy, phrase_ms: word_shape_timing(
        energy, phrase_ms, st, list(effects))


def _only(actions):
    assert len(actions) == 1
    return actions[0]


def _comparable(action) -> dict:
    """Every field of a planned action EXCEPT the shape's own trace — what
    "this word plans exactly as it would without its shape" means, field
    for field (the round-2 review's own standard)."""
    return {
        "verdict": action.verdict, "why": action.why,
        "event": None if action.event is None else action.event.id,
        "blocked_by": action.blocked_by, "energy": action.energy,
        "momentary": action.momentary, "transition_ms": action.transition_ms,
        "form_s": action.form_s, "hold_s": action.hold_s,
        "release_s": action.release_s,
    }


def _words_scene(name="Shape Scene", *, kinds=None, lanes=None,
                 word_bands=True, flare_shape=False) -> SceneV2:
    """A one-virtual scene whose Words section holds a Word Shape kind.
    `flare_shape` attaches the SAME kind to a Flares band too — the
    accepted-but-inert case the model allows and the save warns about."""
    declared = [FlareKind(name="Heart", type="word_shape")]
    attached = dict(kinds or {"Heart": 1.0})
    responses: dict = {}
    if word_bands:
        responses["word"] = ResponseSpec(bands=[FlareBand(
            intensity_min=0.0, intensity_max=1.0, kinds=attached,
            kind_lanes=dict(lanes or {}))])
    if flare_shape:
        responses["flare"] = ResponseSpec(bands=[FlareBand(
            intensity_min=0.0, intensity_max=1.0, kinds={"Heart": 1.0})])
    if "Colour Jump" in attached:
        declared.append(FlareKind(name="Colour Jump", type="drift_jump",
                                  jump="color_set"))
    if "Spin" in attached:
        declared.append(FlareKind(name="Spin", type="momentary",
                                  params={"spin": ParamTarget(mode="absolute",
                                                              value=0.9)}))
    return SceneV2(
        name=name,
        devices=[SceneDeviceConfig(id="d1", target_kind="virtual", target=VID,
                                   effect_type=EFFECT, params={"spin": 0.2})],
        flare_kinds=declared, responses=responses)


# Every effect a wave-1 row has WIRED to the told keys, in landing order.
# A row that opts an effect in adds its registry name here, on its own line,
# in the same change — the assertion below is what makes that deliberate
# rather than discovered later (W0.3 shipped this as "the set is empty"; the
# first wave-1 row to merge turned it into this tuple).
#   W1.6 — STAR, fx/effects/radial.py (the shape divisor, spin to rest)
#   W1.5 — Sauron, fx/effects/sauron.py (the shaped iris and its shaped
#          pupil, his Q8 C)
#   W1.2 — Fireworks, fx/effects/fireworks.py (the shaped payoff burst)
#   W1.3 — ORBITS, fx/effects/orbits.py (few trace it, many become it)
#   W1.1 — Black Hole, fx/effects/blackhole.py (the shaped event horizon)
#   W1.4 — FISH, fx/effects/fish.py (the procession along the outline; also
#          the first effect to declare a minimum form, 2.0 s)
WIRED = (
    "radial",
    "sauron",
    "fireworks",
    "orbits",
    "blackhole",
    "fish",
)


@pytest.fixture()
def shape_effects(monkeypatch):
    """The one thing a wave-1 row changes: the test effect knows shapes.
    `WORD_SHAPE_EFFECTS` must be exactly `WIRED` — see this module's own
    docstring."""
    assert device_model.WORD_SHAPE_EFFECTS == frozenset(WIRED), (
        "WORD_SHAPE_EFFECTS is the Word Shapes switch: it must hold exactly "
        "the effects wave 1 has wired (this module's WIRED tuple), so a row "
        "that opts an effect in appends its name there in the same change. "
        f"Wired here: {sorted(WIRED)}; in fx.device_model: "
        f"{sorted(device_model.WORD_SHAPE_EFFECTS)}")
    monkeypatch.setattr(device_model, "WORD_SHAPE_EFFECTS", frozenset({EFFECT}))


def _scratch(scene: SceneV2, intensity: float = 0.5):
    """The real ResponseEngine over a RecordingExecutor, seeded with the
    scene exactly as a real fire would (flare_preview._scratch_engine —
    the same resolve/compile path production uses)."""
    from spectra.services import flare_preview
    from spectra.services.fx_executor import RecordingExecutor
    clock = flare_preview._FakeClock()
    executor = RecordingExecutor(clock=clock)
    conductor, responder, _writes = flare_preview._scratch_engine(
        scene, intensity, clock, executor)
    responder._rng = Random(7)
    return conductor, responder, executor, clock


def _told(executor) -> list[dict]:
    """Every write that carried word-shape keys."""
    return [w for w in executor.writes if wsk.SHAPE_KEY in (w["params"] or {})]


# ═══ 1. the planner ═══════════════════════════════════════════════════════


def test_a_word_that_reaches_a_shape_draws_it():
    a = _only(_plan([_hit(energy=0.2)]))
    assert a.verdict == le.VERDICT_SHAPE
    assert a.shape_id == "heart" and a.event is None
    # The form IS the lead: one number, read by the trigger clock as
    # `fire_at = word - transition_ms` (docs/SPECTRA_TIMING_CONVENTIONS.md).
    assert a.transition_ms == round(a.form_s * 1000)


def test_a_drop_inside_the_window_skips_the_shape_and_keeps_the_colour():
    """His Q5 A, verbatim: "a drop within the imprint window wins and the
    shape is skipped" — THE SHAPE, not the colour (round-2 review,
    2026-11-16). A word that also reaches a colour set falls through and
    imprints on that drop exactly as it does today; `shape_skipped` is the
    only trace of the shape it did not draw."""
    for delta in (-2000, -1, 0, 1, 2000):
        a = _only(_plan([_hit(sets=("red",))], [_drop(10_000 + delta)]))
        assert a.verdict == le.VERDICT_IMPRINT, delta
        assert a.event is not None and a.event.kind == le.KIND_DROP
        assert a.shape_skipped == le.WHY_DROP_WINS, delta
    for delta in (-2001, 2001):
        far = _only(_plan([_hit(sets=("red",))], [_drop(10_000 + delta)]))
        assert far.verdict == le.VERDICT_SHAPE, delta
        assert far.shape_skipped is None, delta


def test_a_word_near_a_drop_plans_exactly_as_it_would_without_its_shape():
    """THE ROUND-2 TEST, field for field: his existing word colours must be
    byte-for-byte as today. Every "love"/"heart"/"star" sung within the
    window of a drop used to tint that drop, and still does."""
    drop = [_drop(10_400)]
    shaped = _only(_plan([_hit(sets=("red",))], drop))
    plain = _only(_plan([_hit(sets=("red",), shape=None)], drop))
    assert _comparable(shaped) == _comparable(plain)
    assert shaped.shape_skipped == le.WHY_DROP_WINS
    assert plain.shape_skipped is None


def test_a_shape_only_word_near_a_drop_has_nothing_to_fall_through_to():
    a = _only(_plan([_hit(sets=())], [_drop(10_400)]))
    assert a.verdict == le.VERDICT_NOTHING and a.why == le.WHY_DROP_WINS
    assert "no colour set" in le.describe(a)


def test_a_drop_with_its_colour_change_off_still_skips_the_shape():
    """`can_carry` is about carrying a COLOUR; a drop is the bigger musical
    moment either way, so the SHAPE is skipped regardless — and then the
    colour branch applies its own `can_carry` rule, as it always has."""
    cold = le.EventMoment("d", le.KIND_DROP, 10_400, "drop", False,
                          le.CANNOT_DROP_COLOUR_OFF)
    a = _only(_plan([_hit(sets=("red",))], [cold]))
    assert a.shape_skipped == le.WHY_DROP_WINS
    assert a.verdict == le.VERDICT_NOTHING and a.why == le.WHY_CANNOT_CARRY
    plain = _only(_plan([_hit(sets=("red",), shape=None)], [cold]))
    assert _comparable(a) == _comparable(plain)


# ── the plan-time "can anything draw this?" (round-2 fix B) ────────────────


def test_a_word_nothing_can_draw_is_planned_as_todays_colour_word():
    """THE ROUND-2 FIX (B), 2026-11-16. Deciding at the FIRE could only hand
    the colour whatever was left of the SHAPE's lead — 500-900 ms where a
    quiet colour glides in over 1.5-3 s. So the planner asks, and a word no
    scene can draw is planned as the colour word it is: own verdict, own
    momentary rule, own transition, own imprint."""
    for energy in (0.0, 0.2, 0.4, 0.8):
        hits = [_hit(sets=("red",), energy=energy)]
        shaped = _only(le.plan_words(hits, [], TUNING,
                                     shape_timing=_room_timing(),
                                     can_draw=lambda _e: False))
        plain = _only(_plan([_hit(sets=("red",), energy=energy, shape=None)]))
        assert _comparable(shaped) == _comparable(plain), energy
        assert shaped.transition_ms == le.transition_ms_for(energy), energy
        assert shaped.shape_skipped == le.WHY_CANNOT_DRAW, energy


def test_a_word_nothing_can_draw_still_imprints_as_today():
    flare = [_flare(10_400)]
    shaped = _only(le.plan_words([_hit(sets=("red",))], flare, TUNING,
                                 shape_timing=_room_timing(),
                                 can_draw=lambda _e: False))
    plain = _only(_plan([_hit(sets=("red",), shape=None)], flare))
    assert shaped.verdict == le.VERDICT_IMPRINT
    assert _comparable(shaped) == _comparable(plain)


def test_a_scene_that_can_draw_gets_the_shape():
    a = _only(le.plan_words([_hit(sets=("red",))], [], TUNING,
                            shape_timing=_room_timing(),
                            can_draw=lambda _e: True))
    assert a.verdict == le.VERDICT_SHAPE and a.shape_skipped is None


def test_can_draw_is_asked_at_the_words_own_energy():
    asked: list[float] = []

    def can_draw(energy: float) -> bool:
        asked.append(energy)
        return energy >= 0.5
    actions = le.plan_words(
        [_hit(10_000, sets=("red",), energy=0.2, line=0, first=1),
         _hit(30_000, sets=("red",), energy=0.8, line=1, first=2)],
        [], TUNING, shape_timing=_room_timing(), can_draw=can_draw)
    assert sorted(asked) == [0.2, 0.8]
    by_word = {a.hit.first_word: a for a in actions}
    assert by_word[1].verdict == le.VERDICT_FIRE
    assert by_word[2].verdict == le.VERDICT_SHAPE


def test_a_shape_only_word_is_still_a_shape_when_nothing_can_draw():
    """It has no colour to fall back to, so planning it as a colour word
    would invent one. It stays a shape, and the fire path logs `no_class`
    — which is how he finds out a scene needs a Words band."""
    a = _only(le.plan_words([_hit(sets=())], [], TUNING,
                            shape_timing=_room_timing(),
                            can_draw=lambda _e: False))
    assert a.verdict == le.VERDICT_SHAPE


def test_the_showing_scenes_words_band_is_what_can_draw_means():
    """`scene_response.words_band_draws` is the one answer, and it applies
    the same static gates a fire would: the band's Energy window, the
    kind's own `enabled` and its `min_intensity`."""
    full = _words_scene()
    assert sr.words_band_draws(full, 0.1) and sr.words_band_draws(full, 0.9)
    assert not sr.words_band_draws(None, 0.5), "no scene draws nothing"
    assert not sr.words_band_draws(_words_scene(word_bands=False), 0.5)

    narrow = _words_scene()
    narrow.responses["word"] = ResponseSpec(bands=[FlareBand(
        intensity_min=0.8, intensity_max=1.0, kinds={"Heart": 1.0})])
    assert not sr.words_band_draws(narrow, 0.2)
    assert sr.words_band_draws(narrow, 0.9)

    off = _words_scene()
    off.flare_kinds = [FlareKind(name="Heart", type="word_shape", enabled=False)]
    assert not sr.words_band_draws(off, 0.5)

    gated = _words_scene()
    gated.flare_kinds = [FlareKind(name="Heart", type="word_shape",
                                   min_intensity=0.6)]
    assert not sr.words_band_draws(gated, 0.5)
    assert sr.words_band_draws(gated, 0.7)

    # A Words band holding only a COLOUR kind draws no shape.
    colour_only = _words_scene(kinds={"Colour Jump": 1.0})
    colour_only.flare_kinds = [FlareKind(name="Colour Jump", type="drift_jump",
                                         jump="color_set")]
    assert not sr.words_band_draws(colour_only, 0.5)


def test_a_flare_or_a_scene_change_beside_a_shape_does_not_stop_it():
    """His Q5 A: "a flare or scene change does not stop a shape", and "a
    shape never imprints" — so the verdict is SHAPE, not IMPRINT."""
    scene_change = le.EventMoment("s", le.KIND_SCENE, 10_100, "scene change")
    a = _only(_plan([_hit()], [_flare(10_050), scene_change]))
    assert a.verdict == le.VERDICT_SHAPE
    assert a.event is None, "a shape never imprints on anything"


def test_a_shape_takes_its_line_like_a_fired_word():
    shape = _hit(10_000, line=3, first=1, strength=0.9)
    colour = _hit(11_000, shape=None, sets=("red",), line=3, first=2,
                  strength=0.7, phrase="red")
    out = {a.hit.first_word: a for a in _plan([colour, shape], min_gap_s=0)}
    assert out[1].verdict == le.VERDICT_SHAPE
    assert out[2].verdict == le.VERDICT_NOTHING and out[2].why == le.WHY_PHRASE


def test_the_gap_is_shared_between_a_colour_word_and_a_shape_word():
    """Both directions: a fired colour word blocks a shape inside the gap,
    and a shape blocks a colour word — "only a word that really did
    something counts against the next" is one rule for both kinds."""
    colour_first = _hit(10_000, shape=None, sets=("red",), line=0, first=1,
                        strength=0.95, phrase="red")
    shape_after = _hit(12_000, line=1, first=2, strength=0.7)
    out = {a.hit.first_word: a for a in _plan([colour_first, shape_after],
                                              min_gap_s=8)}
    assert out[1].verdict == le.VERDICT_FIRE
    assert out[2].verdict == le.VERDICT_NOTHING and out[2].why == le.WHY_TOO_SOON
    assert out[2].blocked_by == "red"

    shape_first = _hit(10_000, line=0, first=1, strength=0.95)
    colour_after = _hit(12_000, shape=None, sets=("red",), line=1, first=2,
                        strength=0.7, phrase="red")
    out = {a.hit.first_word: a for a in _plan([shape_first, colour_after],
                                              min_gap_s=8)}
    assert out[1].verdict == le.VERDICT_SHAPE
    assert out[2].verdict == le.VERDICT_NOTHING and out[2].why == le.WHY_TOO_SOON
    assert out[2].blocked_by == "heart", "the shape is what blocked it"

    # ... and outside the gap both act.
    far = _hit(20_000, shape=None, sets=("red",), line=1, first=2, strength=0.7,
               phrase="red")
    out = {a.hit.first_word: a for a in _plan([shape_first, far], min_gap_s=8)}
    assert out[1].verdict == le.VERDICT_SHAPE and out[2].verdict == le.VERDICT_FIRE


def test_the_roll_applies_to_a_shape_word():
    """A shape word that did not come up this play sits out BEFORE the
    planner, exactly as a colour word does — `roll_hits` is unchanged, and
    that is the point."""
    hit = _hit(strength=0.5, pin=None)
    sat_out, played = None, None
    for seed in range(200):
        [action] = le.plan_words(
            le.roll_hits([hit], le.Play(URI, seed)), [], TUNING,
            shape_timing=_room_timing())
        if action.why == le.WHY_SAT_OUT:
            sat_out = action
        elif action.verdict == le.VERDICT_SHAPE:
            played = action
        if sat_out and played:
            break
    assert sat_out is not None and played is not None, \
        "a 50% shape word both plays and sits out across plays"
    assert le.chance_for(hit) == pytest.approx(0.5)
    # Pinned Never, it never plays; pinned Always, it always does.
    [never] = le.plan_words(le.roll_hits([_hit(pin=le.PIN_NEVER)],
                                         le.Play(URI, 1)), [], TUNING)
    assert never.why == le.WHY_SAT_OUT


def test_a_word_reaching_a_shape_and_a_colour_set_is_a_shape():
    """The Words band's own colour kinds are how a shape word recolours the
    room, so the shape branch runs FIRST and the colour branch never sees
    it."""
    a = _only(_plan([_hit(sets=("red", "blue"))]))
    assert a.verdict == le.VERDICT_SHAPE
    assert a.hit.set_ids == ("red", "blue"), "it keeps its colour sets"


def test_a_shape_with_no_colour_set_is_no_longer_why_no_colour():
    hits = le.hits_from_matches(
        [{"first_word": 1, "last_word": 1, "phrase": "heart", "label": "heart",
          "ms": 10_000.0, "end_ms": 10_400.0, "score": 0.5, "confidence": 0.8,
          "source": "claude", "id": "m1"}],
        [0, 0], lambda _ms: 0.4,
        reach=lambda _m: [], shapes=lambda _m: [("heart", "Heart")])
    assert len(hits) == 1 and hits[0].shape_id == "heart"
    assert hits[0].why_not is None, "it has something to do"
    # ... and with neither, nothing changed.
    bare = le.hits_from_matches(
        [{"first_word": 1, "last_word": 1, "phrase": "x", "label": "x",
          "ms": 1.0, "end_ms": 2.0, "score": 0.5, "confidence": 0.8,
          "source": "claude"}],
        [0, 0], lambda _ms: None, reach=lambda _m: [], shapes=lambda _m: [])
    assert bare[0].why_not == le.WHY_NO_COLOUR and bare[0].shape_id is None


def test_the_strongest_match_decides_the_shape():
    def shapes(match):
        return [("star", "Star")] if match["id"] == "weak" else [("heart", "Heart")]
    hits = le.hits_from_matches(
        [{"first_word": 1, "last_word": 2, "phrase": "weak", "label": "weak",
          "ms": 10_000.0, "end_ms": 10_400.0, "score": 0.9, "confidence": 0.5,
          "source": "claude", "id": "weak"},
         {"first_word": 1, "last_word": 2, "phrase": "strong", "label": "strong",
          "ms": 10_000.0, "end_ms": 10_400.0, "score": 0.1, "confidence": 1.0,
          "source": "his", "id": "strong"}],
        [0, 0, 0], lambda _ms: 0.4, reach=lambda _m: [], shapes=shapes)
    assert len(hits) == 1 and hits[0].shape_id == "heart"


def test_the_shape_reach_is_off_unless_the_caller_asks():
    """`hits_from_matches` with no `shapes` argument behaves exactly as it
    did before shapes existed — the W0.2 labels side is what turns it on."""
    hits = le.hits_from_matches(
        [{"first_word": 1, "last_word": 1, "phrase": "red", "label": "red",
          "ms": 1.0, "end_ms": 2.0, "score": 0.5, "confidence": 0.8,
          "source": "claude"}],
        [0, 0], lambda _ms: None, reach=lambda _m: [("red", "Red")])
    assert hits[0].shape_id is None


def test_the_test_bed_sentence_and_payload_carry_the_shape():
    a = _only(_plan([_hit(energy=0.2)]))
    words = le.describe(a)
    assert "Heart" in words and "finishing on the word" in words
    payload = le.action_payload(a)
    assert payload["verdict"] == "shape" and payload["shape"] == "heart"
    assert payload["form_s"] == a.form_s and payload["hold_s"] == a.hold_s
    assert payload["release_s"] == a.release_s
    # The song strip's marker: the same kind as a colour word, plus `shape`.
    _imprints, fires = le.word_marks([a])
    assert len(fires) == 1 and fires[0]["kind"] == le.KIND_WORD
    assert fires[0]["shape"] == "heart"
    # ... and the live pulse.
    pushed = le.fired_payload(le.VERDICT_SHAPE, a.hit, event=None, set_id=None,
                              set_name=None, result="applied", landed=True,
                              uri=URI, position_ms=10_000)
    assert pushed["verdict"] == "shape" and pushed["shape"] == "heart"
    colour_push = le.fired_payload(le.VERDICT_FIRE, _hit(shape=None),
                                   event=None, set_id="red", set_name="Red",
                                   result="jumped", landed=True, uri=URI,
                                   position_ms=1)
    assert colour_push["shape"] is None


# ═══ 2. the timing, one rule ══════════════════════════════════════════════


def test_the_form_paces_with_energy_between_his_two_numbers():
    """Every call here names the SHOWING scene's effects, which is what
    every production caller does — a bare call asks for the global maximum
    of every declared minimum (the Fish's 2.0 s since W1.4), which is the
    no-room fallback and not the Energy pacing this test is about."""
    st = RoomControlState()
    showing = [EFFECT]
    assert st.word_shape_form_slow_s == 0.9 and st.word_shape_form_fast_s == 0.5
    assert word_shape_timing(0.0, 1000, st, showing)[0] == 0.9
    assert word_shape_timing(le.FAST_AT_ENERGY, 1000, st, showing)[0] == 0.5
    assert word_shape_timing(1.0, 1000, st, showing)[0] == 0.5, "0.75 and ABOVE"
    half = word_shape_timing(le.FAST_AT_ENERGY / 2, 1000, st, showing)[0]
    assert half == pytest.approx(0.7, abs=1e-3), "linear between"


def test_the_hold_is_the_sung_phrase_clamped_and_the_release_a_multiple():
    st = RoomControlState()
    assert (st.word_shape_hold_min_s, st.word_shape_hold_max_s) == (0.8, 2.0)
    assert st.word_shape_release_ratio == 1.5
    assert word_shape_timing(0.5, 400, st)[1] == 0.8, "shorter than the minimum"
    assert word_shape_timing(0.5, 1200, st)[1] == 1.2, "the phrase itself"
    assert word_shape_timing(0.5, 9000, st)[1] == 2.0, "longer than the maximum"
    form, _hold, release = word_shape_timing(0.0, 1000, st)
    assert release == pytest.approx(form * 1.5)


def test_every_timing_is_his_to_tune():
    st = RoomControlState(word_shape_form_slow_s=2.0, word_shape_form_fast_s=1.0,
                          word_shape_hold_min_s=0.1, word_shape_hold_max_s=0.2,
                          word_shape_release_ratio=0.5)
    showing = [EFFECT]
    assert word_shape_timing(0.0, 1000, st, showing) == (2.0, 0.2, 1.0)
    assert word_shape_timing(1.0, 50, st, showing) == (1.0, 0.1, 0.5)


def test_a_per_effect_minimum_form_floors_the_lead():
    """Plan section 2.4. THE FISH'S 2.0 s IS LIVE (row W1.4): a procession
    has to swim onto the outline, so the floor is declared in
    `fx.device_model.WORD_SHAPE_FORM_MIN_S` — never as a registered param
    (fx/effects/word_shape_keys.py's own "HOW AN EFFECT OPTS IN"). The
    floor applies to the LEAD and never shortens it."""
    assert device_model.WORD_SHAPE_FORM_MIN_S == {"fish": 2.0}
    assert device_model.word_shape_form_min_s(["fish"]) == 2.0
    # PLAN TIME with no room wired: no idea which scene will show, so the
    # global maximum — the only safe answer there.
    assert device_model.word_shape_form_min_s() == 2.0
    # FIRE TIME: exactly the showing effects, so a scene with no Fish in it
    # keeps the approved Energy-paced 0.5-0.9 s form.
    assert device_model.word_shape_form_min_s(["orbits"]) == 0.0
    assert device_model.word_shape_form_min_s(["orbits", "fish"]) == 2.0
    st = RoomControlState()
    assert word_shape_timing(1.0, 1000, st)[0] == 2.0, "the floor wins"
    assert word_shape_timing(1.0, 1000, st, ["fish"])[0] == 2.0
    assert word_shape_timing(1.0, 1000, st, ["orbits"])[0] == 0.5
    # a quiet word would be paced at 0.9 s; Fish still gets 2.0
    assert word_shape_timing(0.0, 1000, st, ["orbits"])[0] == 0.9
    assert word_shape_timing(0.0, 1000, st, ["fish"])[0] == 2.0


def test_the_planned_lead_asks_the_SHOWING_scenes_effects(monkeypatch):
    """THE REVIEW'S FIX (1), 2026-11-16. The lead IS the form in practice
    (the effect is told the time LEFT), so flooring the PLAN-time form at
    the global maximum would make every scene's shape form over the longest
    minimum any effect declares — a Black Hole scene would form over Fish's
    2.0 s instead of the approved Energy-paced 0.5-0.9 s. So the planner
    asks the SHOWING scene."""
    from spectra.services import engine as engine_mod
    monkeypatch.setattr(device_model, "WORD_SHAPE_FORM_MIN_S", {"fish": 2.0})
    energy_form_s = word_shape_timing(0.8, 900, RoomControlState(), ["orbits"])[0]
    assert energy_form_s == 0.5, "the Energy-paced form, with no floor in reach"

    for effect, expected in ((EFFECT, energy_form_s), ("fish", 2.0)):
        scene = _words_scene()
        scene.devices[0].effect_type = effect
        _cond, responder, _executor, _clock = _scratch(scene)
        monkeypatch.setattr(engine_mod, "conductor", responder.conductor)
        [action] = le.plan_words(
            [_hit(energy=0.8, end_ms=10_900)], [], TUNING,
            shape_timing=engine_mod.lyric_shape_timing)
        assert action.form_s == expected, effect
        assert action.transition_ms == round(expected * 1000), effect

    # A bare engine with no room attached keeps the only safe answer there
    # is — the global maximum — and says so in its own docstring.
    from spectra.services.trigger_engine import TriggerEngine
    assert TriggerEngine._room_shape_timing(0.8, 900)[0] == 2.0


def test_unreadable_room_controls_fall_back_to_the_plans_defaults(monkeypatch):
    from spectra.services import room_controls
    monkeypatch.setattr(room_controls, "load_room_controls",
                        lambda: (_ for _ in ()).throw(OSError("gone")))
    assert sr.word_shape_lead_ms(0.0) == int(round(wsk.DEFAULT_FORM_S * 1000))


# ═══ 3. the trigger clock ═════════════════════════════════════════════════


class Rec:
    """Records what the clock asked for, nothing more. `shape_result` is
    what the shape hook reports back, so a spec can put the engine in the
    "nothing could draw" state the colour fallback exists for."""

    shape_result: dict = {"result": "applied", "word_shape": {"virtuals": 1}}

    def __init__(self, shape_result=None):
        self.shapes: list = []
        self.words: list = []
        self.pos = 0
        if shape_result is not None:
            self.shape_result = shape_result

    async def lyric_shape(self, action, ramp_ms):
        self.shapes.append((action.hit.phrase, action.hit.shape_id, ramp_ms,
                            self.pos, action.form_s, action.hold_s,
                            action.release_s, action.energy))
        return dict(self.shape_result)

    async def lyric_colour(self, action, ramp_ms):
        self.words.append((action.hit.phrase, ramp_ms, self.pos,
                           action.verdict, action.momentary,
                           action.transition_ms))
        return {"result": "jumped",
                "color_jump": {"picked_id": "red", "set_name": "Red"}}


async def _noop(_uri):
    return None


class _Plan:
    flares: list = []
    scene_cues: list = []


def _clock_engine(rec, hits, *, triggers=(), mode="full"):
    """A real TriggerEngine over a position feed. `lyric_shape_timing` is
    wired to THIS TEST'S showing effect, exactly as the live engine wires
    `engine.lyric_shape_timing` to the showing scene's own effects: left
    unwired, the engine's own `_room_shape_timing` fallback asks for the
    global maximum of every declared per-effect minimum (the Fish's 2.0 s
    since W1.4), which is the no-room answer and not what a clock test of
    the Energy-paced form is about."""
    from spectra.services.trigger_engine import TriggerEngine
    words = le.SongWords(URI, "ok", hits=tuple(hits))
    return TriggerEngine(
        energy_for=lambda uri, t: 0.5, list_triggers=lambda uri: list(triggers),
        scene_change_mode=lambda: mode, sequencer_enabled=lambda: False,
        analysed_plan=lambda uri, stored: _Plan(), auto_generate=_noop,
        auto_refresh=_noop, clock=lambda: 0.0, render_intensity=lambda x: x,
        lead_ms=lambda t: 0, response_offset_ms=lambda a: 0,
        drop_offset_ms=lambda: 0, select_scene=lambda i: None,
        transition_intensity=lambda: 0.5,
        lyric_enabled=lambda uri: True, lyric_settings=lambda: TUNING,
        lyric_words=lambda uri: words, lyric_colour=rec.lyric_colour,
        lyric_shape=rec.lyric_shape,
        lyric_shape_timing=_room_timing())


def _sweep(engine, rec, stop=20_000, step=200):
    async def run():
        await engine.on_track_state(URI)
        await engine.load_lyric_words(URI)
        for pos in range(0, stop + step, step):
            rec.pos = pos
            await engine.tick(pos)
    asyncio.run(run())


@pytest.mark.parametrize("energy", [0.2, 0.8])
def test_a_shape_fires_its_form_early_and_lands_on_the_word(energy):
    """THE ROW'S CLARITY BAR (plan section 6): "complete on the word". The
    write goes out at `word − form` within one tick, and what the effect is
    told as its form is the time LEFT — so the envelope reaches 1.0 on the
    word by construction."""
    rec = Rec()
    hit = _hit(10_000, energy=energy, end_ms=10_900)
    form_s = word_shape_timing(energy, 900, RoomControlState(), [EFFECT])[0]
    _sweep(_clock_engine(rec, [hit]), rec)
    assert len(rec.shapes) == 1 and rec.words == []
    _phrase, shape, ramp_ms, pos, planned_form, hold_s, release_s, told_e = rec.shapes[0]
    assert shape == "heart"
    fire_at = 10_000 - round(form_s * 1000)
    assert fire_at <= pos < fire_at + 200, "fired its form early"
    assert pos + ramp_ms == 10_000, "the ramp is what is left of the form"
    assert planned_form == form_s
    assert (hold_s, release_s) == word_shape_timing(
        energy, 900, RoomControlState(), [EFFECT])[1:]
    assert told_e == energy


def test_a_late_tick_shortens_the_form_instead_of_landing_late():
    rec = Rec()
    engine = _clock_engine(rec, [_hit(10_000, energy=0.8)])

    async def run():
        await engine.on_track_state(URI)
        await engine.load_lyric_words(URI)
        for pos in (9_000, 9_940):
            rec.pos = pos
            await engine.tick(pos)
    asyncio.run(run())
    [(_p, _s, ramp_ms, pos, *_rest)] = rec.shapes
    assert (pos, ramp_ms) == (9_940, 60)
    assert pos + ramp_ms == 10_000


def test_a_shape_fires_exactly_once_per_approach():
    rec = Rec()
    _sweep(_clock_engine(rec, [_hit(10_000, energy=0.5)]), rec)
    assert len(rec.shapes) == 1


def test_a_seek_over_a_shape_word_does_not_land_it_late():
    rec = Rec()
    engine = _clock_engine(rec, [_hit(10_000, energy=0.8)])

    async def run():
        await engine.on_track_state(URI)
        await engine.load_lyric_words(URI)
        for pos in (9_000, 15_000):
            rec.pos = pos
            await engine.tick(pos)
    asyncio.run(run())
    assert rec.shapes == []


def test_the_show_log_records_every_shape_word():
    from spectra.services import fire_history
    rec = Rec()
    _sweep(_clock_engine(rec, [_hit(10_000, energy=0.4)]), rec)
    rows = [r for r in fire_history.load_show_log(uri=URI)
            if r.get("key") == "lyric:shape"]
    assert len(rows) == 1
    detail = rows[0]["detail"]
    assert detail["verdict"] == "shape" and detail["shape"] == "heart"
    assert detail["result"] == "applied" and detail["ramp_ms"] > 0
    for key in ("form_s", "hold_s", "release_s", "energy"):
        assert key in detail, key


@pytest.mark.parametrize("record,result,held", [
    ({"result": "no_class"}, "no_class", None),
    ({"result": "held", "held_for": "phase", "reason": "lull"}, "held", "phase"),
    ({"result": "held", "held_for": "preview"}, "held", "preview"),
])
def test_a_shape_that_did_nothing_is_logged_too(record, result, held):
    """A scene with no Words band, a phase holding the room, a preview: the
    word is still on the show log, with WHY. Silence would make "the shape
    didn't fire" unanswerable from the record."""
    from spectra.services import fire_history
    rec = Rec()

    async def hook(action, ramp_ms):
        rec.shapes.append((action.hit.phrase, action.hit.shape_id, ramp_ms, rec.pos))
        return dict(record)
    rec.lyric_shape = hook
    _sweep(_clock_engine(rec, [_hit(10_000, energy=0.4)]), rec)
    [row] = [r for r in fire_history.load_show_log(uri=URI)
             if r.get("key") == "lyric:shape"]
    assert row["detail"]["result"] == result
    assert row["detail"]["held_for"] == held
    assert row["detail"]["shape"] == "heart"


def test_an_unwired_shape_hook_is_named_rather_than_silent():
    """The hook is a no-op until services/engine.py wires it (the
    _analysed_color precedent). A show driven by a bare TriggerEngine must
    say "unwired", not pretend it fired."""
    from spectra.services import fire_history
    from spectra.services.trigger_engine import TriggerEngine
    words = le.SongWords(URI, "ok", hits=(_hit(10_000, energy=0.4),))
    engine = TriggerEngine(
        energy_for=lambda uri, t: 0.5, list_triggers=lambda uri: [],
        scene_change_mode=lambda: "full", sequencer_enabled=lambda: False,
        analysed_plan=lambda uri, stored: _Plan(), auto_generate=_noop,
        auto_refresh=_noop, clock=lambda: 0.0, render_intensity=lambda x: x,
        lead_ms=lambda t: 0, response_offset_ms=lambda a: 0,
        drop_offset_ms=lambda: 0, select_scene=lambda i: None,
        transition_intensity=lambda: 0.5,
        lyric_enabled=lambda uri: True, lyric_settings=lambda: TUNING,
        lyric_words=lambda uri: words)
    _sweep(engine, Rec())
    [row] = [r for r in fire_history.load_show_log(uri=URI)
             if r.get("key") == "lyric:shape"]
    assert row["detail"]["result"] == "unwired"


# ═══ 4. the executor ══════════════════════════════════════════════════════


def test_the_told_write_lands_the_six_keys_on_every_shape_effect(shape_effects):
    scene = _words_scene()
    _cond, responder, executor, _clock = _scratch(scene)
    action = _only(_plan([_hit(energy=0.8, end_ms=10_000 + 900)]))
    record = _run(responder.on_word_shape(action))
    assert record["result"] == "applied" and record["class"] == "word"
    [write] = _told(executor)
    assert write["virtual_id"] == VID and write["kind"] == "jump"
    params = write["params"]
    assert set(wsk.KEYS) <= set(params), "all six keys, every time"
    assert params[wsk.SHAPE_KEY] == "heart"
    assert params[wsk.SEQ_KEY] == 1
    assert params[wsk.FORM_KEY] == action.form_s
    assert params[wsk.HOLD_KEY] == action.hold_s
    assert params[wsk.RELEASE_KEY] == action.release_s
    assert params[wsk.LEVEL_KEY] == pytest.approx(0.8)
    # The surge record names what it reached.
    assert record["word_shape"] == {
        "shape": "heart", "seq": 1, "form_s": action.form_s,
        "hold_s": action.hold_s, "release_s": action.release_s,
        "level": pytest.approx(0.8), "virtuals": 1}
    # Nothing carried, nothing released — the firework_burst shape.
    assert record["carried"] == [] and responder.pending_hold_groups() == []


def test_the_seq_edges_for_two_words_of_the_same_shape(shape_effects):
    _cond, responder, executor, _clock = _scratch(_words_scene())
    action = _only(_plan([_hit(energy=0.5)]))
    _run(responder.on_word_shape(action))
    _run(responder.on_word_shape(action))
    seqs = [w["params"][wsk.SEQ_KEY] for w in _told(executor)]
    assert seqs == [1, 2], "an effect watches the SEQ, never the id"


def test_a_told_level_is_never_zero(shape_effects):
    _cond, responder, executor, _clock = _scratch(_words_scene())
    _run(responder.on_word_shape(_only(_plan([_hit(energy=0.0)]))))
    [write] = _told(executor)
    assert write["params"][wsk.LEVEL_KEY] == wsk.LEVEL_FLOOR, \
        "0 may only ever mean 'not told'"


def test_a_flares_off_virtual_gets_nothing(shape_effects):
    _cond, responder, executor, _clock = _scratch(_words_scene())
    responder._flare_blocked = lambda: frozenset({VID})
    record = _run(responder.on_word_shape(_only(_plan([_hit()]))))
    assert _told(executor) == []
    assert record["word_shape"]["virtuals"] == 0


def test_an_effect_that_does_not_know_shapes_gets_nothing():
    """The membership gate, from the other side — and the state of most of
    his room: the Words section runs in full, and an effect that is not in
    WORD_SHAPE_EFFECTS is written nothing at all. This test uses the REAL
    set (no `shape_effects` fixture) on an effect no row has wired, so it
    stays true however many wave-1 rows land."""
    assert UNWIRED not in device_model.WORD_SHAPE_EFFECTS, (
        f"{UNWIRED!r} was wired for word shapes: this test needs an effect "
        "that is NOT, so point it at another one")
    scene = _words_scene()
    scene.devices[0].effect_type = UNWIRED
    _cond, responder, executor, _clock = _scratch(scene)
    record = _run(responder.on_word_shape(_only(_plan([_hit()]))))
    assert record["result"] == "applied"
    assert _told(executor) == []
    assert record["word_shape"]["virtuals"] == 0


def test_a_scene_with_no_words_band_writes_nothing_and_says_so(shape_effects):
    _cond, responder, executor, _clock = _scratch(_words_scene(word_bands=False))
    record = _run(responder.on_word_shape(_only(_plan([_hit()]))))
    assert record["result"] == "no_class"
    assert list(executor.writes) == [], "the band is the switch (his Q6 A)"


def test_a_words_band_that_does_not_reach_this_energy_is_no_band(shape_effects):
    scene = _words_scene()
    scene.responses["word"] = ResponseSpec(bands=[FlareBand(
        intensity_min=0.8, intensity_max=1.0, kinds={"Heart": 1.0})])
    _cond, responder, executor, _clock = _scratch(scene)
    record = _run(responder.on_word_shape(_only(_plan([_hit(energy=0.2)]))))
    assert record["result"] == "no_band" and _told(executor) == []


def test_a_colour_kind_pooled_beside_the_shape_fires_too(shape_effects):
    """His Q5 A: "a colour kind may be pooled beside the shape" — the Words
    band is an ordinary ResponseSpec, so a Colour Jump in it fires exactly
    as it would anywhere."""
    scene = _words_scene(kinds={"Heart": 1.0, "Colour Jump": 1.0})
    _cond, responder, executor, _clock = _scratch(scene)
    record = _run(responder.on_word_shape(_only(_plan([_hit(energy=0.5)]))))
    assert record["result"] == "applied"
    assert len(_told(executor)) == 1
    types = {k["type"] for k in record["kinds"]}
    assert types == {"word_shape", "drift_jump"}
    # The jump went through the SAME _color_jump the other four classes use
    # (what it lands is the colour selector's own business — unconfigured in
    # this scratch room, which is why the result is named rather than
    # asserted to be a specific set).
    assert "color_jump" in record


def test_a_momentary_kind_in_the_words_band_still_releases(shape_effects):
    """The Words section is an ordinary class: a momentary kind beside the
    shape spikes and queues its release, as it would on a flare band."""
    scene = _words_scene(kinds={"Heart": 1.0, "Spin": 1.0})
    _cond, responder, executor, _clock = _scratch(scene)
    record = _run(responder.on_word_shape(_only(_plan([_hit(energy=0.5)]))))
    assert record["result"] == "applied"
    assert responder.pending_hold_groups(), "the spike is queued for release"
    assert len(_told(executor)) == 1


def test_a_shape_kind_on_a_flare_band_writes_nothing(shape_effects):
    """Accepted by the model, inert at fire time, and the save says so."""
    from spectra.services import scene_store
    scene = _words_scene(flare_shape=True)
    _cond, responder, executor, _clock = _scratch(scene)
    record = _run(responder.on_event("flare", 0.5))
    assert record["result"] == "applied"
    assert _told(executor) == [], "no shape, no write"
    [kind] = [k for k in record["kinds"] if k["type"] == "word_shape"]
    assert kind["result"] == "no_word"
    warnings = scene_store.scene_warnings(scene)
    assert len(warnings) == 1 and "does nothing" in warnings[0]
    assert scene_store.scene_warnings(_words_scene()) == []


def test_the_words_section_arms_no_phase(shape_effects):
    """"word" is not in PHASE_RAMP_MS, so a Words band drives no
    charge/lull/drop choreography — the phase machinery never sees it."""
    assert "word" not in sr.PHASE_RAMP_MS
    _cond, responder, executor, _clock = _scratch(_words_scene())
    record = _run(responder.on_word_shape(_only(_plan([_hit()]))))
    assert "phase" not in record
    assert responder.phase_armed() is None
    assert not any(w["params"].get("phase") for w in executor.writes)


def test_no_active_scene_is_named_not_crashed():
    _cond, responder, _executor, _clock = _scratch(_words_scene())
    responder.conductor.scene = None
    record = _run(responder.on_word_shape(_only(_plan([_hit()]))))
    assert record["result"] == "no_active_scene"


# ═══ 5. the gates (P3 A) ══════════════════════════════════════════════════


def test_a_charge_or_lull_or_drop_happening_skips_the_shape(monkeypatch,
                                                            shape_effects):
    """P3 A, the Admiral's own default: "a shape word landing inside a
    charge, lull or drop is skipped and logged"."""
    from spectra.services import engine as engine_mod
    scene = _words_scene()
    _cond, responder, executor, clock = _scratch(scene)
    monkeypatch.setattr(engine_mod, "responses", responder)
    monkeypatch.setattr(engine_mod, "conductor", responder.conductor)
    action = _only(_plan([_hit(energy=0.5)]))

    # Nothing armed: it fires.
    record = _run(engine_mod.fire_lyric_shape_event(action, 500))
    assert record["result"] == "applied"
    assert len(_told(executor)) == 1

    for armed in ("charge", "lull"):
        responder._phase_armed = armed
        held = _run(engine_mod.fire_lyric_shape_event(action, 500))
        assert held == {"result": "held", "held_for": "phase", "reason": armed}
    responder._phase_armed = None

    # A DROP arms no phase of its own, so it counts for its own ramp.
    responder._drop_armed_until = clock() + sr.PHASE_RAMP_MS["drop"] / 1000.0
    assert responder.phase_armed() == "drop"
    held = _run(engine_mod.fire_lyric_shape_event(action, 500))
    assert held["held_for"] == "phase" and held["reason"] == "drop"
    clock.advance_to(clock() + 1.0)
    assert responder.phase_armed() is None
    assert len(_told(executor)) == 1, "nothing was written while held"


def test_a_drop_arming_stamps_its_own_window(shape_effects):
    _cond, responder, _executor, clock = _scratch(_words_scene())
    assert responder.phase_armed() is None
    _run(responder.on_event("drop", 0.8))
    assert responder.phase_armed() == "drop"
    clock.advance_to(clock() + sr.PHASE_RAMP_MS["drop"] / 1000.0 + 0.01)
    assert responder.phase_armed() is None


def test_the_fire_time_form_is_the_time_left_floored_at_the_effects_minimum(
        monkeypatch, shape_effects):
    """The "conservative at plan time, exact at fire time" split: the
    planner's form was the LEAD, and what the effect is TOLD is the ramp —
    never shorter than the showing effect can assemble in."""
    from spectra.services import engine as engine_mod
    _cond, responder, executor, _clock = _scratch(_words_scene())
    monkeypatch.setattr(engine_mod, "responses", responder)
    monkeypatch.setattr(engine_mod, "conductor", responder.conductor)
    action = _only(_plan([_hit(energy=0.8)]))
    _run(engine_mod.fire_lyric_shape_event(action, 310))
    assert _told(executor)[-1]["params"][wsk.FORM_KEY] == pytest.approx(0.31)
    monkeypatch.setattr(device_model, "WORD_SHAPE_FORM_MIN_S", {EFFECT: 2.0})
    _run(engine_mod.fire_lyric_shape_event(action, 310))
    assert _told(executor)[-1]["params"][wsk.FORM_KEY] == pytest.approx(2.0)


def test_a_preview_or_a_house_mode_holds_a_shape(monkeypatch, shape_effects):
    from spectra.services import engine as engine_mod
    from spectra.services import preview_pause
    _cond, responder, executor, _clock = _scratch(_words_scene())
    monkeypatch.setattr(engine_mod, "responses", responder)
    monkeypatch.setattr(engine_mod, "conductor", responder.conductor)
    action = _only(_plan([_hit()]))
    preview_pause.start(30.0)
    try:
        held = _run(engine_mod.fire_lyric_shape_event(action, 500))
    finally:
        preview_pause.clear()
    assert held == {"result": "held", "held_for": "preview"}
    assert _told(executor) == []

    from spectra.services import house
    monkeypatch.setattr(house, "scene_deferral", lambda: "mode 'Away'")
    held = _run(engine_mod.fire_lyric_shape_event(action, 500))
    assert held["held_for"] == "house_mode" and held["reason"] == "mode 'Away'"
    assert _told(executor) == []


# ═══ 5b. the colour fallback (the review's priority fix) ══════════════════


NOTHING_DREW = [
    ({"result": "no_class"}, "no_class"),
    ({"result": "no_band"}, "no_band"),
    ({"result": "no_active_scene"}, "no_active_scene"),
]


@pytest.mark.parametrize("record,why", NOTHING_DREW)
def test_a_shape_with_nowhere_to_draw_falls_back_to_its_colour(record, why):
    """THE REVIEW'S PRIORITY FIX (2026-11-16). He has word colours switched
    on for all 57 songs with sung words, and no existing word colour may
    disappear. A word that reaches a shape AND a colour set, on a scene that
    cannot draw, must change the colour exactly as it did before this row
    existed — its own momentary/held rule by Energy, and the same
    time-left ramp."""
    from spectra.services import fire_history
    rec = Rec(shape_result=record)
    hit = _hit(10_000, energy=0.8, sets=("red",), end_ms=10_900)
    _sweep(_clock_engine(rec, [hit]), rec)
    assert len(rec.shapes) == 1, "the shape was tried first"
    assert len(rec.words) == 1, "and the colour took over"
    phrase, ramp_ms, pos, verdict, momentary, transition_ms = rec.words[0]
    assert phrase == "heart"
    assert verdict == le.VERDICT_FIRE, "the colour path gets a colour word"
    assert momentary is le.is_momentary(0.8, TUNING.energy_cutoff)
    assert transition_ms == le.transition_ms_for(0.8), \
        "its OWN transition, never the shape's form"
    assert pos + ramp_ms == 10_000, "and it still lands on the word"
    [row] = [r for r in fire_history.load_show_log(uri=URI)
             if r.get("key") == "lyric:shape"]
    detail = row["detail"]
    assert detail["result"] == le.RESULT_FELL_BACK
    assert detail["nothing_drew"] == why
    assert detail["colour"] == "jumped"
    assert (detail["set_id"], detail["set_name"]) == ("red", "Red")
    assert detail["shape"] == "heart", "and it says which shape it meant to draw"


def test_a_shape_only_word_with_nowhere_to_draw_does_nothing_and_says_so():
    """No colour set to fall back to: nothing happens, and the row says
    why — "the shape did nothing" has to be answerable from the record."""
    from spectra.services import fire_history
    rec = Rec(shape_result={"result": "no_class"})
    _sweep(_clock_engine(rec, [_hit(10_000, energy=0.8, sets=())]), rec)
    assert len(rec.shapes) == 1 and rec.words == []
    [row] = [r for r in fire_history.load_show_log(uri=URI)
             if r.get("key") == "lyric:shape"]
    assert row["detail"]["result"] == "no_class"
    assert row["detail"]["nothing_drew"] == "no_class"
    assert row["detail"]["colour"] is None


@pytest.mark.parametrize("record", [
    {"result": "held", "held_for": "phase", "reason": "lull"},
    {"result": "held", "held_for": "preview"},
    {"result": "held", "held_for": "house_mode", "reason": "mode 'Away'"},
    {"result": "applied", "word_shape": {"virtuals": 0}},
])
def test_a_hold_or_a_words_band_that_ran_never_falls_back(record):
    """The fallback is for "nothing in the room COULD draw", never for
    "something is deliberately holding the room" — a colour word is held by
    those same gates today, so falling back would walk through one. And a
    Words band that RAN (even with no effect wired yet, which is every
    Words band until wave 1) is the designed path: its own colour kinds are
    the colour path for a shape word."""
    rec = Rec(shape_result=record)
    _sweep(_clock_engine(rec, [_hit(10_000, energy=0.8, sets=("red",))]), rec)
    assert len(rec.shapes) == 1
    assert rec.words == [], "the colour hook was never asked"


def test_the_fallback_word_is_rebuilt_not_carried_over():
    """`colour_fallback` is pure and re-derives both colour numbers from the
    same two functions the colour branch uses. Carrying the shape's own
    `transition_ms` over would silently retune the fade
    (`moment_fade_ms` reads it)."""
    shape = _only(_plan([_hit(energy=0.8, sets=("red",))]))
    assert shape.verdict == le.VERDICT_SHAPE
    fallback = le.colour_fallback(shape, TUNING)
    assert fallback is not None
    assert fallback.verdict == le.VERDICT_FIRE
    assert fallback.transition_ms == le.transition_ms_for(0.8)
    assert fallback.transition_ms != shape.transition_ms
    assert (fallback.form_s, fallback.hold_s, fallback.release_s) == (0.0, 0.0, 0.0)
    assert fallback.shape_id is None, "it is a colour word now"
    assert fallback.hit is shape.hit, "the same word, though"
    assert le.colour_fallback(_only(_plan([_hit(sets=())])), TUNING) is None


# ═══ 6. the edges ═════════════════════════════════════════════════════════


def test_a_trigger_can_never_name_the_word_class():
    from pydantic import ValidationError

    from spectra.models.scene import (RESPONSE_CLASSES,
                                      TRIGGER_RESPONSE_CLASSES)
    from spectra.models.trigger import FireResponseAction, SpectraTrigger
    assert RESPONSE_CLASSES == ("flare", "charge", "lull", "drop", "word")
    assert TRIGGER_RESPONSE_CLASSES == ("flare", "charge", "lull", "drop")
    for cls in TRIGGER_RESPONSE_CLASSES:
        assert FireResponseAction(event_class=cls).event_class == cls
    with pytest.raises(ValidationError) as exc:
        FireResponseAction(event_class="word")
    assert "only a sung word fires it" in str(exc.value)
    # ... through the whole trigger, and through a stored row's own load.
    with pytest.raises(ValidationError):
        SpectraTrigger.model_validate(
            {"timestamp_ms": 1, "action": {"kind": "fire_response",
                                           "event_class": "word"}})
    # ... and the manual event injector leaves it out too.
    from spectra.api.engine import EVENT_CLASSES
    assert "word" not in EVENT_CLASSES and "update" in EVENT_CLASSES


def test_the_preview_ruler_puts_the_trigger_where_the_shape_completes():
    """The three marks (plan section 2.5): start = word − form, trigger =
    word, end = word + hold + release."""
    from spectra.services import flare_preview
    scene = _words_scene()
    kind = scene.flare_kinds[0]
    timeline = _run(flare_preview.build_timeline(scene, kind, 0.8))
    assert timeline["kind_type"] == "word_shape"
    form_s, hold_s, release_s = word_shape_timing(
        0.8, 0.0, RoomControlState(), [EFFECT])
    assert timeline["lead_ms"] == round(form_s * 1000), "the form IS the lead"
    assert timeline["word_shape"] == {
        "shape": "heart", "form_s": form_s, "hold_s": hold_s,
        "release_s": release_s}
    trigger = timeline["trigger_mark_s"]
    assert timeline["fire_at_s"] == pytest.approx(trigger - form_s), \
        "the write goes out a form before the mark"
    assert timeline["effect_animation_ms"] == pytest.approx(
        1000 * (form_s + hold_s + release_s))
    end_s = timeline["fire_at_s"] + timeline["effect_animation_ms"] / 1000.0
    assert end_s == pytest.approx(trigger + hold_s + release_s)


def test_the_words_section_ignores_a_per_kind_offset_and_says_so():
    """THE REVIEW'S FIX (3), 2026-11-16: `on_word_shape` fires its band
    atomically, so a kind's own `trigger_offset_ms` never moves the real
    fire. Stated three ways rather than left to be discovered — the save
    warns, the preview's ruler does not draw it, and the timing doc has
    the row."""
    from spectra.services import flare_preview, scene_store
    scene = _words_scene()
    scene.flare_kinds[0].trigger_offset_ms = -250
    [warning] = scene_store.scene_warnings(scene)
    assert "trigger_offset_ms -250" in warning
    assert "not applied" in warning
    # The ruler draws the mark where the shape really lands, NOT where the
    # offset would have put it (that would be the preview lying).
    timeline = _run(flare_preview.build_timeline(scene, scene.flare_kinds[0], 0.8))
    assert timeline["trigger_mark_s"] == timeline["animation_anchor_s"]
    # ... while an ordinary kind's offset still moves its mark, unchanged.
    other = _words_scene()
    other.flare_kinds = [FlareKind(
        name="Spin", type="momentary", trigger_offset_ms=-250,
        params={"spin": ParamTarget(mode="absolute", value=0.9)})]
    other.responses["word"] = ResponseSpec(bands=[FlareBand(
        intensity_min=0.0, intensity_max=1.0, kinds={"Spin": 1.0})])
    moved = _run(flare_preview.build_timeline(other, other.flare_kinds[0], 0.8))
    assert moved["trigger_mark_s"] > moved["animation_anchor_s"]


def test_the_preview_draws_the_shape_it_is_asked_for():
    from spectra.services import flare_preview
    scene = _words_scene()
    timeline = _run(flare_preview.build_timeline(
        scene, scene.flare_kinds[0], 0.5, shape="star"))
    assert timeline["word_shape"]["shape"] == "star"


def test_the_preview_writes_the_told_keys_when_an_effect_knows_shapes(
        shape_effects):
    from spectra.services import flare_preview
    scene = _words_scene()
    timeline = _run(flare_preview.build_timeline(scene, scene.flare_kinds[0], 0.5))
    [write] = [w for w in timeline["writes"] if wsk.SHAPE_KEY in w["params"]]
    assert write["params"][wsk.SHAPE_KEY] == "heart"
    assert write["at_s"] == 0.0


def test_sonic_can_create_the_kind_and_set_each_timing(tmp_path, monkeypatch):
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path)
    monkeypatch.setattr(scfg, "SCENES_FILE", tmp_path / "scenes.json")
    monkeypatch.setattr(scfg, "SCENE_AGENT_LOG_FILE", tmp_path / "agent.json")
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room.json")
    monkeypatch.setattr(scfg, "SETTINGS_LOG_FILE", tmp_path / "log.json")
    from spectra.services import room_controls, scene_console, scene_store
    from spectra.services import settings_console as sc
    scene = SceneV2(name="Sonic Shape Scene", devices=[SceneDeviceConfig(
        id="d1", target_kind="virtual", target=VID, effect_type=EFFECT)])
    scene_store.save(scene)
    out = _run(scene_console.apply_flare_kind(
        scene.id, name="Heart", type="word_shape"))
    assert out["status"] == "applied"
    saved = scene_store.get_by_id(scene.id)
    [kind] = saved.flare_kinds
    assert kind.type == "word_shape" and kind.params == {} and kind.gain == 1.0
    for key, value in (("word_shape_form_slow_s", 1.2),
                       ("word_shape_form_fast_s", 0.4),
                       ("word_shape_hold_min_s", 0.5),
                       ("word_shape_hold_max_s", 3.0),
                       ("word_shape_release_ratio", 2.0)):
        assert sc.SETTINGS_REGISTRY[key].help_topic == "word-shapes"
        applied = _run(sc.apply_change(key, value))
        assert applied["status"] == "applied"
        assert getattr(room_controls.load_room_controls(), key) == value
    # The same enum the MCP wrapper hand-copies.
    from spectra.services import settings_mcp_server
    assert "word_shape" in settings_mcp_server._FlareTypeEnum.__args__


def test_a_scene_with_a_words_section_round_trips_and_old_scenes_load(tmp_path,
                                                                     monkeypatch):
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "SCENES_FILE", tmp_path / "scenes.json")
    from spectra.services import scene_store
    scene = _words_scene(kinds={"Heart": 1.0, "Colour Jump": 0.5},
                         lanes={"Heart": "shape", "Colour Jump": "shape"})
    scene_store.save(scene)
    back = scene_store.get_by_id(scene.id)
    assert back is not None
    assert set(back.responses) == {"word"}
    [band] = back.responses["word"].bands
    assert band.kinds == {"Heart": 1.0, "Colour Jump": 0.5}
    assert band.kind_lanes == {"Heart": "shape", "Colour Jump": "shape"}
    assert json.loads(back.model_dump_json()) == json.loads(scene.model_dump_json())

    # A scenes file written before the Words section existed loads unchanged.
    old = {"id": "old-1", "name": "Legacy", "devices": [],
           "flare_kinds": [{"name": "k", "type": "momentary",
                            "params": {"spin": 0.5}}],
           "responses": {"flare": {"bands": [{"intensity_min": 0.0,
                                              "intensity_max": 1.0,
                                              "kinds": {"k": 1.0}}]}}}
    (tmp_path / "scenes.json").write_text(json.dumps({"old-1": old}),
                                          encoding="utf-8")
    loaded = scene_store.get_by_id("old-1")
    assert loaded is not None and set(loaded.responses) == {"flare"}
    assert "word" not in loaded.responses, "nothing is invented on load"
    assert scene_store.scene_warnings(loaded) == []


def test_the_six_told_keys_stay_out_of_the_effect_param_registry():
    """The keys ride ONLY the dedicated write (word_shape_keys' rule 1), so
    no band patch, editor surface or drift profile can reach them."""
    for effect in device_model.effect_types():
        params = set(device_model.effect_params(effect))
        assert not params & set(wsk.KEYS), effect
