#!/usr/bin/env python3
"""ENERGY PARITY — the Energy plan's D5 (https://claude.ai/artifact/
2Dy1SnUgNQ2fJQomhk4dkh; spectra/services/energy.py is the binding statement
for Energy itself).

The five room gates below were set against the OLD top-bar number (librosa's
raw section loudness, no Mark). Energy is song-normalized and carries the
Mark math (x 0.8 x the song's scale, an unmarked song capped at 0.75), so the
same numbers would now pass far fewer moments: on an unmarked song the
Shockwave's 0.7 needs a section at 0.875 x 1/scale of the song's range.
This script finds, for each gate, the Energy value that passes THE SAME SHARE
of moments on his library as the gate passes today, and prints the
before/after list. Nothing is written unless he says so (--apply).

  gate                      moments it is measured over
  drop_shock_min_energy     his library's drops (confident + suggested
                            detections), Energy with the look-ahead
  drop_floor                the same drops (it gates which become drops)
  pulse_flash_min_energy    song time (a flash can come anywhere)
  rainbow_select_limit      song time (a colour roll can come anywhere)
  drop_switch_hit_threshold section boundaries (where an analysed flare sits —
                            a Fireworks meld's "next big hit" is one), the
                            old value the planner's own stretch of the section
                            it was generated from, the new its Energy

THE LIKELIHOOD CURVES (the scene and colour-set selectors' curves, x =
energy) are re-set the same way: every point's x moves to the Energy that
passes the same share of song time as that x did on the STRETCHED scale
(the song's own 0..1 — the number every generated scene change, the bulk of
his scene changes in "analysed" mode, was picked at). Some picks (the
song-start transition, the sequencer's own roll) read the raw number
instead, so a curve is "the same as today" for the generated changes and
close for those. Not touched: the wheel-travel curve (its x is degrees of
colour-wheel travel, not energy) and any profile it shares; the flare
selector's curves and the dwell curves, which were read at the fire value
and move by the headroom change he accepted.

Usage:
  # the list — reads his storage, writes nothing:
  .venv/bin/python scripts/energy_parity.py --storage-root /path/to/SpotFX
  # apply it — backs up first, then writes through SPECTRA's own routes:
  .venv/bin/python scripts/energy_parity.py --storage-root /path/to/SpotFX \\
      --apply --spectra-url http://127.0.0.1:8010
  # put back exactly what was there before an apply:
  .venv/bin/python scripts/energy_parity.py --restore <backup dir> \\
      --spectra-url http://127.0.0.1:8010
--storage-root and --spectra-url have no default. --apply writes only through
the running SPECTRA (PUT /api/room-controls, a partial update of the five
gates; PUT /api/sequencer/curves and /config), never to a file — and BEFORE
it writes anything it saves a backup: what those three routes answered
(snapshot.json, what --restore puts back) and copies of the two files they
store in (storage/spectra/room_controls.json and sequencer.json), in
<storage-root>/storage/backups/energy-parity-<time>/ (or --backup-dir).
Re-detection of drops follows from the floor's own change.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

GATES = (
    ("drop_shock_min_energy", "drops"),
    ("drop_floor", "drops"),
    ("pulse_flash_min_energy", "time"),
    ("rainbow_select_limit", "time"),
    ("drop_switch_hit_threshold", "edges"),
)


# ── pure ──────────────────────────────────────────────────────────────────

def share_at_or_above(values: Sequence[float], weights: Sequence[float], t: float) -> float:
    total = sum(weights)
    if total <= 0:
        return 0.0
    return sum(w for v, w in zip(values, weights) if v >= t - 1e-9) / total


def matching_threshold(values: Sequence[float], weights: Sequence[float], share: float) -> float:
    """The value t on `values` whose share at or above t is closest to
    `share` (ties: the higher t, the stricter). share 0 -> 1.0 (nothing
    passes), share 1 -> 0.0 (everything passes)."""
    if share <= 0 or not values:
        return 1.0
    if share >= 1:
        return 0.0
    cands = sorted(set(round(v, 4) for v in values), reverse=True)
    best, best_err = cands[0], None
    for t in cands:
        err = abs(share_at_or_above(values, weights, t) - share)
        if best_err is None or err < best_err - 1e-12:
            best, best_err = t, err
    return round(best, 2)


@dataclass
class Gate:
    key: str
    over: str
    today: float
    share: float
    new: float
    moments: int


def parity(old: dict, new: dict, today: dict) -> list[Gate]:
    """old/new: {"drops": (values, weights), "time": (values, weights)} on
    the two scales at the same moments; today: the room's current values."""
    out = []
    for key, over in GATES:
        ov, ow = old[over]
        nv, nw = new[over]
        cur = float(today.get(key, 0.0))
        share = share_at_or_above(ov, ow, cur)
        out.append(Gate(key=key, over=over, today=cur, share=round(share, 4),
                        new=matching_threshold(nv, nw, share), moments=len(ov)))
    return out


