"""
SpotFX — Absorb Music's house guard: the songs play SILENTLY, the silence is
PROVEN, the Order 27 exception rides on that proof, the lights are held
still, and every change is put back (data/absorb-music-plan/report.md §3,
§6, §6.1-6.3; phase 2). `SilentHouseGuard` is services/absorb.py's
`HouseGuard`; the runner calls it and never touches the house itself.

SILENCE = THE FIVE AUDIBLE ROOMS, NEVER THE CAPTURE CLIENT. The capture taps
`snapcast.monitor`, the monitor of a null sink only the `Effects Host`
snapclient writes into — already inaudible. So silence is River's
`snap_volume` → 0 (api/ha_client.py), which the house's "Snap Volume
Control" automation fans out to the audible rooms and — the evidence says —
not to `Effects Host`. Spotify volume 0 is never used: it is upstream of
the whole chain and the capture would record silence.

THE PROOF, NOT THE BELIEF (§3). After the write: Home Assistant's own
`snap_volume` must read back 0, and Snapcast's own status
(services/snapcast_status.py) must show `Effects Host` connected, unmuted,
at its pre-window percent, and every OTHER connected room at 0 % or muted.
If `Effects Host` moved, the volume is put back at once and the window is
refused by name ("the house volume control reaches the capture client").
A room the volume did not reach is muted DIRECTLY (Client.SetVolume) — the
per-client fallback the proof selects — then the proof is read again. A
room on the TTS stream is hearing one of River's announcements, not absorb,
and is left alone (§6.2: announcements may be urgent).

THE ORDER 27 EXCEPTION (his Q5: "yes", for Absorb only). Absorb may run
while `input_boolean.sleeping` is on, and ONLY while every one of these
holds; any one failing STOPS the window — never a retry:
  1. it is an Absorb window (nothing else reaches this module);
  2. the silence is proven, as above;
  3. the proof is re-run every `silence_recheck_s` (60 s) while the window
     runs — a room coming back on the network joins un-silenced, so the
     recheck mutes the newcomer and re-proves, or stops;
  4. a read that fails is not a pass: snapserver unreachable or malformed
     stops the window (the fail-safe direction is always LESS sound);
  5. River's AUDIO_HARD_BLOCK still refuses — her own label rule, verbatim:
     the file present refuses unless an `allow=` line names "absorb";
  6. the volume must be settable: Home Assistant unreachable means no
     silence to prove, so the window does not open.
`sleeping` is still read and recorded (`run.sleeping_at_open`); an
unreadable boolean is treated as ON (River's own `sleeping_on()` rule).
`run_while_sleeping: false` turns the exception off: sleeping then refuses
at open and stops a running window.

THE YIELD IS THE ONE FAST PATH (§6.1). When his own music takes over, the
house is silent and he has just pressed play — so `yield_now()` restores the
volume FIRST, one snapped write, before anything else; lifts the light
stand-down second; the runner stops its queue third.

RESTORE, EXACTLY, ON EVERY EXIT. `snap_volume` and the capture client are
remembered to `storage/absorb_silence.json` BEFORE the first write (the
`AUDIO_PREV_VOL` pattern River's pretake endpoint uses), and every room
absorb mutes is added to it before its mute is sent. A restore writes the
volume back, un-mutes only the rooms absorb muted (a room he muted himself
stays muted), puts the capture client back if it moved, READS IT ALL BACK,
and only then deletes the file. A restore that does not read back is
CRITICAL, named on the run, and retried by the supervisor — never
swallowed. On a normal close the volume is never restored over absorb's own
music: if absorb's song might still be playing, it is paused first, and if
that cannot be confirmed the house stays silent (and the lights held) until
it can. A process that died mid-window leaves the file behind; the first
supervisor tick of the next process restores it before anything else.

THE LIGHTS (his Q3: "nothing"). `run.lights_held` rides the websocket
`absorb` key; SPECTRA's bridge reads it and stands the show down at every
choke point (spectra/services/absorb_hold.py). It is set only once the
silence is proven and cleared the moment the house is given back.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from config import BASE_DIR
from services.snapcast_status import SnapClient, SnapStatus, SnapcastUnreadable

logger = logging.getLogger(__name__)

SNAPSHOT_FILE = BASE_DIR / "storage" / "absorb_silence.json"

# ── timing (seconds) ─────────────────────────────────────────────────────────
SILENCE_SETTLE_S = 10.0   # the volume automation reaching every room after the write
SETTLE_POLL_S = 0.5
RESTORE_SETTLE_S = 10.0   # the restored volume reading back, the rooms unmuting
TTS_RECHECK_S = 5.0       # recheck sooner while a room sits on the announcement stream
RETRY_PENDING_S = 15.0    # a restore that did not land is tried again this often
VOLUME_TOLERANCE = 0.5    # snap_volume is a whole percent

HARD_BLOCK_LABEL = "absorb"
CHECKS_KEPT = 200         # silence checks kept on a run (also bounded by the store)

Refusal = tuple[str, str]

SENTENCES: dict[str, str] = {
    "hard_block": ("River's audio hard block is in place, and Absorb isn't exempt from it "
                   "(it would need an \"allow=absorb\" line)."),
    "hard_block_unreadable": "River's audio hard block file couldn't be read, so Absorb won't play.",
    "restore_pending": ("The house volume from the last window hasn't been put back yet, "
                        "so a new window can't open."),
    "ha_unreachable": ("Home Assistant couldn't be read, so the house volume can't be set — "
                       "there would be no silence to prove."),
    "sleeping": "The house is sleeping and Absorb's permission to run while it sleeps is off.",
    "snapserver_unreadable": "Snapcast's status couldn't be read, so the silence can't be proven.",
    "foreign_stream": "Someone is playing music to the house ({streams}), so Absorb stepped aside.",
    "capture_client_missing": "The capture client ({name}) isn't connected, so nothing would be captured.",
    "capture_client_muted": "The capture client ({name}) is muted, so the capture would record silence.",
    "capture_client_reached": ("The house volume control reaches the capture client ({name}); "
                               "Absorb cannot run silently."),
    "volume_unsettable": "The house volume couldn't be set to 0.",
    "not_silent": "A room could still hear the music ({rooms}), so Absorb stopped.",
    "snapshot_unwritable": ("Couldn't save the house volume before changing it, so Absorb "
                            "didn't change it."),
}


def sentence(code: str, detail: str = "", **fmt: Any) -> str:
    base = SENTENCES.get(code, code)
    try:
        base = base.format(**fmt)
    except (KeyError, IndexError):
        pass
    return f"{base} ({detail})" if detail else base


# ── River's hard block ───────────────────────────────────────────────────────

def read_hard_block(path: str, label: str = HARD_BLOCK_LABEL) -> Optional[str]:
    """None when Absorb may play; else "present" or "unreadable". Her rule,
    verbatim (pretake-endpoint.py `hard_blocked`): the file present refuses
    every label unless the last `allow=` line lists this one. A file that
    exists but can't be read refuses — fail closed."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return None
    except OSError:
        return "unreadable"
    allowed: set[str] = set()
    for line in text.splitlines():
        if line.strip().lower().startswith("allow="):
            allowed = {x.strip() for x in line.split("=", 1)[1].lower().split(",") if x.strip()}
    return None if label in allowed else "present"


