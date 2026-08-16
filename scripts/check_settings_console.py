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
  - The "cli" (subscription) backend switch (services/settings_agent_cli.py):
    defaults OFF, refuses without an explicit CLAUDE_CODE_OAUTH_TOKEN, never
    passes --bare, and locks the subprocess to --strict-mcp-config / --tools
    "" / --allowedTools naming exactly settings_agent.TOOL_NAMES. Live
    subprocess/transcript-parsing proof is tests/test_settings_agent_cli.py
    (offline, against real captured AND hand-built synthetic transcripts)
    — this script only proves the switch itself defaults safe, since
    that's the property every other check in this repo needs to be able
    to assume.
  - Sonic's WIDENED scene/flare surface (2026-08-15, services/
    scene_console.py, merged into settings_agent.ALL_OPERATIONS): the
    eight-key SCENE_SETTINGS_REGISTRY (bounds read live off SceneV2/
    PhaseBlend/PhaseChoreography/SceneColorJourney, same discipline as the
    room settings registry), create_scene's structural can't-collide
    guarantee, an out-of-range scene setting and a malformed flare kind
    both rejected with the server's own text, a room setting unreachable
    through set_scene_setting, and every write here proven to leave a
    stand-in for one of his real scenes byte-for-byte untouched. Full
    version of this proof (all four adversarial refusal categories, the
    fabrication hunt against run_turn() itself): tests/test_scene_console.py.
  - Sonic's overwrite/backup/undo/preview/restore authority (2026-08-15
    follow-up ask — "edit scenes and overwrite them, back them up ahead
    of time, an easy undo-last-agent-change button, a preview and
    check-in, restore the backup if it's not right"), his four structural
    requirements each proven, not just wired up: a backup taken BEFORE
    every existing-scene edit and RE-READ FROM DISK to confirm it
    actually landed (proven by making the write silently no-op and
    watching the edit refuse); undo_last_scene_change proven to actually
    restore, checked against scene_store directly, never the undo call's
    own claim; get_scene_preview proven to be a real diff of two stored
    snapshots; restoring the permanent "genesis" backup proven to
    reproduce a real scene's exact original bytes after a chain of bad
    edits. Full version (the 10-deep ring, undo-of-an-undo, all nine of
    his real scenes swept, the CLI backend's fabricated-restore-claim
    re-proof): tests/test_scene_console.py section 9 +
    tests/test_settings_agent_cli.py section 5c.

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
scfg.SCENE_AGENT_LOG_FILE = scfg.SPECTRA_STORAGE / "scene_agent_log.json"
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
    "ambient_mode", "ambient_color", "scene_change_mode",
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

check(set(sc.OPERATIONS) == {"get_settings", "set_setting"},
      "the settings domain itself is still exactly two operations")
check({"get_settings", "set_setting"} <= {t["name"] for t in sa.TOOLS},
      "the merged tool set still carries both settings operations")

for bad_tool in ("run_shell", "restart_service", "deploy", "drive_lights"):
    r = run(sa._dispatch(bad_tool, {}))
    check(r["status"] == "rejected", f"dispatch has no branch for {bad_tool!r}")
check(not scfg.ROOM_CONTROLS_FILE.exists() or
      rc.load_room_controls().brightness_multiplier == 1.0,
      "no fabricated tool call touched the store beyond the undo above")

r = run(sa._dispatch("set_setting", {"key": "force_scene_enabled", "value": True}))
check(r["status"] == "rejected", "set_setting still enforces the allowlist, not just validate_change directly")

# ═══ 3b. Sonic's WIDENED scene/flare surface (2026-08-15) — a re-proof
# against the NEW surface, not an inherited assumption; see
# tests/test_scene_console.py for the full version of this proof. ═══════

from spectra.models.scene import SceneV2 as _SceneV2  # noqa: E402
from spectra.services import scene_console as scc  # noqa: E402
from spectra.services import scene_store  # noqa: E402

check(set(scc.SCENE_SETTINGS_REGISTRY) == {
    "entry_ramp_ms", "phase_blend_charge_ramp_ms", "phase_blend_lull_ramp_ms",
    "choreography_enabled", "choreography_transition_ms", "choreography_anchor_frac",
    "color_journey_pace_factor", "accept_all_sets",
}, "scene settings registry is the deliberate eight-key scalar allowlist")
check(scc._model_field_bounds(_SceneV2, "entry_ramp_ms") ==
      (scc.SCENE_SETTINGS_REGISTRY["entry_ramp_ms"].min, scc.SCENE_SETTINGS_REGISTRY["entry_ramp_ms"].max),
      "scene registry bounds are read live off SceneV2, not re-typed")

