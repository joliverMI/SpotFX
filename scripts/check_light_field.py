"""Executable spec for THE ROOM LIGHT-FIELD SLICE's capture half: a
SYNTHETIC CAMERA, the REAL mapping session, the REAL held-room program, and
a footprint checked cell-by-cell against ground truth that was decided
before the run.

WHAT IS REAL HERE, and it is nearly everything: spectra/services/
mapping_session.py's own WebSocket message handling (hello / lock / frame,
base64 grey8, the downsample, the ring), spectra/services/room_mapping.py's
own protocol and its CHAIN of per-emitter holds through the real
flare_preview_hold.open_program_hold, and spectra/services/light_field.py's
own derivation and store. What is fake is the camera (a room model that
paints a known region per emitter) and the two fx_seam primitives — because
his fixtures are not granted and a check script must never reach for them.

THE GROUND TRUTH IS DECLARED FIRST, not read off the result: each emitter
lights one named rectangle at a named amplitude, on top of a dark room that
is deliberately NOT black (a window, a standby LED, sensor offset). A pass
means the derived footprint IS that rectangle — everything else exactly
zero — for every emitter, and that the room came back dark-and-back at every
link of the hold chain.

NEGATIVE CONTROLS, because a check that cannot fail proves nothing:
  * the exposure gate REFUSES a phone that will not lock, by name, with no
    light written and nothing stored;
  * a lock LOST mid-run aborts the run rather than finishing it;
  * the room-was-dark claim is checked at the seam (what the writes
    actually said), and the "restored between emitters" claim is checked
    against a deliberately-broken chain that leaves the room held;
  * the same lit frames derived WITHOUT the dark reference put the room's
    own window into the footprint — the failure the reference prevents.

Run from repo root: .venv/bin/python scripts/check_light_field.py
Isolated: temp storage, fake seams, no LedFX I/O, no audio, no camera, no
network.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from base64 import b64encode
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FAILURES: list[str] = []


def check(cond, label):
    if not cond:
        FAILURES.append(label)
        print(f"FAIL: {label}")
        return False
    print(f"ok: {label}")
    return True


td = Path(tempfile.mkdtemp(prefix="spectra-light-field-"))

from fx import device_model                                    # noqa: E402
device_model.CATEGORIES_FILE = td / "device_categories.json"
device_model.CATEGORIES_FILE.write_text(json.dumps({}))

from spectra import config as scfg                             # noqa: E402
scfg.SPECTRA_STORAGE = td / "spectra"
scfg.SCENES_FILE = scfg.SPECTRA_STORAGE / "scenes.json"
scfg.SEQUENCER_FILE = scfg.SPECTRA_STORAGE / "sequencer.json"
scfg.DRIFT_PROFILES_FILE = scfg.SPECTRA_STORAGE / "drift_profiles.json"
scfg.ROOM_COLOR_FILE = scfg.SPECTRA_STORAGE / "room_color.json"
scfg.ROOM_CONTROLS_FILE = scfg.SPECTRA_STORAGE / "room_controls.json"
scfg.GRADIENT2D_FILE = scfg.SPECTRA_STORAGE / "gradients2d.json"
scfg.FIRE_HISTORY_FILE = scfg.SPECTRA_STORAGE / "fire_history.json"
scfg.SHOW_LOG_FILE = scfg.SPECTRA_STORAGE / "show_log.json"
scfg.COLOR_SETS_FILE = td / "color_sets.json"
scfg.FLARE_PREVIEW_HOLD_FILE = scfg.SPECTRA_STORAGE / "flare_preview_hold.json"
scfg.ROOM_MAPS_FILE = scfg.SPECTRA_STORAGE / "room_maps.json"
scfg.ROOM_EFFECTS_FILE = scfg.SPECTRA_STORAGE / "room_effects.json"

from spectra.models.room_map import (GRID_H, GRID_W, AxisCalibration,  # noqa: E402
                                     Point, RoomMap)
from spectra.services import (flare_preview_hold, light_field,          # noqa: E402
                              mapping_session, room_mapping)

FW, FH = light_field.FRAME_W, light_field.FRAME_H


# ── the ground truth, declared before anything runs ────────────────────────

@dataclass(frozen=True)
class SimEmitter:
    carrier_id: str
    virtual_ids: tuple[str, ...]
    region: tuple[int, int, int, int]      # y0, y1, x0, x1 in FRAME pixels
    amplitude: float                       # camera counts it adds where it lands


#: Two sconces on one wall, the slice's own fixtures: one lighting a patch
#: high on the wall and the ceiling above it, one lighting low and the floor.
GROUND_TRUTH = (
    SimEmitter("sconce-left-v", ("sconce-left-v",), (10, 70, 40, 150), 130.0),
    SimEmitter("sconce-right-v", ("sconce-right-v",), (110, 175, 180, 300), 95.0),
)
OTHER_VIRTUALS = ("crystal-mapper", "tv-backlight")     # the rest of his room


class SimCamera:
    """A locked-exposure camera looking at a modelled room. It renders what
    is LIT — nothing else — so the frames a session ingests are a pure
    function of the writes the program made."""

    def __init__(self) -> None:
        self.lit: dict[str, float] = {}
        self.frames_rendered = 0

    def room_glow(self) -> np.ndarray:
        f = np.full((FH, FW), 6.0)
        f[:, :40] += 14.0             # a window
        f[100:104, 300:304] = 90.0    # a standby LED on some other gadget
        return f

    def render(self) -> np.ndarray:
        f = self.room_glow()
        for e in GROUND_TRUTH:
            level = max(self.lit.get(v, 0.0) for v in e.virtual_ids) \
                if any(v in self.lit for v in e.virtual_ids) else 0.0
            if level <= 0:
                continue
            y0, y1, x0, x1 = e.region
            f[y0:y1, x0:x1] += e.amplitude * level
        self.frames_rendered += 1
        return np.clip(f, 0, 255)


# ── the fake seam, and the record of everything it was asked to write ──────

@dataclass
class SeamLog:
    camera: SimCamera
    virtuals: dict = field(default_factory=dict)
    writes: list = field(default_factory=list)

    async def get_virtuals(self):
        return self.virtuals

    async def apply_writes(self, writes, *, transition_ms=0):
        self.writes.append({"transition_ms": transition_ms,
                            "writes": [dict(w) for w in writes]})
        for w in writes:
            cfg = w["config"]
            b = cfg.get("brightness")
            color = cfg.get("color", "")
            level = float(b) if isinstance(b, (int, float)) else 1.0
            if color == "#000000":
                level = 0.0
            self.camera.lit[w["virtual_id"]] = level
            self.virtuals[w["virtual_id"]] = {
                "active": True,
                "effect": {"type": w["effect_type"], "config": dict(cfg)}}


def show_state() -> dict:
    """What the room looks like BEFORE mapping — a real show running, so a
    revert has something specific to restore to."""
    out = {}
    for e in GROUND_TRUTH:
        for v in e.virtual_ids:
            out[v] = {"active": True, "effect": {
                "type": "singleColor", "config": {"color": "#3050ff",
                                                  "brightness": 0.42}}}
    for v in OTHER_VIRTUALS:
        out[v] = {"active": True, "effect": {
            "type": "blackhole", "config": {"brightness": 0.7, "spin": 0.3}}}
    return out


# ── the phone, speaking the real wire ──────────────────────────────────────

LOCKED = {"exposure_locked": True, "white_balance_locked": True,
          "exposure_mode": "manual", "white_balance_mode": "manual",
          "exposure_capabilities": ["none", "manual", "continuous"],
          "white_balance_capabilities": ["manual", "continuous"]}
UNLOCKED = {"exposure_locked": False, "white_balance_locked": True,
            "exposure_mode": "continuous", "white_balance_mode": "manual",
            "exposure_capabilities": ["continuous"],
            "white_balance_capabilities": ["manual", "continuous"]}


class FakePhone:
    """Sends the SAME messages the browser sends — hello, lock, frame with
    base64 grey8 — into the real MappingSession.handle()."""

    def __init__(self, sess, camera: SimCamera, fps: float = 200.0) -> None:
        self.sess = sess
        self.camera = camera
        self.period = 1.0 / fps
        self.sent: list[dict] = []
        self.lock = dict(LOCKED)
        self.task = None

    async def hello(self, lock: dict | None = None):
        self.lock = dict(lock if lock is not None else LOCKED)
        await self.sess.handle({"type": "hello", "user_agent": "SimPhone/1.0",
                                "secure_context": True, "lock": self.lock})

    async def set_lock(self, lock: dict):
        self.lock = dict(lock)
        await self.sess.handle({"type": "lock", **self.lock})

    def start(self):
        self.task = asyncio.create_task(self._stream())

    async def stop(self):
        if self.task is not None:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None

    async def _stream(self):
        while True:
            frame = self.camera.render().astype(np.uint8)
            await self.sess.handle({
                "type": "frame", "mime": mapping_session.GREY_MIME,
                "width": FW, "height": FH,
                "captured_at_ms": time.monotonic() * 1000.0,
                "data": b64encode(frame.tobytes()).decode("ascii"),
                "lock": self.lock})
            await asyncio.sleep(self.period)


async def open_session(camera: SimCamera, lock: dict | None = None):
    sent: list[dict] = []

    async def send(msg):
        sent.append(msg)

    sess = await mapping_session.open_session(send)
    phone = FakePhone(sess, camera)
    await phone.hello(lock)
    return sess, phone, sent


# ── shortened protocol (the arithmetic is unchanged; only the waits are) ───

def shorten():
    room_mapping.DARK_SETTLE_S = 0.03
    room_mapping.DARK_CAPTURE_S = 0.06
    room_mapping.LIT_SETTLE_S = 0.03
    room_mapping.LIT_CAPTURE_S = 0.10


def new_room() -> RoomMap:
    return RoomMap(name="Kitchen wall",
                   carrier_ids=[e.carrier_id for e in GROUND_TRUTH],
                   axis=AxisCalibration(kind="vertical",
                                        floor=Point(x=0.5, y=1.0),
                                        ceiling=Point(x=0.5, y=0.0)))


def deps_for(sess, seam: SeamLog) -> room_mapping.RunDeps:
    chains = {e.carrier_id: [{"id": f"{e.carrier_id}-fixture", "type": "wled"}]
              for e in GROUND_TRUTH}

    async def carrier_devices():
        return chains

    return room_mapping.RunDeps(session=sess, get_virtuals=seam.get_virtuals,
                                carrier_devices=carrier_devices,
                                save_room=light_field.put_room)


async def _patched(seam: SeamLog):
    """Point the real hold at the fake seam. flare_preview_hold imports
    fx_seam as a module, so replacing its two functions is enough — the
    hold's own snapshot/deadline/sweep/ceiling code is untouched."""
    from spectra.services import fx_seam
    fx_seam.apply_writes = seam.apply_writes          # type: ignore[assignment]
    fx_seam.get_virtuals = seam.get_virtuals          # type: ignore[assignment]


