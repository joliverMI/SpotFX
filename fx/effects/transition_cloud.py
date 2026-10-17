"""THE TRANSITION PROGRAMS, PHASE 4 — every remaining pair of the
transitions-drop plan (/home/javi/fleet-spotfx/data/transitions-drop-plan/
report.md, revision 3, "Thematic transitions" and "Phase 4"), on the clock
fx/effects/transition_program.py built for INFALL and ERUPTION (read that
module's docstring first: the registry, the ONE-PICTURE-BY-MAX rule, the
anchor, the clock). SpotFX-authored, not fork code; fx/VENDOR.md #75
records the effect hooks it reads.

ONE CLOUD, THREE VERBS, factored the way the plan names them, so a future
effect joins by answering three questions:

  RELEASE  how the OUTGOING form lets go of its pieces — a subclass's
           `_release(inc)`: the Fireworks' sparks as they fly, the Black
           Hole's ring unwinding (its blobs leave on the field's own
           velocity), the eye EXPLODING (FLAME LICK), a fish shattering
           into the dots of its body (SHOAL BREAK), a chain unspooling
           from its tail (UNRAVEL).
  FLIGHT   a field that moves the cloud on the program's own clock — a
           subclass's `_fly(inc, t, dt)`: a gravitational pull bending the
           sparks into spiral arms (LENSING), an outward push (FOUNTAIN),
           drag and swirl (the shards, the dots).
  FORM     how the INCOMING effect takes the cloud — chosen by the
           incoming effect, never the outgoing, by `_make_former`:
             FieldFormer   the Black Hole: over the last
                           `transition_velocity_blend_ms` every piece's
                           velocity is blended into the Black Hole's own
                           field at its radius (Blackhole2d._program_field_
                           velocity) and the real Black Hole ADOPTS the
                           cloud still moving (appended) — INFALL's FORM.
             TargetFormer  Orbits / Fish / Squiggles: every piece
                           converges onto a LIVE, MOVING formation point
                           of the incoming effect (`_formation_points()`)
                           on a cubic Hermite in coordinates relative to
                           its target, leaving with its own velocity and
                           arriving with the target's — ERUPTION's FORM,
                           with an optional per-piece stagger (threads).
             SparkFormer   Fireworks: the last stretch flies every piece
                           by the Fireworks' own drag (Fireworks2d._program_
                           field_velocity) and the real Fireworks adopts
                           them as its own sparks, still flying.
             FadeFormer    anything else: the pieces slow and fade.

THE PAIRS (transition_program.PROGRAMS is the table):

  LENSING     Fireworks -> Black Hole (his "Lensing is great", then "there
              appears to be an abrupt change in the trajectory of the
              particles after the transition ends. smooth that out"). Every
              spark keeps its momentum; a central pull that grows over the
              flight, with a swirl in the Black Hole's own sense, bends the
              trails into spiral arms round the forming horizon; then the
              FieldFormer's velocity blend, and the real Black Hole
              continues each spark's motion (no trajectory kink).
  FOUNTAIN    Black Hole -> Fireworks, the reverse: the ring gathers
              toward the centre turning ever faster on the spin it had,
              and at the anchor every blob sprays out of it into sparks
              across the whole set by angle (an outward ring flung off the
              panel was tried first and read as nothing — the pieces left
              before they sprayed); the sparks fly by the Fireworks' own
              drag and the real Fireworks takes them as its own.
  FLAME LICK  Sauron / Eye -> the particle effects (his "make the actual
              eye explode, like have all the pixels (or some fraction of
              them, say half for now) explode and then collapse into the
              black or merge into particles"). The eye's own lit cells are
              split by `explode_frac`: those shards fly out from the eye's
              centre with a little swirl, each in the SET colour nearest
              its own cell (never the white-hot core); the rest contract
              toward the centre while they fade (collapse into the black).
              The eye dissolves into its shards over DISSOLVE_S (his "the
              change from the eye to the explosion is too abrupt ... they
              need to blend better"). The shards slow, and the incoming
              effect's FORM takes them (into the Black Hole: pulled in and
              velocity-blended, like Lensing).
  IGNITION    the particle effects -> Sauron / Eye (his "don't have the
              initial ring around the eye just appear immediately. have it
              come in with the rest of the eye"). The arriving cloud (the
              Black Hole's ring unwound into sparks — no flash) gathers in
              a vortex onto the iris rim, read live off the incoming eye
              (`program_rim`); the eye is revealed from the rim inward (the
              iris) and outward (the flames) by ONE fill curve, so the
              rim's brightness IS the fill's — it never pops in; a landing
              spark only flares locally and fades; the slit opens from a
              hairline (`_lens_gain`). The program hands over at
              IGNITION_HANDOFF_GAIN and the real eye's body fades up FROM
              that brightness (`snap["body_gain"]`), not from its own 25 %.
  SHOAL BREAK Fish -> Orbits / Squiggles (his "have the implosion portion
              move as if it was orbits ... they should implode to the
              moving orbits point"). Each fish's body shatters into its
              dots, which keep the fish's heading and spread
              (`transition_scatter`), then implode onto the live, moving
              orbit blobs / chain heads.
  SHOALING    Orbits -> Fish (his "smooth out the velocity transitions
              across this transition through the transformation on the
              shoaling"). FORM here is the REAL Fish from the first frame:
              the program leaves the outgoing snapshot for the Fish to
              adopt, which now carries each blob's turning rate (`om`) —
              every fish starts AT its blob, heading and speed (phase 3's
              fix) and turning at the blob's own rate, easing into its own
              steering (fish.PEEL_S), its body laid back along that curve.
              The program only lets the blobs the Fish does not take fly
              on and fade, and the outgoing picture fade under the fish.
  UNRAVEL     Squiggles <-> Orbits / Fish: out of Squiggles, each chain
              unspools from its tail into dots (each leaves along the
              chain's own path at the walking speed) that implode onto the
              incoming form; into Squiggles, the cloud threads onto the
              live chain heads one piece after another.

SET COLOURS ONLY, BY MAX. Every piece is drawn in the outgoing set's colour
sliding to the incoming set's at the same gradient position; every layer
composes by max (transition_program.splat_max); there is no white term
anywhere — the flame lick's shards take the set colour NEAREST their cell.

OUT OF STAR (the star plan, data/star-plan/report.md, 2026-10-13 — his
"The ones from star to the others are great and approved"). Star draws its
bands from the strip; on a program its RELEASE is its own
(radial.Radial2d._program_snapshot): ~`transition_bands_pieces` pieces from
its lit cells, each in the SET colour nearest its cell and moving with the
ring it sat on (v = omega x r). Four pairs then run an existing program
unchanged — INFALL (-> Black Hole), FOUNTAIN (-> Fireworks), IGNITION (->
Sauron / Eye), UNRAVEL (-> Squiggles, threading onto the chain heads) — and
two are new flights here:

  UNWIND      Star -> Orbits: the pieces keep turning on their rings for
              `transition_bands_hold_ms` (the tangential velocity kept, the
              radial part settling out — `turn_about`), then unwind outward
              (`transition_unwind` px/s^2) and condense onto the LIVE orbit
              blobs (the TargetFormer).
  CLUSTER     Star -> Fish: the pieces turn and unwind a little, then each
              gathers onto one of the Fish's own count of SEED pieces
              (angularly spread, the brightest first), and each cluster then
              flies onto a live fish on the TargetFormer's Hermite — so every
              piece arrives ON its fish with the fish's velocity and fades
              into it as the Fish fades up.

INTO STAR (2026-10-14, the Admiral: "Do rec on transitions" — the plan's
revised recommendation, data/star-plan/report.md revision 2, after his
"the star just appears, make it smoother" and "all the transitions to star
have the same problem"). Every partner RELEASES its pieces its own way and
Star FORMs them — the RingFormer, chosen by the incoming effect like every
other former:

  RingFormer  FORM begins at transition_program.STAR_FORM_AT (0.35) of the
              program. Each piece, at its own glide start (spread so the
              LANDINGS run from FORM + RING_LOCK_S to RING_LAND_END_S before
              the end — never all on one frame), takes the band of Star's
              strip (radial.Radial2d._program_bands — the strip's bright
              peaks, read once at FORM) nearest where its own FLIGHT is
              taking it, at its own angle in Star's ROTATING frame, and
              glides onto it over RING_LOCK_S on a cubic Hermite relative to
              the moving band point — leaving with its own velocity,
              arriving riding the ring's rotation (velocity continuous at
              both ends). Star's picture is revealed by a per-cell gain, the
              max of: (1) a soft radial FRONT riding out from the core over
              Star's own `ring_reveal_front_s` — in Star's shaped radius, but
              paced by Star's own CELLS: it passes an even share of them
              every frame (feathered over RING_FRONT_W of them), because the
              cells crowd into a narrow band of radius and a front at a
              steady radial speed lights that whole band at once — at
              RING_LEVEL until the TAIL
              eases the level inside the front to full over the program's
              last RING_TAIL_S; (2) a GLOW on every landed piece's band,
              growing from RING_GLOW_R0 cells at RING_GLOW_GROW cells/s (one
              distance transform a frame). A landed piece dissolves into its
              band over RING_FADE_S once the front has passed its cell (and
              by the end regardless). No frame shows the whole star at once.
  FOUNTAIN    Black Hole -> Star: the ring gathers and sprays at FORM.
  SHOAL BREAK Fish -> Star: the bodies shatter into their dots on the mark.
  SPARK RINGS Fireworks -> Star: the sparks fly on, slowing, and land.
  FLAME LICK  Sauron / Eye -> Star: the eye explodes on the mark.
  UNRAVEL     Squiggles -> Star: each chain unspools from its tail.
  WIND        Orbits -> Star — UNWIND with time inverted (his "Just reverse
              the one for the other direction"): each orbit blob comes
              apart into an arc of WIND_DOTS dots along its OWN orbit over
              WIND_ARC_S (±WIND_ARC_DEG, every dot still turning at the
              blob's rate), the arcs wind INWARD on UNWIND's own turn-about
              law with the push reversed (-`transition_unwind`), and the
              RingFormer glides them onto the rings.
The old crossfade choreography toward Star (radial's bloom out of the
centre, the particle side's gather) never runs for these pairs: a program
switch has no crossfade sibling, and radial._adopt_handoff stands down
while a program owns the arrival.

THE ANCHORS (transition_program.anchor_frac, what the trigger clock leads
by): Lensing's is its ignition (like Infall's); the Fountain sprays at
FOUNTAIN_ANCHOR; the Flame Lick explodes, the Shoal Break shatters and a
chain unspools ON the mark (0); the Ignition's rim catches at
IGNITION_ANCHOR; the Shoaling's fish are formed at SHOALING_ANCHOR; the
threads complete at THREAD_ANCHOR.
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np

import fx.effects.particle_handoff as particle_handoff
from fx.effects import transition_program as tp
from fx.effects.transition_program import (
    TransitionProgram,
    _sample_rgb,
    _smoothstep,
    splat_max,
    splat_path,
)

PIECE_CAP = 220            # at most this many pieces in one cloud
MIN_PIECES = 24            # a cloud of three blobs reads as three dots
LENS_G0 = 3.2              # Lensing's pull at full ramp, normalized units/s^2
LENS_T0 = 1.3              # ... and its swirl (tangential) at full ramp
LENS_DRAG = 0.6            # 1/s, so the arms stay bounded
FOUNTAIN_GATHER = 0.85     # the unwind gathers the ring this far in
FOUNTAIN_SPRAY_PX = 70.0   # spray speed added to each spark, px/s
FLIGHT_DRAG = 1.2          # 1/s: the ordinary flight's slowing
SHARD_DRAG = 1.8           # 1/s: the flame lick's shards slow faster
SHARD_SPEED_PX = (22.0, 60.0)
SHARD_SWIRL = 0.3          # tangential fraction of a shard's launch speed
SHARD_CAP = 420
LIT_MIN = 24.0             # a cell of the eye is "lit" above this (0..255)
DISSOLVE_S = 0.3           # the eye dissolves into its shards over this
SHARD_RISE = 0.6           # ... while the shards rise over this much of it
COLLAPSE_S = 0.7           # the other half contracts and fades over this
IGNITION_HANDOFF_GAIN = 0.7
IGNITION_LAND = (0.42, 0.62)   # landing times, fractions of the program
IGNITION_FILL_AT = 0.2         # the fill starts here, ends at the program end
LAND_FADE_S = 0.35             # a landed spark's sparkle fades over this
LENS_MIN = 0.06                # the slit's opening width at its narrowest
SCATTER_PX = 16.0              # a shard / dot's sideways spread at scatter 1
UNSPOOL_S = 0.45               # a chain unspools tail-to-head over this
UNSPOOL_RISE_S = 0.18          # ... its dots easing in over the chain first
SURPLUS_FADE_S = 0.6           # SHOALING's untaken blobs fade over this
SEED_CHAINS = 4                # chains seeded into an empty Squiggles


def _cap_by_brightness(bright: np.ndarray, cap: int) -> np.ndarray:
    """Indices of the `cap` brightest pieces (all of them when fewer)."""
    if bright.size <= cap:
        return np.arange(bright.size)
    return np.sort(np.argsort(bright)[::-1][:cap])


def _split(rng, arrays: dict, n_min: int) -> dict:
    """A cloud of too few pieces split into at least n_min, each copy a
    pixel or so from its parent, moving a little faster or slower."""
    n = arrays["x"].size
    if n == 0 or n >= n_min:
        return arrays
    reps = int(math.ceil(n_min / n))
    m = n * reps
    out = {k: (np.repeat(v, reps, axis=0)) for k, v in arrays.items()}
    jit = rng.normal(0.0, 1.1, (2, m)).astype(np.float32)
    out["x"] = out["x"] + jit[0]
    out["y"] = out["y"] + jit[1]
    k = rng.uniform(0.85, 1.15, m).astype(np.float32)
    out["vx"] = out["vx"] * k
    out["vy"] = out["vy"] * k
    return out


def nearest_set_grad(pal: Optional[np.ndarray], rgb: np.ndarray):
    """For each colour (n, 3), the gradient position of the SET colour
    nearest it by hue/chroma (both normalised to their own brightest
    channel), and that set colour at full. The flame lick's rule: a shard
    carries the set colour nearest its own cell — so the eye's white-hot
    core becomes the set's nearest (brightest) stop, never white."""
    grid = tp.PALETTE_GRID
    if pal is None or rgb.size == 0:
        return np.zeros(len(rgb), np.float32), rgb.astype(np.float32)
    pn = pal / np.maximum(pal.max(axis=1, keepdims=True), 1.0)
    cn = rgb / np.maximum(rgb.max(axis=1, keepdims=True), 1.0)
    d = ((cn[:, None, :] - pn[None, :, :]) ** 2).sum(axis=2)
    j = np.argmin(d, axis=1)
    full = pal[j] * (255.0 / np.maximum(pal[j].max(axis=1, keepdims=True), 1.0))
    return grid[j], full.astype(np.float32)


