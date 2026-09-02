"""ONE CONFIG FILE, AND WHY IT IS THE ENVIRONMENT.

A capture client that runs as a boot service has nobody to type its
arguments. Everything the command line takes can therefore also be declared
in the environment (`SPECTRA_CAPTURE_*`), which is what a systemd
`EnvironmentFile=` is: one file, one place, readable by a person who is
looking for why the machine is talking to the wrong server.

    SPECTRA_CAPTURE_URL=http://spectra:8000/spectra
    SPECTRA_CAPTURE_DEVICE=/dev/video0
    SPECTRA_CAPTURE_POSE=the north shelf

PRECEDENCE, and it only goes one way: an explicit command-line argument
BEATS the environment, and the environment beats the shipped default. So
`deploy/spectra-capture-client.service` passes no arguments at all and the
env file is the whole configuration; a person debugging on the same machine
runs the same module with `--device /dev/video2` and overrides exactly that
one thing without editing the service's file.

THE POSE NAME IS A LABEL, NOT A MEASUREMENT, and this module is where that
distinction has to be stated because this is where the words come from.
`SPECTRA_CAPTURE_POSE` is the human's own name for where this camera stands
— "the north shelf" — carried in `hello` so a status surface can say WHICH
camera is missing rather than "no session". It is not the pose id (minted
inside `camera.open()`, and only that placement makes a reconnect's
assertion honest) and it is not the pose FINGERPRINT (measured by
`spectra/services/pose_fingerprint.py`, which is the only thing that can
tell a moved camera from a changed room). Nothing anywhere may treat this
string as evidence that the camera is where it says it is: it is a name for
a human, and a name is not a measurement.

A MALFORMED NUMBER IN THE ENVIRONMENT IS A REFUSAL, BY NAME, AT STARTUP.
An unattended service that read `SPECTRA_CAPTURE_FPS=fivve` as the default 5
would be a machine quietly doing something other than what its config file
says — the same class of silence this whole area exists to remove. It names
the variable and the value and exits 2.
"""
from __future__ import annotations

import os
from typing import Mapping, Optional

#: Every variable this client reads, and the argparse destination it fills.
#: ONE table, so the docs, the example env file and the parser cannot
#: disagree about what a variable is called — `env_help()` renders it.
ENV_VARS: tuple[tuple[str, str, str], ...] = (
    ("SPECTRA_CAPTURE_URL", "url",
     "SPECTRA's address, e.g. http://spectra:8000/spectra"),
    ("SPECTRA_CAPTURE_DEVICE", "device", "the camera, e.g. /dev/video0"),
    ("SPECTRA_CAPTURE_POSE", "pose_name",
     "this camera's placement in his own words, e.g. 'the north shelf' — a "
     "LABEL carried in hello so a status surface can name which camera is "
     "missing; never evidence of where the camera is"),
    ("SPECTRA_CAPTURE_HOST", "host", "what to call this machine in refusals"),
    ("SPECTRA_CAPTURE_FPS", "fps", "frames per second on the wire"),
    ("SPECTRA_CAPTURE_SIZE", "capture_size",
     "what to ask the camera for, e.g. 1920x1080"),
    ("SPECTRA_CAPTURE_INPUT_FORMAT", "input_format",
     "ffmpeg -input_format, e.g. mjpeg"),
    ("SPECTRA_CAPTURE_QUEUE", "queue", "a declared queue file to run"),
    ("SPECTRA_CAPTURE_LABEL", "label", "a name for that queue"),
    ("SPECTRA_CAPTURE_LOCK_WAIT", "lock_wait",
     "how long to wait for the server to agree the session is locked"),
    ("SPECTRA_CAPTURE_JSON_OUT", "json_out",
     "where to write the machine-readable outcome"),
    ("SPECTRA_CAPTURE_SYNTHETIC", "synthetic",
     "1 to use the black synthetic camera, which reports NO lock — for "
     "proving the wire and the unit reach SPECTRA, never for a map"),
)

#: Which of those are numbers, and what to call them when they are not.
NUMERIC: dict[str, type] = {"fps": float, "lock_wait": float}
#: And which are switches. `SPECTRA_CAPTURE_SYNTHETIC` is safe to have in
#: the environment because the synthetic camera is INCAPABLE of claiming a
#: lock — every run it touches refuses by name. A switch that could make a
#: run happen anyway would not belong here.
BOOLEAN: frozenset = frozenset({"synthetic"})
TRUE_WORDS = ("1", "true", "yes", "on")


class ConfigError(Exception):
    """A configuration file that says something this client cannot read.
    Carried to the command line as exit 2 with the variable named."""


def from_environment(env: Optional[Mapping[str, str]] = None) -> dict:
    """The defaults this environment declares — the argparse `default=` for
    every option, so an explicit argument still wins by construction rather
    than by a merge this module has to get right.

    An empty string is treated as UNSET: a systemd `EnvironmentFile` with a
    commented-out line and one with an empty one should mean the same
    thing, and neither should make a camera try to open the device ''.
    """
    src = os.environ if env is None else env
    out: dict = {}
    for var, dest, _help in ENV_VARS:
        raw = (src.get(var) or "").strip()
        if not raw:
            continue
        if dest in BOOLEAN:
            out[dest] = raw.strip().lower() in TRUE_WORDS
            continue
        caster = NUMERIC.get(dest)
        if caster is not None:
            try:
                out[dest] = caster(raw)
            except ValueError:
                raise ConfigError(
                    f"{var}={raw!r} is not a number, and this client will "
                    f"not start on a configuration it cannot read. Fix the "
                    f"value in the environment file and start it again."
                ) from None
        else:
            out[dest] = raw
    return out


def env_help() -> str:
    """The same table, as prose for `--help` — so the one place a person
    looks for what a variable is called is the program itself."""
    rows = "\n".join(f"  {var:<32} {help_}" for var, _dest, help_ in ENV_VARS)
    return ("Every option below can instead be declared in the environment "
            "(a systemd EnvironmentFile is one file of exactly these); an "
            "explicit argument always wins:\n" + rows)
