"""WORD TEST MODE — one switch that makes every sung word fire (2026-11-17).

The Admiral, verbatim: "did we implement a system to 'test' where all word
flares (shape or color) fire, no matter the confidence? how do i turn that
on?" — and, on 2026-11-12, "an easy way to make all words fire regardless
of chance, a test mode". Where it lives and whether it expires, his own
answer: "Settings, no auto off".

`spectra/services/lyric_events.py`'s "WORD TEST MODE" section is the
binding statement. What this file proves, in his order:

  1. ON: every word wins, whatever its confidence — a colour word and a
     word shape alike, across every play number — and it is decided in
     the ONE place the roll lives (`chance_for`), not per feature.
  2. HIS EXPLICIT NO SURVIVES IT: a match pinned Never still never plays,
     on any play, with the switch on. (A DELETED match never reaches the
     roll at all — proven here by the resolver, so "test mode brought a
     deleted match back" cannot be true by construction.)
  3. EVERY OTHER RULE STANDS: the minimum gap, the phrase rule, the
     imprint window and the shape timings are untouched — the gap most of
     all, because "I turned test mode on and that word still didn't fire"
     is what the gap looks like from the outside.
  4. OFF: byte-identical to today, field for field, over many plays.
  5. NOTHING IS WRITTEN: his pins, his kept rolls and the show's own
     stored settings come out unchanged.
  6. IT PERSISTS ACROSS A RESTART (it is a stored room setting) and reaches
     the engine's very next plan rather than waiting out the replan window.
  7. THE READOUTS SAY SO: the Test Bed's per-word chance sentence, the
     preview payload and the roll payload.
  8. THE REGISTRY AGREES: Sonic can set it, bounds read off the model, and
     the Help topic the Settings page links is a real one.

No live access, no room: pure planner calls, a fake-fed TriggerEngine, and
tmp_path stores.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import pytest

from spectra.models.lyric_labels import LyricEventSettings
from spectra.services import lyric_events as le
from spectra.services import room_controls as rc
from spectra.services import settings_console as sc
from spectra.services.room_controls import RoomControlState

URI = "spotify:track:wordtestmode"
TUNING = LyricEventSettings()


@pytest.fixture(autouse=True)
def _isolated_room_controls(tmp_path, monkeypatch):
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")


def _hit(ms=10_000, *, line=0, strength=0.9, his=False, sets=("red",), energy=0.3,
         first=None, phrase="red", shape=None, pin=None, match_id="m1"):
    first = first if first is not None else ms // 100
    return le.WordHit(
        key=f"{first}-{first}", first_word=first, last_word=first, phrase=phrase,
        label=phrase, line=line, ms=float(ms), end_ms=float(ms + 400),
        emphasis=0.4, strength=strength, his=his, set_ids=tuple(sets),
        set_names=tuple(s.title() for s in sets), energy=energy,
        shape_id=shape, shape_name=None if shape is None else shape.title(),
        pin=pin, match_id=match_id)


def _flare(ms, eid="f"):
    return le.EventMoment(eid, le.KIND_FLARE, ms, "flare")


def _drop(ms, eid="d"):
    return le.EventMoment(eid, le.KIND_DROP, ms, "drop")


def _timing():
    """A fixed form/hold/release, so a shape word's timing can be compared
    with and without the switch without the room's own numbers moving."""
    return lambda _energy, phrase_ms: (0.7, min(2.0, max(0.8, phrase_ms / 1000.0)), 1.05)


# ═══ 1. ON: every word wins, whatever its confidence ═══════════════════════


@pytest.mark.parametrize("strength", [0.0, 0.01, 0.03, 0.2, 0.5, 0.97])
def test_on_every_word_wins_whatever_its_confidence(strength):
    """The clarity bar for the whole row: a 3% guess that plays on 3 plays
    in 100 plays on ALL of them, and the chance it reports is 1.0."""
    hit = _hit(strength=strength)
    for seed in range(250):
        [rolled] = le.roll_hits([hit], le.Play(URI, seed), True)
        assert rolled.won is True, f"a {strength} word sat out play {seed}"
        assert rolled.chance == 1.0
        assert rolled.why_not is None


