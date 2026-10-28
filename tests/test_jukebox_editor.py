"""The Jukebox page (/jukebox — spectra/web/src/jukebox/, phase 1 PR 1.3 of
data/jukebox-plan/report.md).

`scripts/check_jukebox_editor.mjs` drives the editor's click rules
(jukeboxEditor.ts, pure) and mounts the REAL page under jsdom against a
recording fake of SpotFX's /api/jukebox routes: each Manual click PUTs the
slots the rule says, Auto → Manual copies the server's own pattern, the
Live tab is read-only except its own jukebox line (it drags the same way
the Guests tab's does and nothing else on Live writes), and hovering the
page's own controls opens each of its five help topics. This test runs it
so the proof fires on every full test run.

Skipped (not failed) when the frontend toolchain isn't installed — the
same posture as tests/test_absorb_page.py. The script itself skips its
mounted half (only) when the dev-only jsdom is absent.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "check_jukebox_editor.mjs"
ESBUILD = REPO / "spectra" / "web" / "node_modules" / ".bin" / "esbuild"


@pytest.mark.skipif(
    not ESBUILD.exists() or shutil.which("node") is None,
    reason="frontend toolchain (node + esbuild in spectra/web) not installed",
)
def test_jukebox_editor_rules_and_page():
    result = subprocess.run(
        ["node", str(SCRIPT)], cwd=REPO, capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, (
        f"check_jukebox_editor.mjs failed:\n{result.stdout}\n{result.stderr}"
    )
