"""
SpotFX — Absorb Music data model.

Absorb Music plays a linked Spotify playlist on Serenity, unattended, so that
every song's audio shape gets captured (data/absorb-music-plan/report.md,
phase 1 — the runner). Three stores, each with one job:

  AbsorbConfig  storage/absorb.json         HIS settings. Only an edit writes
                                            it; a run never does.
  AbsorbRun     storage/absorb_run.json     the current (or last) run plus a
                                            bounded history of earlier ones.
                                            Churns on every song.
  AbsorbLedger  storage/absorb_ledger.json  per song, ACROSS runs: the filing
                                            steps already done (so a re-run
                                            is a no-op), the lifetime attempt
                                            count, and whether the song is
                                            parked. The report names two
                                            stores; this third one exists
                                            because a re-run's idempotence
                                            and a durable lifetime count both
                                            outlive any one run, and the run
                                            file is bounded.
  AbsorbSchedule storage/absorb_schedule.json  the scheduler's own memory
                                            (phase 3, services/absorb_
                                            schedule.py): which window
                                            occurrences it has already acted
                                            on — so a restart never opens one
                                            twice — and what happened when it
                                            did. His windows themselves live
                                            in AbsorbConfig.

Every model is `extra="ignore"` and every field is defaulted, so an older or
newer file always loads.
"""
from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

ORDERS = ("fresh_first", "playlist", "worst_head_first")
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

