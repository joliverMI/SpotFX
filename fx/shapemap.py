"""Shape maps — text-defined geometry for shaped LED matrices.

A shape map describes which cells of a virtual's W×H render grid are real
LEDs, and in what order the device strip visits them. It compiles into
(a) the virtual's gap/LED segment list, (b) a live-cell mask + per-LED
positions, and (c) resample gather tables (see Virtual._flush_shape_resample).

Pure module: no ledfx imports, numpy only (scipy optional). Safe to import
from external tooling (SpotFX's bootstrap script does).

FORMAT (v1) — line oriented; '#' starts a comment; blank lines ignored:

    shape v1                      # required header
    grid 72 x 37                  # render grid, W x H
    device crystal                # the physical output device id
    gap gap-crystal-mapper        # dummy device id used for dead cells
    parity odd                    # live iff (col+row)%2==1 ('even': ==0;
                                  # 'none': every col in extent is live)
    row 0: 17-51 holes 21,23      # live cells of row 0: parity-matching
                                  # cols in [17,51] minus the holes
    rows 5-7: 12-58               # same extent for a row range
    cell +10,3                    # escape hatch: force one cell live
    cell -10,5                    # ...or dead (applied after row defs)
    order:                        # strip order; directives consume device
                                  # indices 0..N-1 in sequence
      explicit 1,16 0,17 1,18     # exact r,c walk (irregular sections)
      serpentine rows 2-34 first desc   # complete rows, alternating
                                        # direction, row 2 descending

If no `order:` block is given, the default is serpentine over all rows,
row 0 ascending. The compiler validates that every live cell is consumed
exactly once and reports ALL errors with line numbers.

Authoring guidance (for humans and LLMs): prefer `parity` + `row` extents
for the regular body; use `holes` for missing LEDs inside an extent; use
`explicit` order lines only where the physical strip path is irregular
(e.g. interleaved pole caps). Positions are cell centers — pick the grid
so LED spacing is roughly uniform in grid units.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import numpy as np

__all__ = [
    "ShapeMapError",
    "CompiledShape",
    "parse",
    "decode_segments",
    "build_gather",
]


class ShapeMapError(Exception):
    """Raised on parse/compile failure. `errors` is a list of (line, msg)
    covering every problem found, not just the first."""

    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__("; ".join(f"line {ln}: {msg}" for ln, msg in self.errors))


@dataclass
class CompiledShape:
    width: int
    height: int
    device_id: str
    gap_id: str
    mask: np.ndarray                  # (H, W) bool — live cells
    led_rc: np.ndarray                # (N, 2) int32 (row, col), device order
    positions: np.ndarray             # (N, 2) float32 (x, y) cell centers
    segments: list                    # [[dev, a, b, False, 0], ...]
    text: str                         # the source text
    digest: str = ""
    parity: str = "none"              # detected/declared, for round-trips
    extents: list = field(default_factory=list)   # per-row (lo, hi) or None

    @property
    def n_leds(self) -> int:
        return len(self.led_rc)


# ── parsing ──────────────────────────────────────────────────────────────────

def _parity_ok(c: int, r: int, parity: str) -> bool:
    if parity == "odd":
        return (c + r) % 2 == 1
    if parity == "even":
        return (c + r) % 2 == 0
    return True


def parse(text: str) -> CompiledShape:
    """Compile a shape-map text into a CompiledShape. Raises ShapeMapError
    with every problem found (line-numbered)."""
    errors: list[tuple[int, str]] = []
    width = height = None
    device_id = gap_id = None
    parity = "none"
    rowdefs: dict[int, tuple[int, int, set]] = {}   # r -> (lo, hi, holes)
    cell_add: list[tuple[int, int, int]] = []       # (line, r, c)
    cell_del: list[tuple[int, int, int]] = []
    order_dirs: list[tuple[int, str, object]] = []  # (line, kind, payload)
    in_order = False
    saw_header = False

    def _int(tok, ln, what):
        try:
            return int(tok)
        except ValueError:
            errors.append((ln, f"bad integer for {what}: {tok!r}"))
            return None

    for ln, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        low = line.lower()
        if not saw_header:
            if low.replace(" ", "") == "shapev1":
                saw_header = True
                continue
            errors.append((ln, "file must start with 'shape v1'"))
            saw_header = True  # keep parsing for more errors
            # fall through to parse this line normally
        if low.startswith("grid"):
            in_order = False
            parts = low[4:].replace("x", " ").split()
            if len(parts) != 2:
                errors.append((ln, "grid must be 'grid W x H'"))
                continue
            width, height = _int(parts[0], ln, "grid W"), _int(parts[1], ln, "grid H")
            continue
        if low.startswith("device "):
            in_order = False
            device_id = line.split(None, 1)[1].strip()
            continue
        if low.startswith("gap "):
            in_order = False
            gap_id = line.split(None, 1)[1].strip()
            continue
        if low.startswith("parity"):
            in_order = False
            val = low.split(None, 1)[1].strip() if len(low.split(None, 1)) > 1 else ""
            if val not in ("odd", "even", "none"):
                errors.append((ln, "parity must be odd | even | none"))
            else:
                parity = val
            continue
        if low.startswith("row ") or low.startswith("rows "):
            in_order = False
            head, _, rest = line.partition(":")
            if not rest:
                errors.append((ln, "row def needs ':' then 'LO-HI [holes ...]'"))
                continue
            rtok = head.split(None, 1)[1].strip()
            if "-" in rtok:
                a, _, b = rtok.partition("-")
                r0, r1 = _int(a, ln, "row range"), _int(b, ln, "row range")
            else:
                r0 = r1 = _int(rtok, ln, "row")
            body = rest.strip().split()
            if not body or "-" not in body[0]:
                errors.append((ln, "row def needs an extent 'LO-HI'"))
                continue
            lo_s, _, hi_s = body[0].partition("-")
            lo, hi = _int(lo_s, ln, "extent lo"), _int(hi_s, ln, "extent hi")
            holes: set[int] = set()
            if len(body) > 1:
                if body[1].lower() != "holes" or len(body) < 3:
                    errors.append((ln, "expected 'holes a,b,...' after extent"))
                else:
                    for tok in " ".join(body[2:]).replace(",", " ").split():
                        h = _int(tok, ln, "hole col")
                        if h is not None:
                            holes.add(h)
            if None in (r0, r1, lo, hi):
                continue
            if r1 < r0:
                errors.append((ln, f"row range {r0}-{r1} is backwards"))
                continue
            for r in range(r0, r1 + 1):
                if r in rowdefs:
                    errors.append((ln, f"row {r} defined twice"))
                rowdefs[r] = (lo, hi, set(holes))
            continue
        if low.startswith("cell "):
            in_order = False
            body = line[5:].strip()
            sign = body[:1]
            if sign not in "+-":
                errors.append((ln, "cell needs '+R,C' or '-R,C'"))
                continue
            toks = body[1:].replace(",", " ").split()
            if len(toks) != 2:
                errors.append((ln, "cell needs exactly R,C"))
                continue
            r, c = _int(toks[0], ln, "cell row"), _int(toks[1], ln, "cell col")
            if r is None or c is None:
                continue
            (cell_add if sign == "+" else cell_del).append((ln, r, c))
            continue
        if low.startswith("order"):
            in_order = True
            continue
        if in_order:
            if low.startswith("serpentine"):
                toks = low.split()
                # serpentine rows A-B [first asc|desc]
                try:
                    assert toks[1] == "rows"
                    a, _, b = toks[2].partition("-")
                    r0, r1 = int(a), int(b)
                    first = "asc"
                    if len(toks) >= 5 and toks[3] == "first":
                        first = toks[4]
                    assert first in ("asc", "desc")
                except (AssertionError, IndexError, ValueError):
                    errors.append((ln, "serpentine syntax: 'serpentine rows A-B [first asc|desc]'"))
                    continue
                order_dirs.append((ln, "serpentine", (r0, r1, first)))
            elif low.startswith("explicit"):
                cells = []
                ok = True
                for tok in line.split(None, 1)[1].split():
                    rc = tok.split(",")
                    if len(rc) != 2:
                        errors.append((ln, f"explicit cell {tok!r} must be R,C"))
                        ok = False
                        break
                    r, c = _int(rc[0], ln, "explicit row"), _int(rc[1], ln, "explicit col")
                    if r is None or c is None:
                        ok = False
                        break
                    cells.append((r, c))
                if ok:
                    order_dirs.append((ln, "explicit", cells))
            else:
                errors.append((ln, f"unknown order directive: {line!r}"))
            continue
        errors.append((ln, f"unknown statement: {line!r}"))

    if width is None or height is None:
        errors.append((0, "missing 'grid W x H'"))
    if not device_id:
        errors.append((0, "missing 'device <id>'"))
    if not gap_id:
        errors.append((0, "missing 'gap <id>'"))
    if errors:
        raise ShapeMapError(errors)

    # ── build the live-cell set ──
    mask = np.zeros((height, width), dtype=bool)
    for r, (lo, hi, holes) in rowdefs.items():
        if not (0 <= r < height):
            errors.append((0, f"row {r} outside grid height {height}"))
            continue
        if not (0 <= lo <= hi < width):
            errors.append((0, f"row {r} extent {lo}-{hi} outside grid width {width}"))
            continue
        for c in range(lo, hi + 1):
            if _parity_ok(c, r, parity) and c not in holes:
                mask[r, c] = True
        for h in holes:
            if not (lo <= h <= hi):
                errors.append((0, f"row {r} hole {h} outside extent {lo}-{hi}"))
            elif not _parity_ok(h, r, parity):
                errors.append((0, f"row {r} hole {h} is not a {parity}-parity column"))
    for ln, r, c in cell_add:
        if 0 <= r < height and 0 <= c < width:
            mask[r, c] = True
        else:
            errors.append((ln, f"cell +{r},{c} outside grid"))
    for ln, r, c in cell_del:
        if 0 <= r < height and 0 <= c < width:
            mask[r, c] = False
        else:
            errors.append((ln, f"cell -{r},{c} outside grid"))
    if errors:
        raise ShapeMapError(errors)
    if not mask.any():
        raise ShapeMapError([(0, "shape has no live cells")])

    # ── resolve strip order ──
    if not order_dirs:
        order_dirs = [(0, "serpentine", (0, height - 1, "asc"))]
    led_rc: list[tuple[int, int]] = []
    consumed = np.zeros_like(mask)
    for ln, kind, payload in order_dirs:
        if kind == "serpentine":
            r0, r1, first = payload
            direction = first
            for r in range(r0, r1 + 1):
                if not (0 <= r < height):
                    errors.append((ln, f"serpentine row {r} outside grid"))
                    continue
                cols = np.flatnonzero(mask[r] & ~consumed[r])
                if cols.size == 0:
                    continue  # empty rows are fine inside a range
                if direction == "desc":
                    cols = cols[::-1]
                for c in cols:
                    led_rc.append((r, int(c)))
                    consumed[r, c] = True
                direction = "asc" if direction == "desc" else "desc"
        else:  # explicit
            for r, c in payload:
                if not (0 <= r < height and 0 <= c < width) or not mask[r, c]:
                    errors.append((ln, f"explicit cell {r},{c} is not a live cell"))
                elif consumed[r, c]:
                    errors.append((ln, f"explicit cell {r},{c} consumed twice"))
                else:
                    led_rc.append((r, c))
                    consumed[r, c] = True
    missing = int(mask.sum() - consumed.sum())
    if missing:
        rs, cs = np.nonzero(mask & ~consumed)
        sample = ", ".join(f"{r},{c}" for r, c in list(zip(rs, cs))[:6])
        errors.append((0, f"{missing} live cell(s) not consumed by order (e.g. {sample})"))
    if errors:
        raise ShapeMapError(errors)

    led_rc_arr = np.array(led_rc, dtype=np.int32)
    positions = np.stack(
        [led_rc_arr[:, 1] + 0.5, led_rc_arr[:, 0] + 0.5], axis=1
    ).astype(np.float32)
    extents = [
        (int(np.flatnonzero(mask[r]).min()), int(np.flatnonzero(mask[r]).max()))
        if mask[r].any() else None
        for r in range(height)
    ]
    shape = CompiledShape(
        width=width, height=height, device_id=device_id, gap_id=gap_id,
        mask=mask, led_rc=led_rc_arr, positions=positions,
        segments=_emit_segments(mask, led_rc_arr, width, device_id, gap_id),
        text=text, digest=hashlib.sha1(text.encode()).hexdigest()[:12],
        parity=parity, extents=extents,
    )
    return shape


def _emit_segments(mask, led_rc, width, device_id, gap_id) -> list:
    """Canonical segment emission: walk the grid row-major; dead runs merge
    into gap segments whose device indices ARE the virtual offsets; each live
    cell emits a single-pixel device segment carrying its strip index.
    Deterministic, so re-applying an identical map is a no-op."""
    height = mask.shape[0]
    dev_idx = {}
    for i, (r, c) in enumerate(led_rc):
        dev_idx[(int(r), int(c))] = i
    segments = []
    gap_start = None
    v = 0
    for r in range(height):
        for c in range(width):
            if mask[r, c]:
                if gap_start is not None:
                    segments.append([gap_id, gap_start, v - 1, False, 0])
                    gap_start = None
                i = dev_idx[(r, c)]
                segments.append([device_id, i, i, False, 0])
            else:
                if gap_start is None:
                    gap_start = v
            v += 1
    if gap_start is not None:
        segments.append([gap_id, gap_start, v - 1, False, 0])
    return segments


# ── decoding an existing segment list (bootstrap) ────────────────────────────

def decode_segments(
    segments, width: int, height: int, device_id: str | None = None,
    gap_id: str | None = None,
) -> CompiledShape:
    """Inverse of parse().segments: reconstruct a shape (and canonical text)
    from a virtual's existing gap/LED segment list. Detects parity, per-row
    extents + holes, and serpentine order ranges; anything irregular becomes
    explicit order lines. Raises ShapeMapError on unsupported shapes
    (multi-device, inverted segments)."""
    errors = []
    dev_ids = {s[0] for s in segments}
    gaps = {d for d in dev_ids if d.startswith("gap-")}
    devs = dev_ids - gaps
    if device_id is None:
        if len(devs) != 1:
            raise ShapeMapError([(0, f"expected exactly one non-gap device, got {sorted(devs)}")])
        device_id = next(iter(devs))
    if gap_id is None:
        gap_id = next(iter(gaps)) if gaps else f"gap-{device_id}"

    mask = np.zeros((height, width), dtype=bool)
    v2dev: dict[int, int] = {}
    v = 0
    for seg in segments:
        did, a, b, invert = seg[0], seg[1], seg[2], seg[3] if len(seg) > 3 else False
        n = b - a + 1
        if did == device_id:
            if invert:
                raise ShapeMapError([(0, "inverted device segments are not supported by shape maps")])
            for k in range(n):
                r, c = divmod(v + k, width)
                if r >= height:
                    raise ShapeMapError([(0, "segments exceed grid size")])
                mask[r, c] = True
                v2dev[v + k] = a + k
        v += n
    if v != width * height:
        errors.append((0, f"segments cover {v} px, grid is {width * height}"))
    n_leds = len(v2dev)
    if n_leds == 0:
        errors.append((0, "no live cells found"))
    dev_seen = sorted(v2dev.values())
    if dev_seen != list(range(n_leds)):
        errors.append((0, "device indices are not a dense 0..N-1 range"))
    if errors:
        raise ShapeMapError(errors)

    led_rc = np.zeros((n_leds, 2), dtype=np.int32)
    for vpos, i in v2dev.items():
        led_rc[i] = divmod(vpos, width)

    # parity detection
    rc = led_rc
    par = (rc[:, 0] + rc[:, 1]) % 2
    if np.all(par == 1):
        parity = "odd"
    elif np.all(par == 0):
        parity = "even"
    else:
        parity = "none"

    text = _encode(mask, led_rc, width, height, device_id, gap_id, parity)
    shape = parse(text)
    return shape


def _encode(mask, led_rc, width, height, device_id, gap_id, parity) -> str:
    """Canonical text for a decoded shape."""
    lines = [
        "shape v1",
        f"grid {width} x {height}",
        f"device {device_id}",
        f"gap {gap_id}",
        f"parity {parity}",
    ]
    # row extents + holes (grouping identical consecutive defs into `rows A-B`)
    rowspecs = []
    for r in range(height):
        cols = np.flatnonzero(mask[r])
        if cols.size == 0:
            rowspecs.append(None)
            continue
        lo, hi = int(cols.min()), int(cols.max())
        expect = [c for c in range(lo, hi + 1) if _parity_ok(c, r, parity)]
        holes = sorted(set(expect) - set(cols.tolist()))
        rowspecs.append((lo, hi, tuple(holes)))
    r = 0
    while r < height:
        spec = rowspecs[r]
        if spec is None:
            r += 1
            continue
        r2 = r
        while r2 + 1 < height and rowspecs[r2 + 1] == spec:
            r2 += 1
        lo, hi, holes = spec
        hole_s = f" holes {','.join(map(str, holes))}" if holes else ""
        if r2 > r:
            lines.append(f"rows {r}-{r2}: {lo}-{hi}{hole_s}")
        else:
            lines.append(f"row {r}: {lo}-{hi}{hole_s}")
        r = r2 + 1

    # order: detect maximal serpentine runs of complete rows
    lines.append("order:")
    n = len(led_rc)
    row_cells = {
        r: np.flatnonzero(mask[r]).tolist() for r in range(height) if mask[r].any()
    }
    i = 0
    pending_explicit: list[str] = []

    def flush_explicit():
        if pending_explicit:
            lines.append("  explicit " + " ".join(pending_explicit))
            pending_explicit.clear()

    while i < n:
        r0 = int(led_rc[i, 0])
        cells = row_cells.get(r0)
        run_len = 0
        direction0 = None
        if cells and i + len(cells) <= n:
            chunk = led_rc[i:i + len(cells)]
            if np.all(chunk[:, 0] == r0):
                got = chunk[:, 1].tolist()
                if got == cells:
                    direction0 = "asc"
                elif got == cells[::-1]:
                    direction0 = "desc"
        if direction0 is not None:
            # extend over consecutive complete rows with alternating direction
            j = i
            r = r0
            direction = direction0
            while j < n:
                cells_r = row_cells.get(r)
                if not cells_r or j + len(cells_r) > n:
                    break
                chunk = led_rc[j:j + len(cells_r)]
                if not np.all(chunk[:, 0] == r):
                    break
                got = chunk[:, 1].tolist()
                want = cells_r if direction == "asc" else cells_r[::-1]
                if got != want:
                    break
                j += len(cells_r)
                run_len += 1
                r += 1
                direction = "asc" if direction == "desc" else "desc"
            if run_len >= 2:
                flush_explicit()
                lines.append(
                    f"  serpentine rows {r0}-{r0 + run_len - 1} first {direction0}"
                )
                i = j
                continue
        pending_explicit.append(f"{int(led_rc[i, 0])},{int(led_rc[i, 1])}")
        if len(pending_explicit) >= 30:
            flush_explicit()
        i += 1
    flush_explicit()
    return "\n".join(lines) + "\n"


# ── gather tables ────────────────────────────────────────────────────────────

def build_gather(shape: CompiledShape, k_max: int = 8, r_max: float = 2.0) -> dict:
    """Resample tables: per LED, the render cells of its discrete-Voronoi
    catchment (cells whose center is nearest to that LED, within r_max grid
    units), padded/truncated to K columns.

    Returns {idx (N,K) int32 flat frame indices, w (N,K) f32 rows sum to 1,
    live (N,K) bool, idx1 (N,) int32 own-cell, k int, truncated int}.
    The LED's own cell is always member 0, so identity sampling is the
    special case idx[:, 0]."""
    H, W = shape.mask.shape
    pos = shape.positions  # (N,2) x,y
    n = len(pos)
    cy, cx = np.mgrid[0:H, 0:W]
    centers = np.stack([cx.ravel() + 0.5, cy.ravel() + 0.5], axis=1).astype(np.float32)

    try:
        from scipy.spatial import cKDTree
        dist, owner = cKDTree(pos).query(centers, k=1)
        dist = np.asarray(dist, dtype=np.float32)
        owner = np.asarray(owner, dtype=np.int64)
    except ImportError:
        # chunked brute force (H*W × N) — one-time cost, fine for these sizes
        owner = np.empty(H * W, dtype=np.int64)
        dist = np.empty(H * W, dtype=np.float32)
        step = 4096
        for s in range(0, H * W, step):
            d = np.linalg.norm(
                centers[s:s + step, None, :] - pos[None, :, :], axis=2
            )
            owner[s:s + step] = d.argmin(axis=1)
            dist[s:s + step] = d.min(axis=1)
    owner[dist > r_max] = -1  # orphans: too far from any LED

    members: list[list[int]] = [[] for _ in range(n)]
    flat_own = (shape.led_rc[:, 0].astype(np.int64) * W + shape.led_rc[:, 1])
    for cell, o in enumerate(owner):
        if o >= 0:
            members[o].append(cell)
    truncated = 0
    k_used = 1
    for i in range(n):
        m = members[i]
        own = int(flat_own[i])
        # own cell first (it is always owned by construction: distance 0)
        if own in m:
            m.remove(own)
        else:  # defensive — equidistant tie broken elsewhere
            pass
        if len(m) + 1 > k_max:
            d = np.linalg.norm(
                centers[np.array(m)] - pos[i][None, :], axis=1
            )
            keep = np.argsort(d)[: k_max - 1]
            truncated += len(m) - (k_max - 1)
            m = [m[j] for j in keep]
        members[i] = [own] + m
        k_used = max(k_used, len(members[i]))

    k = min(k_max, max(1, k_used))
    idx = np.empty((n, k), dtype=np.int32)
    w = np.zeros((n, k), dtype=np.float32)
    for i, m in enumerate(members):
        cnt = len(m)
        idx[i, :cnt] = m
        idx[i, cnt:] = m[0]           # pad with own cell (weight 0)
        w[i, :cnt] = 1.0 / cnt        # equal-area cells → uniform = area weight
    return {
        "idx": idx,
        "w": w,
        "live": w > 0.0,
        "idx1": idx[:, 0].copy(),
        "k": k,
        "truncated": truncated,
    }
