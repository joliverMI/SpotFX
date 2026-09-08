"""ONE OBSERVATION OF A SCOPED CAPTURE NIGHT, IN A FRESH INTERPRETER.

Read as text and executed by `tests/test_scoped_take_release.py` via
`python -c` — that file's docstring is the binding statement for what is
real here and what is substituted. This module is never imported: it takes
`[work_dir, mode]` on argv, prints one `RESULT <json>` line and exits
through `os._exit` (fx's TemporalEffect spawns non-daemon threads a
frame-stepped harness never joins).

MODES
  scoped     the fix: the night's declaration is resolved to the kitchen
             carrier, so the take never brings the Hue groups up
  unscoped   THE DEFECT, reproduced: the same night with the scope
             resolution disabled, which is exactly the code that shipped
             before this change — his house Hue is streamed by the take and
             switched off by the release
  hue_scoped a night whose room's carrier IS one Hue entertainment group:
             that group is let go of, the OTHER one is left completely alone

THE HUE FIXTURES ARE THE REAL `fx.devices.hue.HueDevice` with exactly three
things stubbed, all of them transport: `_hue_request` (the bridge's REST
discovery), `_blocking_activate`/`_blocking_stop` (the DTLS session), and
`flush` (the recorder standing in for the UDP send). Everything this test
is about — `Device.activate` setting `ever_activated`, the device being
activated ONLY by a virtual with segments on it, `set_frozen`, the
release's own scope decision — is production code.
"""
import asyncio
import json
import os
import pathlib
import sys
import time

WORK = pathlib.Path(sys.argv[1])
MODE = sys.argv[2]

sys.path.insert(0, os.getcwd())

os.environ["SPECTRA_STORAGE_DIR"] = str(WORK / "storage")
os.environ["SPECTRA_NIGHT_SELF_TAKE"] = "1"
os.environ.pop("SPECTRA_HANDOVER_ARMED", None)
os.environ.pop("SPECTRA_PRETAKE_URL", None)
os.environ.pop("SPECTRA_WITNESS_URL", None)

import httpx                                                # noqa: E402
import numpy as np                                          # noqa: E402
from fx import device_model, headless                       # noqa: E402
from fx import light_ownership as lo                        # noqa: E402
from fx.devices.dummy import DummyDevice                    # noqa: E402
from fx.devices.hue import HueDevice                        # noqa: E402

lo.OWNERSHIP_FILE = WORK / "ownership.json"
device_model.CATEGORIES_FILE = WORK / "device_categories.json"

# ── the instrument: every frame that reaches a device's transport ──────────

PHASE = {"now": "before"}
FRAMES = []
BRIDGE = []          # every REST call the release fade makes, per bridge
FROZEN = []


def _record(self, data):
    arr = np.asarray(data)
    FRAMES.append({"phase": PHASE["now"], "device": self.id,
                   "max": float(arr.max()) if arr.size else 0.0})


DummyDevice.flush = _record
HueDevice.flush = _record

# ── the Hue bridges, stubbed at the transport and nowhere else ─────────────

ENT = {"house-hues": "ent-house", "dining-hues": "ent-dining"}
GROUP = {"house-hues": "House Music", "dining-hues": "Dining Music"}
#: bridge ip -> the lights that bridge's entertainment configuration covers.
#: "bathroom" is in the house group on purpose: it is the bulb the Admiral
#: found switched off.
LIGHTS = {"10.0.0.1": ["hallway", "bathroom", "bedroom"],
          "10.0.0.2": ["dining-a", "dining-b"]}
BRIDGE_OF = {"house-hues": "10.0.0.1", "dining-hues": "10.0.0.2"}


def _channels(ip):
    return [{"channel_id": i,
             "position": {"x": 0.0, "y": 0.0, "z": 0.0},
             "members": [{"service": {"rtype": "entertainment",
                                      "rid": f"ent-{name}"}}]}
            for i, name in enumerate(LIGHTS[ip])]