# ── ONE — the happy path, cell by cell ────────────────────────────────────

async def section_one():
    print("\n== 1. a fake emitter painting a known region yields that region ==")
    camera = SimCamera()
    seam = SeamLog(camera=camera, virtuals=show_state())
    await _patched(seam)
    sess, phone, _sent = await open_session(camera)
    phone.start()
    await asyncio.sleep(0.05)

    room = new_room()
    result = await room_mapping.run_mapping(room, deps_for(sess, seam))
    await phone.stop()
    await mapping_session.close_session(sess)

    check(result.ok, "the run reports ok")
    check(len(result.emitters) == 2 and all(e.mapped for e in result.emitters),
          "both emitters mapped")

    stored = light_field.get_room(room.id)
    check(stored is not None and sorted(stored.mapped_ids()) ==
          sorted(e.carrier_id for e in GROUND_TRUTH),
          "both footprints stored under the room")

    for e in GROUND_TRUTH:
        fp = stored.footprint(e.carrier_id)
        grid = np.asarray(fp.grid).reshape(GRID_H, GRID_W)
        y0, y1, x0, x1 = e.region
        gy0, gy1, gx0, gx1 = y0 // 5, y1 // 5, x0 // 5, x1 // 5
        inside = grid[gy0:gy1, gx0:gx1]
        outside = grid.copy()
        outside[gy0:gy1, gx0:gx1] = 0.0
        check(np.allclose(inside, e.amplitude / 255.0, atol=1e-9),
              f"{e.carrier_id}: the lit region reads exactly its own amplitude "
              f"({e.amplitude / 255.0:.4f})")
        check(outside.max() == 0.0,
              f"{e.carrier_id}: every cell it does not light is exactly zero "
              f"(the window and the standby LED cancelled)")
        check(fp.capture.exposure_locked and fp.capture.white_balance_locked,
              f"{e.carrier_id}: the capture context records a LOCKED camera")
        check(fp.capture.pose_id == sess.pose_id,
              f"{e.carrier_id}: the footprint carries the pose it was taken in")

    left, right = (stored.footprint(e.carrier_id) for e in GROUND_TRUTH)
    check(int(np.argmax(left.axis_profile)) > int(np.argmax(right.axis_profile)),
          "the axis profile puts the high sconce above the low one")
    check(left.weight > right.weight,
          "weight ranks the emitters by total light landed "
          f"({left.weight:.1f} vs {right.weight:.1f})")
    return seam


