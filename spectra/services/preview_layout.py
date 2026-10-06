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

A HELD HUE FIXTURE CARRIES ITS REAL COLOUR, NEVER THE STREAM'S (2026-10-06,
`hue_preview_colour.py`'s own module docstring has the full defect). A Hue
device's driving virtual never stops rendering while the device is
FROZEN (held by house lighting or plain Ambient over REST) — so the
preview stream, which taps that same render, shows whatever the room's
ordinary show happens to paint there, unrelated to the colour the real
bulb actually shows. On his "hues" virtual this is structural, not
incidental: it is ONE shared effect pixel, copy-mapped onto every bulb
across both entertainment areas, so even a perfectly correct render could
never show two held areas at two different colours. `held` (per fixture,
and a pixel-weighted mean per virtual for the top strip's single swatch)
is resolved from `house.hue_directive()`'s own per-device look — the
SAME tuple ambient.py sends to the bridge — converted through
`hue_preview_colour.held_hex_for_look`; `None` means "not held, draw the
live render exactly as before". A bulb left to Home Assistant
(`HouseSettings.hue_excluded_lights`) must never draw the held colour
either, even mixed into the SAME SPECTRA device as held bulbs — `_held_hex`
checks that against `ambient.cached_light_names()`'s own cached, per-device
bulb list (never a fresh bridge call), falling back to the live render for
the whole fixture when it can't yet confirm no overlap. `build_layout`/
`virtual_layout` stay PURE (no live read inside them) — `current_layout()`
is the one caller that resolves the live directive via
`current_hue_looks()`.
"""
from __future__ import annotations

import json
import logging
from typing import Callable, Optional

import numpy as np

from spectra import config
from spectra.services import emitters
from spectra.services.preview_stream import profile_cell_index

logger = logging.getLogger(__name__)


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


def _held_hex(device_id: str, device_type: Optional[str], device_cfg: dict,
              looks) -> Optional[str]:
    """The colour a HELD Hue fixture actually shows right now, or `None` to
    draw its live render unchanged (not Hue, no hold in effect, a `"show"`
    look, or this fixture has a bulb left to Home Assistant — see
    hue_preview_colour.py's module docstring for the whole defect this
    closes).

    One preview fixture is a WHOLE SPECTRA device (one Hue entertainment
    area), lumping together every physical bulb it drives — his
    `hue-lights` area mixes 6 bulbs the house mode holds with 4
    (`HouseSettings.hue_excluded_lights`, e.g. Loft Ceiling Uplight, the
    Ledge bulbs) it deliberately leaves alone. `ambient.skipped_lights()`
    is GLOBAL by design (house.py names an excluded bulb under area "*",
    since it has no idea which area a bulb lives in), so a non-empty
    result says nothing about whether THIS device actually has one of
    those bulbs — comparing it against this device's own AREA NAME (the
    original bug) can never match, and comparing it against EVERY area
    unconditionally would disable held preview for every Hue fixture the
    moment any bulb anywhere is excluded, including areas with no overlap
    at all (e.g. `dining-hues`, which shares none of `hue-lights`' excluded
    bulbs). `ambient.cached_light_names()` is the one thing that actually
    knows which bulbs belong to this device — a pure cache read, warmed by
    the SAME hold/verify that reported this exclusion in the first place,
    never a fresh network call. Only once that intersection comes back
    genuinely non-empty do we know this fixture has an excluded bulb mixed
    in, and only then do we fall back to the live render for the WHOLE
    fixture — there is no pixel-level membership to draw the held colour
    on just the rest. An unresolved cache (no hold has touched this device
    yet) is treated the same conservative way: never claim a colour we
    cannot confirm excludes nothing."""
    if looks is None or str(device_type or "").lower() != "hue":
        return None
    from spectra.services import ambient, hue_preview_colour
    excluded = ambient.skipped_lights(device_id, looks)
    if excluded:
        names = ambient.cached_light_names(device_cfg or {})
        if names is None or names & excluded:
            return None
    return hue_preview_colour.held_hex_for_look(ambient.look_for(device_id, looks))


def _virtual_held_hex(fixtures: list[dict]) -> Optional[str]:
    """A single swatch colour for the WHOLE virtual (the top strip has no
    per-fixture granularity) — only when every fixture it reaches is
    currently held; a mix of held/un-held or held/non-Hue draws the live
    render instead, since this module has no render pixels to blend with.
    A pixel-count-weighted mean, so a 10-bulb area doesn't get swamped by a
    1-bulb one."""
    if not fixtures or any(f["held"] is None for f in fixtures):
        return None
    hexes = {f["held"] for f in fixtures}
    if len(hexes) == 1:
        return next(iter(hexes))
    from spectra.services import hue_preview_colour
    total = sum(f["count"] for f in fixtures) or 1
    r = g = b = 0.0
    for f in fixtures:
        cr, cg, cb = hue_preview_colour.hex_to_rgb(f["held"])
        r += cr * f["count"]; g += cg * f["count"]; b += cb * f["count"]
    return hue_preview_colour.rgb_to_hex((round(r / total), round(g / total), round(b / total)))


def virtual_layout(virtual: dict, devices: dict[str, dict], hue_looks=None) -> Optional[dict]:
    """One virtual's fixtures, or None when it reaches no fixture that emits.
    `hue_looks` is `house.hue_directive().looks` (or the plain Ambient
    equivalent) — the SAME tuple ambient.py sends to the bridge, resolved
    ONCE by the caller rather than per fixture."""
    resolved = fixture_pixels(virtual, devices)
    if resolved is None:
        return None
    rows = resolved["rows"]
    fixtures = []
    for fx in resolved["fixtures"]:
        device, pixels, src = fx["device"], fx["virtual_px"], fx["src"]
        kind, orient = ("matrix", "h") if rows > 1 else _kind(device, len(pixels))
        name = (device.get("config") or {}).get("name") or fx["device_id"]
        fixtures.append({
            "device_id": fx["device_id"],
            "name": name,
            "type": device.get("type"),
            "kind": kind, "orient": orient, "count": int(len(pixels)),
            "src": (None if np.array_equal(src, np.arange(len(src)))
                    else [int(i) for i in src]),
            "grid": [int(i) for i in pixels] if rows > 1 else None,
            "held": _held_hex(fx["device_id"], device.get("type"),
                             device.get("config"), hue_looks),
        })
    return {
        "id": resolved["id"], "name": resolved["name"], "rows": rows,
        "cols": resolved["cols"], "cells": resolved["cells"],
        "mapping": "copy" if resolved["copy"] else "span",
        "hex_lattice": rows > 1 and _profile_hex(resolved["id"]),
        "held": _virtual_held_hex(fixtures),
        "fixtures": fixtures,
    }


def current_hue_looks():
    """The look every live Hue device is currently held at, read fresh —
    house lighting's own directive when it holds Hue, else `None` (no mode,
    no Hue looks, or the house layer isn't driving — a plain, non-house
    Ambient hold has no per-device look to show distinct areas with, so it
    is left to the live render same as always). Never raises: a broken read
    must not take the whole layout down with it. Called once by
    `current_layout()` — never by `build_layout`/`virtual_layout`
    themselves, which stay pure (fx config dict in, drawable virtuals out,
    `hue_looks` an explicit argument) so a test can drive them without
    touching any live store."""
    try:
        from spectra.services import house
        directive = house.hue_directive()
        return directive.looks if directive is not None else None
    except Exception:                                    # noqa: BLE001
        logger.exception("preview_layout: could not read the live Hue hold "
                         "— drawing the live render instead")
        return None


def build_layout(raw: dict, driven: set[str], active: Callable[[dict], bool],
                 hue_looks=None) -> list[dict]:
    """Pure: the fx config dict in, the drawable virtuals out. `hue_looks`
    (the house hue_directive's own look tuples, `current_hue_looks()` for a
    live caller) says which Hue fixtures are currently HELD and at what
    colour — `None` (the default) means no override, draw every fixture's
    live render exactly as before this field existed."""
    devices = {str(d.get("id")): d for d in raw.get("devices") or [] if d.get("id")}
    out = []
    for virtual in raw.get("virtuals") or []:
        if driven and virtual.get("id") not in driven:
            continue
        if not active(virtual):
            continue
        described = virtual_layout(virtual, devices, hue_looks)
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

    virtuals = build_layout(raw, room_topology.genuinely_driven_virtual_ids(), active,
                            hue_looks=current_hue_looks())
    favorites = set(device_preview.effective_favorite_ids())
    for virtual in virtuals:
        virtual["favorite"] = virtual["id"] in favorites
    return {"source": "live" if host is not None else "stored", "virtuals": virtuals}


def in_use_virtual_ids() -> list[str]:
    try:
        return [v["id"] for v in current_layout()["virtuals"]]
    except Exception:
        return []
