"""
SpotFX — the Jukebox's GUESTS (data/jukebox-plan/report.md §6, §7 and §9
phases 2-3, PRs 2.1-2.3 and 3.2): tonight's phones, the names they picked,
their votes on the song playing, the songs they add and bump, the free-play
rules (the room's skip, the jail), credits mode (prices, tips, the paid skip
and its pot, play next, the break-out, the Shop), the host's controls over
all of it, and the ONE view the guest page draws.

The guest page itself is a separate process (jukebox_guest/, on :8020): it
serves the page, keeps each phone's cookie, rate-limits, and forwards a short
allowlist of calls here over loopback, naming the phone. This module is what
those calls do; routers/jukebox_guest_router.py is the door, and it opens
only for the guest app's own key. The host's controls are the master's own
routes (routers/jukebox_router.py, LAN-only :8000).

THE SHOW SETTINGS (models.jukebox.ShowConfig, his to set) govern the guests:
how many phones, whether a new phone needs his approval, name changes per
night and the word filter, when requests close, explicit songs, and (its
economy) songs in line per guest and fair order.

PHONES. A phone is a random code (no account, no sign-in) kept in a cookie
and in the phone's own storage, so clearing one keeps the other. A phone
joins tonight's party only with tonight's party token (services/jukebox/
guest_link.py — the `?t=` in the printed link); once it has joined, the code
alone brings it back. A phone from an earlier night keeps its code but must
show tonight's token again. While "new phones need my approval" is on, a new
phone waits for his yes before it can vote or add; a phone he blocks is out
for the night.

NAMES. Every phone gets a fun name ("Sunny Fox") at hello; the welcome
screen's shuffle is free, and after "Let's go" a phone may rename as many
times as the show allows (3). A name is 2-20 letters (any language's),
digits, spaces and ' . - _ — no emoji or symbols; it can't be anyone else's
tonight or the host's, and with the word filter on it can't hold a word on
the short block list. The host can rename any phone and lock its name.

VOTES (free play, the plan's §6). One vote per phone on the song playing —
▲ or ▼, changeable, withdrawable — keyed by the play (the song and the moment
it started), so a song that plays twice is voted on twice. Only while it
plays; never on your own song ("everyone else votes"); never on a song that
isn't part of tonight's program. In credits mode a vote also earns
(`vote_reward`, once per play).

FREE PLAY (report §6, PR 2.3): nothing costs anything, and counts keep it
fair; every number is a show setting (§4's Free play card).
  THE ROOM'S SKIP. The song playing is skipped once it has `free_skip_downs`
  ▼ (3) AND that share of its votes (`free_skip_share`, 67%: two-thirds,
  rounded to a whole percent) — any song, the host's set included — but
  never in its first `skip_grace_s` (20 s, stops mis-taps): a skip that is
  due earlier waits for the grace to end and is checked again then. The
  engine skips (night.skip_by_vote), only if it is still the same play.
  BUMPS. A guest moves their own waiting song up one place, or someone
  else's down one place, `free_bumps_per_hour` (2) times in any hour; a song
  is pushed back at most `bump_down_max_places` (3) places a night — a
  PER-SONG total, not per-mechanism: the song an up-bump steps past gets
  pushed back exactly as a direct down-bump would, and is refused the same
  way once it is already at the cap; nothing passes the song already sent
  to Spotify; a held or jailed song can't move.
  THE JAIL. When the songs a guest added tonight have the jail's net ▼ (the
  economy's `jail_net_downs`, 5, rising with the crowd: 6 at 8 guests, 8 at
  15, 10 at 30 — "guests" being phones seen in the last 15 minutes), the
  guest's waiting songs sit out the next `free_jail_songs` (5) songs: they
  keep their places but are never sent, and the guest can't add or bump
  (they can still vote). When the time-out ends — or the host pardons them
  — their count starts again at 0. The host's songs never go to jail. The
  term is the engine's (JukeboxNight.jail, counted in songs that start); the
  count is this book's (GuestBook.play_by, GuestPhone.jail_base).
  PLAY NEXT is the host's only (his "Play next" on the Guests tab), or off.

ADDING A SONG (report §1.5, in free play). A guest finds a song — his own
library first ("Ready: the lights already know these"), then Spotify — and
adds it, if: requests are open (they close `last_call_min` before the night
ends), explicit songs are allowed by the show (never / always / after a set
time), the song isn't already waiting in line, and the guest has fewer than
`max_waiting` songs waiting. It goes in by FAIR ORDER: it is its adder's
Nth song tonight (played + waiting + 1), and it is placed ahead of the first
waiting song with a higher N — 1st songs before 2nd songs — never ahead of a
song already sent to Spotify. Nothing is accepted that would start after the
night ends: the guest is told so, and nothing is added.

SEARCH never runs on the event loop: his library is a disk scan and Spotify
is a network call, both through `to_thread`, on a gateway of their own (so a
party searching never queues ahead of the engine's commit). Results are
cached by query for SEARCH_CACHE_S; a song's details (art, length, explicit)
for META_CACHE_S.

CREDITS MODE (report §1, PR 3.2; ShowConfig.play_mode == "credits", off by
default). services/jukebox/wallet.py is the wallet (earning, the prices from
the night as it stands, the Shop's words) and services/jukebox/ledger.py the
truth — every grant, earning, tip, spend and refund is a ledger entry, read
back for every number shown; nothing here stores a balance. On top of free
play's book:
  EARNING is checked on the phone's own polls (`_credits_tick`): the welcome
  credits (half at "Let's go", the rest later), the top-ups while the phone
  is here (a phone away more than PRESENT_WINDOW_MS gets none for the time
  away), Adder credits for the ▲ on a guest's song once it has played.
  EVERY SPEND IS PRICED BY THE SERVER AND CHECKED AGAINST THE PRICE THE PAGE
  SHOWED (`_afford`): a price that moved is refused with the new one, never
  charged. Adding (the add price, with its long-song, learn-first and
  explicit extras), bumps (by places, no hourly limit), play next (once
  per song, ≥ `next_min_away_min` away; every song it jumps past is pushed
  back a place — the cap is per song — and it is refused when one of them
  is already at the cap),
  the skip (the rest of its price, or a chip-in toward its POT; a pot filled
  makes the engine skip; a pot whose song ends first is refunded), tips (to
  the guest whose song is playing, never the host or yourself) and the
  break-out from jail. In credits mode the jail lasts until the guest breaks
  out (`jail_fee`) or the host pardons (night.JAIL_UNTIL_FREED).
  REFUNDS are written, never assumed: a paid song the host removed, an
  unfilled pot, and every paid song still waiting when the night ends
  (`_close_night`).
  THE SKIP LOCK (§12, "the host can lock a song from skips") is the
  engine's `no_skip` list, by song, in both modes: the room's vote, a paid
  skip, a chip-in and a pot that fills all refuse a locked song.

THE VIEW is everything one phone's screen shows, built from the engine's
lean read (night.JukeboxRunner.guest_state — no Spotify call) and this book:
what is playing with its votes, the next songs with who added each, "your
songs" with their place and start time, the strip's tone, whether requests
are open, and the house rules. Another phone's id never appears in it — only
names.

Every refusal is a sentence the page shows as it is, with a code.
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
import secrets
import time
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Optional
from zoneinfo import ZoneInfo

from models.jukebox import GuestBook, GuestPhone, LineEntry, ShowConfig
from services.jukebox import store

logger = logging.getLogger(__name__)
HOUSE_TZ = ZoneInfo("America/New_York")
PLAYS_KEPT = 300                 # plays whose votes are kept (the report reads them)
PRESENT_WINDOW_MS = 15 * 60_000  # "guests" in the crowd-scaled rules: phones seen this recently
BUMP_WINDOW_MS = 60 * 60_000     # free play's bumps: so many in any hour
NEXT_SHOWN = 8                   # upcoming songs on the Now and Queue screens
POLL_MS = 3000                   # how often the page asks again while it is open
SEARCH_PAGE = 10                 # Spotify results a page (report §9, PR 2.2)
LIBRARY_HITS = 5                 # his own songs shown first
QUERY_MIN, QUERY_MAX = 2, 60
SEARCH_CACHE_S = 600.0
SEARCH_CACHE_MAX = 300
META_CACHE_S = 3600.0
META_CACHE_MAX = 2000
PHONE_RE = re.compile(r"^[A-Za-z0-9_-]{16,40}$")
NAME_MIN, NAME_MAX = 2, 20
_NAME_PUNCT = set(" '._-")
_RESERVED = {"host", "the host", "dj", "spotfx", "spectra", "serenity", "jukebox", "admin"}

# The words a name may not contain (after folding look-alike digits), with
# the word filter on. Deliberately short: the host renames or blocks anything
# that slips by.
_BLOCKED = ("fuck", "shit", "cunt", "nigg", "fag", "bitch", "whore", "slut", "rape",
            "nazi", "hitler", "dick", "cock", "pussy", "porn", "penis", "vagina",
            "retard", "kike", "spic", "chink", "twat", "wank", "asshole", "bastard",
            "kill", "suicide")
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t",
                       "@": "a", "$": "s", "!": "i"})

ADJECTIVES = ("Sunny", "Lucky", "Cosmic", "Jolly", "Mellow", "Groovy", "Breezy", "Snappy",
              "Velvet", "Golden", "Electric", "Dizzy", "Fuzzy", "Zesty", "Bouncy", "Neon",
              "Lunar", "Sparkly", "Cheery", "Dapper", "Funky", "Glowing", "Happy", "Jazzy",
              "Merry", "Nimble", "Peppy", "Rosy", "Silver", "Swift", "Twirly", "Witty",
              "Brave", "Calm", "Daring", "Gentle", "Lively", "Plucky", "Quirky", "Starry")
ANIMALS = ("Fox", "Otter", "Panda", "Koala", "Falcon", "Dolphin", "Tiger", "Llama",
           "Penguin", "Badger", "Heron", "Lynx", "Moose", "Gecko", "Bison", "Raven",
           "Walrus", "Hedgehog", "Owl", "Seal", "Puffin", "Beaver", "Zebra", "Parrot",
           "Turtle", "Rabbit", "Wolf", "Bear", "Crane", "Squirrel", "Lemur", "Toucan",
           "Hare", "Duck", "Goat", "Mole", "Newt", "Orca", "Swan", "Yak")

PRIVACY = ("This page keeps a random code for your phone and the name you pick, for "
           "tonight's party only. No sign-in, no account, and nothing about you leaves "
           "the house.")
HOW_IT_WORKS_CREDITS: tuple[dict, ...] = (
    {"icon": "vote", "title": "Vote, earn", "text": "Tap ▲ or ▼ on the song that's playing: +1 credit each song."},
    {"icon": "note", "title": "Add a song", "text": "Tap ＋, find a song, add it with credits — this page tells you when it plays."},
    {"icon": "shop", "title": "Tip, bump, skip", "text": "Tip the guest whose song you love, move songs, or chip in to skip."},
)
HOW_IT_WORKS: tuple[dict, ...] = (
    {"icon": "vote", "title": "Vote", "text": "Tap ▲ or ▼ on the song that's playing."},
    {"icon": "note", "title": "Add a song", "text": "Tap ＋, find a song, and add it — this page tells you when it plays."},
    {"icon": "queue", "title": "See what's next", "text": "The Queue shows every song coming up."},
)

SENTENCES: dict[str, str] = {
    "idle": "The Jukebox isn't playing right now. Come back when the music starts.",
    "needs_link": "Open tonight's party link (the QR code at the party) to join.",
    "party_full": "This party has as many phones as it can take tonight.",
    "blocked": "The host has taken this phone out of tonight's party.",
    "not_approved": "The host hasn't let this phone in yet — hang on.",
    "not_joined": "Tap Let's go first.",
    "name_bad": "A name is 2-20 letters, numbers or spaces.",
    "name_taken": "Someone already has that name tonight.",
    "name_blocked": "Pick a different name.",
    "name_locked": "The host has set your name for tonight.",
    "renames_used": "That's all the name changes for tonight.",
    "bad_vote": "That isn't a vote.",
    "nothing_playing": "Nothing is playing yet.",
    "own_song": "It's your song — everyone else votes.",
    "not_votable": "This song isn't part of tonight's program, so it can't be voted on.",
    "skipping": "This song is being skipped.",
    "bad_query": "Type at least two letters.",
    "search_failed": "Spotify didn't answer the search. Try again in a moment.",
    "track_unknown": "Spotify doesn't know that song.",
    "requests_closed": "Requests are closed for tonight — last call was at {at}.",
    "explicit_no": "Explicit songs aren't allowed tonight.",
    "explicit_after": "Explicit songs are allowed after {at}.",
    "in_line": "That song is already in line.",
    "too_many": "You have {n} song{s} in line — wait for one to play.",
    "too_late": "That would start after the night ends, so it can't go in.",
    "not_running": "The Jukebox isn't playing right now.",
    "no_entry": "That song isn't in the line.",
    "no_phone": "That phone isn't at tonight's party.",
    "vote_skipped": "The room voted to skip it.",
    "paid_skipped": "This song is being skipped.",
    "jailed": "You're in a time-out: your songs sit out {n} more song{s}. You can still vote.",
    "bad_bump": "That isn't a bump.",
    "bumps_off": "Bumps are off tonight.",
    "bumps_used": "You've used your {n} bump{s} this hour — the next one is free at {at}.",
    "bump_own_up": "You can move your own songs up.",
    "bump_others_down": "You can move other people's songs down, not your own.",
    "committed_fixed": "That song is already sent to Spotify — it plays next whatever happens.",
    "already_played": "That song has already played.",
    "at_front": "It's already at the front of the line.",
    "at_back": "It's already at the back of the line.",
    "pushed_max": "That song has been moved back as far as it can go tonight.",
    "on_hold": "That song is on hold, so it can't move.",
    "not_jailed": "That phone isn't in a time-out.",
    # credits mode (PR 3.2)
    "credits_off": "Credits are off tonight — it's free play.",
    "skip_locked": "The host has kept this song from skips.",
    "own_skip": "It's your song — you can't skip it.",
    "skip_grace": "No skips in a song's first {s} seconds.",
    "host_tip": "The host's songs take no tips.",
    "own_tip": "You can't tip your own song.",
    "tips_off": "Tips are off tonight.",
    "tip_cap": "That's the most you can tip on this song ({cap}).",
    "price_changed": "The price is now {price} — tap again to pay it.",
    "not_enough": "That needs {need} credits — you have {have}.",
    "nexted": "That song has had its play next.",
    "next_too_soon": "Play next is for a song at least {m} minutes away.",
    "not_jailed_self": "You're not in jail.",
    "skip_none": "There's nothing to skip right now.",
    "pot_full": "The pot is already full — the song is being skipped.",
    "bad_amount": "That isn't an amount of credits.",
    "at_front_next": "It's already the next song to go in.",
    "next_pushed_max": "A song it would jump past has been moved back as far as it can go tonight.",
    "jailed_credits": "You're in jail: your songs wait until you break out ({fee} credits). You can still vote.",
    "chip_off": "Chipping in is off tonight.",
    "next_own": "Play next is for your own songs.",
}


def sentence(code: str, **fmt: Any) -> str:
    text = SENTENCES.get(code, code)
    try:
        return text.format(**fmt) if fmt else text
    except (KeyError, IndexError):
        return text


def refusal(code: str, http: int, **fmt: Any) -> tuple[int, dict]:
    return http, {"status": "refused", "reason": code, "detail": sentence(code, **fmt)}


SHARE_WORDS = {50: "half", 67: "two-thirds", 75: "three-quarters"}


def share_words(pct: int) -> str:
    return SHARE_WORDS.get(int(pct), f"{int(pct)}%")


def house_rules(show: ShowConfig) -> list[str]:
    explicit = {"no": "No explicit songs tonight.",
                "extra": "Explicit songs are allowed tonight.",
                "after": f"Explicit songs only after {show.explicit_after}."}[show.explicit]
    if show.play_mode == "credits":
        cfg = show.economy
        rises = " (more in a big crowd)" if cfg.jail_scale else ""
        return ["Songs for everyone: pick music the room will enjoy.",
                "One vote per song. Vote on what's playing — not on people.",
                "Skips cost credits: the price falls with every ▼, and you can chip in together.",
                explicit,
                f"If your songs get {cfg.jail_net_downs} more ▼ than ▲{rises}, they wait until "
                f"you break out ({cfg.jail_fee} credits).",
                "Credits are free and only for tonight: they can't be bought, sold, traded or "
                "cashed out.",
                "The host's word is final: they can remove any song or name."]
    rules = ["Songs for everyone: pick music the room will enjoy.",
             "One vote per song. Vote on what's playing — not on people.",
             f"{show.free_skip_downs} ▼ and {share_words(show.free_skip_share)} of the votes "
             "skip a song.",
             explicit]
    if show.free_jail_songs:
        rises = " (more in a big crowd)" if show.economy.jail_scale else ""
        n = show.free_jail_songs
        rules.append(f"If your songs get {show.economy.jail_net_downs} more ▼ than ▲{rises}, "
                     f"they sit out {n} song{'' if n == 1 else 's'}.")
    rules.append("The host's word is final: they can remove any song or name.")
    return rules


# ── pure: ids, names ─────────────────────────────────────────────────────────

def new_phone_id() -> str:
    return secrets.token_urlsafe(16)


def valid_phone_id(given: Any) -> bool:
    return isinstance(given, str) and bool(PHONE_RE.match(given))


def _fold(name: str) -> str:
    return re.sub(r"[^a-z]", "", name.lower().translate(_LEET))


def clean_name(raw: Any, word_filter: bool = True) -> tuple[Optional[str], str]:
    """(the name as it will show, "") or (None, the refusal code)."""
    if not isinstance(raw, str):
        return None, "name_bad"
    name = unicodedata.normalize("NFKC", raw)
    name = re.sub(r"\s+", " ", name).strip()
    if not NAME_MIN <= len(name) <= NAME_MAX or not any(c.isalnum() for c in name) or not all(
            c in _NAME_PUNCT or unicodedata.category(c)[0] in "LN" for c in name):
        return None, "name_bad"
    if name.lower() in _RESERVED or (word_filter and any(w in _fold(name) for w in _BLOCKED)):
        return None, "name_blocked"
    return name, ""


def fun_name(rng: random.Random, taken: set[str]) -> str:
    """A fun name nobody has tonight ("Sunny Fox"); a number on the end only
    when 40 tries all collide."""
    for _ in range(40):
        name = f"{rng.choice(ADJECTIVES)} {rng.choice(ANIMALS)}"
        if name.lower() not in taken:
            return name
    base = f"{rng.choice(ADJECTIVES)} {rng.choice(ANIMALS)}"
    n = 2
    while f"{base} {n}".lower() in taken:
        n += 1
    return f"{base} {n}"


def play_key(now: Any) -> str:
    """The play a vote belongs to: the song and when it started."""
    return f"{getattr(now, 'uri', '')}@{getattr(now, 'started_ms', None) or 0}"


def open_url(uri: str) -> str:
    """Spotify's own page for a song (the attribution rule's link back)."""
    return ("https://open.spotify.com/track/" + uri.split(":", 2)[2]
            if uri.startswith("spotify:track:") else "")


# ── pure: the night's clock ──────────────────────────────────────────────────

def _at(started_ms: int, hhmm: str) -> datetime:
    """The first time `hhmm` (house time) comes round after the night started."""
    start = datetime.fromtimestamp(started_ms / 1000, HOUSE_TZ)
    h, m = (int(x) for x in hhmm.split(":"))
    t = start.replace(hour=h, minute=m, second=0, microsecond=0)
    return t if t > start else t + timedelta(days=1)


def _clock(dt: datetime) -> str:
    return f"{dt.hour % 12 or 12}:{dt.minute:02d}"


def requests_state(show: ShowConfig, started_ms: int, now_ms: int) -> dict:
    """When tonight's requests close (last call) and the night ends."""
    ends = _at(started_ms, show.night_ends)
    closes = ends - timedelta(minutes=show.last_call_min)
    closes_ms, ends_ms = int(closes.timestamp() * 1000), int(ends.timestamp() * 1000)
    is_open = now_ms < closes_ms
    return {"open": is_open, "closes_at_ms": closes_ms, "ends_at_ms": ends_ms,
            "closes_at": _clock(closes), "ends_at": _clock(ends),
            "detail": "" if is_open else sentence("requests_closed", at=_clock(closes))}


