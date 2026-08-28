"""The device edit/create domain: the parameter set read off the real
validator, the two write branches, the groupings, and the timing field.

His ask: "We need a device edit page to edit and create devices. It should
include all the parameters that were tunable in ledfx on one tab, as well
as the groupings and namings."

What is proven here rather than asserted in prose:
  * the page's parameter list IS the driver's own schema — every key the
    vendored validator accepts is offered, and a key it would reject is
    refused BY that validator, not by a second copy of the rules;
  * a write with the room DOWN is stored and SAYS it was stored (never
    silently lost, never claimed live), and the next read shows it;
  * a write with the room UP goes through the live host;
  * groupings are edited in place and never invent a category;
  * the timing field carries his sign convention all the way to the
    per-device delay map the flush layer reads.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from fx import device_model, device_schema, device_timing
from spectra.services import device_console, device_settings


@pytest.fixture(autouse=True)
def _isolated_fx_live(tmp_path, monkeypatch):
    from spectra import config as scfg
    monkeypatch.setattr(scfg, "SPECTRA_STORAGE", tmp_path)
    monkeypatch.setattr(scfg, "FX_LIVE_CONFIG_DIR", tmp_path / "fx-live")
    monkeypatch.setattr(device_model, "CATEGORIES_FILE",
                        tmp_path / "device_categories.json")
    device_model.CATEGORIES_FILE.write_text(json.dumps({
        "cat-strips": {"id": "cat-strips", "name": "Strips", "parent_id": None,
                       "virtuals": [], "effects": [], "sort_order": 0, "role": None},
        "cat-matrix": {"id": "cat-matrix", "name": "Matrix", "parent_id": None,
                       "virtuals": [], "effects": [], "sort_order": 1, "role": None},
    }))
    device_model.refresh()
    yield
    device_model.refresh()


def _run(coro):
    return asyncio.run(coro)


# ── the parameter set is the real validator ─────────────────────────────────

def test_the_six_vendored_types_are_offered_and_nothing_else():
    """LedFX ships thirteen more device types whose drivers are not
    vendored here; a config naming one is skipped by the registry at host
    start, so offering it on a create form would offer a device that can
    never come up."""
    assert device_schema.device_types() == ["ddp", "dummy", "e131", "hue",
                                            "udp", "wled"]


def test_every_offered_field_comes_from_the_drivers_own_schema():
    from fx.devices import Device
    for device_type in device_schema.device_types():
        offered = {f["name"] for f in device_schema.fields_for(device_type)}
        real = {str(k) for k in Device.registry()[device_type].schema().schema}
        assert offered == real, device_type


def test_serial_only_keys_are_deliberately_absent():
    """com_port/baudrate belong to the fork's serial device types, none of
    which are vendored — the page never offers them."""
    names = set(device_schema.distinct_parameter_names())
    assert not names & {"com_port", "baudrate"}


def test_fields_are_grouped_base_then_type_for_the_one_tab():
    """His hard constraint is ONE TAB. The grouping inside it is derived
    from the class hierarchy (Device/NetworkedDevice vs. the driver's own
    schema), not a second hand-kept list."""
    fields = device_schema.fields_for("wled")
    groups = [f["group"] for f in fields]
    assert groups == sorted(groups, key=lambda g: g != "base")
    base = {f["name"] for f in fields if f["group"] == "base"}
    assert base == {"name", "icon_name", "center_offset", "refresh_rate",
                    "ip_address"}
    assert {f["name"] for f in fields if f["group"] == "type"} == {
        "sync_mode", "timeout", "create_segments"}


def test_a_fields_bounds_and_choices_are_read_not_retyped():
    by_name = {f["name"]: f for f in device_schema.fields_for("wled")}
    assert by_name["sync_mode"]["kind"] == "enum"
    assert by_name["sync_mode"]["choices"] == ["DDP", "UDP", "E131"]
    assert by_name["timeout"]["min"] == 0 and by_name["timeout"]["max"] == 255
    assert by_name["create_segments"]["kind"] == "boolean"
    assert by_name["name"]["required"] is True
    assert by_name["timeout"]["description"]     # the driver's own words


# ── creating and editing with the room down ─────────────────────────────────

def test_create_with_the_room_down_is_stored_and_says_so():
    result = _run(device_console.create_device(
        "ddp", {"name": "Back Wall", "ip_address": "10.0.0.9",
                "pixel_count": 30}))
    assert result["status"] == "applied"
    assert result["applied"] == "stored"
    assert "not running" in result["summary"]

    listing = _run(device_console.list_devices())
    assert listing["source"] == "stored"
    device = next(d for d in listing["devices"] if d["id"] == result["device_id"])
    assert device["type"] == "ddp"
    assert device["config"]["pixel_count"] == 30
    assert device["virtuals"] == [result["device_id"]]


def test_a_created_device_gets_a_virtual_that_renders_onto_it():
    result = _run(device_console.create_device(
        "dummy", {"name": "Bench", "pixel_count": 12}))
    raw = json.loads((device_console._config_path()).read_text())
    virtual = next(v for v in raw["virtuals"] if v["id"] == result["device_id"])
    assert virtual["is_device"] == result["device_id"]
    assert virtual["segments"] == [[result["device_id"], 0, 11, False]]


def test_create_is_refused_by_the_drivers_own_schema_not_a_second_copy():
    with pytest.raises(device_console.DeviceOpError) as exc:
        _run(device_console.create_device("ddp", {"name": "No IP",
                                                  "pixel_count": 4}))
    assert "ip_address" in str(exc.value.reason)


def test_create_refuses_an_unvendored_type_and_names_the_legal_set():
    with pytest.raises(device_console.DeviceOpError) as exc:
        _run(device_console.create_device("openrgb", {"name": "x"}))
    assert exc.value.extra["known_types"] == device_schema.device_types()


def test_create_refuses_a_duplicate_name_rather_than_overwriting():
    _run(device_console.create_device("dummy", {"name": "Bench",
                                                "pixel_count": 4}))
    with pytest.raises(device_console.DeviceOpError, match="already exists"):
        _run(device_console.create_device("dummy", {"name": "Bench",
                                                    "pixel_count": 8}))


def test_update_is_a_partial_patch_that_leaves_everything_else_alone():
    created = _run(device_console.create_device(
        "ddp", {"name": "Back Wall", "ip_address": "10.0.0.9",
                "pixel_count": 30, "destination_id": 7}))
    did = created["device_id"]
    result = _run(device_console.update_device(did, {"pixel_count": 45}))
    assert result["applied"] == "stored"
    assert result["config"]["pixel_count"] == 45
    assert result["config"]["destination_id"] == 7
    assert result["config"]["ip_address"] == "10.0.0.9"


def test_rename_changes_the_name_and_nothing_else():
    created = _run(device_console.create_device("dummy", {"name": "Bench",
                                                          "pixel_count": 4}))
    did = created["device_id"]
    _run(device_console.rename_device(did, "Workbench"))
    listing = _run(device_console.list_devices())
    device = next(d for d in listing["devices"] if d["id"] == did)
    assert device["name"] == "Workbench"
    assert device["id"] == did                 # the id never moves
    assert device["config"]["pixel_count"] == 4


def test_update_refuses_an_out_of_range_value_through_the_real_validator():
    created = _run(device_console.create_device(
        "e131", {"name": "DMX", "ip_address": "10.0.0.5", "pixel_count": 10}))
    with pytest.raises(device_console.DeviceOpError, match="rejected"):
        _run(device_console.update_device(created["device_id"],
                                          {"packet_priority": 900}))


def test_update_of_an_unknown_device_is_a_stated_refusal():
    with pytest.raises(device_console.DeviceOpError, match="no device"):
        _run(device_console.update_device("nope", {"name": "x"}))


# ── the live branch ─────────────────────────────────────────────────────────

def test_a_write_with_the_room_up_goes_through_the_live_host(monkeypatch):
    """The other branch: when SPECTRA owns and the stack is up, the edit is
    routed to fx.facade — the same in-process transport fx_seam uses — so
    it reaches the running device and the persisted config in one call."""
    calls = []

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"status": "success",
                    "device": {"id": "live-1", "type": "wled",
                               "config": {"name": "Live"}, "virtuals": []}}

    async def fake_handle(method, path, *, json=None, **_kw):
        calls.append((method, path, json))
        return _Resp()

    import fx.facade as facade
    monkeypatch.setattr(device_console, "_live_host", lambda: object())
    monkeypatch.setattr(facade, "handle", fake_handle)

    result = _run(device_console.update_device("live-1", {"pixel_count": 64}))
    assert result["applied"] == "live"
    assert calls == [("PUT", "/api/devices/live-1", {"config": {"pixel_count": 64}})]
    assert "running room" in result["summary"]


def test_a_live_refusal_is_carried_forward_verbatim(monkeypatch):
    class _Resp:
        status_code = 400

        @staticmethod
        def json():
            return {"status": "failed",
                    "payload": {"type": "error",
                                "reason": "device config rejected: nope"}}

    async def fake_handle(*_a, **_kw):
        return _Resp()

    import fx.facade as facade
    monkeypatch.setattr(device_console, "_live_host", lambda: object())
    monkeypatch.setattr(facade, "handle", fake_handle)
    with pytest.raises(device_console.DeviceOpError, match="nope"):
        _run(device_console.update_device("live-1", {"pixel_count": 64}))


# ── groupings ───────────────────────────────────────────────────────────────

def test_groupings_are_set_wholesale_for_one_virtual():
    assert device_console.categories_for_virtual("v1") == []
    result = device_console.set_virtual_categories("v1", ["Strips", "Matrix"])
    assert result["status"] == "applied"
    assert device_console.categories_for_virtual("v1") == ["Matrix", "Strips"]
    device_console.set_virtual_categories("v1", ["Matrix"])
    assert device_console.categories_for_virtual("v1") == ["Matrix"]
    device_console.set_virtual_categories("v1", [])
    assert device_console.categories_for_virtual("v1") == []


def test_groupings_never_invent_a_category_from_a_typo():
    with pytest.raises(device_console.DeviceOpError, match="unknown categor"):
        device_console.set_virtual_categories("v1", ["Strps"])
    assert device_console.category_names() == ["Matrix", "Strips"]


def test_grouping_one_virtual_leaves_the_others_alone():
    device_console.set_virtual_categories("v1", ["Strips"])
    device_console.set_virtual_categories("v2", ["Strips"])
    device_console.set_virtual_categories("v1", [])
    assert device_console.categories_for_virtual("v2") == ["Strips"]


def test_a_devices_listing_carries_its_virtuals_groupings():
    created = _run(device_console.create_device("dummy", {"name": "Bench",
                                                          "pixel_count": 4}))
    device_console.set_virtual_categories(created["device_id"], ["Matrix"])
    listing = _run(device_console.list_devices())
    device = next(d for d in listing["devices"] if d["id"] == created["device_id"])
    assert device["categories"] == {created["device_id"]: ["Matrix"]}


# ── the timing field ────────────────────────────────────────────────────────

def test_the_timing_field_carries_his_sign_convention_into_the_delay_map():
    _run(device_console.create_device("dummy", {"name": "A", "pixel_count": 4}))
    _run(device_console.create_device("dummy", {"name": "B", "pixel_count": 4}))
    result = device_console.set_timing_offset_ms("a", -150)
    assert result["status"] == "applied"
    assert "earlier than the rest of the room" in result["summary"]
    # a fixture can only be made to wait: A keeps its timing, B is delayed
    assert device_timing.delay_s("a") == 0.0
    assert device_timing.delay_s("b") == pytest.approx(0.15)
    assert device_settings.get("a").timing_offset_ms == -150


def test_a_positive_offset_reads_as_later_in_his_own_words():
    _run(device_console.create_device("dummy", {"name": "A", "pixel_count": 4}))
    result = device_console.set_timing_offset_ms("a", 90)
    assert "later than the rest of the room" in result["summary"]


def test_an_out_of_range_timing_offset_is_a_stated_refusal():
    with pytest.raises(device_console.DeviceOpError, match="between"):
        device_console.set_timing_offset_ms("a", 5000)
    with pytest.raises(device_console.DeviceOpError, match="whole number"):
        device_console.set_timing_offset_ms("a", "soon")


def test_the_timing_field_appears_on_every_listed_device():
    created = _run(device_console.create_device("dummy", {"name": "A",
                                                          "pixel_count": 4}))
    listing = _run(device_console.list_devices())
    device = next(d for d in listing["devices"] if d["id"] == created["device_id"])
    assert device["timing_offset_ms"] == 0
    assert listing["timing"]["offset_limit_ms"] == 1000
    assert "negative" in listing["timing"]["convention"].lower()


# ── Sonic parity ────────────────────────────────────────────────────────────

def test_every_field_the_page_can_set_has_a_sonic_operation():
    """His standing preference. The page can create, patch config, rename,
    set the timing offset and set groupings — each of those is a declared
    operation, so anything he can do by tapping he can also say."""
    assert set(device_console.OPERATIONS) == {
        "list_devices", "get_device_params", "create_device", "update_device",
        "rename_device", "set_device_timing_offset", "set_device_categories"}


def test_the_timing_operation_states_the_sign_convention_in_his_words():
    op = device_console.OPERATIONS["set_device_timing_offset"]
    assert "NEGATIVE MEANS IT FIRES EARLIER" in op.summary
    assert "negative is that it fires earlier" in op.instructions
    schema = op.input_schema["properties"]["timing_offset_ms"]
    assert schema["minimum"] == -1000 and schema["maximum"] == 1000


def test_the_device_operations_reach_sonics_one_dispatcher():
    from spectra.services import settings_agent as sa
    for name in device_console.OPERATIONS:
        assert name in sa.ALL_OPERATIONS
        assert name in {t["name"] for t in sa.TOOLS}


def test_a_device_operation_rejection_never_raises_into_the_dispatcher():
    from spectra.services import settings_agent as sa
    result = _run(sa._dispatch("set_device_timing_offset",
                               {"device_id": "a", "timing_offset_ms": 99999}))
    assert result["status"] == "rejected"
    result = _run(sa._dispatch("create_device", {"type": "openrgb",
                                                 "config": {"name": "x"}}))
    assert result["status"] == "rejected"


def test_deleting_a_device_is_not_reachable_by_any_route():
    """Deliberately not built: he asked to edit and create devices, and
    removing one tears down its virtuals and rewrites his scenes."""
    from spectra.services import settings_agent as sa
    assert "delete_device" not in sa.ALL_OPERATIONS
    assert not hasattr(device_console, "delete_device")
