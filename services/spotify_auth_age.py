"""
SpotFX — how old SpotFX's Spotify sign-in is, and a warning before it runs
out (data/jukebox-plan/report.md §9, PR 1.2; the study's risk 3).

Spotify's refresh tokens now die SIX MONTHS AFTER AUTHORIZATION, and nothing
recorded when his was issued: when it lapses, SpotFX's polling, Absorb and
the Jukebox all stop at once, with no warning. This module is the record and
the warning, nothing else.

THE RECORD (storage/spotify_auth.json) is written at the one place SpotFX is
ever authorized — the OAuth callback (routers/auth.py) — with the moment and a
FINGERPRINT of the refresh token (a short SHA-256 prefix; the token itself is
never stored or logged). The clock runs from that sign-in and is never reset
by an ordinary refresh: Spotify may hand back a new refresh token on a
refresh, but whether that restarts its six months is not documented, so a
rotation is NOTED and the warning keeps counting from the sign-in — it can
only ever warn early, never late. The lifetime is counted as 180 days (six
months, rounded down) for the same reason.

A sign-in that happened before this record existed has NO KNOWN DATE, and
that is reported as such ("unknown"), never guessed: the token cache's mtime
changes on every hourly access-token refresh, so it says nothing about the
sign-in. Signing in again (the plan's "re-authorize the week before the
party") starts a known clock.

A DEAD TOKEN is recorded too: when the poll's refresh is refused with
`invalid_grant` (expired or revoked), `note_refresh_failure` stamps it, and
the next successful poll clears it — a refusal is the one thing that proves
the sign-in is gone, so it outranks any date.

`status()` answers one of six states, each with the sentence a person reads:
  no_token        SpotFX isn't signed in to Spotify at all
  unknown         signed in, sign-in date not recorded
  ok              more than WARN_DAYS left — no warning
  soon            within WARN_DAYS of the end
  expired         past the end by the record's own count
  refresh_failed  Spotify refused the sign-in (outranks every date)
Paths are module attributes so a test repoints them (tests/conftest.py's
`_isolated_spotify_auth_age`).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from config import PROFILES_DIR

logger = logging.getLogger(__name__)

RECORD_FILE = PROFILES_DIR.parent / "spotify_auth.json"
TOKEN_CACHE = PROFILES_DIR.parent / ".spotify_token_cache"   # api/spotify_client.py's cache_path

LIFETIME_DAYS = 180          # Spotify's "6 months", rounded DOWN so the warning is never late
WARN_DAYS = 14               # the plan: warn 14 days before the end
DAY_MS = 86_400_000
LOG_EVERY_S = 6 * 3600       # how often the supervised task re-logs a standing warning

_failure_noted = False       # cheap in-memory flag: a success only touches the disk after a failure


def _now_ms() -> int:
    return int(time.time() * 1000)


def _read_json(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception as exc:
        logger.warning("Spotify sign-in: unreadable %s (%s)", path.name, type(exc).__name__)
        return None
    return data if isinstance(data, dict) else None


def _write_record(data: dict) -> None:
    path = RECORD_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def fingerprint(refresh_token: str) -> str:
    return hashlib.sha256(refresh_token.encode("utf-8")).hexdigest()[:16]


def _cache_fingerprint() -> Optional[str]:
    """The fingerprint of the refresh token in spotipy's cache, or None when
    there is no usable cache."""
    cache = _read_json(TOKEN_CACHE)
    token = (cache or {}).get("refresh_token")
    return fingerprint(token) if isinstance(token, str) and token else None


def load_record() -> dict:
    return _read_json(RECORD_FILE) or {}


def _date(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone().strftime("%Y-%m-%d")


# ── writers ──────────────────────────────────────────────────────────────────

def record_authorization(now_ms: Optional[int] = None) -> dict:
    """Called by the OAuth callback after spotipy has cached the new token:
    a new six-month clock starts now. A failure to write is logged, never
    raised — a successful sign-in must not be turned into an error page."""
    global _failure_noted
    now = _now_ms() if now_ms is None else int(now_ms)
    data = {"authorized_at_ms": now, "refresh_fingerprint": _cache_fingerprint() or "",
            "source": "callback"}
    try:
        _write_record(data)
        _failure_noted = False
        logger.info("Spotify sign-in recorded: %s; it runs out by %s", _date(now),
                    _date(now + LIFETIME_DAYS * DAY_MS))
    except Exception as exc:
        logger.warning("Spotify sign-in: could not record it (%s)", type(exc).__name__)
    return data


def is_dead_token_error(exc: BaseException) -> bool:
    """`invalid_grant` on a refresh: the refresh token is expired or revoked."""
    return str(getattr(exc, "error", "") or "") == "invalid_grant" or (
        type(exc).__name__ == "SpotifyOauthError" and "invalid_grant" in str(exc))


def note_refresh_failure(exc: BaseException, now_ms: Optional[int] = None) -> bool:
    """Called from the poll's failure path. Records a DEAD-token refusal
    (once — the first time it is seen) and ignores every other failure (a
    network blip says nothing about the sign-in). Never raises."""
    global _failure_noted
    if not is_dead_token_error(exc):
        return False
    if _failure_noted:
        return True
    try:
        data = load_record()
        if not data.get("refresh_failed_at_ms"):
            data["refresh_failed_at_ms"] = _now_ms() if now_ms is None else int(now_ms)
            data["refresh_failed_detail"] = str(getattr(exc, "error_description", "") or "")[:120]
            _write_record(data)
            logger.critical("Spotify refused SpotFX's sign-in (invalid_grant: %s) — sign in "
                            "again at /api/spotify/login", data["refresh_failed_detail"] or "no detail")
        _failure_noted = True
    except Exception as exc2:
        logger.warning("Spotify sign-in: could not record the refusal (%s)", type(exc2).__name__)
    return True


def note_refresh_ok() -> None:
    """Called on every successful poll. Free unless a refusal was noted in
    this process: then the refusal is cleared (the token works again)."""
    global _failure_noted
    if not _failure_noted:
        return
    try:
        data = load_record()
        if data.pop("refresh_failed_at_ms", None) is not None:
            data.pop("refresh_failed_detail", None)
            _write_record(data)
        _failure_noted = False
    except Exception as exc:
        logger.warning("Spotify sign-in: could not clear the refusal (%s)", type(exc).__name__)


# ── the read ─────────────────────────────────────────────────────────────────

SENTENCES = {
    "no_token": "SpotFX isn't signed in to Spotify — sign in at /api/spotify/login.",
    "unknown": ("When SpotFX last signed in to Spotify isn't recorded, so its 6-month "
                "expiry can't be predicted — sign in again before a party to start a "
                "known clock."),
    "soon": "SpotFX's Spotify sign-in runs out by {date} ({days} left) — sign in again before then.",
    "expired": "SpotFX's Spotify sign-in ran out on {date} — sign in again.",
    "refresh_failed": "Spotify refused SpotFX's sign-in on {date} — sign in again.",
}


def _days(n: int) -> str:
    return "1 day" if n == 1 else f"{n} days"


def status(now_ms: Optional[int] = None) -> dict:
    """The sign-in's age and the warning line, if one is due. Reads two small
    files; never calls Spotify."""
    now = _now_ms() if now_ms is None else int(now_ms)
    cache_fp = _cache_fingerprint()
    rec = load_record()
    out: dict[str, Any] = {"state": "", "warning": None, "authorized_at_ms": None,
                           "expires_at_ms": None, "warn_from_ms": None, "days_left": None,
                           "rotated": False, "login_url": "/api/spotify/login",
                           "lifetime_days": LIFETIME_DAYS, "warn_days": WARN_DAYS}
    failed = rec.get("refresh_failed_at_ms")
    if failed:
        out.update(state="refresh_failed",
                   warning=SENTENCES["refresh_failed"].format(date=_date(int(failed))))
        return out
    if cache_fp is None:
        out.update(state="no_token", warning=SENTENCES["no_token"])
        return out
    authorized = rec.get("authorized_at_ms")
    if not isinstance(authorized, (int, float)) or authorized <= 0:
        out.update(state="unknown", warning=SENTENCES["unknown"])
        return out
    authorized = int(authorized)
    expires = authorized + LIFETIME_DAYS * DAY_MS
    warn_from = expires - WARN_DAYS * DAY_MS
    days_left = max(0, -(-(expires - now) // DAY_MS))          # ceiling, never negative
    out.update(authorized_at_ms=authorized, expires_at_ms=expires, warn_from_ms=warn_from,
               days_left=days_left,
               rotated=bool(rec.get("refresh_fingerprint")) and rec.get("refresh_fingerprint") != cache_fp)
    if now >= expires:
        out.update(state="expired", warning=SENTENCES["expired"].format(date=_date(expires)))
    elif now >= warn_from:
        out.update(state="soon", warning=SENTENCES["soon"].format(date=_date(expires),
                                                                  days=_days(days_left)))
    else:
        out["state"] = "ok"
    return out


async def run_supervised(interval_s: float = LOG_EVERY_S) -> None:
    """Re-log a standing warning every few hours, so it reaches the journal
    and not only a page someone has to open — "unknown" only once a process,
    since it stands until he signs in again. Reads files only."""
    logged_unknown = False
    while True:
        try:
            s = status()
            if s["state"] == "unknown":
                if not logged_unknown:
                    logger.warning("Spotify sign-in: %s", s["warning"])
                    logged_unknown = True
            elif s["warning"]:
                log = logger.critical if s["state"] in ("expired", "refresh_failed") else logger.warning
                log("Spotify sign-in: %s", s["warning"])
        except Exception:                                         # noqa: BLE001
            logger.exception("Spotify sign-in: status check failed")
        await asyncio.sleep(interval_s)
