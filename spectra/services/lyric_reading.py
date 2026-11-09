"""Claude reads a song's lyrics against the sung label list, ahead of time and
as text only (lyrics plan step 3).

The Admiral, 2026-11-09: "I want specific words and phrases to lead to events
... We do need to interpret when the subject of an emphasized phrase or word
relates to something like a color or some other thing from a list we can build."

THIS HAS NO EFFECT ON THE ROOM, and no audio goes anywhere: the only thing sent
is the words of the song and the label list.

READ AGAINST ONE LIST OF LABELS, NOT 62 LISTS. Claude is handed each distinct
label once and says which it fits. Which colour sets carry that label is settled
when the match is read back (lyric_matches.resolve), so the prompt stays small,
is the same for every song (and so is cached), and moving a word from one set to
another needs no re-reading. Only a change to the words on the list does.

A GUESS HAS TO SURVIVE BEING CHECKED. Every row Claude returns is validated
against what is really there: the line must exist, the phrase must be sung on
it, the label must be on the list. One that is not is thrown away and counted by
reason, the same posture Sonic's tool results have towards its prose.

A WEAK MATCH IS NO MATCH. Below WEAK_MATCH_THRESHOLD a guess is not stored at
all, only counted, so nothing downstream can ever act on one. The number is a
first guess and his to tune.

A LINE SUNG AGAIN IS READ ONCE. Each distinct line goes in the prompt once, with
the other places it is sung, and a match on it lands on every one of them. A
chorus read six times would cost six times as much and could disagree with
itself.

OFF BY DEFAULT. run_supervised does nothing until he turns on automatic reading
(SungLabelSettings.auto_read); until then only a press of a read button reaches
Claude. Turned on, it re-reads a song when the words on the list have changed,
waiting for his edits to go quiet and then one song at a time, slowly, because
this spends his Claude allowance.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable, Optional, Sequence

from spectra import config
from spectra.models.lyric_labels import ClaudeGuess, Reading
from spectra.services import (analysis_reader, claude_text, colour_words, lyric_matches,
                              lyrics_emphasis, lyrics_timeline, sung_labels)

logger = logging.getLogger(__name__)

Ask = Callable[..., Awaitable[claude_text.ClaudeReply]]

WEAK_MATCH_THRESHOLD = lyric_matches.WEAK_MATCH_THRESHOLD
MAX_PHRASE_WORDS = 6

# THE AUTOMATIC READER'S PACE. Reading his whole library spends his Claude
# allowance, so one song a minute: about five hours for ~300 songs.
SWEEP_POLL_S = 30.0
READ_GAP_S = 60.0
# Labels changing in a burst should cost one pass over the library, not one
# pass per edit.
LABELS_QUIET_S = 600.0
# After Claude could not be reached, how long before trying again.
FAILURE_BACKOFF_S = 900.0

REFUSED_LINE = "no_such_line"
REFUSED_PHRASE = "phrase_not_on_line"
REFUSED_LABEL = "label_not_on_list"
REFUSED_ROW = "malformed"

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"matches": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "line": {"type": "integer"},
            "phrase": {"type": "string"},
            "label": {"type": "string"},
            "confidence": {"type": "number"},
            "why": {"type": "string"},
        },
        "required": ["line", "phrase", "label", "confidence", "why"],
        "additionalProperties": False,
    }}},
    "required": ["matches"],
    "additionalProperties": False,
}

_read_lock = asyncio.Lock()
_last_read_at = 0.0
_retry_after = 0.0
_unreadable: dict[str, str] = {}


class NoUsableWords(Exception):
    pass


class NoLabels(Exception):
    pass


def reset() -> None:
    global _last_read_at, _retry_after, _read_lock
    _last_read_at = 0.0
    _retry_after = 0.0
    _unreadable.clear()
    _read_lock = asyncio.Lock()


def build_system_prompt(catalogue: sung_labels.Catalogue,
                        weak_match_threshold: float = WEAK_MATCH_THRESHOLD) -> str:
    return (
        "You read song lyrics for a home light show. The show has a list of LABELS "
        "(colours, things, moods, places and effects) and can react when a sung word or "
        "short phrase is really about one of them.\n\n"
        f"Find the words or short phrases, 1 to {MAX_PHRASE_WORDS} words, that are about "
        "something on the list. Judge each one by what its line means:\n"
        "- A word that names a label in the sense it has here counts: \"her red dress\" is "
        "the label red.\n"
        "- A word that only looks like a label does not: \"feeling blue\" means sad, so it "
        "fits a mood like sad, and not the colour blue. \"Green light\" in the sense of "
        "permission is not the colour green.\n"
        "- Lyrics and labels may be in different languages; a label still counts when "
        "the meaning is the same (\"azul\" is blue).\n"
        "- Report specific sung words and phrases only. Do not report what the song as a "
        "whole is about.\n"
        "- A short common word is rarely worth reporting unless the line is really about "
        "it. Prefer saying nothing to stretching.\n\n"
        "Give each match a confidence from 0 to 1: 0.9 or more when the words clearly mean "
        f"the label, about 0.7 for a good fit, and leave out anything below {weak_match_threshold}. "
        "When one phrase fits two labels, give the single best one unless they are really "
        "different meanings.\n\n"
        "For each match, give `line` (the number at the start of the line), `phrase` "
        "(copied from that line exactly), `label` (spelled exactly as listed) and `why` "
        "(a few words).\n\n"
        "COLOUR LABELS: " + ", ".join(catalogue.color_labels) + "\n\n"
        "EFFECT LABELS: " + ", ".join(catalogue.effect_labels) + "\n"
    )


def _lines(words: Sequence[lyrics_emphasis.ScoredWord]) -> dict[int, list[int]]:
    out: dict[int, list[int]] = {}
    for i, word in enumerate(words):
        out.setdefault(word.line, []).append(i)
    return out


def _repeat_groups(lines: dict[int, list[int]],
                   keys: Sequence[str]) -> dict[tuple[str, ...], list[int]]:
    groups: dict[tuple[str, ...], list[int]] = {}
    for line, indexes in lines.items():
        groups.setdefault(tuple(keys[i] for i in indexes), []).append(line)
    return groups


def build_user_prompt(song: str, words: Sequence[lyrics_emphasis.ScoredWord]) -> str:
    lines = _lines(words)
    keys = lyric_matches.word_keys(words)
    groups = _repeat_groups(lines, keys)
    rows: list[str] = []
    for line, indexes in lines.items():
        group = groups[tuple(keys[i] for i in indexes)]
        if group[0] != line:
            continue
        text = " ".join(lyrics_timeline.display_word(words[i].word) for i in indexes)
        again = f" (sung again at {', '.join(str(n) for n in group[1:])})" if group[1:] else ""
        rows.append(f"{line}{again}: {text}")
    return f"Song: {song}\n\nLyrics, one numbered line each:\n" + "\n".join(rows)


def _find_phrase(phrase_keys: Sequence[str], line_indexes: Sequence[int],
                 keys: Sequence[str]) -> Optional[tuple[int, int]]:
    n = len(phrase_keys)
    for start in range(len(line_indexes) - n + 1):
        indexes = line_indexes[start:start + n]
        if [keys[i] for i in indexes] == list(phrase_keys):
            return indexes[0], indexes[-1]
    return None


def _count(refused: dict[str, int], reason: str) -> None:
    refused[reason] = refused.get(reason, 0) + 1


def parse_reply(data: dict[str, Any], words: Sequence[lyrics_emphasis.ScoredWord],
                catalogue: sung_labels.Catalogue,
                weak_match_threshold: float = WEAK_MATCH_THRESHOLD
                ) -> tuple[list[ClaudeGuess], int, dict[str, int]]:
    """Claude's rows, checked. Returns (matches, weak count, refused by reason)."""
    lines = _lines(words)
    keys = lyric_matches.word_keys(words)
    groups = _repeat_groups(lines, keys)
    group_of = {line: group for group in groups.values() for line in group}
    out: list[ClaudeGuess] = []
    seen: set[tuple[int, int, str]] = set()
    n_weak = 0
    refused: dict[str, int] = {}

    for row in data.get("matches") or []:
        if not isinstance(row, dict):
            _count(refused, REFUSED_ROW)
            continue
        try:
            line = int(row.get("line"))
            confidence = float(row.get("confidence"))
        except (TypeError, ValueError):
            _count(refused, REFUSED_ROW)
            continue
        if not 0.0 <= confidence <= 1.0:
            _count(refused, REFUSED_ROW)
            continue
        if confidence < weak_match_threshold:
            n_weak += 1
            continue
        phrase = str(row.get("phrase") or "")
        phrase_keys = [k for k in (colour_words.word_key(w) for w in phrase.split()) if k]
        if not phrase_keys or len(phrase_keys) > MAX_PHRASE_WORDS:
            _count(refused, REFUSED_PHRASE)
            continue
        label_key = colour_words.word_key(str(row.get("label") or ""))
        if label_key not in catalogue.labels:
            _count(refused, REFUSED_LABEL)
            continue
        if line not in group_of:
            _count(refused, REFUSED_LINE)
            continue
        placed = False
        for occurrence in group_of[line]:
            spot = _find_phrase(phrase_keys, lines[occurrence], keys)
            if spot is None:
                continue
            placed = True
            key = (spot[0], spot[1], label_key)
            if key in seen:
                continue
            seen.add(key)
            span = words[spot[0]:spot[1] + 1]
            out.append(ClaudeGuess(
                first_word=spot[0], last_word=spot[1],
                norm=[w.norm or w.word for w in span],
                phrase=" ".join(lyrics_timeline.display_word(w.word) for w in span),
                label=catalogue.labels[label_key], confidence=round(confidence, 3),
                why=str(row.get("why") or "")[:200]))
        if not placed:
            _count(refused, REFUSED_PHRASE)
    out.sort(key=lambda g: g.first_word)
    return out, n_weak, refused


