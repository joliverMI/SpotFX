"""Ambient's binary toggle, its intent/phase contract, and INTERRUPTION —
the 2026-08-30 rework's proof bar, measured on a mock Hue bridge.

His words: "let's only ever toggle between Off and On... The main issue is
when I turn on ambient in a room, there is a lag between when i turn it on
and when it finishes, so I don't know if it has started or not, and I keep
accidentally toggling it multiple times... give the butt[on]s in HA and in
spectra some clarity that they are 'turning on' or 'Turning off'...
Interrupting should snap the state. So if is gradually turning ambient off,
and I turn it back on, it should just snap to being full brightness."

The proofs, in his own order:
  (a) THE 38s SHAPE, red then green. The pre-rework path — two overlapping
      services.ambient.reconcile() calls with no cancellation, exactly what
      ambient_music_gate._apply used to do — is driven directly and MEASURED
      queueing: the second intent's first write does not land until the
      first sequence has finished its whole 22.6s-shaped ramp. The same
      scenario through the new transition owner is then measured snapping:
      the new end state's first write lands within one write slot of the
      cancel, and total time is bounded by bulb count rather than by the
      sequence he changed his mind about.
  (b) A rapid triple-press lands exactly the final intent, through exactly
      ONE surviving transition — no queue, no intermediate state left on the
      bulbs.
  (c) phase walks on -> turning_off -> off and off -> turning_on -> on, with
      a pushed broadcast observed at every step (not just on the 3s poll).
  (d) lives in tests/test_room_controls.py (the migration is a store
      concern) — test_ambient_mode_migrates_to_the_binary_toggle.
  (e) The music-pause branch is ALIVE but gated off: it does nothing at the
      shipped default and does exactly the retired "auto" behaviour once the
      setting is turned on.

Timing is measured on the real wall clock against a mock bridge, with the
production pacing constants scaled DOWN (not zeroed — the whole point is
that the sequence has real duration to interrupt). Every assertion is a
RATIO or an ordering against the scaled constants, never a bare second
count, so the proofs say something about the mechanism rather than about
this machine's speed.

No live Hue bridge, no LedFX, no live_host activation.
"""
from __future__ import annotations

import asyncio
import json
import time

import httpx
import pytest

# Scaled stand-ins for the real constants (3000ms fade / 8000ms catch-up /
# 300ms stagger). Same SHAPE, 1/20th the wall clock: a turn-off is still
# dominated by its two ramps, a turn-on still by its staggered writes.
FADE_MS = 150
CATCHUP_MS = 400
STAGGER_MS = 15
BULBS = 17          # his real room


def _run(coro):
    return asyncio.run(coro)


# ── a timestamping mock bridge ─────────────────────────────────────────────

class Clock:
    """Monotonic origin for a single test, so every recorded event is a
    plain millisecond offset from the scenario's start."""

    def __init__(self) -> None:
        self.t0 = time.monotonic()

    def ms(self) -> float:
        return (time.monotonic() - self.t0) * 1000


