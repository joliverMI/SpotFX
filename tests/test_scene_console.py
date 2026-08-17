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
    monkeypatch.setattr(scfg, "SCENE_BACKUPS_FILE", tmp_path / "scene_backups.json")
    monkeypatch.setattr(scfg, "SCENE_GENESIS_FILE", tmp_path / "scene_genesis.json")
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


def test_no_delete_operation_exists_and_no_write_ever_touches_devices():
    """overwrite_scene is now a real, deliberate operation (his own
    2026-08-15 follow-up ask) — but there is STILL no way to delete a
    scene by id, and device/effect editing is STILL out of scope (that
    boundary wasn't reversed by this widening, only overwrite was)."""
    from spectra.services import scene_console as sc
    from spectra.services import settings_agent as sa

    assert "overwrite_scene" in sc.OPERATIONS, "his ask — this one should exist now"
    for forbidden in ("delete_scene", "update_scene", "save_scene", "set_scene"):
        assert forbidden not in sc.OPERATIONS
        assert forbidden not in sa.ALL_OPERATIONS
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


# ═══ 8. API layer — mostly generic (POST /message serves both domains),
# plus ONE scene-specific endpoint: the plain, model-free undo button. ═══

def test_api_message_503_without_api_key_mentions_no_operation_leak(monkeypatch):
    from fastapi.testclient import TestClient

    from spectra import config as scfg
    from spectra.app import create_app

    monkeypatch.setattr(scfg, "settings_agent_api_key", lambda: "")
    client = TestClient(create_app())
    r = client.post("/api/settings-console/message", json={"text": "create a scene called Test"})
    assert r.status_code == 503
    assert "ANTHROPIC_API_KEY" in r.json()["detail"]


def test_api_scene_undo_needs_no_model_and_actually_restores():
    """The button his words asked for: 'an easy to undo last agent change
    button.' Proves it works with NO ANTHROPIC_API_KEY configured at all
    (unlike /message) — undo is a deterministic restore, not a chat turn."""
    from fastapi.testclient import TestClient

    from spectra.app import create_app
    from spectra.services import scene_store
    from spectra.models.scene import SceneV2

    scene = SceneV2(name="Throwaway", entry_ramp_ms=0)
    scene_store.save(scene)

    client = TestClient(create_app())
    r = client.post("/api/settings-console/scene-undo")
    assert r.status_code == 409, "nothing applied yet — nothing to undo"

    r = client.post("/api/scenes", json=SceneV2(
        **{**scene.model_dump(), "entry_ramp_ms": 1500}).model_dump())
    assert r.status_code == 200
    # That was a human PUT through the ordinary scenes API, not a Sonic
    # edit — it must NOT be undoable via scene-undo (no backup_id).
    r = client.post("/api/settings-console/scene-undo")
    assert r.status_code == 409

    from spectra.services import scene_console as sc
    _run(sc.apply_scene_setting(scene.id, "entry_ramp_ms", 500))

    r = client.post("/api/settings-console/scene-undo")
    assert r.status_code == 200
    assert scene_store.get_by_id(scene.id).entry_ramp_ms == 1500, \
        "the scene is genuinely back to its pre-Sonic-edit value, verified via the store"


# ═══ 9. overwrite/edit authority (2026-08-15 follow-up): backup-before-
# any-edit VERIFIED not merely attempted, undo-last-agent-change proven to
# actually restore, preview/check-in read from stored data, and
# restore-to-any-point including the permanent genesis snapshot. His own
# four structural requirements, each proven, not just wired up. ═════════

def _seed_scene(name="Throwaway", **kwargs):
    from spectra.services import scene_store
    from spectra.models.scene import SceneV2

    scene = SceneV2(name=name, **kwargs)
    scene_store.save(scene)
    return scene


# ── 9a. backup is taken before every existing-scene edit, and VERIFIED ──

