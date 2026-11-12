"""THE LYRICS DOMAIN — Sonic's reach over the sung labels and word matches
built in lyrics plan step 3 (PR #499), AND word colours and imprints from
lyrics plan step 4 (PR #504): what a colour set or effect answers to when
it is sung, Claude's drafted colour meanings, one song's matched words,
the automatic reader's own switch, and — the
step-4 follow-up this module was still missing — the per-show word-colour
switch, its three tuning settings, and a preview of what each word would
do. spectra/services/sung_labels.py, lyric_matches.py, lyric_reading.py,
color_meanings.py and lyric_events.py are the binding statements for the
mechanism; this module only exposes it, through the exact same write
paths the /sung-labels page, the test bed's Sung words lane and its Word
actions row already use — never a second one.

Per the Admiral's standing Sonic coverage protocol (2026-10-06, "add
protocols to make those after all changes ... adding and updating skills
as a final step"): this feature shipped without any Sonic operation, and
this module is that follow-up (both the step-3 one and, now, step-4's).

THE ROLL (2026-11-12, lyric_events.py's "THE ROLL") — FOLLOW-UP OWED. Each
play rolls which words act, by confidence, with his Always / Chance / Never
pin per match and "Keep this roll" per song. Sonic already READS it:
preview_lyric_events passes the Test Bed's payload through, so `roll` (this
play's number, how many words won, a kept roll) and each action's `chance`
/`won`/`pin` are in its answer. Not yet here, and named so an audit can tell
"not yet" from "forgotten": an op to pin a match (by phrase, like
delete_lyric_match; Always on a switched-on show newly lets a word act, so
it would ask first) and an op to keep or release a song's roll. The weak-
match threshold this module used to change is gone: there is no cut-off.

NO LIGHT OUTPUT, NO TRIGGER WIRING. Every handler here reaches only
sung_labels / lyric_matches / lyric_reading / color_meanings / colour_words
/ claude_text / analysis_reader / name_resolve / lyric_events — the same
boundary those modules' own tests already hold (tests/test_lyric_reading.py's
test_nothing_in_the_show_can_reach_the_label_or_match_modules and
test_the_label_and_match_modules_import_nothing_that_can_write_light). The
one exception is a read of the currently-playing track's URI (show_arms.
current_uri — a plain status read, never a write), used only so "read this
song" can default to whatever is playing.

preview_lyric_events ("what would each word do") needs the SAME answer the
Test Bed's own Word actions row shows (TriggerEngine.preview_lyric_events,
spectra/api/lyric_events.py) — including an imprint on a nearby drop, scene
change/update or flare, which needs that engine's own event candidates.
Reaching it by import would pull in the whole engine stack this module is
built to stay out of. So it goes over HTTP instead, the same shape lock_
console.py/absorb_console.py/jukebox_console.py already use for a domain
that has to answer through a process boundary — except here the "other
side" is THIS SAME PROCESS'S own HTTP layer (SPECTRA mounts itself under
"/spectra" even on its own port, `root.mount("/spectra", create_app())` in
spectra/app.py; `settings_agent.dispatch_url()` is the existing precedent
for a SPECTRA-to-itself loopback call, as opposed to lock_console's call to
the ROOT spotfx process). lyric_console.py itself still imports nothing
from engine.py/scene_response.py/drift_conductor.py/fx_executor.py/
trigger_engine.py — the GET just asks the already-running app to answer
through the one mechanism (test_lyric_console.py's import-boundary test
proves it). `http` below is the injectable transport seam, same convention
as the other HTTP domains: tests replace it with a fake backed by a REAL
TestClient over the real router (lock_console's own test precedent),
never a live network call.

OPAQUE IDS ARE OFF-LIMITS, as elsewhere (force_scene_*'s own precedent): a
colour set, an effect and a song are all reached by NAME through
name_resolve.resolve_name — exact, a dropped "V2"/"V1"/"UI" qualifier,
then a clear fuzzy winner, refusing a near-tie rather than guessing. A
song is the one exception to "use resolve_name's own known_names
fallback verbatim": his library can hold hundreds of analysed songs, so a
clean miss's candidate list is capped (SONG_CANDIDATES_SHOWN) rather than
dumped whole — the same reason the Jukebox's own song search (AGENTS.md)
is a bounded search, not a flat name list, over a library this size. A
match itself (a Claude guess or one of his own) has no name to give
either — it is reached by the PHRASE it sits on (and, if that phrase is
ambiguous, the label it carries), never its internal id (a Claude-guess
hash or a UUID nobody would say aloud).

HIS EDITS AND CLAUDE'S OWN NEVER CROSS, exactly as the page enforces:
edit_sung_label and the match ops write through sung_labels.edit /
lyric_matches.add / .delete / .restore_deleted, which keep his additions
and removals as deltas apart from whatever is seeded or drafted — a
re-draft (draft_colour_meanings) or a re-read (read_song_lyrics) can never
undo a word he added or took off, or a match he placed or deleted.

ASKING FIRST, same shape as drop_console.py's in-process confirm/redeem
(itself absorb_console.py's two-call protocol, without the HTTP hop —
these lyric modules live in THIS process, so there is nothing to cross):
turning auto_read ON (letting Claude read songs with nobody pressing
anything, one a minute, continuously spending his Claude allowance) asks
first; turning it off applies at once. draft_colour_meanings and
read_song_lyrics ALWAYS ask — every
call spends his Claude allowance, not just the first one, so there is no
"newly lets it act" distinction to make; absorb_console's start_absorb
(a consequential act repeated every call) is the matching precedent.
set_lyric_event_show turning a show's word colours ON is the same "newly
lets it act" shape as turning auto_read on: it is what lets a matched word
start changing the room's colours while that song plays, so it asks first;
turning it OFF, and changing only the energy cut-off / minimum gap /
imprint window (shared by every show, not a per-show act), apply at once.
An id is single-use, expires, and is refused if what he was asked has
since changed.

WHAT STAYS OFF-LIMITS, DELIBERATELY: the automatic reader's own pacing
constants (lyric_reading.SWEEP_POLL_S / READ_GAP_S / LABELS_QUIET_S /
FAILURE_BACKOFF_S) are a hand-picked pace, not a setting — nothing exposes
them to him either, so there is nothing here to widen. Deleting a colour
set or an effect's registration is not reached from here (that is the
Colours page / the effect registry, same as every other domain's own
"creation and deletion of the underlying thing stays where it already
was" rule). The transition-time range (FAST_TRANSITION_MS/SLOW_TRANSITION_MS/
FAST_AT_ENERGY in lyric_events.py) is likewise a pair of named constants,
not one of the three stored settings — nothing here widens that either.
"""
from __future__ import annotations

