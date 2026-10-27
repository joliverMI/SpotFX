"""The pre-drop controls' own check script (predrop plan step 5), run so it
fires on every full test run rather than only by hand:

  * `scripts/check_pre_drop_phase_tab.mjs` — the pure half
    (spectra/web/src/scenes/tabs/preDropWindows.ts: a scene's window per
    kind, which edits may be written, the looks an entry may pick, the
    drop-sequence preview's request and sentence) and, under jsdom, the
    REAL Phase tab's Pre-drops card (the power button, the min/max fields,
    the look selects, the muted line) and the REAL drop-sequence preview
    (the kind switch, the gap clamped into the draft window, the orange
    mark at the server's mark_s).

Skipped (not failed) when the frontend toolchain isn't installed; the
script itself skips its jsdom sections cleanly when the dev-only jsdom is
missing.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
ESBUILD = REPO / "spectra" / "web" / "node_modules" / ".bin" / "esbuild"

needs_toolchain = pytest.mark.skipif(
    not ESBUILD.exists() or shutil.which("node") is None,
    reason="frontend toolchain (node + esbuild) not installed")


@needs_toolchain
def test_the_pre_drop_phase_tab_controls_behave_as_specified():
    result = subprocess.run(
        ["node", str(REPO / "scripts" / "check_pre_drop_phase_tab.mjs")], cwd=REPO,
        capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, (
        f"check_pre_drop_phase_tab.mjs failed:\n{result.stdout}\n{result.stderr}")
    assert "OK: the pre-drop Phase tab controls behave as specified." in result.stdout
