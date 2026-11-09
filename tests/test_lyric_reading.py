"""Claude's reading of a song's lyrics and his edits to it (lyrics plan step 3):
text only, every guess checked, weak ones gone, off by default, and his edits
standing through a re-read and a recapture. Claude is always a stub here."""
from __future__ import annotations

import asyncio
import json
import os
import stat
import subprocess
import sys
import textwrap

import pytest

from spectra import config as scfg
from spectra.models.lyric_labels import TargetRef
from spectra.services import (analysis_reader, claude_text, lyric_matches, lyric_reading,
                              lyrics_timeline, sung_labels)
from tests.lyric_song_world import (STEM, URI, capture, color_sets, isolate, sidecar, song,
                                    words as make_words)


@pytest.fixture(autouse=True)
def _world(tmp_path, monkeypatch):
    isolate(tmp_path, monkeypatch, scfg, analysis_reader)
    color_sets(scfg)
    song(scfg)


def _client():
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    return TestClient(create_app())


def _stub(rows, calls=None):
    async def ask(*, system, user, schema, purpose):
        if calls is not None:
            calls.append({"system": system, "user": user, "schema": schema, "purpose": purpose})
        return claude_text.ClaudeReply({"matches": rows}, "test-model", "api")
    return ask


def _row(line, phrase, label, confidence=0.9, why="clear"):
    return {"line": line, "phrase": phrase, "label": label, "confidence": confidence, "why": why}


def _timeline():
    return lyrics_timeline.timeline_for_uri(URI)


def _read(rows):
    return asyncio.run(lyric_reading.read_song(URI, ask=_stub(rows)))


def _guesses(payload):
    return [m for m in payload["matches"] if m["source"] == "claude"]


# ── what goes to Claude ─────────────────────────────────────────────────────

def test_the_prompt_is_the_words_and_the_labels_and_nothing_else():
    calls = []
    asyncio.run(lyric_reading.read_song(URI, ask=_stub([], calls)))
    sent = calls[0]
    assert sent["purpose"] == "lyric-reading"
    assert "red light" in sent["user"] and STEM in sent["user"]
    assert "azul" in sent["system"]         # a seeded label
    assert "fish" in sent["system"]         # an effect label
    # Words and labels only: no times, no audio features, no file paths.
    assert "ms" not in sent["user"].split()
    assert ".wav" not in sent["user"] and ".npz" not in sent["user"]


def test_a_line_sung_again_is_sent_once():
    calls = []
    asyncio.run(lyric_reading.read_song(URI, ask=_stub([], calls)))
    assert calls[0]["user"].count("the red light") == 1
    assert "(sung again at 2)" in calls[0]["user"]


def test_the_label_list_does_not_change_from_song_to_song_so_it_caches():
    calls = []
    other_uri = "spotify:track:other"
    song(scfg, make_words(["no blue here"]), stem="Other - Song", uri=other_uri)
    asyncio.run(lyric_reading.read_song(URI, ask=_stub([], calls)))
    asyncio.run(lyric_reading.read_song(other_uri, ask=_stub([], calls)))
    assert calls[0]["system"] == calls[1]["system"]


def test_no_label_list_means_nothing_is_sent(monkeypatch):
    empty = sung_labels.Catalogue(targets={}, labels={}, owners={})
    monkeypatch.setattr(sung_labels, "catalogue", lambda: empty)
    calls = []
    with pytest.raises(lyric_reading.NoLabels):
        asyncio.run(lyric_reading.read_song(URI, ask=_stub([], calls)))
    assert calls == []


# ── every guess is checked ──────────────────────────────────────────────────

def _parse(rows):
    catalogue = sung_labels.catalogue()
    return lyric_reading.parse_reply({"matches": rows}, _timeline().scored, catalogue)


def test_a_good_guess_records_its_confidence_and_that_it_is_a_guess():
    payload = _read([_row(1, "azul", "blue", 0.92, "colour named outright")])
    guess = _guesses(payload)[0]
    assert guess["phrase"] == "azul"
    assert guess["label"] == "blue"
    assert guess["confidence"] == 0.92
    assert guess["provenance"] == "claude_guess"
    assert guess["why"] == "colour named outright"


