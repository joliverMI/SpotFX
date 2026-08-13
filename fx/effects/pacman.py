"""Pacman — a mini Ms. Pac-Man game as a music-reactive matrix effect.

She eats dots in a fixed maze while ghosts chase her. A lone ghost can
never catch her (it stumbles and scrambles away when it gets close), but
two chase ghosts cornering her at once DO catch her: death blink, respawn
at the start, ghosts return to the center house. Ghosts (re)spawn from the
house doors with a moment of invulnerability so she can't camp them.
Eating a power dot — or forcing the `reverse` toggle — frightens the
ghosts: they turn blue, flee, and she hunts them down.

Audio: beats make her jump forward, the selected band drives her speed and
the wall-color gradient cycle. Effect switches ride the LedFX crossfade as a
big chomping Pac-Man that wipes the old effect away / reveals the maze.

Designed for the crystal-mapper lattice: a bold 18x18 logical maze (1 cell
= 4x2 render px at 72x37) fitted to the ball's elliptical silhouette; walls
are one uniform gradient color that rolls with the music; entities are soft
additive glow blobs, not sprites.
"""

import logging
import math
from collections import deque

import numpy as np
import voluptuous as vol
from PIL import Image

import fx.effects.particle_handoff as particle_handoff
from fx.color import validate_gradient
from fx.effects.audio import AudioReactiveEffect
from fx.effects.gradient import GradientEffect
from fx.effects.twod import Twod

_LOGGER = logging.getLogger(__name__)

LOGICAL_W = 18
LOGICAL_H = 18
DT_MAX = 0.1
KERNEL_R = 7  # splat kernel table radius (entity_size max 6)
WIPE_FALLBACK_S = 1.5  # wall-clock wipe when transition counters are unusable

PAC_RGB = (255, 220, 40)
FRIGHT_RGB = (60, 60, 255)
GHOST_COLORS = (
    (255, 40, 40),  # blinky
    (255, 120, 190),  # pinky
    (0, 255, 255),  # inky
    (255, 160, 40),  # sue
)
DOT_RGB = (200, 190, 160)
POWER_RGB = (255, 245, 220)

# Per-ghost chase-target bias (cells ahead/around pacman) so they don't stack.
GHOST_BIAS = ((0.0, 0.0), (2.0, 0.0), (0.0, 2.0), (-2.0, -2.0))

CHASE, FRIGHT, EYES = 0, 1, 2

AVOID_R = 2.5  # pacman starts dodging ghosts within this many cells
STUMBLE_R = 1.4  # chase ghost this close -> stumbles (never-caught rule)
EAT_R = 0.7  # frightened ghost this close -> eaten
STUMBLE_S = 0.8  # stumble duration (ghost scrambles away fast)
STUMBLE_FLEE = 1.7  # stumbled ghost speed vs hers — outruns even her boost
BOOST_S = 0.5  # pacman escape boost duration (1.6x speed)
RESPAWN_S = 2.5  # eyes -> respawn delay
FADE_IN_S = 1.0  # ghost fade-in after (re)spawn
INVULN_S = 1.0  # fresh ghosts can't be eaten (anti-camping)
FRIGHT_FLASH_S = 1.5  # blue/white flashing at the end of fright
LEVEL_FLASH_S = 1.2  # white maze flash on level clear
EAT_FLASH_S = 0.15  # white pop where a ghost was eaten
PINCER_R = 2.2  # two chase ghosts inside this = she can be cornered
CATCH_R = 0.95  # ...and one this close catches her
CAUGHT_S = 1.6  # freeze + death blink before she respawns at start

# 18x18 bold logical maze fitted to the crystal ellipse — each cell renders
# as a 4x2 px block at 72x37, so the maze reads big on the ball.
# '-' void, '#' wall, '.' dot, 'o' power dot, 'T' tunnel mouth (wraps to the
# mirrored mouth on the same row). Left-right symmetric; every lane is
# single-width (no 2x2 open blocks — checked by scratchpad maze_design.py).
MAZE = [
    "----##########----",
    "----#o......o#----",
    "---##.#.##.#.##---",
    "---#..........#---",
    "--##.#.####.#.##--",
    "--#.....##.....#--",
    "-##.#.#.##.#.#.##-",
    "-T..............T-",
    "###.#.######.#.###",
    "T.#.#.######.#.#.T",
    "-T..............T-",
    "-##.#.#.##.#.#.##-",
    "--#.....##.....#--",
    "--##.#.####.#.##--",
    "---#..........#---",
    "---##.#.##.#.##---",
    "----#o......o#----",
    "----##########----",
]

PAC_START = (8, 10)
# corridor cells flanking the center slab — the "ghost house" doors
GHOST_SPAWNS = ((5, 8), (12, 8), (5, 9), (12, 9))