def test_on_the_chance_is_forced_in_the_one_place_the_roll_lives():
    """`chance_for` is the whole mapping (its own docstring), so test mode
    is one branch there and NOT a second switch anywhere downstream."""
    assert le.chance_for(_hit(strength=0.03)) == pytest.approx(0.03)
    assert le.chance_for(_hit(strength=0.03), True) == 1.0
    assert le.chance_for(_hit(strength=0.0, his=False), True) == 1.0
    # ... and plan_play's own parameter is the only way it gets there.
    [off] = le.plan_play([_hit(strength=0.0)], [], TUNING, le.Play(URI, 7))
    [on] = le.plan_play([_hit(strength=0.0)], [], TUNING, le.Play(URI, 7), test_mode=True)
    assert off.why == le.WHY_SAT_OUT and on.verdict == le.VERDICT_FIRE


def test_on_a_word_shape_fires_too_not_just_a_colour():
    """"all word flares (shape or color)" — his own words. A low-confidence
    word that reaches a SHAPE draws it on every play, and its form/hold/
    release are the room's own, unchanged by the switch."""
    hit = _hit(strength=0.02, sets=(), shape="heart", phrase="love")
    for seed in range(120):
        [action] = le.plan_play([hit], [], TUNING, le.Play(URI, seed),
                                shape_timing=_timing(), test_mode=True)
        assert action.verdict == le.VERDICT_SHAPE, f"play {seed} skipped the shape"
    [on] = le.plan_play([hit], [], TUNING, le.Play(URI, 3),
                        shape_timing=_timing(), test_mode=True)
    assert (on.form_s, on.hold_s, on.release_s) == (0.7, 0.8, 1.05), \
        "the shape timings are not test mode's business"


def test_on_a_word_that_reaches_nothing_still_does_nothing():
    """Test mode forces the ROLL, not an outcome: a match with no colour set
    and no shape has nothing to do, and saying "every word fires" must not
    invent something for it."""
    nothing_to_do = replace(_hit(strength=0.1, sets=()), why_not=le.WHY_NO_COLOUR)
    [action] = le.plan_play([nothing_to_do], [], TUNING, le.Play(URI, 5),
                            test_mode=True)
    assert action.verdict == le.VERDICT_NOTHING and action.why == le.WHY_NO_COLOUR


# ═══ 2. his explicit no survives it ════════════════════════════════════════


def test_on_a_never_pin_still_never_plays():
    """"Test mode overrides chance only, not his explicit no." The pin is
    asked BEFORE the switch in `chance_for`, so this holds on every play of
    every song."""
    never = _hit(strength=1.0, his=True, pin=le.PIN_NEVER)
    assert le.chance_for(never, True) == 0.0
    for seed in range(400):
        [rolled] = le.roll_hits([never], le.Play(URI, seed), True)
        assert rolled.won is False and rolled.why_not == le.WHY_SAT_OUT
        [action] = le.plan_play([never], [], TUNING, le.Play(URI, seed), test_mode=True)
        assert action.verdict == le.VERDICT_NOTHING and action.why == le.WHY_SAT_OUT


def test_on_a_never_pin_frees_its_line_for_the_next_word_exactly_as_today():
    """The Never word sitting out is the same sitting-out as any other, so
    a weaker word on the same line still gets the line."""
    never = _hit(10_000, strength=0.9, line=0, first=1, pin=le.PIN_NEVER, match_id="a")
    other = _hit(10_100, strength=0.1, line=0, first=2, match_id="b")
    out = {a.hit.first_word: a for a in
           le.plan_play([never, other], [], TUNING, le.Play(URI, 11), test_mode=True)}
    assert out[1].why == le.WHY_SAT_OUT
    assert out[2].verdict == le.VERDICT_FIRE


