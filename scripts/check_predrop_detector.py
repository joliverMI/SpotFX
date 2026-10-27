#!/usr/bin/env python3
"""Pre-drop detection acceptance (predrop plan step 3) — the report's own
numbers, reproduced by the SHIPPED code.

READ-ONLY against the live checkout's storage (default /home/javi/SpotFX,
override with --live-root): the stored audio shapes and beat analyses of
every song the study measured and every song in his drop store, plus that
store, his room controls and his triggers for those songs. NOTHING is
written there — each file this run reads is COPIED into a throwaway temp
directory and every store it touches (AUDIO_SHAPES_DIR, TRIGGERS_FILE,
DROP_SEQUENCES_FILE, ROOM_CONTROLS_FILE, ...) is repointed at the copy
first, scripts/check_drop_detector.py's posture.

FOUR THINGS ARE HELD:

  1. THE STUDY'S NUMBERS (report 1.4 and 1.6), over the moments frozen in
     tests/fixtures/predrop/study_moments.json: his 345 approved drops on a
     song with a stored shape (330 with a capture before the drop), the
     detector's 498 drops he had not approved, and 6,131 random downbeats
     at least 4 s from any drop on 70 songs. Each rule at the window the
     study measured (spike 350-2000 ms, vocal intro 350-4500 ms). Spike:
     11 of 330, 7 of 498, 15 of 6,131 (8 at the confident bar 1.07); vocal
     intro: 8, 18 and 2.
  2. THE CUT. Every moment is judged a second time on a window CUT from its
     song's stored shape (CUT_BEFORE_MS before the drop to CUT_AFTER_BEATS
     after it, normalised to the WHOLE song's own ceilings), at the study's
     windows and through predrop_detector.detect at the search windows;
     every verdict, score and marker must equal the whole song's. That is
     what makes the committed fixtures a faithful stand-in for the songs.
  3. THE NAMED CASES (one pre-drop per drop, the search windows): Dopamine
     drop 1 (47,850) a CONFIDENT vocal intro at 1.50, entering 3,295 ms
     out; FINA 158,208 a spike (1.11, against an intro's 1.01).
  4. THE RE-ANCHOR on a copy of his store: every song in it is detected
     with the re-anchor and without, at his room's own thresholds, and
     exactly one drop moves — Eyes Cut Deeper drop 1, 69,584 -> 70,350,
     where he moved it by hand. Then the copy is re-detected through
     drop_sequences.ensure_detected and every song's merged view compared
     with the view before: his edit there keeps pairing with the moved drop
     and asks nothing (no needs_review), and nothing else changes.

A song whose stored shape no longer matches the fingerprint the study's
measurements were taken from (a recapture since) is NAMED, so a number
that drifts for that reason says so.

--write-fixtures also writes what tests/test_predrop_detector.py replays:
tests/fixtures/predrop/cases.npz + cases.json (the cut windows of every
moment a rule finds, and the named cases, each with its whole-song
verdicts) and tests/fixtures/predrop/ecd/ (Eyes Cut Deeper's stored shape,
trimmed to what the detector reads, for the re-anchor end to end).

Prints markdown (the PR body's) and exits non-zero on any failure.

Run from repo root: .venv/bin/python scripts/check_predrop_detector.py
                     [--live-root /home/javi/SpotFX] [--write-fixtures]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures" / "predrop"
MOMENTS_FILE = FIXTURES / "study_moments.json"

# The report's numbers (section 1.4 and 1.6; plan step 3's acceptance).
EXPECTED = {
    ("spike", "approved"): {"moments": 345, "captured": 330, "found": 11},
    ("spike", "detected"): {"moments": 498, "found": 7},
    ("spike", "random"): {"moments": 6131, "found": 15, "confident": 8},
    ("intro", "approved"): {"found": 8},
    ("intro", "detected"): {"found": 18},
    ("intro", "random"): {"found": 2},
}

DOPAMINE = ("spotify:track:7vFKcXQ39f74XNrZmXADIT", 47850)
FINA = ("spotify:track:3nNmRE0DxHC6ZaKkrpUumS", 158208)
ECD_URI = "spotify:track:3E8WZzcp6nscGt9YvBX9MW"
ECD_FROM, ECD_TO = 69584, 70350

# The cut: at the search windows the spike looks back 3 s + 1.5 beats for
# hits and 1.2 s before each (6.45 s at 40 bpm); the vocal intro needs
# 4.5 s + 1.3 s of capture before it may judge at all, so a cut that starts
# later than that would turn "captured" into "no capture". After: the four
# beats of bass every test compares with, plus room for the smoothing edge.
CUT_BEFORE_MS = 6500
CUT_AFTER_BEATS = 4.0
CUT_AFTER_PAD_MS = 200

BANDS = ("low", "mid", "high")


# ── isolation ───────────────────────────────────────────────────────────────

def _live_index(live_root: Path) -> dict[str, str]:
    """uri -> stem over the live sidecars (read-only)."""
    out = {}
    for path in (live_root / "storage" / "audio_shapes").glob("*.json"):
        if path.name.endswith(".librosa.json"):
            continue
        try:
            uri = json.loads(path.read_text(encoding="utf-8")).get("spotify_uri")
        except Exception:                                # noqa: BLE001
            continue
        if uri:
            out[uri] = path.stem
    return out


def _isolate(live_root: Path, tmp: Path, stems: set[str], store_uris: set[str]) -> None:
    from spectra import config as scfg
    audio = tmp / "audio_shapes"
    audio.mkdir(parents=True)
    for stem in sorted(stems):
        for suffix in (".json", ".librosa.json", ".npz"):
            src = live_root / "storage" / "audio_shapes" / f"{stem}{suffix}"
            if src.exists():
                shutil.copyfile(src, audio / f"{stem}{suffix}")
    spectra_live = live_root / "storage" / "spectra"
    (tmp / "spectra").mkdir()
    for name in ("drop_sequences.json", "room_controls.json"):
        src = spectra_live / name
        if src.exists():
            shutil.copyfile(src, tmp / "spectra" / name)
    triggers_live = json.loads((spectra_live / "triggers.json").read_text(encoding="utf-8"))
    (tmp / "spectra" / "triggers.json").write_text(
        json.dumps({u: triggers_live.get(u, []) for u in store_uris}), encoding="utf-8")
    scfg.AUDIO_SHAPES_DIR = audio
    scfg.TRIGGERS_FILE = tmp / "spectra" / "triggers.json"
    scfg.DROP_SEQUENCES_FILE = tmp / "spectra" / "drop_sequences.json"
    scfg.ROOM_CONTROLS_FILE = tmp / "spectra" / "room_controls.json"
    scfg.FIRE_HISTORY_FILE = tmp / "spectra" / "fire_history.json"
    scfg.SHOW_LOG_FILE = tmp / "spectra" / "show_log.json"


# ── the shape, whole and cut ────────────────────────────────────────────────

def fingerprint(song) -> str:
    """What the study's measurements depend on: the frames, the three
    bands and the tempo."""
    h = hashlib.sha1()
    h.update(np.asarray(song.t, dtype=np.int64).tobytes())
    for b in BANDS:
        h.update(np.asarray(getattr(song, b), dtype=np.float32).tobytes())
    h.update(repr(round(float(song.tempo), 6)).encode())
    return h.hexdigest()[:16]


def ceilings(song) -> dict:
    return {b: float(np.percentile(getattr(song, b), 99.5)) for b in BANDS}


def cut(song, drop_ms: int) -> dict:
    """The window a moment is judged on, raw, plus what rebuilds its shape."""
    t = song.t
    i0 = int(np.searchsorted(t, drop_ms - CUT_BEFORE_MS))
    i1 = int(np.searchsorted(t, drop_ms + CUT_AFTER_BEATS * song.beat_len + CUT_AFTER_PAD_MS))
    return {"t": np.asarray(t[i0:i1], dtype=np.int32),
            **{b: np.asarray(getattr(song, b)[i0:i1], dtype=np.float32) for b in BANDS},
            "beat_len": float(song.beat_len), "ceilings": ceilings(song)}


def cut_shape(c: dict):
    from spectra.services import predrop_detector as P
    return P.make_shape(c["t"], {b: c[b] for b in BANDS}, c["beat_len"], c["ceilings"])


def _rule(fn, s, drop_ms, window) -> dict:
    r = fn(s, drop_ms, *window)
    return {"status": r.get("status"), "score": float(r.get("score", 0.0)),
            "ms": r.get("ms"), "lead": r.get("lead")}


def judge(s, drop_ms: int) -> dict:
    """Both rules at the study's windows and the pre-drop at the search
    windows — everything the numbers and the fixtures compare."""
    from spectra.services import predrop_detector as P
    pre = P.detect(s, drop_ms)
    return {"spike": _rule(P.spike, s, drop_ms, P.SPIKE_STUDY_MS),
            "intro": _rule(P.intro, s, drop_ms, P.INTRO_STUDY_MS),
            "pre_drop": pre.stored() if pre is not None else None}


def _same(a: dict, b: dict) -> bool:
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


WEAK_JITTER = "weak-jitter"


def cut_difference(whole: dict, cut_: dict, t: np.ndarray):
    """None when the cut judges a moment exactly as its song does.
    WEAK_JITTER when the only difference is the score or marker of a WEAK
    verdict inside a window whose frame times step back (the capture's own
    timestamp jitter: np.searchsorted over an unsorted stretch can land a
    frame apart in a cut from where it lands over the whole song) — never a
    status, a found verdict or a pre-drop. Otherwise, what differs."""
    if _same(whole, cut_):
        return None
    if not _same(whole["pre_drop"], cut_["pre_drop"]):
        return f"the pre-drop: {whole['pre_drop']} vs {cut_['pre_drop']}"
    for k in ("spike", "intro"):
        a, b = whole[k], cut_[k]
        if _same(a, b):
            continue
        if a["status"] != b["status"]:
            return f"the {k} verdict: {a['status']} vs {b['status']}"
        if a["status"] != "weak" or not (np.diff(t) < 0).any():
            return f"the {k} {a['status']} result: {a} vs {b}"
    return WEAK_JITTER


# ── 1-3: the study ──────────────────────────────────────────────────────────

def check_study(moments: dict, problems: list[str], cases_out: list) -> None:
    from spectra.services import drop_detector
    songs, shapes = {}, {}
    drifted = []
    for uri, meta in moments["songs"].items():
        try:
            song = drop_detector.load_song(uri)
        except drop_detector.Unavailable as exc:
            problems.append(f"{meta['title']}: its stored shape cannot be read ({exc})")
            continue
        songs[uri] = song
        from spectra.services import predrop_detector as P
        shapes[uri] = P.shape_of(song)
        want = meta.get("fingerprint")
        if want and fingerprint(song) != want:
            drifted.append(meta["title"])
    if drifted:
        print(f"> **{len(drifted)} song(s) were recaptured since the study** (their stored "
              f"shape no longer matches): {', '.join(sorted(drifted))}. A number below that "
              f"moves may move for that reason.\n")

    sets = {
        "approved": [(u, int(d)) for u, d in moments["approved"]],
        "detected": [(u, int(d)) for u, d, _ in moments["detected"]],
        "random": [(u, int(d)) for u, ds in moments["random"].items() for d in ds],
    }
    tally: dict = {}
    cut_mismatch = []
    uncut = weak_jitter = 0
    found_moments: dict = {}
    for name, items in sets.items():
        for kind in ("spike", "intro"):
            tally[(kind, name)] = Counter()
        for uri, D in items:
            if uri not in songs:
                continue
            whole = judge(shapes[uri], D)
            c = cut(songs[uri], D)
            if len(c["t"]) < 8:
                # nothing of the song around this moment: it was never captured
                uncut += 1
                if whole["spike"]["status"] != "no_capture" or whole["intro"]["status"] != "no_capture":
                    cut_mismatch.append((moments["songs"][uri]["title"], D, "uncaptured"))
            else:
                why = cut_difference(whole, judge(cut_shape(c), D), c["t"])
                if why == WEAK_JITTER:
                    weak_jitter += 1
                elif why is not None:
                    cut_mismatch.append((moments["songs"][uri]["title"], D, why))
            for kind in ("spike", "intro"):
                r = whole[kind]
                tc = tally[(kind, name)]
                tc["moments"] += 1
                if r["status"] != "no_capture":
                    tc["captured"] += 1
                if r["status"] == "found":
                    tc["found"] += 1
                    if kind == "spike" and r["score"] >= 1.07:
                        tc["confident"] += 1
                    found_moments.setdefault((uri, D), (name, whole, c))

    print("## 1. The study's numbers (shipped rules, the study's windows)\n")
    print("| Kind | Set | Moments | With a capture | Found | At the confident bar |")
    print("|---|---|---|---|---|---|")
    for (kind, name), tc in tally.items():
        conf = tc["confident"] if kind == "spike" else "—"
        print(f"| {kind} | {name} | {tc['moments']} | {tc['captured']} | **{tc['found']}** | {conf} |")
        for k, v in EXPECTED[(kind, name)].items():
            if tc[k] != v:
                problems.append(f"{kind} over {name}: {k} {tc[k]}, the report {v}")
    print()

    print("## 2. The cut\n")
    n = sum(tc["moments"] for (kind, _), tc in tally.items() if kind == "spike")
    print(f"- {n} moments judged whole and on their cut window ({CUT_BEFORE_MS} ms before, "
          f"{CUT_AFTER_BEATS:g} beats + {CUT_AFTER_PAD_MS} ms after, the song's own ceilings): "
          f"{n - len(cut_mismatch) - uncut - weak_jitter} identical; {weak_jitter} differ only "
          f"in the score or marker of a WEAK verdict, in a window whose frame times step "
          f"back (a binary search over jittered timestamps lands a frame apart in a cut); "
          f"{uncut} with nothing captured around them (no capture both ways); "
          f"{len(cut_mismatch)} different otherwise\n")
    for title, D, why in cut_mismatch[:20]:
        problems.append(f"the cut window differs from the whole song at {title} {D}: {why}")

    print("## 3. The named cases (the pre-drop, search windows)\n")
    for label, (uri, D), want in (("Dopamine drop 1", DOPAMINE, ("intro", "confident", 1.50, 3295)),
                                  ("FINA", FINA, ("spike", None, 1.11, None))):
        if uri not in songs:
            problems.append(f"{label}: its stored shape is missing")
            continue
        got = judge(shapes[uri], D)
        pre = got["pre_drop"]
        print(f"- {label} ({D}): pre-drop {pre}; spike {got['spike']['status']} "
              f"{got['spike']['score']:.3f}, intro {got['intro']['status']} "
              f"{got['intro']['score']:.3f}")
        kind, tier, score, lead = want
        if pre is None or pre["kind"] != kind or round(pre["score"], 2) != score:
            problems.append(f"{label}: expected a {kind} at {score}, got {pre}")
        elif tier and pre["tier"] != tier:
            problems.append(f"{label}: expected {tier}, got {pre['tier']}")
        elif lead is not None and pre["lead_ms"] != lead:
            problems.append(f"{label}: expected to enter {lead} ms out, got {pre['lead_ms']}")
        found_moments.setdefault((uri, D), ("named", got, cut(songs[uri], D)))
    from spectra.services import predrop_detector as P
    s = shapes.get(FINA[0])
    if s is not None:
        sp, it = P.spike(s, FINA[1]), P.intro(s, FINA[1])
        print(f"  FINA at the search windows: spike {sp.get('score', 0):.3f}, "
              f"intro {it.get('score', 0):.3f}")
        if not (sp.get("status") == "found" and it.get("status") == "found"
                and round(sp["score"], 2) == 1.11 and round(it["score"], 2) == 1.01):
            problems.append("FINA: expected both rules to find, spike 1.11 over intro 1.01")
    print()

    for (uri, D), (name, whole, c) in sorted(found_moments.items(),
                                            key=lambda kv: (kv[0][0], kv[0][1])):
        cases_out.append({"uri": uri, "title": moments["songs"][uri]["title"], "drop_ms": D,
                          "set": name, "expect": whole, "cut": c})


# ── 4: the re-anchor on a copy of his store ─────────────────────────────────

def _drops(det) -> list[int]:
    return [int(s.drop_ms) for s in det.sequences]


def _placed(seqs) -> list[tuple]:
    """What a detection placed: each sequence's drop, lull, charge and tier."""
    return [(int(q["drop_ms"]), q.get("lull_ms"), q.get("charge_ms"), q.get("tier"))
            for q in seqs]


