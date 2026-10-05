"""SONIC'S HOUSE LIGHTING AUTHORITY (spectra/services/house.py; plan
/home/javi/fleet-spotfx/data/standard-lighting-plan/report.md §3.2: "every
field also reachable through Sonic — 'make Evening's crystal 10%'").

IN SCOPE: reading what the house is doing; listing the modes; switching to a
mode (or clearing it) — a person's pick, so it holds until Home Assistant's
word next changes, exactly like a press on the House page; creating a
brand-new mode by name (fresh id, a name clash REJECTED, never overwritten —
the Light Show console's own rule); and editing a mode's fields one at a
time: a named setting, one fixture setting (level / motion / frame-rate cap
/ off), one Hue area's look, or the scene / colour pools.

EXCLUDED, BY NAME: deleting a mode (an irreversible act on his authored
library — the House page's button, his press); taking or releasing the room
(no domain here has that authority; settings_agent.py's boundary argument);
anything that writes Home Assistant (River's side of the seam).

NAMES ARE NEVER GUESSED. A mode, scene, colour set, category, fixture or Hue
area named by a person resolves only on an exact id or case-insensitive
name; anything else is REJECTED with the closest spellings
(difflib.get_close_matches), the show console's own rule. Every write reply
carries a `summary` sentence saying plainly what changed.

EVERY EDIT GOES THROUGH THE MODEL'S OWN VALIDATION (HouseMode(**...)) and
house_store.put_mode — the same save the House page's POST makes — so a
Sonic edit can never be a shape the page could not have saved.
"""
from __future__ import annotations

import difflib
from typing import Any, Optional

from pydantic import ValidationError

from spectra.models.house_mode import (ColorPick, FixtureHook, HouseMode, HouseTarget,
                                       HueLook, ScenePick)
from spectra.services import house, house_store
from spectra.services.sonic_ops import SonicOperation

MUSIC_CHOICES = ("show", "calm", "ignore")
MUSIC_HUE_CHOICES = ("hold", "join", "room")
TARGET_KIND_CHOICES = ("everything", "category", "fixture")
HUE_LOOK_CHOICES = ("hold", "off", "show", "remove")
POOL_CHOICES = ("scenes", "color_sets")

#: key -> (dotted path in HouseMode, kind). Bounds come from the model.
MODE_SETTINGS: dict[str, tuple[str, str]] = {
    "name": ("name", "text"),
    "notes": ("notes", "text"),
    "ha_aliases": ("ha_aliases", "list"),
    "music": ("music", "enum"),
    "music_hue": ("music_hue", "enum"),
    "scene_every_min": ("flow.scene_every_min", "number"),
    "journey_deg_per_min": ("flow.journey_deg_per_min", "number"),
    "intensity": ("flow.intensity", "number"),
    "clock_glide_s": ("transitions.clock_glide_s", "number"),
    "button_glide_s": ("transitions.button_glide_s", "number"),
    "music_debounce_s": ("transitions.music_debounce_s", "number"),
    "music_return_glide_s": ("transitions.music_return_glide_s", "number"),
}


def _close(name: str, candidates: list[str]) -> list[str]:
    return difflib.get_close_matches(name or "", candidates, n=3, cutoff=0.4)


def _reject(reason: str, **extra) -> dict:
    return {"status": "rejected", "reason": reason, **extra}


def _resolve_mode(name_or_id: str):
    m = house_store.find_mode(name_or_id or "")
    if m is not None:
        return m, None
    names = [x.name for x in house_store.list_modes()]
    return None, _reject(f"no house mode called {name_or_id!r}",
                         close_matches=_close(name_or_id, names), known_modes=names)


