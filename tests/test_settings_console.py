"""The settings-console MECHANISM + AUTHORITY BOUNDARY (standing order 5) —
offline proof, no network, no ANTHROPIC_API_KEY required for the bulk of
this file.

The proofs:
  1. SETTINGS_REGISTRY is a real, explicit allowlist — every key exists on
     RoomControlState and carries the SAME bounds RoomControlState enforces.
  2. validate_change/apply_change reject an unknown key, an out-of-range
     value (with the legal range + nearest legal value surfaced), and a
     malformed hex colour — nothing persists on rejection.
  3. apply_change persists through room_controls' own store + ambient
     reconcile (the same calls the human PUT handler makes) and leaves a
     visible, bounded change-log entry; undo reverts through the SAME
     validated path and marks the original entry undone.
  4. settings_agent._dispatch is the WHOLE tool-name -> code mapping: only
     "get_settings" and "set_setting" do anything; any other name is
     rejected without touching storage — proof the boundary is structural,
     not a prompt instruction, and provable without a live model call.
  5. The API layer: registry/log/undo/message/transcribe all respond
     correctly offline, including the 503s a missing ANTHROPIC_API_KEY /
     unwired transcriber produce.

One test (test_live_model_can_apply_a_change) additionally proves the real
tool loop against the live Anthropic API — SKIPPED here (no
ANTHROPIC_API_KEY in this sandbox); it would run this exact suite's own
assertions against a real model when a key is present.
"""
from __future__ import annotations

import asyncio
import os

import httpx
import pytest


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path)
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")
    monkeypatch.setattr(scfg, "SETTINGS_LOG_FILE", tmp_path / "settings_log.json")
    monkeypatch.setattr(scfg, "SCENES_FILE", tmp_path / "scenes.json")
    monkeypatch.setattr(scfg, "COLOR_SETS_FILE", tmp_path / "color_sets.json")
    # Unconfigured by default, regardless of the host env — tests that need
    # a "bridge configured" state override this explicitly.
    monkeypatch.setattr(scfg, "whisper_bridge_url", lambda: None)

    from spectra.services import settings_agent
    settings_agent._SESSIONS.clear()


# ═══ 1. registry ═════════════════════════════════════════════════════════

def test_registry_is_an_explicit_allowlist_matching_room_control_bounds():
    from spectra.services import room_controls as rc
    from spectra.services import settings_console as sc

    assert set(sc.SETTINGS_REGISTRY) == {
        "brightness_multiplier", "global_transition_ms",
        "scene_transition_ms_gentle", "scene_transition_ms_hard",
        "ambient_enabled", "ambient_on_music_pause", "ambient_color",
        "scene_change_mode", "transition_window_beats",
        "transition_edge_sensitivity", "transitions_per_minute",
        "scene_changes_per_minute",
        # 2026-10-06 Sonic coverage audit build (build item D15):
        "midsong_snap_to_beat", "display_mode", "rainbow_select_limit",
        "drop_confident_score", "drop_suggested_score",
        # 2026-10-06, the Admiral's own drop-floor ask:
        "drop_floor",
    }
    # force_scene_* deliberately excluded — see settings_console.py docstring
    assert "force_scene_enabled" not in sc.SETTINGS_REGISTRY
    assert "force_scene_scene_id" not in sc.SETTINGS_REGISTRY

    spec = sc.SETTINGS_REGISTRY["brightness_multiplier"]
    ge, le = rc.field_bounds("brightness_multiplier")
    assert (spec.min, spec.max) == (ge, le) == (0.0, 1.0), \
        "registry bounds are READ from RoomControlState, not re-typed"

    assert sc.SETTINGS_REGISTRY["scene_change_mode"].choices == \
        ["transitions", "analysed", "triggers_only", "full"]


# ═══ 2. validation rejects, nothing persists ════════════════════════════

def test_unknown_key_rejected():
    from spectra.services import settings_console as sc

    with pytest.raises(sc.SettingChangeError) as exc:
        sc.validate_change("force_scene_enabled", True)
    assert "allowed_keys" in exc.value.detail
    assert "force_scene_enabled" not in exc.value.detail["allowed_keys"]


