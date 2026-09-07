"""THE COMMAND LINE — one line to start, and a machine-readable answer when
it finishes.

    # hold a session so someone else can press things
    python -m spectra.capture_client --url http://spectra:8000/spectra

    # the whole night, unattended
    python -m spectra.capture_client --url http://spectra:8000/spectra \\
        --queue overnight.json --json-out /tmp/last-capture.json

    # or with nothing on the command line at all, because a boot service
    # has nobody to type it: SPECTRA_CAPTURE_URL and its siblings say the
    # same things (`config.py`), and an explicit argument still wins.
    python -m spectra.capture_client

    # the OTHER instrument on the same machine: measure how far the lights
    # are behind the sound, using this camera and the microphone beside it
    python -m spectra.capture_client --url http://spectra:8000/spectra \
        --avsync --audio-device BRIO --measure

EXIT CODES, because the caller is a cron line or a systemd unit and not a
person reading prose:

    0  every declared item completed
    1  the queue ran and something did not complete (partial, refused,
       not run) — the JSON says which item and why, in a sentence
    2  nothing ran: no camera, no microphone, no session, a bad queue file,
       or SPECTRA unreachable

In `--avsync --measure` the same three codes mean: 0 the instrument
produced a number for every run, 1 it ran and REFUSED (weak/ambiguous/
unstable/no audio reference — the server's own reason and statement are in
the JSON), 2 nothing ran. A refusal is a result, not a crash: the room was
flashed, the correlation was honest, and it declined to guess.

THE ONE PLACE THIS COULD HAVE CHEATED and does not: `--queue` waits for the
SERVER to agree the session is locked (`GET /api/rooms/capture-queue`'s own
`session` view, which is `mapping_session.lock_refusal`'s answer) before it
posts anything. It never asserts the lock on the server's behalf, and if the
camera will not lock it posts nothing and exits 2 with the camera's own
refusal.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import platform
import sys
from typing import Optional

import httpx

from spectra.capture_client import doctor
from spectra.capture_client.camera import (CameraLock, SyntheticCamera,
                                           V4L2Camera)
from spectra.capture_client.config import (ConfigError, env_help,
                                           from_environment)
from spectra.capture_client.session import CLIENT_VERSION, CaptureClient

#: How long to wait for the SERVER to report the session present and locked
#: before giving up on a queue. Generous: a camera has to settle before it
#: can honestly report anything.
DEFAULT_LOCK_WAIT_S = 90.0
POLL_S = 1.0

#: THE A/V-SYNC MODE'S OWN DEFAULTS. The microphone default is a NAME, and
#: it is the camera's own built-in one: co-locating the two is what makes
#: the measurement about the room rather than about two places in it.
DEFAULT_AUDIO_DEVICE = "BRIO"
#: 30 fps rather than the map's 5. The exposure-integration systematic is
#: half a frame interval, so this buys a tighter light edge; it costs about
#: 2 % of one core in the reduction (measured — `avsync_reduce`'s docstring).
DEFAULT_AVSYNC_FPS = 30.0
#: What the A/V-sync camera asks the device for. Small on purpose: this
#: instrument measures WHEN a region got brighter, never what is in the
#: frame, so pixels past this buy nothing and cost latency in the pipe.
DEFAULT_AVSYNC_CAPTURE_SIZE = (640, 480)


def _venv_path() -> str:
    """The virtualenv this process is running FROM, when it is running from
    one — read off `sys.prefix` rather than guessed from a path the
    installer happens to use today. The launcher execs the venv's own
    python, so `--doctor` through the installed launcher inspects the
    environment it is actually in; run from a checkout's `.venv` it inspects
    that, which is equally honest."""
    if sys.prefix != getattr(sys, "base_prefix", sys.prefix):
        return sys.prefix
    return ""


def _urls(base: str) -> tuple[str, str]:
    """(http base, ws url). Accepts either the proxied address he actually
    uses (http://host:8000/spectra) or the SPECTRA port directly."""
    base = base.rstrip("/")
    ws = base.replace("https://", "wss://").replace("http://", "ws://")
    return base, f"{ws}/api/rooms/map/ws"


async def _wait_locked(http: httpx.AsyncClient, timeout: float) -> tuple[bool, str]:
    """Ask the SERVER whether the session is present and locked. Its answer,
    never ours."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    detail = "SPECTRA never reported a capture session"
    while loop.time() < deadline:
        try:
            body = (await http.get("/api/rooms/capture-queue")).json()
            view = body.get("session") or {}
            if view.get("present") and view.get("locked"):
                return True, ""
            detail = view.get("refusal") or detail
        except httpx.HTTPError as exc:
            detail = f"SPECTRA is not answering at this address ({exc})"
        await asyncio.sleep(POLL_S)
    return False, detail


def _avsync_ws(base: str) -> str:
    """The A/V-sync endpoint on the same address the mapping session uses —
    `spectra/api/av_sync.py`'s own route, derived here rather than typed
    into a config file so one --url covers both instruments."""
    ws = base.rstrip("/").replace("https://", "wss://").replace("http://",
                                                               "ws://")
    return f"{ws}/api/av-sync/ws"


async def _run_avsync(args, ws_url: str) -> tuple[int, dict]:
    """THE A/V-SYNC RUN. Opens the camera and the microphone, refuses by
    name if either will not, streams the two reduced signals, and — with
    --measure — asks the server for the number and reports what it said.

    The three outcomes are kept apart on purpose: 2 is "nothing ran", 1 is
    "it ran and the instrument declined to give a number", 0 is a number.
    Collapsing the middle one into a crash would make an honest refusal look
    like a broken machine."""
    # NOT `import websockets` + `websockets.exceptions` — that attribute
    # does not exist until the submodule is imported by name, and the one
    # moment it would be reached is the one where SPECTRA is unreachable.
    from websockets.exceptions import WebSocketException

    from spectra.capture_client.avsync_audio import (ArecordSource,
                                                     AudioUnavailable,
                                                     resolve_device)
    from spectra.capture_client.avsync_session import (AvSyncKioskClient,
                                                       MeasurementFailed)
    from spectra.capture_client.camera import CameraUnavailable

    try:
        device = resolve_device(args.audio_device)
    except AudioUnavailable as exc:
        return 2, {"started": False, "detail": str(exc)}
    camera = V4L2Camera(args.device, fps=args.avsync_fps,
                        capture_size=DEFAULT_AVSYNC_CAPTURE_SIZE,
                        input_format=args.input_format)
    audio = ArecordSource(device)
    client = AvSyncKioskClient(ws_url, camera, audio, host=args.host,
                               pose_name=args.pose_name)
    try:
        await client.start_devices()
    except (CameraUnavailable, AudioUnavailable) as exc:
        await client.close_devices()
        return 2, {"started": False, "detail": str(exc),
                   "audio_device": device}
    logging.info("av-sync: camera %s at %.0f fps, microphone %s",
                 args.device, args.avsync_fps, device)
    try:
        if not args.measure:
            # HOLD. There is no second way to start a measurement — the
            # server takes `measure` only over this socket — so holding is
            # for watching the two streams arrive (GET /api/av-sync/status)
            # before committing his room to a flash.
            logging.info("av-sync: holding the session (no --measure); "
                         "ctrl-c to stop")
            try:
                await client.hold()
            except KeyboardInterrupt:              # pragma: no cover
                pass
            return 0, {"held": True, "client": client.state.as_dict()}
        runs = await client.run_measurements(
            mode=args.measure_mode, duration_s=args.measure_seconds,
            runs=args.measure_runs)
    except MeasurementFailed as exc:
        return 1, {"started": True, "ok": False, "detail": str(exc),
                   "estimate": exc.estimate, "audio_device": device,
                   "client": client.state.as_dict(),
                   "audio_stats": audio.stats()}
    except (CameraUnavailable, AudioUnavailable) as exc:
        return 2, {"started": True, "ok": False, "detail": str(exc),
                   "audio_device": device,
                   "client": client.state.as_dict()}
    except (OSError, WebSocketException) as exc:
        # SPECTRA is not answering at this address, or answered something
        # that is not a WebSocket. Nothing ran, so it is a 2.
        return 2, {"started": False, "ok": False,
                   "detail": f"could not reach SPECTRA at {ws_url}: "
                             f"{type(exc).__name__}: {exc}"}
    finally:
        await client.close_devices()
    return 0, {"started": True, "ok": True, "audio_device": device,
               "runs": runs,
               "offsets_ms": [r["estimate"]["av_offset_ms"] for r in runs],
               "statements": [r["estimate"]["statement"] for r in runs]}


async def _drive_queue(base: str, queue_path: str, label: str,
                       lock_wait: float) -> tuple[int, dict]:
    try:
        with open(queue_path, "r", encoding="utf-8") as fh:
            declared = json.load(fh)
    except (OSError, ValueError) as exc:
        return 2, {"started": False,
                   "detail": f"the queue file could not be read: {exc}"}
    items = declared.get("items") if isinstance(declared, dict) else declared
    async with httpx.AsyncClient(base_url=base, timeout=30.0) as http:
        ok, detail = await _wait_locked(http, lock_wait)
        if not ok:
            return 2, {"started": False, "detail": detail}
        r = await http.post("/api/rooms/capture-queue",
                            json={"label": label, "items": items})
        if r.status_code >= 400:
            return 2, {"started": False,
                       "detail": r.json().get("detail", r.text)}
        while True:
            await asyncio.sleep(POLL_S)
            try:
                body = (await http.get("/api/rooms/capture-queue")).json()
            except httpx.HTTPError:
                continue
            queue = body.get("current") or {}
            if queue and queue.get("finished_at"):
                counts = queue.get("counts") or {}
                complete = counts.get("ok", 0) == queue.get("declared")
                return (0 if complete else 1), queue


def main(argv: Optional[list[str]] = None) -> int:
    try:
        env = from_environment()
    except ConfigError as exc:
        # AN UNREADABLE CONFIGURATION IS A REFUSAL, NOT A DEFAULT. A boot
        # service that silently ran at 5 fps because its file said "fivve"
        # would be a machine doing something other than what its own config
        # says — exactly the silence this area exists to remove.
        print(str(exc), file=sys.stderr)
        return 2

    p = argparse.ArgumentParser(
        prog="python -m spectra.capture_client",
        description="Hold a SPECTRA capture session from a machine with a "
                    "camera, and optionally run a declared queue of capture "
                    "runs to the end.",
        epilog=env_help(),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    # EVERY DEFAULT COMES FROM THE ENVIRONMENT WHEN IT DECLARED ONE, so an
    # explicit argument beats the file by construction rather than by a
    # merge somebody has to keep correct. `--url` is required only when
    # nothing declared it, which is what lets the boot service pass no
    # arguments at all.
    # NOT `required=`, EVEN THOUGH RUNNING NEEDS IT. `--doctor` exists for
    # the machine whose configuration is the broken thing, so an argparse
    # error about a missing --url would refuse the one command that could
    # have explained it. A run without an address refuses below, by name.
    p.add_argument("--url", default=env.get("url"),
                   help="SPECTRA's address, e.g. http://spectra:8000/spectra")
    p.add_argument("--device", default=env.get("device", "/dev/video0"))
    p.add_argument("--pose-name", dest="pose_name",
                   default=env.get("pose_name", ""),
                   help="this camera's placement in his own words, e.g. "
                        "'the north shelf'. A LABEL carried in hello so a "
                        "status surface can name WHICH camera is missing — "
                        "never evidence of where the camera actually is, "
                        "which only the pose fingerprint measures")
    p.add_argument("--version", action="version",
                   version=f"spectra-capture-client {CLIENT_VERSION}")
    p.add_argument("--fps", type=float, default=env.get("fps", 5.0),
                   help="frames per second on the wire (the server's own tap "
                        "rate is 5)")
    p.add_argument("--capture-size",
                   default=env.get("capture_size", "1920x1080"),
                   help="what to ask the camera for, before it is scaled to "
                        "whatever wire frame size a run asks for (320x180 "
                        "for a map, up to 1920x1080 for the commissioning "
                        "read). The client steps down to 1280x720 then "
                        "640x480 if the camera will not open here, and says "
                        "so; the wire size is never larger than this, "
                        "because a bigger picture of a smaller image is not "
                        "more detail")
    p.add_argument("--input-format", default=env.get("input_format", ""),
                   help="ffmpeg -input_format, e.g. mjpeg, when the camera "
                        "will not give raw at this size")
    p.add_argument("--host", default=env.get("host") or platform.node(),
                   help="what to call this machine in refusals")
    p.add_argument("--queue", default=env.get("queue", ""),
                   help="a declared queue file; without it the client just "
                        "holds the session")
    p.add_argument("--label", default=env.get("label", ""),
                   help="a name for this queue")
    p.add_argument("--lock-wait", type=float,
                   default=env.get("lock_wait", DEFAULT_LOCK_WAIT_S))
    p.add_argument("--json-out", default=env.get("json_out", ""),
                   help="write the machine-readable outcome here")
    p.add_argument("--synthetic", action="store_true",
                   default=bool(env.get("synthetic", False)),
                   help="a black synthetic camera that reports NO lock — for "
                        "checking the wire reaches SPECTRA, never for a map")
    # THE ONE COMMAND HE RUNS WHEN NOTHING IS WORKING. It checks every
    # branch of the chain — interpreter, venv+pip, the two tools, the
    # device, GROUP MEMBERSHIP and whether the user manager has it, the URL
    # (resolves/connects/answers), the unit and its own last error line, and
    # finally whether SPECTRA can see this machine — and it fixes, starts
    # and gates nothing. See `doctor.py`, which is the binding statement.
    # ── the A/V-SYNC INSTRUMENT ───────────────────────────────────────
    # A SEPARATE MODE, not a flag on the mapping one: it opens a microphone
    # as well as a camera, sends two number streams instead of frames, and
    # talks to a different endpoint. The mapping path above is untouched by
    # every option in this block.
    p.add_argument("--avsync", action="store_true",
                   default=bool(env.get("avsync", False)),
                   help="run the A/V-sync instrument (camera + microphone) "
                        "instead of the mapping session: stream the two "
                        "reduced signals SPECTRA correlates into "
                        "av_offset_ms")
    p.add_argument("--audio-device", dest="audio_device",
                   default=env.get("audio_device", DEFAULT_AUDIO_DEVICE),
                   help="the microphone, BY NAME as ALSA publishes it "
                        f"(default {DEFAULT_AUDIO_DEVICE!r} — the camera's "
                        "own built-in mic, which is the point: it hears "
                        "from where the camera sees) or an explicit ALSA "
                        "device such as plughw:CARD=BRIO,DEV=0. Never a "
                        "card index: those are USB enumeration order")
    p.add_argument("--avsync-fps", dest="avsync_fps", type=float,
                   default=env.get("avsync_fps", DEFAULT_AVSYNC_FPS),
                   help="camera frames per second while measuring (its own "
                        "number, not --fps: the light edge is timed to "
                        "within half a frame)")
    p.add_argument("--measure", action="store_true",
                   help="with --avsync: take a measurement and exit, "
                        "printing the number and its statement as JSON. "
                        "Without it the client just holds the session")
    p.add_argument("--measure-mode", dest="measure_mode", default="pattern",
                   choices=("pattern", "show"),
                   help="pattern flashes every light white on/off at random "
                        "for --measure-seconds and puts the room back "
                        "(tight); show flashes nothing and watches the "
                        "show's own changes (much less certain, and says so)")
    p.add_argument("--measure-seconds", dest="measure_seconds", type=float,
                   default=12.0, help="pattern duration (the page uses 12)")
    p.add_argument("--measure-runs", dest="measure_runs", type=int, default=1,
                   help="how many measurements to take back to back. Two or "
                        "more is worth it: the DIFFERENCE between runs from "
                        "one camera is far tighter than either absolute "
                        "number")
    p.add_argument("--doctor", action="store_true",
                   help="check every link in the chain from this machine to "
                        "SPECTRA, name each verdict, and stop. Writes "
                        "nothing, starts nothing, opens no camera or "
                        "microphone. With --avsync it also checks the "
                        "microphone that measurement needs")
    p.add_argument("--doctor-json", action="store_true",
                   help="the same checks as machine-readable JSON")
    p.add_argument("--doctor-offline", action="store_true",
                   help="--doctor without asking the server anything (for a "
                        "machine with no network)")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    if args.doctor or args.doctor_json or args.doctor_offline:
        # IT RUNS WITHOUT A --url, DELIBERATELY. The doctor's whole job is
        # the case where the configuration is the thing that is wrong, so it
        # must never be the one command that refuses to start because of it
        # — a missing address is a FINDING here, not a usage error.
        return doctor.main(url=args.url or "", device=args.device,
                           host=args.host, venv=_venv_path(),
                           as_json=args.doctor_json,
                           skip_server=args.doctor_offline,
                           # ONLY WHEN THIS MACHINE IS THE A/V-SYNC ONE. A
                           # mapping-only camera host has no microphone and
                           # never needed one; reporting that as a fault
                           # would send someone to fix a machine that is
                           # doing its whole job.
                           audio_device=(args.audio_device if args.avsync
                                         else ""))

    if not args.url:
        print("no SPECTRA address: pass --url, or set SPECTRA_CAPTURE_URL in "
              "the client's environment file. Run --doctor to check every "
              "other link in the chain at the same time.", file=sys.stderr)
        return 2

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s")
    base, ws_url = _urls(args.url)
    try:
        w, _, h = args.capture_size.partition("x")
        size = (int(w), int(h))
    except ValueError:
        print(f"--capture-size must look like 1280x720, not {args.capture_size!r}",
              file=sys.stderr)
        return 2

    if args.avsync:
        # A DIFFERENT INSTRUMENT, and it takes the branch before the
        # mapping camera is even constructed — nothing below this line runs
        # for an A/V-sync run, which is what keeps the mapping path exactly
        # what it was.
        status, outcome = asyncio.run(_run_avsync(args, _avsync_ws(base)))
        print(json.dumps(outcome, indent=2, default=str))
        if args.json_out:
            with open(args.json_out, "w", encoding="utf-8") as fh:
                json.dump({"exit": status, "avsync": outcome}, fh, indent=2,
                          default=str)
        return status

    if args.synthetic:
        # Deliberately reports NOT locked: this switch proves the wire, and a
        # synthetic camera that claimed a lock would be exactly the forgery
        # this client is built not to commit.
        camera = SyntheticCamera(lambda: bytes(320 * 180),
                                 lock=CameraLock(source="synthetic:declared"),
                                 capture_size=size)
    else:
        camera = V4L2Camera(args.device, fps=args.fps, capture_size=size,
                            input_format=args.input_format)

    return asyncio.run(_run(args, base, ws_url, camera))


async def _run(args, base: str, ws_url: str, camera) -> int:
    client = CaptureClient(ws_url, camera, host=args.host, fps=args.fps,
                           pose_name=args.pose_name)
    problem = await client.start_camera()
    if problem:
        logging.error("camera: %s", problem)
    holder = asyncio.create_task(client.run())
    status = 0
    outcome: dict = {}
    try:
        if args.queue:
            status, outcome = await _drive_queue(
                base, args.queue, args.label, args.lock_wait)
            print(json.dumps(outcome, indent=2))
            if args.json_out:
                with open(args.json_out, "w", encoding="utf-8") as fh:
                    json.dump({"exit": status, "client": client.state.as_dict(),
                               "queue": outcome}, fh, indent=2)
        else:
            logging.info("holding the capture session; ctrl-c to stop")
            await holder
    except KeyboardInterrupt:                          # pragma: no cover
        pass
    finally:
        client.stop()
        holder.cancel()
        try:
            await holder
        except (asyncio.CancelledError, Exception):    # noqa: BLE001
            pass
    return status


if __name__ == "__main__":                             # pragma: no cover
    raise SystemExit(main())
