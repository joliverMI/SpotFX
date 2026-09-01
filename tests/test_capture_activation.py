"""HIS SECOND FAILED RUN: the carrier in front of the strip, and the strip
that was asleep.

Established cause, not re-derived: `tv-mapper` is COPY-mapped (it renders one
segment and copies it to every segment), so it cannot be lit in parts; the
fixture's own splittable span virtual `tv-backlight` (560 px) exists but is
INACTIVE, so `live_virtual_ids` dropped it. Block granularity correctly
refused the only remaining route and the run produced one whole emitter with
its reason attached where nobody could see it.

The question answered FIRST, on the real render pipeline
(`scripts/check_copy_carrier_wave.py`): the per-pixel gain mask multiplies
the effect buffer BEFORE a copy-mapped virtual expands it into each segment.
So a wave's phase is identical in every segment at every instant — a copy
carrier is not a wave surface at all, however finely it is mapped. That is
why the substitution happens at BOTH ends: light the direct virtual to
measure it, drive the direct virtual to wave along it.

Proved here:
  * the enumeration PREFERS a splittable direct virtual over an unsplittable
    carrier, and the footprints still carry the carrier's own name;
  * the run BRINGS UP an inactive substitute and PUTS IT BACK — including
    on the failure path;
  * every reason this path writes reaches a human surface: the unsplittable
    note (tonight's), a failed activation, a fixture left rendering, and a
    device list that could not be read.
"""
from __future__ import annotations

import asyncio

import pytest

from spectra.models.room_map import AxisCalibration, Point, RoomMap
from spectra.services import emitters as em
from spectra.services import room_mapping

AXIS = AxisCalibration(kind="vertical", floor=Point(x=0.5, y=1.0),
                       ceiling=Point(x=0.5, y=0.0))
CARRIER = "tv-mapper"
DIRECT = "tv-backlight"
CHAIN = [{"id": "tv-backlight", "type": "wled"},
         {"id": "sconce-kitchen-left", "type": "wled"},
         {"id": "sconce-kitchen-right", "type": "wled"}]


def _copy_carrier():
    """His tv-mapper: copy-mapped across three fixtures."""
    return {"active": True, "pixel_count": 60, "config": {"grouping": 1,
                                                          "mapping": "copy"},
            "segments": [["tv-backlight", 0, 19, False],
                         ["sconce-kitchen-left", 0, 19, False],
                         ["sconce-kitchen-right", 0, 19, False]],
            "effect": {"type": "singleColor", "config": {}}}


def _direct(active=False, pixels=560):
    """The fixture's own strip — splittable, and asleep."""
    return {"active": active, "pixel_count": pixels,
            "config": {"grouping": 1, "mapping": "span"},
            "segments": [["tv-backlight", 0, pixels - 1, False]],
            "effect": {"type": "singleColor", "config": {}} if active else {}}


# ── 1. the enumeration prefers the direct virtual ──────────────────────────

def test_a_splittable_direct_virtual_is_preferred_over_an_unsplittable_carrier():
    subs = em.substitutes_for(CARRIER, _copy_carrier(), CHAIN,
                              {CARRIER: _copy_carrier(), DIRECT: _direct()})
    assert [vid for vid, _v in subs] == [DIRECT]
    plan = em.plan_run([CARRIER], {CARRIER: _copy_carrier()}, {CARRIER: CHAIN},
                       substitutes={CARRIER: subs}, granularity="auto",
                       block_pixels=30)
    assert len(plan.emitters) == 18, "blocks over the strip's own 560 pixels"
    assert plan.emitters[0].emitter_id.startswith(f"{DIRECT}:blk")
    assert {e.carrier_id for e in plan.emitters} == {CARRIER}, (
        "the footprints stay under what he picked, not the substitute")
    assert plan.per_carrier[CARRIER] == "block"
    assert any(DIRECT in n and CARRIER in n for n in plan.notes), (
        "and the page is TOLD the run went through the fixture's own strip")


