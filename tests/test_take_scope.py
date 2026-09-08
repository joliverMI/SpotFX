"""WHICH FIXTURES A TAKE MAY BRING UP (spectra/services/take_scope.py) —
the pure half, offline.

`tests/test_scoped_take_release.py` proves what a scoped take DOES at the
emitted light and at the bridge. This file proves the rule that decides the
scope, including every case where it must refuse to narrow: an unresolvable
scope that guessed narrow would bring the room up missing the fixture the
run needed, and a night is not cheap to waste.

The config used here is HIS SHAPE, minimally: a copy-mapped kitchen carrier
fanning out to three fixtures, and one `hues` virtual spanning both Hue
entertainment groups.
"""
from __future__ import annotations

import json

import pytest

from spectra.services import take_scope


def _virtual(vid, segments):
    return {"id": vid, "segments": [[d, a, b, False, 0] for d, a, b in segments]}


CONFIG_VIRTUALS = {v["id"]: v for v in [
    _virtual("tv-mapper", [("tv-backlight", 0, 559),
                           ("sconce-left", 0, 87),
                           ("sconce-right", 0, 87)]),
    _virtual("tv-backlight", [("tv-backlight", 0, 559)]),
    _virtual("sconce-left", [("sconce-left", 0, 87)]),
    _virtual("sconce-right", [("sconce-right", 0, 87)]),
    _virtual("sconce-left-seg-0", [("sconce-left", 0, 27)]),
    # BOTH bridges on one virtual — his real arrangement
    _virtual("hues", [("hue-lights", 0, 9), ("dining-hues", 0, 6)]),
    _virtual("hue-lights", [("hue-lights", 0, 9)]),
    _virtual("dining-hues", [("dining-hues", 0, 6)]),
    _virtual("crystal-mapper", [("crystal", 0, 975),
                                ("gap-crystal-mapper", 0, 4095)]),
    _virtual("no-segments", []),
]}


class _Room:
    def __init__(self, room_id, carriers, footprints=()):
        self.id = room_id
        self.carrier_ids = list(carriers)
        self.footprints = list(footprints)


class _Footprint:
    def __init__(self, emitter_id, carrier):
        self.emitter_id = emitter_id
        self.carrier = carrier


class _Item:
    def __init__(self, room_id, carrier_ids=None, emitter_ids=None):
        self.room_id = room_id
        self.carrier_ids = carrier_ids
        self.emitter_ids = emitter_ids


ROOMS = {
    "living": _Room("living", ["tv-mapper"],
                    [_Footprint("tv-mapper:blk0[0-29]", "tv-mapper")]),
    "hue-room": _Room("hue-room", ["dining-hues"]),
    "empty": _Room("empty", []),
    "two": _Room("two", ["tv-mapper", "dining-hues"]),
}


def _rooms(room_id):
    return ROOMS.get(room_id)


# ── 1. THE RULE ────────────────────────────────────────────────────────────

def test_a_kitchen_carrier_scopes_to_its_own_three_fixtures():
    scope = take_scope.scope_for_carriers(["tv-mapper"], CONFIG_VIRTUALS)

    assert scope.device_ids == {"tv-backlight", "sconce-left", "sconce-right"}
    assert scope.virtual_ids == {
        "tv-mapper", "tv-backlight", "sconce-left", "sconce-right",
        "sconce-left-seg-0"}


def test_no_virtual_in_scope_can_reach_an_out_of_scope_device():
    """THE INVARIANT THE WHOLE MECHANISM RESTS ON — a device is activated
    only by a virtual with segments on it, so a scope in which no in-scope
    virtual touches an out-of-scope device cannot activate one."""
    scope = take_scope.scope_for_carriers(["tv-mapper"], CONFIG_VIRTUALS)

    for vid in scope.virtual_ids:
        reachable = {seg[0] for seg in CONFIG_VIRTUALS[vid]["segments"]}
        assert reachable <= scope.device_ids, (vid, reachable)
    assert "hue-lights" in scope.excluded_device_ids
    assert "dining-hues" in scope.excluded_device_ids


def test_the_virtual_spanning_both_bridges_is_never_in_a_kitchen_scope():
    """`hues` is the exact virtual that carried a kitchen run into his
    bathroom: one virtual, both bridges, seventeen bulbs."""
    scope = take_scope.scope_for_carriers(["tv-mapper"], CONFIG_VIRTUALS)
    assert "hues" not in scope.virtual_ids


def test_a_hue_carrier_scopes_to_its_own_group_and_not_its_sibling():
    scope = take_scope.scope_for_carriers(["dining-hues"], CONFIG_VIRTUALS)

    assert scope.device_ids == {"dining-hues"}
    assert scope.virtual_ids == {"dining-hues"}
    assert "hue-lights" in scope.excluded_device_ids
    # and `hues`, which spans both, is NOT confined to this group
    assert "hues" not in scope.virtual_ids


