"""The sung labels (lyrics plan step 3, data/lyrics-timing-plan/
grilling-notes.md): the words a colour set or an effect answers to when
someone sings them. Claude reads each song's lyrics against this list
(spectra/services/lyric_reading.py); he corrects it on /sung-labels.

The Admiral, 2026-11-09: "We do need to interpret when the subject of an
emphasized phrase or word relates to something like a color or some other
thing from a list we can build. That list should take from the effects, where
we can add 'labels' similar to like how we did in spotfx."

THIS HAS NO EFFECT ON THE ROOM. Nothing in the show reads this module; firing
anything from a match is a later step, and off by default.

ONE LIST PER CARD, BUILT FROM FOUR PLACES, ONLY ONE OF WHICH IS COMPUTED:
  seed     — the card's colours and name (colour_words.seed_labels), worked out
             on every read, so a set he recolours gets the right words.
  claude   — the meanings Claude drafted (things, moods, places).
  his      — whatever he added, and whatever seeded or drafted word he took out.

HIS EDITS ARE STORED AS DELTAS. The computed halves can change under them (a
re-draft, a recoloured set, a better seed table) and each of his edits still
stands, because it is a statement about one word, kept apart from the list it
changes. A re-draft only ever writes `draft`.

ITS OWN FILE, NOT A FIELD IN color_sets.json. The label belongs to a colour set
but SPECTRA never writes that file (color_sets.py's contract: authoring goes
through spot-effects, whose save rewrites the whole card from a page's copy).
Living here, nothing has to be migrated to deploy this, a card's own save cannot
lose it, and an edit on the Colours page cannot race one here. A card that is
deleted leaves its row behind, ignored.

AN UNREADABLE FILE RAISES (StoreUnreadable). An empty list would read as "he has
no edits" and the next save would write that over the ones he has.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from fx import device_model
from spectra import config
from spectra.models.lyric_labels import (
    MEANING_KINDS, ColorSetLabels, EffectLabels, LabelEdits, MeaningList, SungLabelStore,
)
from spectra.services import color_sets, colour_words

logger = logging.getLogger(__name__)

KIND_COLOR_SET = "color_set"
KIND_EFFECT = "effect"

SOURCE_SEED = "seed"
SOURCE_CLAUDE = "claude"
SOURCE_HIS = "his"

FIELD_LABELS = "labels"

MAX_LABEL_CHARS = 60

# The deterministic cap a re-draft enforces on its own (no second Claude
# call): a drafted meaning word may sit on at most this many sets before the
# weakest-fitting occurrences are trimmed. A genuine colour word (colour_words.
# is_colour_word) may honestly belong to a whole family of same-hued sets, so
# it gets a wider cap instead of none at all.
MEANING_WORD_CAP = 3
MEANING_WORD_CAP_COLOUR = 6

# What an effect answers to before he adds anything. The strip version of an
# effect shares its Matrix sibling's words: to someone singing, they are the
# same thing.
_BLACK_HOLE = ("black hole", "agujero negro", "void", "abyss", "gravity")
_ORBITS = ("orbit", "planet", "satellite", "circle")
_FIREWORKS = ("fireworks", "firework", "fuegos artificiales", "rocket", "explosion", "sparks")
_POWER = ("power", "poder", "energy")
EFFECT_SEEDS: dict[str, tuple[str, ...]] = {
    "blackhole": _BLACK_HOLE, "blackhole1d": _BLACK_HOLE,
    "orbits": _ORBITS, "orbits1d": _ORBITS,
    "fireworks": _FIREWORKS, "fireworks1d": _FIREWORKS,
    "fish": ("fish", "pez", "swim", "swimming", "school of fish"),
    "radial": ("star", "stars", "estrella", "shooting star"),
    "squiggles": ("snake", "serpiente", "worm", "wiggle"),
    "pacman": ("pacman", "ghost", "chase"),
    "dancer": ("dance", "dancing", "bailar", "dancer"),
    "eye": ("eye", "eyes", "ojos", "watching", "stare"),
    "sauron": ("sauron", "evil eye", "all seeing eye", "flames"),
    "pulse": ("pulse", "heartbeat", "latido"),
    "power": _POWER,
    "melt": ("melt", "melting", "drip", "wax"),
    "gradient": ("breathe", "breathing", "glow"),
}

EFFECT_NAMES: dict[str, str] = {
    "blackhole": "Black Hole", "blackhole1d": "Black Hole (strips)",
    "orbits1d": "Orbits (strips)", "fireworks1d": "Fireworks (strips)",
    "radial": "Star", "equalizer2d": "Equalizer", "keybeat2d": "Keybeat",
    "gifplayer": "GIF player", "pacman": "Pac-Man",
}

_lock = threading.RLock()


class StoreUnreadable(RuntimeError):
    pass


class EditRefused(ValueError):
    pass


@dataclass(frozen=True)
class Target:
    kind: str
    id: str
    name: str
    swatch: Optional[str] = None


@dataclass(frozen=True)
class Catalogue:
    """Everything a word can be read against, as of one moment."""
    targets: dict[tuple[str, str], Target]
    # label key -> display form
    labels: dict[str, str]
    # label key -> every card carrying that label
    owners: dict[str, tuple[Target, ...]]
    color_labels: tuple[str, ...] = ()
    effect_labels: tuple[str, ...] = ()
    labels_hash: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def load() -> SungLabelStore:
    path = config.SUNG_LABELS_FILE
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return SungLabelStore()
    try:
        return SungLabelStore.model_validate(json.loads(raw))
    except Exception as exc:
        raise StoreUnreadable(f"{path.name} cannot be read ({exc}); refusing to treat "
                              "it as empty") from exc


def _save(store: SungLabelStore) -> None:
    path = config.SUNG_LABELS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(store.model_dump(), ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def clean_label(text: str) -> str:
    """How a word is stored and shown: trimmed, single-spaced, lower case."""
    cleaned = " ".join(str(text or "").split()).lower().strip(" .,;:!?\"")
    if not colour_words.word_key(cleaned):
        raise EditRefused("A label has to contain a word.")
    if len(cleaned) > MAX_LABEL_CHARS:
        raise EditRefused(f"A label can be at most {MAX_LABEL_CHARS} characters.")
    return cleaned


def card_palette(card: color_sets.ColorSetCard,
                 by_id: dict[str, color_sets.ColorSetCard]) -> list[str]:
    """Every colour a card shows. A group's own entries are overrides, so what
    it shows is its members' colours as well."""
    palette = colour_words.palette_of(card.entries)
    if card.kind == "group":
        for member in card.members:
            child = by_id.get(member.color_set_id)
            if child is not None:
                palette += colour_words.palette_of(child.entries)
    return palette


