"""The Light Show's Sequence tab (spectra/web/src/lightshow/SequenceView.tsx)
— the Admiral, 2026-10-09: Show Sequences, built and run in "a new tab,
along with build, run".

`scripts/check_show_sequence_ui.mjs` mounts the REAL SequenceView.tsx under
jsdom (only window.fetch stood in) and drives Build (arming icons, Waits,
the song search, a pointer drag, Save, Duplicate) and Run (the highlighted
current item, every control); this test runs it so the proof fires on every
full run.

Skipped (not failed) when the frontend toolchain or the dev-only jsdom isn't
installed — the posture of tests/test_spectra_web_typecheck.py.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "check_show_sequence_ui.mjs"
NODE_MODULES = REPO / "spectra" / "web" / "node_modules"


@pytest.mark.skipif(
    not (NODE_MODULES / "esbuild").exists() or not (NODE_MODULES / "jsdom").exists()
    or shutil.which("node") is None,
    reason="frontend toolchain (node, esbuild, dev-only jsdom) not installed",
)
def test_show_sequence_tab_builds_and_runs():
    result = subprocess.run(
        ["node", str(SCRIPT)], cwd=REPO, capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, (
        f"check_show_sequence_ui.mjs failed:\n{result.stdout}\n{result.stderr}"
    )
    assert "all passed" in result.stdout
