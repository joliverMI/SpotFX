"""
Benchmark corpus: a stratified, persisted sample of songs from
storage/audio_shapes/ so every benchmark run measures the same material.

Strata: tempo terciles (librosa tempo_bpm) × intro-quietness terciles
(mean rms_total over the first 10 s of the NPZ). Songs need all four asset
files (.wav/.npz/.json/.librosa.json) to qualify. Selection is deterministic
(sorted stems, round-robin across the 9 cells).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from config import AUDIO_SHAPES_DIR

BENCH_DIR = Path(AUDIO_SHAPES_DIR).parent / "benchmarks"


def _eligible_stems() -> list[str]:
    stems = []
    for wav in sorted(AUDIO_SHAPES_DIR.glob("*.wav")):
        stem = wav.stem
        if not ((AUDIO_SHAPES_DIR / f"{stem}.npz").exists()
                and (AUDIO_SHAPES_DIR / f"{stem}.json").exists()
                and (AUDIO_SHAPES_DIR / f"{stem}.librosa.json").exists()):
            continue
        # Require a cached window plan — replay uses it verbatim (planning
        # offline would be slow and could diverge from what live plays used).
        try:
            sidecar = json.loads(
                (AUDIO_SHAPES_DIR / f"{stem}.json").read_text(encoding="utf-8"))
            if not sidecar.get("xcorr_windows"):
                continue
        except Exception:
            continue
        stems.append(stem)
    return stems


def _features(stem: str) -> tuple[float, float] | None:
    """(tempo_bpm, intro_quietness) or None when unreadable."""
    try:
        tempo = json.loads(
            (AUDIO_SHAPES_DIR / f"{stem}.librosa.json").read_text(encoding="utf-8")
        ).get("tempo_bpm") or 0.0
        data = np.load(AUDIO_SHAPES_DIR / f"{stem}.npz")
        ts = data["timestamps_ms"]
        rms = data["rms_total"]
        intro = float(rms[ts <= 10_000].mean()) if (ts <= 10_000).any() else 0.0
        return float(tempo), intro
    except Exception:
        return None


def build_corpus(n: int = 45, name: str = "corpus_v1") -> dict:
    """Build + persist a stratified corpus. Returns the corpus dict."""
    feats: dict[str, tuple[float, float]] = {}
    for stem in _eligible_stems():
        f = _features(stem)
        if f is not None:
            feats[stem] = f
    if not feats:
        raise RuntimeError("no eligible songs (need .wav/.npz/.json/.librosa.json)")

    tempos = sorted(v[0] for v in feats.values())
    intros = sorted(v[1] for v in feats.values())

    def _tercile(sorted_vals, x):
        lo = sorted_vals[len(sorted_vals) // 3]
        hi = sorted_vals[2 * len(sorted_vals) // 3]
        return 0 if x < lo else (1 if x < hi else 2)

    cells: dict[tuple[int, int], list[str]] = {}
    for stem in sorted(feats):
        t, q = feats[stem]
        cells.setdefault((_tercile(tempos, t), _tercile(intros, q)), []).append(stem)

    # Round-robin across cells until n stems collected.
    picked: list[str] = []
    idx = 0
    while len(picked) < min(n, len(feats)):
        progressed = False
        for cell in sorted(cells):
            lst = cells[cell]
            if idx < len(lst):
                picked.append(lst[idx])
                progressed = True
                if len(picked) >= min(n, len(feats)):
                    break
        if not progressed:
            break
        idx += 1

    corpus = {
        "name": name,
        "stems": picked,
        "strata": {f"{c[0]},{c[1]}": len(v) for c, v in sorted(cells.items())},
        "eligible_total": len(feats),
    }
    BENCH_DIR.mkdir(parents=True, exist_ok=True)
    (BENCH_DIR / f"{name}.json").write_text(
        json.dumps(corpus, indent=2), encoding="utf-8")
    return corpus


def load_corpus(name: str = "corpus_v1") -> dict:
    path = BENCH_DIR / f"{name}.json"
    if not path.exists():
        return build_corpus(name=name)
    return json.loads(path.read_text(encoding="utf-8"))
