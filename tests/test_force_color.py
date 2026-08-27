"""FORCE COLOUR (owner ask 2026-08-27) — offline proof.

Force Scene's twin one axis over: the room's colour stops changing and
stays on his pinned colour SET or GROUP. The mechanism, every gate, and
the precedence rulings live in spectra/services/force_color.py's module
docstring; this file proves them.

The proofs:
  1. DEFAULT OFF IS INERT — a fresh RoomControlState changes nothing at
     any choke point, and the field round-trips through storage.
  2. REDIRECT AT EVERY CHOKE POINT, each checked individually (§86's
     lesson): scene_sequencer.fire_scene_by_id, its _roll_color_set,
     scene_compiler.room_active_set, drift_conductor's journey hold + its
     bootstrap, scene_response._color_jump, and trigger_engine's
     select_color_set action.
  3. IMMEDIATE APPLY on enable/repin, with a stated outcome — and NOT on
     an unrelated field re-save.
  4. GROUP vs SET semantics: a Set pin is static; a Group pin keeps its
     own rotation live.
  5. PRECEDENCE vs the active 2D gradient — the pin wins, the gradient is
     untouched and resumes on release.
  6. PERSISTENCE across a reload.
  7. A DISABLED pin applies and is NAMED, never silently refused.
  8. His own explicit apply still works and names the override.

No LedFX I/O, no audio hardware, no live storage.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from fx import device_model
from spectra import config as scfg
from spectra.services import color_set_groups as csg
from spectra.services.color_sets import (ColorSetCard, ColorSetEntry, GroupMember,
                                         SetScope)


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path)
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")
    monkeypatch.setattr(scfg, "ROOM_COLOR_FILE", tmp_path / "room_color.json")
    monkeypatch.setattr(scfg, "SCENES_FILE", tmp_path / "scenes.json")
    monkeypatch.setattr(scfg, "COLOR_SETS_FILE", tmp_path / "color_sets.json")
    monkeypatch.setattr(scfg, "SEQUENCER_FILE", tmp_path / "sequencer.json")
    monkeypatch.setattr(device_model, "CATEGORIES_FILE", tmp_path / "device_categories.json")
    device_model.CATEGORIES_FILE.write_text(json.dumps({
        "singles": {"id": "singles", "name": "Singles", "parent_id": None,
                    "virtuals": ["v1"], "effects": [], "role": None},
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


def _set(id_, color="#112233", **kw) -> ColorSetCard:
    return ColorSetCard(
        id=id_, name=id_, kind="set",
        entries=[ColorSetEntry(scope=SetScope(virtual_ids=["v1"]),
                               color_value=color)],
        **kw)


def _group(id_, member_ids, **kw) -> ColorSetCard:
    return ColorSetCard(id=id_, name=id_, kind="group",
                        members=[GroupMember(color_set_id=m) for m in member_ids],
                        **kw)


def _pin(target_id, **extra):
    from spectra.services import room_controls as rc
    rc.save_room_controls(rc.RoomControlState(
        force_color_enabled=True, force_color_target_id=target_id, **extra))


# ── 1. default off is inert ──────────────────────────────────────────────────

def test_default_off_is_inert_everywhere():
    """The field's arrival changes nothing about his room: a fresh state
    reads as no pin at every entry point this feature has."""
    from spectra.services import force_color
    from spectra.services import room_controls as rc

    _write_cards(_set("s1"))
    st = rc.RoomControlState()
    assert st.force_color_enabled is False
    assert st.force_color_target_id is None
    assert force_color.pinned_id(st) is None
    assert force_color.pinned_card(st) is None
    assert force_color.active(st) is False
    assert force_color.overrode_disabled(st) is False

    # Enabled but with nothing picked yet is equally inert — an in-progress
    # edit must never blank the room's colour.
    half = rc.RoomControlState(force_color_enabled=True)
    assert force_color.pinned_id(half) is None
    assert force_color.active(half) is False


def test_a_pin_pointing_at_a_deleted_card_is_not_active():
    """Degrade gracefully, never colourless: an id that names no card falls
    through to the room's own selection rather than resolving to None and
    leaving a fire with no colour at all."""
    from spectra.services import force_color
    from spectra.services import room_controls as rc

    _write_cards(_set("s1"))
    st = rc.RoomControlState(force_color_enabled=True,
                             force_color_target_id="gone")
    assert force_color.active(st) is False
    assert force_color.pinned_card(st) is None


# ── 6. persistence ───────────────────────────────────────────────────────────

def test_the_pin_survives_a_reload():
    from spectra.services import room_controls as rc

    _write_cards(_set("s1"))
    rc.save_room_controls(rc.RoomControlState(force_color_enabled=True,
                                              force_color_target_id="s1"))
    reloaded = rc.load_room_controls()
    assert reloaded.force_color_enabled is True
    assert reloaded.force_color_target_id == "s1"


# ── 4. set vs group semantics ────────────────────────────────────────────────

def test_a_set_pin_is_static_and_a_group_pin_keeps_rotating():
    """His two halves, side by side. A SET pin resolves to the same card
    every fire. A GROUP pin resolves to its NEXT member every fire — a
    group pins the POOL, which is what a group is."""
    from spectra.services import force_color

    a, b = _set("a"), _set("b")
    _write_cards(a, b, _group("g", ["a", "b"]))

    _pin("a")
    assert [force_color.pinned_card().id for _ in range(4)] == ["a"] * 4

    _pin("g")
    rolled = [force_color.pinned_card().id for _ in range(4)]
    assert rolled == ["a", "b", "a", "b"], \
        "a pinned group keeps its own cycle rotation live"


def test_active_never_advances_a_pinned_groups_rotation():
    """LOAD-BEARING: active() runs on every conductor leg and every status
    poll. If it resolved the pin it would roll his colours on nothing but
    someone looking at the page."""
    from spectra.services import force_color

    _write_cards(_set("a"), _set("b"), _group("g", ["a", "b"]))
    _pin("g")
    for _ in range(20):
        assert force_color.active() is True
        assert force_color.pinned_id() == "g"
    assert force_color.pinned_card().id == "a", \
        "twenty active()/pinned_id() calls advanced the cursor zero times"


# ── 2. the choke points, each on its own ─────────────────────────────────────

def test_fire_scene_by_id_wears_the_pin_over_the_callers_own_choice(monkeypatch):
    """The scene-fire choke point every automatic pick funnels through —
    the pin replaces whatever colour set the caller resolved, and the
    result NAMES it."""
    from spectra.models.scene import SceneV2
    from spectra.services import dwell, scene_compiler, scene_store
    from spectra.services.scene_sequencer import fire_scene_by_id

    _write_cards(_set("requested"), _set("pinned"))
    scene = SceneV2(name="S")
    scene_store.save(scene)

    worn: list = []

    async def fake_fire_scene(sc, *, intensity=0.5, color_set=None,
                              dry_run=True, rng=None):
        worn.append(color_set.id if color_set is not None else None)
        return {"dry_run": dry_run, "intensity": intensity, "writes": [],
                "resolved_bindings": {}, "dice_rolls": {}}

    monkeypatch.setattr(scene_compiler, "fire_scene", fake_fire_scene)

    _pin("pinned")
    result = _run(fire_scene_by_id(scene.id, color_set_id="requested",
                                   intensity=0.7))
    assert worn[-1] == "pinned", "the pin replaces the caller's own colour set"
    assert result["forced_color"] == "pinned", "and the fire says so"

    dwell.reset()
    from spectra.services import room_controls as rc
    rc.save_room_controls(rc.RoomControlState())
    result = _run(fire_scene_by_id(scene.id, color_set_id="requested",
                                   intensity=0.7))
    assert worn[-1] == "requested", "pin off: unchanged behaviour"
    assert "forced_color" not in result


def test_room_active_set_the_terminal_fallback_returns_the_pin():
    """The path 100% of his real fire_scene triggers take (none carry an
    explicit color_set_id) — a pin that didn't reach here would be
    invisible on the fires that matter most."""
    from spectra.services import color_journey, scene_compiler

    _write_cards(_set("wearing"), _set("pinned"))
    color_journey.save_room(color_journey.load_room().model_copy(
        update={"active_set_id": "wearing"}))

    assert scene_compiler.room_active_set().id == "wearing"
    _pin("pinned")
    assert scene_compiler.room_active_set().id == "pinned"


def test_the_sequencers_colour_roll_short_circuits_and_says_why():
    """Rolling under a pin would be worse than pointless — _adopt_colors
    would re-anchor the room's WHEEL POSITION to a set that is never going
    to be worn, silently moving the journey that resumes on release."""
    from spectra.models.sequencer import SelectorEntry, SequencerConfig
    from spectra.services import scene_sequencer as ss

    _write_cards(_set("a"), _set("b"))
    seq = ss.SceneSequencer(
        eligible_sets=lambda _sid: {"a": 10.0, "b": 200.0},
        color_set_name=lambda sid: sid,
    )
    config = SequencerConfig(color_set_entries={"a": SelectorEntry(),
                                                "b": SelectorEntry()})

    unpinned = seq._roll_color_set(config, {}, "scene", 0.5, None)
    assert unpinned["record"]["rung"] != ss.FORCED_COLOR

    _pin("a")
    rolled = seq._roll_color_set(config, {}, "scene", 0.5, None)
    assert rolled["picked_id"] is None, "no selection ran at all"
    assert rolled["record"]["rung"] == ss.FORCED_COLOR, \
        "and the status strip says WHY nothing rolled"
    assert rolled["record"]["forced_color_id"] == "a"
    assert rolled["position_deg"] is None, "so nothing moves the room's wheel"


def test_a_select_color_set_trigger_redirects_and_names_the_override(monkeypatch):
    """A stored trigger firing is an AUTOMATIC path (he authored it
    earlier; he is not pressing a button now), so the pin wins — exactly
    the way Force Scene redirects a stored fire_scene trigger."""
    from spectra.services import engine, trigger_engine as te

    _write_cards(_set("authored"), _set("pinned"))

    applied: list = []

    class _FakeConductor:
        async def apply_set_directly(self, card, *, forced_from=None):
            applied.append((card.id, forced_from))
            return {"applied": card.id, "forced_from": forced_from}

    monkeypatch.setattr(engine, "conductor", _FakeConductor())
    eng = te.TriggerEngine()

    _pin("pinned")
    _run(eng._default_select_color_set("authored"))
    assert applied[-1] == ("pinned", "authored"), \
        "redirected to the pin, and the record names what it was redirected from"

    from spectra.services import room_controls as rc
    rc.save_room_controls(rc.RoomControlState())
    _run(eng._default_select_color_set("authored"))
    assert applied[-1] == ("authored", None), "pin off: unchanged behaviour"


def test_a_flare_colour_jump_draws_from_the_pin():
    """A flare's colour jump is an AUTOMATIC pick, so it lands the pin and
    the selector never runs — including on a room whose sequencer has no
    colour entries authored at all, the same "nothing was ever going to
    pick" shape Force Scene's passive-redirect gap was."""
    from spectra.models.scene import SceneV2
    from spectra.models.sequencer import SequencerConfig
    from spectra.services import color_journey
    from spectra.services.scene_response import ResponseEngine

    _write_cards(_set("pinned", color="#abcdef"))

    class _State:
        set_mode = True
        effect_type = "blackhole"
        gradient = "#000000"
        background_color = None

    class _Conductor:
        virtuals = {"v1": _State()}

    class _Executor:
        def __init__(self):
            self.writes = []

        async def glide(self, vid, effect_type, params, ms):
            self.writes.append((vid, params, ms))

        async def jump(self, vid, effect_type, params):
            self.writes.append((vid, params, 0))

    ex = _Executor()
    responses = ResponseEngine(
        conductor=_Conductor(), executor=ex,
        # An UNCONFIGURED selector: proves the pin governs even where no
        # selection could ever have happened.
        sequencer_config=lambda: SequencerConfig(),
        room_load=color_journey.load_room,
        room_save=lambda st: None,
    )

    _pin("pinned")
    result = _run(responses._color_jump(SceneV2(name="S"), 0.6, {}))
    assert result["result"] == "jumped"
    assert result["picked_id"] == "pinned"
    assert result["forced_color"] == "pinned"
    assert any(p.get("gradient") == "#abcdef" for _v, p, _ms in ex.writes), \
        "the pinned colours actually reached the executor"