# ── the FORMERS (FORM, chosen by the incoming effect) ──────────────────────

class _Former:
    """FORM's interface. `advance` moves the cloud this frame (calling the
    program's own FLIGHT for pieces not yet forming), `gain` is how much
    of the incoming effect shows, `hand_off` gives it the cloud."""

    def __init__(self, prog, inc, t_form):
        self.p = prog
        self.t_form = float(t_form)

    def advance(self, inc, t, dt):
        self.p._fly(inc, t, dt)

    def gain(self, t) -> float:
        d = self.p.duration
        return float(_smoothstep((t - self.t_form) / max(d - self.t_form, 1e-3)))

    def colour(self, t, rgb):
        """The pieces' colours this frame (n, 3) — a former may move them
        toward where they land (the RingFormer's bands)."""
        return rgb

    def hand_off(self, inc):
        return None


class FadeFormer(_Former):
    def advance(self, inc, t, dt):
        self.p._fly(inc, t, dt)
        if t >= self.t_form:
            d = self.p.duration
            f = 1.0 - float(_smoothstep((t - self.t_form)
                                        / max(d - self.t_form, 1e-3)))
            self.p.form_fade[:] = f


class FieldFormer(_Former):
    """INFALL's FORM (transition_program.InfallProgram, the same rule): the
    velocity the flight carried, held in polar coordinates about the Black
    Hole so it turns with the piece, blended into the field over the last
    velocity_blend_s; then appended to the real Black Hole still moving."""

    def __init__(self, prog, bh, t_form=None):
        s = prog.settings
        super().__init__(prog, bh,
                         prog.duration - s.infall_form_s() if t_form is None
                         else t_form)
        self.form_s = max(prog.duration - self.t_form, 1e-3)
        self.cx, self.cy = float(bh.cx), float(bh.cy)
        self.sx = max(float(bh.sx), 1e-6)
        self.sy = max(float(bh.sy), 1e-6)
        self._v0 = None

    def _polar(self, x, y, vx, vy):
        th = np.arctan2((y - self.cy) / self.sy, (x - self.cx) / self.sx)
        nvx, nvy = vx / self.sx, vy / self.sy
        return (nvx * np.cos(th) + nvy * np.sin(th),
                -nvx * np.sin(th) + nvy * np.cos(th))

    def _cart(self, x, y, vr, vt):
        th = np.arctan2((y - self.cy) / self.sy, (x - self.cx) / self.sx)
        return ((vr * np.cos(th) - vt * np.sin(th)) * self.sx,
                (vr * np.sin(th) + vt * np.cos(th)) * self.sy)

    def advance(self, bh, t, dt):
        p = self.p
        if t < self.t_form:
            p._fly(bh, t, dt)
            return
        if self._v0 is None:
            self._v0 = self._polar(p.x, p.y, p.vx, p.vy)
        w = float(np.clip((t - self.t_form) / self.form_s, 0.0, 1.0))
        w = w * (2.0 - w)
        cvx, cvy = self._cart(p.x, p.y, *self._v0)
        fn = getattr(bh, "_program_field_velocity", None)
        fvx, fvy = fn(p.x, p.y) if fn is not None else (0 * cvx, 0 * cvy)
        p.vx = ((1.0 - w) * cvx + w * fvx).astype(np.float32)
        p.vy = ((1.0 - w) * cvy + w * fvy).astype(np.float32)
        p.x = (p.x + p.vx * dt).astype(np.float32)
        p.y = (p.y + p.vy * dt).astype(np.float32)

    def gain(self, t) -> float:
        if self.p.settings.on_mark:
            return 1.0
        # the horizon ignites as it feeds: whole at the start of FORM
        h = 0.5 * self.t_form
        return float(_smoothstep((t - h) / max(h, 1e-3)))

    def hand_off(self, bh):
        adopt = getattr(bh, "_adopt_handoff", None)
        if adopt is None:
            return
        p = self.p
        alive = p.drawn_bright() > 0.03
        if not alive.any():
            return
        adopt(snap={
            "src": "program",
            "t": particle_handoff.now(),
            "dims": p.dims,
            "px": p.x[alive].astype(np.float32),
            "py": p.y[alive].astype(np.float32),
            "vx": p.vx[alive].astype(np.float32),
            "vy": p.vy[alive].astype(np.float32),
            "grad": p.grad[alive].astype(np.float32),
            "bright": np.clip(p.drawn_bright()[alive], 0.0, 1.0).astype(np.float32),
            "gradient": bh._config.get("gradient"),
            "spin_sign": 0.0,
            "blob_size": float(getattr(bh, "blob_size", 0.0)) or None,
            "trail": None,
            "append": True,
            "gesture": p.name,
        }, allow_hold=False)


class SparkFormer(_Former):
    """The Fireworks' FORM: from t_form every piece flies by the Fireworks'
    own drag, and the real Fireworks adopts them as its sparks."""

    def advance(self, fw, t, dt):
        p = self.p
        if t < self.t_form:
            p._fly(fw, t, dt)
            return
        p.x = (p.x + p.vx * dt).astype(np.float32)
        p.y = (p.y + p.vy * dt).astype(np.float32)
        fn = getattr(fw, "_program_field_velocity", None)
        if fn is not None:
            p.vx, p.vy = fn(p.x, p.y, p.vx, p.vy, dt)
        else:
            k = np.float32(math.exp(-FLIGHT_DRAG * dt))
            p.vx, p.vy = p.vx * k, p.vy * k

    def hand_off(self, fw):
        adopt = getattr(fw, "_adopt_handoff", None)
        if adopt is None:
            return
        p = self.p
        b = p.drawn_bright()
        alive = b > 0.03
        if not alive.any():
            return
        life = getattr(fw, "burst_life", 1.0) * p.rng.uniform(
            0.8, 1.2, int(alive.sum()))
        adopt(snap={
            "src": "program",
            "t": particle_handoff.now(),
            "dims": p.dims,
            "px": p.x[alive], "py": p.y[alive],
            "vx": p.vx[alive], "vy": p.vy[alive],
            "grad": p.grad[alive],
            "bright": np.clip(b[alive], 0.0, 1.0).astype(np.float32),
            "life": life.astype(np.float32),
            "gradient": fw._config.get("gradient"),
            "trail": None,
            "append": True,
            "gesture": p.name,
        }, allow_hold=False)


class TargetFormer(_Former):
    """ERUPTION's FORM (transition_program.EruptionProgram), per piece:
    from its own start each piece takes the target NEAREST where it will
    be, and converges onto it on a cubic Hermite relative to the moving
    target — leaving with its own velocity, arriving ON the target with the
    target's — fading as it arrives. `stagger` spreads the starts over that
    fraction of the FORM stage (the threads arrive one after another)."""

    ARRIVE_MIN_S = 0.18

    def __init__(self, prog, inc, t_form, stagger=0.0):
        super().__init__(prog, inc, t_form)
        n = prog.n
        d = prog.duration
        span = max(d - self.t_form, 1e-3)
        u = prog.rng.uniform(0.0, 1.0, n).astype(np.float32)
        self.ts = (self.t_form + stagger * span * u).astype(np.float32)
        self.ts = np.minimum(self.ts, d - self.ARRIVE_MIN_S)
        self.j = np.full(n, -1, dtype=np.int64)
        self.d0x = np.zeros(n, np.float32)
        self.d0y = np.zeros(n, np.float32)
        self.e0x = np.zeros(n, np.float32)
        self.e0y = np.zeros(n, np.float32)
        self._tq = None
        self._tu = None
        self.targets_seen = False
        self.seeded = 0
        self.last_s = np.zeros(n, np.float32)

    def _targets(self, inc, dt):
        fn = getattr(inc, "_formation_points", None)
        if fn is None:
            return None
        try:
            qx, qy = fn()
        except Exception:
            return None
        qx = np.asarray(qx, dtype=np.float32)
        qy = np.asarray(qy, dtype=np.float32)
        if qx.size == 0:
            return None
        if self._tq is not None and self._tq[0].size == qx.size and dt > 0:
            ux = (qx - self._tq[0]) / dt
            uy = (qy - self._tq[1]) / dt
            if self._tu is not None and self._tu[0].size == qx.size:
                ux = 0.5 * ux + 0.5 * self._tu[0]
                uy = 0.5 * uy + 0.5 * self._tu[1]
        else:
            ux = np.zeros_like(qx)
            uy = np.zeros_like(qy)
        self._tq = (qx, qy)
        self._tu = (ux, uy)
        return qx, qy, ux, uy

    def _seed(self, inc):
        """An incoming form with nothing to form ONTO yet (Squiggles walks
        no chain until a beat) is given its first few from the cloud
        itself: its own adoption starts a chain at each of the brightest
        pieces, and the rest of the cloud threads onto those."""
        p = self.p
        adopt = getattr(inc, "_adopt_handoff", None)
        if adopt is None or not hasattr(inc, "chains") or p.n == 0:
            return
        k = int(min(SEED_CHAINS, p.n))
        order = np.argsort(p.drawn_bright())[::-1][:k]
        adopt(snap={"src": "program", "t": particle_handoff.now(),
                    "dims": p.dims,
                    "px": p.x[order].astype(np.float32),
                    "py": p.y[order].astype(np.float32),
                    "grad": p.grad[order].astype(np.float32),
                    "bright": np.clip(p.bright[order], 0.4, 1.0),
                    "gradient": None}, allow_hold=False)
        self.seeded = k

    def advance(self, inc, t, dt):
        p = self.p
        targets = self._targets(inc, dt)
        if targets is None and t >= self.t_form and not self.seeded:
            self._seed(inc)
            targets = self._targets(inc, dt)
        p._fly(inc, t, dt)
        if targets is None:
            if t >= self.t_form:
                f = 1.0 - float(_smoothstep(
                    (t - self.t_form) / max(p.duration - self.t_form, 1e-3)))
                p.form_fade[:] = np.minimum(p.form_fade, f)
            return
        self.targets_seen = True
        qx, qy, ux, uy = targets
        m = qx.size
        forming = t >= self.ts
        new = forming & (self.j < 0)
        if new.any():
            idx = np.flatnonzero(new)
            tau0 = np.maximum(p.duration - self.ts[idx], 1e-3)
            fx_ = p.x[idx] + p.vx[idx] * 0.25 * tau0
            fy_ = p.y[idx] + p.vy[idx] * 0.25 * tau0
            gx_ = qx[None, :] + ux[None, :] * (0.5 * tau0)[:, None]
            gy_ = qy[None, :] + uy[None, :] * (0.5 * tau0)[:, None]
            j = np.argmin((fx_[:, None] - gx_) ** 2 + (fy_[:, None] - gy_) ** 2,
                          axis=1)
            self.j[idx] = j
            self.d0x[idx] = p.x[idx] - qx[j]
            self.d0y[idx] = p.y[idx] - qy[j]
            self.e0x[idx] = p.vx[idx] - ux[j]
            self.e0y[idx] = p.vy[idx] - uy[j]
        if not forming.any():
            return
        i = np.flatnonzero(forming)
        j = self.j[i] % m
        tau = np.maximum(p.duration - self.ts[i], 1e-3)
        s = np.clip((t - self.ts[i]) / tau, 0.0, 1.0)
        h00 = 2 * s ** 3 - 3 * s ** 2 + 1
        h10 = s ** 3 - 2 * s ** 2 + s
        dh00 = (6 * s ** 2 - 6 * s) / tau
        dh10 = 3 * s ** 2 - 4 * s + 1
        p.x[i] = qx[j] + h00 * self.d0x[i] + h10 * tau * self.e0x[i]
        p.y[i] = qy[j] + h00 * self.d0y[i] + h10 * tau * self.e0y[i]
        p.vx[i] = ux[j] + dh00 * self.d0x[i] + dh10 * self.e0x[i]
        p.vy[i] = uy[j] + dh00 * self.d0y[i] + dh10 * self.e0y[i]
        p.form_fade[i] = 1.0 - s ** 3
        self.last_s[i] = s

    def gain(self, t) -> float:
        d = self.p.duration
        s = float(np.clip((t - self.t_form) / max(d - self.t_form, 1e-3), 0, 1))
        return s * s