import json as _json
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Optional

from spectra.models.lyric_labels import TargetRef
from spectra.services import (analysis_reader, claude_text, color_meanings, colour_words,
                              lyric_events, lyric_matches, lyric_reading, lyrics_timeline,
                              name_resolve, sung_labels)
from spectra.services.sonic_ops import SonicOperation

TARGET_KINDS = ("color_set", "effect")
LIST_KINDS = ("labels", "things", "moods", "places")

#: A clean miss over the whole song library would hand back every analysed
#: song's name — capped here, the same reason the Jukebox's own song search
#: is a bounded search rather than a flat list (AGENTS.md).
SONG_CANDIDATES_SHOWN = 20

CONFIRM_TTL_S = 300.0
_PENDING_MAX = 50


@dataclass
class _Ask:
    op: str
    fingerprint: str
    expires: float


_PENDING: dict[str, _Ask] = {}
#: injectable for tests
_clock: Callable[[], float] = time.monotonic


# ── the one HTTP seam: this process's own Test Bed route ───────────────────
#: preview_lyric_events's own transport (see the module docstring's "preview_
#: lyric_events" section for why this is HTTP rather than an import).

LYRIC_EVENTS_HTTP_TIMEOUT_S = 10.0


def _base_url() -> str:
    port = int(os.getenv("SPECTRA_PORT", "8010"))
    return f"http://127.0.0.1:{port}/spectra"


async def _http(method: str, path: str, *, params: Optional[dict] = None):
    """One request to THIS process's own HTTP layer — never the live engine
    stack by import. Injectable for tests (no live access from tests, ever):
    replace `http` with a fake of the same shape, backed by a real TestClient
    over the real router (lock_console.py's own test precedent), never a
    real socket."""
    import httpx
    async with httpx.AsyncClient(timeout=LYRIC_EVENTS_HTTP_TIMEOUT_S) as client:
        return await client.request(method, f"{_base_url()}{path}", params=params)


#: injectable for tests
http = _http


def _unreachable(exc: Exception) -> dict:
    return {"status": "rejected",
            "reason": f"the SPECTRA app's own Test Bed route did not answer: {exc}"}


def _fingerprint(op: str, args: dict, state: dict) -> str:
    return _json.dumps({"op": op, "args": args, "state": state}, sort_keys=True, default=str)


def _ask(op: str, fingerprint: str, question: str, **extra: Any) -> dict:
    now = _clock()
    for k in [k for k, a in _PENDING.items() if a.expires <= now]:
        del _PENDING[k]
    while len(_PENDING) >= _PENDING_MAX:
        del _PENDING[next(iter(_PENDING))]
    cid = uuid.uuid4().hex[:12]
    _PENDING[cid] = _Ask(op, fingerprint, now + CONFIRM_TTL_S)
    return {"status": "needs_confirmation", "op": op, "confirm_id": cid,
            "question": question,
            "reason": f"Not done yet — this needs his yes first. {question}",
            "expires_in_s": int(CONFIRM_TTL_S), **extra}


def _redeem(op: str, fingerprint: str, confirm_id: Any) -> Optional[dict]:
    """None when `confirm_id` is the live answer to exactly this question;
    otherwise the rejection. Used up either way."""
    a = _PENDING.pop(confirm_id, None) if isinstance(confirm_id, str) else None
    if a is None or a.op != op:
        return {"status": "rejected",
                "reason": "that confirm_id is not one this operation handed out, or it was "
                          "already used — call it again without one and ask him"}
    if a.expires <= _clock():
        return {"status": "rejected",
                "reason": "that confirmation expired — call it again without a confirm_id "
                          "and ask him again"}
    if a.fingerprint != fingerprint:
        return {"status": "rejected",
                "reason": "something changed since he was asked, so his yes no longer "
                          "covers it — ask him again"}
    return None


def _onoff(v: Optional[bool]) -> str:
    return "on" if v else "off"


