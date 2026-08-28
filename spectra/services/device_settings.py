"""SPECTRA's per-device settings store (storage/spectra/device_settings.json)
and the ONE push that installs the timing offsets into the render pipeline.

WHAT IT HOLDS: a spectra.models.device_settings.DeviceSettings record per
device id — today one field, `timing_offset_ms` (OFFSET family: negative =
this device fires EARLIER; see that model's docstring for the whole sign
law, and docs/SPECTRA_TIMING_CONVENTIONS.md for how it sits against every
other timing quantity in the codebase).

THE ROOM LEAD IS UNTOUCHED BY EVERYTHING HERE. `RoomControlState.
av_sync_lead_ms` — applied once, at the trigger poll in
spectra/services/engine.py — remains the only knob that moves the room as a
whole against the sound, and it is the only ABSOLUTE alignment term in the
show clock. Per-device offsets change RELATIVE timing only: the engine
anchors them by subtracting the smallest authored offset, so the earliest
device is never delayed and no combination of these values can shift the
room. Measure with /avsync, correct the room with the lead, equalize the
fixtures with these.

WHERE IT LANDS: push_offsets() hands the full map to fx.device_timing, the
process-global registry the device flush layer reads on every frame
(fx/devices/__init__.py::_flush_timed). `fx/` may not import `spectra/`, so
this direction — SPECTRA pushes, fx never pulls — is structural, not a
style choice.

WHICH DEVICES PARTICIPATE. The equalization is anchored on the minimum
offset across the devices handed to fx.device_timing.apply_offsets, so the
set matters. With the live stack up, that set is the HOST'S OWN device ids
with 0 filled in for every device with no stored record — which is what
makes a single device authored at -100 delay every OTHER real fixture by
100 ms rather than delaying nothing. With the stack down the roster comes
from the fx-live config instead (the same file the go-day seeder writes),
so the numbers the device page reports are the ones the next activation
will install; live_host.LiveLights.activate re-pushes against the real host
roster when it comes up. Stored ids are folded in either way, so an offset
authored for a device that has since left the roster is never silently
dropped from his spacing.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile

from spectra import config
from spectra.models.device_settings import DeviceSettings

logger = logging.getLogger(__name__)


def load_all() -> dict[str, DeviceSettings]:
    path = config.DEVICE_SETTINGS_FILE
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return {did: DeviceSettings(**(rec or {}))
                    for did, rec in (raw.get("devices") or {}).items()}
        except Exception as exc:
            logger.warning("device_settings.json parse failed: %s", exc)
    return {}


def get(device_id: str) -> DeviceSettings:
    """This device's record, or the all-defaults record. A device with no
    stored entry and a device stored at its defaults are the same thing."""
    return load_all().get(device_id) or DeviceSettings()


def save_all(records: dict[str, DeviceSettings]) -> None:
    path = config.DEVICE_SETTINGS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"devices": {did: json.loads(r.model_dump_json())
                        for did, r in sorted(records.items())}}
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(body, fh, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    logger.info("device settings: saved %d record(s)", len(records))


def save(device_id: str, record: DeviceSettings) -> DeviceSettings:
    """Write ONE device's record, leaving every other record byte-for-byte
    as it was, then push the new offsets to the render pipeline."""
    records = load_all()
    records[device_id] = record
    save_all(records)
    push_offsets()
    return record


def set_timing_offset_ms(device_id: str, value: int) -> DeviceSettings:
    record = get(device_id).model_copy(update={"timing_offset_ms": int(value)})
    DeviceSettings.model_validate(record.model_dump())   # re-validate the clamp
    return save(device_id, record)


def _host_device_ids() -> list[str]:
    """Every device id the LIVE stack currently holds, or [] when it is
    down. Imported lazily: this module is reachable from an offline script
    and must not drag the live stack in."""
    try:
        from spectra.services.live_host import live
    except Exception:                                    # pragma: no cover
        return []
    host = getattr(live, "host", None)
    if host is None:
        return []
    try:
        return [d.id for d in host.devices.values()]
    except Exception:                                    # pragma: no cover
        logger.exception("device settings: could not read live device ids")
        return []


def _configured_device_ids() -> list[str]:
    """Every device id the fx-live config declares — the room's roster when
    the stack is down. Read straight off the file (never through
    device_console, which imports this module) so there is no cycle."""
    try:
        path = config.FX_LIVE_CONFIG_DIR / "config.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return [d["id"] for d in (raw.get("devices") or []) if d.get("id")]


def resolve_offsets(device_ids: list[str] | None = None) -> dict[str, int]:
    """The map handed to fx.device_timing: every participating device id
    with its authored offset, 0 where unset. See the module docstring for
    which ids participate — the live host's roster when it is up, the
    fx-live config's when it is not, and the stored ids as a last resort so
    an offset is never silently dropped for want of a roster."""
    records = load_all()
    ids = list(device_ids) if device_ids is not None else _host_device_ids()
    if not ids:
        ids = _configured_device_ids()
    if not ids:
        ids = list(records)
    else:
        # never lose an authored offset just because its device has since
        # left the roster — it participates, so his spacing is preserved
        ids = list(dict.fromkeys([*ids, *records]))
    return {did: (records.get(did) or DeviceSettings()).timing_offset_ms
            for did in ids}


def push_offsets(device_ids: list[str] | None = None) -> dict[str, float]:
    """Install the current offsets into the render pipeline. Returns the
    derived per-device delays in seconds (all zero when nothing is
    authored). Safe to call at any time — it is a dict swap, never I/O."""
    from fx import device_timing
    return device_timing.apply_offsets(resolve_offsets(device_ids))
