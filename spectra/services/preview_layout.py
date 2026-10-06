"""What the Live view draws: every in-use fixture, in its real shape, and
which cell of the preview stream lights each of its pixels.

The preview stream (preview_stream.py) carries one record per VIRTUAL — the
thing an effect renders onto. A person looks at FIXTURES: the crystal, the
TV strip, each sconce, each group of bulbs. One virtual often feeds several
(his `tv-mapper` copies one 560-pixel effect onto the TV backlight and both
kitchen sconces; `hues` copies one pixel onto seventeen bulbs). This module
reads the stored fx config's own segment lists and answers, per fixture:

  kind    how to draw it — "matrix" (a grid; `hex_lattice` when its stored
          device profile says so), "strip", "frame" (a strip run around a
          screen), "bulbs" (separate lamps) or "dot" (one or two pixels)
  src     for each fixture pixel, the index of the stream CELL that colours
          it. A cell index is a position in the record's payload, which for
          a masked device (the crystal) is the rank among its real cells,
          not the pixel index.
  grid    matrix only: each pixel's row-major position in rows x cols

THE SHAPE IS A HINT, NOT A MEASUREMENT. Spectra stores how pixels are
addressed, never where they are, so "frame" and "vertical" are read off the
fixture's type and name (`_kind`). The exact crystal lattice is the one real
geometry here (storage/device_profiles). The Live view's position table
takes this as ONE source; the room map (room_view.py) is another source for
the same renderer, built from camera data, and keeps only the crystal's
lattice from here.

COPY MAPPING is reproduced as nearest-pixel: the render path interpolates
the effect onto each segment (fx/virtuals.py `_flush_simple_segments`); a
preview does not need the blend between two neighbouring effect pixels.

Which virtuals: the room's genuinely driven ones (room_topology) that are
active and reach at least one fixture that emits light
(`emitters.emits_light` — a dummy backs real virtuals and emits nothing).
An empty ground truth means no restriction, never "nothing".
"""
from __future__ import annotations

import json
from typing import Callable, Optional

import numpy as np

from spectra import config
from spectra.services import emitters
from spectra.services.preview_stream import profile_cell_index


def _segment(seg: list) -> tuple[str, int, int, bool, int]:
    offset = int(seg[4]) if len(seg) > 4 and seg[4] else 0
    return str(seg[0]), int(seg[1]), int(seg[2]), bool(seg[3]), offset


def _kind(device: dict, count: int) -> tuple[str, str]:
    """(kind, orientation) for a one-row fixture. Read off type and name —
    see the module docstring for why that is all there is to read."""
    name = f"{device.get('id', '')} {(device.get('config') or {}).get('name', '')}".lower()
    if str(device.get("type", "")).lower() == "hue":
        return "bulbs", "h"
    if count <= 2:
        return "dot", "h"
    if "backlight" in name or "tv" in name.replace("-", " ").split():
        return "frame", "h"
    return "strip", ("v" if "sconce" in name else "h")


def _profile_hex(vis_id: str) -> bool:
    path = config.REPO_ROOT / "storage" / "device_profiles" / f"{vis_id}.json"
    try:
        return bool(json.loads(path.read_text(encoding="utf-8")).get("hex_lattice"))
    except (OSError, ValueError):
        return False