def _applied(data: dict, **extra: Any) -> dict:
    """An applied write result built on top of lyric_matches.payload()'s own
    shape, whose `status` field is a FACT ABOUT THE SONG'S WORD TIMELINE
    (ok/none/invalid/stale — lyrics_timeline.STATUS_*), never an operation
    outcome. Renamed out of the way here so it can never silently collide
    with — and override — this operation's own status:"applied" when the
    payload is splatted into the result."""
    out = dict(data)
    out["timeline_status"] = out.pop("status", None)
    out.update(extra)
    out["status"] = "applied"
    return out


# ── naming things by name, never by opaque id ───────────────────────────────

def _current_uri() -> Optional[str]:
    from spectra.services import show_arms
    return show_arms.current_uri()


def _resolve_song(song: Optional[str]) -> tuple[Optional[str], Optional[dict]]:
    """(uri, rejection). No name: whatever is playing now. A name: matched
    against every analysed song's own title/artist (name_resolve's exact /
    dropped-qualifier / fuzzy tiers) — he names a song by its title, never
    by its spotify:track: id."""
    text = (song or "").strip()
    if not text:
        cur = _current_uri()
        if not cur:
            return None, {"status": "rejected",
                          "reason": "nothing is playing right now — name the song"}
        return cur, None
    candidates = list(analysis_reader.stem_index().items())
    match, rejection = name_resolve.resolve_name(text, candidates, noun="song")
    if rejection:
        names = rejection.get("known_names")
        if isinstance(names, list) and len(names) > SONG_CANDIDATES_SHOWN:
            total = len(names)
            rejection["known_names"] = sorted(names)[:SONG_CANDIDATES_SHOWN]
            rejection["reason"] += (f" — {total} analysed songs; naming a few more words "
                                    "from the title usually narrows it")
        return None, rejection
    return match.id, None


def _song_name(uri: str) -> str:
    return analysis_reader.stem_for_uri(uri) or uri


def _target_candidates(kind: str) -> list[tuple[str, str]]:
    cat = sung_labels.catalogue()
    return [(t.id, t.name) for t in cat.targets.values() if t.kind == kind]


def _resolve_target(kind: str, name: str) -> tuple[Optional[str], Optional[dict]]:
    if kind not in TARGET_KINDS:
        return None, {"status": "rejected", "reason": "kind must be color_set or effect"}
    noun = "colour set" if kind == "color_set" else "effect"
    match, rejection = name_resolve.resolve_name(name, _target_candidates(kind), noun=noun)
    if rejection:
        return None, rejection
    return match.id, None


def _page_row(kind: str, target_id: str) -> Optional[dict]:
    page = sung_labels.page()
    rows = page["color_sets"] if kind == "color_set" else page["effects"]
    return next((r for r in rows if r["id"] == target_id), None)


def _phrase_keys(phrase: str) -> list[str]:
    return [k for k in (colour_words.word_key(w) for w in (phrase or "").split()) if k]


def _find_occurrences(keys: list, phrase_keys: list) -> list[tuple[int, int]]:
    n = len(phrase_keys)
    if n == 0 or n > len(keys):
        return []
    out = []
    for start in range(len(keys) - n + 1):
        if list(keys[start:start + n]) == list(phrase_keys):
            out.append((start, start + n - 1))
    return out


# ── his settings: the auto-read switch ──────────────────────────────────────
# (There is no weak-match threshold any more, 2026-11-12: every guess is kept
# and its confidence is its chance of playing, lyric_events.chance_for.)

def _op_get_lyric_reading_settings() -> dict:
    try:
        page = sung_labels.page()
    except sung_labels.StoreUnreadable as exc:
        return {"status": "rejected", "reason": str(exc)}
    avail = claude_text.availability()
    return {"auto_read": page["auto_read"],
            "n_labels": page["n_labels"], "claude_available": avail["available"],
            "claude_reason": avail["reason"], "claude_model": avail["model"]}


async def _op_set_lyric_reading_settings(auto_read: Optional[bool] = None,
                                         confirm_id: Optional[str] = None) -> dict:
    if auto_read is None:
        return {"status": "rejected", "reason": "name the setting to change: auto_read"}
    if not isinstance(auto_read, bool):
        return {"status": "rejected", "reason": "auto_read must be true or false"}
    try:
        store = sung_labels.load()
    except sung_labels.StoreUnreadable as exc:
        return {"status": "rejected", "reason": str(exc)}
    before = {"auto_read": store.settings.auto_read}
    after = {"auto_read": auto_read}
    question = None
    if after["auto_read"] and not before["auto_read"]:
        question = ("Turn on reading songs automatically? Claude will read any song that "
                    "has not been read, and re-read a song when the words on this list "
                    "change — one song a minute, continuously, which spends your Claude "
                    "allowance the whole time it is on.")
    fp = _fingerprint("set_lyric_reading_settings", {"auto_read": auto_read}, before)
    if question is not None:
        if confirm_id is None:
            return _ask("set_lyric_reading_settings", fp, question)
        refusal = _redeem("set_lyric_reading_settings", fp, confirm_id)
        if refusal:
            return refusal
    elif isinstance(confirm_id, str):
        _PENDING.pop(confirm_id, None)      # moot now; still single-use
    try:
        sung_labels.set_auto_read(auto_read)
    except sung_labels.EditRefused as exc:
        return {"status": "rejected", "reason": str(exc)}
    summary = (f"reading songs automatically: {_onoff(before['auto_read'])} → "
               f"{_onoff(after['auto_read'])}.")
    return {"status": "applied", "old": before, "new": after, "summary": summary}


