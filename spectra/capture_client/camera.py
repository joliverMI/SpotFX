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

THE SAME RULE NOW COVERS FOUR PINNED CONTROLS (`LEVERS`, 2026-09-01): a
session may declare an exact INTEGRATION TIME (`exposure_time_absolute`, in
100-microsecond units — the same unit the browser's own `exposureTime` uses,
so nothing converts), an exact GAIN (`gain`, a device-specific scale passed
through verbatim), an exact WHITE BALANCE temperature (Kelvin) and an exact
FOCUS (`focus_absolute`). `apply_lock` writes them and `read_lock` reads
EVERY one of them back out of the device; a control this camera does not
have, or one that came back a different number than it was asked for, is
named in `manual_refusals` and the server refuses on it BEFORE any frame is
measured. Asking for none of them is the shipped behaviour exactly —
converge for SETTLE_BEFORE_LOCK_S, then freeze — so nothing about an
ordinary night run changed.

PERSISTENCE IS SOFTWARE, and that is the point. Whatever a session pinned
is remembered in `self._wanted` and RE-ASSERTED by `open()`, so a reboot, a
camera re-plug, a dead capture pipe or a scaler restart costs nothing: the
camera comes back up pinned the way the session pinned it and the read-back
that follows is what says whether it took. Nothing is written to disk and
nothing about the camera's own memory is relied on.

AND A SETTING IS NOT THE LIGHT. Every read-back above proves what the
DRIVER holds, which is not the same claim as the sensor obeying it —
tonight's evidence is a camera that took 10 ms, 60 ms and 200 ms without
complaint and measured flat noise at all three. That second claim needs a
measurement, and it lives one layer up in
`spectra/services/lever_selftest.py`, which drives a known emitter and
watches the light move. Neither check is a substitute for the other: the
read-back is instant and catches a control that was never taken; the
self-test is the only thing that can catch one that was taken and does
nothing.

AND THE WIRE FRAME SIZE IS PER RUN. The commissioning read asks for
1920x1080 (`spectra/services/capture_settings.py` carries the arithmetic);
a map stays at 320x180. `set_frame_size` restarts only the SCALER, and it
re-reads every control afterwards — a V4L2 device reopen can reset controls
to their defaults, so the read-back is what decides whether the pose
survived rather than an assumption that it did. See that method for why a
CHANGED exposure mints a new pose and an unchanged one does not.

THIS CLIENT NEVER UPSCALES. `open()` clamps the wire size to the largest
declared rung the camera's own capture size can fill, and every frame
carries `source_width`/`source_height` so the server can assert the same
thing independently. A bigger picture of a smaller image is not more
detail, and the decode counts camera pixels.

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

#: THE WIRE-FRAME CONTRACT, and it is a LADDER, not a number — mirrored
#: from `spectra/services/capture_settings.PROFILES` rather than imported,
#: because this package is meant to run on a machine that has only the
#: client. The server rejects any size off the ladder rather than resampling
#: a surprise. These two remain the DEFAULT (the map's own size), which is
#: what a client sends until a run asks otherwise.
FRAME_W = 320
FRAME_H = 180
FRAME_SIZES: tuple[tuple[int, int], ...] = (
    (320, 180), (640, 360), (960, 540), (1280, 720), (1920, 1080))
FRAME_BYTES = FRAME_W * FRAME_H
GREY_MIME = "image/grey8"


def choose_frame_size(want: tuple[int, int], source_w: int,
                      source_h: int) -> tuple[int, int]:
    """The largest rung no bigger than what was asked for and no bigger than
    what this camera actually produces — "never upscale", mirroring
    `capture_settings.choose`."""
    if want not in FRAME_SIZES:
        want = (FRAME_W, FRAME_H)
    if source_w <= 0 or source_h <= 0:
        return want
    for w, h in reversed(FRAME_SIZES):
        if w <= want[0] and h <= want[1] and w <= source_w and h <= source_h:
            return (w, h)
    return FRAME_SIZES[0]

#: Let auto-exposure converge on the scene BEFORE freezing it. A lock
#: applied the instant the device opens freezes a half-converged exposure,
#: which is a worse reference than a settled one — the browser page waits
#: for the same reason and roughly as long.
SETTLE_BEFORE_LOCK_S = 1.5

