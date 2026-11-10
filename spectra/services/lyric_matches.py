"""One song's matched words: Claude's latest reading of its lyrics and his own
edits to it (lyrics plan step 3). Shown on the test bed's Sung words lane.

The Admiral's ruling: "Every match is a guess: deletable and addable on the
timeline, and his edits win and survive recapture."

Only one thing in the show reads this module: word colours, on a show he has
switched on (spectra/services/lyric_events.py, off for every show otherwise).
A match does not reach the lights any other way.

ONE SMALL FILE PER SONG (storage/spectra/lyric_matches/), keyed by the song's
URI and in SPECTRA's own directory, because a recapture replaces everything
stored beside the audio. Three parts, and only one is ever replaced:

  reading  — Claude's guesses. Replaced whole by the next reading.
  his      — words he matched himself. Only he changes these.
  deleted  — guesses he took out. A later reading offering the same words with
             the same label stays deleted. The same words with a DIFFERENT
             label is a new guess, which is what a re-read after a label change
             is for.

A MATCH SITS ON WORDS, NOT ON TIMES. It stores which words (by position) and
what they said. Its times come from the current word timeline at read time, so
a recapture that moves every word cannot leave a stale time behind: the match
simply lands where the words now are. If the word positions themselves moved, a
span is found again by its words, at the occurrence nearest where it was. One of
his that cannot be found is reported as `unplaced` and kept, never dropped.

WHO A MATCH REACHES IS RESOLVED WHEN IT IS READ. A guess names a label; every
colour set or effect that carries that label now is who it would reach. A match
of his can name a colour set or effect outright, and that stands even if the
label list changes.

HIS WIN: a guess that overlaps words he matched himself is not shown, so a
correction takes effect without him also having to delete what it replaces.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional, Sequence

from spectra import config
from spectra.models.lyric_labels import (
    ClaudeGuess, DeletedGuess, HisMatch, Reading, SongMatches, TargetRef,
)
from spectra.services import colour_words, lyrics_emphasis, lyrics_timeline, sung_labels

logger = logging.getLogger(__name__)

STATE_NONE = "none"
STATE_FRESH = "fresh"
STATE_LABELS_CHANGED = "labels_changed"
STATE_WORDS_CHANGED = "words_changed"

PROVENANCE_GUESS = "claude_guess"
PROVENANCE_HIS = "his"

# Below this confidence Claude's guess is not a match, and is not stored.
# A first guess, his to tune — the model field's default
# (SungLabelSettings.weak_match_threshold) and read_song()'s own fallback
# when nothing in particular is asked. sung_labels.weak_match_threshold()
# is the LIVE value a reading actually uses once he changes it.
WEAK_MATCH_THRESHOLD = 0.6

MAX_PHRASE_WORDS = 12
MAX_TARGETS_SHOWN = 8

_lock = threading.RLock()


class MatchRefused(ValueError):
    pass


def _path(uri: str) -> Path:
    # A URI can be a pseudo-URI with spaces and slashes in it; the file name is
    # a hash and the URI is inside the document.
    digest = hashlib.sha256(uri.encode("utf-8")).hexdigest()[:32]
    return config.LYRIC_MATCHES_DIR / f"{digest}.json"


def load(uri: str) -> SongMatches:
    path = _path(uri)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return SongMatches(uri=uri)
    try:
        return SongMatches.model_validate(json.loads(raw))
    except Exception as exc:
        # Never read as "no edits": the next save would write that over his.
        raise sung_labels.StoreUnreadable(
            f"{path.name} cannot be read ({exc}); refusing to treat it as empty") from exc


def _save(doc: SongMatches) -> None:
    path = _path(doc.uri)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc.model_dump(), ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def word_keys(words: Sequence[lyrics_emphasis.ScoredWord]) -> list[str]:
    return [colour_words.word_key(w.norm or w.word) for w in words]


def words_hash(words: Sequence[lyrics_emphasis.ScoredWord]) -> str:
    return hashlib.sha256("|".join(word_keys(words)).encode("utf-8")).hexdigest()


def reading_state(doc: SongMatches, current_words_hash: str, labels_hash: str) -> str:
    if doc.reading is None:
        return STATE_NONE
    if doc.reading.words_hash != current_words_hash:
        return STATE_WORDS_CHANGED
    if doc.reading.labels_hash != labels_hash:
        return STATE_LABELS_CHANGED
    return STATE_FRESH


def anchor(span_first: int, span_norm: Sequence[str],
           keys: Sequence[str]) -> Optional[tuple[int, int]]:
    """Where these words are now: where they were if they are still there,
    otherwise the occurrence nearest that position, otherwise None."""
    target = [colour_words.word_key(w) for w in span_norm]
    n = len(target)
    if n == 0 or n > len(keys):
        return None
    if list(keys[span_first:span_first + n]) == target:
        return span_first, span_first + n - 1
    best: Optional[int] = None
    for start in range(len(keys) - n + 1):
        if list(keys[start:start + n]) == target:
            if best is None or abs(start - span_first) < abs(best - span_first):
                best = start
    return None if best is None else (best, best + n - 1)


def guess_id(guess: ClaudeGuess) -> str:
    return "g_" + hashlib.sha1(
        f"{guess.first_word}|{guess.last_word}|{colour_words.word_key(guess.label)}"
        .encode("utf-8")).hexdigest()[:12]


def _is_deleted(first: int, last: int, label: str, norm: Sequence[str],
                deleted: Sequence[DeletedGuess], keys: Sequence[str]) -> bool:
    label_key = colour_words.word_key(label)
    norm_keys = [colour_words.word_key(w) for w in norm]
    for row in deleted:
        if colour_words.word_key(row.label) != label_key:
            continue
        if [colour_words.word_key(w) for w in row.norm] != norm_keys:
            continue
        spot = anchor(row.first_word, row.norm, keys)
        if spot == (first, last):
            return True
    return False


def _target_payload(target: sung_labels.Target) -> dict:
    return {"kind": target.kind, "id": target.id, "name": target.name, "swatch": target.swatch}


def _span_times(first: int, last: int,
                words: Sequence[lyrics_emphasis.ScoredWord]) -> dict:
    return {"ms": words[first].ms, "end_ms": words[last].end_ms,
            "score": max(w.score for w in words[first:last + 1])}


def resolve(doc: SongMatches, words: Sequence[lyrics_emphasis.ScoredWord],
            catalogue: sung_labels.Catalogue) -> tuple[list[dict], list[dict]]:
    """Every match to show, and every one of his that cannot be placed. Pure:
    the file, the words and the label list in, what the page draws out."""
    keys = word_keys(words)
    out: list[dict] = []
    unplaced: list[dict] = []
    taken: list[tuple[int, int]] = []

    for his in doc.his:
        spot = anchor(his.first_word, his.norm, keys)
        if spot is None:
            unplaced.append({"id": his.id, "phrase": his.phrase, "label": his.label})
            continue
        targets = []
        missing = 0
        for ref in his.targets:
            target = catalogue.targets.get((ref.kind, ref.id))
            if target is None:
                missing += 1
            else:
                targets.append(_target_payload(target))
        if not his.targets:
            targets = [_target_payload(t) for t in catalogue.owners.get(
                colour_words.word_key(his.label), ())]
        out.append({"id": his.id, "source": "his", "provenance": PROVENANCE_HIS,
                    "first_word": spot[0], "last_word": spot[1], "phrase": his.phrase,
                    "label": his.label, "confidence": None, "why": "",
                    "targets": targets, "n_targets": len(targets), "targets_missing": missing,
                    **_span_times(spot[0], spot[1], words)})
        taken.append(spot)

    if doc.reading is not None:
        seen: set[tuple[int, int, str]] = set()
        for guess in doc.reading.matches:
            spot = anchor(guess.first_word, guess.norm, keys)
            if spot is None:
                continue
            label_key = colour_words.word_key(guess.label)
            if (spot[0], spot[1], label_key) in seen:
                continue
            seen.add((spot[0], spot[1], label_key))
            if any(spot[0] <= last and first <= spot[1] for first, last in taken):
                continue
            if _is_deleted(spot[0], spot[1], guess.label, guess.norm, doc.deleted, keys):
                continue
            owners = catalogue.owners.get(label_key, ())
            if not owners:
                continue    # no card carries this label any more
            out.append({"id": guess_id(guess), "source": "claude",
                        "provenance": PROVENANCE_GUESS,
                        "first_word": spot[0], "last_word": spot[1], "phrase": guess.phrase,
                        "label": catalogue.labels.get(label_key, guess.label),
                        "confidence": guess.confidence, "why": guess.why,
                        "targets": [_target_payload(t) for t in owners[:MAX_TARGETS_SHOWN]],
                        "n_targets": len(owners), "targets_missing": 0,
                        **_span_times(spot[0], spot[1], words)})

    out.sort(key=lambda m: (m["ms"], m["last_word"]))
    return out, unplaced


def labels_by_word(uri: str, timeline: lyrics_timeline.Timeline) -> dict[int, str]:
    """Which label each word carries, for the chip on an emphasized mark. An
    unreadable store costs the chips and never the lane."""
    try:
        doc = load(uri)
        if doc.reading is None and not doc.his:
            return {}
        matches, _ = resolve(doc, timeline.scored, sung_labels.catalogue())
    except sung_labels.StoreUnreadable:
        logger.exception("lyric matches: cannot read the labels for %s", uri)
        return {}
    out: dict[int, str] = {}
    for match in matches:
        for index in range(match["first_word"], match["last_word"] + 1):
            out.setdefault(index, match["label"])
    return out


def payload(uri: str) -> dict[str, Any]:
    """What GET /api/testbed/lyric-matches returns."""
    timeline = lyrics_timeline.timeline_for_uri(uri)
    doc = load(uri)
    base: dict[str, Any] = {
        "uri": uri, "status": timeline.status, "note": timeline.note,
        "weak_match_threshold": sung_labels.weak_match_threshold(),
        "n_deleted": len(doc.deleted),
    }
    if not timeline.usable:
        return {**base, "state": STATE_NONE, "reading": None, "matches": [], "unplaced": [],
                "n_his": len(doc.his)}
    catalogue = sung_labels.catalogue()
    matches, unplaced = resolve(doc, timeline.scored, catalogue)
    reading = doc.reading
    return {
        **base,
        "state": reading_state(doc, words_hash(timeline.scored), catalogue.labels_hash),
        "reading": None if reading is None else {
            "at_ms": reading.at_ms, "model": reading.model, "n_weak": reading.n_weak,
            "n_refused": sum(reading.refused.values()),
        },
        "matches": matches,
        "unplaced": unplaced,
        "n_his": len(doc.his),
    }


def save_reading(uri: str, reading: Reading) -> None:
    """Replaces Claude's reading and nothing else."""
    with _lock:
        doc = load(uri)
        doc.reading = reading
        _save(doc)


