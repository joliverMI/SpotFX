"""Isolated Spectra preview server for the perf test.

Runs the REAL preview backend (spectra.services.device_preview relay + frame
hub, spectra.api.device_preview router) against a real fx render host whose
devices are all DUMMIES in his real favourite shapes. Serves the harness page
that mounts the real DevicePreviewStrip. No live storage, no real device, no
audio device, no bridge.

  python spectra_rig.py --port 9110 --harness <dist dir> [--relay-fps 8]

--relay-fps only changes the OLD JSON format's rate (a `spectra-legacy@N`
what-if); the protocol-2 stream paces itself.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.dirname(__file__))

import rig_common  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9110)
    ap.add_argument("--harness", required=True)
    ap.add_argument("--relay-fps", type=float, default=None,
                    help="what-if: override RELAY_TARGET_FPS (default: shipped value)")
    args = ap.parse_args()

    # The same thread-switch interval the real process runs with
    # (spectra/__main__.py): without it the event loop waits up to 5 ms for
    # the render threads at every hop, which is not what he runs.
    sys.setswitchinterval(0.001)
    tmp = tempfile.mkdtemp(prefix="preview-perf-spectra-")
    os.environ["SPECTRA_STORAGE_DIR"] = os.path.join(tmp, "storage")

    import uvicorn
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles

    from fx import headless, light_ownership as lo
    from fx.consts import CONFIGURATION_VERSION
    from fx.host import FxHost
    from spectra import config as scfg
    from spectra.api import device_preview as dp_api
    from spectra.services import device_preview as dp
    from spectra.services.live_host import live

    from pathlib import Path
    lo.OWNERSHIP_FILE = Path(tmp) / "ownership.json"
    scfg.DEVICE_PREVIEW_FILE = Path(tmp) / "device_preview.json"
    scfg.DEVICE_PREVIEW_FILE.write_text(json.dumps({
        "favorite_virtual_ids": [s[0] for s in rig_common.SHAPES], "paused": False}))

    app = FastAPI()
    app.include_router(dp_api.router, prefix="/spectra")
    state: dict = {}

    @app.on_event("startup")
    async def _up() -> None:
        cfg_dir = os.path.join(tmp, "fx-live")
        rig_common.write_config(cfg_dir, CONFIGURATION_VERSION)
        headless.silence_audio()
        host = FxHost(cfg_dir)
        await host.start()
        host.audio = headless.SyntheticAudioSource()
        live.host = host
        lo._save(lo.OwnershipRecord(owner=lo.SPECTRA))
        state["host"] = host
        if args.relay_fps:
            dp.relay.target_fps = args.relay_fps
            dp.relay._min_interval = 1.0 / args.relay_fps
        await dp.start()

    @app.get("/spectra/rig/info")
    async def info():
        host = state["host"]
        return {"pid": os.getpid(), "relay": dp.relay.status(),
                "frames_received": dp.relay.frames_received,
                "dropped": sum(s.dropped_frames for s in dp.frame_hub._senders.values()),
                "stream": dp.stream_hub.stats(),
                "virtuals": {v.id: bool(v.active) for v in host.virtuals.values()}}

    @app.post("/spectra/rig/flash")
    async def flash(on: int = 1):
        v = state["host"].virtuals.get(rig_common.LATENCY_ID)
        effect = v.active_effect
        effect.update_config({"color": "#ffffff" if on else "#000000"})
        # singleColor redraws on its own timer; LedFX's PUT applies a colour
        # at once. Redraw now so both systems start the clock at the request.
        effect.effect_loop()
        return {"ok": True}

    app.mount("/spectra", StaticFiles(directory=args.harness, html=True))
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    os._exit(0)


if __name__ == "__main__":
    main()
