"""THE COMMISSIONING GROUND-TRUTH TEST — gray-code the composition, decode
where every pixel is, and judge the result against a comparison that was
frozen before the run.

THE PLAN'S OWN ARGUMENT FOR WHY THIS EXISTS (§8, and it is the whole
point): "commissioning an already-working device means the correct answer
exists before the test runs, so the result is judged against truth instead
of admired for plausibility — the same instinct as breaking your own
instrument to prove it can fail." His `tv-mapper` is a composition his eyes
have validated for months: 560 pixels of TV backlight plus four sconce
segments across two more fixtures, in a stored order. That is the richest
ground truth in the room, and this test spends about thirty-five seconds
against it.

THE FROZEN COMPARISON IS NOT HERE. It is
`spectra/services/commission_compare.py`, which quotes the plan's table
verbatim and judges every row by rules fixed in advance. This module's job
ends at handing that one a decode; it never decides whether a run passed.

WHAT IS GENUINELY NEW HERE, and it is only two things:

  1. the composition -> global pixel index resolution (below), and
  2. the capture LOOP: ~22 patterns over ONE continuous hold.

Everything else is machinery that already exists and is reused rather than
rebuilt — which is the standing rule on this path:

  * the phone session, its frames, its exposure lock and its refusals:
    `mapping_session` (this run turns on its full-resolution ring, since
    736 pixels cannot be resolved by 2304 map-grid cells, and turns it off
    again in a `finally`);
  * the held room: `flare_preview_hold.open_program_hold` — the ONE hold,
    with its snapshot, deadline, independent sweep, 3-minute ceiling and
    restart recovery. A commissioning run is one `PreviewProgram` like any
    preview;
  * the substitution: a copy-mapped carrier cannot be lit in parts, so the
    patterns are driven through the fixtures' own direct virtuals exactly
    as `room_mapping`'s run already does (`emitters.substitutes_for`);
  * bringing an idle substitute up and putting it back:
    `room_mapping.activate_for_capture` / `deactivate_after_capture`;
  * the fixture's own firmware brightness, taken to full for the capture
    and given back: `fixture_brightness.owned` — a run at 10% brightness
    measures the dimmer, which this codebase learned the hard way;
  * every named refusal: `mapping_refusals`.

ONE CONTINUOUS HOLD, deliberately, where the MAP's run is a chain of short
ones. The reasons are different acts, not a change of mind: a map's
emitters are independent measurements, so releasing the room between them
costs nothing and buys "restorable at any instant". A gray-code STACK is
ONE measurement — every capture in it is differenced against the same dark
and full reference from the same pose with the same exposure — so a room
that came back to life half way through would silently put the show's own
light into the middle of the stack. The whole stack is ~35 s, comfortably
inside the hold's own 3-minute ceiling, and the ceiling still applies.

RUN IT TWICE (the brief's point 4): `repeat=2` runs the whole thing again,
in its own fresh hold, and reports how far the two independent decodes
disagree (`gray_code.agreement`). That is not one of the frozen rows — it
is the instrument's own noise floor, which is what makes a disagreement
with the stored truth readable.

NEVER A JUDGMENT CALL AT RUNTIME. This run either produces a decode and
hands it to the frozen table, or it refuses BY NAME with nothing written.
"""
from __future__ import annotations

import json
import logging
import math
import os
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

from spectra import config
from spectra.models.scene import (SceneColorAssignment, SceneDeviceConfig,
                                  SceneV2)
from spectra.services import commission_compare as compare
from spectra.services import emitters as emitters_mod
from spectra.services import (fixture_brightness, flare_preview_hold,
                              gray_code, mapping_refusals, room_mapping)

logger = logging.getLogger(__name__)

#: The pattern lamp: fx/effects/pixelPattern.py, one character per effect
#: pixel. Registry-exempt on purpose (it is an instrument) — see that
#: module's docstring, and `pixelRange`'s, for the same discipline.
PATTERN_EFFECT_TYPE = "pixelPattern"
DARK_EFFECT_TYPE = room_mapping.MAP_EFFECT_TYPE
WHITE = room_mapping.WHITE
BLACK = room_mapping.BLACK
WRITE_TRANSITION_MS = room_mapping.WRITE_TRANSITION_MS

#: The plan's own budget: "~22 captures at ~1.5 s". A capture is a settle
#: (the write has to actually land, through the same per-device delay every
#: other write goes through) plus a window of frames to average.
SETTLE_S = 0.6
CAPTURE_S = 0.9
#: Frames a capture must actually have. Below this the run refuses rather
#: than decoding a stack built from single frames.
MIN_FRAMES = 2
#: The hold's heartbeat window. A run drives its own hold synchronously; if
#: it dies mid-stack the sweep reverts within this + SWEEP_INTERVAL_S with
#: nothing else needing to have run.
HOLD_HEARTBEAT_S = 30.0
#: Kept results. Bounded like every other log in this codebase.
MAX_STORED_RESULTS = 20


