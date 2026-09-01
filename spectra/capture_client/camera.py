"""THE CAPTURE MACHINE'S CAMERA — and the one thing it is never allowed to
do, which is claim a lock it did not read back.

THE RULE, unchanged from the browser page it stands beside: a footprint is
`lit - dark` in the camera's own byte scale, so if auto-exposure re-scales
between the dark reference and the lit capture, every comparison in the map
is wrong by an unknown factor and NOTHING downstream can detect it. The
server therefore refuses a run unless the client reports both exposure and
white balance actually locked. `spectra/web/src/rooms/mappingCapture.ts`
gets that report from `getSettings()` — what the BROWSER did, never the
constraint it asked for. This module is the same discipline one layer down:

    ASK the driver (V4L2_CID_EXPOSURE_AUTO / white balance auto),
    then READ THE CONTROL BACK OUT OF THE DEVICE,
    and report what came back — including when it came back "auto".

Automating the lock REQUEST is the whole point of an unattended client.
Automating the lock CONFIRMATION would be forging the instrument's
signature, and there is no code path here that can: `read_lock()` only ever
returns what `v4l2-ctl --get-ctrl` printed, `apply_lock()` calls it rather
than assuming its own write worked, and a camera whose controls cannot be
read reports `exposure_locked=False` with the reason attached — which the
server then refuses BY NAME, exactly as it refuses a phone that will not
lock. The unattended path is allowed to be more convenient. It is not
allowed to be more trusting.

WHY A NATIVE CLIENT AND NOT HEADLESS CHROME. Chrome's `exposureMode`
capability is not reliably present for a plain UVC webcam on desktop Linux,
so a headless-browser client would very often report "this camera will not
lock" and refuse — honestly, and uselessly. `v4l2-ctl` sets and reads the
same underlying control the camera actually has. The browser page is
untouched and remains the phone's way in.

TWO EXTERNAL TOOLS, both checked for by name and both refused by name when
missing: `ffmpeg` (opens the device and hands back raw greyscale at the
size the wire wants) and `v4l2-ctl` (the controls). Neither is imported as
a library: a lossy decoder in this path would land in the difference the
instrument measures, and `ffmpeg -pix_fmt gray` hands over exactly the
bytes the protocol already speaks.

THE POSE TOKEN IS GENERATED HERE, INSIDE `open()`, and that placement is
load-bearing. A pose is "this camera, where it stands, at the exposure it
locked"; a reconnecting client may assert its pose to the server so a
dropped WebSocket does not silently split one map into two measurements
(`mapping_session._adopt_pose`). That assertion is only honest while the
camera was never reopened — and because the token is minted by the open, it
structurally cannot survive one.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional

logger = logging.getLogger(__name__)

#: THE WIRE-FRAME CONTRACT. Not this module's to change: the server rejects
#: any other size rather than resampling a surprise, and the commissioning
#: instrument's whole resolution arithmetic is stated against it.
FRAME_W = 320
FRAME_H = 180
FRAME_BYTES = FRAME_W * FRAME_H
GREY_MIME = "image/grey8"

#: Let auto-exposure converge on the scene BEFORE freezing it. A lock
#: applied the instant the device opens freezes a half-converged exposure,
#: which is a worse reference than a settled one — the browser page waits
#: for the same reason and roughly as long.
SETTLE_BEFORE_LOCK_S = 1.5

#: The control names, modern first then the legacy UVC spelling. Both are
#: tried and whichever the device actually has is the one reported.
EXPOSURE_CONTROLS = ("auto_exposure", "exposure_auto")
WB_CONTROLS = ("white_balance_automatic", "white_balance_temperature_auto")
#: V4L2's menu value for manual exposure (1 = Manual Mode, 3 = Aperture
#: Priority Mode) and for white balance auto OFF.
EXPOSURE_MANUAL = 1
WB_AUTO_OFF = 0


@dataclass
class CameraLock:
    """What the DEVICE said, in the shape the wire already speaks."""
    exposure_locked: bool = False
    white_balance_locked: bool = False
    exposure_mode: str = ""
    white_balance_mode: str = ""
    exposure_capabilities: list[str] = field(default_factory=list)
    white_balance_capabilities: list[str] = field(default_factory=list)
    #: Whose read-back these booleans came from. Reported so a reader can
    #: tell a browser's `getSettings()` from a driver's control; it never
    #: changes how much they are trusted.
    source: str = ""
    #: Set only when there is no camera to lock AT ALL — a different
    #: condition from "opened it and it will not lock", and the one an
    #: unattended machine hits first.
    camera_error: str = ""

    @property
    def locked(self) -> bool:
        return (self.exposure_locked and self.white_balance_locked
                and not self.camera_error)

    def as_wire(self) -> dict:
        return {"exposure_locked": self.exposure_locked,
                "white_balance_locked": self.white_balance_locked,
                "exposure_mode": self.exposure_mode,
                "white_balance_mode": self.white_balance_mode,
                "exposure_capabilities": list(self.exposure_capabilities),
                "white_balance_capabilities": list(self.white_balance_capabilities),
                "source": self.source, "camera_error": self.camera_error}


class CameraUnavailable(Exception):
    """No camera to open — carried to the server as `camera_error` rather
    than killing the client, so a laptop with an unplugged webcam SAYS so on
    the surface a human reads instead of dying quietly."""


class BaseCamera:
    """Everything a camera must be, and the pose token every one of them
    mints at open."""

    def __init__(self) -> None:
        self.pose_token = ""
        self.opened = False
        self.lock = CameraLock()

    def _mint_pose(self) -> None:
        # Inside open(), always: see the module docstring on why this
        # placement is what makes a reconnect's pose assertion honest.
        self.pose_token = uuid.uuid4().hex[:8]

    def describe(self) -> dict:
        return {}

    async def open(self) -> None:                      # pragma: no cover
        raise NotImplementedError

    async def apply_lock(self) -> CameraLock:          # pragma: no cover
        raise NotImplementedError

    async def read_lock(self) -> CameraLock:           # pragma: no cover
        raise NotImplementedError

    async def frame(self) -> Optional[bytes]:          # pragma: no cover
        raise NotImplementedError

    async def close(self) -> None:                     # pragma: no cover
        raise NotImplementedError


# ── the real one ───────────────────────────────────────────────────────────

def _tool(name: str) -> Optional[str]:
    return shutil.which(name)


def _run(args: list[str], timeout: float = 5.0) -> tuple[int, str]:
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)


class V4L2Camera(BaseCamera):
    """A UVC webcam on the capture machine: `ffmpeg` for pixels, `v4l2-ctl`
    for the controls, and no image library anywhere in between."""

    def __init__(self, device: str = "/dev/video0", *, fps: float = 5.0,
                 capture_size: tuple[int, int] = (1280, 720),
                 input_format: str = "") -> None:
        super().__init__()
        self.device = device
        self.fps = fps
        self.capture_size = capture_size
        self.input_format = input_format
        self._proc: Optional[subprocess.Popen] = None
        self._reader: Optional[asyncio.StreamReader] = None

    def describe(self) -> dict:
        return {"kind": "v4l2", "device": self.device,
                "capture_size": list(self.capture_size), "fps": self.fps}

    # ── controls ──────────────────────────────────────────────────────────
    def _controls(self) -> dict[str, dict]:
        """Every control this device declares, with its menu options. Parsed
        from `v4l2-ctl --list-ctrls-menus`, which is the device's own answer
        — never a table of what webcams usually have."""
        ctl = _tool("v4l2-ctl")
        if not ctl:
            return {}
        code, out = _run([ctl, "-d", self.device, "--list-ctrls-menus"])
        if code != 0:
            return {}
        found: dict[str, dict] = {}
        name = ""
        for line in out.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if line.startswith((" " * 4, "\t")) and ":" in stripped and stripped[0].isdigit():
                # a menu row: "                1: Manual Mode"
                if name:
                    idx, _, text = stripped.partition(":")
                    found[name]["menu"][idx.strip()] = text.strip()
                continue
            token = stripped.split()[0]
            if "(" in stripped and token:
                name = token
                found[name] = {"menu": {}, "raw": stripped}
        return found

    def _get(self, control: str) -> Optional[str]:
        ctl = _tool("v4l2-ctl")
        if not ctl:
            return None
        code, out = _run([ctl, "-d", self.device, f"--get-ctrl={control}"])
        if code != 0 or ":" not in out:
            return None
        return out.split(":", 1)[1].strip().splitlines()[0].strip()

    def _set(self, control: str, value: int) -> bool:
        ctl = _tool("v4l2-ctl")
        if not ctl:
            return False
        code, _ = _run([ctl, "-d", self.device, f"--set-ctrl={control}={value}"])
        return code == 0

    async def read_lock(self) -> CameraLock:
        """READ THE DEVICE. Never a memory of what was asked for."""
        ctl = _tool("v4l2-ctl")
        if not ctl:
            self.lock = CameraLock(
                exposure_mode="unreadable", white_balance_mode="unreadable",
                exposure_capabilities=["v4l2-ctl is not installed"],
                white_balance_capabilities=["v4l2-ctl is not installed"],
                source="v4l2:unavailable")
            return self.lock
        controls = self._controls()
        exp_name = next((c for c in EXPOSURE_CONTROLS if c in controls), "")
        wb_name = next((c for c in WB_CONTROLS if c in controls), "")
        exp_val = self._get(exp_name) if exp_name else None
        wb_val = self._get(wb_name) if wb_name else None
        exp_menu = controls.get(exp_name, {}).get("menu", {})
        self.lock = CameraLock(
            exposure_locked=exp_val is not None and exp_val.strip() == str(EXPOSURE_MANUAL),
            white_balance_locked=wb_val is not None and wb_val.strip() == str(WB_AUTO_OFF),
            exposure_mode=(exp_menu.get(str(exp_val), str(exp_val))
                           if exp_val is not None else "unknown"),
            white_balance_mode=("manual" if (wb_val or "").strip() == str(WB_AUTO_OFF)
                                else ("auto" if wb_val is not None else "unknown")),
            exposure_capabilities=(sorted(exp_menu.values()) if exp_menu
                                   else ([exp_name] if exp_name else [])),
            white_balance_capabilities=([wb_name] if wb_name else []),
            source=f"v4l2:{exp_name or 'no-exposure-control'}/"
                   f"{wb_name or 'no-white-balance-control'}")
        return self.lock

    async def apply_lock(self) -> CameraLock:
        """Ask for manual exposure and manual white balance, then read back.
        A failed write is not reported as anything: the read-back that
        follows is the only statement this makes."""
        controls = self._controls()
        for name in EXPOSURE_CONTROLS:
            if name in controls:
                self._set(name, EXPOSURE_MANUAL)
                break
        for name in WB_CONTROLS:
            if name in controls:
                self._set(name, WB_AUTO_OFF)
                break
        return await self.read_lock()

    # ── pixels ────────────────────────────────────────────────────────────
    def _ffmpeg_args(self, ffmpeg: str) -> list[str]:
        args = [ffmpeg, "-hide_banner", "-loglevel", "error",
                "-f", "v4l2", "-framerate", str(self.fps)]
        if self.input_format:
            args += ["-input_format", self.input_format]
        args += ["-video_size", f"{self.capture_size[0]}x{self.capture_size[1]}",
                 "-i", self.device,
                 # scale to the wire's own size, then ONE luminance byte per
                 # pixel — the exact bytes the protocol carries, with no
                 # lossy stage anywhere in the path.
                 "-vf", f"scale={FRAME_W}:{FRAME_H}",
                 "-pix_fmt", "gray", "-f", "rawvideo", "-"]
        return args

    async def open(self) -> None:
        ffmpeg = _tool("ffmpeg")
        if not ffmpeg:
            raise CameraUnavailable(
                "ffmpeg is not installed on this machine, and the capture "
                "client reads the camera through it (apt install ffmpeg)")
        if not os.path.exists(self.device):
            raise CameraUnavailable(f"{self.device} does not exist")
        if not os.access(self.device, os.R_OK):
            raise CameraUnavailable(
                f"{self.device} is not readable by this user — add the user "
                f"to the 'video' group and log in again")
        self._proc = subprocess.Popen(
            self._ffmpeg_args(ffmpeg), stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, bufsize=0)
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader(limit=FRAME_BYTES * 8)
        await loop.connect_read_pipe(
            lambda: asyncio.StreamReaderProtocol(reader), self._proc.stdout)
        self._reader = reader
        try:
            await asyncio.wait_for(reader.readexactly(FRAME_BYTES), timeout=15.0)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError) as exc:
            # STOP IT FIRST, then read its complaint: ffmpeg's stderr is a
            # blocking pipe, so reading it while the process is still alive
            # is a hang, not a diagnostic.
            err = self._drain_stderr()
            await self.close()
            raise CameraUnavailable(
                f"{self.device} produced no frames"
                + (f" ({err})" if err else f" ({exc!r})")) from exc
        self._mint_pose()
        self.opened = True
        # Settle, THEN lock, THEN read back — see SETTLE_BEFORE_LOCK_S.
        await asyncio.sleep(SETTLE_BEFORE_LOCK_S)
        await self.apply_lock()

    def _drain_stderr(self) -> str:
        """ffmpeg's own words about why it could not open the device — the
        useful half of "no frames". Terminates first: see the caller."""
        proc = self._proc
        if proc is None:
            return ""
        try:
            proc.terminate()
            _out, err = proc.communicate(timeout=2.0)
        except (OSError, subprocess.SubprocessError):
            return ""
        return (err or b"").decode(errors="replace").strip()[-400:]

    async def frame(self) -> Optional[bytes]:
        if self._reader is None:
            return None
        try:
            return await asyncio.wait_for(
                self._reader.readexactly(FRAME_BYTES), timeout=10.0)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError):
            return None

    async def close(self) -> None:
        self.opened = False
        proc, self._proc = self._proc, None
        self._reader = None
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except (OSError, subprocess.SubprocessError):
                try:
                    proc.kill()
                except OSError:
                    pass


# ── the one used by every proof ────────────────────────────────────────────

class SyntheticCamera(BaseCamera):
    """A camera made of a function. Used by the executable specs, which must
    prove the whole unattended path without a webcam, a room or a light.

    ITS LOCK STATE IS DECLARED BY THE CALLER and is not a shortcut past the
    gate: a proof that could only ever declare "locked" would be unable to
    show the refusal, so the specs declare an UNLOCKED one too and watch the
    run refuse. What this class must never grow is a default that reports
    locked when the caller said nothing."""

    def __init__(self, render: Callable[[], bytes], *,
                 lock: Optional[CameraLock] = None, fps: float = 20.0,
                 fail: str = "") -> None:
        super().__init__()
        self._render = render
        self._declared = lock or CameraLock(source="synthetic:declared")
        self.fps = fps
        self.fail = fail

    def describe(self) -> dict:
        return {"kind": "synthetic", "fps": self.fps}

    async def open(self) -> None:
        if self.fail:
            raise CameraUnavailable(self.fail)
        self._mint_pose()
        self.opened = True
        self.lock = self._declared

    async def apply_lock(self) -> CameraLock:
        self.lock = self._declared
        return self.lock

    async def read_lock(self) -> CameraLock:
        self.lock = self._declared
        return self.lock

    def declare(self, lock: CameraLock) -> None:
        """Change what this camera reports — how a spec makes a lock be LOST
        mid-run without touching the server's gate."""
        self._declared = lock
        self.lock = lock

    async def frame(self) -> Optional[bytes]:
        await asyncio.sleep(1.0 / max(0.5, self.fps))
        data = self._render()
        if len(data) != FRAME_BYTES:
            raise ValueError(f"synthetic camera produced {len(data)} bytes, "
                             f"not {FRAME_BYTES}")
        return data

    async def close(self) -> None:
        self.opened = False