def test_a_weak_guess_is_no_match_and_is_only_counted():
    matches, n_weak, refused = _parse([_row(1, "azul", "blue", lyric_reading.WEAK_MATCH_THRESHOLD - 0.01)])
    assert matches == [] and n_weak == 1 and refused == {}


def test_a_guess_at_the_line_is_a_match():
    matches, n_weak, _ = _parse([_row(1, "azul", "blue", lyric_reading.WEAK_MATCH_THRESHOLD)])
    assert len(matches) == 1 and n_weak == 0


@pytest.mark.parametrize("row,reason", [
    (_row(99, "azul", "blue"), lyric_reading.REFUSED_LINE),
    (_row(1, "verde", "blue"), lyric_reading.REFUSED_PHRASE),
    (_row(1, "azul", "not on the list"), lyric_reading.REFUSED_LABEL),
    ({"line": "x", "phrase": "azul", "label": "blue", "confidence": 0.9, "why": ""}, lyric_reading.REFUSED_ROW),
    (_row(1, "azul", "blue", 1.7), lyric_reading.REFUSED_ROW),
])
def test_a_guess_naming_something_that_is_not_there_is_thrown_away(row, reason):
    matches, _, refused = _parse([row])
    assert matches == [] and refused == {reason: 1}


def test_a_guess_lands_on_every_line_that_sings_it():
    matches, _, _ = _parse([_row(0, "red", "red")])
    assert [m.first_word for m in matches] == [1, 8]


def test_a_guess_is_matched_past_case_accents_and_apostrophes():
    matches, _, _ = _parse([_row(3, "DON'T", "blue"), _row(1, "Azúl", "blue")])
    assert {m.phrase for m in matches} == {"don't", "azul"}


# ── reading, re-reading, and what it never touches ──────────────────────────

def test_a_reading_is_stored_and_the_times_come_from_the_words():
    payload = _read([_row(0, "red light", "red")])
    words = _timeline().scored
    guess = _guesses(payload)[0]
    assert guess["first_word"] == 1 and guess["last_word"] == 2
    assert guess["ms"] == words[1].ms and guess["end_ms"] == words[2].end_ms
    assert guess["score"] == max(words[1].score, words[2].score)
    stored = json.loads(lyric_matches._path(URI).read_text())
    assert "ms" not in stored["reading"]["matches"][0]


def test_who_a_guess_reaches_is_every_card_carrying_the_label():
    sung_labels.edit("color_set", "blue1", "labels", "add", "red")
    guess = _guesses(_read([_row(0, "red", "red")]))[0]
    assert {t["id"] for t in guess["targets"]} == {"red1", "blue1"}
    assert guess["n_targets"] == 2


def test_a_re_read_replaces_claudes_reading_and_nothing_of_his():
    _read([_row(0, "red", "red"), _row(1, "azul", "blue")])
    first = _guesses(lyric_matches.payload(URI))
    deleted = next(m for m in first if m["label"] == "blue")
    lyric_matches.delete(URI, deleted["id"])
    lyric_matches.add(URI, 8, 8, TargetRef(kind="effect", id="fish"))

    payload = _read([_row(1, "azul", "blue"), _row(3, "know", "fish")])
    labels = {m["label"] for m in _guesses(payload)}
    assert labels == {"fish"}           # blue stays deleted, red was not offered again
    his = [m for m in payload["matches"] if m["source"] == "his"]
    assert [m["first_word"] for m in his] == [8]


def test_the_same_words_with_a_different_label_are_a_new_guess():
    _read([_row(1, "azul", "blue")])
    lyric_matches.delete(URI, _guesses(lyric_matches.payload(URI))[0]["id"])
    payload = _read([_row(1, "azul", "ocean")])
    assert [m["label"] for m in _guesses(payload)] == ["ocean"]