def test_two_carriers_union_their_devices():
    scope = take_scope.scope_for_carriers(["tv-mapper", "dining-hues"],
                                          CONFIG_VIRTUALS)
    assert "dining-hues" in scope.device_ids
    assert "tv-backlight" in scope.device_ids
    # still not the other bridge, and still not the spanning virtual
    assert "hue-lights" not in scope.device_ids
    assert "hues" not in scope.virtual_ids


# ── 2. UNRESOLVABLE MEANS THE WHOLE ROOM, WITH A REASON ────────────────────

@pytest.mark.parametrize("carriers", [[], ["not-a-virtual"], ["no-segments"]])
def test_a_carrier_it_cannot_place_refuses_to_narrow(carriers):
    assert take_scope.scope_for_carriers(carriers, CONFIG_VIRTUALS) is None


def test_an_unknown_room_widens_to_the_whole_room_and_says_so(monkeypatch):
    monkeypatch.setattr(take_scope, "load_config_virtuals",
                        lambda config_dir=None: CONFIG_VIRTUALS)
    out = take_scope.resolve_for_items([_Item("nowhere")], get_room=_rooms)

    assert out.scope is None
    assert "not in the room map" in out.reason


def test_a_room_with_no_carriers_widens(monkeypatch):
    monkeypatch.setattr(take_scope, "load_config_virtuals",
                        lambda config_dir=None: CONFIG_VIRTUALS)
    out = take_scope.resolve_for_items([_Item("empty")], get_room=_rooms)

    assert out.scope is None
    assert "declares no carriers" in out.reason


def test_an_unreadable_config_widens(tmp_path, monkeypatch):
    out = take_scope.resolve_for_items([_Item("living")],
                                       config_dir=tmp_path / "missing",
                                       get_room=_rooms)
    assert out.scope is None
    assert "could not be read" in out.reason


def test_no_items_widens():
    assert take_scope.resolve_for_items([]).scope is None


def test_one_unresolvable_item_widens_the_WHOLE_take(monkeypatch):
    """A queue whose second item cannot be placed must not run that item
    against a room brought up for the first."""
    monkeypatch.setattr(take_scope, "load_config_virtuals",
                        lambda config_dir=None: CONFIG_VIRTUALS)
    out = take_scope.resolve_for_items(
        [_Item("living"), _Item("nowhere")], get_room=_rooms)
    assert out.scope is None


# ── 3. A QUEUE'S OWN DECLARATION ───────────────────────────────────────────

def test_a_declared_queue_unions_its_items(monkeypatch):
    monkeypatch.setattr(take_scope, "load_config_virtuals",
                        lambda config_dir=None: CONFIG_VIRTUALS)
    out = take_scope.resolve_for_items(
        [_Item("living"), _Item("hue-room")], get_room=_rooms)

    assert out.scope is not None
    assert out.scope.carriers == ["tv-mapper", "dining-hues"]
    assert out.scope.device_ids == {"tv-backlight", "sconce-left",
                                    "sconce-right", "dining-hues"}
    assert "hue-lights" in out.scope.excluded_device_ids
    assert "left completely alone" in out.reason


def test_an_item_naming_its_own_carriers_beats_the_room_s_list(monkeypatch):
    monkeypatch.setattr(take_scope, "load_config_virtuals",
                        lambda config_dir=None: CONFIG_VIRTUALS)
    out = take_scope.resolve_for_items(
        [_Item("two", carrier_ids=["tv-mapper"])], get_room=_rooms)

    assert out.scope.device_ids == {"tv-backlight", "sconce-left",
                                    "sconce-right"}


def test_an_emitter_scoped_item_resolves_through_its_footprint(monkeypatch):
    monkeypatch.setattr(take_scope, "load_config_virtuals",
                        lambda config_dir=None: CONFIG_VIRTUALS)
    out = take_scope.resolve_for_items(
        [_Item("living", emitter_ids=["tv-mapper:blk0[0-29]"])],
        get_room=_rooms)

    assert out.scope.carriers == ["tv-mapper"]


def test_an_emitter_the_map_has_never_seen_falls_back_to_its_id_prefix(
        monkeypatch):
    """`emitters.py`'s id shape is "<carrier>:<piece>", so a not-yet-mapped
    emitter still names its carrier — but ONLY when that carrier is one of
    this room's own, never by trusting the string."""
    monkeypatch.setattr(take_scope, "load_config_virtuals",
                        lambda config_dir=None: CONFIG_VIRTUALS)
    out = take_scope.resolve_for_items(
        [_Item("living", emitter_ids=["tv-mapper:blk9[270-299]"])],
        get_room=_rooms)
    assert out.scope.carriers == ["tv-mapper"]

    out = take_scope.resolve_for_items(
        [_Item("living", emitter_ids=["somebody-elses-carrier:blk0"])],
        get_room=_rooms)
    assert out.scope is None, out.reason


# ── 4. A SCOPE THAT BRINGS UP NOTHING IS A HARD REFUSAL ────────────────────

def test_a_scope_that_intersects_nothing_refuses_rather_than_narrowing():
    """`live_host.scoped_expected_active` is where a resolvable-but-useless
    scope stops. An activation with no virtual to bring up would sail
    through the freshness gate vacuously and hand back a dark room reported
    as a good take."""
    from spectra.services import live_host

    with pytest.raises(RuntimeError) as exc:
        live_host.scoped_expected_active({"tv-mapper"}, {"hues"})
    assert "brings up nothing" in str(exc.value)


