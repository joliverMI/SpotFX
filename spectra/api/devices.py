"""DEVICE EDIT/CREATE API — the wire for /devices, the page his ask asked
for ("we need a device edit page to edit and create devices... all the
parameters that were tunable in ledfx on one tab, as well as the groupings
and namings"). spectra/services/device_console.py holds the mechanism, the
two write branches and the reasoning; this file is only the wire.

  GET  /api/devices                    every device (type, full config, its
                                       virtuals + their groupings, its
                                       timing offset) PLUS the complete
                                       per-type parameter list read off the
                                       vendored drivers' own schemas, the
                                       category names, and `source`:
                                       "live" (the room is running — edits
                                       reach the fixtures now) or "stored"
                                       (it is not — edits land at the next
                                       activation).
  POST /api/devices                    {type, config} — create a device and
                                       the virtual that renders onto it.
  PUT  /api/devices/{id}               {config} — a PARTIAL config patch.
  PUT  /api/devices/{id}/timing        {timing_offset_ms} — his timing
                                       field. NEGATIVE = fires EARLIER.
  PUT  /api/devices/virtuals/{vid}/categories
                                       {categories} — the groupings, set
                                       wholesale for one virtual.

Every refusal is a 400 carrying the server's own `reason` (and, where it
helps, the legal set) — never a silent drop. A write while the room is
down is reported as `applied: "stored"`, never claimed as live.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from spectra.services import device_console

router = APIRouter(prefix="/api/devices", tags=["spectra-devices"])


class CreateDeviceBody(BaseModel):
    type: str
    config: dict


class UpdateDeviceBody(BaseModel):
    config: dict


class TimingBody(BaseModel):
    timing_offset_ms: int


class CategoriesBody(BaseModel):
    categories: list[str]


def _refused(exc: device_console.DeviceOpError) -> JSONResponse:
    return JSONResponse(status_code=400,
                        content={"detail": exc.reason, **exc.extra})


@router.get("")
async def get_devices():
    try:
        return await device_console.list_devices()
    except device_console.DeviceOpError as exc:
        return _refused(exc)


@router.post("")
async def post_device(body: CreateDeviceBody):
    try:
        return await device_console.create_device(body.type, body.config)
    except device_console.DeviceOpError as exc:
        return _refused(exc)


@router.put("/virtuals/{virtual_id}/categories")
async def put_categories(virtual_id: str, body: CategoriesBody):
    try:
        return device_console.set_virtual_categories(virtual_id, body.categories)
    except device_console.DeviceOpError as exc:
        return _refused(exc)


@router.put("/{device_id}/timing")
async def put_timing(device_id: str, body: TimingBody):
    try:
        return device_console.set_timing_offset_ms(device_id,
                                                   body.timing_offset_ms)
    except device_console.DeviceOpError as exc:
        return _refused(exc)


@router.put("/{device_id}")
async def put_device(device_id: str, body: UpdateDeviceBody):
    try:
        return await device_console.update_device(device_id, body.config)
    except device_console.DeviceOpError as exc:
        return _refused(exc)
