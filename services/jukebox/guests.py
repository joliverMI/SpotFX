"""
SpotFX — the Jukebox's GUESTS (data/jukebox-plan/report.md §7 and §9
phase 2, PR 2.1): tonight's phones, the names they picked, their votes on
the song playing, and the ONE view the guest page draws.

The guest page itself is a separate process (jukebox_guest/, on :8020): it
serves the page, keeps each phone's cookie, rate-limits, and forwards a short
allowlist of calls here over loopback, naming the phone. This module is what
those calls do; routers/jukebox_guest_router.py is the door, and it opens
only for the guest app's own key.

PHONES. A phone is a random code (no account, no sign-in) kept in a cookie
and in the phone's own storage, so clearing one keeps the other. A phone
joins tonight's party only with tonight's party token (services/jukebox/
guest_link.py — the `?t=` in the printed link); once it has joined, the code
alone brings it back. A phone from an earlier night keeps its code but must
show tonight's token again. At most PHONES_MAX phones a night.

NAMES. Every phone gets a fun name ("Sunny Fox") at hello; the welcome
screen's shuffle is free, and after "Let's go" a phone may rename
RENAMES_PER_NIGHT times. A name is 2-20 letters (any language's), digits,
spaces and ' . - _ — no emoji or symbols; it can't be anyone else's
tonight, the host's, or a word on the short block list.

VOTES (free play, the plan's §6). One vote per phone on the song playing —
▲ or ▼, changeable, withdrawable — keyed by the play (the song and the moment
it started), so a song that plays twice is voted on twice. Only while it
plays; never on your own song ("everyone else votes"); never on a song that
isn't part of tonight's program. Vote-to-skip and the jail come in PR 2.3;
credits for votes in phase 3.

THE VIEW is everything one phone's screen shows, built from the engine's
lean read (night.JukeboxRunner.guest_state — no Spotify call) and this book:
what is playing with its votes, the next songs with who added each, "your
songs" with their place and start time, the strip's tone (none / queued /
next / playing), and the house rules. Another phone's id never appears in
it — only names.

Every refusal is a sentence the page shows as it is, with a code.
"""
from __future__ import annotations

import asyncio
import random
import re
import secrets
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from models.jukebox import GuestBook, GuestPhone
from services.jukebox import store

PHONES_MAX = 150
RENAMES_PER_NIGHT = 3
PLAYS_KEPT = 300                 # plays whose votes are kept (the report reads them)
NEXT_SHOWN = 8                   # upcoming songs on the Now and Queue screens
POLL_MS = 3000                   # how often the page asks again while it is open
PHONE_RE = re.compile(r"^[A-Za-z0-9_-]{16,40}$")
NAME_MIN, NAME_MAX = 2, 20
_NAME_PUNCT = set(" '._-")
_RESERVED = {"host", "the host", "dj", "spotfx", "spectra", "serenity", "jukebox", "admin"}

# The words a name may not contain (after folding look-alike digits).
# Deliberately short: the host renames or blocks anything that slips by.
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

HOUSE_RULES: tuple[str, ...] = (
    "Songs for everyone: pick music the room will enjoy.",
    "One vote per song. Vote on what's playing — not on people.",
    "No explicit songs tonight.",
    "The host's word is final: they can remove any song or name.",
)
PRIVACY = ("This page keeps a random code for your phone and the name you pick, for "
           "tonight's party only. No sign-in, no account, and nothing about you leaves "
           "the house.")
HOW_IT_WORKS: tuple[dict, ...] = (
    {"icon": "vote", "title": "Vote", "text": "Tap ▲ or ▼ on the song that's playing."},
    {"icon": "queue", "title": "See what's next", "text": "The Queue shows every song coming up."},
    {"icon": "note", "title": "Your songs", "text": "When the host adds your song, this page tells you when it plays."},
)

SENTENCES: dict[str, str] = {
    "idle": "The Jukebox isn't playing right now. Come back when the music starts.",
    "needs_link": "Open tonight's party link (the QR code at the party) to join.",
    "party_full": "This party has as many phones as it can take tonight.",
    "not_joined": "Tap Let's go first.",
    "name_bad": "A name is 2-20 letters, numbers or spaces.",
    "name_taken": "Someone already has that name tonight.",
    "name_blocked": "Pick a different name.",
    "renames_used": "That's all the name changes for tonight.",
    "bad_vote": "That isn't a vote.",
    "nothing_playing": "Nothing is playing yet.",
    "own_song": "It's your song — everyone else votes.",
    "not_votable": "This song isn't part of tonight's program, so it can't be voted on.",
    "skipping": "This song is being skipped.",
}


def sentence(code: str) -> str:
    return SENTENCES.get(code, code)


def refusal(code: str, http: int) -> tuple[int, dict]:
    return http, {"status": "refused", "reason": code, "detail": sentence(code)}


# ── pure: ids, names ─────────────────────────────────────────────────────────

def new_phone_id() -> str:
    return secrets.token_urlsafe(16)


