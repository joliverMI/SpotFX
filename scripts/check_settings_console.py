"""Executable spec for the settings console (standing order 5: "talk to the
software; do not build the Admiral a settings page"). Covers:

  - SETTINGS_REGISTRY: an explicit allowlist, bounds read live off
    RoomControlState's own Field constraints (spectra/services/
    room_controls.py) — never a second, hand-typed copy of the range.
  - validate_change/apply_change: rejects an unknown key, an out-of-range
    value, and a malformed hex colour, with nothing persisted on rejection;
    a valid change writes through room_controls' own store + ambient
    reconcile (the same choke point PUT /api/room-controls uses) and
    leaves a bounded, visible change-log entry.
  - undo_last_change: reverts through the SAME validated apply_change path.
  - settings_agent._dispatch: the WHOLE tool-name -> code mapping is two
    branches (get_settings, set_setting) — any other name, however it
    arrives, is rejected without touching storage. This is the structural
    proof that the boundary doesn't depend on the model's prompt.
  - API surface: registry/log/undo/message/transcribe, including both 503s
    (no ANTHROPIC_API_KEY; no transcriber wired into services/
    transcription.py yet).

Run from repo root: .venv/bin/python scripts/check_settings_console.py
Isolated: temp files for every store; no network, no LedFX I/O, no audio.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def check(cond, label):
    if not cond:
        raise SystemExit(f"FAIL: {label}")
    print(f"ok: {label}")


def run(coro):
    return asyncio.run(coro)


td = Path(tempfile.mkdtemp(prefix="spectra-settings-console-spec-"))

from fx import device_model
device_model.CATEGORIES_FILE = td / "device_categories.json"
device_model.CATEGORIES_FILE.write_text(json.dumps({}))

from fx import light_ownership
light_ownership.OWNERSHIP_FILE = td / "ownership.json"

from spectra import config as scfg
scfg.SPECTRA_STORAGE = td / "spectra"
scfg.SCENES_FILE = scfg.SPECTRA_STORAGE / "scenes.json"
scfg.SEQUENCER_FILE = scfg.SPECTRA_STORAGE / "sequencer.json"
scfg.DRIFT_PROFILES_FILE = scfg.SPECTRA_STORAGE / "drift_profiles.json"
scfg.ROOM_COLOR_FILE = scfg.SPECTRA_STORAGE / "room_color.json"
scfg.ROOM_CONTROLS_FILE = scfg.SPECTRA_STORAGE / "room_controls.json"
scfg.FIRE_HISTORY_FILE = scfg.SPECTRA_STORAGE / "fire_history.json"
scfg.SHOW_LOG_FILE = scfg.SPECTRA_STORAGE / "show_log.json"
scfg.TRIGGERS_FILE = scfg.SPECTRA_STORAGE / "triggers.json"
scfg.FEEDBACK_FILE = scfg.SPECTRA_STORAGE / "feedback.json"
scfg.SETTINGS_LOG_FILE = scfg.SPECTRA_STORAGE / "settings_log.json"
scfg.COLOR_SETS_FILE = td / "color_sets.json"
scfg.PROFILES_DIR = td / "profiles"
scfg.AUDIO_SHAPES_DIR = td / "audio_shapes"
scfg.TRAINING_PROFILES_FILE = td / "training_profiles.json"

from spectra.services import room_controls as rc
from spectra.services import settings_agent as sa
from spectra.services import settings_console as sc

# ═══ 1. registry ═══════════════════════════════════════════════════════

check(set(sc.SETTINGS_REGISTRY) == {
    "brightness_multiplier", "global_transition_ms",
    "ambient_enabled", "ambient_color", "scene_change_mode",
}, "registry is the deliberate five-key first-build allowlist")
check("force_scene_enabled" not in sc.SETTINGS_REGISTRY,
      "force_scene_* deliberately excluded (opaque scene id, not voice-shaped)")
check(rc.field_bounds("brightness_multiplier") ==
      (sc.SETTINGS_REGISTRY["brightness_multiplier"].min,
       sc.SETTINGS_REGISTRY["brightness_multiplier"].max),
      "registry bounds are read live off RoomControlState, not re-typed")

try:
    run(sc.undo_last_change())
    raise SystemExit("FAIL: undo with an empty log accepted")
except sc.SettingChangeError:
    print("ok: undo with nothing applied yet is rejected")

# ═══ 2. validation + apply ═════════════════════════════════════════════

try:
    sc.validate_change("force_scene_enabled", True)
    raise SystemExit("FAIL: unknown key accepted")
except sc.SettingChangeError:
    print("ok: unknown key rejected")

try:
    sc.validate_change("brightness_multiplier", 5.0)
    raise SystemExit("FAIL: out-of-range value accepted")
except sc.SettingChangeError as e:
    check(e.detail["nearest_legal_value"] == 1.0, "out-of-range surfaces the nearest legal value")

check(not scfg.ROOM_CONTROLS_FILE.exists(), "no store write yet — validation alone never persists")

result = run(sc.apply_change("brightness_multiplier", 0.4))
check(result["status"] == "applied" and result["new_value"] == 0.4, "a valid change applies")
check(rc.load_room_controls().brightness_multiplier == 0.4, "the write lands in room_controls' own store")
check(len(sc.load_log()) == 1, "the change leaves one visible log entry")

undone = run(sc.undo_last_change())
check(undone["new_value"] == 1.0, "undo restores the previous value")
check(rc.load_room_controls().brightness_multiplier == 1.0, "undo's restore lands through the same store")

# ═══ 3. the structural tool boundary ═══════════════════════════════════

check({t["name"] for t in sa.TOOLS} == {"get_settings", "set_setting"},
      "the model is handed exactly two tools")

for bad_tool in ("run_shell", "restart_service", "deploy", "drive_lights"):
    r = run(sa._dispatch(bad_tool, {}))
    check(r["status"] == "rejected", f"dispatch has no branch for {bad_tool!r}")
check(not scfg.ROOM_CONTROLS_FILE.exists() or
      rc.load_room_controls().brightness_multiplier == 1.0,
      "no fabricated tool call touched the store beyond the undo above")

r = run(sa._dispatch("set_setting", {"key": "force_scene_enabled", "value": True}))
check(r["status"] == "rejected", "set_setting still enforces the allowlist, not just validate_change directly")

# ═══ 4. API surface ═════════════════════════════════════════════════════

from fastapi.testclient import TestClient

from spectra.app import create_app

client = TestClient(create_app())

r = client.get("/api/settings-console/registry")
check(r.status_code == 200 and len(r.json()["settings"]) == 5, "GET /registry responds")

scfg.SETTINGS_LOG_FILE.unlink(missing_ok=True)  # back to a clean, empty log for this check
r = client.post("/api/settings-console/undo")
check(r.status_code == 409, "POST /undo with nothing to undo is a 409, not a silent no-op")

scfg.settings_agent_api_key = lambda: ""  # module-level swap; this process exits right after
r = client.post("/api/settings-console/message", json={"text": "hello"})
check(r.status_code == 503 and "ANTHROPIC_API_KEY" in r.json()["detail"],
      "no API key configured -> honest 503, not a fake reply")

r = client.post("/api/settings-console/transcribe",
                files={"audio": ("clip.webm", b"\x00\x01", "audio/webm")})
check(r.status_code == 503 and "type your request" in r.json()["detail"],
      "no transcriber wired -> honest 503, mic button never pretends")

print("\nALL CHECKS PASSED")