GRID = tuple(round(i * 0.05, 2) for i in range(21))


def curve_mapping(old: tuple, new: tuple, xs=GRID) -> list:
    """[(old x, Energy x)] passing the same share of song time, monotone,
    0 -> 0 (an x of 0 passes everything on either scale)."""
    ov, ow = old
    nv, nw = new
    out, top = [], 0.0
    for x in xs:
        y = 0.0 if x <= 0 else matching_threshold(nv, nw, share_at_or_above(ov, ow, x))
        top = max(top, y)
        out.append((x, top))
    return out


def remap_x(x: float, mapping: list) -> float:
    """An old x on the mapping, linearly between its grid points."""
    x = max(0.0, min(1.0, float(x)))
    for (x0, y0), (x1, y1) in zip(mapping, mapping[1:]):
        if x0 <= x <= x1:
            f = 0.0 if x1 == x0 else (x - x0) / (x1 - x0)
            return round(y0 + f * (y1 - y0), 4)
    return mapping[-1][1]


def remap_points(points: list, mapping: list) -> list:
    return [{**pt, "x": remap_x(pt["x"], mapping)} for pt in points]


def remap_sequencer(config: dict, curves: dict, mapping: list) -> tuple[dict, dict, list]:
    """(config, curves, notes) with every scene and colour-set curve re-set.
    Profiles shared with the wheel-travel curve or a flare entry are left
    alone and named."""
    used_by_selectors = set()
    for group in ("entries", "color_set_entries"):
        for e in (config.get(group) or {}).values():
            if e.get("curve_ref"):
                used_by_selectors.add(e["curve_ref"])
    hands_off = {config.get("wheel_travel_curve")} | {
        e.get("curve_ref") for e in (config.get("flare_entries") or {}).values()}
    notes, new_curves = [], dict(curves)
    for pid in sorted(used_by_selectors):
        if pid in hands_off:
            notes.append(f"profile {pid!r} is shared with the wheel travel or a flare entry: left as it is")
            continue
        prof = dict(curves[pid])
        prof["points"] = remap_points(prof.get("points") or [], mapping)
        new_curves[pid] = prof
    new_config = json.loads(json.dumps(config))
    for group in ("entries", "color_set_entries"):
        for e in (new_config.get(group) or {}).values():
            if e.get("inline_points"):
                e["inline_points"] = remap_points(e["inline_points"], mapping)
    return new_config, new_curves, notes


# ── reading his library (read-only) ───────────────────────────────────────

def _point_config(root: Path) -> None:
    """Read his storage; never write it. The automatic scale's feature cache
    writes itself when a song is missing from it, so it is read from a
    temporary copy and any write lands there."""
    import shutil
    import tempfile
    from spectra import config
    storage = root / "storage"
    config.AUDIO_SHAPES_DIR = storage / "audio_shapes"
    spectra_dir = storage / "spectra"
    for name in ("ROOM_CONTROLS_FILE", "DROP_SEQUENCES_FILE", "INTENSITY_SCALE_MARKS_FILE"):
        setattr(config, name, spectra_dir / getattr(config, name).name)
    scratch = Path(tempfile.mkdtemp(prefix="energy-parity-"))
    features = spectra_dir / config.INTENSITY_SCALE_CACHE_FILE.name
    if features.exists():
        shutil.copy2(features, scratch / features.name)
    config.INTENSITY_SCALE_CACHE_FILE = scratch / features.name


OLD_FLOOR = 0.05
EDGE_TRIM_MS = 15_000


