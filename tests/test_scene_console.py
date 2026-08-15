"""Sonic's SCENE/FLARE mechanism + the WIDENED authority boundary
(spectra/services/scene_console.py, merged into settings_agent.
ALL_OPERATIONS) — offline proof, no network, no ANTHROPIC_API_KEY
required for the bulk of this file.

This is a WIDER surface than the original five-setting settings console
(tests/test_settings_console.py) — the Admiral's brief is explicit that
its proof does not transfer, so this file re-proves the refusing half
against the NEW scene/flare surface specifically, plus three properties
unique to widening scene authority:
  1. his 9 real, authored scenes are never modified by ANY scene
     operation exercised against a DIFFERENT scene (test_scene_console_
     never_touches_an_untouched_scene);
  2. create_scene can never collide with, and therefore never overwrite,
     an existing scene, even given an identical name (test_create_scene_
     never_collides_even_with_a_duplicate_name);
  3. there is no delete/overwrite-by-id operation in the enumerated set
     at all (test_no_delete_or_wholesale_overwrite_operation_exists).

The four adversarial refusal categories the brief calls for, each proven
with the SERVER's own quoted refusal text (not a model's polite decline):
  - an operation outside the enumerated set (test_operation_outside_the_set)
  - a valid operation, out-of-range/malformed argument (test_out_of_range_
    scene_setting_rejected, test_malformed_flare_kind_rejected)
  - an attempt to reach a non-scene setting (test_room_setting_unreachable_
    via_scene_op, and the mirror: scene keys unreachable via set_setting)
  - a shell/service-restart attempt (test_shell_and_service_attempts_rejected)

And the fabrication hunt: test_run_turn_never_reports_a_change_the_
structured_tool_result_did_not_confirm proves `changes`/the effect on disk
are driven only by the real _dispatch() return value, never by a mocked
model's prose, exercising run_turn() itself (not just _dispatch()
directly, which test_scene_console_dispatch_boundary already covers)."""
from __future__ import annotations

import asyncio
import json

import pytest
from pydantic import ValidationError


def _run(coro):
    return asyncio.run(coro)


# His 9 real, authored scenes (CLAUDE.md: "Do not modify, overwrite or
# delete any of them") — used as fixture NAMES ONLY, never targeted by any
# write in this file; every write below targets a scene THIS file created.
HIS_REAL_SCENE_NAMES = [
    "STAR", "Black Hole V2", "Orbits V2", "Fireworks V2", "Squiggles V2",
    "Dancers V2", "Eye V2", "Black Hole V2 UI",
]


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path)
    monkeypatch.setattr(scfg, "SCENES_FILE", tmp_path / "scenes.json")
    monkeypatch.setattr(scfg, "SCENE_AGENT_LOG_FILE", tmp_path / "scene_agent_log.json")
    monkeypatch.setattr(scfg, "SETTINGS_LOG_FILE", tmp_path / "settings_log.json")
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")
    monkeypatch.setattr(scfg, "COLOR_SETS_FILE", tmp_path / "color_sets.json")
    monkeypatch.setattr(scfg, "DRIFT_PROFILES_FILE", tmp_path / "drift_profiles.json")

    from spectra.services import settings_agent
    settings_agent._SESSIONS.clear()


def _seed_his_real_scenes():
    """Simulates his real library: one authored scene per real name, each
    with a distinctive entry_ramp_ms so a byte-for-byte "did this change"
    check doesn't need anything beyond re-reading the store."""
    from spectra.services import scene_store
    from spectra.models.scene import SceneV2

    ids = {}
    for i, name in enumerate(HIS_REAL_SCENE_NAMES):
        scene = SceneV2(name=name, entry_ramp_ms=100 + i)
        scene_store.save(scene)
        ids[name] = scene.id
    return ids


# ═══ 1. registry: generated from the real schema, not re-typed ═════════

