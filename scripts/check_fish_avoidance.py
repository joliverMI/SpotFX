"""Measure fish mutual avoidance (fx/effects/fish.py `avoid_strength`).

Read-only, offline, no live access: drives the real vendored effect through
fx.headless at his crystal-mapper's shape and counts CROSSING EVENTS — the
rising edge of two fish coming within a body length of each other — plus the
two failure modes a too-strong steer would produce (jitter, orbit-lock).

Run at HIS current state (jiggle 0.5, roam_scale 0.75) so the chosen default
is picked against the crowd he is actually looking at.

    .venv/bin/python scripts/check_fish_avoidance.py
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fx import headless  # noqa: E402

DT = 1.0 / 60.0
ROWS, COLS = 37, 72

# his live Matrix entry, at the state he is watching right now
HIS = {
    "particle_count": 3, "radius_scale": 1.8, "horizon_scale": 0.19,
    "blob_size": 2.5, "x_offset": 0.5, "y_offset": 0.5, "spin": 0.37,
    "base_speed": 0.3, "jiggle": 0.5, "roam_scale": 0.75,
    "tether_scatter": 0.0, "reactivity_scale": 1.0, "speed_jump": 1.0,
    "speed_jog": 1.0, "brightness_audio": 0.5, "size_audio": 0.5,
    "color_shift": 1, "impulse_decay": 0.06, "reverse": False,
}


async def _measure(strength, count, seconds=40.0, seed=5):
    """Return (crossings, overlap_frac, jitter_deg_per_s, clamp_sat)."""
    with tempfile.TemporaryDirectory() as td:
        host = await headless.start_headless_host(
            str(Path(td) / "f"), pixel_count=ROWS * COLS, rows=ROWS,
            device_id="f",
        )
        virtual = host.virtuals.get("f")
        with headless.fake_clock() as clock:
            eff = headless.attach_effect(
                host, virtual, "fish",
                dict(HIS, particle_count=count, avoid_strength=strength),
            )
            eff._rng = np.random.default_rng(seed)
            for _ in range(120):          # settle
                clock.advance(DT)
                f = virtual.assemble_frame()
                if f is not None:
                    virtual.flush(f)

            body = eff._body_len_px()
            near_prev = set()
            crossings = 0
            turn_sum, turn_n, sat = 0.0, 0, 0
            over_hits, over_frames = 0, 0
            prev_hd, prev_n = eff.p_hd[: eff.n].copy(), eff.n
            for _ in range(int(seconds / DT)):
                clock.advance(DT)
                f = virtual.assemble_frame()
                if f is not None:
                    virtual.flush(f)
                n = eff.n
                live = np.flatnonzero(eff.p_mode[:n] < 2)
                if live.size > 1:
                    x = eff.p_x[:n][live] * eff.sx
                    y = eff.p_y[:n][live] * eff.sy
                    d = np.hypot(x[None, :] - x[:, None],
                                 y[None, :] - y[:, None])
                    np.fill_diagonal(d, np.inf)
                    near = set(map(tuple, np.argwhere(d < body)))
                    crossings += len(near - near_prev)
                    near_prev = near
                    over_hits += int(np.count_nonzero(d < body)) // 2
                    over_frames += live.size * (live.size - 1) // 2
                k = min(prev_n, n)
                if k:
                    dh = np.abs(
                        (eff.p_hd[:k] - prev_hd[:k] + np.pi) % (2 * np.pi)
                        - np.pi
                    )
                    turn_sum += float(dh.sum())
                    turn_n += k
                    ceil = eff.p_spd[:k] / eff.turn_radius_px * DT
                    sat += int(np.count_nonzero(dh > ceil * 0.98))
                prev_hd, prev_n = eff.p_hd[:n].copy(), n
            await host.shutdown()
    jitter = np.degrees(turn_sum / max(turn_n, 1)) / DT
    return (crossings // 2, over_hits / max(over_frames, 1), jitter,
            sat / max(turn_n, 1))


def main():
    print(f"fish mutual avoidance — his state (jiggle {HIS['jiggle']}, "
          f"roam_scale {HIS['roam_scale']}), 40s, 60fps\n")
    for count in (6, 10, 16):
        print(f"  particle_count={count}")
        base = None
        for s in (0.0, 0.25, 0.45, 0.7, 1.0):
            c, ov, j, sat = asyncio.run(_measure(s, count))
            if base is None:
                base = ov
            delta = "" if s == 0.0 else f"({100*(ov-base)/max(base,1e-9):+.0f}%)"
            tag = "  <- NEGATIVE CONTROL" if s == 0.0 else ""
            print(f"    strength {s:<5} overlap {ov:6.2%} {delta:>9}"
                  f"   crossings {c:5d}   turn {j:6.1f} deg/s"
                  f"   clamp-sat {sat:5.1%}{tag}")
        print()


if __name__ == "__main__":
    main()
