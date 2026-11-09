"""Claude drafts what each colour set means: the things, moods and places a
singer might use for it (lyrics plan step 3). He corrects them on one page.

A DRAFT IS A STARTING POINT AND NEVER OVERWRITES HIM. Only the `draft` lists are
written (sung_labels.apply_draft). A word he added stays, a word he took out
stays out even when the next draft offers it again.

BATCHED AT THE CALLER. The page sends DRAFT_BATCH_SIZE cards at a time and shows
its progress, so each call is short enough for an ordinary request, and closing
the tab simply stops: pressing again carries on with the cards not yet drafted.
A card with no colours of its own (his brightness-only sets) has nothing to
mean and is left out.

TELLING SETS APART (the Admiral, 2026-11-09: "redraft with less repitition").
A batch cannot see another batch's words -- each is its own request -- so a
word so generic it fits every set (nightclub, ocean, calm, euphoria) gets
offered again and again with nothing to say it doesn't belong on 15 other
sets too. Two things fix that without a second Claude call: each batch is
told which words are already common on the list so far (_overused_words) and
asked to tell this set apart from a similar one rather than reach for the
same word; and after every draft, sung_labels._enforce_meaning_word_cap trims
a word back down to MEANING_WORD_CAP sets (a wider cap for a genuine colour
word, which may honestly belong to a whole family of same-hued sets).
"""
from __future__ import annotations

import asyncio
from collections import Counter
from typing import Any, Awaitable, Callable, Optional, Sequence

from spectra.models.lyric_labels import MEANING_KINDS
from spectra.services import claude_text, color_sets, colour_words, sung_labels

Ask = Callable[..., Awaitable[claude_text.ClaudeReply]]

DRAFT_BATCH_SIZE = 4
# Must finish inside the spotfx reverse proxy's 60s read timeout
# (services/spectra_proxy.py's READ_TIMEOUT_S), which a 10-set batch did not:
# a live batch of 10 took 66s, about 6.6s/set. At that rate 4 sets take about
# 26s, comfortably under a 30s target (half the proxy's budget, so normal
# per-set variance doesn't reopen the timeout). Raising this constant back
# toward 10 reintroduces the 502 the Admiral hit on 2026-11-09.
MAX_WORDS_PER_KIND = 6
MAX_WORD_CHARS = 40

# A word already drafted on this many sets or more is named to the next batch
# as common, so it reaches for something more specific instead of adding a
# 3rd/4th use that the word cap would trim right back out anyway.
OVERUSED_THRESHOLD = 2
# How many of those words to actually name; the point is a steer, not a
# second full inventory, and keeping this short keeps the spend small.
MAX_TAKEN_WORDS = 30

SYSTEM_PROMPT = (
    "You help tune a home light show that reacts to the words in songs. Each "
    "colour set below is a named palette of colours. For each one, list what those "
    "colours bring to mind, as words a singer might actually sing:\n"
    "- things: concrete things and natural phenomena (fire, ocean, roses)\n"
    "- moods: feelings (longing, joy, rage)\n"
    "- places: places or settings (desert, beach, the city at night)\n\n"
    f"Give up to {MAX_WORDS_PER_KIND} of each kind, one or two words each, lower "
    "case, in English. Choose words specific to that set's own colours and name, "
    "and leave a kind short rather than padding it. Do not list the names of the "
    "colours themselves; those are already known.\n\n"
    "Many sets share a colour family, so a word that fits every blue set or every "
    "fiery set tells them apart from nothing. For each set, favour what makes IT "
    "different from a similar set of the same family -- its particular shade, its "
    "name, how dark, pale or busy its palette is -- over a generic word that could "
    "sit on any of them. A line below may list words already common on other "
    "sets; avoid reaching for one of those again unless it is the one unmistakable "
    "word for this set's own colour (a plain colour name like 'red' or 'gold' is "
    "fine even if it repeats). Use each set's code exactly as given."
)

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"sets": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "code": {"type": "string"},
            "things": {"type": "array", "items": {"type": "string"}},
            "moods": {"type": "array", "items": {"type": "string"}},
            "places": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["code", "things", "moods", "places"],
        "additionalProperties": False,
    }}},
    "required": ["sets"],
    "additionalProperties": False,
}


class DraftRefused(ValueError):
    pass


