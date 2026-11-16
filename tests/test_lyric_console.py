"""Sonic's lyrics domain (spectra/services/lyric_console.py): the sung
labels, Claude's colour meanings, a song's word matches and the automatic
reader's own switch and weak-match threshold (PR #499's own Sonic coverage
follow-up), plus word colours and imprints' per-show switch, tuning and
preview (PR #504's own follow-up), and the SHAPE target kind (Word Shapes
row W0.2). Reached through
spectra.services.settings_agent's real dispatch boundary, same convention
as tests/test_drop_console.py; no live process, no light, Claude always a
stub. preview_lyric_events is the one op that goes over HTTP (the module
docstring's own reasoning) — its own tests wire `lyric_console.http` to a
real TestClient over the real router, never a socket."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import textwrap

import pytest

from spectra import config as scfg
from spectra.services import analysis_reader, claude_text, lyric_console, sung_labels
from tests.lyric_song_world import STEM, URI, color_sets, isolate, song, words as make_words


@pytest.fixture(autouse=True)
def _world(tmp_path, monkeypatch):
    isolate(tmp_path, monkeypatch, scfg, analysis_reader)
    color_sets(scfg)
    song(scfg)
    monkeypatch.setattr(lyric_console, "_PENDING", {})
    clock = [1000.0]
    monkeypatch.setattr(lyric_console, "_clock", lambda: clock[0])
    return clock


def _run(name, /, **kw):
    from spectra.services import settings_agent as sa
    return asyncio.run(sa._dispatch(name, kw))


def _stub(rows):
    async def ask(*, system, user, schema, purpose):
        return claude_text.ClaudeReply({"matches": rows}, "test-model", "api")
    return ask


# ── discoverability ──────────────────────────────────────────────────────

def test_every_lyric_op_is_in_the_merged_dispatch_table():
    from spectra.services import settings_agent as sa
    assert set(lyric_console.OPERATIONS) <= set(sa.ALL_OPERATIONS)
    out = _run("list_operations", domain="lyrics")
    assert {o["name"] for o in out["operations"]} == set(lyric_console.OPERATIONS)


# ── reading and changing sung labels ────────────────────────────────────

def test_list_sung_label_targets_lists_colour_sets_and_effects():
    out = _run("list_sung_label_targets")
    names = {t["name"] for t in out["targets"]}
    assert "Blood Red" in names
    assert "Fish" in names                 # a registered effect
    assert "Heart" in names                # a shape the show can draw


def test_list_can_be_narrowed_to_one_kind():
    out = _run("list_sung_label_targets", kind="effect")
    assert all(t["kind"] == "effect" for t in out["targets"])
    assert "Blood Red" not in {t["name"] for t in out["targets"]}


def test_list_can_be_narrowed_to_the_shapes():
    out = _run("list_sung_label_targets", kind="shape")
    assert [(t["kind"], t["name"]) for t in out["targets"]] == [
        ("shape", "Heart"), ("shape", "Star"), ("shape", "Diamond")]
    assert [t["n_labels"] for t in out["targets"]] == [
        len(words) for _name, words in sung_labels.shape_library().values()]


def test_an_unknown_kind_names_all_three():
    out = _run("list_sung_label_targets", kind="palette")
    assert out["status"] == "rejected"
    assert out["reason"] == "kind must be color_set, effect or shape"


def test_get_sung_labels_resolves_by_exact_name():
    out = _run("get_sung_labels", kind="color_set", name="Blood Red")
    assert out["name"] == "Blood Red"
    assert any(c["text"] == "red" for c in out["labels"])
    assert "meanings" in out and "has_colours" in out


def test_get_sung_labels_resolves_a_dropped_v2_style_name_too():
    # the resolver's close-name tier, proven on an effect whose real name
    # differs only by case/whitespace from what was asked
    out = _run("get_sung_labels", kind="effect", name="fish")
    assert out["name"] == "Fish"


def test_get_sung_labels_refuses_an_unknown_name_naming_candidates():
    out = _run("get_sung_labels", kind="color_set", name="Not A Real Set At All")
    assert out["status"] == "rejected"
    assert "known_names" in out or "close_matches" in out


def test_edit_sung_label_adds_and_removes_a_word():
    out = _run("edit_sung_label", kind="color_set", name="Blood Red",
               list="labels", op="add", text="passion")
    assert out["status"] == "applied"
    row = _run("get_sung_labels", kind="color_set", name="Blood Red")
    assert any(c["text"] == "passion" and c["source"] == "his" for c in row["labels"])

    out2 = _run("edit_sung_label", kind="color_set", name="Blood Red",
               list="labels", op="remove", text="passion")
    assert out2["status"] == "applied"
    row2 = _run("get_sung_labels", kind="color_set", name="Blood Red")
    assert not any(c["text"] == "passion" for c in row2["labels"])


def test_edit_sung_label_can_touch_a_meaning_kind():
    out = _run("edit_sung_label", kind="color_set", name="Blood Red",
               list="moods", op="add", text="rage")
    assert out["status"] == "applied"
    row = _run("get_sung_labels", kind="color_set", name="Blood Red")
    assert any(c["text"] == "rage" for c in row["meanings"]["moods"])


def test_get_and_edit_reach_a_shapes_labels():
    """Word Shapes row W0.2: the third kind, resolved by name like an effect."""
    row = _run("get_sung_labels", kind="shape", name="heart")
    assert row["kind"] == "shape" and row["name"] == "Heart"
    assert any(c["text"] == "love" and c["source"] == "seed" for c in row["labels"])
    assert "meanings" not in row                    # a shape has labels only

    out = _run("edit_sung_label", kind="shape", name="Heart", list="labels",
               op="add", text="sweetheart")
    assert out["status"] == "applied"
    assert "sweetheart" in out["summary"] and "Heart" in out["summary"]
    again = _run("get_sung_labels", kind="shape", name="Heart")
    assert any(c["text"] == "sweetheart" and c["source"] == "his" for c in again["labels"])

    off = _run("edit_sung_label", kind="shape", name="Heart", list="labels",
               op="remove", text="kiss")
    assert off["status"] == "applied"
    assert "kiss" not in {c["text"] for c in
                          _run("get_sung_labels", kind="shape", name="Heart")["labels"]}


def test_a_shape_refuses_a_meaning_kind():
    out = _run("edit_sung_label", kind="shape", name="Heart", list="things",
               op="add", text="valentine")
    assert out["status"] == "rejected"


def test_an_unknown_shape_name_is_refused_without_writing():
    before = scfg.SUNG_LABELS_FILE.exists() and scfg.SUNG_LABELS_FILE.read_text()
    out = _run("edit_sung_label", kind="shape", name="Octagon", list="labels",
               op="add", text="stop")
    assert out["status"] == "rejected"
    assert "known_names" in out or "close_matches" in out
    after = scfg.SUNG_LABELS_FILE.exists() and scfg.SUNG_LABELS_FILE.read_text()
    assert before == after


def test_he_can_match_a_phrase_to_a_shape_by_name():
    out = _run("add_lyric_match", target_kind="shape", target_name="Heart",
               phrase="know", song=STEM)
    assert out["status"] == "applied" and "Heart" in out["summary"]
    rows = _run("get_lyric_matches", song=STEM)["matches"]
    [his] = [m for m in rows if m["source"] == "his"]
    assert [(t["kind"], t["id"]) for t in his["targets"]] == [("shape", "heart")]


def test_an_effect_refuses_a_meaning_kind():
    out = _run("edit_sung_label", kind="effect", name="Fish",
               list="things", op="add", text="shark")
    assert out["status"] == "rejected"


def test_edit_sung_label_refuses_an_unknown_target_without_writing():
    before = scfg.SUNG_LABELS_FILE.exists() and scfg.SUNG_LABELS_FILE.read_text()
    out = _run("edit_sung_label", kind="color_set", name="Nothing Like This",
               list="labels", op="add", text="x")
    assert out["status"] == "rejected"
    after = scfg.SUNG_LABELS_FILE.exists() and scfg.SUNG_LABELS_FILE.read_text()
    assert before == after


# ── the auto-read switch (there is no weak-match threshold any more) ───

def test_get_lyric_reading_settings_reads_the_defaults():
    out = _run("get_lyric_reading_settings")
    assert out["auto_read"] is False
    assert "weak_match_threshold" not in out, "every guess is kept: its confidence is its chance"


def test_turning_auto_read_on_needs_his_yes_first():
    first = _run("set_lyric_reading_settings", auto_read=True)
    assert first["status"] == "needs_confirmation"
    assert sung_labels.auto_read_enabled() is False     # nothing happened yet

    wrong = _run("set_lyric_reading_settings", auto_read=True, confirm_id="not-a-real-id")
    assert wrong["status"] == "rejected"
    assert sung_labels.auto_read_enabled() is False

    second = _run("set_lyric_reading_settings", auto_read=True, confirm_id=first["confirm_id"])
    assert second["status"] == "applied"
    assert sung_labels.auto_read_enabled() is True


def test_a_confirm_id_is_single_use():
    first = _run("set_lyric_reading_settings", auto_read=True)
    _run("set_lyric_reading_settings", auto_read=True, confirm_id=first["confirm_id"])
    sung_labels.set_auto_read(False)        # back off, no confirm needed for that direction
    replay = _run("set_lyric_reading_settings", auto_read=True, confirm_id=first["confirm_id"])
    assert replay["status"] == "rejected"
    assert sung_labels.auto_read_enabled() is False


def test_turning_auto_read_off_applies_at_once_no_confirm():
    sung_labels.set_auto_read(True)
    out = _run("set_lyric_reading_settings", auto_read=False)
    assert out["status"] == "applied"
    assert sung_labels.auto_read_enabled() is False


def test_the_reading_settings_op_no_longer_takes_a_threshold():
    schema = lyric_console.OPERATIONS["set_lyric_reading_settings"].input_schema
    assert set(schema["properties"]) == {"auto_read", "confirm_id"}


def test_naming_nothing_to_change_is_refused():
    out = _run("set_lyric_reading_settings")
    assert out["status"] == "rejected"


# ── drafting colour meanings — always a Claude spend, always asks first ──

def test_draft_colour_meanings_always_asks_first(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(scfg, "settings_agent_backend", lambda: "api")
    calls = []

    async def ask(*, system, user, schema, purpose):
        calls.append(purpose)
        return claude_text.ClaudeReply(
            {"sets": [{"code": "c0", "things": ["volcano"], "moods": [], "places": []}]},
            "test-model", "api")
    monkeypatch.setattr(claude_text, "ask_json", ask)

    first = _run("draft_colour_meanings", names=["Blood Red"])
    assert first["status"] == "needs_confirmation"
    assert calls == []                                  # nothing asked Claude yet

    second = _run("draft_colour_meanings", names=["Blood Red"], confirm_id=first["confirm_id"])
    assert second["status"] == "applied" and second["drafted"] == 1
    assert calls == ["colour-meanings"]
    row = _run("get_sung_labels", kind="color_set", name="Blood Red")
    assert any(c["text"] == "volcano" for c in row["meanings"]["things"])


def test_draft_colour_meanings_refuses_without_asking_claude_when_unavailable(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = _run("draft_colour_meanings", names=["Blood Red"])
    assert out["status"] == "rejected"


def test_draft_colour_meanings_refuses_too_many_names():
    out = _run("draft_colour_meanings", names=[f"x{i}" for i in range(11)])
    assert out["status"] == "rejected"


def test_draft_colour_meanings_refuses_an_unknown_colour_set_before_asking(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(scfg, "settings_agent_backend", lambda: "api")
    out = _run("draft_colour_meanings", names=["Not A Real Colour Set"])
    assert out["status"] == "rejected"


# ── a song's word matches ────────────────────────────────────────────────

def test_get_lyric_matches_resolves_the_song_by_title():
    out = _run("get_lyric_matches", song=STEM)
    assert out["song"] == STEM
    assert out["state"] == "none"


def test_get_lyric_matches_defaults_to_whatever_is_playing(monkeypatch):
    from spectra.services import show_arms
    monkeypatch.setattr(show_arms, "current_uri", lambda: URI)
    out = _run("get_lyric_matches")
    assert out["uri"] == URI


def test_no_song_playing_and_none_named_is_refused(monkeypatch):
    from spectra.services import show_arms
    monkeypatch.setattr(show_arms, "current_uri", lambda: None)
    out = _run("get_lyric_matches")
    assert out["status"] == "rejected"


def test_add_lyric_match_finds_the_phrase_and_matches_it():
    out = _run("add_lyric_match", target_kind="color_set", target_name="Blood Red",
               phrase="red light", song=STEM)
    assert out["status"] == "applied"
    matches = _run("get_lyric_matches", song=STEM)
    his = [m for m in matches["matches"] if m["source"] == "his"]
    assert his and his[0]["phrase"] == "red light"


def test_add_lyric_match_names_how_many_times_a_repeated_phrase_is_sung():
    out = _run("add_lyric_match", target_kind="effect", target_name="Fish",
               phrase="the red light", song=STEM, occurrence=5)
    assert out["status"] == "rejected"
    assert "2" in out["reason"] or "time" in out["reason"]


def test_add_lyric_match_refuses_a_phrase_that_is_not_sung():
    out = _run("add_lyric_match", target_kind="effect", target_name="Fish",
               phrase="nonexistentwordzzz", song=STEM)
    assert out["status"] == "rejected"


def test_delete_lyric_match_takes_his_own_match_off():
    _run("add_lyric_match", target_kind="effect", target_name="Fish",
        phrase="red light", song=STEM)
    out = _run("delete_lyric_match", phrase="red light", song=STEM)
    assert out["status"] == "applied"
    matches = _run("get_lyric_matches", song=STEM)
    assert matches["matches"] == []


def test_delete_lyric_match_disambiguates_by_label():
    _run("add_lyric_match", target_kind="effect", target_name="Fish",
        phrase="red light", song=STEM)
    _run("add_lyric_match", target_kind="color_set", target_name="Blood Red",
        phrase="red light", song=STEM)
    ambiguous = _run("delete_lyric_match", phrase="red light", song=STEM)
    assert ambiguous["status"] == "rejected"

    narrowed = _run("delete_lyric_match", phrase="red light", song=STEM, label="Fish")
    assert narrowed["status"] == "applied"
    remaining = _run("get_lyric_matches", song=STEM)
    assert len(remaining["matches"]) == 1


def test_delete_lyric_match_refuses_a_phrase_with_no_match():
    out = _run("delete_lyric_match", phrase="red light", song=STEM)
    assert out["status"] == "rejected"


def test_restore_lyric_matches_brings_back_a_deleted_claude_guess():
    # "azul" sings once in the song world's lines (unlike "red", sung
    # twice, which would make the delete below ambiguous).
    async def read():
        from spectra.services import lyric_reading as lr
        await lr.read_song(URI, ask=_stub(
            [{"line": 1, "phrase": "azul", "label": "blue", "confidence": 0.9, "why": "x"}]))
    asyncio.run(read())
    before = _run("get_lyric_matches", song=STEM)
    guess_id = before["matches"][0]["id"]
    deleted = _run("delete_lyric_match", phrase="azul", song=STEM)
    assert deleted["status"] == "applied"
    assert _run("get_lyric_matches", song=STEM)["matches"] == []

    out = _run("restore_lyric_matches", song=STEM)
    assert out["status"] == "applied"
    restored = _run("get_lyric_matches", song=STEM)
    assert [m["id"] for m in restored["matches"]] == [guess_id]


def test_restoring_with_nothing_deleted_still_applies():
    out = _run("restore_lyric_matches", song=STEM)
    assert out["status"] == "applied"
    assert "no" in out["summary"].lower()


# ── reading a song's lyrics — always a Claude spend, always asks first ──

def test_read_song_lyrics_always_asks_first(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(scfg, "settings_agent_backend", lambda: "api")
    calls = []

    async def ask(*, system, user, schema, purpose):
        calls.append(purpose)
        return claude_text.ClaudeReply(
            {"matches": [{"line": 1, "phrase": "azul", "label": "blue",
                        "confidence": 0.9, "why": "x"}]}, "test-model", "api")
    monkeypatch.setattr(claude_text, "ask_json", ask)

    first = _run("read_song_lyrics", song=STEM)
    assert first["status"] == "needs_confirmation"
    assert calls == []

    second = _run("read_song_lyrics", song=STEM, confirm_id=first["confirm_id"])
    assert second["status"] == "applied"
    assert calls == ["lyric-reading"]
    assert second["reading"]["model"] == "test-model"


def test_read_song_lyrics_refuses_a_song_with_no_usable_timeline(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(scfg, "settings_agent_backend", lambda: "api")
    out = _run("read_song_lyrics", song="spotify:track:does-not-exist")
    assert out["status"] == "rejected"


def test_read_song_lyrics_refuses_when_claude_is_not_set_up(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(scfg, "settings_agent_backend", lambda: "api")
    out = _run("read_song_lyrics", song=STEM)
    assert out["status"] == "rejected"


# ── word colours and imprints: the per-show switch, tuning and preview ──

def test_get_lyric_event_settings_reads_the_switch_and_the_tuning():
    out = _run("get_lyric_event_settings", song=STEM)
    assert out["enabled"] is False
    assert out["energy_cutoff"] == pytest.approx(0.5)
    assert out["min_gap_s"] == pytest.approx(8.0)
    assert out["imprint_window_s"] == pytest.approx(2.0)
    assert out["n_shows_on"] == 0


def test_get_lyric_event_settings_defaults_to_whatever_is_playing(monkeypatch):
    from spectra.services import show_arms
    monkeypatch.setattr(show_arms, "current_uri", lambda: URI)
    out = _run("get_lyric_event_settings")
    assert out["song"] == STEM


def test_turning_word_colours_on_needs_his_yes_first():
    from spectra.services import lyric_events
    first = _run("set_lyric_event_show", enabled=True, song=STEM)
    assert first["status"] == "needs_confirmation"
    assert lyric_events.enabled(URI) is False     # nothing happened yet

    wrong = _run("set_lyric_event_show", enabled=True, song=STEM, confirm_id="not-a-real-id")
    assert wrong["status"] == "rejected"
    assert lyric_events.enabled(URI) is False

    second = _run("set_lyric_event_show", enabled=True, song=STEM,
                  confirm_id=first["confirm_id"])
    assert second["status"] == "applied"
    assert lyric_events.enabled(URI) is True


def test_a_show_confirm_id_is_single_use():
    from spectra.services import lyric_events
    first = _run("set_lyric_event_show", enabled=True, song=STEM)
    _run("set_lyric_event_show", enabled=True, song=STEM, confirm_id=first["confirm_id"])
    lyric_events.set_show(URI, False)               # back off, no confirm needed that way
    replay = _run("set_lyric_event_show", enabled=True, song=STEM,
                  confirm_id=first["confirm_id"])
    assert replay["status"] == "rejected"
    assert lyric_events.enabled(URI) is False


def test_turning_word_colours_off_applies_at_once_no_confirm():
    from spectra.services import lyric_events
    lyric_events.set_show(URI, True)
    out = _run("set_lyric_event_show", enabled=False, song=STEM)
    assert out["status"] == "applied"
    assert lyric_events.enabled(URI) is False


def test_set_lyric_event_show_requires_a_real_boolean():
    out = _run("set_lyric_event_show", enabled="yes", song=STEM)
    assert out["status"] == "rejected"


def test_set_lyric_event_settings_changes_the_three_values():
    from spectra.services import lyric_events
    out = _run("set_lyric_event_settings", energy_cutoff=0.7, min_gap_s=5.0,
               imprint_window_s=3.0)
    assert out["status"] == "applied"
    settings = lyric_events.settings()
    assert settings.energy_cutoff == pytest.approx(0.7)
    assert settings.min_gap_s == pytest.approx(5.0)
    assert settings.imprint_window_s == pytest.approx(3.0)


def test_set_lyric_event_settings_only_changes_what_is_named():
    from spectra.services import lyric_events
    _run("set_lyric_event_settings", energy_cutoff=0.7)
    settings = lyric_events.settings()
    assert settings.energy_cutoff == pytest.approx(0.7)
    assert settings.min_gap_s == pytest.approx(8.0)
    assert settings.imprint_window_s == pytest.approx(2.0)


def test_set_lyric_event_settings_refuses_out_of_range_with_nothing_changed():
    from spectra.services import lyric_events
    out = _run("set_lyric_event_settings", energy_cutoff=5.0)
    assert out["status"] == "rejected"
    assert lyric_events.settings().energy_cutoff == pytest.approx(0.5)


def test_set_lyric_event_settings_naming_nothing_to_change_is_refused():
    out = _run("set_lyric_event_settings")
    assert out["status"] == "rejected"


@pytest.fixture
def lyric_events_route(monkeypatch):
    """preview_lyric_events reaches the real Test Bed route (spectra/api/
    lyric_events.py) through `lyric_console.http` — here wired to a real
    TestClient over the real router, in-process, same precedent as
    tests/test_lock_console.py's own `root` fixture. No socket, no live
    process, ever."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from spectra.api import lyric_events as lyric_events_api
    app = FastAPI()
    app.include_router(lyric_events_api.router)
    client = TestClient(app)

    async def fake_http(method, path, *, params=None):
        return client.request(method, path, params=params)

    monkeypatch.setattr(lyric_console, "http", fake_http)
    return client