def _handler(clock: Clock, events: list, lights: list):
    """A canned Hue CLIP v2 bridge that records ("PUT", rid, at_ms) for
    every light write, so a test can measure WHEN a write landed rather than
    only that it did. Per-light state is tracked so a read-back only
    confirms once a PUT actually landed."""
    states: dict[str, dict] = {}

    def state(rid: str) -> dict:
        return states.setdefault(rid, {
            "on": {"on": False},
            "dimming": {"brightness": 1.0},
            "color": {"xy": {"x": 0.3127, "y": 0.3290}},
        })

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/clip/v2/resource/entertainment":
            return httpx.Response(200, json={"data": [
                {"id": f"e{i}", "owner": {"rid": light["owner"]}}
                for i, light in enumerate(lights)]})
        if path == "/clip/v2/resource/light":
            return httpx.Response(200, json={"data": [
                {"id": light["id"], "owner": {"rid": light["owner"]},
                 "metadata": {"name": light["id"]}} for light in lights]})
        if path.startswith("/clip/v2/resource/entertainment_configuration/"):
            return httpx.Response(200, json={"data": [{"channels": [
                {"members": [{"service": {"rtype": "entertainment", "rid": f"e{i}"}}]}
                for i in range(len(lights))]}]})
        if path.startswith("/clip/v2/resource/light/"):
            rid = path.rsplit("/", 1)[-1]
            if request.method == "PUT":
                body = json.loads(request.content)
                events.append(("PUT", rid, clock.ms(), body))
                state(rid).update(
                    {k: v for k, v in body.items() if k in ("on", "dimming", "color")})
                return httpx.Response(200, json={"data": []})
            if request.method == "GET":
                return httpx.Response(200, json={"data": [dict(state(rid), id=rid)]})
        raise AssertionError(f"unexpected {request.method} {path}")

    return handler


class FakeHueDevice:
    type = "hue"

    def __init__(self, ip: str, events: list, clock: Clock):
        self.config = {"ip_address": ip, "entertainment_id": f"ent-{ip}", "username": "u"}
        self.frozen: bool | None = None
        self._events = events
        self._clock = clock

    async def set_frozen(self, frozen: bool) -> None:
        self._events.append(("frozen", frozen, self._clock.ms(), {}))
        self.frozen = frozen

    def assemble_frame(self):
        return [(10.0, 20.0, 30.0)]


class FakeHost:
    def __init__(self, devices: dict):
        self.devices = devices


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    from spectra import config as scfg
    from spectra.services import ambient, ambient_music_gate
    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path)
    monkeypatch.setattr(scfg, "ROOM_CONTROLS_FILE", tmp_path / "room_controls.json")
    ambient._light_cache.clear()
    ambient._lock = None          # each asyncio.run() gets a fresh loop
    ambient_music_gate.reset_state()
    yield
    ambient_music_gate.reset_state()
    ambient._lock = None
    ambient._light_cache.clear()


@pytest.fixture(autouse=True)
def _scaled_pacing(monkeypatch):
    """Real shape, 1/20th the wall clock — see the module docstring. Retry
    spacing/settle are zeroed: they are not part of what an interruption
    has to beat, and leaving them in would just make every test slower."""
    from spectra.services import ambient
    monkeypatch.setattr(ambient, "AMBIENT_TRANSITION_MS", FADE_MS)
    monkeypatch.setattr(ambient, "AMBIENT_CATCHUP_MS", CATCHUP_MS)
    monkeypatch.setattr(ambient, "AMBIENT_WRITE_STAGGER_MS", STAGGER_MS)
    monkeypatch.setattr(ambient, "AMBIENT_CONFIRM_SETTLE_MS", 0)
    monkeypatch.setattr(ambient, "AMBIENT_RETRY_SPACING_MS", 0)


@pytest.fixture
def room(monkeypatch):
    """One Hue device carrying his real bulb count, wired to a timestamping
    mock bridge. Returns (device, events, clock)."""
    from spectra.services import ambient
    from spectra.services.live_host import live

    clock = Clock()
    events: list = []
    lights = [{"id": f"l{i}", "owner": f"d{i}"} for i in range(BULBS)]
    handler = _handler(clock, events, lights)

    def fake_bridge_client(cfg):
        return httpx.AsyncClient(base_url=f"https://{cfg['ip_address']}",
                                 transport=httpx.MockTransport(handler))

    monkeypatch.setattr(ambient, "_bridge_client", fake_bridge_client)
    dev = FakeHueDevice("10.0.0.1", events, clock)
    # LiveLights.active is a read-only property (`host is not None`), so
    # host IS the ownership switch these tests flip.
    monkeypatch.setattr(live, "host", FakeHost({"hue-lights": dev}))
    return dev, events, clock


