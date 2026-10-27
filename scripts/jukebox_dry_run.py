#!/usr/bin/env python3
"""
Jukebox dry run: print the next N program items for a set playlist — what a
night would play, set songs and jukebox slots in order, with start times
(data/jukebox-plan/report.md §9, PR 1.1's acceptance).

READ-ONLY BY CONSTRUCTION. With --playlist it reads the playlist through
services/jukebox/gateway.py's ReadOnlyGateway, which refuses every method
that could change playback, the queue or a playlist before it reaches
Spotify; nothing plays, nothing is queued, nothing is written. It uses the
same Spotify token SpotFX does (storage/.spotify_token_cache), so run it from
the checkout that holds it. With --fixture it reads a local JSON list of
songs instead and needs no Spotify at all.

The program comes from services/jukebox/program.py's `project()` — the same
function the engine's own commit decision uses — so this IS what a night
would do, not a model of it.

  .venv/bin/python scripts/jukebox_dry_run.py --playlist <link>
  .venv/bin/python scripts/jukebox_dry_run.py --fixture songs.json --every 3 --line 4

Program settings default to the saved ones (storage/jukebox.json); any flag
overrides them for this run only. --line N puts N placeholder jukebox songs
in the line so you can see where they would play; with none, slots show as
"open" (they pass if nobody has a song waiting).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.jukebox import Cursor, ManualSlot, ProgramConfig, SetItem  # noqa: E402
from services.jukebox import program, store  # noqa: E402

PLACEHOLDER_S = 210          # a placeholder jukebox song's length (his library's median ~3:35)


def _mmss(ms: int) -> str:
    s = max(0, int(ms) // 1000)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def _config(args: argparse.Namespace) -> ProgramConfig:
    base = store.load_config().model_dump(mode="json")
    if args.mode:
        base["mode"] = args.mode
    if args.every is not None:
        base["every"] = args.every
    if args.run is not None:
        base["run"] = args.run
    if args.run_out:
        base["run_out"] = args.run_out
    if args.manual:
        slots = []
        for spec in args.manual:
            uri, _, count = spec.rpartition(":")
            if not uri or not count.isdigit():
                uri, count = spec, "1"
            slots.append(ManualSlot(after_uri=uri, count=int(count)).model_dump())
        base["manual"] = slots
        base["mode"] = "manual"
    if args.playlist:
        base["playlist"] = args.playlist
    return ProgramConfig.model_validate(base)


def _read_set(args: argparse.Namespace, cfg: ProgramConfig) -> tuple[str, list[SetItem]]:
    if args.fixture:
        rows = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
        return Path(args.fixture).name, [SetItem(**r) for r in rows]
    from services.jukebox.gateway import JukeboxGateway, ReadOnlyGateway
    gw = ReadOnlyGateway(JukeboxGateway())
    info = gw.resolve_playlist(cfg.playlist)
    if not info:
        raise SystemExit(f"couldn't read the playlist {cfg.playlist!r}")
    return info.get("name") or info["id"], [SetItem(**r) for r in gw.playlist_items(info["id"])]


def render(name: str, cfg: ProgramConfig, items: list[SetItem], line: int, count: int) -> str:
    fills = [program.Fill(entry_id=f"placeholder-{i}", uri="", title=f"(jukebox song {i + 1})",
                          duration_ms=PLACEHOLDER_S * 1000) for i in range(line)]
    upcoming = program.with_start_times(
        program.project(cfg, items, Cursor(), fills, count), 0)
    lap = program.lap(cfg, items)
    rule = {"auto": f"{cfg.run} jukebox slot(s) after every {cfg.every} set song(s)",
            "jukebox_first": "jukebox first (the set fills the gaps)",
            "manual": f"manual slots after {len(cfg.manual)} set song(s)"}[cfg.mode]
    slots = "as many as the line holds" if lap.unbounded else f"{lap.slots} jukebox slots"
    out = [f"Set: {name} — {len(items)} songs; {rule}; when it runs out: {cfg.run_out}",
           f"One pass through the set: {lap.set_songs} set songs · {slots}",
           f"Line: {line} placeholder song(s)", ""]
    for note in lap.notes:
        out.append(f"note: {note}")
    for n, it in enumerate(upcoming, 1):
        at = _mmss(it.starts_in_ms or 0)
        if it.kind == "set":
            who = f"{it.artist} — {it.title}" if it.artist else it.title
            out.append(f"{n:>3}  {at:>8}  SET {it.set_index + 1:>3}  {who}")
        elif it.kind == "jukebox":
            out.append(f"{n:>3}  {at:>8}  JUKEBOX   {it.title}")
        else:
            out.append(f"{n:>3}  {at:>8}  JUKEBOX   (open slot: passes if nobody has a song waiting)")
    if len(upcoming) < count:
        out.append("     — the program ends here —")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--playlist", help="a Spotify playlist link, URI or id (read-only)")
    src.add_argument("--fixture", help="a JSON list of {uri, title, artist, duration_ms}")
    ap.add_argument("--mode", choices=("auto", "jukebox_first", "manual"))
    ap.add_argument("--every", type=int, help="auto: a slot after every N set songs (1-5)")
    ap.add_argument("--run", type=int, help="auto: K slots in a row (1-3)")
    ap.add_argument("--manual", action="append", metavar="URI[:COUNT]",
                    help="a manual slot run after this set song (repeatable)")
    ap.add_argument("--run-out", choices=("again", "jukebox_only", "end"))
    ap.add_argument("--line", type=int, default=0, help="placeholder jukebox songs waiting")
    ap.add_argument("--count", type=int, default=20)
    args = ap.parse_args(argv)
    cfg = _config(args)
    if not args.fixture and not cfg.playlist.strip():
        ap.error("no playlist: pass --playlist or --fixture (or save one in the program settings)")
    name, items = _read_set(args, cfg)
    if not items:
        print(f"Set: {name} — no playable songs")
        return 1
    print(render(name, cfg, items, max(0, args.line), max(1, args.count)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
