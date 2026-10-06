"""THE ROOM MAP VIEW — the Live view's second position source: every fixture
drawn where one camera saw its light, over a glow of that light.

The Live view (spectra/web/src/live/) draws a position table. Its first
table is a tidy layout (preview_layout.py). This module builds what the
second one needs, PER CAMERA POSE, from data Spectra already stores:

  glow       each mapped emitter's light-field footprint
             (storage/spectra/room_maps.json), as a 64x36 picture the view
             tints with that emitter's live colour and adds together
  pieces     every fixture pixel, grouped into the runs that share one
             answer to "where is this drawn": at the centre of a footprint,
             at a judged commissioning decode's own per-pixel positions, or
             nowhere yet (the "not placed" tray)
  hand       where he put a piece himself, per pose — the ONE thing this
             module writes (config.ROOM_VIEW_FILE). Room maps and
             commissioning results are read and never written.

EVERY POSITION HERE IS A PLACE IN ONE CAMERA'S PICTURE — x and y in 0..1 of
that camera's frame, the convention `spectra/models/room_map.Point` and
`gray_code.Decode.positions` already use. None is a room coordinate and
none says where an LED is: a footprint's centre is where that emitter's
LIGHT landed (a sconce whose spill covers the ceiling has its centre on the
ceiling), and the marker drawn there marks the light. The light-field
model's own fence (models/room_map.py) is unchanged; this module only reads
it.

ONE POSE AT A TIME. A footprint is relative luminance in one camera's byte
scale and one camera's frame, comparable only with footprints carrying the
same `capture.pose_id` (models/room_map.CaptureContext). So a view is the
footprints of ONE pose id — which may span several room entries when one
sitting mapped several (his kiosk pose holds the Living Room, the crystal
and the dining table) — and two poses are never drawn together.

THERE IS NO PHOTOGRAPH. The capture path keeps numbers and never an image
(config.ROOM_MAPS_FILE's own note), so the picture behind the glow is the
camera's measurements themselves: every footprint of the pose added up,
shown dim. It is what the lights revealed to the camera, and nothing else.

ANOTHER POSITION SOURCE PLUGS IN HERE. `register_source` takes a function
that gives per-pixel positions in the pose's picture for a fixture; the
commissioning decode below is the first one and proves the seam. A map made
elsewhere (WLED's own LED maps) joins by registering a source that puts its
positions into the pose's picture — nothing in the view changes. Order of
authority for a pixel: his hand, a per-pixel source, a footprint, the tray.

A FAILED DECODE IS NOT A POSITION. Only a commissioning result whose own
judged table came out `pass` or `findings` is drawn; a `fail` decodes
confidently to wrong places (docs/SPECTRA_SPEC.md §98) and is named in the
view's notes instead. Stored results from before decodes kept their
positions (gray_code.Decode.as_dict) carry none and are skipped the same
way.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import tempfile
import threading
import time
from typing import Callable, Optional

import numpy as np
from pydantic import BaseModel, Field

from spectra import config
from spectra.models.room_map import GRID_H, GRID_W, EmitterFootprint, RoomMap

logger = logging.getLogger(__name__)

#: A light's "core" is the connected patch at or above this share of its peak.
CORE_FRACTION = 0.5
#: Glow below this share of an emitter's own peak is not drawn: the speckle
#: noisy camera cells leave across the whole frame.
GLOW_FLOOR = 0.06
#: A whole fixture is drawn at least this wide (share of the picture's
#: width), so its pixels can be told apart; a piece of one, at least this.
MIN_SHAPE_RADIUS = 0.0425
MIN_CLUSTER_RADIUS = 0.012
MAX_CLUSTER_RADIUS = 0.04
MAX_RADIUS = 0.2
DECODE_VERDICTS = ("pass", "findings")
MAX_PLACEMENTS_PER_POSE = 4000
MAX_KEY_LENGTH = 200

_write_lock = threading.Lock()


# ── per-pixel position sources ─────────────────────────────────────────────

#: fn(pose_id, fixtures) -> {(virtual_id, device_id): {"positions": {fixture
#: pixel: (x, y)}, "note": str}} — positions in the pose's own picture.
PixelSource = Callable[[str, list[dict]], dict]
_sources: list[tuple[str, PixelSource]] = []


def register_source(name: str, fn: PixelSource) -> None:
    """Add a per-pixel position source (see the module docstring). A name
    registered twice replaces the earlier function."""
    global _sources
    _sources = [(n, f) for n, f in _sources if n != name] + [(name, fn)]


def _composition_pixels(composition: dict) -> list[tuple[str, int]]:
    """A commissioning composition's index -> (device id, device pixel)."""
    out: list[tuple[str, int]] = []
    for seg in composition.get("segments") or []:
        device_id = str(seg.get("device_id"))
        for px in range(int(seg.get("start", 0)), int(seg.get("end", -1)) + 1):
            out.append((device_id, px))
    return out