def _save(**kwargs):
    from spectra.services import room_controls as rc
    rc.save_room_controls(rc.RoomControlState(**kwargs))


def _colour_writes(events, xy_x: float) -> list:
    """Every PUT that carried a colour at approximately this x chromaticity
    — i.e. the writes belonging to one specific ambient colour."""
    out = []
    for kind, _rid, at_ms, body in events:
        if kind != "PUT":
            continue
        xy = (body.get("color") or {}).get("xy") or {}
        if xy.get("x") is not None and abs(xy["x"] - xy_x) < 0.005:
            out.append(at_ms)
    return out


CREAM = "#f5da8c"


def _cream_x() -> float:
    from spectra.services.ambient import _hex_to_xy
    return round(_hex_to_xy(CREAM)[0], 4)


# ═══ (a) the 38s shape, reproduced red then proven green ══════════════════

def test_the_old_path_queues_an_interrupting_intent_behind_the_whole_sequence(room):
    """RED — this is the shape he measured live at 38s, driven directly
    against services.ambient.reconcile() with no cancellation token: exactly
    what ambient_music_gate._apply did before this rework (await
    ambient.reconcile(...) inside its own lock, with the module's own I/O
    lock underneath).

    The interrupting ON does not get to write a single bulb until the
    turn-off has finished BOTH ramps and every unfreeze. That is the defect;
    the next test is the same scenario through the new owner."""
    from spectra.services import ambient
    dev, events, clock = room

    async def scenario():
        # Get the room held first, so the OFF has real work to do.
        await ambient.reconcile(True, CREAM)
        events.clear()
        off = asyncio.create_task(ambient.reconcile(False, None))
        await asyncio.sleep(FADE_MS / 1000 / 3)     # a third into the fade
        interrupt_at = clock.ms()
        # No token, no snap — the pre-rework call shape.
        await ambient.reconcile(True, CREAM)
        return interrupt_at, clock.ms(), await off

    interrupt_at, done_at, _ = _run(scenario())

    on_writes = _colour_writes(events, _cream_x())
    assert on_writes, "the interrupting ON must eventually write"
    first_on = min(on_writes)
    # The OFF sequence's own floor: fade ramp + catch-up ramp, both waited
    # out in full because nothing could interrupt them.
    ramps_ms = FADE_MS + CATCHUP_MS
    assert first_on - interrupt_at > ramps_ms, (
        "PRE-REWORK SHAPE: the interrupting intent queued behind the whole "
        f"release sequence — first ON write {first_on - interrupt_at:.0f}ms "
        f"after the press, past the {ramps_ms}ms of ramps alone")