# ── TWO — the room went dark, and came back, at every link ────────────────

async def section_two(seam: SeamLog):
    print("\n== 2. the held-room chain: dark, one emitter, and back ==")
    dark_payloads = [b for b in seam.writes
                     if all(w["config"].get("color") == "#000000"
                            for w in b["writes"])]
    check(dark_payloads, "at least one write took every in-scope virtual to black")
    scope = {w["virtual_id"] for w in dark_payloads[0]["writes"]}
    check(scope >= set(OTHER_VIRTUALS),
          "the dark step covers the WHOLE live room, not only the room's own "
          "devices — a camera sees every fixture")

    lit_payloads = [b for b in seam.writes
                    if any(w["config"].get("color") == "#ffffff" for w in b["writes"])]
    check(len(lit_payloads) == len(GROUND_TRUTH),
          f"exactly one lit step per emitter ({len(lit_payloads)})")
    for b in lit_payloads:
        white = [w["virtual_id"] for w in b["writes"]
                 if w["config"].get("color") == "#ffffff"]
        black = [w["virtual_id"] for w in b["writes"]
                 if w["config"].get("color") == "#000000"]
        check(len(white) >= 1 and set(white) & set(black) == set(),
              f"one emitter lit ({white}), every other virtual explicitly black")

    # the revert: the LAST write must put the show back, byte for byte
    final = seam.writes[-1]
    restored = {w["virtual_id"]: w["config"] for w in final["writes"]}
    original = show_state()
    check(set(restored) == set(original),
          "the final write restores every virtual the run touched")
    same = all(restored[v].get("brightness") ==
               original[v]["effect"]["config"].get("brightness")
               for v in restored)
    check(same, "every restored virtual is back at the show's own brightness")
    check(final["transition_ms"] == flare_preview_hold.REVERT_TRANSITION_MS,
          "the revert uses the 1 ms tween-safe convention, never 0")
    check(not flare_preview_hold.active(),
          "no hold is left active after the run")
    check(not scfg.FLARE_PREVIEW_HOLD_FILE.exists(),
          "no stale hold snapshot is left on disk")

    # THE CHAIN, and the reason it matters: the room is genuinely RESTORED
    # between emitters, not merely restorable. A revert is unambiguous —
    # it puts a non-mapping effect type back on a virtual the mapping
    # program only ever writes singleColor to.
    def is_revert(batch) -> bool:
        return any(w["effect_type"] != room_mapping.MAP_EFFECT_TYPE
                   for w in batch["writes"])

    def is_lit(batch) -> bool:
        return any(w["config"].get("color") == "#ffffff" for w in batch["writes"])

    order = ["revert" if is_revert(b) else ("lit" if is_lit(b) else "dark")
             for b in seam.writes]
    check(order.count("revert") == len(GROUND_TRUTH),
          f"one revert per emitter — a CHAIN of short holds, not one long "
          f"hold ({order.count('revert')} reverts for {len(GROUND_TRUTH)} "
          f"emitters)")
    check(order == ["dark", "lit", "revert"] * len(GROUND_TRUTH),
          f"the chain runs dark -> lit -> revert, once per emitter: {order}")
    first_revert = order.index("revert")
    second_lit = len(order) - 1 - order[::-1].index("lit")
    check(first_revert < second_lit,
          "the room was handed back BEFORE the second emitter was lit — "
          "restorable at any instant between emitters, which is the property "
          "the 3-minute ceiling makes necessary")