def test_his_own_match_on_the_same_words_hides_a_guess_there():
    _read([_row(1, "azul", "blue")])
    lyric_matches.add(URI, 3, 3, TargetRef(kind="effect", id="fish"))
    payload = lyric_matches.payload(URI)
    assert [m["source"] for m in payload["matches"]] == ["his"]
    assert payload["matches"][0]["targets"][0]["name"] == "Fish"


def test_deleted_guesses_can_be_brought_back():
    _read([_row(1, "azul", "blue")])
    lyric_matches.delete(URI, _guesses(lyric_matches.payload(URI))[0]["id"])
    assert _guesses(lyric_matches.payload(URI)) == []
    assert lyric_matches.payload(URI)["n_deleted"] == 1
    assert len(_guesses(lyric_matches.restore_deleted(URI))) == 1


# ── surviving a recapture ───────────────────────────────────────────────────

def _his_edits():
    _read([_row(1, "azul", "blue"), _row(0, "red", "red")])
    guess = next(m for m in _guesses(lyric_matches.payload(URI)) if m["label"] == "red")
    lyric_matches.delete(URI, guess["id"])
    lyric_matches.add(URI, 8, 8, TargetRef(kind="color_set", id="blue1"))


def test_a_recapture_moves_the_times_and_keeps_every_edit():
    _his_edits()
    capture(scfg)
    sidecar(scfg, make_words(start=30_000.0))
    payload = lyric_matches.payload(URI)
    assert payload["state"] == lyric_matches.STATE_FRESH
    words = _timeline().scored
    his = next(m for m in payload["matches"] if m["source"] == "his")
    assert his["ms"] == words[8].ms and his["ms"] > 30_000
    labels = [m["label"] for m in _guesses(payload)]
    assert labels == ["blue"]           # red stayed deleted
    assert payload["n_deleted"] == 1


def test_a_stale_capture_shows_nothing_and_loses_nothing():
    _his_edits()
    capture(scfg)                       # a new capture, words not re-aligned
    (scfg.AUDIO_SHAPES_DIR / f"{STEM}.npz").write_bytes(b"different")
    payload = lyric_matches.payload(URI)
    assert payload["status"] == lyrics_timeline.STATUS_STALE
    assert payload["matches"] == [] and payload["n_his"] == 1
    doc = lyric_matches.load(URI)
    assert len(doc.his) == 1 and len(doc.deleted) == 1 and doc.reading is not None


def test_words_that_shifted_are_found_again_near_where_they_were():
    _his_edits()
    capture(scfg)
    # A new first line pushes every word along by three.
    sidecar(scfg, make_words(["una nueva linea", "the red light", "azul sobre el mar",
                              "the red light", "don't you know"]))
    payload = lyric_matches.payload(URI)
    assert payload["state"] == lyric_matches.STATE_WORDS_CHANGED
    his = next(m for m in payload["matches"] if m["source"] == "his")
    assert his["first_word"] == 11 and his["phrase"] == "red"
    assert not payload["unplaced"]


def test_his_match_on_words_that_are_gone_is_reported_and_kept():
    lyric_matches.add(URI, 3, 3, TargetRef(kind="color_set", id="blue1"))
    capture(scfg)
    sidecar(scfg, make_words(["completely different words"]))
    payload = lyric_matches.payload(URI)
    assert payload["unplaced"] and payload["unplaced"][0]["phrase"] == "azul"
    assert len(lyric_matches.load(URI).his) == 1


# ── freshness ───────────────────────────────────────────────────────────────

def test_the_state_says_when_the_labels_changed_since_the_reading():
    assert lyric_matches.payload(URI)["state"] == lyric_matches.STATE_NONE
    _read([_row(1, "azul", "blue")])
    assert lyric_matches.payload(URI)["state"] == lyric_matches.STATE_FRESH
    sung_labels.edit("color_set", "red1", "labels", "add", "passion")
    assert lyric_matches.payload(URI)["state"] == lyric_matches.STATE_LABELS_CHANGED