class PacGame:
    """Pure game logic on the logical grid — no LedFX imports, testable
    standalone. Cells are (x, y); entities sit at cell + dir * t, t in
    [0, 1), moving toward `nxt` (which differs from cell + dir only across
    tunnel wraps)."""

    def __init__(self, maze=MAZE, ghost_count=4, rng=None):
        self.rng = rng if rng is not None else np.random.default_rng()
        self._load(maze)
        self.dots = set(self.all_dots)
        self.power = set(self.all_power)
        self.fright_timer = 0.0
        self.forced_fright = False
        self.level_flash = 0.0
        self.boost_timer = 0.0
        self.caught_timer = 0.0
        self.caught_count = 0
        self.eat_flashes = []  # [(fx, fy), age]
        self.spawns = [s for s in GHOST_SPAWNS if s in self.neighbors] \
            or list(self.mouths) or [PAC_START]
        self._field = {}
        self._field_src = None
        self._target = None
        self.pac = self._spawn_entity(PAC_START)
        self.ghosts = []
        self.set_ghost_count(ghost_count)

    # ── maze loading ──────────────────────────────────────────────────

    def _load(self, maze):
        if len(maze) != LOGICAL_H or any(len(r) != LOGICAL_W for r in maze):
            raise ValueError("MAZE must be %dx%d" % (LOGICAL_W, LOGICAL_H))
        self.wall = set()
        self.all_dots = set()
        self.all_power = set()
        self.mouths = []
        walkable = set()
        for y, row in enumerate(maze):
            for x, ch in enumerate(row):
                if ch == "#":
                    self.wall.add((x, y))
                elif ch in ".oT":
                    walkable.add((x, y))
                    if ch == ".":
                        self.all_dots.add((x, y))
                    elif ch == "o":
                        self.all_power.add((x, y))
                    else:
                        self.mouths.append((x, y))
        # neighbor graph incl. tunnel wraps (mouths pair left-right per row)
        self.neighbors = {}
        for (x, y) in walkable:
            cands = []
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (x + dx, y + dy)
                if n in walkable:
                    cands.append((n, (dx, dy)))
            self.neighbors[(x, y)] = cands
        by_row = {}
        for m in self.mouths:
            by_row.setdefault(m[1], []).append(m)
        for y, pair in by_row.items():
            if len(pair) != 2:
                _LOGGER.warning("pacman maze: unpaired tunnel mouth row %d", y)
                continue
            a, b = sorted(pair)
            # exiting outward wraps to the mirrored mouth, heading kept
            self.neighbors[a].append((b, (-1, 0)))
            self.neighbors[b].append((a, (1, 0)))
        # cells are 4x2 render px: a dot on EVERY cell of a vertical
        # corridor is twice as dense on screen as on a horizontal one —
        # thin vertical-only runs to every other cell for even spacing
        for c in [c for c in self.all_dots
                  if c[1] % 2 == 1
                  and all(d[0] == 0 for _, d in self.neighbors[c])]:
            self.all_dots.discard(c)
        # flood fill from start; demote unreachable dots instead of crashing
        reach = self._bfs(PAC_START)
        for bad in [c for c in self.all_dots | self.all_power
                    if c not in reach]:
            _LOGGER.warning("pacman maze: unreachable cell %s -> wall", bad)
            self.all_dots.discard(bad)
            self.all_power.discard(bad)
            self.wall.add(bad)
            self.neighbors.pop(bad, None)

    def _bfs(self, src):
        dist = {src: 0}
        q = deque((src,))
        while q:
            c = q.popleft()
            d = dist[c] + 1
            for n, _dir in self.neighbors.get(c, ()):
                if n not in dist:
                    dist[n] = d
                    q.append(n)
        return dist

    def _field_from(self, src):
        if self._field_src != src:
            self._field = self._bfs(src)
            self._field_src = src
        return self._field

    # ── entities ──────────────────────────────────────────────────────

    def _spawn_entity(self, cell):
        nxt, d = self.neighbors[cell][0]
        return {"cell": cell, "nxt": nxt, "dir": d, "t": 0.0}

    def set_ghost_count(self, n):
        n = max(1, min(4, int(n)))
        while len(self.ghosts) > n:
            self.ghosts.pop()
        while len(self.ghosts) < n:
            i = len(self.ghosts)
            g = self._spawn_ghost(i)
            # stagger the initial arrivals
            g["state"] = EYES
            g["respawn_timer"] = 0.4 + 0.6 * i
            self.ghosts.append(g)

    def _spawn_ghost(self, idx):
        # emerge from the center house — prefer the door farthest from her
        # (plus a random tiebreak) so she can't camp a spawn point
        ppos = self.pos(self.pac) if hasattr(self, "pac") else PAC_START
        ranked = sorted(
            self.spawns,
            key=lambda s: self._d2(s, ppos)
            + float(self.rng.random()) * 4.0,
            reverse=True,
        )
        cell = ranked[0]
        nxt, d = self.neighbors[cell][
            int(self.rng.integers(len(self.neighbors[cell])))
        ]
        return {
            "cell": cell, "nxt": nxt, "dir": d, "t": 0.0, "idx": idx,
            "state": FRIGHT if self._fright_active() else CHASE,
            "respawn_timer": 0.0, "stumble_timer": 0.0, "fade_age": 0.0,
        }

    @staticmethod
    def pos(ent):
        cx, cy = ent["cell"]
        dx, dy = ent["dir"]
        return (cx + dx * ent["t"], cy + dy * ent["t"])

    @staticmethod
    def mirror_pos(ent):
        """Second draw position while crossing a tunnel wrap, else None."""
        cx, cy = ent["cell"]
        nx, ny = ent["nxt"]
        if abs(nx - cx) <= 1 and abs(ny - cy) <= 1:
            return None
        dx, dy = ent["dir"]
        return (nx - dx * (1.0 - ent["t"]), ny - dy * (1.0 - ent["t"]))

    def _fright_active(self):
        return self.forced_fright or self.fright_timer > 0.0

    # ── movement ──────────────────────────────────────────────────────

    def _advance(self, ent, dist, is_pac, ghost=None):
        guard = 0
        while dist > 1e-9 and guard < 12:
            guard += 1
            remain = 1.0 - ent["t"]
            if dist < remain:
                ent["t"] += dist
                return
            dist -= remain
            ent["t"] = 0.0
            ent["cell"] = ent["nxt"]
            if is_pac:
                self._eat(ent["cell"])
                self._pac_choose(ent)
            else:
                self._ghost_choose(ghost)

    def _candidates(self, ent):
        cands = self.neighbors.get(ent["cell"], [])
        if len(cands) > 1:
            back = (-ent["dir"][0], -ent["dir"][1])
            fwd = [c for c in cands if c[1] != back]
            if fwd:
                return fwd
        return cands

    def _pac_choose(self, ent):
        cands = self._candidates(ent)
        if not cands:
            return
        ppos = self.pos(ent)
        hostiles = [self.pos(g) for g in self.ghosts
                    if g["state"] == CHASE]
        fright_prey = [g for g in self.ghosts if g["state"] == FRIGHT]
        if self._fright_active() and fright_prey:
            prey = min(fright_prey,
                       key=lambda g: self._d2(ppos, self.pos(g)))
            field = self._field_from(prey["cell"])
        else:
            if self._target not in self.dots and \
                    self._target not in self.power:
                self._target = self._nearest_dot(ent["cell"])
            field = self._field_from(self._target) \
                if self._target else {}
        best, best_score = None, None
        for n, d in cands:
            score = field.get(n, 500.0)
            for h in hostiles:
                score += 8.0 * max(0.0, AVOID_R - math.dist(n, h))
            score += 0.1 * float(self.rng.random())
            if best_score is None or score < best_score:
                best, best_score = (n, d), score
        ent["nxt"], ent["dir"] = best

    def _nearest_dot(self, cell):
        pool = self.dots or self.power
        if not pool:
            return None
        return min(pool, key=lambda c: self._d2(cell, c))

    @staticmethod
    def _d2(a, b):
        return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2

    def _ghost_choose(self, g):
        cands = self._candidates(g)
        if not cands:
            return
        ppos = self.pos(self.pac)
        if g["state"] == FRIGHT or g["stumble_timer"] > 0.0:
            best = max(
                cands,
                key=lambda c: self._d2(c[0], ppos)
                + float(self.rng.random()) * 4.0,
            )
        else:
            bias = GHOST_BIAS[g["idx"] % len(GHOST_BIAS)]
            target = (ppos[0] + bias[0], ppos[1] + bias[1])
            if self.rng.random() < 0.25:
                best = cands[int(self.rng.integers(len(cands)))]
            else:
                best = min(cands, key=lambda c: self._d2(c[0], target))
        g["nxt"], g["dir"] = best

    def _stumble(self, g, ppos):
        """Trip a chase ghost and send it scrambling directly away from
        her — direction chosen over ALL neighbors (reversal allowed), so it
        flees correctly even if she just jumped past it."""
        if g["t"] > 0.5:
            g["cell"] = g["nxt"]
        g["t"] = 0.0
        g["stumble_timer"] = STUMBLE_S
        cands = self.neighbors.get(g["cell"], [])
        if cands:
            g["nxt"], g["dir"] = max(
                cands, key=lambda c: self._d2(c[0], ppos)
            )
        # the node snap above may have moved it closer — always recoil on
        # the post-snap distance, iterating because corridor distance
        # shrinks around corners relative to euclid
        if math.dist(ppos, self.pos(g)) < 1.1:
            tries = 0
            while math.dist(ppos, self.pos(g)) < 1.1 and tries < 5:
                self._advance(g, 0.5, False, ghost=g)
                tries += 1
            if math.dist(ppos, self.pos(g)) < 0.9:
                # nowhere for it to flee — she is truly cornered: caught
                self._catch()

    @staticmethod
    def _reverse(ent):
        ent["cell"], ent["nxt"] = ent["nxt"], ent["cell"]
        ent["dir"] = (-ent["dir"][0], -ent["dir"][1])
        ent["t"] = 1.0 - ent["t"]

    def _eat(self, cell):
        if cell in self.dots:
            self.dots.discard(cell)
            if cell == self._target:
                self._target = None
        elif cell in self.power:
            self.power.discard(cell)
            if cell == self._target:
                self._target = None
            self.fright_timer = self._fright_time
            for g in self.ghosts:
                if g["state"] == CHASE:
                    g["state"] = FRIGHT
                    self._reverse(g)

    # ── frame update ──────────────────────────────────────────────────

    def step(self, dt, pac_speed, ghost_frac, fright_time):
        self._fright_time = fright_time
        if self.caught_timer > 0.0:
            self.caught_timer -= dt
            if self.caught_timer <= 0.0:
                self.pac = self._spawn_entity(PAC_START)
                self._target = None
                self._field_src = None
                for i, g in enumerate(self.ghosts):
                    g["state"] = EYES
                    g["respawn_timer"] = 0.6 + 0.5 * i
            return
        if self.level_flash > 0.0:
            self.level_flash -= dt
            if self.level_flash <= 0.0:
                self.dots = set(self.all_dots)
                self.power = set(self.all_power)
                self._target = None
                self._field_src = None
            return
        if not self.forced_fright and self.fright_timer > 0.0:
            self.fright_timer = max(0.0, self.fright_timer - dt)
            if self.fright_timer == 0.0:
                for g in self.ghosts:
                    if g["state"] == FRIGHT:
                        g["state"] = CHASE
        if self.forced_fright:
            for g in self.ghosts:
                if g["state"] == CHASE:
                    g["state"] = FRIGHT
        self.boost_timer = max(0.0, self.boost_timer - dt)
        self.eat_flashes = [
            (p, age + dt) for p, age in self.eat_flashes
            if age + dt < EAT_FLASH_S
        ]

        boost = 1.6 if self.boost_timer > 0.0 else 1.0
        self._advance(self.pac, pac_speed * boost * dt, True)

        for g in self.ghosts:
            if g["state"] == EYES:
                g["respawn_timer"] -= dt
                if g["respawn_timer"] <= 0.0:
                    fresh = self._spawn_ghost(g["idx"])
                    g.update(fresh)
                continue
            g["fade_age"] += dt
            g["stumble_timer"] = max(0.0, g["stumble_timer"] - dt)
            if g["stumble_timer"] > 0.0 and g["state"] == CHASE:
                # scrambling away from her — must outrun her boost
                speed = pac_speed * STUMBLE_FLEE
            else:
                speed = pac_speed * ghost_frac
            self._advance(g, speed * dt, False, ghost=g)

        self._collisions()
        if not self.dots and not self.power:
            self.level_flash = LEVEL_FLASH_S

    def jump(self, cells):
        """Beat jump: skip ahead along the corridor, eating on the way.
        Advances in small chunks so she can't tunnel through a ghost
        between collision checks."""
        if self.level_flash > 0.0 or self.caught_timer > 0.0 or cells <= 0.0:
            return
        remaining = cells
        while remaining > 0.0:
            chunk = min(remaining, 0.35)
            self._advance(self.pac, chunk, True)
            self._collisions()
            remaining -= chunk

    def _catch(self):
        """She's cornered — freeze for the death blink, then respawn at
        start while every ghost returns to the house."""
        if self.caught_timer > 0.0:
            return
        self.caught_timer = CAUGHT_S
        self.caught_count += 1
        self.fright_timer = 0.0
        self.boost_timer = 0.0
        self.eat_flashes.append((self.pos(self.pac), 0.0))

    def _collisions(self):
        if self.caught_timer > 0.0:
            return
        ppos = self.pos(self.pac)
        # pincer: cornered between two established chase ghosts = caught.
        # A lone ghost can never catch her (the stumble rule saves her),
        # so ghosts stay not-too-effective.
        chasers = [
            g for g in self.ghosts
            if g["state"] == CHASE and g["fade_age"] >= INVULN_S
        ]
        close = [g for g in chasers
                 if math.dist(ppos, self.pos(g)) < PINCER_R]
        if len(close) >= 2 and any(
            math.dist(ppos, self.pos(g)) < CATCH_R for g in close
        ):
            self._catch()
            return
        for g in self.ghosts:
            if g["state"] == EYES:
                continue
            d = math.dist(ppos, self.pos(g))
            if g["state"] == FRIGHT:
                # fresh respawns are invulnerable for a moment (no camping)
                if d < EAT_R and g["fade_age"] >= INVULN_S:
                    g["state"] = EYES
                    g["respawn_timer"] = RESPAWN_S
                    self.eat_flashes.append((self.pos(g), 0.0))
            elif d < STUMBLE_R and (
                g["stumble_timer"] <= 0.0 or d < 1.0
            ):
                # a lone ghost trips and scrambles away
                self._stumble(g, ppos)
                self.boost_timer = BOOST_S