# ── reading and changing the labels themselves ──────────────────────────────

def _op_list_sung_label_targets(kind: Optional[str] = None) -> dict:
    if kind is not None and kind not in TARGET_KINDS:
        return {"status": "rejected", "reason": "kind must be color_set or effect"}
    try:
        page = sung_labels.page()
    except sung_labels.StoreUnreadable as exc:
        return {"status": "rejected", "reason": str(exc)}
    out: list[dict] = []
    if kind in (None, "color_set"):
        for row in page["color_sets"]:
            out.append({"kind": "color_set", "name": row["name"], "disabled": row["disabled"],
                        "has_colours": row["has_colours"], "n_labels": len(row["labels"]),
                        "drafted": row["drafted_ms"] is not None})
    if kind in (None, "effect"):
        for row in page["effects"]:
            out.append({"kind": "effect", "name": row["name"], "n_labels": len(row["labels"])})
    return {"targets": out}


def _op_get_sung_labels(kind: str, name: str) -> dict:
    target_id, rejection = _resolve_target(kind, name)
    if rejection:
        return rejection
    try:
        row = _page_row(kind, target_id)
    except sung_labels.StoreUnreadable as exc:
        return {"status": "rejected", "reason": str(exc)}
    if row is None:
        return {"status": "rejected", "reason": "that target no longer exists"}
    out = {"kind": kind, "name": row["name"], "labels": row["labels"]}
    if kind == "color_set":
        out.update(meanings=row["meanings"], has_colours=row["has_colours"],
                   disabled=row["disabled"], drafted_ms=row["drafted_ms"],
                   draft_model=row["draft_model"])
    return out


async def _op_edit_sung_label(kind: str, name: str, list: str, op: str, text: str) -> dict:
    if list not in LIST_KINDS:
        return {"status": "rejected", "reason": "list must be labels, things, moods or places"}
    if op not in ("add", "remove"):
        return {"status": "rejected", "reason": "op must be add or remove"}
    target_id, rejection = _resolve_target(kind, name)
    if rejection:
        return rejection
    try:
        sung_labels.edit(kind, target_id, list, op, text)
        row = _page_row(kind, target_id)
    except sung_labels.EditRefused as exc:
        return {"status": "rejected", "reason": str(exc)}
    except sung_labels.StoreUnreadable as exc:
        return {"status": "rejected", "reason": str(exc)}
    display_name = row["name"] if row else name
    return {"status": "applied", "name": display_name, "row": row,
            "summary": f"{text.strip()!r} {'added to' if op == 'add' else 'taken off'} "
                      f"{display_name}'s {list}."}


async def _op_draft_colour_meanings(names: list, confirm_id: Optional[str] = None) -> dict:
    if not isinstance(names, list) or not names or not all(isinstance(n, str) for n in names):
        return {"status": "rejected",
                "reason": "names must be a non-empty list of colour set names"}
    if len(names) > color_meanings.DRAFT_BATCH_SIZE:
        return {"status": "rejected",
                "reason": f"draft at most {color_meanings.DRAFT_BATCH_SIZE} colour sets at a time"}
    ids: list[str] = []
    for n in names:
        target_id, rejection = _resolve_target("color_set", n)
        if rejection:
            return rejection
        ids.append(target_id)
    avail = claude_text.availability()
    if not avail["available"]:
        return {"status": "rejected", "reason": avail["reason"]}
    fp = _fingerprint("draft_colour_meanings", {"ids": sorted(ids)}, {})
    if confirm_id is None:
        question = (f"Ask Claude to draft meanings (things, moods, places) for "
                    f"{len(ids)} colour set{'s' if len(ids) != 1 else ''}: "
                    f"{', '.join(names)}? This spends your Claude allowance.")
        return _ask("draft_colour_meanings", fp, question)
    refusal = _redeem("draft_colour_meanings", fp, confirm_id)
    if refusal:
        return refusal
    try:
        result = await color_meanings.draft(ids)
    except color_meanings.DraftRefused as exc:
        return {"status": "rejected", "reason": str(exc)}
    except claude_text.ClaudeUnavailable as exc:
        return {"status": "rejected", "reason": str(exc)}
    except claude_text.ClaudeReplyInvalid as exc:
        return {"status": "rejected", "reason": str(exc)}
    except sung_labels.StoreUnreadable as exc:
        return {"status": "rejected", "reason": str(exc)}
    skipped = result.get("skipped") or []
    summary = f"Drafted meanings for {result['drafted']} colour set(s)."
    if skipped:
        summary += f" {len(skipped)} had no colours of their own and were left out."
    return {"status": "applied", **result, "summary": summary}


# ── one song's word matches ─────────────────────────────────────────────────

def _op_get_lyric_matches(song: Optional[str] = None) -> dict:
    uri, rejection = _resolve_song(song)
    if rejection:
        return rejection
    try:
        data = lyric_matches.payload(uri)
    except sung_labels.StoreUnreadable as exc:
        return {"status": "rejected", "reason": str(exc)}
    return {**data, "song": _song_name(uri)}


