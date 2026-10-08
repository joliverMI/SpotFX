"""The Light Show's High/Low flag drag arithmetic (cueFlags.ts).

Runs scripts/check_show_cue_flags.mjs, which transpiles the real module
with esbuild. Extended 2026-10-08 (the Admiral: "I'm having trouble
precisely moving the trigger on the large bar") with the beat-snap and
"no jump" grab-offset arithmetic a touch-precise drag needs.

Skipped (not failed) when the frontend toolchain isn't installed — the
same posture as tests/test_timeline_follow_playhead.py.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "check_show_cue_flags.mjs"
ESBUILD = REPO / "spectra" / "web" / "node_modules" / ".bin" / "esbuild"


@pytest.mark.skipif(
    not ESBUILD.exists() or shutil.which("node") is None,
    reason="frontend toolchain (node + esbuild in spectra/web) not installed",
)
def test_show_cue_flags_drag_arithmetic():
    result = subprocess.run(
        ["node", str(SCRIPT)], cwd=REPO, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, (
        f"check_show_cue_flags.mjs failed:\n{result.stdout}\n{result.stderr}"
    )
    assert "all passed" in result.stdout
