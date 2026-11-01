"""THE SECOND SPOTIFY ACCOUNT'S LOCK — the barrier between the system and
somebody else's music (SpotFX-authored, shared library, stdlib only).

The Admiral, 2026-11-01, verbatim: "I want a toggle button on settings page
... that must be "enabled" in order for the system to use the second account
in any capacity other than reading info. That means no music can be played
from that account by spectra or spotfx when it is disabled. the idea is to
have a solid barrier so that the second user doesn't get their music taken
from them by the system." His answers: the toggle lives on SPECTRA's
Settings page and SpotFX obeys it; turned off mid-play, the system stops
only the playback it started, then lets go, and never touches the second
user's own playback; it ships OFF.

The second account is Spotify account B — the one the hidden player
"Serenity Capture" plays under (api/spotify_capture.py, capture_lane/). A
Spotify account plays one stream at a time, so a play the system starts on
it is a play the second user stops hearing.

WHY IT LIVES IN fx/: SPECTRA writes it (its Settings page, spectra/api/
second_account.py) and SpotFX — the main process AND the capture lane's own
process — obeys it, and fx/ is the one library all of them may import
(spectra/ may not import api/ or services/; SpotFX may not import spectra/).
fx/light_ownership.py and fx/hue_scope.py are the same shape.

THE RECORD (storage/spectra/second_account.json, following
SPECTRA_STORAGE_DIR like SPECTRA's own stores, so an isolated SPECTRA can
never unlock the real account): `{"enabled": bool, "changed_at_ms",
"changed_by", "history": [...]}`. THREE STATES, and only one lets a write
through:

  on          the record says enabled: true
  off         the record says enabled: false — or there is no record at all
              (the shipped state: nothing touches the account until he turns
              it on)
  unreadable  the file is there but can't be read or doesn't say true/false
              — treated exactly like off, and said so

`check(what)` is the ONE question every account-B write asks, fresh from
disk every time (no cached "on" can outlive his press), and it refuses —
logged at WARNING, raised as SecondAccountLocked — unless the record reads
on. The account-B client (api/spotify_capture.SecondAccountSpotify) asks it
at the HTTP-verb level, for every request that isn't a read, so a write
path added later cannot get round it by calling a different method.

WHAT THE SYSTEM STARTED (storage/spectra/second_account_started.json): the
one record of a play the system itself started on account B — written by
the account-B client BEFORE its play request leaves, cleared once it lets
go. Letting go is the one write the lock does not stop, because stopping
the system's own song is what turning the lock off asks for — but it is
allowed only after `is_system_playback` has confirmed, from a fresh read,
that what is playing now IS that song on that device. Anything else is the
second user's own playback and is left exactly as it is.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _storage_dir() -> Path:
    return Path(os.getenv("SPECTRA_STORAGE_DIR") or _REPO_ROOT / "storage" / "spectra")


LOCK_FILE = _storage_dir() / "second_account.json"
STARTED_FILE = _storage_dir() / "second_account_started.json"

ON, OFF, UNREADABLE = "on", "off", "unreadable"
HISTORY_KEPT = 20

SENTENCES = {
    ON: "On: the system may play music on the second Spotify account.",
    OFF: "Off: the system only reads the second Spotify account and never plays, "
         "pauses, queues or changes anything on it.",
    UNREADABLE: "The setting can't be read, so the system treats the second Spotify "
                "account as locked and never plays anything on it.",
}

_write_lock = threading.Lock()


class SecondAccountLocked(RuntimeError):
    """A write to the second account that the lock refused.

    Deliberately NOT a ValueError: spotipy's request path swallows a
    ValueError (it reads it as an unparseable answer and returns None), which
    would turn a refusal into a silent "success"."""

    def __init__(self, what: str, state: str) -> None:
        super().__init__(f"the second Spotify account is locked ({state}); refused: {what}")
        self.what = what
        self.state = state


@dataclass(frozen=True)
class Lock:
    state: str                         # ON | OFF | UNREADABLE
    changed_at_ms: Optional[int] = None
    changed_by: Optional[str] = None
    detail: str = ""

    @property
    def enabled(self) -> bool:
        return self.state == ON

    @property
    def sentence(self) -> str:
        return SENTENCES[self.state]


def _read_raw() -> tuple[Optional[dict], str]:
    """(the record, "") — or (None, why it isn't usable)."""
    try:
        raw = LOCK_FILE.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, "missing"
    except OSError as exc:
        return None, f"can't be opened ({type(exc).__name__})"
    try:
        data = json.loads(raw)
    except ValueError:
        return None, "isn't valid JSON"
    if not isinstance(data, dict) or not isinstance(data.get("enabled"), bool):
        return None, "doesn't say on or off"
    return data, ""


def read() -> Lock:
    """The lock as it is on disk RIGHT NOW. Never cached."""
    data, why = _read_raw()
    if data is None:
        if why == "missing":
            return Lock(OFF, detail="never turned on")
        return Lock(UNREADABLE, detail=f"{LOCK_FILE.name} {why}")
    at = data.get("changed_at_ms")
    by = data.get("changed_by")
    return Lock(ON if data["enabled"] else OFF,
                changed_at_ms=int(at) if isinstance(at, (int, float)) else None,
                changed_by=str(by) if by is not None else None)


def write_allowed() -> bool:
    """True only when the record reads ON. Off and unreadable are both no."""
    return read().state == ON


def check(what: str) -> None:
    """THE question every account-B write asks. Raises SecondAccountLocked
    (and logs it) unless the lock reads ON right now."""
    lk = read()
    if lk.state != ON:
        logger.warning("Second Spotify account is %s%s: refused %s", lk.state,
                       f" ({lk.detail})" if lk.detail else "", what)
        raise SecondAccountLocked(what, lk.state)


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(data, indent=2))
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def set_enabled(enabled: bool, *, by: str, now_ms: Optional[int] = None) -> Lock:
    """Turn the lock on or off. The ONE writer — SPECTRA's Settings page
    reaches it through spectra/api/second_account.py. Atomic (tmp + fsync +
    replace), so a reader never sees half a record. An unreadable record is
    replaced, and its replacement says so in the history."""
    if not isinstance(enabled, bool):
        raise TypeError("enabled must be True or False")
    at = int(time.time() * 1000) if now_ms is None else int(now_ms)
    with _write_lock:
        old, why = _read_raw()
        history = list((old or {}).get("history") or []) if old else []
        entry = {"enabled": enabled, "at_ms": at, "by": str(by)}
        if old is None and why != "missing":
            entry["replaced_unreadable"] = why
        history.append(entry)
        record = {"enabled": enabled, "changed_at_ms": at, "changed_by": str(by),
                  "history": history[-HISTORY_KEPT:]}
        _atomic_write(LOCK_FILE, record)
    logger.warning("Second Spotify account turned %s by %s", "ON" if enabled else "OFF", by)
    return read()


