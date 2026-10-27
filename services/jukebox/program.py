"""
SpotFX — the Jukebox program's RULES: pure functions, no I/O, no clock.

The program is the night's running order: the host's set (a Spotify
playlist, played as Spotify's own context, shuffle off) with jukebox slots
between set songs (data/jukebox-plan/report.md §5). Spotify never sees a
slot. The runner (services/jukebox/night.py) commits the song that fills a
slot into Spotify's queue just before the slot comes up; everything here only
decides WHERE the slots are and WHAT fills them.

THE ONE DEFINITION. `project()` is the program from the item playing now
onward, and the runner's "what comes next?" is `project(...)[0]` — never a
second reading of the rules. The preview the host sees, the dry run
(scripts/jukebox_dry_run.py) and the engine's own commit decision are the
same function, so they cannot disagree.

THE CURSOR (`models.jukebox.Cursor`) moves only through the transitions
below, each fed by what the runner OBSERVED Spotify start:

  on_set_start(idx)   a set song started. The gap that follows it is sized
                      by the rule, plus any slot a missed commit still owes.
  on_jukebox_start()  a jukebox song started: one slot of the gap used.

A GAP is the run of jukebox slots between two set songs:

  auto           after every `every` set songs, `run` slots in a row
                 (every=1, run=1 is "every other").
  jukebox_first  after every set song, as many slots as the line holds
                 (the set only plays when nobody has a song waiting).
  manual         after the set songs he picked, `count` slots each, keyed
                 by the song's URI so they follow it through a reorder.

AN EMPTY SLOT PASSES. A slot that comes up with nobody's song waiting is
simply passed and the set continues, so there is never a gap in the music;
it closes the rest of its gap too (the line is just as empty for the next
slot). A MISSED slot is different: the line had a song and it did not reach
Spotify in time (a failed call, a stalled engine, a commit that landed after
the player had already picked its next track). That slot is OWED and served
in the next gap (`owe=True`), capped at one gap's worth — the jukebox never
loses its turn to a timing fault, and the set's own rhythm is not shifted.

WHEN THE SET RUNS OUT (`run_out`): "again" wraps to the first set song
(Spotify's repeat-context does the same, so the two agree); "jukebox_only"
turns the gap after the last set song into a jukebox-first gap that ends the
program once the line is empty; "end" ends the program with the last set
song.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

from models.jukebox import Cursor, ManualSlot, ProgramConfig, SetItem

# "As many slots as the line holds" — a jukebox-first gap. Never decremented
# and never owed: the line running dry is what closes it.
UNBOUNDED = 1_000_000


@dataclass(frozen=True)
class Fill:
    """A jukebox song that can fill the next slot. The runner hands
    `project()` the line in slot order: the song already committed to
    Spotify's queue first (it plays next whatever else happens), then every
    queued, ready song in line order."""
    entry_id: str
    uri: str
    title: str = ""
    artist: str = ""
    duration_ms: int = 0
    committed: bool = False


@dataclass
class ProgramItem:
    """One upcoming item. `kind`: "set" (a set song), "jukebox" (a slot and
    the song that fills it), or "open" (a slot nobody has filled yet — it
    passes if it is still empty when it comes up)."""
    kind: str
    uri: str = ""
    title: str = ""
    artist: str = ""
    duration_ms: int = 0
    set_index: Optional[int] = None
    entry_id: str = ""
    committed: bool = False
    starts_in_ms: Optional[int] = None

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


# ── the rule ─────────────────────────────────────────────────────────────────

def owed_cap(cfg: ProgramConfig) -> int:
    """At most one gap's worth of slots is ever owed."""
    return cfg.run if cfg.mode == "auto" else 1


def _manual_count(cfg: ProgramConfig, uri: str) -> int:
    for slot in cfg.manual:
        if slot.after_uri == uri:
            return slot.count
    return 0