def _by_name(items: list[tuple[str, str]], wanted: str, what: str):
    """items: (id, name). Exact id, then case-insensitive name."""
    hit = next((i for i, _n in items if i == wanted), None)
    if hit is not None:
        return hit, None
    low = (wanted or "").strip().lower()
    hit = next((i for i, n in items if (n or "").strip().lower() == low), None)
    if hit is not None:
        return hit, None
    names = [n for _i, n in items]
    return None, _reject(f"no {what} called {wanted!r}",
                         close_matches=_close(wanted, names))


def _save(mode: HouseMode, data: dict) -> tuple[Optional[HouseMode], Optional[dict]]:
    try:
        new = HouseMode(**data)
    except ValidationError as exc:
        return None, _reject("; ".join(f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}"
                                       for e in exc.errors()))
    try:
        return house_store.put_mode(new), None
    except house_store.ModeConflict as exc:
        return None, _reject(str(exc))


def _summary_of(m: HouseMode) -> dict:
    from spectra.services import color_sets, scene_store
    scenes = []
    for p in m.scenes:
        s = scene_store.get_by_id(p.scene_id)
        scenes.append({"name": s.name if s else p.scene_id, "weight": p.weight})
    cards = []
    for p in m.color_sets:
        c = color_sets.get_by_id(p.card_id)
        cards.append({"name": c.name if c else p.card_id, "weight": p.weight})
    return {"id": m.id, "name": m.name, "ha_aliases": m.ha_aliases,
            "scenes": scenes, "color_sets": cards,
            "flow": m.flow.model_dump(), "transitions": m.transitions.model_dump(),
            "fixtures": [h.model_dump() for h in m.fixtures],
            "hue": [lk.model_dump() for lk in m.hue],
            "music": m.music, "music_hue": m.music_hue}


# ── handlers ───────────────────────────────────────────────────────────────

def _op_house_status() -> dict:
    return house.status_dict()


def _op_list_house_modes() -> dict:
    return {"modes": [_summary_of(m) for m in house_store.list_modes()],
            "current": (house.current_mode().name if house.current_mode() else None)}


async def _op_set_house_mode(mode: str) -> dict:
    if (mode or "").strip().lower() in ("", "none", "off", "clear"):
        res = await house.set_mode(clear=True, source="sonic")
        return {"status": "applied", "lighting": res["lighting"],
                "summary": "cleared the house mode — it holds until Home "
                           "Assistant's lighting mode next changes"}
    target, err = _resolve_mode(mode)
    if err:
        return err
    res = await house.set_mode(mode=target.id, source="sonic")
    word = "already in" if res["status"] == "unchanged" else "switched to"
    return {"status": "applied", "lighting": res["lighting"],
            "summary": f"{word} {target.name} — it holds until Home Assistant's "
                       f"lighting mode next changes"}


def _op_create_house_mode(name: str, ha_aliases: Optional[list[str]] = None) -> dict:
    try:
        new = HouseMode(name=name, ha_aliases=list(ha_aliases or []))
    except ValidationError as exc:
        return _reject(str(exc.errors()[0]["msg"]))
    try:
        saved = house_store.put_mode(new)
    except house_store.ModeConflict as exc:
        return _reject(str(exc))
    return {"status": "applied", "mode_id": saved.id,
            "summary": f"created the house mode {saved.name!r} (empty — add "
                       f"scenes, colours and fixture settings to give it a look)"}


async def _after_edit(saved: HouseMode) -> None:
    if saved.id == house_store.state().mode_id:
        await house.tick()


async def _op_set_house_mode_setting(mode: str, key: str, value: Any) -> dict:
    target, err = _resolve_mode(mode)
    if err:
        return err
    if key not in MODE_SETTINGS:
        return _reject(f"{key!r} is not a house-mode setting",
                       known_settings=sorted(MODE_SETTINGS))
    path, _kind = MODE_SETTINGS[key]
    data = target.model_dump()
    node = data
    parts = path.split(".")
    for p in parts[:-1]:
        node = node[p]
    before = node[parts[-1]]
    node[parts[-1]] = value
    saved, err = _save(target, data)
    if err:
        return err
    await _after_edit(saved)
    return {"status": "applied", "before": before, "after": value,
            "summary": f"{saved.name}: {key} {before!r} → {value!r}"}


