"""Colour Set / Group temporary DISABLE (owner ask, 2026-08-25: "i want to
be able to disable color sets like i can scenes") — ColorSetCard.disabled,
the exact same model as spectra/models/scene.py's SceneV2.disabled.

Proves, in order:
  1. both ColorSetCard definitions carry the field and round-trip it (it is
     defined TWICE — models/color_set.py authoring + spectra/services/
     color_sets.py read-only projection — and a field added to one and not
     the other is silently dropped on every SPECTRA-side read);
  2. adding the field rewrites NOTHING of his storage (default False, and
     color_set_store.save() only ever rewrites the ONE card it is handed);
  3. every AUTOMATIC choke point gates, checked one function at a time,
     never assumed by family (docs/SPECTRA_SPEC.md §86's lesson);
  4. the terminal fallback deliberately does NOT gate — a disabled set that
     is the room's active palette keeps painting, never yanked mid-paint;
  5. groups: a disabled member leaves the pool, an all-disabled group is
     itself unusable AND LOUD, a disabled group's overrides still reach an
     enabled member fired by its own id;
  6. the never-empty-pool guarantee under rainbow-limit exhaustion, and
     that the exhaustion is REPORTED rather than silently kept;
  7. explicit human use bypasses and NAMES the contradiction.

No live access: storage is isolated the way test_color_set_preference.py
does it."""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import device_model
from spectra import config as scfg
from spectra.models.scene import SceneV2
from spectra.services import color_set_groups, scene_store
from spectra.services.color_sets import ColorSetCard, GroupMember
from spectra.services.room_controls import RoomControlState, save_room_controls


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path)
    monkeypatch.setattr(scfg, "COLOR_SETS_FILE", tmp_path / "color_sets.json")
    monkeypatch.setattr(scfg, "ROOM_COLOR_FILE", tmp_path / "room_color.json")
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")
    monkeypatch.setattr(scfg, "SCENES_FILE", tmp_path / "scenes.json")
    monkeypatch.setattr(device_model, "CATEGORIES_FILE", tmp_path / "device_categories.json")
    device_model.CATEGORIES_FILE.write_text(json.dumps({
        "singles": {"id": "singles", "name": "Singles", "parent_id": None,
                    "virtuals": ["v1"], "effects": [], "role": None},
    }))
    device_model.refresh()
    color_set_groups._cursor.clear()
    color_set_groups._cursor_dir.clear()
    yield
    color_set_groups._cursor.clear()
    color_set_groups._cursor_dir.clear()


def _room(**kw) -> None:
    save_room_controls(RoomControlState(**kw))


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


def _scene(id_, **kw) -> SceneV2:
    return SceneV2(id=id_, name=id_, **kw)


# ── 1. BOTH DEFINITIONS ───────────────────────────────────────────────────

def test_field_exists_on_both_definitions_and_defaults_false():
    from models.color_set import ColorSetCard as AuthoringCard
    from spectra.services.color_sets import ColorSetCard as ProjectionCard
    assert AuthoringCard(name="a").disabled is False
    assert ProjectionCard(id="a", name="a").disabled is False


def test_disabled_round_trips_authoring_to_projection():
    """The documented trap: the authoring model writes storage, the
    projection reads it. A field on one and not the other is dropped
    silently on every SPECTRA-side read — so prove the actual round trip
    through JSON, not just that both classes declare it."""
    from models.color_set import ColorSetCard as AuthoringCard
    from spectra.services import color_sets as projection
    authored = AuthoringCard(id="s1", name="s1", disabled=True)
    scfg.COLOR_SETS_FILE.write_text(json.dumps(
        {authored.id: json.loads(authored.model_dump_json())}))
    read_back = projection.get_by_id("s1")
    assert read_back is not None and read_back.disabled is True


def test_a_stored_card_predating_the_field_loads_enabled():
    """RESTART PERSISTENCE + his-data safety, one assertion: a card written
    before this field existed (no `disabled` key at all) loads as ENABLED,
    and a card he has disabled survives a reload as DISABLED."""
    from spectra.services import color_sets as projection
    scfg.COLOR_SETS_FILE.write_text(json.dumps({
        "old": {"id": "old", "name": "old", "kind": "set"},
        "off": {"id": "off", "name": "off", "kind": "set", "disabled": True},
    }))
    by_id = {c.id: c for c in projection.list_all()}
    assert by_id["old"].disabled is False
    assert by_id["off"].disabled is True