def _judged_decodes(results: list[dict], pose_id: str):
    """(mapper id, composition, positions, verdict) for every stored decode
    at this pose, newest first."""
    for result in reversed(results):
        if result.get("pose_id") != pose_id:
            continue
        runs = list(result.get("targets") or []) or [result]
        for run in runs:
            decodes = run.get("decodes") or []
            table = run.get("table") or {}
            if not decodes:
                continue
            yield (str(result.get("mapper_id") or ""), run.get("composition") or {},
                   decodes[0].get("positions") or {}, str(table.get("verdict") or ""))


def decode_source(results: list[dict]) -> PixelSource:
    """Judged commissioning decodes as a per-pixel source. The newest usable
    decode of a fixture wins."""
    def source(pose_id: str, fixtures: list[dict]) -> dict:
        out: dict = {}
        for mapper_id, composition, positions, verdict in _judged_decodes(results, pose_id):
            if verdict not in DECODE_VERDICTS or not positions:
                continue
            pixels = _composition_pixels(composition)
            where: dict[tuple[str, int], tuple[float, float]] = {}
            for index, xy in positions.items():
                i = int(index)
                if 0 <= i < len(pixels) and len(xy) == 2:
                    where[pixels[i]] = (float(xy[0]), float(xy[1]))
            for fx in fixtures:
                key = (fx["virtual_id"], fx["device_id"])
                if fx["virtual_id"] != mapper_id or key in out:
                    continue
                found = {j: where[(fx["device_id"], int(px))]
                         for j, px in enumerate(fx["device_px"])
                         if (fx["device_id"], int(px)) in where}
                if found:
                    out[key] = {"positions": found,
                                "note": "each pixel where the camera read it"}
        return out
    return source


def _skipped_decodes(results: list[dict], pose_id: str) -> int:
    return sum(1 for _, _, positions, verdict in _judged_decodes(results, pose_id)
               if verdict not in DECODE_VERDICTS or not positions)


# ── footprints as pictures ─────────────────────────────────────────────────

def _grid(fp: EmitterFootprint) -> np.ndarray:
    return np.asarray(fp.grid, dtype=np.float64).reshape(GRID_H, GRID_W)


def _soften(grid: np.ndarray) -> np.ndarray:
    """3x3 box mean: one noisy camera cell stops being a light of its own."""
    padded = np.pad(grid, 1, mode="edge")
    out = np.zeros_like(grid)
    for dy in range(3):
        for dx in range(3):
            out += padded[dy:dy + GRID_H, dx:dx + GRID_W]
    return out / 9.0


