"""
Offline smoke test: awaited Set Color ramps run in PARALLEL across devices.

Regression guard for the sequential-cascade bug: with await_ramps=True (any
set_color step inside a sequence event) the engine used to await each
device's ramp inline — with server-side tween every call holds for its full
ramp_ms, so an N-device color change cascaded device-by-device for N x
ramp_ms. Asserts, with a stubbed ledfx_client (no LedFX writes):

  1. all devices' ramps START within a tight window of each other;
  2. total wall time ~= ONE ramp_ms (the slowest), not N x ramp_ms;
  3. the wall-clock contract holds (the step still spans the ramp, so a
     following sequence step waits for colors to land).

USAGE
  .venv/bin/python scripts/smoke_parallel_ramps.py
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import ledfx_client                                     # noqa: E402
from models.state import state                                   # noqa: E402
from models.color_set import ColorSetCard, ColorSetEntry         # noqa: E402
from models.music_event import MorphScope, SetColorAction        # noqa: E402
from services import color_set_store, morph_compiler, morph_effect_state  # noqa: E402
from services.trigger_engine import TriggerEngine                # noqa: E402

RAMP_MS = 250
VIDS = [f"fake-{i}" for i in range(6)]

ramp_log: list[tuple[str, float, float]] = []   # (vid, start, end)


async def _fake_ramp(vid, etype, patch, ramp_ms, step_ms=25):
    t0 = time.monotonic()
    await asyncio.sleep(ramp_ms / 1000)
    ramp_log.append((vid, t0, time.monotonic()))


async def main() -> int:
    # ── Stubs: no LedFX, no storage writes ────────────────────────────────
    ledfx_client.ramp_gradient_params = _fake_ramp
    ledfx_client.ramp_effect_params = _fake_ramp
    morph_effect_state.save_many = lambda updates: None

    card = ColorSetCard(
        name="Smoke Set", kind="set",
        entries=[ColorSetEntry(
            scope=MorphScope(),
            color_kind="gradient",
            color_value="linear-gradient(90deg, #ff0000 0%, #0000ff 100%)",
        )],
    )
    color_set_store.get_by_id = lambda cid: card
    morph_compiler.resolve_scope = lambda scope: list(VIDS)

    for vid in VIDS:
        state.ledfx_virtual_cache[vid] = {
            "effect": {"type": "smoke_fx", "config": {"gradient": "#00ff00"}},
        }

    te = object.__new__(TriggerEngine)
    te._ramp_tasks = set()
    te._color_cursor, te._color_cursor_dir, te._color_cursor_prev = {}, {}, {}
    te._palette_hue = None
    te._last_accent_by_vid = {}
    te._signal_now = lambda *a, **k: None

    async def _no_refresh(vids):
        return None
    te._refresh_effect_types = _no_refresh

    action = SetColorAction(ref_id="whatever", ramp_ms=RAMP_MS)

    t0 = time.monotonic()
    await te._execute_set_color(action, await_ramps=True)
    elapsed_ms = (time.monotonic() - t0) * 1000

    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f" — {detail}" if detail else ""))
        ok = ok and cond

    starts = [s for _, s, _ in ramp_log]
    spread_ms = (max(starts) - min(starts)) * 1000 if starts else float("inf")
    check("all devices ramped", len(ramp_log) == len(VIDS),
          f"{len(ramp_log)}/{len(VIDS)}")
    check("ramps start together", spread_ms < 50, f"start spread {spread_ms:.1f}ms")
    check("wall time ~ one ramp, not N ramps",
          elapsed_ms < RAMP_MS * 2, f"{elapsed_ms:.0f}ms for {len(VIDS)} devices @ {RAMP_MS}ms")
    check("step still spans the ramp (sequence contract)",
          elapsed_ms >= RAMP_MS * 0.9, f"{elapsed_ms:.0f}ms >= {RAMP_MS}ms")

    print("OK" if ok else "FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