def test_on_a_deleted_match_is_still_deleted():
    """A deleted match never becomes a WordHit, so there is nothing for the
    switch to override — proven through the REAL resolver rather than
    asserted, since "test mode brought back a match I deleted" is the one
    failure here that would touch his own corrections."""
    from spectra.models.lyric_labels import (ClaudeGuess, DeletedGuess, Reading,
                                             SongMatches)
    from spectra.services import lyric_matches, sung_labels

    target = sung_labels.Target(kind="color_set", id="red1", name="Blood Red",
                                swatch="#c81e1e")
    catalogue = sung_labels.Catalogue(targets={("color_set", "red1"): target},
                                      labels={"red": "red"},
                                      owners={"red": (target,)})
    words = [_scored(0, "red", 1000.0, 1300.0)]
    guess = ClaudeGuess(first_word=0, last_word=0, phrase="red", norm=["red"],
                        label="red", confidence=0.03)
    reading = Reading(at_ms=1, model="m", backend="b", labels_hash="l",
                      words_hash="w", matches=[guess])

    kept = SongMatches(uri=URI, reading=reading)
    alive, _ = lyric_matches.resolve(kept, words, catalogue)
    assert [m["label"] for m in alive] == ["red"], "the 3% guess is there to lose"

    gone = SongMatches(uri=URI, reading=reading,
                       deleted=[DeletedGuess(first_word=0, last_word=0,
                                             norm=["red"], label="red")])
    after, _ = lyric_matches.resolve(gone, words, catalogue)
    assert after == [], "a deleted guess is gone before any roll happens"

    # ... and the roll, test mode and all, can only ever act on what the
    # resolver handed it.
    def energy_at(_ms):
        return 0.3

    def reach(match):
        return [(t["id"], t["name"], t.get("swatch")) for t in match.get("targets", ())]

    hits = le.hits_from_matches(after, [w.line for w in words], energy_at, reach)
    assert hits == []
    assert le.roll_hits(hits, le.Play(URI, 1), True) == []


def _scored(index, word, ms, end_ms, line=0, score=0.9):
    from spectra.services.lyrics_emphasis import ScoredWord, WordFeatures
    return ScoredWord(index=index, word=word, norm=word, line=line, ms=ms,
                      end_ms=end_ms, score=score,
                      features=WordFeatures(loud=0.5, held=0.5, beat=0.5,
                                            line_end=0.0, hook=0.0))


# ═══ 3. every other rule stands ════════════════════════════════════════════


def test_on_the_eight_second_minimum_gap_still_holds():
    """The rule he is most likely to read as a bug once every word fires.
    Two matched words 2 s apart both win the roll; the second is still
    blocked, and names what blocked it."""
    first = _hit(10_000, line=0, first=1, strength=0.05, match_id="a")
    second = _hit(12_000, line=1, first=2, strength=0.05, phrase="blue", match_id="b")
    out = {a.hit.first_word: a for a in
           le.plan_play([first, second], [], TUNING, le.Play(URI, 42), test_mode=True)}
    assert out[1].verdict == le.VERDICT_FIRE
    assert out[2].verdict == le.VERDICT_NOTHING and out[2].why == le.WHY_TOO_SOON
    assert out[2].blocked_by == "red"
    # ... and outside the gap both act, so the gap is the only thing
    # stopping it.
    far = _hit(30_000, line=1, first=3, strength=0.05, phrase="blue", match_id="b")
    out = {a.hit.first_word: a for a in
           le.plan_play([first, far], [], TUNING, le.Play(URI, 42), test_mode=True)}
    assert out[1].verdict == out[3].verdict == le.VERDICT_FIRE


def test_on_a_shape_word_takes_the_gap_from_a_colour_word_as_before():
    shape = _hit(10_000, line=0, first=1, strength=0.02, sets=(), shape="heart",
                 phrase="love", match_id="a")
    colour = _hit(12_000, line=1, first=2, strength=0.02, match_id="b")
    out = {a.hit.first_word: a for a in
           le.plan_play([shape, colour], [], TUNING, le.Play(URI, 9),
                        shape_timing=_timing(), test_mode=True)}
    assert out[1].verdict == le.VERDICT_SHAPE
    assert out[2].why == le.WHY_TOO_SOON and out[2].blocked_by == "love"


