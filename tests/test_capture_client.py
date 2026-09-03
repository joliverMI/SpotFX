"""THE UNATTENDED CAPTURE CLIENT — and the one property it must never lose.

THE PROPERTY: automating the lock REQUEST is the whole point of this client;
automating the lock CONFIRMATION would forge the instrument's signature.
Every test in section 1 exists to make that structural rather than
well-intentioned — a camera whose driver says "auto" reports NOT LOCKED, a
camera whose controls cannot be read reports NOT LOCKED and says why, and
nothing anywhere in this package can produce a `True` the device did not
print.

The rest is what an unattended client has to survive: a machine with no
camera (it CONNECTS and says so, rather than dying quietly on a laptop
nobody is looking at) and a dropped socket (it comes back, and it keeps its
pose, because the camera never closed).

Everything here is hermetic: a fake `v4l2-ctl`, a synthetic camera, and a
local WebSocket server. `scripts/check_capture_queue_e2e.py` proves the same
client against the real SPECTRA app.
"""
from __future__ import annotations

import asyncio
import json

import pytest
import websockets

from spectra.capture_client import camera as cam
from spectra.capture_client.camera import (CameraLock, CameraUnavailable,
                                           SyntheticCamera, V4L2Camera)
from spectra.capture_client.session import CaptureClient
from spectra.services import mapping_refusals, mapping_session

# A real `v4l2-ctl --list-ctrls-menus` shape, trimmed to the two controls
# this client touches.
MENUS = """
User Controls

                     brightness 0x00980900 (int)    : min=0 max=255 value=128
        white_balance_automatic 0x0098090c (bool)   : default=1 value=1

Camera Controls

                  auto_exposure 0x009a0901 (menu)   : min=0 max=3 default=3 value=3
				1: Manual Mode
				3: Aperture Priority Mode
          exposure_time_absolute 0x009a0902 (int)   : min=3 max=2047 value=166
    focus_automatic_continuous 0x009a090c (bool)   : default=1 value=1
"""


class FakeCtl:
    """A `v4l2-ctl` that remembers what was set — so a read-back is a real
    read-back and not the write echoing itself."""

    def __init__(self, values, *, writable=True):
        self.values = dict(values)
        self.writable = writable
        self.sets: list[tuple[str, int]] = []

    def __call__(self, args, timeout=5.0):
        if "--list-ctrls-menus" in args:
            return 0, MENUS
        for arg in args:
            if arg.startswith("--get-ctrl="):
                name = arg.split("=", 1)[1]
                if name not in self.values:
                    return 1, ""
                return 0, f"{name}: {self.values[name]}"
            if arg.startswith("--set-ctrl="):
                name, _, value = arg.split("=", 1)[1].partition("=")
                self.sets.append((name, int(value)))
                if self.writable:
                    self.values[name] = int(value)
                return 0, ""
        return 1, ""