# ── the proof ────────────────────────────────────────────────────────────────

@dataclass
class Proof:
    ok: bool
    code: str = ""                      # a refusal code when the capture client is wrong
    detail: str = ""
    audible: list[SnapClient] = field(default_factory=list)
    on_tts: list[SnapClient] = field(default_factory=list)
    capture: Optional[SnapClient] = None


def judge(status: SnapStatus, capture_name: str, capture_pre: Optional[dict],
          tts_stream: str) -> Proof:
    """Is the house silent with the capture untouched? Pure — the whole rule.

    capture_pre None: before the write — the capture client must be there
    and able to hear. Otherwise it must still be exactly as it was."""
    cap = status.find(capture_name)
    if cap is None or not cap.connected:
        return Proof(False, "capture_client_missing", capture_name)
    if capture_pre is None:
        if cap.silent:
            return Proof(False, "capture_client_muted", capture_name, capture=cap)
    elif (cap.percent != int(capture_pre.get("percent", -1))
          or cap.muted != bool(capture_pre.get("muted"))
          or cap.group_muted != bool(capture_pre.get("group_muted"))):
        return Proof(False, "capture_client_reached",
                     f"{capture_name} went from {capture_pre.get('percent')} % "
                     f"{'muted' if capture_pre.get('muted') else 'unmuted'} to "
                     f"{cap.percent} % {'muted' if cap.muted else 'unmuted'}",
                     capture=cap)
    others = [c for c in status.connected() if c.id != cap.id]
    on_tts = [c for c in others if tts_stream and c.stream_id == tts_stream]
    audible = [c for c in others if c not in on_tts and not c.silent]
    detail = ", ".join(f"{c.name or c.id} {c.percent} %" for c in audible)
    return Proof(not audible, "", detail, audible=audible, on_tts=on_tts, capture=cap)


