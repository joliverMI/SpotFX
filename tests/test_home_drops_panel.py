"""Home's Drops panel (predrop plan step 1 — spectra/web/src/home/
HomeDrops.tsx): `scripts/check_home_drops_panel.mjs` mounts the REAL card,
the real shared song-timeline view state and the real drop editor in jsdom
against a recording fake of the SPECTRA routes, and proves a part tap sends
one `parts` call, the double tick one `approve`, an undo after removing one
of his own drops puts back both stores, Testing is one PUT, the drop that
just played lights up in place, the next one counts down to its fire moment,
a row's time jumps the audio shape, a double-tap switches a part off as one
undo step, high-confidence parts draw approved, and a tap on the song
timeline's drop pill selects it. This test runs it so the proof fires on
every full test run.

Skipped (not failed) when the frontend toolchain isn't installed; the
script itself skips cleanly when the dev-only jsdom is missing.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "check_home_drops_panel.mjs"
ESBUILD = REPO / "spectra" / "web" / "node_modules" / ".bin" / "esbuild"


@pytest.mark.skipif(not ESBUILD.exists() or shutil.which("node") is None,
                    reason="frontend toolchain (node + esbuild) not installed")
def test_the_drops_panel_sends_one_call_per_tap_and_undoes_both_stores():
    result = subprocess.run(["node", str(SCRIPT)], cwd=REPO, capture_output=True,
                            text=True, timeout=180)
    assert result.returncode == 0, (
        f"check_home_drops_panel.mjs failed:\n{result.stdout}\n{result.stderr}")
    assert ("OK: Home's Drops panel behaves as specified." in result.stdout
            or "skipping this check" in result.stdout)
