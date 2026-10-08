"""THE LIGHT SHOW's ACTION CATALOGUE AND EXECUTOR (plan: /home/javi/
fleet-spotfx/data/light-show-plan/report.md §3 and §5).

THE REGISTRY IS THE EXTENSION POINT. Every action kind is ONE declaration in
`ACTION_KINDS` (added through `register()`): its name, its parameters with
bounds, choices and defaults, how it applies, and how it is put back. The
same declaration validates an API body, drives the Build view's form
(`catalogue()` serves it), and — in phase 3 — becomes Sonic's catalogue, the
shape `sonic_ops.SonicOperation` already uses. A new kind is a new
`register()` call and nothing else.

HOW EACH FAMILY LANDS, and how it is put back:

  room settings   (ambient, display mode, forced scene/colour, drift
                  gradient, scene-change tier) — a partial patch through
                  `room_controls.apply_patch`, THE SAME writer the room bar's
                  PUT uses, so every reconciler runs exactly as a human save
                  would. Consecutive room-setting steps in a set are
                  COALESCED into one patch, so a set behaves like one save.
                  Put back from a BASELINE (below).
  house lighting  (turn on house mode, turn house lighting off/on) — through
                  `house.set_mode` (the SAME function the House page's
                  "Switch to" button calls) and `house.set_enabled` (the
                  same EFFECT as the top-bar Mode chip's long press);
                  never `room_controls.apply_patch` — house lighting has
                  its own store. Put back from a BASELINE (below), same
                  as room settings.
  item on/off     (scene, colour set/group) — the same `disabled` flag his
                  power buttons write: a raw single-key patch of
                  scenes.json, and the colour card through SpotFX's own
                  /api/color-sets (SPECTRA never writes color_sets.json
                  itself). Put back from a baseline.
  momentary       (fire a scene now, apply a colour set now) — explicit
                  presses, exactly like his Fire / Apply buttons. Nothing to
                  put back: the room moves on from them as it always does.
  device output   (device state, level, flash) — spectra/services/
                  show_output.py over fx/device_output.py. Put back
                  STRUCTURALLY: the show renders underneath, so letting go
                  fades into the live picture.
  room effects    (run / stop a room effect) — through room_effects.start()
                  and its own held-room program, the ONE entry point every
                  room effect already has; the show only keeps the hold
                  heartbeated for the action's duration. A future room
                  effect kind registers in light_field_fields.KINDS and is
                  armable here with no Light Show change.
  control         (pause) — waits inside a set.

BASELINES. The first time the show changes a setting its value is saved.
End show writes each one back ONLY while the current value still equals
what the show last wrote; anything he changed by hand since is left alone
and NAMED. Changing a setting twice keeps the FIRST original.

THE GATE. Every step except a pause asks `show_output.refusal()` first: the
show acts only while SPECTRA owns the lights and is live, and stands down
while a preview, camera run or night run has the room. It never takes or
releases the room and has no action that could.

A SET NEVER HALF-FAILS SILENTLY: firing returns one outcome per step
(applied / skipped / refused / failed, each with a sentence) and the run
record lists them. A set with a pause returns at its first pause with the
run still going; `status()` shows the rest as it lands.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from spectra.models.light_show import (ActionSet, SettingBaseline, ShowAction,
                                       now_ms)
from spectra.services import show_output, show_store

logger = logging.getLogger(__name__)

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
MAX_PAUSE_S = 600.0
MAX_RUNS_KEPT = 20
#: How often a running show room effect re-arms its held room.
ROOM_EFFECT_HEARTBEAT_S = 5.0


# ── declarations ───────────────────────────────────────────────────────────

@dataclass
class Param:
    """One parameter. `type` is what the Build view renders:
    bool | enum | number | color | text | scene | scenes | color_set |
    color_sets | gradient | target | hue_areas | room_effect | house_mode |
    overrides."""
    name: str
    type: str
    label: str = ""
    default: Any = None
    required: bool = False
    choices: Optional[list] = None
    min: Optional[float] = None
    max: Optional[float] = None
    unit: str = ""
    help: str = ""

    def as_dict(self) -> dict:
        return {"name": self.name, "type": self.type,
                "label": self.label or self.name.replace("_", " "),
                "default": self.default, "required": self.required,
                "choices": self.choices, "min": self.min, "max": self.max,
                "unit": self.unit, "help": self.help}


class ActionError(ValueError):
    """A step's parameters do not describe something that can run."""


@dataclass
class Outcome:
    status: str                 # applied | skipped | refused | failed
    detail: str = ""
    data: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"status": self.status, "detail": self.detail, **self.data}


@dataclass
class ActionKind:
    name: str
    label: str
    group: str                          # setting | device | effect | control
    params: list[Param]
    help: str
    restore: str                        # one sentence: how it is put back
    #: room-setting kinds: params -> partial RoomControlState patch
    room_patch: Optional[Callable[[dict], dict]] = None
    #: everything else
    apply: Optional[Callable[[dict, "RunContext"], Awaitable[Outcome]]] = None
    #: extra normalisation/validation after the generic pass
    check: Optional[Callable[[dict], dict]] = None
    needs_room: bool = True
    help_topic: str = "show-actions"

    def as_dict(self) -> dict:
        return {"kind": self.name, "label": self.label, "group": self.group,
                "params": [p.as_dict() for p in self.params], "help": self.help,
                "restore": self.restore, "help_topic": self.help_topic}


ACTION_KINDS: dict[str, ActionKind] = {}


def register(kind: ActionKind) -> ActionKind:
    """THE extension point: one call per action kind."""
    if kind.room_patch is None and kind.apply is None and kind.name != "pause":
        raise ValueError(f"action kind {kind.name!r} has no way to apply")
    ACTION_KINDS[kind.name] = kind
    return kind


# ── validation ─────────────────────────────────────────────────────────────

def _coerce(p: Param, value: Any) -> Any:
    t = p.type
    if t == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in ("true", "on", "yes", "1"):
            return True
        if isinstance(value, str) and value.lower() in ("false", "off", "no", "0"):
            return False
        if isinstance(value, (int, float)):
            return bool(value)
        raise ActionError(f"{p.name}: expected on/off")
    if t == "number":
        try:
            v = float(value)
        except (TypeError, ValueError):
            raise ActionError(f"{p.name}: expected a number")
        if p.min is not None and v < p.min:
            raise ActionError(f"{p.name}: {v:g} is below the minimum {p.min:g}")
        if p.max is not None and v > p.max:
            raise ActionError(f"{p.name}: {v:g} is above the maximum {p.max:g}")
        return v
    if t == "enum":
        if p.choices is not None and value not in p.choices:
            raise ActionError(f"{p.name}: {value!r} is not one of {p.choices}")
        return value
    if t == "color":
        if not isinstance(value, str) or not HEX.match(value):
            raise ActionError(f"{p.name}: expected a colour like #ffaa00")
        return value.lower()
    if t in ("scenes", "color_sets", "hue_areas"):
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            raise ActionError(f"{p.name}: expected a list of ids")
        return value
    if t == "target":
        if not isinstance(value, dict):
            raise ActionError(f"{p.name}: expected {{kind, id}}")
        kind = value.get("kind", "everything")
        if kind not in ("fixture", "category", "everything"):
            raise ActionError(f"{p.name}: kind must be fixture, category or everything")
        if kind != "everything" and not value.get("id"):
            raise ActionError(f"{p.name}: a {kind} target needs an id")
        return {"kind": kind, "id": value.get("id")}
    if t == "overrides":
        if not isinstance(value, dict):
            raise ActionError(f"{p.name}: expected a mapping of parameter overrides")
        return value
    if isinstance(value, str) or value is None:
        return value
    raise ActionError(f"{p.name}: expected text")