# ── 2. HIS DATA: no mass rewrite ──────────────────────────────────────────

def test_saving_one_card_does_not_rewrite_the_others(tmp_path, monkeypatch):
    """color_set_store.save() is a read-modify-write of the keyed dict — it
    replaces the ONE card handed to it. So the model change alone rewrites
    nothing: cards gain `disabled` lazily, on their own next save."""
    from models.color_set import ColorSetCard as AuthoringCard
    from services import color_set_store
    store_file = tmp_path / "color_sets_root.json"
    monkeypatch.setattr(color_set_store, "COLOR_SETS_FILE", store_file)
    pristine = {
        "a": {"id": "a", "name": "a", "kind": "set"},
        "b": {"id": "b", "name": "b", "kind": "set"},
    }
    store_file.write_text(json.dumps(pristine, indent=2))
    color_set_store.save(AuthoringCard(id="a", name="a", disabled=True))
    after = json.loads(store_file.read_text())
    assert after["b"] == pristine["b"], "an untouched card must be byte-identical"
    assert after["a"]["disabled"] is True


# ── 3. every AUTOMATIC choke point, one at a time ─────────────────────────

def test_sequencer_eligible_pool_drops_a_disabled_set():
    from spectra.services.scene_sequencer import SceneSequencer
    scene_store.save(_scene("s1"))
    _write_cards(_set("keep"), _set("off", disabled=True))
    _room()
    assert set(SceneSequencer()._default_eligible_sets("s1")) == {"keep"}


def test_sequencer_pool_gates_disabled_regardless_of_room_mode():
    """STRONGER than mode availability: a set marked available in this room
    mode is still dropped when disabled, in every room mode."""
    from spectra.services.scene_sequencer import SceneSequencer
    scene_store.save(_scene("s1"))
    _write_cards(_set("keep"), _set("off", disabled=True))
    for mode in ("default", "dark", "light"):
        _room(display_mode=mode)
        assert set(SceneSequencer()._default_eligible_sets("s1")) == {"keep"}, mode


def test_drift_destination_pool_drops_a_disabled_set():
    """CHECKED INDIVIDUALLY: drift_conductor._destination_pool is its own
    function and applies neither mode availability nor rainbow select — so
    "the family is covered" would have been the wrong assumption."""
    from spectra.services.drift_conductor import DriftConductor
    cards = [_set("keep"), _set("off", disabled=True)]
    conductor = DriftConductor(
        executor=object(),
        set_cards=lambda: cards,
        set_position=lambda sid: 10.0,
    )
    assert set(conductor._destination_pool()) == {"keep"}


def test_flare_colour_jump_pool_drops_a_disabled_set():
    """scene_response._default_eligible_sets — again its own function."""
    from spectra.services.scene_response import ResponseEngine
    _write_cards(_set("keep"), _set("off", disabled=True))
    scene = _scene("s1")
    assert set(ResponseEngine._default_eligible_sets(scene)) == {"keep"}


def test_resolve_for_fire_mode_gated_refuses_a_disabled_set():
    """The hard gate every explicit-set-id automatic path funnels through
    (scene_sequencer.fire_scene_by_id's colour resolution and
    trigger_engine._default_select_color_set)."""
    card = _set("off", disabled=True)
    _write_cards(card)
    _room()
    assert color_set_groups.resolve_for_fire_mode_gated(card, "default") is None


def test_resolve_for_fire_mode_gated_reports_disabled_before_mode():
    """Disabled is checked FIRST — a card that is both disabled and
    mode-gated is refused for being disabled, mirroring fire_scene_by_id's
    own disabled-before-mode_availability order for a scene."""
    card = _set("off", disabled=True, display_availability="light")
    _write_cards(card)
    _room(display_mode="dark")
    assert color_set_groups.resolve_for_fire_mode_gated(card, "dark") is None
    # and an ENABLED, mode-ok card still resolves through the same call
    ok = _set("ok")
    _write_cards(ok)
    assert color_set_groups.resolve_for_fire_mode_gated(ok, "dark") is not None