def explicit_rule(show: ShowConfig, started_ms: int, now_ms: int) -> tuple[bool, str]:
    """(an explicit song may go in now, why not)."""
    if show.explicit == "extra":
        return True, ""
    if show.explicit == "after":
        at = _at(started_ms, show.explicit_after)
        if now_ms >= at.timestamp() * 1000:
            return True, ""
        return False, sentence("explicit_after", at=_clock(at))
    return False, sentence("explicit_no")


# ── pure: the view ───────────────────────────────────────────────────────────

def _names(book: GuestBook) -> dict[str, str]:
    return {pid: p.name for pid, p in book.phones.items()}


def _by(added_by: Optional[str], names: dict[str, str]) -> dict:
    if added_by is None:
        return {"kind": "set", "name": "Host's set"}
    if added_by == "host":
        return {"kind": "host", "name": "the host"}
    return {"kind": "guest", "name": names.get(added_by, "a guest")}


def _song(kind: str, uri: str, title: str, artist: str, image: str, thumb: str,
          by: dict, mine: bool) -> dict:
    return {"kind": kind, "uri": uri, "title": title, "artist": artist, "image": image,
            "thumb": thumb, "open_url": open_url(uri), "by": by, "mine": mine}


def tally(book: GuestBook, key: str) -> dict:
    votes = book.votes.get(key) or {}
    return {"up": sum(1 for v in votes.values() if v > 0),
            "down": sum(1 for v in votes.values() if v < 0)}