def test_out_of_range_rejected_with_nearest_legal_value():
    from spectra.services import settings_console as sc

    with pytest.raises(sc.SettingChangeError) as exc:
        sc.validate_change("brightness_multiplier", 2.0)
    assert exc.value.detail["nearest_legal_value"] == 1.0

    with pytest.raises(sc.SettingChangeError) as exc:
        sc.validate_change("global_transition_ms", -500)
    assert exc.value.detail["nearest_legal_value"] == 0


def test_bad_enum_and_bad_hex_rejected():
    from spectra.services import settings_console as sc

    with pytest.raises(sc.SettingChangeError):
        sc.validate_change("scene_change_mode", "sometimes")
    with pytest.raises(sc.SettingChangeError):
        sc.validate_change("ambient_color", "chartreuse")
    with pytest.raises(sc.SettingChangeError):
        sc.validate_change("ambient_color", "#zzzzzz")


def test_rejection_never_writes(tmp_path):
    from spectra import config as scfg
    from spectra.services import settings_console as sc

    with pytest.raises(sc.SettingChangeError):
        sc.validate_change("brightness_multiplier", 5.0)
    assert not scfg.ROOM_CONTROLS_FILE.exists()
    assert not scfg.SETTINGS_LOG_FILE.exists()


# ═══ 3. apply_change + log + undo ════════════════════════════════════════

def test_apply_change_persists_and_logs():
    from spectra.services import room_controls as rc
    from spectra.services import settings_console as sc

    result = _run(sc.apply_change("brightness_multiplier", 0.4))
    assert result["status"] == "applied"
    assert result["old_value"] == 1.0 and result["new_value"] == 0.4
    assert rc.load_room_controls().brightness_multiplier == 0.4

    log = sc.load_log()
    assert len(log) == 1 and log[0]["key"] == "brightness_multiplier"
    assert log[0]["source"] == "agent" and log[0]["undone"] is False


def test_apply_change_reconciles_ambient_only_on_ambient_fields():
    from spectra.services import settings_console as sc

    result = _run(sc.apply_change("brightness_multiplier", 0.6))
    assert "ambient_result" not in result, \
        "unrelated field change must not trigger a reconnect"

    for key, value in (("ambient_on_music_pause", True), ("ambient_enabled", True)):
        result = _run(sc.apply_change(key, value))
        assert result["ambient_result"]["status"] == "dark", \
            (f"{key} is an ambient field, so it reconciles — 'dark' is the "
             "gate's own honest report that no live stack is owned in tests, "
             "not the gate declining to act")
        assert result["ambient_result"]["phase"] == "unavailable", \
            "and it names WHY, rather than reporting a settled state"
        assert result["ambient_result"]["stored"] is True, \
            ("the intent is durable and applies on the next take-back — "
             "never a silent nothing (services/ambient_music_gate.py, "
             "'THE RELEASED ROOM')")


def test_undo_reverts_through_the_validated_path():
    from spectra.services import room_controls as rc
    from spectra.services import settings_console as sc

    _run(sc.apply_change("brightness_multiplier", 0.9))
    _run(sc.apply_change("brightness_multiplier", 0.2))
    assert rc.load_room_controls().brightness_multiplier == 0.2

    undone = _run(sc.undo_last_change())
    assert undone["new_value"] == 0.9
    assert rc.load_room_controls().brightness_multiplier == 0.9

    log = sc.load_log()
    assert log[0]["source"] == "undo" and log[0]["new_value"] == 0.9
    assert log[1]["undone"] is True, "the reverted entry is marked, not deleted"


def test_undo_with_empty_log_rejected():
    from spectra.services import settings_console as sc

    with pytest.raises(sc.SettingChangeError):
        _run(sc.undo_last_change())


# ═══ 4. the tool-dispatch boundary itself ════════════════════════════════

