#!/usr/bin/env python
"""
xcorr benchmark grid runner.

  python -m scripts.xcorr_bench --selftest
  python -m scripts.xcorr_bench --tag baseline                # full grid on corpus
  python -m scripts.xcorr_bench --tag quick --quick           # reduced grid
  python -m scripts.xcorr_bench --compare baseline fft
  python -m scripts.xcorr_bench --tag fftwide --set xcorr_fft_enabled=true --force-search-ms 30000

Outputs storage/benchmarks/<tag>/results.csv + summary.json.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from config import settings  # noqa: E402
from bench.corpus import BENCH_DIR, load_corpus  # noqa: E402
from bench.replay import Scenario, load_song_assets, replay_play  # noqa: E402
from bench.simulate import load_wav, make_frames  # noqa: E402

SEEDS = ["cold", "seeded_correct", "seeded_wrong_2s"]

# (name, true_offset_ms, cut_in_ms, noise_snr_db, blend_ms)
PROFILES = [
    ("off0",        0,      0,     None, 0),
    ("off+200",     200,    0,     None, 0),
    ("off-200",     -200,   0,     None, 0),
    ("off+2s",      2000,   0,     None, 0),
    ("off-2s",      -2000,  0,     None, 0),
    ("off+10s",     10000,  0,     None, 0),
    ("off-10s",     -10000, 0,     None, 0),
    ("off+25s",     25000,  0,     None, 0),
    ("off-25s",     -25000, 0,     None, 0),
    ("noise0",      0,      0,     20.0, 0),
    ("noise-2s",    -2000,  0,     20.0, 0),
    ("cutin5s",     5000,   5000,  None, 0),
    ("cutin15s",    15000,  15000, None, 0),
    ("cutin25s",    25000,  25000, None, 0),
    ("blend8s",     0,      0,     None, 8000),
]
QUICK_PROFILES = {"off0", "off-2s", "off+10s", "cutin15s", "blend8s"}
QUICK_SEEDS = ["cold", "seeded_wrong_2s"]


def run_grid(tag: str, *, corpus_name: str, quick: bool, limit_songs: int | None,
             force_search_ms: int | None, overrides: dict) -> None:
    for k, v in overrides.items():
        if not hasattr(settings, k):
            sys.exit(f"unknown setting: {k}")
        cur = getattr(settings, k)
        cast = (lambda s: s.lower() in ("1", "true", "yes")) if isinstance(cur, bool) \
            else type(cur)
        setattr(settings, k, cast(v))
        print(f"  setting override: {k}={getattr(settings, k)}")

    corpus = load_corpus(corpus_name)
    stems = corpus["stems"][:limit_songs] if limit_songs else corpus["stems"]
    profiles = [p for p in PROFILES if not quick or p[0] in QUICK_PROFILES]
    seeds = QUICK_SEEDS if quick else SEEDS

    out_dir = BENCH_DIR / tag
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    t_start = time.monotonic()
    total = len(stems) * len(profiles) * len(seeds)
    done = 0

    from bench.calibrate import wav_bias

    for si, stem in enumerate(stems):
        try:
            assets = load_song_assets(stem)
            pcm = load_wav(assets["wav_path"])
        except Exception as exc:
            print(f"  ! skipping {stem}: {exc}")
            continue
        clean_frames = make_frames(pcm)
        bias = wav_bias(stem, assets, clean_frames)
        if bias is None:
            print(f"  ! skipping {stem}: WAV↔NPZ bias calibration failed")
            continue
        donor_pcm = None
        donor_stem = stems[si - 1]   # blend donor: previous corpus song (wraps)
        # Offsets only shift timestamps — synthesize once per degradation
        # (cut/noise/blend) and derive per-offset frames cheaply.
        degr_cache: dict = {(0, None, 0): clean_frames}
        for (pname, true_off, cut_in, snr, blend_ms) in profiles:
            key = (cut_in, snr, blend_ms)
            if key not in degr_cache:
                if blend_ms > 0 and donor_pcm is None:
                    try:
                        donor_pcm = load_wav(assets["wav_path"].parent / f"{donor_stem}.wav")
                    except Exception:
                        donor_pcm = None
                degr_cache[key] = make_frames(
                    pcm, cut_in_ms=cut_in, noise_snr_db=snr,
                    blend_donor_pcm=donor_pcm if blend_ms > 0 else None,
                    blend_ms=blend_ms,
                )
            base = degr_cache[key]
            frames = base if true_off == 0 else [(f[0] - true_off,) + f[1:] for f in base]
            for seed in seeds:
                sc = Scenario(name=f"{pname}/{seed}", true_offset_ms=true_off,
                              cut_in_ms=cut_in, noise_snr_db=snr,
                              blend_ms=blend_ms, seed=seed,
                              force_search_ms=force_search_ms)
                res = replay_play(stem, sc, assets=assets, frames=frames,
                                  wav_bias_ms=bias)
                results.append(res)
                done += 1
                # Two-play memory scenario (Phase 4): replay the same blend
                # cut-in / wide offset with the slot state the cold play left
                # behind — exercises cut-in memory + narrow-stage centering.
                if seed == "cold" and (cut_in > 0 or abs(true_off) >= 10000):
                    sc2 = Scenario(name=f"{pname}/second_play",
                                   true_offset_ms=true_off, cut_in_ms=cut_in,
                                   noise_snr_db=snr, blend_ms=blend_ms,
                                   seed="snapshot",
                                   seed_snapshot=res.store_snapshot,
                                   force_search_ms=force_search_ms)
                    results.append(replay_play(stem, sc2, assets=assets,
                                               frames=frames, wav_bias_ms=bias))
                    done += 1
        el = time.monotonic() - t_start
        print(f"  [{si+1}/{len(stems)}] {stem[:46]:<46} bias={bias:+5d}ms  "
              f"{done}/{total} plays, {el:.0f}s")

    # ── Write results.csv ─────────────────────────────────────────────────────
    cols = ["stem", "scenario", "expected_offset_ms", "final_stored_offset_ms",
            "final_stored_error_ms", "engine_final_error_ms",
            "time_to_first_correct_lock_ms", "wrong_lock_events", "n_saves",
            "anchor_matched", "progressive_matched", "locked_via_stop", "windows_evaluated",
            "windows_planned", "cpu_ms_total", "cpu_ms_p50", "cpu_ms_p95", "correct"]
    with (out_dir / "results.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for r in results:
            w.writerow([getattr(r, c) if c != "correct" else r.correct for c in cols])

    # ── Summary by scenario ───────────────────────────────────────────────────
    summary: dict = {"tag": tag, "corpus": corpus_name, "songs": len(stems),
                     "plays": len(results), "overrides": overrides,
                     "force_search_ms": force_search_ms, "scenarios": {}}
    by_scenario: dict[str, list] = {}
    for r in results:
        by_scenario.setdefault(r.scenario, []).append(r)
    for name, rs in sorted(by_scenario.items()):
        errs = [abs(r.final_stored_error_ms) for r in rs if r.final_stored_error_ms is not None]
        locks = [r.time_to_first_correct_lock_ms for r in rs
                 if r.time_to_first_correct_lock_ms is not None]
        summary["scenarios"][name] = {
            "plays": len(rs),
            "saved_pct": round(100 * sum(1 for r in rs if r.n_saves > 0) / len(rs), 1),
            "accuracy_300ms_pct": round(100 * sum(1 for r in rs if r.correct) / len(rs), 1),
            "median_abs_error_ms": int(np.median(errs)) if errs else None,
            "wrong_lock_rate_pct": round(
                100 * sum(1 for r in rs if r.wrong_lock_events > 0) / len(rs), 1),
            "median_time_to_lock_ms": int(np.median(locks)) if locks else None,
            "lock_rate_pct": round(100 * len(locks) / len(rs), 1),
            "cpu_ms_per_window_p50": round(float(np.median([r.cpu_ms_p50 for r in rs])), 1),
            "cpu_ms_per_play_total": round(float(np.median([r.cpu_ms_total for r in rs])), 1),
        }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nWrote {out_dir}/results.csv + summary.json "
          f"({len(results)} plays, {time.monotonic()-t_start:.0f}s)")
    _print_summary(summary)


def _print_summary(summary: dict) -> None:
    print(f"\n=== {summary['tag']} ===")
    hdr = f"{'scenario':<24}{'acc@300':>8}{'saved':>7}{'wrongLk':>8}{'t-lock':>8}{'|err|':>7}{'cpu/win':>8}"
    print(hdr)
    for name, s in summary["scenarios"].items():
        print(f"{name:<24}{s['accuracy_300ms_pct']:>7}%{s['saved_pct']:>6}%"
              f"{s['wrong_lock_rate_pct']:>7}%"
              f"{str(s['median_time_to_lock_ms']):>8}{str(s['median_abs_error_ms']):>7}"
              f"{s['cpu_ms_per_window_p50']:>8}")


def compare(tag_a: str, tag_b: str) -> None:
    sa = json.loads((BENCH_DIR / tag_a / "summary.json").read_text())
    sb = json.loads((BENCH_DIR / tag_b / "summary.json").read_text())
    print(f"\n=== {tag_a} vs {tag_b} ===")
    print(f"{'scenario':<24}{'acc A':>7}{'acc B':>7}{'Δacc':>7}"
          f"{'wrong A':>8}{'wrong B':>8}{'lock A':>8}{'lock B':>8}{'cpu A':>7}{'cpu B':>7}")
    for name in sorted(set(sa["scenarios"]) | set(sb["scenarios"])):
        a = sa["scenarios"].get(name)
        b = sb["scenarios"].get(name)
        if not a or not b:
            print(f"{name:<24}  (only in one tag)")
            continue
        d_acc = b["accuracy_300ms_pct"] - a["accuracy_300ms_pct"]
        print(f"{name:<24}{a['accuracy_300ms_pct']:>6}%{b['accuracy_300ms_pct']:>6}%"
              f"{d_acc:>+6.1f}%{a['wrong_lock_rate_pct']:>7}%{b['wrong_lock_rate_pct']:>7}%"
              f"{str(a['median_time_to_lock_ms']):>8}{str(b['median_time_to_lock_ms']):>8}"
              f"{a['cpu_ms_per_window_p50']:>7}{b['cpu_ms_per_window_p50']:>7}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--tag", default=None, help="run the grid, write to storage/benchmarks/<tag>/")
    ap.add_argument("--corpus", default="corpus_v1")
    ap.add_argument("--quick", action="store_true", help="reduced profile/seed grid")
    ap.add_argument("--limit-songs", type=int, default=None)
    ap.add_argument("--force-search-ms", type=int, default=None)
    ap.add_argument("--set", default="", help="comma-separated settings overrides k=v")
    ap.add_argument("--compare", nargs=2, metavar=("TAG_A", "TAG_B"))
    args = ap.parse_args()

    if args.selftest:
        from bench.selftest import run_selftest
        sys.exit(0 if run_selftest() else 1)
    if args.compare:
        compare(*args.compare)
        return
    if not args.tag:
        ap.error("need --selftest, --compare, or --tag")
    overrides = dict(kv.split("=", 1) for kv in args.set.split(",") if kv)
    run_grid(args.tag, corpus_name=args.corpus, quick=args.quick,
             limit_songs=args.limit_songs,
             force_search_ms=args.force_search_ms, overrides=overrides)


if __name__ == "__main__":
    main()