def rule_gap(cfg: ProgramConfig, set_items: Sequence[SetItem], idx: int,
             since_slot: int) -> tuple[int, int]:
    """The gap the RULE puts after set song `idx`, and the new `since_slot`.
    Owed slots and the run-out policy are applied by `on_set_start`."""
    if cfg.mode == "jukebox_first":
        return UNBOUNDED, 0
    if cfg.mode == "manual":
        return _manual_count(cfg, set_items[idx].uri), 0
    since = since_slot + 1
    if since >= cfg.every:
        return cfg.run, 0
    return 0, since


def is_last(set_items: Sequence[SetItem], idx: int) -> bool:
    return idx == len(set_items) - 1


# ── transitions ──────────────────────────────────────────────────────────────

def on_set_start(cfg: ProgramConfig, set_items: Sequence[SetItem], cur: Cursor,
                 idx: int, owe: bool = False) -> Cursor:
    """Set song `idx` started. `owe` says the gap that just closed had a
    song for its next slot that never played (a MISSED slot, see the module
    docstring); an empty gap closing is not owed."""
    owed = cur.owed
    if owe and 0 < cur.gap_left < UNBOUNDED:
        owed = min(owed + 1, owed_cap(cfg))
    wrapped = cur.started and idx == 0 and cur.set_pos == len(set_items) - 1
    gap, since = rule_gap(cfg, set_items, idx, cur.since_slot)
    if is_last(set_items, idx):
        if cfg.run_out == "end":
            gap, owed = 0, 0
        elif cfg.run_out == "jukebox_only":
            gap = UNBOUNDED
    if gap < UNBOUNDED:
        gap, owed = gap + owed, 0
    else:
        owed = 0
    return Cursor(set_pos=idx, set_uri=set_items[idx].uri, since_slot=since,
                  gap_left=gap, owed=owed, loops=cur.loops + (1 if wrapped else 0),
                  started=True)


def on_jukebox_start(cur: Cursor) -> Cursor:
    """A jukebox song started: one slot of the gap is used. A jukebox song
    nobody planned (his own "Add to queue" of a line song) uses nothing."""
    gap = cur.gap_left
    if 0 < gap < UNBOUNDED:
        gap -= 1
    return cur.model_copy(update={"gap_left": gap})


def close_gap(cur: Cursor) -> Cursor:
    return cur.model_copy(update={"gap_left": 0})


def next_set_index(cfg: ProgramConfig, set_items: Sequence[SetItem],
                   cur: Cursor) -> Optional[int]:
    """The set song after the cursor, or None when the program ends."""
    if not set_items:
        return None
    if not cur.started:
        return 0
    nxt = cur.set_pos + 1
    if nxt < len(set_items):
        return nxt
    return 0 if cfg.run_out == "again" else None


def resolve_set_index(cfg: ProgramConfig, set_items: Sequence[SetItem],
                      cur: Cursor, uri: str) -> Optional[int]:
    """Which set position a started URI is. The expected next one first (a
    playlist may hold a song twice), then the first one ahead of the
    cursor, then anywhere (he jumped back); None = not a set song."""
    expected = next_set_index(cfg, set_items, cur)
    if expected is not None and set_items[expected].uri == uri:
        return expected
    for i in range(max(cur.set_pos + 1, 0), len(set_items)):
        if set_items[i].uri == uri:
            return i
    for i, item in enumerate(set_items):
        if item.uri == uri:
            return i
    return None


def reanchor(set_items: Sequence[SetItem], cur: Cursor) -> Cursor:
    """After the set is re-read (he edited the playlist mid-night): put
    `set_pos` back on the song the cursor was on — the occurrence nearest
    its old position."""
    if not cur.started or not cur.set_uri:
        return cur
    hits = [i for i, s in enumerate(set_items) if s.uri == cur.set_uri]
    if not hits:
        pos = min(cur.set_pos, len(set_items) - 1)
        return cur.model_copy(update={"set_pos": pos})
    best = min(hits, key=lambda i: abs(i - cur.set_pos))
    return cur.model_copy(update={"set_pos": best})