def test_dispatch_recognizes_exactly_the_declared_settings_tools():
    """Sonic's tool set is now wider than settings alone (see
    tests/test_scene_console.py for the full merged-boundary proof, which
    is where the exhaustive full-set assertion now lives) — this file only
    proves the settings domain is exactly these five ops: the original
    get_settings/set_setting, plus the 2026-10-06 Force Scene/Force
    Colour trio (set_force_scene/set_force_color/get_force_pins — by
    NAME, not registry keys; see the module docstring)."""
    from spectra.services import settings_agent as sa
    from spectra.services import settings_console as sc

    assert set(sc.OPERATIONS) == {
        "get_settings", "set_setting",
        "get_force_pins", "set_force_scene", "set_force_color",
    }
    assert set(sc.OPERATIONS) <= {t["name"] for t in sa.TOOLS}


def test_dispatch_get_settings_is_read_only():
    from spectra import config as scfg
    from spectra.services import settings_agent as sa

    result = _run(sa._dispatch("get_settings", {}))
    assert "settings" in result
    assert not scfg.ROOM_CONTROLS_FILE.exists(), "a read never creates the store"


def test_dispatch_set_setting_applies_a_valid_change():
    from spectra.services import room_controls as rc
    from spectra.services import settings_agent as sa

    result = _run(sa._dispatch("set_setting", {"key": "brightness_multiplier", "value": 0.3}))
    assert result["status"] == "applied"
    assert rc.load_room_controls().brightness_multiplier == 0.3


def test_dispatch_set_setting_rejects_disallowed_key_without_writing():
    from spectra import config as scfg
    from spectra.services import settings_agent as sa

    result = _run(sa._dispatch("set_setting", {"key": "force_scene_enabled", "value": True}))
    assert result["status"] == "rejected"
    assert not scfg.ROOM_CONTROLS_FILE.exists()


def test_dispatch_unknown_tool_name_is_rejected_not_executed():
    """No real model response can ever name a tool outside TOOLS — the
    Anthropic API only emits tool_use blocks for declared tools — but this
    proves the SERVER side of the boundary too: even a fabricated tool_use
    for something like 'run_shell' or 'restart_service' hits the same
    exhaustive if/elif and falls through to rejection, because no such
    branch exists to reach."""
    from spectra import config as scfg
    from spectra.services import settings_agent as sa

    for name in ("run_shell", "restart_service", "http_request", "read_file"):
        result = _run(sa._dispatch(name, {"cmd": "rm -rf /"}))
        assert result["status"] == "rejected"
    assert not scfg.ROOM_CONTROLS_FILE.exists()


# ═══ 5. API layer ═════════════════════════════════════════════════════════

def test_api_registry_and_log_and_undo():
    from fastapi.testclient import TestClient

    from spectra.app import create_app
    from spectra.services import settings_console as sc

    client = TestClient(create_app())

    r = client.get("/api/settings-console/registry")
    assert r.status_code == 200
    assert {s["key"] for s in r.json()["settings"]} == set(sc.SETTINGS_REGISTRY)

    r = client.post("/api/settings-console/undo")
    assert r.status_code == 409, "nothing applied yet — nothing to undo"

    r = client.get("/api/settings-console/log")
    assert r.status_code == 200 and r.json() == []


def test_api_message_503_without_api_key(monkeypatch):
    from fastapi.testclient import TestClient

    from spectra import config as scfg
    from spectra.app import create_app

    monkeypatch.setattr(scfg, "settings_agent_api_key", lambda: "")
    client = TestClient(create_app())
    r = client.post("/api/settings-console/message", json={"text": "set brightness to half"})
    assert r.status_code == 503
    assert "ANTHROPIC_API_KEY" in r.json()["detail"]


def test_api_transcribe_503_transcriber_unwired():
    from fastapi.testclient import TestClient

    from spectra.app import create_app

    client = TestClient(create_app())
    r = client.post(
        "/api/settings-console/transcribe",
        files={"audio": ("clip.webm", b"\x00\x01\x02", "audio/webm")},
    )
    assert r.status_code == 503
    assert "type your request" in r.json()["detail"]


def test_vocabulary_hint_degrades_gracefully_with_no_stores():
    from spectra.services import transcription

    hint = transcription.vocabulary_hint()
    assert isinstance(hint, str)


# ═══ the wire contract: a silently-ignored vocabulary is a hard failure ══
# (2026-08-14, coordinated with the ship building the local-Whisper bridge
# against this endpoint — see transcription.py's wire-contract docstring)