def _canned_hue_request(self, method, api_endpoint, data=None, ssl=False):
    """`HueDevice._hue_request`'s stand-in — the bridge's REST discovery
    only. It records nothing: the fade's own writes go through
    `release_fade._bridge_client`, which is recorded separately, so a REST
    call landing on a bulb can never be confused with device setup."""
    ip = self._config["ip_address"]
    did = [d for d, i in BRIDGE_OF.items() if i == ip][0]
    ent_id = ENT[did]
    if api_endpoint.startswith("api/config"):
        return {"swversion": "1950000000"}, {}
    if api_endpoint.startswith("api/"):
        return [{"success": {}}], {}
    if api_endpoint == "/clip/v2/resource/entertainment_configuration":
        return ({"data": [{"id": ent_id, "id_v1": "/groups/7",
                           "name": GROUP[did], "channels": _channels(ip)}]},
                {})
    if api_endpoint.startswith("/clip/v2/resource/entertainment_configuration/"):
        return ({"data": [{"id": ent_id, "id_v1": "/groups/7",
                           "name": GROUP[did], "channels": _channels(ip)}]},
                {})
    if api_endpoint == "/auth/v1":
        return {}, {"hue-application-id": "app-id"}
    raise AssertionError(f"unexpected hue request {api_endpoint}")


def _stub_hue_transport():
    HueDevice._hue_request = _canned_hue_request
    HueDevice._blocking_activate = lambda self: None
    HueDevice._blocking_stop = lambda self: None
    real_freeze = HueDevice.set_frozen

    async def set_frozen(self, frozen):
        FROZEN.append({"device": self.id, "frozen": bool(frozen)})
        return await real_freeze(self, frozen)
    HueDevice.set_frozen = set_frozen


def _bridge_handler(ip):
    """The bridge the RELEASE FADE talks to. Every call is recorded with the
    bridge it landed on, so "his bathroom was written to" is a fact this
    driver can state rather than infer."""
    state = {name: True for name in LIGHTS[ip]}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content or b"{}")
        BRIDGE.append({"ip": ip, "method": request.method, "path": path,
                       "body": body, "phase": PHASE["now"]})
        if path == "/clip/v2/resource/entertainment":
            return httpx.Response(200, json={"data": [
                {"id": f"ent-{n}", "owner": {"rid": f"dev-{n}"}}
                for n in LIGHTS[ip]]})
        if path == "/clip/v2/resource/light":
            return httpx.Response(200, json={"data": [
                {"id": f"light-{n}", "owner": {"rid": f"dev-{n}"},
                 "metadata": {"name": n}} for n in LIGHTS[ip]]})
        if path.startswith("/clip/v2/resource/entertainment_configuration/"):
            return httpx.Response(200, json={"data": [
                {"channels": [{"members": [{"service": {
                    "rtype": "entertainment", "rid": f"ent-{n}"}}]}
                    for n in LIGHTS[ip]]}]})
        if path.startswith("/clip/v2/resource/light/"):
            name = path.rsplit("/", 1)[-1][len("light-"):]
            if request.method == "PUT":
                if "on" in body:
                    state[name] = body["on"]["on"]
                return httpx.Response(200, json={"data": []})
            return httpx.Response(200, json={"data": [
                {"on": {"on": state.get(name, True)}}]})
        raise AssertionError(f"unexpected bridge call {path}")
    return handler


def _stub_release_bridge():
    from spectra.services import release_fade

    def client(cfg):
        return httpx.AsyncClient(
            base_url=f"https://{cfg['ip_address']}",
            transport=httpx.MockTransport(_bridge_handler(cfg["ip_address"])))
    release_fade._bridge_client = client
    release_fade.RELEASE_FADE_MS = 0
    release_fade.RELEASE_OFF_SETTLE_MS = 0
    release_fade.RELEASE_OFF_RETRY_SPACING_MS = 0


from spectra import config as scfg                          # noqa: E402
from spectra.services import (capture_queue, capture_runs,  # noqa: E402
                              engine, handover, light_field,
                              night_run, night_take, room_mapping,
                              take_scope)
from spectra.models.room_map import RoomMap                 # noqa: E402

SETTLE_S = 0.35
KITCHEN_VIDS = ["tv-backlight", "sconce-left"]
WHITE = "#ffffff"
ROOM_ID = "kitchen"

