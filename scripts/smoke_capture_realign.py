"""
Smoke test — recapture self-correction (services/capture_alignment.py).

Synthesizes an "old" and a "new" capture of the same fake song with a known
timebase shift Δ (plus noise, gain change, and the old capture's classic
non-monotonic pre-roll seam), then checks:

  1. measure_capture_shift recovers Δ within one xcorr bin or two
     (positive, negative, and zero shifts)
  2. uncorrelated signals are rejected (returns None)
  3. shift_offset_fields migrates every learned-offset field by Δ and
     leaves user trims untouched

Run: python scripts/smoke_capture_realign.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.capture_alignment import measure_capture_shift, shift_offset_fields  # noqa: E402
from services.xcorr_core import signed_square  # noqa: E402

SR_MS = 46            # frame cadence (ms), ~1024 samples @ 22kHz equivalent
SONG_MS = 200_000     # 200s fake song
FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILURES.append(name)


def _music(rng: np.ndarray, seed: int) -> np.ndarray:
    """Non-periodic 'music' band: smoothed random walk with section-scale
    envelope, evaluated at ms positions `rng`."""
    rs = np.random.RandomState(seed)
    grid_ms = np.arange(-20_000, SONG_MS + 20_000, 10.0)
    walk = np.cumsum(rs.randn(len(grid_ms)))
    kernel = np.hanning(41); kernel /= kernel.sum()
    smooth = np.convolve(walk, kernel, mode="same")
    envelope = 1.0 + 0.5 * np.sin(grid_ms / 17_000.0) + 0.3 * np.sin(grid_ms / 4_300.0)
    sig = np.abs(smooth * envelope)
    sig /= sig.max() + 1e-9
    return np.interp(rng, grid_ms, sig)


def _write_npz(path: Path, ts: np.ndarray, bands: list[np.ndarray]) -> None:
    keys = ("rms_total", "rms_low", "rms_mid", "rms_high")
    payload = {"timestamps_ms": ts.astype(np.int32)}
    for k, b in zip(keys, bands):
        payload[k] = b.astype(np.float32)
        payload[k + "_sq"] = signed_square(b).astype(np.float32)
    np.savez_compressed(path, **payload)


def make_pair(tmp: Path, shift_ms: int, *, correlated: bool = True,
              seam: bool = True) -> tuple[Path, Path]:
    """old capture: label t → music(t). new capture: label t → music(t − Δ)
    (music appears Δ later in the new file → Δ = new_label − old_label)."""
    ts = np.arange(0.0, SONG_MS, SR_MS)
    old_bands = [_music(ts, seed) for seed in (1, 2, 3, 4)]
    if correlated:
        rs = np.random.RandomState(99)
        new_bands = [
            0.8 * _music(ts - shift_ms, seed) + 0.02 * rs.randn(len(ts))
            for seed in (1, 2, 3, 4)
        ]
    else:
        new_bands = [_music(ts, seed) for seed in (11, 12, 13, 14)]

    old_ts = ts
    if seam:
        # Reproduce the buggy old-capture head: ~1.5s of mislabeled pre-roll
        # frames whose labels overlap the live frames written after them.
        seam_ts = np.arange(0.0, 1500, SR_MS)
        seam_bands = [_music(seam_ts + 42_000, seed) for seed in (5, 6, 7, 8)]
        old_ts = np.concatenate([seam_ts, ts])
        old_bands = [np.concatenate([sb, ob]) for sb, ob in zip(seam_bands, old_bands)]

    old_p = tmp / f"old_{shift_ms}_{correlated}.npz"
    new_p = tmp / f"new_{shift_ms}_{correlated}.npz"
    _write_npz(old_p, old_ts, old_bands)
    _write_npz(new_p, ts, new_bands)
    return old_p, new_p


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="smoke_realign_"))
    print(f"scratch: {tmp}")

    print("\n1. shift recovery")
    for true_shift in (900, -650, 0, 3200):
        old_p, new_p = make_pair(tmp, true_shift)
        m = measure_capture_shift(old_p, new_p)
        if m is None:
            check(f"Δ={true_shift:+d}ms recovered", False, "returned None")
            continue
        err = m.shift_ms - true_shift
        check(f"Δ={true_shift:+d}ms recovered", abs(err) <= 50,
              f"measured {m.shift_ms:+d}ms (err {err:+d}ms, r={m.r:.3f})")

    print("\n2. uncorrelated rejection")
    old_p, new_p = make_pair(tmp, 0, correlated=False)
    m = measure_capture_shift(old_p, new_p)
    check("different songs rejected", m is None,
          "" if m is None else f"accepted shift {m.shift_ms} r={m.r:.3f}")

    print("\n3. offset-field migration")
    old_meta = {
        "timestamp_offset_ms": -350,
        "perception_trim_ms": 60,
        "offset_verification": "auto_verified",
        "offset_quality": 0.71,
        "offset_history": [{"iso_timestamp": "t0", "offset_ms": -340, "quality": 0.7}],
        "setlist_offsets": {
            "sl-1": {
                "timestamp_offset_ms": -1200,
                "offset_quality": 0.8,
                "observed_cut_in_ms": -1150,
                "observed_cut_ms": 4000,
                "perception_trim_ms": -40,
                "history": [{"offset_ms": -1190, "quality": 0.75, "generated_at": "t1"}],
                "anti_corr_count": 2,
                "last_anti_corr_at": "t2",
            }
        },
    }
    data = shift_offset_fields({}, old_meta, 900)
    sl = data["setlist_offsets"]["sl-1"]
    check("base offset shifted", data["timestamp_offset_ms"] == 550)
    check("trim carried unshifted", data["perception_trim_ms"] == 60)
    check("verification carried", data["offset_verification"] == "auto_verified")
    check("history entry shifted", data["offset_history"][0]["offset_ms"] == 560)
    check("setlist lock shifted", sl["timestamp_offset_ms"] == -300)
    check("setlist cut-in shifted", sl["observed_cut_in_ms"] == -250)
    check("setlist cut (duration delta) unshifted", sl["observed_cut_ms"] == 4000)
    check("setlist trim carried unshifted", sl["perception_trim_ms"] == -40)
    check("setlist history shifted", sl["history"][0]["offset_ms"] == -290)
    check("anti-corr state reset", sl["anti_corr_count"] == 0 and "last_anti_corr_at" not in sl)

    print(f"\n{'ALL PASS' if not FAILURES else f'{len(FAILURES)} FAILURE(S): {FAILURES}'}")
    return 0 if not FAILURES else 1


if __name__ == "__main__":
    sys.exit(main())