def test_backup_is_taken_before_the_edit_and_holds_the_pre_edit_value():
    from spectra.services import scene_console as sc

    scene = _seed_scene(entry_ramp_ms=0)
    result = _run(sc.apply_scene_setting(scene.id, "entry_ramp_ms", 1500))

    backups = sc._load_backups()[scene.id]
    assert len(backups) == 1
    assert backups[0]["id"] == result["backup_id"]
    assert backups[0]["scene"]["entry_ramp_ms"] == 0, \
        "the backup holds the value BEFORE the edit, not after"


def test_genesis_is_captured_once_on_first_edit_and_never_overwritten():
    from spectra.services import scene_console as sc

    scene = _seed_scene(entry_ramp_ms=0)
    _run(sc.apply_scene_setting(scene.id, "entry_ramp_ms", 1500))
    genesis_after_first = sc._load_genesis()[scene.id]
    assert genesis_after_first["scene"]["entry_ramp_ms"] == 0

    _run(sc.apply_scene_setting(scene.id, "entry_ramp_ms", 3000))
    _run(sc.apply_flare_kind(scene.id, name="Boom", type="permanent", params={"gain": 1.0}))
    genesis_after_more_edits = sc._load_genesis()[scene.id]
    assert genesis_after_more_edits == genesis_after_first, \
        "genesis must be written exactly once and never touched again"


def test_backup_ring_is_capped_at_ten_oldest_evicted_first():
    from spectra.services import scene_console as sc

    scene = _seed_scene(entry_ramp_ms=0)
    for i in range(1, 13):  # 12 edits — well past the cap
        _run(sc.apply_scene_setting(scene.id, "entry_ramp_ms", i * 100))

    ring = sc._load_backups()[scene.id]
    assert len(ring) == sc.SCENE_BACKUP_RING_SIZE == 10
    # the oldest two backups (pre-edit values 0 and 100) must be evicted;
    # the ring's oldest surviving entry is the pre-edit-3 value (200).
    values = [e["scene"]["entry_ramp_ms"] for e in ring]
    assert values[0] == 200 and values[-1] == 1100
    # genesis (value 0, from edit 1) survives the eviction untouched.
    assert sc._load_genesis()[scene.id]["scene"]["entry_ramp_ms"] == 0


def test_backup_verification_failure_refuses_the_edit_and_writes_nothing(monkeypatch):
    """Proves "verified, not merely attempted": the backup WRITE call is
    made to silently succeed without actually landing (a no-op standing
    in for a torn/partial write), and the mechanism must catch this by
    RE-READING the file and finding the entry absent — not by an
    exception from the write itself."""
    from spectra.services import scene_console as sc

    scene = _seed_scene(entry_ramp_ms=0)
    real_write = sc._atomic_write_json

    def fake_write(path, data):
        if path == sc.config.SCENE_BACKUPS_FILE:
            return  # silently doesn't write — no exception, no evidence, no proof
        return real_write(path, data)

    monkeypatch.setattr(sc, "_atomic_write_json", fake_write)

    with pytest.raises(sc.SceneOpError, match="backup could not be verified"):
        _run(sc.apply_scene_setting(scene.id, "entry_ramp_ms", 1500))

    from spectra.services import scene_store
    assert scene_store.get_by_id(scene.id).entry_ramp_ms == 0, \
        "the scene itself must be untouched — the write must never reach scene_store.save()"


def test_genesis_verification_failure_also_refuses_the_edit(monkeypatch):
    from spectra.services import scene_console as sc

    scene = _seed_scene(entry_ramp_ms=0)
    real_write = sc._atomic_write_json

    def fake_write(path, data):
        if path == sc.config.SCENE_GENESIS_FILE:
            return  # ring write succeeds; genesis write silently doesn't
        return real_write(path, data)

    monkeypatch.setattr(sc, "_atomic_write_json", fake_write)

    with pytest.raises(sc.SceneOpError, match="genesis snapshot could not be verified"):
        _run(sc.apply_scene_setting(scene.id, "entry_ramp_ms", 1500))

    from spectra.services import scene_store
    assert scene_store.get_by_id(scene.id).entry_ramp_ms == 0


