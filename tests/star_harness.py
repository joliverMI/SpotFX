"""A headless room for Star (fx/effects/radial.py) — the star plan's rig.

Star draws nothing of its own: it samples the `radial-dummy` strip (the
scene's Strips effect, Melt on STAR) and bends it into rings. So the room
hosts BOTH: a 280-px `radial-dummy` running Melt and the crystal-shaped
72 x 37 Matrix virtual running Radial, on the real render pipeline
(fx.headless, a fake clock — also behind time.time_ns, which Melt reads),
driven by the PRODUCTION ResponseEngine on the FacadeExecutor through
tests/strip_phase_harness.Room. Each step renders the strip FIRST and
publishes it as `assembled_frame` (what Radial reads), then the crystal,
and turns Star the way its audio callback would (`impulse x spin`).

Used by tests/test_star_phases.py, tests/test_star_programs.py and
scripts/check_star_phases.py.
"""
from __future__ import annotations

import numpy as np

from strip_phase_harness import PALETTE, Room, _AudioFrame  # noqa: F401

STAR = "crystal"
STRIP = "radial-dummy"
COLS, ROWS = 72, 37
STRIP_N = 280
# Star rotates on its own clock in the rig: this many revolutions a second
STAR_REV_S = 0.15


def star_room(tmp_dir, *, radial=None, melt=None, layer=True, **kw):
    """A Room with the strip (first — Star samples it) and the crystal."""
    rcfg = {"source_virtual": STRIP, "edges": 6, "polygon": True,
            "star": 0.3, "twist": 0.0, "spin": 0.55,
            "background_brightness": 0.0, "gradient": PALETTE}
    rcfg.update(radial or {})
    mcfg = {"gradient": PALETTE, "speed": 0.08, "reactivity": 0.3,
            "blur": 1.0, "brightness": 1.0, "background_brightness": 0.0}
    mcfg.update(melt or {})
    return StarRoom(tmp_dir, {
        STRIP: ("melt", STRIP_N, 1, mcfg),
        STAR: ("radial", COLS * ROWS, ROWS, rcfg),
    }, layer=layer, **kw)


class StarRoom(Room):
    """strip_phase_harness.Room, plus: the strip's frame is published as
    `assembled_frame` before the crystal renders, and Star turns."""

    rev_s = STAR_REV_S

    def step(self, n: int = 1):
        from strip_phase_harness import DT
        for _ in range(n):
            self.clock.advance(DT)
            self.i += 1
            audio = _AudioFrame(self.i)
            for vid, v in self.virtuals.items():
                eff = self.effects[vid]
                if type(eff)._strip_phase and hasattr(eff, "audio_data_updated"):
                    with eff.lock:
                        eff.audio_data_updated(audio)
                if vid == STAR and hasattr(eff, "_reactive_advance"):
                    with eff.lock:
                        adv = self.rev_s * DT
                        eff._reactive_advance += adv
                        eff.spin_total = (eff.spin_total + adv) % 1.0
                f = v.assemble_frame()
                if f is not None:
                    v.assembled_frame = f
                    v.flush(f)
                    self.frames[vid].append(
                        np.array(f, dtype=np.float64, copy=True))

    @property
    def star(self):
        return self.effects[STAR]

    def matrix(self) -> np.ndarray:
        """The crystal's last rendered matrix (ROWS x COLS x 3, 0..255)."""
        return np.asarray(self.star.matrix, dtype=np.float64)

    def secs(self, s: float) -> int:
        from strip_phase_harness import FPS
        return int(round(s * FPS))


def lit_cells(m: np.ndarray, thresh: float = 20.0) -> int:
    return int((np.asarray(m).max(axis=-1) > thresh).sum())


def white_cells(m: np.ndarray, level: float = 200.0) -> int:
    m = np.asarray(m)
    return int((m.min(axis=-1) > level).sum())


__all__ = ["star_room", "StarRoom", "lit_cells", "white_cells", "STAR",
           "STRIP", "COLS", "ROWS", "PALETTE"]
