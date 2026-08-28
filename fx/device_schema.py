"""THE DEVICE PARAMETER SET, READ OFF THE REAL VALIDATOR (SpotFX-authored;
not fork code).

The device edit/create page must offer every parameter a device actually
has, and must never be able to drift from what the vendored driver will
accept. So it is not a hand-written list: this module introspects each
vendored device class's OWN merged `CONFIG_SCHEMA` — the exact voluptuous
schema `Device.update_config` validates against — and reports it as plain
data the API can serialize.

SCOPE: the six device types vendored under `fx/devices/` (fx.host.
VENDORED_DEVICE_TYPES). LedFX ships thirteen more; none of their drivers
are vendored here, so a config naming one is skipped by the device registry
at host start with a warning — offering them on a create form would be
offering a device that can never come up. `com_port`/`baudrate` belong to
the fork's serial device types and are deliberately absent for the same
reason.

GROUPING: `base` is everything on `Device.CONFIG_SCHEMA` +
`NetworkedDevice.CONFIG_SCHEMA` (name/icon_name/center_offset/refresh_rate/
ip_address) — the keys shared across types; `type` is what that one driver
adds. The page groups by exactly this, so the grouping is derived from the
class hierarchy rather than a second hand-kept list.

The per-device TIMING field (`timing_offset_ms`) is NOT here: it is
SPECTRA's own record, not a vendored device config key
(spectra/models/device_settings.py). It is a third group on the page.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from fx.devices import Device, NetworkedDevice
from fx.host import VENDORED_DEVICE_TYPES

# Import the driver modules so BaseRegistry has them all registered — the
# host does this via the registry loader; a bare `import fx.devices` does not.
from fx.devices import ddp, dummy, e131, hue, udp, wled  # noqa: F401


def device_types() -> list[str]:
    """The types a device may be CREATED as, in a stable order."""
    return sorted(set(Device.registry()) & set(VENDORED_DEVICE_TYPES))


def _base_keys() -> set[str]:
    keys: set[str] = set()
    for cls in (Device, NetworkedDevice):
        schema = cls.CONFIG_SCHEMA
        if isinstance(schema, property):
            schema = schema.fget()
        keys |= {str(k) for k in schema.schema}
    return keys


def _unwrap(validator: Any) -> tuple[str, dict]:
    """(kind, extras) for one voluptuous validator. `kind` is what an input
    control needs to know: text / integer / boolean / enum."""
    extras: dict[str, Any] = {}
    if isinstance(validator, vol.All):
        for inner in validator.validators:
            kind, more = _unwrap(inner)
            extras.update(more)
            if kind != "text":
                base_kind = kind
                break
        else:
            base_kind = "text"
        # a Range inside an All carries the bounds; the type carries the kind
        for inner in validator.validators:
            if isinstance(inner, vol.Range):
                if inner.min is not None:
                    extras["min"] = inner.min
                if inner.max is not None:
                    extras["max"] = inner.max
        return base_kind, extras
    if isinstance(validator, vol.In):
        return "enum", {"choices": list(validator.container)}
    if isinstance(validator, vol.Range):
        if validator.min is not None:
            extras["min"] = validator.min
        if validator.max is not None:
            extras["max"] = validator.max
        return "text", extras
    if validator is bool:
        return "boolean", extras
    if validator is int:
        return "integer", extras
    if validator is float:
        return "number", extras
    if validator is str:
        return "text", extras
    # fps_validator and friends: a plain callable coercing an int
    return "integer" if getattr(validator, "__name__", "") == "fps_validator" \
        else "text", extras


def _default(marker) -> Any:
    default = getattr(marker, "default", None)
    if default is None:
        return None
    try:
        value = default()
    except Exception:
        return None
    return None if value is vol.UNDEFINED else value


def fields_for(device_type: str) -> list[dict]:
    """Every config key this device type accepts, base group first, each
    with the kind/default/bounds/choices/description read off the schema
    itself. Raises KeyError for an unknown or unvendored type."""
    if device_type not in device_types():
        raise KeyError(device_type)
    cls = Device.registry()[device_type]
    base = _base_keys()
    fields: list[dict] = []
    for marker, validator in cls.schema().schema.items():
        name = str(marker)
        kind, extras = _unwrap(validator)
        fields.append({
            "name": name,
            "group": "base" if name in base else "type",
            "kind": kind,
            "required": isinstance(marker, vol.Required),
            "default": _default(marker),
            "description": getattr(marker, "description", None) or "",
            **extras,
        })
    fields.sort(key=lambda f: (f["group"] != "base", f["name"]))
    return fields


def all_fields() -> dict[str, list[dict]]:
    return {t: fields_for(t) for t in device_types()}


def distinct_parameter_names() -> list[str]:
    """Every distinct config key across all six vendored types — what the
    page's completeness claim is counted against."""
    names: set[str] = set()
    for fields in all_fields().values():
        names |= {f["name"] for f in fields}
    return sorted(names)


def validate_config(device_type: str, config: dict) -> dict:
    """Run a candidate config through the REAL validator the driver's own
    update_config uses. Raises voluptuous.Invalid — the caller turns that
    into a stated rejection, never a silent drop."""
    if device_type not in device_types():
        raise KeyError(device_type)
    return Device.registry()[device_type].schema()(dict(config))