def validate(kind_name: str, params: Optional[dict]) -> dict:
    """Normalise a step's params against its declaration: unknown keys are
    refused (a typo must not silently do nothing), defaults filled in."""
    kind = ACTION_KINDS.get(kind_name)
    if kind is None:
        raise ActionError(f"unknown action {kind_name!r}")
    params = dict(params or {})
    known = {p.name for p in kind.params}
    extra = sorted(set(params) - known)
    if extra:
        raise ActionError(f"{kind.label}: unknown parameter(s) {', '.join(extra)}")
    out: dict = {}
    for p in kind.params:
        if params.get(p.name) is None:
            if p.required:
                raise ActionError(f"{kind.label}: {p.label or p.name} is required")
            out[p.name] = p.default
            continue
        out[p.name] = _coerce(p, params[p.name])
    if kind.check is not None:
        out = kind.check(out)
    return out


def validate_set(actions: list[ShowAction]) -> list[str]:
    """Every problem in a set, one sentence each (empty = valid)."""
    problems = []
    for i, a in enumerate(actions, 1):
        try:
            validate(a.kind, a.params)
        except ActionError as exc:
            problems.append(f"step {i}: {exc}")
    return problems


def conflicts(actions: list[ShowAction]) -> list[str]:
    """Later-wins collisions inside one set, named for the editor. The set
    still saves; the later step wins when it runs."""
    seen: dict[str, int] = {}
    out = []
    for i, a in enumerate(actions, 1):
        kind = ACTION_KINDS.get(a.kind)
        if kind is None or not a.enabled or kind.room_patch is None:
            continue
        try:
            keys = kind.room_patch(validate(a.kind, a.params)).keys()
        except Exception:                                # noqa: BLE001
            continue
        for k in keys:
            if k in seen:
                out.append(f"step {i} changes {k} again (step {seen[k]} also "
                           f"does) — step {i} wins")
            seen[k] = i
    return out


# ── baselines ──────────────────────────────────────────────────────────────

def _baseline(key: str, label: str, original: Any, written: Any) -> None:
    st = show_store.state()
    b = st.baselines.get(key)
    if b is None:
        st.baselines[key] = SettingBaseline(key=key, label=label,
                                            original=original, written=written)
    else:
        b.written = written
    if st.started_ms is None:
        st.started_ms = now_ms()


# ── the room-setting kinds ─────────────────────────────────────────────────

def _room_choices(name: str) -> Optional[list]:
    try:
        from spectra.services import room_controls
        return room_controls.field_choices(name)
    except Exception:                                    # noqa: BLE001
        return None


def _ambient_patch(p: dict) -> dict:
    patch = {"ambient_enabled": bool(p["on"])}
    if p.get("areas") is not None:
        patch["ambient_hue_group_ids"] = list(p["areas"])
    return patch


def _check_force_scene(p: dict) -> dict:
    if p["on"] and not p.get("scene_id"):
        raise ActionError("Forced scene: choose the scene to pin")
    if p.get("scene_id"):
        from spectra.services import scene_store
        if scene_store.get_by_id(p["scene_id"]) is None:
            raise ActionError(f"Forced scene: no scene {p['scene_id']!r}")
    return p


def _check_force_color(p: dict) -> dict:
    if p["on"] and not p.get("target_id"):
        raise ActionError("Forced colour: choose the colour set or group")
    if p.get("target_id"):
        from spectra.services import color_sets
        if color_sets.get_by_id(p["target_id"]) is None:
            raise ActionError(f"Forced colour: no colour set or group {p['target_id']!r}")
    return p


def _check_gradient(p: dict) -> dict:
    if p["on"] and not p.get("gradient_id"):
        raise ActionError("Drift gradient: choose the gradient")
    if p["on"]:
        from spectra.services import gradient2d_store
        if p["gradient_id"] not in gradient2d_store.load_all():
            raise ActionError(f"Drift gradient: no gradient {p['gradient_id']!r}")
    return p


register(ActionKind(
    name="ambient", label="Ambient", group="setting",
    params=[Param("on", "bool", "On", default=True),
            Param("areas", "hue_areas", "Hue areas",
                  help="Empty = every Hue area (the room bar's own default)."),
            Param("speed", "enum", "Speed", default="eased",
                  choices=["eased", "snap"],
                  help="Eased takes ~15-22 s across his bulbs; snap drops the "
                       "ramps (~5 s, the 300 ms per-bulb gap is zigbee physics). "
                       "For an instant change use Device state → Steady on the Hue areas.")],
    help="Turn Ambient on or off (Hue only), optionally choosing the areas.",
    restore="End show puts Ambient back as it was, unless you changed it since.",
    room_patch=_ambient_patch, help_topic="show-actions"))

register(ActionKind(
    name="display_mode", label="Display mode", group="setting",
    params=[Param("mode", "enum", "Mode", default="dark", required=True,
                  choices=_room_choices("display_mode") or ["default", "dark", "light"])],
    help="Hybrid (default), Dark or Light.",
    restore="End show puts the mode back, unless you changed it since.",
    room_patch=lambda p: {"display_mode": p["mode"]}))

register(ActionKind(
    name="force_scene", label="Forced scene", group="setting",
    params=[Param("on", "bool", "On", default=True),
            Param("scene_id", "scene", "Scene")],
    help="Pin a scene (fires it at once), or release the pin.",
    restore="End show puts the pin back as it was, unless you changed it since.",
    room_patch=lambda p: ({"force_scene_enabled": True,
                           "force_scene_scene_id": p["scene_id"]}
                          if p["on"] else {"force_scene_enabled": False}),
    check=_check_force_scene))

register(ActionKind(
    name="force_color", label="Forced colour", group="setting",
    params=[Param("on", "bool", "On", default=True),
            Param("target_id", "color_set", "Colour set or group")],
    help="Pin the colours to a set or group, or release the pin.",
    restore="End show puts the pin back as it was, unless you changed it since.",
    room_patch=lambda p: ({"force_color_enabled": True,
                           "force_color_target_id": p["target_id"]}
                          if p["on"] else {"force_color_enabled": False}),
    check=_check_force_color))

register(ActionKind(
    name="drift_gradient", label="Drift gradient", group="setting",
    params=[Param("on", "bool", "On", default=True),
            Param("gradient_id", "gradient", "Gradient")],
    help="Turn the 2D drift gradient on (choosing one) or off.",
    restore="End show puts the gradient back as it was, unless you changed it since.",
    room_patch=lambda p: {"active_gradient_id": p["gradient_id"] if p["on"] else None},
    check=_check_gradient))

register(ActionKind(
    name="scene_change_mode", label="Scene-change setting", group="setting",
    params=[Param("mode", "enum", "Scene changes", required=True,
                  default="full",
                  choices=_room_choices("scene_change_mode")
                  or ["transitions", "analysed", "triggers_only", "full"])],
    help="Which scene changes the room makes (the room bar's Scene changes select).",
    restore="End show puts it back, unless you changed it since.",
    room_patch=lambda p: {"scene_change_mode": p["mode"]}))


