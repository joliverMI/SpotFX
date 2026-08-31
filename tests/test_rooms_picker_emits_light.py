"""THE MAPPING PICKER OFFERS ONLY LIGHT-EMITTING DEVICES.

He hit it live: gap-crystal-mapper — a dummy that is load-bearing in the
crystal's mapper chain, and therefore genuinely IN USE — appeared in the
Rooms page's device picker. `device_usage`'s list answers "does this back
something driven", the right question for the /devices page and the wrong
one for a picker whose act is photographing what a fixture lights. One
list, two questions; `emitters.emits_light` is the second one.

Proved here, against his real config shape (tests/test_device_usage.py's
own HIS_ROOM, imported rather than re-typed):

  * the picker offers exactly the physical in-use set — 8 devices, 6 wled
    and 2 hue, with both load-bearing dummies absent;
  * the /devices page's own list is UNCHANGED — all 21, both dummies still
    flagged in use;
  * a room that already names a dummy still maps, with the dummy SKIPPED
    and named in the run's problems, never silently dropped.
"""
from __future__ import annotations

import asyncio

import pytest

from spectra.api import rooms as rooms_api
from spectra.services import device_console, emitters

from tests.test_device_usage import (HIS_IN_USE, HIS_ROOM,  # noqa: F401
                                     his_room)


PHYSICAL_IN_USE = {d for d in HIS_IN_USE
                   if d not in ("gap-crystal-mapper", "radial-dummy")}


def test_emits_light_is_a_type_rule_and_takes_a_dict_or_a_type():
    assert emitters.emits_light({"id": "crystal", "type": "wled"}) is True
    assert emitters.emits_light({"id": "hue-lights", "type": "Hue"}) is True
    assert emitters.emits_light({"id": "gap-crystal-mapper",
                                 "type": "dummy"}) is False
    assert emitters.emits_light("dummy") is False
    assert emitters.emits_light("wled") is True
    # unknown/absent type is offered rather than hidden — the exclusion is
    # an enumerated list, not a guess
    assert emitters.emits_light({"id": "x"}) is True


def test_the_picker_offers_exactly_the_physical_in_use_set(his_room):
    body = asyncio.run(rooms_api.room_devices())
    offered = {d["id"] for d in body["devices"]}
    in_use = {d["id"] for d in body["devices"] if d["in_use"]}
    # the picker's default view is the in-use half of what it is handed —
    # eight physical fixtures, six WLED and two Hue
    assert in_use == PHYSICAL_IN_USE
    assert len(in_use) == 8
    used_types = sorted(d["type"] for d in body["devices"] if d["in_use"])
    assert used_types.count("wled") == 6 and used_types.count("hue") == 2
    # and BOTH load-bearing dummies are gone from the listing entirely —
    # "Show all" cannot reach them either, because a camera cannot
    for dummy in ("gap-crystal-mapper", "radial-dummy"):
        assert dummy not in offered
    assert all(emitters.emits_light(d) for d in body["devices"])


def test_the_devices_page_list_is_untouched(his_room):
    data = asyncio.run(device_console.list_devices())
    assert len(data["devices"]) == 21
    by_id = {d["id"]: d for d in data["devices"]}
    assert by_id["gap-crystal-mapper"]["in_use"] is True
    assert by_id["radial-dummy"]["in_use"] is True
    assert data["usage"]["in_use"] == 10


def test_a_room_already_holding_a_dummy_maps_with_it_skipped_and_named():
    virtuals = {"crystal-mapper": {"pixel_count": 4, "config": {},
                                   "segments": [["crystal", 0, 3, False]]}}
    plan = emitters.plan_run(
        ["crystal", "gap-crystal-mapper"], virtuals,
        {"crystal": ["crystal-mapper"],
         "gap-crystal-mapper": ["crystal-mapper"]},
        {"crystal": "wled", "gap-crystal-mapper": "dummy"},
        granularity="device")
    assert [e.device_id for e in plan.emitters] == ["crystal"]
    said = [p for p in plan.problems if p.startswith("gap-crystal-mapper:")]
    assert len(said) == 1
    assert "emits no light" in said[0] and "skipped" in said[0]
