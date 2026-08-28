"""ONLY THE DEVICES HE USES, by default — the /devices list cleanup.

His ask, verbatim: "we need go clean up the device list soon. only devices
i use should be visible on default. can show more with expansion tab."

The rule is spectra/services/device_usage.py's: a device is in use iff it
backs a virtual in room_topology.genuinely_driven_virtual_ids(). What is
proved here:

  * the split against a copy of HIS REAL fx-live config shape — all 21
    device/virtual relationships, byte-for-byte the ids and segment wiring
    read off the live config — lands 10 in use / 11 not, including the two
    load-bearing DUMMIES that must show and the eleven seed-machinery
    entries that must not;
  * the rule is LIVE, not a snapshot: saving a scene that targets a
    previously-unused device's virtual moves it into the default view on
    the next read, with nothing migrated;
  * an absent ground truth is never a restriction (a fresh install shows
    everything, never an empty page);
  * the duplicate flag is generic — same name + same type + backing
    nothing — and never fires on a device that is doing a job.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from spectra.models.scene import SceneDeviceConfig, SceneV2
from spectra.services import device_console, device_usage


# ── his real config shape, as read from the live fx-live config ─────────────
#
# (device id, type, config name, [virtual ids its segments back]) — the
# relationships that decide the split. Nothing else about a device matters
# to this rule, so nothing else is reproduced.
HIS_ROOM = [
    ("tv-backlight", "wled", "WLED", ["tv-backlight", "tv-mapper"]),
    ("porch-rail", "wled", "WLED", ["porch-rail", "single-color-effect"]),
    ("hue-lights", "hue", "Hue Lights", ["hue-lights", "hues"]),
    ("gap-matrix", "dummy", "gap-matrix", ["gap-matrix"]),
    ("gap-crystal-virt", "dummy", "gap-crystal-virt", ["gap-crystal-virt"]),
    ("gap-mapped", "dummy", "gap-mapped", ["gap-mapped"]),
    ("gap-crystal-mapper", "dummy", "gap-crystal-mapper",
     ["crystal-mapper", "gap-crystal-mapper"]),
    ("crystal", "wled", "WLED", ["crystal-mapper", "crystal"]),
    ("gap-actual-crystal-mapper", "dummy", "gap-actual-crystal-mapper",
     ["gap-actual-crystal-mapper"]),
    ("crystal-mapper-mask", "dummy", "crystal-mapper-mask",
     ["crystal-mapper-mask"]),
    ("crystal-mapper-foreground", "dummy", "crystal-mapper-foreground",
     ["crystal-mapper-foreground"]),
    ("crystal-mapper-background", "dummy", "crystal-mapper-background",
     ["crystal-mapper-background"]),
    ("radial-dummy", "dummy", "Radial Dummy", ["radial-dummy"]),
    ("dining-hues", "hue", "Dining Hues", ["dining-hues", "hues"]),
    ("single-color-effect-mask", "dummy", "single-color-effect-mask",
     ["single-color-effect-mask"]),
    ("single-color-effect-foreground", "dummy", "single-color-effect-foreground",
     ["single-color-effect-foreground"]),
    ("single-color-effect-background", "dummy", "single-color-effect-background",
     ["single-color-effect-background"]),
    ("sconce-kitchen-left", "wled", "Sconce, Kitchen, Left",
     ["tv-mapper", "sconce-kitchen-left", "sconce-kitchen-left-seg-0",
      "sconce-left-kitchen-seg-0"]),
    ("sconce-kitchen-left-1", "wled", "Sconce, Kitchen, Left",
     ["sconce-kitchen-left-1"]),
    ("sconce-kitchen-right", "wled", "Sconce, Kitchen, Right",
     ["tv-mapper", "sconce-kitchen-right-seg-0", "sconce-kitchen-right-seg-1",
      "sconce-kitchen-right"]),
    ("dining-table", "wled", "Dining Table",
     ["single-color-effect", "dining-table"]),
]

# What his live category registry actually imports — the whole ground truth
# in his real data today (zero stored scenes name a literal virtual).
HIS_DRIVEN = {"crystal-mapper", "dining-hues", "hue-lights", "hues",
              "radial-dummy", "single-color-effect", "tv-mapper"}

HIS_IN_USE = {"tv-backlight", "porch-rail", "hue-lights", "gap-crystal-mapper",
              "crystal", "radial-dummy", "dining-hues", "sconce-kitchen-left",
              "sconce-kitchen-right", "dining-table"}


def _entries():
    return [{"id": did, "type": typ, "config": {"name": name},
             "virtuals": list(virtuals)}
            for did, typ, name, virtuals in HIS_ROOM]


# ── the split, against his real config shape ────────────────────────────────

def test_his_real_room_splits_ten_in_use_eleven_not():
    out = device_usage.annotate(_entries(), HIS_DRIVEN)
    used = {e["id"] for e in out if e["in_use"]}
    assert used == HIS_IN_USE
    assert len(used) == 10
    assert len(out) - len(used) == 11
    assert device_usage.summary(out)["in_use"] == 10
    assert device_usage.summary(out)["not_in_use"] == 11


def test_the_two_load_bearing_dummies_show_and_the_seed_dummies_do_not():
    """Type is never consulted. Two dummies are genuinely driven —
    gap-crystal-mapper sits in the crystal mapper chain and radial-dummy
    backs a real category virtual — while eight other dummies back
    nothing. A rule that keyed on 'dummy' would get both halves wrong."""
    by_id = {e["id"]: e for e in device_usage.annotate(_entries(), HIS_DRIVEN)}
    assert by_id["gap-crystal-mapper"]["in_use"] is True
    assert by_id["radial-dummy"]["in_use"] is True
    for seed in ("gap-matrix", "gap-crystal-virt", "gap-mapped",
                 "gap-actual-crystal-mapper", "crystal-mapper-mask",
                 "crystal-mapper-foreground", "crystal-mapper-background",
                 "single-color-effect-mask", "single-color-effect-foreground",
                 "single-color-effect-background"):
        assert by_id[seed]["in_use"] is False, seed


def test_the_duplicate_is_flagged_generically_and_points_at_the_live_one():
    by_id = {e["id"]: e for e in device_usage.annotate(_entries(), HIS_DRIVEN)}
    assert by_id["sconce-kitchen-left-1"]["duplicate_of"] == "sconce-kitchen-left"
    # the twin that IS doing a job is never called a duplicate of anything
    assert by_id["sconce-kitchen-left"]["duplicate_of"] is None
    # and no unrelated device picks up the flag
    assert [e["id"] for e in by_id.values() if e["duplicate_of"]] == \
        ["sconce-kitchen-left-1"]


def test_a_shared_name_on_a_different_type_is_not_a_duplicate():
    """Both 'WLED'-named devices in his room ARE in use, so neither is
    flagged; a same-name entry of a DIFFERENT type is not a duplicate
    either, even when it is unused."""
    entries = [
        {"id": "a", "type": "wled", "config": {"name": "Lamp"}, "virtuals": ["v"]},
        {"id": "b", "type": "dummy", "config": {"name": "Lamp"}, "virtuals": []},
    ]
    out = {e["id"]: e for e in device_usage.annotate(entries, {"v"})}
    assert out["b"]["in_use"] is False
    assert out["b"]["duplicate_of"] is None


# ── an absent ground truth is never a restriction ───────────────────────────

def test_no_ground_truth_shows_every_device_never_an_empty_page():
    out = device_usage.annotate(_entries(), set())
    assert all(e["in_use"] for e in out)
    assert device_usage.summary(out)["not_in_use"] == 0


# ── the rule is LIVE, through the real listing, end to end ──────────────────

def _write_his_config(monkeypatch, tmp_path):
    from spectra import config as scfg
    d = tmp_path / "fx-live"
    d.mkdir(parents=True, exist_ok=True)
    virtual_ids = sorted({v for _, _, _, vs in HIS_ROOM for v in vs})
    virtuals = [
        {"id": vid,
         "segments": [[did, 0, 10, False] for did, _, _, vs in HIS_ROOM
                      if vid in vs]}
        for vid in virtual_ids
    ]
    (d / "config.json").write_text(json.dumps({
        "devices": [{"id": did, "type": typ, "config": {"name": name}}
                    for did, typ, name, _ in HIS_ROOM],
        "virtuals": virtuals,
    }), encoding="utf-8")
    monkeypatch.setattr(scfg, "FX_LIVE_CONFIG_DIR", d)


@pytest.fixture
def his_room(tmp_path, monkeypatch):
    """His config shape on disk, the stack down (the stored branch), and
    the ground truth pinned to a category-derived roster the way his real
    registry supplies it."""
    _write_his_config(monkeypatch, tmp_path)
    monkeypatch.setattr(device_console, "_live_host", lambda: None)
    monkeypatch.setattr("fx.device_model.get_all_virtual_ids",
                        lambda: sorted(HIS_DRIVEN))
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "SCENES_FILE", tmp_path / "scenes.json")
    return tmp_path


def _listing():
    return asyncio.run(device_console.list_devices())


def test_the_listing_carries_the_split_so_the_page_derives_nothing(his_room):
    data = _listing()
    assert data["source"] == "stored"
    assert {d["id"] for d in data["devices"] if d["in_use"]} == HIS_IN_USE
    assert data["usage"] == {"in_use": 10, "not_in_use": 11,
                             "rule": data["usage"]["rule"]}
    assert data["usage"]["rule"]
    # every device is still RETURNED — hiding is the page's default view,
    # not a server-side omission, so the expansion has something to show
    assert len(data["devices"]) == 21


def test_a_device_added_to_a_scene_joins_the_default_view_on_the_next_read(his_room):
    """The rule is computed at request time, so this needs no migration and
    no restart: save a scene naming a previously-unused virtual and its
    device is in use on the very next listing."""
    from spectra.services import scene_store

    before = {d["id"]: d["in_use"] for d in _listing()["devices"]}
    assert before["gap-matrix"] is False

    scene_store.save(SceneV2(name="Gap Matrix Test", devices=[
        SceneDeviceConfig(target_kind="virtual", target="gap-matrix",
                          effect_type="solid"),
    ]))

    after = {d["id"]: d["in_use"] for d in _listing()["devices"]}
    assert after["gap-matrix"] is True
    # and nothing else moved
    assert {k for k, v in after.items() if v} == HIS_IN_USE | {"gap-matrix"}
