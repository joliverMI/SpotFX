"""The sung labels (lyrics plan step 3): what a colour set or effect answers to
when it is sung, how the list is seeded, and that his edits outlast everything
computed around them."""
from __future__ import annotations

import asyncio
import json

import pytest

from tests.lyric_song_world import color_sets as write_color_sets, isolate
from spectra import config as scfg
from spectra.services import analysis_reader, claude_text, color_meanings, colour_words, sung_labels


@pytest.fixture(autouse=True)
def _world(tmp_path, monkeypatch):
    isolate(tmp_path, monkeypatch, scfg, analysis_reader)
    write_color_sets(scfg)


def _client():
    from fastapi.testclient import TestClient
    from spectra.app import create_app
    return TestClient(create_app())


def _row(page, card_id):
    return next(r for r in page["color_sets"] if r["id"] == card_id)


def _texts(chips):
    return [c["text"] for c in chips]


def _source(chips, text):
    return next(c["source"] for c in chips if c["text"] == text)


# ── the seed ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("hex_colour,family", [
    ("#ff0000", "red"), ("#ff3900", "orange"), ("#faff00", "yellow"), ("#00ff07", "green"),
    ("#00fff0", "cyan"), ("#0500ff", "blue"), ("#a600ff", "purple"), ("#ff00ae", "pink"),
    ("#ffffff", "white"), ("#000000", "black"), ("#808080", "grey"),
])
def test_a_hue_is_named_for_its_family(hex_colour, family):
    assert colour_words.family_of(hex_colour)[0] == family


def test_the_seed_is_smarter_than_the_colour_names():
    words = colour_words.seed_labels("Line - Blue", ["#0500ff"])
    assert "blue" in words                 # the name
    assert "azul" in words                 # Spanish: his library is half Latin
    assert "sapphire" in words             # another word for it
    assert "ocean" in words                # what it brings to mind


def test_a_dark_blue_is_navy_and_a_pale_one_is_sky():
    assert "navy" in colour_words.seed_labels("x", ["#000060"])
    assert "navy" not in colour_words.seed_labels("x", ["#0000ff"])
    assert "sky blue" in colour_words.seed_labels("x", ["#a0c8ff"])


def test_black_between_coloured_stops_is_the_shape_of_the_effect_not_a_colour():
    words = colour_words.seed_labels("Line - Red", ["#000000", "#ff0000"])
    assert "red" in words and "black" not in words
    assert "black" in colour_words.seed_labels("x", ["#000000"])


def test_a_rainbow_is_a_rainbow_however_many_hues_it_has():
    assert colour_words.seed_labels("Hype 1", ["#ff0000"], is_rainbow=True) == [
        "hype", "rainbow", "arcoiris"]
    five = ["#ff0000", "#ffff00", "#00ff00", "#0000ff", "#ff00ff"]
    assert "rainbow" in colour_words.seed_labels("x", five)


@pytest.mark.parametrize("name,expected,absent", [
    ("Mid - Ice", ["ice"], ["mid"]),
    ("Blood Red", ["blood", "red"], []),
    ("Puerto Rico Red", ["puerto rico", "red"], ["rico"]),
    ("Black Hole - Green", ["green"], ["hole", "black hole"]),
    ("Black Hole Rainbow", ["rainbow"], ["hole"]),
    ("Calm - Evening Purple", ["calm", "evening", "purple"], []),
    ("Bass Drop Brightness", [], ["bass", "drop", "brightness"]),
])
def test_a_card_name_adds_what_the_colours_cannot(name, expected, absent):
    words = colour_words.seed_labels(name, [])
    for word in expected:
        assert word in words
    for word in absent:
        assert word not in words


