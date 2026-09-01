"""ROOMS + the light-field mapping wire.

  GET    /api/rooms                       every room, with each emitter's
                                          mapped/not state and a small heat
                                          thumbnail (numbers, not an image)
  POST   /api/rooms                       create / update a room (name,
                                          carriers, axis calibration)
  DELETE /api/rooms/{room_id}             remove a room (its footprints go
                                          with it — a map belongs to a pose,
                                          and a deleted room has no pose)
  GET    /api/rooms/carriers              what the Room Builder picks from:
                                          the genuinely-driven carriers whose
                                          chain reaches a light-emitting
                                          fixture (spectra/services/
                                          carriers.py is the criterion)
  WS     /api/rooms/map/ws                the phone's capture session
  GET    /api/rooms/map/status            live session status + refusal
  GET    /api/rooms/map/frame/latest      newest tapped frame, as an 8-bit
                                          greyscale PGM, for checking aim
  GET    /api/rooms/{room_id}/plan        what a run at a given granularity
                                          WOULD light, and for how long —
                                          read-only, so a nineteen-emitter
                                          run is never a surprise
  POST   /api/rooms/{room_id}/map         RUN the mapping protocol at the
                                          granularity chosen for THIS run
  POST   /api/rooms/{room_id}/commission
  POST   /api/rooms/commission/{mapper_id} RUN the commissioning
                                          ground-truth test: gray-code one
                                          stored composition and judge the
                                          comparison frozen in the plan
  GET    /api/rooms/commission/results    the judged tables of recent runs
  GET    /api/rooms/{room_id}/footprint/{emitter_id}
                                          one footprint's full grid

THE RUN IS THE ONLY ROUTE HERE THAT TOUCHES A LIGHT, and it refuses before
it does so when the phone's camera is not locked — the refusal names the
phone and the capability rather than saying "mapping failed"
(spectra/services/mapping_session.py's docstring is the binding statement).
Everything else is a read or a store write.

GRANULARITY IS PER RUN, never a stored global: `granularity` and
`block_pixels` are arguments to the map/plan routes. The room remembers the
last values only so the page's control comes back where he left it, which
is a different thing from a setting the runs read
(spectra/services/emitters.py is the binding statement for what each
granularity means).

Nothing here decides where a fixture is. The map records where each
emitter's light LANDS (spectra/models/room_map.py); a sub-device emitter's
id names a PIXEL RANGE, which is an addressing fact from the device
configuration and never a position in the room.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from spectra.models.room_map import AxisCalibration, RoomMap
from spectra.services import emitters as emitters_mod
from spectra.services import commission_compare
from spectra.services import (commissioning, light_field, mapping_refusals,
                              mapping_session, room_mapping)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["spectra-rooms"])

#: One mapping run at a time, process-wide — a second one would fight the
#: first for the held room and for the same phone's frames.
_run_lock = asyncio.Lock()
_running: Optional[str] = None


class RoomBody(BaseModel):
    id: Optional[str] = None
    name: str
    carrier_ids: list[str] = []
    axis: Optional[AxisCalibration] = None
    granularity: Optional[str] = None
    block_pixels: Optional[int] = None


class MapBody(BaseModel):
    """What THIS run does, all optional: an omitted granularity means the
    room's own remembered choice (itself only a seed for the page's
    control), and an omitted settle means the shipped protocol exactly.

    All FOUR protocol waits are exposed — the two settles and the two
    CAPTURE windows — because the speed sweep varies one knob at a time and
    cannot do that with only half of them. They are BOUNDED server-side
    (`room_mapping.clamp_settle` / `clamp_capture`), so a stray number falls
    back to the default rather than refusing a run or holding the room dark
    for a minute.

    ONE THING NOT TO MIS-READ IN A SWEEP: at the phone's fixed ~5 fps,
    `lit_capture_s` IS the frame count — dwell and frames-averaged are one
    knob, not two (room_mapping's own note above MIN_CAPTURE_S)."""
    granularity: Optional[str] = None
    block_pixels: Optional[int] = None
    dark_settle_s: Optional[float] = None
    lit_settle_s: Optional[float] = None
    dark_capture_s: Optional[float] = None
    lit_capture_s: Optional[float] = None


class CommissionBody(BaseModel):
    """What THIS commissioning run does. `mapper_id` names the stored
    composition to check (defaulting to the room's only carrier when it has
    exactly one, so the common case needs no body at all); `repeat` runs the
    stack twice back to back, so two independent decodes bound the
    instrument's own noise.

    `targets` NAMES WHAT TO COMMISSION, and per the captain's ruling
    (2026-09-01) the useful answer is almost never the stitched whole:

      omitted        the whole composition — the original behaviour, kept,
                     and on his own tv-mapper it refuses as IMPOSSIBLE
                     within four seconds with the arithmetic
                     (`gray_code.MIN_CAMERA_PX_PER_INDEX`).
      ["fixtures"]   one run per fixture. `per_fixture: true` is the same
                     thing spelled as a switch.
      ["segments"]   one run per stored segment, finer still.
      explicit       "device:<id>" / "segment:<n>", any mixture.

    Every target is judged by the SAME frozen table against the stored
    composition's own slice of ground truth, and the set aggregates back
    into one table of the same five rows
    (`commission_compare.aggregate`)."""
    mapper_id: Optional[str] = None
    repeat: int = 1
    targets: Optional[list[str]] = None
    per_fixture: bool = False


def _run_granularity(room: RoomMap, granularity: Optional[str],
                     block_pixels: Optional[int]) -> tuple[str, int]:
    g = (granularity or room.granularity or emitters_mod.DEFAULT_GRANULARITY)
    g = g.strip().lower()
    g = emitters_mod.GRANULARITY_ALIASES.get(g, g)
    if g not in emitters_mod.GRANULARITIES:
        g = emitters_mod.DEFAULT_GRANULARITY
    try:
        block = int(block_pixels if block_pixels is not None
                    else (room.block_pixels or emitters_mod.DEFAULT_BLOCK_PIXELS))
    except (TypeError, ValueError):
        block = emitters_mod.DEFAULT_BLOCK_PIXELS
    block = max(emitters_mod.MIN_BLOCK_PIXELS,
                min(emitters_mod.MAX_BLOCK_PIXELS, block))
    return g, block


def _room_view(room: RoomMap) -> dict:
    # A thumbnail is normalized to its OWN peak, so it is blind to the
    # magnitude it normalized away: every row carries its WEIGHT, and one
    # that is whisper signal against the rest of this room says so.
    faint = set(light_field.faint_ids(room))
    weights = [f.weight for f in room.footprints if f.mapped]
    peak = max(weights) if weights else 0.0
    fps = []
    for f in room.footprints:
        fps.append({
            "emitter_id": f.emitter_id, "label": f.label,
            "carrier_id": f.carrier, "whole_carrier": f.whole_carrier,
            "ranges": [r.model_dump() for r in f.ranges],
            "virtual_ids": f.virtual_ids, "mapped": f.mapped,
            # An emitter that RAN and whose light this pose could not see.
            # Sent so the page can render it AS THAT, beside the mapped
            # thumbnails, rather than as a piece nobody has tried yet.
            "unseen": f.unseen, "note": f.note, "retried": f.retried,
            "weight": round(f.weight, 4),
            "faint": f.emitter_id in faint,
            #: this footprint's weight as a fraction of the strongest in the
            #: SAME room — the only comparison a relative measurement allows
            "weight_share": round(f.weight / peak, 4) if peak > 0 else 0.0,
            "axis_profile": [round(v, 5) for v in f.axis_profile],
            "thumbnail": light_field.thumbnail(f),
            "capture": f.capture.model_dump(),
        })
    return {**room.model_dump(exclude={"footprints"}),
            "footprints": fps,
            "mapped_ids": room.mapped_ids(),
            "mapped_carriers": room.mapped_carriers(),
            "unmapped_ids": room.unmapped_ids(),
            "unseen_ids": room.unseen_ids(),
            "faint_ids": sorted(faint),
            "peak_weight": round(peak, 4)}


@router.get("/rooms")
async def list_rooms():
    return {"rooms": [_room_view(r) for r in light_field.load_rooms()]}


@router.post("/rooms")
async def upsert_room(body: RoomBody):
    """Create or update. An existing room keeps its FOOTPRINTS across an
    edit — renaming a room or adding a carrier must not silently discard
    measurements that took a dark room to collect. Removing a carrier DOES
    drop its footprint: it is no longer part of this room."""
    existing = light_field.get_room(body.id) if body.id else None
    room = existing or RoomMap(name=body.name)
    room.name = body.name
    room.carrier_ids = list(dict.fromkeys(body.carrier_ids))
    if body.axis is not None:
        room.axis = body.axis
    if body.granularity is not None:
        room.granularity = _run_granularity(room, body.granularity, None)[0]
    if body.block_pixels is not None:
        room.block_pixels = _run_granularity(room, None, body.block_pixels)[1]
    keep = set(room.carrier_ids)
    # Matched on the footprint's CARRIER, not its emitter id: a carrier
    # mapped per segment carries several emitter ids and none of them is the
    # carrier id, so an emitter-id match would silently discard every
    # measurement taken at a sub-device granularity on the next room edit.
    room.footprints = [f for f in room.footprints if f.carrier in keep]
    return _room_view(light_field.put_room(room))


@router.delete("/rooms/{room_id}")
async def remove_room(room_id: str):
    if not light_field.delete_room(room_id):
        return JSONResponse(status_code=404, content={"detail": "no such room"})
    return {"deleted": room_id}


@router.get("/rooms/carriers")
async def room_carriers():
    """What the Room Builder picks from — the CARRIERS, not the fixtures.

    His words: "i want to be able to work with the devices that i directly
    use in spectra even if they have layers of virtuals before shining."
    A carrier is a genuinely-driven virtual whose chain reaches at least one
    light-emitting fixture; `spectra/services/carriers.py` owns that
    criterion and the reasoning, including why it is a different question
    from the /devices page's `in_use` (which is unchanged and still lists
    every fixture, dummies included).

    `hidden` names the driven carriers a camera could not see, so "where is
    radial-dummy" has an answer rather than a shrug."""
    from spectra.services import carriers, device_console
    listing = await device_console.list_devices()
    entries = listing.get("devices") or []
    names = {d.get("id"): (d.get("config") or {}).get("name") or d.get("id")
             for d in entries}
    rows = [{**row, "device_names": [names.get(d, d) for d in row["devices"]]}
            for row in carriers.carrier_rows(entries)]
    return {"carriers": rows, "hidden": carriers.hidden_rows(entries),
            "source": listing.get("source")}


@router.get("/rooms/map/status")
async def map_status():
    return {**mapping_session.status(),
            "running_room": _running,
            "granularities": list(emitters_mod.GRANULARITIES),
            "block_pixels_default": emitters_mod.DEFAULT_BLOCK_PIXELS,
            "max_emitters_per_run": emitters_mod.MAX_EMITTERS_PER_RUN,
            "protocol": {
                "dark_settle_s": room_mapping.DARK_SETTLE_S,
                "dark_capture_s": room_mapping.DARK_CAPTURE_S,
                "lit_settle_s": room_mapping.LIT_SETTLE_S,
                "lit_capture_s": room_mapping.LIT_CAPTURE_S,
                "min_frames": room_mapping.MIN_FRAMES,
            }}


@router.get("/rooms/map/frame/latest")
async def map_frame_latest():
    """The newest tapped frame, so a human can check the phone's aim.

    Served as a binary PGM (P5) — the raw greyscale bytes with a 15-byte
    header — because that is what arrived; re-encoding it would put an
    image library in a path that needs none, and this is a diagnostic view,
    not an asset. Never stored."""
    sess = mapping_session.current
    frame = sess.frames.latest() if (sess is not None and not sess.closed) else None
    if frame is None:
        return JSONResponse(status_code=404, content={"detail": "no tapped frame"})
    header = f"P5\n{frame.width} {frame.height}\n255\n".encode("ascii")
    return Response(content=header + frame.data, media_type="image/x-portable-graymap",
                    headers={"Cache-Control": "no-store"})


@router.get("/rooms/{room_id}/plan")
async def plan_map(room_id: str, granularity: Optional[str] = None,
                   block_pixels: Optional[int] = None):
    """What a run at this granularity WOULD light, without lighting it.

    Read-only and camera-free, deliberately: a nineteen-emitter run takes
    the room dark for over a minute, which is a different act from a
    two-emitter one, and he should see which he is about to press rather
    than learn it from a progress bar. It reports the granularity each
    carrier actually resolves to (his "auto" default is per carrier) and
    everything the enumeration declined to split, by name."""
    room = light_field.get_room(room_id)
    if room is None:
        return JSONResponse(status_code=404, content={"detail": "no such room"})
    g, block = _run_granularity(room, granularity, block_pixels)
    deps = room_mapping.production_deps(None)
    try:
        scope = await room_mapping.live_virtual_ids(deps.get_virtuals)
        plan = await room_mapping.resolve_plan(room, deps, scope, g, block)
    except Exception as exc:                           # noqa: BLE001
        # An ownership state is an ANTICIPATED condition on this path, not a
        # server fault: it gets its own sentence and a 409, the same one the
        # run itself gives, so the plan and the run never describe his room
        # differently. Anything else is still a 503 with what went wrong.
        named = mapping_refusals.ownership_refusal(exc)
        if named is not None:
            return JSONResponse(status_code=409, content={
                "detail": named, "refusal": "ownership"})
        logger.exception("rooms: the plan read failed for %s", room_id)
        return JSONResponse(status_code=503, content={
            "detail": f"cannot read the live virtuals: {exc}"})
    body = plan.as_dict()
    # BEFORE THE COST: the run is now ONE continuous dark room from the first
    # emitter to the last, so how long it may hold that room belongs beside
    # the emitter count — and a plan past the hard cap says so here rather
    # than half-way through a dark room. It is a REFUSAL, not a correction:
    # nothing here changes his granularity or block size to make it fit.
    if body.get("too_long"):
        body["problems"] = list(body.get("problems") or []) + [body["too_long"]]
    body["sub_device"] = any(not e.whole_carrier for e in plan.emitters)
    body["spectra_owns"] = room_mapping.spectra_owns_lights()
    if body["sub_device"] and not body["spectra_owns"]:
        body["problems"] = list(body["problems"]) + [
            "SPECTRA is not driving the lights, so a sub-device run would be "
            "refused: the range lamp lives in this process."]
    return body


@router.post("/rooms/{room_id}/map")
async def run_map(room_id: str, body: Optional[MapBody] = None):
    """Run the mapping protocol for every emitter in this room, at the
    granularity chosen for THIS run.

    One run at a time; a second request while one is live is refused by
    name rather than queued — two runs would fight over the same held room
    and the same phone."""
    global _running
    room = light_field.get_room(room_id)
    if room is None:
        return JSONResponse(status_code=404, content={"detail": "no such room"})
    sess = mapping_session.current
    if sess is None or sess.closed:
        return JSONResponse(status_code=409, content={
            "detail": "no phone connected — open this page on the phone that "
                      "will do the capture and start its camera"})
    if _run_lock.locked():
        return JSONResponse(status_code=409, content={
            "detail": f"a mapping run is already in progress ({_running})"})
    g, block = _run_granularity(room, body.granularity if body else None,
                                body.block_pixels if body else None)
    async with _run_lock:
        _running = room_id
        try:
            result = await room_mapping.run_mapping(
                room, room_mapping.production_deps(sess),
                granularity=g, block_pixels=block,
                dark_settle_s=body.dark_settle_s if body else None,
                lit_settle_s=body.lit_settle_s if body else None,
                dark_capture_s=body.dark_capture_s if body else None,
                lit_capture_s=body.lit_capture_s if body else None)
        except Exception as exc:                       # noqa: BLE001
            # The backstop for the thing that started this: an ownership
            # refusal reached him as a bare 500 and a stack trace, for a
            # condition one press of the ownership bar fixes. run_mapping
            # states these itself now; this catches any that reach the route
            # from a seam it does not wrap, so the SENTENCE is what he sees
            # either way. A genuine bug still 500s — it should.
            named = mapping_refusals.ownership_refusal(exc)
            if named is None:
                raise
            return JSONResponse(status_code=409, content={
                "detail": named, "refusal": "ownership"})
        finally:
            _running = None
    # Remember the choice for the page's control only — a run always takes
    # its own granularity as an argument, so this is never what one reads.
    stored = light_field.get_room(room_id) or room
    if (stored.granularity, stored.block_pixels) != (g, block):
        stored.granularity, stored.block_pixels = g, block
        light_field.put_room(stored)
    out = result.as_dict()
    out["room"] = _room_view(light_field.get_room(room_id) or stored)
    return out


@router.get("/rooms/commission/results")
async def commission_results(limit: int = 5):
    """The judged tables of recent runs, newest first — including refused
    ones, which are a fact about the evening too."""
    rows = commissioning.load_results()[-max(1, min(50, limit)):]
    return {"results": list(reversed(rows)),
            "tolerances": {
                "seen_min_fraction": commission_compare.SEEN_MIN_FRACTION,
                "order_max_outlier_fraction":
                    commission_compare.ORDER_MAX_OUTLIER_FRACTION,
                "arrangement_max_error": commission_compare.ARRANGEMENT_MAX_ERROR,
                "stitch_max_error": commission_compare.STITCH_MAX_ERROR,
                "latency_tolerance_ms": commission_compare.LATENCY_TOLERANCE_MS}}


@router.post("/rooms/{room_id}/commission")
async def run_commission(room_id: str, body: Optional[CommissionBody] = None):
    """THE COMMISSIONING GROUND-TRUTH TEST (the plan's §8), runnable with
    nothing live but the camera session: gray-code the stored composition,
    decode where every pixel is, and judge the comparison FROZEN in the plan
    before any run — `spectra/services/commission_compare.py` quotes that
    table verbatim and owns every tolerance.

    UNATTENDED-SAFE, deliberately: it takes no judgment call at runtime.
    Either the frozen table is judged and returned (verdict pass / findings
    / incomplete / fail, each red row attributed to the side the table's own
    right-hand column names), or the run refuses BY NAME with nothing
    written. Every result is stored either way.

    PER TARGET, on the captain's ruling — see `CommissionBody.targets`. A
    per-fixture run is the SAME pre-registered comparison on a slice of the
    same stored ground truth, aggregated back into the same five rows; a
    target the camera cannot read SAFELY from this pose refuses by name and
    the next fixture is still asked, with the unread one reported as
    unmeasured rather than dropped from the denominator.

    One run at a time, sharing the mapping run's own lock — both hold the
    room and both consume the same phone's frames, so a second one would
    fight the first for both."""
    global _running
    room = light_field.get_room(room_id)
    if room is None:
        return JSONResponse(status_code=404, content={"detail": "no such room"})
    mapper_id = (body.mapper_id if body else None) or _only_carrier(room)
    if not mapper_id:
        return JSONResponse(status_code=400, content={
            "detail": f"name the composition to commission — this room has "
                      f"{len(room.carrier_ids)} carriers "
                      f"({', '.join(room.carrier_ids) or 'none'})"})
    sess = mapping_session.current
    if sess is None or sess.closed:
        return JSONResponse(status_code=409, content={
            "detail": "no phone connected — open this page on the phone that "
                      "will do the capture and start its camera"})
    if _run_lock.locked():
        return JSONResponse(status_code=409, content={
            "detail": f"a run is already in progress ({_running})"})
    async with _run_lock:
        _running = f"{room_id}/commission"
        try:
            result = await commissioning.run_commission(
                mapper_id, room_mapping.production_deps(sess),
                repeat=(body.repeat if body else 1),
                targets=_commission_targets(body))
        except Exception as exc:                       # noqa: BLE001
            named = mapping_refusals.ownership_refusal(exc)
            if named is None:
                raise
            return JSONResponse(status_code=409, content={
                "detail": named, "refusal": "ownership"})
        finally:
            _running = None
    stored = commissioning.save_result(result)
    if not result.ok:
        # A REFUSAL IS NOT A SERVER FAULT and is not a failed comparison
        # either: 409 with the sentence, and the stored record, so an
        # unattended caller can tell "we could not run" from "we ran and a
        # row is red" without parsing prose.
        return JSONResponse(status_code=409, content=stored)
    return stored


def _commission_targets(body: Optional[CommissionBody]) -> Optional[list[str]]:
    """`targets` wins when it is given; `per_fixture` is the switch form of
    `["fixtures"]`; neither means the whole composition, unchanged."""
    if body is None:
        return None
    if body.targets:
        return list(body.targets)
    if body.per_fixture:
        return [commissioning.TARGET_FIXTURES]
    return None


def _only_carrier(room: RoomMap) -> str:
    return room.carrier_ids[0] if len(room.carrier_ids) == 1 else ""


@router.get("/rooms/{room_id}/footprint/{emitter_id}")
async def get_footprint(room_id: str, emitter_id: str):
    room = light_field.get_room(room_id)
    fp = room.footprint(emitter_id) if room else None
    if fp is None:
        return JSONResponse(status_code=404, content={"detail": "not mapped"})
    from spectra.models.room_map import GRID_H, GRID_W
    return {"emitter_id": fp.emitter_id, "width": GRID_W, "height": GRID_H,
            "grid": fp.grid, "axis_profile": fp.axis_profile,
            "weight": fp.weight, "capture": fp.capture.model_dump()}


@router.websocket("/rooms/map/ws")
async def rooms_map_ws(ws: WebSocket):
    await ws.accept()
    sess = await mapping_session.open_session(ws.send_json)
    try:
        while True:
            msg = await ws.receive_json()
            if isinstance(msg, dict):
                await sess.handle(msg)
    except WebSocketDisconnect:
        pass
    except Exception:
        # A malformed message must not leave a run holding the room: the
        # session close below drops every ring, and any hold in flight is
        # reverted by flare_preview_hold's own sweep on its own clock.
        logger.exception("room mapping ws: session %s failed", sess.id)
    finally:
        sess.run_abort = sess.run_abort or "the phone disconnected"
        await mapping_session.close_session(sess)