def fixture_pixels(virtual: dict, devices: dict[str, dict]) -> Optional[dict]:
    """One virtual resolved to its light-emitting fixtures, pixel by pixel.

    Per fixture, three parallel arrays over the fixture's own pixels (the
    order `virtual_layout` publishes them in):
      virtual_px   the virtual's effect pixel each one shows
      device_px    its index on the device's own strip
      src          the stream cell that colours it
    `virtual_layout` is this with the arrays turned into the Live view's
    wire shape; the room map (room_view.py) reads the arrays themselves to
    tie a measured pixel range to the fixture pixels it lit."""
    cfg = virtual.get("config") or {}
    segments = [_segment(s) for s in virtual.get("segments") or []]
    if not segments:
        return None
    copy = cfg.get("mapping") == "copy"
    lengths = [end - start + 1 for _, start, end, _, _ in segments]
    pixel_count = max(lengths) if copy else sum(lengths)
    rows = max(1, int(cfg.get("rows") or 1))
    cols = pixel_count // rows
    vis_id = str(virtual.get("id"))
    cell_index = profile_cell_index(vis_id, pixel_count, rows)
    # stream cell for each virtual pixel; -1 where the pixel is not sent
    if cell_index is None:
        rank = np.arange(pixel_count, dtype=np.int64)
    else:
        rank = np.full(pixel_count, -1, dtype=np.int64)
        rank[cell_index] = np.arange(len(cell_index))

    per_device: dict[str, list[tuple[int, np.ndarray]]] = {}
    position = 0
    for (device_id, start, end, invert, offset), length in zip(segments, lengths):
        if copy:
            pixels = (np.zeros(1, dtype=np.int64) if length == 1 else
                      np.rint(np.linspace(0, pixel_count - 1, length)).astype(np.int64))
        else:
            pixels = np.arange(position, position + length, dtype=np.int64)
            position += length
        if invert:
            pixels = pixels[::-1]
        if offset:
            pixels = np.roll(pixels, offset)
        device = devices.get(device_id)
        if device is not None and emitters.emits_light(device):
            per_device.setdefault(device_id, []).append((start, pixels))

    fixtures = []
    for device_id, parts in per_device.items():
        parts = sorted(parts, key=lambda part: part[0])
        pixels = np.concatenate([p for _, p in parts])
        device_px = np.concatenate(
            [np.arange(start, start + len(p), dtype=np.int64) for start, p in parts])
        if rows > 1:
            order = np.argsort(pixels, kind="stable")
            pixels, device_px = pixels[order], device_px[order]
        sent = rank[pixels] >= 0
        pixels, device_px = pixels[sent], device_px[sent]
        if len(pixels) == 0:
            continue
        fixtures.append({"device_id": device_id, "device": devices[device_id],
                         "virtual_px": pixels, "device_px": device_px,
                         "src": rank[pixels]})
    if not fixtures:
        return None
    return {
        "id": vis_id, "name": cfg.get("name") or vis_id, "rows": rows, "cols": cols,
        "cells": int(len(cell_index)) if cell_index is not None else pixel_count,
        "copy": copy, "fixtures": fixtures,
    }


def virtual_layout(virtual: dict, devices: dict[str, dict]) -> Optional[dict]:
    """One virtual's fixtures, or None when it reaches no fixture that emits."""
    resolved = fixture_pixels(virtual, devices)
    if resolved is None:
        return None
    rows = resolved["rows"]
    fixtures = []
    for fx in resolved["fixtures"]:
        device, pixels, src = fx["device"], fx["virtual_px"], fx["src"]
        kind, orient = ("matrix", "h") if rows > 1 else _kind(device, len(pixels))
        fixtures.append({
            "device_id": fx["device_id"],
            "name": (device.get("config") or {}).get("name") or fx["device_id"],
            "type": device.get("type"),
            "kind": kind, "orient": orient, "count": int(len(pixels)),
            "src": (None if np.array_equal(src, np.arange(len(src)))
                    else [int(i) for i in src]),
            "grid": [int(i) for i in pixels] if rows > 1 else None,
        })
    return {
        "id": resolved["id"], "name": resolved["name"], "rows": rows,
        "cols": resolved["cols"], "cells": resolved["cells"],
        "mapping": "copy" if resolved["copy"] else "span",
        "hex_lattice": rows > 1 and _profile_hex(resolved["id"]),
        "fixtures": fixtures,
    }


def build_layout(raw: dict, driven: set[str], active: Callable[[dict], bool]) -> list[dict]:
    """Pure: the fx config dict in, the drawable virtuals out."""
    devices = {str(d.get("id")): d for d in raw.get("devices") or [] if d.get("id")}
    out = []
    for virtual in raw.get("virtuals") or []:
        if driven and virtual.get("id") not in driven:
            continue
        if not active(virtual):
            continue
        described = virtual_layout(virtual, devices)
        if described is not None:
            out.append(described)
    # Four of his WLEDs are all named "WLED": a name shared by two fixtures
    # tells him nothing, so those are labelled by their device id instead.
    names = [f["name"] for v in out for f in v["fixtures"]]
    for v in out:
        for f in v["fixtures"]:
            if names.count(f["name"]) > 1:
                f["name"] = f["device_id"].replace("-", " ").capitalize()
    return out


def current_layout() -> dict:
    """The layout of the room as stored, with each virtual's `active` read
    off the running host when the stack is up."""
    from spectra.services import device_console, device_preview, room_topology

    raw = device_console._read_stored_config()
    host = device_console._live_host()

    def active(virtual: dict) -> bool:
        if host is not None:
            live_virtual = host.virtuals.get(virtual.get("id"))
            if live_virtual is not None:
                return bool(live_virtual.active)
        return virtual.get("active") is True

    virtuals = build_layout(raw, room_topology.genuinely_driven_virtual_ids(), active)
    favorites = set(device_preview.effective_favorite_ids())
    for virtual in virtuals:
        virtual["favorite"] = virtual["id"] in favorites
    return {"source": "live" if host is not None else "stored", "virtuals": virtuals}


def in_use_virtual_ids() -> list[str]:
    try:
        return [v["id"] for v in current_layout()["virtuals"]]
    except Exception:
        return []
