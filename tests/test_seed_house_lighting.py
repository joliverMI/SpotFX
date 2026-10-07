"""scripts/seed_house_lighting.py — his starting content, written as data.

  * Dry run writes nothing; --apply adds exactly the content and nothing
    else: every pre-existing entry is byte-identical afterwards, the
    whole-file diff only ADDS lines, and each file is backed up first.
  * Idempotent; an entry he edited after seeding is kept, not clobbered.
  * EVERY Home Assistant lighting_mode value reaches the intended mode.
  * "Calm - Evening" is a group of COPIES: Calm's own members, fired by
    their own id, never pick up the evening background (the shared-member
    override trap, proven through the real resolver).
  * The house scenes breathe on the single-colour virtual only, carry no
    flares, and get no sequencer entry; every param is real.
  * House lighting is never switched on by seeding; the left-alone Hue
    bulbs are seeded; Night light holds no Hue at all.

A synthetic root shaped like his storage (his real Calm ids and entries);
never his live files.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.seed_house_lighting as seed

CALM = {
    "77426cff-a1ff-4e7c-8c0a-91028964270b": {
        "id": "77426cff-a1ff-4e7c-8c0a-91028964270b", "name": "Calm", "color": "#6b6b6b",
        "kind": "group", "labels": [], "display_mode": "default",
        "display_availability": "default",
        "entries": [
            {"scope": {"virtual_ids": [], "categories": ["Singles"], "roles": []},
             "color_kind": "solid", "color_value": "#ffd37d", "bg_color": "#ffd37d",
             "bg_mode": "overwrite", "brightness": 1.0, "background_brightness": 0.64,
             "accent_color": None, "ramp_ms": None},
            {"scope": {"virtual_ids": [], "categories": ["Matrix"], "roles": []},
             "color_kind": None, "color_value": None, "bg_color": "#ffcf46",
             "bg_mode": "overwrite", "brightness": 1.0, "background_brightness": 0.8,
             "accent_color": None, "ramp_ms": None}],
        "members": [{"color_set_id": "p", "weight": 1.0}, {"color_set_id": "g", "weight": 1.0},
                    {"color_set_id": "c", "weight": 1.0}],
        "mode": "cycle", "cycle_behavior": "wrap", "exclude_current": True,
        "dark_variant": None, "light_variant": None, "palette_sync": True,
        "scene_v2_opt_out": False, "disabled": False, "is_rainbow": False},
}


def _member(cid, name, grad):
    return {"id": cid, "name": name, "color": "#f8c8fe", "kind": "set",
            "labels": ["imported-colors"], "display_mode": "default",
            "display_availability": "default",
            "entries": [{"scope": {"virtual_ids": [], "categories": ["Strips and Matrix"],
                                   "roles": []},
                         "color_kind": "gradient", "color_value": grad, "bg_color": "#ff9940",
                         "bg_mode": "overwrite", "brightness": 1.0,
                         "background_brightness": 1.0, "accent_color": None, "ramp_ms": None}],
            "members": [], "mode": "cycle", "cycle_behavior": "wrap", "exclude_current": True,
            "dark_variant": None, "light_variant": None, "palette_sync": False,
            "scene_v2_opt_out": True, "disabled": False, "is_rainbow": False}


@pytest.fixture
def root(tmp_path):
    cards = {
        "p": _member("p", "Calm - Purple", "linear-gradient(90deg, #ff00b3 21.00%,#0000ff 100.00%)"),
        "g": _member("g", "Calm - Green", "linear-gradient(90deg, #00ff6e 21.00%,#00dcff 69.00%)"),
        "c": _member("c", "Calm - Cyan", "linear-gradient(90deg, #0058ff 17.00%,#00f1f9 67.00%)"),
        **CALM,
        "x": _member("x", "Unrelated", "#123456"),
    }
    scenes = {"s1": {"id": "s1", "name": "STAR", "devices": [], "labels": ["star"]}}
    (tmp_path / "storage" / "spectra").mkdir(parents=True)
    (tmp_path / "storage" / "color_sets.json").write_text(json.dumps(cards, indent=2))
    (tmp_path / "storage" / "spectra" / "scenes.json").write_text(json.dumps(scenes, indent=2))
    return tmp_path


def _files(root: Path):
    return {p: (root / p).read_text() if (root / p).exists() else None
            for p in ("storage/color_sets.json", "storage/spectra/scenes.json",
                      "storage/spectra/house_modes.json")}


def test_a_dry_run_writes_nothing(root):
    before = _files(root)
    assert seed.main(["--root", str(root)]) == 0
    assert _files(root) == before


def test_apply_adds_exactly_the_content_and_nothing_else(root):
    before = _files(root)
    plans = seed.plan(root)
    for p in plans:
        assert not [ln for ln in p.diff().splitlines()
                    if ln.startswith("-") and not ln.startswith("---")], \
            f"{p.path}: the whole-file diff must only add lines"
    backups = seed.apply(plans, root / "storage" / "spectra" / "backups")
    after = _files(root)
    cards_before = json.loads(before["storage/color_sets.json"])
    cards_after = json.loads(after["storage/color_sets.json"])
    for k, v in cards_before.items():
        assert json.dumps(cards_after[k], indent=2) == json.dumps(v, indent=2), k
    added = {v["name"] for k, v in cards_after.items() if k not in cards_before}
    assert added == {"Calm - Evening Purple", "Calm - Evening Green", "Calm - Evening Cyan",
                     "Calm - Evening", "Night Light"}
    scenes_after = json.loads(after["storage/spectra/scenes.json"])
    assert scenes_after["s1"] == json.loads(before["storage/spectra/scenes.json"])["s1"]
    assert {v["name"] for k, v in scenes_after.items() if k != "s1"} == {"House Star", "House Fish"}
    lib = json.loads(after["storage/spectra/house_modes.json"])
    assert [m["name"] for m in lib["modes"]] == [
        "Standard", "Evening", "Dim", "Night light", "Away", "TV", "TV paused"]
    assert {b.name.split("-pre-")[0] for b in backups} == {"color_sets", "scenes"}, \
        "both existing files backed up (house_modes.json did not exist)"
    for b in backups:
        assert b.read_text() in (before["storage/color_sets.json"],
                                 before["storage/spectra/scenes.json"])


def test_a_second_run_changes_nothing(root):
    seed.apply(seed.plan(root), root / "b")
    assert not any(p.changed for p in seed.plan(root))


def test_an_entry_he_edited_since_seeding_is_kept(root):
    seed.apply(seed.plan(root), root / "b")
    path = root / "storage" / "color_sets.json"
    cards = json.loads(path.read_text())
    nid = seed._sid("color-set", seed.NIGHT_SET)
    cards[nid]["entries"][0]["bg_color"] = "#000033"
    path.write_text(json.dumps(cards, indent=2))
    plans = seed.plan(root)
    assert plans[0].kept == ["Night Light"] and not plans[0].changed
    plans = seed.plan(root, overwrite=True)
    assert plans[0].updated == ["Night Light"]


@pytest.mark.parametrize("word,mode", [
    ("Daytime", "Standard"), ("Party", "Standard"), ("Evening", "Evening"), ("Dim", "Dim"),
    ("Bedtime", "Night light"), ("Travel", "Away"), ("Away", "Away"),
    ("TV", "TV"), ("TV paused", "TV paused"),
])
def test_every_home_assistant_word_reaches_its_mode(root, monkeypatch, word, mode):
    from spectra import config as scfg
    from spectra.services import house_store
    seed.apply(seed.plan(root), root / "b")
    monkeypatch.setattr(scfg, "HOUSE_MODES_FILE", root / "storage" / "spectra" / "house_modes.json")
    assert house_store.mode_for_ha(word).name == mode


def test_the_mapping_check_covers_every_lighting_mode_option(root):
    plans = seed.plan(root)
    assert seed.check_mapping(plans[2].after) == []
    assert set(seed.HA_LIGHTING_MODES) >= {"Daytime", "Evening", "Dim", "Bedtime", "Travel", "Party"}


def test_home_assistants_unknown_word_is_left_unmapped(root, monkeypatch):
    """An HA restart's "unknown" keeps the current mode — never Standard at 3am."""
    from spectra import config as scfg
    from spectra.services import house_store
    seed.apply(seed.plan(root), root / "b")
    monkeypatch.setattr(scfg, "HOUSE_MODES_FILE", root / "storage" / "spectra" / "house_modes.json")
    assert house_store.mode_for_ha("unknown") is None
    assert house_store.mode_for_ha("unavailable") is None