# ── 5. the journey holds, and beats the gradient ─────────────────────────────

def _conductor(**kw):
    from spectra.services import color_journey
    from spectra.services.drift_conductor import DriftConductor
    from spectra.services.fx_executor import RecordingExecutor

    saved: dict = {}

    def room_save(st):
        saved["state"] = st

    return DriftConductor(
        executor=RecordingExecutor(),
        room_load=color_journey.load_room,
        room_save=room_save,
        gradient_profiles=lambda: {},
        **kw), saved


def test_the_colour_journey_holds_under_a_pin_and_outranks_the_gradient():
    """PRECEDENCE, stated: both a 2D gradient and a pin are "an alternate
    colour source takes over", so one has to be on top. The pin wins; the
    gradient id is untouched and drives again the moment the pin releases."""
    from spectra.services import color_journey
    from spectra.services import room_controls as rc

    _write_cards(_set("pinned"))
    color_journey.save_room(color_journey.load_room().model_copy(
        update={"active_set_id": "pinned", "wheel_position_deg": 90.0}))

    # A pin AND a gradient both live at once.
    controls = rc.RoomControlState(force_color_enabled=True,
                                   force_color_target_id="pinned",
                                   active_gradient_id="grad-1")
    rc.save_room_controls(controls)
    conductor, _saved = _conductor(room_controls=lambda: controls)
    rec = _run(conductor.tick())
    assert rec["journey"]["paused"] is True
    assert rec["journey"]["held_for"] == "force_color"
    assert rec["journey"]["forced_color_id"] == "pinned"
    assert rec["gradient"]["active"] is False
    assert rec["gradient"]["held_for"] == "force_color"

    # Released: the stored gradient id was never cleared, so it drives on
    # the very next leg (it names no saved profile here, which the gradient
    # leg reports as "missing" — the point is it is CONSULTED again).
    released = controls.model_copy(update={"force_color_enabled": False})
    rc.save_room_controls(released)
    conductor2, _s2 = _conductor(room_controls=lambda: released)
    rec2 = _run(conductor2.tick())
    assert rec2["journey"].get("held_for") == "gradient_drift"
    assert rec2["gradient"].get("missing") == "grad-1", \
        "the gradient resumed on release — nothing about it was torn down"