def test_dispatch_overwrite_scene_with_failed_backup_refuses_via_the_real_model_shaped_path(monkeypatch):
    """The exact adversarial case the deploy hold calls out by name: 'an
    overwrite attempted while the backup mechanism FAILS must REFUSE' —
    run through settings_agent._dispatch(), the same entry point a real
    model's tool_use reaches, not the internal function directly."""
    from spectra.services import scene_console as sc
    from spectra.services import settings_agent as sa
    from spectra.services import scene_store

    scene = _seed_scene(name="STAR", entry_ramp_ms=0)
    real_write = sc._atomic_write_json
    calls = {"n": 0}

    def fake_write(path, data):
        if path == sc.config.SCENE_BACKUPS_FILE:
            calls["n"] += 1
            return
        return real_write(path, data)

    monkeypatch.setattr(sc, "_atomic_write_json", fake_write)
    result = _run(sa._dispatch("overwrite_scene", {
        "scene_id": scene.id, "name": "STAR (hijacked)"}))

    assert result["status"] == "rejected"
    assert "backup could not be verified" in result["reason"]
    assert calls["n"] >= 1, "the backup write was actually attempted, and still refused"
    assert scene_store.get_by_id(scene.id).name == "STAR", \
        "the real model's tool call must land on an untouched scene after refusal"


# ── 9b. preview/check-in reads stored data, never the agent's account ───

def test_preview_on_a_write_result_is_computed_from_real_before_after_state():
    from spectra.services import scene_console as sc

    scene = _seed_scene(entry_ramp_ms=0)
    result = _run(sc.apply_scene_setting(scene.id, "entry_ramp_ms", 1500))
    assert result["preview"] == {"entry_ramp_ms": {"before": 0, "after": 1500}}


def test_get_scene_preview_reads_the_real_backup_and_the_real_current_scene():
    from spectra.services import scene_console as sc
    from spectra.services import scene_store

    scene = _seed_scene(name="Throwaway", entry_ramp_ms=0)
    _run(sc.apply_scene_setting(scene.id, "entry_ramp_ms", 1500))

    preview = sc.get_scene_preview(scene.id)
    assert preview["has_backup"] is True
    assert preview["preview"] == {"entry_ramp_ms": {"before": 0, "after": 1500}}

    # Prove it's a REAL read, not cached: edit again with a totally
    # different value and confirm the preview tracks the NEW backup, not
    # a stale copy of the first call's answer.
    _run(sc.apply_scene_setting(scene.id, "entry_ramp_ms", 9000))
    preview2 = sc.get_scene_preview(scene.id)
    assert preview2["preview"] == {"entry_ramp_ms": {"before": 1500, "after": 9000}}


def test_get_scene_preview_with_no_backup_yet_is_honest_not_fabricated():
    from spectra.services import scene_console as sc

    scene = _seed_scene()
    preview = sc.get_scene_preview(scene.id)
    assert preview == {"scene_id": scene.id, "name": scene.name,
                       "has_backup": False, "preview": {}}


def test_preview_is_never_swayed_by_a_fabricated_model_reply(monkeypatch):
    """The exact failure this project caught tonight on the real model:
    a confident, specific claim about what changed. Here the model's
    reply text claims a completely different, much larger change than
    what the real tool call actually did — get_scene_preview (called
    independently, exactly as Sonic is instructed to call it before
    trusting its own account) must report the REAL diff regardless."""
    from spectra.services import scene_console as sc

    scene = _seed_scene(entry_ramp_ms=0)
    _run(sc.apply_scene_setting(scene.id, "entry_ramp_ms", 500))

    fabricated_claim = ("I changed the entry ramp to 9999ms, the choreography "
                        "transition to 5000ms, and renamed the scene to 'Epic'.")
    preview = sc.get_scene_preview(scene.id)

    assert preview["preview"] == {"entry_ramp_ms": {"before": 0, "after": 500}}
    assert "9999" not in json.dumps(preview)
    assert "Epic" not in json.dumps(preview)
    assert fabricated_claim  # the claim exists (as a model might say it); the preview ignores it


