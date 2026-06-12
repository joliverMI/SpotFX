"""
Re-score benchmark results.csv files under the "what would the next play
load" metric, uniformly across tags recorded before the metric landed in
replay.py. For rows with no save (empty final_stored_offset_ms), the slot
retains its seed: seeded_correct → expected (correct), seeded_wrong_2s →
expected+2000 (wrong), cold → unknown (not correct).
"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

import numpy as np

from bench.corpus import BENCH_DIR


def rescore(tag: str) -> dict[str, dict]:
    rows = list(csv.DictReader(open(BENCH_DIR / tag / "results.csv", encoding="utf-8")))
    out: dict[str, dict] = {}
    by_scen = defaultdict(list)
    for r in rows:
        by_scen[r["scenario"]].append(r)
    for scen, rs in sorted(by_scen.items()):
        seed = scen.split("/")[1]
        n_correct = 0
        errs = []
        locks = []
        wrong = 0
        for r in rs:
            expected = int(r["expected_offset_ms"])
            stored = r["final_stored_offset_ms"]
            if stored not in ("", "None"):
                stored_v = int(float(stored))
            elif seed == "seeded_correct":
                stored_v = expected
            elif seed == "seeded_wrong_2s":
                stored_v = expected + 2000
            else:
                stored_v = None
            if stored_v is not None:
                err = abs(stored_v - expected)
                errs.append(err)
                if err <= 300:
                    n_correct += 1
            if int(r["wrong_lock_events"]) > 0:
                wrong += 1
            t = r["time_to_first_correct_lock_ms"]
            if t not in ("", "None"):
                locks.append(int(float(t)))
        out[scen] = {
            "acc": round(100 * n_correct / len(rs), 1),
            "wrong": round(100 * wrong / len(rs), 1),
            "tlock": int(np.median(locks)) if locks else None,
            "lock_rate": round(100 * len(locks) / len(rs), 1),
        }
    return out


def compare(tags: list[str]) -> None:
    data = {t: rescore(t) for t in tags}
    scens = sorted(set().union(*(d.keys() for d in data.values())))
    hdr = f"{'scenario':<26}"
    for t in tags:
        hdr += f"{t[:6]+'_acc':>11}{'wL':>7}{'tlk':>7}"
    print(hdr)
    for s in scens:
        row = f"{s:<26}"
        for t in tags:
            v = data[t].get(s, {})
            row += f"{v.get('acc','-'):>10}%{v.get('wrong','-'):>6}%{str(v.get('tlock','-')):>7}"
        print(row)
    import statistics as st
    for t in tags:
        d = data[t]
        accs = [v["acc"] for v in d.values()]
        wls = [v["wrong"] for v in d.values()]
        tls = [v["tlock"] for v in d.values() if v["tlock"]]
        print(f"{t:>8}: mean acc={st.mean(accs):.1f}%  wrongLk={st.mean(wls):.1f}%  "
              f"median t-lock={st.median(tls):.0f}ms")


if __name__ == "__main__":
    import sys
    compare(sys.argv[1:] or ["baseline", "fft", "accum", "prog"])