def test_interrupting_a_turn_off_with_on_snaps(room):
    """GREEN — his literal example: "if is gradually turning ambient off,
    and I turn it back on, it should just snap to being full brightness".

    Three things are asserted, and they are the whole mechanic:
      1. the new end state's first write lands within ONE WRITE SLOT of the
         cancel — not after the ramps;
      2. total time is bounded by BULB COUNT (the staggered confirmed
         writes, which stay — zigbee physics), not by the abandoned
         sequence;
      3. the snapped hold carries NO bridge-side ramp (`dynamics`), because
         the ramps are exactly what he asked to snap away."""
    from spectra.services import ambient_music_gate as gate
    dev, events, clock = room
    _save(ambient_enabled=True, ambient_color=CREAM)

    async def scenario():
        await gate.reconcile(True)                       # held
        events.clear()
        _save(ambient_enabled=False, ambient_color=CREAM)
        turning_off = await gate.reconcile(True, wait=False)
        assert turning_off["phase"] == "turning_off"
        await asyncio.sleep(FADE_MS / 1000 / 3)          # mid-fade
        _save(ambient_enabled=True, ambient_color=CREAM)
        interrupt_at = clock.ms()
        turning_on = await gate.reconcile(True, wait=False)
        assert turning_on["phase"] == "turning_on"
        assert turning_on["snap"] is True, "an interrupted transition snaps"
        result = await gate._await_transition(gate._transition)
        return interrupt_at, clock.ms(), result

    interrupt_at, done_at, result = _run(scenario())

    assert result["status"] == "on"
    on_writes = sorted(_colour_writes(events, _cream_x()))
    assert on_writes, "the snapped ON must write the ambient colour"

    one_slot_ms = STAGGER_MS * 2 + 60      # one write slot + scheduling slack
    assert on_writes[0] - interrupt_at < one_slot_ms, (
        f"the snapped ON's first write landed {on_writes[0] - interrupt_at:.0f}ms "
        f"after the press — it must land within one write slot of the cancel, "
        "never behind the abandoned sequence")

    # Bounded by bulb count, not by the sequence: writes + read-backs for
    # BULBS lights, with generous slack, and well under what waiting the
    # abandoned ramps out would have cost.
    assert done_at - interrupt_at < FADE_MS + CATCHUP_MS, (
        f"the whole snap took {done_at - interrupt_at:.0f}ms — it must not "
        "have waited out the ramps it cancelled")

    snapped_bodies = [body for kind, _rid, _at, body in events
                      if kind == "PUT" and (body.get("color") or {}).get("xy", {}).get("x")
                      == _cream_x()]
    assert snapped_bodies and all("dynamics" not in b for b in snapped_bodies), \
        "a snapped hold carries no bridge-side ramp — that is what 'snap' means"
    assert dev.frozen is True, "the room ends up genuinely held, not half-released"


def test_interrupting_a_turn_on_with_off_snaps_too(room):
    """The other direction, which his sentence implies but does not spell
    out: a turn-ON interrupted by OFF must not wait out the hold's own
    ramp/confirmation either, and a SNAPPED release skips both the dim fade
    and the catch-up ramp — straight back to the stream, which never stopped
    rendering the room's real scene."""
    from spectra.services import ambient_music_gate as gate
    dev, events, clock = room
    _save(ambient_enabled=False)

    async def scenario():
        await gate.reconcile(True)                       # released, settled
        events.clear()
        _save(ambient_enabled=True, ambient_color=CREAM)
        await gate.reconcile(True, wait=False)           # turning on
        await asyncio.sleep(STAGGER_MS * 3 / 1000)       # a few bulbs in
        _save(ambient_enabled=False)
        interrupt_at = clock.ms()
        turning_off = await gate.reconcile(True, wait=False)
        assert turning_off["phase"] == "turning_off"
        await gate._await_transition(gate._transition)
        return interrupt_at, clock.ms()

    interrupt_at, done_at = _run(scenario())

    assert done_at - interrupt_at < FADE_MS + CATCHUP_MS, (
        f"the snapped release took {done_at - interrupt_at:.0f}ms — a snapped "
        "release skips BOTH ramps")
    # A snapped release writes nothing at all: unfreezing hands the device
    # back to the live stream.
    late_puts = [at for kind, _rid, at, _b in events if kind == "PUT" and at >= interrupt_at]
    assert not late_puts, \
        "a snapped release must not fade or catch-up — it just lets go"
    assert dev.frozen is False, "the room ends up genuinely released"


def test_an_uninterrupted_turn_off_keeps_its_two_phase_ease(room):
    """SCOPE GUARD. His complaint was the interruption, not the fade — an
    ordinary turn-off must still do the deliberate dim-then-catch-up ease
    services/ambient.py was built for."""
    from spectra.services import ambient_music_gate as gate
    dev, events, clock = room
    _save(ambient_enabled=True, ambient_color=CREAM)

    async def scenario():
        await gate.reconcile(True)
        events.clear()
        _save(ambient_enabled=False)
        started = clock.ms()
        await gate.reconcile(True)
        return started, clock.ms()

    started, done = _run(scenario())
    bodies = [body for kind, _rid, _at, body in events if kind == "PUT"]
    assert any("color" not in b and "dimming" in b for b in bodies), \
        "phase 1 (the brightness-only dim fade) still runs"
    assert any((b.get("dynamics") or {}).get("duration") == CATCHUP_MS for b in bodies), \
        "phase 2 (the catch-up ramp toward the live look) still runs"
    assert done - started >= FADE_MS + CATCHUP_MS, \
        "an uninterrupted release still waits out both ramps in full"


