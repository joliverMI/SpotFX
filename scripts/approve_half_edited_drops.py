"""APPROVE HIS HALF-EDITED DROPS, ONCE (2026-10-28 — the Drops panel
proposal's Q8, his answer: "Approve them once under the new rule. I list
them first and you say yes").

Before ANY EDIT APPROVES (spectra/services/drop_sequences.py's own section
of that name) a part edit approved only the part he tapped, so his store can
hold drops he touched but left part-way: a part approved and the drop still
waiting; the drop approved and its build still waiting; the drop switched off
with the rest waiting; a pre-drop relabelled and nothing approved. Under the
new rule none of those can arise any more — this script brings the old ones
level, ONCE, and only after he has seen the list.

EACH DROP IS LISTED UNDER WHY IT IS HALF-EDITED (`GROUPS`), so he can say
yes to some groups and not others (`--only`):
  drop_waiting          a part approved, the drop still waiting (his Q8 words)
  build_waiting         the drop approved alone, its charge/lull still waiting
  drop_off              the drop switched off, the rest still waiting
  pre_drop_placed       he moved or placed the pre-drop and never approved it
  pre_drop_found_later  the detector found the pre-drop AFTER he approved the
                        drop — he has not seen it; approving it is a choice
  his_pre_drop          one of HIS OWN drops' pre-drops he moved or relabelled

DRY RUN BY DEFAULT: lists every such drop (song, drop time, its group, each
part before → after) and writes nothing. `--apply` backs the store up beside
itself (`drop_sequences.json.bak-half-edited-<stamp>`) and approves exactly
the drops the dry run listed, each through the store's own
`_approve_edited` (one locked write per song) — the same code an edit runs
now. A drop he switched off stays off (Q6: reviewed, plays nothing).

His OWN drops' pre-drops (overrides "mine:<id>") are listed too when he
moved or relabelled one without approving it; `--apply` approves those
pre-drops. Removed (dismissed) drops are never touched, and neither is a
sequence he added (every part of it is his already).

  .venv/bin/python scripts/approve_half_edited_drops.py \\
      [--file storage/spectra/drop_sequences.json] [--profiles storage/profiles] \\
      [--json] [--only GROUP,GROUP] [--apply]

`--file` names the store (default: the configured one); `--profiles` a song
profile folder to name songs by title. Read-only unless `--apply`.
"""
from __future__ import annotations

import argparse
import copy
import json
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from spectra import config  # noqa: E402


def _titles(folder: Path | None) -> dict:
    out: dict[str, str] = {}
    if folder is None or not folder.is_dir():
        return out
    for f in folder.glob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        uri = d.get("spotify_uri")
        if isinstance(uri, str):
            out[uri] = f"{d.get('artist') or '?'} — {d.get('title') or '?'}"
    return out


def _fmt(ms) -> str:
    if ms is None:
        return "?"
    m = int(ms) // 60000
    return f"{m}:{(int(ms) - m * 60000) / 1000:04.1f}"


def _detected_parts(ds, entry: dict, okey: str, ov: dict) -> dict | None:
    """The four parts as the view reads them for this override (None when
    the override is not one this script handles)."""
    try:
        _key, det = ds._resolve_detected_key(entry, okey)
    except ds.SequenceNotFound:
        det = None
    base = det or ov.get("detected") or {}
    eff = ds._effective(base, ov)
    pre = ds._pre_drop_of(ds._base_pre(base), ov)
    stored = ov.get("parts") if isinstance(ov.get("parts"), dict) else None
    legacy = ds._legacy_his(ov)
    out = {}
    for h in ("charge", "lull"):
        if ov.get(f"{h}_off"):
            out[h] = ds.PART_OFF
        elif eff.get(h) is None:
            out[h] = ds.PART_ABSENT
        elif stored is not None:
            out[h] = ds.PART_ON if stored.get(h) == ds.PART_ON else ds.PART_WAITING
        else:
            out[h] = ds.PART_ON if legacy else ds.PART_WAITING
    if pre["off"]:
        out["pre_drop"] = ds.PART_OFF
    elif pre["ms"] is None:
        out["pre_drop"] = ds.PART_ABSENT
    elif stored is not None:
        out["pre_drop"] = ds.PART_ON if stored.get(ds.PRE_DROP) == ds.PART_ON else ds.PART_WAITING
    else:
        out["pre_drop"] = ds.PART_ON if (legacy and pre["moved"]) else ds.PART_WAITING
    if stored is not None and stored.get("drop") == ds.PART_OFF:
        out["drop"] = ds.PART_OFF
    elif stored is not None:
        out["drop"] = ds.PART_ON if stored.get("drop") == ds.PART_ON else ds.PART_WAITING
    else:
        out["drop"] = ds.PART_ON if legacy else ds.PART_WAITING
    out["drop_ms"] = eff.get("drop")
    return out


GROUPS = ("drop_waiting", "build_waiting", "drop_off", "pre_drop_placed",
          "pre_drop_found_later", "his_pre_drop")


def _group(ds, ov: dict, before: dict, live: list) -> str:
    waiting = [p for p in live if before[p] == ds.PART_WAITING]
    if before["drop"] == ds.PART_OFF:
        return "drop_off"
    if before["drop"] == ds.PART_WAITING:
        return "drop_waiting"
    if any(p in ("charge", "lull") for p in waiting):
        return "build_waiting"
    if ov.get("pre_drop_ms") is not None or "pre_drop_kind" in ov:
        return "pre_drop_placed"
    return "pre_drop_found_later"


