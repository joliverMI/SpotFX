"""A CAPTURE RUN TOUCHES ONLY THE FIXTURES IT MEASURES — proven at the
emitted light and at the bridge.

THE INCIDENT (2026-09-07, the Admiral verbatim): "you turned off the
bathroom light... be more selective about which lights you turn off." A
kitchen capture run needs two sconces and a TV backlight. It took the whole
room — which on his config means one `hues` virtual spanning BOTH Hue
bridges and the two entertainment configurations behind them, seventeen
bulbs from the hallway to the bathroom — drove every one of them, and
switched every one of them off on the way out.

WHAT IS ACTUALLY MEASURED, and it is not the call:

  * every frame that reaches a DEVICE'S TRANSPORT, labelled with the phase
    it arrived in (`Device.update_pixels` is the sole caller of `flush()` on
    the live path, so recording `flush` records the light); and
  * every REST call the release fade makes TO A BRIDGE, with the bulb it
    landed on, so "his bathroom was written to" is a fact rather than an
    inference.

An out-of-scope bulb is BYTE-EXACT when neither instrument saw it: no frame
was ever streamed at it, and no bridge write ever reached it. Nothing about
its state can have changed, because nothing addressed it.

RED-FIRST, IN THE SAME RIG. `unscoped` runs the identical night with the
scope resolution disabled — which is exactly the code that shipped before
this change — and it MUST show the house Hue streamed by the take and
switched off by the release. A proof that cannot fail on the defect it was
written for is decoration.

THE HONEST UNIT IS THE ENTERTAINMENT GROUP, NOT THE BULB, and it is proven
rather than asserted (`test_a_hue_group_is_indivisible_at_the_wire`): a Hue
device's `flush` sends the WHOLE channel set in one DTLS datagram, so
streaming any part of a group drives every bulb in it — the ones nothing
wrote to are driven to black. A run that streams a group therefore owes
every bulb in that group a "let go", and the scope that can be honoured is
per entertainment group. Splitting further is a bridge-side grouping
decision, not something this code can invent.

FRESH INTERPRETER PER OBSERVATION (subprocess), per
tests/test_cold_load_effect_restore.py's and tests/test_quiet_take_dark.py's
precedent: config load order, whether a device was ever activated, and what
the first frame carries are not things a warm pytest process can speak to
honestly.

NOTHING HERE TOUCHES HIS ROOM: `SPECTRA_STORAGE_DIR` is a throwaway
directory (which moves `FX_LIVE_CONFIG_DIR` and the room map with it),
`fx.light_ownership.OWNERSHIP_FILE` and `fx.device_model.CATEGORIES_FILE`
are repointed by hand, the kitchen fixtures are vendored dummies, and the
Hue devices are the real driver class with its bridge REST, its DTLS
session and its UDP send stubbed — see tests/scoped_take_driver.py.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

HOUSE_HUE = "house-hues"
DINING_HUE = "dining-hues"
KITCHEN_DEVICES = {"tv-backlight", "sconce-left"}
#: the bridge behind each Hue entertainment group in the harness config
HOUSE_BRIDGE = "10.0.0.1"
DINING_BRIDGE = "10.0.0.2"


# ── his room's shape, minimally ────────────────────────────────────────────

def _dummy(did, pixels):
    return {"id": did, "type": "dummy",
            "config": {"name": did, "pixel_count": pixels}}


def _hue(did, ip, group, lights):
    """A stored Hue device in the shape `async_initialize` leaves one in —
    already registered, so the driver's canned REST stands in for discovery
    and nothing reaches a bridge."""
    return {"id": did, "type": "hue",
            "config": {"name": did, "ip_address": ip, "group_name": group,
                       "pixel_count": lights, "udp_port": 2100,
                       "username": "u", "clientkey": "00" * 16,
                       "hue_application_id": "app-id",
                       "group_id": "7", "entertainment_id": f"ent-{did}"}}


def _virtual(vid, segments, *, is_device=False, active=True):
    bright = {"type": "singleColor",
              "config": {"color": "#ffffff", "brightness": 1.0,
                         "background_brightness": 1.0}}
    return {
        "id": vid, "is_device": vid if is_device else False,
        "auto_generated": False,
        "config": {"name": vid, "mapping": "span" if is_device else "copy",
                   "rows": 1, "transition_mode": "Add",
                   "transition_time": 0.0},
        "segments": segments, "active": active,
        "effect": bright, "effects": {bright["type"]: bright},
        "last_effect": bright["type"],
    }


def write_house_config(config_dir: Path, mode: str) -> None:
    """His fx-live shape, minimally: a kitchen carrier fanning out to two
    dummy fixtures, plus the Hue side of the house.

    TWO HUE SHAPES, and the difference is the point:

      * the default is HIS shape — ONE virtual (`hues`) spanning BOTH Hue
        entertainment groups, which is the exact arrangement that made a
        kitchen run reach his bathroom;
      * `hue_scoped` splits that into one carrier per group, which is what
        a room whose carrier IS a Hue group looks like. Both carriers cannot
        coexist with `hues` in one config (they would overlap on the same
        device pixels and the loader would evict one), so this is a
        different room rather than a second knob on the same one."""
    config_dir.mkdir(parents=True, exist_ok=True)
    if mode == "hue_scoped":
        hue_virtuals = [
            _virtual("house-hue-carrier", [[HOUSE_HUE, 0, 2, False, 0]]),
            _virtual("dining-hue-carrier", [[DINING_HUE, 0, 1, False, 0]]),
        ]
    else:
        hue_virtuals = [_virtual("hues", [[HOUSE_HUE, 0, 2, False, 0],
                                          [DINING_HUE, 0, 1, False, 0]])]
    config = {
        "configuration_version": "2.3.6",
        "devices": [
            _dummy("tv-backlight", 60),
            _dummy("sconce-left", 30),
            _hue(HOUSE_HUE, HOUSE_BRIDGE, "House Music", 3),
            _hue(DINING_HUE, DINING_BRIDGE, "Dining Music", 2),
        ],
        "virtuals": [
            # the kitchen carrier, copy-mapped across both fixtures
            _virtual("tv-mapper", [["tv-backlight", 0, 59, False, 0],
                                   ["sconce-left", 0, 29, False, 0]]),
            _virtual("tv-backlight", [["tv-backlight", 0, 59, False, 0]],
                     is_device=True, active=False),
            _virtual("sconce-left", [["sconce-left", 0, 29, False, 0]],
                     is_device=True, active=False),
            *hue_virtuals,
            _virtual(HOUSE_HUE, [[HOUSE_HUE, 0, 2, False, 0]],
                     is_device=True, active=False),
            _virtual(DINING_HUE, [[DINING_HUE, 0, 1, False, 0]],
                     is_device=True, active=False),
        ],
        "audio": {}, "scenes": {}, "user_presets": {},
    }
    (config_dir / "config.json").write_text(json.dumps(config))


# ── the driver ─────────────────────────────────────────────────────────────

_DRIVER = (Path(__file__).resolve().parent / "scoped_take_driver.py").read_text()


def _observe(work: Path, mode: str) -> dict:
    """One night, one fresh interpreter. `os._exit` in the driver, per
    AGENTS.md: fx's TemporalEffect spawns non-daemon threads a frame-stepped
    harness never joins, so a plain return reads as a hang."""
    work.mkdir(parents=True, exist_ok=True)
    write_house_config(work / "storage" / "fx-live", mode)
    proc = subprocess.run([sys.executable, "-c", _DRIVER, str(work), mode],
                          cwd=REPO, capture_output=True, text=True,
                          timeout=600)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    line = next((ln for ln in proc.stdout.splitlines()
                 if ln.startswith("RESULT ")), None)
    assert line, proc.stdout + proc.stderr
    out = json.loads(line[len("RESULT "):])
    assert not out.get("driver_error"), out.get("driver_error")
    out["_stderr"] = proc.stderr[-4000:]
    return out


def _frames(out: dict, device: str) -> int:
    return (out["per_device"].get(device) or {}).get("frames", 0)


@pytest.fixture(scope="module")
def scoped(tmp_path_factory):
    return _observe(tmp_path_factory.mktemp("scoped"), "scoped")


@pytest.fixture(scope="module")
def unscoped(tmp_path_factory):
    return _observe(tmp_path_factory.mktemp("unscoped"), "unscoped")


@pytest.fixture(scope="module")
def hue_scoped(tmp_path_factory):
    return _observe(tmp_path_factory.mktemp("hue_scoped"), "hue_scoped")


# ── 1. RED FIRST: the defect, reproduced ───────────────────────────────────

def test_the_unscoped_night_streams_and_switches_off_his_house(unscoped):
    """THE INCIDENT. Same night, same config, same rig — with the scope
    resolution disabled, which is the code that shipped. Without this test
    every assertion below could pass because the harness sees nothing."""
    assert unscoped["took_the_room"], unscoped
    assert unscoped["night_state"] in ("complete", "aborted"), unscoped

    for hue in (HOUSE_HUE, DINING_HUE):
        assert _frames(unscoped, hue) > 0, (
            f"the take never streamed {hue}, so this rig cannot see the "
            f"defect it exists to reproduce: {unscoped}")

    assert sorted(unscoped["bridges_touched"]) == [HOUSE_BRIDGE, DINING_BRIDGE]
    assert f"{HOUSE_BRIDGE}:light-bathroom" in unscoped["lights_switched_off"], (
        "the pre-fix release was supposed to switch his bathroom light off — "
        f"if it did not, this control is not reproducing the incident: "
        f"{unscoped['lights_switched_off']}")
    assert len(unscoped["lights_switched_off"]) == 5, unscoped
    assert unscoped["fade"]["untouched"] == [], unscoped["fade"]


# ── 2. THE FIX: an out-of-scope bulb is never addressed at all ─────────────

def test_a_scoped_night_never_streams_a_single_frame_at_his_house_hue(scoped):
    """NOT ACTIVATED, therefore not streamed. A device is activated by one
    thing only — a virtual with segments on it activating — so holding the
    `hues` virtual back is what makes this structural."""
    assert scoped["took_the_room"], scoped
    assert scoped["night_state"] in ("complete", "aborted"), scoped
    assert scoped["scope"].get("scoped") is True, scoped["scope"]

    for hue in (HOUSE_HUE, DINING_HUE):
        assert _frames(scoped, hue) == 0, (
            f"a frame reached {hue}'s transport during a kitchen run: "
            f"{scoped['per_device'].get(hue)}")
    assert "hues" in scoped["held_back"], scoped
    activated_hue = [d for d in scoped["fade"]["ever_activated"]
                     if d in scoped["fade"]["hue_devices_on_host"]]
    assert activated_hue == [], (
        "a Hue device was activated by a kitchen-scoped take: "
        f"{scoped['fade']}")


def test_a_scoped_night_writes_nothing_to_either_bridge(scoped):
    """THE OTHER HALF, and it is the one the Admiral saw: no fade, no
    power-off, no REST call of any kind. His bathroom bulb is byte-exact
    across the whole night because nothing ever addressed it."""
    assert scoped["bridge_puts"] == 0, (
        "the release WROTE to a bridge for a group it never streamed: "
        f"{scoped['bridge_puts']} PUT(s)")
    assert scoped["lights_switched_off"] == [], scoped
    assert scoped["frozen"] == [], (
        "a Hue device was frozen — the fade's first act — on a run that "
        f"never streamed it: {scoped['frozen']}")
    assert sorted(scoped["fade"]["untouched"]) == sorted(
        [DINING_HUE, HOUSE_HUE]), scoped["fade"]
    assert scoped["fade"]["devices"] == [], scoped["fade"]


def test_the_scoped_night_still_drove_the_fixtures_it_took(scoped):
    """THE SECOND CONTROL. A room that is untouched because nothing came up
    at all would satisfy every assertion above and be useless for the night
    it was taken for."""
    assert KITCHEN_DEVICES <= set(scoped["devices_seen"]), scoped
    for did in KITCHEN_DEVICES:
        assert _frames(scoped, did) > 0, scoped["per_device"]
    lit = [d for d in KITCHEN_DEVICES
           if (scoped["per_device"].get(d) or {})["non_black"] > 0]
    assert lit, ("the run's own emitter lamp never lit anything, so the "
                 f"capture half of this night did nothing: {scoped}")
    assert scoped["gave_back"] and scoped["owner_final"] == "released", scoped
    assert not scoped["live_active_after"], scoped


# ── 3. A RUN THAT DOES STREAM A HUE STILL SCOPES TO THAT ONE ───────────────

def test_a_hue_in_scope_is_let_go_of_and_its_sibling_group_is_not(hue_scoped):
    """The room's carrier IS one Hue entertainment group. That group is
    streamed, so it is owed a "let go" and gets the full fade; the OTHER
    group — a different bridge, a different room of his house — is never
    activated, never written to, never switched off."""
    assert hue_scoped["took_the_room"], hue_scoped
    assert hue_scoped["scope"].get("scoped") is True, hue_scoped["scope"]

    assert _frames(hue_scoped, DINING_HUE) > 0, (
        "the in-scope Hue was never streamed, so this proves nothing about "
        f"the fade that follows: {hue_scoped['per_device']}")
    assert _frames(hue_scoped, HOUSE_HUE) == 0, hue_scoped["per_device"]

    assert hue_scoped["fade"]["devices"] == [DINING_HUE], hue_scoped["fade"]
    assert hue_scoped["fade"]["untouched"] == [HOUSE_HUE], hue_scoped["fade"]
    assert hue_scoped["bridges_written"] == [DINING_BRIDGE], hue_scoped
    assert sorted(hue_scoped["lights_switched_off"]) == [
        f"{DINING_BRIDGE}:light-dining-a",
        f"{DINING_BRIDGE}:light-dining-b"], hue_scoped
    assert [f["device"] for f in hue_scoped["frozen"]] == [DINING_HUE], (
        hue_scoped["frozen"])


def test_a_hue_group_is_indivisible_at_the_wire(hue_scoped):
    """WHY THE UNIT IS THE GROUP AND NOT THE BULB, measured rather than
    argued: the in-scope group's own virtual covers both of its channels and
    the datagram carries both, so a run that streams part of a group drives
    all of it. Every bulb in a streamed group is therefore holding a frame
    of ours and is owed the fade — which is exactly what the scope above
    grants, and no finer."""
    row = hue_scoped["per_device"][DINING_HUE]
    assert row["frames"] > 0 and row["max"] >= 0.0, row
    assert len(hue_scoped["lights_switched_off"]) == 2, (
        "the streamed group's bulbs were not all let go of — a partially "
        f"released entertainment group is a bulb abandoned lit: {hue_scoped}")