async def read_song(uri: str, *, ask: Optional[Ask] = None) -> dict[str, Any]:
    """One reading of one song, now. Replaces Claude's previous reading and
    nothing else. Raises NoUsableWords, NoLabels, or claude_text's two."""
    global _last_read_at
    async with _read_lock:
        timeline = await asyncio.to_thread(lyrics_timeline.timeline_for_uri, uri)
        if not timeline.usable:
            raise NoUsableWords(timeline.note or "This song has no usable word timeline.")
        catalogue = await asyncio.to_thread(sung_labels.catalogue)
        if not catalogue.labels:
            raise NoLabels("There are no sung labels to read against yet.")
        threshold = await asyncio.to_thread(sung_labels.weak_match_threshold)
        stem = await asyncio.to_thread(analysis_reader.stem_for_uri, uri)
        reply = await (ask or claude_text.ask_json)(
            system=build_system_prompt(catalogue, threshold),
            user=build_user_prompt(stem or uri, timeline.scored),
            schema=SCHEMA, purpose="lyric-reading")
        matches, n_weak, refused = parse_reply(reply.data, timeline.scored, catalogue, threshold)
        reading = Reading(
            at_ms=int(time.time() * 1000), model=reply.model, backend=reply.backend,
            labels_hash=catalogue.labels_hash,
            words_hash=lyric_matches.words_hash(timeline.scored),
            matches=matches, n_weak=n_weak, refused=refused)
        await asyncio.to_thread(lyric_matches.save_reading, uri, reading)
        _last_read_at = time.monotonic()
    logger.info("lyric reading: %s — %d matches, %d weak, %d refused",
                uri, len(matches), n_weak, sum(refused.values()))
    return await asyncio.to_thread(lyric_matches.payload, uri)


