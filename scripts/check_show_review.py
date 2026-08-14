"""Executable spec for Stage 3 of the owner's feedback sessions — the
review view (spectra/services/show_reconstruction.py +
spectra/api/show_review.py). Covers:

  - merge_timeline(): the pure reconstruction/ordering rule (position_ms
    primary, missing-position entries last by wall_ms).
  - list_sessions()/reconstruct(): session = one feedback batch, per-song
    windowing padded by SESSION_PAD_MS, uri-scoped (no cross-song leakage).
  - The two API endpoints (spectra/api/show_review.py): GET
    /api/review/sessions, GET /api/review/timeline.

Run from repo root: .venv/bin/python scripts/check_show_review.py
Isolated: temp files for every store; no LedFX I/O, no audio, no network.
"""
from __future__ import annotations

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


td = Path(tempfile.mkdtemp(prefix="spectra-show-review-spec-"))

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
scfg.COLOR_SETS_FILE = td / "color_sets.json"
scfg.PROFILES_DIR = td / "profiles"
scfg.AUDIO_SHAPES_DIR = td / "audio_shapes"
scfg.TRAINING_PROFILES_FILE = td / "training_profiles.json"

from spectra.services import feedback, fire_history, show_reconstruction

# ═══ 1. merge_timeline — pure ordering rule ═══════════════════════════════

merged = show_reconstruction.merge_timeline(
    events=[
        {"wall_ms": 1000, "position_ms": 30000, "bucket": "scenes", "key": "s1", "detail": {}},
        {"wall_ms": 4000, "position_ms": 10000, "bucket": "scenes", "key": "s2", "detail": {}},
    ],
    notes=[{"wall_ms": 2000, "position_ms": 20000, "id": "n1", "note": "here"}],
)
check([i["position_ms"] for i in merged] == [10000, 20000, 30000],
      "merge orders by position_ms, not wall_ms or input order")
check([i["type"] for i in merged] == ["event", "note", "event"], "types tag correctly through the sort")

merged = show_reconstruction.merge_timeline(
    events=[{"wall_ms": 9000, "position_ms": None, "bucket": "responses", "key": "flare", "detail": {}}],
    notes=[{"wall_ms": 3000, "position_ms": None, "id": "n1", "note": "bridge down"},
           {"wall_ms": 1, "position_ms": 5000, "id": "n2", "note": "positioned"}],
)
check(merged[0]["id"] == "n2", "positioned entries sort before any missing-position entry")
check([i.get("id") or i.get("key") for i in merged[1:]] == ["n1", "flare"],
      "missing-position entries land last, ordered among themselves by wall_ms")

check(show_reconstruction.merge_timeline([], []) == [], "empty inputs merge to an empty timeline")

# ═══ 2. list_sessions / reconstruct — store-backed ════════════════════════

check(show_reconstruction.list_sessions() == [], "no batches sent yet — no sessions")

batch1 = feedback.save_batch([
    feedback.FeedbackEntry(id="a", wall_ms=1000, uri="spotify:track:x", position_ms=1000, note="x1"),
])
batch2 = feedback.save_batch([
    feedback.FeedbackEntry(id="b", wall_ms=100_000, uri="spotify:track:y", position_ms=30000, note="y1"),
])

sessions = show_reconstruction.list_sessions()
check(len(sessions) == 2, "one session per sent batch")
check(sessions[0]["session_id"] == batch2.session_id, "sessions list newest-first")
check(sessions[0]["uris"] == ["spotify:track:y"], "session names the songs it has notes for")

fire_history.append_show_log("scenes", "pulse", {"scene_name": "Pulse"},
                             uri="spotify:track:y", position_ms=29000, now_ms=95_000)
fire_history.append_show_log("scenes", "far", {"scene_name": "Far"},
                             uri="spotify:track:y", position_ms=1000, now_ms=1_000)
fire_history.append_show_log("scenes", "other-song", {"scene_name": "Other"},
                             uri="spotify:track:z", position_ms=29000, now_ms=95_500)

result = show_reconstruction.reconstruct(batch2.session_id, "spotify:track:y")
check(result["window"] == {
    "start_wall_ms": 100_000 - show_reconstruction.SESSION_PAD_MS,
    "end_wall_ms": 100_000 + show_reconstruction.SESSION_PAD_MS,
}, "window is padded around this song's note wall-times")
event_keys = {i["key"] for i in result["timeline"] if i["type"] == "event"}
check(event_keys == {"pulse"}, "out-of-window and other-song events never leak in")

check(show_reconstruction.reconstruct("no-such-session", "spotify:track:x")["timeline"] == [],
      "unknown session reconstructs to an empty timeline, not an error")
check(show_reconstruction.reconstruct(batch1.session_id, "spotify:track:never-marked")["timeline"] == [],
      "a song with no notes in this session reconstructs to an empty timeline")

# ═══ 3. API surface ════════════════════════════════════════════════════════

from fastapi.testclient import TestClient

from spectra.app import create_app

client = TestClient(create_app())

r = client.get("/api/review/sessions")
check(r.status_code == 200 and len(r.json()) == 2, "GET /api/review/sessions responds with both sessions")

r = client.get("/api/review/timeline", params={"session_id": batch2.session_id, "uri": "spotify:track:y"})
check(r.status_code == 200, "GET /api/review/timeline responds")
body = r.json()
check(body["session_id"] == batch2.session_id and body["uri"] == "spotify:track:y", "timeline echoes its scope")
check([i["type"] for i in body["timeline"]] == ["event", "note"], "timeline is merged and ordered over HTTP")

r = client.get("/api/review/timeline", params={"session_id": batch2.session_id})
check(r.status_code == 422, "uri is a required query param")

print("\nALL CHECKS PASSED")