# ═══ (b) rapid presses land exactly the final intent, once ════════════════

def test_rapid_triple_press_lands_the_final_intent_through_one_transition(room):
    """His actual behaviour when the button gives him no feedback: press,
    press, press. The queue is abolished — at most one transition survives,
    the newest generation wins, and the room ends in the state of the LAST
    press, not of some earlier one that was still draining."""
    from spectra.services import ambient_music_gate as gate
    dev, events, clock = room
    _save(ambient_enabled=False)

    async def scenario():
        await gate.reconcile(True)
        generations = []
        for enabled in (True, False, True):              # on, off, on
            _save(ambient_enabled=enabled, ambient_color=CREAM)
            res = await gate.reconcile(True, wait=False)
            generations.append(res["generation"])
            await asyncio.sleep(STAGGER_MS * 2 / 1000)   # a real, fast burst
        survivor = gate._transition
        result = await gate._await_transition(survivor)
        return generations, survivor, result

    generations, survivor, result = _run(scenario())

    assert generations == sorted(set(generations)), \
        "each press starts a NEW generation — never reuses or queues one"
    assert survivor.generation == generations[-1], \
        "the newest generation owns the room"
    assert result["status"] == "on", "the room lands on the LAST press's intent"
    assert dev.frozen is True

    st = gate.status()
    assert st["intent"] == "on" and st["phase"] == "on"
    assert st["held"] is True, "and it genuinely landed — confirmed, not claimed"


def test_a_superseded_transition_never_writes_the_bookkeeping(room):
    """A superseded run must abandon cleanly: it never lands its own
    outcome over the newer one's. Without the `_transition is tr` guard, a
    slow cancelled turn-off finishing late would flip `_held` back to False
    while the room is genuinely lit."""
    from spectra.services import ambient_music_gate as gate
    dev, events, clock = room
    _save(ambient_enabled=True, ambient_color=CREAM)

    async def scenario():
        await gate.reconcile(True)
        _save(ambient_enabled=False)
        off = await gate.reconcile(True, wait=False)
        off_tr = gate._transition
        await asyncio.sleep(FADE_MS / 1000 / 3)
        _save(ambient_enabled=True, ambient_color=CREAM)
        await gate.reconcile(True, wait=False)
        on_tr = gate._transition
        await gate._await_transition(on_tr)
        # Let the superseded task finish however it wants to.
        await off_tr.task
        return off_tr, on_tr

    off_tr, on_tr = _run(scenario())
    assert off_tr.superseded is True
    assert off_tr.result == {"status": "superseded", "intent": "off"}
    assert gate._held is True, \
        "the superseded turn-off must not land its state over the newer hold"
    assert gate.status()["phase"] == "on"


# ═══ (c) the phase contract, and the pushed broadcast ═════════════════════

@pytest.fixture
def pushes(monkeypatch):
    """Collect every ambient_status message the gate pushes over the SPECTRA
    websocket, without a socket."""
    from spectra.services import ws
    seen: list = []

    async def fake_broadcast(payload):
        seen.append(payload)

    monkeypatch.setattr(ws.ws_manager, "broadcast", fake_broadcast)
    return seen