async def _op_add_lyric_match(target_kind: str, target_name: str, phrase: str,
                              song: Optional[str] = None, occurrence: int = 1) -> dict:
    if not isinstance(occurrence, int) or occurrence < 1:
        return {"status": "rejected", "reason": "occurrence must be a whole number, 1 or more"}
    uri, rejection = _resolve_song(song)
    if rejection:
        return rejection
    timeline = lyrics_timeline.timeline_for_uri(uri)
    if not timeline.usable:
        return {"status": "rejected",
                "reason": timeline.note or "this song has no usable word timeline"}
    phrase_keys = _phrase_keys(phrase)
    if not phrase_keys:
        return {"status": "rejected", "reason": "name a word or phrase that is actually sung"}
    keys = lyric_matches.word_keys(timeline.scored)
    spots = _find_occurrences(keys, phrase_keys)
    if not spots:
        return {"status": "rejected", "reason": f"{phrase!r} is not sung in this song"}
    if occurrence > len(spots):
        return {"status": "rejected",
                "reason": f"{phrase!r} is sung {len(spots)} time(s) in this song — "
                          f"occurrence must be between 1 and {len(spots)}"}
    target_id, t_rejection = _resolve_target(target_kind, target_name)
    if t_rejection:
        return t_rejection
    first, last = spots[occurrence - 1]
    try:
        data = lyric_matches.add(uri, first, last, TargetRef(kind=target_kind, id=target_id))
        row = _page_row(target_kind, target_id)
    except lyric_matches.MatchRefused as exc:
        return {"status": "rejected", "reason": str(exc)}
    except sung_labels.StoreUnreadable as exc:
        return {"status": "rejected", "reason": str(exc)}
    display_name = row["name"] if row else target_name
    return _applied(data, song=_song_name(uri), summary=f"{phrase!r} matched to {display_name}.")


async def _op_delete_lyric_match(phrase: str, song: Optional[str] = None,
                                 label: Optional[str] = None) -> dict:
    uri, rejection = _resolve_song(song)
    if rejection:
        return rejection
    try:
        data = lyric_matches.payload(uri)
    except sung_labels.StoreUnreadable as exc:
        return {"status": "rejected", "reason": str(exc)}
    phrase_key = colour_words.word_key(phrase)
    label_key = colour_words.word_key(label) if label else None
    hits = [m for m in data.get("matches", [])
            if colour_words.word_key(m["phrase"]) == phrase_key
            and (label_key is None or colour_words.word_key(m["label"]) == label_key)]
    if not hits:
        return {"status": "rejected",
                "reason": f"no match on {phrase!r} in this song"
                          + (f" labelled {label!r}" if label else ""),
                "current_matches": [{"phrase": m["phrase"], "label": m["label"]}
                                    for m in data.get("matches", [])]}
    if len(hits) > 1:
        return {"status": "rejected",
                "reason": f"more than one match on {phrase!r} — name the label too",
                "candidates": [{"phrase": m["phrase"], "label": m["label"]} for m in hits]}
    try:
        new_data = lyric_matches.delete(uri, hits[0]["id"])
    except lyric_matches.MatchRefused as exc:
        return {"status": "rejected", "reason": str(exc)}
    except sung_labels.StoreUnreadable as exc:
        return {"status": "rejected", "reason": str(exc)}
    return _applied(new_data, song=_song_name(uri),
                    summary=f"Took {hits[0]['phrase']!r} ({hits[0]['label']}) off the timeline.")


async def _op_restore_lyric_matches(song: Optional[str] = None) -> dict:
    uri, rejection = _resolve_song(song)
    if rejection:
        return rejection
    try:
        before = lyric_matches.payload(uri)
        data = lyric_matches.restore_deleted(uri)
    except sung_labels.StoreUnreadable as exc:
        return {"status": "rejected", "reason": str(exc)}
    n = before.get("n_deleted", 0)
    summary = (f"Brought back {n} deleted guess(es)." if n
              else "There were no deleted guesses to bring back.")
    return _applied(data, song=_song_name(uri), summary=summary)


async def _op_read_song_lyrics(song: Optional[str] = None,
                               confirm_id: Optional[str] = None) -> dict:
    uri, rejection = _resolve_song(song)
    if rejection:
        return rejection
    timeline = lyrics_timeline.timeline_for_uri(uri)
    if not timeline.usable:
        return {"status": "rejected",
                "reason": timeline.note or "this song has no usable word timeline"}
    try:
        catalogue = sung_labels.catalogue()
    except sung_labels.StoreUnreadable as exc:
        return {"status": "rejected", "reason": str(exc)}
    if not catalogue.labels:
        return {"status": "rejected", "reason": "there are no sung labels to read against yet"}
    avail = claude_text.availability()
    if not avail["available"]:
        return {"status": "rejected", "reason": avail["reason"]}
    name = _song_name(uri)
    fp = _fingerprint("read_song_lyrics", {"uri": uri}, {})
    if confirm_id is None:
        question = (f"Ask Claude to read {name!r}'s lyrics against the sung-label list now? "
                    "This spends your Claude allowance.")
        return _ask("read_song_lyrics", fp, question)
    refusal = _redeem("read_song_lyrics", fp, confirm_id)
    if refusal:
        return refusal
    try:
        data = await lyric_reading.read_song(uri)
    except (lyric_reading.NoUsableWords, lyric_reading.NoLabels) as exc:
        return {"status": "rejected", "reason": str(exc)}
    except claude_text.ClaudeUnavailable as exc:
        return {"status": "rejected", "reason": str(exc)}
    except claude_text.ClaudeReplyInvalid as exc:
        return {"status": "rejected", "reason": str(exc)}
    except sung_labels.StoreUnreadable as exc:
        return {"status": "rejected", "reason": str(exc)}
    reading = data.get("reading") or {}
    n_matches = len([m for m in data.get("matches", []) if m.get("source") == "claude"])
    summary = (f"Read {name!r}: {n_matches} match(es) found, "
               f"{reading.get('n_refused', 0)} refused.")
    return _applied(data, song=name, summary=summary)


