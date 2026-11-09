"""Runs scripts/check_testbed_lyrics_lane.mjs (the Sung words lane's pure
helpers and the real component) so the proof fires on every full test run,
and scripts/render_testbed_lyrics_lane.py when a built harness and a Chromium
are present. Skipped, not failed, when the frontend toolchain is missing."""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
ESBUILD = REPO / "spectra" / "web" / "node_modules" / ".bin" / "esbuild"


@pytest.mark.skipif(not ESBUILD.exists() or shutil.which("node") is None,
                    reason="frontend toolchain (node + esbuild) not installed")
def test_the_sung_words_lane_frontend():
    result = subprocess.run(
        ["node", str(REPO / "scripts" / "check_testbed_lyrics_lane.mjs")],
        cwd=REPO, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"


def test_the_sung_words_lane_in_a_real_browser():
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "render_testbed_lyrics_lane.py"), "--no-shots"],
        cwd=REPO, capture_output=True, text=True, timeout=240,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