# What a song is to a window: already captured (filed without playing), no
# usable shape yet (the passive capture path takes it), or a complete shape
# that fails the bar (only a FORCED capture replaces it).
SongKind = Literal["skip", "fresh", "recapture"]
# What absorb is doing with the song it is playing. A warm-up song is
# already captured and is played only so the next song starts at a track
# boundary (report §8.5).
PlayMode = Literal["fresh", "recapture", "warmup"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class AbsorbWindow(_Model):
    """A scheduled window in HOUSE time (America/New_York; services/
    absorb_schedule.py evaluates these). `days` name the day the window
    STARTS: Mon 21:30-00:30 runs Monday evening into Tuesday. An `end`
    before `start` crosses midnight; an `end` equal to `start` is refused by
    the edit path (`absorb.apply_config_patch`) and never opens."""
    days: list[str] = Field(default_factory=lambda: list(DAYS))
    start: str = "21:30"
    end: str = "00:30"

    @field_validator("days")
    @classmethod
    def _days(cls, v: list[str]) -> list[str]:
        out = []
        for d in v:
            d = str(d).strip().lower()[:3]
            if d not in DAYS:
                raise ValueError(f"unknown day {d!r} (use {', '.join(DAYS)})")
            if d not in out:
                out.append(d)
        return out

    @field_validator("start", "end")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        if not _HHMM.match(str(v)):
            raise ValueError(f"{v!r} is not HH:MM")
        return str(v)


class AbsorbConfig(_Model):
    """His settings — report §5, field for field."""
    # The SCHEDULE's switch. Ships OFF, and `windows` ships EMPTY: a window
    # opens on its own only when both are set. His press works either way.
    enabled: bool = False
    source_playlist_uri: str = ""            # the playlist he links
    captured_playlist_name: str = "Recently Captured"
    # HIS TAG — off by default. Under his Q1 answer it means "re-capture even
    # the songs that already pass the bar" (report §8.6).
    force_recapture: bool = False
    head_max_ms: int = Field(1000, ge=0, le=60_000)   # Q1: the head bar (§8.1)
    order: Literal["fresh_first", "playlist", "worst_head_first"] = "fresh_first"
    warm_up: bool = True                     # open each window with a captured song (§8.5)
    windows: list[AbsorbWindow] = Field(default_factory=list)  # house time; ships EMPTY
    max_attempts: int = Field(3, ge=1, le=10)
    play_window_size: int = Field(10, ge=1, le=50)
    overrun_grace_min: int = Field(5, ge=0, le=60)
    recently_captured_max: int = Field(200, ge=1, le=10_000)
    recently_captured_includes_skipped: bool = True   # Q2: yes, tagged
    # Q4 — yield and resume (phase 2)
    resume_after_quiet_min: int = Field(20, ge=1, le=240)
    min_remaining_min: int = Field(20, ge=0, le=240)
    max_resumes_per_window: int = Field(3, ge=0, le=20)
    # Q5 — the Order 27 exception and the proof it rides on (phase 2)
    run_while_sleeping: bool = True
    silence_recheck_s: int = Field(60, ge=10, le=600)


class SongEntry(_Model):
    """One line in a run's captured / failed / parked / skipped lists."""
    uri: str
    title: str = ""
    at_ms: int = 0
    attempt: int = 0
    mode: str = ""
    reason: str = ""          # a short tag: gap, head_missed, too_short, ...
    detail: str = ""
    head_ms: Optional[int] = None


class NowPlaying(_Model):
    uri: str
    title: str = ""
    started_ms: int = 0
    attempt: int = 0
    mode: PlayMode = "fresh"


class RealignEntry(_Model):
    """A committed re-capture's timebase realign (report §8.3 item 4): when
    `triggers` > 0 his authored marks on that song were moved."""
    uri: str
    title: str = ""
    status: str = ""
    shift_ms: int = 0
    r: float = 0.0
    triggers: int = 0
    at_ms: int = 0


class HeadTally(_Model):
    attempted: int = 0
    with_head: int = 0


class HeadRate(_Model):
    """§8.4: of the captures that COMMITTED, how many landed their head.
    `attempted`/`with_head` count every committed capture; `by_mode` splits
    them so the re-capture fraction — the number that says 42 evenings or
    54 — is read directly."""
    attempted: int = 0
    with_head: int = 0
    by_mode: dict[str, HeadTally] = Field(default_factory=dict)


class AbsorbCounts(_Model):
    captured: int = 0
    failed: int = 0
    requeued: int = 0
    skipped: int = 0
    parked: int = 0
    head_missed: int = 0


class AbsorbRun(_Model):
    """One window — report §5's AbsorbRun, plus the few fields the runner
    needs to resume its own bookkeeping (named below)."""
    id: str = ""
    state: Literal["running", "paused", "ended", "refused"] = "running"
    started_ms: int = 0
    ended_ms: int = 0
    end_reason: str = ""                     # a short code
    end_detail: str = ""                     # the sentence a person reads
    # {start, end} in epoch ms; `end` is None for a press. A scheduled window
    # also carries `scheduled_start` (the occurrence it opened for) and
    # `label` ("Mon 21:30–00:30").
    window: dict = Field(default_factory=dict)
    started_by: Literal["schedule", "press", "sonic", "ha"] = "press"
    pre_window: dict = Field(default_factory=dict)      # the restore contract (phase 2)
    queue: list[str] = Field(default_factory=list)
    now_playing: Optional[NowPlaying] = None
    captured: list[SongEntry] = Field(default_factory=list)
    failed: list[SongEntry] = Field(default_factory=list)
    parked: list[SongEntry] = Field(default_factory=list)
    skipped: list[SongEntry] = Field(default_factory=list)
    counts: AbsorbCounts = Field(default_factory=AbsorbCounts)
    head_rate: HeadRate = Field(default_factory=HeadRate)
    realigned: list[RealignEntry] = Field(default_factory=list)
    sleeping_at_open: Optional[bool] = None
    silence_checks: list[dict] = Field(default_factory=list)
    yields: list[dict] = Field(default_factory=list)
    resumes: int = 0
    log: list[str] = Field(default_factory=list)
    # ── phase 3: scheduling ───────────────────────────────────────────────
    # When the window first opened (house silenced, queue built); 0 while a
    # scheduled window that found him listening is still waiting.
    opened_ms: int = 0
    # Why a paused window is paused — a yield's code, or "music_playing" for
    # a scheduled window waiting from its start — and the sentence. "" while
    # running.
    wait_reason: str = ""
    wait_detail: str = ""
    # ── phase 2: the house guard (services/absorb_silence.py) ─────────────
    # The silence is proven and the house volume is absorb's (until restored).
    silent: bool = False
    # SPECTRA's light stand-down: set once the silence is proven, cleared the
    # moment the house is given back (yield or close). Rides the websocket
    # `absorb` key — spectra/services/absorb_hold.py reads it.
    lights_held: bool = False
    # The last restore: {at_ms, ok, detail, why}.
    restore: dict = Field(default_factory=dict)
    # Why the house may still be silent after the window (a restore that did
    # not read back, or absorb's song still playing) — "" when it is back.
    restore_pending: str = ""
    # ── beyond §5, the runner's own bookkeeping ───────────────────────────
    source_playlist_uri: str = ""
    source_playlist_name: str = ""
    # per-run attempts, counted when an attempt RESOLVES (a success or a
    # failure) — an interrupted or manually skipped play is not an attempt.
    attempts: dict[str, int] = Field(default_factory=dict)
    titles: dict[str, str] = Field(default_factory=dict)
    warm_up_uri: str = ""
    # "opening" | "warming_up" | "capturing" | "draining" — what a running
    # window is doing right now.
    stage: str = ""


class Filing(_Model):
    """Moving one song out of the source playlist and into Recently Captured.
    Two steps, recorded separately so a re-run only does what is missing."""
    kind: Literal["captured", "skipped"] = "captured"
    started_ms: int = 0
    rc_added: bool = False
    source_removed: bool = False
    done_ms: int = 0


class LedgerEntry(_Model):
    uri: str
    title: str = ""
    lifetime_attempts: int = 0
    last_failure: str = ""
    last_attempt_ms: int = 0
    filing: Optional[Filing] = None
    parked: bool = False
    parked_reason: str = ""
    parked_ms: int = 0


class AbsorbLedger(_Model):
    entries: dict[str, LedgerEntry] = Field(default_factory=dict)
    captured_playlist_id: str = ""
    captured_playlist_name: str = ""


class ScheduleOutcome(_Model):
    """What the scheduler did with one occurrence of one window, so "did
    last night run, and if not, why not?" is a read, never a silence.

    outcome  opened | waiting (his music was playing; it opens after his
             quiet clock) | refused | ended (opened and ended at once, e.g.
             nothing left to capture) | joined (an overlapping scheduled
             window was already open; its end now follows this one) |
             already_running (his own press was running) | too_late (too
             little of the window left to open) | interrupted (SpotFX
             restarted while it was open; not reopened)"""
    occurrence_start_ms: int = 0
    occurrence_end_ms: int = 0
    label: str = ""
    at_ms: int = 0
    outcome: str = ""
    reason: str = ""
    detail: str = ""
    run_id: str = ""


class AbsorbSchedule(_Model):
    # Occurrence START times (epoch ms) already acted on. Written BEFORE the
    # window is opened, so a crash mid-open can never open it a second time.
    fired: list[int] = Field(default_factory=list)
    outcomes: list[ScheduleOutcome] = Field(default_factory=list)   # newest first