def light_core(grid: np.ndarray) -> tuple[float, float, float]:
    """(x, y, radius) of the brightest connected patch of a softened
    footprint: its weighted centre in the picture, and half its longer side
    as a share of the picture's WIDTH. Where the light is strongest, not
    where a fixture is."""
    peak = float(grid.max())
    if peak <= 0.0:
        return 0.5, 0.5, 0.0
    bright = grid >= CORE_FRACTION * peak
    start = np.unravel_index(int(np.argmax(grid)), grid.shape)
    seen = np.zeros_like(bright)
    stack = [(int(start[0]), int(start[1]))]
    seen[start] = True
    cells = []
    while stack:
        y, x = stack.pop()
        cells.append((y, x))
        for ny in range(max(0, y - 1), min(GRID_H, y + 2)):
            for nx in range(max(0, x - 1), min(GRID_W, x + 2)):
                if bright[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
    ys = np.array([c[0] for c in cells])
    xs = np.array([c[1] for c in cells])
    w = grid[ys, xs]
    cx = float(((xs + 0.5) * w).sum() / w.sum()) / GRID_W
    cy = float(((ys + 0.5) * w).sum() / w.sum()) / GRID_H
    wide = (xs.max() - xs.min() + 1) / GRID_W
    # a cell is as tall as it is wide: rows as a share of the WIDTH
    tall = (ys.max() - ys.min() + 1) / GRID_W
    return cx, cy, float(max(wide, tall) / 2.0)


def _glow(grid: np.ndarray, pose_peak: float) -> np.ndarray:
    """One emitter's glow picture, 0..1. Its SHAPE is the footprint as
    measured (linear in its own peak, the faint tail cut at GLOW_FLOOR). Its
    STRENGTH against the pose's other emitters is the square root of the
    measured ratio: a light the camera saw a tenth as bright still shows, at
    about a third, and the order of brightness is kept."""
    peak = float(grid.max())
    if peak <= 0.0 or pose_peak <= 0.0:
        return np.zeros_like(grid)
    own = grid / peak
    own[own < GLOW_FLOOR] = 0.0
    return own * np.sqrt(min(1.0, peak / pose_peak))


def _b64(values: np.ndarray) -> str:
    return base64.b64encode(
        np.clip(np.rint(values * 255.0), 0, 255).astype(np.uint8).tobytes()).decode("ascii")


# ── poses ──────────────────────────────────────────────────────────────────

def poses(rooms: list[RoomMap], results: list[dict]) -> list[dict]:
    """Every camera pose that has something to draw, newest first."""
    found: dict[str, dict] = {}
    for room in rooms:
        for fp in room.footprints:
            pose_id = fp.capture.pose_id
            if not pose_id or not (fp.mapped or fp.unseen):
                continue
            pose = found.setdefault(pose_id, {
                "pose_id": pose_id, "rooms": [], "mapped": 0, "unseen": 0,
                "decodes": 0, "captured_at": 0.0})
            if room.id not in [r["id"] for r in pose["rooms"]]:
                pose["rooms"].append({"id": room.id, "name": room.name})
            pose["mapped" if fp.mapped else "unseen"] += 1
            pose["captured_at"] = max(pose["captured_at"], float(fp.capture.captured_at))
    for result in results:
        pose_id = str(result.get("pose_id") or "")
        usable = [1 for _, _, positions, verdict in _judged_decodes([result], pose_id)
                  if verdict in DECODE_VERDICTS and positions]
        if not pose_id or not usable:
            continue
        pose = found.setdefault(pose_id, {
            "pose_id": pose_id, "rooms": [], "mapped": 0, "unseen": 0,
            "decodes": 0, "captured_at": 0.0})
        pose["decodes"] += len(usable)
        pose["captured_at"] = max(pose["captured_at"], float(result.get("at") or 0.0))
    out = sorted(found.values(), key=lambda p: p["captured_at"], reverse=True)
    for pose in out:
        names = [r["name"] for r in pose["rooms"]]
        pose["label"] = " + ".join(names) if names else f"Commissioning pose {pose['pose_id']}"
    return out


# ── the view ───────────────────────────────────────────────────────────────

def _runs(indices: np.ndarray) -> list[tuple[int, int]]:
    """Sorted indices as (first, count) runs of consecutive values."""
    if len(indices) == 0:
        return []
    breaks = np.nonzero(np.diff(indices) != 1)[0] + 1
    return [(int(part[0]), int(len(part))) for part in np.split(indices, breaks)]


def _resolve_fixtures(raw: dict, layout: dict) -> list[dict]:
    """The layout's fixtures with their per-pixel arrays (preview_layout.
    fixture_pixels), in the layout's own order."""
    from spectra.services import preview_layout

    devices = {str(d.get("id")): d for d in raw.get("devices") or [] if d.get("id")}
    by_id = {str(v.get("id")): v for v in raw.get("virtuals") or []}
    fixtures = []
    for shown in layout.get("virtuals") or []:
        virtual = by_id.get(shown["id"])
        resolved = preview_layout.fixture_pixels(virtual, devices) if virtual else None
        if resolved is None:
            continue
        kinds = {f["device_id"]: f for f in shown.get("fixtures") or []}
        for fx in resolved["fixtures"]:
            described = kinds.get(fx["device_id"])
            if described is None or described["count"] != len(fx["virtual_px"]):
                continue
            fixtures.append({
                "virtual_id": shown["id"], "device_id": fx["device_id"],
                "name": described["name"], "kind": described["kind"],
                "count": len(fx["virtual_px"]),
                "virtual_px": fx["virtual_px"], "device_px": fx["device_px"],
            })
    return fixtures


def _emitter_masks(fp: EmitterFootprint, fixtures: list[dict], raw: dict) -> dict[int, np.ndarray]:
    """Which pixels of which fixture one emitter lit: fixture index -> mask."""
    from spectra.services import preview_layout

    targets = [(i, fx) for i, fx in enumerate(fixtures) if fx["virtual_id"] == fp.carrier]
    if not targets:
        return {}
    if not fp.ranges:
        return {i: np.ones(fx["count"], dtype=bool) for i, fx in targets}
    devices = {str(d.get("id")): d for d in raw.get("devices") or [] if d.get("id")}
    by_id = {str(v.get("id")): v for v in raw.get("virtuals") or []}
    masks = {i: np.zeros(fx["count"], dtype=bool) for i, fx in targets}
    for rng in fp.ranges:
        if rng.virtual_id == fp.carrier:
            for i, fx in targets:
                masks[i] |= (fx["virtual_px"] >= rng.start) & (fx["virtual_px"] <= rng.end)
            continue
        # a range of ANOTHER virtual (a copy-mapped carrier is measured
        # through each fixture's own strip): find the device pixels it lit
        other = by_id.get(rng.virtual_id)
        resolved = preview_layout.fixture_pixels(other, devices) if other else None
        for lit in (resolved or {}).get("fixtures", []):
            inside = (lit["virtual_px"] >= rng.start) & (lit["virtual_px"] <= rng.end)
            device_px = lit["device_px"][inside]
            for i, fx in targets:
                if fx["device_id"] == lit["device_id"]:
                    masks[i] |= np.isin(fx["device_px"], device_px)
    return {i: m for i, m in masks.items() if m.any()}


def _piece_key(fx: dict, first: int, count: int) -> str:
    return f"{fx['virtual_id']}/{fx['device_id']}:{first}-{first + count - 1}"


def _piece_label(fx: dict, first: int, count: int) -> str:
    if count == fx["count"]:
        return fx["name"]
    if fx["kind"] in ("bulbs", "dot") and count == 1:
        noun = "lamp" if fx["kind"] == "bulbs" else "pixel"
        return f"{fx['name']} {noun} {first + 1}"
    return f"{fx['name']} px {first}–{first + count - 1}"


def build_view(pose_id: str, *, raw: dict, layout: dict, rooms: list[RoomMap],
               results: list[dict], hand: dict,
               sources: Optional[list[tuple[str, PixelSource]]] = None) -> Optional[dict]:
    """Pure: stored data in, one pose's view out. None for an unknown pose."""
    listed = {p["pose_id"]: p for p in poses(rooms, results)}
    pose = listed.get(pose_id)
    if pose is None:
        return None
    fixtures = _resolve_fixtures(raw, layout)
    notes: list[str] = []

    at_pose = [(room, fp) for room in rooms for fp in room.footprints
               if fp.capture.pose_id == pose_id and (fp.mapped or fp.unseen)]
    # a measured range beats a whole carrier, and seen beats unseen, when
    # two records claim one pixel
    at_pose.sort(key=lambda pair: (pair[1].unseen, pair[1].whole_carrier))

    soft = {id(fp): _soften(_grid(fp)) for _, fp in at_pose if fp.mapped}
    pose_peak = max((float(g.max()) for g in soft.values()), default=0.0)

    owner = [np.full(fx["count"], -1, dtype=np.int64) for fx in fixtures]
    claims: list[dict] = []
    emitters: list[dict] = []
    not_in_use = 0
    for room, fp in at_pose:
        masks = _emitter_masks(fp, fixtures, raw)
        if not masks:
            not_in_use += 1
            continue
        claim = {"source": "unseen" if fp.unseen else "footprint", "emitter": None,
                 "room": room.name, "label": fp.label or fp.emitter_id,
                 "note": fp.note if fp.unseen else "", "at": None}
        if fp.mapped and pose_peak > 0.0:
            grid = soft[id(fp)]
            x, y, radius = light_core(grid)
            glow = _glow(grid, pose_peak)
            claim["emitter"] = len(emitters)
            claim["at"] = (x, y, radius)
            emitters.append({
                "id": fp.emitter_id, "label": claim["label"], "room": room.name,
                "weight": round(float(fp.weight), 4), "centre": [round(x, 5), round(y, 5)],
                "glow": _b64(glow),
                # the fixture pixels whose live colour tints this glow —
                # every pixel it lit, wherever (or whether) each is drawn
                "pixels": [{"virtual_id": fixtures[i]["virtual_id"],
                            "device_id": fixtures[i]["device_id"],
                            "first": first, "count": count}
                           for i, mask in masks.items()
                           for first, count in _runs(np.nonzero(mask)[0])],
            })
        index = len(claims)
        claims.append(claim)
        for i, mask in masks.items():
            free = mask & (owner[i] < 0)
            owner[i][free] = index
    if not_in_use:
        notes.append(f"{not_in_use} measured emitter(s) of this pose belong to a "
                     "carrier that is not in use right now (or to pixels it no longer "
                     "has), so they are not drawn.")

    refs = [{"virtual_id": fx["virtual_id"], "device_id": fx["device_id"],
             "device_px": fx["device_px"]} for fx in fixtures]
    exact: dict[tuple[str, str], tuple[str, dict]] = {}
    all_sources = [("decode", decode_source(results))] if sources is None else sources
    for name, fn in list(all_sources) + (list(_sources) if sources is None else []):
        try:
            answered = fn(pose_id, refs) or {}
        except Exception:                                  # noqa: BLE001
            logger.exception("room_view: position source %s failed", name)
            notes.append(f"The position source \"{name}\" could not be read.")
            continue
        for key, value in answered.items():
            exact.setdefault(tuple(key), (name, value))
    skipped = _skipped_decodes(results, pose_id)
    if skipped:
        notes.append(f"{skipped} per-pixel camera read(s) of this pose are not drawn: "
                     "their own check failed, or they were stored before reads kept "
                     "their positions.")

    pieces: list[dict] = []
    for i, fx in enumerate(fixtures):
        taken = np.zeros(fx["count"], dtype=bool)
        hit = exact.get((fx["virtual_id"], fx["device_id"]))
        if hit:
            name, value = hit
            known = {int(j): xy for j, xy in (value.get("positions") or {}).items()
                     if 0 <= int(j) < fx["count"]}
            if known:
                js = sorted(known)
                first, count = js[0], js[-1] - js[0] + 1
                span = np.arange(first, first + count)
                xs = np.interp(span, js, [known[j][0] for j in js])
                ys = np.interp(span, js, [known[j][1] for j in js])
                xy = [round(float(v), 5) for pair in zip(xs, ys) for v in pair]
                note = str(value.get("note") or "")
                if len(js) < count:
                    note = (f"{note}; " if note else "") + (
                        f"{len(js)} of {count} pixels were read, the rest are drawn "
                        "between their neighbours")
                pieces.append({
                    "key": _piece_key(fx, first, count), "virtual_id": fx["virtual_id"],
                    "device_id": fx["device_id"], "first": first, "count": count,
                    "label": _piece_label(fx, first, count), "source": name,
                    "emitter": None, "at": None, "xy": xy, "cluster": False, "note": note})
                taken[first:first + count] = True
        for index in sorted(set(int(v) for v in owner[i][~taken]) - {-1}):
            claim = claims[index]
            for first, count in _runs(np.nonzero((owner[i] == index) & ~taken)[0]):
                pieces.append({
                    "key": _piece_key(fx, first, count), "virtual_id": fx["virtual_id"],
                    "device_id": fx["device_id"], "first": first, "count": count,
                    "label": _piece_label(fx, first, count), "source": claim["source"],
                    "emitter": claim["emitter"], "at": claim["at"], "xy": None,
                    "cluster": count < fx["count"] and fx["kind"] in ("strip", "frame"),
                    "note": claim["note"], "_claim": index})
        loose = np.nonzero((owner[i] < 0) & ~taken)[0]
        single = fx["kind"] in ("bulbs", "dot")
        for first, count in ([(int(j), 1) for j in loose] if single else _runs(loose)):
            pieces.append({
                "key": _piece_key(fx, first, count), "virtual_id": fx["virtual_id"],
                "device_id": fx["device_id"], "first": first, "count": count,
                "label": _piece_label(fx, first, count), "source": "unmapped",
                "emitter": None, "at": None, "xy": None, "cluster": False, "note": ""})

    # Pieces that share one footprint sit side by side at its centre.
    shared: dict[int, list[dict]] = {}
    for piece in pieces:
        if piece.get("at") is not None:
            shared.setdefault(piece["_claim"], []).append(piece)
    for members in shared.values():
        x, y, radius = members[0]["at"]
        n = len(members)
        for slot, piece in enumerate(members):
            if piece["cluster"]:
                r = min(MAX_CLUSTER_RADIUS, max(MIN_CLUSTER_RADIUS, radius / n))
            else:
                r = min(MAX_RADIUS, max(MIN_SHAPE_RADIUS, radius / n))
            centre = x + (slot - (n - 1) / 2.0) * 2.0 * r if n > 1 else x
            piece["at"] = {"x": round(min(1.0, max(0.0, centre)), 5), "y": round(y, 5),
                           "r": round(r, 5)}
    for piece in pieces:
        piece.pop("_claim", None)

    backdrop = None
    if soft and pose_peak > 0.0:
        total = sum(soft.values())
        backdrop = _b64(np.sqrt(np.clip(total / float(total.max()), 0.0, 1.0)))

    keys = {p["key"] for p in pieces}
    return {
        "pose_id": pose_id, "label": pose["label"], "rooms": pose["rooms"],
        "captured_at": pose["captured_at"],
        "grid": {"w": GRID_W, "h": GRID_H}, "aspect": GRID_W / GRID_H,
        "backdrop": backdrop, "emitters": emitters, "pieces": pieces,
        "hand": {k: v for k, v in hand.items() if k in keys},
        "notes": notes, "layout_source": layout.get("source"),
    }


# ── the hand-placement store ───────────────────────────────────────────────

class Placement(BaseModel):
    """Where he put one piece, in the pose's picture: its centre (x, y in
    0..1 of the frame), its longest side as a share of the picture's width,
    and its turn in degrees."""
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    size: float = Field(gt=0.0, le=1.0)
    angle: float = Field(default=0.0, ge=-360.0, le=360.0)


def _load_store() -> dict:
    path = config.ROOM_VIEW_FILE
    try:
        if not os.path.exists(path):
            return {"poses": {}}
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data.get("poses"), dict) else {"poses": {}}
    except Exception:                                      # noqa: BLE001
        logger.exception("room_view: unreadable placement store %s", path)
        return {"poses": {}}