def test_evening_is_a_group_of_copies_so_calm_never_turns_red(root, monkeypatch):
    from spectra import config as scfg
    from spectra.services import color_set_groups, color_sets
    seed.apply(seed.plan(root), root / "b")
    monkeypatch.setattr(scfg, "COLOR_SETS_FILE", root / "storage" / "color_sets.json")
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", root / "room_controls.json")
    cards = {c.name: c for c in color_sets.list_all()}
    evening = cards["Calm - Evening"]
    assert {m.color_set_id for m in evening.members}.isdisjoint({"p", "g", "c"})
    for name in ("Calm - Evening Purple", "Calm - Evening Green", "Calm - Evening Cyan"):
        copy_ = cards[name]
        assert copy_.scene_v2_opt_out is True, "kept out of the music pools"
        assert all(e.bg_color == seed.EVENING_BG
                   and e.background_brightness == seed.EVENING_BG_BRIGHTNESS
                   for e in copy_.entries)
    # The trap: a set fired by its own id wears EVERY enclosing group's
    # overrides. Calm's members must resolve exactly as before.
    from fx import device_model
    vids = {"Strips and Matrix": ["tv-mapper", "crystal-mapper"], "Matrix": ["crystal-mapper"],
            "Strips": ["tv-mapper"], "Singles": ["single-color-effect"]}
    monkeypatch.setattr(device_model, "resolve_scope",
                        lambda v, cats, r: [x for c in cats for x in vids.get(c, [])] + list(v))
    assert [g.name for g in color_set_groups._enclosing_groups_with_overrides("p")] == ["Calm"]
    purple = {e.scope.virtual_ids[0]: e
              for e in color_set_groups.resolve_for_fire(cards["Calm - Purple"]).entries}
    assert purple["tv-mapper"].bg_color == "#ff9940"
    assert purple["crystal-mapper"].bg_color == "#ffcf46", "Calm's own Matrix override"
    assert purple["single-color-effect"].color_value == "#ffd37d"
    # And Evening's copies wear Evening's group overrides, not Calm's.
    eve = {e.scope.virtual_ids[0]: e
           for e in color_set_groups.resolve_for_fire(cards["Calm - Evening Purple"]).entries}
    assert eve["tv-mapper"].bg_color == seed.EVENING_BG
    assert eve["tv-mapper"].background_brightness == seed.EVENING_BG_BRIGHTNESS
    assert eve["single-color-effect"].color_value == "#ff8a3d"
    assert eve["crystal-mapper"].bg_color == "#ff5a1f"