def test_on_the_phrase_rule_and_the_imprint_window_are_unchanged():
    strong = _hit(10_000, line=0, first=1, strength=0.4, match_id="a")
    weak = _hit(10_100, line=0, first=2, strength=0.1, phrase="blue", match_id="b")
    out = {a.hit.first_word: a for a in
           le.plan_play([strong, weak], [_flare(10_050, "f1")], TUNING,
                        le.Play(URI, 13), test_mode=True)}
    assert out[1].verdict == le.VERDICT_IMPRINT and out[1].event.id == "f1"
    assert out[2].why in (le.WHY_PHRASE, le.WHY_LOST)


def test_on_a_drop_still_wins_over_a_shape():
    """His Q5 A is a planner rule, downstream of the roll, so the switch
    cannot change it."""
    hit = _hit(10_000, strength=0.01, sets=("red",), shape="heart", phrase="love")
    [action] = le.plan_play([hit], [_drop(10_500, "d1")], TUNING, le.Play(URI, 4),
                            shape_timing=_timing(), test_mode=True)
    assert action.verdict == le.VERDICT_IMPRINT and action.shape_skipped == le.WHY_DROP_WINS


# ═══ 4. OFF: byte-identical to today ══════════════════════════════════════


def _comparable(action) -> dict:
    return {
        "key": action.hit.key, "verdict": action.verdict, "why": action.why,
        "chance": action.hit.chance, "draw": action.hit.draw, "won": action.hit.won,
        "why_not": action.hit.why_not, "pin": action.hit.pin,
        "event": None if action.event is None else action.event.id,
        "blocked_by": action.blocked_by, "energy": action.energy,
        "momentary": action.momentary, "transition_ms": action.transition_ms,
        "form_s": action.form_s, "hold_s": action.hold_s, "release_s": action.release_s,
        "shape_id": action.shape_id, "shape_skipped": action.shape_skipped,
    }


def test_off_is_byte_identical_to_a_plan_that_never_heard_of_the_switch():
    """`test_mode=False` must be the SAME CALL as before this row: field for
    field, play after play, for every kind of word on the page."""
    hits = [
        _hit(10_000, line=0, first=1, strength=0.97, match_id="a"),
        _hit(14_000, line=1, first=2, strength=0.03, phrase="blue", match_id="b"),
        _hit(22_000, line=2, first=3, strength=0.5, his=True, phrase="gold", match_id="c"),
        _hit(31_000, line=3, first=4, strength=0.4, pin=le.PIN_ALWAYS,
             phrase="rose", match_id="d"),
        _hit(40_000, line=4, first=5, strength=0.9, pin=le.PIN_NEVER,
             phrase="jade", match_id="e"),
        _hit(50_000, line=5, first=6, strength=0.2, sets=(), shape="heart",
             phrase="love", match_id="f"),
    ]
    events = [_flare(14_200, "f1"), _drop(31_400, "d1")]
    for seed in range(60):
        play = le.Play(URI, seed)
        today = le.plan_words(le.roll_hits(hits, play), events, TUNING,
                              shape_timing=_timing())
        off = le.plan_play(hits, events, TUNING, play, shape_timing=_timing(),
                           test_mode=False)
        assert [_comparable(a) for a in today] == [_comparable(a) for a in off]
        # ... including every byte of the payload the pages read.
        assert ([le.action_payload(a) for a in today]
                == [le.action_payload(a) for a in off])


def test_off_the_default_is_off_everywhere_it_is_read():
    assert RoomControlState().word_test_mode is False
    assert rc.load_room_controls().word_test_mode is False, "no store = off"
    assert le.chance_for(_hit(strength=0.3)) == pytest.approx(0.3), \
        "the default argument is off, so an old caller is unchanged"


def test_off_a_plan_rolled_under_test_mode_comes_straight_back():
    """The draw is still taken under test mode (roll_hits' docstring), so
    turning the switch off restores the very same winners without
    re-rolling: the same seed, the same words."""
    hits = [_hit(10_000 + i * 9_000, line=i, first=i + 1, strength=0.5,
                 phrase=f"w{i}", match_id=f"m{i}") for i in range(6)]
    play = le.Play(URI, 777)
    on = le.roll_hits(hits, play, True)
    off = le.roll_hits(hits, play, False)
    assert all(h.won for h in on)
    assert [h.draw for h in on] == [h.draw for h in off], \
        "test mode does not touch the draw, only what it is compared against"