def test_a_set_less_room_bootstraps_to_the_pin_not_a_selector_draw():
    """Anchoring the wheel on a selector draw that is about to be
    overridden on the very next fire would leave active_set_id disagreeing
    with what the room actually wears."""
    from spectra.services import color_journey
    from spectra.services import room_controls as rc

    _write_cards(_set("other"), _set("pinned"))
    assert color_journey.load_room().active_set_id is None

    controls = rc.RoomControlState(force_color_enabled=True,
                                   force_color_target_id="pinned")
    rc.save_room_controls(controls)
    conductor, saved = _conductor(room_controls=lambda: controls)
    rec = _run(conductor.tick())
    assert rec["journey"]["bootstrap"]["applied"] == "pinned"
    assert rec["journey"]["bootstrap"]["rung"] == "force_color"
    assert saved["state"].active_set_id == "pinned"


# ── 3. the immediate apply ───────────────────────────────────────────────────

class _RecordingConductor:
    def __init__(self):
        self.applied: list = []

    async def apply_set_directly(self, card, *, forced_from=None):
        self.applied.append(card.id)
        return {"applied": card.id, "set_name": card.name, "virtuals": 1}


def test_enabling_the_pin_applies_it_immediately(monkeypatch):
    """The passive-redirect trap, not repeated: every gate this feature
    installs is a redirect on a choice something else was about to make,
    so on a quiet song the switch would look dead. The pin applies here,
    on the edit that turns it on."""
    from spectra.services import engine
    from spectra.services import room_controls as rc

    _write_cards(_set("pinned"), _set("other"))
    conductor = _RecordingConductor()
    monkeypatch.setattr(engine, "conductor", conductor)

    off = rc.RoomControlState()
    on = rc.RoomControlState(force_color_enabled=True,
                             force_color_target_id="pinned")
    result = _run(rc.reconcile_force_color_if_changed(off, on))
    assert result["status"] == "applied"
    assert result["target_id"] == "pinned"
    assert result["target_kind"] == "set"
    assert conductor.applied == ["pinned"]

    # A repin while already enabled applies the new one.
    repinned = on.model_copy(update={"force_color_target_id": "other"})
    result = _run(rc.reconcile_force_color_if_changed(on, repinned))
    assert result["status"] == "applied"
    assert conductor.applied == ["pinned", "other"]