def test_api_transcribe_hard_fails_when_vocabulary_silently_ignored(monkeypatch):
    """A concrete transcriber that returns text WITHOUT confirming it used
    the vocabulary hint must be rejected (502), never accepted as a normal
    200 — a request whose vocabulary was silently ignored is a bug in the
    transcriber, not a degraded-but-fine transcription."""
    from fastapi.testclient import TestClient

    from spectra.app import create_app
    from spectra.services import transcription

    async def forgetful_transcribe(audio, mime_type, vocabulary=""):
        return transcription.TranscriptionResult(text="whatever it heard")  # vocabulary_honored left None

    monkeypatch.setattr(transcription, "transcribe", forgetful_transcribe)
    monkeypatch.setattr(transcription, "vocabulary_hint", lambda: "Sunset Drift Warm White")

    client = TestClient(create_app())
    r = client.post(
        "/api/settings-console/transcribe",
        files={"audio": ("clip.webm", b"\x00\x01\x02", "audio/webm;codecs=opus")},
    )
    assert r.status_code == 502
    assert "vocabulary" in r.json()["detail"]


def test_api_transcribe_accepts_a_confirmed_vocabulary_use(monkeypatch):
    from fastapi.testclient import TestClient

    from spectra.app import create_app
    from spectra.services import transcription

    async def honest_transcribe(audio, mime_type, vocabulary=""):
        assert vocabulary == "Sunset Drift Warm White"
        return transcription.TranscriptionResult(text="turn on sunset drift", vocabulary_honored=True)

    monkeypatch.setattr(transcription, "transcribe", honest_transcribe)
    monkeypatch.setattr(transcription, "vocabulary_hint", lambda: "Sunset Drift Warm White")

    client = TestClient(create_app())
    r = client.post(
        "/api/settings-console/transcribe",
        files={"audio": ("clip.webm", b"\x00\x01\x02", "audio/webm;codecs=opus")},
    )
    assert r.status_code == 200
    assert r.json() == {"text": "turn on sunset drift", "vocabulary_honored": True}


def test_api_transcribe_empty_vocabulary_needs_no_confirmation(monkeypatch):
    """No vocabulary to honor (e.g. an empty library) is not a failure —
    only a NON-empty, silently-dropped vocabulary is."""
    from fastapi.testclient import TestClient

    from spectra.app import create_app
    from spectra.services import transcription

    async def bare_transcribe(audio, mime_type, vocabulary=""):
        return transcription.TranscriptionResult(text="turn on sunset drift")

    monkeypatch.setattr(transcription, "transcribe", bare_transcribe)
    monkeypatch.setattr(transcription, "vocabulary_hint", lambda: "")

    client = TestClient(create_app())
    r = client.post(
        "/api/settings-console/transcribe",
        files={"audio": ("clip.webm", b"\x00\x01\x02", "audio/webm;codecs=opus")},
    )
    assert r.status_code == 200


# ═══ the bridge-facing contract itself (2026-08-15) — proven with an
# httpx.MockTransport, never a real socket. The real bridge is confirmed
# NOT running right now (its ship tore its test container down); these
# tests prove transcribe()'s SHAPE against the published contract without
# touching — or hunting for — anything on the real host. ═══════════════

def test_transcribe_rejects_a_streamed_audio_argument(monkeypatch):
    """The bridge requires fixed Content-Length and rejects chunked
    transfer-encoding; httpx only guarantees that when `content` is bytes.
    A caller handing transcribe() a file-like/iterator must be refused
    before any request is attempted, not silently streamed."""
    from spectra import config as scfg
    from spectra.services import transcription

    monkeypatch.setattr(scfg, "whisper_bridge_url", lambda: "http://bridge.example")
    with pytest.raises(transcription.TranscriptionUnavailable, match="raw bytes"):
        _run(transcription.transcribe(iter([b"chunk"]), "audio/webm"))