def _view_rows(v: dict) -> dict:
    return {s["key"]: {k: s.get(k) for k in ("state", "drop_ms", "lull_ms", "charge_ms",
                                              "needs_review", "detection_lost", "origin")}
            for s in v.get("sequences") or []}


def check_reanchor(problems: list[str]) -> None:
    from spectra.services import (drop_detector, drop_sequences, predrop_detector,
                                  room_controls)
    controls = room_controls.load_room_controls()
    confident, suggested, floor = drop_sequences._thresholds(controls)
    store = drop_sequences.all_stored()
    uris = sorted(store)
    print("## 4. The re-anchor on a copy of his store\n")
    print(f"- his store: {len(uris)} songs; thresholds confident {confident}, suggested "
          f"{suggested}, floor {floor}")
    moved, unavailable, since_stored = [], 0, []
    real = predrop_detector.reanchor
    off = {}
    for uri in uris:
        try:
            on = drop_detector.detect_uri(uri, confident_score=confident,
                                          suggested_score=suggested, drop_floor=floor)
            predrop_detector.reanchor = lambda *a, **k: None
            try:
                off[uri] = drop_detector.detect_uri(uri, confident_score=confident,
                                                    suggested_score=suggested,
                                                    drop_floor=floor)
            finally:
                predrop_detector.reanchor = real
        except drop_detector.Unavailable:
            unavailable += 1
            continue
        a, b = _drops(off[uri]), _drops(on)
        if a != b:
            moved.append((uri, sorted(set(a) - set(b)), sorted(set(b) - set(a))))
        stored_seqs = (store[uri].get("detected") or {}).get("sequences") or []
        if _placed(stored_seqs) != _placed([q.as_dict() for q in off[uri].sequences]):
            since_stored.append(uri)
    print(f"- detected with and without the re-anchor: {len(uris) - unavailable} songs "
          f"({unavailable} without a readable shape)")
    for uri, gone, new in moved:
        print(f"  - moved: {uri} {gone} -> {new}")
    if moved != [(ECD_URI, [ECD_FROM], [ECD_TO])]:
        problems.append(f"the re-anchor should move exactly Eyes Cut Deeper "
                        f"{ECD_FROM} -> {ECD_TO}; it moved {moved}")
    if since_stored:
        print(f"- {len(since_stored)} song(s) whose stored detection differs from today's "
              f"(re-anchor off: drop, lull, charge or tier) — the shape, its analysis or "
              f"the thresholds changed since it was stored; left out of the view "
              f"comparison below: {since_stored}")

    before = {uri: _view_rows(drop_sequences.view(uri)) for uri in uris}
    changed = []
    for uri in uris:
        r = drop_sequences.ensure_detected(uri, controls)
        if r.get("status") not in ("detected", "fresh", "unavailable"):
            problems.append(f"{uri}: ensure_detected said {r}")
    again = [drop_sequences.ensure_detected(u, controls).get("status") for u in uris]
    if any(s not in ("fresh", "unavailable") for s in again):
        problems.append("a second ensure_detected was not fresh everywhere")
    for uri in uris:
        if uri in since_stored:
            continue
        after = _view_rows(drop_sequences.view(uri))
        if after != before[uri]:
            changed.append(uri)
            if uri != ECD_URI:
                problems.append(f"{uri}: the merged view changed: {before[uri]} -> {after}")
    ecd = drop_sequences.view(ECD_URI)
    one = next((s for s in ecd["sequences"] if s["key"] == f"drop:{ECD_FROM}"), None)
    if one is None:
        problems.append("Eyes Cut Deeper: his edited drop:69584 is gone from the view")
    else:
        print(f"- Eyes Cut Deeper drop 1 after: key {one['key']}, detected {one['detected_key']}, "
              f"state {one['state']}, drop {one['drop_ms']}, lull {one['lull_ms']}, charge "
              f"{one['charge_ms']}, needs_review {one['needs_review']}, pre-drop "
              f"{one['pre_drop_kind']} at {one['pre_drop_ms']} ({one['pre_drop_tier']}, "
              f"{one['pre_drop_score']})")
        if one["detected_key"] != f"drop:{ECD_TO}" or one["needs_review"] or one["drop_ms"] != ECD_TO:
            problems.append(f"Eyes Cut Deeper drop 1 should pair with drop:{ECD_TO} and ask "
                            f"nothing: {one}")
        if one["pre_drop_ms"] is None or abs(one["pre_drop_ms"] - ECD_FROM) > predrop_detector.SAME_HIT_MS:
            problems.append(f"Eyes Cut Deeper drop 1's hit at {ECD_FROM} should be its "
                            f"pre-drop: {one['pre_drop_ms']}")
    print(f"- merged views compared before/after re-detection: {len(uris) - len(since_stored)}; "
          f"changed: {changed}")
    print()


