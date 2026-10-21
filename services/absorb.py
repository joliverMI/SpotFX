"""
SpotFX — Absorb Music: the runner (data/absorb-music-plan/report.md, phase 1).

Plays a linked Spotify playlist on Serenity, song after song, so that the
capture path (services/audio_shape_service.py) records every song's audio
shape. His six asks, and where each lives:

  1. silent playback        PHASE 2. `HouseGuard` is the seam. The default
                            (`UnbuiltHouseGuard`) REFUSES every window, so
                            until the silence and the light stand-down exist
                            no press can make this play music out loud.
  2. requeue / skip ahead   here: the mid-song detectors condemn a doomed
                            capture (capture_watch.py on the frames, the
                            governor and the device on the poll), the runner
                            plays the next song at once and puts the failed
                            one back AFTER the next song. A committed capture
                            is judged AGAIN by the bar (§8.4) — committed but
                            headless is a failure, `head_missed`.
  3+5. the two playlists    here: a captured song leaves the source playlist
                            and goes on top of "Recently Captured" in one
                            filing, recorded step by step in the ledger.
  4. scheduling             PHASE 3 (AbsorbConfig.windows is stored, unread).
  6. skip the captured      here: the skip pass files every song that already
                            passes the bar without playing it, unless his
                            force-recapture tag is on.

THE QUEUE IS ABSORB'S, NOT SPOTIFY'S (report §4.4, D2). Spotify's API can
only append to its queue, so "after the next song" is not expressible there.
The runner keeps `run.queue` and sends Spotify a WINDOW of URIs
(`play_window_size`). Spotify walks the window by itself — no API call per
song — and the runner re-sends only when the song Spotify started is not the
song it wants (a requeue, a removal he made, the window running out). A
re-send can only happen as a new song STARTS, so what it cuts is the first
seconds of a song that was going to be replayed anyway — never the tail of
a capture in progress.

FORCE, PER SONG. A re-capture (a complete shape that fails the bar) only
happens if `audio_shape_service.force_uris` names it, so every window sent
puts exactly its re-capture songs there, and every fresh song in
`preroll_uris` — the runner started it from position 0, which vouches for
the pre-roll splice (see that set's comment). The runner owns both sets'
contents while a run is live and empties them when it ends.

READ THE OUTCOME, NEVER ASSUME IT. Every capture ends with exactly one
`CaptureOutcome`; the runner matches it to the attempt by the capture's own
start time, so a late outcome from an abandoned capture can never be read as
the current one's.

WHAT A LOST SESSION IS. There is one Spotify playback session per account.
If his own music starts, playback leaves Serenity, or Spotify sits paused,
Absorb has lost the session. Phase 1 ENDS the window and never touches
playback again (`_on_session_lost`); phase 2 turns that into yield-and-resume.

One process-wide runner, `runner`; `install()` wires its listeners.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from models.absorb import (
    AbsorbConfig, AbsorbLedger, AbsorbRun, Filing, HeadTally, LedgerEntry,
    NowPlaying, RealignEntry, SongEntry,
)
from services import absorb_bar, absorb_store
from services.capture_watch import Condemnation, governor_moved

logger = logging.getLogger(__name__)

# ── timing (seconds) ─────────────────────────────────────────────────────────
PLAY_SETTLE_S = 12.0          # after a play, how long Spotify may still report the old song
CAPTURE_START_GRACE_S = 30.0  # a song playing this long with no capture is condemned
PAUSE_GRACE_S = 20.0          # Spotify paused this long mid-song = the session is lost
END_TOLERANCE_MS = 8000       # a song whose last seen progress was this close to its end ended naturally
OUTCOME_TIMEOUT_S = 300.0     # a capture whose outcome never arrives is failed "no_outcome"

# ── refusals and endings: ONE sentence per code ──────────────────────────────
SENTENCES: dict[str, str] = {
    "already_running": "Absorb is already running.",
    "no_playlist": "No playlist is linked — link one first.",
    "anchor_disabled": ("Anchor detection is switched off (settings.anchor_enabled), "
                        "and every re-capture would roll back without it."),
    "analysis_disabled": "Audio analysis is switched off, so nothing would be captured.",
    "music_playing": "Music is already playing on Spotify — Absorb won't take over your listening.",
    "silence_unbuilt": ("Absorb can't open a window yet: silencing the house and holding the "
                        "lights still (phase 2) aren't built, and it will not play music out loud."),
    "night_run_active": "A night run has the room.",
    "camera_run_active": "A camera run is in progress.",
    "spectra_unreadable": "Couldn't confirm that no night run or camera run is in progress.",
    "device_unreachable": "{device} isn't available as a Spotify Connect device.",
    "playlist_unresolved": "The linked playlist couldn't be read.",
    "spotify_error": "Spotify didn't answer.",
    "nothing_to_capture": "Every song in the playlist is already captured.",
    "queue_done": "Every song in the queue was captured or parked.",
    "stopped": "Stopped.",
    "playback_did_not_start": "Spotify didn't start the song Absorb asked for.",
    "playback_failed": "Spotify refused to start playback.",
    "foreign_playback": "Other music started playing, so Absorb stepped aside.",
    "left_device": "Playback moved off {device}, so Absorb stepped aside.",
    "paused": "Spotify was paused, so Absorb stepped aside.",
    "process_restarted": "SpotFX restarted while the window was open.",
    "guard": "The house guard stopped the window.",
}


def sentence(code: str, detail: str = "", **fmt: Any) -> str:
    base = SENTENCES.get(code, code)
    try:
        base = base.format(**fmt)
    except (KeyError, IndexError):
        pass
    return f"{base} ({detail})" if detail else base


Refusal = tuple[str, str]   # (code, sentence)


# ── the phase-2 seam ─────────────────────────────────────────────────────────

class HouseGuard:
    """What makes a window safe to run in his house: silence (and its
    proof), the Order 27 gate, the light stand-down. Phase 2 implements it.

    ready()   cheap, before any Spotify call; a refusal stops the window.
    open()    after every other gate passed; may change the house (phase 2
              writes the volume here) and must undo its own change before
              returning a refusal.
    recheck() every poll while a window runs; a refusal ENDS the window.
    close()   every ending, whatever the reason."""

    def ready(self, cfg: AbsorbConfig) -> Optional[Refusal]:
        return None

    async def open(self, run: AbsorbRun, cfg: AbsorbConfig) -> Optional[Refusal]:
        return None

    async def recheck(self, run: AbsorbRun, cfg: AbsorbConfig) -> Optional[Refusal]:
        return None

    async def close(self, run: AbsorbRun, reason: str) -> None:
        return None


class UnbuiltHouseGuard(HouseGuard):
    """The shipped guard until phase 2: refuses, by name, before anything
    else happens — the runner never plays a song out loud."""

    def ready(self, cfg: AbsorbConfig) -> Optional[Refusal]:
        return ("silence_unbuilt", sentence("silence_unbuilt"))


# ── dependencies ─────────────────────────────────────────────────────────────

async def _default_to_thread(fn: Callable, *args: Any) -> Any:
    return await asyncio.to_thread(fn, *args)


async def _spectra_runs() -> Optional[Refusal]:
    """A night run or a camera run in SPECTRA (her process — this one may not
    import it) refuses the window. Unreadable fails closed."""
    import httpx
    from config import settings
    base = f"http://127.0.0.1:{settings.spectra_port}/spectra/api"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            status = (await client.get(f"{base}/engine/status")).json()
            maps = (await client.get(f"{base}/rooms/map/status")).json()
    except Exception as exc:
        return ("spectra_unreadable", sentence("spectra_unreadable", str(exc)[:120]))
    if ((status or {}).get("night_run") or {}).get("active"):
        return ("night_run_active", sentence("night_run_active"))
    if (maps or {}).get("running_room"):
        return ("camera_run_active", sentence("camera_run_active"))
    return None


@dataclass
class AbsorbDeps:
    gateway: Any
    capture: Any                                   # AudioShapeService-like
    guard: HouseGuard
    spectra_runs: Callable[[], Awaitable[Optional[Refusal]]]
    governor: Callable[[], Optional[dict]]
    classify: Callable[[str, int, bool], absorb_bar.Verdict] = absorb_bar.classify
    has_head: Callable[[str, int], tuple] = absorb_bar.has_head
    analysis_enabled: Callable[[], bool] = lambda: True
    anchor_enabled: Callable[[], bool] = lambda: True
    current_track: Callable[[], Any] = lambda: None
    device_name: Callable[[], str] = lambda: "Serenity"
    to_thread: Callable[..., Awaitable[Any]] = _default_to_thread
    # Ask the Spotify poller to look again soon (after a play): the idle poll
    # interval is 30 s, and absorb wants to see its song arrive.
    request_burst: Callable[[float], None] = lambda seconds: None
    monotonic: Callable[[], float] = time.monotonic
    now_ms: Callable[[], int] = lambda: int(time.time() * 1000)


def production_deps() -> AbsorbDeps:
    from config import settings
    from models.state import state
    from services import absorb_spotify
    from services.audio_shape_service import audio_shape_service
    from services.capture_watch import read_governor
    return AbsorbDeps(
        gateway=absorb_spotify.default_gateway(),
        capture=audio_shape_service,
        guard=UnbuiltHouseGuard(),
        spectra_runs=_spectra_runs,
        governor=lambda: read_governor(settings.absorb_governor_status_path),
        analysis_enabled=lambda: bool(state.audio_analysis_enabled),
        anchor_enabled=lambda: bool(settings.anchor_enabled),
        current_track=lambda: state.current_track,
        device_name=lambda: (settings.spotify_device_names or ["Serenity"])[0],
        request_burst=_request_burst,
    )


def _request_burst(seconds: float) -> None:
    from api import spotify_client
    from models.state import state
    until = time.monotonic() + seconds
    spotify_client._burst_until = max(spotify_client._burst_until, until)
    state.last_activity_time = time.monotonic()


# ── the runner ───────────────────────────────────────────────────────────────

@dataclass
class _Attempt:
    """One play of one song that was meant to capture it."""
    uri: str
    mode: str
    number: int
    started_mono: float
    gov_start: Optional[dict] = None
    capture_seen: bool = False
    ended_mono: Optional[float] = None
    follower: Optional[str] = None     # the song that came next — a requeue goes after it
    condemned: str = ""                # a reason once absorb gave up on this play
    counted: bool = False              # resolved and counted (success or failure)
    governor_detail: str = ""


def order_work(verdicts: list[absorb_bar.Verdict], order: str) -> list[str]:
    """Report §8.5 / D13. `verdicts` in playlist order, skips excluded.

    fresh_first       the songs with no usable shape, in playlist order, then
                      the re-captures, worst head first;
    worst_head_first  everything by how much of the song is missing;
    playlist          the playlist's own order."""
    work = [v for v in verdicts if v.kind != "skip"]
    if order == "playlist":
        return [v.uri for v in work]
    if order == "worst_head_first":
        return [v.uri for v in sorted(work, key=lambda v: -v.missing_ms)]
    fresh = [v.uri for v in work if v.kind == "fresh"]
    rec = sorted((v for v in work if v.kind == "recapture"), key=lambda v: -v.missing_ms)
    return fresh + [v.uri for v in rec]


