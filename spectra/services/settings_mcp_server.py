"""Sonic's MCP TOOL SURFACE for the "cli" (subscription) settings-agent
backend (spectra/services/settings_agent_cli.py) -- a stdio MCP server
exposing EXACTLY the operations declared in settings_agent.ALL_OPERATIONS
(settings_console.OPERATIONS + scene_console.OPERATIONS + the
list_operations meta-tool -- widened 2026-08-15 to cover Sonic's scene/
flare authority alongside the original five settings), dispatching every
one of them to settings_agent._dispatch(), the SAME exhaustive
name -> operation lookup the Anthropic-API backend's tool loop already
uses (settings_agent.py's own docstring: "There is no third source of
tool names"). This file adds no authority of its own -- it is a wire
adapter from MCP's stdio protocol onto that one, already-proven dispatch
function, so a CLI-driven agent and an API-driven agent can never diverge
in what either is allowed to do.

Spawned as a SUBPROCESS by `claude -p` itself (see settings_agent_cli.py's
_mcp_config_json(), which names this module by its `python -m` path in
the inline --mcp-config it builds) -- never imported into the main
FastAPI process. Its only job is to exist as a standalone entry point:

    python -m spectra.services.settings_mcp_server

CWD-INDEPENDENT ON PURPOSE (live production defect, 2026-08-15, found by
firstmate: `claude -p` runs with its cwd set to settings_agent_cli.py's
dedicated clean workdir -- see that module's docstring for why that
directory must stay empty -- and does NOT honour the per-server `cwd`
this module's --mcp-config entry used to declare; the subprocess it spawns
inherits the PARENT `claude` process's cwd instead. `python -m` resolves
imports off the CURRENT WORKING DIRECTORY, not this file's own location,
so `import spectra` silently failed with the server launched from that
clean workdir -- reproduced by hand: `python -m
spectra.services.settings_mcp_server` succeeds from the repo root and
raises `ModuleNotFoundError: No module named 'spectra'` from the clean
workdir. The fix is entirely LOCAL to this file -- the two lines below
insert this file's own resolved repo root into sys.path before importing
spectra, so the module works regardless of the spawning process's cwd,
regardless of whether any --mcp-config field the CLI does or doesn't
honour changes in a future version, and regardless of `-m` vs. a direct
script path. This does NOT touch, weaken, or route around the clean
workdir requirement itself: that directory governs the `claude` PROCESS's
OWN cwd, used only for ITS auto-discovery of a project's
`.claude/settings.json` hooks and `.mcp.json`/`CLAUDE.md` (the actual
hole `_workdir()` guards) -- a completely different mechanism from this
file's own sys.path, which affects nothing outside this one Python
process's own import resolution.

Every tool function below is a thin, HAND-WRITTEN wrapper -- one per
settings_agent.ALL_OPERATIONS entry -- because the `mcp` package's
add_tool() builds its JSON schema by introspecting a real Python function
signature (no programmatic "register from a dict" path), so the dynamic,
data-driven declaration sonic_ops.SonicOperation gives the API backend
can't be replayed here without synthesizing function objects at runtime --
a fragility not worth taking on for a backend that is itself dark, default
OFF, and not yet authorised against his real account (see settings_agent_
cli.py's module docstring). `test_settings_mcp_server_starts_from_a_clean_
cwd` (tests/test_settings_agent_cli.py) asserts this file's registered
tool NAMES equal set(settings_agent.ALL_OPERATIONS) exactly -- forgetting
to add a wrapper here fails that test (and, in production, fails
_verify_tool_manifest()'s live manifest check, refusing the whole turn
rather than silently under-exposing a capability).

Every `key`/`type`/`jump` parameter below is typed as a Literal built from
the real registry (settings_console.SETTINGS_REGISTRY /
scene_console.SCENE_SETTINGS_REGISTRY) or the real pydantic model
(FlareKind) at import time, not re-typed by hand -- the same enum
constraint the Anthropic-API path's JSON schemas declare (also read from
those same registries), kept in sync automatically because both read the
one source rather than each other. The enum is defense-in-depth only:
settings_agent._dispatch() / settings_console.apply_change() /
scene_console's apply_* functions re-validate every key/value server-side
regardless of what any schema advertised, exactly as they do for the API
backend -- see data/spectra-console-subscription-backend/report.md for
the live re-proof (out-of-range, unknown-key, and malformed-type all
rejected through this exact path, with a JSON tool schema that
deliberately omitted the enum, to prove the mechanism -- not client-side
schema policing -- is what refuses)."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Literal, Optional

# Must run before the `spectra.services` import below -- see module
# docstring's "CWD-INDEPENDENT ON PURPOSE" section. This file lives at
# <repo_root>/spectra/services/settings_mcp_server.py, so its own resolved
# path (never the process's cwd) is what locates the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from mcp.server import MCPServer  # noqa: E402

from spectra.services import (  # noqa: E402
    device_console,
    room_effect_console,
    scene_console,
    settings_agent,
    settings_console,
)
from fx import device_schema  # noqa: E402

_KeyEnum = Literal[tuple(sorted(settings_console.SETTINGS_REGISTRY))]
_SceneKeyEnum = Literal[tuple(sorted(scene_console.SCENE_SETTINGS_REGISTRY))]
_FlareTypeEnum = Literal["drift_jump", "momentary", "permanent"]
_JumpEnum = Literal["color_set", "dice"]
_DeviceTypeEnum = Literal[tuple(device_schema.device_types())]
_RoomEffectKeyEnum = Literal[tuple(list(room_effect_console.KNOBS)
                                   + ["name", "device_ids"])]

mcp = MCPServer("settings-console")


async def _call(op_name: str, /, **kwargs: Any) -> dict:
    """`op_name` is POSITIONAL-ONLY (the `/` marker) -- LIVE PRODUCTION
    DEFECT, found 2026-08-15 running the adversarial set against the real
    model on the deployed CLI backend: every wrapper below whose own tool
    happens to have a parameter also called `name` (create_scene,
    get_flare_kind, set_flare_kind, remove_flare_kind, overwrite_scene,
    list_operations) called `_call("op", name=name, ...)` -- and because
    this function's own first parameter used to be a plain keyword-or-
    positional `name: str`, that keyword `name=` collided with it:
    `_call() got multiple values for argument 'name'`, TypeError, on
    every single call to any of those six tools. Caught live because the
    real Sonnet model, given the real broken tool, reported the failure
    HONESTLY instead of fabricating success (see tests/
    test_settings_agent_cli.py::test_settings_mcp_server_actually_invokes_
    every_tool_without_a_python_level_argument_error) -- the offline
    proof (test_settings_mcp_server_starts_from_a_clean_cwd) only ever
    listed tool schemas over MCP, never actually INVOKED a wrapped
    function with real arguments, so this whole class of bug had no
    offline coverage until now. `/` makes this the LAST time a future
    tool's own kwarg name can collide with this dispatcher's own argument
    name, whatever that kwarg is called -- not just a fix for `name`."""
    return await settings_agent._dispatch(op_name, kwargs)


@mcp.tool()
async def list_operations(domain: Optional[str] = None, name: Optional[str] = None) -> dict:
    """Discover what Sonic can currently do -- every declared operation
    across every domain (settings, scene, device), or full detail for one named
    operation. Call first if unsure what's available or how to call it."""
    return await _call("list_operations", domain=domain, name=name)


