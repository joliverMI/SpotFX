"""Executable spec for Stage 2 of the owner's feedback sessions — the
mark-then-nudge, batch-send feedback page (spectra-design-decisions.md
"Feedback-session design requirements"). Covers the server-side half:

  - capture_moment(): a fresh wall_ms/uri/position_ms triple read from the
    live bridge state, degrading to None/None (never raising) when the
    bridge is down — the MARK button's server half.
  - save_batch()/load_all_batches()/load_entries(): one Send press lands
    as one atomic, durable, uri/since-filterable record; bounded growth
    (oldest whole batch evicted first, the just-sent batch never evicted).
  - The three API endpoints (spectra/api/feedback.py): GET /api/feedback/
    mark, POST /api/feedback/batch (incl. validation), GET /api/feedback.

The client-side mark-then-nudge queue itself (localStorage persistence,
nudge arithmetic, reorder/delete, reload survival) has no Python surface
— proved by a phone-viewport chrome-devtools-axi eye-check against the dev
server instead (see the PR description).

Run from repo root: .venv/bin/python scripts/check_feedback.py
Isolated: temp files for every store; no LedFX I/O, no audio, no network.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pydantic import ValidationError


def check(cond, label):
    if not cond:
        raise SystemExit(f"FAIL: {label}")
    print(f"ok: {label}")


td = Path(tempfile.mkdtemp(prefix="spectra-feedback-spec-"))

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

from spectra.services import feedback

# ═══ 1. capture_moment ═══════════════════════════════════════════════════

moment = feedback.capture_moment()
check(set(moment) == {"wall_ms", "uri", "position_ms"}, "capture shape")
check(isinstance(moment["wall_ms"], int) and moment["wall_ms"] > 0,
      "capture stamps a wall_ms even with no bridge connection")
check(moment["uri"] is None and moment["position_ms"] is None,
      "no live track — degrades to neutral, never raises")

# ═══ 2. model validation ═════════════════════════════════════════════════


def expect_invalid(fn, label):
    try:
        fn()
        raise SystemExit(f"FAIL: {label} — accepted")
    except ValidationError:
        print(f"ok: {label} rejected")


expect_invalid(lambda: feedback.FeedbackEntry(id="", wall_ms=1), "empty id")
expect_invalid(lambda: feedback.FeedbackEntry(id="a", wall_ms=-1), "negative wall_ms")
expect_invalid(lambda: feedback.FeedbackEntry(id="a", wall_ms=1, position_ms=-1),
              "negative position_ms")
expect_invalid(lambda: feedback.FeedbackEntry(id="a", wall_ms=1, note="x" * 4001),
              "note over the length cap")

entry = feedback.FeedbackEntry(id="a", wall_ms=1000, uri="spotify:track:x",
                               position_ms=5000, note="loved this drop")
check(entry.note == "loved this drop", "a valid entry constructs cleanly")

# ═══ 3. store round trip + bounded growth ═══════════════════════════════

check(feedback.load_all_batches() == [], "no file yet — empty")

batch1 = feedback.save_batch([entry])
check(bool(batch1.session_id), "save_batch stamps a session_id")
check(feedback.load_all_batches()[0]["session_id"] == batch1.session_id,
      "batch persists under its own session_id")
check(not list(td.glob("**/*.tmp")), "atomic write leaves no temp file behind")

batch2 = feedback.save_batch([
    feedback.FeedbackEntry(id="b", wall_ms=2000, uri="spotify:track:y",
                           position_ms=1000, note=""),
])
all_entries = feedback.load_entries()
check({e["id"] for e in all_entries} == {"a", "b"},
      "load_entries flattens across every sent batch")
check(all(e["session_id"] in (batch1.session_id, batch2.session_id) for e in all_entries),
      "each flattened entry carries its batch's session_id")

check({e["id"] for e in feedback.load_entries(uri="spotify:track:x")} == {"a"},
      "uri filter narrows to one song")
check({e["id"] for e in feedback.load_entries(since_ms=1500)} == {"b"},
      "since filter narrows to a wall-time floor")

_orig_cap = feedback.FEEDBACK_MAX_ENTRIES
feedback.FEEDBACK_MAX_ENTRIES = 3
try:
    # storage already holds batch1={"a"} and batch2={"b"} (2 entries); adding
    # 2 more crosses the cap of 3, evicting only the oldest whole batch
    # (batch1/"a") — "b" survives since 3 entries no longer exceeds the cap
    feedback.save_batch([feedback.FeedbackEntry(id=f"c{i}", wall_ms=i, note="") for i in range(2)])
    ids = {e["id"] for e in feedback.load_entries()}
    check(ids == {"b", "c0", "c1"},
          "exceeding the cap evicts the oldest whole batch first")

    feedback.save_batch([feedback.FeedbackEntry(id=f"d{i}", wall_ms=i, note="") for i in range(5)])
    ids = {e["id"] for e in feedback.load_entries()}
    check(ids == {f"d{i}" for i in range(5)},
          "a single batch alone exceeding the cap is never evicted — "
          "it's the one just sent, nothing older is left to drop instead")
finally:
    feedback.FEEDBACK_MAX_ENTRIES = _orig_cap

# reset storage for the clean API-level pass below
scfg.FEEDBACK_FILE.unlink(missing_ok=True)

# ═══ 4. API surface ══════════════════════════════════════════════════════

from fastapi.testclient import TestClient

from spectra.app import create_app

client = TestClient(create_app())

r = client.get("/api/feedback/mark")
check(r.status_code == 200, "GET /api/feedback/mark responds")
body = r.json()
check(set(body) == {"wall_ms", "uri", "position_ms"}, "mark response shape")

r = client.get("/api/feedback")
check(r.status_code == 200 and r.json() == [], "GET /api/feedback starts empty")

payload = {"entries": [
    {"id": "m1", "wall_ms": 1000, "uri": "spotify:track:show", "position_ms": 12000,
     "note": "lights dropped a beat late"},
    {"id": "m2", "wall_ms": 5000, "uri": "spotify:track:show", "position_ms": 40000,
     "note": ""},
]}
r = client.post("/api/feedback/batch", json=payload)
check(r.status_code == 200, "POST /api/feedback/batch accepts a valid batch")
posted = r.json()
check(posted["count"] == 2 and bool(posted["session_id"]),
      "batch response reports the count and a session_id")

r = client.get("/api/feedback")
check(r.status_code == 200 and {e["id"] for e in r.json()} == {"m1", "m2"},
      "the sent batch is immediately readable")

r = client.get("/api/feedback", params={"uri": "spotify:track:show"})
check({e["id"] for e in r.json()} == {"m1", "m2"}, "GET /api/feedback?uri= filters")

r = client.get("/api/feedback", params={"since": 3000})
check({e["id"] for e in r.json()} == {"m2"}, "GET /api/feedback?since= filters")

bad = {"entries": [{"id": "", "wall_ms": 1000, "note": "bad id"}]}
r = client.post("/api/feedback/batch", json=bad)
check(r.status_code == 422, "an empty id in the batch is rejected — nothing partially lands")
check({e["id"] for e in client.get("/api/feedback").json()} == {"m1", "m2"},
      "a rejected batch never touches the durable store")

print("\nALL CHECKS PASSED")