class Pacman(Twod, GradientEffect):
    NAME = "Pacman"
    # maze walls + lattice-snapped dots are drawn pixel-exact — shape-mapped
    # virtuals identity-sample this effect rather than kernel-resampling
    LATTICE_EXACT = True
    CATEGORY = "Matrix"
    # walls/dots fill the frame — background keys are meaningless; the wall
    # cycle accumulator supersedes gradient_roll
    HIDDEN_KEYS = Twod.HIDDEN_KEYS + [
        "gradient_roll",
        "background_color",
        "background_brightness",
        "background_mode",
    ]
    ADVANCED_KEYS = Twod.ADVANCED_KEYS + [
        "ghost_speed",
        "impulse_decay",
        "fright_time",
    ]

    CONFIG_SCHEMA = vol.Schema(
        {
            vol.Optional(
                "gradient",
                description="Maze wall color gradient",
                default="linear-gradient(90deg, #0020ff 0.00%, #00c0ff 45.00%, #a000ff 100.00%)",
            ): validate_gradient,
            vol.Optional(
                "wall_brightness",
                description="Maze wall brightness",
                default=0.34,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.05, max=1.0)),
            vol.Optional(
                "dot_brightness",
                description="Dot brightness",
                default=0.78,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "wall_cycle",
                description="Base wall gradient cycle speed (rev/s)",
                default=0.41,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "wall_audio",
                description="How much the music level speeds up the wall color cycle",
                default=1.3,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=2.0)),
            vol.Optional(
                "base_speed",
                description="Ms Pacman baseline speed, maze cells per second",
                default=2.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=1.0, max=12.0)),
            vol.Optional(
                "speed_audio",
                description="How much music intensity boosts her speed",
                default=3.3,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=5.0)),
            vol.Optional(
                "beat_jump",
                description="Cells she jumps forward on each beat",
                default=1.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=4.0)),
            vol.Optional(
                "reverse",
                description="Force power-dot mode: ghosts stay blue and she hunts them",
                default=False,
            ): bool,
            vol.Optional(
                "fright_time",
                description="Seconds ghosts stay frightened after a power dot",
                default=6.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=2.0, max=15.0)),
            vol.Optional(
                "ghost_count",
                description="Number of ghosts",
                default=4,
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=4)),
            vol.Optional(
                "ghost_speed",
                description="Ghost speed as a fraction of hers (a lone ghost can never catch her)",
                default=0.73,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=0.95)),
            vol.Optional(
                "entity_size",
                description="Glow blob radius in pixels",
                default=3.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=1.0, max=6.0)),
            vol.Optional(
                "trail_decay",
                description="Comet-trail length: 0 = crisp blobs, 1 = long smear",
                default=0.35,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "smooth_motion",
                description="Glide entities between positions (beat jumps and recoils ease instead of teleporting); game logic unchanged",
                default=True,
            ): bool,
            vol.Optional(
                "frequency_range",
                description="Audio band driving speed and wall cycling",
                default="Lows (beat+bass)",
            ): vol.In(list(AudioReactiveEffect.POWER_FUNCS_MAPPING.keys())),
            vol.Optional(
                "impulse_decay",
                description="Decay filter applied to the audio impulse",
                default=0.09,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.01, max=0.3)),
        }
    )

    def __init__(self, ledfx, config):
        # Game state lives here (NOT do_once) so it survives config patches —
        # morph ramps are a patch storm and would reset the game constantly.
        self.game = PacGame()
        self.impulse = 0.0
        self._beat_pending = False
        self._beat_phase = 0.0
        self._phase_seen = -1.0
        self._phase_moved_at = 0.0
        self.cycle_pos = 0.0
        self._wipe_t0 = None
        self._morph_out_p = None  # crossfade frac while a particle sibling waits to adopt our entities
        self.trail = None  # persistent comet-trail buffer (do_once sizes it)
        self._disp = {}  # smoothed display positions per entity

        # static splat kernel offset table (same idiom as blackhole/orbits)
        span = np.arange(-KERNEL_R, KERNEL_R + 1)
        kdx, kdy = np.meshgrid(span, span)
        kdist = np.sqrt(kdx**2 + kdy**2).ravel()
        keep = kdist <= KERNEL_R
        self.k_dx = kdx.ravel()[keep].astype(np.int32)
        self.k_dy = kdy.ravel()[keep].astype(np.int32)
        self.k_dist = kdist[keep].astype(np.float32)

        super().__init__(ledfx, config)

    def config_updated(self, config):
        super().config_updated(config)
        self.wall_brightness = self._config["wall_brightness"]
        self.dot_brightness = self._config["dot_brightness"]
        self.wall_cycle = self._config["wall_cycle"]
        self.wall_audio = self._config["wall_audio"]
        self.base_speed = self._config["base_speed"]
        self.speed_audio = self._config["speed_audio"]
        self.beat_jump = self._config["beat_jump"]
        self.fright_time = self._config["fright_time"]
        self.ghost_frac = self._config["ghost_speed"]
        self.entity_size = self._config["entity_size"]
        self.trail_decay = self._config["trail_decay"]
        self.smooth_motion = bool(self._config["smooth_motion"])
        self.game.forced_fright = bool(self._config["reverse"])
        self.game.set_ghost_count(int(self._config["ghost_count"]))
        self.power_func = self.POWER_FUNCS_MAPPING[
            self._config["frequency_range"]
        ]
        self.impulse_filter = self.create_filter(
            alpha_decay=self._config["impulse_decay"], alpha_rise=0.99
        )

    def audio_data_updated(self, data):
        # audio thread — latch only
        impulse = self.impulse_filter.update(getattr(data, self.power_func)())
        self.impulse = float(impulse) if np.isfinite(impulse) else 0.0
        phase = data.beat_oscillator()
        self._beat_phase = float(phase) if np.isfinite(phase) else 0.0
        if data.bpm_beat_now():
            self._beat_pending = True

    def do_once(self):
        super().do_once()
        # Render caches only — nearest-neighbor logical->render maps work on
        # any matrix size (exactly 2x1 blocks on the 72x37 crystal-mapper).
        w, h = self.r_width, self.r_height
        lx = (np.arange(w) * LOGICAL_W) // w
        ly = (np.arange(h) * LOGICAL_H) // h
        self.cell_id_img = (
            ly[:, None] * LOGICAL_W + lx[None, :]
        ).astype(np.int32)
        wall_lut = np.zeros(LOGICAL_W * LOGICAL_H, dtype=bool)
        for (x, y) in self.game.wall:
            wall_lut[y * LOGICAL_W + x] = True
        wall_mask = wall_lut[self.cell_id_img]
        self.wall_flat_idx = np.flatnonzero(wall_mask)
        self.sx = w / LOGICAL_W
        self.sy = h / LOGICAL_H
        self._n_cells = w * h
        # one render pixel per dot, snapped to the device lattice via the
        # shared lattice view (shape map when present, else the historical
        # parity guess); harmless on other matrices
        from fx.effects import lattice

        lat = lattice.get_view(self)
        self.dot_px = {}
        for (x, y) in self.game.all_dots:
            r = min(int((y + 0.5) * self.sy), h - 1)
            cands = np.flatnonzero(lx == x)
            if lat.has_real_shape:
                live = [c for c in cands if lat.inside(int(c), r)]
                if live:
                    c = live[len(live) // 2]
                else:
                    mid = cands[len(cands) // 2]
                    c, r = lat.snap(float(mid), float(r))
            else:
                want = 1 - (r % 2)
                match = [c for c in cands if c % 2 == want]
                c = match[len(match) // 2] if match else cands[len(cands) // 2]
            self.dot_px[(x, y)] = r * w + int(c)
        # persistent trail survives config patches; resize only when the
        # render dims actually change (same guard as orbits/blackhole)
        if self.trail is None or self.trail.shape[:2] != (h, w):
            self.trail = np.zeros((h, w, 3), dtype=np.float32)

    def _to_px(self, pos):
        return ((pos[0] + 0.5) * self.sx, (pos[1] + 0.5) * self.sy)

    def _splat(self, buf, xs, ys, rgb, size):
        """Additively stamp a soft dot at each (xs, ys) pixel position."""
        keep = self.k_dist <= size
        k_dx = self.k_dx[keep]
        k_dy = self.k_dy[keep]
        k_w = (1.0 - self.k_dist[keep] / (size + 0.5)).astype(np.float32)
        xi = np.round(np.atleast_1d(xs)).astype(np.int32)
        yi = np.round(np.atleast_1d(ys)).astype(np.int32)
        px = (xi[:, None] + k_dx[None, :]).ravel()
        py = (yi[:, None] + k_dy[None, :]).ravel()
        valid = (
            (px >= 0)
            & (px < self.r_width)
            & (py >= 0)
            & (py < self.r_height)
        )
        if not valid.any():
            return
        idx = (py * self.r_width + px)[valid]
        w = np.broadcast_to(
            k_w[None, :], (xi.size, k_w.size)
        ).ravel()[valid]
        for channel in range(3):
            buf[..., channel] += np.bincount(
                idx, weights=w * rgb[channel], minlength=self._n_cells
            ).reshape(self.r_height, self.r_width)

    SMOOTH_TAU = 0.07  # seconds; display position eases toward the true one
    SMOOTH_SNAP_PX = 24.0  # bigger jumps (tunnel wraps) snap instead

    def _smooth_px(self, key, px, py, dt):
        """Ease the rendered position toward the true game position so beat
        jumps and stumble recoils glide instead of teleporting. Purely
        cosmetic — collision/eat logic runs on the true positions."""
        if not self.smooth_motion:
            self._disp.pop(key, None)
            return px, py
        prev = self._disp.get(key)
        if (
            prev is None
            or (prev[0] - px) ** 2 + (prev[1] - py) ** 2
            > self.SMOOTH_SNAP_PX**2
        ):
            self._disp[key] = (px, py)
            return px, py
        a = 1.0 - math.exp(-dt / self.SMOOTH_TAU)
        nx = prev[0] + (px - prev[0]) * a
        ny = prev[1] + (py - prev[1]) * a
        self._disp[key] = (nx, ny)
        return nx, ny

    def _chomp_phase(self):
        """Beat phase when the tempo tracker is alive, wall-clock otherwise."""
        if self._beat_phase != self._phase_seen:
            self._phase_seen = self._beat_phase
            self._phase_moved_at = self.now
        if self.now - self._phase_moved_at > 1.5:
            return (self.now * 2.5) % 1.0
        return self._beat_phase

    # ── particle handoff (pacman -> blackhole/orbits/fireworks) ───────

    PARTICLE_SIBLINGS = frozenset(
        {"Blackhole", "Orbits", "Fireworks", "Squiggles"}
    )

    def _handoff_snapshot(self):
        """Live entities in the neutral particle-handoff format: each one
        becomes a particle (blackhole/orbits) or its own exploding firework.
        The carried gradient is built from the entities' actual colors so
        she flies off yellow and each ghost keeps its identity."""
        if getattr(self, "r_width", None) is None or self.trail is None:
            return None
        game = self.game
        ents = [(*self._to_px(game.pos(game.pac)), PAC_RGB, 1.0)]
        for g in game.ghosts:
            if g["state"] == EYES:
                continue
            rgb = (
                FRIGHT_RGB
                if g["state"] == FRIGHT
                else GHOST_COLORS[g["idx"] % len(GHOST_COLORS)]
            )
            fade = min(g["fade_age"] / FADE_IN_S, 1.0)
            gx, gy = self._to_px(game.pos(g))
            ents.append((gx, gy, rgb, max(fade, 0.3)))
        n = len(ents)
        grad_pos = [0.5] if n == 1 else [i / (n - 1) for i in range(n)]
        stops = ", ".join(
            "#%02x%02x%02x %.2f%%" % (*e[2], p * 100.0)
            for e, p in zip(ents, grad_pos)
        )
        if n == 1:
            stops = "%s, %s" % (
                stops.replace(" 50.00%", " 0.00%"),
                stops.replace(" 50.00%", " 100.00%"),
            )
        return {
            "src": "pacman",
            "t": particle_handoff.now(),
            "dims": (self.r_width, self.r_height),
            "px": np.array([e[0] for e in ents], dtype=np.float32),
            "py": np.array([e[1] for e in ents], dtype=np.float32),
            "grad": np.array(grad_pos, dtype=np.float32),
            "bright": np.array([e[3] for e in ents], dtype=np.float32),
            "gradient": "linear-gradient(90deg, %s)" % stops,
            "spin_sign": 0.0,
            "blob_size": float(self.entity_size),
            "flow": "out",
            "center_px": (self.r_width / 2.0, self.r_height / 2.0),
            "trail": self.trail,
        }

    def deactivate(self):
        virtual = self._virtual
        try:
            if virtual is not None:
                particle_handoff.store(virtual.id, self._handoff_snapshot())
        except Exception:
            pass
        super().deactivate()

    # ── wipe (rides the LedFX Add crossfade, which is a linear blend) ──

    def _wipe_state(self):
        """(role, progress) where role is 'in'/'out'/None."""
        virtual = self._virtual
        self._morph_out_p = None
        sib = getattr(virtual, "_transition_effect", None)
        if sib is None:
            self._wipe_t0 = None
            return None, 0.0
        if sib is self:
            # a particle sibling adopts our entities instead of being wiped:
            # phase 1 fades the maze (walls/dots) while the entities play on;
            # at PACMAN_MORPH_START the sibling turns them into particles
            inc = particle_handoff.incoming_sibling(virtual, self)
            if getattr(inc, "NAME", None) in self.PARTICLE_SIBLINGS:
                self._wipe_t0 = None
                self._morph_out_p = particle_handoff.transition_progress(
                    virtual
                )
                return None, 0.0
            role = "out"
        elif getattr(sib, "NAME", None) != self.NAME:
            role = "in"
        else:  # pacman -> pacman recreation: no wipe
            self._wipe_t0 = None
            return None, 0.0
        p = particle_handoff.transition_progress(virtual)
        if p is None:
            if self._wipe_t0 is None:
                self._wipe_t0 = self.now
            p = min((self.now - self._wipe_t0) / WIPE_FALLBACK_S, 1.0)
        return role, p

    def _draw_wipe(self, buf, role, p):
        w, h = self.r_width, self.r_height
        e = p * p * (3.0 - 2.0 * p)  # smoothstep
        radius = 0.45 * h
        front_x = e * (w + 2.0 * radius) - radius
        cy = h / 2.0
        cols = np.arange(w, dtype=np.float32)
        if role == "in":
            buf[:, cols > front_x] = 0.0
            buf *= min(1.0 / max(p, 0.45), 2.2)
            # counter the p-share so the disc isn't translucent early
            sprite_gain = min(1.0 / max(p, 0.4), 2.5)
        else:
            buf[:, cols < front_x] = 0.0
            sprite_gain = min(1.0 / max(1.0 - p, 1e-3), 3.0)
        # big chomping pacman at the wavefront
        x0 = max(int(front_x - radius) - 1, 0)
        x1 = min(int(front_x + radius) + 2, w)
        if x1 <= x0:
            return
        yy, xx = np.mgrid[0:h, x0:x1]
        dx = xx - front_x
        dy = yy - cy
        dist = np.sqrt(dx * dx + dy * dy)
        chomp = self._chomp_phase()
        half = math.radians(10.0 + 35.0 * abs(math.sin(math.pi * chomp)))
        mouth = np.abs(np.arctan2(dy, dx)) < half  # opens toward +x
        body = (dist <= radius) & ~mouth
        region = buf[:, x0:x1]
        region[body] = np.array(PAC_RGB, dtype=np.float32) * min(
            sprite_gain, 3.0
        )
        # single dark eye so the disc reads as a face
        eye = (
            np.sqrt(
                (xx - (front_x + radius * 0.1)) ** 2
                + (yy - (cy - radius * 0.55)) ** 2
            )
            < radius * 0.14
        )
        region[eye & body] = 0.0

    # ── frame ─────────────────────────────────────────────────────────

    def draw(self):
        if self.test:
            self.draw_test(self.m_draw)
            return
        dt = self.passed
        if not np.isfinite(dt) or dt <= 0.0:
            dt = 1.0 / 60.0
        dt = min(dt, DT_MAX)

        role, wipe_p = self._wipe_state()

        # particle-handoff phase 1: maze layers fade to black while the
        # entities keep playing; once the sibling adopts them (phase 2) we
        # stop drawing them too and only the comet trails decay out
        maze_fade = 1.0
        entities_on = True
        if self._morph_out_p is not None:
            ph = min(
                self._morph_out_p / particle_handoff.PACMAN_MORPH_START, 1.0
            )
            maze_fade = (1.0 - ph) * (1.0 - ph)
            entities_on = (
                self._morph_out_p < particle_handoff.PACMAN_MORPH_START
            )

        game = self.game
        pac_speed = min(
            self.base_speed * (0.35 + self.speed_audio * self.impulse), 14.0
        )
        if self._beat_pending:
            self._beat_pending = False
            game.jump(self.beat_jump)
        game.step(dt, pac_speed, self.ghost_frac, self.fright_time)

        w, h = self.r_width, self.r_height
        buf = np.zeros((h, w, 3), dtype=np.float32)

        # walls: one uniform color bouncing back and forth through the
        # gradient with music — a triangle wave instead of a wrapping ramp,
        # so non-cyclic gradients never snap from end back to start
        self.cycle_pos = (
            self.cycle_pos
            + (self.wall_cycle + self.wall_audio * self.impulse * 0.5) * dt
        ) % 2.0
        tri = (
            self.cycle_pos
            if self.cycle_pos <= 1.0
            else 2.0 - self.cycle_pos
        )
        wall_rgb = self.get_gradient_color_vectorized1d(
            np.array([tri], dtype=np.float32)
        ).astype(np.float32)[0]
        if game.level_flash > 0.0 and int(game.level_flash * 8.0) % 2 == 0:
            wall_rgb = np.full(3, 255.0, dtype=np.float32)
        buf.reshape(-1, 3)[self.wall_flat_idx] = (
            wall_rgb * (self.wall_brightness * maze_fade)
        )

        # dots: one faint pixel each, on the lattice
        if game.dots:
            idxs = np.fromiter(
                (self.dot_px[c] for c in game.dots if c in self.dot_px),
                dtype=np.int64,
            )
            if idxs.size:
                buf.reshape(-1, 3)[idxs] = (
                    np.array(DOT_RGB, dtype=np.float32)
                    * (self.dot_brightness * maze_fade)
                )
        chomp = self._chomp_phase()
        if game.power and maze_fade > 0.0:
            pulse = (0.55 + 0.45 * (1.0 - chomp)) * maze_fade
            for (x, y) in game.power:
                px, py = self._to_px((x, y))
                self._splat(
                    buf,
                    px,
                    py,
                    np.array(POWER_RGB, dtype=np.float32) * pulse,
                    1.5,
                )

        # moving entities draw into a separate layer that feeds the
        # persistent comet-trail buffer (walls/dots stay crisp)
        ent = np.zeros_like(buf)
        # ghosts
        fright_flash = (
            not game.forced_fright
            and 0.0 < game.fright_timer < FRIGHT_FLASH_S
            and int(game.fright_timer * 10.0) % 2 == 0
        )
        for g in game.ghosts:
            if g["state"] == EYES:
                continue
            if g["state"] == FRIGHT:
                rgb = (255.0, 255.0, 255.0) if fright_flash else FRIGHT_RGB
            elif g["stumble_timer"] > STUMBLE_S - 0.15:
                rgb = (255.0, 255.0, 255.0)  # stumble blink
            else:
                rgb = GHOST_COLORS[g["idx"] % len(GHOST_COLORS)]
            fade = min(g["fade_age"] / FADE_IN_S, 1.0)
            rgb = np.array(rgb, dtype=np.float32) * fade
            size = self.entity_size * 0.9
            px, py = self._to_px(game.pos(g))
            mirror = game.mirror_pos(g)
            if mirror is None:
                px, py = self._smooth_px(("g", g["idx"]), px, py, dt)
            else:
                # mid-wrap: render both sides raw (smoothing would drag)
                self._disp[("g", g["idx"])] = (px, py)
                mx, my = self._to_px(mirror)
                self._splat(ent, mx, my, rgb, size)
            self._splat(ent, px, py, rgb, size)

        # ms pacman: yellow blob with a beat-locked chomp pulse
        pac_rgb = np.array(PAC_RGB, dtype=np.float32) * (
            0.65 + 0.35 * abs(math.sin(math.pi * chomp))
        )
        if game.caught_timer > 0.0:
            # death blink while the game freezes
            if int(game.caught_timer * 6.0) % 2 == 0:
                pac_rgb = np.full(3, 255.0, dtype=np.float32)
            else:
                pac_rgb *= 0.25
        px, py = self._to_px(game.pos(game.pac))
        mirror = game.mirror_pos(game.pac)
        if mirror is None:
            px, py = self._smooth_px("pac", px, py, dt)
        else:
            self._disp["pac"] = (px, py)
            mx, my = self._to_px(mirror)
            self._splat(ent, mx, my, pac_rgb, self.entity_size)
        self._splat(ent, px, py, pac_rgb, self.entity_size)

        # ghost-eaten white pops
        for pos, age in game.eat_flashes:
            fx, fy = self._to_px(pos)
            gain = 1.0 - age / EAT_FLASH_S
            self._splat(
                ent,
                fx,
                fy,
                np.array((255.0, 255.0, 255.0)) * gain,
                self.entity_size * 1.3,
            )

        # phase 2 of a particle handoff: the sibling has adopted the
        # entities — stop drawing them and let their trails decay out
        if not entities_on:
            ent[:] = 0.0

        # decay + max-merge into the comet trail, composite over the maze
        half_life = 0.02 + self.trail_decay * 0.5
        self.trail *= np.float32(0.5 ** (dt / half_life))
        np.maximum(self.trail, np.minimum(ent, 255.0), out=self.trail)
        buf += self.trail

        if role is not None:
            self._draw_wipe(buf, role, wipe_p)

        self.matrix = Image.fromarray(
            np.clip(buf, 0.0, 255.0).astype(np.uint8), "RGB"
        )
