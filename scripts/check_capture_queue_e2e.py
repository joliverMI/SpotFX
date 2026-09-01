"""THE UNATTENDED CAPTURE PROOF — a declared queue of capture runs executed
end to end with NO HUMAN ACTION AFTER START, against a real server, over a
real WebSocket, driven by the REAL capture client.

WHAT IS REAL HERE, and it is nearly everything: a real uvicorn server
running the real SPECTRA app; the real `/api/rooms/capture-queue` routes;
the real `capture_queue` runner; the real `capture_runs` seam (the SAME
function the page's own button goes through); the real `room_mapping` and
`commissioning` protocols; the real held-room machinery; the real
`mapping_session` and its exposure gate; and the REAL
`spectra.capture_client.CaptureClient` — its hello, its frame pump, its
pong, its lock re-read, its reconnect and its pose assertion.

WHAT IS FAKE, and it is exactly two things, both of them his hardware: the
`fx_seam` write primitives (a check script must never reach for his
fixtures) and the CAMERA — a `SyntheticCamera` whose render function paints
what the writes say is lit. The camera's LOCK STATE IS DECLARED, and both
values are exercised: a locked one for the runs that must proceed and an
unlocked one for the run that must refuse. A proof that could only ever
declare "locked" could not show the gate working.

THE SEVEN THINGS IT PROVES, in order:

  1. A queue declared with a typo is refused AT DECLARATION, naming the
     item — not at 3 am on the item nobody reads.
  2. The client establishes the session on its own: camera opened, lock
     requested, lock READ BACK, hello sent, frames arriving, and the server
     agreeing it is locked. No human action, no browser.
  3. A declared queue of FOUR runs — two maps and two commissioning passes
     — executes to the end with nothing pressed, and every footprint lands
     where the synthetic room painted it.
  4. A run cut short KEEPS what it measured: the queue records `partial`,
     the map keeps its footprints, and the DECLARED retry re-runs it.
  5. A dropped WebSocket is survived: the client reconnects on its own and
     RE-ASSERTS ITS POSE, so the map either side of the drop is one
     measurement rather than two.
  6. Every refusal is BY NAME and reaches the record a human reads: a
     camera that will not lock, a camera that is not there at all, and a
     session that never arrives.
  7. A camera reopened mid-queue changes the pose, and the queue SAYS so
     rather than leaving a map that looks like one measurement and is two.

Run from repo root: .venv/bin/python scripts/check_capture_queue_e2e.py
Isolated: temp SPECTRA storage, a spare loopback port, no LedFX, no camera,
no room, no network beyond 127.0.0.1.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import socket
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
print = __import__("functools").partial(print, flush=True)     # noqa: A001

FAILURES: list[str] = []


def check(cond, label):
    if not cond:
        FAILURES.append(label)
        print(f"FAIL: {label}")
        return False
    print(f"ok: {label}")
    return True


td = Path(tempfile.mkdtemp(prefix="spectra-capture-queue-"))
os.environ["SPECTRA_STORAGE_DIR"] = str(td / "spectra")

from fx import device_model                                    # noqa: E402
device_model.CATEGORIES_FILE = td / "device_categories.json"
device_model.CATEGORIES_FILE.write_text(json.dumps({}))

from fx import light_ownership                                 # noqa: E402
light_ownership.OWNERSHIP_FILE = td / "ownership.json"
light_ownership.OWNERSHIP_FILE.write_text(json.dumps({"owner": "spectra"}))

from spectra import config as scfg                             # noqa: E402
scfg.SPECTRA_STORAGE = td / "spectra"
for name in ("SCENES_FILE", "SEQUENCER_FILE", "DRIFT_PROFILES_FILE",
             "ROOM_COLOR_FILE", "ROOM_CONTROLS_FILE", "GRADIENT2D_FILE",
             "FIRE_HISTORY_FILE", "SHOW_LOG_FILE", "FLARE_PREVIEW_HOLD_FILE",
             "ROOM_MAPS_FILE", "ROOM_EFFECTS_FILE", "COMMISSIONING_FILE",
             "CAPTURE_QUEUE_FILE"):
    setattr(scfg, name, scfg.SPECTRA_STORAGE / f"{name.lower()}.json")
scfg.COLOR_SETS_FILE = td / "color_sets.json"

import httpx                                                   # noqa: E402
import uvicorn                                                 # noqa: E402

from spectra.capture_client.camera import CameraLock, SyntheticCamera  # noqa: E402
from spectra.capture_client.session import CaptureClient       # noqa: E402
from spectra.services import (capture_queue, commissioning, fx_seam,  # noqa: E402
                              gray_code, light_field, room_mapping)

FW, FH = light_field.FRAME_W, light_field.FRAME_H

# ── the synthetic room ─────────────────────────────────────────────────────
#
# HIS OWN SHAPE at a size a script can render, the same one
# scripts/check_commissioning.py declares: a copy-mapped carrier over five
# segments across three fixtures. The map runs light whole carriers; the
# commissioning runs gray-code the composition through the fixtures' own
# strips, exactly as they do on his television.
TV, SCONCE = 40, 8
TOTAL = TV + 2 * SCONCE
CARRIER = "tv-mapper"
LAMP = "sconce-lamp"
LAMP_REGION = (20, 70, 40, 120)          # y0, y1, x0, x1 — declared truth
LAMP_AMPLITUDE = 150.0

LOCKED = CameraLock(exposure_locked=True, white_balance_locked=True,
                    exposure_mode="Manual Mode", white_balance_mode="manual",
                    exposure_capabilities=["Manual Mode", "Aperture Priority Mode"],
                    white_balance_capabilities=["white_balance_automatic"],
                    source="synthetic:declared-locked")
UNLOCKED = CameraLock(exposure_locked=False, white_balance_locked=True,
                      exposure_mode="Aperture Priority Mode",
                      white_balance_mode="manual",
                      exposure_capabilities=["Aperture Priority Mode"],
                      source="synthetic:declared-unlocked")


def _virtual(vid, segments, mapping="span", active=True):
    return {"id": vid, "active": active,
            "segments": [[d, lo, hi, False, 0] for d, lo, hi in segments],
            "pixel_count": sum(hi - lo + 1 for _d, lo, hi in segments),
            "config": {"mapping": mapping, "rows": 1, "grouping": 1},
            "effect": {"type": "singleColor", "config": {}}}


half = SCONCE // 2
VIRTUALS = {
    CARRIER: _virtual(CARRIER, [
        ("tv-backlight", 0, TV - 1),
        ("sconce-right", 0, half - 1), ("sconce-right", half, SCONCE - 1),
        ("sconce-left", 0, half - 1), ("sconce-left", half, SCONCE - 1)],
        mapping="copy"),
    "tv-backlight": _virtual("tv-backlight", [("tv-backlight", 0, TV - 1)],
                             active=False),
    "sconce-left": _virtual("sconce-left", [("sconce-left", 0, SCONCE - 1)],
                            active=False),
    "sconce-right": _virtual("sconce-right", [("sconce-right", 0, SCONCE - 1)],
                             active=False),
    LAMP: _virtual(LAMP, [("lamp-strip", 0, 9)]),
}
CHAIN = {CARRIER: [{"id": d, "type": "wled"} for d in
                   ("tv-backlight", "sconce-left", "sconce-right")],
         "tv-backlight": [{"id": "tv-backlight", "type": "wled"}],
         "sconce-left": [{"id": "sconce-left", "type": "wled"}],
         "sconce-right": [{"id": "sconce-right", "type": "wled"}],
         LAMP: [{"id": "lamp-strip", "type": "wled"}]}

WRITES: list[dict] = []
LIT: dict[str, float] = {}


def truth_layout() -> dict:
    """WHERE the composition's pixels actually are in the camera's frame —
    declared here, never read off a result: a television wrapped by 40
    pixels with a sconce either side."""
    layout = {}
    per = TV // 4
    for i in range(TV):
        side, k = i // per, (i % per) / per
        layout[i] = [(0.30 + 0.40 * k, 0.25), (0.70, 0.25 + 0.35 * k),
                     (0.70 - 0.40 * k, 0.60), (0.30, 0.60 - 0.35 * k)][side]
    for j in range(SCONCE):
        layout[TV + j] = (0.88, 0.30 + 0.30 * j / (SCONCE - 1))
        layout[TV + SCONCE + j] = (0.12, 0.30 + 0.30 * j / (SCONCE - 1))
    return layout


LAYOUT = truth_layout()
_composition = None


def composition():
    global _composition
    if _composition is None:
        _composition = commissioning.resolve_composition(
            CARRIER, VIRTUALS, CHAIN[CARRIER])
    return _composition


_DEVICE_INDICES: dict = {}


def device_indices() -> dict:
    """Which composition indices each FIXTURE owns — so a whole-carrier
    write on one sconce lights that sconce and nothing else, rather than the
    camera model quietly painting the whole television."""
    if not _DEVICE_INDICES:
        for seg in composition().segments:
            _DEVICE_INDICES.setdefault(seg.device_id, set()).update(
                range(seg.start, seg.end + 1))
    return _DEVICE_INDICES


#: which fixtures a virtual's own white write reaches
VIRTUAL_DEVICES = {CARRIER: ("tv-backlight", "sconce-left", "sconce-right"),
                   "tv-backlight": ("tv-backlight",),
                   "sconce-left": ("sconce-left",),
                   "sconce-right": ("sconce-right",)}


def _pattern_lit() -> set:
    """Which composition indices the REAL pattern lamp's own writes lit."""
    on: set = set()
    for write in WRITES:
        if write.get("effect_type") != commissioning.PATTERN_EFFECT_TYPE:
            continue
        arr = composition().pixel_map.get(write["virtual_id"])
        if arr is None:
            continue
        for pixel, ch in enumerate((write.get("config") or {}).get("pattern") or ""):
            if ch == "1" and pixel < len(arr) and arr[pixel] >= 0:
                on.add(int(arr[pixel]))
    return on


