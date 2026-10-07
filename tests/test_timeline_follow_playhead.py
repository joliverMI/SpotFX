"""The Timeline's follow window keeps the DRAWN playhead in view.

The Admiral, 2026-10-07, on Pop Off: "the playhead appears to be ahead of
the scrolling view on the timeline". The playhead layer draws at the audible
clock plus the song's stored shape offset; follow mode anchored its window on
the raw progress clock, so on a song whose offset exceeds the look-ahead
(Pop Off: 14,450 ms against 10 s) the line sat past the right edge for the
whole song. `scripts/check_timeline_follow_playhead.mjs` transpiles the real
frontend arithmetic, drives it with his numbers, carries the pre-fix anchor
as a red control and pins the wiring in both Timeline twins; this test runs
it so the proof fires on every full test run.

Skipped (not failed) when the frontend toolchain isn't installed — the same
posture as tests/test_spectra_web_typecheck.py.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "check_timeline_follow_playhead.mjs"
ESBUILD = [REPO / "spectra" / "web" / "node_modules" / ".bin" / "esbuild",
           REPO / "web" / "node_modules" / ".bin" / "esbuild"]


@pytest.mark.skipif(
    not all(p.exists() for p in ESBUILD) or shutil.which("node") is None,
    reason="frontend toolchain (node + esbuild in both web apps) not installed",
)
def test_follow_window_keeps_the_drawn_playhead_in_view():
    result = subprocess.run(
        ["node", str(SCRIPT)], cwd=REPO, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, (
        f"check_timeline_follow_playhead.mjs failed:\n{result.stdout}\n{result.stderr}"
    )
    assert "ALL OK" in result.stdout