def old_stretch(sections: list) -> list:
    """The planner's stretch before Energy (midsong_generator's
    _normalized_intensities on origin/master at 6ea5b2bc): per-song min-max
    over the middle sections with a 0.05 floor, the first/last 15 s clamped,
    a flat song 0.5 — the number an analysed flare carried and the meld's
    big-hit threshold was compared with."""
    raw = []
    for sec in sections:
        try:
            raw.append(max(0.0, min(1.0, float(sec.get("energy_rms", 0.0)))))
        except (TypeError, ValueError):
            raw.append(0.0)
    if not raw:
        return []
    end = max((int(sec.get("end_ms", 0)) for sec in sections), default=0)
    edge = [int(sec.get("start_ms", 0)) < EDGE_TRIM_MS
            or int(sec.get("end_ms", 0)) > end - EDGE_TRIM_MS for sec in sections]
    middle = [v for v, e in zip(raw, edge) if not e]
    if not middle:
        middle, edge = raw, [False] * len(raw)
    lo, hi = min(middle), max(middle)
    if hi - lo <= 1e-9:
        return [0.5] * len(raw)
    out = []
    for v, e in zip(raw, edge):
        s = (v - lo) / (hi - lo)
        out.append(max(0.0, min(1.0, s)) if e else OLD_FLOOR + s * (1.0 - OLD_FLOOR))
    return out


def collect(root: Path) -> tuple[dict, dict, dict, int]:
    """(old, new, today, songs) over his library."""
    import numpy as np
    _point_config(root)
    from spectra.services import energy, intensity_scale, intensity_scale_marks, room_controls
    controls = room_controls.load_room_controls()
    look = int(round(float(controls.energy_lookahead_s) * 1000))
    shapes = root / "storage" / "audio_shapes"
    drops_doc = {}
    try:
        drops_doc = json.loads((root / "storage" / "spectra" / "drop_sequences.json").read_text())
    except Exception:
        drops_doc = {}
    old = {"drops": ([], []), "time": ([], []), "stretched": ([], []), "edges": ([], [])}
    new = {"drops": ([], []), "time": ([], []), "edges": ([], [])}
    songs = 0
    for lj in sorted(shapes.glob("*.librosa.json")):
        stem = lj.name[: -len(".librosa.json")]
        try:
            sidecar = json.loads((shapes / f"{stem}.json").read_text())
            uri = sidecar.get("spotify_uri")
            sections = json.loads(lj.read_text()).get("sections") or []
        except Exception:
            continue
        if not uri or not sections:
            continue
        try:
            offset = int(np.load(shapes / f"{stem}.npz")["timestamps_ms"][0])
        except Exception:
            offset = 0
        mark = intensity_scale_marks.get_mark(uri)
        if mark is not None:
            factor, marked = float(mark), True
        else:
            try:
                factor, marked = float(intensity_scale.auto_scaling_factor(uri, [])), False
            except Exception:
                factor, marked = 1.0, False
        tl = energy.build_timeline(uri, sections, offset, factor, marked)
        songs += 1
        for s in tl.sections:
            w = max(0, s.end_ms - s.start_ms)
            old["time"][0].append(s.raw); old["time"][1].append(w)
            old["stretched"][0].append(s.normalized); old["stretched"][1].append(w)
            new["time"][0].append(s.energy); new["time"][1].append(w)
        for s, before in list(zip(tl.sections, old_stretch(sections)))[1:]:
            old["edges"][0].append(before); old["edges"][1].append(1.0)
            new["edges"][0].append(s.energy); new["edges"][1].append(1.0)
        for seq in ((drops_doc.get(uri) or {}).get("detected") or {}).get("sequences") or []:
            if seq.get("tier") not in ("confident", "suggested"):
                continue
            ms = int(seq.get("drop_ms") or 0)
            raw = tl.sections[tl._index(ms)].raw
            old["drops"][0].append(raw); old["drops"][1].append(1.0)
            new["drops"][0].append(tl.at(ms, look)); new["drops"][1].append(1.0)
    today = {key: getattr(controls, key) for key, _ in GATES}
    return old, new, today, songs


def _call(url: str, method: str = "GET", body=None):
    req = urllib.request.Request(url, method=method,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read() or b"null")


STORED_FILES = ("room_controls.json", "sequencer.json")