# ── the composition ────────────────────────────────────────────────────────

@dataclass
class Composition:
    """The thing being commissioned: the stored mapper's segments, in the
    order it stores them, resolved down to WHICH VIRTUAL AND WHICH EFFECT
    PIXEL each composition index is driven through.

    `pixel_map[virtual_id]` is index-aligned with that virtual's own effect
    buffer and holds the composition index each pixel carries, or -1 for a
    pixel this composition does not use. That array IS the wire format's
    input (`gray_code.pattern_string`), so the lamp and the decoder cannot
    disagree about which pixel is which.

    A RANGE IS AN ADDRESSING FACT, NOT A POSITION — the same guardrail
    `spectra/services/emitters.py` states. Nothing here knows or stores
    where a pixel is; that is what the camera is for."""
    mapper_id: str
    segments: list[compare.Segment] = field(default_factory=list)
    pixel_map: dict[str, np.ndarray] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(s.length for s in self.segments)

    @property
    def virtual_ids(self) -> list[str]:
        return sorted(self.pixel_map)

    @property
    def devices(self) -> list[str]:
        return sorted({s.device_id for s in self.segments})

    def indices_for_device(self, device_id: str) -> list[int]:
        return [i for s in self.segments if s.device_id == device_id
                for i in s.indices]

    def as_dict(self) -> dict:
        return {"mapper_id": self.mapper_id, "total": self.total,
                "segments": [s.as_dict() for s in self.segments],
                "virtual_ids": self.virtual_ids, "devices": self.devices,
                "notes": self.notes}


class CompositionRefused(Exception):
    """This composition cannot be commissioned, and the message says why in
    his words. Raised BEFORE anything is written or held."""


def _grouping(virtual: dict) -> int:
    try:
        return max(1, int(((virtual or {}).get("config") or {}).get("grouping") or 1))
    except (TypeError, ValueError):
        return 1


def _segment_rows(virtual: dict) -> list[tuple[str, int, int]]:
    out = []
    for seg in (virtual or {}).get("segments") or []:
        if isinstance(seg, (list, tuple)) and len(seg) >= 3:
            out.append((str(seg[0]), int(seg[1]), int(seg[2])))
    return out


def _device_pixel_to_effect(virtual: dict) -> dict[tuple[str, int], int]:
    """(device id, device pixel) -> this virtual's own effect-pixel index,
    by the SAME walk the fork's `Virtual._segments_by_device` makes and
    `emitters.carrier_segment_ranges` mirrors: every segment advances
    `data_start` by its own width, gap devices included."""
    group = _grouping(virtual)
    out: dict[tuple[str, int], int] = {}
    data_start = 0
    for device_id, lo, hi in _segment_rows(virtual):
        for p in range(lo, hi + 1):
            out[(device_id, p)] = (data_start + (p - lo)) // group
        data_start += hi - lo + 1
    return out


