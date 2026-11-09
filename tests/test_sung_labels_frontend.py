"""Runs scripts/check_sung_labels_page.mjs (the page's and the Word matches
row's pure parts, the real row component) so the proof fires on every full test
run, and scripts/render_sung_labels.py when a built harness and a Chromium are
present (the render script skips, saying why, when they are not)."""
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
def test_the_sung_labels_page_and_match_row():
    result = subprocess.run(["node", str(REPO / "scripts" / "check_sung_labels_page.mjs")],
                            cwd=REPO, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"


def test_the_sung_labels_page_in_a_real_browser():
    result = subprocess.run([sys.executable, str(REPO / "scripts" / "render_sung_labels.py"), "--no-shots"],
                            cwd=REPO, capture_output=True, text=True, timeout=240)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
