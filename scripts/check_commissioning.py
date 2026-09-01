"""Executable spec for THE COMMISSIONING GROUND-TRUTH TEST — the plan's §8,
whose comparison was frozen before any run.

WHY THIS SCRIPT EXISTS AT ALL, in the plan's own words: "commissioning an
already-working device means the correct answer exists before the test
runs, so the result is judged against truth instead of admired for
plausibility — the same instinct as breaking your own instrument to prove
it can fail." A commissioning instrument that has never been shown to FAIL
is decoration, so half of this script is deliberate sabotage.

WHAT IS REAL HERE: the REAL pattern lamp on the REAL vendored render
pipeline (section one, through fx.headless — a lamp that lights the wrong
pixels would make every later conclusion wrong in a way nothing downstream
could see), the REAL composition resolution against his OWN stored
tv-mapper shape, the REAL program and its writes, the REAL decoder, and the
REAL frozen table. What is fake is the camera (a room model that paints a
known blob per pixel) and the fx_seam — his fixtures are not granted, and a
check script must never reach for them.

THE GROUND TRUTH IS DECLARED BEFORE ANYTHING RUNS: a synthetic composition
with his own shape (a copy-mapped carrier over five segments across three
fixtures) and a declared arrangement — a wrapped television with a sconce
either side. A pass means:

  1. the pattern lamp lights EXACTLY the pixels of its mask on the real
     render pipeline, and exactly nothing else;
  2. the composition resolves to his stored segment order, driven through
     the fixtures' own strips, every index addressed exactly once;
  3. ~22 captures (dark + full + one per bit and its inverse) recover the
     declared arrangement, and the frozen table's rows 1-4 come out green;
  4. SABOTAGE, each failing ITS OWN row with the attribution the table's
     own right-hand column names: dead pixels (a FINDING about his
     hardware), a broad occlusion (a commissioning FAIL), a scrambled
     order (a commissioning FAIL), a stored layout nothing agrees with (a
     commissioning FAIL), and a stored layout most of it agrees with (a
     FINDING about his mapper);
  5. running it twice bounds the instrument's own noise;
  6. every refusal happens BY NAME with nothing written.

Run from repo root: .venv/bin/python scripts/check_commissioning.py
Isolated: temp storage, fake seams, no LedFX I/O, no audio, no camera, no
network, and his own storage is never touched.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import sys
import tempfile
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


td = Path(tempfile.mkdtemp(prefix="spectra-commissioning-"))

from fx import device_model                                    # noqa: E402
device_model.CATEGORIES_FILE = td / "device_categories.json"
device_model.CATEGORIES_FILE.write_text(json.dumps({}))

from spectra import config as scfg                             # noqa: E402
scfg.SPECTRA_STORAGE = td / "spectra"
for name in ("SCENES_FILE", "SEQUENCER_FILE", "DRIFT_PROFILES_FILE",
             "ROOM_COLOR_FILE", "ROOM_CONTROLS_FILE", "GRADIENT2D_FILE",
             "FIRE_HISTORY_FILE", "SHOW_LOG_FILE", "FLARE_PREVIEW_HOLD_FILE",
             "ROOM_MAPS_FILE", "ROOM_EFFECTS_FILE", "COMMISSIONING_FILE",
             "AV_SYNC_MEASUREMENTS_FILE", "DEVICE_SETTINGS_FILE"):
    setattr(scfg, name, scfg.SPECTRA_STORAGE / f"{name.lower()}.json")
scfg.COLOR_SETS_FILE = td / "color_sets.json"

from fx import light_ownership                                 # noqa: E402
light_ownership.OWNERSHIP_FILE = td / "ownership.json"
light_ownership.OWNERSHIP_FILE.write_text(json.dumps({"owner": "spectra"}))

from spectra.services import commission_compare as cc          # noqa: E402
from spectra.services import commissioning, gray_code, room_mapping  # noqa: E402

FW, FH = 320, 180

# ── the ground truth, declared before anything runs ────────────────────────
#
# HIS OWN SHAPE, read from the live config and reproduced at a size a
# script can render: `tv-mapper` is `mapping: copy` over FIVE segments
# across THREE fixtures — tv-backlight 0-559, sconce-right 0-27,
# sconce-right 28-87, sconce-left 0-27, sconce-left 28-87.
TV, SCONCE = 60, 8
TOTAL = TV + 2 * SCONCE


def _virtual(vid, segments, mapping="span", active=True):
    return {"id": vid, "active": active,
            "segments": [[d, lo, hi, False, 0] for d, lo, hi in segments],
            "pixel_count": sum(hi - lo + 1 for _d, lo, hi in segments),
            "config": {"mapping": mapping, "rows": 1, "grouping": 1},
            "effect": {"type": "singleColor", "config": {}}}


def his_room() -> dict:
    half = SCONCE // 2
    return {
        "tv-mapper": _virtual("tv-mapper", [
            ("tv-backlight", 0, TV - 1),
            ("sconce-kitchen-right", 0, half - 1),
            ("sconce-kitchen-right", half, SCONCE - 1),
            ("sconce-kitchen-left", 0, half - 1),
            ("sconce-kitchen-left", half, SCONCE - 1)], mapping="copy"),
        # idle, exactly as his real config has them: the copy carrier stands
        # in front of them, so a run brings each up and puts it back
        "tv-backlight": _virtual("tv-backlight", [("tv-backlight", 0, TV - 1)],
                                 active=False),
        "sconce-kitchen-left": _virtual(
            "sconce-kitchen-left", [("sconce-kitchen-left", 0, SCONCE - 1)],
            active=False),
        "sconce-kitchen-right": _virtual(
            "sconce-kitchen-right", [("sconce-kitchen-right", 0, SCONCE - 1)],
            active=False),
    }


def truth_layout() -> dict[int, tuple[float, float]]:
    """WHERE those pixels actually are, in the camera's frame — declared
    here, never read off a result: a television wrapped by 60 pixels, with
    a sconce either side of it."""
    layout = {}
    per = TV // 4
    for i in range(TV):
        side, k = i // per, (i % per) / per
        layout[i] = [(0.30 + 0.40 * k, 0.25), (0.70, 0.25 + 0.35 * k),
                     (0.70 - 0.40 * k, 0.60), (0.30, 0.60 - 0.35 * k)][side]
    for j in range(SCONCE):
        layout[TV + j] = (0.86, 0.30 + 0.30 * j / (SCONCE - 1))
        layout[TV + SCONCE + j] = (0.14, 0.30 + 0.30 * j / (SCONCE - 1))
    return layout


CHAIN = [{"id": d, "type": "wled"} for d in
         ("tv-backlight", "sconce-kitchen-left", "sconce-kitchen-right")]


# ── the fake room: a camera looking at the writes the REAL program made ────

class Room:
    def __init__(self, *, dead=None, layout=None, delay_ms=None, fps=30.0,
                 virtuals=None, radius_px=2.0, noise=0.0, peak=None):
        self.virtuals = virtuals or his_room()
        self.layout = layout or truth_layout()
        self.dead = set(dead or ())
        self.delay_ms = dict(delay_ms or {})
        self.fps = fps
        #: the field regime's own camera: a tighter blob, read noise, and a
        #: per-pixel level calibrated so ALL-ON reaches `peak` of 255 — see
        #: section 3c. Left alone this is the same camera it always was.
        self.radius_px = radius_px
        self.noise = noise
        self.peak = peak
        self._rng = np.random.default_rng(3)
        self._gain = None
        self.writes: list[dict] = []
        self.closed = 0
        self.activated: list[str] = []
        self.deactivated: list[str] = []
        self.t = 0.0
        self.write_at = 0.0
        self.seq = 0
        self._blobs: dict = {}
        self._cache: dict = {}
        self.composition = commissioning.resolve_composition(
            "tv-mapper", self.virtuals, CHAIN)
        self.session = Phone(self)

    def device_of(self, index: int) -> str:
        for seg in self.composition.segments:
            if seg.start <= index <= seg.end:
                return seg.device_id
        return ""

    def lit(self) -> set[int]:
        out: set[int] = set()
        for write in self.writes:
            if write.get("effect_type") != commissioning.PATTERN_EFFECT_TYPE:
                continue
            arr = self.composition.pixel_map.get(write["virtual_id"])
            if arr is None:
                continue
            for pixel, ch in enumerate((write.get("config") or {}).get("pattern") or ""):
                if ch == "1" and pixel < len(arr) and arr[pixel] >= 0:
                    out.add(int(arr[pixel]))
        return out

    def _render_raw(self, on) -> np.ndarray:
        if self.peak is None:
            return gray_code.render_frame(
                self.layout, on, width=FW, height=FH,
                radius_px=self.radius_px, dead=self.dead, blobs=self._blobs)
        if self._gain is None:
            unit = gray_code.render_frame(
                self.layout, set(self.layout), width=FW, height=FH,
                radius_px=self.radius_px, dark_level=2.0, lit_level=3.0,
                blobs=self._blobs, window_sigmas=5.0)
            self._gain = self.peak / max(1e-9, float((unit - 2.0).max()))
        return gray_code.render_frame(
            self.layout, on, width=FW, height=FH, radius_px=self.radius_px,
            dark_level=2.0, lit_level=2.0 + self._gain, dead=self.dead,
            blobs=self._blobs, window_sigmas=5.0)

    def render(self, elapsed_ms: float = 1e9) -> np.ndarray:
        arrived = tuple(sorted(d for d in self.composition.devices
                               if self.delay_ms.get(d, 0.0) <= elapsed_ms))
        on = {i for i in self.lit() if self.device_of(i) in arrived}
        if self.noise:
            # fresh noise per frame: an averaging window that averages the
            # SAME noise four times is not the camera this is modelling.
            return np.clip(self._render_raw(on)
                           + self._rng.normal(0.0, self.noise, (FH, FW)),
                           0.0, 255.0)
        key = (self.seq, arrived)
        got = self._cache.get(key)
        if got is None:
            got = self._render_raw(on)
            self._cache[key] = got
        return got

    def deps(self) -> room_mapping.RunDeps:
        room = self

        async def get_virtuals():
            return room.virtuals

        async def open_hold(program, intensity, *, step, heartbeat_timeout_s):
            await program.execute(step, Ctx(room))
            return {"held": True, "step": step}

        async def close_hold():
            room.closed += 1
            return {"reverted": True}

        async def sleep(seconds):
            room.t += float(seconds)

        async def activate(vid):
            room.activated.append(vid)
            room.virtuals[vid]["active"] = True

        async def deactivate(vid):
            room.deactivated.append(vid)
            room.virtuals[vid]["active"] = False

        async def fixture_devices():
            return []

        async def carrier_devices():
            return {"tv-mapper": CHAIN}

        return room_mapping.RunDeps(
            session=room.session, get_virtuals=get_virtuals,
            open_hold=open_hold, close_hold=close_hold, sleep=sleep,
            clock=lambda: room.t, carrier_devices=carrier_devices,
            spectra_owns=lambda: True, activate=activate,
            deactivate=deactivate, fixture_devices=fixture_devices)


class Ctx:
    def __init__(self, room):
        self.room = room

    async def apply_scene(self, writes=None, transition_ms=None):
        self.room.writes = list(writes or [])
        self.room.seq += 1
        self.room.t += 0.01
        self.room.write_at = self.room.t


class Phone:
    """A connected, locked camera. Refuses nothing; the refusal paths are
    exercised by overriding `refusal` in section six."""

    def __init__(self, room):
        self.room = room
        self.pose_id = "pose-check"
        self.run_abort = None
        self.keep_full_frames = False
        self.full = []
        self.lock = type("L", (), {"exposure_locked": True,
                                   "white_balance_locked": True,
                                   "exposure_mode": "manual",
                                   "white_balance_mode": "manual"})()

    def refusal(self):
        return None

    async def gather_full(self, seconds, *, min_frames=1):
        n = max(min_frames, int(seconds * self.room.fps))
        start = self.room.t
        self.room.t += float(seconds)
        out = []
        for k in range(n):
            at = start + k / self.room.fps
            frame = self.room.render((at - self.room.write_at) * 1000.0)
            out.append(type("TF", (), {"at_s": at,
                                       "frame": frame.astype(np.uint8)})())
        return out


def run(room: Room, **kw):
    return asyncio.run(commissioning.run_commission(
        "tv-mapper", room.deps(), **kw))


def rows_of(result) -> dict:
    return {r["field"]: r for r in result.table["rows"]}


# ── ONE — the pattern lamp on the REAL render pipeline ────────────────────

async def section_one():
    print("\n== 1. the pattern lamp lights EXACTLY its mask, on the real "
          "render pipeline ==")
    from fx import facade, headless
    from fx.consts import CONFIGURATION_VERSION
    from fx.host import FxHost

    config_dir = str(td / "fx-lamp")
    os.makedirs(config_dir, exist_ok=True)
    with open(os.path.join(config_dir, "config.json"), "w") as fh:
        json.dump({"configuration_version": CONFIGURATION_VERSION,
                   "devices": [{"id": "strip", "type": "dummy",
                                "config": {"name": "strip",
                                           "pixel_count": TV}}],
                   "virtuals": [{"id": "strip", "is_device": "strip",
                                 "auto_generated": False,
                                 "config": {"name": "strip", "mapping": "span",
                                            "rows": 1},
                                 "segments": [["strip", 0, TV - 1, False]]}]},
                  fh)
    headless.silence_audio()
    host = FxHost(config_dir)
    await host.start()
    host.audio = headless.SyntheticAudioSource()
    facade.set_host(host)
    virtual = host.virtuals.get("strip")

    # a real gray-code pattern, produced by the real pattern builder
    indices = np.arange(TV, dtype=np.int64)
    mask = gray_code.pattern_string(indices, 2)
    headless.attach_effect(host, virtual, commissioning.PATTERN_EFFECT_TYPE,
                           {"color": "#ffffff", "pattern": mask,
                            "brightness": 1.0, "background_brightness": 0.0})
    frame = np.asarray(virtual.assemble_frame())
    lit = np.array([c == "1" for c in mask])
    check(frame[lit].min() > 200.0,
          f"every pixel the mask names is lit (min {frame[lit].min():.0f}/255)")
    check(float(np.abs(frame[~lit]).max()) == 0.0,
          f"and every pixel it does not is EXACTLY zero "
          f"(max {float(np.abs(frame[~lit]).max()):.3f}) — the references "
          f"this stack is differenced against are genuinely dark")

    # the INVERSE lights exactly the complement — the pair the decode reads
    headless.attach_effect(host, virtual, commissioning.PATTERN_EFFECT_TYPE,
                           {"color": "#ffffff", "brightness": 1.0,
                            "pattern": gray_code.pattern_string(indices, 2,
                                                                invert=True),
                            "background_brightness": 0.0})
    inverse = np.asarray(virtual.assemble_frame())
    check(float(np.abs(inverse[lit]).max()) == 0.0 and inverse[~lit].min() > 200.0,
          "the inverse lights exactly the complement — every camera pixel is "
          "differenced against its own opposite, which is what cancels the "
          "surface, the lens and the fixture")

    headless.attach_effect(host, virtual, commissioning.PATTERN_EFFECT_TYPE,
                           {"color": "#ffffff", "pattern": "",
                            "brightness": 1.0, "background_brightness": 0.0})
    empty = np.asarray(virtual.assemble_frame())
    check(float(np.abs(empty).max()) == 0.0,
          "an empty mask lights nothing at all rather than guessing")

    check(commissioning.PATTERN_EFFECT_TYPE not in device_model.effect_types(),
          "the pattern lamp is REGISTRY-EXEMPT: absent from the effect-param "
          "registry, so it never reaches an authoring surface")


# ── TWO — the composition is his stored one ───────────────────────────────

def section_two():
    print("\n== 2. the composition is the stored mapper's own five segments ==")
    room = Room()
    comp = room.composition
    check(comp.total == TOTAL, f"every stored pixel is addressed ({comp.total})")
    check([(s.device_id, s.start, s.end) for s in comp.segments] == [
        ("tv-backlight", 0, TV - 1),
        ("sconce-kitchen-right", TV, TV + SCONCE // 2 - 1),
        ("sconce-kitchen-right", TV + SCONCE // 2, TV + SCONCE - 1),
        ("sconce-kitchen-left", TV + SCONCE, TV + SCONCE + SCONCE // 2 - 1),
        ("sconce-kitchen-left", TV + SCONCE + SCONCE // 2, TOTAL - 1)],
        "in the mapper's OWN stored order, across all three fixtures")
    check("tv-mapper" not in comp.pixel_map,
          "driven through the fixtures' own strips, never the copy carrier — "
          "a copy-mapped virtual would light every segment identically and "
          "identify nothing")
    used = np.concatenate([a[a >= 0] for a in comp.pixel_map.values()])
    check(sorted(used.tolist()) == list(range(TOTAL)),
          "and every composition index is addressed exactly once")
    bits = gray_code.bits_needed(comp.total)
    print(f"     his real 736-pixel composition: {gray_code.bits_needed(736)} "
          f"patterns -> {2 + 2 * gray_code.bits_needed(736)} captures "
          f"(this synthetic one: {bits} -> {2 + 2 * bits})")


# ── THREE — the whole run, against the declared arrangement ───────────────

def section_three():
    print("\n== 3. ~22 captures recover the declared arrangement, and the "
          "frozen table is green ==")
    room = Room()
    result = run(room, layout=room.layout, instrument={})
    check(result.ok, f"the run reports ok ({result.reason})")
    bits = gray_code.bits_needed(TOTAL)
    check(len(result.captures) == 2 + 2 * bits,
          f"{len(result.captures)} captures: dark + full + one per bit and "
          f"its inverse")
    seen = result.decodes[0]["seen"]
    check(seen == TOTAL, f"every one of the {TOTAL} pixels was identified "
                         f"({seen})")
    rows = rows_of(result)
    for field in ("Pixel count seen", "Pixel ordering", "2-D arrangement",
                  "Cross-device stitch"):
        check(rows[field]["verdict"] == cc.PASS,
              f"row '{field}': {rows[field]['verdict']} "
              f"({rows[field]['measured']})")
    check(rows["Device latency"]["verdict"] == cc.UNMEASURED,
          "row 'Device latency': unmeasured — no second instrument's reading "
          "here, and an unmeasured row is never a silent pass")
    check(result.table["verdict"] == "incomplete",
          f"so the verdict is 'incomplete', not green "
          f"({result.table['verdict']})")
    check(room.closed == 1, "ONE continuous hold, released by the run itself")
    check(sorted(set(room.activated)) == sorted(set(room.deactivated)) ==
          sorted(room.composition.virtual_ids),
          "the idle strips were brought up for the capture and put back")
    check(room.session.keep_full_frames is False,
          "and the full-resolution frame ring is off again")
    return room


def section_three_b():
    print("\n== 3b. a fast camera measures a real per-device arrival ==")
    room = Room(fps=100.0, delay_ms={"sconce-kitchen-right": 40.0})
    result = run(room, layout=room.layout,
                 instrument={"tv-backlight": 0.0, "sconce-kitchen-left": 0.0,
                             "sconce-kitchen-right": 40.0})
    numbers = rows_of(result)["Device latency"]["numbers"]
    got = numbers["commissioning_ms"]
    delta = got.get("sconce-kitchen-right", 0) - got.get("tv-backlight", 0)
    check(abs(delta - 40.0) <= 10.0,
          f"the injected 40 ms arrival delay comes back as {delta:.0f} ms "
          f"(camera cadence {numbers['resolution_ms']:.0f} ms)")
    check(rows_of(result)["Device latency"]["verdict"] == cc.PASS,
          "and an instrument that agrees within +/- 15 ms passes the row")
    disagreeing = run(Room(fps=100.0, delay_ms={"sconce-kitchen-right": 40.0}),
                      layout=None,
                      instrument={"tv-backlight": 0.0,
                                  "sconce-kitchen-left": 0.0,
                                  "sconce-kitchen-right": 0.0})
    row = rows_of(disagreeing)["Device latency"]
    check(row["verdict"] == cc.FAIL and "instruments" in row["indicts"],
          "one that does not is a FAIL indicting an instrument, not the "
          "fixture — the table's own wording")
    slow = run(Room(fps=5.0), layout=None, instrument={"a": 0.0, "b": 1.0})
    check(rows_of(slow)["Device latency"]["verdict"] == cc.UNMEASURED,
          "and at the mapping tap's real 5 fps the row is UNMEASURED: a "
          "200 ms cadence cannot answer a 15 ms question")


# ── THREE-C — THE FIELD REGIME: the failure his room actually produced ────
#
# HIS OWN NUMBERS, from the two runs of 2026-09-01 and the raw frame kept
# from the same pose (data/commissioning-field-evidence/): 736 pixels, 22
# captures, ~42 s, verdict FAIL, 0 of 736 decoded, ~3,165 "lit" camera
# pixels ALL undecodable, 0 out of range — and, in the second run, 0 lit
# pixels at all. The frame from that pose is 320x180 and all but 66 of its
# 57,600 pixels are exactly zero: the whole composition arrives as THREE
# compact glows, about 8x4 camera pixels each, peaking at 99 of 255.
#
# So this section builds that camera — his composition at his sizes, imaged
# into those three glows, calibrated to that peak, with read noise and the
# wire's own grey8 quantisation — and drives the REAL decoder and the REAL
# run with it. Everything above this line runs at about 6 camera pixels per
# composition index; his room ran at about 0.09. That gap, not the mechanics,
# is what the synthetic proof was never asked about.

FIELD_TV, FIELD_RIGHT, FIELD_LEFT = 560, (28, 60), (28, 60)
FIELD_TOTAL = FIELD_TV + sum(FIELD_RIGHT) + sum(FIELD_LEFT)
#: The brightest camera pixel in his own pose frame, of 255.
FIELD_PEAK = 99.0
#: The three glows, as measured off that frame: centre (x, y) in pixels and
#: how much of the frame's width the fixture's whole strip covers.
FIELD_GLOWS = {"tv-backlight": (140.0, 55.5, 8.0),
               "sconce-kitchen-right": (73.0, 56.5, 6.0),
               "sconce-kitchen-left": (207.5, 54.0, 6.0)}


def field_room_virtuals() -> dict:
    """His stored tv-mapper at ITS OWN size: 560 + 28 + 60 + 28 + 60."""
    r0, r1 = FIELD_RIGHT
    l0, l1 = FIELD_LEFT
    return {
        "tv-mapper": _virtual("tv-mapper", [
            ("tv-backlight", 0, FIELD_TV - 1),
            ("sconce-kitchen-right", 0, r0 - 1),
            ("sconce-kitchen-right", r0, r0 + r1 - 1),
            ("sconce-kitchen-left", 0, l0 - 1),
            ("sconce-kitchen-left", l0, l0 + l1 - 1)], mapping="copy"),
        "tv-backlight": _virtual("tv-backlight",
                                 [("tv-backlight", 0, FIELD_TV - 1)],
                                 active=False),
        "sconce-kitchen-right": _virtual(
            "sconce-kitchen-right",
            [("sconce-kitchen-right", 0, r0 + r1 - 1)], active=False),
        "sconce-kitchen-left": _virtual(
            "sconce-kitchen-left",
            [("sconce-kitchen-left", 0, l0 + l1 - 1)], active=False),
    }


def field_layout(span_scale: float = 1.0) -> dict[int, tuple[float, float]]:
    """WHERE those 736 pixels land in his frame: each fixture's whole strip
    inside its own glow. `span_scale` widens the glows — 1.0 is his pose,
    and a large value is the close-up this test would need."""
    counts = [("tv-backlight", FIELD_TV),
              ("sconce-kitchen-right", FIELD_RIGHT[0]),
              ("sconce-kitchen-right", FIELD_RIGHT[1]),
              ("sconce-kitchen-left", FIELD_LEFT[0]),
              ("sconce-kitchen-left", FIELD_LEFT[1])]
    used: dict[str, int] = {}
    layout, index = {}, 0
    for device, n in counts:
        cx, cy, span = FIELD_GLOWS[device]
        span *= span_scale
        total_on_device = sum(m for d, m in counts if d == device)
        for k in range(n):
            at = used.get(device, 0) + k
            x = cx + (at / max(1, total_on_device - 1) - 0.5) * span
            layout[index] = (x / FW, cy / FH)
            index += 1
        used[device] = used.get(device, 0) + n
    return layout


def field_stack(layout, *, noise=1.0, seed=11, radius_px=2.0, dark=2.0):
    """The reference pair and every bit's pattern/inverse, as HIS camera
    would deliver them: the per-pixel light calibrated so ALL-ON reaches the
    99-of-255 his own frame peaks at, plus read noise, plus the wire's own
    grey8 rounding — the quantisation is not a detail here, it is most of
    why a half-lit pattern and its opposite come back identical."""
    every = set(layout)
    rng = np.random.default_rng(seed)
    cache: dict = {}

    def raw(on, gain):
        return gray_code.render_frame(
            layout, on, width=FW, height=FH, radius_px=radius_px,
            dark_level=dark, lit_level=dark + gain, blobs=cache,
            window_sigmas=5.0)

    unit = float((raw(every, 1.0) - dark).max())
    gain = FIELD_PEAK / max(1e-9, unit)

    def shot(on):
        # four frames averaged, exactly as a capture window does, each one
        # quantised to the grey8 the phone actually sends.
        frames = [np.clip(np.round(raw(on, gain)
                                   + rng.normal(0.0, noise, (FH, FW))),
                          0, 255).astype(np.uint8).astype(np.float64)
                  for _ in range(4)]
        return np.mean(frames, axis=0)

    dark_frame, full_frame = shot(set()), shot(every)
    pairs = []
    for bit in range(gray_code.bits_needed(len(layout))):
        on = {i for i in every if gray_code.pattern_bits(np.array([i]), bit)[0]}
        pairs.append((shot(on), shot(every - on)))
    return dark_frame, full_frame, pairs


def _old_lit_count(dark, full):
    """The gate as it was when his runs were judged: a 99th-percentile
    peak and a 1e-9 floor. Kept here, and only here, so the reproduction can
    show what those two field numbers actually were."""
    bright = np.clip(np.asarray(full, float) - np.asarray(dark, float), 0, None)
    peak = float(np.percentile(bright, 99.0))
    return int((bright >= max(1e-9, peak * gray_code.LIT_FRACTION)).sum())


def section_three_c():
    print("\n== 3c. THE FIELD REGIME — his own failure, reproduced on "
          "demand ==")
    layout = field_layout()
    dark, full, pairs = field_stack(layout)

    # (a) the failure MODE, on the real decoder
    decode = gray_code.decode_stack(dark, full, pairs, total=FIELD_TOTAL)
    check(len(decode.seen) == 0,
          f"0 of {FIELD_TOTAL} pixels decoded — his own result "
          f"({len(decode.seen)} seen)")
    check(decode.lit_pixels > 0 and
          decode.undecodable_pixels == decode.lit_pixels,
          f"with abundant light: every one of the {decode.lit_pixels} lit "
          f"camera pixels is UNDECODABLE, his own signature")
    check(decode.out_of_range_pixels == 0,
          "and 0 out of range — nothing decoded to a wrong index, nothing "
          "decoded at all")

    # (b) WHERE it dies, which is the question the field response could not
    #     answer and now can
    contrast = decode.bit_contrast
    low = [c["median_strength"] for c in contrast[:6]]
    high = [c["median_strength"] for c in contrast[7:]]
    check(all(v is not None and v < gray_code.BIT_CONFIDENCE for v in low),
          f"the LOW bits are where it dies: median contrast {low} against a "
          f"{gray_code.BIT_CONFIDENCE} bar — a pattern and its opposite "
          f"alternate faster than this camera can see, and cancel")
    check(all(v is not None and v > gray_code.BIT_CONFIDENCE for v in high),
          f"while the HIGH bits are perfectly confident ({high}) — the "
          f"stack is not noise, and it is not mistimed")

    # (c) the discriminator: a TIMING error does not look like this
    flat = [f for pair in pairs for f in pair]
    lagged = [full] + flat[:-1]
    late = gray_code.decode_stack(
        dark, full, [(lagged[2 * b], lagged[2 * b + 1])
                     for b in range(len(pairs))], total=FIELD_TOTAL)
    mistimed = [c["median_strength"] for c in late.bit_contrast[:6]]
    check(any(v is not None and v > gray_code.BIT_CONFIDENCE
              for v in mistimed),
          f"reading every capture one step late leaves the low bits with "
          f"REAL contrast ({mistimed}) — two different patterns differ; "
          f"they do not cancel. His runs showed the opposite, so the frames "
          f"were not read at the wrong moments")

    # (d) the lit gate itself, which reported two numbers that described
    #     nothing
    old_count = _old_lit_count(dark, full)
    report = gray_code.resolution_report(dark, full, total=FIELD_TOTAL)
    check(old_count > 10 * report["lit_pixels"],
          f"the old 99th-percentile gate called {old_count} camera pixels "
          f"lit (his run: 3,165) where the composition lights "
          f"{report['lit_pixels']} — a composition covering 0.1% of the "
          f"frame puts the 99th percentile in the noise")
    check(report["lit_pixels"] > 0 and not report["resolvable"],
          f"the shipped gate: {report['lit_pixels']} camera pixels, "
          f"{report['camera_px_per_index']} per composition pixel, against "
          f"{report['min_camera_px_per_index']} needed "
          f"({report['needed_camera_px']} of the {FW}x{FH} frame)")

    # (e) the run refuses BY NAME, two captures in, instead of spending the
    #     room's dark time to reach a verdict about the wrong thing
    room = Room(virtuals=field_room_virtuals(), layout=layout,
                radius_px=2.0, noise=1.0, peak=FIELD_PEAK)
    result = run(room, layout=layout, instrument={})
    check(not result.ok and result.refusal == "resolution",
          f"the run refuses ({result.refusal}): {result.reason[:110]}...")
    check(len(result.captures) == 2,
          f"after the dark and full reference captures ONLY — "
          f"{len(result.captures)} of the {2 + 2 * gray_code.bits_needed(FIELD_TOTAL)} "
          f"his runs spent")
    check(result.table == {} and not result.decodes,
          "nothing is judged and no decode is claimed — the frozen table is "
          "never handed a stack this camera could not read")
    check(result.resolution.get("camera_px_per_index", 9) < 1.0,
          f"and the response carries the measurement itself: "
          f"{result.resolution.get('camera_px_per_index')} camera pixels "
          f"per composition pixel")
    check(room.closed == 1 and
          sorted(set(room.activated)) == sorted(set(room.deactivated)),
          "the hold is released and the strips it brought up are put back, "
          "refusal or not")

    # (f) it is not the LIGHT: the same 99-of-255 room, the same read noise
    #     and the same grey8 wire, decodes a composition small enough for
    #     this frame
    small = {i: (0.10 + 0.80 * i / 87.0, 0.5) for i in range(88)}
    d2, f2, p2 = field_stack(small)
    near = gray_code.decode_stack(d2, f2, p2, total=88)
    ok = gray_code.resolution_report(d2, f2, total=88)
    check(ok["resolvable"] and len(near.seen) > 0.8 * 88,
          f"88 pixels across the same frame at the same 99-of-255: "
          f"{ok['camera_px_per_index']} camera pixels each, "
          f"{len(near.seen)} of 88 decoded — his run lacked resolution, not "
          f"light")

    # (g) AND IT IS NOT ONLY THE POSE. 736 pixels need about
    #     736 x MIN_CAMERA_PX_PER_INDEX camera pixels of imaged strip; the
    #     frame the phone sends is 320x180, whose entire border is ~1,000.
    #     A television wrapped once by one strip cannot carry 1,472 of them
    #     however the phone is held — which is the honest answer to "what
    #     would a passing run need", and it is not a pose.
    needed = int(FIELD_TOTAL * gray_code.MIN_CAMERA_PX_PER_INDEX)
    border = 2 * (FW + FH)
    check(needed > border,
          f"{FIELD_TOTAL} pixels need ~{needed} camera pixels of imaged "
          f"strip, and the whole border of the {FW}x{FH} frame is ~{border} "
          f"— no pose fixes that; the wire's own frame size is the bound")
    print(f"     a frame able to carry them, at his composition's own wrap, "
          f"is about {int(round(needed / border * FW))}x"
          f"{int(round(needed / border * FH))} — the phone captures at "
          f"1280x720 and downsamples to {FW}x{FH} before sending")


# ── FOUR — sabotage: each failure lands on ITS OWN row ────────────────────

def section_four():
    print("\n== 4. SABOTAGE — each corrupted stack fails its own row, with "
          "the table's own attribution ==")

    room = Room(dead={20, 21, 44})
    row = rows_of(run(room, layout=room.layout, instrument={}))["Pixel count seen"]
    check(row["verdict"] == cc.FINDING and "dead pixels" in row["indicts"],
          f"three dead LEDs -> a FINDING about his hardware, never a "
          f"commissioning failure ({row['measured']})")

    room = Room(dead=set(range(10, 34)))
    result = run(room, layout=room.layout, instrument={})
    row = rows_of(result)["Pixel count seen"]
    check(row["verdict"] == cc.FAIL and "occlusion" in row["indicts"],
          f"a whole occluded stretch -> a commissioning FAIL "
          f"({row['measured']})")
    check(result.table["verdict"] == "fail", "and the verdict is 'fail'")

    truth = truth_layout()
    scrambled = dict(truth)
    block = list(range(12, 40))
    for a, b in zip(block, block[::-1][:7] + block[7:]):
        scrambled[a] = truth[b]
    row = rows_of(run(Room(layout=scrambled), layout=None,
                      instrument={}))["Pixel ordering"]
    check(row["verdict"] == cc.FAIL and "sequencing" in row["indicts"],
          f"a scrambled order -> a commissioning FAIL ({row['measured']})")

    room = Room()
    rng = np.random.default_rng(5)
    nothing_agrees = {i: (min(0.99, max(0.01, x + rng.normal(0, 0.05))),
                          min(0.99, max(0.01, y + rng.normal(0, 0.05))))
                      for i, (x, y) in room.layout.items()}
    row = rows_of(run(room, layout=nothing_agrees,
                      instrument={}))["2-D arrangement"]
    check(row["verdict"] == cc.FAIL and "camera-geometry" in row["indicts"],
          f"a stored layout nothing agrees with -> a commissioning FAIL "
          f"({row['measured']})")

    room = Room()
    stored = dict(room.layout)
    cx = float(np.mean([room.layout[i][0] for i in range(TV)]))
    cy = float(np.mean([room.layout[i][1] for i in range(TV)]))
    turn = math.radians(35)
    for i in range(TV):
        dx, dy = room.layout[i][0] - cx, room.layout[i][1] - cy
        stored[i] = (cx + dx * math.cos(turn) - dy * math.sin(turn),
                     cy + dx * math.sin(turn) + dy * math.cos(turn))
    result = run(room, layout=stored, instrument={})
    row = rows_of(result)["2-D arrangement"]
    check(row["verdict"] == cc.FINDING and "hand-built mapper" in row["indicts"],
          f"a stored layout MOST of it agrees with -> a FINDING about his "
          f"mapper ({row['measured']})")
    check(result.table["verdict"] != "fail",
          "and that is never reported as a commissioning failure")

    room = Room()
    stored = dict(room.layout)
    for i in range(TV, TV + SCONCE):
        x, y = stored[i]
        stored[i] = (min(0.99, x + 0.12), y)
    row = rows_of(run(room, layout=stored,
                      instrument={}))["Cross-device stitch"]
    check(row["verdict"] == cc.FINDING and "stale stitched" in row["indicts"],
          f"a sconce the right SHAPE in the wrong PLACE -> a FINDING about "
          f"the stored mapper ({row['measured']})")


# ── FIVE — twice, back to back ────────────────────────────────────────────

def section_five():
    print("\n== 5. run it twice: two independent decodes bound the "
          "instrument's own noise ==")
    room = Room()
    result = run(room, repeat=2, layout=room.layout, instrument={})
    check(result.repeats == 2 and room.closed == 2,
          "two passes, each in its own continuous hold")
    got = result.agreement
    check(got["compared"] >= int(0.95 * TOTAL),
          f"{got['compared']} of {TOTAL} pixels decoded in both")
    check(got["median_shift"] is not None and got["median_shift"] < 0.01,
          f"median disagreement between the two decodes: "
          f"{got['median_shift']:.5f} of the frame")


# ── SIX — refusals, before anything is written ────────────────────────────

def section_six():
    print("\n== 6. every refusal is BY NAME, with nothing written ==")
    room = Room()
    room.session.refusal = lambda: "this browser will not lock EXPOSURE"
    result = run(room, layout=room.layout, instrument={})
    check(not result.ok and result.refusal == "camera_lock" and not room.writes,
          "an unlocked camera refuses before a light is touched")

    room = Room()
    deps = room.deps()
    deps = room_mapping.RunDeps(**{**deps.__dict__, "spectra_owns": lambda: False})
    result = asyncio.run(commissioning.run_commission("tv-mapper", deps))
    check(not result.ok and result.refusal == "ownership" and not room.writes,
          "spot-effects owning the lights refuses by name: the pattern lamp "
          "is an effect inside THIS process")

    virtuals = his_room()
    del virtuals["sconce-kitchen-left"]
    try:
        commissioning.resolve_composition("tv-mapper", virtuals, CHAIN)
        check(False, "a fixture with no addressable virtual is refused")
    except commissioning.CompositionRefused as exc:
        check("sconce-kitchen-left" in str(exc),
              "a fixture with no addressable virtual is refused by name "
              "rather than commissioning a smaller composition than the "
              "stored one")

    layout, note = commissioning.stored_layout(
        "tv-mapper", his_room()["tv-mapper"], TOTAL, None)
    check(layout is None and "no 2-D layout" in note,
          "and a mapper that stores an ORDER but no LAYOUT says so rather "
          "than inventing a rectangle to be judged against")
    print(f"     (his real tv-mapper is exactly this case — the note says: "
          f"{note[:110]}...)")


def print_table(result):
    print("\n== the frozen table, as this run judged it ==")
    for row in result.table["rows"]:
        print(f"  [{row['verdict']:>10}] {row['field']:<20} "
              f"{row['measured'] or '-'}")
        if row["indicts"]:
            print(f"               indicts: {row['indicts']}")
    print(f"  VERDICT: {result.table['verdict']}")


def main():
    asyncio.run(section_one())
    section_two()
    room = section_three()
    section_three_b()
    section_three_c()
    section_four()
    section_five()
    section_six()
    print_table(run(Room(), layout=truth_layout(), instrument={}))
    del room
    print()
    if FAILURES:
        raise SystemExit(f"FAILED {len(FAILURES)} check(s):\n  " +
                         "\n  ".join(FAILURES))
    print("ALL COMMISSIONING CHECKS PASSED")


if __name__ == "__main__":
    status = 0
    try:
        main()
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