# ═══ 5. nothing is written ════════════════════════════════════════════════


def test_nothing_about_a_song_or_his_pins_is_written_while_the_mode_runs(tmp_path,
                                                                         monkeypatch):
    """"His saved pins and 'Keep this roll' seeds are untouched, and nothing
    is written to song data." Proven by byte-comparing both stores across a
    full set of planning calls with the switch on."""
    from spectra import config as scfg
    events_file = tmp_path / "lyric_events.json"
    matches_dir = tmp_path / "matches"
    matches_dir.mkdir()
    monkeypatch.setattr(scfg, "LYRIC_EVENTS_FILE", events_file)
    if hasattr(scfg, "LYRIC_MATCHES_DIR"):
        monkeypatch.setattr(scfg, "LYRIC_MATCHES_DIR", matches_dir)
    events_file.write_text(json.dumps({
        "schema_version": 1,
        "settings": {"energy_cutoff": 0.5, "min_gap_s": 8.0, "imprint_window_s": 2.0},
        "shows": {URI: {"enabled": True, "changed_ms": 1, "kept_seed": 4242,
                        "kept_ms": 2}},
    }), encoding="utf-8")
    before = events_file.read_bytes()
    hits = [_hit(strength=0.1, pin=le.PIN_NEVER, match_id="a"),
            _hit(30_000, line=1, first=2, strength=0.1, match_id="b")]
    for seed in range(40):
        le.plan_play(hits, [], TUNING, le.Play(URI, seed), test_mode=True)
    assert events_file.read_bytes() == before, "the switch reads; it never writes"
    assert sorted(p.name for p in matches_dir.iterdir()) == []


# ═══ 6. it persists, and it reaches the next plan ═════════════════════════


def test_it_persists_across_a_restart():
    """An ordinary stored room setting: saved, then read back by a process
    that has no memory of this one (a fresh `load_room_controls`, which
    holds no cache)."""
    rc.save_room_controls(replace_state(word_test_mode=True))
    assert rc.load_room_controls().word_test_mode is True
    raw = json.loads(rc.config.ROOM_CONTROLS_FILE.read_text(encoding="utf-8"))
    assert raw["word_test_mode"] is True, "it is in the file, not only in memory"
    rc.save_room_controls(replace_state(word_test_mode=False))
    assert rc.load_room_controls().word_test_mode is False


def replace_state(**over) -> RoomControlState:
    return RoomControlState(**{**rc.load_room_controls().model_dump(), **over})


def test_the_engine_reads_the_room_switch_by_default_and_replans_on_a_flip():
    """The `drop_testing` shape: read fresh each replan AND folded into the
    replan memo key, so a flip reaches the very next plan instead of
    waiting out LYRIC_REPLAN_S."""
    from spectra.services.trigger_engine import TriggerEngine
    eng = TriggerEngine()
    assert eng._lyric_test_mode() is False
    rc.save_room_controls(replace_state(word_test_mode=True))
    assert eng._lyric_test_mode() is True, "no cache between the store and the plan"

    flips = iter([False, True])
    eng2 = TriggerEngine(lyric_test_mode=lambda: next(flips))
    hits = [_hit(strength=0.05)]
    words = le.SongWords(URI, "ok", None, tuple(hits))
    plans = []
    for _ in range(2):
        eng2._lyric_words, eng2._lyric_words_at = words, 0.0
        test_mode = eng2._lyric_test_mode()
        plans.append(le.plan_play(hits, [], TUNING, le.Play(URI, 5),
                                  test_mode=test_mode))
    assert plans[0][0].why == le.WHY_SAT_OUT
    assert plans[1][0].verdict == le.VERDICT_FIRE


