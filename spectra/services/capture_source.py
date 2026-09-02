"""WHICH CLIENT ESTABLISHED THIS SESSION, AND WHAT THAT ENTITLES IT TO —
the browser demoted from calibration instrument to viewfinder, by name.

THE EVENING THIS EXISTS FOR (2026-09-01). The browser path failed him four
distinct ways in one sitting, and three of them are properties of the
browser itself rather than of any code above it:

  * HIS BRIO EXPOSES NO GAIN through a browser at all, so a whole pinned
    lever is simply unreachable there.
  * THE READ-BACK ECHOES THE REQUEST. `getSettings()` reported back what was
    asked for; commanded integration times of 10 ms, 60 ms and 200 ms — a
    factor of twenty end to end — produced footprint weights of 0.0, 0.0014
    and 0.0051 against the 1.0 an emitter must clear to count as SEEN. The
    driver agreed with every command and the sensor obeyed none of them.
  * AN AUTO MECHANISM KEPT RE-ADAPTING UNDERNEATH, which the page cannot
    pin and his own eyes reported as "I can see well, then it gets really
    dark" — the camera's own converged regime wandering 0.23 to 0.01
    between two runs of the same thing.

(The fourth was a cached tab silently running old capture code, and it dies
here too, for a reason that needs no new machinery: calibration can no
longer ride stale browser code because it cannot ride the browser at all.)

WHAT IS DEMOTED, PRECISELY. The BROWSER'S STANDING AS A CALIBRATION SOURCE,
and nothing else. The wire protocol is SHARED — the native client speaks the
same `hello`/`frame`/`lock` session `spectra/services/mapping_session.py`
has always spoken — so none of that machinery moves, weakens or forks. A
browser session still connects, still streams frames, still reports its lock
and is still the right tool for the job it is genuinely good at: POINTING A
CAMERA. Aiming is a live picture and a person's judgement, and neither of
them cares whether the sensor obeys its own exposure control.

WHAT A BROWSER SESSION MAY STILL DO, deliberately and in full: the live
preview, Start camera, the two axis taps, every read surface, and PRESSING
THE RUN BUTTONS — the page stays the remote control. What it may no longer
do is BE the instrument those buttons measure with.

THE RULE, one sentence: a calibration-grade run (`capture_runs.
CALIBRATION_GRADE`) requires a session the NATIVE capture client
established. A session that has not said what it is is NOT native — the
same conservative default `is_native` has always had, and the reason an
unknown client can never be promoted by silence.

WHY THIS IS ITS OWN MODULE rather than three lines in `capture_runs`: the
client-kind question is asked by the run gate, by the queue's own wait, by
the session-status surface the page reads and by the test doubles that
stand in for a client. One definition, so a fourth caller cannot invent a
fifth answer — the same discipline `mapping_session.lock_refusal` and
`capture_runs` itself are built on. It imports nothing from `spectra`, so
anything may ask it.
"""
from __future__ import annotations

from typing import Any, Optional

#: What the native capture client calls itself in `hello`. Mirrored rather
#: than imported: this module runs in the SPECTRA process and the client
#: package is meant to run on a machine that has only the client
#: (`requirements-capture-client.txt` is two lines for exactly that reason).
NATIVE_CLIENT = "spectra-capture-client"

#: The unattended capture client on the machine by the camera — the one
#: thing that can pin this camera and prove it obeyed.
KIND_NATIVE = "native"
#: A browser page. A VIEWFINDER: first-class for aiming, never a calibration
#: source.
KIND_BROWSER = "browser"
#: Nothing is holding a camera on the room at all.
KIND_NONE = "none"


def kind_of_hello(hello: dict) -> str:
    """Which sort of client said this `hello`. The whole decision, on the
    one field a client says about itself — so a caller holding only the
    hello (a status view being read back, a queue log) reaches the same
    answer as one holding the session."""
    if str((hello or {}).get("client") or "") == NATIVE_CLIENT:
        return KIND_NATIVE
    return KIND_BROWSER


def kind(session: Any) -> str:
    """Which sort of client this session is, from its own `hello`.

    Duck-typed on purpose, like `capture_health.describe`: every test
    double is a valid argument and this module imports no session class."""
    if session is None:
        return KIND_NONE
    return kind_of_hello(getattr(session, "hello", None) or {})


def is_native(session: Any) -> bool:
    """Is this the unattended capture client rather than a browser page?

    THE ONE IMPLEMENTATION. `lever_selftest.is_native` is this function; so
    is the calibration-grade gate in `capture_runs`. A session that has not
    said is NOT native, so nothing is ever promoted by silence."""
    return kind(session) == KIND_NATIVE


def calibration_grade(session: Any) -> bool:
    """May this session SOURCE a measurement somebody later compares against
    another measurement? Today that is exactly "is it native" — and it is a
    separate name because it is a separate question, and the day a second
    client kind can hold a camera honestly, this is the one line that
    changes rather than every caller that asks."""
    return is_native(session)


def measured_by(session: Any) -> str:
    """WHOSE CAMERA a run would measure with, in his words — so a page
    showing a Start button is never ambiguous about which device is about to
    take the readings.

    A WHOLE SENTENCE, not a fragment: it is the line a page puts above a
    Start button, and it has to make sense on its own to somebody who did
    not read the paragraph before it. The browser case says what the browser
    IS doing before it says what it is not, because that is the true and
    more useful half — it really is aiming the camera.

    ONE WORDING PER STATE, and the native one is `mapping_refusals`' own —
    that module owns every sentence on this path, and a second copy of "the
    capture client on X is holding the camera" living here would be exactly
    the drift it exists to prevent."""
    k = kind(session)
    if k == KIND_NONE:
        return "No camera is connected."
    if k == KIND_NATIVE:
        from spectra.services import mapping_refusals
        return mapping_refusals.calibration_source_note(describe(session))
    return ("This browser is holding the camera, which aims it. A "
            "measurement is taken by the capture client on the machine "
            "beside the camera.")


def describe_hello(hello: dict) -> dict:
    """The small identity row, from a `hello` alone — for a caller that has
    the published view rather than the session object (the queue's own wait
    is the one that needs it)."""
    hello = dict(hello or {})
    return {"kind": kind_of_hello(hello),
            "host": str(hello.get("host") or ""),
            "pose_name": str(hello.get("pose_name") or ""),
            "version": str(hello.get("client_version") or ""),
            "user_agent": str(hello.get("user_agent") or "")}


def describe(session: Any) -> dict:
    """The small identity row a status surface needs, without reaching into
    the session object."""
    return describe_hello(getattr(session, "hello", None) or {})


def calibration_refusal(session: Any, *, action: str = "") -> Optional[str]:
    """The sentence a calibration-grade run refuses with when this session
    cannot source one, or None when it can.

    `mapping_refusals` OWNS THE WORDING — imported here rather than
    reimplemented, so the run gate, the queue's wait and the page all say
    the same thing, which is the whole reason that module exists. Imported
    inside the function only to keep this module import-free at the top,
    so anything at all may ask it."""
    if session is None or calibration_grade(session):
        return None
    from spectra.services import mapping_refusals
    return mapping_refusals.browser_not_calibration_grade(
        describe(session), action=action)
