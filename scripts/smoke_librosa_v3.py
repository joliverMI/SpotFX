"""
Offline smoke test for the librosa v3 analysis format (HPSS bass/snare onsets).

Asserts:
  1. Backward compat — existing v2 *.librosa.json sidecars load through the
     extended Pydantic schema with snare_onsets == [] and
     beats[*].snare_onset_score == 0.0.
  2. In-memory detectors — on one training-song WAV, the refactored
     bass/snare detectors return onsets with strengths in (0, 1], the snare
     track is non-empty, and the decluttered bass count is strictly below the
     v2 on-disk count.
  3. Round-trip (--full) — analyze_sync on that song writes a sidecar with
     librosa_version == 3 and snare data present in the .librosa.json.

USAGE
  .venv/bin/python scripts/smoke_librosa_v3.py          # checks 1 + 2
  .venv/bin/python scripts/smoke_librosa_v3.py --full   # also re-analyzes one song (rewrites its sidecars)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import AUDIO_SHAPES_DIR, settings  # noqa: E402
from models.audio_shape import AudioShapeMeta  # noqa: E402
from models.librosa_analysis import LibrosaAnalysis  # noqa: E402

FAILURES: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{'  — ' + detail if detail else ''}")
    if not ok:
        FAILURES.append(label)


def load_v2_sidecars(limit: int = 3) -> list[tuple[Path, LibrosaAnalysis]]:
    out = []
    for p in sorted(AUDIO_SHAPES_DIR.glob("*.librosa.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if "snare_onsets" in data:  # already v3 — not a backward-compat case
            continue
        out.append((p, LibrosaAnalysis(**data)))
        if len(out) >= limit:
            break
    return out


def find_training_song_with_wav() -> AudioShapeMeta | None:
    """First training-profile song that still has a WAV + old librosa JSON."""
    tp_path = Path(__file__).resolve().parent.parent / "storage" / "training_profiles.json"
    uris: set[str] = set()
    for prof in json.loads(tp_path.read_text(encoding="utf-8")).values():
        uris.update(prof.get("training_uris") or [])
        uris.update(prof.get("embedded_only_uris") or [])
    for jp in sorted(AUDIO_SHAPES_DIR.glob("*.json")):
        if jp.name.endswith(".librosa.json"):
            continue
        try:
            data = json.loads(jp.read_text(encoding="utf-8"))
            meta = AudioShapeMeta(**data)
        except Exception:
            continue
        if meta.spotify_uri not in uris:
            continue
        stem = Path(meta.npz_file).stem
        if (AUDIO_SHAPES_DIR / f"{stem}.wav").exists() and (AUDIO_SHAPES_DIR / f"{stem}.librosa.json").exists():
            return meta
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true",
                        help="also run analyze_sync round-trip (rewrites one song's sidecars)")
    args = parser.parse_args()

    print("1) Backward compat: v2 sidecars load through the v3 schema")
    v2 = load_v2_sidecars()
    check("found v2 sidecars", len(v2) > 0, f"{len(v2)} loaded")
    for p, la in v2:
        ok = la.snare_onsets == [] and all(b.snare_onset_score == 0.0 for b in la.beats[:20])
        check(p.name[:60], ok)

    print("\n2) In-memory detectors on one training WAV")
    from services.librosa_service import (
        compute_percussive, _detect_bass_onsets, _detect_snare_onsets, wav_path,
    )
    import librosa

    meta = find_training_song_with_wav()
    check("training song with WAV found", meta is not None,
          f"{meta.title} — {meta.artist}" if meta else "")
    if meta is None:
        return 1

    old_raw = json.loads(
        (AUDIO_SHAPES_DIR / f"{Path(meta.npz_file).stem}.librosa.json").read_text(encoding="utf-8"))
    old = LibrosaAnalysis(**old_raw)
    old_is_v2 = "snare_onsets" not in old_raw
    y, sr = librosa.load(str(wav_path(meta)), sr=None, mono=True)
    y_perc = compute_percussive(y, sr, settings.librosa_hpss_margin)
    bass = _detect_bass_onsets(y_perc, sr)
    snare = _detect_snare_onsets(y_perc, sr)

    dur_s = len(y) / sr
    print(f"     old bass onsets: {len(old.bass_onsets)}  new bass: {len(bass)}  "
          f"snare: {len(snare)}  ({dur_s:.0f}s → bass {len(bass)/dur_s:.2f}/s, snare {len(snare)/dur_s:.2f}/s)")
    check("snare onsets non-empty", len(snare) > 0)
    if old_is_v2:
        check("bass count below v2 count", len(bass) < len(old.bass_onsets),
              f"{len(bass)} < {len(old.bass_onsets)}")
    else:
        check("bass count reproducible vs stored v3", len(bass) == len(old.bass_onsets),
              f"{len(bass)} == {len(old.bass_onsets)}")
    check("bass strengths in (0,1]", all(0 < o.strength <= 1 for o in bass))
    check("snare strengths in (0,1]", all(0 < o.strength <= 1 for o in snare))

    if args.full:
        print("\n3) analyze_sync round-trip (rewrites sidecars for this song)")
        from services.librosa_service import analyze_sync, get_analysis, LIBROSA_VERSION
        analyze_sync(meta)
        la = get_analysis(meta)
        check("reloaded analysis has snare_onsets", la is not None and len(la.snare_onsets) > 0)
        check("meta stamped v3", meta.librosa_version == LIBROSA_VERSION)
        sidecar = json.loads(((AUDIO_SHAPES_DIR / meta.npz_file).with_suffix(".json")).read_text(encoding="utf-8"))
        check("sidecar stamped v3", sidecar.get("librosa_version") == LIBROSA_VERSION)
        check("beat snare scores populated", la is not None and any(b.snare_onset_score > 0 for b in la.beats))
    else:
        print("\n3) round-trip skipped (pass --full to run analyze_sync)")

    print(f"\n{'OK' if not FAILURES else 'FAILED'}: {len(FAILURES)} failure(s)")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