def test_the_replan_key_carries_the_switch():
    """The memo key `_refresh_lyric_plan` builds must contain the flag, or a
    flip sits unapplied for up to LYRIC_REPLAN_S while the memo still
    matches. Read off that one method's source, so it cannot pass on a
    coincidence elsewhere in the module."""
    import inspect
    from spectra.services.trigger_engine import TriggerEngine
    src = inspect.getsource(TriggerEngine._refresh_lyric_plan)
    assert "test_mode = bool(self._lyric_test_mode())" in src
    assert "tuning.imprint_window_s, test_mode)" in src
    assert "test_mode=test_mode" in src


# ═══ 7. the readouts say so ═══════════════════════════════════════════════


def test_the_test_bed_per_word_chance_reflects_the_mode():
    """"Plays on about 3% of plays" while every word is firing would be a
    lie; so would hiding what the real confidence is."""
    [on] = le.plan_play([_hit(strength=0.03)], [], TUNING, le.Play(URI, 1),
                        test_mode=True)
    payload = le.action_payload(on)
    assert payload["chance"] == 1.0 and payload["won"] is True
    assert payload["test_mode"] is True
    assert "Word test mode is on" in payload["chance_words"]
    assert "3%" in payload["chance_words"], "and it still says what it would be"

    [never] = le.plan_play([_hit(strength=0.9, pin=le.PIN_NEVER)], [], TUNING,
                           le.Play(URI, 1), test_mode=True)
    assert "does not override" in le.action_payload(never)["chance_words"]

    [off] = le.plan_play([_hit(strength=0.03)], [], TUNING, le.Play(URI, 1))
    assert le.action_payload(off)["test_mode"] is False
    assert "Word test mode" not in le.action_payload(off)["chance_words"]


def test_the_sampled_play_readout_reflects_the_mode():
    """The Test Bed's own "n of m play" line, and the flag beside it."""
    hits = [_hit(10_000 + i * 9_000, line=i, first=i + 1, strength=0.02,
                 phrase=f"w{i}", match_id=f"m{i}") for i in range(5)]
    play = le.Play(URI, 31337, source=le.ROLL_SAMPLE)
    preview = le.Preview(
        enabled=True, words=le.SongWords(URI, "ok", None, tuple(hits)),
        actions=le.plan_play(hits, [], TUNING, play, test_mode=True),
        play=play, test_mode=True)
    roll = le.roll_payload(preview)
    assert roll["n_won"] == roll["n_words"] == 5 and roll["test_mode"] is True
    assert le.preview_payload(preview, TUNING)["test_mode"] is True

    off_play = le.Play(URI, 31337, source=le.ROLL_SAMPLE)
    off = le.Preview(
        enabled=True, words=le.SongWords(URI, "ok", None, tuple(hits)),
        actions=le.plan_play(hits, [], TUNING, off_play), play=off_play)
    assert le.roll_payload(off)["n_won"] < 5
    assert le.roll_payload(off)["test_mode"] is False


# ═══ 8. the registry agrees ═══════════════════════════════════════════════


def test_sonic_can_set_it_and_the_registry_reads_the_model():
    spec = sc.SETTINGS_REGISTRY["word_test_mode"]
    assert spec.kind == "bool"
    assert spec.help_topic == "word-test-mode"
    for phrase in ("every", "Never", "minimum gap", "auto-off"):
        assert phrase.lower() in spec.description.lower(), phrase

    applied = asyncio.run(sc.apply_change("word_test_mode", True))
    assert applied["status"] == "applied" and applied["new_value"] is True
    assert rc.load_room_controls().word_test_mode is True
    undone = asyncio.run(sc.undo_last_change())
    assert undone["new_value"] is False
    assert rc.load_room_controls().word_test_mode is False


def test_the_help_topic_the_settings_page_links_is_a_real_one():
    """A `help_topic` naming nothing would render a dead link — the orphan
    rule in reverse."""
    from pathlib import Path
    content = Path("spectra/web/src/help/helpContent.ts").read_text(encoding="utf-8")
    assert "id: 'word-test-mode'" in content
    assert "word_test_mode" in content, "the key is searchable from Help"
