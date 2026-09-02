"""THE LEVER-IS-REAL SELF-TEST, PROVEN OVER THE WHOLE REAL PATH — a real
server, a real WebSocket, the REAL capture client, the real capture-run
seam, and a camera that either obeys its exposure control or does not.

WHY THIS SCRIPT EXISTS BESIDE THE PYTEST FILE. `tests/test_lever_selftest.py`
proves the judgement and the run against a session double. This proves the
WIRE: that a pinned regime actually crosses it, that the client actually
writes it and reads it back, that the server's own `LockState` carries all
four read-backs, and that `POST /api/rooms/{id}/map` — the route his own
button and his own overnight queue both go through — actually refuses a
camera whose light does not follow its command.

THE FOUR PASSES, and the second one is the whole point:

  1. GREEN     a camera whose measured light rises with commanded time. The
               self-test passes, the map RUNS, and the verdict rides on the
               run's own result. A gate that refuses everything is a wall.
  2. RED       tonight's own measured shape (2026-09-01): commanded 10 ms /
               60 ms / 200 ms producing flat noise-level light. The map
               REFUSES BY NAME, before any footprint is written.
  3. DRIFT     a camera whose sensitivity moves between two IDENTICAL
               commanded settings — the invisible re-clamping. Refused.
  4. BROWSER   an HONEST camera, connecting as the page rather than the
               native client. REFUSED BEFORE THIS TEST, and for the broader
               reason — a browser cannot pin the camera at all
               (`spectra/services/capture_source.py`, 2026-09-02). The order
               is the point: a browser reaching this test would be told its
               camera is not obeying its exposure control, and sent to look
               at a camera that is working. The session stays present,
               locked and first-class for AIMING.

WHAT IS FAKE, and it is exactly two things, both of them his hardware: the
`fx_seam` write primitives (a check script never reaches for his fixtures)
and the CAMERA. The camera's DRIVER takes every setting and reads it back
honestly — which is the situation that fooled everyone: every read-back was
fine. Only its SENSOR differs between the passes.

Run from repo root: .venv/bin/python scripts/check_lever_selftest.py
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
from dataclasses import replace
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


td = Path(tempfile.mkdtemp(prefix="spectra-lever-selftest-"))
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

from spectra.capture_client.camera import (CameraLock,          # noqa: E402
                                           SyntheticCamera)
from spectra.capture_client.session import CaptureClient       # noqa: E402
from spectra.services import (fx_seam, lever_selftest,          # noqa: E402
                              light_field, mapping_refusals,
                              mapping_session, room_mapping)

FW, FH = light_field.FRAME_W, light_field.FRAME_H

#: One carrier over one fixture, and a declared region of the frame its
#: light lands in. Nothing here needs his real composition: the question is
#: whether the light MOVES with the command, not where it falls.
CARRIER = "corner-lamp"
LAMP_REGION = (20, 70, 40, 120)          # y0, y1, x0, x1

#: THE PINNED REGIME the map asks for, all four levers at once.
PINNED = {"exposure_time": 300, "gain": 64, "white_balance": 4600,
          "focus": 120}

LOCKED = CameraLock(exposure_locked=True, white_balance_locked=True,
                    exposure_mode="Manual Mode", white_balance_mode="manual",
                    exposure_capabilities=["Manual Mode",
                                           "Aperture Priority Mode"],
                    white_balance_capabilities=["white_balance_automatic"],
                    exposure_time_range=[3.0, 2047.0],
                    gain_range=[0.0, 255.0],
                    white_balance_range=[2000.0, 6500.0],
                    focus_range=[0.0, 255.0],
                    source="synthetic:driver-takes-everything")

VIRTUALS = {CARRIER: {"id": CARRIER, "active": True, "pixel_count": 20,
                      "config": {"grouping": 1},
                      "segments": [[f"{CARRIER}-fixture", 0, 19, False]],
                      "effect": {"type": "singleColor", "config": {}}}}
CHAIN = {CARRIER: [{"id": f"{CARRIER}-fixture", "type": "wled"}]}
LIT: dict = {}


# ── the camera ─────────────────────────────────────────────────────────────

class RespondingCamera(SyntheticCamera):
    """A camera whose DRIVER TAKES EVERY SETTING — the read-back always
    agrees with the request, exactly as his Brio's did all evening — and
    whose SENSOR obeys, or does not, according to `respond`.

    That split IS the finding this whole build exists for: nothing on the
    read-back path can tell these cameras apart, and the difference is
    visible only in the light."""

    def __init__(self, respond) -> None:
        super().__init__(self._render, lock=LOCKED,
                         capture_size=(FW, FH))
        self.respond = respond
        self.lit_captures = 0
        self._was_lit = False

    async def apply_lock(self, **levers):
        await super().apply_lock(**levers)
        self.lock = replace(self._declared, **{
            name: (None if self.applied.get(name) is None
                   else float(self.applied[name]))
            for name in ("exposure_time", "gain", "white_balance", "focus")})
        return self.lock

    def _render(self) -> bytes:
        lit = LIT.get(CARRIER, 0.0) > 0
        if lit and not self._was_lit:
            self.lit_captures += 1
        self._was_lit = lit
        f = np.full((FH, FW), 6.0)
        f[:, :24] += 10.0                 # a window, in both frames
        if lit:
            y0, y1, x0, x1 = LAMP_REGION
            value = float(self.respond(self.applied.get("exposure_time"),
                                       self.lit_captures))
            f[y0:y1, x0:x1] += value
        return np.clip(f, 0, 255).astype(np.uint8).tobytes()


#: What a camera asked for nothing settles on, so an ordinary map after a
#: self-test still sees light.
CONVERGED = 200


def honest(exposure, _n):
    """A sensor in its linear regime: more time, more light."""
    return 0.5 * float(exposure or CONVERGED)


def tonight(exposure, _n):
    """HIS OWN MEASURED SHAPE. Three commanded times a factor of twenty
    apart produced footprint weights of 0.0, 0.0014 and 0.0051 — every one
    of them at the noise floor."""
    return 0.0008 * float(exposure or CONVERGED)


def wanders(exposure, n):
    """The re-clamping camera: it obeys, and then its sensitivity moves
    under a command that did not. 0.23 -> 0.01 is the pair he actually saw."""
    return honest(exposure, n) / (23.0 if n >= 3 else 1.0)


# ── the room's write seam ──────────────────────────────────────────────────

async def fake_get_virtuals():
    return VIRTUALS


async def fake_apply_writes(writes, *, transition_ms=0):
    for w in writes:
        cfg = w["config"]
        black = cfg.get("color") == "#000000" or cfg.get("brightness", 1.0) == 0
        LIT[w["virtual_id"]] = 0.0 if black else float(cfg.get("brightness", 1.0))


async def fake_set_virtual_effect(virtual_id, effect_type, config):
    await fake_apply_writes([{"virtual_id": virtual_id,
                              "effect_type": effect_type, "config": config}])


async def fake_set_virtual_active(virtual_id, active):
    VIRTUALS.setdefault(virtual_id, {})["active"] = bool(active)
    if not active:
        LIT[virtual_id] = 0.0


fx_seam.apply_writes = fake_apply_writes            # type: ignore[assignment]
fx_seam.get_virtuals = fake_get_virtuals            # type: ignore[assignment]
fx_seam.set_virtual_effect = fake_set_virtual_effect  # type: ignore[assignment]
fx_seam.set_virtual_active = fake_set_virtual_active  # type: ignore[assignment]

_real_deps = room_mapping.production_deps


async def _chain():
    return CHAIN


async def _no_devices():
    return []


def patched_deps(session):
    deps = _real_deps(session)
    deps.get_virtuals = fake_get_virtuals
    deps.carrier_devices = lambda: _chain()
    deps.fixture_devices = _no_devices
    deps.spectra_owns = lambda: True
    return deps


room_mapping.production_deps = patched_deps         # type: ignore[assignment]
# CAPTURE-THEN-RESTORE is the rule for a constant a script mutates
# (AGENTS.md); these are never restored because this process exits, but they
# are captured so a future edit that needs them has them.
_ORIG_WAITS = (room_mapping.DARK_SETTLE_S, room_mapping.DARK_CAPTURE_S,
               room_mapping.LIT_SETTLE_S, room_mapping.LIT_CAPTURE_S)
room_mapping.DARK_SETTLE_S = 0.05
room_mapping.DARK_CAPTURE_S = 0.14
room_mapping.LIT_SETTLE_S = 0.05
room_mapping.LIT_CAPTURE_S = 0.18


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


class Held:
    """One REAL capture client holding one REAL session, as a context."""

    def __init__(self, ws_url, camera, *, browser=False):
        self.client = CaptureClient(ws_url, camera, host="capture-pi", fps=20.0)
        self.browser = browser
        self.task = None

    async def __aenter__(self):
        # A NEW PASS IS A NEW ROOM: the previous run's hold revert leaves
        # its own last write behind, and a camera that starts "lit" would
        # render its first frame against a regime nothing has asked for yet.
        LIT.clear()
        if self.browser:
            # THE PAGE'S OWN HELLO: no `client` field, so nothing about the
            # native path is asked of it. This is the one honest way to say
            # "a browser session" without inventing a second client.
            self.client._hello = _browser_hello(self.client)   # noqa: SLF001
        problem = await self.client.start_camera()
        if problem:
            raise RuntimeError(problem)
        self.task = asyncio.create_task(self.client.run())
        # A FRESH session, not merely "a session": the previous pass's
        # object stays on the registry until its own socket closes, and a
        # verdict from another camera must never be inherited.
        before = getattr(mapping_session.current, "id", None)

        def ready():
            sess = mapping_session.current
            return (sess is not None and not sess.closed and sess.id != before
                    and sess.lock.reported and sess.counts["frames"] > 1)

        got = await wait_for(ready)
        if not got:
            sess = mapping_session.current
            raise RuntimeError(
                f"the client never established a session "
                f"(current={getattr(sess, 'id', None)} before={before} "
                f"closed={getattr(sess, 'closed', None)} "
                f"frames={getattr(sess, 'counts', None)} "
                f"state={self.client.state.as_dict()})")
        return self.client

    async def __aexit__(self, *exc):
        self.client.stop()
        if self.task is not None:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self.task
        await wait_for(lambda: mapping_session.current is None
                       or mapping_session.current.closed, timeout=5.0)


def _browser_hello(client):
    async def hello(ws):
        await ws.send(json.dumps({
            "type": "hello",
            "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)",
            "secure_context": True,
            "frame_size": {"width": client.camera.frame_size[0],
                           "height": client.camera.frame_size[1]},
            "lock": client.camera.lock.as_wire()}))
    return hello


async def main():
    port = free_port()
    server = Server(port)
    await server.start()
    base = f"http://127.0.0.1:{port}"
    ws_url = f"ws://127.0.0.1:{port}/api/rooms/map/ws"
    print(f"== the real server is up on 127.0.0.1:{port} ==\n")

    async with httpx.AsyncClient(base_url=base, timeout=120.0) as http:
        room = (await http.post("/api/rooms", json={
            "name": "Corner lamp", "carrier_ids": [CARRIER],
            "axis": {"kind": "vertical", "floor": {"x": 0.5, "y": 1.0},
                     "ceiling": {"x": 0.5, "y": 0.0}}})).json()
        room_id = room["id"]

        # ── 1. GREEN — an honest camera passes, and the map RUNS ──────────
        print("\n-- 1. GREEN: the lever is real, so the work goes through --")
        async with Held(ws_url, RespondingCamera(honest)):
            body = (await http.post(f"/api/rooms/{room_id}/map", json={
                "granularity": "whole", **PINNED})).json()
            lever = body.get("lever") or {}
            check(body.get("ok"), "the map ran and produced a footprint")
            check(lever.get("verdict") == mapping_refusals.LEVER_OK,
                  f"the self-test passed ({lever.get('verdict')})")
            check(lever.get("proven") is True,
                  "and the verdict says PROVEN, not merely 'not refused'")
            check((lever.get("response_ratio") or 0) >=
                  lever_selftest.min_response_ratio(),
                  f"the measured light rose {lever.get('response_ratio')}x for a "
                  f"commanded {lever.get('commanded_factor')}x")
            check(body.get("mapped_count") == 1,
                  "and the map's own footprint landed")

            # THE PINNED REGIME ACTUALLY CROSSED THE WIRE, all four of it,
            # and came back off the DRIVER rather than out of the request.
            sess = mapping_session.current
            lock = sess.lock.as_dict()
            check([lock.get(k) for k in ("exposure_time", "gain",
                                         "white_balance", "focus")]
                  == [300.0, 64.0, 4600.0, 120.0],
                  f"all four pinned levers read back off the camera: "
                  f"{[lock.get(k) for k in ('exposure_time', 'gain', 'white_balance', 'focus')]}")
            # A SECOND RUN IN THE SAME SESSION PAYS FOR IT ONCE.
            before = sess.lever_verdict
            body2 = (await http.post(f"/api/rooms/{room_id}/map", json={
                "granularity": "whole", **PINNED})).json()
            check(body2.get("ok") and sess.lever_verdict is before,
                  "a queue of runs in one session pays for the self-test once")

        # ── 2. RED — tonight's camera, refused by name, nothing written ───
        print("\n-- 2. RED: tonight's own measured shape --")
        async with Held(ws_url, RespondingCamera(tonight)):
            r = await http.post(f"/api/rooms/{room_id}/map",
                                json={"granularity": "whole", **PINNED})
            body = r.json()
            lever = body.get("lever") or {}
            check(not body.get("ok"), "the map refused")
            check(body.get("refusal") == "lever",
                  f"and it refused ON THE SELF-TEST, by name "
                  f"({body.get('refusal')})")
            check(lever.get("verdict") == mapping_refusals.LEVER_NO_SIGNAL,
                  f"the verdict names WHICH measurement failed "
                  f"({lever.get('verdict')})")
            detail = body.get("detail") or ""
            check("integration time of" in detail and "measured" in detail,
                  "the refusal quotes both commands and both measurements")
            check("Nothing was written" in detail,
                  "and says nothing was written")
            check(len(lever.get("readings") or []) >= 2,
                  "both readings ride on the verdict for a human to read")
            # The camera's own read-back was PERFECT throughout — which is
            # exactly why the read-back could never have caught this.
            lock = mapping_session.current.lock.as_dict()
            check(lock.get("exposure_time") is not None
                  and not lock.get("manual_refusals"),
                  "the driver's read-back passed the whole time — this is "
                  "the measurement it cannot make")

        # ── 3. DRIFT — the same command twice, two different sensitivities ─
        print("\n-- 3. DRIFT: the invisible re-clamping --")
        async with Held(ws_url, RespondingCamera(wanders)):
            body = (await http.post(f"/api/rooms/{room_id}/map", json={
                "granularity": "whole", **PINNED})).json()
            lever = body.get("lever") or {}
            check(body.get("refusal") == "lever"
                  and lever.get("verdict") == mapping_refusals.LEVER_DRIFT,
                  f"a camera that wanders between two IDENTICAL commands is "
                  f"refused ({lever.get('verdict')})")
            check((lever.get("repeat_ratio") or 1.0)
                  < 1.0 / lever_selftest.REPEAT_BAND,
                  f"and the refusal quotes how far it moved "
                  f"({lever.get('repeat_ratio')})")

        # ── 4. THE BROWSER IS REFUSED EARLIER, AND FOR A BROADER REASON ───
        #
        # It used to run its map untouched by any of this, and the demotion
        # (2026-09-02, `spectra/services/capture_source.py`) replaced that:
        # a browser cannot pin the camera AT ALL, so a calibration-grade run
        # is refused before the self-test rather than by it. THE ORDER IS
        # WHAT IS CHECKED HERE. A browser reaching this test and failing it
        # would say "your camera is not obeying its exposure control" —
        # true of the browser, and an instruction that would send him to
        # look at a camera that is standing there working perfectly.
        print("\n-- 4. a BROWSER session is refused BEFORE this test --")
        async with Held(ws_url, RespondingCamera(honest), browser=True):
            view = (await http.get("/api/rooms/capture-queue")).json()
            session = view.get("session") or {}
            check(session.get("native") is False,
                  "the server knows this is not the native client")
            check(session.get("calibration_grade") is False
                  and bool(session.get("calibration_refusal")),
                  "and says so BEFORE he presses, in a sentence")
            reply = await http.post(f"/api/rooms/{room_id}/map",
                                    json={"granularity": "whole"})
            body = reply.json()
            check(reply.status_code == 409
                  and body.get("refusal") == "browser_session",
                  f"its map is refused by name ({body.get('refusal')})")
            check(mapping_refusals.CLIENT_COMMAND in (body.get("detail") or ""),
                  "naming the one next step, not just the rule")
            check(not body.get("lever"),
                  "carrying no verdict — this camera was never measured, and "
                  "the record must not imply it was")
            check(mapping_session.current.lever_verdict is None,
                  "nothing was asked of a page that cannot answer it")
            # AND THE SESSION ITSELF IS FINE: aiming is what it is for, and
            # the demotion took nothing away from that.
            check(session.get("present") and session.get("locked")
                  and session.get("aiming") is True,
                  "while the session stays present, locked and good for aiming")

    await server.stop()
    print("\n" + ("ALL CHECKS PASSED" if not FAILURES else
                  f"{len(FAILURES)} FAILURE(S):\n  " + "\n  ".join(FAILURES)))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    status = 1
    try:
        status = asyncio.run(main())
    except Exception:                                          # noqa: BLE001
        import traceback
        traceback.print_exc()
    # A script that renders through fx must exit hard: see AGENTS.md.
    os._exit(status)