# ── THE HOST FRAME: the shoaling family's FORM ─────────────────────────────

ORPHAN_FADE_S = 0.45       # a piece whose host retired fades over this
HOST_PIECE_FADE = 0.35     # ... and it starts from this much of its brightness


class HostFormer(_Former):
    """THE HOST FRAME (the shoal-burst plan, /home/javi/fleet-spotfx/data/
    shoal-burst-plan/report.md §5; the Admiral: "The burst particles
    continue generally moving as if the original object were still moving,
    like nothing happened, except it burst into particles ... Then, the new
    effect object matches initial conditions, and starts doing it's own
    motion, so it smoothly flows, and the particles recombine into the new
    object").

    A piece is not a free particle that has to be DRIVEN to a destination
    (the TargetFormer's Hermite to a stranger, whose peak speed scales with
    however far apart the two forms happened to be — the "zoom"). It is an
    OFFSET FROM A HOST, and the host does the travelling::

        piece_i(t) = host_j(i)(t) + ( shape_i + u_i.R.E_burst(t) ) . E_land(t)

    `host_j(t)` is the incoming object this piece's own parent BECAME, read
    live off the incoming effect every frame (`_program_hosts`), born on the
    parent's position, velocity and turn rate — so for its first stretch the
    host's trajectory IS the parent's continuation (the velocity graft on
    Orbits, the peel on Fish) and the cloud riding it continues the parent's
    motion BY CONSTRUCTION; then the same cloud is carried by the new
    object's own motion, with no second mechanism and no moment where the
    two disagree. `shape_i` is where the piece sat inside its parent,
    measured against WHERE ITS HOST ACTUALLY IS rather than where the parent
    was (`CloudProgram._host_frame`), so `host(0) + shape` is exactly the
    piece's own position on the first frame for every incoming form — each
    program keeps its own release shape, so each transition keeps its
    character. `u_i.R` is the burst, opening from rest over
    `transition_burst_ms` and gathered back to nothing from
    `transition_land_at`.

    A piece's motion RELATIVE to the thing it is joining is the derivative
    of that bracket — bounded by R and the envelopes, independent of how far
    apart anything is. There is no term that grows with distance, which is
    the whole fix.

    ASSIGNMENT IS INHERITED, NEVER SEARCHED (`object_of` -> pid), which is
    also what stops two pieces of one fish being sent to opposite sides of
    the panel. A piece whose host has since retired (a fish disperses, a
    blob is shed) continues on the constant-turn model its parent published
    (transition_program.turn_integrate) and fades — never a flight to a
    stranger."""

    def __init__(self, prog, inc, t_land):
        super().__init__(prog, inc, t_land)
        n = prog.n
        self.t_land = float(t_land)
        self.R = float(prog.settings.burst_px)
        self.burst_s = max(float(prog.settings.burst_open_s()), 1e-3)
        self.lost = np.full(n, np.nan, np.float32)
        self.hosts_seen = False

    def _hosts(self, inc):
        p = self.p
        try:
            qx, qy = inc._program_hosts(p.host_pids)
        except Exception:
            return None
        qx = np.asarray(qx, dtype=np.float32)
        qy = np.asarray(qy, dtype=np.float32)
        if qx.size != p.host_pids.size:
            return None
        return qx[p.obj_of], qy[p.obj_of]

    def advance(self, inc, t, dt):
        p = self.p
        hosts = self._hosts(inc)
        if hosts is None:
            p._fly(inc, t, dt)
            return
        hx, hy = hosts
        have = np.isfinite(hx) & np.isfinite(hy)
        if have.any():
            self.hosts_seen = True
        eb = _smoothstep((t - p.t_burst0) / self.burst_s).astype(np.float32)
        span = max(p.duration - self.t_land, 1e-3)
        el = np.float32(1.0 - float(_smoothstep((t - self.t_land) / span)))
        ox = (p.shape_ox + p.burst_ux * self.R * eb) * el
        oy = (p.shape_oy + p.burst_uy * self.R * eb) * el
        nx = hx + ox
        ny = hy + oy
        # ORPHANS: the continuation the release itself published — constant
        # speed on a constant turn rate — then a fade. Never a flight to a
        # stranger, and never a dead-straight drift out of a turn.
        gone = ~have
        if gone.any():
            fresh = gone & ~np.isfinite(self.lost)
            if fresh.any():
                self.lost = np.where(fresh, np.float32(t), self.lost)
            ovx, ovy = tp.turn_integrate(p.vx, p.vy, p.piece_om, dt)
            nx = np.where(gone, p.x + ovx * dt, nx)
            ny = np.where(gone, p.y + ovy * dt, ny)
            p.vx = np.where(gone, ovx, p.vx).astype(np.float32)
            p.vy = np.where(gone, ovy, p.vy).astype(np.float32)
        if dt > 0:
            vx = (nx - p.x) / dt
            vy = (ny - p.y) / dt
            p.vx = np.where(have, vx, p.vx).astype(np.float32)
            p.vy = np.where(have, vy, p.vy).astype(np.float32)
        p.x = nx.astype(np.float32)
        p.y = ny.astype(np.float32)
        # a hosted piece dissolves into its host as the gather closes; an
        # orphan fades on its own clock from where it was dropped
        fade = np.where(have, HOST_PIECE_FADE + (1.0 - HOST_PIECE_FADE) * el,
                        np.clip(1.0 - (t - np.nan_to_num(self.lost, nan=t))
                                / ORPHAN_FADE_S, 0.0, 1.0))
        p.form_fade = np.clip(fade, 0.0, 1.0).astype(np.float32)

    def gain(self, t) -> float:
        """The new object IS the continuation, so it comes up as the burst
        opens and is fully there when the gather begins."""
        return float(_smoothstep(t / max(self.t_land, 1e-3)))

    def hand_off(self, inc):
        # Nothing to adopt: every piece has arrived ON its host and faded
        # into it, and the host is the real effect's own object.
        return None


# ── the cloud program ──────────────────────────────────────────────────────

class CloudProgram(TransitionProgram):
    """A cloud of pieces (x, y, vx, vy in px and px/s; grad; bright; the
    outgoing colour sliding to the incoming one), RELEASED by the subclass,
    flown by `_fly`, FORMED by the former the incoming effect picks."""

    FORM_AT = 0.55         # TargetFormer / SparkFormer / FadeFormer start
    STAGGER = 0.0
    DRAG = FLIGHT_DRAG
    SPLIT_MIN = 0          # split a cloud smaller than this

    @classmethod
    def stage_fracs(cls, settings, out_type=None, in_type=None):
        a = tp.anchor_frac(cls.name, settings, out_type, in_type)
        f = cls._form_frac(settings, in_type)
        out = []
        if a > 0.0:
            out.append({"label": cls.STAGE_WORDS[0], "from": 0.0, "to": a})
            out.append({"label": cls.STAGE_WORDS[1], "from": a,
                        "to": max(f, a), "anchor": True})
        else:
            out.append({"label": cls.STAGE_WORDS[1], "from": 0.0, "to": f,
                        "anchor": True})
        out.append({"label": cls.STAGE_WORDS[2], "from": max(f, a), "to": 1.0})
        return [s for s in out if s["to"] > s["from"]]

    STAGE_WORDS = ("release", "flight", "form")

    @classmethod
    def _form_frac(cls, settings, in_type):
        if in_type == "blackhole":
            return 1.0 - settings.infall_form_s() / settings.duration_s
        return cls.FORM_AT

    # ── the host frame (HostFormer's docstring is the binding statement)
    # A release that sets these up gets the HostFormer; one that does not
    # keeps today's former exactly.
    obj_of = None          # piece -> released-object index
    shape_ox = None        # where the piece sat inside its parent (px)
    shape_oy = None
    burst_ux = None        # its own unit burst direction
    burst_uy = None
    t_burst0 = None        # when its puff starts (the unspool staggers it)
    piece_om = None        # its parent's turn rate (orphan continuation)
    host_pids = None       # object -> the pid its host was born with

    def _host_frame(self, objs, obj_of, inc=None, *, extra=None,
                    t_burst0=None, om=None) -> bool:
        """Hand the cloud to the HostFormer: `obj_of` names each piece's own
        parent, and the SHAPE — where that piece sat inside it — is measured
        against WHERE ITS HOST ACTUALLY IS, read once here, not against the
        released object's own position. The two differ whenever the incoming
        form places its new object on a grid of its own (a chain head snaps
        to the device lattice), and measuring against the host is what makes
        `host(0) + shape` exactly the piece's own position on frame one for
        every form, rather than up to a pixel off for some. `extra` is a
        release's own spread, added on top as a distance.

        The pids come from the matched birth the incoming effect has already
        consumed on its first draw; an object the count clamped out (-1) has
        its pieces MERGED INTO THE NEAREST BORN HOST — two fish visibly
        becoming one orbit — rather than a count nobody asked for."""
        pids = self._birth_pids(self.incoming)
        if pids is None or objs is None or pids.size != objs["px"].size:
            return False
        born = np.flatnonzero(pids >= 0)
        if born.size == 0:
            return False
        orphan = np.flatnonzero(pids < 0)
        if orphan.size:
            d = ((objs["px"][orphan][:, None] - objs["px"][born][None, :]) ** 2
                 + (objs["py"][orphan][:, None] - objs["py"][born][None, :]) ** 2)
            pids = pids.copy()
            pids[orphan] = pids[born][np.argmin(d, axis=1)]
        obj_of = np.asarray(obj_of, dtype=np.int64)
        n = int(self.x.size)
        # a mapping that does not line up is a BUG, not something to clamp
        # into silence: fall back to today's former rather than send a piece
        # to a host its parent never became
        if obj_of.size != n or n == 0:
            return False
        if obj_of.min() < 0 or obj_of.max() >= pids.size:
            return False
        self.host_pids = pids
        self.obj_of = obj_of
        rx = np.asarray(objs["px"], np.float32).copy()
        ry = np.asarray(objs["py"], np.float32).copy()
        inc = inc if inc is not None else self.incoming
        try:
            qx, qy = inc._program_hosts(pids)
            qx = np.asarray(qx, np.float32)
            qy = np.asarray(qy, np.float32)
            if qx.size == rx.size:
                ok = np.isfinite(qx) & np.isfinite(qy)
                rx = np.where(ok, qx, rx)
                ry = np.where(ok, qy, ry)
        except Exception:
            pass
        ox = self.x - rx[obj_of]
        oy = self.y - ry[obj_of]
        if extra is not None:
            ox = ox + np.asarray(extra[0], np.float32)
            oy = oy + np.asarray(extra[1], np.float32)
        self.shape_ox = np.asarray(ox, np.float32).copy()
        self.shape_oy = np.asarray(oy, np.float32).copy()
        ang = self.rng.uniform(0.0, 2.0 * np.pi, n).astype(np.float32)
        rad = np.sqrt(self.rng.uniform(0.0, 1.0, n)).astype(np.float32)
        self.burst_ux = (np.cos(ang) * rad).astype(np.float32)
        self.burst_uy = (np.sin(ang) * rad).astype(np.float32)
        self.t_burst0 = (np.zeros(n, np.float32) if t_burst0 is None
                         else np.asarray(t_burst0, np.float32).copy())
        self.piece_om = (objs["om"][self.obj_of].astype(np.float32)
                         if om is None else
                         np.asarray(om, np.float32).copy())
        return True

    # ── setup ─────────────────────────────────────────────────────────
    def _setup(self, inc) -> None:
        self.c_from_t = 0.0
        self.c_to_t = None
        self._release(inc)
        self.n = int(self.x.size)
        self.form_fade = np.ones(self.n, np.float32)
        rgb_in = _sample_rgb(inc, self.grad)
        self.rgb_to = rgb_in if rgb_in is not None else self.rgb_from.copy()
        self.former = self._make_former(inc)
        if self.c_to_t is None:
            self.c_to_t = max(self.former.t_form, 0.2)

    def _set_pieces(self, x, y, vx, vy, grad, bright, rgb):
        self.x = np.asarray(x, np.float32).copy()
        self.y = np.asarray(y, np.float32).copy()
        self.vx = np.asarray(vx, np.float32).copy()
        self.vy = np.asarray(vy, np.float32).copy()
        self.grad = np.asarray(grad, np.float32).copy()
        self.bright = np.clip(np.asarray(bright, np.float32), 0.0, 1.0).copy()
        self.rgb_from = np.asarray(rgb, np.float32).copy()

    def _release_snapshot(self, cap=PIECE_CAP, min_bright=0.35):
        """The outgoing snapshot's pieces as they are: positions,
        velocities, colours — capped to the brightest, a small cloud split
        (SPLIT_MIN). `_rel_obj` records which released OBJECT each piece
        came from (the host frame's `object_of`)."""
        px, py, vx, vy, grad, bright, rgb = self._snap_arrays()
        keep = _cap_by_brightness(bright, cap)
        a = {"x": px[keep], "y": py[keep], "vx": vx[keep], "vy": vy[keep],
             "grad": grad[keep], "bright": np.clip(bright[keep], min_bright, 1.0),
             "rgb": rgb[keep], "obj": keep.astype(np.int64)}
        if self.SPLIT_MIN:
            a = _split(self.rng, a, self.SPLIT_MIN)
        self._rel_obj = np.asarray(a["obj"], dtype=np.int64)
        self._set_pieces(a["x"], a["y"], a["vx"], a["vy"], a["grad"],
                         a["bright"], a["rgb"])

    def _make_former(self, inc):
        d = self.duration
        if self.in_type == tp.STAR and hasattr(inc, "_program_bands"):
            return RingFormer(self, inc, tp.STAR_FORM_AT * d)
        if self.in_type == "blackhole" and hasattr(inc, "_program_field_velocity"):
            return FieldFormer(self, inc)
        if self.in_type == "fireworks":
            return SparkFormer(self, inc, self.FORM_AT * d)
        # THE HOST FRAME: only when this release built one AND the incoming
        # form was born matched — every other pair keeps today's former.
        if self.obj_of is not None and hasattr(inc, "_program_hosts"):
            return HostFormer(self, inc, self.settings.land_s())
        if hasattr(inc, "_formation_points"):
            return TargetFormer(self, inc, self.FORM_AT * d, self.STAGGER)
        return FadeFormer(self, inc, self.FORM_AT * d)

    # ── per frame ─────────────────────────────────────────────────────
    def drawn_bright(self) -> np.ndarray:
        """Each piece's brightness as drawn this frame (0..1)."""
        return self.bright * self.form_fade * self._piece_gain()

    _t = 0.0

    def _piece_gain(self):
        return 1.0

    def _fly(self, inc, t, dt) -> None:
        """FLIGHT: on the motion it had, slowing (subclasses bend it)."""
        k = np.float32(math.exp(-self.DRAG * dt))
        self.x = (self.x + self.vx * dt).astype(np.float32)
        self.y = (self.y + self.vy * dt).astype(np.float32)
        self.vx = self.vx * k
        self.vy = self.vy * k

    def _draw_extras(self, inc, t, dt, layer) -> None:
        """Anything the release draws beside the pieces (the eye
        dissolving, the collapsing half)."""
        return None

    def _colour(self, t):
        c = float(_smoothstep((t - self.c_from_t)
                              / max(self.c_to_t - self.c_from_t, 1e-3)))
        return self.rgb_from + (self.rgb_to - self.rgb_from) * c

    def _step(self, inc, t, dt, layer):
        self._t = t
        self._draw_extras(inc, t, dt, layer)
        px, py = self.x.copy(), self.y.copy()
        self.former.advance(inc, t, dt)
        b = self.drawn_bright()
        on = b > 0.005
        if on.any():
            rgb = self.former.colour(t, self._colour(t)) * b[:, None]
            splat_path(layer, px[on], py[on], self.x[on], self.y[on], rgb[on])
        return self.former.gain(t)

    def _hand_off(self, inc) -> None:
        if self._ready:
            self.former.hand_off(inc)

    @classmethod
    def star_in_stage_fracs(cls, settings, out_type=None, in_type=None):
        """INTO STAR (module docstring): the partner's own release, then
        Star's FORM ("grow in") from STAR_FORM_AT."""
        a = tp.anchor_frac(cls.name, settings, out_type, in_type)
        f = tp.STAR_FORM_AT
        rel = {"label": STAR_IN_WORDS.get(cls.name, "release"),
               "from": 0.0, "to": f}
        form = {"label": "grow in", "from": f, "to": 1.0}
        if a >= f - 1e-6:
            form["anchor"] = True
        else:
            rel["anchor"] = True
        return [rel, form]


