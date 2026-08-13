"""Flame bursts for the Dancer effect.

A FlameField is a particle system tuned to read as fire on a coarse LED
matrix: plumes rise with buoyancy, minor vortices swirl them, a lateral
flicker keeps them alive, per-particle size peaks mid-life and everything
scales with the music (louder = bigger, brighter, longer-lived). Mirrored
dancers' opposing plumes deflect UP at the midline like colliding jets.

Kept separate from dancer.py so flame behavior can be tuned (or reused)
without touching the choreography.
"""

from __future__ import annotations

import math

import numpy as np

CAP = 320
VORTEX_CAP = 8
DEG_MARGIN = 10.0   # offscreen cull margin, px
SUB = 2             # render substeps (motion smear)


class FlameField:
    def __init__(self, rng: np.random.Generator):
        self._rng = rng
        self.x = np.zeros(CAP, np.float32)
        self.y = np.zeros(CAP, np.float32)
        self.x0 = np.zeros(CAP, np.float32)   # previous position (smear)
        self.y0 = np.zeros(CAP, np.float32)
        self.vx = np.zeros(CAP, np.float32)
        self.vy = np.zeros(CAP, np.float32)
        self.age = np.zeros(CAP, np.float32)
        self.life = np.full(CAP, 1.0, np.float32)
        self.grad = np.zeros(CAP, np.float32)   # <0 = accent color
        self.size = np.full(CAP, 1.5, np.float32)
        self.phase = np.zeros(CAP, np.float32)  # flicker phase
        self.side = np.zeros(CAP, np.int8)
        self.n = 0
        # vortices
        self.w_x = np.zeros(VORTEX_CAP, np.float32)
        self.w_y = np.zeros(VORTEX_CAP, np.float32)
        self.w_s = np.zeros(VORTEX_CAP, np.float32)  # signed strength
        self.w_age = np.zeros(VORTEX_CAP, np.float32)
        self.w_life = np.zeros(VORTEX_CAP, np.float32)
        self.n_w = 0

    # ── emission ────────────────────────────────────────────────────────

    def emit(
        self, ox, oy, count, mag, scale, side=0,
        dir_rad=None, spread=0.55, third=None, accent=False,
        extra_vx=0.0, extra_vy=0.0,
    ):
        """One plume. `mag` 0..1 is the music magnitude (size, speed,
        life all grow with it); `scale` is the figure height in px.
        `extra_vx/vy` add inherited momentum (px/s) — flames thrown by a
        swinging limb carry its motion."""
        k = int(min(count, CAP - self.n))
        if k <= 0:
            return
        rng = self._rng
        s = slice(self.n, self.n + k)
        if dir_rad is None:
            dirs = rng.uniform(0.0, 2.0 * math.pi, k)
        else:
            dirs = rng.normal(dir_rad, spread, k)
        speed = scale * (0.55 + 1.5 * mag) * rng.uniform(0.35, 1.1, k)
        self.x[s] = ox + rng.normal(0.0, 0.6, k)
        self.y[s] = oy + rng.normal(0.0, 0.6, k)
        self.x0[s] = self.x[s]
        self.y0[s] = self.y[s]
        self.vx[s] = np.cos(dirs) * speed + extra_vx
        self.vy[s] = (
            np.sin(dirs) * speed - scale * 0.18 + extra_vy
        )  # upward bias + inherited limb momentum
        self.age[s] = 0.0
        self.life[s] = rng.uniform(0.55, 1.1, k) * (0.75 + 0.75 * mag)
        if accent:
            self.grad[s] = -1.0
        else:
            if third is None:
                third = int(rng.integers(0, 3))
            self.grad[s] = rng.uniform(third / 3.0, (third + 1) / 3.0, k)
        self.size[s] = np.clip(
            scale * 0.055 * (1.0 + 1.9 * mag) * rng.uniform(0.7, 1.45, k),
            1.0,
            4.5,
        )
        self.phase[s] = rng.uniform(0.0, 2.0 * math.pi, k)
        self.side[s] = side
        self.n += k
        # a couple of minor vortices ride along with each plume
        for _ in range(1 if mag < 0.55 else 2):
            if self.n_w >= VORTEX_CAP:
                self.w_age[np.argmax(self.w_age[: self.n_w])] = 1e9
                self._cull_vortices()
            i = self.n_w
            self.w_x[i] = ox + rng.normal(0.0, scale * 0.12)
            self.w_y[i] = oy - scale * rng.uniform(0.05, 0.3)
            self.w_s[i] = rng.choice([-1.0, 1.0]) * scale * scale * (
                0.55 + 1.3 * mag
            ) * rng.uniform(0.7, 1.3)
            self.w_age[i] = 0.0
            self.w_life[i] = rng.uniform(0.5, 1.0)
            self.n_w += 1

    def emit_points(
        self, xs, ys, cx, cy, count, mag, scale, side=0,
        third=None, accent=False,
    ):
        """Outline burst: particles born along the body's bone samples,
        flying OUTWARD from the figure's centroid — the whole silhouette
        ignites instead of a point at the chest."""
        k = int(min(count, CAP - self.n))
        if k <= 0 or len(xs) == 0:
            return
        rng = self._rng
        idx = rng.integers(0, len(xs), k)
        px = np.asarray(xs)[idx].astype(np.float32)
        py = np.asarray(ys)[idx].astype(np.float32)
        dx = px - cx
        dy = py - cy
        dist = np.hypot(dx, dy)
        rnd = rng.uniform(0.0, 2.0 * math.pi, k)
        ux = np.where(dist > 1e-3, dx / np.maximum(dist, 1e-6), np.cos(rnd))
        uy = np.where(dist > 1e-3, dy / np.maximum(dist, 1e-6), np.sin(rnd))
        speed = scale * (0.5 + 1.3 * mag) * rng.uniform(0.35, 1.05, k)
        s = slice(self.n, self.n + k)
        self.x[s] = px
        self.y[s] = py
        self.x0[s] = px
        self.y0[s] = py
        self.vx[s] = ux * speed + rng.normal(0.0, scale * 0.12, k)
        self.vy[s] = uy * speed - scale * 0.18
        self.age[s] = 0.0
        self.life[s] = rng.uniform(0.5, 1.0, k) * (0.75 + 0.75 * mag)
        if accent:
            self.grad[s] = -1.0
        else:
            if third is None:
                third = int(rng.integers(0, 3))
            self.grad[s] = rng.uniform(third / 3.0, (third + 1) / 3.0, k)
        self.size[s] = np.clip(
            scale * 0.05 * (1.0 + 1.8 * mag) * rng.uniform(0.7, 1.4, k),
            1.0, 4.5,
        )
        self.phase[s] = rng.uniform(0.0, 2.0 * math.pi, k)
        self.side[s] = side
        self.n += k
        for _ in range(2):
            if self.n_w >= VORTEX_CAP:
                self.w_age[np.argmax(self.w_age[: self.n_w])] = 1e9
                self._cull_vortices()
            i = self.n_w
            self.w_x[i] = cx + rng.normal(0.0, scale * 0.2)
            self.w_y[i] = cy - scale * rng.uniform(0.1, 0.35)
            self.w_s[i] = rng.choice([-1.0, 1.0]) * scale * scale * (
                0.5 + 1.2 * mag
            )
            self.w_age[i] = 0.0
            self.w_life[i] = rng.uniform(0.5, 0.9)
            self.n_w += 1

    def _cull_vortices(self):
        keep = self.w_age[: self.n_w] < self.w_life[: self.n_w]
        m = int(np.count_nonzero(keep))
        for arr in (self.w_x, self.w_y, self.w_s, self.w_age, self.w_life):
            arr[:m] = arr[: self.n_w][keep]
        self.n_w = m

    # ── physics ─────────────────────────────────────────────────────────

    def step(self, dt, now, scale, w, h, mid_x=None):
        """Advance the field. `mid_x` (when both mirrored dancers exist)
        makes opposing plumes deflect upward at the midline."""
        n = self.n
        if n:
            self.x0[:n] = self.x[:n]
            self.y0[:n] = self.y[:n]
            heat = np.clip(
                1.0 - self.age[:n] / np.maximum(self.life[:n], 1e-3),
                0.0, 1.0,
            )
            # buoyancy (hot rises), anisotropic drag, lateral flicker
            self.vy[:n] -= scale * 1.05 * heat * dt
            self.vx[:n] *= np.float32(math.exp(-2.4 * dt))
            self.vy[:n] *= np.float32(math.exp(-1.5 * dt))
            self.vx[:n] += (
                np.sin(now * 9.0 + self.phase[:n])
                * (0.14 + 0.30 * heat)
                * scale
                * dt
            )
            # minor vortices: tangential swirl, strength fades with age
            for i in range(self.n_w):
                rx = self.x[:n] - self.w_x[i]
                ry = self.y[:n] - self.w_y[i]
                d2 = rx * rx + ry * ry + 14.0
                g = (
                    self.w_s[i]
                    * (1.0 - self.w_age[i] / max(self.w_life[i], 1e-3))
                    / d2
                )
                self.vx[:n] += -ry * g * dt
                self.vy[:n] += rx * g * dt
            self.x[:n] += self.vx[:n] * dt
            self.y[:n] += self.vy[:n] * dt
            self.age[:n] += dt

            if mid_x is not None:
                side = self.side[:n]
                hit = (
                    ((side == 0) & (self.x[:n] > mid_x) & (self.vx[:n] > 0))
                    | ((side == 1) & (self.x[:n] < mid_x) & (self.vx[:n] < 0))
                )
                if np.any(hit):
                    k = int(hit.sum())
                    vx = self.vx[:n][hit]
                    # colliding jets splash UP like flame fronts meeting
                    self.vy[:n][hit] = (
                        self.vy[:n][hit] * 0.3
                        - np.abs(vx) * self._rng.uniform(0.8, 1.4, k)
                    )
                    self.vx[:n][hit] = -0.15 * vx
                    self.x[:n][hit] = mid_x
                    self.side[:n][hit] = side[hit] + 2

            alive = (self.age[:n] < self.life[:n]) & (
                (self.x[:n] > -DEG_MARGIN)
                & (self.x[:n] < w + DEG_MARGIN)
                & (self.y[:n] > -DEG_MARGIN)
                & (self.y[:n] < h + DEG_MARGIN)
            )
            m = int(np.count_nonzero(alive))
            for arr in (
                self.x, self.y, self.x0, self.y0, self.vx, self.vy,
                self.age, self.life, self.grad, self.size, self.phase,
                self.side,
            ):
                arr[:m] = arr[:n][alive]
            self.n = m
        # vortices drift up and die
        if self.n_w:
            self.w_y[: self.n_w] -= scale * 0.35 * dt
            self.w_age[: self.n_w] += dt
            self._cull_vortices()

    # ── render ──────────────────────────────────────────────────────────

    def render(self, frame, sampler, accent_rgb, kernel_fn, now, impulse):
        """Additive splat with a hot-core color ramp. `sampler` maps 0..1
        gradient positions to (n,3) RGB; `kernel_fn(radius)` returns
        (k_dx, k_dy, k_w) offset tables (the dancer's cached kernels)."""
        n = self.n
        if not n:
            return
        h_frame, w_frame = frame.shape[:2]
        cells = w_frame * h_frame
        heat = np.clip(
            1.0 - self.age[:n] / np.maximum(self.life[:n], 1e-3), 0.0, 1.0
        )
        g = self.grad[:n]
        rgbs = sampler(np.clip(g, 0.0, 1.0)).astype(np.float32)
        acc = g < 0.0
        if np.any(acc):
            rgbs[acc] = accent_rgb
        # hot core: young flames pull toward white
        core = (heat * heat * 0.35)[:, None]
        rgbs = rgbs + (255.0 - rgbs) * core
        flick = 0.8 + 0.2 * math.sin(now * 13.0) + 0.35 * min(impulse, 1.0)
        env = np.power(heat, 0.85) * np.clip(flick, 0.5, 1.35)
        rgbs *= env[:, None]
        # radius peaks mid-life (lick grows, then dissolves)
        radius = self.size[:n] * (0.55 + 1.4 * heat * (1.0 - heat) + 0.25 * heat)
        buckets = np.round(radius / 0.75).astype(np.int32)
        fr = np.arange(1, SUB + 1, dtype=np.float32) / SUB
        for b in np.unique(buckets):
            sel = buckets == b
            r = float(np.clip(b * 0.75, 1.0, 5.5))
            k_dx, k_dy, k_w = kernel_fn(r)
            xs = (
                self.x0[:n][sel][:, None]
                + (self.x[:n][sel] - self.x0[:n][sel])[:, None] * fr
            ).ravel()
            ys = (
                self.y0[:n][sel][:, None]
                + (self.y[:n][sel] - self.y0[:n][sel])[:, None] * fr
            ).ravel()
            xi = np.round(xs).astype(np.int32)
            yi = np.round(ys).astype(np.int32)
            pn = len(xi)
            kn = len(k_dx)
            px = (xi[:, None] + k_dx[None, :]).ravel()
            py = (yi[:, None] + k_dy[None, :]).ravel()
            valid = (
                (px >= 0) & (px < w_frame) & (py >= 0) & (py < h_frame)
            )
            idx = (py * w_frame + px)[valid]
            kw = np.broadcast_to(k_w[None, :], (pn, kn)).ravel()[valid]
            rgb_sub = rgbs[sel] / SUB
            for ch in range(3):
                per_pt = np.repeat(rgb_sub[:, ch], SUB)
                vals = (
                    np.broadcast_to(per_pt[:, None], (pn, kn)).ravel()[valid]
                    * kw
                )
                frame[..., ch] += np.bincount(
                    idx, weights=vals, minlength=cells
                ).reshape(h_frame, w_frame).astype(np.float32)