# ── 9c. undo-last-agent-change: proven to actually restore ──────────────

def test_undo_last_scene_change_actually_restores_verified_against_stored_data():
    from spectra.services import scene_console as sc
    from spectra.services import scene_store

    scene = _seed_scene(entry_ramp_ms=0)
    _run(sc.apply_scene_setting(scene.id, "entry_ramp_ms", 1500))
    assert scene_store.get_by_id(scene.id).entry_ramp_ms == 1500, "the edit really landed"

    undo_result = _run(sc.apply_undo_last_scene_change())

    # Verify against STORED DATA, not the undo call's own return value.
    assert scene_store.get_by_id(scene.id).entry_ramp_ms == 0, \
        "the scene must genuinely be back to its pre-edit value on disk"
    assert undo_result["status"] == "applied"


def test_undo_marks_the_original_entry_undone_not_deleted():
    from spectra.services import scene_console as sc

    scene = _seed_scene(entry_ramp_ms=0)
    _run(sc.apply_scene_setting(scene.id, "entry_ramp_ms", 1500))
    _run(sc.apply_undo_last_scene_change())

    log = sc.load_log()
    original = next(e for e in log if e["op"] == "set_scene_setting")
    assert original["undone"] is True
    undo_entry = next(e for e in log if e["op"] == "restore_scene_backup")
    assert undo_entry["source"] == "undo"


def test_undo_of_an_undo_works_the_ring_retention_reason_he_gave():
    """His own stated reason for keeping more than one backup: 'an undo
    of an undo works.' Edit A, edit B, undo (back to after-A), undo again
    (back to after-B, i.e. re-applying B) — proven against stored data at
    every step, not assumed from the call succeeding."""
    from spectra.services import scene_console as sc
    from spectra.services import scene_store

    scene = _seed_scene(entry_ramp_ms=0)
    _run(sc.apply_scene_setting(scene.id, "entry_ramp_ms", 100))   # edit A
    _run(sc.apply_scene_setting(scene.id, "entry_ramp_ms", 200))   # edit B
    assert scene_store.get_by_id(scene.id).entry_ramp_ms == 200

    _run(sc.apply_undo_last_scene_change())  # undo B -> back to A's result
    assert scene_store.get_by_id(scene.id).entry_ramp_ms == 100

    _run(sc.apply_undo_last_scene_change())  # undo the undo -> back to B
    assert scene_store.get_by_id(scene.id).entry_ramp_ms == 200


def test_undo_with_nothing_to_undo_is_rejected():
    from spectra.services import scene_console as sc

    with pytest.raises(sc.SceneOpError, match="nothing to undo"):
        _run(sc.apply_undo_last_scene_change())


def test_create_scene_is_never_an_undo_candidate():
    """create_scene carries no backup_id (nothing existed before it to
    restore), so it must never be the target of undo_last_scene_change —
    there is still no delete operation, so 'undoing' a create is not
    something this mechanism can or should attempt."""
    from spectra.services import scene_console as sc

    _run(sc.apply_create_scene("Freshly created"))
    with pytest.raises(sc.SceneOpError, match="nothing to undo"):
        _run(sc.apply_undo_last_scene_change())


def test_undo_is_global_across_scenes_targets_the_most_recent_edit_anywhere():
    from spectra.services import scene_console as sc
    from spectra.services import scene_store

    a = _seed_scene(name="Scene A", entry_ramp_ms=0)
    b = _seed_scene(name="Scene B", entry_ramp_ms=0)
    _run(sc.apply_scene_setting(a.id, "entry_ramp_ms", 111))
    _run(sc.apply_scene_setting(b.id, "entry_ramp_ms", 222))

    result = _run(sc.apply_undo_last_scene_change())

    assert result["scene_id"] == b.id
    assert scene_store.get_by_id(b.id).entry_ramp_ms == 0, "B's edit (the most recent) was undone"
    assert scene_store.get_by_id(a.id).entry_ramp_ms == 111, "A's edit is untouched — it wasn't the most recent"


# ── 9d. restore_scene_backup: pick-a-point, including permanent genesis ──