def test_the_house_scenes_breathe_on_the_single_colour_virtual_only(root):
    scenes = seed.scene_entries()
    for s in scenes.values():
        breathing = [d for d in s["devices"] if d["effect_type"] == "gradient"]
        assert len(breathing) == 1
        assert breathing[0]["target_kind"] == "virtual"
        assert breathing[0]["target"] == "single-color-effect", "never the Hue virtual"
        assert breathing[0]["params"]["modulation_effect"] == "sine"
        assert not s["flare_kinds"] and not s["responses"], "nothing plays on them at rest"
        assert any(d["effect_type"] == "melt" and d["target"] == "Strips" for d in s["devices"])
    star = next(s for s in scenes.values() if s["name"] == "House Star")
    fish = next(s for s in scenes.values() if s["name"] == "House Fish")
    assert next(d for d in star["devices"] if d["target"] == "Matrix")["effect_type"] == "radial"
    f = next(d for d in fish["devices"] if d["target"] == "Matrix")
    assert f["effect_type"] == "fish" and f["params"]["particle_count"] == 3
    assert f["params"]["reactivity_scale"] == 0.0, "no music reaction"


def test_seeding_never_touches_the_sequencer(root):
    """No entry = the music engine never draws a house scene."""
    seq = root / "storage" / "spectra" / "sequencer.json"
    seq.write_text(json.dumps({"entries": {}}, indent=2))
    before = seq.read_text()
    seed.apply(seed.plan(root), root / "b")
    assert seq.read_text() == before
    assert all(str(p.path).endswith(("color_sets.json", "scenes.json", "house_modes.json"))
               for p in seed.plan(root))