@mcp.tool()
async def get_settings() -> dict:
    """Read every settings-console setting's current value, type, unit, and legal range/choices."""
    return await _call("get_settings")


@mcp.tool()
async def set_setting(key: _KeyEnum, value: Any) -> dict:
    """Change ONE declared room-wide setting. The server validates the key
    and value against its declared range/choices server-side and rejects
    anything outside them -- this is the only way this agent can change
    anything."""
    return await _call("set_setting", key=key, value=value)


@mcp.tool()
async def list_scenes() -> dict:
    """List every scene's id, name, and labels -- never the full scene."""
    return await _call("list_scenes")


@mcp.tool()
async def get_scene_settings(scene_id: str) -> dict:
    """Read one scene's settable settings with their current values and legal ranges."""
    return await _call("get_scene_settings", scene_id=scene_id)


@mcp.tool()
async def list_flare_kinds(scene_id: str) -> dict:
    """List a scene's named flare kinds (summary only, not full parameter detail)."""
    return await _call("list_flare_kinds", scene_id=scene_id)


@mcp.tool()
async def get_flare_kind(scene_id: str, name: str) -> dict:
    """Read one named flare kind's full definition on one scene."""
    return await _call("get_flare_kind", scene_id=scene_id, name=name)


@mcp.tool()
async def list_scene_params(scene_id: str) -> dict:
    """List the parameter NAMES available on one scene's devices, grouped
    by effect -- cheap, names only, no detail."""
    return await _call("list_scene_params", scene_id=scene_id)