his_scene = _SceneV2(name="STAR", entry_ramp_ms=1234)  # stands in for one of his 9 real scenes
scene_store.save(his_scene)
his_scene_bytes_before = scfg.SCENES_FILE.read_bytes()

throwaway = run(scc.apply_create_scene("Throwaway check scene"))
check(throwaway["scene_id"] != his_scene.id, "create_scene never collides with an existing scene id")

try:
    run(scc.apply_scene_setting(throwaway["scene_id"], "entry_ramp_ms", 999999))
    raise SystemExit("FAIL: an out-of-range scene setting was accepted")
except scc.SceneOpError as e:
    check("20000" in " ".join(e.detail.get("pydantic_errors", [])),
          "out-of-range scene setting rejected with the server's own legal-range text")

try:
    scc._validate_scene_setting(throwaway["scene_id"], "brightness_multiplier", 0.2)
    raise SystemExit("FAIL: a room setting was reachable through a scene operation")
except scc.SceneOpError:
    print("ok: a room-level setting is unreachable through set_scene_setting")

for bad_op in ("delete_scene", "run_shell", "restart_service", "read_file"):
    r = run(sa._dispatch(bad_op, {"scene_id": throwaway["scene_id"]}))
    check(r["status"] == "rejected", f"dispatch has no branch for {bad_op!r} either")

check(scfg.SCENES_FILE.read_bytes() != his_scene_bytes_before,
      "the store DID change (the throwaway scene landed) ...")
import json as _json  # noqa: E402
_raw = _json.loads(scfg.SCENES_FILE.read_text())
check(_json.dumps(_raw[his_scene.id], sort_keys=True) ==
      _json.dumps(_json.loads(his_scene_bytes_before.decode())[his_scene.id], sort_keys=True),
      "...but his 'STAR' scene's own stored bytes are byte-identical to before any of this")

flare_result = run(scc.apply_flare_kind(throwaway["scene_id"], name="Boom", type="momentary",
                                        params={"gain": 1.0}, gain=1.5))
check(flare_result["status"] == "applied" and flare_result["op"] == "flare_kind_created",
      "a valid named flare kind is created")
try:
    scc._validate_set_flare_kind(throwaway["scene_id"], name="BadJump", type="drift_jump",
                                 jump="dice", params={"x": 1.0}, gain=1.0, hold_ms=None)
    raise SystemExit("FAIL: a malformed flare kind (params on a drift_jump) was accepted")
except scc.SceneOpError as e:
    check("jumps the drift" in str(e), "malformed flare kind rejected with the server's own shape rule")

# ═══ 3c. Sonic's overwrite/backup/undo/preview/restore authority
# (2026-08-15 follow-up widening) — his four structural requirements,
# each proven, not just wired up. Full version: tests/test_scene_console.py
# section 9. ═══════════════════════════════════════════════════════════

original_star = scene_store.get_by_id(his_scene.id).model_dump(mode="json")

r1 = run(scc.apply_scene_setting(his_scene.id, "entry_ramp_ms", 500))
check("backup_id" in r1 and "preview" in r1, "an edit to an existing scene carries a backup id and a real preview")
check(scc._load_genesis()[his_scene.id]["scene"]["entry_ramp_ms"] == original_star["entry_ramp_ms"],
      "genesis captured the ORIGINAL value on the scene's first-ever edit")

# BACKUP VERIFIED, NOT MERELY ATTEMPTED — silently no-op the backup write
# and confirm the edit is REFUSED (a read-back mismatch, not an exception).
_real_scene_write = scc._atomic_write_json


def _swallow_backup_write(path, data):
    if path == scfg.SCENE_BACKUPS_FILE:
        return
    return _real_scene_write(path, data)


scc._atomic_write_json = _swallow_backup_write
try:
    run(scc.apply_scene_setting(his_scene.id, "entry_ramp_ms", 999))
    raise SystemExit("FAIL: an edit proceeded despite an unverifiable backup")
