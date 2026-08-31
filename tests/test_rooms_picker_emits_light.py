"""THE MAPPING PICKER LISTS CARRIERS A CAMERA CAN SEE.

He hit it live: `gap-crystal-mapper` — a dummy, load-bearing in the
crystal's mapper chain and therefore genuinely IN USE — appeared in the
Rooms page's device picker. Then his clarification moved the criterion
rather than only narrowing it: "i want to be able to work with the devices
that i directly use in spectra even if they have layers of virtuals before
shining. The devices that actually run effects should be the ones that are
shown by default and these are the ones i want to calibrate."

So the picker's question is "what do I address that a camera can see" — a
composite: genuinely driven (room_topology) AND the segment chain reaches a
light-emitting fixture (emitters.emits_light). `device_usage`'s `in_use`
answers a different question — "does this back something driven" — which is
the right one for the /devices page and stays untouched there.

Proved here, against his real config shape (tests/test_device_usage.py's own
HIS_ROOM, imported rather than re-typed):

  * the picker lists exactly his six carriers, and radial-dummy — driven,
    but reaching no emitter — is hidden WITH its reason;
  * every layer virtual (masks, foregrounds, backgrounds, gap placeholders)
    is absent, because none of them is driven;
  * the /devices page's own list is UNCHANGED — all 21, both dummies still
    flagged in use;
  * enumerating tv-mapper at block granularity spans its FULL pixel space
    across all three fixtures it fans out to — the thing a device-keyed
    enumeration could never express;
  * a room that still names a carrier whose chain emits nothing maps with
    it SKIPPED and named, never silently.
"""
from __future__ import annotations

import asyncio

import pytest

from spectra.api import rooms as rooms_api
from spectra.services import carriers, device_console, emitters

from tests.test_device_usage import (HIS_DRIVEN, HIS_ROOM,  # noqa: F401
                                     his_room)


#: His six offerable carriers. radial-dummy is driven and deliberately not
#: here: its whole chain is one dummy device, so a camera has nothing to
#: photograph.
HIS_CARRIERS = {"crystal-mapper", "dining-hues", "hue-lights", "hues",
                "single-color-effect", "tv-mapper"}


def _entries():
    return [{"id": did, "type": typ, "config": {"name": name},
             "virtuals": list(virtuals)}
            for did, typ, name, virtuals in HIS_ROOM]


# ── the predicate, and the chain it is applied at ──────────────────────────

def test_emits_light_is_a_type_rule_and_takes_a_dict_or_a_type():
    assert emitters.emits_light({"id": "crystal", "type": "wled"}) is True
    assert emitters.emits_light({"id": "hue-lights", "type": "Hue"}) is True
    assert emitters.emits_light({"id": "gap-crystal-mapper",
                                 "type": "dummy"}) is False
    assert emitters.emits_light("dummy") is False
    assert emitters.emits_light("wled") is True
    # an unknown/absent type is offered rather than hidden — the exclusion
    # is an enumerated list, not a guess
    assert emitters.emits_light({"id": "x"}) is True


def test_the_chain_check_is_what_hides_a_carrier_not_the_picked_thing():
    """crystal-mapper's chain contains a DUMMY and is still offered, because
    the same chain reaches the crystal. The check is on the chain, never on
    one member of it."""
    chains = carriers.devices_by_carrier(_entries())
    assert {d["id"] for d in chains["crystal-mapper"]} == {
        "gap-crystal-mapper", "crystal"}
    assert carriers.reaches_an_emitter(chains["crystal-mapper"]) is True
    assert carriers.reaches_an_emitter(chains["radial-dummy"]) is False


# ── the picker, against his real config shape ──────────────────────────────

def test_the_picker_lists_exactly_his_six_carriers():
    rows = carriers.carrier_rows(_entries(), HIS_DRIVEN)
    assert {r["id"] for r in rows} == HIS_CARRIERS
    by_id = {r["id"]: r for r in rows}
    # the four that fan out to more than one fixture — the whole reason a
    # device-keyed picker could not name what he calibrates
    assert set(by_id["tv-mapper"]["devices"]) == {
        "tv-backlight", "sconce-kitchen-left", "sconce-kitchen-right"}
    assert set(by_id["hues"]["devices"]) == {"hue-lights", "dining-hues"}
    assert set(by_id["single-color-effect"]["devices"]) == {
        "porch-rail", "dining-table"}
    # the chain dummy is never offered as a fixture of the carrier it backs
    assert by_id["crystal-mapper"]["devices"] == ["crystal"]