def test_restore_to_genesis_returns_a_scene_edited_many_times_to_its_original():
    from spectra.services import scene_console as sc
    from spectra.services import scene_store

    scene = _seed_scene(name="STAR", entry_ramp_ms=0)
    original_dump = scene_store.get_by_id(scene.id).model_dump(mode="json")

    _run(sc.apply_scene_setting(scene.id, "entry_ramp_ms", 500))
    _run(sc.apply_flare_kind(scene.id, name="Boom", type="permanent", params={"gain": 1.0}))
    _run(sc.apply_overwrite_scene(scene.id, name="STAR (mangled)", settings={"entry_ramp_ms": 9999}))
    mangled = scene_store.get_by_id(scene.id)
    assert mangled.name == "STAR (mangled)" and mangled.flare_kinds

    result = _run(sc.apply_restore_scene_backup(scene.id, "genesis"))
    assert result["status"] == "applied"

    restored = scene_store.get_by_id(scene.id)
    assert restored.model_dump(mode="json") == original_dump, \
        "restoring genesis must reproduce the ORIGINAL scene exactly, byte for byte"


def test_restore_to_a_specific_ring_entry_not_just_the_most_recent():
    from spectra.services import scene_console as sc
    from spectra.services import scene_store

    scene = _seed_scene(entry_ramp_ms=0)
    _run(sc.apply_scene_setting(scene.id, "entry_ramp_ms", 100))
    r2 = _run(sc.apply_scene_setting(scene.id, "entry_ramp_ms", 200))
    _run(sc.apply_scene_setting(scene.id, "entry_ramp_ms", 300))
    assert scene_store.get_by_id(scene.id).entry_ramp_ms == 300

    # r2["backup_id"] is the pre-edit-2 snapshot (value 100) — restoring
    # it should NOT require stepping back one-at-a-time via undo.
    _run(sc.apply_restore_scene_backup(scene.id, r2["backup_id"]))
    assert scene_store.get_by_id(scene.id).entry_ramp_ms == 100


def test_restore_with_unknown_backup_id_is_rejected_with_the_servers_own_text():
    from spectra.services import scene_console as sc

    scene = _seed_scene()
    with pytest.raises(sc.SceneOpError, match="no backup"):
        _run(sc.apply_restore_scene_backup(scene.id, "not-a-real-backup-id"))


def test_restore_is_itself_backed_up_so_it_is_never_a_dead_end():
    from spectra.services import scene_console as sc
    from spectra.services import scene_store

    scene = _seed_scene(entry_ramp_ms=0)
    _run(sc.apply_scene_setting(scene.id, "entry_ramp_ms", 500))
    _run(sc.apply_restore_scene_backup(scene.id, "genesis"))
    assert scene_store.get_by_id(scene.id).entry_ramp_ms == 0

    # undo the restore itself — should bring back the 500 state.
    _run(sc.apply_undo_last_scene_change())
    assert scene_store.get_by_id(scene.id).entry_ramp_ms == 500


# ── 9e. his 9 real, authored scenes stay recoverable under the new
# genuinely-destructive capability — the anchor, not just the enumeration ─

def test_his_real_scenes_get_a_genesis_anchor_on_first_touch_and_survive_bad_edits():
    ids = _seed_his_real_scenes()
    from spectra.services import scene_console as sc
    from spectra.services import scene_store

    star_id = ids["STAR"]
    original = scene_store.get_by_id(star_id).model_dump(mode="json")

    # A legitimately destructive overwrite — now possible by design.
    _run(sc.apply_overwrite_scene(star_id, name="STAR (accidentally clobbered)",
                                  settings={"entry_ramp_ms": 1}))
    _run(sc.apply_overwrite_scene(star_id, name="STAR (clobbered again)",
                                  flare_kinds=[{"name": "Oops", "type": "permanent",
                                               "params": {"gain": 1.0}}]))
    clobbered = scene_store.get_by_id(star_id)
    assert clobbered.name != "STAR"

    restored = _run(sc.apply_restore_scene_backup(star_id, "genesis"))
    assert restored["status"] == "applied"
    assert scene_store.get_by_id(star_id).model_dump(mode="json") == original, \
        "his real scene's exact original state survives any chain of bad edits"

    # And every OTHER real scene remained completely untouched throughout.
    for name, sid in ids.items():
        if sid == star_id:
            continue
        assert scene_store.get_by_id(sid).name == name