def test_a_typo_in_a_param_is_refused(monkeypatch):
    bad = {"name": "X", "devices": [{"effect_type": "radial", "params": {"spinn": 1}}]}
    with pytest.raises(seed.SeedError, match="spinn"):
        seed._check_params(bad)


def test_it_refuses_when_calms_members_are_not_the_three_it_copies(root):
    path = root / "storage" / "color_sets.json"
    cards = json.loads(path.read_text())
    cards["77426cff-a1ff-4e7c-8c0a-91028964270b"]["members"].append(
        {"color_set_id": "x", "weight": 1.0})
    path.write_text(json.dumps(cards, indent=2))
    with pytest.raises(seed.SeedError, match="refusing to guess"):
        seed.plan(root)


def test_it_refuses_a_file_not_in_the_stores_own_layout(root):
    path = root / "storage" / "color_sets.json"
    path.write_text(json.dumps(json.loads(path.read_text())))      # one line
    with pytest.raises(seed.SeedError, match="layout"):
        seed.plan(root)


def test_seeding_leaves_house_lighting_off_and_touches_no_bulb_exclusion(root):
    seed.apply(seed.plan(root), root / "b")
    lib = json.loads((root / "storage/spectra/house_modes.json").read_text())
    assert lib["settings"]["enabled"] is False
    assert lib["settings"]["hue_excluded_lights"] == [], \
        "every Hue bulb in Spectra's entertainment areas is an ordinary bulb; " \
        "the seeder never excludes one"
    night = next(m for m in lib["modes"] if m["name"] == "Night light")
    assert all(h["look"] == "off" for h in night["hue"]), "Night light lights no Hue at all"
    assert night["music"] == "ignore"


def test_a_list_he_already_set_is_kept(root):
    from spectra.models.house_mode import HouseLibrary, HouseSettings
    path = root / "storage/spectra/house_modes.json"
    path.write_text(json.dumps(HouseLibrary(settings=HouseSettings(
        enabled=True, hue_excluded_lights=["Ledge Left"])).model_dump(), indent=2))
    seed.apply(seed.plan(root), root / "b")
    lib = json.loads(path.read_text())
    assert lib["settings"]["hue_excluded_lights"] == ["Ledge Left"]
    assert lib["settings"]["enabled"] is True, "his switch is his"


def test_the_modes_validate_against_the_seeded_scenes_and_sets(root, monkeypatch):
    from spectra import config as scfg
    from spectra.api import house as api
    from spectra.services import house_store
    seed.apply(seed.plan(root), root / "b")
    monkeypatch.setattr(scfg, "COLOR_SETS_FILE", root / "storage" / "color_sets.json")
    monkeypatch.setattr(scfg, "SCENES_FILE", root / "storage" / "spectra" / "scenes.json")
    monkeypatch.setattr(scfg, "HOUSE_MODES_FILE", root / "storage" / "spectra" / "house_modes.json")
    for mode in house_store.list_modes():
        problems, _warnings = api.validate_mode(mode)
        assert problems == [], (mode.name, problems)
