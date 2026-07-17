"""
Smoke test for the systemic starting-offset learner (services/systemic_offset.py).

Exercises the three behaviours the feature promises, with the clock pinned so
results are deterministic:

  1. Reinforcement   — several consistent residuals raise confidence + bias.
  2. Agreement gate  — scattered residuals across songs yield ~0 bias.
  3. Idle decay      — confidence collapses after a long idle gap.
  4. Self-zeroing    — once residuals shrink to ~0 the bias follows.
  5. Disabled flag   — predict() is inert when the learner is off.

Run:  python -m scripts.smoke_systemic_offset
Exit code 0 = all assertions passed.
"""
from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import settings
from services import systemic_offset as so

# Never touch the live storage/offset_bias.json — reset()/record() persist,
# so an un-redirected run wipes the learner's real samples.
so._STORE_PATH = Path(tempfile.mkstemp(suffix="_offset_bias_smoke.json")[1])

T0 = datetime(2026, 6, 30, 2, 0, 0, tzinfo=timezone.utc)
PASS, FAIL = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m"
_failures = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _failures
    print(f"  [{PASS if cond else FAIL}] {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        _failures += 1


def _seed(samples: list[tuple[int, float, datetime]]) -> None:
    """Reset and inject samples directly (bypasses record()'s clock)."""
    so.reset()
    so._samples = [
        {"residual_ms": r, "quality": q, "at": at.isoformat()}
        for r, q, at in samples
    ]


def main() -> int:
    # Enable + use known knobs for deterministic expectations.
    settings.systemic_offset_enabled = True
    settings.systemic_offset_min_quality = 0.55
    settings.systemic_offset_half_life_h = 3.0
    settings.systemic_offset_max_age_h = 24.0
    settings.systemic_offset_full_mass = 3.0
    settings.systemic_offset_spread_tol_ms = 1500
    settings.systemic_offset_min_confidence = 0.25
    settings.systemic_offset_max_bias_ms = 5000

    print("1. Reinforcement: 4 consistent ~+1500ms residuals, all recent")
    _seed([(1500, 0.9, T0 - timedelta(minutes=m)) for m in (5, 12, 20, 30)])
    p = so.predict(now=T0)
    check("center near +1500", 1300 <= p.center_ms <= 1700, f"center={p.center_ms}")
    check("confidence high", p.confidence >= 0.7, f"conf={p.confidence}")
    check("bias applied & positive", 900 <= p.bias_ms <= 1600, f"bias={p.bias_ms}")

    print("2. Agreement gate: scattered residuals (−3000..+10000), all recent")
    _seed([(r, 0.9, T0 - timedelta(minutes=m))
           for r, m in [(-3000, 5), (10000, 8), (200, 12), (5000, 18), (-1000, 25)]])
    p = so.predict(now=T0)
    check("bias suppressed by disagreement", abs(p.bias_ms) < 400,
          f"bias={p.bias_ms} mad={p.mad_ms} conf={p.confidence}")

    print("3. Idle decay: same 4 consistent residuals but ~18h old")
    _seed([(1500, 0.9, T0 - timedelta(hours=18, minutes=m)) for m in (0, 7, 15, 25)])
    p = so.predict(now=T0)
    check("confidence collapsed after idle", p.confidence < 0.25,
          f"conf={p.confidence} mass={p.mass}")
    check("bias zeroed below floor", p.bias_ms == 0, f"bias={p.bias_ms}")

    print("4. Self-zeroing: residuals shrink toward 0 → bias follows")
    _seed([(r, 0.9, T0 - timedelta(minutes=m)) for r, m in [(80, 5), (-40, 12), (0, 20)]])
    p = so.predict(now=T0)
    check("bias near zero when residuals small", abs(p.bias_ms) < 150,
          f"bias={p.bias_ms} center={p.center_ms}")

    print("5. Low-quality saves are not recorded")
    so.reset()
    so.record(1500, 0.40)   # below min_quality
    so.record(1500, 0.90)   # accepted
    check("only the confident sample stored", len(so._load()) == 1,
          f"n={len(so._load())}")

    print("6. Disabled flag → inert")
    settings.systemic_offset_enabled = False
    _seed([(1500, 0.9, T0 - timedelta(minutes=5))])
    p = so.predict(now=T0)
    check("disabled returns zero bias + zero confidence",
          p.bias_ms == 0 and p.confidence == 0.0, f"bias={p.bias_ms} conf={p.confidence}")

    so.reset()
    print()
    if _failures:
        print(f"\033[31m{_failures} assertion(s) failed\033[0m")
        return 1
    print("\033[32mAll assertions passed\033[0m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