# ── projection ───────────────────────────────────────────────────────────────

def project(cfg: ProgramConfig, set_items: Sequence[SetItem], cur: Cursor,
            fills: Iterable[Fill], count: int = 20) -> list[ProgramItem]:
    """The next `count` program items after the one playing now (from the
    very start when nothing has played). Slots are filled from `fills` in
    order; a gap the line can't fill shows its slots as "open" (none for a
    jukebox-first gap: there the set simply continues)."""
    out: list[ProgramItem] = []
    pending = list(fills)
    c = cur
    guard = 0
    while len(out) < count and guard < 4 * count + 16:
        guard += 1
        if c.gap_left > 0:
            if pending:
                f = pending.pop(0)
                out.append(ProgramItem(kind="jukebox", uri=f.uri, title=f.title,
                                       artist=f.artist, duration_ms=f.duration_ms,
                                       entry_id=f.entry_id, committed=f.committed))
                c = on_jukebox_start(c)
                continue
            if c.gap_left < UNBOUNDED:
                for _ in range(min(c.gap_left, count - len(out))):
                    out.append(ProgramItem(kind="open"))
            c = close_gap(c)
            if len(out) >= count:
                break
        idx = next_set_index(cfg, set_items, c)
        if idx is None:
            break
        s = set_items[idx]
        out.append(ProgramItem(kind="set", uri=s.uri, title=s.title, artist=s.artist,
                               duration_ms=s.duration_ms, set_index=idx))
        c = on_set_start(cfg, set_items, c, idx)
    return out


def with_start_times(items: list[ProgramItem], remaining_ms: int) -> list[ProgramItem]:
    """Stamp each item with when it would start, counting from the end of
    the item playing now (`remaining_ms` from now). An open slot takes no
    time: it passes."""
    t = max(0, int(remaining_ms))
    for item in items:
        item.starts_in_ms = t
        t += max(0, int(item.duration_ms)) if item.kind != "open" else 0
    return items


@dataclass
class Lap:
    set_songs: int = 0
    slots: int = 0
    unbounded: bool = False
    notes: list[str] = field(default_factory=list)


def lap(cfg: ProgramConfig, set_items: Sequence[SetItem]) -> Lap:
    """One pass through the set with an empty line: how many slots the rule
    places (a jukebox-first program has as many as the line holds)."""
    out = Lap(set_songs=len(set_items))
    if cfg.mode == "jukebox_first":
        out.unbounded = True
        return out
    c = Cursor()
    for idx in range(len(set_items)):
        c = on_set_start(cfg, set_items, close_gap(c), idx)
        if c.gap_left >= UNBOUNDED:
            out.unbounded = True
        else:
            out.slots += c.gap_left
    if cfg.mode == "manual":
        uris = {s.uri for s in set_items}
        for slot in cfg.manual:
            if slot.after_uri not in uris:
                out.notes.append(f"a manual slot follows {slot.after_uri}, which is not in the set")
    return out


def as_manual(cfg: ProgramConfig, set_items: Sequence[SetItem]) -> list[ManualSlot]:
    """The slots the current rule places in one pass, written as MANUAL
    slots — what "switch Auto to Manual" copies so he can edit the pattern
    (report §5). A jukebox-first program becomes one slot after every set
    song (its closest fixed pattern). A song in the set twice keeps its
    first run of slots: manual slots follow a song by its URI."""
    out: dict[str, int] = {}
    since = 0
    for idx, item in enumerate(set_items):
        if cfg.mode == "jukebox_first":
            gap = 1
        elif cfg.mode == "manual":
            gap = _manual_count(cfg, item.uri)
        else:
            gap, since = rule_gap(cfg, set_items, idx, since)
        if gap > 0 and item.uri not in out:
            out[item.uri] = min(gap, 3)
    return [ManualSlot(after_uri=uri, count=n) for uri, n in out.items()]