def test_a_guess_whose_label_nobody_carries_any_more_is_not_shown():
    _read([_row(1, "azul", "blue")])
    sung_labels.edit("color_set", "blue1", "labels", "remove", "blue")
    assert _guesses(lyric_matches.payload(URI)) == []


def test_a_word_he_matched_outright_stands_when_the_labels_change():
    lyric_matches.add(URI, 3, 3, TargetRef(kind="color_set", id="blue1"))
    sung_labels.edit("color_set", "blue1", "labels", "remove", "azul")
    his = lyric_matches.payload(URI)["matches"][0]
    assert his["source"] == "his" and his["targets"][0]["id"] == "blue1"


def test_his_match_on_a_card_since_deleted_says_so():
    lyric_matches.add(URI, 3, 3, TargetRef(kind="color_set", id="blue1"))
    color_sets(scfg, [{"id": "red1", "name": "Blood Red", "kind": "set",
                       "entries": [{"color_value": "#ff0000"}]}])
    his = lyric_matches.payload(URI)["matches"][0]
    assert his["targets"] == [] and his["targets_missing"] == 1


def test_his_add_is_refused_for_words_and_targets_that_do_not_exist():
    with pytest.raises(lyric_matches.MatchRefused):
        lyric_matches.add(URI, 500, 501, TargetRef(kind="effect", id="fish"))
    with pytest.raises(lyric_matches.MatchRefused):
        lyric_matches.add(URI, 1, 1, TargetRef(kind="effect", id="not-an-effect"))
    with pytest.raises(lyric_matches.MatchRefused):
        lyric_matches.add(URI, 0, 50, TargetRef(kind="effect", id="fish"))


def test_adding_the_same_match_twice_is_one_match():
    lyric_matches.add(URI, 3, 3, TargetRef(kind="effect", id="fish"))
    lyric_matches.add(URI, 3, 3, TargetRef(kind="effect", id="fish"))
    assert len(lyric_matches.load(URI).his) == 1


def test_the_emphasized_lane_mark_carries_the_label():
    _read([_row(0, "red light", "red")])
    from spectra.services import testbed_engines
    marks = testbed_engines._lyrics_marks(URI, emphasis_sensitivity=1.0)
    by_word = {m.label: m.detail["matched_label"] for m in marks}
    assert by_word["red"] == "red" and by_word["light"] == "red" and by_word["azul"] is None


# ── the automatic reader ────────────────────────────────────────────────────

def _quiet_labels():
    store = sung_labels.load()
    store.labels_changed_ms = 0
    sung_labels._save(store)


def test_off_by_default_nothing_is_ever_sent():
    calls = []
    assert asyncio.run(lyric_reading.sweep_once(ask=_stub([], calls))) is None
    assert calls == []


def test_turned_on_it_reads_a_song_that_has_no_reading():
    sung_labels.set_auto_read(True)
    calls = []
    assert asyncio.run(lyric_reading.sweep_once(ask=_stub([], calls))) == URI
    assert len(calls) == 1
    assert lyric_matches.payload(URI)["state"] == lyric_matches.STATE_FRESH


def test_it_re_reads_when_the_labels_change_but_waits_for_his_edits_to_go_quiet():
    sung_labels.set_auto_read(True)
    asyncio.run(lyric_reading.sweep_once(ask=_stub([])))
    lyric_reading.reset()
    sung_labels.edit("color_set", "red1", "labels", "add", "passion")

    calls = []
    assert asyncio.run(lyric_reading.sweep_once(ask=_stub([], calls))) is None
    assert calls == []                  # just edited: not yet

    _quiet_labels()
    assert asyncio.run(lyric_reading.sweep_once(ask=_stub([], calls))) == URI
    assert len(calls) == 1


def test_a_song_read_against_this_list_is_left_alone():
    sung_labels.set_auto_read(True)
    asyncio.run(lyric_reading.sweep_once(ask=_stub([])))
    lyric_reading.reset()
    calls = []
    assert asyncio.run(lyric_reading.sweep_once(ask=_stub([], calls))) is None
    assert calls == []