except scc.SceneOpError as e:
    check("backup could not be verified" in str(e),
          "a backup that silently doesn't land refuses the edit, proven by making it fail")
finally:
    scc._atomic_write_json = _real_scene_write
check(scene_store.get_by_id(his_scene.id).entry_ramp_ms == 500,
      "the scene itself is untouched by the refused edit")

# OVERWRITE — his first genuinely destructive scene operation.
run(scc.apply_overwrite_scene(his_scene.id, name="STAR (clobbered)",
                              flare_kinds=[{"name": "Oops", "type": "permanent", "params": {"gain": 1.0}}]))
check(scene_store.get_by_id(his_scene.id).name == "STAR (clobbered)", "overwrite really lands")

# UNDO — proven to actually restore, verified against stored data, not the call's own claim.
run(scc.apply_undo_last_scene_change())
check(scene_store.get_by_id(his_scene.id).name == "STAR" and
      scene_store.get_by_id(his_scene.id).entry_ramp_ms == 500,
      "undo_last_scene_change genuinely restores the pre-overwrite scene, read back from storage")

# RESTORE GENESIS — the permanent anchor survives the whole chain of edits above.
run(scc.apply_restore_scene_backup(his_scene.id, "genesis"))
check(scene_store.get_by_id(his_scene.id).model_dump(mode="json") == original_star,
      "restoring 'genesis' reproduces his real scene's exact original state, byte for byte")

# PREVIEW READS STORED DATA, NEVER A NARRATION.
value_before_this_edit = scene_store.get_by_id(his_scene.id).entry_ramp_ms
run(scc.apply_scene_setting(his_scene.id, "entry_ramp_ms", 42))
preview = scc.get_scene_preview(his_scene.id)
check(preview["preview"] == {"entry_ramp_ms": {"before": value_before_this_edit, "after": 42}},
      "get_scene_preview is a real diff of stored before/after state")

check("overwrite_scene" in sa.ALL_OPERATIONS and "undo_last_scene_change" in sa.ALL_OPERATIONS
      and "restore_scene_backup" in sa.ALL_OPERATIONS and "get_scene_preview" in sa.ALL_OPERATIONS
      and "list_scene_backups" in sa.ALL_OPERATIONS,
      "all five new operations are discoverable in the merged allowlist")

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

from spectra import config as scfg  # noqa: E402  (re-import for clarity at this point)

scfg.whisper_bridge_url = lambda: None  # the "genuinely unconfigured" case
r = client.post("/api/settings-console/transcribe",
                files={"audio": ("clip.webm", b"\x00\x01", "audio/webm")})
check(r.status_code == 503 and "type your request" in r.json()["detail"],
      "no bridge configured -> honest 503, mic button never pretends")

# ═══ 5. the wire contract: a silently-ignored vocabulary is a hard fail ═
# (coordinated with the ship building the local-Whisper bridge against
# this endpoint — see transcription.py's wire-contract docstring). These
# replace transcribe() wholesale, so still no real network.

from spectra.services import transcription as tr

_real_transcribe = tr.transcribe  # saved so it can be restored without a
                                  # module reload (which would mint a NEW
                                  # TranscriptionUnavailable/VocabularyNot
                                  # Honored class, no longer `is`-identical
                                  # to the ones settings_console.py already
                                  # imported — its except clauses would
                                  # stop catching them)


async def forgetful(audio, mime_type, vocabulary=""):
    return tr.TranscriptionResult(text="whatever it heard")  # vocabulary_honored left None


tr.transcribe = forgetful
tr.vocabulary_hint = lambda: "Sunset Drift Warm White"
r = client.post("/api/settings-console/transcribe",
                files={"audio": ("clip.webm", b"\x00\x01", "audio/webm;codecs=opus")})
check(r.status_code == 502 and "vocabulary" in r.json()["detail"],
      "a transcriber that doesn't confirm using the vocabulary hint is a hard 502, not a quiet 200")


async def honest(audio, mime_type, vocabulary=""):
    return tr.TranscriptionResult(text="turn on sunset drift", vocabulary_honored=True)


tr.transcribe = honest
r = client.post("/api/settings-console/transcribe",
                files={"audio": ("clip.webm", b"\x00\x01", "audio/webm;codecs=opus")})
check(r.status_code == 200 and r.json()["vocabulary_honored"] is True,
      "a transcriber that confirms using the vocabulary hint is accepted")