MEASURING = {"present": True, "locked": True, "session_id": "sess-scope",
             "pose_id": "pose-scope", "refusal": "", "unable": "",
             "native": True, "source": "native", "calibration_grade": True,
             "calibration_refusal": "", "aiming": True,
             "measured_by": "the capture client", "client": {}, "lever": {},
             "host": {"state": "present"}}

TRIGGER = {"event": "sleep-window-start", "ts": "2026-09-07T01:12:00Z",
           "source": "home-assistant"}

FADE = {}
NOTES = []


def _sides_factory():
    real = handover.production_sides

    def sides(*, quiet=False, scope=None):
        built = real(quiet=quiet, scope=scope)
        built[lo.SPECTRA] = handover.SpectraSide(
            config_dir=str(scfg.FX_LIVE_CONFIG_DIR), open_audio=False,
            quiet=quiet, scope=scope)
        return built
    return sides


def _stub_the_two_network_touchpoints():
    from spectra.services import ledfx_release

    async def _no_virtuals(*a, **kw):
        return {}

    async def _quiesced(self):
        return True

    ledfx_release.get_all_virtuals = _no_virtuals
    handover.SpotEffectsSide.verify_quiesced = _quiesced


async def _price(items, now=None):
    return {"items": [{"name": getattr(i, "name", "item"), "seconds": 5.0}
                      for i in items],
            "total_seconds": 5.0 * max(1, len(items)),
            "window_seconds": 9999.0,
            "planned_end": time.time() + 9999,
            "planned_end_label": night_run.PLANNED_END_LABEL}


async def _run_queue(items, *, label="", run=None, save=None, guard=None,
                     **kw):
    """THE RUN'S OWN LIGHT-DRIVING HALF, through the production machinery:
    `room_mapping.MappingProgram` over `flare_preview_hold.
    open_program_hold`, scoped — like the real run — to WHAT IS LIVE
    (`room_mapping.live_virtual_ids`), which under a scoped take is
    precisely the fixtures the take brought up."""
    from spectra.services import flare_preview_hold, fx_seam

    live_ids = await room_mapping.live_virtual_ids(fx_seam.get_virtuals)
    NOTES.append(f"run scope (live virtuals): {live_ids}")
    if not live_ids:
        NOTES.append("nothing live to map")
        return run
    program = room_mapping.MappingProgram(list(live_ids))
    ceiling = room_mapping.run_ceiling_s(30.0)

    PHASE["now"] = "queue_dark"
    opened = await flare_preview_hold.open_program_hold(
        program, 0.0, step="dark",
        heartbeat_timeout_s=flare_preview_hold.HEARTBEAT_TIMEOUT_S,
        max_duration_s=ceiling)
    NOTES.append(f"hold dark step: held={opened.get('held')}")
    await asyncio.sleep(SETTLE_S)

    PHASE["now"] = "queue_lamp"
    program.select([live_ids[0]])
    await flare_preview_hold.open_program_hold(
        program, 0.0, step="lit",
        heartbeat_timeout_s=flare_preview_hold.HEARTBEAT_TIMEOUT_S,
        max_duration_s=ceiling)
    await asyncio.sleep(SETTLE_S)

    PHASE["now"] = "queue_revert"
    await flare_preview_hold.close_hold()
    await asyncio.sleep(SETTLE_S)
    PHASE["now"] = "queue_done"
    return run


def _wrap_give_back():
    real = night_take.give_back

    async def give_back(**kw):
        PHASE["now"] = "give_back"
        try:
            return await real(**kw)
        finally:
            PHASE["now"] = "after"
    night_take.give_back = give_back


def _wrap_fade():
    """Keep the REAL fade — only record what it decided, so `untouched` is
    read off the production function rather than re-derived here."""
    from spectra.services import release_fade
    real = release_fade.fade_and_release_hue

    async def fade(host, **kw):
        out = await real(host, **kw)
        FADE.update(out)
        # `host.devices` is a RegistryLoader, not a dict — iterate it the
        # same way `release_fade._hue_devices` does.
        devices = {did: host.devices.get(did) for did in host.devices}
        FADE["hue_devices_on_host"] = sorted(
            did for did, dev in devices.items()
            if getattr(dev, "type", None) == "hue")
        FADE["ever_activated"] = sorted(
            did for did, dev in devices.items()
            if getattr(dev, "ever_activated", False))
        return out
    release_fade.fade_and_release_hue = fade


