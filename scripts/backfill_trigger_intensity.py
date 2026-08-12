#!/usr/bin/env python3
"""
Backfill every song profile's trigger `intensity` from the librosa section
energy at that trigger's timestamp.

Rule
----
A trigger takes the energy of the section it falls in. If it sits within 2
beats *before* a section line, it takes the energy of the section on the far
side of that line instead — a build placed just ahead of the drop should fire
at the drop's energy, not the build's.

Why the raw energy needs renormalizing
--------------------------------------
`librosa_service._detect_sections` normalizes section energy by the loudest
section only (`energy / max_e`) with no floor subtraction, so the quietest
section of a song lands at `min/max` — a median of 0.33 across the library,
never near 0. It also works in linear RMS, and modern masters are heavily
limited (median song-wide dynamic range is only ~9.6 dB), so real loudness
differences compress into a narrow band near the top.

`--curve` picks how those raw values map to intensity:

  minmax     (default) per-song linear min-max stretch. Fixes the missing
             floor: the quietest section becomes 0, the loudest 1. Keeps
             relative magnitude — a section half as loud stays half as far up.
  raw        the stored energy_rms, unchanged (the original behavior).
  rank       per-song percentile rank. Guarantees a uniform spread across the
             full range, but discards magnitude: two nearly-equal sections can
             land far apart. Use when you want maximum visual contrast.
  dbstretch  per-song min-max in dB. Perceptually even, but note this pushes
             values UP relative to `minmax` (linear 0.5 is only -6 dB), so it
             does NOT help if the complaint is "everything reads too high".

`--gamma` post-shapes the curve (intensity ** gamma). >1 pushes values down,
<1 pushes them up. `--floor` lifts the bottom so a trigger never lands at a
dead 0.

Time base
---------
Sections are read raw (no `librosa_offset_ms`), matching what the engine does
at playback: `signal_resolver._section_energy` / `trigger_engine._section_intensity`
both consume `load_sections_for_uri()` output unshifted. The stored offsets are
unreliable anyway — see CLAUDE.md.

Usage
-----
    python3 scripts/backfill_trigger_intensity.py                  # dry run
    python3 scripts/backfill_trigger_intensity.py --apply          # write + backup
    python3 scripts/backfill_trigger_intensity.py --curve rank --apply
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import statistics
import sys
from bisect import bisect_left
from datetime import datetime
from pathlib import Path

STORAGE = Path(__file__).resolve().parent.parent / "storage"
PROFILES_DIR = STORAGE / "profiles"
SHAPES_DIR = STORAGE / "audio_shapes"
BACKUPS_DIR = STORAGE / "backups"

BEATS_BEFORE_LINE = 2       # how close to a section line counts as "on" it
DEFAULT_TEMPO_BPM = 120.0
CURVES = ("minmax", "raw", "rank", "dbstretch")


def load_librosa_by_uri() -> dict[str, dict]:
    """Map spotify_uri -> parsed librosa analysis (sections/beats/tempo only)."""
    out: dict[str, dict] = {}
    for path in SHAPES_DIR.glob("*.librosa.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        uri = data.get("spotify_uri")
        if not uri:
            continue
        sections = data.get("sections") or []
        if not sections:
            continue
        out[uri] = {
            "sections": sorted(sections, key=lambda s: int(s.get("start_ms", 0))),
            "beat_ms": [int(b.get("ms", 0)) for b in (data.get("beats") or [])],
            "tempo_bpm": data.get("tempo_bpm"),
        }
    return out


# ── Section-energy → intensity curves ───────────────────────────────────────

def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def normalized_energies(sections: list[dict], curve: str) -> list[float | None]:
    """Map a song's section energies to intensities in 0-1 under `curve`.

    Returns one value per section, None where energy is missing/unparseable.
    Normalization is per song, so every song is shaped against its own
    quietest and loudest section.
    """
    raw: list[float | None] = []
    for sec in sections:
        try:
            raw.append(_clamp(float(sec.get("energy_rms"))))
        except (TypeError, ValueError):
            raw.append(None)

    good = [v for v in raw if v is not None]
    if not good:
        return raw
    lo, hi = min(good), max(good)

    if curve == "raw":
        return raw

    if curve == "minmax":
        span = hi - lo
        if span <= 0:
            return [None if v is None else 1.0 for v in raw]
        return [None if v is None else _clamp((v - lo) / span) for v in raw]

    if curve == "rank":
        # Percentile position among this song's sections; ties share a rank.
        order = sorted(set(good))
        n = max(len(order) - 1, 1)
        pos = {v: i / n for i, v in enumerate(order)}
        return [None if v is None else pos[v] for v in raw]

    if curve == "dbstretch":
        peak = hi or 1e-9
        db = [None if v is None else 20 * math.log10(max(v, 1e-9) / peak) for v in raw]
        floor_db = min(x for x in db if x is not None)
        span = -floor_db
        if span <= 0:
            return [None if v is None else 1.0 for v in raw]
        return [None if x is None else _clamp((x - floor_db) / span) for x in db]

    raise ValueError(f"unknown curve: {curve}")


def shape(v: float, gamma: float, floor: float) -> float:
    """Apply post-curve gamma and lift the bottom to `floor`."""
    if gamma != 1.0:
        v = v ** gamma
    if floor > 0.0:
        v = floor + v * (1.0 - floor)
    return round(_clamp(v), 4)


# ── Section lookup ──────────────────────────────────────────────────────────

def two_beat_window(la: dict) -> float:
    """Duration of BEATS_BEFORE_LINE beats, in ms."""
    tempo = la.get("tempo_bpm")
    try:
        tempo = float(tempo)
    except (TypeError, ValueError):
        tempo = 0.0
    if not (40.0 <= tempo <= 250.0):
        beats = la["beat_ms"]
        if len(beats) >= 8:
            deltas = [b - a for a, b in zip(beats, beats[1:]) if b > a]
            tempo = 60000.0 / statistics.median(deltas) if deltas else DEFAULT_TEMPO_BPM
        else:
            tempo = DEFAULT_TEMPO_BPM
    return BEATS_BEFORE_LINE * 60000.0 / tempo


def line_threshold(la: dict, boundary_ms: int, window_ms: float) -> float:
    """Timestamp at/after which a trigger counts as sitting on `boundary_ms`.

    Prefers walking back BEATS_BEFORE_LINE actual beats (handles tempo drift);
    falls back to a flat tempo-derived window when beats are unusable.
    """
    beats = la["beat_ms"]
    if len(beats) >= BEATS_BEFORE_LINE + 1:
        i = bisect_left(beats, boundary_ms)
        j = i - BEATS_BEFORE_LINE
        if 0 <= j < len(beats):
            back = boundary_ms - beats[j]
            # Guard against a sparse/garbled beat grid producing a silly window.
            if 0 < back <= window_ms * 3:
                return float(beats[j])
    return boundary_ms - window_ms


def section_index_for(sections: list[dict], ms: int) -> int:
    """Index of the section containing `ms`; nearest section if outside them all.

    Mirrors signal_resolver._section_energy's containment + nearest fallback.
    """
    for i, sec in enumerate(sections):
        if int(sec.get("start_ms", 0)) <= ms < int(sec.get("end_ms", 0)):
            return i
    return min(
        range(len(sections)),
        key=lambda i: min(
            abs(int(sections[i].get("start_ms", 0)) - ms),
            abs(int(sections[i].get("end_ms", 0)) - ms),
        ),
    )


def resolve_section(la: dict, ms: int, window_ms: float) -> tuple[int, bool]:
    """Section index for a trigger, applying the 2-beats-before-the-line bump."""
    sections = la["sections"]
    i = section_index_for(sections, ms)
    if i + 1 < len(sections):
        boundary = int(sections[i].get("end_ms", 0))
        if ms < boundary and ms >= line_threshold(la, boundary, window_ms):
            return i + 1, True
    return i, False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="write changes (default is a dry run)")
    ap.add_argument("--curve", choices=CURVES, default="minmax",
                    help="section-energy -> intensity mapping (default: minmax)")
    ap.add_argument("--gamma", type=float, default=1.0,
                    help="post-curve shaping exponent; >1 pushes values down")
    ap.add_argument("--floor", type=float, default=0.0,
                    help="lift the bottom of the range so nothing lands at 0")
    args = ap.parse_args()

    if not 0.0 <= args.floor < 1.0:
        ap.error("--floor must be in [0, 1)")
    if args.gamma <= 0:
        ap.error("--gamma must be > 0")

    librosa = load_librosa_by_uri()
    print(f"curve={args.curve} gamma={args.gamma} floor={args.floor}")
    print(f"librosa analyses with sections: {len(librosa)}")

    profile_paths = sorted(PROFILES_DIR.glob("*.json"))
    print(f"profiles on disk:               {len(profile_paths)}\n")

    updated_docs: list[tuple[Path, dict]] = []
    n_triggers = n_changed = n_bumped = 0
    n_no_analysis = n_no_triggers = 0
    skipped: list[str] = []
    values: list[float] = []

    for path in profile_paths:
        try:
            prof = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            skipped.append(f"{path.name}: unreadable ({exc})")
            continue

        groups: list[list[dict]] = []
        if isinstance(prof.get("triggers"), list):
            groups.append(prof["triggers"])
        for lst in (prof.get("setlist_triggers") or {}).values():
            if isinstance(lst, list):
                groups.append(lst)
        if not any(groups):
            n_no_triggers += 1
            continue

        la = librosa.get(prof.get("spotify_uri"))
        if not la:
            n_no_analysis += 1
            skipped.append(f"{path.name}: no librosa sections")
            continue

        window_ms = two_beat_window(la)
        norm = normalized_energies(la["sections"], args.curve)
        touched = False

        for group in groups:
            for trig in group:
                if not isinstance(trig, dict):
                    continue
                ms = trig.get("timestamp_ms")
                if not isinstance(ms, (int, float)):
                    continue
                idx, bumped = resolve_section(la, int(ms), window_ms)
                if norm[idx] is None:
                    continue
                new = shape(norm[idx], args.gamma, args.floor)
                n_triggers += 1
                values.append(new)
                if bumped:
                    n_bumped += 1
                if trig.get("intensity") != new:
                    trig["intensity"] = new
                    n_changed += 1
                    touched = True

        if touched:
            updated_docs.append((path, prof))

    print(f"triggers processed:       {n_triggers}")
    print(f"  intensity changed:      {n_changed}")
    if n_triggers:
        print(f"  bumped to next section: {n_bumped} ({100 * n_bumped / n_triggers:.1f}%)")
    print(f"profiles to write:        {len(updated_docs)}")
    print(f"profiles w/o triggers:    {n_no_triggers}")
    print(f"profiles w/o analysis:    {n_no_analysis}")

    if values:
        vs = sorted(values)
        q = lambda p: vs[int(p * (len(vs) - 1))]
        print(f"\nassigned intensity: min={vs[0]:.3f} p10={q(.10):.3f} p25={q(.25):.3f} "
              f"med={statistics.median(vs):.3f} p75={q(.75):.3f} p90={q(.90):.3f} max={vs[-1]:.3f}")
        print(f"                    below 0.5: {100 * sum(1 for x in vs if x < 0.5) / len(vs):.1f}%")

    if skipped:
        print(f"\nskipped ({len(skipped)}), first 10:")
        for s in skipped[:10]:
            print("  " + s)

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply.")
        return 0

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = BACKUPS_DIR / f"profiles-preintensity-{stamp}"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(PROFILES_DIR, backup)
    print(f"\nbacked up profiles -> {backup}")

    for path, prof in updated_docs:
        tmp = path.with_suffix(".json.tmp")
        # ensure_ascii matches how the app itself writes profiles (\uXXXX escapes),
        # so this backfill doesn't churn every accented title into raw UTF-8.
        tmp.write_text(json.dumps(prof, indent=2), encoding="utf-8")
        tmp.replace(path)
    print(f"wrote {len(updated_docs)} profiles")
    return 0


if __name__ == "__main__":
    sys.exit(main())