def test_transcribe_rejects_audio_over_the_bridge_cap(monkeypatch):
    from spectra import config as scfg
    from spectra.services import transcription

    monkeypatch.setattr(scfg, "whisper_bridge_url", lambda: "http://bridge.example")
    oversized = b"0" * (transcription.BRIDGE_MAX_AUDIO_BYTES + 1)
    with pytest.raises(transcription.TranscriptionUnavailable, match="cap"):
        _run(transcription.transcribe(oversized, "audio/webm"))


def test_transcribe_sends_fixed_length_never_chunked_and_the_documented_headers(monkeypatch):
    from spectra import config as scfg
    from spectra.services import transcription

    monkeypatch.setattr(scfg, "whisper_bridge_url", lambda: "http://bridge.example")
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["content_length"] = request.headers.get("content-length")
        captured["transfer_encoding"] = request.headers.get("transfer-encoding")
        captured["content_type"] = request.headers.get("content-type")
        captured["x_vocabulary"] = request.headers.get("x-vocabulary")
        captured["body"] = request.content
        return httpx.Response(200, json={"text": "turn on sunset drift", "vocabulary_applied": True})

    monkeypatch.setattr(transcription, "_client",
                        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0))

    result = _run(transcription.transcribe(
        b"abc123", "audio/webm;codecs=opus", vocabulary="Sunset Drift"))

    assert result == transcription.TranscriptionResult(
        text="turn on sunset drift", vocabulary_honored=True)
    assert captured["url"] == "http://bridge.example/transcribe"
    assert captured["content_length"] == "6", "fixed-length body, not chunked"
    assert captured["transfer_encoding"] is None
    assert captured["content_type"] == "audio/webm;codecs=opus", \
        "forwarded exactly what the browser sent, never renegotiated"
    assert captured["x_vocabulary"] == "Sunset%20Drift", "percent-encoded for a header"
    assert captured["body"] == b"abc123", "raw bytes, never multipart-wrapped"


def test_transcribe_raises_when_bridge_does_not_confirm_vocabulary(monkeypatch):
    from spectra import config as scfg
    from spectra.services import transcription

    monkeypatch.setattr(scfg, "whisper_bridge_url", lambda: "http://bridge.example")

    def handler(request):
        return httpx.Response(200, json={"text": "generic text", "vocabulary_applied": False})

    monkeypatch.setattr(transcription, "_client",
                        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0))

    with pytest.raises(transcription.VocabularyNotHonored):
        _run(transcription.transcribe(b"abc", "audio/webm", vocabulary="Sunset Drift"))


def test_transcribe_connection_refused_is_the_honest_unavailable_state(monkeypatch):
    """The real bridge is confirmed down tonight — this is what that
    actually produces: an ordinary connection error, handled as the
    already-built 503 path, never chased with a retry or a port scan."""
    from spectra import config as scfg
    from spectra.services import transcription

    monkeypatch.setattr(scfg, "whisper_bridge_url", lambda: "http://127.0.0.1:8090")

    def handler(request):
        raise httpx.ConnectError("Connection refused", request=request)

    monkeypatch.setattr(transcription, "_client",
                        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0))

    with pytest.raises(transcription.TranscriptionUnavailable, match="unreachable"):
        _run(transcription.transcribe(b"abc", "audio/webm"))


# ═══ 5b. the three new room-control registry keys (build item D15) ═════

def test_new_registry_keys_are_readable_and_writable():
    from spectra.services import settings_console as sc

    for key, value in (("midsong_snap_to_beat", False),
                       ("display_mode", "dark"),
                       ("rainbow_select_limit", 0.5),
                       ("drop_confident_score", 1.2),
                       ("drop_suggested_score", 0.6)):
        result = _run(sc.apply_change(key, value))
        assert result["status"] == "applied"
        assert sc.current_values()[key] == value


def test_display_mode_is_an_enum_with_its_real_choices():
    from spectra.services import settings_console as sc

    spec = sc.SETTINGS_REGISTRY["display_mode"]
    assert spec.kind == "enum"
    assert set(spec.choices) == {"default", "dark", "light"}
    with pytest.raises(sc.SettingChangeError):
        _run(sc.apply_change("display_mode", "not-a-real-mode"))