# ── house lighting ─────────────────────────────────────────────────────────
# (spectra/services/house.py is the binding statement; HouseSettings.enabled
# is THE CUTOVER SWITCH, the same one the top-bar Mode chip's long press and
# the House page's own power button flip.)

def _check_house_mode(p: dict) -> dict:
    from spectra.services import house_store
    if house_store.find_mode(p["mode"]) is None:
        known = [m.name for m in house_store.list_modes()]
        raise ActionError(
            f"House mode: no house mode called {p['mode']!r}"
            + (f" — known: {', '.join(known)}" if known else
               " — no house modes exist yet"))
    return p


def _house_mode_snapshot() -> dict:
    from spectra.services import house_store
    st = house_store.state()
    return {"mode_id": st.mode_id, "manual": st.manual, "source": st.source}


async def _apply_house_mode_on(p: dict, ctx: "RunContext") -> Outcome:
    from spectra.services import house, house_store
    enabled_before = house.house_enabled()
    mode_before = _house_mode_snapshot()
    switched_on = False
    if not enabled_before:
        await house.set_enabled(True)
        switched_on = True
    _baseline("house:enabled", "house lighting", enabled_before, True)
    result = await house.set_mode(mode=p["mode"], source="light-show",
                                  glide_s=p.get("glide_s"))
    status = result.get("status")
    if status == "unknown_mode":
        # The check() above catches this under ordinary editing; still
        # refuse cleanly rather than silently doing nothing if the mode was
        # deleted between save and fire.
        show_store.save_state()
        return Outcome("failed", result.get("reason") or f"no house mode {p['mode']!r}")
    _baseline("house:mode", "house mode", mode_before, _house_mode_snapshot())
    show_store.save_state()
    mode_obj = house_store.find_mode(p["mode"])
    name = mode_obj.name if mode_obj else p["mode"]
    prefix = "switched house lighting on; " if switched_on else ""
    return Outcome("applied", f"{prefix}house mode: {name} ({status})")


async def _apply_house_lighting_off(p: dict, ctx: "RunContext") -> Outcome:
    from spectra.services import house
    before = house.house_enabled()
    if not before:
        return Outcome("skipped", "house lighting was already off")
    await house.set_enabled(False)
    _baseline("house:enabled", "house lighting", before, False)
    show_store.save_state()
    return Outcome("applied", "house lighting off — handing the look back to the show")


async def _apply_house_lighting_on(p: dict, ctx: "RunContext") -> Outcome:
    from spectra.services import house
    before = house.house_enabled()
    if before:
        return Outcome("skipped", "house lighting was already on")
    await house.set_enabled(True)
    _baseline("house:enabled", "house lighting", before, True)
    show_store.save_state()
    return Outcome("applied", "house lighting on")


register(ActionKind(
    name="house_mode_on", label="Turn on house mode", group="setting",
    params=[Param("mode", "house_mode", "Mode", required=True,
                  help="One of his house modes (Standard, Evening, Dim, "
                       "Night light, Away, TV, TV paused, or any he adds)."),
            Param("glide_s", "number", "Glide", min=0.0, max=600.0, unit="s",
                  help="Empty = the mode's own button glide.")],
    help="Switch house lighting on (if it is off) and select a mode — the "
         "same as the House page's own mode picker.",
    restore="End show puts the switch and the mode back, unless you "
            "changed either since.",
    apply=_apply_house_mode_on, check=_check_house_mode, help_topic="house"))

register(ActionKind(
    name="house_lighting_off", label="Turn house lighting off", group="setting",
    params=[],
    help="Switch house lighting off — hands the look back to the music "
         "show smoothly, the same as the top-bar Mode chip's long press.",
    restore="Turn house lighting on brings it back (the mode stays set, "
            "if one is), or End show puts the switch back, unless you "
            "changed it since.",
    apply=_apply_house_lighting_off, help_topic="house"))

register(ActionKind(
    name="house_lighting_on", label="Turn house lighting on", group="setting",
    params=[],
    help="Switch house lighting back on without changing which mode is set.",
    restore="Turn house lighting off switches it back off, or End show "
            "puts the switch back, unless you changed it since.",
    apply=_apply_house_lighting_on, help_topic="house"))


# ── item on/off ────────────────────────────────────────────────────────────

async def _apply_scene_enabled(p: dict, ctx: "RunContext") -> Outcome:
    from spectra.services import scene_store
    done, missing = [], []
    for sid in p["scenes"]:
        before = scene_store.set_disabled(sid, not p["enabled"])
        if before is None:
            missing.append(sid)
            continue
        scene = scene_store.get_by_id(sid)
        name = scene.name if scene else sid
        _baseline(f"scene:{sid}", f"scene {name}", before, not p["enabled"])
        done.append(name)
    show_store.save_state()
    if not done:
        return Outcome("failed", f"no such scene(s): {', '.join(missing)}")
    word = "enabled" if p["enabled"] else "disabled"
    detail = f"{word}: {', '.join(done)}"
    if missing:
        return Outcome("applied", detail + f" (not found: {', '.join(missing)})")
    return Outcome("applied", detail)


async def _color_set_http(card_id: str, disabled: bool) -> Optional[bool]:
    """Flip ONE colour card's `disabled` through SpotFX's own API — the
    only writer of color_sets.json. Returns the value it had, or None if
    the card does not exist."""
    import httpx
    from spectra.services.bridge import default_http_url
    base = default_http_url()
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"{base}/api/color-sets/{card_id}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        card = r.json()
        before = bool(card.get("disabled", False))
        if before != disabled:
            card["disabled"] = disabled
            w = await client.post(f"{base}/api/color-sets", json=card)
            w.raise_for_status()
        return before


#: injectable for tests (no live access from tests, ever)
color_set_writer: Callable[[str, bool], Awaitable[Optional[bool]]] = _color_set_http


async def _apply_color_set_enabled(p: dict, ctx: "RunContext") -> Outcome:
    from spectra.services import color_sets
    done, missing, failed = [], [], []
    for cid in p["color_sets"]:
        try:
            before = await color_set_writer(cid, not p["enabled"])
        except Exception as exc:                         # noqa: BLE001
            failed.append(f"{cid} ({exc})")
            continue
        if before is None:
            missing.append(cid)
            continue
        card = color_sets.get_by_id(cid)
        name = getattr(card, "name", None) or cid
        _baseline(f"color_set:{cid}", f"colour set {name}", before, not p["enabled"])
        done.append(name)
    show_store.save_state()
    if not done:
        return Outcome("failed", "; ".join(
            ([f"not found: {', '.join(missing)}"] if missing else [])
            + ([f"could not write: {', '.join(failed)}"] if failed else []))
            or "nothing to change")
    word = "enabled" if p["enabled"] else "disabled"
    extra = []
    if missing:
        extra.append(f"not found: {', '.join(missing)}")
    if failed:
        extra.append(f"could not write: {', '.join(failed)}")
    return Outcome("applied", f"{word}: {', '.join(done)}"
                   + (f" ({'; '.join(extra)})" if extra else ""))


register(ActionKind(
    name="scene_enabled", label="Scene on/off", group="setting",
    params=[Param("scenes", "scenes", "Scenes", required=True),
            Param("enabled", "bool", "Enabled", default=False)],
    help="Enable or disable scenes — the same switch as each scene's power button.",
    restore="End show puts each scene back, unless you changed it since.",
    apply=_apply_scene_enabled))