def _touched(ov: dict) -> bool:
    """He edited this override (anything of his beyond the snapshot)."""
    return any(k not in ("detected", "at") for k in ov)


def find(ds, data: dict) -> list[dict]:
    """Every half-edited drop in the store (module docstring)."""
    found: list[dict] = []
    for uri, entry in sorted(data.items()):
        if not isinstance(entry, dict):
            continue
        for okey, ov in sorted((entry.get("overrides") or {}).items()):
            if not isinstance(ov, dict) or ov.get("state") == ds.STATE_DISMISSED:
                continue
            if okey.startswith(ds.MINE_PREFIX):
                edited = (ov.get("pre_drop_ms") is not None or "pre_drop_kind" in ov)
                parts = ov.get("parts") if isinstance(ov.get("parts"), dict) else {}
                if (edited and not ov.get("pre_drop_off")
                        and parts.get(ds.PRE_DROP) != ds.PART_ON):
                    found.append({"uri": uri, "key": okey, "kind": "his_pre_drop",
                                  "group": "his_pre_drop", "drop_ms": None,
                                  "before": {"pre_drop": ds.PART_WAITING},
                                  "after": {"pre_drop": ds.PART_ON}})
                continue
            if drop_key_ms(ds, okey) is None or not _touched(ov):
                continue
            before = _detected_parts(ds, entry, okey, ov)
            if before is None:
                continue
            live = [p for p in ds.PARTS if before[p] not in (ds.PART_OFF, ds.PART_ABSENT)]
            if not any(before[p] == ds.PART_WAITING for p in live):
                continue
            after = {p: (ds.PART_ON if p in live else before[p]) for p in ds.PARTS}
            found.append({"uri": uri, "key": okey, "kind": "detection",
                          "group": _group(ds, ov, before, live),
                          "drop_ms": before["drop_ms"],
                          "before": {p: before[p] for p in ds.PARTS}, "after": after})
    return found


def drop_key_ms(ds, key: str):
    return ds.drop_detector.key_ms(key)


def apply(ds, found: list[dict]) -> int:
    by_uri: dict[str, list[dict]] = {}
    for f in found:
        by_uri.setdefault(f["uri"], []).append(f)
    n = 0
    for uri, items in by_uri.items():
        def fn(entry, items=items):
            done = 0
            for f in items:
                ovs = entry.get("overrides") or {}
                ov = ovs.get(f["key"])
                if not isinstance(ov, dict):
                    continue
                if f["kind"] == "his_pre_drop":
                    ov.setdefault("parts", {})[ds.PRE_DROP] = ds.PART_ON
                else:
                    ds._approve_edited(entry, f["key"])
                ov["at"] = ds._now_ms()
                done += 1
            return done
        n += ds._mutate(uri, fn)
    return n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", type=Path, default=None, help="the drop store (default: configured)")
    ap.add_argument("--profiles", type=Path, default=None, help="song profiles, to name songs")
    ap.add_argument("--json", action="store_true", help="print the list as JSON")
    ap.add_argument("--only", default=None,
                    help=f"comma-separated groups to list/approve ({', '.join(GROUPS)})")
    ap.add_argument("--apply", action="store_true", help="approve them (backs the store up first)")
    args = ap.parse_args(argv)
    if args.file is not None:
        config.DROP_SEQUENCES_FILE = args.file.resolve()
    from spectra.services import drop_sequences as ds
    ds.reset()
    path = Path(config.DROP_SEQUENCES_FILE)
    if not path.exists():
        print(f"no drop store at {path}")
        return 1
    data = json.loads(path.read_text(encoding="utf-8"))
    found = find(ds, copy.deepcopy(data))
    if args.only:
        only = {g.strip() for g in args.only.split(",") if g.strip()}
        unknown = only - set(GROUPS)
        if unknown:
            print(f"unknown group(s): {', '.join(sorted(unknown))} — one of {', '.join(GROUPS)}")
            return 2
        found = [f for f in found if f["group"] in only]
    titles = _titles(args.profiles)
    if args.json:
        print(json.dumps([{**f, "song": titles.get(f["uri"])} for f in found], indent=2))
    else:
        print(f"{len(found)} half-edited drop{'s' if len(found) != 1 else ''} in {path}:")
        for f in found:
            song = titles.get(f["uri"], f["uri"])
            if f["kind"] == "his_pre_drop":
                print(f"  [{f['group']}] {song}: the pre-drop of your own drop ({f['key']}) — "
                      "moved or relabelled, not approved → approved")
                continue
            parts = ", ".join(f"{p.replace('_', '-')} {f['before'][p]}→{f['after'][p]}"
                              for p in ds.PARTS if f["before"][p] != f["after"][p])
            print(f"  [{f['group']}] {song}: drop at {_fmt(f['drop_ms'])} ({f['key']}) — {parts}")
    if not args.apply:
        print("dry run: nothing written (--apply approves exactly these, after a backup)")
        return 0
    if not found:
        print("nothing to approve")
        return 0
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.name}.bak-half-edited-{stamp}")
    shutil.copy2(path, backup)
    n = apply(ds, found)
    print(f"approved {n} drop{'s' if n != 1 else ''}; the store as it was is at {backup}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