@mcp.tool()
async def get_param_info(effect_type: str, name: str) -> dict:
    """Full detail for ONE named parameter on ONE effect: what it does,
    its type, and its legal range -- read live from the real effect
    definition."""
    return await _call("get_param_info", effect_type=effect_type, name=name)


@mcp.tool()
async def create_scene(name: str, labels: Optional[list[str]] = None) -> dict:
    """Create a new, empty scene shell with a name -- always a fresh id,
    can never overwrite an existing scene."""
    return await _call("create_scene", name=name, labels=labels)


@mcp.tool()
async def set_scene_setting(scene_id: str, key: _SceneKeyEnum, value: Any) -> dict:
    """Change ONE declared setting on ONE existing scene. The server
    re-validates the key and value against that scene's own declared
    range and rejects anything outside them."""
    return await _call("set_scene_setting", scene_id=scene_id, key=key, value=value)


@mcp.tool()
async def set_flare_kind(scene_id: str, name: str, type: _FlareTypeEnum,  # noqa: A002
                         jump: Optional[_JumpEnum] = None,
                         params: Optional[dict] = None, gain: float = 1.0,
                         hold_ms: Optional[int] = None,
                         enabled: Optional[bool] = None) -> dict:
    """Create or update one NAMED flare kind on one scene, matched by name.
    enabled=false disables it (never fires automatically); omit to leave
    the current setting alone."""
    return await _call("set_flare_kind", scene_id=scene_id, name=name, type=type,
                       jump=jump, params=params, gain=gain, hold_ms=hold_ms,
                       enabled=enabled)


@mcp.tool()
async def remove_flare_kind(scene_id: str, name: str) -> dict:
    """Remove one named flare kind from one scene. Refused if still referenced."""
    return await _call("remove_flare_kind", scene_id=scene_id, name=name)


@mcp.tool()
async def overwrite_scene(scene_id: str, name: Optional[str] = None,
                          labels: Optional[list[str]] = None,
                          settings: Optional[dict] = None,
                          flare_kinds: Optional[list[dict]] = None) -> dict:
    """Wholesale-replace an EXISTING scene's name/labels/settings/
    flare_kinds in one shot -- always backed up (and the backup verified)
    before anything is written; refuses if the backup can't be confirmed."""
    return await _call("overwrite_scene", scene_id=scene_id, name=name, labels=labels,
                       settings=settings, flare_kinds=flare_kinds)


@mcp.tool()
async def list_scene_backups(scene_id: str) -> dict:
    """List one scene's available restore points: the last 10 edits plus
    the permanent pre-Sonic genesis snapshot."""
    return await _call("list_scene_backups", scene_id=scene_id)


@mcp.tool()
async def get_scene_preview(scene_id: str) -> dict:
    """What actually changed on one scene since its last backup -- read
    from the stored scene and its stored backup, never from memory."""
    return await _call("get_scene_preview", scene_id=scene_id)


@mcp.tool()
async def restore_scene_backup(scene_id: str, backup_id: str) -> dict:
    """Restore one scene to a specific earlier point -- any entry from
    list_scene_backups, or "genesis" for the permanent pre-Sonic snapshot."""
    return await _call("restore_scene_backup", scene_id=scene_id, backup_id=backup_id)