register(ActionKind(
    name="color_set_enabled", label="Colour set on/off", group="setting",
    params=[Param("color_sets", "color_sets", "Colour sets or groups", required=True),
            Param("enabled", "bool", "Enabled", default=False)],
    help="Enable or disable colour sets or groups — the same switch as their power buttons.",
    restore="End show puts each one back, unless you changed it since.",
    apply=_apply_color_set_enabled))


# ── momentary ──────────────────────────────────────────────────────────────

async def _apply_fire_scene(p: dict, ctx: "RunContext") -> Outcome:
    from spectra.services import scene_compiler, scene_store
    scene = scene_store.get_by_id(p["scene_id"])
    if scene is None:
        return Outcome("failed", f"no scene {p['scene_id']!r}")
    await scene_compiler.fire_scene(scene, intensity=p["intensity"], dry_run=False)
    return Outcome("applied", f"fired {scene.name}")


async def _apply_color_set_now(p: dict, ctx: "RunContext") -> Outcome:
    from spectra.services import color_set_groups, engine
    try:
        card = color_set_groups.resolve_ref(p["set_id"])
    except ValueError as exc:
        return Outcome("failed", str(exc))
    await engine.conductor.apply_set_directly(card)
    return Outcome("applied", f"applied {getattr(card, 'name', p['set_id'])}")


register(ActionKind(
    name="fire_scene", label="Fire a scene now", group="setting",
    params=[Param("scene_id", "scene", "Scene", required=True),
            Param("intensity", "number", "Intensity", default=0.6, min=0.0, max=1.0)],
    help="Fire a scene immediately, exactly like its Fire button.",
    restore="Nothing to put back — the room moves on from it as from any fire.",
    apply=_apply_fire_scene))

register(ActionKind(
    name="apply_color_set", label="Apply a colour set now", group="setting",
    params=[Param("set_id", "color_set", "Colour set or group", required=True)],
    help="Apply a colour set or group to the room now, exactly like Apply.",
    restore="Nothing to put back — the colour journey carries on from it.",
    apply=_apply_color_set_now))


# ── device output ──────────────────────────────────────────────────────────

def _hex_rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _ambient_hex() -> str:
    try:
        from spectra.services import room_controls
        c = room_controls.effective_ambient_color(room_controls.load_room_controls())
        if isinstance(c, str) and HEX.match(c):
            return c
    except Exception:                                    # noqa: BLE001
        pass
    return "#f5da8c"


def _resolve(p: dict) -> tuple[list[str], Optional[Outcome]]:
    devices, problems = show_output.resolve_target(p["target"])
    if not devices:
        return [], Outcome("failed", "; ".join(problems) or "no fixture resolved")
    return devices, None


async def _apply_device_state(p: dict, ctx: "RunContext") -> Outcome:
    devices, bad = _resolve(p)
    if bad:
        return bad
    color = None
    if p["state"] == "steady":
        color = _hex_rgb(p.get("color") or _ambient_hex())
    res = show_output.set_state(devices, p["state"], color=color,
                                fade_ms=int(p["fade_ms"]), source=ctx.source)
    names = ", ".join(r["name"] for r in res)
    notes = [f"{r['name']}: {r['note']}" for r in res if r.get("note")]
    return Outcome("applied", f"{p['state']}: {names}" + (f" ({'; '.join(notes)})" if notes else ""),
                   {"devices": devices})


async def _apply_level(p: dict, ctx: "RunContext") -> Outcome:
    devices, bad = _resolve(p)
    if bad:
        return bad
    lv = show_output.add_level(devices, p["level"] / 100.0,
                               fade_in_ms=int(p["fade_in_ms"]),
                               fade_out_ms=int(p["fade_out_ms"]),
                               until=p["until"], duration_s=p["duration_s"],
                               source=ctx.source)
    names = ", ".join(show_output.device_label(d) for d in devices)
    end = {"time": f"for {p['duration_s']:g} s", "scene_change": "until the next scene change",
           "released": "until released"}.get(lv.until, "")
    return Outcome("applied", f"level {p['level']:g}% on {names} {end}".strip(),
                   {"devices": devices, "level_id": lv.id})


async def _apply_flash(p: dict, ctx: "RunContext") -> Outcome:
    devices, bad = _resolve(p)
    if bad:
        return bad
    show_output.flash(devices, color=_hex_rgb(p["color"]), amount=p["amount"],
                      attack_ms=p["attack_ms"], hold_ms=p["hold_ms"],
                      decay_ms=p["decay_ms"])
    return Outcome("applied", "flash: " + ", ".join(show_output.device_label(d) for d in devices),
                   {"devices": devices})


def _check_level(p: dict) -> dict:
    if p["until"] == "time" and not p.get("duration_s"):
        raise ActionError("Level: a timed level needs a duration (or choose "
                          "'until released' / 'until the next scene change')")
    return p


_TARGET = Param("target", "target", "Fixture or category", required=True,
                help="One fixture, a category, or everything.")

register(ActionKind(
    name="device_state", label="Device state", group="device",
    params=[_TARGET,
            Param("state", "enum", "State", default="dark", required=True,
                  choices=["show", "steady", "freeze", "dark"],
                  help="Show = music reactive. Steady = one still colour. "
                       "Freeze = hold the picture as it is. Dark = off."),
            Param("color", "color", "Steady colour",
                  help="Steady only. Empty = his Ambient colour."),
            Param("fade_ms", "number", "Fade", default=0, min=0, max=60000, unit="ms",
                  help="0 = instant.")],
    help="Make a fixture or category Dark, Steady, Frozen, or back to Show. "
         "The show keeps running underneath, so Show comes back in step.",
    restore="Another Device state action, its Release button, or End show.",
    apply=_apply_device_state, help_topic="show-device-states"))

register(ActionKind(
    name="level", label="Level (dim or brighten)", group="device",
    params=[_TARGET,
            Param("level", "number", "Level", default=50, min=0, max=200, unit="%",
                  help="100 = unchanged; above 100 brightens (clipped at full)."),
            Param("fade_in_ms", "number", "Fade in", default=500, min=0, max=60000, unit="ms"),
            Param("until", "enum", "Ends", default="time",
                  choices=["time", "scene_change", "released"]),
            Param("duration_s", "number", "For", default=10, min=0, max=3600, unit="s"),
            Param("fade_out_ms", "number", "Fade out", default=1000, min=0, max=60000, unit="ms")],
    help="Temporarily darken or brighten a fixture or category. Levels stack.",
    restore="Ends by itself (after its time, at the next scene change, or when released).",
    apply=_apply_level, check=_check_level, help_topic="show-level"))

register(ActionKind(
    name="flash", label="Flash", group="device",
    params=[_TARGET,
            Param("color", "color", "Colour", default="#ffffff"),
            Param("amount", "number", "Amount", default=1.0, min=0.0, max=1.0),
            Param("attack_ms", "number", "Attack", default=50, min=0, max=5000, unit="ms"),
            Param("hold_ms", "number", "Hold", default=100, min=0, max=10000, unit="ms"),
            Param("decay_ms", "number", "Decay", default=400, min=0, max=10000, unit="ms")],
    help="Mix a fixture toward a colour (white by default) for a moment — "
         "the visible 'brighten' on a light already at full.",
    restore="Nothing to put back — it fades away by itself.",
    apply=_apply_flash, help_topic="show-device-states"))