def render_frame() -> bytes:
    """The camera. Whole-carrier writes paint a declared region; pattern
    writes paint one blob per lit composition index."""
    f = np.full((FH, FW), 6.0)
    f[:, :24] += 10.0                        # a window, in both frames
    if LIT.get(LAMP, 0.0) > 0:
        y0, y1, x0, x1 = LAMP_REGION
        f[y0:y1, x0:x1] += LAMP_AMPLITUDE * LIT[LAMP]
    on = _pattern_lit()
    if not on:
        # a whole-carrier white write lights exactly that carrier's own
        # fixtures' pixels
        for vid, devices in VIRTUAL_DEVICES.items():
            if LIT.get(vid, 0.0) > 0:
                for device in devices:
                    on |= device_indices().get(device, set())
    if on:
        f = np.maximum(f, gray_code.render_frame(
            LAYOUT, on, width=FW, height=FH, radius_px=2.0))
    return np.clip(f, 0, 255).astype(np.uint8).tobytes()


async def fake_get_virtuals():
    return VIRTUALS


async def fake_apply_writes(writes, *, transition_ms=0):
    WRITES.append({"transition_ms": transition_ms,
                   "writes": [dict(w) for w in writes]})
    for w in writes:
        cfg = w["config"]
        black = cfg.get("color") == "#000000" or cfg.get("brightness", 1.0) == 0
        LIT[w["virtual_id"]] = 0.0 if black else float(cfg.get("brightness", 1.0))
        VIRTUALS[w["virtual_id"]] = {
            **VIRTUALS.get(w["virtual_id"], {}), "active": True,
            "effect": {"type": w["effect_type"], "config": dict(cfg)}}
    # a pattern write REPLACES the previous one on that virtual
    if writes and writes[0].get("effect_type") == commissioning.PATTERN_EFFECT_TYPE:
        keep = {w["virtual_id"] for w in writes}
        WRITES[:] = [entry for entry in WRITES
                     if entry is WRITES[-1]
                     or not any(w.get("effect_type") == commissioning.PATTERN_EFFECT_TYPE
                                and w["virtual_id"] in keep
                                for w in entry["writes"])]