def test_phase_walks_off_to_turning_on_to_on_with_pushes(room, pushes):
    """(c), first direction. The FROZEN contract: intent/phase on
    GET /api/engine/status and on the status websocket, updated by a push at
    the transition's start and end — not only when the 3s poll happens to
    come round."""
    from spectra.services import ambient_music_gate as gate
    dev, events, clock = room
    _save(ambient_enabled=False)

    async def scenario():
        assert gate.status()["phase"] == "off"
        assert gate.status()["intent"] == "off"
        _save(ambient_enabled=True, ambient_color=CREAM)
        await gate.reconcile(True, wait=False)
        mid = gate.status()
        await gate._await_transition(gate._transition)
        return mid, gate.status()

    mid, end = _run(scenario())
    assert mid["phase"] == "turning_on" and mid["intent"] == "on"
    assert end["phase"] == "on" and end["intent"] == "on"

    phases = [p["phase"] for p in pushes]
    assert phases == ["turning_on", "on"], \
        f"a push at start and at end, in order — got {phases}"
    assert all(p["type"] == "ambient_status" for p in pushes)


def test_phase_walks_on_to_turning_off_to_off_with_pushes(room, pushes):
    """(c), the other direction."""
    from spectra.services import ambient_music_gate as gate
    dev, events, clock = room
    _save(ambient_enabled=True, ambient_color=CREAM)

    async def scenario():
        await gate.reconcile(True)
        pushes.clear()
        assert gate.status()["phase"] == "on"
        _save(ambient_enabled=False)
        await gate.reconcile(True, wait=False)
        mid = gate.status()
        await gate._await_transition(gate._transition)
        return mid, gate.status()

    mid, end = _run(scenario())
    assert mid["phase"] == "turning_off" and mid["intent"] == "off"
    assert end["phase"] == "off" and end["intent"] == "off"
    assert [p["phase"] for p in pushes] == ["turning_off", "off"]


def test_a_cancel_pushes_the_new_phase_immediately(room, pushes):
    """The third push point the contract names: a CANCEL. The superseding
    transition's own start push IS the notification — the phase flips to the
    new direction the moment the interrupt is taken, so a button never sits
    on a direction the room has already abandoned."""
    from spectra.services import ambient_music_gate as gate
    dev, events, clock = room
    _save(ambient_enabled=True, ambient_color=CREAM)

    async def scenario():
        await gate.reconcile(True)
        _save(ambient_enabled=False)
        await gate.reconcile(True, wait=False)
        await asyncio.sleep(FADE_MS / 1000 / 3)
        pushes.clear()
        _save(ambient_enabled=True, ambient_color=CREAM)
        await gate.reconcile(True, wait=False)
        await asyncio.sleep(0)      # let the new task's start push run
        cancelled_view = list(pushes)
        await gate._await_transition(gate._transition)
        return cancelled_view

    cancelled_view = _run(scenario())
    assert cancelled_view and cancelled_view[0]["phase"] == "turning_on", (
        "the cancel is announced as the new direction, immediately — got "
        f"{[p['phase'] for p in cancelled_view]}")
    # The superseded generation must never push a phase it no longer owns.
    assert all(p["phase"] != "turning_off" for p in pushes[len(cancelled_view):])


def test_phase_is_unavailable_when_the_room_is_not_ours(monkeypatch):
    """A press while the room is released or owned by spot-effects cannot
    act on lights — say so, rather than reporting a settled on/off the
    bulbs are not in. The intent is still stored (it IS
    RoomControlState.ambient_enabled) and still applies on the next
    take-back; nothing is silently dropped."""
    from spectra.services import ambient_music_gate as gate
    from spectra.services.live_host import live
    monkeypatch.setattr(live, "host", None)

    _save(ambient_enabled=True, ambient_color=CREAM)
    st = gate.status()
    assert st["phase"] == "unavailable"
    assert st["intent"] == "on", \
        "the stored intent is still reported — 'unavailable' is about the room"