# ── effect modifiers: Pulse modulation and flares on/off (show_mods.py) ────

_UNTIL = Param("until", "enum", "Ends", default="released",
               choices=["released", "time", "scene_change"],
               help="Until released (its End button or End show), after a "
                    "time, or at the next scene change.")
_FOR = Param("duration_s", "number", "For", default=30, min=0, max=3600, unit="s",
             help="Only when it ends after a time.")


def _resolve_virtuals(p: dict) -> tuple[list[str], str, list[str], Optional[Outcome]]:
    from spectra.services import show_mods
    vids, label, shared, problems = show_mods.resolve_virtuals(p["target"])
    if not vids:
        return [], label, [], Outcome("failed", "; ".join(problems) or "no virtual resolved")
    return vids, label, shared, None


def _check_timed(p: dict) -> dict:
    if p.get("until") == "time" and not p.get("duration_s"):
        raise ActionError("a timed hold needs a duration (or choose "
                          "'until released' / 'until the next scene change')")
    return p


def _pulse_note(vids: list[str]) -> str:
    """Which of these virtuals run Pulse right now, said plainly."""
    from spectra.services.live_host import live
    host = live.host
    if host is None:
        return ""
    running, idle = [], []
    for vid in vids:
        v = host.virtuals.get(vid)
        eff = getattr(v, "active_effect", None) if v is not None else None
        (running if getattr(eff, "type", None) == "pulse" else idle).append(vid)
    if not running:
        return (" — nothing there runs Pulse right now; it applies the moment "
                "Pulse runs there while this holds")
    return f" (Pulse on {', '.join(running)})"


def _ends_word(p: dict) -> str:
    return {"time": f"for {p['duration_s']:g} s",
            "scene_change": "until the next scene change",
            "released": "until released"}.get(p["until"], "")


async def _apply_pulse_reactivity(p: dict, ctx: "RunContext") -> Outcome:
    from spectra.services import show_mods
    vids, label, _shared, bad = _resolve_virtuals(p)
    if bad:
        return bad
    m = show_mods.add_pulse_mod(vids, label=label, reactivity=float(p["reactivity"]),
                                fade_in_ms=int(p["fade_in_ms"]),
                                fade_out_ms=int(p["fade_out_ms"]),
                                until=p["until"], duration_s=p["duration_s"],
                                source=ctx.source)
    return Outcome("applied", f"Pulse reactivity {p['reactivity']:g} on {label} "
                              f"{_ends_word(p)}{_pulse_note(vids)}",
                   {"virtuals": vids, "pulse_mod_id": m.id})


def _check_pulse_brightness(p: dict) -> dict:
    p = _check_timed(p)
    if p["floor"] > p["ceiling"]:
        raise ActionError(f"Pulse brightness: the floor ({p['floor']:g}) is above "
                          f"the ceiling ({p['ceiling']:g})")
    if p["floor"] <= 0.0 and p["ceiling"] >= 1.0:
        raise ActionError("Pulse brightness: set a floor above 0 or a ceiling "
                          "below 1 — 0 and 1 change nothing")
    return p


async def _apply_pulse_brightness(p: dict, ctx: "RunContext") -> Outcome:
    from spectra.services import show_mods
    vids, label, _shared, bad = _resolve_virtuals(p)
    if bad:
        return bad
    floor = float(p["floor"]) if p["floor"] > 0.0 else None
    ceiling = float(p["ceiling"]) if p["ceiling"] < 1.0 else None
    m = show_mods.add_pulse_mod(vids, label=label, floor=floor, ceiling=ceiling,
                                fade_in_ms=int(p["fade_in_ms"]),
                                fade_out_ms=int(p["fade_out_ms"]),
                                until=p["until"], duration_s=p["duration_s"],
                                source=ctx.source)
    return Outcome("applied", f"Pulse brightness {p['floor']:g}–{p['ceiling']:g} on "
                              f"{label} {_ends_word(p)}{_pulse_note(vids)}",
                   {"virtuals": vids, "pulse_mod_id": m.id})


async def _release_phase_on(vids: list[str]) -> list[str]:
    from spectra.services import engine
    return await engine.responses.release_phase_on(vids)


#: Flares going off lets go of a charge/lull already under way there. The
#: seam to the production response engine; replaced in tests.
phase_releaser = _release_phase_on


async def _apply_flares(p: dict, ctx: "RunContext") -> Outcome:
    from spectra.services import show_mods
    vids, label, shared, bad = _resolve_virtuals(p)
    if bad:
        return bad
    if p["flares"] == "on":
        ended = show_mods.lift_flares(vids)
        if not ended:
            return Outcome("skipped", f"flares were already on for {label}",
                           {"virtuals": vids})
        return Outcome("applied", f"flares back on for {label}",
                       {"virtuals": vids, "ended": ended})
    b = show_mods.add_flare_block(vids, label=label, until=p["until"],
                                  duration_s=p["duration_s"], source=ctx.source)
    released: list[str] = []
    try:
        released = await phase_releaser(vids)
    except Exception:                                    # noqa: BLE001
        logger.exception("light show: letting go of a charge/lull on flares-off failed")
    also = f" — also {', '.join(shared)}, which share{'s' if len(shared) == 1 else ''} " \
           f"its virtual" if shared else ""
    let_go = f"; let go of the charge/lull on {', '.join(released)}" if released else ""
    return Outcome("applied", f"flares off for {label} {_ends_word(p)}{also}{let_go}",
                   {"virtuals": vids, "flare_block_id": b.id, "shared_with": shared,
                    "phase_released": released})


register(ActionKind(
    name="pulse_reactivity", label="Pulse reactivity", group="effect",
    params=[_TARGET,
            Param("reactivity", "number", "Reactivity", default=0.5, required=True,
                  min=0.0, max=1.0,
                  help="1 = as reactive as it is now (full), 0 = no reaction "
                       "to the music's hits."),
            Param("fade_in_ms", "number", "Fade in", default=1000, min=0, max=60000, unit="ms"),
            _UNTIL, _FOR,
            Param("fade_out_ms", "number", "Fade out", default=1000, min=0, max=60000, unit="ms")],
    help="Turn how strongly the Pulse effect reacts to the music up or down "
         "on a fixture, a category or everything. Only Pulse listens; holds "
         "stack (they multiply).",
    restore="Ends by itself (after its time, at the next scene change), its "
            "End button, or End show.",
    apply=_apply_pulse_reactivity, check=_check_timed, help_topic="show-pulse"))

register(ActionKind(
    name="pulse_brightness", label="Pulse brightness floor / ceiling", group="effect",
    params=[_TARGET,
            Param("floor", "number", "Floor", default=0.0, min=0.0, max=1.0,
                  help="Pulse never goes darker than this (0 = no floor)."),
            Param("ceiling", "number", "Ceiling", default=1.0, min=0.0, max=1.0,
                  help="Pulse never goes brighter than this (1 = no ceiling)."),
            Param("fade_in_ms", "number", "Fade in", default=1000, min=0, max=60000, unit="ms"),
            _UNTIL, _FOR,
            Param("fade_out_ms", "number", "Fade out", default=1000, min=0, max=60000, unit="ms")],
    help="Keep the Pulse effect between a brightness floor and ceiling "
         "(0..1, the effect's own brightness scale) — through hits, drops, "
         "lulls and flares alike.",
    restore="Ends by itself (after its time, at the next scene change), its "
            "End button, or End show.",
    apply=_apply_pulse_brightness, check=_check_pulse_brightness,
    help_topic="show-pulse"))