def _unit(dx, dy, rng):
    d = np.hypot(dx, dy)
    rnd = rng.uniform(0.0, 2 * np.pi, dx.size)
    ux = np.where(d > 1e-4, dx / np.maximum(d, 1e-6), np.cos(rnd))
    uy = np.where(d > 1e-4, dy / np.maximum(d, 1e-6), np.sin(rnd))
    return ux.astype(np.float32), uy.astype(np.float32), d


# ── LENSING: Fireworks -> Black Hole ───────────────────────────────────────

class LensingProgram(CloudProgram):
    name = tp.LENSING
    STAGE_WORDS = ("lens", "ignite", "ignite")

    @classmethod
    def stage_fracs(cls, settings, out_type=None, in_type=None):
        a = tp.anchor_frac(cls.name, settings, out_type, in_type)
        return [{"label": "lens", "from": 0.0, "to": a},
                {"label": "ignite", "from": a, "to": 1.0, "anchor": True}]

    def _release(self, bh):
        self._release_snapshot()
        sw = float(getattr(bh, "swirl", 1.0) or 1.0)
        self.spin = 1.0 if sw >= 0 else -1.0

    def _fly(self, bh, t, dt):
        f = self.former
        ramp = float(_smoothstep(t / max(0.5 * f.t_form, 1e-3)))
        pull = self.settings.lensing_pull
        gx = (self.x - f.cx) / f.sx
        gy = (self.y - f.cy) / f.sy
        ux, uy, r = _unit(gx, gy, self.rng)
        ax = -LENS_G0 * pull * ramp * ux - self.spin * LENS_T0 * pull * ramp * uy
        ay = -LENS_G0 * pull * ramp * uy + self.spin * LENS_T0 * pull * ramp * ux
        nvx = self.vx / f.sx + ax * dt
        nvy = self.vy / f.sy + ay * dt
        k = math.exp(-LENS_DRAG * ramp * dt)
        self.vx = (nvx * k * f.sx).astype(np.float32)
        self.vy = (nvy * k * f.sy).astype(np.float32)
        self.x = (self.x + self.vx * dt).astype(np.float32)
        self.y = (self.y + self.vy * dt).astype(np.float32)


# ── FOUNTAIN: Black Hole -> Fireworks ──────────────────────────────────────