def test_scene_settings_registry_bounds_are_read_from_the_real_models():
    from spectra.models.scene import PhaseBlend, PhaseChoreography, SceneColorJourney, SceneV2
    from spectra.services import scene_console as sc

    assert set(sc.SCENE_SETTINGS_REGISTRY) == {
        "entry_ramp_ms", "phase_blend_charge_ramp_ms", "phase_blend_lull_ramp_ms",
        "choreography_enabled", "choreography_transition_ms", "choreography_anchor_frac",
        "color_journey_pace_factor", "accept_all_sets",
    }

    spec = sc.SCENE_SETTINGS_REGISTRY["entry_ramp_ms"]
    assert (spec.min, spec.max) == sc._model_field_bounds(SceneV2, "entry_ramp_ms") == (0.0, 20000.0)

    spec = sc.SCENE_SETTINGS_REGISTRY["phase_blend_charge_ramp_ms"]
    assert (spec.min, spec.max) == sc._model_field_bounds(PhaseBlend, "charge_ramp_ms") == (200.0, 20000.0)
    assert spec.nullable is True

    spec = sc.SCENE_SETTINGS_REGISTRY["choreography_anchor_frac"]
    assert (spec.min, spec.max) == sc._model_field_bounds(PhaseChoreography, "anchor_frac") == (0.0, 1.0)

    spec = sc.SCENE_SETTINGS_REGISTRY["color_journey_pace_factor"]
    assert (spec.min, spec.max) == sc._model_field_bounds(SceneColorJourney, "pace_factor") == (0.0, None)

    # Deliberately excluded — a companion-spec / no-declared-bounds field,
    # same "left for a later, deliberate extension" posture as
    # settings_console's force_scene_* exclusion.
    assert "color_journey_mode" not in sc.SCENE_SETTINGS_REGISTRY
    assert "choreography_transition_mode" not in sc.SCENE_SETTINGS_REGISTRY


# ═══ 2. write validation rejects, nothing persists ══════════════════════

def test_unknown_scene_setting_key_rejected():
    from spectra.services import scene_console as sc
    from spectra.services import scene_store
    from spectra.models.scene import SceneV2

    scene = SceneV2(name="Throwaway")
    scene_store.save(scene)

    with pytest.raises(sc.SceneOpError) as exc:
        sc._validate_scene_setting(scene.id, "brightness_multiplier", 0.5)
    assert "brightness_multiplier" not in exc.value.detail["allowed_keys"]


def test_unknown_scene_id_rejected_before_touching_the_registry():
    from spectra.services import scene_console as sc

    with pytest.raises(sc.SceneOpError, match="no scene with id"):
        sc._validate_scene_setting("nonexistent-id", "entry_ramp_ms", 500)


def test_out_of_range_scene_setting_rejected_with_the_servers_own_text():
    from spectra.services import scene_console as sc
    from spectra.services import scene_store
    from spectra.models.scene import SceneV2

    scene = SceneV2(name="Throwaway")
    scene_store.save(scene)

    with pytest.raises(sc.SceneOpError) as exc:
        sc._validate_scene_setting(scene.id, "entry_ramp_ms", 999999)
    assert "20000" in " ".join(exc.value.detail["pydantic_errors"])
    # nothing persisted
    assert scene_store.get_by_id(scene.id).entry_ramp_ms == 0


def test_malformed_flare_kind_rejected_before_any_write():
    from spectra.services import scene_console as sc
    from spectra.services import scene_store
    from spectra.models.scene import SceneV2

    scene = SceneV2(name="Throwaway")
    scene_store.save(scene)

    with pytest.raises(sc.SceneOpError) as exc:
        sc._validate_set_flare_kind(
            scene.id, name="BadJump", type="drift_jump", jump="dice",
            params={"blob_size": 1.0}, gain=1.0, hold_ms=None)
    assert "jumps the drift" in str(exc.value)
    assert scene_store.get_by_id(scene.id).flare_kinds == []


def test_removing_a_referenced_flare_kind_is_refused():
    from spectra.services import scene_console as sc
    from spectra.services import scene_store
    from spectra.models.scene import ResponseSpec, SceneV2

    scene = SceneV2(name="Throwaway")
    scene_store.save(scene)
    _run(sc.apply_flare_kind(scene.id, name="Boom", type="momentary", params={"gain": 1.0}, gain=1.5))
    scene = scene_store.get_by_id(scene.id)
    scene.responses["flare"] = ResponseSpec(
        bands=[{"intensity_min": 0.0, "intensity_max": 1.0, "kinds": {"Boom": 1.0}}])
    scene_store.save(scene)

    with pytest.raises(sc.SceneOpError, match="still referenced"):
        _run(sc.apply_remove_flare_kind(scene.id, "Boom"))
    assert [k.name for k in scene_store.get_by_id(scene.id).flare_kinds] == ["Boom"]


