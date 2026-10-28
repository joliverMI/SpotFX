"""
SpotFX — the Jukebox's SAVED SHOWS (data/jukebox-plan/report.md §4: "One
page in the master view, filled in before a party (a 'show' is a saved set
of these)", and the Show card's "Name"). A show is everything §4 lists — the
show settings (services/jukebox/show.py's ShowConfig: the guests' rules, the
economy, approval, the board, the mode), the program settings (ProgramConfig:
the set playlist, the slots, the run-out, play next jumping the set) and
whether the guest link is on — saved under its name and loaded back whole.

SAVING copies what is in force now; it changes nothing that plays. A name is
1-60 characters and unique without regard to case: saving under a name that
exists REPLACES that show (the caller says so before it does). LOADING goes
through the same steps a page edit takes (routers/jukebox_router.py): the
program through the engine's own `apply_config` (so a running night refuses a
different set playlist, by name, and nothing is changed), the show through
its own store and the jail conversion a mode switch needs, the guest link
through its controller. Loading never starts or stops a night.

His file is never written over when it can't be read (services/jukebox/
store.py's `load_shows` raises), and at most SHOWS_MAX shows are kept.
"""
from __future__ import annotations

import threading
from typing import Optional

from models.jukebox import ProgramConfig, SavedShow, ShowConfig
from services.jukebox import store

SHOWS_MAX = 30

_lock = threading.Lock()


class ShowsError(ValueError):
    def __init__(self, code: str, sentence: str) -> None:
        self.code = code
        self.sentence = sentence
        super().__init__(sentence)


def clean_name(raw: object) -> str:
    name = " ".join(str(raw or "").split())
    if not 1 <= len(name) <= 60:
        raise ShowsError("bad_name", "A show's name is 1 to 60 characters.")
    return name


def _key(shows: dict, name: str) -> Optional[str]:
    """The stored key for `name`, ignoring case."""
    want = name.casefold()
    return next((k for k in shows if k.casefold() == want), None)


def listing() -> list[dict]:
    """The saved shows, newest first, each in a line: its name, when it was
    saved, its mode, preset and set playlist."""
    shows = store.load_shows().shows
    rows = [{"name": k, "saved_ms": v.saved_ms, "play_mode": v.show.play_mode,
             "preset": v.show.preset, "playlist": v.program.playlist or None,
             "guest_link": v.guest_link}
            for k, v in shows.items()]
    return sorted(rows, key=lambda r: -r["saved_ms"])


def save(name: object, show: ShowConfig, program: ProgramConfig, guest_link: bool,
         now_ms: int) -> tuple[str, bool]:
    """Save what is in force now under `name` (the show's own name becomes
    it). Returns (the name, whether an older show of that name was
    replaced)."""
    name = clean_name(name)
    with _lock:
        saved = store.load_shows()
        old = _key(saved.shows, name)
        if old is None and len(saved.shows) >= SHOWS_MAX:
            raise ShowsError("too_many", f"That's {SHOWS_MAX} saved shows — delete one first.")
        if old is not None:
            del saved.shows[old]
        saved.shows[name] = SavedShow(saved_ms=int(now_ms), show=show.model_copy(update={"name": name}),
                                      program=program, guest_link=bool(guest_link))
        store.save_shows(saved)
        return name, old is not None


def get(name: object) -> tuple[str, SavedShow]:
    name = clean_name(name)
    shows = store.load_shows().shows
    key = _key(shows, name)
    if key is None:
        raise ShowsError("no_show", f"There's no saved show called “{name}”.")
    return key, shows[key]


def delete(name: object) -> str:
    name = clean_name(name)
    with _lock:
        saved = store.load_shows()
        key = _key(saved.shows, name)
        if key is None:
            raise ShowsError("no_show", f"There's no saved show called “{name}”.")
        del saved.shows[key]
        store.save_shows(saved)
        return key