#: The control names, modern first then the legacy UVC spelling. Both are
#: tried and whichever the device actually has is the one reported.
EXPOSURE_CONTROLS = ("auto_exposure", "exposure_auto")
WB_CONTROLS = ("white_balance_automatic", "white_balance_temperature_auto")
#: THE TWO MANUAL LEVERS' controls, modern spelling first. Integration time
#: is in 100-microsecond units, which is V4L2's own unit for it AND the
#: browser's, so nothing anywhere converts. Gain is a device-specific scale
#: and is passed through verbatim; converting it would be an invention.
EXPOSURE_TIME_CONTROLS = ("exposure_time_absolute", "exposure_absolute")
GAIN_CONTROLS = ("gain",)
#: THE OTHER TWO PINNED CONTROLS (2026-09-01). White balance TEMPERATURE is
#: a number in Kelvin the device holds once its own auto white balance is
#: off; FOCUS is `focus_absolute`, a device-specific scale, and it needs the
#: camera's continuous autofocus turned off first or the driver will take
#: the write and then move the lens again.
WB_TEMPERATURE_CONTROLS = ("white_balance_temperature",)
FOCUS_CONTROLS = ("focus_absolute",)
FOCUS_AUTO_CONTROLS = ("focus_automatic_continuous", "focus_auto")
#: V4L2's menu value for manual exposure (1 = Manual Mode, 3 = Aperture
#: Priority Mode) and for white balance auto OFF.
EXPOSURE_MANUAL = 1
WB_AUTO_OFF = 0
#: Continuous autofocus OFF. Written ONLY when a run asks for a focus
#: value — a camera that was left to focus itself keeps doing so, because
#: silently disabling autofocus for every run would change what an ordinary
#: night sees rather than pinning what a calibration asked for.
FOCUS_AUTO_OFF = 0

#: THE FOUR PINNED LEVERS, in the order they are written and read back.
#: One tuple so the client, the read-back and the refusal cannot disagree
#: about what "all four" means — adding a fifth control is one row here.
#: (name, control candidates, words for a refusal, unit words)
LEVERS: tuple[tuple[str, tuple[str, ...], str, str], ...] = (
    ("exposure_time", EXPOSURE_TIME_CONTROLS,
     "a manual integration time", " (x100 us)"),
    ("gain", GAIN_CONTROLS, "a manual gain", ""),
    ("white_balance", WB_TEMPERATURE_CONTROLS,
     "a manual white balance temperature", " K"),
    ("focus", FOCUS_CONTROLS, "a manual focus", ""),
)


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
    #: THE TWO LEVERS, AS THE DEVICE REPORTED THEM BACK — never what was
    #: asked for. `exposure_time` is in 100-microsecond units; `gain` is
    #: this device's own scale. None means the control could not be read,
    #: which is a different answer from zero.
    exposure_time: Optional[float] = None
    gain: Optional[float] = None
    #: THE OTHER TWO PINNED LEVERS, same rule: white balance TEMPERATURE in
    #: Kelvin and FOCUS on the device's own scale, both as the device
    #: reported them back. Read whenever the control exists, whether or not
    #: this run asked for one — reporting is free, and a refusal that can
    #: quote where the lens actually is says more than one that cannot.
    white_balance: Optional[float] = None
    focus: Optional[float] = None
    exposure_time_range: Optional[list] = None
    gain_range: Optional[list] = None
    white_balance_range: Optional[list] = None
    focus_range: Optional[list] = None
    #: Whether the camera's own continuous autofocus reads OFF right now.
    #: None means this camera has no such control to read.
    focus_auto: Optional[bool] = None
    #: A lever a run asked for that this camera does not have, or gave back
    #: a different number for. The server refuses on these; this module
    #: only ever reports what it read.
    manual_refusals: list[str] = field(default_factory=list)

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
                "source": self.source, "camera_error": self.camera_error,
                "exposure_time": self.exposure_time, "gain": self.gain,
                "white_balance": self.white_balance, "focus": self.focus,
                "focus_auto": self.focus_auto,
                "exposure_time_range": (list(self.exposure_time_range)
                                        if self.exposure_time_range else None),
                "gain_range": (list(self.gain_range) if self.gain_range
                               else None),
                "white_balance_range": (list(self.white_balance_range)
                                        if self.white_balance_range else None),
                "focus_range": (list(self.focus_range) if self.focus_range
                                else None),
                "manual_refusals": list(self.manual_refusals)}


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
        #: The wire size this camera sends, and the camera image it is
        #: derived from. Both go on every frame so the server can assert
        #: "never upscale" independently of the client that promised it.
        self.frame_size: tuple[int, int] = (FRAME_W, FRAME_H)
        self.capture_size: tuple[int, int] = (FRAME_W, FRAME_H)

    @property
    def frame_bytes(self) -> int:
        return self.frame_size[0] * self.frame_size[1]

    async def set_frame_size(self, size: tuple[int, int]) -> tuple[int, int]:
        """Adopt this wire size, clamped to what this camera can fill.
        Returns what was actually adopted — a camera that cannot reach the
        request downgrades honestly and the server reads the frames it gets
        rather than the ones it asked for."""
        self.frame_size = choose_frame_size(tuple(size), *self.capture_size)
        return self.frame_size

    def _mint_pose(self) -> None:
        # Inside open(), always: see the module docstring on why this
        # placement is what makes a reconnect's pose assertion honest.
        self.pose_token = uuid.uuid4().hex[:8]

    def describe(self) -> dict:
        return {}

    async def open(self) -> None:                      # pragma: no cover
        raise NotImplementedError

    async def apply_lock(self, **levers) -> CameraLock:  # pragma: no cover
        """Pin the camera. `levers` are the four of `LEVERS` by name; any
        omitted one is left alone, which is converge-then-freeze exactly."""
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