def _resolve_target(kind: str, name: Optional[str]):
    if kind == "everything":
        return HouseTarget(kind="everything"), None
    if not name:
        return None, _reject(f"a {kind} target needs a name")
    if kind == "category":
        from fx import device_model
        cats = [c.get("name") for c in device_model.list_categories() if isinstance(c, dict)]
        hit, err = _by_name([(c, c) for c in cats], name, "category")
        return (HouseTarget(kind="category", id=hit), None) if hit else (None, err)
    from spectra.services import show_output
    targets = show_output.list_targets()
    if not targets.get("live"):
        return None, _reject("the live room is down, so a fixture name cannot be "
                             "checked — use a category, or try when SPECTRA holds the room")
    hit, err = _by_name([(f["id"], f["name"]) for f in targets["fixtures"]], name, "fixture")
    return (HouseTarget(kind="fixture", id=hit), None) if hit else (None, err)


async def _op_set_house_fixture(mode: str, target_kind: str = "everything",
                                target_name: Optional[str] = None,
                                level: Optional[float] = None,
                                motion: Optional[float] = None,
                                fps: Optional[int] = None, off: Optional[bool] = None,
                                remove: bool = False) -> dict:
    m, err = _resolve_mode(mode)
    if err:
        return err
    target, err = _resolve_target(target_kind, target_name)
    if err:
        return err
    hooks = [h.model_dump() for h in m.fixtures]
    key = target.model_dump()
    idx = next((i for i, h in enumerate(hooks) if h["target"] == key), None)
    label = target.id or "everything"
    if remove:
        if idx is None:
            return _reject(f"{m.name} has no fixture setting for {label}")
        hooks.pop(idx)
        summary = f"{m.name}: removed the fixture setting for {label}"
    else:
        hook = hooks[idx] if idx is not None else FixtureHook(target=target).model_dump()
        for field_name, v in (("level", level), ("motion", motion), ("fps", fps), ("off", off)):
            if v is not None:
                hook[field_name] = v
        if idx is None:
            hooks.append(hook)
        else:
            hooks[idx] = hook
        bits = [f"{k} {hook[k]}" for k in ("level", "motion", "fps") if hook.get(k) is not None]
        if hook.get("off"):
            bits.append("off")
        summary = f"{m.name}: {label} — " + (", ".join(bits) or "nothing set")
    data = m.model_dump()
    data["fixtures"] = hooks
    saved, err = _save(m, data)
    if err:
        return err
    await _after_edit(saved)
    return {"status": "applied", "summary": summary}


async def _resolve_area(area: str):
    if (area or "").strip().lower() in ("*", "every", "all", "everything", "every area"):
        return "*", None
    from spectra.services import ambient
    groups = await ambient.list_groups()
    if not groups:
        return None, _reject("no live Hue area to check that name against — use '*' "
                             "for every area, or try when SPECTRA holds the room")
    return _by_name([(g["id"], g["name"]) for g in groups], area, "Hue area")


async def _op_set_house_hue(mode: str, area: str = "*", look: str = "hold",
                            kelvin: Optional[int] = None, color: Optional[str] = None,
                            brightness: Optional[float] = None) -> dict:
    m, err = _resolve_mode(mode)
    if err:
        return err
    area_id, err = await _resolve_area(area)
    if err:
        return err
    looks = [lk.model_dump() for lk in m.hue if lk.area != area_id]
    if look == "remove":
        summary = f"{m.name}: Hue area {area_id} no longer has a look"
    else:
        entry = {"area": area_id, "look": look, "kelvin": kelvin, "color": color,
                 "brightness": brightness if brightness is not None else 100.0}
        try:
            HueLook(**entry)
        except ValidationError as exc:
            return _reject(exc.errors()[0]["msg"])
        looks.append(entry)
        what = (f"{kelvin} K" if kelvin else color or look)
        summary = f"{m.name}: Hue area {area_id} — {look} {what} at {entry['brightness']:g}%"
    data = m.model_dump()
    data["hue"] = looks
    saved, err = _save(m, data)
    if err:
        return err
    await _after_edit(saved)
    return {"status": "applied", "summary": summary}