def test_radial_dummy_is_hidden_with_its_reason_not_silently():
    hidden = carriers.hidden_rows(_entries(), HIS_DRIVEN)
    assert [h["id"] for h in hidden] == ["radial-dummy"]
    assert "emits light" in hidden[0]["reason"]


def test_no_layer_virtual_is_ever_offered():
    offered = {r["id"] for r in carriers.carrier_rows(_entries(), HIS_DRIVEN)}
    for layer in ("crystal-mapper-mask", "crystal-mapper-foreground",
                  "crystal-mapper-background", "single-color-effect-mask",
                  "gap-matrix", "gap-mapped", "gap-crystal-mapper",
                  "sconce-kitchen-left-seg-0"):
        assert layer not in offered, layer


def test_an_absent_ground_truth_is_no_restriction_but_the_chain_still_is():
    """A fresh install shows a list rather than an empty page — and a
    carrier a camera cannot see is still not offered, because that is true
    whether or not anything is seeded."""
    rows = carriers.carrier_rows(_entries(), set())
    ids = {r["id"] for r in rows}
    assert HIS_CARRIERS <= ids
    assert "radial-dummy" not in ids
    assert "crystal-mapper-mask" not in ids


def test_the_route_answers_with_those_carriers_and_names_the_fixtures(his_room):
    body = asyncio.run(rooms_api.room_carriers())
    assert {r["id"] for r in body["carriers"]} == HIS_CARRIERS
    assert [h["id"] for h in body["hidden"]] == ["radial-dummy"]
    tv = next(r for r in body["carriers"] if r["id"] == "tv-mapper")
    assert set(tv["device_names"]) == {"WLED", "Sconce, Kitchen, Left",
                                       "Sconce, Kitchen, Right"}


def test_the_devices_page_list_is_untouched(his_room):
    data = asyncio.run(device_console.list_devices())
    assert len(data["devices"]) == 21
    by_id = {d["id"]: d for d in data["devices"]}
    assert by_id["gap-crystal-mapper"]["in_use"] is True
    assert by_id["radial-dummy"]["in_use"] is True
    assert data["usage"]["in_use"] == 10


# ── the enumeration, keyed by carrier ──────────────────────────────────────

def _tv_mapper_virtual():
    """His tv-mapper's shape: three fixtures' segments in ONE buffer."""
    return {"active": True, "pixel_count": 90, "config": {"grouping": 1},
            "segments": [["tv-backlight", 0, 49, False],
                         ["sconce-kitchen-left", 0, 19, False],
                         ["sconce-kitchen-right", 0, 19, False]]}


def test_enumerating_tv_mapper_spans_every_fixture_it_reaches():
    virtual = _tv_mapper_virtual()
    chain = [{"id": d, "type": "wled"} for d in
             ("tv-backlight", "sconce-kitchen-left", "sconce-kitchen-right")]
    plan = emitters.plan_run(["tv-mapper"], {"tv-mapper": virtual},
                             {"tv-mapper": chain},
                             granularity="block", block_pixels=30)
    assert plan.per_carrier == {"tv-mapper": "block"}
    covered = {i for e in plan.emitters
               for r in e.ranges for i in range(r.start, r.end + 1)}
    assert covered == set(range(90)), "the whole carrier, not one fixture's third"
    assert [e.emitter_id for e in plan.emitters] == [
        "tv-mapper:blk0[0-29]", "tv-mapper:blk1[30-59]", "tv-mapper:blk2[60-89]"]
    # the sconces' pixels are in there — the part a device-keyed enumeration
    # keyed on tv-backlight could never have reached
    assert 50 in covered and 89 in covered


def test_a_room_holding_an_unphotographable_carrier_skips_it_and_says_so():
    virtual = {"pixel_count": 4, "config": {}, "segments": []}
    plan = emitters.plan_run(
        ["crystal-mapper", "radial-dummy"],
        {"crystal-mapper": virtual, "radial-dummy": virtual},
        {"crystal-mapper": [{"id": "gap-crystal-mapper", "type": "dummy"},
                            {"id": "crystal", "type": "wled"}],
         "radial-dummy": [{"id": "radial-dummy", "type": "dummy"}]},
        granularity="whole")
    assert [e.carrier_id for e in plan.emitters] == ["crystal-mapper"]
    said = [p for p in plan.problems if p.startswith("radial-dummy:")]
    assert len(said) == 1
    assert "emits light" in said[0] and "skipped" in said[0]
