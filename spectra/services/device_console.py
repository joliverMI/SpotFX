"""THE DEVICE DOMAIN — reading, creating and editing devices, their
groupings and their names, plus SPECTRA's own per-device settings.

His two asks, verbatim: "We need a device edit page to edit and create
devices. It should include all the parameters that were tunable in ledfx on
one tab, as well as the groupings and namings", and (the field the page
exists to expose) "maybe each device needs a timing offset (stick with the
convention that negative is that it fires earlier)".

THE PARAMETER SET IS READ OFF THE REAL VALIDATOR, never a hand-kept list:
fx/device_schema.py introspects each vendored driver's own merged
CONFIG_SCHEMA — the exact voluptuous schema Device.update_config validates
against — so the page cannot drift from what the driver will accept. Six
types (wled, hue, e131, ddp, udp, dummy); LedFX's other thirteen are not
vendored here and are not offered, because a config naming one is skipped
by the device registry at host start.

TWO WRITE BRANCHES, MUTUALLY EXCLUSIVE BY CONSTRUCTION — never a second
write path racing the first:

  LIVE   SPECTRA owns the lights and the live stack is up. Every write goes
         through fx.facade (the same in-process transport fx_seam routes to
         when SPECTRA owns), which runs the vendored create/update_config
         and then the vendored save_config into storage/spectra/fx-live —
         so the edit reaches the running device AND the file in one call,
         and the room follows immediately.
  STORED The stack is down (SPECTRA does not own, or has not been handed
         the room). There is no host to reach, and nothing else is writing
         that file, so the edit is validated against the SAME vendored
         schema and written into storage/spectra/fx-live/config.json
         atomically — the file the go-day seeder (scripts/
         seed_spectra_fx_live.py) owns and the next activation reads.

Both branches STATE which one ran (`applied`: "live" | "stored"), so an
edit made while the room is dark is never silently lost and never silently
claimed to have reached a fixture. A device edit is never dropped.

TIMING is a third thing again: `timing_offset_ms` is SPECTRA's own record
(spectra/services/device_settings.py), not a vendored device config key. It
is written and pushed into the render pipeline whether the stack is up or
not — pushing is a dict swap — and takes effect on the next rendered frame
with nothing to restart.

GROUPINGS are the shared category registry (fx/device_model, backed by
storage/device_categories.json), which maps a CATEGORY to VIRTUAL ids. A
device's grouping is therefore its virtuals' membership, edited here in
place. The registry is read fresh on every write (no in-memory cache on
either side of the process split) and written atomically.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from typing import Any, Optional

from fx import device_model, device_schema
from spectra.models.device_settings import OFFSET_LIMIT_MS, DeviceSettings
from spectra.services import device_settings
from spectra.services.sonic_ops import SonicOperation

logger = logging.getLogger(__name__)


class DeviceOpError(Exception):
    """A refusal with a reason, in the shape Sonic's dispatcher expects and
    the API turns into a 400. Never raised past the operation handlers."""

    def __init__(self, reason: str, **extra: Any) -> None:
        super().__init__(reason)
        self.reason = reason
        self.extra = extra

    def as_rejection(self) -> dict:
        return {"status": "rejected", "reason": self.reason, **self.extra}


# ── where the fx config lives, in both branches ─────────────────────────────

def _live_host():
    """The running FxHost, or None. SPECTRA owning the record is not enough
    — the stack has to actually be up."""
    try:
        from fx import light_ownership
        from spectra.services.live_host import live
    except Exception:                                      # pragma: no cover
        return None
    if light_ownership.load().owner != light_ownership.SPECTRA:
        return None
    return getattr(live, "host", None)


def _config_path():
    from spectra import config as scfg
    return scfg.FX_LIVE_CONFIG_DIR / "config.json"


def _read_stored_config() -> dict:
    path = _config_path()
    if not path.exists():
        return {"devices": [], "virtuals": []}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise DeviceOpError(f"the fx-live config could not be read: {exc}")
    raw.setdefault("devices", [])
    raw.setdefault("virtuals", [])
    return raw


def _write_stored_config(raw: dict) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(raw, fh, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ── groupings (the shared category registry) ────────────────────────────────

def _categories_raw() -> dict:
    path = device_model.CATEGORIES_FILE
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise DeviceOpError(f"the category registry could not be read: {exc}")


def _write_categories(raw: dict) -> None:
    path = device_model.CATEGORIES_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(raw, fh, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    device_model.refresh()


def category_names() -> list[str]:
    return sorted(c.get("name", "") for c in device_model.list_categories()
                  if c.get("name"))


def categories_for_virtual(virtual_id: str) -> list[str]:
    return sorted(c.get("name", "") for c in device_model.list_categories()
                  if virtual_id in (c.get("virtuals") or []))


def set_virtual_categories(virtual_id: str, names: list[str]) -> dict:
    """Set exactly which categories this virtual belongs to. Every named
    category must already exist — creating categories is a different job
    (the category editor), and inventing one here from a typo would put a
    virtual somewhere nothing ever looks."""
    raw = _categories_raw()
    known = {c.get("name"): cid for cid, c in raw.items()}
    wanted = list(dict.fromkeys(names or []))
    unknown = [n for n in wanted if n not in known]
    if unknown:
        raise DeviceOpError(
            f"unknown categor{'y' if len(unknown) == 1 else 'ies'}: "
            f"{', '.join(sorted(unknown))}",
            known_categories=sorted(n for n in known if n))
    for cid, cat in raw.items():
        virtuals = list(cat.get("virtuals") or [])
        should = cat.get("name") in wanted
        has = virtual_id in virtuals
        if should and not has:
            virtuals.append(virtual_id)
        elif has and not should:
            virtuals = [v for v in virtuals if v != virtual_id]
        else:
            continue
        cat["virtuals"] = virtuals
        raw[cid] = cat
    _write_categories(raw)
    return {"status": "applied", "virtual_id": virtual_id,
            "categories": categories_for_virtual(virtual_id),
            "summary": f"{virtual_id} is now in "
                       f"{', '.join(wanted) if wanted else 'no category'}"}


# ── reading devices ─────────────────────────────────────────────────────────

def _virtual_ids_for(device_id: str, virtuals: list[dict]) -> list[str]:
    out = []
    for v in virtuals:
        segments = v.get("segments") or []
        if any(seg and seg[0] == device_id for seg in segments):
            out.append(v.get("id"))
    return sorted(x for x in out if x)


def _decorate(entry: dict, settings: dict[str, DeviceSettings]) -> dict:
    record = settings.get(entry["id"]) or DeviceSettings()
    entry = dict(entry)
    entry["name"] = (entry.get("config") or {}).get("name") or entry["id"]
    entry["timing_offset_ms"] = record.timing_offset_ms
    entry["categories"] = {vid: categories_for_virtual(vid)
                           for vid in entry.get("virtuals") or []}
    return entry


async def list_devices() -> dict:
    """Every device, from the LIVE host when the stack is up and from the
    stored fx-live config when it is not — with its type, its full config,
    the virtuals its segments back, their category membership, and its
    SPECTRA timing offset. `source` says which branch answered, so the page
    can say plainly whether it is looking at a running room."""
    settings = device_settings.load_all()
    host = _live_host()
    if host is not None:
        from fx import facade
        resp = await facade.handle("GET", "/api/devices")
        if resp.status_code == 200:
            devices = resp.json().get("devices") or {}
            return {"source": "live",
                    "devices": [_decorate(d, settings)
                                for d in sorted(devices.values(),
                                                key=lambda d: d["id"])],
                    **_catalogue()}
        logger.warning("device console: live device read failed (%s) — "
                       "falling back to the stored config", resp.status_code)
    raw = _read_stored_config()
    virtuals = raw.get("virtuals") or []
    entries = [
        {"id": d.get("id"), "type": d.get("type"),
         "config": dict(d.get("config") or {}), "online": None, "active": None,
         "virtuals": _virtual_ids_for(d.get("id"), virtuals)}
        for d in raw.get("devices") or [] if d.get("id")
    ]
    return {"source": "stored",
            "devices": [_decorate(e, settings)
                        for e in sorted(entries, key=lambda e: e["id"])],
            **_catalogue()}


def _catalogue() -> dict:
    from fx import device_timing
    return {
        "types": device_schema.device_types(),
        "fields": device_schema.all_fields(),
        "category_names": category_names(),
        "timing": {
            "offset_limit_ms": OFFSET_LIMIT_MS,
            "convention": "Negative fires this device EARLIER than the rest "
                          "of the room, positive later, 0 unchanged. Only "
                          "differences between devices matter.",
            "applied_delay_ms": device_timing.delays_ms(),
        },
    }


# ── writing devices ─────────────────────────────────────────────────────────

def _validated(device_type: str, config: dict) -> dict:
    try:
        return device_schema.validate_config(device_type, config)
    except KeyError:
        raise DeviceOpError(
            f"unknown device type {device_type!r}",
            known_types=device_schema.device_types())
    except Exception as exc:
        raise DeviceOpError(f"device config rejected by the driver's own "
                            f"schema: {exc}")


async def create_device(device_type: str, config: dict) -> dict:
    """Create a device (and the virtual that renders onto it). Live: the
    vendored Devices.add_new_device, the same call the fork's own create
    endpoint makes. Stored: the same validated entry appended to the
    fx-live config, with the matching span virtual, so the next activation
    brings it up."""
    if device_type not in device_schema.device_types():
        raise DeviceOpError(f"unknown device type {device_type!r}",
                            known_types=device_schema.device_types())
    name = (config or {}).get("name")
    if not name:
        raise DeviceOpError("a device needs a name")
    host = _live_host()
    if host is not None:
        from fx import facade
        resp = await facade.handle("POST", "/api/devices",
                                   json={"type": device_type, "config": dict(config)})
        if resp.status_code != 200:
            raise DeviceOpError(_reason(resp))
        device = resp.json().get("device") or {}
        return {"status": "applied", "applied": "live", "device": device,
                "summary": f"created {device.get('id')} ({device_type}) on the "
                           f"running room"}

    validated = _validated(device_type, config)
    raw = _read_stored_config()
    from fx.utils import generate_id
    device_id = generate_id(str(name))
    existing = {d.get("id") for d in raw["devices"]}
    if device_id in existing:
        raise DeviceOpError(f"a device named {name!r} already exists "
                            f"(id {device_id})")
    raw["devices"].append({"id": device_id, "type": device_type,
                           "config": dict(validated)})
    pixel_count = int(validated.get("pixel_count") or 1)
    raw["virtuals"].append({
        "id": device_id, "is_device": device_id, "auto_generated": False,
        "config": {"name": str(name),
                   "icon_name": validated.get("icon_name", "mdi:led-strip"),
                   "mapping": "span", "rows": 1},
        "segments": [[device_id, 0, max(0, pixel_count - 1), False]],
    })
    _write_stored_config(raw)
    return {"status": "applied", "applied": "stored", "device_id": device_id,
            "summary": f"created {device_id} ({device_type}) in the stored "
                       f"fx-live config — it comes up at the next activation, "
                       f"the room is not running right now"}


def _reason(resp) -> str:
    try:
        body = resp.json()
    except Exception:
        return f"the live host refused the write (HTTP {resp.status_code})"
    return ((body.get("payload") or {}).get("reason")
            or body.get("reason") or f"HTTP {resp.status_code}")


async def update_device(device_id: str, config: dict) -> dict:
    """Merge a partial config into one device. Live: the vendored
    update_config (which revalidates, re-segments its virtuals and
    re-activates them) plus the vendored save_config. Stored: the merged
    config revalidated against the same schema and written back."""
    if not isinstance(config, dict) or not config:
        raise DeviceOpError("nothing to change")
    host = _live_host()
    if host is not None:
        from fx import facade
        resp = await facade.handle("PUT", f"/api/devices/{device_id}",
                                   json={"config": dict(config)})
        if resp.status_code != 200:
            raise DeviceOpError(_reason(resp))
        return {"status": "applied", "applied": "live",
                "device": resp.json().get("device") or {},
                "summary": f"{device_id}: {', '.join(sorted(config))} updated "
                           f"on the running room"}

    raw = _read_stored_config()
    for entry in raw["devices"]:
        if entry.get("id") == device_id:
            merged = {**(entry.get("config") or {}), **config}
            entry["config"] = dict(_validated(entry.get("type"), merged))
            _write_stored_config(raw)
            return {"status": "applied", "applied": "stored",
                    "device_id": device_id, "config": entry["config"],
                    "summary": f"{device_id}: {', '.join(sorted(config))} "
                               f"written to the stored fx-live config — the "
                               f"room is not running right now, so it lands "
                               f"at the next activation"}
    raise DeviceOpError(f"no device {device_id!r}")


async def rename_device(device_id: str, name: str) -> dict:
    if not name or not str(name).strip():
        raise DeviceOpError("a device needs a name")
    return await update_device(device_id, {"name": str(name)})


def set_timing_offset_ms(device_id: str, value: int) -> dict:
    """His timing field. Written to SPECTRA's own per-device store and
    pushed into the render pipeline immediately — nothing to restart, and
    it works whether or not the stack is up (an offset with no host is
    simply inert until one exists)."""
    try:
        value = int(value)
    except (TypeError, ValueError):
        raise DeviceOpError(f"timing_offset_ms must be a whole number of "
                            f"milliseconds, got {value!r}")
    if not -OFFSET_LIMIT_MS <= value <= OFFSET_LIMIT_MS:
        raise DeviceOpError(f"timing_offset_ms must be between "
                            f"-{OFFSET_LIMIT_MS} and {OFFSET_LIMIT_MS} ms")
    device_settings.set_timing_offset_ms(device_id, value)
    from fx import device_timing
    direction = ("earlier than the rest of the room" if value < 0
                 else "later than the rest of the room" if value > 0
                 else "with the rest of the room")
    return {"status": "applied", "device_id": device_id,
            "timing_offset_ms": value,
            "applied_delay_ms": device_timing.delays_ms(),
            "summary": f"{device_id} now fires {abs(value)} ms {direction}"
                       if value else f"{device_id} now fires {direction}"}


# ── Sonic operations (the device domain) ────────────────────────────────────

def _guarded(fn):
    def run(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except DeviceOpError as exc:
            return exc.as_rejection()
    return run


def _guarded_async(fn):
    async def run(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except DeviceOpError as exc:
            return exc.as_rejection()
    return run


@_guarded_async
async def _op_list_devices() -> dict:
    return await list_devices()


@_guarded
def _op_get_device_params(device_type: str) -> dict:
    try:
        return {"type": device_type, "fields": device_schema.fields_for(device_type)}
    except KeyError:
        raise DeviceOpError(f"unknown device type {device_type!r}",
                            known_types=device_schema.device_types())


@_guarded_async
async def _op_create_device(type: str, config: dict) -> dict:  # noqa: A002
    return await create_device(type, config)


@_guarded_async
async def _op_update_device(device_id: str, config: dict) -> dict:
    return await update_device(device_id, config)


@_guarded_async
async def _op_rename_device(device_id: str, name: str) -> dict:
    return await rename_device(device_id, name)


@_guarded
def _op_set_device_timing_offset(device_id: str, timing_offset_ms: int) -> dict:
    return set_timing_offset_ms(device_id, timing_offset_ms)


@_guarded
def _op_set_device_categories(virtual_id: str, categories: list[str]) -> dict:
    return set_virtual_categories(virtual_id, categories)


OPERATIONS: dict[str, SonicOperation] = {
    "list_devices": SonicOperation(
        name="list_devices", domain="device", kind="read",
        summary="Every device in the room — type, full config, the virtuals "
                "it renders, their groupings, and its timing offset.",
        instructions=(
            "Call this first for anything device-related: it returns each "
            "device's id (what every other device operation takes), its "
            "current config values, the virtual ids its segments back, which "
            "categories those virtuals are in, and the complete parameter "
            "list for every device type. `source` is 'live' when the room is "
            "running (edits reach the fixtures immediately) or 'stored' when "
            "it is not (edits are written to the fx-live config and land at "
            "the next activation) — say which one when reporting back."),
        input_schema={"type": "object", "properties": {},
                      "additionalProperties": False},
        handler=_op_list_devices),
    "get_device_params": SonicOperation(
        name="get_device_params", domain="device", kind="read",
        summary="The full tunable parameter list for one device TYPE, read "
                "off the driver's own schema.",
        instructions=(
            "type is one of the six vendored types (wled, hue, e131, ddp, "
            "udp, dummy). Each field comes back with its kind, whether it is "
            "required, its default, its bounds or choices, and the driver's "
            "own description. This is read from the real validator, so a "
            "value it accepts here is a value the device will accept."),
        input_schema={
            "type": "object",
            "properties": {"device_type": {
                "type": "string", "enum": device_schema.device_types()}},
            "required": ["device_type"], "additionalProperties": False},
        handler=_op_get_device_params),
    "create_device": SonicOperation(
        name="create_device", domain="device", kind="write",
        summary="Create a new device (and the virtual that renders onto it).",
        instructions=(
            "Call get_device_params for the type first and supply at least "
            "every required field — the server re-validates against the "
            "driver's own schema and rejects anything it would not accept. "
            "With the room running this creates the device live; with the "
            "room down it is written to the stored fx-live config and comes "
            "up at the next activation. The result's `applied` field says "
            "which happened — report it, never assume 'live'."),
        input_schema={
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": device_schema.device_types()},
                "config": {"type": "object",
                           "description": "Config values for this device type; "
                                          "'name' is always required."},
            },
            "required": ["type", "config"], "additionalProperties": False},
        handler=_op_create_device),
    "update_device": SonicOperation(
        name="update_device", domain="device", kind="write",
        summary="Change one or more config values on one existing device.",
        instructions=(
            "config is a PARTIAL patch — only the keys you name change; "
            "everything else is left exactly as it was. Keys must be ones "
            "get_device_params lists for that device's type. Same live/"
            "stored behaviour and the same `applied` field as create_device."),
        input_schema={
            "type": "object",
            "properties": {"device_id": {"type": "string"},
                           "config": {"type": "object"}},
            "required": ["device_id", "config"], "additionalProperties": False},
        handler=_op_update_device),
    "rename_device": SonicOperation(
        name="rename_device", domain="device", kind="write",
        summary="Rename one device (its friendly name, the 'name' config key).",
        instructions=(
            "This changes the device's display name only — its id, its "
            "virtuals and its groupings are untouched."),
        input_schema={
            "type": "object",
            "properties": {"device_id": {"type": "string"},
                           "name": {"type": "string"}},
            "required": ["device_id", "name"], "additionalProperties": False},
        handler=_op_rename_device),
    "set_device_timing_offset": SonicOperation(
        name="set_device_timing_offset", domain="device", kind="write",
        summary="Set one device's timing offset in milliseconds — NEGATIVE "
                "MEANS IT FIRES EARLIER, positive later, 0 unchanged.",
        instructions=(
            "His convention, exactly: negative is that it fires earlier. "
            f"Range -{OFFSET_LIMIT_MS} to {OFFSET_LIMIT_MS} ms. Only "
            "DIFFERENCES between devices matter — shifting every device by "
            "the same amount changes nothing at all, because a fixture can "
            "only be made to wait: 'earlier' for one device is implemented "
            "as delay for the others, and the earliest device is never "
            "delayed. This therefore cannot move the room as a whole against "
            "the music; that is the room's own A/V sync lead, a different "
            "setting with the OPPOSITE sign convention. Takes effect on the "
            "next rendered frame, no restart."),
        input_schema={
            "type": "object",
            "properties": {
                "device_id": {"type": "string"},
                "timing_offset_ms": {
                    "type": "integer", "minimum": -OFFSET_LIMIT_MS,
                    "maximum": OFFSET_LIMIT_MS,
                    "description": "Negative = this device fires EARLIER."},
            },
            "required": ["device_id", "timing_offset_ms"],
            "additionalProperties": False},
        handler=_op_set_device_timing_offset),
    "set_device_categories": SonicOperation(
        name="set_device_categories", domain="device", kind="write",
        summary="Set exactly which groupings (categories) one virtual "
                "belongs to.",
        instructions=(
            "Groupings are per VIRTUAL, not per device — list_devices shows "
            "each device's virtual ids and their current categories. Pass "
            "the complete list you want that virtual to be in; anything "
            "omitted is removed. Every name must already exist — this never "
            "invents a category, because a typo would file a light "
            "somewhere nothing looks."),
        input_schema={
            "type": "object",
            "properties": {"virtual_id": {"type": "string"},
                           "categories": {"type": "array",
                                          "items": {"type": "string"}}},
            "required": ["virtual_id", "categories"],
            "additionalProperties": False},
        handler=_op_set_device_categories),
}