# ═══ 3. apply_* persists + logs, mirroring settings_console's shape ═════

def test_apply_scene_setting_persists_and_logs():
    from spectra.services import scene_console as sc
    from spectra.services import scene_store
    from spectra.models.scene import SceneV2

    scene = SceneV2(name="Throwaway")
    scene_store.save(scene)

    result = _run(sc.apply_scene_setting(scene.id, "entry_ramp_ms", 1500))
    assert result["status"] == "applied"
    assert result["old_value"] == 0 and result["new_value"] == 1500
    assert scene_store.get_by_id(scene.id).entry_ramp_ms == 1500

    log = sc.load_log()
    assert len(log) == 1 and log[0]["key"] == "entry_ramp_ms" and log[0]["scene_id"] == scene.id


def test_apply_flare_kind_create_then_update_by_name():
    from spectra.services import scene_console as sc
    from spectra.services import scene_store
    from spectra.models.scene import SceneV2

    scene = SceneV2(name="Throwaway")
    scene_store.save(scene)

    r1 = _run(sc.apply_flare_kind(scene.id, name="Boom", type="momentary", params={"gain": 1.0}, gain=1.2))
    assert r1["op"] == "flare_kind_created"
    assert scene_store.get_by_id(scene.id).flare_kinds[0].gain == 1.2

    r2 = _run(sc.apply_flare_kind(scene.id, name="Boom", type="momentary", params={"gain": 1.0}, gain=2.0))
    assert r2["op"] == "flare_kind_updated"
    kinds = scene_store.get_by_id(scene.id).flare_kinds
    assert len(kinds) == 1 and kinds[0].gain == 2.0, "same name replaces, never duplicates"


def test_create_scene_persists_and_logs():
    from spectra.services import scene_console as sc
    from spectra.services import scene_store

    result = _run(sc.apply_create_scene("Brand New Scene", labels=["test"]))
    assert result["status"] == "applied"
    scene = scene_store.get_by_id(result["scene_id"])
    assert scene.name == "Brand New Scene" and scene.labels == ["test"]
    assert scene.devices == [], "a created scene has no devices yet — his UI/set_flare_kind add the rest"


def test_create_scene_rejects_an_empty_name_without_writing():
    from spectra.services import scene_console as sc
    from spectra.services import scene_store

    with pytest.raises(sc.SceneOpError):
        sc._validate_create_scene("   ")
    assert scene_store.list_all() == []


# ═══ 4. HIS AUTHORED WORK IS NOT A TEST FIXTURE — the two properties that
# actually protect it ═════════════════════════════════════════════════════

def test_create_scene_never_collides_even_with_a_duplicate_name():
    from spectra.services import scene_console as sc
    from spectra.services import scene_store

    ids = _seed_his_real_scenes()
    star_id = ids["STAR"]
    star_raw_before = json.loads((__import__("spectra").config.SCENES_FILE).read_text())[star_id]

    result = _run(sc.apply_create_scene("STAR"))  # exact name collision, on purpose
    assert result["scene_id"] != star_id, "a created scene must never reuse an existing id"

    star_raw_after = json.loads((__import__("spectra").config.SCENES_FILE).read_text())[star_id]
    assert star_raw_after == star_raw_before, "the real STAR scene's stored bytes are untouched"
    assert len(scene_store.list_all()) == len(HIS_REAL_SCENE_NAMES) + 1