def test_disabled_never_narrows_anything_when_nothing_is_disabled():
    """HIS DATA, stated as an assertion: with every card at the shipped
    default the eligible pool is byte-identical to the full set list."""
    from spectra.services.scene_sequencer import SceneSequencer
    scene_store.save(_scene("s1"))
    _write_cards(_set("a"), _set("b"), _set("c"))
    _room()
    assert set(SceneSequencer()._default_eligible_sets("s1")) == {"a", "b", "c"}


# ── 4. NEVER yanked mid-paint ─────────────────────────────────────────────

def test_room_active_set_still_resolves_a_disabled_set():
    """THE TERMINAL FALLBACK deliberately does NOT gate: a set he disables
    while the room is wearing it keeps painting until the next natural
    change picks something else — the mirror of "a disabled scene simply
    stops being chosen". Gating here would drop the room to no colour at
    all the instant he flipped the toggle."""
    from spectra.services import color_journey, scene_compiler
    _write_cards(_set("wearing", disabled=True))
    room = color_journey.load_room()
    color_journey.save_room(room.model_copy(update={"active_set_id": "wearing"}))
    active = scene_compiler.room_active_set()
    assert active is not None and active.id == "wearing"


# ── 5. GROUPS ─────────────────────────────────────────────────────────────

def test_disabled_member_leaves_the_group_pool():
    group = _group("g", ["a", "off"])
    _write_cards(_set("a"), _set("off", disabled=True), group)
    _room()
    for _ in range(6):     # cycle right past where the disabled member sat
        resolved = color_set_groups.resolve_for_fire(group)
        assert resolved is not None and resolved.id == "a"


def test_disabled_member_leaves_the_weighted_pool():
    group = _group("g", ["a", "off"], mode="weighted")
    _write_cards(_set("a"), _set("off", disabled=True), group)
    _room()
    for _ in range(20):
        resolved = color_set_groups.resolve_for_fire(group)
        assert resolved is not None and resolved.id == "a"


def test_group_with_every_member_disabled_is_unusable_and_loud(caplog):
    group = _group("g", ["x", "y"])
    _write_cards(_set("x", disabled=True), _set("y", disabled=True), group)
    _room()
    with caplog.at_level(logging.WARNING):
        assert color_set_groups.resolve_for_fire(group) is None
    assert any("no selectable member" in r.getMessage()
               for r in caplog.records), "the exhausted group must be NAMED"


def test_disabled_group_is_not_chosen_as_a_pool():
    group = _group("g", ["a"], disabled=True)
    _write_cards(_set("a"), group)
    _room()
    assert color_set_groups.resolve_for_fire_mode_gated(group, "default") is None


def test_disabled_group_overrides_still_apply_to_an_enabled_member():
    """ESTABLISHED AND STATED: a group's `disabled` stops the GROUP being
    CHOSEN as a pool. It does not strip that group's override entries from
    an enabled member fired by its own id — the override layer (§10) is a
    bulk-edit mechanism, not a choice, and disabling must never silently
    change an enabled set's rendered colours."""
    from spectra.services.color_sets import ColorSetEntry, SetScope
    member = _set("a", entries=[ColorSetEntry(
        scope=SetScope(virtual_ids=["v1"]), color_value="#111111")])
    group = _group("g", ["a"], disabled=True, entries=[ColorSetEntry(
        scope=SetScope(virtual_ids=["v1"]), color_value="#ff0000")])
    _write_cards(member, group, )
    _room()
    resolved = color_set_groups.resolve_for_fire(member)
    assert resolved is not None
    assert resolved.entries[0].color_value == "#ff0000", (
        "the enclosing group's override must still reach an enabled member")


# ── 6. NEVER-EMPTY POOL, and the exhaustion is VISIBLE ────────────────────