# ═══ 5c. Force Scene / Force Colour by NAME (his ruling, 2026-10-06:
# "allow some flexibility in phrasing ... it should be a close match") ═══

def test_set_force_scene_by_exact_name(monkeypatch):
    from spectra.models.scene import SceneV2
    from spectra.services import room_controls as rc
    from spectra.services import scene_compiler, scene_store
    from spectra.services import settings_console as sc

    scene = SceneV2(name="Orbits V2")
    scene_store.save(scene)

    fired = []

    async def fake_fire_scene(s, *, intensity=0.5, color_set=None, dry_run=True, rng=None):
        fired.append(s.id)
        return {"dry_run": dry_run, "intensity": intensity, "writes": [],
               "resolved_bindings": {}, "dice_rolls": {}}
    monkeypatch.setattr(scene_compiler, "fire_scene", fake_fire_scene)

    result = _run(sc.apply_force_scene(True, "Orbits V2"))
    assert result["status"] == "applied"
    assert result["scene_id"] == scene.id
    assert fired == [scene.id]
    assert rc.load_room_controls().force_scene_enabled is True
    assert rc.load_room_controls().force_scene_scene_id == scene.id


def test_set_force_scene_tolerates_a_dropped_v2_suffix(monkeypatch):
    """His own example, verbatim: 'I know we have scenes named with "V2"
    at the end, and I don't want to have to say that.'"""
    from spectra.models.scene import SceneV2
    from spectra.services import scene_compiler, scene_store
    from spectra.services import settings_console as sc

    scene = SceneV2(name="Orbits V2")
    scene_store.save(scene)

    async def fake_fire_scene(s, *, intensity=0.5, color_set=None, dry_run=True, rng=None):
        return {"dry_run": dry_run, "intensity": intensity, "writes": [],
               "resolved_bindings": {}, "dice_rolls": {}}
    monkeypatch.setattr(scene_compiler, "fire_scene", fake_fire_scene)

    result = _run(sc.apply_force_scene(True, "Orbits"))
    assert result["status"] == "applied"
    assert result["scene_name"] == "Orbits V2"


def test_set_force_scene_refuses_a_near_tie_between_two_scenes():
    from spectra.models.scene import SceneV2
    from spectra.services import scene_store
    from spectra.services import settings_console as sc

    scene_store.save(SceneV2(name="Black Hole V2"))
    scene_store.save(SceneV2(name="Black Hole V2 UI"))

    with pytest.raises(sc.SettingChangeError) as exc:
        _run(sc.apply_force_scene(True, "Black Hole"))
    assert "candidates" in exc.value.detail or "close_matches" in exc.value.detail


def test_set_force_scene_refuses_with_no_close_match():
    from spectra.models.scene import SceneV2
    from spectra.services import scene_store
    from spectra.services import settings_console as sc

    scene_store.save(SceneV2(name="Orbits V2"))
    with pytest.raises(sc.SettingChangeError) as exc:
        _run(sc.apply_force_scene(True, "a completely unrelated name"))
    assert "known_names" in exc.value.detail


def test_set_force_scene_turning_off_needs_no_name():
    from spectra.services import room_controls as rc
    from spectra.services import settings_console as sc

    rc.save_room_controls(rc.RoomControlState(force_scene_enabled=True,
                                              force_scene_scene_id="whatever"))
    result = _run(sc.apply_force_scene(False))
    assert result["status"] == "applied"
    assert rc.load_room_controls().force_scene_enabled is False


def test_set_force_scene_turning_on_with_no_name_and_none_pinned_is_refused():
    from spectra.services import settings_console as sc

    with pytest.raises(sc.SettingChangeError, match="name a scene"):
        _run(sc.apply_force_scene(True))


