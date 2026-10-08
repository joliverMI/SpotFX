"""Single-finger touch panning on the Timeline's audio-shape canvas.

The Admiral, 2026-10-08: "i want to be able to drag the audio shape graph
somehow on a tablet or phone. double finger scroll would work for me, or
single finger if it would work well." A single-finger drag on empty graph
(no marker/trigger under it — the existing hit test already decides that)
now pans the window with a small direction-lock threshold, so a mostly-
vertical swipe is left to the browser's own page scroll instead.
`scripts/check_timeline_touch_pan.mjs` transpiles the real frontend
arithmetic (canvas/touchPan.ts) and drives it directly, and asserts the
two Timeline twins' copies of the module are byte-identical; this test
runs it so the proof fires on every full test run.

Skipped (not failed) when the frontend toolchain isn't installed — the
same posture as tests/test_timeline_follow_playhead.py.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "check_timeline_touch_pan.mjs"
ESBUILD = [REPO / "spectra" / "web" / "node_modules" / ".bin" / "esbuild",
           REPO / "web" / "node_modules" / ".bin" / "esbuild"]


@pytest.mark.skipif(
    not all(p.exists() for p in ESBUILD) or shutil.which("node") is None,
    reason="frontend toolchain (node + esbuild in both web apps) not installed",
)
def test_touch_pan_direction_lock_and_delta_match_the_mouse_pan():
    result = subprocess.run(
        ["node", str(SCRIPT)], cwd=REPO, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, (
        f"check_timeline_touch_pan.mjs failed:\n{result.stdout}\n{result.stderr}"
    )
    assert "ALL OK" in result.stdout
