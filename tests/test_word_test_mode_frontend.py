"""Runs scripts/check_word_test_mode_ui.mjs (WORD TEST MODE's two UI
surfaces — the Settings card and the roll line — the real components in
jsdom against a fake /room-controls) so the proof fires on every full test
run. Skipped, not failed, when the frontend toolchain is missing; the
check itself skips cleanly when jsdom is not installed (it is dev-only,
not a declared dependency).
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
ESBUILD = REPO / "spectra" / "web" / "node_modules" / ".bin" / "esbuild"


@pytest.mark.skipif(not ESBUILD.exists() or shutil.which("node") is None,
                    reason="frontend toolchain (node + esbuild) not installed")
def test_the_word_test_mode_ui():
    result = subprocess.run(
        ["node", str(REPO / "scripts" / "check_word_test_mode_ui.mjs")],
        cwd=REPO, capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
