"""
Smoke test for the Timing-page lock history (services/lock_history.py,
routers/lock_history_router.py) and the per-device offset layer.

  1. Grades      — quality notches, no-hard-lock penalty, slow-lock penalty.
  2. Record      — entries persist with delta_ms computed from prev offset.
  3. Recent      — recent_songs() dedupes to the latest entry per uri.
  4. Search      — case-insensitive substring over title/artist/uri/device.
  5. API         — /api/lock-history endpoints serve the same data.
  6. Device layer— trigger_engine adds the active device's offset; systemic
                   learner isolates samples per device.

Run:  PYTHONPATH=. .venv/bin/python scripts/smoke_lock_history.py
Exit code 0 = all assertions passed.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from config import settings
from services import lock_history as lh

# Never touch the live storage/lock_history.json.
lh._STORE_PATH = Path(tempfile.mkstemp(suffix="_lock_history_smoke.json")[1])
lh._entries = []

PASS, FAIL = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m"
_failures = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _failures
    print(f"  [{PASS if cond else FAIL}] {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        _failures += 1


def main() -> int:
    print("1. Grade computation")
    check("Q .95 hard fast lock → A", lh.compute_grade(0.95, True, 5000) == "A")
    check("Q .85 hard fast lock → B", lh.compute_grade(0.85, True, 5000) == "B")
    check("Q .95 hard SLOW lock → B", lh.compute_grade(0.95, True, 45000) == "B")
    check("Q .95 no hard lock → B", lh.compute_grade(0.95, False, None) == "B")
    check("Q .65 no hard lock → F", lh.compute_grade(0.65, False, None) == "F")
    check("Q .40 anything → F", lh.compute_grade(0.40, True, 1000) == "F")

    print("2. Record + delta")
    lh.record(uri="spotify:track:aaa", title="Alpha", artist="Artist One",
              device="default", play_type="first", locked=True,
              time_to_lock_ms=8400, offset_ms=1500, prev_offset_ms=1300,
              quality=0.91, n_windows=4)
    lh.record(uri="spotify:track:bbb", title="Beta", artist="Artist Two",
              device="living-room", play_type="first", locked=False,
              time_to_lock_ms=None, offset_ms=-200, prev_offset_ms=None,
              quality=0.72, n_windows=2)
    lh.record(uri="spotify:track:aaa", title="Alpha", artist="Artist One",
              device="default", play_type="repeat", locked=True,
              time_to_lock_ms=42000, offset_ms=1550, prev_offset_ms=1500,
              quality=0.88, n_windows=6)
    entries = lh.search("", limit=10)
    check("3 entries stored", len(entries) == 3, f"n={len(entries)}")
    check("newest first", entries[0]["play_type"] == "repeat")
    check("delta computed", entries[0]["delta_ms"] == 50, f"delta={entries[0]['delta_ms']}")
    check("null prev → null delta", entries[1]["delta_ms"] is None)
    check("slow hard lock graded C (B base − 1)", entries[0]["grade"] == "C",
          f"grade={entries[0]['grade']}")
    # Persisted round-trip: drop the cache and reload from disk.
    lh._entries = None
    check("persists to disk", len(lh.search("", limit=10)) == 3)

    print("3. Recent dedupes per song")
    recent = lh.recent_songs(limit=10)
    check("2 distinct songs", len(recent) == 2, f"n={len(recent)}")
    check("latest play of aaa wins", recent[0]["uri"] == "spotify:track:aaa"
          and recent[0]["play_type"] == "repeat")

    print("4. Search")
    check("by title", len(lh.search("alpha")) == 2)
    check("by artist", len(lh.search("artist two")) == 1)
    check("by device", len(lh.search("living-room")) == 1)
    check("by uri fragment", len(lh.search("track:bbb")) == 1)
    check("no match", len(lh.search("zzz-nothing")) == 0)
    check("entries_for_uri", len(lh.entries_for_uri("spotify:track:aaa")) == 2)

    print("5. API endpoints (in-process TestClient)")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers import lock_history_router
    app = FastAPI()
    app.include_router(lock_history_router.router)
    client = TestClient(app)
    r = client.get("/api/lock-history/recent?limit=10").json()
    check("recent endpoint", len(r["entries"]) == 2 and "active_device" in r)
    r = client.get("/api/lock-history/search?q=beta").json()
    check("search endpoint", len(r["entries"]) == 1)
    # Beta is Q .72 (C base) with no hard lock → one notch down → D.
    check("no-hard-lock grade is D", r["entries"][0]["grade"] == "D",
          f"grade={r['entries'][0]['grade']}")
    r = client.get("/api/lock-history/song?uri=spotify:track:aaa").json()
    check("song endpoint", len(r["entries"]) == 2)

    print("6. Per-device offset layer")
    from services.trigger_engine import _device_offset, _layer_systemic
    settings.systemic_offset_enabled = False
    settings.timing_device_offsets = {"living-room": 350, "patio": -120}
    settings.active_timing_device = "living-room"
    check("device offset resolves", _device_offset() == (350, "living-room"))
    off, _q, src = _layer_systemic(1000, 0.9, "default")
    check("layered into offset", off == 1350, f"off={off}")
    check("source labelled", "dev:living-room:+350" in src, src)
    settings.active_timing_device = "default"
    off, _q, src = _layer_systemic(1000, 0.9, "default")
    check("default device = no-op", off == 1000 and "dev:" not in src)

    from services import systemic_offset as so
    so._STORE_PATH = Path(tempfile.mkstemp(suffix="_bias_smoke.json")[1])
    so.reset()
    settings.systemic_offset_enabled = True
    settings.systemic_offset_min_quality = 0.55
    settings.active_timing_device = "living-room"
    so.record(800, 0.9)
    so.record(820, 0.9)
    so.record(810, 0.9)
    so.record(805, 0.9)
    p_lr = so.predict()
    settings.active_timing_device = "patio"
    p_patio = so.predict()
    check("systemic learns on its device", p_lr.n == 4 and p_lr.confidence > 0,
          f"n={p_lr.n} conf={p_lr.confidence}")
    check("other device sees none of it", p_patio.n == 0 and p_patio.bias_ms == 0,
          f"n={p_patio.n}")
    settings.systemic_offset_enabled = False
    settings.active_timing_device = "default"
    settings.timing_device_offsets = {}

    print()
    if _failures:
        print(f"\033[31m{_failures} assertion(s) failed\033[0m")
        return 1
    print("\033[32mAll assertions passed\033[0m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
