"""THE COMMAND LINE — one line to start, and a machine-readable answer when
it finishes.

    # hold a session so someone else can press things
    python -m spectra.capture_client --url http://spectra:8000/spectra

    # the whole night, unattended
    python -m spectra.capture_client --url http://spectra:8000/spectra \\
        --queue overnight.json --json-out /tmp/last-capture.json

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

from spectra.capture_client.camera import (CameraLock, SyntheticCamera,
                                           V4L2Camera)
from spectra.capture_client.session import CaptureClient

#: How long to wait for the SERVER to report the session present and locked
#: before giving up on a queue. Generous: a camera has to settle before it
#: can honestly report anything.
DEFAULT_LOCK_WAIT_S = 90.0
POLL_S = 1.0


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
    p = argparse.ArgumentParser(
        prog="python -m spectra.capture_client",
        description="Hold a SPECTRA capture session from a machine with a "
                    "camera, and optionally run a declared queue of capture "
                    "runs to the end.")
    p.add_argument("--url", required=True,
                   help="SPECTRA's address, e.g. http://spectra:8000/spectra")
    p.add_argument("--device", default="/dev/video0")
    p.add_argument("--fps", type=float, default=5.0,
                   help="frames per second on the wire (the server's own tap "
                        "rate is 5)")
    p.add_argument("--capture-size", default="1920x1080",
                   help="what to ask the camera for, before it is scaled to "
                        "whatever wire frame size a run asks for (320x180 "
                        "for a map, up to 1920x1080 for the commissioning "
                        "read). The client steps down to 1280x720 then "
                        "640x480 if the camera will not open here, and says "
                        "so; the wire size is never larger than this, "
                        "because a bigger picture of a smaller image is not "
                        "more detail")
    p.add_argument("--input-format", default="",
                   help="ffmpeg -input_format, e.g. mjpeg, when the camera "
                        "will not give raw at this size")
    p.add_argument("--host", default=platform.node(),
                   help="what to call this machine in refusals")
    p.add_argument("--queue", default="",
                   help="a declared queue file; without it the client just "
                        "holds the session")
    p.add_argument("--label", default="", help="a name for this queue")
    p.add_argument("--lock-wait", type=float, default=DEFAULT_LOCK_WAIT_S)
    p.add_argument("--json-out", default="",
                   help="write the machine-readable outcome here")
    p.add_argument("--synthetic", action="store_true",
                   help="a black synthetic camera that reports NO lock — for "
                        "checking the wire reaches SPECTRA, never for a map")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

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
    client = CaptureClient(ws_url, camera, host=args.host, fps=args.fps)
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