def test_a_group_is_seeded_from_its_members_colours():
    write_color_sets(scfg, [
        {"id": "m", "name": "Member", "kind": "set",
         "entries": [{"color_value": "#00ff07"}]},
        {"id": "g", "name": "Lines", "kind": "group", "members": [{"color_set_id": "m"}]},
    ])
    row = _row(sung_labels.page(), "g")
    assert "verde" in _texts(row["labels"]) and row["has_colours"] is True


def test_a_group_of_many_colours_is_a_pool_and_not_a_rainbow():
    many = ["#ff0000", "#ff8000", "#ffff00", "#00ff00", "#0000ff"]
    write_color_sets(scfg, [
        *[{"id": f"m{i}", "name": f"Member {i}", "kind": "set", "entries": [{"color_value": c}]}
          for i, c in enumerate(many)],
        {"id": "g", "name": "Lines", "kind": "group",
         "members": [{"color_set_id": f"m{i}"} for i in range(5)]},
        {"id": "r", "name": "Mine", "kind": "group", "is_rainbow": True,
         "members": [{"color_set_id": "m0"}]},
    ])
    page = sung_labels.page()
    assert _row(page, "g")["labels"] == []
    assert "rainbow" in _texts(_row(page, "r")["labels"])


def test_a_card_with_no_colours_has_nothing_to_mean():
    write_color_sets(scfg, [{"id": "b", "name": "Bass Drop Brightness", "kind": "set",
                             "entries": [{"brightness": 0.5}]}])
    row = _row(sung_labels.page(), "b")
    assert row["labels"] == [] and row["has_colours"] is False


def test_the_swatch_is_a_real_colour_not_the_black_authored_for_dark_effects():
    write_color_sets(scfg, [{"id": "o", "name": "Orbit - Red", "kind": "set", "color": "#000000",
                             "entries": [{"color_value": "#ff0000"}]}])
    assert _row(sung_labels.page(), "o")["swatch"] == "#ff0000"
    write_color_sets(scfg, [{"id": "p", "name": "x", "kind": "set", "entries": [
        {"color_value": "linear-gradient(90deg, #ffffff 0%, #ff0000 50%)"}]}])
    assert _row(sung_labels.page(), "p")["swatch"] == "#ff0000"


# ── his edits ───────────────────────────────────────────────────────────────

def test_he_adds_and_removes_a_word_and_it_says_whose_it_is():
    sung_labels.edit("color_set", "red1", "labels", "add", "  Passion! ")
    sung_labels.edit("color_set", "red1", "labels", "remove", "cherry")
    row = _row(sung_labels.page(), "red1")
    assert _source(row["labels"], "passion") == "his"
    assert _source(row["labels"], "red") == "seed"
    assert "cherry" not in _texts(row["labels"])


def test_taking_a_word_back_out_of_his_list_then_adding_it_restores_it():
    sung_labels.edit("color_set", "red1", "labels", "remove", "cherry")
    sung_labels.edit("color_set", "red1", "labels", "add", "cherry")
    assert "cherry" in _texts(_row(sung_labels.page(), "red1")["labels"])


def test_his_edits_survive_the_set_being_recoloured():
    sung_labels.edit("color_set", "red1", "labels", "add", "passion")
    sung_labels.edit("color_set", "red1", "labels", "remove", "blood")
    write_color_sets(scfg, [{"id": "red1", "name": "Renamed", "kind": "set",
                             "entries": [{"color_value": "#0500ff"}]}])
    labels = _texts(_row(sung_labels.page(), "red1")["labels"])
    assert "azul" in labels and "passion" in labels and "blood" not in labels


def test_a_blank_word_is_refused():
    with pytest.raises(sung_labels.EditRefused):
        sung_labels.edit("color_set", "red1", "labels", "add", "  !!! ")


def test_a_card_that_does_not_exist_is_refused():
    with pytest.raises(sung_labels.EditRefused):
        sung_labels.edit("color_set", "nope", "labels", "add", "x")