def valid_phone_id(given: Any) -> bool:
    return isinstance(given, str) and bool(PHONE_RE.match(given))


def _fold(name: str) -> str:
    return re.sub(r"[^a-z]", "", name.lower().translate(_LEET))


def clean_name(raw: Any) -> tuple[Optional[str], str]:
    """(the name as it will show, "") or (None, the refusal code)."""
    if not isinstance(raw, str):
        return None, "name_bad"
    name = unicodedata.normalize("NFKC", raw)
    name = re.sub(r"\s+", " ", name).strip()
    if not NAME_MIN <= len(name) <= NAME_MAX or not any(c.isalnum() for c in name) or not all(
            c in _NAME_PUNCT or unicodedata.category(c)[0] in "LN" for c in name):
        return None, "name_bad"
    folded = _fold(name)
    if name.lower() in _RESERVED or any(w in folded for w in _BLOCKED):
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


def build_view(book: GuestBook, phone_id: str, gs: dict, now_ms: int) -> dict:
    """Everything one phone's screen shows. Pure: the book, the phone, the
    engine's lean read (night.JukeboxRunner.guest_state) and the clock."""
    me = book.phones[phone_id]
    names = _names(book)
    out: dict[str, Any] = {
        "state": "running", "server_ms": now_ms, "poll_ms": POLL_MS,
        "me": {"name": me.name, "joined": me.joined,
               "renames_left": max(0, RENAMES_PER_NIGHT - me.renames)},
        "features": {"add": False, "board": False, "credits": False},
        "house_rules": list(HOUSE_RULES), "privacy": PRIVACY, "how": list(HOW_IT_WORKS),
    }
    entries = {e.id: e for e in gs.get("line") or []}
    set_items = gs.get("set_items") or []
    now = gs.get("now")
    np: Optional[dict] = None
    kind = getattr(now, "kind", "") if now is not None else ""
    if kind in ("set", "jukebox"):
        entry = entries.get(now.entry_id) if kind == "jukebox" else None
        idx = now.set_index if kind == "set" else None
        item = set_items[idx] if idx is not None and 0 <= idx < len(set_items) else None
        src = entry or item
        added_by = entry.added_by if entry is not None else None
        mine = added_by == phone_id
        key = play_key(now)
        my_vote = (book.votes.get(key) or {}).get(phone_id, 0)
        np = _song("set" if kind == "set" else "jukebox", now.uri,
                   getattr(src, "title", "") or now.title, getattr(src, "artist", ""),
                   getattr(src, "image", ""), getattr(src, "thumb", ""),
                   _by(added_by, names), mine)
        np.update({"votes": tally(book, key), "my_vote": my_vote,
                   "can_vote": not mine and bool(now.started_ms),
                   "why_not": sentence("own_song") if mine else ""})
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
                     "duration_ms": it.duration_ms, "place": len(upcoming) + 1})
        if added_by == phone_id:
            song["entry_id"] = it.entry_id
        upcoming.append(song)
    out["next"] = upcoming[:NEXT_SHOWN]

    places = {s.get("entry_id"): s for s in upcoming if s.get("entry_id")}
    mine_list: list[dict] = []
    for e in gs.get("line") or []:
        if e.added_by != phone_id or e.state not in ("queued", "committed", "playing"):
            continue
        at = places.get(e.id)
        song = _song("jukebox", e.uri, e.title, e.artist, e.image, e.thumb,
                     _by(e.added_by, names), True)
        song.update({"entry_id": e.id, "state": "playing" if e.state == "playing" else
                     "next" if at is not None and at["place"] == 1 else "waiting",
                     "committed": e.state == "committed",
                     "place": at["place"] if at else None,
                     "starts_in_ms": at["starts_in_ms"] if at else None})
        mine_list.append(song)
    mine_list.sort(key=lambda s: (s["state"] != "playing",
                                  s["place"] if s["place"] is not None else 10_000))
    out["mine"] = mine_list
    lead = mine_list[0] if mine_list else None
    out["strip"] = {"tone": ("playing" if lead["state"] == "playing" else
                             "next" if lead["state"] == "next" else "queued") if lead else "none",
                    "title": lead["title"] if lead else "",
                    "place": lead["place"] if lead else None,
                    "starts_in_ms": lead["starts_in_ms"] if lead else None,
                    "count": len(mine_list)}
    return out


def idle_view(now_ms: int) -> dict:
    return {"state": "idle", "server_ms": now_ms, "poll_ms": POLL_MS * 5,
            "detail": sentence("idle"), "house_rules": list(HOUSE_RULES), "privacy": PRIVACY}


# ── the book, with its store ────────────────────────────────────────────────

def _default_state() -> dict:
    from services.jukebox import night
    return night.runner.guest_state(count=NEXT_SHOWN * 3)


def _default_token_ok(token: Any) -> bool:
    from services.jukebox import guest_link
    return guest_link.token_matches(token, store.load_guest_link()[1])


async def _default_to_thread(fn: Callable, *args: Any) -> Any:
    return await asyncio.to_thread(fn, *args)