def test_a_press_while_unavailable_is_stored_and_applied_on_take_back(monkeypatch, room):
    """The released-room case end to end: press while the room is not ours
    (nothing physical happens, phase 'unavailable'), then hand the room back
    — the stored intent lands, through the same reconcile_now() app.py's
    startup and handover's own commit both call."""
    from spectra.services import ambient_music_gate as gate
    from spectra.services.live_host import live
    dev, events, clock = room

    ours = live.host

    async def scenario():
        live.host = None                                  # room released
        _save(ambient_enabled=True, ambient_color=CREAM)
        pressed = await gate.reconcile(True, wait=False)
        assert gate._transition is None, \
            "no transition is even started for a room that is not ours"
        dark_phase = gate.status()["phase"]
        dark_frozen = dev.frozen

        live.host = ours                                  # take-back
        await gate.reconcile(True)
        return pressed, dark_phase, dark_frozen, gate.status()

    pressed, dark_phase, dark_frozen, after = _run(scenario())
    assert pressed["phase"] == "unavailable" and pressed["stored"] is True, \
        "the press is answered honestly, never a silent nothing"
    assert dark_phase == "unavailable"
    assert dark_frozen is None, "nothing physical happened while the room was not ours"
    assert after["phase"] == "on" and after["held"] is True, \
        "the stored intent is applied on the next take-back reconcile"
    assert dev.frozen is True


def test_status_publishes_the_frozen_contract_vocabulary(room):
    """The contract is handed to another captain building Home Assistant
    against it — these names and value sets are FROZEN. This test exists to
    make a rename loud."""
    from spectra.services import ambient_music_gate as gate
    _save(ambient_enabled=False)
    st = gate.status()
    assert set(("intent", "phase")) <= set(st)
    assert st["intent"] in ("on", "off")
    assert st["phase"] in ("on", "off", "turning_on", "turning_off", "unavailable")


# ═══ (e) the music-pause branch: alive, and gated off ═════════════════════

def test_music_pause_branch_is_inert_at_the_shipped_default(room):
    """His "set it to false for now": with Ambient off and the music-pause
    switch off, a confirmed-quiet room must do NOTHING at all."""
    from spectra.services import ambient_music_gate as gate
    dev, events, clock = room
    _save(ambient_enabled=False, ambient_on_music_pause=False, ambient_color=CREAM)

    result = _run(gate.reconcile(False))     # music confirmed NOT playing

    assert result["status"] == "off"
    assert dev.frozen is None, "nothing was touched"
    assert gate.status()["intent"] == "off"


def test_music_pause_branch_is_alive_once_the_setting_is_on(room):
    """The same branch, with only the setting flipped: the retired "auto"
    behaviour verbatim — a confirmed-quiet room engages the hold, confirmed
    playback releases it, and an UNKNOWN read never actively changes
    anything either way."""
    from spectra.services import ambient_music_gate as gate
    dev, events, clock = room
    _save(ambient_enabled=False, ambient_on_music_pause=True, ambient_color=CREAM)

    async def scenario():
        quiet = await gate.reconcile(False)              # confirmed not playing
        held_now = dev.frozen
        unknown = await gate.reconcile(None)             # no signal at all
        still_held = dev.frozen
        playing = await gate.reconcile(True)             # confirmed playing
        return quiet, held_now, unknown, still_held, playing

    quiet, held_now, unknown, still_held, playing = _run(scenario())
    assert quiet["status"] == "on" and held_now is True, \
        "confirmed-quiet engages the hold — the branch is alive, not deleted"
    assert still_held is True, "an unknown read never actively releases a held room"
    assert playing["status"] == "off" and dev.frozen is False, \
        "confirmed playback releases it again"


def test_the_toggle_beats_the_music_pause_switch(room):
    """ambient_enabled=True is unconditional and never consults playback —
    that is what the toggle means, and it is why the music-pause switch can
    only ever act while the toggle is OFF."""
    from spectra.services import ambient_music_gate as gate
    dev, events, clock = room
    _save(ambient_enabled=True, ambient_on_music_pause=True, ambient_color=CREAM)

    result = _run(gate.reconcile(True))      # music confirmed PLAYING

    assert result["status"] == "on" and dev.frozen is True