def resolve_composition(mapper_id: str, virtuals: dict[str, dict],
                        chain: Optional[list[dict]] = None) -> Composition:
    """The stored mapper -> the composition this run will address.

    THE SUBSTITUTION IS THE SAME ONE THE MAP'S RUN MAKES, and for the same
    measured reason: a copy-mapped carrier renders one segment's worth of
    pixels and copies it to every segment, so a pattern written to it would
    appear identically on all five segments and identify nothing
    (`scripts/check_copy_carrier_wave.py` measured this on the real
    pipeline). The patterns therefore go through each fixture's own DIRECT
    virtual, exactly as `emitters.substitutes_for` already resolves them —
    while the composition's own segment order, which is the ground truth
    for rows 2 and 4, stays the mapper's.

    REFUSES BY NAME rather than commissioning a partial composition: if one
    segment cannot be driven, the pixel COUNT is wrong, and row 1 is judged
    on that count. A quietly smaller denominator would turn a real gap into
    a pass."""
    mapper = (virtuals or {}).get(mapper_id)
    if not mapper:
        raise CompositionRefused(
            f"{mapper_id} is not rendering right now, so there is nothing to "
            f"commission. Check SPECTRA is driving the room, then press "
            f"Commission again.")
    rows = _segment_rows(mapper)
    if not rows:
        raise CompositionRefused(
            f"{mapper_id} has no segments configured, so there is no stored "
            f"composition to check against.")

    substitutes = dict(emitters_mod.substitutes_for(
        mapper_id, mapper, chain or [], virtuals or {}))
    direct = emitters_mod._splittable(mapper)[0]     # noqa: SLF001 (same module family)

    comp = Composition(mapper_id=mapper_id)
    if direct:
        comp.notes.append(
            f"{mapper_id} spans its own pixels, so the patterns are written "
            f"to it directly — no substitution needed.")
    else:
        comp.notes.append(
            f"{mapper_id} copies one effect onto every segment, so the "
            f"patterns are driven through each fixture's own strip "
            f"({', '.join(sorted(substitutes)) or 'none found'}) — the same "
            f"substitution a mapping run makes.")

    # index_of[(virtual, effect pixel)] -> composition index, built as the
    # mapper's segments are walked IN ITS OWN STORED ORDER. That order is
    # the ground truth rows 2 and 4 are judged against.
    plans: dict[str, dict[int, int]] = {}
    cursor = 0
    for seg_no, (device_id, lo, hi) in enumerate(rows):
        if direct:
            driver_id, driver = mapper_id, mapper
        else:
            driver_id, driver = _driver_for(device_id, substitutes, virtuals)
            if driver is None:
                raise CompositionRefused(
                    f"{mapper_id} segment {seg_no} is backed by {device_id}, "
                    f"and no virtual addresses that fixture's pixels on its "
                    f"own — so this segment cannot be lit separately and the "
                    f"composition cannot be commissioned as stored. Add a "
                    f"plain span virtual for {device_id}, or commission a "
                    f"composition whose fixtures each have one.")
        if _grouping(driver) != 1:
            raise CompositionRefused(
                f"{driver_id} groups {_grouping(driver)} pixels together, so "
                f"individual pixels cannot be addressed and a pixel-level "
                f"ground truth cannot be checked. Commissioning needs "
                f"grouping 1 on the virtual it drives.")
        lookup = _device_pixel_to_effect(driver)
        target = plans.setdefault(driver_id, {})
        for p in range(lo, hi + 1):
            effect_pixel = lookup.get((device_id, p))
            if effect_pixel is None:
                raise CompositionRefused(
                    f"{driver_id} does not carry {device_id} pixel {p}, which "
                    f"{mapper_id} segment {seg_no} names — the stored "
                    f"composition and the live configuration disagree, so "
                    f"there is no ground truth to judge against.")
            if effect_pixel in target:
                raise CompositionRefused(
                    f"{driver_id} pixel {effect_pixel} is claimed by two "
                    f"segments of {mapper_id}, so those pixels cannot be told "
                    f"apart in one run.")
            target[effect_pixel] = cursor + (p - lo)
        comp.segments.append(compare.Segment(
            index=seg_no, device_id=device_id, virtual_id=driver_id,
            start=cursor, end=cursor + (hi - lo)))
        cursor += hi - lo + 1

    for vid, mapping in plans.items():
        size = emitters_mod.effective_pixel_count(virtuals.get(vid) or {})
        arr = np.full(max(size, (max(mapping) + 1) if mapping else 0), -1,
                      dtype=np.int64)
        for effect_pixel, index in mapping.items():
            arr[effect_pixel] = index
        comp.pixel_map[vid] = arr
    return comp


def _driver_for(device_id: str, substitutes: dict[str, dict],
                virtuals: dict[str, dict]) -> tuple[str, Optional[dict]]:
    """The virtual to drive for one fixture: the substitution the mapping
    run already resolved, else any span virtual that carries that fixture's
    pixels. Deterministic (sorted) so two runs address the same thing."""
    for vid, virtual in sorted(substitutes.items()):
        if any(d == device_id for d, _lo, _hi in _segment_rows(virtual)):
            return vid, virtual
    for vid in sorted(virtuals or {}):
        virtual = virtuals[vid]
        if not emitters_mod._splittable(virtual)[0]:      # noqa: SLF001
            continue
        if any(d == device_id for d, _lo, _hi in _segment_rows(virtual)):
            return vid, virtual
    return "", None


# ── the stored 2-D layout (row 3's ground truth, when there is one) ────────

