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
    # UNATTENDED CAPTURE: a declared queue of map + commissioning runs
    # executed end to end against the REAL capture client and a synthetic
    # camera, with no human action after start — plus the drop, the kept
    # partial, the pose assertion and every refusal by name
    ("check_capture_queue_e2e.py", 600,
     "ALL UNATTENDED CAPTURE CHECKS PASSED"),
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
    # COMMISSIONING: the pattern lamp on the real pipeline, a declared
    # arrangement recovered end to end, the sabotage each failing its own
    # frozen row — AND (section 3c) the field regime his own two runs hit,
    # reproduced on demand. A reproduction nobody runs is not a standing
    # proof, which is why this one is in the suite rather than only in a
    # PR's own transcript.
    ("check_commissioning.py", 300, "ALL COMMISSIONING CHECKS PASSED"),
    # THE LEVER-IS-REAL SELF-TEST, over the whole real path: the real
    # client, a real WebSocket, the real capture-run seam and the real map
    # route. Both directions, because a gate that refuses everything is a
    # wall — an honest camera PASSES and its map runs; tonight's own
    # measured shape and a re-clamping camera are each refused by name.
    ("check_lever_selftest.py", 600, "ALL CHECKS PASSED"),
    # A STAMP IS NOT A PHOTON. The self-test above proves the JUDGEMENT
    # against a camera that is a function; this measures the TRANSPORT that
    # a function does not have — how many whole frames really sit between
    # ffmpeg and the client (19, 3.8 s at 5 fps, and it saturates there),
    # that the read this replaced handed back frames seconds old, and that
    # a capture window over the real wire now averages only frames stamped
    # within a frame period of being taken.
    ("check_stream_freshness.py", 300, "STREAM FRESHNESS CHECKS PASSED"),
    # THE POSE FINGERPRINT's boundaries, SWEPT rather than sampled: a camera
    # move and a room change of growing size, parallax, the instrument's own
    # repeat wander, and the two anchor sets that can never discriminate.
    # The property that matters is not that each verdict is reachable but
    # that there is NOWHERE in the range where it says something confident
    # and wrong — which only a sweep can show.
    ("check_pose_fingerprint.py", 300,
     "ALL POSE FINGERPRINT CHECKS PASSED"),
    # THE CAMERA HOST AS A BOOT SERVICE: the shipped systemd unit verified
    # by systemd's own parser, the provisioning script's refusals and its
    # idempotence on a throwaway HOME, and the unit's own ExecStart —
    # configured ONLY by the unit's own EnvironmentFile, no arguments —
    # establishing a real session on a real server, dying, being READ as
    # absent by name, and coming back under the unit's own Restart policy.
    # What it cannot do here is let systemd itself start the unit (this
    # machine has no session bus); the script says so in its own output.
    ("check_capture_client_service.py", 600,
     "ALL CAPTURE CLIENT SERVICE CHECKS PASSED"),
    # AND THE SAME FAILURES ON MACHINES THAT NEVER SAW THIS REPO: a REAL
    # 216/GROUP from the host's own systemd user manager, and a stock Debian
    # container with a user created seconds ago (not in `video`, and with no
    # ensurepip) refusing by name and writing nothing. The script SKIPS a
    # rig it cannot run — no docker, no session bus — with the reason named,
    # so an unavailable facility is a hole in the ledger rather than a pass.
    ("check_capture_client_fresh_host.py", 1200,
     "FRESH-HOST CHECKS PASSED"),
    # WHAT THE CLIENT IMPORTS, which is the only part of the ARM question
    # an x86 machine can answer: it imports with every server-only package
    # blocked at the meta path, its third-party closure is exactly the two
    # declared, it never reaches into fx/, and nothing in it branches on an
    # architecture. No board has run it, and the script says that too.
    ("check_capture_client_deps.py", 180,
     "ALL CAPTURE CLIENT DEPENDENCY CHECKS PASSED"),
])
def test_check_script_passes(name, timeout, tail):
    stdout = _run(name, timeout)
    assert stdout.strip().splitlines()[-1] == tail
    assert "FAIL:" not in stdout