# ═══ the press itself must not block ══════════════════════════════════════

def test_a_press_returns_before_the_room_has_finished_moving(room):
    """The other half of his complaint: the PUT used to block for the whole
    15-22s sequence, which is why he could not tell whether it had started.
    reconcile_ambient_if_changed now starts the transition and returns —
    proven here by the press returning long before the ramps could have
    completed, while phase already says turning_off."""
    from spectra.services import room_controls as rc
    from spectra.services import ambient_music_gate as gate
    dev, events, clock = room

    async def scenario():
        _save(ambient_enabled=True, ambient_color=CREAM)
        await gate.reconcile(True)
        previous = rc.load_room_controls()
        new_state = previous.model_copy(update={"ambient_enabled": False})
        rc.save_room_controls(new_state)
        t0 = clock.ms()
        result = await rc.reconcile_ambient_if_changed(previous, new_state)
        returned_at = clock.ms()
        phase_now = gate.status()["phase"]
        await gate._await_transition(gate._transition)
        return result, returned_at - t0, phase_now

    result, took_ms, phase_now = _run(scenario())
    assert result["status"] == "turning_off" and result["phase"] == "turning_off"
    assert phase_now == "turning_off"
    assert took_ms < FADE_MS, (
        f"the press took {took_ms:.0f}ms to return — it must not wait for the "
        "sequence it started")


def test_repeated_identical_presses_never_restart_a_transition(room):
    """A burst of bridge broadcasts (engine.py reconciles on every one)
    must not be able to cancel-and-restart an in-flight transition forever.
    The short-circuit compares against the in-flight TARGET, not against
    `_held` — which does not move until the run lands."""
    from spectra.services import ambient_music_gate as gate
    dev, events, clock = room
    _save(ambient_enabled=True, ambient_color=CREAM)

    async def scenario():
        first = await gate.reconcile(True, wait=False)
        seen = [first["generation"]]
        for _ in range(5):
            await asyncio.sleep(STAGGER_MS / 1000)
            again = await gate.reconcile(True, wait=False)
            seen.append(again["generation"])
        await gate._await_transition(gate._transition)
        return seen

    seen = _run(scenario())
    assert len(set(seen)) == 1, \
        f"one transition, not one per broadcast — generations seen: {seen}"
    assert dev.frozen is True


# ═══ the real HTTP surface, end to end ═══════════════════════════════════

def test_put_room_controls_returns_turning_and_engine_status_carries_the_phase(room):
    """Through the REAL routes, not the service functions: his press
    (PUT /api/room-controls) comes back "turning_on" straight away, and
    GET /api/engine/status's `ambient` key carries the frozen contract for
    anything polling it — including Home Assistant, which another captain
    builds against these exact names. Then it settles to "on" on its own,
    without the press ever having waited for it."""
    from fastapi.testclient import TestClient

    from spectra.app import create_app
    dev, events, clock = room
    _save(ambient_enabled=False)

    with TestClient(create_app()) as client:
        state = client.get("/api/room-controls").json()
        state["ambient_enabled"] = True
        state["ambient_color"] = CREAM
        put = client.put("/api/room-controls", json=state).json()
        assert put["ambient_result"]["status"] == "turning_on"
        assert put["ambient_result"]["phase"] == "turning_on"

        mid = client.get("/api/engine/status").json()["ambient"]
        assert mid["intent"] == "on"
        assert mid["phase"] == "turning_on"
        assert mid["enabled"] is True and mid["on_music_pause"] is False

        # The transition runs on the app's own loop while we poll — the
        # press never waited for it, which is the whole point.
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            end = client.get("/api/engine/status").json()["ambient"]
            if end["phase"] != "turning_on":
                break
            time.sleep(0.05)
        assert end["phase"] == "on" and end["held"] is True
    assert dev.frozen is True