def stored_layout(mapper_id: str, mapper: dict, total: int,
                  profile: Optional[dict] = None
                  ) -> tuple[Optional[dict[int, tuple[float, float]]], str]:
    """The mapper's stored pixel LAYOUT, or None with the sentence saying
    why there is none.

    Two sources, both stored and neither invented:
      * a DEVICE PROFILE for this virtual (`storage/device_profiles/
        <id>.json`, the shape `crystal-mapper.json` already uses): rows,
        cols and a buffer index per cell.
      * the virtual's own `rows` > 1, which folds its buffer into a matrix.

    AND NOTHING ELSE. His real `tv-mapper` is `mapping: copy` with
    `rows: 1` and no shape map: it stores a pixel ORDER and no geometry at
    all. Deriving a rectangle from "it is wrapped around a television"
    would be precisely the plausible-looking answer this test exists to
    refuse, so the row is reported UNMEASURED with what would make it
    judgeable — and the run's verdict comes out incomplete rather than
    green."""
    if profile:
        rows = int(profile.get("rows") or 0)
        cols = int(profile.get("cols") or 0)
        count = int(profile.get("pixel_count") or (rows * cols))
        if rows > 1 and cols > 0 and count == total:
            return ({i: (((i % cols) + 0.5) / cols, ((i // cols) + 0.5) / rows)
                     for i in range(total)},
                    f"from the stored device profile for {mapper_id} "
                    f"({rows}x{cols})")
        return None, (
            f"the stored device profile for {mapper_id} describes "
            f"{count} pixels in {rows}x{cols}, which is not this "
            f"composition's {total} — there is no layout to fit against.")
    rows = int(((mapper or {}).get("config") or {}).get("rows") or 1)
    if rows > 1 and total % rows == 0:
        cols = total // rows
        return ({i: (((i % cols) + 0.5) / cols, ((i // cols) + 0.5) / rows)
                 for i in range(total)},
                f"from {mapper_id}'s own rows={rows} fold")
    return None, (
        f"{mapper_id} stores a pixel ORDER but no 2-D layout (rows="
        f"{rows}, no device profile), so there is no stored arrangement to "
        f"fit the decode against. Rows 1, 2 and 4's segment membership are "
        f"unaffected. To make this row judgeable, give {mapper_id} a device "
        f"profile with its real rows/cols — the same shape "
        f"storage/device_profiles/crystal-mapper.json already uses.")


def load_profile(virtual_id: str) -> Optional[dict]:
    path = os.path.join(str(config.REPO_ROOT), "storage", "device_profiles",
                        f"{virtual_id}.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


# ── the held-room program ──────────────────────────────────────────────────

def _dark_entry(vid: str) -> SceneDeviceConfig:
    return SceneDeviceConfig(
        target_kind="virtual", target=vid, effect_type=DARK_EFFECT_TYPE,
        params={"color": BLACK},
        # "fixed", never "set": a measuring write must not pick up the
        # room's active colour set — room_mapping's own rule.
        color=SceneColorAssignment(mode="fixed"),
        brightness=0.0, background_brightness=0.0)


class CommissionProgram(flare_preview_hold.PreviewProgram):
    """One program, three named steps, ONE hold.

    Every step writes the COMPLETE state of every in-scope virtual — never
    a delta — so a virtual can never be left carrying the previous
    pattern by an ordering accident. That is `room_mapping.MappingProgram`'s
    own rule, for the same reason.

      dark      every in-scope virtual black. Also the hold scene, so the
                snapshot is taken against it.
      full      every composition pixel lit; everything else black. The
                brightness reference the decode divides by, and the step
                whose ARRIVAL the latency row watches.
      pattern   whatever `set_patterns()` last handed in."""

    steps = ("dark", "full", "pattern")

    def __init__(self, virtual_ids: list[str], composition: Composition) -> None:
        self.virtual_ids = list(dict.fromkeys(virtual_ids))
        self.composition = composition
        self.patterns: dict[str, str] = {}
        self.hold_scene = SceneV2(
            name="· commissioning (dark) ·",
            devices=[_dark_entry(v) for v in self.virtual_ids])

    def set_patterns(self, patterns: dict[str, str]) -> None:
        self.patterns = dict(patterns)

    def full_patterns(self) -> dict[str, str]:
        return {vid: "".join("1" if i >= 0 else "0" for i in arr)
                for vid, arr in self.composition.pixel_map.items()}

    def extra_snapshot_writes(self, intensity: float) -> list[dict]:
        # Every virtual this program can touch has to enter the snapshot, or
        # close() hands some of them back and silently keeps the rest.
        return [{"virtual_id": vid} for vid in self.composition.pixel_map
                if vid not in set(self.virtual_ids)]

    def _writes(self, patterns: dict[str, str]) -> list[dict]:
        out = []
        for vid in dict.fromkeys(list(self.virtual_ids) + sorted(patterns)):
            pattern = patterns.get(vid)
            if pattern:
                out.append({"virtual_id": vid,
                            "effect_type": PATTERN_EFFECT_TYPE,
                            "config": {"color": WHITE, "pattern": pattern,
                                       "brightness": 1.0,
                                       "background_brightness": 0.0}})
            else:
                out.append({"virtual_id": vid,
                            "effect_type": DARK_EFFECT_TYPE,
                            "config": {"color": BLACK, "brightness": 0.0,
                                       "background_brightness": 0.0}})
        return out

    async def execute(self, step: str, ctx) -> dict:
        if step == "dark":
            patterns: dict[str, str] = {}
        elif step == "full":
            patterns = self.full_patterns()
        elif step == "pattern":
            patterns = self.patterns
        else:
            raise ValueError(f"unknown commissioning step: {step!r}")
        await ctx.apply_scene(writes=self._writes(patterns),
                              transition_ms=WRITE_TRANSITION_MS)
        return {"result": step, "lit_virtuals": sorted(patterns)}


# ── the run ────────────────────────────────────────────────────────────────

@dataclass
class Capture:
    label: str
    frames: int
    at_s: float


@dataclass
class RunResult:
    mapper_id: str
    ok: bool
    reason: str = ""
    refusal: str = ""
    pose_id: str = ""
    seconds: float = 0.0
    repeats: int = 0
    composition: dict = field(default_factory=dict)
    layout_note: str = ""
    decodes: list[dict] = field(default_factory=list)
    agreement: dict = field(default_factory=dict)
    table: dict = field(default_factory=dict)
    captures: list[dict] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    at: float = field(default_factory=time.time)

    @property
    def verdict(self) -> str:
        return str(self.table.get("verdict") or ("refused" if not self.ok else ""))

    def as_dict(self) -> dict:
        return {"mapper_id": self.mapper_id, "ok": self.ok,
                "reason": self.reason, "refusal": self.refusal,
                "verdict": self.verdict, "pose_id": self.pose_id,
                "seconds": round(self.seconds, 2), "repeats": self.repeats,
                "composition": self.composition,
                "layout_note": self.layout_note,
                "decodes": self.decodes, "agreement": self.agreement,
                "table": self.table, "captures": self.captures,
                "problems": self.problems, "notes": self.notes,
                "at": self.at}


async def _capture(deps: room_mapping.RunDeps, program: CommissionProgram,
                   step: str, label: str, result: RunResult, *,
                   watch_arrival: bool = False
                   ) -> tuple[Optional[np.ndarray], list, float]:
    """One capture: land the step, let it settle, average a window of
    full-resolution frames. Returns (average, timed frames, write time).

    `watch_arrival` collects frames FROM THE WRITE rather than after the
    settle — the only way to see WHEN each fixture's light appeared, which
    is what row 5 measures. The average still comes from the settled tail,
    so the reference frame it produces is identical either way: watching
    the arrival costs frames, never accuracy."""
    sess = deps.session
    held = await deps.open_hold(program, 1.0, step=step,
                                heartbeat_timeout_s=HOLD_HEARTBEAT_S)
    if not (held or {}).get("held"):
        raise HoldRefused(mapping_refusals.hold_refusal(
            str((held or {}).get("reason") or "no writes")))
    write_at = deps.clock()
    if watch_arrival:
        timed = await sess.gather_full(SETTLE_S + CAPTURE_S,
                                       min_frames=MIN_FRAMES)
        settled = [t for t in timed if t.at_s >= write_at + SETTLE_S]
    else:
        await deps.sleep(SETTLE_S)
        timed = await sess.gather_full(CAPTURE_S, min_frames=MIN_FRAMES)
        settled = timed
    result.captures.append({"label": label, "frames": len(settled),
                            "watched": len(timed),
                            "at_s": round(write_at, 3)})
    if len(settled) < MIN_FRAMES:
        return None, timed, write_at
    stack = np.stack([t.frame.astype(np.float64) for t in settled], axis=0)
    return stack.mean(axis=0), timed, write_at


class HoldRefused(Exception):
    """The room could not be held for a capture — already worded."""


async def _one_pass(deps: room_mapping.RunDeps, program: CommissionProgram,
                    composition: Composition, result: RunResult,
                    label: str) -> tuple[Optional[gray_code.Decode], dict]:
    """ONE full gray-code stack in ONE continuous hold: dark, full, then
    every bit and its inverse. The hold is closed by the caller's `finally`
    — never here, because a pass that raises must not leave the room dark
    for the next one."""
    sess = deps.session
    total = composition.total
    bits = gray_code.bits_needed(total)

    dark, _, _ = await _capture(deps, program, "dark", f"{label}/dark", result)
    if sess.run_abort:
        raise RunAborted(sess.run_abort)
    full, full_timed, full_at = await _capture(
        deps, program, "full", f"{label}/full", result, watch_arrival=True)
    if dark is None or full is None:
        raise NotEnoughFrames(
            f"not enough frames arrived for the {label} reference captures "
            f"(each needs {MIN_FRAMES}) — is the camera running and the "
            f"phone still connected?")
    latency = _latency_from_step(dark, full_timed, full_at)

    pairs = []
    for bit in range(bits):
        for invert in (False, True):
            patterns = {
                vid: gray_code.pattern_string(arr, bit, invert=invert)
                for vid, arr in composition.pixel_map.items()}
            program.set_patterns(patterns)
            frame, _, _ = await _capture(
                deps, program, "pattern",
                f"{label}/bit{bit}{'-inv' if invert else ''}", result)
            if sess.run_abort:
                raise RunAborted(sess.run_abort)
            if frame is None:
                raise NotEnoughFrames(
                    f"not enough frames arrived for {label} bit {bit}"
                    f"{' (inverse)' if invert else ''} — the stack cannot be "
                    f"decoded with a capture missing.")
            if invert:
                pairs[-1] = (pairs[-1][0], frame)
            else:
                pairs.append((frame, None))
    decode = gray_code.decode_stack(dark, full, pairs, total=total)
    return decode, latency


class RunAborted(Exception):
    """The session ended the run (camera lock lost, phone gone) — the
    session's own sentence is the message."""


class NotEnoughFrames(Exception):
    """A capture did not receive enough frames to average."""


def _latency_from_step(dark: np.ndarray, timed: list, write_at: float) -> dict:
    """When the light actually arrived, per FRAME, plus the cadence that
    bounds how well that can be known.

    The per-device split needs the decode (which comes later), so this
    keeps the raw material — each frame's time and its mean brightness
    ABOVE the dark reference, per camera pixel — and
    `_device_latencies` reduces it once the decode says which pixels
    belong to which fixture."""
    if len(timed) < 2:
        return {"resolution_ms": 1e9, "frames": len(timed),
                "write_at": write_at, "times": [], "stack": None, "dark": None}
    times = [float(t.at_s) for t in timed]
    gaps = np.diff(times)
    # kept as the bytes that arrived (never a float copy of the whole
    # window): a fast camera can put hundreds of frames in this window, and
    # only the handful of camera pixels belonging to each fixture are ever
    # differenced — see `_device_latencies`.
    return {"resolution_ms": float(np.median(gaps) * 1000.0),
            "frames": len(timed), "write_at": float(write_at),
            "times": times,
            "stack": np.stack([t.frame for t in timed], axis=0),
            "dark": np.asarray(dark, dtype=np.float64).reshape(-1)}


def _device_latencies(latency: dict, decode: gray_code.Decode,
                      composition: Composition) -> dict[str, float]:
    """Each fixture's own arrival, in ms after the write, from the same
    step the references were taken on.

    The crossing is the half-way point between that fixture's dark level
    and its settled level, linearly interpolated between the two frames
    that straddle it. Interpolation cannot beat the frame cadence for a
    step this sharp, which is exactly why the row reports
    `resolution_ms` and refuses to be judged when the cadence is coarser
    than the tolerance."""
    stack = latency.get("stack")
    if stack is None or not latency.get("times"):
        return {}
    times = latency["times"]
    write_at = latency["write_at"]
    flat = stack.reshape(len(times), -1)
    dark = latency["dark"]
    out: dict[str, float] = {}
    for device in composition.devices:
        wanted = set(composition.indices_for_device(device))
        pixels = np.flatnonzero(np.isin(decode.index_map, list(wanted)))
        if pixels.size < 8:
            continue
        trace = (flat[:, pixels].astype(np.float64)
                 - dark[pixels]).mean(axis=1)
        settled = float(np.median(trace[-max(1, len(trace) // 5):]))
        if settled <= 0:
            continue                     # this fixture never lit at all
        half = 0.5 * settled
        crossed = np.flatnonzero(trace >= half)
        if not crossed.size:
            continue
        k = int(crossed[0])
        if k == 0:
            # ALREADY LIT IN THE FIRST FRAME AFTER THE WRITE. Reported as
            # that frame's own time rather than dropped: at this cadence
            # "arrived within one frame" IS the measurement, and dropping
            # the fastest fixture would silently remove the reference every
            # other device is compared against.
            t = times[0]
        else:
            span = trace[k] - trace[k - 1]
            frac = 0.0 if span <= 0 else (half - trace[k - 1]) / span
            t = times[k - 1] + frac * (times[k] - times[k - 1])
        out[device] = (t - write_at) * 1000.0
    return out


def instrument_latencies() -> dict[str, float]:
    """The PER-DEVICE instrument's own reading for each fixture, from its
    stored measurement log — row 5's ground truth. Read through
    `device_equalization`, never re-derived: that module already owns
    subtracting today's applied delay back out, and a second copy of that
    arithmetic is how two instruments start disagreeing for a reason
    neither of them measured."""
    from spectra.services import av_sync_session, device_equalization
    try:
        from spectra.services import device_settings
        offsets = device_settings.resolve_offsets()
    except Exception:                                  # noqa: BLE001
        offsets = {}
    records = av_sync_session.load_measurements()
    return {m.device_id: m.intrinsic_ms
            for m in device_equalization.per_device_measurements(records, offsets)}


async def run_commission(mapper_id: str, deps: room_mapping.RunDeps, *,
                         repeat: int = 1,
                         layout: Optional[dict] = None,
                         instrument: Optional[dict[str, float]] = None
                         ) -> RunResult:
    """The whole test: resolve the composition, gray-code it (once, or
    twice back to back), and judge the frozen table.

    REFUSES BEFORE TOUCHING A LIGHT when the camera is not locked, when
    SPECTRA is not driving the lights (the pattern lamp is an effect inside
    this process, and the external LedFX service has never heard of it), or
    when the composition cannot be addressed as stored. Nothing is written
    and nothing is stored on any of those paths.

    RESTORES IN A `finally`, three separate things, in the order they were
    taken: the hold (the lights), any virtual this run brought up, and the
    session's full-frame ring."""
    started = deps.clock()
    sess = deps.session
    result = RunResult(mapper_id=mapper_id, ok=False,
                       pose_id=getattr(sess, "pose_id", ""),
                       repeats=max(1, min(2, int(repeat or 1))))

    refusal = sess.refusal()
    if refusal:
        result.reason = refusal
        result.refusal = "camera_lock"
        return result
    if not deps.spectra_owns():
        result.reason = (
            "commissioning needs SPECTRA to be driving the lights: the "
            "pattern lamp is an effect inside this process, and the external "
            "LedFX service does not have it. Take the room back on the "
            "ownership bar, then press Commission again.")
        result.refusal = "ownership"
        return result

    try:
        scope = await room_mapping.live_virtual_ids(deps.get_virtuals)
        virtuals = await deps.get_virtuals() or {}
    except Exception as exc:                           # noqa: BLE001
        named = mapping_refusals.ownership_refusal(exc)
        if named is None:
            raise
        result.reason, result.refusal = named, "ownership"
        return result

    chains = {}
    try:
        chains = await deps.carrier_devices() or {}
    except Exception as exc:                           # noqa: BLE001
        result.problems.append(
            f"the device list could not be read ({exc}), so the substitution "
            f"falls back to whatever virtual addresses each fixture")
    try:
        composition = resolve_composition(mapper_id, virtuals,
                                          chains.get(mapper_id) or [])
    except CompositionRefused as exc:
        result.reason, result.refusal = str(exc), "composition"
        return result
    result.composition = composition.as_dict()
    result.notes.extend(composition.notes)

    if layout is None:
        layout, layout_note = stored_layout(
            mapper_id, virtuals.get(mapper_id) or {}, composition.total,
            load_profile(mapper_id))
    else:
        layout_note = "supplied by the caller"
    result.layout_note = layout_note

    plan = _ActivationPlan(composition)
    scope, activated, not_up = await room_mapping.activate_for_capture(
        plan, scope, deps)
    result.problems.extend(not_up)
    if activated:
        result.notes.append(
            f"Brought up {', '.join(activated)} for the capture and put "
            f"{'it' if len(activated) == 1 else 'them'} back afterwards.")

    program = CommissionProgram(scope, composition)
    decodes: list[gray_code.Decode] = []
    latency_by_device: dict[str, float] = {}
    resolution_ms = 1e9
    sess.keep_full_frames = True
    sess.run_abort = None
    try:
        fixtures = await _fixtures_for(composition, chains, deps)
        readings = await fixture_brightness.read_all(fixtures)
        warning = fixture_brightness.warning_for(readings)
        if warning:
            result.problems.append(warning)
        async with fixture_brightness.owned(fixtures, readings) as owned:
            for pass_no in range(result.repeats):
                label = f"run{pass_no + 1}"
                try:
                    decode, latency = await _one_pass(
                        deps, program, composition, result, label)
                finally:
                    # ONE CONTINUOUS HOLD PER PASS, released before the next
                    # one opens — and released whatever happened inside it.
                    try:
                        await deps.close_hold()
                    except Exception:                  # noqa: BLE001
                        logger.warning("commissioning: releasing the hold "
                                       "after %s failed; the hold sweep owns "
                                       "it from here", label, exc_info=True)
                if decode is not None:
                    decodes.append(decode)
                    if not latency_by_device:
                        latency_by_device = _device_latencies(
                            latency, decode, composition)
                        resolution_ms = float(latency.get("resolution_ms", 1e9))
        if owned.note:
            result.notes.append(owned.note)
        result.problems.extend(owned.problems)
    except (RunAborted, NotEnoughFrames, HoldRefused) as exc:
        result.reason = str(exc)
        result.refusal = ("aborted" if isinstance(exc, RunAborted)
                          else "hold" if isinstance(exc, HoldRefused)
                          else "frames")
    except Exception as exc:                           # noqa: BLE001
        named = mapping_refusals.ownership_refusal(exc)
        if named is None:
            raise
        result.reason, result.refusal = mapping_refusals.MID_RUN_LOSS, "ownership"
    finally:
        sess.keep_full_frames = False
        sess.full.clear()
        left_on = await room_mapping.deactivate_after_capture(activated, deps)
        if left_on:
            result.problems.append(
                f"left rendering after the capture (they were idle before "
                f"it): {', '.join(left_on)} — turn them off on the devices "
                f"page, or run this again")

    result.seconds = deps.clock() - started
    if not decodes:
        if not result.reason:
            result.reason = ("no capture stack was decoded — see the "
                             "problems for why")
        return result
    result.decodes = [d.as_dict() for d in decodes]
    if len(decodes) > 1:
        result.agreement = gray_code.agreement(decodes[0], decodes[1])
    result.table = compare.judge(
        decodes[0], composition.segments, layout, layout_note,
        latency_measured=latency_by_device,
        latency_instrument=(instrument if instrument is not None
                            else _safe_instrument(result)),
        latency_resolution_ms=resolution_ms)
    result.ok = True
    return result


def _safe_instrument(result: RunResult) -> dict[str, float]:
    try:
        return instrument_latencies()
    except Exception as exc:                           # noqa: BLE001
        result.problems.append(
            f"the per-device instrument's own readings could not be read "
            f"({exc}), so the latency row has nothing to compare against")
        return {}


class _ActivationPlan:
    """`room_mapping.activate_for_capture` reads exactly one thing off a
    plan — the virtuals its emitters need — so this is that, and nothing
    else. Reusing that function (rather than a second copy of "bring it up
    and put it back") is what keeps the `active` flag's restore in ONE
    place; the run's own `finally` calls its partner."""

    def __init__(self, composition: Composition) -> None:
        self.emitters = [
            emitters_mod.Emitter(emitter_id=vid, carrier_id=vid, label=vid,
                                 virtual_ids=[vid])
            for vid in composition.virtual_ids]


async def _fixtures_for(composition: Composition, chains: dict,
                        deps: room_mapping.RunDeps) -> list:
    """The live driver objects for the fixtures THIS composition lights —
    never the whole house, so a lamp in another room is neither read nor
    turned up."""
    wanted = set(composition.devices)
    for entries in chains.values():
        for entry in entries or []:
            if entry.get("id") in wanted:
                wanted.add(str(entry["id"]))
    try:
        return [d for d in (await deps.fixture_devices() or [])
                if str(getattr(d, "id", "") or "") in wanted]
    except Exception as exc:                           # noqa: BLE001
        logger.info("commissioning: no driver layer to read brightness: %s", exc)
        return []


# ── the store ──────────────────────────────────────────────────────────────

def _path(path=None):
    return config.COMMISSIONING_FILE if path is None else path


def load_results(path=None) -> list[dict]:
    p = _path(path)
    try:
        if not os.path.exists(p):
            return []
        with open(p, "r", encoding="utf-8") as fh:
            return list(json.load(fh).get("results") or [])
    except Exception:                                  # noqa: BLE001
        logger.exception("commissioning: unreadable result store %s", p)
        return []


def save_result(result: RunResult, path=None) -> dict:
    """Append one run, bounded and atomic — the store convention across
    spectra/. A REFUSED run is stored too: "we tried and the camera was not
    locked" is a fact about the evening, and a store that only keeps
    successes cannot be read as a record of what happened."""
    p = _path(path)
    body = result.as_dict()
    kept = (load_results(p) + [body])[-MAX_STORED_RESULTS:]
    os.makedirs(os.path.dirname(str(p)) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(str(p)) or ".",
                               prefix="commissioning", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"results": kept}, fh, indent=2, default=_jsonable)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return body


def _jsonable(value: Any):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, float) and math.isnan(value):
        return None
    raise TypeError(f"{type(value).__name__} is not JSON serialisable")