def test_writing_labels_never_touches_his_colour_set_file():
    before = scfg.COLOR_SETS_FILE.read_bytes()
    sung_labels.edit("color_set", "red1", "labels", "add", "passion")
    sung_labels.apply_draft({"red1": {"things": ["roses"], "moods": [], "places": []}}, "m")
    assert scfg.COLOR_SETS_FILE.read_bytes() == before


def test_a_store_that_cannot_be_read_is_never_treated_as_empty():
    sung_labels.edit("color_set", "red1", "labels", "add", "passion")
    scfg.SUNG_LABELS_FILE.write_text("{ torn", encoding="utf-8")
    with pytest.raises(sung_labels.StoreUnreadable):
        sung_labels.page()
    with pytest.raises(sung_labels.StoreUnreadable):
        sung_labels.edit("color_set", "red1", "labels", "add", "other")
    assert scfg.SUNG_LABELS_FILE.read_text(encoding="utf-8") == "{ torn"


# ── effects ─────────────────────────────────────────────────────────────────

def test_every_registered_effect_is_listed():
    from fx import device_model
    page = sung_labels.page()
    assert {r["id"] for r in page["effects"]} == set(device_model.effect_types())


def test_the_effects_in_his_scenes_are_seeded_and_can_be_edited():
    sung_labels.edit("effect", "fish", "labels", "add", "shark")
    row = next(r for r in sung_labels.page()["effects"] if r["id"] == "fish")
    assert _source(row["labels"], "fish") == "seed"
    assert _source(row["labels"], "shark") == "his"


def test_an_effect_has_labels_and_not_meanings():
    with pytest.raises(sung_labels.EditRefused):
        sung_labels.edit("effect", "fish", "things", "add", "shark")


# ── the list Claude is read against ─────────────────────────────────────────

def test_the_list_says_who_carries_each_label():
    cat = sung_labels.catalogue()
    assert [t.id for t in cat.owners["red"]] == ["red1"]
    assert "fish" in cat.effect_labels
    assert "azul" in cat.color_labels
    assert cat.targets[("effect", "fish")].kind == "effect"


def test_meanings_are_on_the_list_too():
    sung_labels.apply_draft({"red1": {"things": ["volcano"], "moods": ["rage"], "places": []}}, "m")
    cat = sung_labels.catalogue()
    assert [t.id for t in cat.owners["volcano"]] == ["red1"]
    assert [t.id for t in cat.owners["rage"]] == ["red1"]


def test_the_hash_moves_when_a_word_is_added_and_not_when_a_word_moves_between_cards():
    start = sung_labels.catalogue().labels_hash
    sung_labels.edit("color_set", "red1", "labels", "add", "passion")
    added = sung_labels.catalogue().labels_hash
    assert added != start
    sung_labels.edit("color_set", "red1", "labels", "remove", "passion")
    sung_labels.edit("color_set", "blue1", "labels", "add", "passion")
    assert sung_labels.catalogue().labels_hash == added


# ── Claude's meanings ───────────────────────────────────────────────────────

def _drafter(sets):
    calls = []

    async def ask(*, system, user, schema, purpose):
        calls.append({"system": system, "user": user, "purpose": purpose})
        return claude_text.ClaudeReply({"sets": sets}, "test-model", "api")
    return ask, calls


def test_claude_drafts_things_moods_and_places_and_the_page_says_whose_they_are():
    ask, calls = _drafter([{"code": "c0", "things": ["Volcano", "embers"], "moods": ["rage"],
                            "places": ["desert"]}])
    result = asyncio.run(color_meanings.draft(["red1"], ask=ask))
    assert result["drafted"] == 1
    assert "Blood Red" in calls[0]["user"] and "#ff0000" in calls[0]["user"]
    row = _row(sung_labels.page(), "red1")
    assert _texts(row["meanings"]["things"]) == ["volcano", "embers"]
    assert _source(row["meanings"]["moods"], "rage") == "claude"
    assert row["draft_model"] == "test-model" and row["drafted_ms"]