@mcp.tool()
async def undo_last_scene_change() -> dict:
    """Undo the single most recent scene edit Sonic made, across any
    scene -- one action, no scene_id needed."""
    return await _call("undo_last_scene_change")


@mcp.tool()
async def list_devices() -> dict:
    """Every device in the room -- type, full config, the virtuals it
    renders, their groupings, and its timing offset. `source` says whether
    the room is running ('live', edits reach the fixtures now) or not
    ('stored', edits land at the next activation)."""
    return await _call("list_devices")


@mcp.tool()
async def get_device_params(device_type: _DeviceTypeEnum) -> dict:
    """The full tunable parameter list for one device TYPE, read off the
    driver's own schema -- kind, required, default, bounds/choices and the
    driver's own description for each."""
    return await _call("get_device_params", device_type=device_type)


@mcp.tool()
async def create_device(type: _DeviceTypeEnum, config: dict) -> dict:  # noqa: A002
    """Create a new device (and the virtual that renders onto it). Call
    get_device_params first and supply every required field; the server
    re-validates against the driver's own schema."""
    return await _call("create_device", type=type, config=config)


@mcp.tool()
async def update_device(device_id: str, config: dict) -> dict:
    """Change one or more config values on one existing device. config is a
    PARTIAL patch -- only the keys named change."""
    return await _call("update_device", device_id=device_id, config=config)


@mcp.tool()
async def rename_device(device_id: str, name: str) -> dict:
    """Rename one device (its friendly name). Its id, virtuals and
    groupings are untouched."""
    return await _call("rename_device", device_id=device_id, name=name)


@mcp.tool()
async def set_device_timing_offset(device_id: str, timing_offset_ms: int) -> dict:
    """Set one device's timing offset in milliseconds. NEGATIVE MEANS IT
    FIRES EARLIER, positive later, 0 unchanged. Only differences between
    devices matter -- this can never move the room as a whole."""
    return await _call("set_device_timing_offset", device_id=device_id,
                       timing_offset_ms=timing_offset_ms)


@mcp.tool()
async def set_device_categories(virtual_id: str, categories: list[str]) -> dict:
    """Set exactly which groupings one VIRTUAL belongs to. Pass the complete
    list; anything omitted is removed. Every name must already exist."""
    return await _call("set_device_categories", virtual_id=virtual_id,
                       categories=categories)


# ── room light-field effects ──────────────────────────────────────────────
# The settable fields of the Room Effects page and nothing else: starting or
# stopping an effect drives his fixtures and holds the room, and running a
# mapping sync needs a phone camera — both excluded by name, see
# spectra/services/room_effect_console.py's docstring.


@mcp.tool()
async def list_rooms() -> dict:
    """Every mapped room -- its fixtures, which of them have a MEASURED light
    footprint, and how much light each one lands. A device in `not_mapped`
    cannot be driven by a room effect until it is mapped, which needs a phone
    camera on the Rooms page."""
    return await _call("list_rooms")


@mcp.tool()
async def list_room_effects() -> dict:
    """Every authored room effect with its knobs' real bounds and units.
    Only 'dim_wave' is built; the other field kinds cannot be created."""
    return await _call("list_room_effects")


@mcp.tool()
async def create_room_effect(room_id: str, name: Optional[str] = None) -> dict:
    """Create a Dim Wave on a room. Always a NEW effect with a fresh id, so
    it can never overwrite an existing one. Does not start it."""
    return await _call("create_room_effect", room_id=room_id, name=name)


@mcp.tool()
async def set_room_effect(effect_id: str, key: _RoomEffectKeyEnum, value: Any) -> dict:
    """Set one field of a room effect: wavelength (axis units, 1.0 = one full
    cycle floor to ceiling), speed (cycles/second, positive travels toward the
    ceiling), depth (how far the trough dips, 0 is an exact no-op), name, or
    device_ids (only fixtures that room has MAPPED; empty means all of them)."""
    return await _call("set_room_effect", effect_id=effect_id, key=key, value=value)


if __name__ == "__main__":
    mcp.run(transport="stdio")