def waiting(line: list, phone_id: str) -> list:
    """A phone's songs still to play (in line or sent to Spotify)."""
    return [e for e in line if e.added_by == phone_id and e.state in ("queued", "committed")]


# ── pure: free play's counts ─────────────────────────────────────────────────

def share_met(downs: int, ups: int, pct: int) -> bool:
    """▼ are at least `pct` percent of the votes (rounded to a whole percent,
    so two of three is two-thirds)."""
    total = downs + ups
    return total > 0 and round(100 * downs / total) >= pct


def skip_needed(downs: int, ups: int, show: ShowConfig) -> int:
    """How many more ▼ skip the song (0: the room has voted it off)."""
    for more in range(0, 200):
        d = downs + more
        if d >= show.free_skip_downs and share_met(d, ups, show.free_skip_share):
            return more
    return 200


def jailed_now(gs: dict, phone_id: str) -> int:
    """Songs left in this guest's time-out (0: not in one)."""
    until = (gs.get("jail") or {}).get(phone_id)
    plays = int(gs.get("plays") or 0)
    return max(0, until - plays) if until is not None else 0


def net_downs(book: GuestBook, phone_id: str) -> int:
    """▼ minus ▲ on every song this guest added tonight (before the reset)."""
    total = 0
    for key, by in book.play_by.items():
        if by == phone_id:
            votes = book.votes.get(key) or {}
            total += sum(1 for v in votes.values() if v < 0) - sum(1 for v in votes.values() if v > 0)
    return total


def jail_count(book: GuestBook, phone_id: str, gs: dict) -> int:
    """The count the jail reads: net ▼ since the last time-out ended (0 the
    moment one ends, before the book has noticed)."""
    p = book.phones[phone_id]
    if p.jail_open and not jailed_now(gs, phone_id):
        return 0
    return net_downs(book, phone_id) - p.jail_base


def present(seen: dict[str, int], now_ms: int) -> int:
    """Phones seen in the last 15 minutes (at least 1)."""
    return max(1, sum(1 for t in seen.values() if now_ms - t <= PRESENT_WINDOW_MS))


def bumps_state(p: GuestPhone, show: ShowConfig, now_ms: int) -> dict:
    """A phone's bumps this hour: how many are left and when the next frees up."""
    per = show.free_bumps_per_hour
    recent = sorted(t for t in p.bumps_ms if now_ms - t < BUMP_WINDOW_MS)
    left = max(0, per - len(recent))
    free_at = None
    if per and not left and recent:
        free_at = _clock(datetime.fromtimestamp((recent[-per] + BUMP_WINDOW_MS) / 1000, HOUSE_TZ))
    return {"per_hour": per, "left": left, "next_at": free_at}


def build_view(book: GuestBook, phone_id: str, gs: dict, now_ms: int,
               show: Optional[ShowConfig] = None, crowd: int = 1,
               credits: Optional[dict] = None) -> dict:
    """Everything one phone's screen shows. Pure: the book, the phone, the
    engine's lean read (night.JukeboxRunner.guest_state), the show settings,
    the clock and — in credits mode — the few numbers read from the night's
    ledger (`credits`: balance, whether this play's vote is paid, the tips
    this phone put on it, the skip pot, the wait for a song at the back)."""
    show = show or ShowConfig()
    me = book.phones[phone_id]
    names = _names(book)
    line = gs.get("line") or []
    reqs = requests_state(show, int(gs.get("started_ms") or now_ms), now_ms)
    mine_waiting = len(waiting(line, phone_id))
    from services.jukebox import economy, wallet
    cfg = show.economy
    cr = credits if show.play_mode == "credits" and credits is not None else None
    balance = int(cr["balance"]) if cr else 0
    left = jailed_now(gs, phone_id)
    out: dict[str, Any] = {
        "state": "running", "server_ms": now_ms, "poll_ms": POLL_MS,
        "me": {"name": me.name, "joined": me.joined, "approved": me.approved,
               "name_locked": me.name_locked,
               "renames_left": max(0, show.renames_per_night - me.renames),
               "jail": {"in": bool(left), "songs_left": left if not cr else 0,
                        "kind": "breakout" if cr else "timeout",
                        "fee": cfg.jail_fee,
                        "can_break_out": bool(cr) and bool(left) and balance >= cfg.jail_fee,
                        "count": jail_count(book, phone_id, gs),
                        "at": economy.jail_threshold(crowd, cfg),
                        "on": bool(cr) or bool(show.free_jail_songs)},
               "bumps": bumps_state(me, show, now_ms)},
        "features": {"add": True, "board": False, "credits": bool(cr), "shop": bool(cr)},
        "requests": {**reqs, "max_waiting": cfg.max_waiting,
                     "waiting": mine_waiting},
        "house_rules": house_rules(show), "privacy": PRIVACY,
        "how": list(HOW_IT_WORKS_CREDITS if cr else HOW_IT_WORKS),
    }
    if cr:
        out["me"]["credits"] = balance
        out["start_credits"] = cfg.start_credits
    entries = {e.id: e for e in line}
    set_items = gs.get("set_items") or []
    now = gs.get("now")
    np: Optional[dict] = None
    kind = getattr(now, "kind", "") if now is not None else ""
    skip_reason = getattr(now, "skip_reason", "") if now is not None else ""
    voted_off = kind == "skipping" and skip_reason in ("votes", "paid")
    if kind in ("set", "jukebox") or voted_off:
        entry = entries.get(now.entry_id) if now.entry_id else None
        idx = now.set_index if entry is None else None
        item = set_items[idx] if idx is not None and 0 <= idx < len(set_items) else None
        src = entry or item
        added_by = entry.added_by if entry is not None else None
        mine = added_by == phone_id
        key = play_key(now)
        my_vote = (book.votes.get(key) or {}).get(phone_id, 0)
        np = _song("set" if entry is None else "jukebox", now.uri,
                   getattr(src, "title", "") or now.title, getattr(src, "artist", ""),
                   getattr(src, "image", ""), getattr(src, "thumb", ""),
                   _by(added_by, names), mine)
        why = (sentence("paid_skipped" if skip_reason == "paid" else "vote_skipped") if voted_off else
               sentence("own_song") if mine else
               sentence("not_approved") if not me.approved else "")
        votes = tally(book, key)
        played_s = (now_ms - now.started_ms) / 1000 if now.started_ms else 0.0
        locked = now.uri in (gs.get("no_skip") or [])
        grace_left = max(0, int((cfg.skip_grace_s - played_s) * 1000))
        np.update({"votes": votes, "my_vote": my_vote,
                   "can_vote": not voted_off and not mine and me.approved and bool(now.started_ms),
                   "why_not": why})
        if not cr:
            np["skip"] = {"mode": "vote", "downs_at": show.free_skip_downs,
                          "share": show.free_skip_share,
                          "rule": f"{show.free_skip_downs} ▼ and "
                                  f"{share_words(show.free_skip_share)} of the votes skip a song",
                          "needed": 0 if voted_off else skip_needed(votes["down"], votes["up"], show),
                          "skipping": voted_off, "locked": locked, "grace_left_ms": grace_left}
        else:
            np["earn"] = 0 if cr.get("vote_paid") or mine else cfg.vote_reward
            price = wallet.skip_price(cr.get("back_wait_ms"), votes["up"], votes["down"], crowd, cfg)
            have, mine_pot = cr.get("pot", 0), cr.get("pot_mine", 0)
            why_skip = "" if not voted_off else why
            if voted_off:
                pass
            elif locked:
                why_skip = sentence("skip_locked")
            elif mine:
                why_skip = sentence("own_skip")
            elif not me.approved:
                why_skip = sentence("not_approved")
            elif grace_left:
                why_skip = sentence("skip_grace", s=int(cfg.skip_grace_s))
            np["skip"] = {"mode": "paid", "price": price, "pot": have, "pot_mine": mine_pot,
                          "need": max(0, price - have), "chip_in": cfg.chip_in,
                          "per_down_pct": cfg.skip_down_pct,
                          "skipping": voted_off, "locked": locked, "grace_left_ms": grace_left,
                          "can": not why_skip and balance >= max(1, price - have),
                          "can_chip": not why_skip and cfg.chip_in and balance >= 1,
                          "why": why_skip}
            tip: dict[str, Any] = {"can": False, "why": "", "to": "", "unit": cfg.tip_unit,
                                   "left": 0}
            if entry is None or added_by == "host":
                tip["why"] = sentence("host_tip")
            elif mine:
                tip["why"] = sentence("own_tip")
            elif not cfg.tips:
                tip["why"] = sentence("tips_off")
            else:
                left_units = economy.tip_units_allowed(int(cr.get("tipped", 0)), cfg)
                tip.update({"to": names.get(added_by, "a guest"), "left": left_units,
                            "can": me.approved and left_units > 0 and balance >= cfg.tip_unit,
                            "why": ("" if left_units > 0 else
                                    sentence("tip_cap", cap=cfg.tip_max_per_song))})
            np["tip"] = tip
            if mine:
                np["coming_in"] = {"ups": votes["up"] * cfg.adder_up_reward,
                                   "tips": int(cr.get("tips_in", 0))}
    elif kind in ("skipping", "foreign"):
        np = _song("other", now.uri, now.title, "", "", "", {"kind": "other", "name": ""}, False)
        np.update({"votes": {"up": 0, "down": 0}, "my_vote": 0, "can_vote": False,
                   "why_not": sentence("skipping" if kind == "skipping" else "not_votable")})
    if np is not None:
        duration = int(gs.get("duration_ms") or 0)
        remaining = int(gs.get("remaining_ms") or 0)
        np.update({"duration_ms": duration,
                   "progress_ms": max(0, duration - remaining) if duration else 0,
                   "is_playing": bool(gs.get("is_playing"))})
    out["now"] = np

    # bumps: the waiting songs that can be sent, in line order
    movable = [e.id for e in line if e.state == "queued" and not e.held
               and not jailed_now(gs, e.added_by)]
    front_eta: Optional[int] = None
    max_back = show.economy.bump_down_max_places
    upcoming: list[dict] = []
    for it in gs.get("next") or []:
        if it.kind not in ("set", "jukebox"):
            continue                                   # an open slot passes; guests don't see it
        entry = entries.get(it.entry_id) if it.kind == "jukebox" else None
        item = (set_items[it.set_index] if it.kind == "set" and it.set_index is not None
                and 0 <= it.set_index < len(set_items) else None)
        src = entry or item
        added_by = entry.added_by if entry is not None else None
        song = _song(it.kind, it.uri, it.title, it.artist, getattr(src, "image", ""),
                     getattr(src, "thumb", ""), _by(added_by, names), added_by == phone_id)
        song.update({"committed": bool(it.committed), "starts_in_ms": it.starts_in_ms,
                     "duration_ms": it.duration_ms, "place": len(upcoming) + 1,
                     "known": bool(getattr(entry, "known", False))})
        if entry is not None and front_eta is None and entry.id in movable:
            front_eta = it.starts_in_ms
        if entry is not None:
            song["entry_id"] = it.entry_id
            song["bump"] = None
            if not it.committed and entry.id in movable:
                pos = movable.index(entry.id)
                if added_by == phone_id:
                    # An up-bump steps past the song ahead of it, pushing
                    # THAT song back one place — refused once it is already
                    # at the cap, same as a down-bump on one's own song.
                    ahead = entries.get(movable[pos - 1]) if pos > 0 else None
                    ok = pos > 0 and (ahead is None or ahead.pushed_back < max_back)
                    song["bump"] = "up" if ok else None
                    song["bump_why"] = ("" if ok else sentence("at_front") if pos == 0
                                        else sentence("pushed_max"))
                else:
                    ok = pos < len(movable) - 1 and entry.pushed_back < max_back
                    song["bump"] = "down" if ok else None
                    song["bump_why"] = ("" if ok else sentence("at_back") if pos >= len(movable) - 1
                                        else sentence("pushed_max"))
                if cr and song["bump"]:
                    up_price, down_price = wallet.bump_prices(movable, entry.id, cfg)
                    song["bump_price"] = up_price if song["bump"] == "up" else down_price
                if cr and added_by == phone_id:
                    q = wallet.next_quote(it.starts_in_ms, front_eta, entry.nexted, cfg)
                    passed = [entries.get(x) for x in movable[:pos]]
                    if q["allowed"] and any(p is not None and p.pushed_back >= max_back
                                            for p in passed):
                        q.update(allowed=False, why=sentence("next_pushed_max"))
                    song["next"] = q
        upcoming.append(song)
    out["next"] = upcoming[:NEXT_SHOWN]

    places = {s.get("entry_id"): s for s in upcoming if s.get("entry_id")}
    mine_list: list[dict] = []
    for e in line:
        if e.added_by != phone_id or e.state not in ("queued", "committed", "playing"):
            continue
        at = places.get(e.id)
        song = _song("jukebox", e.uri, e.title, e.artist, e.image, e.thumb,
                     _by(e.added_by, names), True)
        song.update({"entry_id": e.id, "state": "playing" if e.state == "playing" else
                     "next" if at is not None and at["place"] == 1 else "waiting",
                     "committed": e.state == "committed", "held": e.held,
                     "jailed": bool(left) and e.state == "queued",
                     "known": e.known,
                     "place": at["place"] if at else None,
                     "starts_in_ms": at["starts_in_ms"] if at else None})
        if cr:
            song["paid"] = e.paid
            if at is not None:
                for k in ("bump", "bump_why", "bump_price", "next"):
                    if k in at:
                        song[k] = at[k]
        mine_list.append(song)
    mine_list.sort(key=lambda s: (s["state"] != "playing",
                                  s["place"] if s["place"] is not None else 10_000))
    out["mine"] = mine_list
    lead = mine_list[0] if mine_list else None
    out["strip"] = {"tone": "jail" if left and not (lead and lead["state"] == "playing") else
                    ("playing" if lead["state"] == "playing" else
                     "next" if lead["state"] == "next" else "queued") if lead else "none",
                    "jail_left": left if not cr else 0,
                    "jail_kind": "breakout" if cr else "timeout",
                    "jail_fee": cfg.jail_fee,
                    "title": lead["title"] if lead else "",
                    "place": lead["place"] if lead else None,
                    "starts_in_ms": lead["starts_in_ms"] if lead else None,
                    "held": bool(lead and lead["held"]),
                    "count": len(mine_list)}
    return out


