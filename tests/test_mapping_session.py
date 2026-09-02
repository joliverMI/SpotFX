"""The mapping session's own properties — the exposure gate's wording, the
grey8 wire, and the structural absence of audio.

The end-to-end proofs (a real socket, a real run, a footprint against ground
truth) are the check scripts in tests/test_light_field_checks.py; this file
holds the small claims that are cheapest to state directly.
"""
from __future__ import annotations

import asyncio
import json
import sys
from base64 import b64encode
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spectra.services import mapping_session as ms

LOCKED = {"exposure_locked": True, "white_balance_locked": True,
          "exposure_mode": "manual", "white_balance_mode": "manual",
          "exposure_capabilities": ["manual", "continuous"],
          "white_balance_capabilities": ["manual", "continuous"]}


def _session():
    sent: list[dict] = []

    async def send(msg):
        sent.append(msg)

    return ms.MappingSession(send), sent


def _frame_msg(arr: np.ndarray, lock=None) -> dict:
    return {"type": "frame", "mime": ms.GREY_MIME,
            "width": arr.shape[1], "height": arr.shape[0],
            "captured_at_ms": 1000.0,
            "data": b64encode(arr.astype(np.uint8).tobytes()).decode("ascii"),
            **({"lock": lock} if lock else {})}


# ── 1. no audio, by construction ──────────────────────────────────────────

def test_the_mapping_session_has_no_audio_path_at_all():
    """His own requirement: "never arms audio — no-audio is true by
    construction, not a flag". A mode on the AV-sync session would have made
    this a branch; a separate type makes it an absence."""
    sess, _ = _session()
    for attr in ("audio_ref", "audio_probe", "_audio_ref_started", "estimate"):
        assert not hasattr(sess, attr), f"{attr} must not exist on this type"
    # and no audio machinery is even reachable from this module: the ONE
    # mention of AudioReference is the docstring explaining its absence.
    src = Path(ms.__file__).read_text()
    code = "\n".join(line for line in src.splitlines()
                     if not line.lstrip().startswith("#"))
    body = code.split('"""', 2)[-1]           # everything after the module docstring
    assert "AudioReference" not in body and "audio_probe" not in body
    assert "AudioWorklet" not in body and "getUserMedia" not in body


def test_it_reuses_the_existing_frame_ring_rather_than_a_second_one():
    from spectra.services import av_sync_session
    sess, _ = _session()
    assert isinstance(sess.frames, av_sync_session.FrameRing)


# ── 2. the exposure gate ──────────────────────────────────────────────────

def test_a_session_that_has_not_reported_a_lock_refuses_with_that_reason():
    sess, _ = _session()
    assert "has not reported its camera lock state" in sess.refusal()


def test_the_refusal_names_the_phone_and_the_missing_capability():
    sess, _ = _session()
    asyncio.run(sess.handle({"type": "hello", "user_agent": "Pixel/Firefox",
                             "lock": {**LOCKED, "exposure_locked": False,
                                      "exposure_mode": "continuous",
                                      "exposure_capabilities": ["continuous"]}}))
    reason = sess.refusal()
    assert "Pixel/Firefox" in reason
    assert "EXPOSURE" in reason and "continuous" in reason
    assert "WHITE BALANCE" not in reason, "only the capability that failed"
    assert "the whole map would lie" in reason, (
        "the refusal must say WHY, not just that it refused")


def test_a_locked_camera_does_not_refuse():
    sess, _ = _session()
    asyncio.run(sess.handle({"type": "hello", "user_agent": "Pixel/Chrome",
                             "lock": LOCKED}))
    assert sess.refusal() is None
    assert sess.lock.locked


def test_losing_the_lock_mid_run_arms_an_abort_by_name():
    sess, _ = _session()
    asyncio.run(sess.handle({"type": "hello", "lock": LOCKED}))
    assert sess.run_abort is None
    asyncio.run(sess.handle({"type": "lock", **LOCKED,
                             "white_balance_locked": False,
                             "white_balance_mode": "continuous"}))
    assert sess.run_abort and "lock was lost" in sess.run_abort
    assert "WHITE BALANCE" in sess.run_abort