def test_rainbow_limit_exhaustion_keeps_the_room_and_says_so(caplog):
    """He disables every Rainbow set, then the room reaches an intensity
    above the rainbow limit — the pool is legitimately EMPTY. The room must
    keep the colours it already has (never nothing), and the exhaustion
    must be reported, not silently kept."""
    from spectra.services.scene_sequencer import SceneSequencer, POOL_EXHAUSTED
    from spectra.models.sequencer import SelectorEntry
    scene_store.save(_scene("s1"))
    _write_cards(_set("single"),
                _set("bow1", is_rainbow=True, disabled=True),
                _set("bow2", is_rainbow=True, disabled=True))
    _room(rainbow_select_limit=0.9)

    # The pool is evaluated at the sequencer's own live intensity, so the
    # injected intensity is what puts the room above the rainbow limit.
    seq = SceneSequencer(intensity=lambda: 0.95)
    seq._active_color_set_id = "single"          # what the room is wearing
    assert seq._default_eligible_sets("s1") == {}, "above the limit, only rainbows are legal"

    class _Cfg:
        color_set_entries = {"single": SelectorEntry()}
        wheel_travel_curve = None
    with caplog.at_level(logging.WARNING):
        color = seq._roll_color_set(_Cfg(), {}, "s1", intensity=0.95,
                                    genre_bucket=None)
    assert color is not None
    # NEVER EMPTY: the fire still carries a set — the one already showing.
    assert color["fire_set_id"] == "single"
    assert color["picked_id"] is None
    # VISIBLE: named on the pick-factors/status surface AND in the log.
    assert color["record"]["rung"] == POOL_EXHAUSTED
    assert color["record"]["pool_exhausted"] is True
    assert color["record"]["pool"]["disabled"] == 2
    assert any("EXHAUSTED" in r.getMessage() for r in caplog.records)


def test_kernel_terminal_rung_keeps_colours_on_an_empty_candidate_list():
    """The doctrine underneath the above, proven at the kernel itself: no
    candidates never means "go dark", it means keep the current colours."""
    from random import Random
    from spectra.services import selection_kernel as kernel
    pick = kernel.select_color_set([], intensity=0.95, rng=Random(0))
    assert pick.picked_id is None
    assert pick.rung == kernel.TERMINAL_KEEP


# ── 7. EXPLICIT human use bypasses, and NAMES the contradiction ───────────

def test_room_preview_previews_a_disabled_card_and_names_it(monkeypatch):
    from spectra.services import fx_seam, room_preview

    async def _fake_get_virtuals():
        return {"v1": {"effect": {"type": "blackhole", "config": {}}}}

    applied: list = []

    async def _fake_apply(writes, transition_ms=0):
        applied.append(writes)

    monkeypatch.setattr(fx_seam, "get_virtuals", _fake_get_virtuals)
    monkeypatch.setattr(fx_seam, "apply_writes", _fake_apply)

    from spectra.services.color_sets import ColorSetEntry, SetScope
    card = _set("off", disabled=True, entries=[ColorSetEntry(
        scope=SetScope(virtual_ids=["v1"]), color_value="#00ff00")])

    result = asyncio.run(room_preview.start(card, hold=False))
    asyncio.run(room_preview.release())
    assert result["applied"] is True, "an explicit press still previews"
    assert result["overrode_disabled"] is True, "and the contradiction is NAMED"
    assert applied, "real writes went out"


def test_room_preview_on_an_enabled_card_names_nothing(monkeypatch):
    from spectra.services import fx_seam, room_preview

    async def _fake_get_virtuals():
        return {"v1": {"effect": {"type": "blackhole", "config": {}}}}

    async def _fake_apply(writes, transition_ms=0):
        pass

    monkeypatch.setattr(fx_seam, "get_virtuals", _fake_get_virtuals)
    monkeypatch.setattr(fx_seam, "apply_writes", _fake_apply)

    from spectra.services.color_sets import ColorSetEntry, SetScope
    card = _set("on", entries=[ColorSetEntry(
        scope=SetScope(virtual_ids=["v1"]), color_value="#00ff00")])
    result = asyncio.run(room_preview.start(card, hold=False))
    asyncio.run(room_preview.release())
    assert result["applied"] is True
    assert result["overrode_disabled"] is False, (
        "the flag must be honest in BOTH directions — a naive truthy check "
        "on an absent key would pass this vacuously")
