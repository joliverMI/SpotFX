"""FOUR PINNED CONTROLS, AND NOT ONE OF THEM TRUSTED WITHOUT A READ-BACK.

THE EVENING THIS IS FOR (2026-09-01). The browser path could not pin gain at
all on his Brio, and what it called a read-back was an echo of its own
request. So the native client pins FOUR controls — integration time, gain,
white balance temperature, focus — and every one of them is read back OUT OF
THE DRIVER before any frame is measured; a control that answered a different
number refuses BY NAME.

Everything here is hermetic: a fake `v4l2-ctl` that remembers what was
written, so a read-back is a real read-back and never the write echoing
itself. `tests/test_lever_selftest.py` is the other half — proving the
driver holds a value is not proving the sensor obeys it.
"""
from __future__ import annotations

import asyncio

import pytest

from spectra.capture_client import camera as cam
from spectra.capture_client.camera import CameraLock, V4L2Camera
from spectra.capture_client.session import CaptureClient
from spectra.services import capture_settings as cs
from spectra.services import mapping_session

# A real `v4l2-ctl --list-ctrls-menus` shape carrying all four controls this
# client pins, plus the two auto switches it has to turn off first.
MENUS = """
User Controls

                     brightness 0x00980900 (int)    : min=0 max=255 value=128
        white_balance_automatic 0x0098090c (bool)   : default=1 value=1
                           gain 0x00980913 (int)    : min=0 max=255 value=0
      white_balance_temperature 0x0098091a (int)    : min=2000 max=6500 value=4000

Camera Controls

                  auto_exposure 0x009a0901 (menu)   : min=0 max=3 default=3 value=3
				1: Manual Mode
				3: Aperture Priority Mode
         exposure_time_absolute 0x009a0902 (int)    : min=3 max=2047 value=166
    focus_automatic_continuous 0x009a090c (bool)    : default=1 value=1
                 focus_absolute 0x009a090a (int)    : min=0 max=255 value=68
"""


class FakeCtl:
    """A `v4l2-ctl` that remembers. `stuck` names controls that take the
    write and keep their own value — the shape a camera lies in."""

    def __init__(self, values, *, stuck=()):
        self.values = dict(values)
        self.stuck = set(stuck)
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
                if name not in self.stuck:
                    self.values[name] = int(value)
                return 0, ""
        return 1, ""


DEFAULTS = {"auto_exposure": 3, "white_balance_automatic": 1,
            "exposure_time_absolute": 166, "gain": 0,
            "white_balance_temperature": 4000,
            "focus_automatic_continuous": 1, "focus_absolute": 68}

PINNED = {"exposure_time": 400, "gain": 96, "white_balance": 4600,
          "focus": 120}