# ═══ 6. the REAL transcribe()'s bridge-facing contract (2026-08-15) ═════
# httpx.MockTransport only — the real bridge is confirmed down tonight
# (its ship tore its test container down); these prove transcribe()'s
# SHAPE against the published contract without a real socket, never by
# probing/scanning the actual host.

import httpx

tr.transcribe = _real_transcribe  # restore — the checks above replaced it wholesale
scfg.whisper_bridge_url = lambda: "http://bridge.example"

try:
    run(tr.transcribe(iter([b"chunk"]), "audio/webm"))
    raise SystemExit("FAIL: a streamed/iterator audio argument was accepted")
except tr.TranscriptionUnavailable:
    print("ok: a non-bytes audio argument is refused before any request is attempted")

oversized = b"0" * (tr.BRIDGE_MAX_AUDIO_BYTES + 1)
try:
    run(tr.transcribe(oversized, "audio/webm"))
    raise SystemExit("FAIL: an over-cap clip was accepted")
except tr.TranscriptionUnavailable:
    print("ok: a clip over the bridge's 25MB cap is refused with a clear reason, not a bridge 4xx")

captured = {}


def fixed_length_handler(request):
    captured["content_length"] = request.headers.get("content-length")
    captured["transfer_encoding"] = request.headers.get("transfer-encoding")
    captured["x_vocabulary"] = request.headers.get("x-vocabulary")
    return httpx.Response(200, json={"text": "turn on sunset drift", "vocabulary_applied": True})


tr._client = lambda: httpx.AsyncClient(transport=httpx.MockTransport(fixed_length_handler), timeout=5.0)
result = run(tr.transcribe(b"abc123", "audio/webm;codecs=opus", vocabulary="Sunset Drift"))
check(captured["content_length"] == "6" and captured["transfer_encoding"] is None,
      "the real bridge call sends a fixed Content-Length body, never chunked")
check(captured["x_vocabulary"] == "Sunset%20Drift", "vocabulary travels percent-encoded in X-Vocabulary")
check(result.vocabulary_honored is True, "vocabulary_applied: true from the bridge translates through")


def refused_handler(request):
    raise httpx.ConnectError("Connection refused", request=request)


tr._client = lambda: httpx.AsyncClient(transport=httpx.MockTransport(refused_handler), timeout=5.0)
try:
    run(tr.transcribe(b"abc", "audio/webm"))
    raise SystemExit("FAIL: connection-refused was swallowed instead of surfacing")
except tr.TranscriptionUnavailable:
    print("ok: connection-refused (the real bridge's current state) is the honest 503 path, not chased")

# ═══ 7. the "cli" (subscription) backend switch defaults safe ═══════════
# Full argv/env/transcript-parsing proof lives in
# tests/test_settings_agent_cli.py (offline, against real captured
# transcripts) and is not duplicated here — this is the one property every
# other check in this repo needs to be able to assume without re-deriving it.

os.environ.pop("SPECTRA_SETTINGS_AGENT_BACKEND", None)
os.environ.pop("CLAUDE_CODE_OAUTH_TOKEN", None)

from spectra.services import settings_agent_cli as sac  # noqa: E402

check(scfg.settings_agent_backend() == "api",
      "settings-agent backend defaults to \"api\" — a subscription CLI backend never enables itself")
check(scfg.settings_agent_cli_oauth_token() == "",
      "no CLAUDE_CODE_OAUTH_TOKEN configured by default")

try:
    run(sac.run_turn(None, "set brightness to half"))
    raise SystemExit("FAIL: the cli backend ran without a token")
except sa.SettingsAgentUnavailable as e:
    check("CLAUDE_CODE_OAUTH_TOKEN" in str(e),
          "cli backend refuses before any subprocess without an explicit token")

check("--bare" not in sac._argv("hi", None), "the cli backend never passes --bare (can't read the OAuth token)")
check(sac._argv("hi", None)[sac._argv("hi", None).index("--tools") + 1] == "",
      "the cli backend strips every built-in tool")
mcp_cfg = json.loads(sac._mcp_config_json())
check(set(mcp_cfg["mcpServers"]) == {sac.MCP_SERVER_NAME},
      "the cli backend's --mcp-config names exactly one server")

print("\nALL CHECKS PASSED")