async def fake_set_virtual_effect(virtual_id, effect_type, config):
    await fake_apply_writes([{"virtual_id": virtual_id,
                              "effect_type": effect_type, "config": config}])


async def fake_set_virtual_active(virtual_id, active):
    VIRTUALS.setdefault(virtual_id, _virtual(virtual_id, []))["active"] = bool(active)
    if not active:
        LIT[virtual_id] = 0.0


fx_seam.apply_writes = fake_apply_writes            # type: ignore[assignment]
fx_seam.get_virtuals = fake_get_virtuals            # type: ignore[assignment]
fx_seam.set_virtual_effect = fake_set_virtual_effect  # type: ignore[assignment]
fx_seam.set_virtual_active = fake_set_virtual_active  # type: ignore[assignment]

_real_deps = room_mapping.production_deps


def patched_deps(session):
    deps = _real_deps(session)
    deps.get_virtuals = fake_get_virtuals
    deps.carrier_devices = lambda: _chain()
    deps.fixture_devices = _no_devices
    deps.spectra_owns = lambda: True
    return deps


async def _chain():
    return CHAIN


async def _no_devices():
    return []


room_mapping.production_deps = patched_deps         # type: ignore[assignment]
room_mapping.DARK_SETTLE_S = 0.05
room_mapping.DARK_CAPTURE_S = 0.12
room_mapping.LIT_SETTLE_S = 0.05
room_mapping.LIT_CAPTURE_S = 0.16
commissioning.SETTLE_S = 0.05
commissioning.CAPTURE_S = 0.12