def _as_float(value) -> Optional[float]:
    """A read-back number, or None. None and 0 are different answers: "this
    camera would not tell us" is not "it is zero"."""
    try:
        return None if value is None else float(str(value).strip())
    except (TypeError, ValueError):
        return None


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
                 capture_size: tuple[int, int] = (1920, 1080),
                 input_format: str = "",
                 fallback_sizes: tuple[tuple[int, int], ...] =
                 ((1280, 720), (640, 480))) -> None:
        super().__init__()
        self.device = device
        self.fps = fps
        self.capture_size = capture_size
        #: Sizes to try, in order, when the camera will not open at
        #: `capture_size`. The default asks for 1080p — what the
        #: commissioning read wants — and falls back rather than leaving an
        #: unattended run dead at three in the morning over a camera that
        #: tops out at 720p. Every fallback is SAID (`open_note`).
        self.fallback_sizes = tuple(fallback_sizes)
        self.open_note = ""
        self.input_format = input_format
        #: The wire size this camera is currently sending, and the largest
        #: rung it could ever send (clamped to what it actually captures).
        self.frame_size: tuple[int, int] = (FRAME_W, FRAME_H)
        self._proc: Optional[subprocess.Popen] = None
        self._reader: Optional[asyncio.StreamReader] = None
        #: Levers a run asked for that this device would not take, carried
        #: from `apply_lock` into every subsequent `read_lock` so a paced
        #: re-read does not silently drop the refusal.
        self._manual_refusals: list[str] = []
        #: THE PINNED REGIME, and it is the whole of "persistence is
        #: software". Every lever a session ever asked for is remembered
        #: here and RE-ASSERTED by `open()` — so a reboot, a re-plug, a dead
        #: capture pipe or a scaler restart costs nothing: the camera comes
        #: back up pinned the way the session pinned it, and the read-back
        #: that follows is what says whether it took.
        self._wanted: dict = {name: None for name, *_ in LEVERS}

    @property
    def frame_bytes(self) -> int:
        return self.frame_size[0] * self.frame_size[1]

    def describe(self) -> dict:
        return {"kind": "v4l2", "device": self.device,
                "capture_size": list(self.capture_size), "fps": self.fps,
                "frame_size": list(self.frame_size),
                "max_frame_size": list(choose_frame_size(
                    FRAME_SIZES[-1], *self.capture_size)),
                "open_note": self.open_note}

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

    @staticmethod
    def _range(raw: str) -> Optional[list]:
        """min/max out of a `--list-ctrls-menus` line, when the driver
        prints them. Reported so a refusal can quote what this camera
        offers rather than only what it would not take."""
        lo = hi = None
        for token in (raw or "").split():
            if token.startswith("min="):
                lo = token[4:]
            elif token.startswith("max="):
                hi = token[4:]
        try:
            return None if lo is None or hi is None else [float(lo), float(hi)]
        except ValueError:
            return None

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
        # ALL FOUR PINNED LEVERS, READ THE SAME WAY: out of the device,
        # never out of a memory of what was asked for. Read whether or not
        # this run asked for one — reporting is free, and a refusal that can
        # quote where the lens actually is says more than one that cannot.
        found = {name: next((c for c in names if c in controls), "")
                 for name, names, _w, _u in LEVERS}
        read = {name: (_as_float(self._get(ctlname)) if ctlname else None)
                for name, ctlname in found.items()}
        ranges = {name: (self._range(controls.get(ctlname, {}).get("raw", ""))
                         if ctlname else None)
                  for name, ctlname in found.items()}
        focus_auto_name = next((c for c in FOCUS_AUTO_CONTROLS if c in controls), "")
        focus_auto_val = self._get(focus_auto_name) if focus_auto_name else None
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
            exposure_time=read["exposure_time"], gain=read["gain"],
            white_balance=read["white_balance"], focus=read["focus"],
            focus_auto=(None if focus_auto_val is None
                        else focus_auto_val.strip() != str(FOCUS_AUTO_OFF)),
            exposure_time_range=ranges["exposure_time"],
            gain_range=ranges["gain"],
            white_balance_range=ranges["white_balance"],
            focus_range=ranges["focus"],
            manual_refusals=list(self._manual_refusals),
            source=f"v4l2:{exp_name or 'no-exposure-control'}/"
                   f"{wb_name or 'no-white-balance-control'}")
        return self.lock

    async def apply_lock(self, **levers) -> CameraLock:
        """Ask for manual exposure and manual white balance — and, for every
        lever this run named, that exact value — then READ EVERY CONTROL
        BACK OUT OF THE DEVICE.

        THE FOUR LEVERS (`LEVERS`): integration time, gain, white balance
        temperature, focus. Every one of them is written and every one of
        them is read back; a control this camera does not have, or one that
        came back a different number than it was asked for, lands in
        `manual_refusals` and the server refuses on it BEFORE any frame is
        measured. A failed write is not reported on its own — the read-back
        that follows is the only statement this makes, because a returning
        write call is never evidence.

        WHAT IS ASKED FOR IS REMEMBERED (`self._wanted`), so `open()` can
        re-assert it after a reopen: a camera that comes back from a re-plug
        or a scaler restart at its factory defaults would otherwise measure
        a different regime under the same session, silently.

        ORDER MATTERS TWICE: `exposure_time_absolute` is ignored by most UVC
        drivers while auto exposure is still on, and `focus_absolute` is
        overridden moments later by a camera still focusing itself. So
        manual exposure mode and manual white balance are set first, the
        camera's continuous autofocus is turned off ONLY when a focus value
        was asked for, and the values are written after that."""
        wanted = dict(self._wanted)
        wanted.update({k: v for k, v in levers.items() if k in wanted})
        self._wanted = wanted
        controls = self._controls()
        refusals: list[str] = []
        for name in EXPOSURE_CONTROLS:
            if name in controls:
                self._set(name, EXPOSURE_MANUAL)
                break
        for name in WB_CONTROLS:
            if name in controls:
                self._set(name, WB_AUTO_OFF)
                break
        if wanted.get("focus") is not None:
            # ONLY when a focus was asked for: see FOCUS_AUTO_OFF. A camera
            # with no autofocus control to turn off is not a refusal — the
            # focus write's own read-back is what decides.
            for name in FOCUS_AUTO_CONTROLS:
                if name in controls:
                    self._set(name, FOCUS_AUTO_OFF)
                    break
        for lever, names, what, unit in LEVERS:
            want = wanted.get(lever)
            if want is None:
                continue
            name = next((c for c in names if c in controls), "")
            if not name:
                refusals.append(
                    f"this camera has no {' or '.join(names)} control, so "
                    f"{what} cannot be set on it")
                continue
            if not self._set(name, int(want)):
                refusals.append(f"the driver refused {name}={int(want)}{unit}")
        self._manual_refusals = refusals
        lock = await self.read_lock()
        # THE READ-BACK IS WHAT DECIDES. A control that took a different
        # value than it was asked for is refusing just as much as one that
        # is absent — and more dangerously, because the frames still arrive
        # and only the numbers are wrong.
        extra: list[str] = []
        for lever, _names, what, unit in LEVERS:
            want = wanted.get(lever)
            got = getattr(lock, lever)
            if want is None or got is None:
                continue
            if abs(got - want) > 1e-6:
                extra.append(f"asked for {what} of {want}{unit} and the "
                             f"device reports {got:g}")
        if extra:
            self._manual_refusals = refusals + extra
            lock.manual_refusals = list(self._manual_refusals)
        return lock

    # ── pixels ────────────────────────────────────────────────────────────
    def _ffmpeg_args(self, ffmpeg: str,
                     capture_size: Optional[tuple[int, int]] = None
                     ) -> list[str]:
        cap = capture_size or self.capture_size
        args = [ffmpeg, "-hide_banner", "-loglevel", "error",
                "-f", "v4l2", "-framerate", str(self.fps)]
        if self.input_format:
            args += ["-input_format", self.input_format]
        args += ["-video_size", f"{cap[0]}x{cap[1]}",
                 "-i", self.device,
                 # scale to the wire's own CURRENT size, then ONE luminance
                 # byte per pixel — the exact bytes the protocol carries,
                 # with no lossy stage anywhere in the path. The size is
                 # never larger than `capture_size` (see
                 # `choose_frame_size`), so this only ever downsamples.
                 "-vf", f"scale={self.frame_size[0]}:{self.frame_size[1]}",
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
        # A CAMERA THAT WILL NOT OPEN AT 1080p IS NOT A DEAD NIGHT. The
        # default asks for what the commissioning read wants and steps down
        # rather than leaving an unattended run with no camera at all; every
        # step is SAID (`open_note` -> the client's `hello`), never silent.
        problems: list[str] = []
        wanted = self.capture_size
        ladder = [wanted] + [s for s in self.fallback_sizes if s != wanted]
        for size in ladder:
            problem = await self._open_at(ffmpeg, size)
            if problem is None:
                if size != wanted:
                    self.open_note = (
                        f"this camera would not open at "
                        f"{wanted[0]}x{wanted[1]} "
                        f"({problems[0]}); it is running at "
                        f"{size[0]}x{size[1]}, so the largest frame it can "
                        f"send is "
                        f"{choose_frame_size(FRAME_SIZES[-1], *size)[0]}x"
                        f"{choose_frame_size(FRAME_SIZES[-1], *size)[1]}")
                    self.capture_size = size
                break
            problems.append(problem)
        else:
            raise CameraUnavailable("; ".join(problems))
        self._mint_pose()
        self.opened = True
        # Settle, THEN lock, THEN read back — see SETTLE_BEFORE_LOCK_S.
        await asyncio.sleep(SETTLE_BEFORE_LOCK_S)
        # RE-ASSERT WHATEVER THIS CAMERA WAS PINNED TO. On a first open
        # nothing is pinned and this is exactly converge-then-freeze; after
        # a re-plug, a reboot or a dead capture pipe it is what makes the
        # pinned regime survive with no stored state anywhere but here.
        await self.apply_lock(**self._wanted)

    async def _open_at(self, ffmpeg: str,
                       capture_size: tuple[int, int]) -> Optional[str]:
        """Start the pixel pipe at this capture size. Returns ffmpeg's own
        complaint, or None when frames arrived.

        The WIRE size is derived here, never asked for: the largest declared
        rung this capture size can fill, capped at whatever was last
        requested. That is "never upscale", enforced at the only place that
        knows both numbers."""
        self.frame_size = choose_frame_size(self.frame_size, *capture_size)
        want = self.frame_bytes
        self._proc = subprocess.Popen(
            self._ffmpeg_args(ffmpeg, capture_size), stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, bufsize=0)
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader(limit=want * 8)
        await loop.connect_read_pipe(
            lambda: asyncio.StreamReaderProtocol(reader), self._proc.stdout)
        self._reader = reader
        try:
            await asyncio.wait_for(reader.readexactly(want), timeout=15.0)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError) as exc:
            # STOP IT FIRST, then read its complaint: ffmpeg's stderr is a
            # blocking pipe, so reading it while the process is still alive
            # is a hang, not a diagnostic.
            err = self._drain_stderr()
            await self.close()
            return (f"{self.device} produced no frames at "
                    f"{capture_size[0]}x{capture_size[1]}"
                    + (f" ({err})" if err else f" ({exc!r})"))
        return None

    async def set_frame_size(self, size: tuple[int, int]) -> tuple[int, int]:
        """Send at this wire size from now on — clamped to what this camera
        actually captures, so it can only ever go DOWN from the source.
        Returns the size actually adopted.

        IT RESTARTS THE SCALER, WHICH REOPENS THE DEVICE, AND THAT IS WHY
        THE POSE IS RE-DECIDED HERE RATHER THAN ASSUMED. A pose is "this
        camera, where it stands, at the exposure it locked", and a scaler
        restart moves nothing and re-frames nothing — but a V4L2 reopen CAN
        reset controls to their defaults, and a re-converged auto exposure
        would be a genuinely different byte scale wearing the same pose id.
        So every control is re-applied and RE-READ, and the read-back
        decides: an exposure that came back where it was keeps the pose, one
        that did not mints a new one and the queue names the change
        (`mapping_refusals.pose_changed_note`). Measured, never assumed —
        which is the same rule the lock itself lives by."""
        want = choose_frame_size(tuple(size), *self.capture_size)
        if want == self.frame_size:
            return self.frame_size
        before = (self.lock.exposure_mode, self.lock.exposure_time,
                  self.lock.gain, self.lock.white_balance_mode,
                  self.lock.white_balance, self.lock.focus)
        ffmpeg = _tool("ffmpeg")
        if not ffmpeg:
            return self.frame_size
        await self.close()
        self.frame_size = want
        problem = await self._open_at(ffmpeg, self.capture_size)
        if problem is not None:
            raise CameraUnavailable(problem)
        self.opened = True
        await self.apply_lock(**self._wanted)
        after = (self.lock.exposure_mode, self.lock.exposure_time,
                 self.lock.gain, self.lock.white_balance_mode,
                 self.lock.white_balance, self.lock.focus)
        if after != before:
            self._mint_pose()
        return self.frame_size

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
                self._reader.readexactly(self.frame_bytes), timeout=10.0)
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
                 fail: str = "",
                 capture_size: tuple[int, int] = (FRAME_W, FRAME_H)) -> None:
        super().__init__()
        self._render = render
        self._declared = lock or CameraLock(source="synthetic:declared")
        self.fps = fps
        self.fail = fail
        #: What the last `apply_lock` was asked for. Declared here rather
        #: than grown lazily so a render function can read it on the very
        #: first frame.
        self.applied: dict = {}
        self.applies = 0
        # A SYNTHETIC CAMERA DECLARES WHAT IT CAN CAPTURE, like a real one,
        # and the default is the wire's own smallest rung because that is
        # what a fixed-size render function actually produces. Declaring
        # more would make `set_frame_size` hand the run a size this camera
        # cannot fill, and `frame()` would raise rather than the negotiation
        # coming down honestly — the same lie about resolution the whole
        # "never upscale" rule exists to stop, wearing a test double.
        self.capture_size = capture_size

    def describe(self) -> dict:
        return {"kind": "synthetic", "fps": self.fps,
                "capture_size": list(self.capture_size),
                "frame_size": list(self.frame_size)}

    async def open(self) -> None:
        if self.fail:
            raise CameraUnavailable(self.fail)
        self._mint_pose()
        self.opened = True
        self.lock = self._declared

    async def apply_lock(self, **levers) -> CameraLock:
        # It reports WHAT WAS DECLARED, never what was asked for — the same
        # refusal to forge a read-back the real camera lives by. A spec that
        # wants a lever to be taken declares a lock carrying it.
        self.applied.update({k: v for k, v in levers.items() if v is not None})
        self.applies += 1
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
        if len(data) != self.frame_bytes:
            raise ValueError(f"synthetic camera produced {len(data)} bytes, "
                             f"not {self.frame_bytes}")
        return data

    async def close(self) -> None:
        self.opened = False