def test_a_lock_report_riding_on_a_frame_is_honoured():
    """Every frame carries the live lock state, so a mid-run change is
    caught at the frame that carries it, not at the next capture."""
    sess, _ = _session()
    asyncio.run(sess.handle({"type": "hello", "lock": LOCKED}))
    sess.frames.configure(enabled=True)
    arr = np.zeros((ms.FRAME_H, ms.FRAME_W))
    sess._ingest_frame(_frame_msg(arr, lock={**LOCKED, "exposure_locked": False}))
    assert sess.run_abort and "lock was lost" in sess.run_abort


# ── 3. the grey8 wire ─────────────────────────────────────────────────────

def test_a_grey8_frame_becomes_the_stored_grid():
    from spectra.models.room_map import GRID_H, GRID_W
    sess, _ = _session()
    sess.frames.configure(enabled=True)
    arr = np.full((ms.FRAME_H, ms.FRAME_W), 42.0)
    arr[0:5, 0:5] = 200.0                       # exactly one grid cell
    sess._ingest_frame(_frame_msg(arr))
    assert len(sess.grids) == 1
    grid = sess.grids[0].grid
    assert grid.shape == (GRID_H, GRID_W)
    assert grid[0, 0] == pytest.approx(200.0)
    assert grid[0, 1] == pytest.approx(42.0)
    assert sess.grids[0].raw_max == 200


def test_a_frame_of_the_wrong_size_is_rejected_with_a_reason_not_resampled():
    """An UNDECLARED shape means the client and the server disagree, and
    quietly stretching it would hide that. "Declared" is the LADDER since
    the commissioning read moved to 1080p (`capture_settings.PROFILES`), so
    the reason names every size this wire speaks rather than one."""
    sess, _ = _session()
    sess.frames.configure(enabled=True)
    sess._ingest_frame(_frame_msg(np.zeros((100, 100))))
    assert not sess.grids and sess.counts["rejected"] == 1
    assert "not one of the sizes this wire declares" in (sess.last_error or "")
    assert "1920x1080" in (sess.last_error or "")


def test_a_jpeg_is_refused_because_a_lossy_codec_lands_in_the_difference():
    sess, _ = _session()
    sess.frames.configure(enabled=True)
    msg = _frame_msg(np.zeros((ms.FRAME_H, ms.FRAME_W)))
    msg["mime"] = "image/jpeg"
    sess._ingest_frame(msg)
    assert not sess.grids and "not 'image/grey8'" in (sess.last_error or "")


def test_the_grid_ring_is_bounded():
    sess, _ = _session()
    sess.frames.configure(enabled=True)
    arr = np.zeros((ms.FRAME_H, ms.FRAME_W))
    for _ in range(ms.GRID_RING + 20):
        sess._ingest_frame(_frame_msg(arr))
    assert len(sess.grids) == ms.GRID_RING
    assert len(sess.frames._frames) == ms.FRAME_RING_MAX


# ── 4. nothing is written to disk by this module ──────────────────────────

def test_the_session_persists_no_pixels(tmp_path, monkeypatch):
    """NOTHING FROM THE CAMERA IS WRITTEN — not a frame, not a grid, not an
    image. The one file this module now writes is the camera HOST's own row
    (which machine is holding the camera, its build, its declared placement,
    its lock state), so that a host being GONE is a read rather than the
    same silence as one that never existed; `spectra/services/
    capture_health.py` is the boundary statement, and the autouse
    `_isolated_capture_health` fixture is why it lands in tmp_path."""
    before = set(tmp_path.iterdir())
    sess, _ = _session()
    sess.frames.configure(enabled=True)
    asyncio.run(sess.handle({"type": "hello", "lock": LOCKED}))
    sess._ingest_frame(_frame_msg(np.zeros((ms.FRAME_H, ms.FRAME_W))))
    asyncio.run(sess.close())
    written = set(tmp_path.iterdir()) - before
    assert {p.name for p in written} == {"capture_health.json"}, written
    body = json.loads((tmp_path / "capture_health.json").read_text())
    row = body["clients"][0]
    assert set(row) <= {
        "host", "client", "version", "pose_name", "user_agent", "platform",
        "camera", "session_id", "pose_id", "locked", "camera_error", "lever",
        "first_seen_ms", "last_seen_ms", "last_event", "sessions",
        "lever_seen_ms"}, "no pixels, no grids, no image — only who and what"
    assert not sess.grids and not sess.frames._frames, (
        "every ring is dropped on close")