def test_a_re_draft_keeps_his_additions_and_his_removals():
    ask, _ = _drafter([{"code": "c0", "things": ["volcano", "embers"], "moods": [], "places": []}])
    asyncio.run(color_meanings.draft(["red1"], ask=ask))
    sung_labels.edit("color_set", "red1", "things", "add", "lava")
    sung_labels.edit("color_set", "red1", "things", "remove", "embers")

    ask2, _ = _drafter([{"code": "c0", "things": ["embers", "magma"], "moods": ["fury"], "places": []}])
    asyncio.run(color_meanings.draft(["red1"], ask=ask2))
    row = _row(sung_labels.page(), "red1")
    assert _texts(row["meanings"]["things"]) == ["magma", "lava"]  # no embers, no volcano
    assert _source(row["meanings"]["things"], "lava") == "his"
    assert _texts(row["meanings"]["moods"]) == ["fury"]


def test_a_draft_touches_only_the_cards_it_was_asked_about():
    sung_labels.edit("color_set", "blue1", "things", "add", "tide")
    ask, _ = _drafter([{"code": "c0", "things": ["volcano"], "moods": [], "places": []}])
    asyncio.run(color_meanings.draft(["red1"], ask=ask))
    assert _texts(_row(sung_labels.page(), "blue1")["meanings"]["things"]) == ["tide"]


def test_a_code_claude_made_up_writes_nothing():
    ask, _ = _drafter([{"code": "c9", "things": ["x"], "moods": [], "places": []}])
    result = asyncio.run(color_meanings.draft(["red1"], ask=ask))
    assert result["drafted"] == 0
    assert _row(sung_labels.page(), "red1")["drafted_ms"] is None


def test_a_card_with_no_colours_is_not_sent_to_claude():
    write_color_sets(scfg, [{"id": "b", "name": "Bass Drop Brightness", "kind": "set",
                             "entries": [{"brightness": 0.5}]}])
    ask, calls = _drafter([])
    result = asyncio.run(color_meanings.draft(["b"], ask=ask))
    assert calls == [] and result["skipped"] == ["b"]


def test_too_many_cards_at_once_is_refused():
    ask, _ = _drafter([])
    with pytest.raises(color_meanings.DraftRefused):
        asyncio.run(color_meanings.draft([f"c{i}" for i in range(11)], ask=ask))


# ── the routes ──────────────────────────────────────────────────────────────

def test_the_page_route_reports_the_list_and_that_nothing_reads_automatically():
    body = _client().get("/api/sung-labels").json()
    assert body["auto_read"] is False
    assert body["n_labels"] > 0
    assert body["draft_batch_size"] == color_meanings.DRAFT_BATCH_SIZE
    assert body["claude"]["available"] is False


def test_the_edit_route_edits_and_answers_with_the_new_page():
    client = _client()
    body = client.post("/api/sung-labels/edit", json={
        "kind": "color_set", "id": "red1", "list": "moods", "op": "add", "text": "rage"}).json()
    assert "rage" in _texts(_row(body, "red1")["meanings"]["moods"])
    refused = client.post("/api/sung-labels/edit", json={
        "kind": "effect", "id": "nope", "list": "labels", "op": "add", "text": "x"})
    assert refused.status_code == 422


def test_the_draft_route_says_why_when_claude_is_not_set_up(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    response = _client().post("/api/sung-labels/draft", json={"ids": ["red1"]})
    assert response.status_code == 503
    assert "API key" in response.json()["detail"]


def test_automatic_reading_ships_off_and_can_be_switched():
    client = _client()
    assert sung_labels.auto_read_enabled() is False
    assert client.put("/api/sung-labels/settings", json={"auto_read": True}).json()["auto_read"] is True
    assert sung_labels.auto_read_enabled() is True
    stored = json.loads(scfg.SUNG_LABELS_FILE.read_text())
    assert stored["settings"]["auto_read"] is True