def test_a_splittable_carrier_never_gets_a_substitute():
    span = {"active": True, "pixel_count": 60, "config": {"mapping": "span"},
            "segments": [["tv-backlight", 0, 59, False]]}
    assert em.substitutes_for(CARRIER, span, CHAIN,
                              {CARRIER: span, DIRECT: _direct()}) == []


def test_an_explicit_whole_run_still_measures_the_carrier_itself():
    """"Whole" is a deliberate choice — one measurement of what he picked —
    so it is not quietly redirected through something else."""
    subs = em.substitutes_for(CARRIER, _copy_carrier(), CHAIN,
                              {CARRIER: _copy_carrier(), DIRECT: _direct()})
    plan = em.plan_run([CARRIER], {CARRIER: _copy_carrier()}, {CARRIER: CHAIN},
                       substitutes={CARRIER: subs}, granularity="whole")
    assert [e.emitter_id for e in plan.emitters] == [CARRIER]
    assert plan.notes == []


def test_one_substitute_per_device_never_two_claiming_the_same_pixels():
    alt = dict(_direct())
    alt["pixel_count"] = 100
    all_virtuals = {CARRIER: _copy_carrier(), DIRECT: _direct(),
                    "tv-backlight-copy": alt}
    subs = em.substitutes_for(CARRIER, _copy_carrier(), CHAIN, all_virtuals)
    assert len(subs) == 1, "the same fixture must not be mapped twice"


# ── 2. the reason that died on his run ─────────────────────────────────────

def test_the_unsplittable_reason_reaches_the_plan_not_just_the_emitter():
    """Tonight's defect: "auto" resolved to whole BECAUSE the carrier is
    unsplittable, and the branch returned before the reason was computed —
    so a run refused a granularity and said nothing a human could read."""
    plan = em.plan_run([CARRIER], {CARRIER: _copy_carrier()}, {CARRIER: CHAIN},
                       granularity="auto")
    assert len(plan.emitters) == 1
    assert plan.emitters[0].note, "the emitter still carries it"
    assert any("copies one effect onto every segment" in p
               for p in plan.problems), "and it LEAVES, into the wire body"
    assert "problems" in plan.as_dict() and plan.as_dict()["problems"]


def test_a_bulb_is_not_reported_as_a_refusal_it_is_simply_one_piece():
    bulb = {"active": True, "pixel_count": 1, "config": {"mapping": "span"},
            "segments": [["hue", 0, 0, False]]}
    plan = em.plan_run(["hues"], {"hues": bulb},
                       {"hues": [{"id": "hue", "type": "hue"}]},
                       granularity="auto")
    assert plan.problems == [] and plan.warnings == []


# ── 3. the run brings the strip up, and puts it back ───────────────────────

class _Session:
    pose_id = "pose-1"
    run_abort = None
    closed = False

    class lock:
        exposure_locked = True
        white_balance_locked = True
        exposure_mode = "manual"
        white_balance_mode = "manual"

    def __init__(self):
        self._n = 0

    def refusal(self):
        return None

    async def gather(self, seconds, min_frames=1):
        import numpy as np
        self._n += 1
        value = 0.0 if self._n % 2 else 0.5
        grid = np.full((36, 64), value, dtype=np.float64)
        return [grid, grid], [10, 10]


def _deps(activated, *, activate_raises=False, deactivate_raises=False,
          chains_raise=False, open_hold=None):
    live = {CARRIER: _copy_carrier()}

    async def get_virtuals():
        out = dict(live)
        if DIRECT in activated:
            out[DIRECT] = _direct(active=True)
        return out

    async def carrier_devices():
        if chains_raise:
            raise RuntimeError("the device list is unreadable")
        return {CARRIER: CHAIN}

    async def activate(vid):
        if activate_raises:
            raise OSError("no route to host")
        activated.append(vid)

    async def deactivate(vid):
        if deactivate_raises:
            raise OSError("no route to host")
        activated.remove(vid)

    async def default_open(program, intensity, *, step="fire",
                           heartbeat_timeout_s=0.0, max_duration_s=None):
        return {"held": True}

    async def close_hold():
        return None

    async def sleep(_s):
        return None

    return room_mapping.RunDeps(
        session=_Session(), get_virtuals=get_virtuals,
        carrier_devices=carrier_devices, activate=activate,
        deactivate=deactivate, open_hold=open_hold or default_open,
        close_hold=close_hold, sleep=sleep, spectra_owns=lambda: True)


