"""The light-field executable specs, run as SUBPROCESSES from pytest.

WHY SUBPROCESSES and not an in-process import (the shape
tests/test_av_sync_session.py uses for its own simulator): each of these
scripts repoints process-global state on purpose — spectra.config's store
paths, fx.device_model.CATEGORIES_FILE, fx.light_ownership.OWNERSHIP_FILE
(to "spectra owns"), and the fx_seam write primitives themselves. Importing
one into the shared pytest interpreter would leak all of that into every
later test in the session, and an ownership record reading "spectra" is
exactly the kind of leak that makes another test pass or fail for a reason
nobody can find. A fresh interpreter per script costs seconds and makes the
isolation structural rather than careful.

Each script prints one `ok:` line per assertion and exits non-zero on the
first failure, so the assertion below carries the script's own output.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _run(name: str, timeout: int) -> str:
    out = subprocess.run([sys.executable, str(REPO / "scripts" / name)],
                         cwd=REPO, capture_output=True, text=True, timeout=timeout)
    assert out.returncode == 0, out.stdout + out.stderr
    return out.stdout


@pytest.mark.parametrize("name,timeout,tail", [
    # capture: a fake emitter painting a known region must yield that
    # region's grid, and the held-room chain must go dark and come back
    ("check_light_field.py", 180, "ALL LIGHT-FIELD CAPTURE CHECKS PASSED"),
    # the wave, measured on the REAL render pipeline through fx.headless
    ("check_room_effect_wave.py", 300, "ALL ROOM-EFFECT WAVE CHECKS PASSED"),
    # the whole capture session over a real WebSocket and real HTTP routes
    ("check_mapping_capture_e2e.py", 300, "ALL END-TO-END CAPTURE CHECKS PASSED"),
    # SUB-DEVICE granularity: the range lamp on the real render pipeline,
    # three distinct footprints from one strip, and the device-granularity
    # merge as the negative control
    ("check_light_field_granularity.py", 300,
     "ALL LIGHT-FIELD GRANULARITY CHECKS PASSED"),
    # the per-pixel gain MASK: a wave running ALONG one wrapped device,
    # measured on rendered pixels, with the no-mask bit-identity control
    ("check_room_effect_mask.py", 300, "ALL ROOM-EFFECT MASK CHECKS PASSED"),
    # WHICH SIDE of a copy-mapped virtual's copy step the gain mask lands
    # on — the question his second failed run turned on, answered on
    # rendered device pixels rather than reasoned about
    ("check_copy_carrier_wave.py", 180,
     "COPY-CARRIER WAVE QUESTION ANSWERED: BEFORE THE COPY (no travel)"),
])
def test_check_script_passes(name, timeout, tail):
    stdout = _run(name, timeout)
    assert stdout.strip().splitlines()[-1] == tail
    assert "FAIL:" not in stdout