def _swatch(palette: Sequence[str], fallback: str) -> str:
    """A colour to draw the card with: the first real hue in its palette. The
    swatch field is black on the sets authored for dark-background effects,
    and a white first stop ("Puerto Rico Red") says less than the red after it."""
    families = [(colour_words.family_of(h)[0], h) for h in palette]
    for family, hex_colour in families:
        if family not in (None, "black", "white", "grey"):
            return hex_colour
    for family, hex_colour in families:
        if family not in (None, "black"):
            return hex_colour
    return fallback


def _apply_edits(computed: Sequence[str], edits: LabelEdits) -> list[str]:
    """`computed` less what he took out, plus what he added."""
    removed = {colour_words.word_key(w) for w in edits.removed}
    kept = [w for w in computed if colour_words.word_key(w) not in removed]
    return colour_words.dedupe([*kept, *edits.added])


def _chips(computed: Sequence[str], source: str, edits: LabelEdits) -> list[dict]:
    computed_keys = {colour_words.word_key(w) for w in computed}
    added_keys = {colour_words.word_key(w) for w in edits.added}
    out = []
    for word in _apply_edits(computed, edits):
        key = colour_words.word_key(word)
        out.append({"text": word,
                    "source": SOURCE_HIS if key in added_keys and key not in computed_keys
                    else source})
    return out


def _effect_name(effect: str) -> str:
    return EFFECT_NAMES.get(effect) or effect.replace("_", " ").title()


def _meaning_words(row: Optional[ColorSetLabels], kind: str) -> list[str]:
    if row is None:
        return []
    meaning: MeaningList = getattr(row.meanings, kind)
    return _apply_edits(meaning.draft, meaning)


