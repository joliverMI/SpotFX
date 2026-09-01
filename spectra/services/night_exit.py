"""THE HONEST EXIT — at the end of a night run, read every fixture back AT
THE EMITTED LIGHT and say what is dark, what still emits, and why.

THE STANDARD, and this is its first application: A MODE OR SETTING READ IS
NOT VERIFICATION. "The setting is not the light." Reading `display_mode ==
"dark"` back, or seeing `close_hold` return `{"reverted": true}`, or
watching a `set_power_state` POST come back 2xx, proves that a decision was
recorded — not that a bulb went out. This codebase has been bitten by
exactly that gap three separate times and written each one down:

  * `ambient_music_gate.status()` reported `held: true` all night while
    every one of his 36 bulbs was physically off, because a write's own
    read-back proves the moment it was taken and nothing re-checked later
    (spectra/services/ambient_music_gate.py, "Status honesty").
  * a Hue bridge returns a clean 200 whether or not the bulb took the write
    (spectra/services/ambient.py, "Read-back confirmation").
  * a same-type effects PUT returned success, filled the executor log with
    real glide writes, and left the fixture dark (`fx/VENDOR.md` #29, "a
    returning write call is never evidence").

And it is what the morning of 2026-09-01 actually cost: the run never
ended, the closing act never ran, and he woke to lit fixtures nobody's
record described as lit.

WHAT THIS READS, per fixture, over the fixture's OWN transport:

  WLED   `json/state` (`on`, `bri`) and `json/info` (`live`, `lip`) — the
         power switch, the master brightness and whether anything is still
         streaming at it, from the firmware. `live` is only ever reported
         under json/info, never json/state (fx/utils.py::get_info).
  HUE    the bridge's own light resource, per bulb, via
         `release_fade.read_hue_light_states` — reusing that module's
         entertainment-stream -> light-resource walk rather than opening a
         third copy of the bridge client.
  ANYTHING ELSE   e131 / ddp / udp / dummy have no control channel to ask,
         so they are reported UNKNOWN and are never counted as dark. An
         unreadable fixture is not a confirmed-dark one — the same rule
         `release_fade._read_still_on` holds, and the whole point of this
         report is that it does not flatter itself.

THE ONE INSTRUMENT CAVEAT worth repeating here because it is easy to
misread: while a Hue entertainment stream is live, the CLIP light resource
does not reflect the streamed COLOUR (AGENTS.md, "Reading real Hue bulb
state"). It does honestly report on/off, which is the only thing asked. Do
not extend this to read a colour back and believe it.

"STILL EMITTING" IS NOT AUTOMATICALLY WRONG, and the report says which kind
it is. His Dark mode carries a shield (`dark_light_shield_categories`,
default "Singles") that Dark NEVER clamps — the fixtures behind it keep
showing the resumed show by inherited design, and those were precisely the
lit sets he woke to on 2026-09-01, lit outside any run's scope. A fixture
lit for that reason is named BY DESIGN with the shield named; a fixture the
run itself drove that is still lit afterwards is named as a PROBLEM. Two
different facts that look identical from a light meter, and a report that
conflated them would send the morning backstop after the wrong list.

THE HOUSE'S OWN ENVELOPE IS NOT TAKEN ON TRUST EITHER. His Home Assistant
"Dark Music" scene darkens everything except the SPECTRA fixtures, fired and
restored by the house side around the run — this module fires nothing and
assumes nothing about it. A fixture found emitting is NAMED whichever of the
three it is (the run's, shield-exempt, or the house's), by the captain's own
order: the envelope is not a substitute for checking. Reporting a room as
dark because a scene was supposed to have been fired is the same mistake as
reporting it dark because a mode field says "dark".
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

VERDICT_DARK = "dark"
VERDICT_EMITTING = "emitting"
VERDICT_UNKNOWN = "unknown"

#: Why a fixture that still emits does so.
BY_DESIGN = "by_design"          # the Dark-mode shield exempts it
BY_RUN = "run_fixture"           # the night run drove it and it did not let go
OUTSIDE_RUN = "outside_run"      # neither — the room's own resumed show


@dataclass
class FixtureExit:
    """One fixture, read back. `verdict` is the word a program branches on;
    `why` is the sentence a person reads at breakfast."""
    device_id: str
    name: str
    address: str = ""
    kind: str = ""
    verdict: str = VERDICT_UNKNOWN
    why: str = ""
    #: Set only when `verdict == "emitting"`: which of the three it is.
    attribution: str = ""
    #: True when this fixture is one the night run itself drove.
    in_run: bool = False
    #: The shielded virtual(s) that exempt this fixture from Dark mode, if
    #: any — named, so the morning backstop knows what to turn off and the
    #: reader knows why it was never going to go out on its own.
    shielded_via: list[str] = field(default_factory=list)
    #: The raw reading, for a record that has to survive an argument.
    readback: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"device_id": self.device_id, "name": self.name,
                "address": self.address, "kind": self.kind,
                "verdict": self.verdict, "why": self.why,
                "attribution": self.attribution, "in_run": self.in_run,
                "shielded_via": list(self.shielded_via),
                "readback": dict(self.readback)}


@dataclass
class ExitReport:
    fixtures: list[FixtureExit] = field(default_factory=list)
    #: Fixtures the RUN drove that are still emitting — the only category
    #: this seam owes anybody an explanation for.
    problems: list[str] = field(default_factory=list)

    @property
    def dark(self) -> list[str]:
        return [f.device_id for f in self.fixtures if f.verdict == VERDICT_DARK]

    @property
    def emitting(self) -> list[str]:
        return [f.device_id for f in self.fixtures
                if f.verdict == VERDICT_EMITTING]

    @property
    def unknown(self) -> list[str]:
        return [f.device_id for f in self.fixtures
                if f.verdict == VERDICT_UNKNOWN]

    @property
    def summary(self) -> str:
        parts = [f"{len(self.dark)} dark", f"{len(self.emitting)} still lit",
                 f"{len(self.unknown)} could not be read"]
        by_design = [f.device_id for f in self.fixtures
                     if f.attribution == BY_DESIGN]
        line = ("Read back at the fixtures: " + ", ".join(parts) + ".")
        if by_design:
            line += (f" {len(by_design)} of the lit ones are Dark-mode "
                     f"shielded and lit by design ({', '.join(by_design)}).")
        if self.problems:
            line += f" {len(self.problems)} unexplained."
        return line

    def as_dict(self) -> dict:
        return {"verified_at_the_light": True, "summary": self.summary,
                "dark": self.dark, "emitting": self.emitting,
                "unknown": self.unknown, "problems": list(self.problems),
                "fixtures": [f.as_dict() for f in self.fixtures]}


def _wled(device):
    """The driver's own WLED helper, or None when this fixture cannot be
    asked at all.

    The KIND is decided by the device listing entry (`device_console`'s own
    report, the one definition of what a fixture is), not re-derived here;
    what this checks is whether the live driver has actually resolved its
    destination — `WLEDDevice.wled` is only built at that point
    (fx/devices/wled.py), which is `fixture_brightness._wled`'s own reason
    for reading the driver rather than the config."""
    return getattr(device, "wled", None)


async def _read_wled(device) -> tuple[str, str, dict]:
    """(verdict, why, readback) for one WLED, from the firmware itself."""
    helper = _wled(device)
    if helper is None:
        return (VERDICT_UNKNOWN,
                "this fixture is a WLED whose driver has not resolved its "
                "address, so its firmware could not be asked", {})
    try:
        state = await helper.get_state()
        info = await helper.get_info()
    except Exception as exc:                            # noqa: BLE001
        logger.info("night_exit: could not read %s back: %s",
                    getattr(device, "id", "?"), exc)
        return (VERDICT_UNKNOWN,
                f"the fixture did not answer when read back "
                f"({type(exc).__name__}) — its light is unknown, and an "
                f"unread fixture is not a dark one", {})
    on = bool(state.get("on"))
    bri = int(state.get("bri") or 0)
    live = bool(info.get("live"))
    lip = str(info.get("lip") or "")
    readback = {"on": on, "bri": bri, "live": live, "lip": lip}
    if not on:
        return (VERDICT_DARK,
                "the fixture reads switched off at its own firmware", readback)
    if bri <= 0:
        return (VERDICT_DARK,
                "the fixture is on but its master brightness reads 0, so it "
                "emits nothing", readback)
    streaming = (f", still taking a realtime stream from {lip}" if live
                 else ", showing its own on-device effect (no realtime "
                      "stream)")
    return (VERDICT_EMITTING,
            f"the fixture reads on at {round(bri * 100 / 255)}% brightness"
            f"{streaming}", readback)


def _address(entry: dict) -> str:
    cfg = (entry or {}).get("config") or {}
    return str(cfg.get("ip_address") or cfg.get("destination") or "")


def _name(entry: dict) -> str:
    cfg = (entry or {}).get("config") or {}
    return str(cfg.get("name") or entry.get("name") or entry.get("id") or "")


async def build(*, device_entries: list[dict], devices_by_id: dict,
                run_device_ids: set[str],
                shielded_devices: dict[str, list[str]],
                host: Any = None,
                read_hue: Optional[Any] = None) -> ExitReport:
    """Read every fixture in `device_entries` back and judge it.

    `run_device_ids` are the fixtures the night run itself drove;
    `shielded_devices` maps a device id to the shielded virtual(s) that
    exempt it from Dark mode. `devices_by_id` are the LIVE driver objects —
    the only thing that can be asked a firmware state, exactly as
    `fixture_brightness` and `night_power` both read through.

    Never raises for a fixture that will not answer: an unreadable one is
    reported UNKNOWN, which is a third thing and never folded into dark."""
    report = ExitReport()

    hue_by_device: dict[str, list[dict]] = {}
    if host is not None:
        reader = read_hue
        if reader is None:
            from spectra.services import release_fade
            reader = release_fade.read_hue_light_states
        try:
            for row in await reader(host) or []:
                hue_by_device.setdefault(str(row.get("device_id") or ""),
                                         []).append(row)
        except Exception:                               # noqa: BLE001
            logger.exception("night_exit: could not read the Hue bridges back")

    for entry in sorted(device_entries or [], key=lambda e: str(e.get("id"))):
        did = str(entry.get("id") or "")
        if not did:
            continue
        kind = str(entry.get("type") or "").lower()
        fx = FixtureExit(device_id=did, name=_name(entry),
                         address=_address(entry), kind=kind,
                         in_run=did in run_device_ids,
                         shielded_via=list(shielded_devices.get(did) or []))
        if kind == "wled":
            fx.verdict, fx.why, fx.readback = await _read_wled(
                devices_by_id.get(did))
        elif kind == "hue":
            rows = hue_by_device.get(did) or []
            if not rows:
                fx.verdict = VERDICT_UNKNOWN
                fx.why = ("no bulb on this bridge could be read back, so its "
                          "light is unknown — an unread fixture is not a dark "
                          "one")
            else:
                lit = [r["name"] for r in rows if r.get("on") is True]
                unread = [r["name"] for r in rows if r.get("on") is None]
                fx.readback = {"lights": rows, "lit": lit, "unread": unread}
                if lit:
                    fx.verdict = VERDICT_EMITTING
                    fx.why = (f"{len(lit)} of {len(rows)} bulbs on this "
                              f"bridge read on: {', '.join(lit)}")
                elif unread:
                    fx.verdict = VERDICT_UNKNOWN
                    fx.why = (f"{len(unread)} of {len(rows)} bulbs could not "
                              f"be read back ({', '.join(unread)}), so this "
                              f"fixture is not confirmed dark")
                else:
                    fx.verdict = VERDICT_DARK
                    fx.why = (f"all {len(rows)} bulbs on this bridge read "
                              f"off at the bridge itself")
        else:
            fx.verdict = VERDICT_UNKNOWN
            fx.why = (f"a {kind or 'unknown'} fixture has no control channel "
                      f"to ask, so whether it is emitting cannot be read "
                      f"back — it is reported unknown rather than assumed "
                      f"dark")

        if fx.verdict == VERDICT_EMITTING:
            if fx.shielded_via:
                fx.attribution = BY_DESIGN
                fx.why += (f" — BY DESIGN: Dark mode never clamps this "
                           f"fixture ({', '.join(fx.shielded_via)} is "
                           f"shielded), so it keeps showing the resumed "
                           f"show. Turning it off is Home Assistant's to do; "
                           f"it is on the standing_lit_under_dark list for "
                           f"exactly this reason.")
            elif fx.in_run:
                fx.attribution = BY_RUN
                fx.why += (" — UNEXPLAINED: this is a fixture the night run "
                           "drove, and it should have been handed back with "
                           "the room. Something did not let go.")
                report.problems.append(f"{fx.name or did}: {fx.why}")
            else:
                fx.attribution = OUTSIDE_RUN
                fx.why += (" — this fixture was not part of the run and is "
                           "not Dark-mode shielded; it is showing the room's "
                           "own resumed show. Named rather than passed over: "
                           "the house's own darkening scene is Home "
                           "Assistant's act, and a report that assumed it "
                           "landed would be believing a setting instead of "
                           "reading a light.")
        report.fixtures.append(fx)
    return report
