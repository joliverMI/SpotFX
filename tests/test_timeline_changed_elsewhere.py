"""A stale Timeline never saves a removed trigger back silently (predrop
plan step 1 — spectra/web/src/timeline/store.ts's `changedElsewhere`):
`scripts/check_timeline_changed_elsewhere.mjs` drives the REAL Builder
store and its REAL websocket hook through Home's Drops panel's
`profile_triggers_changed` broadcast — an unsaved edit's save is held until
he chooses, a clean tab reloads, and either reload starts a fresh undo
history. This test runs it so the proof fires on every full test run.

Skipped (not failed) when the frontend toolchain isn't installed; the
script itself skips cleanly when the dev-only jsdom is missing.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "check_timeline_changed_elsewhere.mjs"
ESBUILD = REPO / "spectra" / "web" / "node_modules" / ".bin" / "esbuild"


@pytest.mark.skipif(not ESBUILD.exists() or shutil.which("node") is None,
                    reason="frontend toolchain (node + esbuild) not installed")
def test_a_stale_timeline_holds_its_save_and_says_the_song_changed():
    result = subprocess.run(["node", str(SCRIPT)], cwd=REPO, capture_output=True,
                            text=True, timeout=180)
    assert result.returncode == 0, (
        f"check_timeline_changed_elsewhere.mjs failed:\n{result.stdout}\n{result.stderr}")
    assert ("OK: a stale Timeline never saves a removed trigger back silently." in result.stdout
            or "skipping this check" in result.stdout)
