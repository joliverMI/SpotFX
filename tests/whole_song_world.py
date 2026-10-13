"""
Fixtures for the whole-song check (services/whole_song_check.py).

The report's §5.4 run used real LIVE frames polled from his room on
2026-10-12; those frames lived in a scratch session and are gone (§5.6). The
evidence is rebuilt the same way it was measured, from the two pieces that
still exist:

  * the STORED shapes of his two failing songs, copied verbatim (raw bands,
    compressed) into tests/fixtures/whole_song/ — El Efecto and Ponle
    Dembow. Their repeating phrases are what made the twins, so the twins
    are in these fixtures for real;
  * a live capture SYNTHESISED from the stored shape at the report's true
    offset: the room plays the shape `offset_ms` ahead (live(t) =
    stored(t + offset)), through a short smoothing (the speaker/room), a
    gain change and noise, at the capture's own ~11.6 ms frame rate.

Built this way, the El Efecto twin the engine sat on (+325 ms) scores a
median r ≈ 0.55 against the true +11,750 at ≈ 0.93 — the report measured
0.56 and 0.95 on the real play — so the synthetic room reproduces the
measured separation rather than inventing an easier one.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "whole_song"
BANDS = ("rms_total", "rms_low", "rms_mid", "rms_high")
CAPTURE_FRAME_MS = 512 / 44100 * 1000.0        # config.audio_chunk_size @ 44.1 kHz

# The report's two failing songs: (fixture, title, true offset, the offset
# the engine kept re-saving).
EL_EFECTO = ("el_efecto", "El Efecto", 11750, 325)
PONLE_DEMBOW = ("ponle_dembow", "Ponle Dembow", 6250, 1225)

# The report's §5.4 table: the 20 songs that LOCKED on 2026-10-12, at the
# offset the engine locked on (for "think you're someone new", the lock
# before the monitor recovery moved it). Title substrings match the live
# shape library's sidecar titles.
REPORT_LOCKS: list[tuple[str, int]] = [
    ("Mayores", 103), ("Bzrp Music Sessions, Vol. 58", 4673), ("La Jumpa", 4802),
    ("Brinca", 294), ("Bzrp Music Sessions, Vol. 62", 239),
    ("Bzrp Music Sessions, Vol. 56", 150), ("Bzrp Music Sessions, Vol. 57", 522),
    ("SHADOWS", -167), ("Lo Siento BB", 725), ("Smells Like Teen Spirit", -241),
    ("Tom Sawyer", 375), ("Money for Nothing", -75), ("Dream On", 519),
    ("The Chain", -50), ("Welcome to Hard Times", 5054), ("The Man from Waco", 5124),
    ("Jamestown Ferry", 5150), ("Winny", 317), ("on fire", -1674),
    ("think you're someone new", -1704),
]


def _signed_square(a: np.ndarray) -> np.ndarray:
    return a * np.abs(a)


def shape_from_npz(path: Path) -> tuple[np.ndarray, list[np.ndarray], list[np.ndarray]]:
    """(timestamps, squared bands, raw bands) — the squared bands exactly as
    the sweep loads them (`<band>_sq`, or x·|x| for a legacy shape)."""
    z = np.load(path)
    ts = np.asarray(z["timestamps_ms"], dtype=float)
    raw = [np.asarray(z[b], dtype=float) for b in BANDS]
    sq = [np.asarray(z[b + "_sq"], dtype=float) if (b + "_sq") in z.files
          else _signed_square(r) for b, r in zip(BANDS, raw)]
    return ts, sq, raw


def load_fixture(name: str):
    return shape_from_npz(FIXTURES / f"{name}.npz")


def live_frames(ts: np.ndarray, raw: list[np.ndarray], offset_ms: int, *,
                seed: int = 0, noise: float = 0.15, gain: float = 0.8,
                smooth: int = 5, frame_ms: float = CAPTURE_FRAME_MS,
                until_ms: Optional[float] = None,
                ) -> list[tuple[int, float, float, float, float]]:
    """A play's capture frames when the song truly aligns at `offset_ms`
    (positive = the room is AHEAD of the stored shape: live(t) =
    stored(t + offset)). `until_ms` ends the play early (a skip)."""
    rng = np.random.default_rng(seed)
    order = np.argsort(ts, kind="stable")
    t_sorted = ts[order]
    end = t_sorted[-1] - max(offset_ms, 0)
    if until_ms is not None:
        end = min(end, until_ms)
    live_t = np.arange(max(0.0, -float(offset_ms)), end, frame_ms)
    cols = []
    kernel = np.ones(max(1, smooth)) / max(1, smooth)
    for band in raw:
        v = np.interp(live_t + offset_ms, t_sorted, band[order])
        v = np.convolve(v, kernel, mode="same") * gain
        v = v + rng.normal(0.0, noise * float(np.std(v)) + 1e-9, len(v))
        cols.append(v)
    return [(int(round(t)), float(a), float(b), float(c), float(d))
            for t, a, b, c, d in zip(live_t, *cols)]


def periodic_shape(period_ms: int = 2000, duration_ms: int = 200_000, *,
                   seed: int = 7) -> tuple[np.ndarray, list[np.ndarray], list[np.ndarray]]:
    """A song that is ONE short phrase repeated end to end (a loop-based
    track at its most extreme): every whole number of phrases away from the
    truth is an equally good fit, so a whole-song vote has nothing to choose
    between — the twin-ambiguous case."""
    rng = np.random.default_rng(seed)
    ts = np.arange(0.0, float(duration_ms), CAPTURE_FRAME_MS)
    phrase_t = np.arange(0.0, float(period_ms), CAPTURE_FRAME_MS)
    raw = []
    for _b in BANDS:
        # A few sharp hits per phrase on a quiet bed.
        phrase = 0.05 + 0.02 * rng.random(len(phrase_t))
        for hit in rng.uniform(0, period_ms, 4):
            phrase += 0.6 * np.exp(-0.5 * ((phrase_t - hit) / 40.0) ** 2)
        raw.append(np.interp(np.mod(ts, period_ms), phrase_t, phrase))
    return ts, [_signed_square(r) for r in raw], raw


def find_live_shape(title_part: str, shapes_dir: Path) -> Optional[Path]:
    """The npz of the live library's shape whose sidecar title contains
    `title_part` (read-only; for the executable spec's --live-shapes run)."""
    import json
    for side in sorted(shapes_dir.glob("*.json")):
        if side.name.endswith(".librosa.json"):
            continue
        try:
            meta = json.loads(side.read_text(encoding="utf-8"))
        except Exception:
            continue
        if title_part.lower() in str(meta.get("title", "")).lower() and meta.get("npz_file"):
            p = shapes_dir / meta["npz_file"]
            if p.exists():
                return p
    return None