class AbsorbRunner:
    def __init__(self, deps: Optional[AbsorbDeps] = None) -> None:
        self._deps = deps
        self.run: Optional[AbsorbRun] = None
        self._lock: Optional[asyncio.Lock] = None
        self._file_lock: Optional[asyncio.Lock] = None
        # Serialize the two off-loop persists (below) so a slower write can
        # never land its older snapshot after a faster one's newer write.
        self._ledger_persist_lock: Optional[asyncio.Lock] = None
        self._run_persist_lock: Optional[asyncio.Lock] = None
        self._tasks: set[asyncio.Task] = set()
        self._reset_live_state()

    def _reset_live_state(self) -> None:
        # The ONE in-memory ledger for this run — loaded once (`_load_ledger_
        # once`), mutated only on the event loop, never reloaded from disk
        # mid-run. See `_persist_ledger`'s own docstring for why.
        self._ledger: Optional[AbsorbLedger] = None
        self.cfg: AbsorbConfig = AbsorbConfig()
        self.device_id: Optional[str] = None
        self.source_id: str = ""
        self.source_snapshot: Optional[str] = None
        self.source_uris: list[str] = []
        self.rc_id: str = ""
        self.sent: list[str] = []
        self.sent_pos: int = -1
        self.modes: dict[str, str] = {}
        self.switching_to: Optional[str] = None
        self.switch_deadline: float = 0.0
        self.switch_retries: int = 0
        self.current: Optional[_Attempt] = None
        self.awaiting: dict[str, _Attempt] = {}
        self.np_duration_ms: int = 0
        self.np_progress_ms: int = 0
        self.paused_since: Optional[float] = None
        self.warmup_pending: bool = False
        self.distrust: set[str] = set()
        self.my_force: set[str] = set()
        self.my_vouch: set[str] = set()
        self.ours: set[str] = set()        # every URI absorb has sent Spotify this run
        self.reconciling: bool = False

    # ── plumbing ────────────────────────────────────────────────────────────

    @property
    def deps(self) -> AbsorbDeps:
        if self._deps is None:
            self._deps = production_deps()
        return self._deps

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    @property
    def active(self) -> bool:
        return self.run is not None and self.run.state == "running"

    def install(self) -> None:
        """Listen to the capture service, and pick up the last run from disk
        so the websocket's `absorb` key never has to read the file. Idempotent."""
        if self.run is None:
            try:
                self.run = absorb_store.latest_run()
            except Exception:
                self.run = None
        cap = self.deps.capture
        if self._on_condemn_sync not in cap.condemn_listeners:
            cap.condemn_listeners.append(self._on_condemn_sync)
        if self._on_outcome_sync not in cap.outcome_listeners:
            cap.outcome_listeners.append(self._on_outcome_sync)

    def _spawn(self, coro) -> Optional[asyncio.Task]:
        async def guarded():
            try:
                await coro
            except Exception:
                logger.exception("Absorb: background step failed")

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            coro.close()
            return None
        task = loop.create_task(guarded())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def settle(self) -> None:
        """Wait for every task the runner spawned (tests, shutdown)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    def _log(self, msg: str) -> None:
        logger.info("Absorb: %s", msg)
        if self.run is not None:
            stamp = time.strftime("%H:%M:%S")
            self.run.log.append(f"{stamp} {msg}")

    def _persist(self) -> None:
        if self.run is None:
            return
        self._spawn(self._persist_run_record())

    async def _persist_run_record(self) -> None:
        """Bound + cache + dump `self.run` (cheap CPU, on the loop, inside
        the lock) and write the result off the loop. Whichever call is LAST
        to hold the lock always serializes the freshest `self.run` state,
        however task scheduling actually orders several of these — the same
        guarantee `_persist_ledger` keeps for the ledger. `write_run_file`'s
        own generation check extends that guarantee past this lock too, to
        cover `_refuse`/`recover_orphaned_run`'s synchronous `save_run`
        calls, which never acquire it."""
        if self._run_persist_lock is None:
            self._run_persist_lock = asyncio.Lock()
        async with self._run_persist_lock:
            if self.run is None:
                return
            gen, data = absorb_store.prepare_run_write(self.run)
            try:
                await self.deps.to_thread(absorb_store.write_run_file, gen, data)
            except Exception as exc:
                logger.warning("Absorb: could not save the run record: %s", exc)

    async def _load_ledger_once(self) -> AbsorbLedger:
        """The ONE in-memory ledger for this run, loaded once off the event
        loop. Call this only at the start of a run (`_open_queue`); every
        later read/mutate — `_pick_warm_up`, `_file_locked`, `_resolve_
        failure`, `_judge_committed`, `_reconcile` — uses `_ledger_ref()`,
        which returns this SAME object, never a fresh disk copy. That is
        what closes the lost-update race `_file_locked` used to have: it
        loads, awaits several Spotify calls, then saves — and while it is
        in flight, `_resolve_failure`/`_judge_committed` used to load their
        OWN fresh copy, mutate it, and save it, discarding whatever
        `_file_locked` was still building up (or vice versa)."""
        if self._ledger is None:
            self._ledger = await self.deps.to_thread(absorb_store.load_ledger)
        return self._ledger

    def _ledger_ref(self) -> AbsorbLedger:
        """The in-memory ledger `_load_ledger_once` already loaded for this
        run. A defensive fallback (a fresh disk read) covers only the
        shouldn't-happen case of a caller reaching this before a run ever
        opened its queue."""
        if self._ledger is None:
            self._ledger = absorb_store.load_ledger()
        return self._ledger

    async def _persist_ledger(self) -> None:
        """Snapshot the in-memory ledger and write it off the loop. The
        snapshot is taken INSIDE the lock, right before the write, so
        whichever persist is physically LAST to hold the lock always wins
        with the then-current (always freshest, since mutations only ever
        accumulate on the one shared `self._ledger` object) state — this
        holds regardless of the order several spawned persists actually
        get scheduled in."""
        if self._ledger_persist_lock is None:
            self._ledger_persist_lock = asyncio.Lock()
        async with self._ledger_persist_lock:
            if self._ledger is None:
                return
            snapshot = self._ledger.model_dump(mode="json")
            try:
                await self.deps.to_thread(absorb_store.save_ledger_dict, snapshot)
            except Exception as exc:
                logger.warning("Absorb: could not save the ledger: %s", exc)

    def _title(self, uri: str) -> str:
        if self.run is not None:
            return self.run.titles.get(uri, "")
        return ""

    def _entry(self, uri: str, **kw: Any) -> SongEntry:
        return SongEntry(uri=uri, title=self._title(uri), at_ms=self.deps.now_ms(), **kw)

    # ── opening a window ────────────────────────────────────────────────────

    async def _gates(self, cfg: AbsorbConfig) -> Optional[Refusal]:
        d = self.deps
        if not cfg.source_playlist_uri.strip():
            return ("no_playlist", sentence("no_playlist"))
        if not d.anchor_enabled():
            return ("anchor_disabled", sentence("anchor_disabled"))
        if not d.analysis_enabled():
            return ("analysis_disabled", sentence("analysis_disabled"))
        track = d.current_track()
        if track is not None and getattr(track, "is_playing", False):
            return ("music_playing", sentence("music_playing"))
        refusal = d.guard.ready(cfg)
        if refusal:
            return refusal
        refusal = await d.spectra_runs()
        if refusal:
            return refusal
        device = d.device_name()
        try:
            self.device_id = await d.to_thread(d.gateway.device_id, device)
        except Exception as exc:
            return ("spotify_error", sentence("spotify_error", str(exc)[:120]))
        if not self.device_id:
            return ("device_unreachable", sentence("device_unreachable", device=device))
        try:
            info = await d.to_thread(d.gateway.resolve_playlist, cfg.source_playlist_uri)
        except Exception as exc:
            return ("playlist_unresolved", sentence("playlist_unresolved", str(exc)[:120]))
        if not info:
            return ("playlist_unresolved", sentence("playlist_unresolved"))
        self.source_id = info["id"]
        if self.run is not None:
            self.run.source_playlist_name = info.get("name") or ""
        return None

    def _refuse(self, run: AbsorbRun, refusal: Refusal) -> dict:
        code, text = refusal
        run.state = "refused"
        run.ended_ms = self.deps.now_ms()
        run.end_reason = code
        run.end_detail = text
        run.stage = ""
        run.log.append(f"refused: {text}")
        logger.info("Absorb: window refused — %s", text)
        try:
            absorb_store.save_run(run)
        except Exception as exc:
            logger.warning("Absorb: could not record the refusal: %s", exc)
        return {"status": "refused", "reason": code, "detail": text,
                "run": brief(run)}

    async def start(self, started_by: str = "press") -> dict:
        """Open a window now. Every refusal is RECORDED (a run in state
        "refused" with its reason) and answered, never a silence."""
        async with self._get_lock():
            if self.active:
                return {"status": "already_running", "reason": "already_running",
                        "detail": sentence("already_running"), "run": brief(self.run)}
            self._reset_live_state()
            cfg = absorb_store.load_config()
            self.cfg = cfg
            d = self.deps
            run = AbsorbRun(
                id=uuid.uuid4().hex[:12], state="running", started_ms=d.now_ms(),
                started_by=started_by if started_by in ("schedule", "press", "sonic", "ha") else "press",
                source_playlist_uri=cfg.source_playlist_uri,
                window={"start": d.now_ms(), "end": None}, stage="opening",
            )
            self.run = run
            refusal = await self._gates(cfg)
            if refusal is None:
                refusal = await d.guard.open(run, cfg)
            if refusal is not None:
                self._reset_live_state()
                return self._refuse(run, refusal)
            self._log(f"window opened ({started_by}) on {run.source_playlist_name or cfg.source_playlist_uri}")
            self._persist()
            try:
                await self._open_queue()
            except Exception as exc:
                logger.exception("Absorb: building the queue failed")
                await self._end("spotify_error", sentence("spotify_error", str(exc)[:120]),
                                pause=False)
                return {"status": "ended", "reason": "spotify_error",
                        "detail": self.run.end_detail, "run": brief(self.run)}
            return {"status": run.state if run.state != "running" else "running",
                    "reason": run.end_reason, "detail": run.end_detail, "run": brief(run)}

    async def _read_source(self) -> list[dict]:
        d = self.deps
        snapshot = await d.to_thread(d.gateway.playlist_snapshot, self.source_id)
        tracks = await d.to_thread(d.gateway.playlist_tracks, self.source_id)
        self.source_snapshot = snapshot
        self.source_uris = [t["uri"] for t in tracks]
        for t in tracks:
            if self.run is not None and t.get("title"):
                self.run.titles.setdefault(t["uri"], t["title"])
        return tracks

    async def _classify_all(self, uris: list[str]) -> list[absorb_bar.Verdict]:
        d, cfg = self.deps, self.cfg

        def work() -> list[absorb_bar.Verdict]:
            return [d.classify(u, cfg.head_max_ms, cfg.force_recapture) for u in uris]

        return await d.to_thread(work)

    async def _open_queue(self) -> None:
        run, cfg = self.run, self.cfg
        tracks = await self._read_source()
        uris = [t["uri"] for t in tracks]
        verdicts = await self._classify_all(uris)
        ledger = await self._load_ledger_once()
        parked = {u for u, e in ledger.entries.items() if e.parked}
        skips = [v for v in verdicts if v.kind == "skip"]
        work = [v for v in verdicts if v.kind != "skip" and v.uri not in parked]
        held = [v for v in verdicts if v.kind != "skip" and v.uri in parked]
        for v in verdicts:
            if v.title:
                run.titles.setdefault(v.uri, v.title)
        if held:
            self._log(f"{len(held)} parked song(s) left in the playlist (Retry un-parks one)")
        self._log(f"playlist read: {len(uris)} songs — {len(skips)} already captured, "
                  f"{sum(1 for v in work if v.kind == 'fresh')} to capture, "
                  f"{sum(1 for v in work if v.kind == 'recapture')} to re-capture")
        if skips:
            await self._skip_pass([v.uri for v in skips], verdicts={v.uri: v for v in skips})
        run.queue = order_work(work, cfg.order)
        if not run.queue:
            await self._end("nothing_to_capture", sentence("nothing_to_capture"), pause=False)
            return
        warm = ""
        if cfg.warm_up:
            warm = await self._pick_warm_up([v.uri for v in skips])
            if warm:
                run.warm_up_uri = warm
                self.warmup_pending = True
                self._log(f"warm-up: {self._title(warm) or warm}")
            else:
                self._log("no already-captured song to warm up with; starting cold")
        await self._send_window(lead=warm or None)
        self._persist()

    async def _pick_warm_up(self, skip_uris: list[str]) -> str:
        if skip_uris:
            return skip_uris[0]
        d, cfg = self.deps, self.cfg
        ledger = self._ledger_ref()
        candidates = [u for u, e in ledger.entries.items()
                      if e.filing is not None and e.filing.done_ms]

        def first_passing() -> str:
            for u in candidates[-50:][::-1]:
                ok, _v = d.has_head(u, cfg.head_max_ms)
                if ok:
                    return u
            return ""

        try:
            return await d.to_thread(first_passing)
        except Exception:
            return ""

    # ── filing: out of the source, onto Recently Captured ───────────────────

    async def _skip_pass(self, uris: list[str], verdicts: dict, wait: bool = True) -> None:
        run = self.run
        for u in uris:
            v = verdicts.get(u)
            run.skipped.append(self._entry(u, reason="already_captured",
                                           head_ms=getattr(v, "head_ms", None)))
        run.counts.skipped += len(uris)
        if wait:
            await self._file(uris, "skipped")
        else:
            self._spawn(self._file(uris, "skipped"))
        self._log(f"skip pass: {len(uris)} already-captured song(s) filed without playing")

    async def _file(self, uris: list[str], kind: str) -> None:
        """Move songs out of the source playlist and onto the top of Recently
        Captured, in that order (a song is never in neither list). The
        ledger records each step as it lands, so running this again only
        does what is missing — and a song filed a second time is MOVED to
        the top of Recently Captured, never duplicated."""
        if not uris:
            return
        if self._file_lock is None:
            self._file_lock = asyncio.Lock()
        async with self._file_lock:
            await self._file_locked(uris, kind)

    async def _file_locked(self, uris: list[str], kind: str) -> None:
        d, cfg = self.deps, self.cfg
        ledger = self._ledger_ref()
        now = d.now_ms()
        include_rc = kind == "captured" or cfg.recently_captured_includes_skipped
        to_add: list[str] = []
        to_remove: list[str] = []
        for u in uris:
            e = ledger.entries.get(u)
            if e is None:
                e = ledger.entries[u] = LedgerEntry(uri=u, title=self._title(u))
            f = e.filing
            if f is None or f.done_ms:
                f = e.filing = Filing(kind=kind, started_ms=now)
            if include_rc and not f.rc_added:
                to_add.append(u)
            if not f.source_removed:
                to_remove.append(u)
        await self._persist_ledger()

        if to_add:
            try:
                if not self.rc_id:
                    self.rc_id = await d.to_thread(
                        d.gateway.find_or_create_playlist, cfg.captured_playlist_name,
                        ledger.captured_playlist_id
                        if ledger.captured_playlist_name == cfg.captured_playlist_name else "")
                    ledger.captured_playlist_id = self.rc_id
                    ledger.captured_playlist_name = cfg.captured_playlist_name
                # remove-then-add: newest first, never twice
                await d.to_thread(d.gateway.remove_tracks, self.rc_id, to_add)
                await d.to_thread(d.gateway.add_tracks_top, self.rc_id, list(reversed(to_add)))
                for u in to_add:
                    ledger.entries[u].filing.rc_added = True
                beyond = await d.to_thread(d.gateway.tracks_beyond, self.rc_id,
                                           cfg.recently_captured_max)
                if beyond:
                    await d.to_thread(d.gateway.remove_tracks, self.rc_id, beyond)
            except Exception as exc:
                self._log(f"Recently Captured update failed ({str(exc)[:80]}); will retry")
        if to_remove and self.source_id:
            try:
                await d.to_thread(d.gateway.remove_tracks, self.source_id, to_remove)
                for u in to_remove:
                    ledger.entries[u].filing.source_removed = True
                self.source_uris = [u for u in self.source_uris if u not in set(to_remove)]
            except Exception as exc:
                self._log(f"removing from the source playlist failed ({str(exc)[:80]}); will retry")
        for u in uris:
            f = ledger.entries[u].filing
            if f is not None and f.source_removed and (f.rc_added or not include_rc):
                f.done_ms = d.now_ms()
        await self._persist_ledger()

    # ── playback ────────────────────────────────────────────────────────────

    async def _mode_for(self, uris: list[str]) -> dict[str, str]:
        """Decide fresh/recapture at send time from the disk as it is NOW.
        A song that has meanwhile come to pass the bar (he played it) is
        reported as "skip"; one the runner distrusts is a re-capture."""
        d, cfg = self.deps, self.cfg

        def work() -> dict[str, str]:
            out = {}
            for u in uris:
                v = d.classify(u, cfg.head_max_ms, cfg.force_recapture)
                kind = v.kind
                if kind == "skip" and u in self.distrust:
                    kind = "recapture"
                out[u] = kind
            return out

        return await d.to_thread(work)

    async def _send_window(self, lead: Optional[str] = None) -> bool:
        """Send Spotify the next window and arm the per-song force sets.
        Returns False when there was nothing to send or the play failed."""
        d, run, cfg = self.deps, self.run, self.cfg
        size = cfg.play_window_size
        while True:
            head = run.queue[: size - (1 if lead else 0)]
            modes = await self._mode_for(head) if head else {}
            done = [u for u in head if modes.get(u) == "skip"]
            if not done:
                break
            # captured meanwhile (his own listening) — file it, never play it
            run.queue = [u for u in run.queue if u not in set(done)]
            for u in done:
                run.skipped.append(self._entry(u, reason="captured_meanwhile"))
            run.counts.skipped += len(done)
            self._spawn(self._file(done, "skipped"))
        uris = ([lead] if lead else []) + head
        if not uris:
            # every remaining queued song passed the bar between the queue
            # build/reconcile and this send — nothing is left to play. Drain
            # exactly as a genuinely empty queue would, so the run is never
            # left "running" with nothing driving it forward.
            await self._drain()
            return False
        self.modes.update(modes)
        force = {u for u in head if modes.get(u) == "recapture"}
        vouch = {u for u in head if modes.get(u) == "fresh"}
        cap = d.capture
        cap.force_uris.difference_update(self.my_force)
        cap.preroll_uris.difference_update(self.my_vouch)
        cap.force_uris.update(force)
        cap.preroll_uris.update(vouch)
        self.my_force, self.my_vouch = force, vouch
        if self.current is not None and not self.current.condemned:
            self.current.condemned = "interrupted"
            self.current.counted = True
            self.current.ended_mono = d.monotonic()
        self.ours.update(uris)
        try:
            await d.to_thread(d.gateway.play, self.device_id, uris)
            d.request_burst(PLAY_SETTLE_S)
        except Exception as exc:
            self._log(f"play failed: {str(exc)[:100]}")
            if self.switch_retries >= 1:
                await self._end("playback_failed", sentence("playback_failed", str(exc)[:80]),
                                pause=False)
                return False
            self.switch_retries += 1
        self.sent = uris
        self.sent_pos = -1
        self.switching_to = uris[0]
        self.switch_deadline = d.monotonic() + PLAY_SETTLE_S
        run.now_playing = None
        self.current = None
        run.stage = "capturing" if not lead else "warming_up"
        self._log(f"play → {self._title(uris[0]) or uris[0]} (+{len(uris) - 1} queued on Spotify)")
        return True

    def _clear_sets(self) -> None:
        cap = self.deps.capture
        cap.force_uris.difference_update(self.my_force)
        cap.preroll_uris.difference_update(self.my_vouch)
        self.my_force, self.my_vouch = set(), set()

    def _arrive(self, uri: str, track: Any) -> None:
        """The song Absorb wanted is now playing."""
        d, run = self.deps, self.run
        self.switching_to = None
        self.switch_retries = 0
        self.paused_since = None
        if uri in self.sent:
            self.sent_pos = self.sent.index(uri)
        self.np_duration_ms = int(getattr(track, "duration_ms", 0) or 0)
        self.np_progress_ms = 0
        title = f"{getattr(track, 'artist', '')} — {getattr(track, 'title', '')}".strip(" —")
        if title:
            run.titles.setdefault(uri, title)
        if self.warmup_pending and uri == run.warm_up_uri:
            self.warmup_pending = False
            run.now_playing = NowPlaying(uri=uri, title=self._title(uri),
                                         started_ms=d.now_ms(), mode="warmup")
            self.current = None
            run.stage = "warming_up"
            self._persist()
            return
        self.warmup_pending = False
        if run.queue and run.queue[0] == uri:
            run.queue.pop(0)
        elif uri in run.queue:
            run.queue.remove(uri)
        mode = self.modes.get(uri, "fresh")
        number = run.attempts.get(uri, 0) + 1
        run.now_playing = NowPlaying(uri=uri, title=self._title(uri), started_ms=d.now_ms(),
                                     attempt=number, mode=mode)
        att = _Attempt(uri=uri, mode=mode, number=number, started_mono=d.monotonic(),
                       gov_start=d.governor())
        self.current = att
        self.awaiting[uri] = att
        run.stage = "capturing"
        self._persist()
        if not self.reconciling:
            self._spawn(self._reconcile())

    # ── the poll ────────────────────────────────────────────────────────────

    async def on_track_state(self, track: Any) -> None:
        """Called on every Spotify poll, BEFORE the capture service sees the
        same track (so the force sets are right when it decides)."""
        if self.run is None:
            return
        # Never raise into the Spotify polling loop: an exception here would
        # end the poller, and with it every capture.
        try:
            async with self._get_lock():
                self._sweep_outcomes()
                if not self.active:
                    return
                await self._poll(track)
        except Exception:
            logger.exception("Absorb: poll handling failed")

    async def _poll(self, track: Any) -> None:
        d, run = self.deps, self.run
        refusal = await d.guard.recheck(run, self.cfg)
        if refusal:
            await self._end(refusal[0], refusal[1], pause=True)
            return
        now = d.monotonic()
        uri = getattr(track, "spotify_uri", None) if track else None
        playing = bool(track and getattr(track, "is_playing", False))
        device = d.device_name()
        on_device = bool(track) and str(getattr(track, "device_name", "")).lower() == device.lower()

        if self.switching_to:
            if uri == self.switching_to and playing:
                if not on_device:
                    await self._on_session_lost("left_device", "")
                    return
                self._arrive(uri, track)
            elif playing and uri and uri not in self.ours:
                await self._on_session_lost("foreign_playback", self._describe(track))
            elif now >= self.switch_deadline:
                if self.switch_retries < 1:
                    self.switch_retries += 1
                    self._log("Spotify hasn't started the song yet; asking again")
                    await self._resend()
                else:
                    await self._end("playback_did_not_start",
                                    sentence("playback_did_not_start"), pause=False)
            return

        np_ = run.now_playing
        if np_ is None:
            # draining: everything is played, outcomes are still landing
            if playing and uri and uri not in self.ours:
                await self._on_session_lost("foreign_playback", self._describe(track))
            return

        if uri == np_.uri:
            if playing and not on_device:
                await self._on_session_lost("left_device", "")
                return
            if playing:
                self.paused_since = None
                self.np_progress_ms = max(self.np_progress_ms,
                                          int(track.interpolated_progress_ms()))
                await self._watch_current(now)
                return
            if self._ended_naturally():
                await self._song_ended(None, track)
                return
            if self.paused_since is None:
                self.paused_since = now
            elif now - self.paused_since >= PAUSE_GRACE_S:
                await self._on_session_lost("paused", "")
            return

        # a different song, or nothing at all
        if not playing:
            if self._ended_naturally():
                await self._song_ended(None, track)
                return
            if self.paused_since is None:
                self.paused_since = now
            elif now - self.paused_since >= PAUSE_GRACE_S:
                await self._on_session_lost("paused", "")
            return
        if not on_device:
            await self._on_session_lost("left_device", self._describe(track))
            return
        if uri in self.ours:
            await self._song_ended(uri, track)
            return
        if self._ended_naturally() and self.sent and np_.uri == self.sent[-1]:
            # the window ran out and Spotify carried on with something of its own
            await self._song_ended(None, track)
            return
        await self._on_session_lost("foreign_playback", self._describe(track))

    @staticmethod
    def _describe(track: Any) -> str:
        if not track:
            return ""
        return f"{getattr(track, 'artist', '')} — {getattr(track, 'title', '')}".strip(" —")

    def _ended_naturally(self) -> bool:
        return (self.np_duration_ms > 0
                and self.np_progress_ms >= self.np_duration_ms - END_TOLERANCE_MS)

    async def _watch_current(self, now: float) -> None:
        """The poll-side detectors, for the song absorb is capturing."""
        att, d = self.current, self.deps
        if att is None or att.condemned:
            return
        if d.capture.recording_uri == att.uri:
            att.capture_seen = True
        elif not att.capture_seen and now - att.started_mono >= CAPTURE_START_GRACE_S:
            await self._condemn_current("no_capture",
                                        "no capture started for this song")
            return
        moved = governor_moved(att.gov_start, d.governor())
        if moved:
            await self._condemn_current("governor_drain", moved, distrust=True)

    async def _song_ended(self, arrived: Optional[str], track: Any) -> None:
        """The song absorb was playing is over. `arrived` is the song Spotify
        moved on to when that song is one of absorb's (None: Spotify stopped,
        or carried on with something of its own)."""
        d, run = self.deps, self.run
        att = self.current
        self.current = None
        if att is not None and not att.condemned:
            att.ended_mono = d.monotonic()
            att.follower = arrived if arrived else (run.queue[0] if run.queue else None)
            moved = governor_moved(att.gov_start, d.governor())
            if moved:
                att.governor_detail = moved
            if not att.capture_seen and d.capture.recording_uri != att.uri:
                self.awaiting.pop(att.uri, None)
                self._resolve_failure(att, "no_capture", "no capture started for this song")
        run.now_playing = None
        if arrived is not None and run.queue and arrived == run.queue[0] \
                and not self.warmup_pending:
            self._arrive(arrived, track)
            return
        if run.queue:
            await self._send_window()
            return
        await self._drain()

    async def _drain(self) -> None:
        """Nothing left to play. Stop the music; end once every outcome has
        landed (one may still requeue a song)."""
        d, run = self.deps, self.run
        run.stage = "draining"
        self.sent, self.sent_pos, self.switching_to = [], -1, None
        self._clear_sets()
        try:
            await d.to_thread(d.gateway.pause, self.device_id)
        except Exception as exc:
            self._log(f"pause failed: {str(exc)[:80]}")
        self._persist()
        await self._maybe_finish()

    async def _maybe_finish(self) -> None:
        run = self.run
        if not self.active or run.queue or run.now_playing or self.switching_to:
            return
        if any(not a.condemned for a in self.awaiting.values()):
            return
        await self._end("queue_done", sentence("queue_done"), pause=False)

    async def _resend(self) -> None:
        lead = self.sent[0] if self.sent and self.sent[0] == self.run.warm_up_uri \
            and self.warmup_pending else None
        await self._send_window(lead=lead)

    # ── condemnation, requeue, park ─────────────────────────────────────────

    def _on_condemn_sync(self, c: Condemnation) -> None:
        if self.active and self.current is not None and self.current.uri == c.uri:
            self._spawn(self._on_condemn(c))

    async def _on_condemn(self, c: Condemnation) -> None:
        async with self._get_lock():
            att = self.current
            if not self.active or att is None or att.uri != c.uri or att.condemned:
                return
            await self._condemn_current(c.reason, c.detail)

    async def _condemn_current(self, reason: str, detail: str, distrust: bool = False) -> None:
        """Give up on the song playing now: count the failure, requeue it
        after the next song (or park it at the cap) and play the next song
        at once."""
        att, run = self.current, self.run
        att.condemned = reason
        att.ended_mono = self.deps.monotonic()
        att.follower = run.queue[0] if run.queue else None
        if distrust:
            self.distrust.add(att.uri)
        self._log(f"condemned {self._title(att.uri) or att.uri}: {reason} — {detail}")
        self._resolve_failure(att, reason, detail)
        self.current = None
        run.now_playing = None
        if run.queue:
            await self._send_window()
        else:
            await self._drain()
        self._persist()

    def _resolve_failure(self, att: _Attempt, reason: str, detail: str) -> None:
        if att.counted:
            return
        att.counted = True
        run, cfg, d = self.run, self.cfg, self.deps
        run.attempts[att.uri] = run.attempts.get(att.uri, 0) + 1
        run.counts.failed += 1
        if reason == "head_missed":
            run.counts.head_missed += 1
        ledger = self._ledger_ref()
        e = ledger.entries.get(att.uri) or LedgerEntry(uri=att.uri, title=self._title(att.uri))
        e.lifetime_attempts += 1
        e.last_failure = reason
        e.last_attempt_ms = d.now_ms()
        entry = self._entry(att.uri, attempt=att.number, mode=att.mode, reason=reason, detail=detail)
        run.failed.append(entry)
        if run.attempts[att.uri] >= cfg.max_attempts:
            tag = "head_unreachable" if reason == "head_missed" else reason
            e.parked, e.parked_reason, e.parked_ms = True, tag, d.now_ms()
            run.parked.append(self._entry(att.uri, attempt=att.number, mode=att.mode,
                                          reason=tag, detail=detail))
            run.counts.parked += 1
            self._log(f"parked {self._title(att.uri) or att.uri} after "
                      f"{run.attempts[att.uri]} attempts: {tag}")
        elif self.active:
            self._requeue(att.uri, att.follower)
            run.counts.requeued += 1
        ledger.entries[att.uri] = e
        # sync — spawn the write rather than await it (`_resolve_failure`
        # is called synchronously from several places); the persist lock
        # still serializes it against every other save.
        self._spawn(self._persist_ledger())

    def _requeue(self, uri: str, follower: Optional[str]) -> None:
        """Back in the queue right AFTER the song that followed it — his
        "requeues it after the next song"."""
        q = self.run.queue
        while uri in q:
            q.remove(uri)
        if follower and follower in q:
            q.insert(q.index(follower) + 1, uri)
        else:
            q.insert(0, uri)

    # ── outcomes ────────────────────────────────────────────────────────────

    def _on_outcome_sync(self, outcome: Any) -> None:
        if outcome.uri in self.awaiting:
            self._spawn(self._on_outcome(outcome))

    async def _on_outcome(self, o: Any) -> None:
        async with self._get_lock():
            att = self.awaiting.get(o.uri)
            if att is None:
                return
            started = getattr(o, "capture_started_at", None)
            if started is not None and started < att.started_mono - 1.0:
                return  # an earlier, abandoned capture of the same song
            del self.awaiting[o.uri]
            if att.condemned or att.counted:
                self._log(f"finalize for {self._title(o.uri) or o.uri}: {o.status} "
                          f"{o.reason} (already {att.condemned or 'counted'})")
                await self._maybe_finish()
                self._persist()
                return
            still_playing = att is self.current
            if still_playing:
                # The capture stopped while its song is still on. If Spotify
                # is paused that is HIS pause (pausing is what stopped it):
                # not an attempt, and the pause rule decides what happens.
                track = self.deps.current_track()
                if track is not None and not getattr(track, "is_playing", True):
                    att.condemned, att.counted = "interrupted", True
                    att.ended_mono = self.deps.monotonic()
                    if self.active:
                        # if he resumes, this play's capture is already gone:
                        # the song comes round again after the next one
                        self._requeue(att.uri, self.run.queue[0] if self.run.queue else None)
                        self.run.counts.requeued += 1
                    self._persist()
                    return
                self.current = None
            if o.status != "ok":
                self._resolve_failure(att, o.reason or "failed", "")
            elif att.governor_detail:
                self.distrust.add(o.uri)
                self._resolve_failure(att, "governor_drain", att.governor_detail)
            else:
                await self._judge_committed(att, o)
            if still_playing and self.active:
                # the song is still on, but its capture is over — move on
                self.run.now_playing = None
                if self.run.queue:
                    await self._send_window()
                else:
                    await self._drain()
            await self._maybe_finish()
            self._persist()

    async def _judge_committed(self, att: _Attempt, o: Any) -> None:
        """THE SECOND GATE (report §8.4): a committed capture counts only if
        the shape on disk passes the bar — a committed-but-headless capture
        is `head_missed`, requeued, and parked as `head_unreachable` at the
        cap."""
        d, run, cfg = self.deps, self.run, self.cfg
        ok, verdict = await d.to_thread(d.has_head, att.uri, cfg.head_max_ms)
        rate = run.head_rate
        tally = rate.by_mode.setdefault(att.mode, HeadTally())
        rate.attempted += 1
        tally.attempted += 1
        if ok:
            rate.with_head += 1
            tally.with_head += 1
        realign = getattr(o, "realign", None)
        if isinstance(realign, dict) and realign.get("status"):
            run.realigned.append(RealignEntry(
                uri=att.uri, title=self._title(att.uri), status=str(realign.get("status")),
                shift_ms=int(realign.get("shift_ms") or 0), r=float(realign.get("r") or 0.0),
                triggers=int(realign.get("triggers") or 0), at_ms=d.now_ms()))
        if not ok:
            reasons = list(getattr(verdict, "reasons", []) or [])
            reason = "head_missed" if "headless" in reasons else (reasons[0] if reasons else "bar")
            detail = (f"first sample at {verdict.head_ms} ms" if verdict.head_ms is not None
                      else ", ".join(reasons))
            self._resolve_failure(att, reason, detail)
            return
        att.counted = True
        run.attempts[att.uri] = run.attempts.get(att.uri, 0) + 1
        run.counts.captured += 1
        run.captured.append(self._entry(att.uri, attempt=att.number, mode=att.mode,
                                        head_ms=verdict.head_ms))
        self.distrust.discard(att.uri)
        ledger = self._ledger_ref()
        e = ledger.entries.get(att.uri) or LedgerEntry(uri=att.uri, title=self._title(att.uri))
        e.lifetime_attempts += 1
        e.last_attempt_ms = d.now_ms()
        e.parked = False
        ledger.entries[att.uri] = e
        await self._persist_ledger()
        self._log(f"captured {self._title(att.uri) or att.uri} "
                  f"(head at {verdict.head_ms} ms, {att.mode})")
        self._spawn(self._file([att.uri], "captured"))

    def _sweep_outcomes(self) -> None:
        now = self.deps.monotonic()
        for uri, att in list(self.awaiting.items()):
            if att.ended_mono is not None and now - att.ended_mono >= OUTCOME_TIMEOUT_S:
                del self.awaiting[uri]
                if not att.condemned and not att.counted and self.run is not None:
                    self._resolve_failure(att, "no_outcome", "the capture never reported back")
                    self._persist()

    # ── reconciling his playlist edits (D6) ─────────────────────────────────

    async def _reconcile(self) -> None:
        """At each song boundary: if the source playlist changed, songs he
        added join the end of the queue (in playlist order) and songs he
        removed leave it. A song he removed while it plays finishes, is
        filed, and is not re-added."""
        if self.reconciling or not self.active or not self.source_id:
            return
        self.reconciling = True
        try:
            d = self.deps
            try:
                snap = await d.to_thread(d.gateway.playlist_snapshot, self.source_id)
            except Exception:
                return
            if snap is not None and snap == self.source_snapshot:
                return
            try:
                tracks = await d.to_thread(d.gateway.playlist_tracks, self.source_id)
            except Exception:
                return
            async with self._get_lock():
                if not self.active:
                    return
                run = self.run
                self.source_snapshot = snap
                now_uris = [t["uri"] for t in tracks]
                for t in tracks:
                    if t.get("title"):
                        run.titles.setdefault(t["uri"], t["title"])
                present = set(now_uris)
                removed = [u for u in run.queue if u not in present]
                if removed:
                    run.queue = [u for u in run.queue if u in present]
                    self._log(f"{len(removed)} song(s) removed from the playlist left the queue")
                known = set(run.queue) | set(self.awaiting) | set(self.source_uris)
                if run.now_playing:
                    known.add(run.now_playing.uri)
                known |= {e.uri for e in run.captured} | {e.uri for e in run.parked}
                added = [u for u in now_uris if u not in known]
                self.source_uris = now_uris
                if not added:
                    self._persist()
                    return
                ledger = self._ledger_ref()
                verdicts = await self._classify_all(added)
                skips = [v for v in verdicts if v.kind == "skip"]
                for v in verdicts:
                    if v.kind == "skip":
                        continue
                    if ledger.entries.get(v.uri) and ledger.entries[v.uri].parked:
                        continue
                    run.queue.append(v.uri)
                if skips:
                    await self._skip_pass([v.uri for v in skips], {v.uri: v for v in skips},
                                          wait=False)
                self._log(f"{len(added)} song(s) added to the playlist: "
                          f"{len(skips)} already captured, {len(added) - len(skips)} queued")
                self._persist()
        finally:
            self.reconciling = False

    # ── his presses ─────────────────────────────────────────────────────────

    async def stop(self, reason: str = "stopped") -> dict:
        async with self._get_lock():
            if not self.active:
                return {"status": "not_running", "run": brief(self.run)}
            await self._end(reason, sentence(reason) if reason in SENTENCES else reason,
                            pause=True)
            return {"status": "ended", "run": brief(self.run)}

    async def skip_song(self) -> dict:
        """His "Skip this song": move on now; the song goes back in the queue
        after the next one, and the skip is not counted as a failed attempt."""
        async with self._get_lock():
            run = self.run
            if not self.active or run.now_playing is None:
                return {"status": "nothing_playing", "run": brief(run)}
            np_ = run.now_playing
            att = self.current
            if att is not None:
                att.condemned = "skipped_by_you"
                att.counted = True
                att.ended_mono = self.deps.monotonic()
                self._requeue(att.uri, run.queue[0] if run.queue else None)
                run.counts.requeued += 1
            self._log(f"skipped {np_.title or np_.uri} by request")
            self.current = None
            run.now_playing = None
            if self.warmup_pending or np_.mode == "warmup":
                self.warmup_pending = False
            if run.queue:
                await self._send_window()
            else:
                await self._drain()
            self._persist()
            return {"status": "skipped", "skipped_uri": np_.uri, "run": brief(run)}

    async def unpark(self, uri: str) -> bool:
        """His per-song Retry: the song is captured again from the next
        window (or, mid-run, the next reconcile). True when it was parked.
        While THIS run holds the ledger in memory, mutate that SAME object
        and persist it through the ordered ledger persist — a direct disk
        edit here would be invisible to a run that never reloads its
        ledger from disk, and the run's own very next ledger-mutating
        persist would silently revert it. With no ledger loaded yet (no
        run has opened its queue), edit the file directly."""
        async with self._get_lock():
            if self._ledger is not None:
                if not _unpark_entry(self._ledger, uri):
                    return False
                await self._persist_ledger()
                return True
            ledger = absorb_store.load_ledger()
            if not _unpark_entry(ledger, uri):
                return False
            absorb_store.save_ledger(ledger)
            return True

    # ── endings ─────────────────────────────────────────────────────────────

    async def _on_session_lost(self, code: str, detail: str) -> None:
        """His listening (or something else) took the Spotify session.
        PHASE 1: end the window and never touch playback again. Phase 2
        replaces this with yield-and-resume (report §6.1). The interrupted
        song is not counted as an attempt — it stays in the playlist."""
        await self._end(code, sentence(code, detail, device=self.deps.device_name()),
                        pause=False)

    async def _end(self, code: str, text: str, pause: bool) -> None:
        d, run = self.deps, self.run
        if run is None or run.state != "running":
            return
        att = self.current
        if att is not None and not att.condemned:
            att.condemned = "interrupted"
            att.counted = True
            att.ended_mono = d.monotonic()
        run.state = "ended"
        run.ended_ms = d.now_ms()
        run.end_reason = code
        run.end_detail = text
        run.stage = ""
        run.now_playing = None
        self.current = None
        self.switching_to = None
        self._clear_sets()
        if pause and self.device_id:
            try:
                await d.to_thread(d.gateway.pause, self.device_id)
            except Exception as exc:
                self._log(f"pause failed: {str(exc)[:80]}")
        try:
            await d.guard.close(run, code)
        except Exception as exc:
            logger.warning("Absorb: house guard close failed: %s", exc)
        self._log(f"window ended: {text}")
        self.sent, self.sent_pos = [], -1
        self._persist()


# ── reads ────────────────────────────────────────────────────────────────────

def brief(run: Optional[AbsorbRun]) -> dict:
    """What the websocket `state` broadcast carries under `absorb` and what
    every route answers with: small, flat, stable."""
    if run is None:
        return {"state": "idle"}
    np_ = run.now_playing
    return {
        "state": run.state, "stage": run.stage, "run_id": run.id,
        "started_ms": run.started_ms, "ended_ms": run.ended_ms,
        "end_reason": run.end_reason, "end_detail": run.end_detail,
        "started_by": run.started_by,
        "source_playlist_uri": run.source_playlist_uri,
        "source_playlist_name": run.source_playlist_name,
        "now_playing": np_.model_dump() if np_ else None,
        "queue_len": len(run.queue),
        "counts": run.counts.model_dump(),
        "head_rate": {"attempted": run.head_rate.attempted,
                      "with_head": run.head_rate.with_head},
    }


def status_brief() -> dict:
    """The websocket's `absorb` key: the live (or last) run. In memory only —
    this rides every state broadcast, so it never touches the disk."""
    return brief(runner.run)


async def preview(deps: Optional[AbsorbDeps] = None) -> dict:
    """The skip / fresh / re-capture split of the linked playlist as it
    stands — what a window would do. Reads only."""
    d = deps or runner.deps
    cfg = absorb_store.load_config()
    if not cfg.source_playlist_uri.strip():
        return {"linked": False, "detail": sentence("no_playlist")}
    info = await d.to_thread(d.gateway.resolve_playlist, cfg.source_playlist_uri)
    if not info:
        return {"linked": True, "resolved": False, "detail": sentence("playlist_unresolved")}
    tracks = await d.to_thread(d.gateway.playlist_tracks, info["id"])
    uris = [t["uri"] for t in tracks]

    def work() -> list:
        return [d.classify(u, cfg.head_max_ms, cfg.force_recapture) for u in uris]

    verdicts = await d.to_thread(work)
    ledger = absorb_store.load_ledger()
    parked = {u for u, e in ledger.entries.items() if e.parked}
    counts = {"total": len(uris), "skip": 0, "fresh": 0, "recapture": 0, "parked": 0}
    reasons: dict[str, int] = {}
    for v in verdicts:
        if v.kind != "skip" and v.uri in parked:
            counts["parked"] += 1
            continue
        counts[v.kind] += 1
        for r in v.reasons:
            reasons[r] = reasons.get(r, 0) + 1
    return {"linked": True, "resolved": True, "playlist": info, "counts": counts,
            "reasons": reasons, "force_recapture": cfg.force_recapture,
            "head_max_ms": cfg.head_max_ms}


# ── config edits ─────────────────────────────────────────────────────────────

def apply_config_patch(patch: dict) -> AbsorbConfig:
    """A PARTIAL update: only the keys sent change, every other key keeps
    its stored value. An unknown key is refused by name (a typo must never
    read as success)."""
    if not isinstance(patch, dict):
        raise ValueError("expected an object of settings")
    unknown = sorted(set(patch) - set(AbsorbConfig.model_fields))
    if unknown:
        raise ValueError(f"unknown setting(s): {', '.join(unknown)}")
    current = absorb_store.load_config().model_dump(mode="json")
    current.update(patch)
    cfg = AbsorbConfig.model_validate(current)
    absorb_store.save_config(cfg)
    return cfg


# ── un-parking ───────────────────────────────────────────────────────────────

def _unpark_entry(ledger: AbsorbLedger, uri: str) -> bool:
    e = ledger.entries.get(uri)
    if e is None or not e.parked:
        return False
    e.parked, e.parked_reason, e.parked_ms = False, "", 0
    return True


async def unpark(uri: str) -> bool:
    """His per-song Retry. See `AbsorbRunner.unpark`'s own docstring for why
    this goes through the live runner rather than always touching disk."""
    return await runner.unpark(uri)


# ── recovery ─────────────────────────────────────────────────────────────────

def recover_orphaned_run() -> Optional[str]:
    """At startup: a run left "running" by a process that died is stamped
    ended. (Phase 2 also restores the house's volume here, first.)"""
    try:
        run = absorb_store.latest_run()
    except Exception:
        return None
    if run is None or run.state not in ("running", "paused"):
        return None
    run.state = "ended"
    run.end_reason = "process_restarted"
    run.end_detail = sentence("process_restarted")
    run.ended_ms = int(time.time() * 1000)
    run.stage = ""
    run.now_playing = None
    run.log.append("ended: SpotFX restarted while the window was open")
    absorb_store.save_run(run)
    logger.warning("Absorb: run %s was open when SpotFX stopped — marked ended", run.id)
    return run.id


runner = AbsorbRunner()


def install() -> None:
    """Wire the process-wide runner to the capture service (main.py)."""
    runner.install()