@pytest.fixture
def ctl(monkeypatch):
    fake = FakeCtl({"auto_exposure": 3, "white_balance_automatic": 1})
    monkeypatch.setattr(cam, "_tool", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(cam, "_run", fake)
    return fake


# ── 1. THE LOCK IS READ BACK, NEVER ASSERTED ───────────────────────────────

def test_a_camera_reporting_auto_is_reported_as_not_locked(ctl):
    """The device says exposure is on Aperture Priority. Nothing here is
    allowed to round that up."""
    lock = asyncio.run(V4L2Camera().read_lock())
    assert lock.exposure_locked is False
    assert lock.white_balance_locked is False
    assert lock.exposure_mode == "Aperture Priority Mode"
    assert lock.exposure_capabilities == ["Aperture Priority Mode", "Manual Mode"]
    assert lock.source.startswith("v4l2:auto_exposure")


# ── THE ANNOTATED MENU VALUE — the owner's own laptop, 2026-09-03 ──────────
#
# `v4l2-ctl --get-ctrl` HAS NO SINGLE OUTPUT FORMAT. Some drivers print
#
#     auto_exposure: 1
#
# and others — including his — annotate the menu entry:
#
#     auto_exposure: 1 (Manual Mode)
#
# The read-back compared that whole string to `"1"` by equality, so a camera
# GENUINELY AT MANUAL reported `exposure_locked=False`. The client told
# SPECTRA it could not lock, every calibration-grade run refused by name,
# and the reason it quoted said the mode was `1 (Manual Mode)` while
# insisting it would not lock: a machine contradicting itself in one
# sentence.
#
# BOTH FORMATS ARE TEST CASES, and the annotated one is RED against the
# pre-fix code. Every menu control is covered, not just exposure — the same
# equality comparison was on white balance and continuous autofocus.

ANNOTATED = {"auto_exposure": "1 (Manual Mode)",
             "white_balance_automatic": "0 (Auto Mode off)",
             "focus_automatic_continuous": "0 (off)"}
PLAIN = {"auto_exposure": "1", "white_balance_automatic": "0",
         "focus_automatic_continuous": "0"}


@pytest.mark.parametrize("values,shape", [(PLAIN, "plain"),
                                          (ANNOTATED, "annotated")])
def test_a_menu_value_is_read_the_same_however_the_driver_prints_it(
        monkeypatch, values, shape):
    fake = FakeCtl(values)
    monkeypatch.setattr(cam, "_tool", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(cam, "_run", fake)
    lock = asyncio.run(V4L2Camera().read_lock())
    assert lock.exposure_locked is True, \
        f"a camera at Manual must read as locked ({shape} output)"
    assert lock.white_balance_locked is True, shape
    assert lock.focus_auto is False, \
        f"continuous autofocus off must read as off ({shape} output)"
    assert lock.locked is True, shape


def test_the_annotated_label_is_kept_rather_than_thrown_away(monkeypatch):
    """The label is the driver's own words about its own state, so it is
    reported. What it may not do is decide the boolean."""
    fake = FakeCtl(dict(ANNOTATED))
    monkeypatch.setattr(cam, "_tool", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(cam, "_run", fake)
    lock = asyncio.run(V4L2Camera().read_lock())
    assert "Manual" in lock.exposure_mode
    assert lock.white_balance_mode == "manual"


def test_an_annotated_auto_reading_is_still_NOT_locked(monkeypatch):
    """THE FIX MAY NOT OVER-CORRECT. Parsing the leading integer must not
    turn every annotated reading into a lock — an annotated AUTO is auto."""
    fake = FakeCtl({"auto_exposure": "3 (Aperture Priority Mode)",
                    "white_balance_automatic": "1 (Auto Mode)"})
    monkeypatch.setattr(cam, "_tool", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(cam, "_run", fake)
    lock = asyncio.run(V4L2Camera().read_lock())
    assert lock.exposure_locked is False
    assert lock.white_balance_locked is False
    assert lock.locked is False


def test_the_leading_number_parser_takes_the_number_and_nothing_else():
    """Directly, because every read-back in this file goes through it — and
    a value with no leading number is None (an UNKNOWN), never a default."""
    assert cam._menu_value("1") == 1
    assert cam._menu_value("1 (Manual Mode)") == 1
    assert cam._menu_value("  3 (Aperture Priority Mode)  ") == 3
    assert cam._menu_value("0 (Auto Mode)") == 0
    for junk in ("", None, "Manual Mode", "(1)"):
        assert cam._menu_value(junk) is None, junk
    # The LEVERS are read with the same parser, so an annotating driver must
    # not silently report every one of them as unreadable.
    assert cam._as_float("250 (whatever)") == 250.0
    assert cam._as_float("-3 (below zero)") == -3.0


def test_apply_lock_asks_the_driver_then_reports_what_it_read_back(ctl):
    lock = asyncio.run(V4L2Camera().apply_lock())
    assert ctl.sets == [("auto_exposure", cam.EXPOSURE_MANUAL),
                        ("white_balance_automatic", cam.WB_AUTO_OFF)]
    assert lock.exposure_locked and lock.white_balance_locked
    assert lock.exposure_mode == "Manual Mode"


def test_a_write_that_does_not_take_is_reported_as_not_locked(monkeypatch):
    """THE FORGERY GUARD. `v4l2-ctl --set-ctrl` returning 0 is not evidence:
    a camera that keeps its own auto exposure reports auto on the read-back,
    and this client must report auto — a run then refuses BY NAME, which is
    the correct outcome and the whole point of the gate."""
    fake = FakeCtl({"auto_exposure": 3, "white_balance_automatic": 1},
                   writable=False)
    monkeypatch.setattr(cam, "_tool", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(cam, "_run", fake)
    lock = asyncio.run(V4L2Camera().apply_lock())
    assert fake.sets, "it did ask"
    assert lock.locked is False, "and it did not pretend the ask worked"
    assert mapping_session.lock_refusal(
        mapping_session.LockState(reported=True, **{
            k: v for k, v in lock.as_wire().items()
            if k not in ("source", "camera_error")},
            source=lock.source)) is not None


def test_a_camera_whose_controls_cannot_be_read_says_so(monkeypatch):
    monkeypatch.setattr(cam, "_tool", lambda name: None)
    lock = asyncio.run(V4L2Camera().read_lock())
    assert lock.locked is False
    assert "v4l2-ctl is not installed" in lock.exposure_capabilities
    assert lock.source == "v4l2:unavailable"


def test_the_synthetic_camera_has_no_locked_default():
    """A test camera that reported locked by default would let a proof pass
    without ever exercising the gate."""
    lock = asyncio.run(SyntheticCamera(lambda: bytes(cam.FRAME_BYTES)).read_lock())
    assert lock.locked is False


def test_the_wire_frame_contract_is_enforced_by_the_camera():
    """320x180 grey8 is not this module's to change: the server rejects any
    other size rather than resampling a surprise."""
    bad = SyntheticCamera(lambda: bytes(100))
    asyncio.run(bad.open())
    with pytest.raises(ValueError, match="not 57600"):
        asyncio.run(bad.frame())


# ── 2. no camera at all ────────────────────────────────────────────────────

def test_a_missing_device_is_named_before_anything_opens(monkeypatch):
    monkeypatch.setattr(cam, "_tool", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(cam.os.path, "exists", lambda _p: False)
    with pytest.raises(CameraUnavailable, match="does not exist"):
        asyncio.run(V4L2Camera("/dev/video9").open())


def test_a_client_with_no_camera_still_connects_and_says_why():
    """Dying quietly on a laptop nobody is looking at is the failure mode
    this whole client exists to remove."""
    blind = SyntheticCamera(lambda: bytes(cam.FRAME_BYTES),
                            fail="/dev/video0: Device or resource busy")
    client = CaptureClient("ws://127.0.0.1:1", blind, host="sofa-laptop")
    problem = asyncio.run(client.start_camera())
    assert "Device or resource busy" in problem
    assert blind.lock.camera_error and blind.lock.locked is False
    # and the SERVER's own gate turns that into the sentence a human reads
    state = mapping_session.LockState(reported=True,
                                      camera_error=blind.lock.camera_error)
    said = mapping_session.lock_refusal(state, {"host": "sofa-laptop"})
    assert said == mapping_refusals.no_camera(blind.lock.camera_error,
                                              "sofa-laptop")
    assert "sofa-laptop" in said and "could not open a camera" in said


# ── 3. holding the session through a drop ──────────────────────────────────

LOCKED = CameraLock(exposure_locked=True, white_balance_locked=True,
                    exposure_mode="Manual Mode", white_balance_mode="manual",
                    source="synthetic:declared-locked")


def test_it_reconnects_and_re_asserts_its_pose():
    """A dropped WebSocket moves no camera and re-locks no exposure, so the
    map either side of it is ONE measurement. Minting a fresh pose id would
    label it as two."""
    hellos: list[dict] = []

    async def handler(ws):
        async for raw in ws:
            msg = json.loads(raw)
            if msg.get("type") == "hello":
                hellos.append(msg)
                await ws.send(json.dumps({"type": "hello_ack",
                                          "session_id": "s",
                                          "pose_id": msg.get("pose_hint")}))

    async def go():
        async with websockets.serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            camera = SyntheticCamera(lambda: bytes(cam.FRAME_BYTES),
                                     lock=LOCKED, fps=50.0)
            client = CaptureClient(f"ws://127.0.0.1:{port}", camera,
                                   host="t", fps=50.0)
            assert await client.start_camera() is None
            pose = camera.pose_token
            task = asyncio.create_task(client.run())
            for _ in range(200):
                if client.state.frames_sent > 2:
                    break
                await asyncio.sleep(0.02)
            await client._ws.close()               # noqa: SLF001
            for _ in range(300):
                if client.state.connects > 1 and client.state.connected:
                    break
                await asyncio.sleep(0.02)
            client.stop()
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):   # noqa: BLE001
                pass
            return client.state, pose, camera.pose_token

    state, pose, after = asyncio.run(go())
    assert state.connects >= 2 and state.drops >= 1, "it came back on its own"
    assert after == pose, "the camera never closed, so the pose is the same"
    assert len(hellos) >= 2
    assert all(h["pose_hint"] == pose for h in hellos), (
        "and it says so on every connect")
    assert hellos[0]["host"] == "t" and hellos[0]["lock"]["exposure_locked"]


def test_reopening_the_camera_mints_a_new_pose():
    """Structural, not a decision: the token is generated inside open(), so
    a re-locked exposure cannot be labelled as the old measurement."""
    camera = SyntheticCamera(lambda: bytes(cam.FRAME_BYTES), lock=LOCKED)
    asyncio.run(camera.open())
    first = camera.pose_token
    asyncio.run(camera.close())
    asyncio.run(camera.open())
    assert camera.pose_token and camera.pose_token != first


def test_the_server_only_adopts_a_sane_pose_hint():
    """A pose id reaches the store on every footprint, so what a client may
    assert is bounded."""
    sess = mapping_session.MappingSession(send=None)
    minted = sess.pose_id
    for junk in (None, 123, "", "   ", "///"):
        sess._adopt_pose(junk)                     # noqa: SLF001
        assert sess.pose_id == minted and not sess.pose_asserted
    sess._adopt_pose("a" * 200)                    # noqa: SLF001
    assert len(sess.pose_id) == 32 and sess.pose_asserted