@dataclass
class GuestDeps:
    state: Callable[[], dict] = _default_state
    token_ok: Callable[[Any], bool] = _default_token_ok
    now_ms: Callable[[], int] = lambda: int(time.time() * 1000)
    to_thread: Callable[..., Awaitable[Any]] = _default_to_thread
    rng: random.Random = field(default_factory=random.Random)


class Guests:
    """Tonight's book of phones and votes. Held in memory, written through
    (off the event loop) on every change; every method answers
    (http status, body)."""

    def __init__(self, deps: Optional[GuestDeps] = None) -> None:
        self.deps = deps or GuestDeps()
        self._book: Optional[GuestBook] = None
        self._lock: Optional[asyncio.Lock] = None

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _book_for(self, night_id: str) -> GuestBook:
        if self._book is None:
            self._book = store.load_guests()
        if self._book.night_id != night_id:
            self._book = GuestBook(night_id=night_id)
        return self._book

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
            return (200, idle_view(self.deps.now_ms())), None, None
        book = self._book_for(gs["night_id"])
        if not valid_phone_id(phone) or phone not in book.phones:
            return refusal("needs_link", 403), None, None
        return None, gs, book

    def _ok(self, book: GuestBook, pid: str, gs: dict, **extra: Any) -> tuple[int, dict]:
        return 200, {"status": "ok", **extra,
                     "view": build_view(book, pid, gs, self.deps.now_ms())}

    # ── the calls the guest app forwards ────────────────────────────────────

    async def hello(self, phone: Any, token: Any) -> tuple[int, dict]:
        """A phone opens the page. A phone already in tonight's book needs
        nothing more; any other needs tonight's token, and gets a code (its
        own, if it brought a well-formed one) and a fun name."""
        async with self._get_lock():
            gs = self._running()
            if gs is None:
                return 200, idle_view(self.deps.now_ms())
            book = self._book_for(gs["night_id"])
            if valid_phone_id(phone) and phone in book.phones:
                return self._ok(book, phone, gs, phone=phone)
            if not self.deps.token_ok(token):
                return refusal("needs_link", 403)
            if len(book.phones) >= PHONES_MAX:
                return refusal("party_full", 403)
            pid = phone if valid_phone_id(phone) else new_phone_id()
            book.phones[pid] = GuestPhone(id=pid, name=fun_name(self.deps.rng, self._taken(book)),
                                          created_ms=self.deps.now_ms())
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
            if name is not None and name != me.name:
                clean, why = clean_name(name)
                if clean is None:
                    return refusal(why, 422)
                if clean.lower() in self._taken(book, phone):
                    return refusal("name_taken", 422)
                me.name = clean
            if not me.joined:
                me.joined, me.joined_ms = True, self.deps.now_ms()
            await self._save()
            return self._ok(book, phone, gs)

    async def rename(self, phone: Any, name: Any = None, shuffle: bool = False) -> tuple[int, dict]:
        """A new name: typed, or a fresh fun one (shuffle). Free on the
        welcome screen; RENAMES_PER_NIGHT after joining."""
        async with self._get_lock():
            gate, gs, book = self._gate(phone)
            if gate:
                return gate
            me = book.phones[phone]
            if me.joined and me.renames >= RENAMES_PER_NIGHT:
                return refusal("renames_used", 422)
            if shuffle:
                new = fun_name(self.deps.rng, self._taken(book, phone) | {me.name.lower()})
            else:
                new, why = clean_name(name)
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
            if not book.phones[phone].joined:
                return refusal("not_joined", 409)
            view = build_view(book, phone, gs, self.deps.now_ms())
            now = view["now"]
            if now is None:
                return refusal("nothing_playing", 409)
            if not now["can_vote"]:
                code = ("own_song" if now["mine"] else
                        "skipping" if getattr(gs["now"], "kind", "") == "skipping" else
                        "not_votable")
                return refusal(code, 409)
            key = play_key(gs["now"])
            plays = book.votes.setdefault(key, {})
            if values[vote]:
                plays[phone] = values[vote]
            else:
                plays.pop(phone, None)
            while len(book.votes) > PLAYS_KEPT:
                book.votes.pop(next(iter(book.votes)))
            await self._save()
            return self._ok(book, phone, gs)

    async def view(self, phone: Any) -> tuple[int, dict]:
        gate, gs, book = self._gate(phone)
        if gate:
            return gate
        return 200, {"status": "ok", "view": build_view(book, phone, gs, self.deps.now_ms())}

    # ── the master's read ───────────────────────────────────────────────────

    def summary(self, night_id: Optional[str]) -> dict:
        """How many phones joined tonight (the master's Live tab)."""
        if not night_id:
            return {"phones": 0, "joined": 0}
        if self._book is None:
            self._book = store.load_guests()
        book = self._book if self._book.night_id == night_id else GuestBook()
        return {"phones": len(book.phones),
                "joined": sum(1 for p in book.phones.values() if p.joined)}


book = Guests()