def idle_view(now_ms: int, show: Optional[ShowConfig] = None) -> dict:
    return {"state": "idle", "server_ms": now_ms, "poll_ms": POLL_MS * 5,
            "detail": sentence("idle"), "house_rules": house_rules(show or ShowConfig()),
            "privacy": PRIVACY}


EXPLICIT_EXTRA = 2            # credits mode, explicit "allowed": +2 credits (report §4)


def add_cost(duration_ms: int, known: bool, explicit: bool, wait_ms: Optional[int],
             show: ShowConfig) -> int:
    """What adding a song costs in credits mode (§1 rule 5): by when it
    would play, its length, whether the lights know it; +2 for an explicit
    song where the show allows them at a price."""
    from services.jukebox import wallet
    extra = EXPLICIT_EXTRA if explicit and show.explicit == "extra" else 0
    return wallet.add_price(wait_ms, duration_ms, known, show.economy) + extra


def result_view(meta: dict, *, known: bool, in_line: bool, explicit_ok: bool,
                explicit_why: str, long_over_min: float, library: bool,
                price: Optional[int] = None, balance: Optional[int] = None) -> dict:
    """One search result as the Add screen draws it: badges and whether the
    Add button works (and if not, why). In credits mode, its price and
    whether this phone can pay it."""
    duration = int(meta.get("duration_ms") or 0)
    why = ("in_line" if in_line else
           "explicit" if meta.get("explicit") and not explicit_ok else "")
    out = {"uri": meta["uri"], "title": meta.get("title") or "", "artist": meta.get("artist") or "",
           "image": meta.get("image") or "", "thumb": meta.get("thumb") or "",
           "duration_ms": duration, "explicit": bool(meta.get("explicit")),
           "open_url": open_url(meta["uri"]), "known": known, "library": library,
           "long": duration > long_over_min * 60_000, "in_line": in_line,
           "can_add": not why,
           "why_not": (sentence("in_line") if why == "in_line" else
                       explicit_why if why == "explicit" else "")}
    if price is not None:
        out["price"] = price
        out["afford"] = balance is None or balance >= price
    return out


# ── the book, with its store ────────────────────────────────────────────────

def _default_state() -> dict:
    from services.jukebox import night
    return night.runner.guest_state(count=NEXT_SHOWN * 3)


def _default_token_ok(token: Any) -> bool:
    from services.jukebox import guest_link
    return guest_link.token_matches(token, store.load_guest_link()[1])


async def _default_to_thread(fn: Callable, *args: Any) -> Any:
    return await asyncio.to_thread(fn, *args)


def _default_runner() -> Any:
    from services.jukebox import night
    return night.runner


def _default_gateway() -> Any:
    from services.jukebox import gateway
    return gateway.search_gateway()


def _default_library_search(query: str, limit: int) -> list:
    from services.jukebox import library
    return library.search(query, limit)


def _default_known(uris: list[str]) -> dict[str, bool]:
    from services.jukebox import library
    return {u: library.known(u) for u in uris}


@dataclass
class GuestDeps:
    state: Callable[[], dict] = _default_state
    token_ok: Callable[[Any], bool] = _default_token_ok
    show: Callable[[], ShowConfig] = lambda: store.load_show()
    now_ms: Callable[[], int] = lambda: int(time.time() * 1000)
    to_thread: Callable[..., Awaitable[Any]] = _default_to_thread
    rng: random.Random = field(default_factory=random.Random)
    runner: Callable[[], Any] = _default_runner
    # blocking — always through to_thread
    gateway: Callable[[], Any] = _default_gateway
    library_search: Callable[[str, int], list] = _default_library_search
    known: Callable[[list[str]], dict[str, bool]] = _default_known
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep


class Guests:
    """Tonight's book of phones and votes. Held in memory, written through
    (off the event loop) on every change; every method answers
    (http status, body)."""

    def __init__(self, deps: Optional[GuestDeps] = None) -> None:
        self.deps = deps or GuestDeps()
        self._book: Optional[GuestBook] = None
        self._lock: Optional[asyncio.Lock] = None
        self._searches: dict[tuple[str, int], tuple[float, list[dict], list[str], bool]] = {}
        self._meta: dict[str, tuple[float, dict]] = {}
        # when each phone last asked anything (memory only: the crowd size
        # the jail's bar rises with — phones poll every few seconds, so a
        # restart has it back within moments)
        self._seen: dict[str, int] = {}
        self._skip_armed: set[str] = set()
        self._tasks: set[asyncio.Task] = set()
        # credits mode (PR 3.2): the night's wallet (its ledger), and a short
        # cache of the back-of-line wait the skip price reads
        self._wallet: Optional[Any] = None
        self._wallet_closed: set[str] = set()
        self._polled: dict[str, int] = {}       # a phone's last poll: "here" for top-ups
        self._back_wait: tuple[tuple, Optional[int]] = ((), None)

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _book_for(self, night_id: str) -> GuestBook:
        if self._book is None:
            self._book = store.load_guests()
        if self._book.night_id != night_id:
            self._book = GuestBook(night_id=night_id)
            self._seen.clear()
            self._skip_armed.clear()
            self._polled.clear()
        return self._book

    def _crowd(self) -> int:
        return present(self._seen, self.deps.now_ms())

    async def _save(self) -> None:
        await self.deps.to_thread(store.save_guests, self._book.model_dump(mode="json"))

    def _running(self) -> Optional[dict]:
        gs = self.deps.state()
        return gs if gs.get("running") else None

    def _taken(self, book: GuestBook, but: str = "") -> set[str]:
        return {p.name.lower() for pid, p in book.phones.items() if pid != but}

    def _gate(self, phone: Any) -> tuple[Optional[tuple[int, dict]], Optional[dict],
                                         Optional[GuestBook]]:
        gs = self._running()
        if gs is None:
            return (200, idle_view(self.deps.now_ms(), self.deps.show())), None, None
        book = self._book_for(gs["night_id"])
        if not valid_phone_id(phone) or phone not in book.phones:
            return refusal("needs_link", 403), None, None
        if book.phones[phone].blocked:
            return refusal("blocked", 403), None, None
        self._seen[phone] = self.deps.now_ms()
        return None, gs, book

    def _view(self, book: GuestBook, pid: str, gs: dict) -> dict:
        show = self.deps.show()
        credits = self._credit_info(book, pid, gs, show) if show.play_mode == "credits" else None
        return build_view(book, pid, gs, self.deps.now_ms(), show, self._crowd(), credits)

    # ── credits mode: the wallet, earning, settling (PR 3.2) ───────────────

    def _wallet_for(self, night_id: str, show: ShowConfig) -> Any:
        from services.jukebox import wallet
        if self._wallet is None or self._wallet.night_id != night_id:
            self._wallet = wallet.Wallet(night_id, show.economy)
        self._wallet.led.cfg = show.economy
        return self._wallet

    def _back_wait_ms(self, gs: dict) -> Optional[int]:
        from services.jukebox import wallet
        key = (gs.get("night_id"), gs.get("plays"), len(gs.get("line") or []),
               self.deps.now_ms() // 5000)
        if self._back_wait[0] != key:
            self._back_wait = (key, wallet.back_wait_quote(self.deps.runner()))
        return self._back_wait[1]

    def _credit_info(self, book: GuestBook, pid: str, gs: dict, show: ShowConfig) -> dict:
        w = self._wallet_for(gs["night_id"], show)
        now = gs.get("now")
        key = play_key(now) if getattr(now, "kind", "") in ("set", "jukebox", "skipping") else ""
        have, mine = w.pot(key) if key else (0, {})
        info = {"balance": w.balance(pid), "back_wait_ms": self._back_wait_ms(gs),
                "vote_paid": bool(key) and w.led.voted_paid(pid, key),
                "tipped": w.led.tipped_on(pid, key) if key else 0,
                "pot": have, "pot_mine": mine.get(pid, 0)}
        entry = next((e for e in gs.get("line") or [] if e.id == getattr(now, "entry_id", "")), None)
        if key and entry is not None and entry.added_by == pid:
            info["tips_in"] = sum(e.delta for e in w.led.history(pid)
                                  if e.ref == key and e.kind in ("tip_in", "tip_bonus"))
        return info

    async def _ledger(self, fn: Callable, *args: Any) -> Any:
        """One ledger write, off the loop (it fsyncs)."""
        return await self.deps.to_thread(fn, *args)

    async def _credits_tick(self, book: GuestBook, pid: str, gs: dict, show: ShowConfig) -> None:
        """The grants due to this phone (its welcome credits, its top-ups)
        and the night's settling (Adder credits for songs that have played,
        skip pots that weren't filled, songs the host removed). Checked on
        the phone's own polls; written under the lock only when something is
        due, so a poll with nothing to do never waits."""
        if show.play_mode != "credits":
            return
        w = self._wallet_for(gs["night_id"], show)
        me = book.phones.get(pid)
        if me is None or not me.joined:
            return
        now_ms = self.deps.now_ms()
        prev = self._polled.get(pid)
        self._polled[pid] = now_ms
        away = prev is not None and now_ms - prev > PRESENT_WINDOW_MS
        due, tick = w.due_grants(pid, me.joined_ms, book.credit_tick.get(pid), now_ms, show.economy)
        if not due and not away and not self._pending_settle(w, book, gs):
            return
        async with self._get_lock():
            if away:                       # here again: no top-ups for the time away
                book.credit_tick[pid] = now_ms
            due, tick = w.due_grants(pid, me.joined_ms, book.credit_tick.get(pid), now_ms,
                                     show.economy)
            for kind, amount in due:
                w.noted([await self._ledger(w.led.grant, pid, kind, amount)])
            changed = away or bool(due)
            if tick is not None and book.credit_tick.get(pid) != tick:
                book.credit_tick[pid] = tick
                changed = True
            changed |= await self._settle(w, book, gs)
            if changed:
                await self._save()

    def _pending_settle(self, w: Any, book: GuestBook, gs: dict) -> bool:
        cur = play_key(gs.get("now")) if gs.get("now") is not None else ""
        if any(k not in book.settled and k != cur for k in book.play_by):
            return True
        if any(k != cur and k not in book.pots and w.pot(k)[0] for k in w.pledges):
            return True
        return any(e.paid_seq and e.removed and not w.led.is_refunded(e.paid_seq)
                   for e in gs.get("line") or [])

    async def _settle(self, w: Any, book: GuestBook, gs: dict) -> bool:
        """Under the lock: pay Adder credits for guests' songs that have
        played, return the pledges of a skip pot that wasn't filled before its
        song ended, and refund a song the host removed."""
        from services.jukebox.ledger import LedgerError
        cur = play_key(gs.get("now")) if gs.get("now") is not None else ""
        changed = False
        for key, adder in list(book.play_by.items()):
            if key in book.settled or key == cur:
                continue
            ups = tally(book, key)["up"]
            try:
                e = await self._ledger(w.led.adder_ups, adder, key, ups, False)
                if e is not None:
                    w.noted([e])
            except LedgerError:
                pass                       # already paid (a restart replayed it)
            book.settled.append(key)
            changed = True
        for key in list(w.pledges):
            if key == cur or key in book.pots:
                continue
            for _phone, _amount, seq in w.pledges[key]:
                if not w.led.is_refunded(seq):
                    w.noted([await self._ledger(w.led.refund, seq, None, "the pot wasn't filled")])
            book.pots[key] = "refunded"
            changed = True
        for e in gs.get("line") or []:
            if e.paid_seq and e.removed and not w.led.is_refunded(e.paid_seq):
                w.noted([await self._ledger(w.led.refund, e.paid_seq, None, "the host removed it")])
                changed = True
        return changed

    async def _close_night(self) -> None:
        """After a night ends: return what was paid for songs that never
        played and pledges still in a pot (the night ended first)."""
        w = self._wallet
        if w is None or w.night_id in self._wallet_closed:
            return
        night = getattr(self.deps.runner(), "night", None)
        if night is None or night.id != w.night_id or night.state == "running":
            return
        self._wallet_closed.add(w.night_id)
        async with self._get_lock():
            for e in night.line:
                if e.paid_seq and e.state in ("queued", "committed", "removed") \
                        and not w.led.is_refunded(e.paid_seq):
                    w.noted([await self._ledger(w.led.refund, e.paid_seq, None,
                                                "the night ended first")])
            for key, pledges in w.pledges.items():
                for _phone, _amount, seq in pledges:
                    if not w.led.is_refunded(seq):
                        w.noted([await self._ledger(w.led.refund, seq, None,
                                                    "the night ended first")])

    def _ok(self, book: GuestBook, pid: str, gs: dict, **extra: Any) -> tuple[int, dict]:
        return 200, {"status": "ok", **extra, "view": self._view(book, pid, gs)}

    # ── the calls the guest app forwards ────────────────────────────────────

    async def hello(self, phone: Any, token: Any) -> tuple[int, dict]:
        """A phone opens the page. A phone already in tonight's book needs
        nothing more; any other needs tonight's token, and gets a code (its
        own, if it brought a well-formed one) and a fun name."""
        async with self._get_lock():
            gs = self._running()
            if gs is None:
                return 200, idle_view(self.deps.now_ms(), self.deps.show())
            book = self._book_for(gs["night_id"])
            if valid_phone_id(phone) and phone in book.phones:
                if book.phones[phone].blocked:
                    return refusal("blocked", 403)
                self._seen[phone] = self.deps.now_ms()
                return self._ok(book, phone, gs, phone=phone)
            if not self.deps.token_ok(token):
                return refusal("needs_link", 403)
            show = self.deps.show()
            if len(book.phones) >= show.max_phones:
                return refusal("party_full", 403)
            pid = phone if valid_phone_id(phone) else new_phone_id()
            book.phones[pid] = GuestPhone(id=pid, name=fun_name(self.deps.rng, self._taken(book)),
                                          created_ms=self.deps.now_ms(),
                                          approved=not show.approve_new_phones)
            self._seen[pid] = self.deps.now_ms()
            await self._save()
            return self._ok(book, pid, gs, phone=pid)

    async def join(self, phone: Any, name: Any = None) -> tuple[int, dict]:
        """"Let's go": the phone joins, with the name on its welcome screen
        (or a name it typed there)."""
        async with self._get_lock():
            gate, gs, book = self._gate(phone)
            if gate:
                return gate
            me = book.phones[phone]
            if name is not None and name != me.name and not me.name_locked:
                clean, why = clean_name(name, self.deps.show().word_filter)
                if clean is None:
                    return refusal(why, 422)
                if clean.lower() in self._taken(book, phone):
                    return refusal("name_taken", 422)
                me.name = clean
            if not me.joined:
                me.joined, me.joined_ms = True, self.deps.now_ms()
            await self._save()
        await self._credits_tick(book, phone, gs, self.deps.show())     # the welcome credits
        return self._ok(book, phone, gs)

    async def rename(self, phone: Any, name: Any = None, shuffle: bool = False) -> tuple[int, dict]:
        """A new name: typed, or a fresh fun one (shuffle). Free on the
        welcome screen; the show's number of changes after joining."""
        async with self._get_lock():
            gate, gs, book = self._gate(phone)
            if gate:
                return gate
            me = book.phones[phone]
            show = self.deps.show()
            if me.name_locked:
                return refusal("name_locked", 422)
            if me.joined and me.renames >= show.renames_per_night:
                return refusal("renames_used", 422)
            if shuffle:
                new = fun_name(self.deps.rng, self._taken(book, phone) | {me.name.lower()})
            else:
                new, why = clean_name(name, show.word_filter)
                if new is None:
                    return refusal(why, 422)
                if new.lower() in self._taken(book, phone):
                    return refusal("name_taken", 422)
            if new != me.name:
                me.name = new
                if me.joined:
                    me.renames += 1
                await self._save()
            return self._ok(book, phone, gs)

    async def vote(self, phone: Any, vote: Any) -> tuple[int, dict]:
        """▲ (up), ▼ (down) or none (take it back) on the song playing now."""
        values = {"up": 1, "down": -1, "none": 0}
        if vote not in values:
            return refusal("bad_vote", 422)
        async with self._get_lock():
            gate, gs, book = self._gate(phone)
            if gate:
                return gate
            me = book.phones[phone]
            if not me.joined:
                return refusal("not_joined", 409)
            if not me.approved:
                return refusal("not_approved", 409)
            view = self._view(book, phone, gs)
            now = view["now"]
            if now is None:
                return refusal("nothing_playing", 409)
            if not now["can_vote"]:
                code = ("own_song" if now["mine"] else
                        "skipping" if getattr(gs["now"], "kind", "") == "skipping" else
                        "not_votable")
                return refusal(code, 409)
            key = play_key(gs["now"])
            adder = self._guest_adder(book, gs)
            if adder:
                self._count_release(book, gs, adder)      # before this vote moves the count
                book.play_by[key] = adder
            plays = book.votes.setdefault(key, {})
            if values[vote]:
                plays[phone] = values[vote]
            else:
                plays.pop(phone, None)
            while len(book.votes) > PLAYS_KEPT:
                old = next(iter(book.votes))
                book.votes.pop(old)
                book.play_by.pop(old, None)
            if adder:
                await self._maybe_jail(book, gs, adder)
            show = self.deps.show()
            earned = 0
            if show.play_mode == "credits" and values[vote]:
                w = self._wallet_for(gs["night_id"], show)
                paid = await self._ledger(w.led.vote, phone, key, False)
                if paid is not None:
                    w.noted([paid])
                    earned = paid.delta
            await self._save()
            if show.play_mode == "credits":
                if await self._maybe_fill_pot(book, gs, key):    # a ▼ lowers the price
                    gs = self.deps.state()
            elif await self._maybe_skip(book, gs, key):
                gs = self.deps.state()
        await self._credits_tick(book, phone, gs, self.deps.show())
        return self._ok(book, phone, gs, earned=earned)

    # ── free play: the room's skip and the jail (PR 2.3) ───────────────────

    def _guest_adder(self, book: GuestBook, gs: dict) -> str:
        """The guest whose song is playing ('' for the host's and the set's)."""
        now = gs.get("now")
        if getattr(now, "kind", "") != "jukebox" or not now.entry_id:
            return ""
        for e in gs.get("line") or []:
            if e.id == now.entry_id:
                return e.added_by if e.added_by in book.phones else ""
        return ""

    def _count_release(self, book: GuestBook, gs: dict, pid: str) -> None:
        """A time-out that has ended since the book last looked: the count
        starts again at 0 from here."""
        p = book.phones[pid]
        if p.jail_open and not jailed_now(gs, pid):
            p.jail_open = False
            p.jail_base = net_downs(book, pid)

    async def _maybe_jail(self, book: GuestBook, gs: dict, pid: str) -> None:
        from services.jukebox import economy
        show = self.deps.show()
        p = book.phones[pid]
        credits = show.play_mode == "credits"     # credits: jailed until they break out
        if (not credits and not show.free_jail_songs) or p.jail_open or jailed_now(gs, pid):
            return
        if not economy.jailed(net_downs(book, pid) - p.jail_base, self._crowd(), show.economy):
            return
        out = await self.deps.runner().jail(pid, None if credits else show.free_jail_songs)
        if out.get("status") == "jailed":
            p.jail_open, p.jailed_ms = True, self.deps.now_ms()
            p.jails += 1

    async def _maybe_skip(self, book: GuestBook, gs: dict, key: str) -> bool:
        """The room's skip: due now, or once the song's first seconds (the
        grace that stops mis-taps) are over — checked again then. True: the
        engine skipped it."""
        now = gs.get("now")
        if getattr(now, "kind", "") not in ("set", "jukebox") or play_key(now) != key:
            return False
        show = self.deps.show()
        votes = tally(book, key)
        if skip_needed(votes["down"], votes["up"], show):
            return False
        wait_s = show.economy.skip_grace_s - (self.deps.now_ms() - (now.started_ms or 0)) / 1000
        if wait_s > 0:
            if key not in self._skip_armed:
                self._skip_armed.add(key)
                task = asyncio.create_task(self._skip_later(key, wait_s))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
            return False
        out = await self.deps.runner().skip_by_vote(now.started_ms, now.uri)
        return out.get("status") == "skipped"

    async def _skip_later(self, key: str, wait_s: float) -> None:
        await self.deps.sleep(wait_s + 0.05)
        async with self._get_lock():
            self._skip_armed.discard(key)
            try:
                gs = self._running()
                if gs is None or self._book is None or self._book.night_id != gs["night_id"]:
                    return
                await self._maybe_skip(self._book, gs, key)
            except Exception:                                      # noqa: BLE001
                logger.exception("Jukebox: the room's skip couldn't be checked after the grace")

    async def bump(self, phone: Any, entry_id: Any, direction: Any,
                   price: Any = None) -> tuple[int, dict]:
        """A bump: your own waiting song up one place, or someone else's down
        one place — so many times an hour in free play; at its price in
        credits mode (`price` is what the page showed: a dearer price now is
        refused, never charged)."""
        if direction not in ("up", "down") or not isinstance(entry_id, str):
            return refusal("bad_bump", 422)
        async with self._get_lock():
            gate, gs, book = self._gate(phone)
            if gate:
                return gate
            me = book.phones[phone]
            if not me.joined:
                return refusal("not_joined", 409)
            if not me.approved:
                return refusal("not_approved", 409)
            show = self.deps.show()
            credits = show.play_mode == "credits"
            left = jailed_now(gs, phone)
            if left:
                return self._jailed_refusal(left, credits, show)
            now_ms = self.deps.now_ms()
            if not credits:
                if not show.free_bumps_per_hour:
                    return refusal("bumps_off", 409)
                me.bumps_ms = [t for t in me.bumps_ms if now_ms - t < BUMP_WINDOW_MS]
                state = bumps_state(me, show, now_ms)
                if not state["left"]:
                    n = show.free_bumps_per_hour
                    return refusal("bumps_used", 409, n=n, s="" if n == 1 else "s",
                                   at=state["next_at"])
            line = gs.get("line") or []
            entry = next((e for e in line if e.id == entry_id), None)
            if entry is None or entry.state not in ("queued", "committed"):
                return refusal("no_entry", 404)
            if direction == "up" and entry.added_by != phone:
                return refusal("bump_own_up", 409)
            if direction == "down" and entry.added_by == phone:
                return refusal("bump_others_down", 409)
            cost = 0
            if credits:
                from services.jukebox import wallet
                movable = [e.id for e in line if e.state == "queued" and not e.held
                           and not jailed_now(gs, e.added_by)]
                if entry_id in movable:
                    up_price, down_price = wallet.bump_prices(movable, entry_id, show.economy)
                    cost = up_price if direction == "up" else down_price
                    stop = self._afford(gs, phone, show, cost, price)
                    if stop:
                        return stop
            out = await self.deps.runner().bump(entry_id, direction == "up",
                                                max_back=show.economy.bump_down_max_places)
            if out.get("status") != "moved":
                code = out.get("reason", "not_running")
                if code in SENTENCES:
                    return refusal(code, 409)
                return 409, {"status": "refused", "reason": code, "detail": out.get("detail", "")}
            if credits and cost:
                await self._spend(gs, show, phone, "bump_up" if direction == "up" else "bump_down",
                                  cost, entry_id)
            else:
                me.bumps_ms.append(now_ms)
            await self._save()
            gs = self.deps.state()
            return 200, {"status": "ok", "bumped": {"place": out.get("place"),
                                                    "starts_in_ms": out.get("starts_in_ms")},
                         "view": self._view(book, phone, gs)}

    # ── credits mode: the guest's own spends (PR 3.2) ──────────────────────

    def _jailed_refusal(self, left: int, credits: bool, show: ShowConfig) -> tuple[int, dict]:
        if credits:
            return refusal("jailed_credits", 409, fee=show.economy.jail_fee)
        return refusal("jailed", 409, n=left, s="" if left == 1 else "s")

    def _afford(self, gs: dict, phone: str, show: ShowConfig, cost: int,
                seen: Any) -> Optional[tuple[int, dict]]:
        """Refuse a spend whose price rose since the page showed it (never
        charge more than the guest saw), or that the phone can't pay."""
        try:
            seen_i = None if seen is None else int(seen)
        except (TypeError, ValueError):
            return refusal("bad_amount", 422)
        if seen_i is not None and cost > seen_i:
            return 409, {"status": "refused", "reason": "price_changed", "price": cost,
                         "detail": sentence("price_changed", price=cost)}
        have = self._wallet_for(gs["night_id"], show).balance(phone)
        if have < cost:
            return refusal("not_enough", 409, need=cost, have=have)
        return None

    async def _spend(self, gs: dict, show: ShowConfig, phone: str, kind: str, amount: int,
                     ref: str, note: str = "") -> Any:
        w = self._wallet_for(gs["night_id"], show)
        e = await self._ledger(w.led.spend, phone, kind, amount, ref, note)
        w.noted([e])
        return e

    def _ledger_refusal(self, err: Exception) -> tuple[int, dict]:
        return 409, {"status": "refused", "reason": getattr(err, "code", "refused"),
                     "detail": getattr(err, "sentence", str(err))}

    async def _credits_gate(self, phone: Any) -> tuple[Optional[tuple[int, dict]], Optional[dict],
                                                       Optional[GuestBook], ShowConfig]:
        """Under the lock: a joined, approved phone in credits mode."""
        show = self.deps.show()
        gate, gs, book = self._gate(phone)
        if gate:
            return gate, None, None, show
        me = book.phones[phone]
        if not me.joined:
            return refusal("not_joined", 409), None, None, show
        if not me.approved:
            return refusal("not_approved", 409), None, None, show
        if show.play_mode != "credits":
            return refusal("credits_off", 409), None, None, show
        return None, gs, book, show

    async def tip(self, phone: Any, units: Any = 1) -> tuple[int, dict]:
        """Tip the guest whose song is playing (§1 rule 4): a tap at a time,
        at most `tip_max_per_song` per song; never the host, never yourself.
        The page holds a tap for a few seconds (its undo) before sending it."""
        from services.jukebox.ledger import LedgerError
        try:
            n = int(units)
        except (TypeError, ValueError):
            return refusal("bad_amount", 422)
        async with self._get_lock():
            gate, gs, book, show = await self._credits_gate(phone)
            if gate:
                return gate
            now = gs.get("now")
            if getattr(now, "kind", "") != "jukebox":
                return refusal("host_tip", 409)
            entry = next((e for e in gs.get("line") or [] if e.id == now.entry_id), None)
            if entry is None or entry.added_by not in book.phones:
                return refusal("host_tip", 409)
            w = self._wallet_for(gs["night_id"], show)
            try:
                parts = await self._ledger(w.led.tip, phone, entry.added_by, play_key(now), n, False)
            except LedgerError as err:
                return self._ledger_refusal(err)
            w.noted(parts)
            await self._save()
            return self._ok(book, phone, gs, tipped={"to": book.phones[entry.added_by].name,
                                                     "amount": -parts[0].delta,
                                                     "bonus": sum(p.delta for p in parts[2:])})

    async def skip(self, phone: Any, how: Any = "pay", amount: Any = None,
                   price: Any = None) -> tuple[int, dict]:
        """Skip the song playing (§1 rule 8): pay the rest of its price now,
        or chip in toward it (the pledges come back if the pot isn't filled
        before the song ends). Anyone's song but your own, the host's
        included; never in its first seconds; never one the host kept from
        skips."""
        if how not in ("pay", "chip"):
            return refusal("bad_amount", 422)
        async with self._get_lock():
            gate, gs, book, show = await self._credits_gate(phone)
            if gate:
                return gate
            cfg = show.economy
            now = gs.get("now")
            if getattr(now, "kind", "") not in ("set", "jukebox") or not now.started_ms:
                return refusal("skip_none", 409)
            key = play_key(now)
            if now.uri in (gs.get("no_skip") or []):
                return refusal("skip_locked", 409)
            if self._guest_adder(book, gs) == phone:
                return refusal("own_skip", 409)
            played_s = (self.deps.now_ms() - now.started_ms) / 1000
            from services.jukebox import economy, wallet
            if not economy.skip_allowed(played_s, cfg):
                return refusal("skip_grace", 409, s=int(cfg.skip_grace_s))
            if book.pots.get(key) == "filled":
                return refusal("pot_full", 409)
            w = self._wallet_for(gs["night_id"], show)
            votes = tally(book, key)
            full = wallet.skip_price(self._back_wait_ms(gs), votes["up"], votes["down"],
                                     self._crowd(), cfg)
            have, _ = w.pot(key)
            need = max(1, full - have)
            if how == "pay":
                cost, kind = need, "skip"
                stop = self._afford(gs, phone, show, cost, price)
            else:
                if not cfg.chip_in:
                    return refusal("chip_off", 409)
                try:
                    cost = int(amount)
                except (TypeError, ValueError):
                    return refusal("bad_amount", 422)
                if cost < 1:
                    return refusal("bad_amount", 422)
                cost, kind = min(cost, need), "skip_pledge"
                stop = self._afford(gs, phone, show, cost, None)
            if stop:
                return stop
            spent = await self._spend(gs, show, phone, kind, cost, key)
            skipped = False
            if have + cost >= full:
                out = await self.deps.runner().skip_by_vote(now.started_ms, now.uri, reason="paid")
                if out.get("status") == "skipped":
                    book.pots[key] = "filled"
                    skipped = True
                else:          # it moved on, or was locked, in the meantime: nothing was bought
                    w.noted([await self._ledger(w.led.refund, spent.seq, None, "the song moved on")])
            await self._save()
            if skipped:
                gs = self.deps.state()
            return self._ok(book, phone, gs, skip={"paid": cost, "skipped": skipped,
                                                   "pot": have + cost, "price": full})

    async def _maybe_fill_pot(self, book: GuestBook, gs: dict, key: str) -> bool:
        """Under the lock, after a vote: a ▼ lowers the skip price, so a
        chip-in pot may now be enough. True: the engine skipped it."""
        from services.jukebox import economy, wallet
        show = self.deps.show()
        now = gs.get("now")
        if (getattr(now, "kind", "") not in ("set", "jukebox") or play_key(now) != key
                or book.pots.get(key) or now.uri in (gs.get("no_skip") or [])):
            return False
        w = self._wallet_for(gs["night_id"], show)
        have, _ = w.pot(key)
        if not have:
            return False
        votes = tally(book, key)
        full = wallet.skip_price(self._back_wait_ms(gs), votes["up"], votes["down"],
                                 self._crowd(), show.economy)
        played_s = (self.deps.now_ms() - (now.started_ms or 0)) / 1000
        if have < full or not economy.skip_allowed(played_s, show.economy):
            return False
        out = await self.deps.runner().skip_by_vote(now.started_ms, now.uri, reason="paid")
        if out.get("status") == "skipped":
            book.pots[key] = "filled"
            await self._save()
            return True
        return False

    async def play_next(self, phone: Any, entry_id: Any, price: Any = None) -> tuple[int, dict]:
        """Play next (§1 rule 7): your own waiting song to the front of the
        jukebox line, priced by how far it jumps; only for a song at least
        `next_min_away_min` away, once per song."""
        if not isinstance(entry_id, str):
            return refusal("no_entry", 404)
        async with self._get_lock():
            gate, gs, book, show = await self._credits_gate(phone)
            if gate:
                return gate
            left = jailed_now(gs, phone)
            if left:
                return self._jailed_refusal(left, True, show)
            line = gs.get("line") or []
            entry = next((e for e in line if e.id == entry_id), None)
            if entry is None or entry.state not in ("queued", "committed"):
                return refusal("no_entry", 404)
            if entry.added_by != phone:
                return refusal("next_own", 409)
            if entry.state == "committed":
                return refusal("committed_fixed", 409)
            from services.jukebox import wallet
            runner = self.deps.runner()
            movable = [e.id for e in line if e.state == "queued" and not e.held
                       and not jailed_now(gs, e.added_by)]
            if not movable or movable[0] == entry_id:
                return refusal("at_front_next", 409)
            q = wallet.next_quote(runner._starts_in(entry_id), runner._starts_in(movable[0]),
                                  entry.nexted, show.economy)
            if not q["allowed"]:
                if entry.nexted:
                    return refusal("nexted", 409)
                return refusal("next_too_soon", 409, m=int(show.economy.next_min_away_min))
            stop = self._afford(gs, phone, show, q["price"], price)
            if stop:
                return stop
            out = await runner.play_next(entry_id, max_back=show.economy.bump_down_max_places)
            if out.get("status") != "moved":
                code = out.get("reason", "not_running")
                return refusal(code, 409) if code in SENTENCES else \
                    (409, {"status": "refused", "reason": code, "detail": out.get("detail", "")})
            await self._spend(gs, show, phone, "play_next", q["price"], entry_id)
            await self._save()
            gs = self.deps.state()
            return 200, {"status": "ok", "next": {"price": q["price"],
                                                  "starts_in_ms": out.get("starts_in_ms")},
                         "view": self._view(book, phone, gs)}

    async def break_out(self, phone: Any) -> tuple[int, dict]:
        """Break out of jail (§1 rule 9): `jail_fee` credits, and your count
        starts again at 0."""
        async with self._get_lock():
            gate, gs, book, show = await self._credits_gate(phone)
            if gate:
                return gate
            if not jailed_now(gs, phone):
                return refusal("not_jailed_self", 409)
            fee = show.economy.jail_fee
            stop = self._afford(gs, phone, show, fee, None)
            if stop:
                return stop
            w = self._wallet_for(gs["night_id"], show)
            spent = await self._ledger(w.led.jail_breakout, phone, "jail")
            w.noted([spent])
            out = await self.deps.runner().pardon(phone, broke_out=True)
            if out.get("status") != "pardoned":
                w.noted([await self._ledger(w.led.refund, spent.seq, None, "not in jail after all")])
                await self._save()
                return refusal("not_jailed_self", 409)
            p = book.phones[phone]
            p.jail_open, p.jail_base = False, net_downs(book, phone)
            await self._save()
            gs = self.deps.state()
            return self._ok(book, phone, gs, broke_out={"paid": fee})

    async def wallet_view(self, phone: Any) -> tuple[int, dict]:
        """The Shop: the balance and how it was made, what each thing costs
        right now, how to earn, and this phone's history in words."""
        from services.jukebox import economy, wallet
        gate, gs, book = self._gate(phone)
        if gate:
            return gate
        show = self.deps.show()
        if show.play_mode != "credits":
            return refusal("credits_off", 409)
        await self._credits_tick(book, phone, gs, show)
        cfg = show.economy
        w = self._wallet_for(gs["night_id"], show)
        entries = w.led.history(phone)
        titles: dict[str, str] = {}
        for e in gs.get("line") or []:
            titles[e.uri] = e.title
            titles[e.id] = e.title
        for it in gs.get("set_items") or []:
            titles.setdefault(it.uri, it.title)
        names = {pid: p.name for pid, p in book.phones.items()}
        line = gs.get("line") or []
        played = sum(1 for e in line if e.added_by == phone and e.state in ("played", "playing"))
        rnd = played + len(waiting(line, phone)) + 1
        runner = self.deps.runner()
        add_wait = runner.quote_wait(rnd, cfg.fair_order)
        now = gs.get("now")
        skip_now = None
        if getattr(now, "kind", "") in ("set", "jukebox"):
            votes = tally(book, play_key(now))
            skip_now = wallet.skip_price(self._back_wait_ms(gs), votes["up"], votes["down"],
                                         self._crowd(), cfg)
        shop = [
            {"id": "add", "title": "Add a song",
             "price": wallet.add_price(add_wait, 216_000, True, cfg),
             "note": f"{cfg.add_base} when it plays within {int(cfg.add_free_min)} min; "
                     f"it doubles every {int(cfg.add_double_min)} min of wait"},
            {"id": "next", "title": "Play next", "price": economy.play_next_price(10, cfg),
             "note": f"from {cfg.next_base}: your song to the front of the line, once per song"},
            {"id": "skip", "title": "Skip", "price": skip_now,
             "note": "the price falls with every ▼ on the song"},
            {"id": "chip", "title": "Chip in", "price": 1 if cfg.chip_in else None,
             "note": "put something toward a skip; it comes back if the pot isn't filled"},
            {"id": "bump", "title": "Bump", "price": economy.bump_up_price(0, cfg),
             "note": f"move a song one place: up from {cfg.bump_up_base}, down from "
                     f"{cfg.bump_down_base}"},
            {"id": "breakout", "title": "Break out", "price": cfg.jail_fee,
             "note": "leave jail; your count starts again"},
        ]
        return 200, {"status": "ok", "balance": w.balance(phone), "earned": wallet.earned(entries),
                     "history": wallet.history_rows(entries, names, titles), "shop": shop,
                     "how_to_earn": list(wallet.HOW_TO_EARN), "disclaimer": wallet.DISCLAIMER,
                     "view": self._view(book, phone, gs)}

    async def view(self, phone: Any) -> tuple[int, dict]:
        gate, gs, book = self._gate(phone)
        if gate:
            if gs is None and self._wallet is not None:
                await self._close_night()
            return gate
        await self._credits_tick(book, phone, gs, self.deps.show())
        return 200, {"status": "ok", "view": self._view(book, phone, gs)}

    # ── finding and adding a song ───────────────────────────────────────────

    def _cached_meta(self, uri: str) -> Optional[dict]:
        hit = self._meta.get(uri)
        if hit and self.deps.clock() - hit[0] < META_CACHE_S:
            return hit[1]
        return None

    def _remember(self, metas: list[dict]) -> None:
        now = self.deps.clock()
        for m in metas:
            self._meta[m["uri"]] = (now, m)
        if len(self._meta) > META_CACHE_MAX:
            for k, _ in sorted(self._meta.items(), key=lambda kv: kv[1][0])[: META_CACHE_MAX // 5]:
                self._meta.pop(k, None)

    async def _find(self, query: str, offset: int) -> tuple[list[dict], list[str], bool]:
        """(the songs for a query — his library's first, on the first page —
        which of them came from his library, and whether Spotify has another
        page). Cached; every disk read and Spotify call off the event loop."""
        key = (" ".join(query.lower().split()), offset)
        hit = self._searches.get(key)
        if hit and self.deps.clock() - hit[0] < SEARCH_CACHE_S:
            return hit[1], hit[2], hit[3]
        gw = self.deps.gateway()
        library_uris: list[str] = []
        metas: list[dict] = []
        if offset == 0:
            mine = await self.deps.to_thread(self.deps.library_search, query, LIBRARY_HITS)
            library_uris = [s.uri for s in mine]
            if library_uris:
                metas = await self.deps.to_thread(gw.tracks, library_uris)
                order = {u: i for i, u in enumerate(library_uris)}
                metas.sort(key=lambda m: order.get(m["uri"], 99))
        found = await self.deps.to_thread(gw.search, query, SEARCH_PAGE, offset)
        seen = {m["uri"] for m in metas}
        metas += [m for m in found if m["uri"] not in seen]
        self._remember(metas)
        more = len(found) >= SEARCH_PAGE
        self._searches[key] = (self.deps.clock(), metas, library_uris, more)
        if len(self._searches) > SEARCH_CACHE_MAX:
            for k, _ in sorted(self._searches.items(), key=lambda kv: kv[1][0])[: SEARCH_CACHE_MAX // 5]:
                self._searches.pop(k, None)
        return metas, library_uris, more

    async def search(self, phone: Any, query: Any, offset: Any = 0) -> tuple[int, dict]:
        """A guest's search: his library's songs first ("Ready"), then
        Spotify, SEARCH_PAGE a page; each with its badges and whether it can
        go in (and why not)."""
        gate, gs, book = self._gate(phone)
        if gate:
            return gate
        q = " ".join(str(query or "").split())
        if not QUERY_MIN <= len(q) <= QUERY_MAX:
            return refusal("bad_query", 422)
        try:
            off = max(0, min(int(offset or 0), 200))
        except (TypeError, ValueError):
            off = 0
        try:
            metas, library_uris, more = await self._find(q, off)
        except Exception:                                          # noqa: BLE001
            return refusal("search_failed", 503)
        known = await self.deps.to_thread(self.deps.known, [m["uri"] for m in metas])
        show = self.deps.show()
        now_ms = self.deps.now_ms()
        ok, why = explicit_rule(show, int(gs.get("started_ms") or now_ms), now_ms)
        in_line = {e.uri for e in gs.get("line") or [] if e.state in ("queued", "committed")}
        lib = set(library_uris)
        wait_ms: Optional[int] = None
        balance: Optional[int] = None
        credits = show.play_mode == "credits"
        if credits:
            line = gs.get("line") or []
            played = sum(1 for e in line if e.added_by == phone and e.state in ("played", "playing"))
            wait_ms = self.deps.runner().quote_wait(played + len(waiting(line, phone)) + 1,
                                                    show.economy.fair_order)
            balance = self._wallet_for(gs["night_id"], show).balance(phone)
        results = [result_view(m, known=bool(known.get(m["uri"])), in_line=m["uri"] in in_line,
                               explicit_ok=ok, explicit_why=why,
                               long_over_min=show.economy.long_over_min, library=m["uri"] in lib,
                               price=(add_cost(int(m.get("duration_ms") or 0),
                                               bool(known.get(m["uri"])), bool(m.get("explicit")),
                                               wait_ms, show) if credits else None),
                               balance=balance)
                   for m in metas]
        return 200, {"status": "ok", "query": q, "offset": off, "results": results,
                     "more": more,
                     "next_offset": off + SEARCH_PAGE,
                     "view": self._view(book, phone, gs)}

    async def add(self, phone: Any, uri: Any, price: Any = None) -> tuple[int, dict]:
        """A guest adds a song: every rule in the module docstring, then
        fair order, then "would it start before the night ends?". In credits
        mode it is priced by when it would play (`price` is what the page
        showed: a dearer price now is refused, never charged) and the price
        is locked when it goes in. A refusal adds nothing and costs nothing."""
        from services.jukebox.gateway import parse_track_uri
        gate, gs, book = self._gate(phone)
        if gate:
            return gate
        me = book.phones[phone]
        if not me.joined:
            return refusal("not_joined", 409)
        if not me.approved:
            return refusal("not_approved", 409)
        show = self.deps.show()
        left = jailed_now(gs, phone)
        if left:
            return self._jailed_refusal(left, show.play_mode == "credits", show)
        track_uri = parse_track_uri(uri if isinstance(uri, str) else "")
        if not track_uri:
            return refusal("track_unknown", 422)
        now_ms = self.deps.now_ms()
        started = int(gs.get("started_ms") or now_ms)
        reqs = requests_state(show, started, now_ms)
        if not reqs["open"]:
            return 409, {"status": "refused", "reason": "requests_closed", "detail": reqs["detail"]}
        meta = self._cached_meta(track_uri)
        if meta is None:
            try:
                meta = await self.deps.to_thread(self.deps.gateway().track, track_uri)
            except Exception:                                      # noqa: BLE001
                return refusal("search_failed", 503)
            if not meta:
                return refusal("track_unknown", 422)
            self._remember([meta])
        if meta.get("explicit"):
            ok, why = explicit_rule(show, started, now_ms)
            if not ok:
                return 409, {"status": "refused", "reason": "explicit", "detail": why}
        known = (await self.deps.to_thread(self.deps.known, [track_uri])).get(track_uri, False)
        async with self._get_lock():
            gs = self.deps.state()
            if not gs.get("running"):
                return refusal("not_running", 409)
            line = gs.get("line") or []
            if any(e.uri == track_uri and e.state in ("queued", "committed") for e in line):
                return refusal("in_line", 409)
            mine = waiting(line, phone)
            limit = show.economy.max_waiting
            if len(mine) >= limit:
                return refusal("too_many", 409, n=len(mine), s="" if len(mine) == 1 else "s")
            played = sum(1 for e in line if e.added_by == phone and e.state in ("played", "playing"))
            entry = LineEntry(id=uuid.uuid4().hex[:10], uri=track_uri, title=meta.get("title") or "",
                              artist=meta.get("artist") or "",
                              duration_ms=int(meta.get("duration_ms") or 0),
                              image=meta.get("image") or "", thumb=meta.get("thumb") or "",
                              explicit=bool(meta.get("explicit")), known=bool(known),
                              added_ms=now_ms, added_by=phone, round=played + len(mine) + 1)
            cost = 0
            if show.play_mode == "credits":
                wait_ms = self.deps.runner().quote_wait(entry.round, show.economy.fair_order,
                                                        entry.duration_ms or 210_000)
                cost = add_cost(entry.duration_ms, entry.known, entry.explicit, wait_ms, show)
                stop = self._afford(gs, phone, show, cost, price)
                if stop:
                    return stop
            fresh_now_ms = self.deps.now_ms()
            out = await self.deps.runner().add_entry(entry, fair=show.economy.fair_order,
                                                     latest_start_ms=reqs["ends_at_ms"] - fresh_now_ms)
            if out.get("status") != "added":
                if out.get("reason") == "too_late":
                    return refusal("too_late", 409)
                return 409, {"status": "refused", "reason": out.get("reason", "not_running"),
                             "detail": out.get("detail") or sentence("not_running")}
            if cost:
                paid = await self._spend(gs, show, phone, "add", cost, entry.id)
                await self.deps.runner().mark_paid(entry.id, cost, paid.seq)
            gs = self.deps.state()
            return 200, {"status": "ok", "added": {"entry_id": entry.id, "title": entry.title,
                                                   "starts_in_ms": out.get("starts_in_ms"),
                                                   "paid": cost},
                         "view": self._view(book, phone, gs)}

    # ── the host's controls (the master's own routes) ───────────────────────

    def phones(self) -> dict:
        """Every phone at tonight's party, for the host: its code, name, how
        it stands, and its songs."""
        gs = self.deps.state()
        if not gs.get("running"):
            return {"running": False, "phones": []}
        book = self._book_for(gs["night_id"])
        line = gs.get("line") or []
        votes: dict[str, int] = {}
        for plays in book.votes.values():
            for pid in plays:
                votes[pid] = votes.get(pid, 0) + 1
        from services.jukebox import economy
        show = self.deps.show()
        at = economy.jail_threshold(self._crowd(), show.economy)
        credits = show.play_mode == "credits"
        w = self._wallet_for(gs["night_id"], show) if credits else None
        out = []
        for p in sorted(book.phones.values(), key=lambda p: p.created_ms):
            mine = [e for e in line if e.added_by == p.id]
            row = p.model_dump(mode="json", exclude={"bumps_ms"})
            out.append({**row,
                        "waiting": sum(1 for e in mine if e.state in ("queued", "committed")),
                        "played": sum(1 for e in mine if e.state == "played"),
                        "votes": votes.get(p.id, 0),
                        "jail_left": jailed_now(gs, p.id),
                        "jail_kind": "breakout" if credits else "timeout",
                        "jail_count": jail_count(book, p.id, gs), "jail_at": at,
                        **({"credits": w.balance(p.id)} if credits else {})})
        return {"running": True, "phones": out,
                "pending": sum(1 for p in book.phones.values() if not p.approved and not p.blocked),
                "jailed": sum(1 for p in out if p["jail_left"]), "crowd": self._crowd(),
                "play_mode": show.play_mode}

    async def host_set(self, phone: str, *, approved: Optional[bool] = None,
                       blocked: Optional[bool] = None, name_locked: Optional[bool] = None,
                       name: Optional[str] = None, pardon: bool = False) -> tuple[int, dict]:
        """The host: approve or block a phone, rename it (no word filter, no
        limit — his word), lock its name, pardon it (its time-out ends now
        and its count starts again at 0)."""
        async with self._get_lock():
            gs = self.deps.state()
            if not gs.get("running"):
                return refusal("not_running", 409)
            book = self._book_for(gs["night_id"])
            p = book.phones.get(phone)
            if p is None:
                return refusal("no_phone", 404)
            if pardon:                     # first: a refused pardon changes nothing else
                out = await self.deps.runner().pardon(phone)
                if out.get("status") != "pardoned":
                    return refusal("not_jailed", 409)
                p.jail_open, p.jail_base = False, net_downs(book, phone)
            if name is not None:
                clean, why = clean_name(name, word_filter=False)
                if clean is None:
                    return refusal(why, 422)
                if clean.lower() in self._taken(book, phone):
                    return refusal("name_taken", 422)
                p.name = clean
            if approved is not None:
                p.approved = approved
            if blocked is not None:
                p.blocked = blocked
            if name_locked is not None:
                p.name_locked = name_locked
            await self._save()
        return 200, {"status": "ok", **self.phones()}

    # ── the master's read ───────────────────────────────────────────────────

    def summary(self, night_id: Optional[str]) -> dict:
        """How many phones joined tonight (the master's Live tab)."""
        if not night_id:
            return {"phones": 0, "joined": 0, "pending": 0}
        if self._book is None:
            self._book = store.load_guests()
        book = self._book if self._book.night_id == night_id else GuestBook()
        return {"phones": len(book.phones),
                "joined": sum(1 for p in book.phones.values() if p.joined),
                "pending": sum(1 for p in book.phones.values() if not p.approved and not p.blocked)}


book = Guests()
