"""TimelineCanvas.tsx's per-pointer isolation on a multi-touch drag.

PR "no-mistakes(review): Fix touch beat-snap radius scale and pointer-id
cross-contamination" (2026-10-08) made `dragging`/`panStart` carry the
owning pointer's own id so a second, unrelated pointer (a resting palm
beside a panning/dragging finger) can never drive or end the first
pointer's gesture. `scripts/check_timeline_canvas_pointer_isolation.mjs`
mounts the REAL component (both Timeline twins) under jsdom via
react-dom/client and dispatches real multi-pointer PointerEvents,
asserting on the `pointer` prop's own callback invocations.

Skipped (not failed) when the frontend toolchain isn't installed, OR
when `jsdom` isn't installed in spectra/web/node_modules — jsdom is a
dev-only check dependency here (not a declared package.json dependency,
matching scripts/check_topbar_scene_colour_names.mjs's own convention);
install with `cd spectra/web && npm install --no-save jsdom` to run it.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "check_timeline_canvas_pointer_isolation.mjs"
ESBUILD = [REPO / "spectra" / "web" / "node_modules" / ".bin" / "esbuild",
           REPO / "web" / "node_modules" / ".bin" / "esbuild"]
JSDOM = REPO / "spectra" / "web" / "node_modules" / "jsdom"


@pytest.mark.skipif(
    not all(p.exists() for p in ESBUILD) or not JSDOM.exists() or shutil.which("node") is None,
    reason="frontend toolchain (node + esbuild in both web apps + dev-only jsdom) not installed",
)
def test_a_second_pointer_never_drives_or_ends_the_first_pointers_drag_or_pan():
    result = subprocess.run(
        ["node", str(SCRIPT)], cwd=REPO, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, (
        f"check_timeline_canvas_pointer_isolation.mjs failed:\n{result.stdout}\n{result.stderr}"
    )
    assert "PASS" in result.stdout