# ── 9f. overwrite_scene's own validation, mirroring the other write ops ──

def test_overwrite_scene_rejects_an_unknown_settings_key():
    from spectra.services import scene_console as sc

    scene = _seed_scene()
    with pytest.raises(sc.SceneOpError, match="not a scene setting"):
        sc._validate_overwrite_scene(scene.id, None, None, {"brightness_multiplier": 0.5}, None)


def test_overwrite_scene_rejects_a_blank_name():
    from spectra.services import scene_console as sc

    scene = _seed_scene()
    with pytest.raises(sc.SceneOpError, match="cannot be blanked"):
        sc._validate_overwrite_scene(scene.id, "   ", None, None, None)


def test_overwrite_scene_omitted_fields_are_left_alone():
    from spectra.services import scene_console as sc
    from spectra.services import scene_store

    scene = _seed_scene(name="Keep Me", entry_ramp_ms=42, labels=["a", "b"])
    _run(sc.apply_overwrite_scene(scene.id, settings={"accept_all_sets": False}))

    after = scene_store.get_by_id(scene.id)
    assert after.name == "Keep Me", "name wasn't passed — must stay unchanged"
    assert after.labels == ["a", "b"], "labels weren't passed — must stay unchanged"
    assert after.entry_ramp_ms == 42, "not in the settings dict — must stay unchanged"
    assert after.accept_all_sets is False


def test_overwrite_scene_replaces_flare_kinds_wholesale_not_merges():
    from spectra.services import scene_console as sc
    from spectra.services import scene_store

    scene = _seed_scene()
    _run(sc.apply_flare_kind(scene.id, name="Old", type="permanent", params={"gain": 1.0}))
    _run(sc.apply_overwrite_scene(scene.id, flare_kinds=[
        {"name": "New", "type": "permanent", "params": {"gain": 1.0}}]))

    kinds = [k.name for k in scene_store.get_by_id(scene.id).flare_kinds]
    assert kinds == ["New"], "flare_kinds is a REPLACE, not a merge — 'Old' must be gone"


# ── 9g. discovery — the new operations are queryable, per the same
# one-declaration principle as everything else in this file ─────────────

def test_new_operations_are_discoverable_via_list_operations():
    from spectra.services import settings_agent as sa

    idx = _run(sa._dispatch("list_operations", {"domain": "scene"}))
    names = {o["name"] for o in idx["operations"]}
    for expected in ("overwrite_scene", "list_scene_backups", "get_scene_preview",
                     "restore_scene_backup", "undo_last_scene_change"):
        assert expected in names

    detail = _run(sa._dispatch("list_operations", {"name": "overwrite_scene"}))
    assert "backup" in detail["operation"]["instructions"].lower()


# ═══ 10. parameter discovery (his ask: "visibility into parameters and
# such and what they do") — generated from the REAL definitions (fx/
# device_model.py reading the vendored effect schema), never a second
# hand-written catalogue ═══════════════════════════════════════════════

def _seed_scene_with_devices(name="Throwaway", effect_type="fireworks"):
    from spectra.models.scene import SceneDeviceConfig
    return _seed_scene(name, devices=[
        SceneDeviceConfig(target_kind="all", effect_type=effect_type)])


def test_list_scene_params_groups_by_the_scenes_real_effects():
    from spectra.services import scene_console as sc

    scene = _seed_scene_with_devices()
    result = sc.list_scene_params(scene.id)
    assert result["effects"] == [{"effect_type": "fireworks",
                                  "params": sorted(result["effects"][0]["params"])}]
    assert "reverse" in result["effects"][0]["params"]
    # cheap index only — no per-param detail leaked into the list call
    assert all(isinstance(p, str) for p in result["effects"][0]["params"])