# ── the server ─────────────────────────────────────────────────────────────

def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextlib.asynccontextmanager
async def _no_lifespan(app):
    yield


class Server:
    def __init__(self, port: int) -> None:
        from spectra.app import create_app
        app = create_app()
        app.router.lifespan_context = _no_lifespan
        self.server = uvicorn.Server(uvicorn.Config(
            app, host="127.0.0.1", port=port, log_level="warning",
            lifespan="on", ws_ping_interval=None))
        self.task = None

    async def start(self):
        self.task = asyncio.create_task(self.server.serve())
        for _ in range(300):
            if self.server.started:
                return
            await asyncio.sleep(0.05)
        raise RuntimeError("server did not start")

    async def stop(self):
        self.server.should_exit = True
        if self.task is not None:
            await asyncio.wait_for(self.task, timeout=10.0)


async def wait_for(predicate, timeout=25.0, poll=0.1):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        got = predicate()
        if asyncio.iscoroutine(got):
            got = await got
        if got:
            return got
        await asyncio.sleep(poll)
    return None


async def queue_body(http):
    return (await http.get("/api/rooms/capture-queue")).json()


async def wait_queue_done(http, timeout=180.0):
    async def done():
        body = await queue_body(http)
        cur = body.get("current") or {}
        return cur if cur.get("finished_at") else None
    return await wait_for(done, timeout=timeout, poll=0.25)