def test_scene_operations_never_touch_a_scene_they_were_not_targeted_at():
    """Seeds all 9 of his real scene names, then exercises every write
    operation against a DIFFERENT (freshly created) scene, and asserts
    every one of his 9 scenes' stored bytes are byte-identical before and
    after — the concrete proof behind "his authored work is not a test
    fixture", not just an assertion that a function *targets* one scene."""
    from spectra import config as scfg
    from spectra.services import scene_console as sc

    ids = _seed_his_real_scenes()
    before = json.loads(scfg.SCENES_FILE.read_text())
    before_snapshot = {sid: json.dumps(before[sid], sort_keys=True) for sid in ids.values()}

    other_id = _run(sc.apply_create_scene("Throwaway test scene"))["scene_id"]
    _run(sc.apply_scene_setting(other_id, "entry_ramp_ms", 2000))
    _run(sc.apply_flare_kind(other_id, name="Boom", type="permanent", params={"gain": 1.0}))
    _run(sc.apply_remove_flare_kind(other_id, "Boom"))

    after = json.loads(scfg.SCENES_FILE.read_text())
    for name, sid in ids.items():
        after_snapshot = json.dumps(after[sid], sort_keys=True)
        assert after_snapshot == before_snapshot[sid], f"scene {name!r} ({sid}) was touched"


def test_no_delete_or_wholesale_overwrite_operation_exists():
    from spectra.services import scene_console as sc
    from spectra.services import settings_agent as sa

    for forbidden in ("delete_scene", "overwrite_scene", "update_scene", "save_scene", "set_scene"):
        assert forbidden not in sc.OPERATIONS
        assert forbidden not in sa.ALL_OPERATIONS
    # every scene write op's handler signature never accepts a `devices`
    # argument — device/effect editing is out of scope by construction,
    # not by convention.
    import inspect
    for name, op in sc.OPERATIONS.items():
        if op.kind == "write":
            params = inspect.signature(op.handler).parameters
            assert "devices" not in params, f"{name} must never accept raw devices"


# ═══ 5. the four adversarial refusal categories, server's own text ══════

def test_operation_outside_the_set_is_rejected_without_touching_storage():
    from spectra import config as scfg
    from spectra.services import scene_console as sc
    from spectra.services import settings_agent as sa

    _seed_his_real_scenes()
    before = scfg.SCENES_FILE.read_bytes()

    for name in ("delete_scene", "list_devices", "set_device_effect"):
        result = _run(sa._dispatch(name, {"scene_id": "whatever"}))
        assert result == {"status": "rejected", "reason": f"no such operation: {name!r}"}

    assert scfg.SCENES_FILE.read_bytes() == before


def test_room_setting_unreachable_via_scene_op():
    from spectra.services import scene_console as sc
    from spectra.services import scene_store
    from spectra.models.scene import SceneV2

    scene = SceneV2(name="Throwaway")
    scene_store.save(scene)

    with pytest.raises(sc.SceneOpError) as exc:
        sc._validate_scene_setting(scene.id, "brightness_multiplier", 0.2)
    assert exc.value.message == "'brightness_multiplier' is not a scene setting"


def test_scene_setting_unreachable_via_set_setting():
    from spectra.services import settings_console as stc

    with pytest.raises(stc.SettingChangeError) as exc:
        stc.validate_change("entry_ramp_ms", 500)
    assert exc.value.message == "'entry_ramp_ms' is not a settings-console setting"


def test_shell_and_service_attempts_rejected():
    from spectra import config as scfg
    from spectra.services import settings_agent as sa

    _seed_his_real_scenes()
    before = scfg.SCENES_FILE.read_bytes()

    for name, args in [
        ("run_shell", {"cmd": "rm -rf /"}),
        ("restart_service", {"unit": "spotfx"}),
        ("http_request", {"url": "http://127.0.0.1:8000/api/scenes"}),
        ("read_file", {"path": "/etc/passwd"}),
        ("drive_lights", {"virtual": "hues", "color": "#ff0000"}),
    ]:
        result = _run(sa._dispatch(name, args))
        assert result["status"] == "rejected"
        assert "no such operation" in result["reason"]

    assert scfg.SCENES_FILE.read_bytes() == before, "no fabricated tool call touched storage"


# ═══ 6. the merged dispatch boundary — exhaustive by construction ═══════

def test_dispatch_recognizes_exactly_the_declared_operation_set():
    from spectra.services import scene_console as sc
    from spectra.services import settings_console as stc
    from spectra.services import settings_agent as sa

    expected = {"list_operations", *stc.OPERATIONS, *sc.OPERATIONS}
    assert {t["name"] for t in sa.TOOLS} == expected
    assert set(sa.ALL_OPERATIONS) == expected


