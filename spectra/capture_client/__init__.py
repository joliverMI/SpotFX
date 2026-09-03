"""THE UNATTENDED CAPTURE CLIENT — a process on a machine with a camera that
establishes a SPECTRA mapping session on its own, holds it through drops,
and (optionally) drives a declared queue of capture runs to the end.

    python -m spectra.capture_client --url http://spectra:8000/spectra \\
        --device /dev/video0 --queue overnight.json

It exists because the camera session was the single point of failure only
the captain could set up: every capture experiment queued behind him being
awake and holding a phone. What it does NOT relax is the instrument's
honesty — `camera.py`'s docstring is the binding statement on that, and the
short version is that automating the lock REQUEST is the point and
automating the lock CONFIRMATION is forgery.

  camera.py    what a camera is, and the read-back rule
  session.py   the WebSocket half: hello, frames, pong, reconnect, pose
  __main__.py  the command line, and the machine-readable outcome
  doctor.py    `--doctor`: every link in the chain from this machine to
               SPECTRA, named. STDLIB-ONLY and runnable as a plain file, so
               it still works when the virtualenv is the broken thing

`docs/UNATTENDED_CAPTURE.md` carries the ledger: what now runs with no human
at all, what needs one once, and what still needs his hands per run.
"""
from __future__ import annotations

from spectra.capture_client.camera import (BaseCamera, CameraLock,  # noqa: F401
                                           CameraUnavailable, FRAME_H,
                                           FRAME_W, SyntheticCamera,
                                           V4L2Camera)
from spectra.capture_client.session import CaptureClient, ClientState  # noqa: F401
