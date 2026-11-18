"""Home's audio shape carries the word trigger points, and a tap says what
a word will do (Word Shapes W5.2).

The Admiral, 2026-11-18: "Show the word/effect details on the audio shape
on home page. Put the trigger point on the audio shape, not just to top
ticker. i should be able to tap the audio shape to learn more. make it
clean."

`spectra/web/src/timeline/canvas/wordsLayer.ts` draws every `kind: "word"`
row of `/api/upcoming` — plus a tick on every event a word imprints its
colour on — at `eventFireMs`, in `wordColour`, with `shapeGlyph`: the SAME
helpers `components/songStrip.ts` already draws the top ticker's markers
with, so the two surfaces can never disagree about when a word fires or
what it is. `home/WordDetailsCard.tsx` is the tap's own answer.

`scripts/check_home_words.mjs` is the executable spec: the real layer and
card driven with a recording fake 2D context (markers, dimming, the ±6 px
hit test, the card's lines and its phone gutter), the ticker/shape
agreement proved against `drawShapeMarkers` on the same rows, the REAL
HomeTimeline mounted in jsdom and tapped (the card opens, dismisses on an
outside tap and on Escape, and the drop-select tap still selects), and the
`home-page` help topic's new link and sentence.

Skipped (not failed) when the frontend toolchain isn't installed — the
same posture as tests/test_home_rms_scaling.py. The script's own jsdom
section self-skips when that dev-only package is absent, so this wrapper
still passes on a box with node and esbuild but no jsdom.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "check_home_words.mjs"
ESBUILD = REPO / "spectra" / "web" / "node_modules" / ".bin" / "esbuild"


@pytest.mark.skipif(
    not ESBUILD.exists() or shutil.which("node") is None,
    reason="frontend toolchain (node + esbuild in spectra/web) not installed",
)
def test_home_audio_shape_word_markers_and_details_card():
    result = subprocess.run(
        ["node", str(SCRIPT)], cwd=REPO, capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0, (
        f"check_home_words.mjs failed:\n{result.stdout}\n{result.stderr}"
    )
    assert "ALL CHECKS PASSED" in result.stdout
