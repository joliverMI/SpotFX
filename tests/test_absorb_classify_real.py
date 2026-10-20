"""Runs scripts/check_absorb_classify.py — Absorb Music's bar against his
REAL shapes, read-only — when his library is on this machine; skips
otherwise. The script classifies a 20-song mix with the runner's own bar and
again with an independent reading of the files, and fails on a disagreement."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SHAPES = Path("/home/javi/SpotFX/storage/audio_shapes")


@pytest.mark.skipif(not SHAPES.is_dir(), reason="his shapes library is not on this machine")
def test_the_bar_agrees_with_an_independent_reading_of_his_real_shapes():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_absorb_classify.py"),
         "--shapes-dir", str(SHAPES)],
        cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-2000:]
    assert "OK: all 20 songs agree" in proc.stdout
