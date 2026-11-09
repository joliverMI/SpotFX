"""The per-song word timeline's file: `<stem>.lyrics.json`, beside the song's
`.librosa.json` in storage/audio_shapes. Its format is the alignment job's
(/home/javi/fleet-spotfx/data/lyrics-step1-measure/desktop-job-spec.md,
section 7, schema "spotfx.lyrics.v2"); this module owns the two questions
everything else asks about one:

  validate()    — is this document a well-formed word timeline?
  problems_against_capture() — do the audio files it was aligned against
                  still exist unchanged?

The second question exists because a word's times are positions in ONE
capture. A recapture writes a new WAV and new frame labels, and every stored
word time is then wrong by an amount nobody can see from the sidecar. So the
sidecar stamps the WAV's size and mtime and the `.npz`'s SHA-256, and both
the import and every read compare them. It is deliberately strict: the
import refuses by name rather than copying something that no longer lines
up, and a read reports the song stale rather than drawing it.

The clock: `ms` / `end_ms` are capture labels (the `.npz` `timestamps_ms`,
the clock the show runs on); `wav_ms` / `end_wav_ms` are positions in the
WAV. See docs/SPECTRA_TIMING_CONVENTIONS.md's "Sung-word times" row and
spectra/services/lyrics_timeline.py.

`storage/audio_shapes` is scanned as `*.json` by several readers looking for
capture sidecars. A `.lyrics.json` matches that pattern, so each of those
scans skips this suffix by name, or it would parse every word timeline on
every index rebuild (analysis_reader rebuilds on every miss).
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Mapping, Optional

SCHEMA = "spotfx.lyrics.v2"
SUFFIX = ".lyrics.json"

# Word labels may step back a little: a pre-roll seam in the capture does
# (the alignment job's own LabelMap says so). A real shuffle is seconds.
OUT_OF_ORDER_TOLERANCE_MS = 500.0
# A one-letter word can come out a few milliseconds backwards from the frame
# lookup (-10 ms at worst across the backfill). A rounding quirk, not a fault.
INVERTED_WORD_TOLERANCE_MS = 50.0


def path_for(shapes_dir: Path, stem: str) -> Path:
    return shapes_dir / f"{stem}{SUFFIX}"


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate(doc: object, *, expected_stem: Optional[str] = None) -> list[str]:
    """Every reason this document is not a usable word timeline, by name; an
    empty list means it is one. Checks shape and internal sense only, never
    the audio files (problems_against_capture does that)."""
    if not isinstance(doc, Mapping):
        return ["not_an_object"]
    problems: list[str] = []
    if doc.get("schema") != SCHEMA:
        problems.append(f"schema_not_{SCHEMA}")
    for key in ("uri", "stem"):
        if not isinstance(doc.get(key), str) or not doc.get(key):
            problems.append(f"missing_{key}")
    if expected_stem is not None and doc.get("stem") != expected_stem:
        problems.append("stem_does_not_match_filename")
    flags = doc.get("flags")
    if not isinstance(flags, list):
        problems.append("missing_flags")
    elif flags:
        problems.append("flagged_by_the_alignment_job")

    stamp = doc.get("stamp")
    if not isinstance(stamp, Mapping):
        problems.append("missing_stamp")
    else:
        if not _is_number(stamp.get("capture_offset_ms")):
            problems.append("missing_stamp_capture_offset_ms")
        if not _is_number(stamp.get("wav_bytes")):
            problems.append("missing_stamp_wav_bytes")
        if not _is_number(stamp.get("wav_mtime_ns")):
            problems.append("missing_stamp_wav_mtime_ns")
        label_map = stamp.get("label_map")
        if not isinstance(label_map, Mapping) or not label_map.get("npz_sha256"):
            problems.append("missing_stamp_npz_sha256")

    words = doc.get("words")
    if not isinstance(words, list) or not words:
        problems.append("no_words")
        return problems
    previous = float("-inf")
    for word in words:
        if not isinstance(word, Mapping):
            problems.append("word_not_an_object")
            break
        if not isinstance(word.get("w"), str) or not isinstance(word.get("n"), str):
            problems.append("word_missing_text")
            break
        numbers = [word.get(k) for k in ("line", "ms", "end_ms", "wav_ms", "end_wav_ms")]
        if not all(_is_number(n) for n in numbers):
            problems.append("word_missing_times")
            break
        if float(word["end_ms"]) < float(word["ms"]) - INVERTED_WORD_TOLERANCE_MS:
            problems.append("word_ends_before_it_starts")
            break
        if float(word["ms"]) < previous - OUT_OF_ORDER_TOLERANCE_MS:
            problems.append("words_out_of_order")
            break
        previous = max(previous, float(word["ms"]))
    return problems


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def problems_against_capture(doc: Mapping, shapes_dir: Path, *,
                             require_wav: bool) -> list[str]:
    """Whether the audio this timeline was aligned against is still there,
    unchanged. `require_wav` is the import's rule: the WAV must be present
    and match. A read passes False because the WAV-retention cap
    (services/librosa_service.manage_wav_retention) deletes older WAVs on
    purpose; a missing WAV says nothing about a recapture, while the `.npz`
    is kept for every played song and is what the labels came from."""
    stem = str(doc.get("stem"))
    stamp = doc.get("stamp") or {}
    problems: list[str] = []

    wav = shapes_dir / f"{stem}.wav"
    try:
        wav_stat = wav.stat()
    except OSError:
        wav_stat = None
    if wav_stat is None:
        if require_wav:
            problems.append("wav_missing")
    elif (wav_stat.st_size != stamp.get("wav_bytes")
          or wav_stat.st_mtime_ns != stamp.get("wav_mtime_ns")):
        problems.append("wav_changed")

    npz = shapes_dir / f"{stem}.npz"
    try:
        actual = sha256_of(npz)
    except OSError:
        problems.append("npz_missing")
    else:
        if actual != (stamp.get("label_map") or {}).get("npz_sha256"):
            problems.append("npz_changed")
    return problems