register(ActionKind(
    name="flares", label="Flares on / off", group="effect",
    params=[_TARGET,
            Param("flares", "enum", "Flares", default="off", required=True,
                  choices=["off", "on"],
                  help="Off: flares stop reaching these lights. On: lift any "
                       "flares-off on them."),
            _UNTIL, _FOR],
    help="Switch flares off (or back on) for a fixture, a category or "
         "everything — e.g. keep the Hue bulbs steady while everything else "
         "flares. Off also skips the charge/lull/drop there (no climb, no "
         "lull darkness, no drop burst); the scene and its colour journey "
         "carry on.",
    restore="Ends by itself (after its time, at the next scene change), a "
            "'Flares on' step, its End button, or End show.",
    apply=_apply_flares, check=_check_timed, help_topic="show-flares"))


# ── room effects ───────────────────────────────────────────────────────────

class RoomEffectRunner:
    """The seam to room_effects' ONE entry point. Replaced by a stub in
    tests; production delegates straight through."""

    async def start(self, room, spec) -> dict:
        from spectra.services import room_effects
        return await room_effects.start(room, spec)

    async def stop(self) -> dict:
        from spectra.services import room_effects
        return await room_effects.stop()

    async def touch(self, window_s: float) -> None:
        from spectra.services import flare_preview_hold
        await flare_preview_hold.touch(window_s)

    def get_room(self, room_id: str):
        from spectra.services import light_field
        return light_field.get_room(room_id)

    def load_effects(self) -> list:
        from spectra.services import room_effects
        return room_effects.load_effects()

    def ceiling_s(self) -> float:
        from spectra.services import flare_preview_hold
        return float(flare_preview_hold.MAX_HOLD_DURATION_S)


room_effect_runner = RoomEffectRunner()
_effect_task: Optional[asyncio.Task] = None


def _find_effect(ref: str):
    effects = room_effect_runner.load_effects()
    hit = next((e for e in effects if e.id == ref), None)
    if hit is None:
        low = (ref or "").strip().lower()
        hit = next((e for e in effects if e.name.strip().lower() == low), None)
    return hit


def _check_room_effect(p: dict) -> dict:
    spec = _find_effect(p["effect"])
    if spec is None:
        raise ActionError(f"Room effect: no room effect called {p['effect']!r}")
    overrides = dict(p.get("params") or {})
    for locked in ("id", "room_id"):
        if locked in overrides:
            raise ActionError(f"Room effect: {locked} cannot be overridden")
    try:
        type(spec)(**{**spec.model_dump(), **overrides})
    except Exception as exc:                             # noqa: BLE001
        raise ActionError(f"Room effect: {exc}")
    return p


async def _effect_keepalive(duration_s: float) -> None:
    """Keep the show's room effect's held room alive for its duration, then
    stop it. The hold's own 3-minute ceiling still bounds it."""
    deadline = time.monotonic() + duration_s
    try:
        while time.monotonic() < deadline:
            await room_effect_runner.touch(ROOM_EFFECT_HEARTBEAT_S * 3)
            await asyncio.sleep(min(ROOM_EFFECT_HEARTBEAT_S,
                                    max(0.05, deadline - time.monotonic())))
        await _stop_show_room_effect()
    except asyncio.CancelledError:
        raise


async def _stop_show_room_effect() -> Optional[dict]:
    st = show_store.state()
    if st.room_effect is None:
        return None
    try:
        result = await room_effect_runner.stop()
    finally:
        st.room_effect = None
        show_store.save_state()
    return result


async def _apply_room_effect(p: dict, ctx: "RunContext") -> Outcome:
    global _effect_task
    spec = _find_effect(p["effect"])
    if spec is None:
        return Outcome("failed", f"no room effect called {p['effect']!r}")
    run_spec = type(spec)(**{**spec.model_dump(), **(p.get("params") or {})})
    room = room_effect_runner.get_room(run_spec.room_id)
    if room is None:
        return Outcome("failed", f"room {run_spec.room_id!r} no longer exists")
    ceiling = room_effect_runner.ceiling_s()
    duration = float(p["duration_s"] or ceiling)
    if _effect_task is not None and not _effect_task.done():
        _effect_task.cancel()
    result = await room_effect_runner.start(room, run_spec)
    if not (result or {}).get("running"):
        return Outcome("failed", (result or {}).get("reason")
                       or "the room effect did not start")
    st = show_store.state()
    st.room_effect = {"effect_id": spec.id, "name": spec.name,
                      "started_ms": now_ms(), "duration_s": min(duration, ceiling)}
    if st.started_ms is None:
        st.started_ms = now_ms()
    show_store.save_state()
    _effect_task = asyncio.create_task(_effect_keepalive(min(duration, ceiling)),
                                       name="light-show-room-effect")
    note = ""
    if duration > ceiling:
        note = f" (capped at the held room's {ceiling:g} s ceiling)"
    return Outcome("applied", f"running {spec.name} for {min(duration, ceiling):g} s{note}",
                   {"effect": result})


async def _apply_stop_room_effect(p: dict, ctx: "RunContext") -> Outcome:
    global _effect_task
    if _effect_task is not None and not _effect_task.done():
        _effect_task.cancel()
    _effect_task = None
    result = await _stop_show_room_effect()
    if result is None:
        result = await room_effect_runner.stop()
        if not (result or {}).get("stopped"):
            return Outcome("skipped", "no room effect was running")
    return Outcome("applied", "room effect stopped")


register(ActionKind(
    name="room_effect", label="Run a room effect", group="effect",
    params=[Param("effect", "room_effect", "Room effect", required=True),
            Param("params", "overrides", "Parameter overrides", default={},
                  help="Any of the effect's own parameters, for this run only."),
            Param("duration_s", "number", "For", default=30, min=0, max=180, unit="s",
                  help="0 = as long as the held room allows (3 minutes).")],
    help="Run one of his room effects (e.g. a Dim Wave) through its own "
         "held-room program. Any future room effect appears here once authored.",
    restore="Stops by itself after its time; Stop room effect or End show stops it sooner.",
    apply=_apply_room_effect, check=_check_room_effect, help_topic="show-room-effects"))

register(ActionKind(
    name="stop_room_effect", label="Stop room effect", group="effect",
    params=[],
    help="Stop the running room effect and hand the room back.",
    restore="—",
    apply=_apply_stop_room_effect, help_topic="show-room-effects"))


# ── control ────────────────────────────────────────────────────────────────

register(ActionKind(
    name="pause", label="Pause", group="control",
    params=[Param("seconds", "number", "Wait", default=2, min=0.1, max=MAX_PAUSE_S, unit="s")],
    help="Wait before the next step of the set.",
    restore="—", needs_room=False, help_topic="show-sets"))


# ── catalogue (for the Build view and, later, Sonic) ───────────────────────