def _run(deps, granularity="auto", tmp_path=None, monkeypatch=None):
    if tmp_path is not None:
        from spectra import config as scfg
        monkeypatch.setattr(scfg, "ROOM_MAPS_FILE", tmp_path / "maps.json")
    room = RoomMap(name="Living room", carrier_ids=[CARRIER], axis=AXIS)
    return room, asyncio.run(room_mapping.run_mapping(
        room, deps, granularity=granularity, block_pixels=30))


def test_the_run_brings_up_the_sleeping_strip_and_puts_it_back(tmp_path,
                                                               monkeypatch):
    activated: list[str] = []
    # the substitute is only findable because resolve_plan reads ALL
    # virtuals, not the live ones — it is asleep, which is the whole point
    deps = _deps(activated)
    real_get = deps.get_virtuals

    async def all_virtuals():
        out = await real_get()
        out.setdefault(DIRECT, _direct(active=DIRECT in activated))
        return out

    deps.get_virtuals = all_virtuals
    room, result = _run(deps, tmp_path=tmp_path, monkeypatch=monkeypatch)

    assert result.ok is True
    assert len(result.emitters) == 18 and all(e.mapped for e in result.emitters)
    assert activated == [], "the strip was put back to sleep afterwards"
    assert any(DIRECT in n for n in result.notes), (
        "and the run SAYS it brought something up")
    assert room.mapped_carriers() == [CARRIER]


def test_the_strip_is_put_back_even_when_the_run_fails(tmp_path, monkeypatch):
    activated: list[str] = []

    async def refuse_hold(program, intensity, *, step="fire",
                          heartbeat_timeout_s=0.0, max_duration_s=None):
        return {"held": False, "reason": "no writes"}

    deps = _deps(activated, open_hold=refuse_hold)
    real_get = deps.get_virtuals

    async def all_virtuals():
        out = await real_get()
        out.setdefault(DIRECT, _direct(active=DIRECT in activated))
        return out

    deps.get_virtuals = all_virtuals
    _room, result = _run(deps, tmp_path=tmp_path, monkeypatch=monkeypatch)
    assert result.ok is False
    assert activated == [], "a failed run does not leave his strip lit"


def test_a_failed_activation_is_named_not_only_logged(tmp_path, monkeypatch):
    activated: list[str] = []
    deps = _deps(activated, activate_raises=True)
    real_get = deps.get_virtuals

    async def all_virtuals():
        out = await real_get()
        out.setdefault(DIRECT, _direct())
        return out

    deps.get_virtuals = all_virtuals
    _room, result = _run(deps, tmp_path=tmp_path, monkeypatch=monkeypatch)
    assert any(DIRECT in p and "brought up" in p for p in result.problems)
    assert result.ok is False


def test_a_strip_left_rendering_is_named_because_the_room_really_changed(
        tmp_path, monkeypatch):
    activated: list[str] = []
    deps = _deps(activated, deactivate_raises=True)
    real_get = deps.get_virtuals

    async def all_virtuals():
        out = await real_get()
        out.setdefault(DIRECT, _direct(active=DIRECT in activated))
        return out

    deps.get_virtuals = all_virtuals
    _room, result = _run(deps, tmp_path=tmp_path, monkeypatch=monkeypatch)
    assert any("left rendering" in p and DIRECT in p for p in result.problems)


def test_an_unreadable_device_list_says_its_own_check_is_off(tmp_path,
                                                             monkeypatch):
    """Without the chain the emits-light backstop cannot run. Proceeding is
    fine; proceeding SILENTLY with a check switched off is not."""
    activated: list[str] = []
    deps = _deps(activated, chains_raise=True)
    _room, result = _run(deps, granularity="whole", tmp_path=tmp_path,
                         monkeypatch=monkeypatch)
    assert any("device list could not be read" in p for p in result.problems)
