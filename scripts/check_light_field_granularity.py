"""Executable spec for SUB-DEVICE GRANULARITY in the room light-field
capture — his own correction: "A single device that spans the direction of
the wave should be able to show the effect. the tv mapper is wrapped around
a tv. It should be able to run a dimness wave vertically."

WHAT IS REAL HERE, and it is nearly everything: the REAL enumeration
(spectra/services/emitters.py), the REAL mapping session and its WebSocket
message handling, the REAL held-room chain through
flare_preview_hold.open_program_hold, the REAL derivation and store, and —
in section ONE — the REAL vendored render pipeline through fx.headless,
because a lamp that lights the wrong pixels would make every footprint
after it wrong in a way no later check could see. What is fake is the
camera (a room model that paints a known region PER PIXEL) and, from
section two on, the two fx_seam primitives — his fixtures are not granted
and a check script must never reach for them.

THE GROUND TRUTH IS DECLARED FIRST, not read off the result. A synthetic
60-pixel strip wrapped round a television in three 20-pixel runs; each
PIXEL paints one named rectangle of the camera frame at a named amplitude,
on top of a room glow that is deliberately not black. A pass means:

  1. the range lamp lights EXACTLY its range on the real render pipeline,
     and exactly nothing else — measured on assembled pixels;
  2. capture at SEGMENT granularity yields THREE footprints, each equal
     cell-for-cell to its own segment's painted region, and pairwise
     disjoint — three distinct measurements, not one smeared one;
  3. the NEGATIVE CONTROL: the same room at DEVICE granularity yields ONE
     footprint, equal to the union of the three;
  4. the enumeration's own rules — "auto" resolves per device (a Hue bulb
     is never split), a copy-mapping virtual is reported rather than
     silently mis-mapped, block granularity subdivides regardless of how
     the config is segmented, and the run cap holds;
  5. a sub-device run is REFUSED by name when SPECTRA does not own the
     lights, with nothing written.

Run from repo root: .venv/bin/python scripts/check_light_field_granularity.py
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

print = __import__("functools").partial(print, flush=True)   # noqa: A001

FAILURES: list[str] = []


def check(cond, label):
    if not cond:
        FAILURES.append(label)
        print(f"FAIL: {label}")
        return False
    print(f"ok: {label}")
    return True


td = Path(tempfile.mkdtemp(prefix="spectra-granularity-"))

from fx import device_model                                    # noqa: E402
device_model.CATEGORIES_FILE = td / "device_categories.json"
device_model.CATEGORIES_FILE.write_text(json.dumps({}))

from spectra import config as scfg                             # noqa: E402
scfg.SPECTRA_STORAGE = td / "spectra"
for name in ("SCENES_FILE", "SEQUENCER_FILE", "DRIFT_PROFILES_FILE",
             "ROOM_COLOR_FILE", "ROOM_CONTROLS_FILE", "GRADIENT2D_FILE",
             "FIRE_HISTORY_FILE", "SHOW_LOG_FILE", "FLARE_PREVIEW_HOLD_FILE",
             "ROOM_MAPS_FILE", "ROOM_EFFECTS_FILE"):
    setattr(scfg, name, scfg.SPECTRA_STORAGE / f"{name.lower()}.json")
scfg.COLOR_SETS_FILE = td / "color_sets.json"

from fx import light_ownership                                 # noqa: E402
light_ownership.OWNERSHIP_FILE = td / "ownership.json"
light_ownership.OWNERSHIP_FILE.write_text(json.dumps({"owner": "spectra"}))

from spectra.models.room_map import (GRID_H, GRID_W, AxisCalibration,  # noqa: E402
                                     Point, RoomMap)
from spectra.services import emitters as emitters_mod          # noqa: E402
from spectra.services import (flare_preview_hold, light_field,  # noqa: E402
                              mapping_session, room_mapping)

FW, FH = light_field.FRAME_W, light_field.FRAME_H

# ── the ground truth, declared before anything runs ────────────────────────

DEVICE = "tv-mapper"
VIRTUAL = "tv-mapper-v"
PIXELS = 60
SEG = 20                       # three runs of twenty: left, top, right
AMP = 110.0                    # camera counts one lit pixel adds in its rect


#: Anything below this in a footprint is not light. A footprint is in units
#: of camera bytes / 255, so ONE camera count is 3.9e-3; this is twelve
#: orders of magnitude below that. It exists because averaging a different
#: NUMBER of identical frames for the dark reference and the lit capture
#: leaves a ~1e-17 float residue in cells whose box mean is not exactly
#: representable, and `clip(lit - dark, 0)` keeps a positive one. Real, and
#: not a measurement.
NOISE_FLOOR = 1e-9


def pixel_region(i: int) -> tuple[int, int, int, int]:
    """Where pixel `i` of the wrapped strip puts its light, in FRAME pixels.

    Declared as ground truth, and deliberately DIFFERENT and DISJOINT for
    the three runs: up the left side of the television, across the top, down
    the right. This is a model of a camera's view, not a claim about the
    room — nothing in the code under test ever sees it."""
    if i < SEG:                                        # left run, bottom->top
        top = 145 - (i * 5)
        return (top, top + 5, 40, 80)
    if i < 2 * SEG:                                    # top run, left->right
        j = i - SEG
        left = 40 + j * 10
        return (10, 40, left, left + 10)
    j = i - 2 * SEG                                    # right run, top->bottom
    top = 50 + (j * 5)
    return (top, top + 5, 240, 280)


SEGMENTS = {0: range(0, SEG), 1: range(SEG, 2 * SEG), 2: range(2 * SEG, PIXELS)}


def region_mask(pixels) -> np.ndarray:
    """The GRID cells the given strip pixels light — the ground truth every
    derived footprint is compared against, cell for cell."""
    frame = np.zeros((FH, FW))
    for i in pixels:
        y0, y1, x0, x1 = pixel_region(i)
        frame[y0:y1, x0:x1] = 1.0
    return light_field.downsample(frame) > 0.0


class SimCamera:
    """A locked-exposure camera looking at a modelled room. It renders what
    is LIT — per PIXEL — so the frames a session ingests are a pure function
    of the writes the program made, at any granularity."""

    def __init__(self) -> None:
        self.lit: dict[str, set] = {}
        self.frames_rendered = 0

    def room_glow(self) -> np.ndarray:
        f = np.full((FH, FW), 7.0)
        f[:, :30] += 12.0              # a window
        f[120:124, 300:304] = 90.0     # a standby LED on some other gadget
        return f

    def render(self) -> np.ndarray:
        f = self.room_glow()
        for i in self.lit.get(VIRTUAL, ()):
            y0, y1, x0, x1 = pixel_region(i)
            f[y0:y1, x0:x1] += AMP
        self.frames_rendered += 1
        return np.clip(f, 0, 255)


# ── the fake seam, and the record of everything it was asked to write ──────

def _live_entry(effect_type: str, cfg: dict) -> dict:
    return {"active": True, "pixel_count": PIXELS,
            "config": {"name": VIRTUAL, "mapping": "span", "grouping": 1},
            "segments": [[DEVICE, 0, SEG - 1, False],
                         [DEVICE, SEG, 2 * SEG - 1, False],
                         [DEVICE, 2 * SEG, PIXELS - 1, False]],
            "effect": {"type": effect_type, "config": dict(cfg)}}


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
            level = float(b) if isinstance(b, (int, float)) else 1.0
            black = cfg.get("color", "") == "#000000" or level <= 0.0
            if black:
                lit = set()
            elif w["effect_type"] == room_mapping.RANGE_EFFECT_TYPE:
                start = int(cfg.get("range_start", 0))
                end = int(cfg.get("range_end", -1))
                end = PIXELS - 1 if end < 0 else min(end, PIXELS - 1)
                lit = set(range(max(0, start), end + 1))
            else:
                lit = set(range(PIXELS))
            self.camera.lit[w["virtual_id"]] = lit
            entry = _live_entry(w["effect_type"], cfg)
            self.virtuals[w["virtual_id"]] = entry


def show_state() -> dict:
    """What the room looks like BEFORE mapping — a real show running, so a
    revert has something specific to restore to."""
    return {VIRTUAL: _live_entry("singleColor",
                                 {"color": "#3050ff", "brightness": 0.42})}


# ── the phone, speaking the real wire ──────────────────────────────────────

LOCKED = {"exposure_locked": True, "white_balance_locked": True,
          "exposure_mode": "manual", "white_balance_mode": "manual",
          "exposure_capabilities": ["none", "manual", "continuous"],
          "white_balance_capabilities": ["manual", "continuous"]}


class FakePhone:
    def __init__(self, sess, camera: SimCamera, fps: float = 200.0) -> None:
        self.sess = sess
        self.camera = camera
        self.period = 1.0 / fps
        self.lock = dict(LOCKED)
        self.task = None

    async def hello(self):
        await self.sess.handle({"type": "hello", "user_agent": "SimPhone/1.0",
                                "secure_context": True, "lock": self.lock})

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


def shorten():
    room_mapping.DARK_SETTLE_S = 0.03
    room_mapping.DARK_CAPTURE_S = 0.06
    room_mapping.LIT_SETTLE_S = 0.03
    room_mapping.LIT_CAPTURE_S = 0.10


AXIS = AxisCalibration(kind="vertical", floor=Point(x=0.5, y=1.0),
                       ceiling=Point(x=0.5, y=0.0))


def new_room() -> RoomMap:
    return RoomMap(name="Living room", device_ids=[DEVICE], axis=AXIS)


def deps_for(sess, seam: SeamLog, owns: bool = True) -> room_mapping.RunDeps:
    async def virtuals_for_device(device_id):
        return [VIRTUAL] if device_id == DEVICE else []

    async def device_type(_device_id):
        return "wled"

    return room_mapping.RunDeps(session=sess, get_virtuals=seam.get_virtuals,
                                virtuals_for_device=virtuals_for_device,
                                device_type=device_type,
                                spectra_owns=lambda: owns,
                                save_room=light_field.put_room)


async def _patched(seam: SeamLog):
    from spectra.services import fx_seam
    fx_seam.apply_writes = seam.apply_writes          # type: ignore[assignment]
    fx_seam.get_virtuals = seam.get_virtuals          # type: ignore[assignment]


async def open_session(camera: SimCamera):
    async def send(_msg):
        pass

    sess = await mapping_session.open_session(send)
    phone = FakePhone(sess, camera)
    await phone.hello()
    return sess, phone


async def run_at(granularity: str, block_pixels: int = 30, owns: bool = True):
    camera = SimCamera()
    seam = SeamLog(camera=camera, virtuals=show_state())
    await _patched(seam)
    sess, phone = await open_session(camera)
    phone.start()
    await asyncio.sleep(0.05)
    room = new_room()
    result = await room_mapping.run_mapping(room, deps_for(sess, seam, owns),
                                            granularity=granularity,
                                            block_pixels=block_pixels)
    await phone.stop()
    await mapping_session.close_session(sess)
    return result, light_field.get_room(room.id), seam


# ── ONE — the range lamp on the REAL render pipeline ───────────────────────

async def section_one():
    print("\n== 1. the range lamp lights EXACTLY its range, on the real "
          "render pipeline ==")
    from fx import facade, headless
    from fx.consts import CONFIGURATION_VERSION
    from fx.host import FxHost

    config_dir = str(td / "fx-lamp")
    os.makedirs(config_dir, exist_ok=True)
    with open(os.path.join(config_dir, "config.json"), "w") as fh:
        json.dump({"configuration_version": CONFIGURATION_VERSION,
                   "devices": [{"id": DEVICE, "type": "dummy",
                                "config": {"name": DEVICE,
                                           "pixel_count": PIXELS}}],
                   "virtuals": [{"id": DEVICE, "is_device": DEVICE,
                                 "auto_generated": False,
                                 "config": {"name": DEVICE, "mapping": "span",
                                            "rows": 1},
                                 "segments": [[DEVICE, 0, PIXELS - 1, False]]}]},
                  fh)
    headless.silence_audio()
    host = FxHost(config_dir)
    await host.start()
    host.audio = headless.SyntheticAudioSource()
    facade.set_host(host)
    virtual = host.virtuals.get(DEVICE)

    headless.attach_effect(host, virtual, room_mapping.RANGE_EFFECT_TYPE,
                           {"color": "#ffffff", "range_start": SEG,
                            "range_end": 2 * SEG - 1, "brightness": 1.0,
                            "background_brightness": 0.0})
    frame = np.asarray(virtual.assemble_frame())
    inside = frame[SEG:2 * SEG]
    outside = np.concatenate([frame[:SEG], frame[2 * SEG:]])
    check(inside.min() > 200.0,
          f"every pixel of the range is lit (min {inside.min():.0f}/255)")
    check(float(np.abs(outside).max()) == 0.0,
          f"and every pixel outside it is EXACTLY zero "
          f"(max {float(np.abs(outside).max()):.3f}) — the dark reference "
          f"this footprint is subtracted against is genuinely dark")

    # the whole-device control, the shipped lamp
    headless.attach_effect(host, virtual, room_mapping.MAP_EFFECT_TYPE,
                           {"color": "#ffffff", "brightness": 1.0,
                            "background_brightness": 0.0})
    whole = np.asarray(virtual.assemble_frame())
    check(whole.min() > 200.0,
          "the whole-device lamp still lights every pixel — the shipped "
          "primitive is untouched")

    # an inverted / out-of-bounds range lights NOTHING rather than guessing
    headless.attach_effect(host, virtual, room_mapping.RANGE_EFFECT_TYPE,
                           {"color": "#ffffff", "range_start": 40,
                            "range_end": 10, "brightness": 1.0,
                            "background_brightness": 0.0})
    inverted = np.asarray(virtual.assemble_frame())
    check(float(np.abs(inverted).max()) == 0.0,
          "an inverted range lights nothing at all — a capture that "
          "photographs the wrong pixels is worse than one that reports no "
          "measurable light, which the run already says by name")

    check(room_mapping.RANGE_EFFECT_TYPE not in device_model.effect_types(),
          "the range lamp is REGISTRY-EXEMPT: absent from the effect-param "
          "registry, so it never reaches an authoring surface")
    check(device_model.effect_params(room_mapping.RANGE_EFFECT_TYPE) == {},
          "and the seam's own param rounding is a no-op for it rather than "
          "an error")


# ── TWO — capture at segment granularity, cell by cell ────────────────────

async def section_two():
    print("\n== 2. SEGMENT granularity: three distinct footprints, each its "
          "own segment's painted region ==")
    result, stored, seam = await run_at("segment")
    check(result.ok, f"the run reports ok ({result.reason})")
    check(result.per_device.get(DEVICE) == "segment",
          f"the device resolved to segment granularity "
          f"({result.per_device.get(DEVICE)})")
    check(len(result.emitters) == 3 and all(e.mapped for e in result.emitters),
          f"three emitters, all mapped ({len(result.emitters)})")

    ids = [e.emitter_id for e in result.emitters]
    check(all(i.startswith(f"{DEVICE}:seg") and "[" in i for i in ids),
          f"the NEW id shape the schema anticipated: {ids}")
    check(len(set(ids)) == 3, "and every id is distinct")

    masks = []
    for n, (index, pixels) in enumerate(sorted(SEGMENTS.items())):
        fp = stored.footprints[n] if n < len(stored.footprints) else None
        fp = next((f for f in stored.footprints
                   if f.ranges and f.ranges[0].start == pixels[0]), None)
        if fp is None:
            check(False, f"segment {index}: a footprint was stored for it")
            continue
        grid = np.asarray(fp.grid).reshape(GRID_H, GRID_W)
        truth = region_mask(pixels)
        got = grid > NOISE_FLOOR
        masks.append(got)
        if not (got == truth).all():
            bad = np.argwhere(got != truth)[:6]
            print("    DEBUG disagreeing cells:",
                  [(int(r), int(c), float(grid[r, c]), bool(truth[r, c]))
                   for r, c in bad])
        check(bool((got == truth).all()),
              f"segment {index}: the footprint IS its own painted region, "
              f"cell for cell ({int(got.sum())} lit cells, "
              f"{int((got != truth).sum())} disagreeing)")
        check(float(grid[~truth].max() if (~truth).any() else 0.0) < NOISE_FLOOR,
              f"segment {index}: everything it does not light reads as no "
              f"light at all — the window and the standby LED cancelled "
              f"(max {float(grid[~truth].max() if (~truth).any() else 0.0):.2e}, "
              f"vs 3.9e-03 for one camera count)")
        check(fp.device == DEVICE and fp.ranges
              and fp.ranges[0].virtual_id == VIRTUAL
              and (fp.ranges[0].start, fp.ranges[0].end)
              == (pixels[0], pixels[-1]),
              f"segment {index}: the stored range is the addressing fact "
              f"({fp.ranges[0].start}-{fp.ranges[0].end} of {VIRTUAL})")

    if len(masks) == 3:
        overlap = [(a, b) for a in range(3) for b in range(a + 1, 3)
                   if (masks[a] & masks[b]).any()]
        check(not overlap,
              "the three footprints are pairwise DISJOINT — three distinct "
              "measurements, not one smeared one")

    check(stored.mapped_devices() == [DEVICE] and stored.unmapped_ids() == [],
          "the DEVICE reads as mapped even though no emitter carries its id")

    lit_writes = [w for burst in seam.writes for w in burst["writes"]
                  if w["effect_type"] == room_mapping.RANGE_EFFECT_TYPE]
    check(len(lit_writes) == 3,
          f"exactly one range write per emitter ({len(lit_writes)})")
    check(all(w["config"]["color"] == room_mapping.WHITE for w in lit_writes),
          "every range write is full white through the one write seam")
    return masks


# ── THREE — the negative control: device granularity merges them ──────────

async def section_three(segment_masks):
    print("\n== 3. NEGATIVE CONTROL: device granularity yields ONE merged "
          "footprint ==")
    result, stored, _seam = await run_at("device")
    check(result.ok and len(result.emitters) == 1,
          f"one emitter ({len(result.emitters)})")
    check(result.emitters[0].emitter_id == DEVICE,
          f"whose id is the DEVICE id, byte-identical to the shipped slice "
          f"({result.emitters[0].emitter_id})")
    fp = stored.footprint(DEVICE)
    check(fp is not None and fp.whole_device and not fp.ranges,
          "and it carries no ranges — the whole-device shape every already-"
          "stored footprint has")
    merged = np.asarray(fp.grid).reshape(GRID_H, GRID_W) > NOISE_FLOOR
    union = segment_masks[0] | segment_masks[1] | segment_masks[2]
    check(bool((merged == union).all()),
          f"the merged footprint IS the union of the three segment ones "
          f"({int(merged.sum())} cells vs {int(union.sum())}) — which is "
          f"exactly why a wave over it can only dim the whole television at "
          f"once, and what his correction was about")
    truth_axis = [float(np.asarray(f).sum()) for f in segment_masks]
    check(min(truth_axis) > 0 and merged.sum() > max(
        int(m.sum()) for m in segment_masks),
        "the whole device lands strictly more light than any one of its runs")


# ── FOUR — the enumeration's own rules ────────────────────────────────────

def _v(pixel_count: int, segments, mapping="span", grouping=1) -> dict:
    return {"active": True, "pixel_count": pixel_count,
            "config": {"mapping": mapping, "grouping": grouping},
            "segments": segments,
            "effect": {"type": "singleColor", "config": {}}}


def section_four():
    print("\n== 4. the enumeration's own rules ==")
    strip = {VIRTUAL: _v(PIXELS, [[DEVICE, 0, SEG - 1, False],
                                  [DEVICE, SEG, 2 * SEG - 1, False],
                                  [DEVICE, 2 * SEG, PIXELS - 1, False]])}

    auto = emitters_mod.enumerate_device(DEVICE, [VIRTUAL], strip,
                                         granularity="auto", device_type="wled")
    check(len(auto) == 3,
          f"'auto' gives a WLED strip SEGMENT granularity ({len(auto)} "
          f"emitters) — his 'default segment for strips'")
    bulb = {"hue-v": _v(1, [["hue-bulb", 0, 0, False]])}
    auto_hue = emitters_mod.enumerate_device("hue-bulb", ["hue-v"], bulb,
                                             granularity="auto",
                                             device_type="hue")
    check(len(auto_hue) == 1 and auto_hue[0].whole_device,
          "'auto' gives a Hue bulb WHOLE-DEVICE granularity — his 'device "
          "for Hue', resolved PER DEVICE, never a global")
    forced = emitters_mod.enumerate_device("hue-bulb", ["hue-v"], bulb,
                                           granularity="segment",
                                           device_type="hue")
    check(len(forced) == 1 and forced[0].whole_device and forced[0].note,
          f"forcing a split on a single point of light is REPORTED, not "
          f"silently mis-mapped: {forced[0].note!r}")

    blocks = emitters_mod.enumerate_device(DEVICE, [VIRTUAL], strip,
                                           granularity="block",
                                           block_pixels=10)
    spans = [(e.ranges[0].start, e.ranges[0].end) for e in blocks]
    check(len(blocks) == 6 and spans[0] == (0, 9) and spans[-1] == (50, 59),
          f"'block' subdivides regardless of how the config is segmented "
          f"({len(blocks)} blocks of 10: {spans})")
    covered = set()
    for lo, hi in spans:
        covered |= set(range(lo, hi + 1))
    check(covered == set(range(PIXELS)),
          "and the blocks cover every pixel exactly once, with the last "
          "absorbing the remainder rather than leaving a stub emitter")
    odd = emitters_mod.enumerate_device(DEVICE, [VIRTUAL], strip,
                                        granularity="block", block_pixels=25)
    check([(e.ranges[0].start, e.ranges[0].end) for e in odd] == [(0, 24), (25, 59)],
          "a block size that does not divide evenly puts the remainder in "
          "the LAST block — a two-pixel tail emitter would cost a full "
          "four-second capture to measure almost nothing")

    copied = {VIRTUAL: _v(PIXELS, strip[VIRTUAL]["segments"], mapping="copy")}
    cp = emitters_mod.enumerate_device(DEVICE, [VIRTUAL], copied,
                                       granularity="segment")
    check(len(cp) == 1 and cp[0].whole_device and "copies" in cp[0].note,
          f"a COPY-mapping virtual cannot light one segment alone, and says "
          f"so: {cp[0].note!r}")

    grouped = {VIRTUAL: _v(PIXELS, strip[VIRTUAL]["segments"], grouping=2)}
    g = emitters_mod.enumerate_device(DEVICE, [VIRTUAL], grouped,
                                      granularity="segment")
    check(emitters_mod.effective_pixel_count(grouped[VIRTUAL]) == 30
          and [(e.ranges[0].start, e.ranges[0].end) for e in g]
          == [(0, 9), (10, 19), (20, 29)],
          "pixel GROUPING is honoured: ranges are in the virtual's EFFECT "
          "pixel space, the same space the lamp lights and the mask indexes")

    big = {VIRTUAL: _v(4000, [[DEVICE, 0, 3999, False]])}
    plan = emitters_mod.plan_run([DEVICE], big, {DEVICE: [VIRTUAL]},
                                 {DEVICE: "wled"}, granularity="block",
                                 block_pixels=1)
    check(plan.truncated and len(plan.emitters) == emitters_mod.MAX_EMITTERS_PER_RUN
          and plan.problems,
          f"a mis-set block size is capped and NAMED, never an eight-hour "
          f"dark room ({len(plan.emitters)} emitters, "
          f"{plan.problems[-1][:60]}...)")
    ok_plan = emitters_mod.plan_run([DEVICE], strip, {DEVICE: [VIRTUAL]},
                                    {DEVICE: "wled"}, granularity="segment")
    check(ok_plan.seconds > 0 and ok_plan.as_dict()["count"] == 3,
          f"a plan says how long the room is dark before he presses "
          f"({ok_plan.seconds}s for 3 emitters)")


# ── FIVE — ownership refusal ──────────────────────────────────────────────

async def section_five():
    print("\n== 5. a sub-device run is REFUSED when SPECTRA does not own "
          "the lights ==")
    result, stored, seam = await run_at("segment", owns=False)
    check(not result.ok and "SPECTRA" in result.reason,
          f"refused by name: {result.reason[:90]}...")
    check(not result.emitters, "no emitter was attempted")
    lit = [w for burst in seam.writes for w in burst["writes"]
           if w["config"].get("color") == room_mapping.WHITE]
    check(not lit, "and NOTHING was written to the lights")
    check(stored is None or not stored.footprints,
          "and nothing was stored")

    result, _stored, seam = await run_at("device", owns=False)
    check(result.ok,
          "a WHOLE-DEVICE run is unaffected — it uses the shipped lamp, "
          "which the external LedFX service does have")


async def main():
    shorten()
    await section_one()
    masks = await section_two()
    if len(masks) == 3:
        await section_three(masks)
    section_four()
    await section_five()
    print()
    if FAILURES:
        raise SystemExit(f"FAILED {len(FAILURES)} check(s):\n  " +
                         "\n  ".join(FAILURES))
    print("ALL LIGHT-FIELD GRANULARITY CHECKS PASSED")


if __name__ == "__main__":
    status = 0
    try:
        asyncio.run(main())
    except SystemExit as exc:
        print(exc)
        status = 1
    except BaseException:
        import traceback
        traceback.print_exc()
        status = 1
    # fx's TemporalEffect spawns non-daemon threads this frame-stepped
    # harness never joins — a plain return would leave the interpreter alive.
    os._exit(status)