async def _op_set_house_mode_pool(mode: str, pool: str, names: list[str],
                                  weights: Optional[list[float]] = None) -> dict:
    from spectra.services import color_sets, scene_store
    m, err = _resolve_mode(mode)
    if err:
        return err
    if pool not in POOL_CHOICES:
        return _reject(f"pool must be one of {list(POOL_CHOICES)}")
    if weights is not None and len(weights) != len(names):
        return _reject("give one weight per name, or none")
    if pool == "scenes":
        items = [(s.id, s.name) for s in scene_store.list_all()]
        what = "scene"
    else:
        items = [(c.id, c.name) for c in color_sets.list_all()]
        what = "colour set or group"
    picks = []
    for i, n in enumerate(names or []):
        hit, err = _by_name(items, n, what)
        if err:
            return err
        w = float(weights[i]) if weights is not None else 1.0
        picks.append(ScenePick(scene_id=hit, weight=w).model_dump() if pool == "scenes"
                     else ColorPick(card_id=hit, weight=w).model_dump())
    data = m.model_dump()
    data[pool] = picks
    saved, err = _save(m, data)
    if err:
        return err
    await _after_edit(saved)
    label = "scenes" if pool == "scenes" else "colours"
    return {"status": "applied",
            "summary": f"{m.name}: {label} — " + (", ".join(names) or "none")}


_EMPTY = {"type": "object", "properties": {}, "additionalProperties": False}

