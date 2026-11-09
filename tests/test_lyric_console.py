"""Sonic's lyrics domain (spectra/services/lyric_console.py): the sung
labels, Claude's colour meanings, a song's word matches, and the automatic
reader's own switch and weak-match threshold — the Sonic coverage
follow-up for PR #499. Reached through spectra.services.settings_agent's
real dispatch boundary, same convention as tests/test_drop_console.py; no
HTTP, no light, Claude always a stub."""
from __future__ import annotations

import asyncio

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


def test_list_can_be_narrowed_to_one_kind():
    out = _run("list_sung_label_targets", kind="effect")
    assert all(t["kind"] == "effect" for t in out["targets"])
    assert "Blood Red" not in {t["name"] for t in out["targets"]}


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


# ── the auto-read switch and the weak-match threshold ──────────────────

def test_get_lyric_reading_settings_reads_the_defaults():
    out = _run("get_lyric_reading_settings")
    assert out["auto_read"] is False
    assert out["weak_match_threshold"] == pytest.approx(0.6)


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


def test_the_weak_match_threshold_changes_with_no_confirmation():
    out = _run("set_lyric_reading_settings", weak_match_threshold=0.8)
    assert out["status"] == "applied"
    assert sung_labels.weak_match_threshold() == pytest.approx(0.8)


def test_the_weak_match_threshold_is_refused_out_of_range():
    out = _run("set_lyric_reading_settings", weak_match_threshold=1.5)
    assert out["status"] == "rejected"
    assert sung_labels.weak_match_threshold() == pytest.approx(0.6)


def test_asking_to_turn_auto_read_off_and_lower_the_threshold_together_needs_no_confirm():
    sung_labels.set_auto_read(True)
    out = _run("set_lyric_reading_settings", auto_read=False, weak_match_threshold=0.7)
    assert out["status"] == "applied"
    assert sung_labels.auto_read_enabled() is False
    assert sung_labels.weak_match_threshold() == pytest.approx(0.7)


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


# ── nothing here writes light ───────────────────────────────────────────

def test_lyric_console_imports_nothing_that_can_write_light():
    import ast
    forbidden = {"fx_seam", "engine", "trigger_engine", "scene_response", "scene_compiler",
                "scene_sequencer", "drift_conductor", "fx_executor", "live_host",
                "show_actions"}
    path = scfg.REPO_ROOT / "spectra" / "services" / "lyric_console.py"
    imported: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            imported.update(a.name for a in node.names)
            imported.add((node.module or "").rsplit(".", 1)[-1])
        elif isinstance(node, ast.Import):
            imported.update(a.name.rsplit(".", 1)[-1] for a in node.names)
    assert not (imported & forbidden), f"lyric_console imports {sorted(imported & forbidden)}"
