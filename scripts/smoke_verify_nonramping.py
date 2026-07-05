"""
Offline smoke test for non-ramping write verification (verify_and_correct).

Simulates the reported failures — a dropped/overwritten PUT that leaves the live
LedFX state desynced from what SpotFX intended — and asserts the reconciler
re-issues exactly the values that didn't land:
  * power.sparks_color shows white though black was intended → corrected
  * effect type didn't switch → re-PUT the switch (reported as "type")
  * everything already matches → no correction (no wasted PUT)
  * numeric within tolerance → no correction; out of tolerance → corrected

No live LedFX backend: the bus-drain, GET (get_virtual) and direct PUT
(_set_virtual_effect_direct) are stubbed; the stubbed GET returns the desynced
"live" state for each case.

USAGE
  .venv/bin/python scripts/smoke_verify_nonramping.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import api.ledfx_client as lc  # noqa: E402


async def _run_case(label, *, targets, live, expect_puts, expect_corrected) -> bool:
    puts: list[tuple] = []

    async def _fake_drain():
        return None

    async def _fake_get_virtual(vid):
        # /api/virtuals/{id} returns {vid: payload}; mirror that shape.
        return {vid: live.get(vid, {})}

    async def _fake_put(vid, etype, cfg):
        puts.append((vid, etype, dict(cfg)))
        return True

    lc._capture_in_progress = lambda: False           # type: ignore[assignment]
    lc.drain_bus = _fake_drain                         # type: ignore[assignment]
    lc.get_virtual = _fake_get_virtual                 # type: ignore[assignment]
    lc._set_virtual_effect_direct = _fake_put          # type: ignore[assignment]
    lc.state.ledfx_virtual_cache = {}                  # fresh cache per case

    corrected = await lc.verify_and_correct(targets, settle_ms=0, timeout_ms=500)

    # Compare PUTs ignoring order; each as (vid, etype, sorted-config-keys).
    got_puts = sorted((v, e, tuple(sorted(c))) for v, e, c in puts)
    exp_puts = sorted((v, e, tuple(sorted(c))) for v, e, c in expect_puts)
    ok = got_puts == exp_puts and corrected == expect_corrected
    print(f"[{'PASS' if ok else 'FAIL'}] {label}")
    print(f"        puts={puts}")
    print(f"        corrected={corrected}  expected={expect_corrected}")
    return ok


def _eff(etype, **cfg):
    return {"effect": {"type": etype, "config": cfg}}


async def main() -> None:
    results = [
        await _run_case(
            "sparks_color white though black intended → corrected",
            targets={"v1": {"type": "power",
                            "config": {"sparks_color": "#000000", "background_color": "#112233"}}},
            live={"v1": _eff("power", sparks_color="#FFFFFF", background_color="#112233")},
            expect_puts=[("v1", "power", {"sparks_color": "#000000"})],
            expect_corrected={"v1": ["sparks_color"]},
        ),
        await _run_case(
            "effect didn't switch → re-PUT the switch",
            targets={"v1": {"type": "power",
                            "config": {"sparks_color": "#000000"}}},
            live={"v1": _eff("melt", background_color="#000000")},
            expect_puts=[("v1", "power", {"sparks_color": "#000000"})],
            expect_corrected={"v1": ["type"]},
        ),
        await _run_case(
            "everything matches → no correction",
            targets={"v1": {"type": "power",
                            "config": {"sparks_color": "#000000"}}},
            # case-insensitive / whitespace-tolerant compare must hold.
            live={"v1": _eff("power", sparks_color=" #000000 ")},
            expect_puts=[],
            expect_corrected={},
        ),
        await _run_case(
            "numeric within tolerance → no correction",
            targets={"v1": {"type": None, "config": {"sparks_decay_rate": 0.4}}},
            live={"v1": _eff("power", sparks_decay_rate=0.4000004)},
            expect_puts=[],
            expect_corrected={},
        ),
        await _run_case(
            "numeric out of tolerance → corrected",
            targets={"v1": {"type": None, "config": {"sparks_decay_rate": 0.4}}},
            live={"v1": _eff("power", sparks_decay_rate=0.1)},
            expect_puts=[("v1", "power", {"sparks_decay_rate": 0.4})],
            expect_corrected={"v1": ["sparks_decay_rate"]},
        ),
    ]
    print()
    if all(results):
        print("ALL PASS")
    else:
        print("FAILURES present")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