OPERATIONS: dict[str, SonicOperation] = {
    "house_status": SonicOperation(
        name="house_status", domain="house", kind="read",
        summary="Which house lighting mode is set, by whom, and what it is "
                "doing right now (resting, music, standby, or inactive and why).",
        instructions="Call this first for anything about the house modes. "
                    "`phase` inactive with a reason means nothing is applied — "
                    "usually because SPECTRA does not hold the room yet.",
        input_schema=_EMPTY, handler=_op_house_status),
    "list_house_modes": SonicOperation(
        name="list_house_modes", domain="house", kind="read",
        summary="His house lighting modes with their scenes, colours, fixture "
                "settings, Hue looks and music behaviour.",
        instructions="Use the exact mode names from here; never guess one.",
        input_schema=_EMPTY, handler=_op_list_house_modes),
    "set_house_mode": SonicOperation(
        name="set_house_mode", domain="house", kind="write",
        summary="Switch the house to a mode (or 'none' to clear it).",
        instructions="A pick by him: it holds until Home Assistant's lighting "
                    "mode next changes (HA's 5-minute re-assert of the same "
                    "value does not undo it). Applies only while SPECTRA holds "
                    "the room; otherwise it is recorded and applies on take-back.",
        input_schema={"type": "object",
                      "properties": {"mode": {"type": "string"}},
                      "required": ["mode"], "additionalProperties": False},
        handler=_op_set_house_mode),
    "create_house_mode": SonicOperation(
        name="create_house_mode", domain="house", kind="write",
        summary="Create a brand-new, empty house mode by name, optionally with "
                "the Home Assistant lighting_mode words it answers to.",
        instructions="Always a NEW mode with a fresh id; an existing name or "
                    "alias is rejected, never overwritten.",
        input_schema={"type": "object",
                      "properties": {"name": {"type": "string"},
                                     "ha_aliases": {"type": "array", "items": {"type": "string"}}},
                      "required": ["name"], "additionalProperties": False},
        handler=_op_create_house_mode),
    "set_house_mode_setting": SonicOperation(
        name="set_house_mode_setting", domain="house", kind="write",
        summary="Change one setting of a house mode: name, notes, ha_aliases, "
                "music, music_hue, scene_every_min, journey_deg_per_min, "
                "intensity, clock_glide_s, button_glide_s, music_debounce_s, "
                "music_return_glide_s.",
        instructions="music: show | calm | ignore. music_hue: hold | join | "
                    "room. Glides and the debounce are seconds; "
                    "journey_deg_per_min is the colour drift pace; intensity "
                    "is 0..1. Out-of-range values are rejected by the model.",
        input_schema={"type": "object",
                      "properties": {"mode": {"type": "string"},
                                     "key": {"type": "string", "enum": sorted(MODE_SETTINGS)},
                                     "value": {}},
                      "required": ["mode", "key", "value"], "additionalProperties": False},
        handler=_op_set_house_mode_setting),
    "set_house_fixture": SonicOperation(
        name="set_house_fixture", domain="house", kind="write",
        summary="Set a mode's per-fixture setting — brightness level (%), "
                "resting motion (0..1), frame-rate cap (fps) or off — for "
                "everything, a category, or one fixture. 'Make Evening's "
                "crystal 10%' is level 10 on the crystal's category or fixture.",
        instructions="Only the fields you pass change; remove=true deletes "
                    "that target's setting. motion 0 is the effect's slowest, "
                    "1 its fastest. A fixture target needs the live room "
                    "(names are checked); a category never does.",
        input_schema={"type": "object",
                      "properties": {"mode": {"type": "string"},
                                     "target_kind": {"type": "string", "enum": list(TARGET_KIND_CHOICES)},
                                     "target_name": {"type": "string"},
                                     "level": {"type": "number", "minimum": 0, "maximum": 200},
                                     "motion": {"type": "number", "minimum": 0, "maximum": 1},
                                     "fps": {"type": "integer", "minimum": 1, "maximum": 60},
                                     "off": {"type": "boolean"},
                                     "remove": {"type": "boolean"}},
                      "required": ["mode"], "additionalProperties": False},
        handler=_op_set_house_fixture),
    "set_house_hue": SonicOperation(
        name="set_house_hue", domain="house", kind="write",
        summary="Set how one Hue area (or '*' for every area) is held in a "
                "mode: a colour temperature in kelvin or a colour, at a "
                "brightness; or off; or 'show' (follow the stream); or "
                "'remove'.",
        instructions="look: hold | off | show | remove. For hold give kelvin "
                    "(2000-6500) OR color (#rrggbb), not both. Held over the "
                    "bridge, never streamed.",
        input_schema={"type": "object",
                      "properties": {"mode": {"type": "string"},
                                     "area": {"type": "string"},
                                     "look": {"type": "string", "enum": list(HUE_LOOK_CHOICES)},
                                     "kelvin": {"type": "integer", "minimum": 2000, "maximum": 6500},
                                     "color": {"type": "string"},
                                     "brightness": {"type": "number", "minimum": 1, "maximum": 100}},
                      "required": ["mode"], "additionalProperties": False},
        handler=_op_set_house_hue),
    "set_house_mode_pool": SonicOperation(
        name="set_house_mode_pool", domain="house", kind="write",
        summary="Replace a mode's scene pool or colour pool with named "
                "scenes / colour sets or groups (optionally weighted).",
        instructions="pool: scenes | color_sets. names are exact names; an "
                    "unknown one is rejected with close matches. weights, if "
                    "given, is one number per name.",
        input_schema={"type": "object",
                      "properties": {"mode": {"type": "string"},
                                     "pool": {"type": "string", "enum": list(POOL_CHOICES)},
                                     "names": {"type": "array", "items": {"type": "string"}},
                                     "weights": {"type": "array", "items": {"type": "number"}}},
                      "required": ["mode", "pool", "names"], "additionalProperties": False},
        handler=_op_set_house_mode_pool),
}