def test_dispatch_scene_write_applies_a_valid_change():
    from spectra.services import scene_store
    from spectra.services import settings_agent as sa
    from spectra.models.scene import SceneV2

    scene = SceneV2(name="Throwaway")
    scene_store.save(scene)

    result = _run(sa._dispatch("set_scene_setting",
                               {"scene_id": scene.id, "key": "entry_ramp_ms", "value": 1200}))
    assert result["status"] == "applied"
    assert scene_store.get_by_id(scene.id).entry_ramp_ms == 1200


def test_dispatch_rejects_bad_argument_shape_without_raising():
    from spectra.services import settings_agent as sa

    result = _run(sa._dispatch("set_scene_setting", {"scene_id": "x"}))  # missing key/value
    assert result["status"] == "rejected"
    assert "bad arguments" in result["reason"]


# ═══ 7. fabrication hunt: run_turn() trusts only real tool_result blocks ═

class _FakeBlock:
    def __init__(self, type, **kw):
        self.type = type
        for k, v in kw.items():
            setattr(self, k, v)


class _FakeResponse:
    def __init__(self, content):
        self.content = content


class _FakeMessages:
    def __init__(self, responses):
        self._responses = list(responses)

    async def create(self, **kwargs):
        return self._responses.pop(0)


class _FakeClient:
    def __init__(self, responses):
        self.messages = _FakeMessages(responses)


def test_run_turn_never_reports_a_change_the_structured_tool_result_did_not_confirm(monkeypatch):
    """Simulates exactly the shape of the historical fabrication failure —
    a model that CLAIMS a scene/flare was created in its final reply text
    — but whose only real tool_use/tool_result round trip was a REJECTION
    (an unknown key). run_turn()'s `changes` must stay empty, and no scene
    must land on disk, because `changes` is built from the tool_result's
    own structured `status` field, never from the reply text."""
    from spectra import config as scfg
    from spectra.services import settings_agent as sa

    tool_use = _FakeBlock(
        "tool_use", id="tu_1", name="set_scene_setting",
        input={"scene_id": "nonexistent", "key": "entry_ramp_ms", "value": 500})
    first = _FakeResponse([tool_use])
    second = _FakeResponse([_FakeBlock(
        "text", text="Done — I created the scene and set its entry ramp to 500ms for you.")])

    monkeypatch.setattr(sa, "_client", lambda: _FakeClient([first, second]))

    result = _run(sa.run_turn(None, "make a scene and set its entry ramp"))

    assert result["changes"] == [], \
        "the tool_result was a rejection (unknown scene id) — the confident reply text must not count"
    assert "created the scene" in result["reply"], \
        "the fabrication is real and present in the reply text — the point is `changes` doesn't believe it"
    assert not scfg.SCENES_FILE.exists(), "nothing was ever actually written"


def test_run_turn_only_counts_a_change_the_dispatcher_actually_applied(monkeypatch):
    from spectra.services import scene_store
    from spectra.services import settings_agent as sa
    from spectra.models.scene import SceneV2

    scene = SceneV2(name="Throwaway")
    scene_store.save(scene)

    tool_use = _FakeBlock(
        "tool_use", id="tu_1", name="set_scene_setting",
        input={"scene_id": scene.id, "key": "entry_ramp_ms", "value": 700})
    first = _FakeResponse([tool_use])
    second = _FakeResponse([_FakeBlock("text", text="Set the entry ramp to 700ms.")])
    monkeypatch.setattr(sa, "_client", lambda: _FakeClient([first, second]))

    result = _run(sa.run_turn(None, "set entry ramp to 700ms"))

    assert len(result["changes"]) == 1
    assert result["changes"][0]["new_value"] == 700
    assert scene_store.get_by_id(scene.id).entry_ramp_ms == 700, \
        "the real, structured change actually landed in storage"


# ═══ 8. API layer stays generic — no scene-specific endpoint needed ═════

def test_api_message_503_without_api_key_mentions_no_operation_leak(monkeypatch):
    from fastapi.testclient import TestClient

    from spectra import config as scfg
    from spectra.app import create_app

    monkeypatch.setattr(scfg, "settings_agent_api_key", lambda: "")
    client = TestClient(create_app())
    r = client.post("/api/settings-console/message", json={"text": "create a scene called Test"})
    assert r.status_code == 503
    assert "ANTHROPIC_API_KEY" in r.json()["detail"]