def test_list_scene_params_unknown_scene_rejected():
    from spectra.services import scene_console as sc

    with pytest.raises(sc.SceneOpError, match="no scene with id"):
        sc.list_scene_params("nonexistent-id")


def test_list_scene_params_empty_for_a_deviceless_scene():
    from spectra.services import scene_console as sc

    scene = _seed_scene()  # no devices
    assert sc.list_scene_params(scene.id)["effects"] == []


def test_get_param_info_matches_the_real_vendored_schema_not_a_guess():
    """The concrete real-world case: his "Reverse Direction" flare kind set
    reverse=1.0 on a fireworks-carrying scene. get_param_info must describe
    that exact parameter, in his language, sourced live from fx/effects/
    fireworks.py's own CONFIG_SCHEMA — never a hand-typed second copy that
    could go stale."""
    from spectra.services import scene_console as sc

    info = sc.get_param_info("fireworks", "reverse")
    assert info["effect_type"] == "fireworks"
    assert info["name"] == "reverse"
    assert info["type"] == "toggle"
    assert "implode" in info["description"].lower()


def test_get_param_info_description_cannot_drift_from_a_live_schema_edit():
    """Proves the description is read LIVE, not baked/cached at import time
    — the strongest form of "cannot describe a parameter that no longer
    behaves that way": change the real schema, the catalogue changes too,
    with nothing else to edit."""
    import voluptuous as vol
    from fx import device_model
    from fx.effects import power

    device_model.refresh()
    before = device_model.param_descriptions("power")["blur"]
    assert before == "Amount to blur the effect"

    original_schema = power.PowerAudioEffect.CONFIG_SCHEMA
    try:
        power.PowerAudioEffect.CONFIG_SCHEMA = vol.Schema({
            vol.Optional("blur", description="A completely different description", default=0.0):
                vol.All(vol.Coerce(float), vol.Range(min=0.0, max=10)),
        })
        device_model.refresh()
        after = device_model.param_descriptions("power")["blur"]
        assert after == "A completely different description"
    finally:
        power.PowerAudioEffect.CONFIG_SCHEMA = original_schema
        device_model.refresh()


def test_get_param_info_unknown_effect_type_rejected_with_known_types():
    from spectra.services import scene_console as sc

    with pytest.raises(sc.SceneOpError) as exc:
        sc.get_param_info("not-a-real-effect", "reverse")
    assert "no such effect type" in str(exc.value)
    assert "fireworks" in exc.value.detail["known_effect_types"]


def test_get_param_info_unknown_param_name_rejected_with_known_params():
    from spectra.services import scene_console as sc

    with pytest.raises(sc.SceneOpError) as exc:
        sc.get_param_info("fireworks", "not-a-real-param")
    assert "has no parameter named" in str(exc.value)
    assert "reverse" in exc.value.detail["known_params"]


def test_dispatch_reaches_both_new_param_operations():
    from spectra.services import settings_agent as sa

    scene = _seed_scene_with_devices()
    listed = _run(sa._dispatch("list_scene_params", {"scene_id": scene.id}))
    assert listed["effects"][0]["effect_type"] == "fireworks"

    info = _run(sa._dispatch("get_param_info", {"effect_type": "fireworks", "name": "reverse"}))
    assert info["type"] == "toggle"


# ═══ 11. the "did it work" line — one deterministic, plain-language
# summary on every write result, never the model's own account (2026-08-17
# fix: he watched Sonic dump a raw JSON diff instead of a clear answer) ══