def test_an_unrelated_field_resave_never_reapplies(monkeypatch):
    """A re-apply would advance a pinned GROUP's rotation cursor, rolling
    his colours on an edit that had nothing to do with colour."""
    from spectra.services import engine
    from spectra.services import room_controls as rc

    _write_cards(_set("pinned"))
    conductor = _RecordingConductor()
    monkeypatch.setattr(engine, "conductor", conductor)

    on = rc.RoomControlState(force_color_enabled=True,
                             force_color_target_id="pinned")
    nudged = on.model_copy(update={"brightness_multiplier": 0.6})
    assert _run(rc.reconcile_force_color_if_changed(on, nudged)) is None
    assert conductor.applied == []

    # Releasing does nothing live either — the room keeps the colours it
    # is wearing and picks normally from the next change onward.
    released = on.model_copy(update={"force_color_enabled": False})
    assert _run(rc.reconcile_force_color_if_changed(on, released)) is None
    assert conductor.applied == []


def test_a_refusal_always_states_its_reason(monkeypatch):
    """Never a silent no-op — the silence is what read as broken when
    Force Scene had the same gap."""
    from spectra.services import engine
    from spectra.services import room_controls as rc

    _write_cards(_set("a", disabled=True), _group("empty", []))
    monkeypatch.setattr(engine, "conductor", _RecordingConductor())
    off = rc.RoomControlState()

    nothing = rc.RoomControlState(force_color_enabled=True)
    assert _run(rc.reconcile_force_color_if_changed(off, nothing)) == {
        "status": "skipped", "reason": "no colour set pinned"}

    missing = rc.RoomControlState(force_color_enabled=True,
                                  force_color_target_id="gone")
    result = _run(rc.reconcile_force_color_if_changed(off, missing))
    assert result["status"] == "skipped"
    assert result["reason"] == "pinned colour set not found"

    empty_group = rc.RoomControlState(force_color_enabled=True,
                                      force_color_target_id="empty")
    result = _run(rc.reconcile_force_color_if_changed(off, empty_group))
    assert result["status"] == "skipped"
    assert "no usable member" in result["reason"]


