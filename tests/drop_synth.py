"""A synthetic song for the drop detector's tests — never his storage.

Writes the three files the detector reads into an AUDIO_SHAPES_DIR (the
`<stem>.npz` audio shape at 12 ms frames IN SONG TIME, the
`<stem>.librosa.json` beats IN RECORDING TIME, the `<stem>.json` capture
sidecar) for a song built from named SECTIONS:

  ("loud", start_s, end_s, level)   a kick on every beat over a sustained
                                    bass bed at `level` (0..1)
  ("quiet", start_s, end_s, level)  no kick; bass and total held at `level`

A drop is simply a quiet stretch followed by a louder loud one — what the
detector looks for — so a test places its own drops by choosing sections.
`offset_ms` makes a capture that starts mid-song: the shape's timestamps
start there, and the beats are written relative to it, exactly as a real
capture stores them.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

FRAME_MS = 12


def write_song(shapes_dir: Path, uri: str, sections: list[tuple], *,
               tempo: float = 120.0, offset_ms: int = 0, duration_ms: int | None = None,
               stem: str = "Synth - Song", analyzed_at: str = "2026-10-01T00:00:00",
               double_hit_at_s: tuple = ()) -> str:
    shapes_dir.mkdir(parents=True, exist_ok=True)
    end_s = max(s[2] for s in sections)
    t = np.arange(offset_ms, int(end_s * 1000), FRAME_MS, dtype=np.int64)
    low = np.full(len(t), 0.01)
    total = np.full(len(t), 0.02)
    high = np.full(len(t), 0.02)
    beat = 60000.0 / tempo

    def kick(at_ms: float, peak: float) -> None:
        i0 = int(np.searchsorted(t, at_ms))
        for k in range(0, 18):
            if i0 + k < len(t):
                v = peak * np.exp(-k / 6.0)
                low[i0 + k] = max(low[i0 + k], v)
                total[i0 + k] = max(total[i0 + k], 0.9 * v)

    for kind, a_s, b_s, level in sections:
        m = (t >= a_s * 1000) & (t < b_s * 1000)
        if kind == "quiet":
            low[m] = level
            total[m] = max(level, 0.03)
            high[m] = 0.05
            continue
        low[m] = 0.45 * level
        total[m] = 0.55 * level
        high[m] = 0.3 * level
        k_ms = a_s * 1000
        while k_ms < b_s * 1000:
            if k_ms >= offset_ms:
                kick(k_ms, level)
            k_ms += beat
    for at_s in double_hit_at_s:
        kick(at_s * 1000 - 0.25 * beat, 0.9)

    np.savez(shapes_dir / f"{stem}.npz", timestamps_ms=t, rms_low=low,
             rms_mid=total * 0.5, rms_high=high, rms_total=total)
    beats = []
    k = 0
    b_ms = 0.0
    while b_ms < end_s * 1000:
        if b_ms >= offset_ms:
            beats.append({"ms": round(b_ms - offset_ms, 1), "is_downbeat": k % 4 == 0})
        k += 1
        b_ms = k * beat
    (shapes_dir / f"{stem}.librosa.json").write_text(json.dumps({
        "spotify_uri": uri, "tempo_bpm": tempo, "analyzed_at": analyzed_at,
        "beats": beats, "sections": [],
    }), encoding="utf-8")
    (shapes_dir / f"{stem}.json").write_text(json.dumps({
        "spotify_uri": uri,
        "duration_ms": duration_ms if duration_ms is not None else int(end_s * 1000),
    }), encoding="utf-8")
    return stem


def one_drop_song(shapes_dir: Path, uri: str, **kw) -> str:
    """Loud from 0-40 s, a 4 s break (8 beats at 120 bpm) from 40-44 s, the
    DROP at 44 s (louder), loud to 80 s, outro to 100 s."""
    return write_song(shapes_dir, uri, [
        ("loud", 0, 40, 0.55), ("quiet", 40, 44, 0.01),
        ("loud", 44, 80, 1.0), ("loud", 80, 100, 0.5),
    ], **kw)


DROP_S = 44.0


def reset_index() -> None:
    from spectra.services import analysis_reader, drop_detector
    analysis_reader._shape_index.clear()
    analysis_reader._index_built = False
    drop_detector.reset_memo()