def test_preview_lyric_events_shows_the_plan_for_a_song_with_no_matches(lyric_events_route):
    out = _run("preview_lyric_events", song=STEM)
    assert out["song"] == STEM
    assert out["enabled"] is False
    assert out["actions"] == []


def test_preview_lyric_events_reflects_the_switch(lyric_events_route):
    from spectra.services import lyric_events
    lyric_events.set_show(URI, True)
    out = _run("preview_lyric_events", song=STEM)
    assert out["enabled"] is True


def test_preview_lyric_events_defaults_to_whatever_is_playing(lyric_events_route, monkeypatch):
    from spectra.services import show_arms
    monkeypatch.setattr(show_arms, "current_uri", lambda: URI)
    out = _run("preview_lyric_events")
    assert out["uri"] == URI


def test_preview_lyric_events_carries_the_shape_verdict_and_its_times(lyric_events_route):
    """Word Shapes row W2.4's audit of what W0.3 landed on THIS side of the
    seam: a word Sonic itself matched to a shape comes back through the
    preview op as the shape it is — verdict, shape id/name and the form/
    hold/release the room's own settings resolved — not as a plain colour
    word. The planner's own branch is proven in test_word_shape_contract.py;
    this proves the op RELAYS it, since `preview_lyric_events` is the only
    lyrics op that crosses the HTTP seam and could lose a field on the way."""
    from spectra.services import lyric_events

    assert _run("add_lyric_match", target_kind="shape", target_name="Heart",
                phrase="know", song=STEM)["status"] == "applied"
    lyric_events.set_show(URI, True)

    out = _run("preview_lyric_events", song=STEM)
    shaped = [a for a in out["actions"] if a["verdict"] == "shape"]
    assert shaped, out["actions"]
    action = shaped[0]
    assert action["shape"] == "heart" and action["shape_name"] == "Heart"
    assert action["shape_skipped"] is None
    assert action["form_s"] > 0 and action["hold_s"] > 0 and action["release_s"] > 0
    # the lead IS the form (the word-shapes skill's own rule), in ms
    assert action["transition_ms"] == pytest.approx(action["form_s"] * 1000, abs=1)
    assert "shape" in action["words"].lower()


