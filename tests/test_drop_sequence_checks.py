"""The drop-sequence Timeline's own check scripts (drop-detection plan
phases 3-4, and the pre-drop handle of predrop plan step 4), run so they
fire on every full test run rather than only by hand:

  * `scripts/check_drop_sequence_view.mjs` — the display model, the canvas
    layer's geometry and hit tests, and the pre-drop's glyph per kind, its
    looks per part state and its two snap rails (hits and vocal entries);
  * `scripts/check_drop_sequence_edit.mjs` — the editing arithmetic (snap,
    step, the order clamp, the pre-drop held inside its kind's lead range,
    a whole-sequence move carrying it) and, under jsdom, the real hook and
    detail card sending exactly one request per press, his "his:" key
    included, and undo through /restore.

Skipped (not failed) when the frontend toolchain isn't installed; the edit
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


def _run(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(["node", str(REPO / "scripts" / script)], cwd=REPO,
                          capture_output=True, text=True, timeout=300)


@needs_toolchain
def test_the_drop_sequence_view_and_layer_behave_as_specified():
    result = _run("check_drop_sequence_view.mjs")
    assert result.returncode == 0, (
        f"check_drop_sequence_view.mjs failed:\n{result.stdout}\n{result.stderr}")
    assert "OK: the drop-sequence view and layer behave as specified." in result.stdout


@needs_toolchain
def test_editing_drop_sequences_and_their_pre_drops_behaves_as_specified():
    result = _run("check_drop_sequence_edit.mjs")
    assert result.returncode == 0, (
        f"check_drop_sequence_edit.mjs failed:\n{result.stdout}\n{result.stderr}")
    assert "OK: editing drop sequences behaves as specified." in result.stdout