def history() -> list[dict]:
    data, _ = _read_raw()
    return list((data or {}).get("history") or [])


# ── what the system started ─────────────────────────────────────────────────

def note_started(device_id: Optional[str], uris: list[str], *, now_ms: Optional[int] = None) -> None:
    """Record a play the system is about to start on account B."""
    at = int(time.time() * 1000) if now_ms is None else int(now_ms)
    _atomic_write(STARTED_FILE, {"device_id": device_id, "uris": [str(u) for u in uris],
                                 "started_at_ms": at})


def started() -> Optional[dict]:
    """The play the system started and hasn't let go of, or None."""
    try:
        data = json.loads(STARTED_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("device_id"):
        return None
    data["uris"] = [str(u) for u in (data.get("uris") or [])]
    return data


def clear_started() -> None:
    try:
        STARTED_FILE.unlink()
    except FileNotFoundError:
        pass


def is_system_playback(record: Optional[dict], playback: Optional[dict], *,
                       end_of_song: bool = False) -> tuple[bool, str]:
    """Is what account B is playing RIGHT NOW the play the system started?
    (True, why) only then; every other answer leaves the playback alone.

      nothing_started   the system has no play of its own on record
      not_playing       nothing is playing, so there is nothing to stop
      other_device      it is playing somewhere else — the second user's own
      system_song       the system's own song, on the system's own device
      continuation      a different song on the system's device straight
                        after the system's own song ended (Spotify's autoplay
                        carrying on from the system's play) — only when the
                        caller says the song just ended
      other_song        a different song on the system's device — somebody
                        chose it; the second user's own
    """
    if not record or not record.get("device_id"):
        return False, "nothing_started"
    if not playback or not playback.get("is_playing"):
        return False, "not_playing"
    device = ((playback.get("device") or {}).get("id"))
    if device != record["device_id"]:
        return False, "other_device"
    uri = ((playback.get("item") or {}).get("uri"))
    if uri and uri in (record.get("uris") or []):
        return True, "system_song"
    if end_of_song:
        return True, "continuation"
    return False, "other_song"


def status() -> dict:
    """What SPECTRA's API serves (and a future Home Assistant would read)."""
    lk = read()
    return {"enabled": lk.enabled, "state": lk.state, "sentence": lk.sentence,
            "detail": lk.detail, "changed_at_ms": lk.changed_at_ms,
            "changed_by": lk.changed_by, "history": history()[-5:],
            "system_started": started()}