def catalogue() -> dict:
    kinds = [k.as_dict() for k in ACTION_KINDS.values()]
    effects = []
    effect_schema = None
    try:
        for e in room_effect_runner.load_effects():
            effects.append({"id": e.id, "name": e.name, "kind": e.kind,
                            "room_id": e.room_id})
        from spectra.services.room_effects import RoomEffectSpec
        effect_schema = RoomEffectSpec.model_json_schema()
    except Exception:                                    # noqa: BLE001
        logger.exception("light show: could not list room effects")
    house_modes = []
    try:
        from spectra.services import house_store
        house_modes = [{"id": m.id, "name": m.name} for m in house_store.list_modes()]
    except Exception:                                    # noqa: BLE001
        logger.exception("light show: could not list house modes")
    return {"kinds": kinds, "room_effects": effects,
            "room_effect_schema": effect_schema, "house_modes": house_modes}


# ── running a set ──────────────────────────────────────────────────────────

@dataclass
class RunContext:
    run_id: str
    source: str


@dataclass
class Run:
    id: str
    name: str
    set_id: Optional[str]
    source: str
    started_ms: int
    steps: list[dict]
    state: str = "running"          # running | done | partial | failed | refused | cancelled
    ended_ms: Optional[int] = None
    task: Optional[asyncio.Task] = None
    ready: asyncio.Event = field(default_factory=asyncio.Event)

    def as_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "set_id": self.set_id,
                "source": self.source, "started_ms": self.started_ms,
                "ended_ms": self.ended_ms, "state": self.state,
                "steps": list(self.steps)}


_runs: list[Run] = []
_executing = 0


def executing() -> bool:
    """True while a show step is being applied — a scene change the show
    itself causes (a Forced scene or Fire-a-scene step) must never count as
    "the next scene change" for an arm, or a repeat arm would loop
    (spectra/services/show_arms.py)."""
    return _executing > 0


def runs() -> list[dict]:
    return [r.as_dict() for r in reversed(_runs)]


def _label(a: ShowAction) -> str:
    kind = ACTION_KINDS.get(a.kind)
    return a.label or (kind.label if kind else a.kind)


def _record(run: Run, idx: int, outcome: Outcome) -> None:
    run.steps[idx].update(outcome.as_dict())
    try:
        from spectra.services import fire_history
        fire_history.record_fire("show", run.steps[idx]["kind"],
                                 {"run": run.id, "set": run.name,
                                  "step": run.steps[idx]["label"],
                                  "status": outcome.status,
                                  "detail": outcome.detail})
    except Exception:                                    # noqa: BLE001
        logger.exception("light show: show-log write failed")


async def _run_room_group(run: Run, group: list[tuple[int, ShowAction, dict]]) -> None:
    from spectra.services import room_controls
    patch: dict = {}
    snap = False
    for _i, a, p in group:
        patch.update(ACTION_KINDS[a.kind].room_patch(p))
        if a.kind == "ambient" and p.get("speed") == "snap":
            snap = True
    previous = room_controls.load_room_controls().model_dump()
    try:
        result = await room_controls.apply_patch(patch, ambient_snap=snap)
    except Exception as exc:                             # noqa: BLE001
        for i, _a, _p in group:
            _record(run, i, Outcome("failed", f"the room settings did not save: {exc}"))
        return
    for key, value in patch.items():
        _baseline(f"room:{key}", key.replace("_", " "), previous.get(key), value)
    show_store.save_state()
    notes = []
    for k in ("ambient_result", "dark_light_result", "force_scene_result",
              "force_color_result"):
        r = result.get(k)
        if isinstance(r, dict):
            word = r.get("status") or r.get("result") or r.get("reason")
            if word:
                notes.append(f"{k.replace('_result', '').replace('_', ' ')}: {word}")
    for i, a, p in group:
        keys = ", ".join(ACTION_KINDS[a.kind].room_patch(p).keys())
        detail = f"set {keys}" + (f" ({'; '.join(notes)})" if notes else "")
        _record(run, i, Outcome("applied", detail))


def _finish(run: Run) -> None:
    statuses = [s.get("status") for s in run.steps]
    if run.state == "cancelled":
        pass
    elif statuses and all(s == "refused" for s in statuses if s != "skipped") \
            and "refused" in statuses and "applied" not in statuses:
        run.state = "refused"
    elif any(s in ("failed", "refused") for s in statuses):
        run.state = "partial" if "applied" in statuses else "failed"
    else:
        run.state = "done"
    run.ended_ms = now_ms()


async def _execute(run: Run, actions: list[ShowAction]) -> None:
    global _executing
    ctx = RunContext(run_id=run.id, source=run.source)
    pending: list[tuple[int, ShowAction, dict]] = []

    async def flush_group():
        if pending:
            group = list(pending)
            pending.clear()
            reason = show_output.refusal()
            if reason:
                for i, _a, _p in group:
                    _record(run, i, Outcome("refused", reason))
                return
            global _executing
            _executing += 1
            try:
                await _run_room_group(run, group)
            finally:
                _executing -= 1

    try:
        for i, a in enumerate(actions):
            if not a.enabled:
                _record(run, i, Outcome("skipped", "switched off in this set"))
                continue
            try:
                p = validate(a.kind, a.params)
            except ActionError as exc:
                await flush_group()
                _record(run, i, Outcome("failed", str(exc)))
                continue
            kind = ACTION_KINDS[a.kind]
            if kind.room_patch is not None:
                pending.append((i, a, p))
                continue
            await flush_group()
            if a.kind == "pause":
                run.ready.set()
                run.steps[i]["status"] = "waiting"
                await asyncio.sleep(float(p["seconds"]))
                _record(run, i, Outcome("applied", f"waited {p['seconds']:g} s"))
                continue
            reason = show_output.refusal() if kind.needs_room else None
            if reason:
                _record(run, i, Outcome("refused", reason))
                continue
            _executing += 1
            try:
                outcome = await kind.apply(p, ctx)
            except Exception as exc:                     # noqa: BLE001
                logger.exception("light show: %s failed", a.kind)
                outcome = Outcome("failed", f"{type(exc).__name__}: {exc}")
            finally:
                _executing -= 1
            _record(run, i, outcome)
        await flush_group()
    except asyncio.CancelledError:
        run.state = "cancelled"
        for s in run.steps:
            if s.get("status") in (None, "pending", "waiting"):
                s["status"] = "skipped"
                s["detail"] = "the show was ended before this step ran"
        _finish(run)
        run.ready.set()
        raise
    _finish(run)
    run.ready.set()


async def fire(actions: list[ShowAction], *, name: str, set_id: Optional[str] = None,
               source: str = "button") -> dict:
    """Run steps NOW. Returns once every step up to the first pause has
    landed (or the run has finished); the rest continues in the background
    and shows in `runs()`."""
    run = Run(id=uuid.uuid4().hex[:10], name=name, set_id=set_id,
              source=source if not set_id else f"set:{set_id}",
              started_ms=now_ms(),
              steps=[{"action_id": a.id, "kind": a.kind, "label": _label(a),
                      "status": "pending", "detail": ""} for a in actions])
    _runs.append(run)
    del _runs[:-MAX_RUNS_KEPT]
    run.task = asyncio.create_task(_execute(run, actions), name=f"light-show-{run.id}")
    await run.ready.wait()
    return run.as_dict()


async def fire_set(set_id_or_name: str, *, source: str = "button") -> dict:
    s = show_store.find_set(set_id_or_name)
    if s is None:
        raise ActionError(f"no set called {set_id_or_name!r}")
    if not s.actions:
        raise ActionError(f"set {s.name!r} has no steps")
    return await fire(s.actions, name=s.name, set_id=s.id, source=source)