def test_set_force_color_by_exact_and_fuzzy_name(monkeypatch):
    import json
    from spectra import config as scfg
    from spectra.services import engine
    from spectra.services import room_controls as rc
    from spectra.services import settings_console as sc
    from spectra.services.color_sets import ColorSetCard

    card = ColorSetCard(id="warm-set", name="Warm Hype V2")
    scfg.COLOR_SETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    scfg.COLOR_SETS_FILE.write_text(json.dumps({card.id: json.loads(card.model_dump_json())}))

    applied = []

    class _FakeConductor:
        async def apply_set_directly(self, c, *, forced_from=None):
            applied.append(c.id)
            return {"applied": c.id, "set_name": c.name, "virtuals": []}
    monkeypatch.setattr(engine, "conductor", _FakeConductor())

    result = _run(sc.apply_force_color(True, "Warm Hype"))
    assert result["status"] == "applied"
    assert result["target_id"] == "warm-set"
    assert applied == ["warm-set"]
    assert rc.load_room_controls().force_color_enabled is True


def test_set_force_color_refuses_turning_on_with_nothing_pinned_and_no_target():
    from spectra.services import settings_console as sc

    with pytest.raises(sc.SettingChangeError, match="name a colour set"):
        _run(sc.apply_force_color(True))


def test_get_force_pins_reads_both_pins_by_name():
    from spectra.models.scene import SceneV2
    from spectra.services import room_controls as rc
    from spectra.services import scene_store
    from spectra.services import settings_console as sc

    scene = SceneV2(name="Fireworks V2")
    scene_store.save(scene)
    rc.save_room_controls(rc.RoomControlState(force_scene_enabled=True,
                                              force_scene_scene_id=scene.id))
    result = sc.get_force_pins()
    assert result["force_scene"]["enabled"] is True
    assert result["force_scene"]["scene_name"] == "Fireworks V2"
    assert result["force_color"]["enabled"] is False


def test_force_scene_and_color_ops_wrap_errors_as_rejected_not_raise():
    from spectra.services import settings_console as sc

    assert _run(sc._op_set_force_scene(True))["status"] == "rejected"
    assert _run(sc._op_set_force_color(True))["status"] == "rejected"


def test_force_scene_and_color_are_declared_and_discoverable():
    from spectra.services import settings_agent as sa

    for name in ("get_force_pins", "set_force_scene", "set_force_color"):
        assert name in sa.ALL_OPERATIONS
        assert sa.ALL_OPERATIONS[name].domain == "settings"
    idx = _run(sa._dispatch("list_operations", {"domain": "settings"}))
    names = {o["name"] for o in idx["operations"]}
    assert {"get_force_pins", "set_force_scene", "set_force_color"} <= names


def test_name_resolve_tiers_directly():
    """The resolver itself, independent of any one domain's wiring —
    exact, dropped-suffix, near-tie, no-match."""
    from spectra.services import name_resolve as nr

    candidates = [("1", "Orbits V2"), ("2", "Fish")]
    match, rej = nr.resolve_name("Orbits V2", candidates, noun="scene")
    assert rej is None and match.id == "1"

    match, rej = nr.resolve_name("orbits", candidates, noun="scene")
    assert rej is None and match.id == "1"

    match, rej = nr.resolve_name("fish", candidates, noun="scene")
    assert rej is None and match.id == "2"

    tie_candidates = [("1", "Black Hole V2"), ("2", "Black Hole V2 UI")]
    match, rej = nr.resolve_name("Black Hole", tie_candidates, noun="scene")
    assert match is None and rej is not None

    match, rej = nr.resolve_name("nothing like this at all", candidates, noun="scene")
    assert match is None and rej is not None
    assert rej["known_names"] == ["Fish", "Orbits V2"]

    match, rej = nr.resolve_name("", candidates, noun="scene")
    assert match is None and rej is not None

    match, rej = nr.resolve_name("x", [], noun="scene")
    assert match is None and "no scenes exist" in rej["reason"]


# ═══ 6. live-model smoke test (skipped: no ANTHROPIC_API_KEY here) ═══════

@pytest.mark.skipif(not os.getenv("ANTHROPIC_API_KEY"),
                    reason="needs a real ANTHROPIC_API_KEY — live-model smoke test")
def test_live_model_can_apply_a_change():
    from spectra.services import room_controls as rc
    from spectra.services import settings_agent as sa

    result = _run(sa.run_turn(None, "Set the brightness to 50%."))
    assert result["changes"], "the model should have called set_setting"
    assert rc.load_room_controls().brightness_multiplier == pytest.approx(0.5, abs=0.05)