def _resolve_target(ref: TargetRef, catalogue: sung_labels.Catalogue) -> sung_labels.Target:
    target = catalogue.targets.get((ref.kind, ref.id))
    if target is None:
        raise MatchRefused("That colour set or effect no longer exists.")
    return target


def add(uri: str, first_word: int, last_word: int, target: TargetRef) -> dict[str, Any]:
    """He matched these words to this colour set or effect."""
    timeline = lyrics_timeline.timeline_for_uri(uri)
    if not timeline.usable:
        raise MatchRefused(timeline.note or "This song has no usable word timeline.")
    words = timeline.scored
    if not (0 <= first_word <= last_word < len(words)):
        raise MatchRefused("Those words are not in this song.")
    if last_word - first_word + 1 > MAX_PHRASE_WORDS:
        raise MatchRefused(f"A match can be at most {MAX_PHRASE_WORDS} words.")
    catalogue = sung_labels.catalogue()
    chosen = _resolve_target(target, catalogue)
    span = words[first_word:last_word + 1]
    norm = [w.norm or w.word for w in span]
    phrase = " ".join(lyrics_timeline.display_word(w.word) for w in span)
    with _lock:
        doc = load(uri)
        for his in doc.his:
            if (his.first_word, his.last_word) == (first_word, last_word) and any(
                    (r.kind, r.id) == (target.kind, target.id) for r in his.targets):
                return payload(uri)
        doc.his.append(HisMatch(
            id=f"h_{uuid.uuid4().hex[:12]}", first_word=first_word, last_word=last_word,
            norm=norm, phrase=phrase, label=chosen.name, targets=[target],
            added_ms=int(time.time() * 1000)))
        _save(doc)
    return payload(uri)


def delete(uri: str, match_id: str) -> dict[str, Any]:
    """Takes a match off the timeline: his own is removed, a guess stays
    deleted through every later reading."""
    with _lock:
        doc = load(uri)
        kept = [h for h in doc.his if h.id != match_id]
        if len(kept) != len(doc.his):
            doc.his = kept
            _save(doc)
            return payload(uri)
        guess = next((g for g in (doc.reading.matches if doc.reading else [])
                      if guess_id(g) == match_id), None)
        if guess is None:
            raise MatchRefused("That match is no longer there.")
        doc.deleted.append(DeletedGuess(first_word=guess.first_word, last_word=guess.last_word,
                                        norm=guess.norm, label=guess.label))
        _save(doc)
    return payload(uri)


def restore_deleted(uri: str) -> dict[str, Any]:
    """Brings back every guess he deleted on this song."""
    with _lock:
        doc = load(uri)
        doc.deleted = []
        _save(doc)
    return payload(uri)