def test_the_preview_ops_instructions_name_every_shape_outcome_it_can_return():
    """W2.4 spec item 4. The three words a shape word can come back as are
    `shape_skipped` = drop_wins / nothing_can_draw (the planner's two
    skips) and the show log's `fell_back_to_colour` (the fire-time net) —
    all three read off lyric_events' own constants rather than re-typed
    here, so a renamed constant fails this instead of silently leaving
    Sonic describing an outcome that no longer exists."""
    from spectra.services import lyric_events as le

    text = lyric_console.OPERATIONS["preview_lyric_events"].instructions
    for token in (le.WHY_DROP_WINS, le.WHY_CANNOT_DRAW, le.RESULT_FELL_BACK):
        assert token in text, token


def test_preview_lyric_events_refuses_a_song_with_no_timeline(monkeypatch):
    from spectra.services import show_arms
    monkeypatch.setattr(show_arms, "current_uri", lambda: None)
    out = _run("preview_lyric_events")
    assert out["status"] == "rejected"


def test_preview_lyric_events_is_a_stated_rejection_when_the_app_is_unreachable(monkeypatch):
    async def down(*a, **k):
        raise ConnectionError("connection refused")
    monkeypatch.setattr(lyric_console, "http", down)
    out = _run("preview_lyric_events", song=STEM)
    assert out["status"] == "rejected" and "did not answer" in out["reason"]