def test_a_scope_narrows_the_expected_active_set_it_verifies_against():
    """It MUST narrow, or the activation gate refuses forever over virtuals
    the take deliberately held back."""
    from spectra.services import live_host

    assert live_host.scoped_expected_active(
        {"tv-mapper", "hues"}, {"tv-mapper", "sconce-left"}) == {"tv-mapper"}


def test_no_scope_is_the_whole_room_unchanged():
    from spectra.services import live_host

    assert live_host.scoped_expected_active({"tv-mapper", "hues"},
                                            None) == {"tv-mapper", "hues"}


# ── 5. IT READS THE STORED CONFIG ON DISK, BEFORE ANY HOST EXISTS ──────────

def test_it_reads_the_fx_live_config_from_disk(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps(
        {"virtuals": [{"id": "a", "segments": [["dev-a", 0, 9, False, 0]]}]}))

    virtuals = take_scope.load_config_virtuals(tmp_path)
    assert set(virtuals) == {"a"}
    scope = take_scope.scope_for_carriers(["a"], virtuals)
    assert scope.device_ids == {"dev-a"}


# ── 6. THE HANDOVER ROUTE'S OPT-IN SCOPE ───────────────────────────────────
#
# "Give SPECTRA the room" stays a whole-room act. What this adds is the
# OTHER kind of take — a capture run driven by hand, which has no business
# bringing up the Hue groups spanning the rest of his house — and it is
# opt-in, so the room bar's own press is byte-identical to before.

def _run(coro):
    import asyncio
    return asyncio.run(coro)


def _route_bits():
    from fx import light_ownership as lo
    from spectra.api.ownership import HandoverRequest, _requested_scope
    return lo, HandoverRequest, _requested_scope


def test_an_unscoped_handover_request_asks_for_no_scope_at_all():
    """The default press: no keyword reaches `production_sides`, so nothing
    about it can behave differently from before this field existed."""
    lo, HandoverRequest, _requested_scope = _route_bits()
    assert _requested_scope(HandoverRequest(to=lo.SPECTRA)) is None


def test_a_handover_to_spot_effects_is_never_scoped():
    lo, HandoverRequest, _requested_scope = _route_bits()
    assert _requested_scope(HandoverRequest(
        to=lo.SPOT_EFFECTS, carrier_ids=["tv-mapper"])) is None


def test_a_carrier_scoped_request_resolves_against_the_stored_config(
        monkeypatch):
    lo, HandoverRequest, _requested_scope = _route_bits()
    monkeypatch.setattr(take_scope, "load_config_virtuals",
                        lambda config_dir=None: CONFIG_VIRTUALS)

    out = _requested_scope(HandoverRequest(to=lo.SPECTRA,
                                           carrier_ids=["tv-mapper"]))
    assert out.scope.device_ids == {"tv-backlight", "sconce-left",
                                    "sconce-right"}
    assert "hues" not in out.scope.virtual_ids


def test_a_scope_the_route_cannot_place_is_a_REFUSAL_not_a_widening(
        monkeypatch):
    """The asymmetry is deliberate, and it is the whole incident: an
    UNATTENDED night widens (a wrongly-narrow take wastes a night), but
    somebody who ASKED for a narrow take and silently got the whole house is
    what this change exists to stop."""
    lo, HandoverRequest, _requested_scope = _route_bits()
    monkeypatch.setattr(take_scope, "load_config_virtuals",
                        lambda config_dir=None: CONFIG_VIRTUALS)

    out = _requested_scope(HandoverRequest(to=lo.SPECTRA,
                                           carrier_ids=["not-a-virtual"]))
    assert out is not None and out.scope is None
    assert "could not be placed" in out.reason


def test_the_route_refuses_before_the_record_moves_on_an_unplaceable_scope(
        tmp_path, monkeypatch):
    """422, nothing quiesced, nothing taken — the readiness-gate shape."""
    import json as _json

    from fx import light_ownership as lo
    from spectra.api.ownership import HandoverRequest, post_handover
    from spectra.services import handover as handover_svc

    lo.OWNERSHIP_FILE = tmp_path / "ownership.json"
    monkeypatch.setenv("SPECTRA_HANDOVER_ARMED", "1")
    monkeypatch.setattr(take_scope, "load_config_virtuals",
                        lambda config_dir=None: CONFIG_VIRTUALS)

    def _never(*a, **kw):
        raise AssertionError("the route reached the handover on a refusal")
    monkeypatch.setattr(handover_svc, "production_sides", _never)

    resp = _run(post_handover(HandoverRequest(to=lo.SPECTRA,
                                              carrier_ids=["nope"])))
    assert resp.status_code == 422
    body = _json.loads(bytes(resp.body))
    assert body["result"] == "refused-scope-unresolved"
    assert body["record"]["owner"] == lo.SPOT_EFFECTS
