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

EXIT CODES, because the caller is a cron line or a systemd unit and not a
person reading prose:

    0  every declared item completed
    1  the queue ran and something did not complete (partial, refused,
       not run) — the JSON says which item and why, in a sentence
    2  nothing ran: no camera, no session, a bad queue file, or SPECTRA
       unreachable

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
    p.add_argument("--doctor", action="store_true",
                   help="check every link in the chain from this machine to "
                        "SPECTRA, name each verdict, and stop. Writes "
                        "nothing, starts nothing, opens no camera")
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
                           skip_server=args.doctor_offline)

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