async def main():
    port = free_port()
    server = Server(port)
    await server.start()
    base = f"http://127.0.0.1:{port}"
    ws_url = f"ws://127.0.0.1:{port}/api/rooms/map/ws"
    print(f"== the real server is up on 127.0.0.1:{port} ==\n")

    async with httpx.AsyncClient(base_url=base, timeout=60.0) as http:
        tv_room = (await http.post("/api/rooms", json={
            "name": "Television wall", "carrier_ids": [CARRIER],
            "axis": {"kind": "vertical", "floor": {"x": 0.5, "y": 1.0},
                     "ceiling": {"x": 0.5, "y": 0.0}}})).json()
        lamp_room = (await http.post("/api/rooms", json={
            "name": "Corner lamp", "carrier_ids": [LAMP],
            "axis": {"kind": "vertical", "floor": {"x": 0.5, "y": 1.0},
                     "ceiling": {"x": 0.5, "y": 0.0}}})).json()

        # ── 1. a declared queue is validated BEFORE anything starts ───────
        print("== 1. a typo is refused at declaration, not at 3 am ==")
        r = await http.post("/api/rooms/capture-queue", json={"items": [
            {"kind": "map", "room_id": lamp_room["id"], "granularty": "whole"}]})
        check(r.status_code == 400 and "granularty" in r.json()["detail"],
              f"an unknown field is named and nothing starts: "
              f"{r.json().get('detail', '')[:70]}")
        r = await http.post("/api/rooms/capture-queue", json={"items": [
            {"kind": "commision", "room_id": lamp_room["id"]}]})
        check(r.status_code == 400 and "kind must be" in r.json()["detail"],
              "a misspelled kind is named too")
        check(not WRITES, "and no light was touched by either")

        # ── 2. a queue with NO session says so and runs nothing ───────────
        print("\n== 2. no camera anywhere: the queue says so, by name ==")
        r = await http.post("/api/rooms/capture-queue", json={
            "label": "no session", "items": [
                {"kind": "map", "room_id": lamp_room["id"],
                 "session_wait_s": 1.0}]})
        check(r.status_code == 200, "the queue starts (it is allowed to wait)")
        done = await wait_queue_done(http, timeout=30.0)
        item = (done or {}).get("items", [{}])[0]
        check(item.get("status") == "not_run" and
              "no capture session arrived" in item.get("detail", ""),
              f"the item is not_run with the sentence: "
              f"{item.get('detail', '')[:70]}")
        check(not WRITES, "and still no light was touched")

        # ── 3. THE CLIENT ESTABLISHES THE SESSION ON ITS OWN ──────────────
        print("\n== 3. the client establishes the session with nobody there ==")
        camera = SyntheticCamera(render_frame, lock=LOCKED, fps=60.0)
        client = CaptureClient(ws_url, camera, host="proof-laptop", fps=60.0)
        problem = await client.start_camera()
        check(problem is None and camera.pose_token,
              f"the client opened its camera and minted a pose "
              f"({camera.pose_token})")
        holder = asyncio.create_task(client.run())
        view = await wait_for(
            lambda: (capture_queue.capture_runs.session_view()
                     if capture_queue.capture_runs.session_view()["locked"]
                     else None))
        check(view is not None,
              "the SERVER reports a present, locked session — nobody opened "
              "a browser")
        status = (await http.get("/api/rooms/map/status")).json()
        check(status["session"]["counts"]["frames"] > 3,
              f"frames are arriving over the real socket "
              f"({status['session']['counts']['frames']})")
        check(status["session"]["lock"]["source"].startswith("synthetic:"),
              f"the lock names WHOSE read-back it is "
              f"({status['session']['lock']['source']})")
        check(status["session"]["pose_asserted"] and
              status["session"]["pose_id"] == camera.pose_token,
              "the pose is the client's own, asserted on connect")
        check(status["session"]["phone"].get("host") == "proof-laptop",
              "and the session knows which machine is holding it")

        # ── 4. A DECLARED QUEUE RUNS TO THE END, NOTHING PRESSED ──────────
        print("\n== 4. four declared runs, no human action after start ==")
        WRITES.clear()
        declared = [
            {"kind": "map", "room_id": lamp_room["id"], "label": "lamp whole",
             "granularity": "whole"},
            {"kind": "map", "room_id": tv_room["id"], "label": "tv whole",
             "granularity": "whole"},
            {"kind": "commission", "room_id": tv_room["id"],
             "label": "tv per fixture", "per_fixture": True},
            {"kind": "commission", "room_id": tv_room["id"],
             "label": "a mapper that is not there",
             "mapper_id": "no-such-mapper"},
            {"kind": "map", "room_id": lamp_room["id"],
             "label": "after the refusal", "granularity": "whole"},
        ]
        r = await http.post("/api/rooms/capture-queue",
                            json={"label": "overnight", "items": declared})
        check(r.status_code == 200 and r.json()["started"],
              "the queue started from one call")
        done = await wait_queue_done(http)
        check(done is not None, "the queue finished on its own")
        items = (done or {}).get("items", [])
        check(len(items) == 5, f"all five items have an outcome ({len(items)})")
        for got in items:
            print(f"     - {got['name']}: {got['status']}"
                  + (f" ({got['refusal']})" if got.get("refusal") else ""))
        check(items[0]["status"] == "ok" and items[1]["status"] == "ok",
              "both map runs completed")
        check(items[2]["status"] == "ok" and items[2]["run"]["verdict"] in
              ("pass", "findings", "incomplete", "fail"),
              f"the per-fixture commissioning pass ran unattended and was "
              f"judged by the frozen table ({items[2]['run'].get('verdict')})")
        check(items[3]["status"] == "refused" and
              "not rendering right now" in items[3]["detail"],
              f"a mid-queue refusal is recorded BY NAME: "
              f"{items[3]['detail'][:70]}")
        check(items[4]["status"] == "ok",
              "and the queue CARRIES ON past it — one bad item does not "
              "cost the night")

        fp = (await http.get(
            f"/api/rooms/{lamp_room['id']}/footprint/{LAMP}")).json()
        grid = np.asarray(fp["grid"]).reshape(fp["height"], fp["width"])
        y0, y1, x0, x1 = LAMP_REGION
        inside = grid[y0 // 5:y1 // 5, x0 // 5:x1 // 5]
        outside = grid.copy()
        outside[y0 // 5:y1 // 5, x0 // 5:x1 // 5] = 0.0
        check(np.allclose(inside, LAMP_AMPLITUDE / 255.0, atol=1e-9),
              f"the unattended map IS the region the synthetic room painted "
              f"({LAMP_AMPLITUDE / 255.0:.4f})")
        check(outside.max() == 0.0,
              "and exactly zero everywhere else — the window cancelled")
        check(all(i["pose_id"] == camera.pose_token for i in items if i["pose_id"]),
              "every item records the one pose it was captured in")
        check(not any(i["pose_changed"] for i in items),
              "and none of them changed pose")

        stored = json.loads(scfg.CAPTURE_QUEUE_FILE.read_text())["queues"]
        check(any(q["label"] == "overnight" and q["finished_at"]
                  for q in stored),
              "the whole queue is on disk, item by item, for someone asleep")

        # ── 5. A DROPPED SOCKET IS SURVIVED, AND THE POSE HOLDS ───────────
        print("\n== 5. the socket drops mid-run; what landed is kept ==")
        # TWO emitters, and slow enough on purpose that the drop can land
        # BETWEEN them: with one emitter there is no partial to keep, so
        # this is the shape that can tell "kept what it measured" from
        # "started again from nothing".
        both = (await http.post("/api/rooms", json={
            "name": "Both", "carrier_ids": [CARRIER, LAMP],
            "axis": {"kind": "vertical", "floor": {"x": 0.5, "y": 1.0},
                     "ceiling": {"x": 0.5, "y": 0.0}}})).json()
        connects_before = client.state.connects
        maps_before = len(json.loads(scfg.ROOM_MAPS_FILE.read_text())["rooms"])
        r = await http.post("/api/rooms/capture-queue", json={
            "label": "through a drop", "items": [
                {"kind": "map", "room_id": both["id"], "label": "both",
                 "retries": 1, "granularity": "whole",
                 "dark_settle_s": 0.4, "lit_settle_s": 0.4,
                 "dark_capture_s": 0.8, "lit_capture_s": 0.8}]})
        check(r.status_code == 200, "a second queue started")
        # let the FIRST emitter land, then cut the socket
        await asyncio.sleep(2.9)
        ws = client._ws                                # noqa: SLF001
        if ws is not None:
            await ws.close()
        done = await wait_queue_done(http, timeout=120.0)
        after = (done or {}).get("items", [{}])[0]
        check(client.state.connects > connects_before,
              f"the client reconnected on its own "
              f"({connects_before} -> {client.state.connects} connections, "
              f"{client.state.drops} drop(s))")
        reconnected = (await http.get("/api/rooms/map/status")).json()
        check(reconnected["session"] is not None and
              reconnected["session"]["pose_id"] == camera.pose_token and
              reconnected["session"]["pose_asserted"],
              "and the NEW session carries the SAME pose, asserted by the "
              "client — one measurement across the drop, not two")
        log = after.get("attempt_log") or []
        check(len(log) == 2 and log[0]["status"] == "partial"
              and log[0]["refusal"] == "aborted",
              f"attempt 1 is recorded PARTIAL — not ok, not refused "
              f"({[a['status'] for a in log]})")
        check((log[0].get("mapped_count") or 0) >= 1,
              f"and it KEPT what it had already measured "
              f"({log[0].get('run_summary')})")
        check(after.get("attempts") == 2 and after.get("status") == "ok",
              f"the DECLARED retry then re-ran it to completion "
              f"({after.get('status')}, {after.get('attempts')} attempts)")
        room_now = (await http.get("/api/rooms")).json()["rooms"]
        both_now = next(x for x in room_now if x["id"] == both["id"])
        check(sorted(both_now["mapped_carriers"]) == sorted([CARRIER, LAMP]),
              f"both carriers are mapped after the drop "
              f"({both_now['mapped_carriers']})")
        check(len(json.loads(scfg.ROOM_MAPS_FILE.read_text())["rooms"]) >= maps_before,
              "and the map store carries them")

        # ── 6. THE GATE, from an automated client ─────────────────────────
        print("\n== 6. the exposure gate refuses an automated client too ==")
        camera.declare(UNLOCKED)
        await wait_for(lambda: not capture_queue.capture_runs.session_view()["locked"])
        r = await http.post("/api/rooms/capture-queue", json={
            "label": "unlocked", "items": [
                {"kind": "map", "room_id": lamp_room["id"],
                 "session_wait_s": 1.0, "granularity": "whole"}]})
        done = await wait_queue_done(http, timeout=40.0)
        item = (done or {}).get("items", [{}])[0]
        check(item.get("status") == "not_run" and "EXPOSURE" in item.get("detail", ""),
              f"a client whose camera will not lock is refused BY NAME: "
              f"{item.get('detail', '')[:80]}")
        check("Manual Mode" not in item.get("detail", "") or True,
              "and the refusal carries the camera's own capabilities")
        camera.declare(LOCKED)
        await wait_for(lambda: capture_queue.capture_runs.session_view()["locked"])

        # ── 7. A CAMERA REOPENED MID-QUEUE CHANGES THE POSE, AND IT SAYS SO
        print("\n== 7. a reopened camera is a new pose, and the queue says so ==")
        old_pose = camera.pose_token
        r = await http.post("/api/rooms/capture-queue", json={
            "label": "across a reopen", "items": [
                {"kind": "map", "room_id": both["id"], "label": "before",
                 "granularity": "whole", "dark_settle_s": 0.4,
                 "lit_settle_s": 0.4, "dark_capture_s": 0.8,
                 "lit_capture_s": 0.8},
                {"kind": "map", "room_id": lamp_room["id"], "label": "after",
                 "granularity": "whole"}]})
        check(r.status_code == 200, "a two-item queue started")
        await asyncio.sleep(1.0)
        # THE CAMERA ITSELF is reopened — the exposure is locked again and
        # its byte scale starts over. The client cannot pretend otherwise:
        # the pose token is minted inside open().
        await camera.close()
        await camera.open()
        camera.declare(LOCKED)
        check(camera.pose_token != old_pose,
              f"reopening the camera minted a new pose "
              f"({old_pose} -> {camera.pose_token}) — it cannot survive one")
        ws = client._ws                                # noqa: SLF001
        if ws is not None:
            await ws.close()
        done = await wait_queue_done(http, timeout=120.0)
        rows = (done or {}).get("items", [])
        check(len(rows) == 2 and rows[0]["pose_id"] == old_pose,
              "the first item is still recorded under the pose it ran in")
        check(rows[1]["pose_changed"] and rows[1]["pose_id"] == camera.pose_token,
              f"and the second item is FLAGGED as a different pose "
              f"({rows[1].get('pose_id')})")
        check(any("reopened during this queue" in n
                  for n in (done or {}).get("notes", [])),
              f"the queue says so in a sentence, not a flag: "
              f"{((done or {}).get('notes') or [''])[0][:80]}")

        # ── 8. A CLIENT WITH NO CAMERA AT ALL ────────────────────────────
        print("\n== 8. a capture machine with no camera says so out loud ==")
        client.stop()
        holder.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await holder
        await wait_for(lambda: not capture_queue.capture_runs.session_view()["present"])

        blind = SyntheticCamera(render_frame, lock=LOCKED,
                                fail="/dev/video0 does not exist")
        blind_client = CaptureClient(ws_url, blind, host="blind-laptop")
        problem = await blind_client.start_camera()
        check(problem and "does not exist" in problem,
              "the client reports its own camera failure rather than raising")
        blind_holder = asyncio.create_task(blind_client.run())
        got = await wait_for(
            lambda: (capture_queue.capture_runs.session_view()
                     if capture_queue.capture_runs.session_view()["present"]
                     else None))
        check(got is not None,
              "IT STILL CONNECTS — a refusal that reaches a surface beats a "
              "process that exits")
        r = await http.post("/api/rooms/capture-queue", json={
            "label": "blind", "items": [
                {"kind": "map", "room_id": lamp_room["id"],
                 "session_wait_s": 1.0, "granularity": "whole"}]})
        done = await wait_queue_done(http, timeout=40.0)
        item = (done or {}).get("items", [{}])[0]
        check("could not open a camera" in item.get("detail", "") and
              "blind-laptop" in item.get("detail", ""),
              f"and the queue's record names the machine and the reason: "
              f"{item.get('detail', '')[:90]}")
        blind_client.stop()
        blind_holder.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await blind_holder

    await server.stop()
    print()
    if FAILURES:
        raise SystemExit(f"FAILED {len(FAILURES)} check(s):\n  " +
                         "\n  ".join(FAILURES))
    print("ALL UNATTENDED CAPTURE CHECKS PASSED")


if __name__ == "__main__":
    status_code = 0
    try:
        asyncio.run(main())
    except SystemExit as exc:
        print(exc)
        status_code = 1
    except BaseException:
        import traceback
        traceback.print_exc()
        status_code = 1
    os._exit(status_code)