# ── the snapshot (restore contract) on disk ──────────────────────────────────

def load_snapshot(path: Optional[Path] = None) -> Optional[dict]:
    p = path or SNAPSHOT_FILE
    try:
        raw = json.loads(Path(p).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception as exc:                                      # noqa: BLE001
        # Unreadable is NOT absent: something was silenced. Keep it named.
        logger.critical("Absorb: the silence snapshot %s is unreadable (%s) — "
                        "the house volume may still be at 0", p, exc)
        return {"unreadable": True}
    return raw if isinstance(raw, dict) else {"unreadable": True}


def save_snapshot(data: dict, path: Optional[Path] = None) -> None:
    p = Path(path or SNAPSHOT_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=p.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def delete_snapshot(path: Optional[Path] = None) -> None:
    try:
        Path(path or SNAPSHOT_FILE).unlink()
    except FileNotFoundError:
        pass


# ── the guard ────────────────────────────────────────────────────────────────

async def _no_announce() -> None:
    return None


@dataclass
class SilenceDeps:
    audio: Any                                   # api.ha_client.HouseAudio
    snap: Any                                    # services.snapcast_status.SnapcastClient
    hard_block: Callable[[], Optional[str]]
    # Spotify, for "is absorb's own song still playing" before a restore:
    # playback() -> {uri, is_playing, device_name} | None (nothing); raises
    # when Spotify can't say. pause() pauses the Serenity device.
    playback: Callable[[], Awaitable[Optional[dict]]]
    pause: Callable[[], Awaitable[None]]
    device_name: Callable[[], str] = lambda: "Serenity"
    capture_client: str = "Effects Host"
    tts_stream: str = "TTS"
    guest_streams: tuple = ("Guest", "AirPlay")
    announce: Callable[[], Awaitable[None]] = _no_announce
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    monotonic: Callable[[], float] = time.monotonic
    now_ms: Callable[[], int] = lambda: int(time.time() * 1000)
    snapshot_path: Optional[Path] = None


class SilentHouseGuard:
    """services/absorb.py's HouseGuard, for real. See this module's
    docstring for every rule; the methods are the runner's seam."""

    def __init__(self, deps: SilenceDeps) -> None:
        self.d = deps
        self.silence: Optional[dict] = load_snapshot(deps.snapshot_path)
        self.pending: str = ("a previous window's silence was found on disk"
                             if self.silence is not None else "")
        self._next_check = 0.0
        self._next_retry = 0.0

    # ── small reads ─────────────────────────────────────────────────────────

    def holding(self) -> bool:
        """The house volume is (or may still be) lowered by absorb."""
        return self.silence is not None

    def _hard_block_refusal(self) -> Optional[Refusal]:
        hb = self.d.hard_block()
        if hb == "present":
            return ("hard_block", sentence("hard_block"))
        if hb:
            return ("hard_block", sentence("hard_block_unreadable"))
        return None

    def _foreign(self, status: SnapStatus) -> list[str]:
        return [sid for sid, st in status.streams.items()
                if st == "playing" and sid in self.d.guest_streams]

    def _check(self, run, ok: bool, detail: str, **extra) -> None:
        entry = {"at_ms": self.d.now_ms(), "ok": ok, "detail": detail, **extra}
        run.silence_checks.append(entry)
        if len(run.silence_checks) > CHECKS_KEPT:
            del run.silence_checks[:-CHECKS_KEPT]

    def _save(self) -> None:
        save_snapshot(self.silence, self.d.snapshot_path)

    async def _lights(self, run, held: bool) -> None:
        if run is not None and run.lights_held != held:
            run.lights_held = held
            try:
                await self.d.announce()
            except Exception:                                     # noqa: BLE001
                logger.exception("Absorb: could not announce the light stand-down")

    async def _await_volume(self, target: float, settle_s: float) -> tuple[bool, Optional[float]]:
        deadline = self.d.monotonic() + settle_s
        last: Optional[float] = None
        while True:
            reading = await self.d.audio.read()
            last = reading.volume
            if last is not None and abs(last - target) <= VOLUME_TOLERANCE:
                return True, last
            if self.d.monotonic() >= deadline:
                return False, last
            await self.d.sleep(SETTLE_POLL_S)

    # ── the HouseGuard seam ─────────────────────────────────────────────────

    def ready(self, cfg) -> Optional[Refusal]:
        refusal = self._hard_block_refusal()
        if refusal:
            return refusal
        if self.holding():
            return ("restore_pending", sentence("restore_pending", self.pending))
        return None

    async def open(self, run, cfg) -> Optional[Refusal]:
        """Silence the house and prove it. A refusal leaves the house as it
        was (restored and read back) before it is returned."""
        d = self.d
        refusal = self.ready(cfg)
        if refusal:
            return refusal
        reading = await d.audio.read()
        if reading.volume is None:
            return ("ha_unreachable", sentence("ha_unreachable", reading.detail))
        sleeping = True if reading.sleeping is None else reading.sleeping
        if run.sleeping_at_open is None:        # a resume keeps the window's own
            run.sleeping_at_open = sleeping
        if sleeping and not cfg.run_while_sleeping:
            return ("sleeping", sentence("sleeping"))
        try:
            status = await d.snap.read_status()
        except SnapcastUnreadable as exc:
            return ("snapserver_unreadable", sentence("snapserver_unreadable", str(exc)))
        foreign = self._foreign(status)
        if foreign:
            return ("foreign_stream", sentence("foreign_stream", streams=", ".join(foreign)))
        pre = judge(status, d.capture_client, None, d.tts_stream)
        if pre.code:
            return (pre.code, sentence(pre.code, name=d.capture_client))
        cap = pre.capture
        self.silence = {
            "run_id": run.id, "written_ms": d.now_ms(), "stage": "silencing",
            "snap_volume": reading.volume, "via": getattr(d.audio, "via", ""),
            "capture": {**cap.snapshot(), "group_muted": cap.group_muted},
            "muted": [],
        }
        try:
            self._save()
        except OSError as exc:
            self.silence = None
            return ("snapshot_unwritable", sentence("snapshot_unwritable", str(exc)[:80]))
        logger.warning("Absorb: silencing the house (snap_volume %s → 0, %s left alone)",
                       reading.volume, d.capture_client)
        failure = await self._silence_and_prove(run, cfg)
        if failure is not None:
            code, text = failure
            ok, detail = await self._restore()
            self._record_restore(run, ok, detail, f"open refused ({code})")
            if not ok:
                text = f"{text} The volume could not be put back: {detail}"
            return (code, text)
        self.silence["stage"] = "silent"
        try:
            self._save()
        except OSError as exc:      # the "silencing" copy on disk still restores
            logger.warning("Absorb: could not mark the silence snapshot silent: %s", exc)
        run.pre_window = {k: self.silence[k] for k in ("snap_volume", "capture", "muted", "via")}
        run.silent = True
        run.restore_pending = ""
        self._check(run, True, "open: the house is silent", sleeping=sleeping)
        await self._lights(run, True)
        self._next_check = d.monotonic() + cfg.silence_recheck_s
        return None

    async def _silence_and_prove(self, run, cfg) -> Optional[Refusal]:
        d = self.d
        w = await d.audio.set_volume(0)
        if not w.ok:
            return ("volume_unsettable", sentence("volume_unsettable", w.detail))
        ok, last = await self._await_volume(0, SILENCE_SETTLE_S)
        if not ok:
            return ("volume_unsettable",
                    sentence("volume_unsettable", f"snap_volume read back {last}"))
        deadline = d.monotonic() + SILENCE_SETTLE_S
        proof = None
        while True:
            try:
                status = await d.snap.read_status()
            except SnapcastUnreadable as exc:
                return ("snapserver_unreadable", sentence("snapserver_unreadable", str(exc)))
            proof = judge(status, d.capture_client, self.silence["capture"], d.tts_stream)
            if proof.code:
                return (proof.code, sentence(proof.code, proof.detail, name=d.capture_client))
            if proof.ok or d.monotonic() >= deadline:
                break
            await d.sleep(SETTLE_POLL_S)
        if proof.ok:
            return None
        return await self._mute_and_reprove(proof)

    async def _mute_and_reprove(self, proof: Proof) -> Optional[Refusal]:
        """The fallback the proof selects: mute the rooms the volume did not
        reach, each REMEMBERED before its mute is sent, then prove again."""
        d = self.d
        known = {m["id"] for m in self.silence["muted"]}
        for c in proof.audible:
            if c.id not in known:
                self.silence["muted"].append({"id": c.id, "name": c.name,
                                              "percent": c.percent, "muted": False})
                known.add(c.id)
        try:
            self._save()
        except OSError as exc:
            return ("snapshot_unwritable", sentence("snapshot_unwritable", str(exc)[:80]))
        for c in proof.audible:
            try:
                await d.snap.set_client_volume(c.id, c.percent, True)
            except SnapcastUnreadable as exc:
                return ("not_silent", sentence("not_silent", str(exc), rooms=c.name or c.id))
        logger.warning("Absorb: muted %s directly — the house volume did not reach them",
                       ", ".join(c.name or c.id for c in proof.audible))
        try:
            status = await d.snap.read_status()
        except SnapcastUnreadable as exc:
            return ("snapserver_unreadable", sentence("snapserver_unreadable", str(exc)))
        again = judge(status, d.capture_client, self.silence["capture"], d.tts_stream)
        if again.code:
            return (again.code, sentence(again.code, again.detail, name=d.capture_client))
        if not again.ok:
            return ("not_silent", sentence("not_silent", rooms=again.detail))
        return None

    async def recheck(self, run, cfg) -> Optional[Refusal]:
        """While the window runs: the Order 27 conditions, re-proven every
        `silence_recheck_s`. A refusal STOPS the window (the runner
        restores), except "foreign_stream", which is a yield."""
        d = self.d
        if not self.holding():
            return None
        now = d.monotonic()
        if now < self._next_check:
            return None
        self._next_check = now + cfg.silence_recheck_s
        refusal = self._hard_block_refusal()
        if refusal:
            self._check(run, False, refusal[1])
            return refusal
        sleeping = None
        if not cfg.run_while_sleeping:
            reading = await d.audio.read()
            sleeping = True if reading.sleeping is None else reading.sleeping
            if sleeping:
                self._check(run, False, sentence("sleeping"), sleeping=True)
                return ("sleeping", sentence("sleeping"))
        try:
            status = await d.snap.read_status()
        except SnapcastUnreadable as exc:
            text = sentence("snapserver_unreadable", str(exc))
            self._check(run, False, text)
            return ("snapserver_unreadable", text)
        foreign = self._foreign(status)
        if foreign:
            text = sentence("foreign_stream", streams=", ".join(foreign))
            self._check(run, False, text)
            return ("foreign_stream", text)
        proof = judge(status, d.capture_client, self.silence["capture"], d.tts_stream)
        if proof.code:
            text = sentence(proof.code, proof.detail, name=d.capture_client)
            self._check(run, False, text)
            return (proof.code, text)
        detail = "silent"
        if not proof.ok:
            rooms = proof.detail
            failure = await self._mute_and_reprove(proof)
            if failure is not None:
                self._check(run, False, failure[1])
                return failure
            detail = f"muted {rooms} (joined un-silenced)"
        if proof.on_tts:
            detail += "; announcement on " + ", ".join(c.name or c.id for c in proof.on_tts)
            self._next_check = now + min(TTS_RECHECK_S, cfg.silence_recheck_s)
        self._check(run, True, detail, **({"sleeping": sleeping} if sleeping is not None else {}))
        return None

    async def yield_now(self, run) -> dict:
        """His music took over: the volume FIRST, then the lights."""
        out = {"ok": True, "detail": "the house was not silenced", "restored_ms": self.d.now_ms()}
        if self.holding():
            ok, detail = await self._restore()
            out = {"ok": ok, "detail": detail, "restored_ms": self.d.now_ms()}
            self._record_restore(run, ok, detail, "yield")
        await self._lights(run, False)
        return out

    async def close(self, run, reason: str, ours: frozenset = frozenset()) -> None:
        """Every ending. Never restores the volume over absorb's own song."""
        if self.holding():
            await self._restore_when_safe(run, ours, f"close ({reason})")
        else:
            await self._lights(run, False)

    async def retry_pending(self, run, ours: frozenset = frozenset()) -> Optional[dict]:
        """No window running and the house may still be silent — a crash, or
        a restore that did not read back. Tried at once (the first tick of a
        new process), then every RETRY_PENDING_S."""
        if not self.holding():
            return None
        now = self.d.monotonic()
        if now < self._next_retry:
            return None
        self._next_retry = now + RETRY_PENDING_S
        return await self._restore_when_safe(run, ours, "pending")

    # ── restore ─────────────────────────────────────────────────────────────

    async def _ours_may_play(self, ours: frozenset) -> Optional[bool]:
        """True if absorb's own song may still be playing on Serenity (or
        Spotify can't say), False if confirmed not."""
        try:
            pb = await self.d.playback()
        except Exception:                                         # noqa: BLE001
            return True
        if not pb or not pb.get("is_playing"):
            return False
        if str(pb.get("device_name", "")).lower() != self.d.device_name().lower():
            return False
        return pb.get("uri") in ours

    async def _restore_when_safe(self, run, ours: frozenset, why: str) -> dict:
        if await self._ours_may_play(ours):
            try:
                await self.d.pause()
            except Exception as exc:                              # noqa: BLE001
                logger.warning("Absorb: pause before restoring failed: %s", exc)
            if await self._ours_may_play(ours):
                detail = ("Absorb's song may still be playing on Serenity, so the house stays "
                          "silent until it stops")
                self.pending = detail
                logger.critical("Absorb: volume NOT restored (%s): %s", why, detail)
                if run is not None:
                    run.restore_pending = detail
                return {"ok": False, "detail": detail}
        ok, detail = await self._restore()
        self._record_restore(run, ok, detail, why)
        await self._lights(run, False)
        return {"ok": ok, "detail": detail}

    def _record_restore(self, run, ok: bool, detail: str, why: str) -> None:
        if run is None:
            return
        run.restore = {"at_ms": self.d.now_ms(), "ok": ok, "detail": detail, "why": why}
        run.restore_pending = "" if ok else detail
        if ok:
            run.silent = False

    async def _restore(self) -> tuple[bool, str]:
        """Put back everything absorb changed and READ IT BACK. The snapshot
        file is deleted only when all of it confirmed."""
        d, s = self.d, self.silence
        if s is None:
            return True, "nothing to restore"
        if s.get("unreadable"):
            detail = ("the silence snapshot on disk is unreadable — the house volume must be "
                      "checked by hand")
            self.pending = detail
            logger.critical("Absorb: %s", detail)
            return False, detail
        s["stage"] = "restoring"
        problems: list[str] = []
        target = float(s.get("snap_volume") or 0)
        w = await d.audio.set_volume(int(round(target)))
        if not w.ok:
            problems.append(f"snap_volume not written ({w.detail})")
        muted = list(s.get("muted") or [])
        cap = s.get("capture") or {}
        try:
            status = await d.snap.read_status()
            for m in muted:
                c = status.find(m["id"])
                if c is not None and not c.muted:
                    continue
                percent = c.percent if c is not None else int(m.get("percent") or 0)
                await d.snap.set_client_volume(m["id"], percent, False)
        except SnapcastUnreadable as exc:
            problems.append(f"rooms not unmuted ({exc})")
        ok_vol, last = await self._await_volume(target, RESTORE_SETTLE_S)
        if not ok_vol:
            problems.append(f"snap_volume reads {last}, not {target:g}")
        # read the rooms back: the ones absorb muted unmuted, the capture
        # client exactly as it was (put back if the volume control moved it)
        deadline = d.monotonic() + RESTORE_SETTLE_S
        while True:
            try:
                status = await d.snap.read_status()
            except SnapcastUnreadable as exc:
                problems.append(f"rooms unreadable after restore ({exc})")
                break
            still = [m.get("name") or m["id"] for m in muted
                     if (status.find(m["id"]) or SnapClient(m["id"], "", False, 0, False)).muted]
            c = status.find(cap.get("id", "")) if cap else None
            cap_off = c is not None and (c.percent != int(cap.get("percent", -1))
                                         or c.muted != bool(cap.get("muted")))
            if not still and not cap_off:
                break
            if d.monotonic() >= deadline:
                if cap_off:
                    try:
                        await d.snap.set_client_volume(c.id, int(cap["percent"]), bool(cap["muted"]))
                        status = await d.snap.read_status()
                        c = status.find(c.id)
                        cap_off = c is None or c.percent != int(cap["percent"]) \
                            or c.muted != bool(cap["muted"])
                    except SnapcastUnreadable as exc:
                        problems.append(f"capture client not put back ({exc})")
                    if cap_off:
                        problems.append(f"{d.capture_client} is not back at {cap.get('percent')} %")
                if still:
                    problems.append("still muted: " + ", ".join(still))
                break
            await d.sleep(SETTLE_POLL_S)
        if problems:
            detail = "; ".join(problems)
            s["stage"] = "restore_failed"
            s["last_error"] = detail
            try:
                self._save()
            except OSError:
                pass
            self.pending = detail
            logger.critical("Absorb: the house was NOT put back as it was: %s", detail)
            return False, detail
        delete_snapshot(d.snapshot_path)
        self.silence = None
        self.pending = ""
        detail = f"snap_volume back at {target:g}" + (
            f", unmuted {', '.join(m.get('name') or m['id'] for m in muted)}" if muted else "")
        logger.warning("Absorb: the house is back — %s", detail)
        return True, detail


def production_guard(*, gateway: Any, to_thread: Callable[..., Awaitable[Any]],
                     device_name: Callable[[], str],
                     announce: Callable[[], Awaitable[None]]) -> SilentHouseGuard:
    from api import ha_client
    from config import settings
    from services import snapcast_status

    async def playback() -> Optional[dict]:
        return await to_thread(gateway.current_playback)

    async def pause() -> None:
        device_id = await to_thread(gateway.device_id, device_name())
        if device_id:
            await to_thread(gateway.pause, device_id)

    return SilentHouseGuard(SilenceDeps(
        audio=ha_client.from_settings(),
        snap=snapcast_status.from_settings(),
        hard_block=lambda: read_hard_block(settings.absorb_audio_hard_block_path),
        playback=playback, pause=pause, device_name=device_name,
        capture_client=settings.absorb_capture_client_name,
        tts_stream=settings.absorb_tts_stream_id,
        guest_streams=tuple(settings.guest_streams or ()),
        announce=announce,
    ))