@pytest.fixture
def ctl(monkeypatch):
    fake = FakeCtl(DEFAULTS)
    monkeypatch.setattr(cam, "_tool", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(cam, "_run", fake)
    return fake


def _lock_state(lock: CameraLock) -> mapping_session.LockState:
    """What the SERVER would make of this client's report — the same
    `_apply_lock` path a real frame takes, so a test cannot prove a refusal
    the wire could not carry."""
    sess = mapping_session.MappingSession(send=None)
    sess._apply_lock(lock.as_wire())                   # noqa: SLF001
    return sess.lock


# ── 1. ALL FOUR ARE WRITTEN, AND ALL FOUR ARE READ BACK ────────────────────

def test_all_four_pinned_controls_reach_the_driver_and_are_read_back(ctl):
    lock = asyncio.run(V4L2Camera().apply_lock(**PINNED))
    written = dict(ctl.sets)
    assert written["exposure_time_absolute"] == 400
    assert written["gain"] == 96
    assert written["white_balance_temperature"] == 4600
    assert written["focus_absolute"] == 120
    # AND THE MODE SWITCHES THAT MAKE THEM STICK, in the right order: a UVC
    # driver ignores an integration time while auto exposure is live, and
    # re-focuses over a focus write while it is still focusing itself.
    order = [name for name, _v in ctl.sets]
    assert order.index("auto_exposure") < order.index("exposure_time_absolute")
    assert order.index("focus_automatic_continuous") < order.index("focus_absolute")
    # THE REPORT IS THE READ-BACK, for every one of them.
    assert (lock.exposure_time, lock.gain) == (400.0, 96.0)
    assert (lock.white_balance, lock.focus) == (4600.0, 120.0)
    assert lock.focus_auto is False
    assert lock.manual_refusals == []
    assert lock.exposure_time_range == [3.0, 2047.0]
    assert lock.focus_range == [0.0, 255.0]


def test_autofocus_is_left_alone_when_no_focus_was_asked_for(ctl):
    """A camera left to focus itself keeps doing so. Silently disabling
    autofocus for every run would change what an ordinary night sees rather
    than pinning what a calibration asked for."""
    asyncio.run(V4L2Camera().apply_lock(exposure_time=400))
    assert "focus_automatic_continuous" not in dict(ctl.sets)


@pytest.mark.parametrize("lever,control,other", [
    ("exposure_time", "exposure_time_absolute", 166.0),
    ("gain", "gain", 0.0),
    ("white_balance", "white_balance_temperature", 4000.0),
    ("focus", "focus_absolute", 68.0),
])
def test_a_control_that_answers_a_different_number_refuses_by_name(
        monkeypatch, lever, control, other):
    """THE FORGERY GUARD, one lever at a time. `--set-ctrl` returning 0 is
    not evidence: a driver that takes the write and keeps its own value is
    the dangerous case, because the frames still arrive and only the numbers
    are wrong."""
    fake = FakeCtl(DEFAULTS, stuck={control})
    monkeypatch.setattr(cam, "_tool", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(cam, "_run", fake)
    lock = asyncio.run(V4L2Camera().apply_lock(**PINNED))
    assert fake.sets, "it did ask"
    assert any(str(int(other)) in r or f"{other:g}" in r
               for r in lock.manual_refusals), lock.manual_refusals

    # AND THE SERVER REFUSES ON IT, before any frame is measured.
    class Double(cs.SessionCameraDouble):
        camera_lock = lock.as_wire()

        def _camera_clock(self):
            return 0.0

    sess = Double()
    sess.init_camera(cs.MAP_PROFILE)
    sess.camera_request = cs.request(**PINNED)
    refusal = sess.camera_refusal()
    assert refusal and "did not take" in refusal


def test_a_camera_with_no_such_control_is_named_not_assumed(monkeypatch):
    fake = FakeCtl({"auto_exposure": 3, "white_balance_automatic": 1})
    monkeypatch.setattr(cam, "_tool", lambda name: f"/usr/bin/{name}")
    # A device whose menus list nothing but the two auto switches.
    monkeypatch.setattr(cam, "_run", lambda args, timeout=5.0: (
        (0, "auto_exposure 0x1 (menu) : min=0 max=3 value=3\n"
            "white_balance_automatic 0x2 (bool) : value=1\n")
        if "--list-ctrls-menus" in args else fake(args, timeout)))
    lock = asyncio.run(V4L2Camera().apply_lock(**PINNED))
    joined = " ".join(lock.manual_refusals)
    for control in ("exposure_time_absolute", "gain",
                    "white_balance_temperature", "focus_absolute"):
        assert control in joined
    assert (lock.white_balance, lock.focus) == (None, None), \
        "a control that cannot be read is None, never a plausible number"


# ── 2. PERSISTENCE IS SOFTWARE ─────────────────────────────────────────────

def test_a_reopened_camera_comes_back_pinned(ctl, monkeypatch):
    """A re-plug, a reboot or a dead capture pipe costs nothing, because
    `open()` re-asserts whatever this camera was pinned to. Nothing is
    written to disk and nothing about the camera's own memory is relied on."""
    camera = V4L2Camera()

    async def opened(*_a, **_k):
        return None

    monkeypatch.setattr(camera, "_open_at", opened)
    monkeypatch.setattr(cam.os.path, "exists", lambda _p: True)
    monkeypatch.setattr(cam.os, "access", lambda _p, _m: True)
    monkeypatch.setattr(cam, "SETTLE_BEFORE_LOCK_S", 0.0)
    asyncio.run(camera.apply_lock(**PINNED))
    # The camera "goes away" and comes back at its factory defaults, the way
    # a re-plugged UVC device does.
    ctl.values.update(DEFAULTS)
    asyncio.run(camera.open())
    assert (camera.lock.exposure_time, camera.lock.gain) == (400.0, 96.0)
    assert (camera.lock.white_balance, camera.lock.focus) == (4600.0, 120.0)
    assert camera.lock.manual_refusals == []


def test_a_reconnecting_client_re_asserts_the_pinned_regime(ctl):
    """The other half of the same rule: a dropped socket comes back to a
    camera pinned the way this session pinned it, not to a memory of one."""
    sent: list[dict] = []

    class Ws:
        async def send(self, raw):
            import json
            sent.append(json.loads(raw))

    camera = V4L2Camera()
    client = CaptureClient("ws://x", camera)

    async def go():
        # The server asks for a regime; the client pins it.
        await client._apply_config(Ws(), {                 # noqa: SLF001
            "type": "config", **PINNED})
        # The camera silently returns to its defaults (an auto mechanism
        # re-clamping, a driver reset) and the socket drops and comes back.
        ctl.values.update(DEFAULTS)
        await client._hello(Ws())                          # noqa: SLF001

    asyncio.run(go())
    assert client.state.reasserts == 1
    hello = sent[-1]
    assert hello["type"] == "hello"
    assert hello["lock"]["exposure_time"] == 400.0
    assert hello["lock"]["focus"] == 120.0
    assert hello["lock"]["white_balance"] == 4600.0


def test_a_client_that_pinned_nothing_re_asserts_nothing(ctl):
    """An ordinary night run costs exactly what it always did."""
    client = CaptureClient("ws://x", V4L2Camera())

    class Ws:
        async def send(self, raw):
            pass

    asyncio.run(client._hello(Ws()))                       # noqa: SLF001
    assert client.state.reasserts == 0


def test_naming_one_lever_does_not_un_pin_the_others(ctl):
    """A config that names an integration time must not silently drop the
    focus a previous one set. Un-pinning is saying so, explicitly."""
    client = CaptureClient("ws://x", V4L2Camera())

    class Ws:
        async def send(self, raw):
            pass

    async def go():
        await client._apply_config(Ws(), dict(PINNED))     # noqa: SLF001
        await client._apply_config(Ws(), {"exposure_time": 800})  # noqa: SLF001

    asyncio.run(go())
    assert client._pinned == {"exposure_time": 800, "gain": 96,   # noqa: SLF001
                              "white_balance": 4600, "focus": 120}

    async def release():
        await client._apply_config(Ws(), {"focus": None})  # noqa: SLF001

    asyncio.run(release())
    assert client._pinned["focus"] is None                 # noqa: SLF001


# ── 3. THE WIRE CARRIES ALL FOUR, BOTH WAYS ────────────────────────────────

def test_the_server_records_every_read_back_the_client_sent(ctl):
    lock = asyncio.run(V4L2Camera().apply_lock(**PINNED))
    state = _lock_state(lock)
    assert (state.exposure_time, state.gain) == (400.0, 96.0)
    assert (state.white_balance, state.focus) == (4600.0, 120.0)
    assert state.focus_auto is False
    assert state.white_balance_range == [2000.0, 6500.0]
    assert state.as_dict()["focus"] == 120.0


def test_a_request_that_pins_nothing_is_not_manual():
    """The founding property, still: a run that asks for none of the four
    must behave exactly as it did before they existed."""
    assert cs.request().manual is False
    assert cs.request().levers == {}
    assert cs.request(focus=120).manual is True
    assert cs.request(white_balance=4600).levers == {"white_balance": 4600}


def test_out_of_range_levers_are_clamped_and_said():
    req = cs.request(white_balance=99, focus=-4)
    assert req.white_balance == cs.MIN_WHITE_BALANCE
    assert req.focus == cs.MIN_FOCUS
    assert len(req.notes) == 2 and "clamped" in req.notes[0]
