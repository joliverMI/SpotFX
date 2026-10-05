"""SONIC'S HOUSE LIGHTING AUTHORITY (spectra/services/house_console.py).

  * The operations are in the dispatcher under domain "house" and nowhere
    else — no delete, no room take/release.
  * Names are never guessed: an unknown mode / scene / category / Hue area
    is REJECTED with close matches.
  * "Make Evening's crystal ten percent" is one call: a level on a category,
    upserted (a second call edits the same setting, never a duplicate).
  * Every edit goes through the model's own validation; a bad value is a
    rejection naming the field, and nothing is saved.
  * Switching mode is a person's pick (manual, source "sonic").
"""
from __future__ import annotations

import asyncio
import json

import pytest


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def lib(tmp_path, monkeypatch):
    from spectra import config as scfg
    from spectra.models.scene import SceneV2
    from spectra.services import house, scene_store, show_output
    monkeypatch.setattr(scfg, "SCENES_FILE", tmp_path / "scenes.json")
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "rc.json")
    monkeypatch.setattr(scfg, "COLOR_SETS_FILE", tmp_path / "color_sets.json")
    (tmp_path / "color_sets.json").write_text(json.dumps({
        "calm": {"id": "calm", "name": "Calm", "kind": "group", "members": []},
        "eve": {"id": "eve", "name": "Calm - Evening", "kind": "set", "entries": []}}))
    for n in ("Star", "Fish"):
        scene_store.save(SceneV2(name=n))
    monkeypatch.setattr(house, "gate", lambda: ("refused", "the room is released"))
    monkeypatch.setattr(show_output, "list_targets",
                        lambda: {"live": False, "fixtures": [], "categories": []})
    from fx import device_model
    monkeypatch.setattr(device_model, "list_categories",
                        lambda: [{"name": "Matrix"}, {"name": "Strips"}, {"name": "Singles"}])
    from spectra.services import house_console as hc
    assert hc.OPERATIONS["create_house_mode"].handler("Evening", ["Evening"])["status"] == "applied"
    return hc


def _op(hc, op_name, /, **kw):
    res = hc.OPERATIONS[op_name].handler(**kw)
    return _run(res) if asyncio.iscoroutine(res) else res


def test_the_house_domain_is_registered_and_bounded():
    from spectra.services import house_console as hc, settings_agent as sa
    assert set(hc.OPERATIONS) <= set(sa.ALL_OPERATIONS)
    assert {op.domain for op in hc.OPERATIONS.values()} == {"house"}
    assert not any("delete" in n or "release" in n or "take" in n for n in hc.OPERATIONS)


def test_creating_a_mode_never_overwrites_one(lib):
    res = _op(lib, "create_house_mode", name="evening")
    assert res["status"] == "rejected" and "already exists" in res["reason"]


def test_switching_mode_is_a_manual_pick_and_names_are_never_guessed(lib):
    from spectra.services import house_store
    res = _op(lib, "set_house_mode", mode="evening")
    assert res["status"] == "applied" and "holds until" in res["summary"]
    st = house_store.state()
    assert st.manual is True and st.source == "sonic"
    res = _op(lib, "set_house_mode", mode="Evenning")
    assert res["status"] == "rejected" and "Evening" in res["close_matches"]
    res = _op(lib, "set_house_mode", mode="none")
    assert res["status"] == "applied" and house_store.state().mode_id is None


def test_make_evenings_crystal_ten_percent_is_one_upserted_call(lib):
    from spectra.services import house_store
    res = _op(lib, "set_house_fixture", mode="Evening", target_kind="category",
              target_name="matrix", level=10)
    assert res["status"] == "applied" and "level 10" in res["summary"]
    _op(lib, "set_house_fixture", mode="Evening", target_kind="category",
        target_name="Matrix", fps=15)
    hooks = house_store.find_mode("Evening").fixtures
    assert len(hooks) == 1
    assert (hooks[0].target.id, hooks[0].level, hooks[0].fps) == ("Matrix", 10, 15)
    res = _op(lib, "set_house_fixture", mode="Evening", target_kind="category",
              target_name="Matrix", remove=True)
    assert res["status"] == "applied" and house_store.find_mode("Evening").fixtures == []


def test_the_music_level_is_one_more_field_of_the_same_setting(lib):
    """Phase 2: Spectra owns the WLEDs' own brightness, so 'the crystal at
    40% during music in Evening' is music_level on the same fixture row."""
    from spectra.services import house_store
    _op(lib, "set_house_fixture", mode="Evening", target_kind="category",
        target_name="Matrix", level=13)
    res = _op(lib, "set_house_fixture", mode="Evening", target_kind="category",
              target_name="Matrix", music_level=40)
    assert res["status"] == "applied" and "music_level 40" in res["summary"]
    hooks = house_store.find_mode("Evening").fixtures
    assert len(hooks) == 1 and (hooks[0].level, hooks[0].music_level) == (13, 40)


def test_an_unknown_category_and_an_unchecked_fixture_are_rejected(lib):
    res = _op(lib, "set_house_fixture", mode="Evening", target_kind="category",
              target_name="Matrx", level=10)
    assert res["status"] == "rejected" and "Matrix" in res["close_matches"]
    res = _op(lib, "set_house_fixture", mode="Evening", target_kind="fixture",
              target_name="crystal", level=10)
    assert res["status"] == "rejected" and "live room is down" in res["reason"]


def test_settings_go_through_the_models_own_validation(lib):
    from spectra.services import house_store
    res = _op(lib, "set_house_mode_setting", mode="Evening", key="music", value="ignore")
    assert res["status"] == "applied" and house_store.find_mode("Evening").music == "ignore"
    res = _op(lib, "set_house_mode_setting", mode="Evening", key="clock_glide_s", value=9999)
    assert res["status"] == "rejected"
    assert house_store.find_mode("Evening").transitions.clock_glide_s == 90
    res = _op(lib, "set_house_mode_setting", mode="Evening", key="bogus", value=1)
    assert res["status"] == "rejected"


def test_hue_looks_kelvin_or_colour_never_both(lib):
    from spectra.services import house_store
    res = _op(lib, "set_house_hue", mode="Evening", area="*", look="hold", kelvin=2000)
    assert res["status"] == "applied" and "2000 K" in res["summary"]
    assert house_store.find_mode("Evening").hue[0].mirek == 500
    res = _op(lib, "set_house_hue", mode="Evening", area="*", look="hold",
              kelvin=2000, color="#ff0000")
    assert res["status"] == "rejected"
    res = _op(lib, "set_house_hue", mode="Evening", area="*", look="remove")
    assert res["status"] == "applied" and house_store.find_mode("Evening").hue == []


def test_pools_are_set_by_exact_names(lib):
    from spectra.services import house_store
    res = _op(lib, "set_house_mode_pool", mode="Evening", pool="scenes",
              names=["star", "Fish"], weights=[2, 1])
    assert res["status"] == "applied"
    picks = house_store.find_mode("Evening").scenes
    assert [p.weight for p in picks] == [2.0, 1.0]
    res = _op(lib, "set_house_mode_pool", mode="Evening", pool="color_sets",
              names=["Calm - Evenin"])
    assert res["status"] == "rejected" and "Calm - Evening" in res["close_matches"]


def test_dispatch_reaches_a_house_operation():
    from spectra.services import settings_agent as sa
    res = _run(sa._dispatch("house_status", {}))
    assert res["phase"] == "inactive"