def test_every_write_op_result_carries_a_plain_language_summary():
    from spectra.services import scene_console as sc

    created = _run(sc.apply_create_scene("Warm Fade"))
    assert created["summary"] == 'Created scene "Warm Fade".'

    scene = _seed_scene()
    setting = _run(sc.apply_scene_setting(scene.id, "entry_ramp_ms", 1500))
    assert setting["summary"] == 'Set Entry blend to 1500 on "Throwaway".'

    flare = _run(sc.apply_flare_kind(
        scene.id, name="Reverse Direction", type="momentary",
        params={"reverse": 1.0}, hold_ms=500))
    assert flare["summary"] == 'Created flare kind "Reverse Direction" on "Throwaway".'

    flare2 = _run(sc.apply_flare_kind(
        scene.id, name="Reverse Direction", type="momentary",
        params={"reverse": 1.0}, hold_ms=750))
    assert flare2["summary"] == 'Updated flare kind "Reverse Direction" on "Throwaway".'

    removed = _run(sc.apply_remove_flare_kind(scene.id, "Reverse Direction"))
    assert removed["summary"] == 'Removed flare kind "Reverse Direction" from "Throwaway".'


def test_flare_kind_summary_never_contains_the_raw_json_diff():
    """The literal regression: creating a second flare kind on a scene
    that already has one diffs the WHOLE flare_kinds list (_diff_scenes'
    own documented "nested structure -> whole field" behavior) — the
    summary line must stay a short plain sentence regardless, never grow
    with however many flare kinds the scene already has."""
    from spectra.services import scene_console as sc

    scene = _seed_scene()
    _run(sc.apply_flare_kind(scene.id, name="First", type="permanent", params={"gain": 1.2}))
    _run(sc.apply_flare_kind(scene.id, name="Second", type="permanent", params={"gain": 1.3}))
    result = _run(sc.apply_flare_kind(scene.id, name="Third", type="permanent", params={"gain": 1.4}))

    assert result["summary"] == 'Created flare kind "Third" on "Throwaway".'
    assert len(result["summary"]) < 80
    assert "{" not in result["summary"] and "[" not in result["summary"]
    # the raw diff is still there for the UI's own dedicated preview
    # rendering — this test only asserts the SUMMARY line stays short
    assert len(result["preview"]["flare_kinds"]["after"]) == 3


def test_overwrite_and_restore_and_undo_summaries_are_plain_language():
    from spectra.services import scene_console as sc

    scene = _seed_scene()
    overwritten = _run(sc.apply_overwrite_scene(scene.id, name="Renamed"))
    assert overwritten["summary"].startswith('Overwrote scene "Renamed" — changed:')

    restored = _run(sc.apply_restore_scene_backup(scene.id, "genesis"))
    assert restored["summary"] == 'Restored "Throwaway" to its original, pre-Sonic version.'

    _run(sc.apply_scene_setting(scene.id, "entry_ramp_ms", 999))
    undone = _run(sc.apply_undo_last_scene_change())
    assert undone["summary"].startswith('Undid the last change to "')


def test_rejected_scene_write_has_a_plain_reason_no_summary_needed():
    """A refusal's own `reason` already IS the plain-language failure
    statement — no separate `summary` field is needed on that side (see
    settings_agent.SYSTEM_PROMPT)."""
    from spectra.services import scene_console as sc

    result = _run(sc._op_set_scene_setting("nonexistent-id", "entry_ramp_ms", 500))
    assert result["status"] == "rejected"
    assert result["reason"] == "no scene with id 'nonexistent-id'"


def test_run_turn_surfaces_rejections_structurally_not_only_applied(monkeypatch):
    """His 'if it failed, that says so just as plainly' ask needs a
    rejected write's real `reason` available the same way an applied
    write's `summary` is — never only inferred from the model's prose."""
    from spectra.services import settings_agent as sa

    tool_use = _FakeBlock(
        "tool_use", id="tu_1", name="set_scene_setting",
        input={"scene_id": "nonexistent-id", "key": "entry_ramp_ms", "value": 500})
    first = _FakeResponse([tool_use])
    second = _FakeResponse([_FakeBlock("text", text="That scene doesn't exist.")])
    monkeypatch.setattr(sa, "_client", lambda: _FakeClient([first, second]))

    result = _run(sa.run_turn(None, "set entry ramp on a scene that doesn't exist"))
    assert result["changes"] == []
    assert len(result["rejected"]) == 1
    assert "no scene with id" in result["rejected"][0]["reason"]