def preview(actions: list[ShowAction]) -> list[dict]:
    """What firing would change against the room as it is NOW. Writes
    nothing."""
    from spectra.services import room_controls
    current = room_controls.load_room_controls().model_dump()
    out = []
    for a in actions:
        kind = ACTION_KINDS.get(a.kind)
        row = {"action_id": a.id, "kind": a.kind, "label": _label(a)}
        try:
            p = validate(a.kind, a.params)
        except ActionError as exc:
            out.append({**row, "problem": str(exc)})
            continue
        if not a.enabled:
            out.append({**row, "change": "switched off — will not run"})
        elif kind.room_patch is not None:
            changes = [f"{k}: {current.get(k)!r} → {v!r}"
                       for k, v in kind.room_patch(p).items() if current.get(k) != v]
            out.append({**row, "change": "; ".join(changes) or "already so — no change"})
        elif kind.name in ("pulse_reactivity", "pulse_brightness", "flares"):
            from spectra.services import show_mods
            vids, label, shared, problems = show_mods.resolve_virtuals(p["target"])
            extra = f" (also {', '.join(shared)})" if shared else ""
            out.append({**row, "change": f"{kind.label} on {label}{extra}" if vids
                        else "; ".join(problems)})
        elif kind.name in ("device_state", "level", "flash"):
            devices, problems = show_output.resolve_target(p["target"])
            names = ", ".join(show_output.device_label(d) for d in devices)
            out.append({**row, "change": f"{kind.label} on {names}" if devices
                        else "; ".join(problems)})
        elif kind.name == "pause":
            out.append({**row, "change": f"wait {p['seconds']:g} s"})
        else:
            out.append({**row, "change": kind.help})
    return out


# ── End show ───────────────────────────────────────────────────────────────

async def _current_value(key: str) -> tuple[bool, Any]:
    """(known, value) for a baseline key, read fresh."""
    kind, _, rest = key.partition(":")
    if kind == "room":
        from spectra.services import room_controls
        return True, room_controls.load_room_controls().model_dump().get(rest)
    if kind == "scene":
        from spectra.services import scene_store
        s = scene_store.get_by_id(rest)
        return (s is not None), (bool(s.disabled) if s else None)
    if kind == "color_set":
        from spectra.services import color_sets
        c = color_sets.get_by_id(rest)
        return (c is not None), (bool(getattr(c, "disabled", False)) if c else None)
    if kind == "house":
        from spectra.services import house
        if rest == "enabled":
            return True, house.house_enabled()
        if rest == "mode":
            return True, _house_mode_snapshot()
    return False, None


async def end_show(*, fade_ms: int = show_output.DEFAULT_RELEASE_FADE_MS) -> dict:
    """Put the room back: cancel running sets, stop the show's room effect,
    fade every held fixture back to Show, and restore every setting the show
    changed — unless he has changed it since, which is left alone and
    named. Not gated on ownership: restoring stored settings and letting go
    of holds is always safe."""
    from spectra.services import house, room_controls, scene_store
    global _effect_task
    cancelled = []
    for r in _runs:
        if r.task is not None and not r.task.done():
            r.task.cancel()
            cancelled.append(r.name)
    effect = None
    if _effect_task is not None and not _effect_task.done():
        _effect_task.cancel()
    _effect_task = None
    try:
        effect = await _stop_show_room_effect()
    except Exception as exc:                             # noqa: BLE001
        effect = {"error": str(exc)}
    st = show_store.state()
    effect_holds = {"pulse_mods": len(st.pulse_mods),
                    "flare_blocks": len(st.flare_blocks)}
    released = show_output.release_all(fade_ms)
    restored, left_alone, failed = [], [], []
    room_patch: dict = {}
    for key, b in list(st.baselines.items()):
        known, value = await _current_value(key)
        if not known:
            left_alone.append({"key": key, "label": b.label,
                               "reason": "it no longer exists"})
            continue
        if value != b.written:
            left_alone.append({"key": key, "label": b.label,
                               "reason": f"changed since the show set it "
                                         f"(now {value!r}) — left as you have it"})
            continue
        kind, _, rest = key.partition(":")
        try:
            if kind == "room":
                room_patch[rest] = b.original
            elif kind == "scene":
                scene_store.set_disabled(rest, bool(b.original))
                restored.append(b.label)
            elif kind == "color_set":
                await color_set_writer(rest, bool(b.original))
                restored.append(b.label)
            elif kind == "house" and rest == "enabled":
                await house.set_enabled(bool(b.original))
                restored.append(b.label)
            elif kind == "house" and rest == "mode":
                orig = b.original or {}
                mode_id = orig.get("mode_id")
                source = orig.get("source") or "light-show"
                if mode_id is None:
                    await house.set_mode(clear=True, source=source)
                else:
                    await house.set_mode(mode=mode_id, source=source)
                restored.append(b.label)
        except Exception as exc:                         # noqa: BLE001
            failed.append({"key": key, "label": b.label, "reason": str(exc)})
    if room_patch:
        try:
            await room_controls.apply_patch(room_patch)
            restored.extend(st.baselines[f"room:{k}"].label for k in room_patch)
        except Exception as exc:                         # noqa: BLE001
            failed.extend({"key": f"room:{k}", "label": k, "reason": str(exc)}
                          for k in room_patch)
    st.baselines.clear()
    st.started_ms = None
    show_store.save_state()
    try:
        from spectra.services import fire_history
        fire_history.record_fire("show", "end_show", {
            "restored": restored, "left_alone": [x["label"] for x in left_alone],
            "released": released})
    except Exception:                                    # noqa: BLE001
        pass
    return {"cancelled_runs": cancelled, "room_effect_stopped": effect is not None,
            "released_devices": released, "restored": restored,
            "ended_pulse_mods": effect_holds["pulse_mods"],
            "ended_flare_blocks": effect_holds["flare_blocks"],
            "left_alone": left_alone, "failed": failed}


def status() -> dict:
    st = show_store.state()
    running = [r.as_dict() for r in _runs if r.state == "running"]
    armed = any(a.status == "armed" for a in st.arms)
    return {"active": bool(st.started_ms or st.holds or st.levels or st.baselines
                           or st.room_effect or running or armed
                           or st.pulse_mods or st.flare_blocks),
            "started_ms": st.started_ms,
            "baselines": [{"key": b.key, "label": b.label, "original": b.original,
                           "written": b.written} for b in st.baselines.values()],
            "room_effect": st.room_effect,
            "running_sets": running,
            "recent_runs": runs()[:5],
            "arms": [a.model_dump() for a in st.arms if a.status == "armed"]}


def brief() -> dict:
    """The small summary the top-bar strip and engine status carry."""
    out = show_output.status()
    act = status()
    return {"active": act["active"] or bool(out["holds"] or out["levels"]),
            "holds": len(out["holds"]), "levels": len(out["levels"]),
            "pulse_mods": len(out["pulse_mods"]),
            "flare_blocks": len(out["flare_blocks"]),
            "running_sets": len(act["running_sets"]),
            "room_effect": (act["room_effect"] or {}).get("name"),
            "changed_settings": len(act["baselines"]),
            "armed": len(act["arms"]),
            "standdown": out["standdown"], "refusal": out["refusal"]}


def reset() -> None:
    """Tests."""
    global _effect_task, _executing
    _executing = 0
    _runs.clear()
    _effect_task = None
