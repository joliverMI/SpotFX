"""spectra.services.color_set_groups — day-one bar item §10 ("Colour Set
Groups: rotating/synced pools", docs/SPECTRA_SPEC.md). Proves the pick logic
(cycle wrap/bounce, weighted+exclude_current, Palette Sync anchoring against
SPECTRA's own room-colour state) and the override-entries merge against his
8 real authored groups' shape (storage/color_sets.json, read live
2026-08-15) — every one of them mode="cycle", exclude_current=True,
palette_sync=True, 5/8 with real override entries. No live access: storage
is a tmp file per test, isolated the same way scripts/check_spectra.py
isolates it (scfg.COLOR_SETS_FILE / scfg.ROOM_COLOR_FILE repointed)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import device_model
from spectra import config as scfg
from spectra.services import color_set_groups as csg
from spectra.services import color_journey
from spectra.services.color_journey import RoomColorState
from spectra.services.color_sets import ColorSetCard, ColorSetEntry, GroupMember, SetScope


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(scfg, "COLOR_SETS_FILE", tmp_path / "color_sets.json")
    monkeypatch.setattr(scfg, "ROOM_COLOR_FILE", tmp_path / "room_color.json")
    monkeypatch.setattr(device_model, "CATEGORIES_FILE", tmp_path / "device_categories.json")
    device_model.CATEGORIES_FILE.write_text(json.dumps({
        "singles": {"id": "singles", "name": "Singles", "parent_id": None,
                    "virtuals": ["v1"], "effects": [], "role": None},
        "matrix": {"id": "matrix", "name": "Matrix", "parent_id": None,
                   "virtuals": ["v2"], "effects": [], "role": None},
    }))
    device_model.refresh()
    csg._cursor.clear()
    csg._cursor_dir.clear()
    yield
    csg._cursor.clear()
    csg._cursor_dir.clear()


def _write_cards(*cards: ColorSetCard) -> None:
    scfg.COLOR_SETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    scfg.COLOR_SETS_FILE.write_text(json.dumps(
        {c.id: json.loads(c.model_dump_json()) for c in cards}))


def _set(id_, **kw) -> ColorSetCard:
    return ColorSetCard(id=id_, name=id_, kind="set", **kw)


def _group(id_, member_ids, **kw) -> ColorSetCard:
    return ColorSetCard(id=id_, name=id_, kind="group",
                        members=[GroupMember(color_set_id=m) for m in member_ids],
                        **kw)


# ── pass-through / failure paths ─────────────────────────────────────────────

def test_a_set_card_passes_through_unchanged():
    card = _set("s1")
    assert csg.resolve_for_fire(card) is card


def test_empty_group_resolves_to_none():
    group = _group("g1", [])
    assert csg.resolve_for_fire(group) is None


def test_group_with_only_stale_members_resolves_to_none():
    _write_cards(_set("s1"))
    group = _group("g1", ["does-not-exist"])
    assert csg.resolve_for_fire(group) is None


def test_group_member_that_is_itself_a_group_is_rejected():
    inner = _group("inner", [])
    outer = _group("g1", ["inner"])
    _write_cards(inner, outer)
    assert csg.resolve_for_fire(outer) is None


def test_resolve_ref_raises_on_unknown_id():
    with pytest.raises(ValueError, match="not found"):
        csg.resolve_ref("nope")


def test_resolve_ref_raises_on_unusable_group():
    _write_cards(_group("g1", []))
    with pytest.raises(ValueError, match="no usable member"):
        csg.resolve_ref("g1")


def test_resolve_ref_returns_the_set_itself():
    _write_cards(_set("s1"))
    assert csg.resolve_ref("s1").id == "s1"


# ── cycle: wrap ───────────────────────────────────────────────────────────────

def test_cycle_wrap_advances_sequentially_and_wraps():
    _write_cards(_set("a"), _set("b"), _set("c"))
    group = _group("g1", ["a", "b", "c"], mode="cycle", cycle_behavior="wrap",
                   palette_sync=False)
    picks = [csg.resolve_for_fire(group).id for _ in range(5)]
    assert picks == ["a", "b", "c", "a", "b"]


def test_cycle_wrap_two_members_alternates():
    _write_cards(_set("a"), _set("b"))
    group = _group("g1", ["a", "b"], mode="cycle", cycle_behavior="wrap",
                   palette_sync=False)
    picks = [csg.resolve_for_fire(group).id for _ in range(4)]
    assert picks == ["a", "b", "a", "b"]


# ── cycle: bounce ─────────────────────────────────────────────────────────────

def test_cycle_bounce_reverses_at_the_ends():
    _write_cards(_set("a"), _set("b"), _set("c"))
    group = _group("g1", ["a", "b", "c"], mode="cycle", cycle_behavior="bounce",
                   palette_sync=False)
    picks = [csg.resolve_for_fire(group).id for _ in range(6)]
    # a -> b -> c -> b -> a -> b  (reflect at each end, never repeat cur)
    assert picks == ["a", "b", "c", "b", "a", "b"]


def test_cycle_bounce_never_settles_on_the_showing_member():
    _write_cards(*[_set(f"s{i}") for i in range(4)])
    group = _group("g1", [f"s{i}" for i in range(4)], mode="cycle",
                   cycle_behavior="bounce", palette_sync=False)
    prev = None
    for _ in range(12):
        picked = csg.resolve_for_fire(group).id
        assert picked != prev
        prev = picked


def test_cycle_bounce_single_member_never_advances():
    _write_cards(_set("only"))
    group = _group("g1", ["only"], mode="cycle", cycle_behavior="bounce",
                   palette_sync=False)
    picks = [csg.resolve_for_fire(group).id for _ in range(3)]
    assert picks == ["only", "only", "only"]


# ── weighted ──────────────────────────────────────────────────────────────────

def test_weighted_zero_weight_members_never_picked():
    _write_cards(_set("a"), _set("b"))
    group = _group("g1", ["a", "b"], mode="weighted", palette_sync=False)
    group.members[1].weight = 0.0
    picks = {csg.resolve_for_fire(group).id for _ in range(20)}
    assert picks == {"a"}


def test_weighted_exclude_current_avoids_repeats_when_possible():
    _write_cards(_set("a"), _set("b"))
    group = _group("g1", ["a", "b"], mode="weighted", exclude_current=True,
                   palette_sync=False)
    picks = [csg.resolve_for_fire(group).id for _ in range(10)]
    for prev, cur in zip(picks, picks[1:]):
        assert prev != cur


def test_weighted_exclude_current_single_member_still_fires():
    # A single member: excluding "current" would zero out the ONLY weight,
    # so the fallback ladder (all-zero -> raw weights) must re-include it —
    # a group of one is never a lockout.
    _write_cards(_set("only"))
    group = _group("g1", ["only"], mode="weighted", exclude_current=True,
                   palette_sync=False)
    picks = [csg.resolve_for_fire(group).id for _ in range(3)]
    assert picks == ["only", "only", "only"]


def test_weighted_exclude_current_false_allows_immediate_repeats():
    _write_cards(_set("a"), _set("b"))
    group = _group("g1", ["a", "b"], mode="weighted", exclude_current=False,
                   palette_sync=False)
    group.members[1].weight = 0.0  # deterministic: "a" is the only live weight
    picks = [csg.resolve_for_fire(group).id for _ in range(5)]
    assert picks == ["a", "a", "a", "a", "a"]


# ── palette sync ──────────────────────────────────────────────────────────────

def test_palette_sync_anchors_on_the_rooms_active_set_when_its_a_member():
    _write_cards(_set("a"), _set("b"), _set("c"))
    color_journey.save_room(RoomColorState(active_set_id="c"))
    group = _group("g1", ["a", "b", "c"], mode="cycle", cycle_behavior="wrap",
                   palette_sync=True)
    # anchors at index of "c" (2), then advances from there.
    assert csg.resolve_for_fire(group).id == "a"  # (2+1) % 3 == 0 -> "a"


def test_palette_sync_anchors_on_nearest_wheel_hue_when_not_a_member():
    # "a" is red (0deg), "b" is green (~120deg) — room sits near red.
    a = _set("a", entries=[ColorSetEntry(color_kind="solid", color_value="#ff0000")])
    b = _set("b", entries=[ColorSetEntry(color_kind="solid", color_value="#00ff00")])
    _write_cards(a, b)
    color_journey.save_room(RoomColorState(active_set_id="not-a-member",
                                           wheel_position_deg=5.0))
    group = _group("g1", ["a", "b"], mode="cycle", cycle_behavior="wrap",
                   palette_sync=True)
    # anchors at "a" (nearest hue), advances to "b".
    assert csg.resolve_for_fire(group).id == "b"


def test_palette_sync_falls_back_to_private_cursor_with_no_room_anchor():
    _write_cards(_set("a"), _set("b"))
    color_journey.save_room(RoomColorState())  # no active_set_id, no wheel position
    group = _group("g1", ["a", "b"], mode="cycle", cycle_behavior="wrap",
                   palette_sync=True)
    picks = [csg.resolve_for_fire(group).id for _ in range(3)]
    assert picks == ["a", "b", "a"]


def test_palette_sync_reanchor_does_not_repeat_the_rooms_current_set():
    _write_cards(_set("a"), _set("b"), _set("c"))
    color_journey.save_room(RoomColorState(active_set_id="b"))
    group = _group("g1", ["a", "b", "c"], mode="cycle", cycle_behavior="bounce",
                   palette_sync=True)
    picked = csg.resolve_for_fire(group).id
    assert picked != "b"


# ── override-entries merge ───────────────────────────────────────────────────

def test_group_overrides_layer_onto_the_picked_member_per_virtual():
    member = _set("m1", entries=[
        ColorSetEntry(scope=SetScope(categories=["Singles"]),
                      color_kind="solid", color_value="#ff0000", brightness=0.5),
        ColorSetEntry(scope=SetScope(categories=["Matrix"]),
                      color_kind="solid", color_value="#00ff00"),
    ])
    group = _group("g1", ["m1"], palette_sync=False, entries=[
        # Overrides brightness on v1 only; leaves color_value alone.
        ColorSetEntry(scope=SetScope(categories=["Singles"]), brightness=0.9),
    ])
    _write_cards(member, group)
    resolved = csg.resolve_for_fire(group)
    assert resolved.id == "m1"  # wheel/active_set_id tracking uses the real member id
    by_vid = {e.scope.virtual_ids[0]: e for e in resolved.entries}
    assert by_vid["v1"].color_value == "#ff0000"   # kept from the member
    assert by_vid["v1"].brightness == 0.9          # group override wins
    assert by_vid["v2"].color_value == "#00ff00"   # untouched virtual passes through


def test_group_overrides_reach_virtuals_the_member_does_not_cover():
    member = _set("m1", entries=[
        ColorSetEntry(scope=SetScope(categories=["Singles"]), color_value="#ff0000"),
    ])
    group = _group("g1", ["m1"], palette_sync=False, entries=[
        ColorSetEntry(scope=SetScope(categories=["Matrix"]), background_brightness=0.2),
    ])
    _write_cards(member, group)
    resolved = csg.resolve_for_fire(group)
    by_vid = {e.scope.virtual_ids[0]: e for e in resolved.entries}
    assert by_vid["v2"].background_brightness == 0.2   # group-only virtual still lands
    assert by_vid["v1"].color_value == "#ff0000"        # member's own coverage survives


def test_no_group_overrides_returns_the_member_unmodified():
    member = _set("m1", entries=[ColorSetEntry(color_value="#ff0000")])
    group = _group("g1", ["m1"], palette_sync=False)
    _write_cards(member, group)
    resolved = csg.resolve_for_fire(group)
    assert resolved == member   # re-fetched from storage, not the same object — content match