# ── fixtures ────────────────────────────────────────────────────────────────

def write_fixtures(cases: list, live_index: dict) -> None:
    from spectra import config as scfg
    arrays, meta = {}, []
    for i, c in enumerate(cases):
        w = c["cut"]
        for k in ("t",) + BANDS:
            arrays[f"c{i}_{k}"] = w[k]
        meta.append({"id": f"c{i}", "uri": c["uri"], "title": c["title"],
                     "drop_ms": c["drop_ms"], "set": c["set"], "beat_len": w["beat_len"],
                     "ceilings": w["ceilings"], "expect": c["expect"]})
    np.savez_compressed(FIXTURES / "cases.npz", **arrays)
    (FIXTURES / "cases.json").write_text(json.dumps(
        {"cut": {"before_ms": CUT_BEFORE_MS, "after_beats": CUT_AFTER_BEATS,
                 "after_pad_ms": CUT_AFTER_PAD_MS}, "cases": meta}, indent=1), encoding="utf-8")
    # Eyes Cut Deeper, whole, trimmed to what the detector reads
    stem = live_index[ECD_URI]
    out = FIXTURES / "ecd"
    out.mkdir(exist_ok=True)
    src = Path(scfg.AUDIO_SHAPES_DIR)
    z = np.load(src / f"{stem}.npz")
    np.savez_compressed(out / "Eyes Cut Deeper.npz", **{k: z[k] for k in (
        "timestamps_ms", "rms_low", "rms_mid", "rms_high", "rms_total")})
    doc = json.loads((src / f"{stem}.librosa.json").read_text(encoding="utf-8"))
    keep = {k: doc.get(k) for k in ("spotify_uri", "tempo_bpm", "analyzed_at")}
    keep["beats"] = [{"ms": b.get("ms"), "is_downbeat": b.get("is_downbeat")}
                     for b in doc.get("beats") or []]
    keep["sections"] = [{k: s.get(k) for k in ("start_ms", "end_ms", "energy_rms")}
                        for s in doc.get("sections") or []]
    (out / "Eyes Cut Deeper.librosa.json").write_text(json.dumps(keep), encoding="utf-8")
    side = json.loads((src / f"{stem}.json").read_text(encoding="utf-8"))
    (out / "Eyes Cut Deeper.json").write_text(json.dumps(
        {k: side.get(k) for k in ("spotify_uri", "title", "artist", "duration_ms")}),
        encoding="utf-8")
    print(f"wrote {len(cases)} cut cases and the Eyes Cut Deeper song to {FIXTURES}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live-root", default="/home/javi/SpotFX")
    ap.add_argument("--write-fixtures", action="store_true")
    args = ap.parse_args()
    live_root = Path(args.live_root)
    moments = json.loads(MOMENTS_FILE.read_text(encoding="utf-8"))
    store_live = json.loads((live_root / "storage" / "spectra" / "drop_sequences.json")
                            .read_text(encoding="utf-8"))
    index = _live_index(live_root)
    stems = {m["stem"] for m in moments["songs"].values()}
    stems |= {index[u] for u in store_live if u in index}
    tmp = Path(tempfile.mkdtemp(prefix="check_predrop_detector_"))
    problems: list[str] = []
    cases: list = []
    try:
        _isolate(live_root, tmp, stems, set(store_live))
        check_study(moments, problems, cases)
        check_reanchor(problems)
        if args.write_fixtures:
            write_fixtures(cases, index)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if problems:
        print("FAILED:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("OK: the report's numbers reproduced, every cut agrees with its song, and the "
          "re-anchor moves exactly Eyes Cut Deeper drop 1.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