# ── 7. a disabled pin applies and is NAMED ───────────────────────────────────

def test_pinning_a_disabled_card_applies_it_and_names_the_contradiction(monkeypatch):
    """The same contradiction shape as Force Scene firing a disabled
    scene: he marked it disabled, then pinned it anyway. The pin wins —
    he pressed it, he means it — but never silently."""
    from spectra.services import engine, force_color
    from spectra.services import room_controls as rc

    _write_cards(_set("off-set", disabled=True))
    conductor = _RecordingConductor()
    monkeypatch.setattr(engine, "conductor", conductor)

    on = rc.RoomControlState(force_color_enabled=True,
                             force_color_target_id="off-set")
    result = _run(rc.reconcile_force_color_if_changed(rc.RoomControlState(), on))
    assert result["status"] == "applied", "a disabled pin is never refused"
    assert result["overrode_disabled"] is True, "and never silent"
    assert conductor.applied == ["off-set"]

    # The gate is not re-applied at fire time either — a pin is an
    # explicit statement, so it resolves through resolve_for_fire, never
    # the disabled/mode-gated variant.
    assert force_color.pinned_card(on).id == "off-set"
    assert force_color.overrode_disabled(on) is True


# ── 8. his own explicit actions still work, and say so ───────────────────────

def test_a_manual_apply_still_works_under_a_pin_and_names_the_override(monkeypatch):
    """The pin gates AUTOMATIC choices, not him. POST /room-color/apply
    lands as normal — but the pin is not cleared, so it reasserts on the
    next automatic change, which is exactly why the response must say so."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from spectra.api import journey as journey_api
    from spectra.services import engine

    _write_cards(_set("chosen"), _set("pinned"))
    monkeypatch.setattr(engine, "conductor", _RecordingConductor())

    app = FastAPI()
    app.include_router(journey_api.router)
    client = TestClient(app)

    body = client.post("/api/room-color/apply", json={"set_id": "chosen"}).json()
    assert "overrode_force_color" not in body

    _pin("pinned")
    body = client.post("/api/room-color/apply", json={"set_id": "chosen"}).json()
    assert body["applied"] == "chosen", "his explicit press still wins"
    assert body["overrode_force_color"] == "pinned", "and the pin is named"

    from spectra.services import room_controls as rc
    assert rc.load_room_controls().force_color_enabled is True, \
        "a manual apply never clears the pin"