def _describe(card: color_sets.ColorSetCard,
              by_id: dict[str, color_sets.ColorSetCard]) -> Optional[str]:
    palette = sung_labels.card_palette(card, by_id)
    if not palette:
        return None
    if card.is_rainbow:
        colours = "every colour of the rainbow"
    else:
        names: list[str] = []
        for hex_colour in palette:
            family = colour_words.family_of(hex_colour)[0]
            if family and family not in names:
                names.append(family)
        colours = ", ".join(names)
    return f"{card.name} (colours: {colours}; hex: {' '.join(palette[:6])})"


def _overused_words(store: sung_labels.SungLabelStore) -> list[str]:
    """Words already drafted on OVERUSED_THRESHOLD or more sets, most-common
    first. A genuine colour word is left out: the prompt already excuses it
    from this, and MEANING_WORD_CAP_COLOUR, not MEANING_WORD_CAP, is its cap."""
    counts: Counter[str] = Counter()
    display: dict[str, str] = {}
    for row in store.color_sets.values():
        seen_on_this_card: set[str] = set()
        for kind in MEANING_KINDS:
            for word in getattr(row.meanings, kind).draft:
                key = colour_words.word_key(word)
                if colour_words.is_colour_word(key) or key in seen_on_this_card:
                    continue
                seen_on_this_card.add(key)
                counts[key] += 1
                display.setdefault(key, word)
    words = [display[key] for key, n in counts.items() if n >= OVERUSED_THRESHOLD]
    words.sort(key=lambda w: -counts[colour_words.word_key(w)])
    return words[:MAX_TAKEN_WORDS]


def build_prompt(cards: Sequence[color_sets.ColorSetCard],
                 by_id: dict[str, color_sets.ColorSetCard],
                 taken: Sequence[str] = ()) -> tuple[str, dict[str, str]]:
    """The user message, and which code stands for which card."""
    lines: list[str] = []
    if taken:
        lines.append("Already common on other sets, so used up: " + ", ".join(taken))
        lines.append("")
    codes: dict[str, str] = {}
    for card in cards:
        description = _describe(card, by_id)
        if description is None:
            continue
        code = f"c{len(codes)}"
        codes[code] = card.id
        lines.append(f"{code}: {description}")
    return "\n".join(lines), codes


def parse_reply(data: dict[str, Any], codes: dict[str, str]) -> dict[str, dict[str, list[str]]]:
    """Each card's meanings. A code that is not one of ours is dropped."""
    out: dict[str, dict[str, list[str]]] = {}
    for row in data.get("sets") or []:
        if not isinstance(row, dict) or row.get("code") not in codes:
            continue
        meanings: dict[str, list[str]] = {}
        for kind in MEANING_KINDS:
            words: list[str] = []
            for raw in row.get(kind) or []:
                if not isinstance(raw, str):
                    continue
                try:
                    word = sung_labels.clean_label(raw)
                except sung_labels.EditRefused:
                    continue
                if len(word) <= MAX_WORD_CHARS:
                    words.append(word)
            meanings[kind] = colour_words.dedupe(words)[:MAX_WORDS_PER_KIND]
        out[codes[row["code"]]] = meanings
    return out


async def draft(ids: Sequence[str], *, ask: Optional[Ask] = None) -> dict[str, Any]:
    """Draft these cards. Returns how many were drafted and any it could not."""
    if len(ids) > DRAFT_BATCH_SIZE:
        raise DraftRefused(f"Draft at most {DRAFT_BATCH_SIZE} colour sets at a time.")
    all_cards = await asyncio.to_thread(color_sets.list_all)
    by_id = {c.id: c for c in all_cards}
    cards = [by_id[i] for i in ids if i in by_id]
    store = await asyncio.to_thread(sung_labels.load)
    taken = _overused_words(store)
    user, codes = build_prompt(cards, by_id, taken)
    if not codes:
        return {"drafted": 0, "ids": [], "skipped": list(ids)}
    reply = await (ask or claude_text.ask_json)(
        system=SYSTEM_PROMPT, user=user, schema=SCHEMA, purpose="colour-meanings")
    drafts = parse_reply(reply.data, codes)
    if drafts:
        await asyncio.to_thread(sung_labels.apply_draft, drafts, reply.model)
    return {"drafted": len(drafts), "ids": sorted(drafts),
            "skipped": sorted(set(ids) - set(drafts)), "model": reply.model}