def test_one_song_at_a_time_at_a_slow_pace():
    other_uri = "spotify:track:other"
    song(scfg, make_words(["no blue here"]), stem="Other - Song", uri=other_uri)
    sung_labels.set_auto_read(True)
    calls = []
    asyncio.run(lyric_reading.sweep_once(ask=_stub([], calls)))
    assert asyncio.run(lyric_reading.sweep_once(ask=_stub([], calls))) is None
    assert len(calls) == 1              # the second had to wait READ_GAP_S


def test_a_failure_backs_off_instead_of_hammering():
    sung_labels.set_auto_read(True)
    calls = []

    async def fails(*, system, user, schema, purpose):
        calls.append(1)
        raise claude_text.ClaudeUnavailable("quota")
    assert asyncio.run(lyric_reading.sweep_once(ask=fails)) is None
    assert asyncio.run(lyric_reading.sweep_once(ask=fails)) is None
    assert len(calls) == 1


def test_a_reply_that_cannot_be_used_skips_that_song_only():
    other_uri = "spotify:track:zzz"
    song(scfg, make_words(["no blue here"]), stem="Other - Song", uri=other_uri)
    sung_labels.set_auto_read(True)
    calls = []

    async def ask(*, system, user, schema, purpose):
        calls.append(user)
        if STEM in user:
            raise claude_text.ClaudeReplyInvalid("declined")
        return claude_text.ClaudeReply({"matches": []}, "m", "api")
    assert asyncio.run(lyric_reading.sweep_once(ask=ask)) is None
    lyric_reading._last_read_at = 0.0       # past the pacing gap
    assert asyncio.run(lyric_reading.sweep_once(ask=ask)) == other_uri
    assert len(calls) == 2


def test_a_torn_match_file_is_never_read_as_no_edits():
    lyric_matches.add(URI, 3, 3, TargetRef(kind="effect", id="fish"))
    path = lyric_matches._path(URI)
    path.write_text("{ torn", encoding="utf-8")
    with pytest.raises(sung_labels.StoreUnreadable):
        lyric_matches.load(URI)
    with pytest.raises(sung_labels.StoreUnreadable):
        lyric_matches.add(URI, 4, 4, TargetRef(kind="effect", id="fish"))
    assert path.read_text(encoding="utf-8") == "{ torn"
    # The lane keeps its words; only the chips go.
    assert lyric_matches.labels_by_word(URI, _timeline()) == {}


def test_a_song_that_cannot_be_read_is_skipped_and_does_not_stop_the_pass():
    other_uri = "spotify:track:zzz"
    song(scfg, make_words(["no blue here"]), stem="Other - Song", uri=other_uri)
    (scfg.AUDIO_SHAPES_DIR / f"{STEM}.npz").write_bytes(b"different")    # URI is now stale
    sung_labels.set_auto_read(True)
    calls = []
    assert asyncio.run(lyric_reading.sweep_once(ask=_stub([], calls))) is None
    assert calls == []
    assert asyncio.run(lyric_reading.sweep_once(ask=_stub([], calls))) == other_uri
    assert len(calls) == 1


# ── the routes ──────────────────────────────────────────────────────────────

def test_the_routes_read_add_delete_and_restore(monkeypatch):
    monkeypatch.setattr(claude_text, "ask_json", _stub([_row(1, "azul", "blue")]))
    client = _client()
    assert client.get("/api/testbed/lyric-matches", params={"uri": URI}).json()["state"] == "none"
    read = client.post("/api/testbed/lyric-matches/read", params={"uri": URI}).json()
    assert read["state"] == "fresh" and len(read["matches"]) == 1

    added = client.post("/api/testbed/lyric-matches/add", json={
        "uri": URI, "first_word": 8, "last_word": 9,
        "target": {"kind": "effect", "id": "fish"}}).json()
    assert len(added["matches"]) == 2

    gone = client.post("/api/testbed/lyric-matches/delete",
                       json={"uri": URI, "id": read["matches"][0]["id"]}).json()
    assert [m["source"] for m in gone["matches"]] == ["his"]

    back = client.post("/api/testbed/lyric-matches/restore-deleted", params={"uri": URI}).json()
    assert len(back["matches"]) == 2