def backup(spectra_url: str, storage_root: Optional[Path], backup_dir: Path) -> dict:
    """Before anything is written: what the three routes answer now (the
    restore source) and copies of the two files they store in."""
    import shutil
    import time
    base = spectra_url.rstrip("/")
    snapshot = {"taken_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "spectra_url": base,
                "room_controls": _call(base + "/api/room-controls"),
                "sequencer_config": _call(base + "/api/sequencer/config"),
                "sequencer_curves": _call(base + "/api/sequencer/curves")}
    backup_dir.mkdir(parents=True, exist_ok=False)
    (backup_dir / "snapshot.json").write_text(json.dumps(snapshot, indent=2))
    copied = []
    if storage_root is not None:
        for name in STORED_FILES:
            src = storage_root / "storage" / "spectra" / name
            if src.exists():
                shutil.copy2(src, backup_dir / name)
                copied.append(name)
    return {"dir": str(backup_dir), "files": copied}


def restore(spectra_url: str, backup_dir: Path) -> dict:
    """Put back exactly what the backup's snapshot recorded: the five gates
    (a partial update — nothing else moves) and the sequencer's curves and
    config, through the same routes the apply used."""
    snap = json.loads((backup_dir / "snapshot.json").read_text())
    base = spectra_url.rstrip("/")
    gates = {key: snap["room_controls"][key] for key, _ in GATES if key in snap["room_controls"]}
    _call(base + "/api/room-controls", "PUT", gates)
    _call(base + "/api/sequencer/curves", "PUT", snap["sequencer_curves"])
    _call(base + "/api/sequencer/config", "PUT", snap["sequencer_config"])
    return {"room_controls": gates, "curves": len(snap["sequencer_curves"]),
            "from": str(backup_dir)}


def apply(spectra_url: str, gates: list[Gate], mapping: list) -> dict:
    """Write through SPECTRA's own routes: the gates (a partial room-controls
    update) and the re-set curves (the sequencer's curves and config). The
    caller has backed up first (main)."""
    base = spectra_url.rstrip("/")
    body = {g.key: g.new for g in gates if abs(g.new - g.today) > 1e-9}
    if body:
        _call(base + "/api/room-controls", "PUT", body)
    config = _call(base + "/api/sequencer/config")
    curves = _call(base + "/api/sequencer/curves")
    new_config, new_curves, notes = remap_sequencer(config, curves, mapping)
    if new_curves != curves:
        _call(base + "/api/sequencer/curves", "PUT", new_curves)
    if new_config != config:
        _call(base + "/api/sequencer/config", "PUT", new_config)
    return {"room_controls": body, "curves_changed": new_curves != curves,
            "config_changed": new_config != config, "notes": notes}


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--storage-root", type=Path)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--restore", type=Path, metavar="BACKUP_DIR")
    ap.add_argument("--backup-dir", type=Path)
    ap.add_argument("--spectra-url")
    args = ap.parse_args(argv)
    if (args.apply or args.restore) and not args.spectra_url:
        ap.error("--apply and --restore need --spectra-url (no default target)")
    if args.restore:
        print(f"restored: {restore(args.spectra_url, args.restore)}")
        return 0
    if args.storage_root is None:
        ap.error("--storage-root is required (no default)")
    old, new, today, songs = collect(args.storage_root)
    gates = parity(old, new, today)
    print(f"Energy parity over {songs} analysed songs ({len(old['drops'][0])} drops).")
    print("The automatic scale here uses no genre (Spotify names a song's genres only "
          "while it plays), so a genre-matched song's live Energy runs a little higher.\n")
    print(f"  {'gate':26} {'today':>6}  {'passes':>7}  {'Energy':>6}")
    for g in gates:
        print(f"  {g.key:26} {g.today:6.2f}  {g.share:7.1%}  {g.new:6.2f}   ({g.over})")
    mapping = curve_mapping(old["stretched"], new["time"])
    print("\nLikelihood curves (scene and colour set): every point's x moves "
          "from the stretched scale to Energy")
    print("  " + "  ".join(f"{x:.1f}->{y:.2f}" for x, y in mapping[::2]))
    if args.apply:
        import time
        target = args.backup_dir or (args.storage_root / "storage" / "backups"
                                     / f"energy-parity-{time.strftime('%Y%m%d-%H%M%S')}")
        saved = backup(args.spectra_url, args.storage_root, target)
        print(f"\nbacked up first: {saved}")
        written = apply(args.spectra_url, gates, mapping)
        (target / "applied.json").write_text(json.dumps(written, indent=2))
        print(f"applied: {written}")
        print(f"to put it back: --restore {target} --spectra-url {args.spectra_url}")
    else:
        print("\ndry run: nothing written. Re-run with --apply --spectra-url URL on his word.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