def _card_rows(store: SungLabelStore) -> list[dict]:
    cards = color_sets.list_all()
    by_id = {c.id: c for c in cards}
    out = []
    for card in cards:
        palette = card_palette(card, by_id)
        row = store.color_sets.get(card.id)
        edits = row.labels if row else LabelEdits()
        seed = colour_words.seed_labels(card.name, palette, is_rainbow=card.is_rainbow,
                                        is_pool=card.kind == "group")
        meanings = {}
        for kind in MEANING_KINDS:
            meaning: MeaningList = getattr(row.meanings, kind) if row else MeaningList()
            meanings[kind] = _chips(meaning.draft, SOURCE_CLAUDE, meaning)
        out.append({
            "id": card.id, "name": card.name, "kind": card.kind,
            "disabled": card.disabled, "swatch": _swatch(palette, card.color),
            "has_colours": bool(palette),
            "labels": _chips(seed, SOURCE_SEED, edits),
            "meanings": meanings,
            "drafted_ms": row.drafted_ms if row else None,
            "draft_model": row.draft_model if row else None,
        })
    return out


def _effect_rows(store: SungLabelStore) -> list[dict]:
    out = []
    for effect in device_model.effect_types():
        row = store.effects.get(effect)
        edits = row.labels if row else LabelEdits()
        out.append({"id": effect, "name": _effect_name(effect),
                    "labels": _chips(EFFECT_SEEDS.get(effect, ()), SOURCE_SEED, edits)})
    return sorted(out, key=lambda r: r["name"].lower())


def _hash_labels(color_labels: Sequence[str], effect_labels: Sequence[str]) -> str:
    keys = {"color": sorted(colour_words.word_key(w) for w in color_labels),
            "effect": sorted(colour_words.word_key(w) for w in effect_labels)}
    return hashlib.sha256(json.dumps(keys, ensure_ascii=False).encode("utf-8")).hexdigest()


def _build_catalogue(card_rows: list[dict], effect_rows: list[dict]) -> Catalogue:
    targets: dict[tuple[str, str], Target] = {}
    labels: dict[str, str] = {}
    owners: dict[str, list[Target]] = {}
    color_keys: set[str] = set()
    effect_keys: set[str] = set()

    def add(target: Target, words: list[str], bucket: set[str]) -> None:
        targets[(target.kind, target.id)] = target
        for word in colour_words.dedupe(words):
            key = colour_words.word_key(word)
            labels.setdefault(key, word)
            owners.setdefault(key, []).append(target)
            bucket.add(key)

    for row in card_rows:
        words = [c["text"] for c in row["labels"]]
        for kind in MEANING_KINDS:
            words += [c["text"] for c in row["meanings"][kind]]
        add(Target(KIND_COLOR_SET, row["id"], row["name"], row["swatch"]), words, color_keys)
    for row in effect_rows:
        add(Target(KIND_EFFECT, row["id"], row["name"]),
            [c["text"] for c in row["labels"]], effect_keys)

    color_labels = tuple(sorted(labels[k] for k in color_keys))
    effect_labels = tuple(sorted(labels[k] for k in effect_keys))
    return Catalogue(
        targets=targets, labels=labels,
        owners={k: tuple(v) for k, v in owners.items()},
        color_labels=color_labels, effect_labels=effect_labels,
        labels_hash=_hash_labels(color_labels, effect_labels))


def catalogue() -> Catalogue:
    """The whole label list right now. The hash covers only which words are
    on it: two sets swapping a word changes who a match reaches, which is
    resolved live, and needs no second reading of the lyrics."""
    store = load()
    return _build_catalogue(_card_rows(store), _effect_rows(store))


def page() -> dict:
    """What GET /api/sung-labels returns."""
    store = load()
    card_rows = _card_rows(store)
    effect_rows = _effect_rows(store)
    cat = _build_catalogue(card_rows, effect_rows)
    return {
        "color_sets": card_rows,
        "effects": effect_rows,
        "labels_hash": cat.labels_hash,
        "n_labels": len(cat.labels),
        "auto_read": store.settings.auto_read,
    }


def labels_changed_ms() -> int:
    return load().labels_changed_ms


def auto_read_enabled() -> bool:
    return load().settings.auto_read


def set_auto_read(enabled: bool) -> bool:
    with _lock:
        store = load()
        store.settings.auto_read = bool(enabled)
        _save(store)
    return store.settings.auto_read


def _edit_list(edits: LabelEdits, computed: Sequence[str], op: str, word: str) -> None:
    key = colour_words.word_key(word)
    computed_keys = {colour_words.word_key(w) for w in computed}
    if op == "add":
        edits.removed = [w for w in edits.removed if colour_words.word_key(w) != key]
        if key not in computed_keys and key not in {colour_words.word_key(w) for w in edits.added}:
            edits.added.append(word)
    elif op == "remove":
        edits.added = [w for w in edits.added if colour_words.word_key(w) != key]
        if key in computed_keys and key not in {colour_words.word_key(w) for w in edits.removed}:
            edits.removed.append(word)
    else:
        raise EditRefused(f"Unknown edit {op!r}.")