# ── nothing here writes light ───────────────────────────────────────────

#: Every handler called directly (never through settings_agent._dispatch,
#: which merges in sibling domains — scene_console, show_console,
#: device_console — that legitimately import several of these and would
#: make the forbidden-module check below a false positive). A fresh
#: interpreter, since this file's own tests may already have pulled some
#: of these into THIS process's sys.modules for unrelated reasons.
_NO_LIGHT_DRIVER = textwrap.dedent('''
    import asyncio
    import inspect
    import json
    import os
    import sys
    import tempfile
    from pathlib import Path

    from spectra import config as scfg
    from spectra.services import analysis_reader, claude_text, lyric_console, lyric_reading
    from tests.lyric_song_world import STEM, color_sets, song

    tmp = Path(tempfile.mkdtemp())
    scfg.AUDIO_SHAPES_DIR = tmp / "audio_shapes"
    scfg.COLOR_SETS_FILE = tmp / "color_sets.json"
    scfg.TRIGGERS_FILE = tmp / "triggers.json"
    scfg.PROFILES_DIR = tmp / "profiles"
    scfg.SUNG_LABELS_FILE = tmp / "sung_labels.json"
    scfg.LYRIC_MATCHES_DIR = tmp / "lyric_matches"
    scfg.LYRIC_EVENTS_FILE = tmp / "lyric_events.json"
    scfg.LYRIC_PLAYS_FILE = tmp / "lyric_plays.json"
    scfg.ROOM_CONTROLS_FILE = tmp / "room_controls.json"
    scfg.PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    scfg.AUDIO_SHAPES_DIR.mkdir(parents=True, exist_ok=True)
    analysis_reader._shape_index.clear()
    analysis_reader._index_built = False
    lyric_reading.reset()
    color_sets(scfg)
    song(scfg)

    os.environ["ANTHROPIC_API_KEY"] = "test-key"
    scfg.settings_agent_backend = lambda: "api"

    async def stub_ask(*, system, user, schema, purpose):
        return claude_text.ClaudeReply(
            {"matches": [], "sets": [{"code": "c0", "things": ["volcano"], "moods": [],
                                      "places": []}]},
            "test-model", "api")
    claude_text.ask_json = stub_ask

    def run(op_name, **kw):
        out = lyric_console.OPERATIONS[op_name].handler(**kw)
        return asyncio.run(out) if inspect.isawaitable(out) else out

    run("get_lyric_reading_settings")
    run("list_sung_label_targets")
    run("get_sung_labels", kind="color_set", name="Blood Red")
    run("get_lyric_matches", song=STEM)
    run("set_lyric_reading_settings", auto_read=False)
    run("edit_sung_label", kind="color_set", name="Blood Red", list="labels", op="add",
        text="scarlet")
    run("add_lyric_match", target_kind="color_set", target_name="Blood Red",
        phrase="red light", song=STEM)
    run("delete_lyric_match", phrase="red light", song=STEM)
    run("restore_lyric_matches", song=STEM)

    run("get_sung_labels", kind="shape", name="Heart")
    run("edit_sung_label", kind="shape", name="Heart", list="labels", op="add",
        text="sweetheart")
    run("add_lyric_match", target_kind="shape", target_name="Heart", phrase="know",
        song=STEM)

    first = run("set_lyric_reading_settings", auto_read=True)
    run("set_lyric_reading_settings", auto_read=True, confirm_id=first["confirm_id"])

    first = run("draft_colour_meanings", names=["Blood Red"])
    run("draft_colour_meanings", names=["Blood Red"], confirm_id=first["confirm_id"])

    first = run("read_song_lyrics", song=STEM)
    run("read_song_lyrics", song=STEM, confirm_id=first["confirm_id"])

    run("get_lyric_event_settings", song=STEM)
    run("set_lyric_event_settings", min_gap_s=5.0)

    # preview_lyric_events goes over HTTP (lyric_console.http), never an
    # import of the engine stack — stubbed here so calling it still proves
    # the import boundary without this driver dialing 127.0.0.1 at all.
    async def no_http(*a, **k):
        raise ConnectionError("no real socket in this driver")
    lyric_console.http = no_http
    run("preview_lyric_events", song=STEM)

    first = run("set_lyric_event_show", enabled=True, song=STEM)
    run("set_lyric_event_show", enabled=True, song=STEM, confirm_id=first["confirm_id"])

    forbidden = ["fx_seam", "engine", "trigger_engine", "scene_response", "scene_compiler",
                "scene_sequencer", "drift_conductor", "fx_executor", "live_host",
                "show_actions"]
    reached = {n: True for n in forbidden if f"spectra.services.{n}" in sys.modules}
    print(json.dumps(reached))
''')


def test_lyric_console_operations_never_reach_a_light_writing_module():
    """Every one of lyric_console's own operations, actually called — not a
    grep of its import statements, which a transitive re-export or a
    dynamic import could satisfy without proving anything. A fresh
    interpreter calls every handler (driving the ask/confirm dance for the
    ones that need it) and reports which, if any, light-writing module
    ended up loaded as a side effect. preview_lyric_events's own `http` is
    stubbed to raise rather than dial out, so this driver proves the
    import boundary without ever touching a socket — the real HTTP path is
    proven separately, against a real TestClient, in the tests above."""
    proc = subprocess.run([sys.executable, "-c", _NO_LIGHT_DRIVER],
                          cwd=os.fspath(scfg.REPO_ROOT), capture_output=True, text=True,
                          timeout=90)
    assert proc.returncode == 0, proc.stderr[-3000:]
    reached = json.loads(proc.stdout.strip().splitlines()[-1])
    assert reached == {}, f"running lyric_console's operations pulled in {sorted(reached)}"
