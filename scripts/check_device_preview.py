"""Executable spec for the device-preview strip
(data/spectra-device-preview-plan/report.md + the pause requirement
appended to it):

  - favourites store round-trips; empty store falls back to the
    genuinely-driven default (room_topology's own ground truth), sorted,
    capped at DEFAULT_FAVORITES_CAP.
  - DevicePreviewRelay's _active_event only wants an upstream connection
    when unpaused AND favourites exist AND at least one downstream viewer
    is connected (OQ-7's demand-driven hidden-tab auto-pause — a SEPARATE
    mechanism from the sticky pause flag, never touching it).
  - frame throttling is per-vis_id and independent across vis_ids.
  - the API surface (favorites GET/PUT, status, pause/resume).

The live-socket proofs that pause (and, separately, zero viewers)
actually close the upstream connection — not just the display — are
slower tests in tests/test_device_preview.py, each spinning up a real
fake-LedFX WebSocket server on an ephemeral loopback port:
test_pause_actually_closes_the_upstream_socket_not_just_the_display and
test_last_viewer_leaving_closes_the_upstream_socket_and_a_viewer_
returning_reopens_it. Run them directly for that proof:
  .venv/bin/python -m pytest tests/test_device_preview.py -q

Run from repo root: .venv/bin/python scripts/check_device_preview.py
Isolated: temp files for every store; no LedFX I/O, no audio, no network.
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


def _run(coro):
    return asyncio.run(coro)


td = Path(tempfile.mkdtemp(prefix="spectra-device-preview-spec-"))

from fx import device_model
device_model.CATEGORIES_FILE = td / "device_categories.json"
device_model.CATEGORIES_FILE.write_text(json.dumps({
    "strips": {"name": "strips", "virtuals": ["zebra", "alpha", "mid", "delta"], "effects": []},
}))
device_model.refresh()

from fx import light_ownership
light_ownership.OWNERSHIP_FILE = td / "ownership.json"

from spectra import config as scfg
scfg.SPECTRA_STORAGE = td / "spectra"
scfg.SCENES_FILE = scfg.SPECTRA_STORAGE / "scenes.json"
scfg.ROOM_CONTROLS_FILE = scfg.SPECTRA_STORAGE / "room_controls.json"
scfg.DEVICE_PREVIEW_FILE = scfg.SPECTRA_STORAGE / "device_preview.json"
scfg.COLOR_SETS_FILE = td / "color_sets.json"
scfg.PROFILES_DIR = td / "profiles"
scfg.AUDIO_SHAPES_DIR = td / "audio_shapes"
scfg.TRAINING_PROFILES_FILE = td / "training_profiles.json"

from spectra.services import device_preview as dp

# ═══ 1. store round trip + default population ════════════════════════════

check(dp.load_state() == dp.DevicePreviewState(), "no file yet — defaults")

check(dp.default_favorite_ids() == ["alpha", "delta", "mid", "zebra"],
      "default population sorts the genuinely-driven ground truth")
check(dp.effective_favorite_ids() == ["alpha", "delta", "mid", "zebra"],
      "empty store falls back to the default")

dp.save_state(dp.DevicePreviewState(favorite_virtual_ids=["zebra"], paused=True))
check(dp.load_state().favorite_virtual_ids == ["zebra"], "store persists his explicit choice")
check(dp.effective_favorite_ids() == ["zebra"], "his explicit choice overrides the default")
check(not list(td.glob("**/*.tmp")), "atomic write leaves no temp file behind")

# reset for the clean sections below
scfg.DEVICE_PREVIEW_FILE.unlink(missing_ok=True)

# ═══ 2. relay wanting-upstream logic ═══════════════════════════════════

relay = dp.DevicePreviewRelay()
check(not relay._active_event.is_set(), "no favourites — nothing to subscribe to")
relay.set_favorites(["a"])
check(relay._active_event.is_set(), "favourites present, unpaused — wants upstream")
relay.pause()
check(not relay._active_event.is_set(), "paused — must not want upstream regardless of favourites")
relay.resume()
check(relay._active_event.is_set(), "resumed — wants upstream again")

# ═══ 2b. OQ-7 — demand-driven hidden-tab auto-pause ═══════════════════════

has_viewer = {"v": False}
viewer_relay = dp.DevicePreviewRelay(has_viewers=lambda: has_viewer["v"])
viewer_relay.set_favorites(["a"])
check(not viewer_relay._active_event.is_set(), "unpaused + favourites but zero viewers — no upstream")
has_viewer["v"] = True
viewer_relay.viewers_changed()
check(viewer_relay._active_event.is_set(), "a viewer connected — wants upstream")
has_viewer["v"] = False
viewer_relay.viewers_changed()
check(not viewer_relay._active_event.is_set(), "last viewer left — auto-paused")
check(viewer_relay.paused is False, "auto-pause via zero viewers never touches the sticky pause flag")

# ═══ 3. per-vis_id frame throttling ═════════════════════════════════════

clock = {"t": 0.0}
received = []


async def on_frame(payload):
    received.append(payload)


throttled_relay = dp.DevicePreviewRelay(target_fps=10.0, on_frame=on_frame,
                                        clock=lambda: clock["t"])
_run(throttled_relay._handle_frame(
    {"event_type": "visualisation_update", "vis_id": "a", "pixels": "x", "shape": [1, 1]}))
clock["t"] += 0.05
_run(throttled_relay._handle_frame(
    {"event_type": "visualisation_update", "vis_id": "a", "pixels": "y", "shape": [1, 1]}))
_run(throttled_relay._handle_frame(
    {"event_type": "visualisation_update", "vis_id": "b", "pixels": "z", "shape": [1, 1]}))
clock["t"] += 0.1
_run(throttled_relay._handle_frame(
    {"event_type": "visualisation_update", "vis_id": "a", "pixels": "w", "shape": [1, 1]}))
check([r["vis_id"] for r in received] == ["a", "b", "a"],
      "throttle is per-vis_id — a busy vis_id never starves another's first frame")
check(throttled_relay.frames_received == 4 and throttled_relay.frames_relayed == 3,
      "every arriving frame counts; only throttled ones are dropped from relaying")

# ═══ 4. API surface ══════════════════════════════════════════════════════

from fastapi.testclient import TestClient

from spectra.app import create_app

client = TestClient(create_app())

r = client.get("/api/device-preview/favorites")
check(r.status_code == 200, "GET /api/device-preview/favorites responds")
body = r.json()
check(body["favorite_virtual_ids"] == [] and body["is_default"] is True,
      "empty store — GET reports the default, honestly flagged")

r = client.put("/api/device-preview/favorites",
               json={"favorite_virtual_ids": ["mid", "mid", "alpha"]})
check(r.status_code == 200, "PUT /api/device-preview/favorites accepts a list")
body = r.json()
check(body["favorite_virtual_ids"] == ["mid", "alpha"], "de-duped, order preserved")
check(dp.relay._favorite_ids == ["mid", "alpha"], "the live relay adopts the change immediately")

r = client.get("/api/device-preview/status")
check(r.status_code == 200 and r.json()["paused"] is False, "GET status reports live paused state")

r = client.post("/api/device-preview/pause")
check(r.status_code == 200 and r.json()["paused"] is True, "POST pause flips paused")
check(dp.load_state().paused is True, "pause persists to disk — survives a restart")

r = client.post("/api/device-preview/resume")
check(r.status_code == 200 and r.json()["paused"] is False, "POST resume flips it back")

# leave the singleton clean for anything run after this in the same process
dp.relay.set_favorites([])
dp.relay.paused = False
dp.relay._sync()

print("\nALL CHECKS PASSED")