class FountainProgram(CloudProgram):
    name = tp.FOUNTAIN

    @classmethod
    def stage_fracs(cls, settings, out_type=None, in_type=None):
        a = tp.anchor_frac(cls.name, settings, out_type, in_type)
        out = [{"label": "gather", "from": 0.0, "to": a},
               {"label": "spray", "from": a, "to": 1.0, "anchor": True}]
        return [s for s in out if s["to"] > s["from"]]

    def _release(self, fw):
        self._release_snapshot(cap=120)
        c = self.snap.get("center_px") or (fw.r_width / 2.0, fw.r_height / 2.0)
        self.ccx, self.ccy = float(c[0]), float(c[1])
        self.t_spray = self.anchor * self.duration
        self.sprayed = False
        # the unwind gathers the ring toward the centre on its own spin,
        # then sprays out of it (a fountain, never a ring flung off-panel)
        self.p0x, self.p0y = self.x.copy(), self.y.copy()
        self.v0x, self.v0y = self.vx.copy(), self.vy.copy()
        dx, dy = self.x - self.ccx, self.y - self.ccy
        self.rho0 = np.hypot(dx, dy).astype(np.float32)
        self.phi0 = np.arctan2(dy, dx).astype(np.float32)
        rho = np.maximum(self.rho0, 1e-3)
        self.om0 = ((dx * self.vy - dy * self.vx) / (rho * rho)).astype(np.float32)

    def _make_former(self, fw):
        if self.in_type == tp.STAR and hasattr(fw, "_program_bands"):
            # into Star the sprayed sparks land on the bands (RingFormer)
            return RingFormer(self, fw, tp.STAR_FORM_AT * self.duration)
        return SparkFormer(self, fw, self.t_spray)

    def _spray(self, fw):
        n = self.x.size
        per = int(np.clip(160 // max(n, 1), 3, 12))
        m = n * per
        rng = self.rng
        x = np.repeat(self.x, per) + rng.normal(0.0, 0.6, m).astype(np.float32)
        y = np.repeat(self.y, per) + rng.normal(0.0, 0.6, m).astype(np.float32)
        # out of the centre, across the whole set by angle
        ang = rng.uniform(0.0, 2 * np.pi, m).astype(np.float32)
        spd = (FOUNTAIN_SPRAY_PX * self.settings.eruption_speed
               * self.settings.lensing_pull ** 0.5
               * rng.uniform(0.45, 1.0, m)).astype(np.float32)
        aspect = fw.r_height / max(fw.r_width, 1)
        vx = np.repeat(self.vx, per) + np.cos(ang) * spd
        vy = np.repeat(self.vy, per) + np.sin(ang) * spd * aspect
        grad = ((ang / (2 * np.pi)) % 1.0).astype(np.float32)
        rgb_from = np.repeat(self._colour(self.t_spray), per, axis=0)
        self._set_pieces(x, y, vx, vy, grad, np.repeat(self.bright, per),
                         rgb_from)
        self.n = m
        self.form_fade = np.ones(m, np.float32)
        rgb_in = _sample_rgb(fw, grad)
        self.rgb_to = rgb_in if rgb_in is not None else rgb_from.copy()
        self.c_from_t = self.t_spray
        self.c_to_t = self.duration

    def _fly(self, fw, t, dt):
        if self.sprayed:
            # after the spray the sparks fly on, slowing (into Star the
            # RingFormer flies them until each glides onto its band; into
            # Fireworks the SparkFormer owns this stretch)
            return CloudProgram._fly(self, fw, t, dt)
        # the unwind (before the spray): the ring and its blobs gather
        # toward the centre turning faster on the spin they had, bent from
        # the motion they had over the first stretch
        s = t / max(self.t_spray, 1e-3)
        e = float(_smoothstep(s))
        rho = self.rho0 * (1.0 - FOUNTAIN_GATHER * e)
        phi = self.phi0 + self.om0 * t * (1.0 + 2.0 * e)
        tx = self.ccx + rho * np.cos(phi)
        ty = self.ccy + rho * np.sin(phi)
        b = float(_smoothstep(s / 0.4))
        bx = self.p0x + self.v0x * t
        by = self.p0y + self.v0y * t
        nx = bx + (tx - bx) * b
        ny = by + (ty - by) * b
        if dt > 0:
            self.vx = ((nx - self.x) / dt).astype(np.float32)
            self.vy = ((ny - self.y) / dt).astype(np.float32)
        self.x, self.y = nx.astype(np.float32), ny.astype(np.float32)

    def _step(self, fw, t, dt, layer):
        if not self.sprayed and t >= self.t_spray:
            self.sprayed = True
            self._spray(fw)
        return super()._step(fw, t, dt, layer)


# ── FLAME LICK: Sauron / Eye -> anything ───────────────────────────────────

class FlameLickProgram(CloudProgram):
    name = tp.FLAME_LICK
    DRAG = SHARD_DRAG
    FORM_AT = 0.55

    @classmethod
    def stage_fracs(cls, settings, out_type=None, in_type=None):
        f = cls._form_frac(settings, in_type)
        dis = min(DISSOLVE_S / settings.duration_s, f)
        return [{"label": "explode", "from": 0.0, "to": dis, "anchor": True},
                {"label": "shards", "from": dis, "to": f},
                {"label": "merge", "from": f, "to": 1.0}]

    def capture(self, virtual, outgoing) -> bool:
        if not super().capture(virtual, outgoing):
            return False
        snap = self.snap
        c = snap.get("center_px") or (self.dims[0] / 2.0, self.dims[1] / 2.0)
        self.ex0, self.ey0 = float(c[0]), float(c[1])
        self.rim0 = float(np.hypot(snap["px"][0] - self.ex0,
                                   snap["py"][0] - self.ey0))
        # the eye's own picture is drawn by the dissolve, never decayed
        # behind it by the base class
        self.eye_pic = self.release
        self.release = None
        self.outgoing = outgoing
        return True

    def _release(self, inc):
        rng = self.rng
        pic = self.eye_pic
        if pic is None:
            # no picture to explode (a flipped/rotated eye): its rim
            self._release_snapshot()
            self.c_x = np.zeros(0, np.float32)
            return
        lum = pic.max(axis=2)
        ys, xs = np.nonzero(lum > LIT_MIN)
        cols = pic[ys, xs]
        order = rng.permutation(xs.size)
        n_sh = int(round(self.settings.explode_frac * xs.size))
        n_sh = min(n_sh, SHARD_CAP)
        sh, co = order[:n_sh], order[n_sh:]
        x = xs[sh].astype(np.float32) + 0.5
        y = ys[sh].astype(np.float32) + 0.5
        grad, full = nearest_set_grad(self.out_palette, cols[sh].astype(np.float32))
        bright = np.clip(lum[ys[sh], xs[sh]] / 255.0, 0.35, 1.0)
        ux, uy, _ = _unit(x - self.ex0, y - self.ey0, rng)
        spd = rng.uniform(*SHARD_SPEED_PX, x.size).astype(np.float32) \
            * self.settings.eruption_speed
        swirl = SHARD_SWIRL * spd * rng.choice([-1.0, 1.0])
        vx = ux * spd - uy * swirl
        vy = uy * spd + ux * swirl
        self._set_pieces(x, y, vx, vy, grad, bright, full)
        # the other half collapses into the black
        self.c_x = xs[co].astype(np.float32) + 0.5
        self.c_y = ys[co].astype(np.float32) + 0.5
        self.c_rgb = cols[co].astype(np.float32)

    def _make_former(self, inc):
        if self.in_type == "blackhole" and hasattr(inc, "_program_field_velocity"):
            return FieldFormer(self, inc)
        return super()._make_former(inc)

    def _piece_gain(self):
        # the shards rise as the eye they are made of dissolves under them
        # (by max, so the eye never reads dimmer than its own fading picture)
        return float(_smoothstep(self._t / (SHARD_RISE * DISSOLVE_S)))

    def _fly(self, inc, t, dt):
        super()._fly(inc, t, dt)
        f = self.former
        if isinstance(f, FieldFormer):
            # into the Black Hole the slowing shards are drawn in (Lensing's
            # pull, growing after the explosion has spent itself)
            ramp = float(_smoothstep((t - 0.3 * f.t_form) / max(0.6 * f.t_form, 1e-3)))
            if ramp > 0.0:
                gx = (self.x - f.cx) / f.sx
                gy = (self.y - f.cy) / f.sy
                ux, uy, _ = _unit(gx, gy, self.rng)
                g = LENS_G0 * self.settings.lensing_pull * ramp
                self.vx = (self.vx + (-g * ux - LENS_T0 * ramp * uy) * f.sx * dt
                           ).astype(np.float32)
                self.vy = (self.vy + (-g * uy + LENS_T0 * ramp * ux) * f.sy * dt
                           ).astype(np.float32)

    def _draw_extras(self, inc, t, dt, layer):
        if self.eye_pic is not None and t < DISSOLVE_S:
            g = 1.0 - float(_smoothstep(t / DISSOLVE_S))
            np.maximum(layer, self.eye_pic * np.float32(g), out=layer)
        if self.c_x.size and t < COLLAPSE_S:
            e = float(_smoothstep(t / COLLAPSE_S))
            x = self.ex0 + (self.c_x - self.ex0) * (1.0 - e)
            y = self.ey0 + (self.c_y - self.ey0) * (1.0 - e)
            splat_max(layer, x, y, self.c_rgb * np.float32(1.0 - t / COLLAPSE_S),
                      0.8)


# ── IGNITION: anything -> Sauron / Eye ─────────────────────────────────────

class IgnitionProgram(CloudProgram):
    name = tp.IGNITION
    SPLIT_MIN = MIN_PIECES

    @classmethod
    def stage_fracs(cls, settings, out_type=None, in_type=None):
        a = tp.anchor_frac(cls.name, settings, out_type, in_type)
        return [{"label": "vortex", "from": 0.0, "to": a},
                {"label": "ignite", "from": a, "to": 1.0, "anchor": True}]

    def _rim(self, eye):
        rim = getattr(eye, "program_rim", None)
        if rim is None:
            return (eye.r_width / 2.0, eye.r_height / 2.0,
                    0.2 * min(eye.r_width, eye.r_height))
        return float(rim[0]), float(rim[1]), max(float(rim[2]), 1.0)

    def _release(self, eye):
        self._release_snapshot(cap=160)
        ex, ey, rr = self._rim(eye)
        self.p0x, self.p0y = self.x.copy(), self.y.copy()
        self.v0x, self.v0y = self.vx.copy(), self.vy.copy()
        dx, dy = self.x - ex, self.y - ey
        self.r0 = np.hypot(dx, dy).astype(np.float32)
        self.th0 = np.arctan2(dy, dx).astype(np.float32)
        # the cloud keeps its own sense of rotation about the eye
        ang = float(np.sum(dx * self.vy - dy * self.vx))
        self.spin = 1.0 if ang >= 0.0 else -1.0
        d = self.duration
        n = self.x.size
        self.T = (d * self.rng.uniform(*IGNITION_LAND, n)).astype(np.float32)
        self.landed = np.zeros(n, bool)
        self._sparkle = np.ones(n, np.float32)
        self.handed_gain = 0.0
        # the colours reach the eye's own as the sparks land
        self.c_to_t = float(np.mean(self.T)) if n else 0.5 * d

    def _make_former(self, eye):
        return _Former(self, eye, IGNITION_FILL_AT * self.duration)

    def fill(self, t) -> float:
        d = self.duration
        a = IGNITION_FILL_AT * d
        return float(_smoothstep((t - a) / max(d - a, 1e-3)))

    def _piece_gain(self):
        return self._sparkle

    def _step(self, eye, t, dt, layer):
        ex, ey, rr = self._rim(eye)
        turns = self.settings.ignition_turns
        s = np.clip(t / np.maximum(self.T, 1e-3), 0.0, 1.0)
        e = s * s
        r = self.r0 + (rr - self.r0) * e
        end_rate = self.spin * 4.0 * np.pi * turns / np.maximum(self.T, 1e-3)
        th = self.th0 + self.spin * 2.0 * np.pi * turns * e \
            + end_rate * np.maximum(t - self.T, 0.0)
        tx = ex + r * np.cos(th)
        ty = ey + r * np.sin(th)
        b = _smoothstep(t / np.maximum(self.T * 0.35, 1e-3))
        bx = self.p0x + self.v0x * t
        by = self.p0y + self.v0y * t
        px, py = self.x.copy(), self.y.copy()
        nx = bx + (tx - bx) * b
        ny = by + (ty - by) * b
        if dt > 0:
            self.vx = ((nx - self.x) / dt).astype(np.float32)
            self.vy = ((ny - self.y) / dt).astype(np.float32)
        self.x, self.y = nx.astype(np.float32), ny.astype(np.float32)
        # a landed spark flares locally and fades; it never lights the rim
        over = np.maximum(t - self.T, 0.0)
        self._sparkle = np.where(
            over > 0.0, np.clip(1.0 - over / LAND_FADE_S, 0.0, 1.0), 1.0
        ).astype(np.float32)
        self.landed |= over > 0.0
        b_ = self.drawn_bright()
        on = b_ > 0.005
        if on.any():
            rgb = self._colour(t) * b_[:, None]
            size = np.where(over[on] > 0.0, 1.3, 0.9)
            for big in (False, True):
                sel = (size > 1.0) == big
                if sel.any():
                    splat_path(layer, px[on][sel], py[on][sel], self.x[on][sel],
                               self.y[on][sel], rgb[on][sel], 1.3 if big else 0.9)
        # the slit / pupil opens from a hairline over the second half
        lens = float(_smoothstep((t - 0.5 * self.duration) / (0.5 * self.duration)))
        if hasattr(eye, "_lens_gain"):
            eye._lens_gain = LENS_MIN + (1.0 - LENS_MIN) * lens
        # ONE fill reveals the eye from the rim: inward (the iris) and
        # outward (the flames); its gain is the fill's own curve, so the
        # rim can never be brighter than the eye it belongs to
        f = self.fill(t)
        g = IGNITION_HANDOFF_GAIN * f
        self.handed_gain = g
        h, w = layer.shape[:2]
        if not hasattr(self, "_yy"):
            self._yy, self._xx = np.mgrid[0:h, 0:w].astype(np.float32)
            self.reach = float(np.hypot(w, h))
        dist = np.hypot(self._xx + 0.5 - ex, self._yy + 0.5 - ey) - rr
        soft = 2.0
        inner = _smoothstep((dist + f * rr + soft) / (2.0 * soft))
        outer = _smoothstep((f * self.reach - dist + soft) / (2.0 * soft))
        mask = np.where(dist < 0.0, inner, outer).astype(np.float32)
        return mask * np.float32(g)

    def finish(self) -> None:
        inc = self.incoming
        if inc is not None and hasattr(inc, "_lens_gain"):
            inc._lens_gain = 1.0
        super().finish()

    def _hand_off(self, eye):
        adopt = getattr(eye, "_adopt_handoff", None)
        if adopt is None:
            return
        adopt(snap={
            "src": "program",
            "t": particle_handoff.now(),
            "dims": self.dims,
            "px": np.zeros(0, np.float32),
            "py": np.zeros(0, np.float32),
            "grad": np.zeros(0, np.float32),
            "bright": np.zeros(0, np.float32),
            "gradient": None,
            "body_gain": float(getattr(self, "handed_gain", 0.0)),
            "gesture": "ignite",
        }, allow_hold=False)


# ── SHOAL BREAK: Fish -> Orbits / Squiggles ────────────────────────────────

DOTS_PER_FISH = 6
# In the host frame a release's sideways spread is a DISTANCE, not a
# velocity: the same `transition_scatter` number read as px/s then times
# this many seconds of it, so the shape a fish shatters into is the one it
# always had without a term that keeps pushing the dot away from its host.
HOST_LAT_S = 0.12


class ShoalBreakProgram(CloudProgram):
    name = tp.SHOAL_BREAK
    FORM_AT = 0.45
    STAGGER = 0.3
    DRAG = 1.0
    HOST_FRAME = True

    @classmethod
    def stage_fracs(cls, settings, out_type=None, in_type=None):
        f = cls.FORM_AT
        return [{"label": "break", "from": 0.0, "to": f, "anchor": True},
                {"label": "implode", "from": f, "to": 1.0}]

    def capture(self, virtual, outgoing) -> bool:
        if not super().capture(virtual, outgoing):
            return False
        try:
            body = float(outgoing._body_len_px())
        except Exception:
            body = 6.0
        self.body_px = max(body, 3.0)
        return True

    def _release(self, inc):
        px, py, vx, vy, grad, bright, rgb = self._snap_arrays()
        keep = _cap_by_brightness(bright, PIECE_CAP // DOTS_PER_FISH)
        px, py, vx, vy = px[keep], py[keep], vx[keep], vy[keep]
        grad, bright, rgb = grad[keep], bright[keep], rgb[keep]
        n = px.size
        rng = self.rng
        ux, uy, spd = _unit(vx, vy, rng)
        k = np.linspace(0.0, 1.0, DOTS_PER_FISH, dtype=np.float32)
        # each body's dots, head first, back along its heading
        x = (px[:, None] - ux[:, None] * k[None, :] * self.body_px).ravel()
        y = (py[:, None] - uy[:, None] * k[None, :] * self.body_px).ravel()
        lat = rng.uniform(-1.0, 1.0, (n, DOTS_PER_FISH)).astype(np.float32) \
            * SCATTER_PX * self.settings.scatter
        fwd = rng.uniform(-0.25, 0.25, (n, DOTS_PER_FISH)).astype(np.float32)
        dvx = (vx[:, None] * (1.0 + fwd) - uy[:, None] * lat).ravel()
        dvy = (vy[:, None] * (1.0 + fwd) + ux[:, None] * lat).ravel()
        self._set_pieces(x, y, dvx, dvy, np.repeat(grad, DOTS_PER_FISH),
                         np.repeat(np.clip(bright, 0.35, 1.0), DOTS_PER_FISH),
                         np.repeat(rgb, DOTS_PER_FISH, axis=0))
        # THE HOST FRAME: the shape IS the body — each dot's own place in
        # the fish it came from, laid back along its heading, with the
        # lateral spread a STATIC offset rather than a sideways velocity (a
        # scatter in the velocity is what sent a dot off at up to 80 degrees
        # to the fish it came out of). Every dot of one fish rides the one
        # object that fish became.
        obj = np.repeat(keep, DOTS_PER_FISH)
        lat_x = (-uy[:, None] * lat * HOST_LAT_S).ravel().astype(np.float32)
        lat_y = (ux[:, None] * lat * HOST_LAT_S).ravel().astype(np.float32)
        self._host_frame(self.objs, obj, inc, extra=(lat_x, lat_y))


# ── SHOALING: Orbits -> Fish ───────────────────────────────────────────────

class ShoalingProgram(TransitionProgram):
    """The REAL Fish adopts the orbit blobs on its first frame (the snapshot
    is left in the registry: TAKE_REGISTRY False) — at their positions,
    headings, speeds and turning rates (fish.PEEL_S). The program draws the
    outgoing picture fading under the arriving fish and lets the blobs the
    Fish does not take fly on along their curves and fade."""

    name = tp.SHOALING
    TAKE_REGISTRY = False
    RELEASE_HALF_LIFE_S = 0.2

    @classmethod
    def stage_fracs(cls, settings, out_type=None, in_type=None):
        a = tp.anchor_frac(cls.name, settings, out_type, in_type)
        return [{"label": "peel", "from": 0.0, "to": a},
                {"label": "shoal", "from": a, "to": 1.0, "anchor": True}]

    def _setup(self, fish) -> None:
        px, py, vx, vy, grad, bright, rgb = self._snap_arrays()
        snap = self.snap
        full_bright = np.asarray(snap["bright"], np.float32)
        order = np.argsort(full_bright)[::-1]
        want = min(int(getattr(fish, "particle_count", 0)), order.size)
        taken = set(order[:want].tolist())
        om = snap.get("om")
        om = (np.asarray(om, np.float32) if om is not None
              and len(om) == len(full_bright) else np.zeros(len(full_bright),
                                                            np.float32))
        # _snap_arrays dropped near-dark pieces; map back by position
        keep = (np.isfinite(np.asarray(snap["px"], np.float32))
                & np.isfinite(np.asarray(snap["py"], np.float32))
                & (np.clip(full_bright, 0.0, 1.0) > 0.03))
        idx = np.flatnonzero(keep)
        surplus = np.array([i not in taken for i in idx], dtype=bool)
        self.sx_, self.sy_ = px[surplus], py[surplus]
        self.svx, self.svy = vx[surplus], vy[surplus]
        self.som = om[idx][surplus]
        self.srgb = rgb[surplus] * np.clip(bright[surplus], 0.3, 1.0)[:, None]

    def _step(self, fish, t, dt, layer) -> float:
        if self.sx_.size and t < SURPLUS_FADE_S:
            # the untaken blobs fly on along their own curves, fading
            c, s = np.cos(self.som * dt), np.sin(self.som * dt)
            vx = self.svx * c - self.svy * s
            vy = self.svx * s + self.svy * c
            self.svx, self.svy = vx, vy
            x0, y0 = self.sx_.copy(), self.sy_.copy()
            self.sx_ = self.sx_ + vx * dt
            self.sy_ = self.sy_ + vy * dt
            f = np.float32(1.0 - t / SURPLUS_FADE_S)
            splat_path(layer, x0, y0, self.sx_, self.sy_, self.srgb * f)
        return 1.0

    def _hand_off(self, fish) -> None:
        return None


DOTS_PER_BLOB = 6          # pieces an orbit blob comes apart into
BLOB_DOT_R = 1.6           # ... spread this far round it before the burst


class ShoalBurstProgram(CloudProgram):
    """SHOALING WITH A BURST (the Admiral's D1 on the shoal-burst plan: it
    is the pair he named, and today it has no burst at all — the fish simply
    appear on the blobs). Each orbit blob comes apart into its own pixels,
    the Fish is BORN MATCHED on the blobs (one fish per blob, on its
    velocity and turning rate), and every piece rides the fish its own blob
    became — so the cloud bursts and rejoins without ever leaving it.

    `transition_burst_px = 0` selects the plain `ShoalingProgram` instead
    (transition_program.program_class), which is today's pair frame for
    frame."""

    name = tp.SHOALING
    HOST_FRAME = True
    DRAG = 1.0
    RELEASE_HALF_LIFE_S = 0.2
    STAGE_WORDS = ("burst", "burst", "gather")

    @classmethod
    def stage_fracs(cls, settings, out_type=None, in_type=None):
        return [{"label": "burst", "from": 0.0,
                 "to": settings.land_at, "anchor": True},
                {"label": "gather", "from": settings.land_at, "to": 1.0}]

    def _release(self, inc):
        px, py, vx, vy, grad, bright, rgb = self._snap_arrays()
        keep = _cap_by_brightness(bright, PIECE_CAP // DOTS_PER_BLOB)
        px, py, vx, vy = px[keep], py[keep], vx[keep], vy[keep]
        grad, bright, rgb = grad[keep], bright[keep], rgb[keep]
        n = px.size
        k = (np.arange(DOTS_PER_BLOB, dtype=np.float32) / DOTS_PER_BLOB
             * 2.0 * np.pi)
        jit = self.rng.uniform(0.0, 2.0 * np.pi, n).astype(np.float32)
        ox = (np.cos(k[None, :] + jit[:, None]) * BLOB_DOT_R).ravel()
        oy = (np.sin(k[None, :] + jit[:, None]) * BLOB_DOT_R).ravel()
        x = (np.repeat(px, DOTS_PER_BLOB) + ox).astype(np.float32)
        y = (np.repeat(py, DOTS_PER_BLOB) + oy).astype(np.float32)
        self._set_pieces(x, y,
                         np.repeat(vx, DOTS_PER_BLOB),
                         np.repeat(vy, DOTS_PER_BLOB),
                         np.repeat(grad, DOTS_PER_BLOB),
                         np.repeat(np.clip(bright, 0.35, 1.0), DOTS_PER_BLOB),
                         np.repeat(rgb, DOTS_PER_BLOB, axis=0))
        self._host_frame(self.objs, np.repeat(keep, DOTS_PER_BLOB), inc)


# ── UNRAVEL: Squiggles <-> Orbits / Fish ──────────────────────────────────

class UnravelProgram(CloudProgram):
    """Out of Squiggles (`unspool`): each chain's path cells become dots,
    released tail-first over UNSPOOL_S, each leaving along the chain's own
    path at the walking speed with a sideways scatter, then imploding onto
    the incoming form. Into Squiggles (`thread`): the cloud flies on, then
    threads onto the live chain heads one piece after another."""

    name = tp.UNRAVEL
    DRAG = 1.0
    HOST_FRAME = True

    @classmethod
    def stage_fracs(cls, settings, out_type=None, in_type=None):
        if in_type == "squiggles":
            a = tp.anchor_frac(cls.name, settings, out_type, in_type)
            if a <= 0.25:
                return [{"label": "thread", "from": 0.0, "to": 1.0,
                         "anchor": True}]
            return [{"label": "drift", "from": 0.0, "to": 0.25},
                    {"label": "thread", "from": 0.25, "to": a},
                    {"label": "threaded", "from": a, "to": 1.0, "anchor": True}]
        return [{"label": "unspool", "from": 0.0, "to": 0.5, "anchor": True},
                {"label": "implode", "from": 0.5, "to": 1.0}]

    @property
    def threading(self) -> bool:
        return self.in_type == "squiggles"

    def capture(self, virtual, outgoing) -> bool:
        if not super().capture(virtual, outgoing):
            return False
        self.paths = []
        if self.out_type == "squiggles":
            spd = float(getattr(outgoing, "base_speed", 0.0) or 0.0)
            for c in list(getattr(outgoing, "chains", []) or []):
                pts = np.asarray(list(c.get("path", [])), dtype=np.float32)
                if pts.ndim == 2 and pts.shape[0] >= 1:
                    self.paths.append((pts, float(c.get("grad", 0.0)),
                                       float(c.get("bright", 1.0))))
            self.walk_px = max(spd, 5.0)
        self.outgoing = outgoing
        return True

    def _release(self, inc):
        if self.threading or not self.paths:
            self.FORM_AT = 0.25 if self.threading else 0.5
            self.STAGGER = 0.5 if self.threading else 0.35
            self.SPLIT_MIN = MIN_PIECES
            self._release_snapshot()
            self.t_rel = np.zeros(self.x.size, np.float32)
            self.v_go = None
            # THE HOST FRAME: each split copy rides the object it came from
            # (its jitter is the shape), threading onto the chain head /
            # blob that object became instead of flying to the nearest one
            obj = getattr(self, "_rel_obj", None)
            o = self.objs
            if (obj is not None and o is not None and obj.size == self.x.size
                    and obj.size and 0 <= obj.min() and obj.max() < o["px"].size):
                self._host_frame(o, obj, inc)
            return
        self.FORM_AT = 0.5
        self.STAGGER = 0.35
        rng = self.rng
        xs, ys, tx, ty, gr, br, rel = [], [], [], [], [], [], []
        ch = []
        for ci, (pts, grad, bright) in enumerate(self.paths):
            m = pts.shape[0]
            nxt = np.vstack([pts[1:], pts[-1:]])
            prv = np.vstack([pts[:1], pts[:-1]])
            tan = nxt - prv
            xs.append(pts[:, 0])
            ys.append(pts[:, 1])
            tx.append(tan[:, 0])
            ty.append(tan[:, 1])
            gr.append(np.full(m, grad, np.float32))
            # the tail is dimmer, as the chain draws it
            br.append(np.clip(bright * (0.4 + 0.6 * np.arange(m) / max(m - 1, 1)),
                              0.0, 1.0))
            rel.append(UNSPOOL_S * np.arange(m, dtype=np.float32) / max(m - 1, 1))
            ch.append(np.full(m, ci, dtype=np.int64))
        x = np.concatenate(xs) + 0.5
        y = np.concatenate(ys) + 0.5
        keep = np.arange(x.size)
        if x.size > PIECE_CAP:
            keep = np.sort(rng.choice(x.size, PIECE_CAP, replace=False))
        tx_ = np.concatenate(tx)[keep]
        ty_ = np.concatenate(ty)[keep]
        ux, uy, _ = _unit(tx_, ty_, rng)
        spd = self.walk_px * rng.uniform(0.6, 1.0, keep.size).astype(np.float32)
        lat = rng.uniform(-1.0, 1.0, keep.size).astype(np.float32) \
            * SCATTER_PX * self.settings.scatter
        grad = np.concatenate(gr)[keep]
        rgb = tp.palette_rgb(self.out_palette, grad)
        if rgb is None:
            rgb = np.full((keep.size, 3), 200.0, np.float32)
        bright = np.concatenate(br)[keep]
        pic = self.release
        if pic is not None:
            # each dot starts as bright as the chain is drawn at its cell,
            # so the first frame is the chain, not a brighter copy of it
            h, w = pic.shape[:2]
            xi = np.clip(np.floor(x[keep]).astype(int), 0, w - 1)
            yi = np.clip(np.floor(y[keep]).astype(int), 0, h - 1)
            lum = pic[yi, xi].max(axis=1) / 255.0
            peak = np.maximum(rgb.max(axis=1) / 255.0, 1e-3)
            bright = np.clip(lum / peak, 0.12, 1.0).astype(np.float32)
        self._set_pieces(x[keep], y[keep], np.zeros(keep.size), np.zeros(keep.size),
                         grad, bright, rgb)
        self.v_go = ((ux * spd - uy * lat).astype(np.float32),
                     (uy * spd + ux * lat).astype(np.float32))
        self.t_rel = np.concatenate(rel)[keep].astype(np.float32)
        # THE HOST FRAME: a chain IS the object, so every dot of its body
        # rides the chain head / blob / fish that chain became, holding its
        # own place back along the body (`self.paths` is in raw chain order,
        # which `raw_to_object` maps onto the released objects). The
        # tail-first UNSPOOL survives as each dot's own burst start, so the
        # chain still comes apart from its tail rather than all at once.
        o = self.objs
        if o is not None and o["px"].size:
            raw = self.raw_to_object(o, max(len(self.paths), 1))
            ci_ = np.concatenate(ch)[keep]
            obj = raw[ci_] if (ci_.size and ci_.min() >= 0
                               and ci_.max() < raw.size) else np.full(1, -1)
            if obj.size == x[keep].size and (obj >= 0).all():
                self._host_frame(o, obj, inc, t_burst0=self.t_rel)

    def _piece_gain(self):
        # out of Squiggles the dots ease in over the chain picture they are
        # made of (by max) as it fades
        if getattr(self, "v_go", None) is not None:
            return float(_smoothstep(self._t / UNSPOOL_RISE_S))
        return 1.0

    def _fly(self, inc, t, dt):
        if self.v_go is not None:
            # a dot leaves the chain at its release time, easing up to its
            # speed (a chain cell was standing still)
            go = _smoothstep((t - self.t_rel) / 0.2).astype(np.float32)
            self.vx = self.v_go[0] * go
            self.vy = self.v_go[1] * go
            self.x = (self.x + self.vx * dt).astype(np.float32)
            self.y = (self.y + self.vy * dt).astype(np.float32)
            return
        super()._fly(inc, t, dt)


# ── OUT OF STAR: UNWIND (-> Orbits) and CLUSTER (-> Fish) ───────────────

CLUSTER_UNWIND = 8.0 / 14.0    # the cluster flight unwinds this much of UNWIND's
CLUSTER_GATHER = 0.5           # share of FORM over which pieces gather on seeds
CLUSTER_SEP_RAD = 0.8          # seeds at least this far apart in angle (rad)


def turn_about(prog, cx, cy, dt, drag=0.4, unwind=0.0, settle=0.25):
    """Rings keep turning: the tangential part of each piece's velocity
    about (cx, cy) is kept (decaying by `drag` 1/s, and turning with the
    piece), the radial part settles out over `settle` s plus an optional
    outward `unwind` px/s^2 — so a piece rides a circle about the centre on
    the speed it had, then spirals outward."""
    dx = prog.x - cx
    dy = prog.y - cy
    rho = np.maximum(np.hypot(dx, dy), 1e-3)
    ux, uy = dx / rho, dy / rho
    vr = prog.vx * ux + prog.vy * uy
    vt = -prog.vx * uy + prog.vy * ux
    vr = vr * np.float32(math.exp(-dt / max(settle, 1e-3))) + unwind * dt
    vt = vt * np.float32(math.exp(-drag * dt))
    om = vt / rho
    ang = np.arctan2(dy, dx) + om * dt
    rho2 = np.maximum(rho + vr * dt, 1.0)
    nx = cx + rho2 * np.cos(ang)
    ny = cy + rho2 * np.sin(ang)
    if dt > 0:
        prog.vx = ((nx - prog.x) / dt).astype(np.float32)
        prog.vy = ((ny - prog.y) / dt).astype(np.float32)
    prog.x = nx.astype(np.float32)
    prog.y = ny.astype(np.float32)


class _StarRelease(CloudProgram):
    """Shared by the two new flights out of Star: the release is Star's own
    snapshot (radial._program_snapshot — the set colours already named), and
    the flight turns about Star's centre."""

    RELEASE_HALF_LIFE_S = 0.22   # Star's picture fades a little slower than
    #                              a particle effect's, under its own pieces
    DRAG = 0.3
    UNWIND_SCALE = 1.0

    def _release(self, inc):
        self._release_snapshot(cap=int(self.settings.bands_pieces),
                               min_bright=0.3)
        c = self.snap.get("center_px") or (inc.r_width / 2.0, inc.r_height / 2.0)
        self.ccx, self.ccy = float(c[0]), float(c[1])

    def _fly(self, inc, t, dt):
        hold = self.settings.bands_hold_s
        unwind = 0.0 if t < hold else self.settings.unwind * self.UNWIND_SCALE
        turn_about(self, self.ccx, self.ccy, dt, drag=self.DRAG, unwind=unwind)


class UnwindProgram(_StarRelease):
    name = tp.UNWIND
    FORM_AT = 0.5
    STAGGER = 0.3

    @classmethod
    def stage_fracs(cls, settings, out_type=None, in_type=None):
        return [{"label": "unwind", "from": 0.0, "to": cls.FORM_AT,
                 "anchor": True},
                {"label": "condense", "from": cls.FORM_AT, "to": 1.0}]


class ClusterFormer(TargetFormer):
    """CLUSTER's FORM (module docstring): gather onto the Fish's count of
    seed pieces, then fly each cluster onto a live fish (the TargetFormer's
    Hermite, so every piece arrives ON its fish with its velocity)."""

    def __init__(self, prog, inc, t_form):
        super().__init__(prog, inc, t_form, 0.0)
        self.t_mid = t_form + CLUSTER_GATHER * max(prog.duration - t_form, 1e-3)
        self.seed = None      # per piece: the index of its seed piece
        self.d_gx = None      # its offset from the seed at FORM's start
        self.d_gy = None
        self.target = None    # per piece: its seed's fish
        self.launched = False

    def _choose(self, qx, qy):
        p = self.p
        n = p.n
        k = int(max(1, min(qx.size, n)))
        ang = np.arctan2(p.y - p.ccy, p.x - p.ccx)
        seeds = []
        sep = min(CLUSTER_SEP_RAD, 0.6 * 2.0 * np.pi / k)
        for i in np.argsort(p.drawn_bright())[::-1]:
            if all(abs((ang[i] - ang[j] + np.pi) % (2 * np.pi) - np.pi) > sep
                   for j in seeds):
                seeds.append(int(i))
            if len(seeds) >= k:
                break
        seeds = np.asarray(seeds, dtype=np.int64)
        d = np.abs((ang[:, None] - ang[seeds][None, :] + np.pi)
                   % (2 * np.pi) - np.pi)
        self.seed = seeds[np.argmin(d, axis=1)]
        self.d_gx = (p.x - p.x[self.seed]).astype(np.float32)
        self.d_gy = (p.y - p.y[self.seed]).astype(np.float32)
        # each seed its own fish: the nearest still free (greedy)
        free = list(range(qx.size))
        fish_of = {}
        for s_ in seeds:
            dd = [(p.x[s_] - qx[f]) ** 2 + (p.y[s_] - qy[f]) ** 2 for f in free]
            f = free.pop(int(np.argmin(dd))) if free else int(
                np.argmin((p.x[s_] - qx) ** 2 + (p.y[s_] - qy) ** 2))
            fish_of[int(s_)] = f
        self.target = np.asarray([fish_of[int(s_)] for s_ in self.seed],
                                 dtype=np.int64)

    def advance(self, inc, t, dt):
        p = self.p
        targets = self._targets(inc, dt)
        if t < self.t_form or targets is None:
            p._fly(inc, t, dt)
            if targets is None and t >= self.t_form:
                f = 1.0 - float(_smoothstep(
                    (t - self.t_form) / max(p.duration - self.t_form, 1e-3)))
                p.form_fade[:] = np.minimum(p.form_fade, f)
            return
        self.targets_seen = True
        qx, qy, ux, uy = targets
        if self.seed is None:
            self._choose(qx, qy)
        if t < self.t_mid:
            # GATHER: the seeds fly on; every other piece closes on its seed
            x0, y0 = p.x.copy(), p.y.copy()
            p._fly(inc, t, dt)
            e = float(_smoothstep((t - self.t_form)
                                  / max(self.t_mid - self.t_form, 1e-3)))
            p.x = (p.x[self.seed] + self.d_gx * (1.0 - e)).astype(np.float32)
            p.y = (p.y[self.seed] + self.d_gy * (1.0 - e)).astype(np.float32)
            if dt > 0:
                p.vx = ((p.x - x0) / dt).astype(np.float32)
                p.vy = ((p.y - y0) / dt).astype(np.float32)
            return
        m = qx.size
        if not self.launched:
            self.launched = True
            j = self.target % m
            self.j[:] = j
            self.ts[:] = t
            self.d0x[:] = p.x - qx[j]
            self.d0y[:] = p.y - qy[j]
            self.e0x[:] = p.vx - ux[j]
            self.e0y[:] = p.vy - uy[j]
        j = self.j % m
        tau = np.maximum(p.duration - self.ts, 1e-3)
        s = np.clip((t - self.ts) / tau, 0.0, 1.0)
        h00 = 2 * s ** 3 - 3 * s ** 2 + 1
        h10 = s ** 3 - 2 * s ** 2 + s
        dh00 = (6 * s ** 2 - 6 * s) / tau
        dh10 = 3 * s ** 2 - 4 * s + 1
        p.x = (qx[j] + h00 * self.d0x + h10 * tau * self.e0x).astype(np.float32)
        p.y = (qy[j] + h00 * self.d0y + h10 * tau * self.e0y).astype(np.float32)
        p.vx = (ux[j] + dh00 * self.d0x + dh10 * self.e0x).astype(np.float32)
        p.vy = (uy[j] + dh00 * self.d0y + dh10 * self.e0y).astype(np.float32)
        p.form_fade[:] = 1.0 - s ** 3
        self.last_s[:] = s

    def gain(self, t) -> float:
        d = self.p.duration
        return float(_smoothstep((t - self.t_mid) / max(d - self.t_mid, 1e-3)))


class ClusterProgram(_StarRelease):
    name = tp.CLUSTER
    FORM_AT = 0.45
    DRAG = 0.4
    UNWIND_SCALE = CLUSTER_UNWIND

    @classmethod
    def stage_fracs(cls, settings, out_type=None, in_type=None):
        mid = cls.FORM_AT + CLUSTER_GATHER * (1.0 - cls.FORM_AT)
        return [{"label": "break", "from": 0.0, "to": cls.FORM_AT,
                 "anchor": True},
                {"label": "gather", "from": cls.FORM_AT, "to": mid},
                {"label": "shoal", "from": mid, "to": 1.0}]

    def _release(self, inc):
        super()._release(inc)
        cap = min(int(self.settings.bands_pieces), 160)
        if self.x.size > cap:
            keep = _cap_by_brightness(self.bright, cap)
            self._set_pieces(self.x[keep], self.y[keep], self.vx[keep],
                             self.vy[keep], self.grad[keep], self.bright[keep],
                             self.rgb_from[keep])

    def _make_former(self, inc):
        if hasattr(inc, "_formation_points"):
            return ClusterFormer(self, inc, self.FORM_AT * self.duration)
        return FadeFormer(self, inc, self.FORM_AT * self.duration)


# ── INTO STAR: the RingFormer, SPARK RINGS and WIND (module docstring) ────

RING_LOCK_S = 0.45      # a piece's glide onto its band
RING_FADE_S = 0.25      # a landed piece melts into its band once passed
RING_LAND_END_S = 0.25  # every piece has landed this long before the end
RING_LEVEL = 0.35       # the star inside the front, until the tail
RING_FRONT_W = 0.22     # the front's feather, as a share of Star's cells
RING_TAIL_S = 0.45      # the level inside the front eases to full over the
#                         program's last this-long
RING_GLOW = 0.4         # a landed piece's glow on its band ...
RING_GLOW_R0 = 2.0      # ... this many cells across at landing ...
RING_GLOW_GROW = 4.0    # ... growing this many cells a second
RING_PASSED = 0.5       # the front term at a landed piece's cell that lets
#                         it melt into its band
RING_U_MIN = 0.04       # a band this close to the core is not landed on

STAR_IN_WORDS = {
    tp.FOUNTAIN: "gather",
    tp.SHOAL_BREAK: "break",
    tp.SPARK_RINGS: "fly",
    tp.FLAME_LICK: "explode",
    tp.UNRAVEL: "unspool",
    tp.WIND: "wind",
}


def _hermite(s, tau):
    s = np.clip(s, 0.0, 1.0)
    return (2 * s ** 3 - 3 * s ** 2 + 1, s ** 3 - 2 * s ** 2 + s,
            (6 * s ** 2 - 6 * s) / tau, 3 * s ** 2 - 4 * s + 1)


class RingFormer(_Former):
    """Star's FORM (module docstring, INTO STAR): the pieces glide onto
    Star's bands, staggered, while a soft front grows the star out of the
    core; landings glow on their band ahead of it, and a landed piece melts
    into its band once the front has passed it."""

    def __init__(self, prog, star, t_form):
        super().__init__(prog, star, t_form)
        d = prog.duration
        span = max(d - self.t_form, 1e-3)
        self.lock = float(min(RING_LOCK_S, max(0.15, 0.45 * span)))
        self.land_end = d - min(RING_LAND_END_S, 0.3 * span)
        self.last_start = max(self.t_form, self.land_end - self.lock)
        try:
            want = float(star._config.get("ring_reveal_front_s", 0.65))
        except Exception:                                  # noqa: BLE001
            want = 0.65
        room = max(self.land_end - self.t_form, 0.1)
        self.front_s = float(min(max(want, 0.1), room))
        self.tail_s = float(min(RING_TAIL_S, span))
        self.cx, self.cy = float(star.cx), float(star.cy)
        self.formed = False
        self.bands = None
        self.band_rgb = None
        self._u_sorted = None
        self._gain = None
        self._shape = (int(star.r_height), int(star.r_width))

    # ── FORM's start: the pieces as they are now (a fountain has just
    # sprayed), the bands as the strip shows them ──────────────────────────
    def _begin(self, star):
        p = self.p
        n = int(p.x.size)
        self.n = n
        self.formed = True
        try:
            self.bands, self.band_rgb = star._program_bands()
        except Exception:                                  # noqa: BLE001
            self.bands = np.linspace(0.12, 0.92, 8, dtype=np.float32)
            self.band_rgb = np.full((self.bands.size, 3), 200.0, np.float32)
        # the front passes an even SHARE of Star's cells every frame (its
        # cells crowd into a narrow band of radius, so a front at a steady
        # radial speed would light the whole middle at once)
        self._u_sorted = np.sort(self._u_field(star).ravel()).astype(np.float32)
        order = p.rng.permutation(n).astype(np.float32)
        self.ts = (self.t_form + (self.last_start - self.t_form)
                   * (order + 0.5) / max(n, 1)).astype(np.float32)
        self.j = np.full(n, -1, dtype=np.int64)
        self.ub = np.zeros(n, np.float32)
        self.phib = np.zeros(n, np.float32)
        self.d0x = np.zeros(n, np.float32)
        self.d0y = np.zeros(n, np.float32)
        self.e0x = np.zeros(n, np.float32)
        self.e0y = np.zeros(n, np.float32)
        self.s = np.zeros(n, np.float32)
        self.t_land = np.full(n, np.inf, np.float32)
        self.t_melt = np.full(n, np.inf, np.float32)
        if p.form_fade.size != n:
            p.form_fade = np.ones(n, np.float32)

    def _band_point(self, star, ub, phib):
        """Where a band point (rotating frame) is now, and its velocity
        (riding Star's rotation)."""
        qx, qy = star._piece_xy(ub, phib, star._program_theta())
        w = float(getattr(star, "_omega", 0.0) or 0.0)
        ux = -w * (qy - self.cy)
        uy = w * (qx - self.cx)
        return qx, qy, ux.astype(np.float32), uy.astype(np.float32)

    def _assign(self, star, idx):
        """Each piece starting its glide takes the band nearest where its
        own flight is taking it, at its own angle, inside the panel."""
        p = self.p
        h, w = self._shape
        fx_ = p.x[idx] + p.vx[idx] * 0.5 * self.lock
        fy_ = p.y[idx] + p.vy[idx] * 0.5 * self.lock
        u_pred, phi = star._program_polar(fx_, fy_)
        u_c = star._program_band_u(self.bands[None, :], phi[:, None])
        bx, by = star._piece_xy(u_c, np.broadcast_to(phi[:, None], u_c.shape),
                                star._program_theta())
        ok = ((u_c >= RING_U_MIN) & (bx >= 0.5) & (bx <= w - 0.5)
              & (by >= 0.5) & (by <= h - 0.5))
        cost = np.abs(u_c - u_pred[:, None]) + np.where(ok, 0.0, 10.0)
        j = np.argmin(cost, axis=1)
        rows = np.arange(idx.size)
        self.j[idx] = j
        self.ub[idx] = u_c[rows, j]
        self.phib[idx] = phi
        qx, qy, ux, uy = self._band_point(star, self.ub[idx], self.phib[idx])
        self.d0x[idx] = p.x[idx] - qx
        self.d0y[idx] = p.y[idx] - qy
        self.e0x[idx] = p.vx[idx] - ux
        self.e0y[idx] = p.vy[idx] - uy

    def advance(self, star, t, dt):
        p = self.p
        p._fly(star, t, dt)
        if t < self.t_form:
            return
        if not self.formed:
            self._begin(star)
        if self.n == 0:
            self._gain = self._gain_map(star, t)
            return
        new = (t >= self.ts) & (self.j < 0)
        if new.any():
            self._assign(star, np.flatnonzero(new))
        i = np.flatnonzero(self.j >= 0)
        if i.size:
            qx, qy, ux, uy = self._band_point(star, self.ub[i], self.phib[i])
            s = np.clip((t - self.ts[i]) / self.lock, 0.0, 1.0)
            h00, h10, dh00, dh10 = _hermite(s, self.lock)
            p.x[i] = (qx + h00 * self.d0x[i] + h10 * self.lock * self.e0x[i]
                      ).astype(np.float32)
            p.y[i] = (qy + h00 * self.d0y[i] + h10 * self.lock * self.e0y[i]
                      ).astype(np.float32)
            p.vx[i] = (ux + dh00 * self.d0x[i] + dh10 * self.e0x[i]
                       ).astype(np.float32)
            p.vy[i] = (uy + dh00 * self.d0y[i] + dh10 * self.e0y[i]
                       ).astype(np.float32)
            self.s[i] = s
            landed = i[s >= 1.0]
            self.t_land[landed] = np.minimum(self.t_land[landed], t)
        self._gain = self._gain_map(star, t)
        # a landed piece melts into its band once the front has passed its
        # cell — and by the end regardless
        land = np.flatnonzero(np.isfinite(self.t_land) & ~np.isfinite(self.t_melt))
        if land.size:
            hh, ww = self._shape
            xi = np.clip(np.floor(p.x[land]).astype(int), 0, ww - 1)
            yi = np.clip(np.floor(p.y[land]).astype(int), 0, hh - 1)
            passed = self._front_term[yi, xi] >= RING_PASSED
            self.t_melt[land[passed]] = t
        late = p.duration - RING_FADE_S
        if t >= late:
            self.t_melt = np.minimum(self.t_melt, np.float32(late))
        melt = np.isfinite(self.t_melt)
        p.form_fade[:] = 1.0
        if melt.any():
            p.form_fade[melt] = 1.0 - _smoothstep(
                (t - self.t_melt[melt]) / RING_FADE_S)

    def _u_field(self, star):
        u = getattr(star, "_last_u", None)
        if isinstance(u, np.ndarray) and u.shape == self._shape:
            return u
        hh, ww = self._shape
        yy, xx = np.mgrid[0:hh, 0:ww]
        r = np.hypot(xx + 0.5 - self.cx, yy + 0.5 - self.cy)
        return r / max(float(r.max()), 1.0)

    def _gain_map(self, star, t):
        d = self.p.duration
        u = self._u_field(star)
        srt = self._u_sorted
        rank = (np.searchsorted(srt, u, side="right").astype(np.float32)
                / max(srt.size, 1))
        q = (1.0 + RING_FRONT_W) * (t - self.t_form) / self.front_s
        level = RING_LEVEL + (1.0 - RING_LEVEL) * float(
            _smoothstep((t - (d - self.tail_s)) / max(self.tail_s, 1e-3)))
        front = _smoothstep((q - rank) / RING_FRONT_W).astype(np.float32)
        self._front_term = front * np.float32(level)
        g = self._front_term.copy()
        land = np.flatnonzero(np.isfinite(self.t_land)) if self.n else []
        if len(land):
            from scipy.ndimage import distance_transform_edt
            hh, ww = self._shape
            p = self.p
            xi = np.clip(np.floor(p.x[land]).astype(int), 0, ww - 1)
            yi = np.clip(np.floor(p.y[land]).astype(int), 0, hh - 1)
            owner = np.full((hh, ww), -1, dtype=np.int64)
            owner[yi, xi] = np.arange(land.size)
            dist, (ny, nx) = distance_transform_edt(owner < 0,
                                                    return_indices=True)
            who = owner[ny, nx]
            rad = (RING_GLOW_R0 + RING_GLOW_GROW
                   * np.maximum(t - self.t_land[land], 0.0)).astype(np.float32)
            glow = RING_GLOW * _smoothstep(1.0 - dist / rad[who])
            np.maximum(g, glow.astype(np.float32), out=g)
        return g

    def gain(self, t):
        if t < self.t_form or self._gain is None:
            return 0.0
        return self._gain

    def colour(self, t, rgb):
        """A gliding piece takes its band's colour as it lands."""
        if not self.formed or self.n == 0 or rgb.shape[0] != self.n:
            return rgb
        i = np.flatnonzero(self.j >= 0)
        if not i.size:
            return rgb
        out = rgb.copy()
        k = _smoothstep(self.s[i])[:, None].astype(np.float32)
        out[i] = rgb[i] + (self.band_rgb[self.j[i]] - rgb[i]) * k
        return out


class SparkRingsProgram(CloudProgram):
    """Fireworks -> Star: the sparks fly on as they were, slowing, and the
    RingFormer lands them on the bands."""

    name = tp.SPARK_RINGS
    SPLIT_MIN = MIN_PIECES

    def _release(self, star):
        self._release_snapshot()


WIND_ARC_S = 0.3        # the blobs come apart into arcs over this
WIND_ARC_DEG = 50.0     # ... each arc reaching this far along its orbit
WIND_ARC_MAX_T = 0.35   # ... (s of the blob's own motion, at most)
WIND_DOTS = 20          # dots per blob
WIND_DRAG = 0.3         # UNWIND's own drag (_StarRelease.DRAG)


class WindProgram(CloudProgram):
    """Orbits -> Star — UNWIND with time inverted (module docstring)."""

    name = tp.WIND
    DRAG = WIND_DRAG

    def _release(self, star):
        snap = self.snap
        px, py, vx, vy, grad, bright, rgb = self._snap_arrays()
        full_b = np.asarray(snap["bright"], np.float32)
        keep = (np.isfinite(np.asarray(snap["px"], np.float32))
                & np.isfinite(np.asarray(snap["py"], np.float32))
                & (np.clip(full_b, 0.0, 1.0) > 0.03))
        om = snap.get("om")
        om = (np.asarray(om, np.float32)[keep] if om is not None
              and len(om) == len(full_b) else np.zeros(px.size, np.float32))
        om = np.where(np.isfinite(om), om, 0.0).astype(np.float32)
        n = px.size
        dots = WIND_DOTS
        if n * dots > PIECE_CAP:
            dots = max(3, PIECE_CAP // max(n, 1))
            if n * dots > PIECE_CAP:
                sel = _cap_by_brightness(bright, PIECE_CAP // dots)
                px, py, vx, vy = px[sel], py[sel], vx[sel], vy[sel]
                grad, bright, rgb, om = grad[sel], bright[sel], rgb[sel], om[sel]
                n = px.size
        arc = math.radians(WIND_ARC_DEG)
        span = np.where(np.abs(om) > 1e-3,
                        np.minimum(arc / np.maximum(np.abs(om), 1e-3),
                                   WIND_ARC_MAX_T),
                        WIND_ARC_MAX_T).astype(np.float32)
        k = np.linspace(-1.0, 1.0, dots, dtype=np.float32)
        self.w_tau = (span[:, None] * k[None, :]).ravel()
        rep = lambda a: np.repeat(a, dots, axis=0)        # noqa: E731
        self.w_p0x, self.w_p0y = rep(px), rep(py)
        self.w_v0x, self.w_v0y = rep(vx), rep(vy)
        self.w_om = rep(om)
        self._set_pieces(self.w_p0x, self.w_p0y, self.w_v0x, self.w_v0y,
                         rep(grad), rep(np.clip(bright, 0.35, 1.0)), rep(rgb))
        self.ccx, self.ccy = float(star.cx), float(star.cy)

    def _orbit_at(self, s):
        """Each dot's blob's own orbit, `s` seconds on (the blob's velocity
        turning at its rate om) — the arc a dot is laid along."""
        om = self.w_om
        small = np.abs(om) < 1e-4
        safe = np.where(small, 1.0, om)
        a = np.where(small, s, np.sin(om * s) / safe)
        b = np.where(small, 0.5 * om * s * s, (1.0 - np.cos(om * s)) / safe)
        x = self.w_p0x + a * self.w_v0x - b * self.w_v0y
        y = self.w_p0y + a * self.w_v0y + b * self.w_v0x
        return x.astype(np.float32), y.astype(np.float32)

    def _fly(self, star, t, dt):
        if t < WIND_ARC_S:
            # each blob comes apart into an arc along its own orbit, every
            # dot still turning at the blob's rate
            e = float(_smoothstep(t / WIND_ARC_S))
            nx, ny = self._orbit_at(t + self.w_tau * e)
            if dt > 0:
                self.vx = ((nx - self.x) / dt).astype(np.float32)
                self.vy = ((ny - self.y) / dt).astype(np.float32)
            self.x, self.y = nx, ny
            return
        # then the arcs wind INWARD on UNWIND's own law (turn_about: the
        # tangential speed kept, decaying by DRAG; the radial part settling
        # out; the push, reversed), integrated in polar terms. turn_about
        # re-reads each piece's radial speed off its last frame's chord,
        # which adds a small outward drift on a turning ring (rho om^2 dt/2
        # a frame) — harmless outward, but it outruns an inward push, so
        # WIND keeps each piece's (vr, vt) itself.
        dx = self.x - self.ccx
        dy = self.y - self.ccy
        rho = np.maximum(np.hypot(dx, dy), 1e-3)
        ang = np.arctan2(dy, dx)
        if getattr(self, "w_vr", None) is None or self.w_vr.size != rho.size:
            ux, uy = dx / rho, dy / rho
            self.w_vr = (self.vx * ux + self.vy * uy).astype(np.float32)
            self.w_vt = (-self.vx * uy + self.vy * ux).astype(np.float32)
        self.w_vr = (self.w_vr * np.float32(math.exp(-dt / 0.25))
                     - np.float32(self.settings.unwind * dt))
        self.w_vt = self.w_vt * np.float32(math.exp(-self.DRAG * dt))
        ang = ang + self.w_vt / rho * dt
        rho2 = np.maximum(rho + self.w_vr * dt, 1.0)
        nx = (self.ccx + rho2 * np.cos(ang)).astype(np.float32)
        ny = (self.ccy + rho2 * np.sin(ang)).astype(np.float32)
        if dt > 0:
            self.vx = ((nx - self.x) / dt).astype(np.float32)
            self.vy = ((ny - self.y) / dt).astype(np.float32)
        self.x, self.y = nx, ny


PROGRAM_CLASSES = {
    tp.SPARK_RINGS: SparkRingsProgram,
    tp.WIND: WindProgram,
    tp.LENSING: LensingProgram,
    tp.FOUNTAIN: FountainProgram,
    tp.FLAME_LICK: FlameLickProgram,
    tp.IGNITION: IgnitionProgram,
    tp.SHOAL_BREAK: ShoalBreakProgram,
    tp.SHOALING: ShoalingProgram,
    # the host-frame variant of the SAME name, chosen by
    # transition_program.program_class when transition_burst_px > 0
    "shoaling_burst": ShoalBurstProgram,
    tp.UNRAVEL: UnravelProgram,
    tp.UNWIND: UnwindProgram,
    tp.CLUSTER: ClusterProgram,
}