def _next_song(labels_hash: str) -> Optional[str]:
    """The first song with sung words whose reading is missing or was made
    against a different list. Reads only each song's small match file."""
    for uri, stem in sorted(analysis_reader.stem_index().items()):
        if not analysis_reader.has_lyrics(stem) or _unreadable.get(uri) == labels_hash:
            continue
        reading = lyric_matches.load(uri).reading
        if reading is None or reading.labels_hash != labels_hash:
            return uri
    return None


def _due(now: float, labels_changed_ms: int) -> bool:
    if now < _retry_after:
        return False
    if _last_read_at and now - _last_read_at < READ_GAP_S:
        return False
    return time.time() * 1000 - labels_changed_ms >= LABELS_QUIET_S * 1000


async def sweep_once(*, ask: Optional[Ask] = None) -> Optional[str]:
    """Reads at most one song. None if automatic reading is off, it is not
    time yet, or nothing needs reading."""
    global _retry_after
    if not await asyncio.to_thread(sung_labels.auto_read_enabled):
        return None
    if ask is None and not claude_text.availability()["available"]:
        return None
    changed_ms = await asyncio.to_thread(sung_labels.labels_changed_ms)
    if not _due(time.monotonic(), changed_ms):
        return None
    catalogue = await asyncio.to_thread(sung_labels.catalogue)
    if not catalogue.labels:
        return None
    uri = await asyncio.to_thread(_next_song, catalogue.labels_hash)
    if uri is None:
        return None
    try:
        await read_song(uri, ask=ask)
    except claude_text.ClaudeUnavailable as exc:
        logger.warning("lyric reading: %s — stopping for a while: %s", uri, exc)
        _retry_after = time.monotonic() + FAILURE_BACKOFF_S
        return None
    except (NoUsableWords, claude_text.ClaudeReplyInvalid) as exc:
        # This song, not the service: a timeline gone stale, or a reply that
        # could not be used. Not worth asking again until the label list
        # changes, and never a reason to stop the pass.
        logger.info("lyric reading: skipping %s: %s", uri, exc)
        _unreadable[uri] = catalogue.labels_hash
        return None
    return uri


async def run_supervised() -> None:
    while True:
        await asyncio.sleep(SWEEP_POLL_S)
        try:
            await sweep_once()
        except asyncio.CancelledError:
            raise
        except sung_labels.StoreUnreadable:
            logger.exception("lyric reading: the sung-label store cannot be read")
        except Exception:
            logger.exception("lyric reading: sweep failed")