# ── word colours and imprints: the per-show switch, tuning and preview ─────

def _op_get_lyric_event_settings(song: Optional[str] = None) -> dict:
    uri, rejection = _resolve_song(song)
    if rejection:
        return rejection
    try:
        tuning = lyric_events.settings()
        on = lyric_events.enabled(uri)
        n_shows_on = len(lyric_events.shows_on())
    except lyric_events.StoreUnreadable as exc:
        return {"status": "rejected", "reason": str(exc)}
    return {"song": _song_name(uri), "enabled": on, "n_shows_on": n_shows_on,
            **tuning.model_dump()}


async def _op_set_lyric_event_show(enabled: Optional[bool] = None, song: Optional[str] = None,
                                   confirm_id: Optional[str] = None) -> dict:
    if not isinstance(enabled, bool):
        return {"status": "rejected", "reason": "enabled must be true or false"}
    uri, rejection = _resolve_song(song)
    if rejection:
        return rejection
    try:
        before = lyric_events.enabled(uri)
    except lyric_events.StoreUnreadable as exc:
        return {"status": "rejected", "reason": str(exc)}
    name = _song_name(uri)
    fp = _fingerprint("set_lyric_event_show", {"uri": uri, "enabled": enabled},
                      {"before": before})
    if enabled and not before:
        question = (f"Turn word colours on for {name!r}? A matched word can then change the "
                    "room's colours while this song plays.")
        if confirm_id is None:
            return _ask("set_lyric_event_show", fp, question)
        refusal = _redeem("set_lyric_event_show", fp, confirm_id)
        if refusal:
            return refusal
    elif isinstance(confirm_id, str):
        _PENDING.pop(confirm_id, None)      # moot now; still single-use
    try:
        lyric_events.set_show(uri, enabled)
    except lyric_events.StoreUnreadable as exc:
        return {"status": "rejected", "reason": str(exc)}
    return {"status": "applied", "song": name, "old": before, "new": enabled,
            "summary": f"Word colours for {name!r}: {_onoff(before)} → {_onoff(enabled)}."}


async def _op_set_lyric_event_settings(energy_cutoff: Optional[float] = None,
                                       min_gap_s: Optional[float] = None,
                                       imprint_window_s: Optional[float] = None) -> dict:
    if energy_cutoff is None and min_gap_s is None and imprint_window_s is None:
        return {"status": "rejected",
                "reason": "name at least one setting to change: energy_cutoff, min_gap_s or "
                          "imprint_window_s"}
    try:
        before = lyric_events.settings()
        after = lyric_events.update_settings(energy_cutoff=energy_cutoff, min_gap_s=min_gap_s,
                                             imprint_window_s=imprint_window_s)
    except lyric_events.StoreUnreadable as exc:
        return {"status": "rejected", "reason": str(exc)}
    except ValueError as exc:
        return {"status": "rejected", "reason": str(exc)}
    bits = []
    for key, label in (("energy_cutoff", "energy cut-off"), ("min_gap_s", "minimum gap"),
                       ("imprint_window_s", "imprint window")):
        old, new = getattr(before, key), getattr(after, key)
        if old != new:
            bits.append(f"{label}: {old} → {new}")
    return {"status": "applied", "old": before.model_dump(), "new": after.model_dump(),
            "summary": ("; ".join(bits) + "." if bits else "Nothing changed.")}


async def _op_preview_lyric_events(song: Optional[str] = None) -> dict:
    uri, rejection = _resolve_song(song)
    if rejection:
        return rejection
    try:
        resp = await http("GET", "/api/testbed/lyric-events", params={"uri": uri})
        resp.raise_for_status()
    except Exception as exc:                                # noqa: BLE001
        return _unreachable(exc)
    return {**resp.json(), "song": _song_name(uri)}


# ── the declarations ─────────────────────────────────────────────────────────

_CONFIRM_PROP = {"type": "string",
                 "description": "The confirm_id a needs_confirmation result returned — only "
                                 "pass it after he has said yes to that exact question."}
_INSTR_CONFIRM = (
    " When the result's status is needs_confirmation NOTHING has happened yet: read him the "
    "question and that confirm_id, verbatim. Never call again with a confirm_id he has not "
    "said yes to.")
_SONG_PROP = {"type": "string",
             "description": "The song's title (or title and artist) — omit to mean whatever "
                             "is playing right now."}
_KIND_PROP = {"type": "string", "enum": list(TARGET_KINDS),
             "description": "color_set (a colour set or group on the Colours page) or "
                             "effect (a registered light effect)."}