def load_placements(pose_id: str) -> dict:
    entry = _load_store()["poses"].get(pose_id) or {}
    return dict(entry.get("placements") or {})


def put_placements(pose_id: str, patch: dict[str, Optional[Placement]]) -> dict:
    """Merge a partial update into one pose's placements (None removes a
    key) and return what is stored. Atomic tmp+replace."""
    with _write_lock:
        store = _load_store()
        entry = store["poses"].setdefault(pose_id, {"placements": {}})
        placements = dict(entry.get("placements") or {})
        for key, value in patch.items():
            if value is None:
                placements.pop(key, None)
            else:
                placements[key] = value.model_dump()
        if len(placements) > MAX_PLACEMENTS_PER_POSE:
            raise ValueError(f"a pose holds at most {MAX_PLACEMENTS_PER_POSE} placements")
        entry["placements"] = placements
        entry["updated_at"] = time.time()
        path = config.ROOM_VIEW_FILE
        os.makedirs(os.path.dirname(str(path)) or ".", exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(str(path)) or ".",
                                   prefix="room_view", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(store, fh, indent=2)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return placements


# ── against the stored room ────────────────────────────────────────────────

def _stored():
    from spectra.services import commissioning, light_field
    return light_field.load_rooms(), commissioning.load_results()


def current_poses() -> list[dict]:
    rooms, results = _stored()
    return poses(rooms, results)


def current_view(pose_id: str) -> Optional[dict]:
    from spectra.services import device_console, preview_layout

    rooms, results = _stored()
    return build_view(
        pose_id, raw=device_console._read_stored_config(),
        layout=preview_layout.current_layout(), rooms=rooms, results=results,
        hand=load_placements(pose_id))
