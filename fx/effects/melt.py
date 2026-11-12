import time

import numpy as np
import voluptuous as vol

from fx.effects.audio import AudioReactiveEffect
from fx.effects.hsv_effect import HSVEffect
from fx.effects.strip_phase import StripPhase


class Melt(StripPhase, AudioReactiveEffect, HSVEffect):
    """Charge/lull/drop come from the shared strip phase layer
    (fx/effects/strip_phase.py): its gain/fill/shockwave/fade run in the
    output stage, and its ACTIVITY scales Melt's own clock step (the melt
    runs up to charge_activity x faster on a build, drop_activity x on a
    drop, lull_activity x as a lull relaxes). At activity 1 the step is
    left untouched, so off-phase Melt is byte-identical to before."""

    NAME = "Melt"
    CATEGORY = "Atmospheric"
    CONFIG_SCHEMA = vol.Schema(
        {
            vol.Optional(
                "speed",
                description="Effect Speed modifier",
                default=0.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.001, max=1)),
            vol.Optional(
                "reactivity",
                description="Audio Reactive modifier",
                default=0.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0001, max=1)),
            # DARK FLOOR (the star improve plan, 2026-11-12 — his "more dark
            # blobs so that the whole effect isn't as overpoweringly bright
            # compared to other effects in dark mode"): the melt's value is a
            # squared sine chain that is never black between blobs, so a
            # 560-px strip ran ~61% lit against 14–28% for the particle
            # strips. Everything below this level is cut to black and the
            # rest re-stretched to full, so the blobs become separate
            # islands with real gaps: 0.5 measured 33% lit, luminance 0.082
            # (today 0.130). 0 = today, byte-identical — House Star / House
            # Fish and every other Melt keep it; STAR's Strips entry sets 0.5.
            vol.Optional(
                "dark_floor",
                description=(
                    "Cut the melt's brightness below this level to black "
                    "(0 = none): more dark gaps between the blobs"
                ),
                default=0.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=0.9)),
        }
    )

    def on_activate(self, pixel_count):
        self.hl = pixel_count
        self.c1 = np.linspace(0, 1, pixel_count)

        self.timestep = 0
        self.last_time = time.time_ns()
        self.dt = 0

    def config_updated(self, config):
        self._lows_power = 0
        self._lows_filter = self.create_filter(alpha_decay=0.1, alpha_rise=0.1)
        # Melt repurposes the base "flip" switch as a motion-direction toggle:
        # the animation clock runs backward instead of mirroring the output,
        # so flipping mid-run is continuous — no spatial jump, no restart.
        # Clear self.flip (set by _apply_config just before this hook) so the
        # base render path doesn't also flipud the pixels.
        self._direction = -1.0 if config["flip"] else 1.0
        self.flip = False

    def audio_data_updated(self, data):
        self._lows_power = self._lows_filter.update(
            data.lows_power(filtered=False)
        )

    def render_hsv(self):
        self.dt = time.time_ns() - self.last_time
        step = self.dt + (
            self._lows_power
            * self._config["reactivity"]
            / self._config["speed"]
            * 1000000000.0
        )
        act = self._sp_activity
        if act != 1.0:
            step *= act
        self.timestep += self._direction * step
        self.last_time = time.time_ns()

        t1 = self.time(self._config["speed"] * 5, timestep=self.timestep)
        t2 = self.time(self._config["speed"] * 6.5, timestep=self.timestep)

        self.c1[:] = np.linspace(0, 1, self.pixel_count)
        # np.subtract(self.c1, self.hl, out=self.c1)
        # np.abs(self.c1, out=self.c1)
        # np.divide(self.c1, self.hl, out=self.c1)
        np.subtract(1, self.c1, out=self.c1)

        self.v = np.copy(self.c1)
        np.add(self.c1, t2, out=self.c1)

        self.array_sin(self.v)
        np.add(self.v, t1, out=self.v)
        self.array_sin(self.v)
        np.add(self.v, t1, out=self.v)
        self.array_sin(self.v)
        np.power(self.v, 2, out=self.v)

        floor = float(self._config.get("dark_floor", 0.0) or 0.0)
        if floor > 0.0:
            # THE DARK FLOOR: below `floor` is black, the rest stretched
            # back to 0..1 so a blob's peak stays full
            np.subtract(self.v, floor, out=self.v)
            np.divide(self.v, 1.0 - floor, out=self.v)
            np.clip(self.v, 0.0, 1.0, out=self.v)

        self.hsv_array[:, 0] = self.c1
        self.hsv_array[:, 1] = 1
        self.hsv_array[:, 2] = self.v