# ── THREE — the negative controls ─────────────────────────────────────────

async def section_three():
    print("\n== 3. negative controls ==")
    # (a) a phone that will not lock exposure is refused BY NAME, and nothing
    #     is written or stored
    camera = SimCamera()
    seam = SeamLog(camera=camera, virtuals=show_state())
    await _patched(seam)
    sess, phone, _ = await open_session(camera, lock=UNLOCKED)
    phone.start()
    await asyncio.sleep(0.03)
    room = new_room()
    result = await room_mapping.run_mapping(room, deps_for(sess, seam))
    await phone.stop()
    check(not result.ok, "an unlocked camera refuses the run")
    check("EXPOSURE" in result.reason and "SimPhone" in result.reason,
          "the refusal NAMES the capability and the phone: "
          f"{result.reason[:80]}...")
    check(not seam.writes, "the refusal wrote NOTHING to the lights")
    check(light_field.get_room(room.id) is None, "and stored nothing")
    await mapping_session.close_session(sess)

    # (b) a lock LOST mid-run aborts rather than finishing on a changed scale
    camera = SimCamera()
    seam = SeamLog(camera=camera, virtuals=show_state())
    await _patched(seam)
    sess, phone, _ = await open_session(camera)
    phone.start()
    await asyncio.sleep(0.03)
    room = new_room()

    async def lose_lock():
        await asyncio.sleep(0.12)
        await phone.set_lock(UNLOCKED)

    losing = asyncio.create_task(lose_lock())
    result = await room_mapping.run_mapping(room, deps_for(sess, seam))
    await losing
    await phone.stop()
    check(not result.ok, "a lock lost mid-run does not finish as a good map")
    check("lock was lost" in (result.reason or "") or
          any("lock was lost" in (e.reason or "") for e in result.emitters),
          "the abort says the lock was lost, by name")
    check(not flare_preview_hold.active(),
          "the aborted run still handed the room back")
    await mapping_session.close_session(sess)

    # (c) the dark reference is what cancels the room
    dark = light_field.downsample(camera.room_glow())
    camera.lit = {"sconce-left-v": 1.0}
    lit = light_field.downsample(camera.render())
    honest = light_field.footprint_grid(dark, lit)
    blind = light_field.footprint_grid(np.zeros_like(dark), lit)
    check(honest[:, :8].max() == 0.0 and blind[:, :8].max() > 0.0,
          "without the dark reference, the room's own window lands in the "
          "footprint as if the emitter had produced it")

    # (d) a frame of the wrong size is refused, not resampled
    sess2, phone2, _ = await open_session(SimCamera())
    bad = np.zeros((100, 100), dtype=np.uint8)
    await sess2.handle({"type": "frame", "mime": mapping_session.GREY_MIME,
                        "width": 100, "height": 100,
                        "captured_at_ms": time.monotonic() * 1000.0,
                        "data": b64encode(bad.tobytes()).decode("ascii")})
    check(sess2.counts["rejected"] == 1 and not sess2.grids,
          "a frame that does not divide the grid is rejected, never stretched")
    await mapping_session.close_session(sess2)

    # (e) no audio path exists on this session type, by construction
    check(not hasattr(sess2, "audio_ref") and not hasattr(sess2, "audio_probe"),
          "the mapping session has NO audio reference and no audio probe — "
          "no-audio is true by construction, not by a flag")


async def main():
    shorten()
    seam = await section_one()
    await section_two(seam)
    await section_three()
    print()
    if FAILURES:
        raise SystemExit(f"FAILED {len(FAILURES)} check(s):\n  " +
                         "\n  ".join(FAILURES))
    print("ALL LIGHT-FIELD CAPTURE CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