def _seed_for_card(card_id: str) -> tuple[Optional[color_sets.ColorSetCard], list[str]]:
    cards = color_sets.list_all()
    by_id = {c.id: c for c in cards}
    card = by_id.get(card_id)
    if card is None:
        return None, []
    palette = card_palette(card, by_id)
    return card, colour_words.seed_labels(card.name, palette, is_rainbow=card.is_rainbow,
                                          is_pool=card.kind == "group")


def edit(kind: str, target_id: str, field_name: str, op: str, text: str) -> None:
    """One word added to or taken out of one list."""
    word = clean_label(text)
    with _lock:
        store = load()
        if kind == KIND_COLOR_SET:
            card, seed = _seed_for_card(target_id)
            if card is None:
                raise EditRefused("That colour set no longer exists.")
            row = store.color_sets.setdefault(target_id, ColorSetLabels())
            if field_name == FIELD_LABELS:
                _edit_list(row.labels, seed, op, word)
            elif field_name in MEANING_KINDS:
                meaning: MeaningList = getattr(row.meanings, field_name)
                _edit_list(meaning, meaning.draft, op, word)
            else:
                raise EditRefused(f"Unknown list {field_name!r}.")
        elif kind == KIND_EFFECT:
            if target_id not in device_model.effect_types():
                raise EditRefused("That effect is not registered.")
            if field_name != FIELD_LABELS:
                raise EditRefused("An effect has only sung labels.")
            row_e = store.effects.setdefault(target_id, EffectLabels())
            _edit_list(row_e.labels, EFFECT_SEEDS.get(target_id, ()), op, word)
        else:
            raise EditRefused(f"Unknown kind {kind!r}.")
        store.labels_changed_ms = int(time.time() * 1000)
        _save(store)


def _enforce_meaning_word_cap(store: SungLabelStore) -> None:
    """A drafted meaning word on more sets than its cap allows is trimmed back
    to the cap, keeping it on the sets where Claude itself ranked it earliest
    in that set's list (its best fit) and dropping it from the rest. Touches
    only `draft`, never his `added`/`removed`, so this can never undo an edit
    of his -- it just thins out what the next draft would otherwise pile up."""
    best_rank: dict[str, dict[str, int]] = {}
    for card_id, row in store.color_sets.items():
        for kind in MEANING_KINDS:
            for index, word in enumerate(getattr(row.meanings, kind).draft):
                key = colour_words.word_key(word)
                ranks = best_rank.setdefault(key, {})
                if card_id not in ranks or index < ranks[card_id]:
                    ranks[card_id] = index
    for key, ranks in best_rank.items():
        cap = MEANING_WORD_CAP_COLOUR if colour_words.is_colour_word(key) else MEANING_WORD_CAP
        if len(ranks) <= cap:
            continue
        keep = {card_id for card_id, _ in
                sorted(ranks.items(), key=lambda kv: (kv[1], kv[0]))[:cap]}
        for card_id in ranks:
            if card_id in keep:
                continue
            row = store.color_sets[card_id]
            for kind in MEANING_KINDS:
                meaning = getattr(row.meanings, kind)
                if any(colour_words.word_key(w) == key for w in meaning.draft):
                    meaning.draft = [w for w in meaning.draft if colour_words.word_key(w) != key]


def apply_draft(drafts: dict[str, dict[str, list[str]]], model: str) -> None:
    """Claude's meanings for some cards. Writes each card's `draft` lists and
    nothing else, which is why a re-draft cannot touch one of his edits. Then
    re-enforces the word cap over every card's draft, not only the ones just
    drafted, because the cap is a statement about the whole list."""
    with _lock:
        store = load()
        now = int(time.time() * 1000)
        for card_id, meanings in drafts.items():
            row = store.color_sets.setdefault(card_id, ColorSetLabels())
            for kind in MEANING_KINDS:
                getattr(row.meanings, kind).draft = colour_words.dedupe(meanings.get(kind) or [])
            row.drafted_ms = now
            row.draft_model = model
        _enforce_meaning_word_cap(store)
        store.labels_changed_ms = now
        _save(store)