def _seed_room(carrier: str):
    light_field.put_room(RoomMap(id=ROOM_ID, name="Kitchen",
                                 carrier_ids=[carrier]))


async def run_night() -> dict:
    headless.silence_audio()
    _stub_hue_transport()
    _stub_release_bridge()
    _stub_the_two_network_touchpoints()
    handover.production_sides = _sides_factory()
    night_run.price_items = _price
    capture_runs.session_view = lambda: dict(MEASURING)
    capture_queue.run_queue = _run_queue
    _wrap_give_back()
    _wrap_fade()

    _seed_room("dining-hue-carrier" if MODE == "hue_scoped"
               else "tv-mapper")

    if MODE == "unscoped":
        # THE DEFECT, REPRODUCED EXACTLY: this is the code that shipped —
        # `night_run.start` had no scope to hand the take, so the take
        # brought up every genuinely driven virtual in the config.
        take_scope.resolve_for_items = lambda items, **kw: \
            take_scope.ScopeOutcome(None, "scope resolution disabled (the "
                                          "pre-fix behaviour)")

    lo._save(lo.OwnershipRecord(owner=lo.RELEASED))
    night_run.save_declaration(
        "scoped take", [{"kind": "map", "room_id": ROOM_ID,
                         "label": "kitchen emitter"}])

    PHASE["now"] = "take"
    run = await night_run.start(TRIGGER)

    deadline = time.monotonic() + 120
    while night_run.running() and time.monotonic() < deadline:
        await asyncio.sleep(0.05)
    PHASE["now"] = "after"
    await asyncio.sleep(0.75)

    from spectra.services.live_host import live
    record = night_run.last_night() or {}
    take_block = record.get("take") or {}
    return {
        "mode": MODE,
        "took_the_room": bool(take_block.get("self_taken")),
        "night_state": record.get("state"),
        "night_refusal": record.get("refusal"),
        "night_detail": record.get("detail"),
        "scope": take_block.get("scope") or {},
        "held_back": sorted(take_block.get("held_back") or []),
        "blacked_out": sorted(take_block.get("blacked_out") or []),
        "gave_back": bool(take_block.get("given_back")),
        "owner_final": lo.load().owner,
        "live_active_after": bool(live.active),
        "fade": dict(FADE),
    }


def summarise(base: dict) -> dict:
    per_device = {}
    for f in FRAMES:
        row = per_device.setdefault(f["device"], {"frames": 0, "non_black": 0,
                                                  "max": 0.0, "phases": []})
        row["frames"] += 1
        row["max"] = max(row["max"], f["max"])
        if f["max"] > 0.0:
            row["non_black"] += 1
        if f["phase"] not in row["phases"]:
            row["phases"].append(f["phase"])
    writes = [c for c in BRIDGE if c["method"] == "PUT"]
    off_writes = sorted({(c["ip"], c["path"].rsplit("/", 1)[-1])
                         for c in writes
                         if c["body"].get("on") == {"on": False}})
    base.update({
        "per_device": per_device,
        "devices_seen": sorted(per_device),
        "bridge_calls": len(BRIDGE),
        "bridges_touched": sorted({c["ip"] for c in BRIDGE}),
        "bridges_written": sorted({c["ip"] for c in writes}),
        "bridge_puts": len(writes),
        "bridge_gets": sum(1 for c in BRIDGE if c["method"] == "GET"),
        "lights_switched_off": [f"{ip}:{lid}" for ip, lid in off_writes],
        "frozen": FROZEN,
        "notes": NOTES,
    })
    return base


async def main() -> dict:
    try:
        return summarise(await run_night())
    except Exception as exc:                                # noqa: BLE001
        import traceback
        return {"mode": MODE, "driver_error": traceback.format_exc(),
                "exc": repr(exc)}


out = asyncio.run(main())
sys.stdout.write("RESULT " + json.dumps(out) + "\n")
sys.stdout.flush()
sys.stderr.flush()
os._exit(0)
