#!/usr/bin/env python3
"""Copy the alignment job's word timelines beside each song's analysis.

Reads the holding directory the desktop job returned to (for example
/home/javi/fleet-spotfx/data/lyrics-backfill/stage2) and copies
`<stem>.lyrics.json` into storage/audio_shapes, beside `<stem>.librosa.json`.
The format and the rules are the job spec's section 7 and 8
(/home/javi/fleet-spotfx/data/lyrics-step1-measure/desktop-job-spec.md).

A sidecar is copied ONLY when:

  - it is a valid "spotfx.lyrics.v2" timeline for that song, with no job flags,
  - the live WAV's size and mtime and the live `.npz`'s SHA-256 are still
    the ones it was aligned against (a recapture makes every word time wrong),
  - the song still has its `.librosa.json` to score against.

Anything else is refused BY NAME and left alone. The `flagged/` directory is
never read: a song the job set aside is reported as `flagged`, from the
file's existence alone.

Provenance is kept. The sidecar's own lrclib_id, provenance, mode and stamp
are copied verbatim, and an `imported` block is added saying when, from which
file, and that file's hash.

Dry run by default; `--apply` writes. Each write is tmp + rename, so a reader
sees the old file or the new one, never half. Running it again is a no-op for
a song already imported from the same bytes.

Selecting songs: `--songs FILE` for the curated list
(scripts/lyrics_first_songs.json is the first ten), or `--all` for everything
in the holding directory.

    .venv/bin/python scripts/import_lyrics_sidecars.py \\
        --source /home/javi/fleet-spotfx/data/lyrics-backfill/stage2 \\
        --songs scripts/lyrics_first_songs.json            # dry run
    .venv/bin/python scripts/import_lyrics_sidecars.py ... --apply
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from spectra import config  # noqa: E402
from spectra.services import lyrics_sidecar  # noqa: E402

IMPORTER_NAME = "scripts/import_lyrics_sidecars.py"

OUTCOME_WOULD_IMPORT = "would_import"
OUTCOME_IMPORTED = "imported"
OUTCOME_UNCHANGED = "already_imported"
OUTCOME_FLAGGED = "flagged"
OUTCOME_NOT_IN_SOURCE = "not_in_source"
OUTCOME_REFUSED = "refused"


@dataclass
class Outcome:
    stem: str
    outcome: str
    reasons: list[str] = field(default_factory=list)


def _names_from_songs_file(path: Path) -> list[str]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    songs = doc.get("songs") if isinstance(doc, dict) else doc
    if not isinstance(songs, list):
        raise SystemExit(f"{path}: expected a list of songs, or an object with a 'songs' list")
    stems = []
    for entry in songs:
        stem = entry.get("stem") if isinstance(entry, dict) else entry
        if not isinstance(stem, str) or not stem:
            raise SystemExit(f"{path}: every song needs a stem, got {entry!r}")
        stems.append(stem)
    return stems


def _stems_in_source(source: Path) -> list[str]:
    return sorted(p.name[:-len(lyrics_sidecar.SUFFIX)]
                  for p in source.glob(f"*{lyrics_sidecar.SUFFIX}"))


def _write_atomically(path: Path, text: str, mode: Optional[int]) -> None:
    """Tmp + rename in the same directory. The tmp name ends in `.tmp`, so a
    reader scanning `*.json` never picks up a half-written file."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _capture_uri(shapes_dir: Path, stem: str) -> Optional[str]:
    try:
        doc = json.loads((shapes_dir / f"{stem}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    uri = doc.get("spotify_uri") if isinstance(doc, dict) else None
    return uri if isinstance(uri, str) and uri else None


def import_one(stem: str, source: Path, shapes_dir: Path, *, apply: bool,
               now: Optional[str] = None) -> Outcome:
    src = lyrics_sidecar.path_for(source, stem)
    if not src.exists():
        if (source / "flagged" / f"{stem}.flagged.json").exists():
            return Outcome(stem, OUTCOME_FLAGGED)
        return Outcome(stem, OUTCOME_NOT_IN_SOURCE)

    try:
        raw = src.read_bytes()
        doc = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError) as exc:
        return Outcome(stem, OUTCOME_REFUSED, [f"unreadable: {exc}"])

    reasons = lyrics_sidecar.validate(doc, expected_stem=stem)
    if not reasons:
        capture_uri = _capture_uri(shapes_dir, stem)
        if capture_uri is None:
            reasons.append("no_capture_sidecar")
        elif capture_uri != doc.get("uri"):
            reasons.append("uri_does_not_match_capture")
        reasons.extend(lyrics_sidecar.problems_against_capture(doc, shapes_dir, require_wav=True))
        if not (shapes_dir / f"{stem}.librosa.json").exists():
            reasons.append("no_librosa_analysis")
    if reasons:
        return Outcome(stem, OUTCOME_REFUSED, reasons)

    source_hash = lyrics_sidecar.sha256_bytes(raw)
    dest = lyrics_sidecar.path_for(shapes_dir, stem)
    if dest.exists():
        try:
            existing = json.loads(dest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            existing = None
        if isinstance(existing, dict) and (existing.get("imported") or {}).get("source_sha256") == source_hash:
            return Outcome(stem, OUTCOME_UNCHANGED)

    if not apply:
        return Outcome(stem, OUTCOME_WOULD_IMPORT)

    doc["imported"] = {
        "at": now or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_file": str(src),
        "source_sha256": source_hash,
        "importer": IMPORTER_NAME,
    }
    neighbour = shapes_dir / f"{stem}.librosa.json"
    mode = neighbour.stat().st_mode & 0o777
    _write_atomically(dest, json.dumps(doc, ensure_ascii=False), mode)
    return Outcome(stem, OUTCOME_IMPORTED)


def run(source: Path, shapes_dir: Path, stems: list[str], *, apply: bool) -> list[Outcome]:
    return [import_one(stem, source, shapes_dir, apply=apply) for stem in stems]


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", required=True, type=Path,
                        help="the job's holding directory (never its flagged/ subfolder)")
    parser.add_argument("--shapes-dir", type=Path, default=config.AUDIO_SHAPES_DIR,
                        help=f"default: {config.AUDIO_SHAPES_DIR}")
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--songs", type=Path, help="JSON list of the songs to import")
    which.add_argument("--all", action="store_true", help="everything in --source")
    parser.add_argument("--apply", action="store_true", help="write (default: dry run)")
    args = parser.parse_args(argv)

    if args.source.name == "flagged":
        raise SystemExit("refusing to read the flagged/ directory: those songs are set aside")
    if not args.source.is_dir():
        raise SystemExit(f"{args.source} is not a directory")
    if not args.shapes_dir.is_dir():
        raise SystemExit(f"{args.shapes_dir} is not a directory")

    stems = _stems_in_source(args.source) if args.all else _names_from_songs_file(args.songs)
    outcomes = run(args.source, args.shapes_dir, stems, apply=args.apply)

    print(f"{'APPLY' if args.apply else 'DRY RUN'}: {len(outcomes)} song(s), "
          f"from {args.source} into {args.shapes_dir}")
    for outcome in outcomes:
        detail = f" ({', '.join(outcome.reasons)})" if outcome.reasons else ""
        print(f"  {outcome.outcome:18s} {outcome.stem}{detail}")
    counts: dict[str, int] = {}
    for outcome in outcomes:
        counts[outcome.outcome] = counts.get(outcome.outcome, 0) + 1
    print("summary: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    if not args.apply:
        print("nothing written. --apply to import.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