OPERATIONS: dict[str, SonicOperation] = {
    "get_lyric_reading_settings": SonicOperation(
        name="get_lyric_reading_settings", domain="lyrics", kind="read",
        summary="Read whether songs are read automatically.",
        instructions=("No arguments. Call this before changing it so you can tell him the "
                     "current value. There is no weak-match threshold any more: every guess "
                     "is kept, and its confidence is the share of plays it acts on."),
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=_op_get_lyric_reading_settings,
    ),
    "set_lyric_reading_settings": SonicOperation(
        name="set_lyric_reading_settings", domain="lyrics", kind="write",
        summary="Turn reading songs automatically on or off.",
        instructions=(
            "Pass auto_read (true/false). Turning it ON needs his yes first (it spends his "
            "Claude allowance continuously, one song a minute, with nobody pressing "
            "anything)." + _INSTR_CONFIRM + " Turning it off applies at once with no "
            "confirm_id needed."),
        input_schema={
            "type": "object",
            "properties": {
                "auto_read": {"type": "boolean"},
                "confirm_id": _CONFIRM_PROP},
            "additionalProperties": False},
        handler=_op_set_lyric_reading_settings,
    ),
    "list_sung_label_targets": SonicOperation(
        name="list_sung_label_targets", domain="lyrics", kind="read",
        summary="List every colour set's and effect's name, with how many sung labels "
                "each carries.",
        instructions=("Pass kind (color_set or effect) to narrow it, or omit it for both. "
                     "Call this first to find the exact name get_sung_labels / "
                     "edit_sung_label expect — a close spoken name still resolves, but the "
                     "real name is never wrong."),
        input_schema={"type": "object",
                     "properties": {"kind": _KIND_PROP},
                     "additionalProperties": False},
        handler=_op_list_sung_label_targets,
    ),
    "get_sung_labels": SonicOperation(
        name="get_sung_labels", domain="lyrics", kind="read",
        summary="Read one colour set's or effect's sung labels (and, for a colour set, "
                "its drafted meanings: things, moods, places).",
        instructions="kind and name (a close spoken name resolves; a near-tie is refused).",
        input_schema={"type": "object",
                     "properties": {"kind": _KIND_PROP, "name": {"type": "string"}},
                     "required": ["kind", "name"], "additionalProperties": False},
        handler=_op_get_sung_labels,
    ),
    "edit_sung_label": SonicOperation(
        name="edit_sung_label", domain="lyrics", kind="write",
        summary="Add or take off one word from a colour set's or effect's sung labels, "
                "or from a colour set's drafted meanings (things/moods/places).",
        instructions=(
            "kind, name, list (labels, or — colour sets only — things/moods/places), "
            "op (add or remove) and text (the one word or short phrase). An effect only has "
            "labels. Removing a seeded or drafted word just takes it off his view of the "
            "list — a later re-seed or re-draft offering it again will not bring it back "
            "until he adds it again himself."),
        input_schema={
            "type": "object",
            "properties": {
                "kind": _KIND_PROP, "name": {"type": "string"},
                "list": {"type": "string", "enum": list(LIST_KINDS)},
                "op": {"type": "string", "enum": ["add", "remove"]},
                "text": {"type": "string"}},
            "required": ["kind", "name", "list", "op", "text"], "additionalProperties": False},
        handler=_op_edit_sung_label,
    ),
    "draft_colour_meanings": SonicOperation(
        name="draft_colour_meanings", domain="lyrics", kind="write",
        summary="Ask Claude to draft things/moods/places for up to "
                f"{color_meanings.DRAFT_BATCH_SIZE} named colour sets "
                "— SPENDS HIS CLAUDE ALLOWANCE, every call.",
        instructions=(
            f"names: a list of up to {color_meanings.DRAFT_BATCH_SIZE} colour set names. "
            "This always needs his yes first, "
            "every single call, because every call asks Claude." + _INSTR_CONFIRM + " A word "
            "he already added or removed on any of these sets is never touched by the "
            "draft — only the draft's own words move."),
        input_schema={
            "type": "object",
            "properties": {
                "names": {"type": "array", "items": {"type": "string"}, "minItems": 1,
                          "maxItems": 10},
                "confirm_id": _CONFIRM_PROP},
            "required": ["names"], "additionalProperties": False},
        handler=_op_draft_colour_meanings,
    ),
    "get_lyric_matches": SonicOperation(
        name="get_lyric_matches", domain="lyrics", kind="read",
        summary="Show one song's matched words: Claude's latest reading and his own "
                "corrections.",
        instructions="song is optional (omit to mean whatever is playing now).",
        input_schema={"type": "object", "properties": {"song": _SONG_PROP},
                     "additionalProperties": False},
        handler=_op_get_lyric_matches,
    ),
    "add_lyric_match": SonicOperation(
        name="add_lyric_match", domain="lyrics", kind="write",
        summary="Match a sung word or phrase to a colour set or effect, himself.",
        instructions=(
            "target_kind, target_name (the colour set or effect it should reach), phrase "
            "(the exact words, copied as sung — case and accents do not matter) and song "
            "(optional, defaults to whatever is playing). If that phrase is sung more than "
            "once, occurrence (1-based, default 1) picks which; the result names how many "
            "times it is sung so you can ask which one he means."),
        input_schema={
            "type": "object",
            "properties": {
                "target_kind": _KIND_PROP, "target_name": {"type": "string"},
                "phrase": {"type": "string"}, "song": _SONG_PROP,
                "occurrence": {"type": "integer", "minimum": 1}},
            "required": ["target_kind", "target_name", "phrase"],
            "additionalProperties": False},
        handler=_op_add_lyric_match,
    ),
    "delete_lyric_match": SonicOperation(
        name="delete_lyric_match", domain="lyrics", kind="write",
        summary="Take a match off a song's timeline — his own, or one of Claude's "
                "guesses (which stays deleted through every later reading).",
        instructions=(
            "phrase (as shown in get_lyric_matches) and song (optional). Pass label too "
            "when the same phrase has more than one match — the result names every current "
            "match on that phrase so you can tell which one he means."),
        input_schema={
            "type": "object",
            "properties": {"phrase": {"type": "string"}, "song": _SONG_PROP,
                          "label": {"type": "string"}},
            "required": ["phrase"], "additionalProperties": False},
        handler=_op_delete_lyric_match,
    ),
    "restore_lyric_matches": SonicOperation(
        name="restore_lyric_matches", domain="lyrics", kind="write",
        summary="Bring back every one of Claude's guesses he deleted on a song.",
        instructions="song is optional (omit to mean whatever is playing now).",
        input_schema={"type": "object", "properties": {"song": _SONG_PROP},
                     "additionalProperties": False},
        handler=_op_restore_lyric_matches,
    ),
    "read_song_lyrics": SonicOperation(
        name="read_song_lyrics", domain="lyrics", kind="write",
        summary="Ask Claude to read one song's lyrics against the sung-label list, now "
                "— SPENDS HIS CLAUDE ALLOWANCE, every call.",
        instructions=(
            "song is optional (omit to mean whatever is playing now). This always needs his "
            "yes first, every single call, because every call asks Claude." + _INSTR_CONFIRM
            + " Replaces only Claude's previous reading of that one song; none of his own "
            "matches or deletions are touched."),
        input_schema={
            "type": "object",
            "properties": {"song": _SONG_PROP, "confirm_id": _CONFIRM_PROP},
            "additionalProperties": False},
        handler=_op_read_song_lyrics,
    ),
    "get_lyric_event_settings": SonicOperation(
        name="get_lyric_event_settings", domain="lyrics", kind="read",
        summary="Read whether word colours are on for a song, the energy cut-off, minimum "
                "gap and imprint window, and how many shows have it on.",
        instructions="song is optional (omit to mean whatever is playing now).",
        input_schema={"type": "object", "properties": {"song": _SONG_PROP},
                     "additionalProperties": False},
        handler=_op_get_lyric_event_settings,
    ),
    "set_lyric_event_show": SonicOperation(
        name="set_lyric_event_show", domain="lyrics", kind="write",
        summary="Turn word colours on or off for one song's show.",
        instructions=(
            "enabled (true/false) and song (optional, defaults to whatever is playing). "
            "Turning it ON needs his yes first — a matched word can then change the room's "
            "colours while that song plays." + _INSTR_CONFIRM + " Turning it off applies at "
            "once with no confirm_id needed."),
        input_schema={
            "type": "object",
            "properties": {"enabled": {"type": "boolean"}, "song": _SONG_PROP,
                          "confirm_id": _CONFIRM_PROP},
            "required": ["enabled"], "additionalProperties": False},
        handler=_op_set_lyric_event_show,
    ),
    "set_lyric_event_settings": SonicOperation(
        name="set_lyric_event_settings", domain="lyrics", kind="write",
        summary="Change the energy cut-off, minimum gap and/or imprint window word colours "
                "use — shared by every show.",
        instructions=(
            "Pass energy_cutoff (0 to 1 — at or above this a word's colour is momentary, "
            "below it the colour holds), min_gap_s (0 to 120 — the shortest distance between "
            "two lyric events, fired or imprinted) and/or imprint_window_s (0 to 10 — how "
            "close a word must be, either way, to a drop/scene change/flare to give it its "
            "colour instead of firing on its own) — whichever he asked to change; an omitted "
            "one is left exactly as it is. Applies at once, no confirm_id needed; out-of-range "
            "is refused with nothing changed."),
        input_schema={
            "type": "object",
            "properties": {
                "energy_cutoff": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "min_gap_s": {"type": "number", "minimum": 0.0, "maximum": 120.0},
                "imprint_window_s": {"type": "number", "minimum": 0.0, "maximum": 10.0}},
            "additionalProperties": False},
        handler=_op_set_lyric_event_settings,
    ),
    "preview_lyric_events": SonicOperation(
        name="preview_lyric_events", domain="lyrics", kind="read",
        summary="Show what each matched word in a song would do — fire its own colour, "
                "give it to a nearby drop, scene change/update or flare, or do nothing and "
                "why — the same plan the Test Bed's Word actions row shows.",
        instructions=(
            "song is optional (omit to mean whatever is playing now). Works whether or not "
            "word colours are switched on for that song — it previews the plan either way, "
            "and the result's own enabled field says which. Each play rolls which words act: "
            "a word plays on the share of plays its `chance` says (Claude's confidence; his "
            "own matches and Always pins every time). `roll.state` says which play the plan "
            "is for — `playing` (this play of the song playing, `roll.tag` its number), "
            "`kept` (his kept roll), or `none` (not playing: every word shown as if it "
            "plays) — and `won` false / why `sat_out` marks a word sitting out this play."),
        input_schema={"type": "object", "properties": {"song": _SONG_PROP},
                     "additionalProperties": False},
        handler=_op_preview_lyric_events,
    ),
}