def test_the_read_route_says_why_when_it_cannot(monkeypatch):
    client = _client()
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    no_key = client.post("/api/testbed/lyric-matches/read", params={"uri": URI})
    assert no_key.status_code == 503 and "API key" in no_key.json()["detail"]
    no_words = client.post("/api/testbed/lyric-matches/read", params={"uri": "spotify:track:none"})
    assert no_words.status_code == 409


def test_the_route_refuses_a_bad_add_and_an_unknown_delete():
    client = _client()
    bad = client.post("/api/testbed/lyric-matches/add", json={
        "uri": URI, "first_word": 500, "last_word": 500,
        "target": {"kind": "effect", "id": "fish"}})
    assert bad.status_code == 422
    unknown = client.post("/api/testbed/lyric-matches/delete", json={"uri": URI, "id": "nope"})
    assert unknown.status_code == 404


# ── the Claude client ───────────────────────────────────────────────────────

def test_the_real_sdk_is_given_the_schema_and_the_cached_label_list(monkeypatch):
    anthropic = pytest.importorskip("anthropic")
    import httpx
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(scfg, "settings_agent_backend", lambda: "api")
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": "x",
            "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 3, "output_tokens": 2},
            "content": [{"type": "text", "text": '{"matches": []}'}]})

    real = anthropic.AsyncAnthropic

    def client(**kwargs):
        return real(**kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(anthropic, "AsyncAnthropic", client)
    reply = asyncio.run(claude_text.ask_json(system="LABELS", user="WORDS",
                                             schema={"type": "object"}, purpose="t"))
    assert reply.data == {"matches": []} and reply.backend == "api"
    assert seen["body"]["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert seen["body"]["output_config"]["format"]["type"] == "json_schema"
    assert seen["body"]["messages"] == [{"role": "user", "content": "WORDS"}]
    # Its tokens land on the same record Sonic's do.
    from spectra.services import sonic_usage
    assert sonic_usage.summary()["last_query"]["input_tokens"] == 3


@pytest.mark.parametrize("stop_reason,text", [("refusal", ""), ("max_tokens", '{"matches": [')])
def test_a_refused_or_cut_off_reply_is_not_used(monkeypatch, stop_reason, text):
    anthropic = pytest.importorskip("anthropic")
    import httpx
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(scfg, "settings_agent_backend", lambda: "api")

    def handler(request):
        return httpx.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": "x",
            "stop_reason": stop_reason, "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "content": [{"type": "text", "text": text}]})
    real = anthropic.AsyncAnthropic
    monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda **k: real(
        **k, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))))
    with pytest.raises(claude_text.ClaudeReplyInvalid):
        asyncio.run(claude_text.ask_json(system="s", user="u", schema={}, purpose="t"))


def test_no_key_is_stated_and_asks_nothing(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(scfg, "settings_agent_backend", lambda: "api")
    assert claude_text.availability()["available"] is False
    with pytest.raises(claude_text.ClaudeUnavailable):
        asyncio.run(claude_text.ask_json(system="s", user="u", schema={}, purpose="t"))


def _fake_cli(tmp_path, result_text, is_error=False):
    out = tmp_path / "argv.json"
    script = tmp_path / "claude"
    script.write_text("#!" + sys.executable + "\n" + textwrap.dedent(f"""
        import json, os, sys
        json.dump({{"argv": sys.argv[1:], "has_key": "ANTHROPIC_API_KEY" in os.environ,
                   "cwd": os.getcwd()}}, open({str(out)!r}, "w"))
        print(json.dumps([{{"type": "system", "subtype": "init", "tools": []}},
                          {{"type": "result", "result": {result_text!r}, "is_error": {is_error!r},
                           "usage": {{"input_tokens": 5, "output_tokens": 1}}, "num_turns": 1}}]))
    """), encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script, out


def test_the_cli_backend_offers_no_tools_and_uses_his_token(tmp_path, monkeypatch):
    script, out = _fake_cli(tmp_path, 'here you go: {"matches": []}')
    monkeypatch.setattr(scfg, "settings_agent_backend", lambda: "cli")
    monkeypatch.setattr(scfg, "settings_agent_cli_oauth_token", lambda: "tok")
    monkeypatch.setattr(scfg, "settings_agent_cli_binary", lambda: str(script))
    monkeypatch.setattr(scfg, "settings_agent_cli_workdir", lambda: tmp_path / "work")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-reach-the-child")
    reply = asyncio.run(claude_text.ask_json(system="LABELS", user="WORDS", schema={"type": "object"},
                                             purpose="t"))
    assert reply.data == {"matches": []} and reply.backend == "cli"
    argv = json.loads(out.read_text())
    assert argv["has_key"] is False
    assert argv["argv"][argv["argv"].index("--tools") + 1] == ""
    assert "--strict-mcp-config" in argv["argv"]
    assert "--allowedTools" not in argv["argv"]
    assert argv["cwd"] == str(tmp_path / "work")
    system = argv["argv"][argv["argv"].index("--system-prompt") + 1]
    assert system.startswith("LABELS") and "JSON" in system


def test_the_cli_reporting_an_error_is_unavailable(tmp_path, monkeypatch):
    script, _ = _fake_cli(tmp_path, "quota exhausted", is_error=True)
    monkeypatch.setattr(scfg, "settings_agent_backend", lambda: "cli")
    monkeypatch.setattr(scfg, "settings_agent_cli_oauth_token", lambda: "tok")
    monkeypatch.setattr(scfg, "settings_agent_cli_binary", lambda: str(script))
    monkeypatch.setattr(scfg, "settings_agent_cli_workdir", lambda: tmp_path / "work")
    with pytest.raises(claude_text.ClaudeUnavailable, match="quota"):
        asyncio.run(claude_text.ask_json(system="s", user="u", schema={}, purpose="t"))


# ── nothing reaches the room ────────────────────────────────────────────────

_SHOW_BOUNDARY_DRIVER = textwrap.dedent('''
    import json
    import sys

    import spectra.services.engine
    import spectra.services.trigger_engine
    import spectra.services.scene_response
    import spectra.services.scene_sequencer
    import spectra.services.scene_compiler
    import spectra.services.drift_conductor
    import spectra.services.fx_seam

    names = ["sung_labels", "lyric_matches", "lyric_reading", "color_meanings",
             "colour_words", "claude_text"]
    print(json.dumps({n: f"spectra.services.{n}" in sys.modules for n in names}))
''')


def test_nothing_in_the_show_can_reach_the_label_or_match_modules():
    """No light output in this step. A fresh interpreter, because this file's
    own tests have already imported them here."""
    proc = subprocess.run([sys.executable, "-c", _SHOW_BOUNDARY_DRIVER],
                          cwd=os.fspath(scfg.REPO_ROOT), capture_output=True, text=True, timeout=90)
    assert proc.returncode == 0, proc.stderr[-3000:]
    reached = {k: v for k, v in json.loads(proc.stdout.strip().splitlines()[-1]).items() if v}
    assert reached == {}, f"the show's own modules pulled in {sorted(reached)}"


def test_the_label_and_match_modules_import_nothing_that_can_write_light():
    import ast
    forbidden = {"fx_seam", "engine", "trigger_engine", "scene_response", "scene_compiler",
                 "scene_sequencer", "drift_conductor", "fx_executor", "live_host", "show_actions"}
    for name in ("sung_labels", "lyric_matches", "lyric_reading", "color_meanings",
                 "colour_words", "claude_text"):
        path = scfg.REPO_ROOT / "spectra" / "services" / f"{name}.py"
        imported: set[str] = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                imported.update(a.name for a in node.names)
                imported.add((node.module or "").rsplit(".", 1)[-1])
            elif isinstance(node, ast.Import):
                imported.update(a.name.rsplit(".", 1)[-1] for a in node.names)
        assert not (imported & forbidden), f"{name} imports {sorted(imported & forbidden)}"
