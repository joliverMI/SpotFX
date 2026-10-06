"""DROP SEQUENCES — the detected charge/lull/drop of each song, plus HIS
edits to them (drop-detection plan, phase 2; report section 7.1 and the
plan page's "How edits are kept, and what wins" table).

ONE SMALL FILE (`storage/spectra/drop_sequences.json`), never triggers.json.
Storing a sequence as three ordinary generated triggers was rejected in the
plan for the reasons the Light Show's High/Low cues already gave
(show_cues.py): a human edit stamps a trigger `source="authored"`, which
under "My triggers only" silences that song's whole analysed show; the
three would be unlinked; and every edit rewrites the ~9.5 MB trigger file.
Per song the file holds:

  "detected"   what the detector found (drop_detector.SongDetection) and
               the STAMP it was found under. A regenerable cache: nothing
               about it is his, and a stale stamp replaces it wholesale.
  "overrides"  ONLY what he changed, keyed by the detection it was made
               against ("drop:<ms>", the drop time the detector found).
  "added"      sequences he placed himself, whole.

WHEN DETECTION RUNS. On a song's first play (`on_song_played`, wired off
services/engine.py's song-change edge beside the analysed cues' own
auto-generation) and again whenever its STAMP goes stale: the detector
version, the two tier thresholds (RoomControlState.drop_confident_score /
drop_suggested_score) and the song's own analysis inputs (the beat
analysis's analyzed_at, the audio shape's content, the song's length).
Content values, never file times — a capture sidecar rewritten with the
same numbers does not re-detect. A GET of the view runs the same check
(read-through), so a song never played since this shipped is detected the
first time anything asks.

HOW EDITS ARE KEPT, AND WHAT WINS (the plan's table, each a test):
  nothing       nothing is saved; the sequence is worked out from the
                song each time and may move if the detector improves.
  confirm       {"state": "confirmed"} against the drop it was found at.
                It stays confirmed; if a re-detection moves the drop by
                more than a beat the view sets `needs_review` (keep his,
                or take the new place — his call, phase 4).
  drag          that handle's time only; the others stay automatic. His
                time always wins; `auto` keeps the detector's own place.
  lull/charge   off flags: that member is gone, the rest stay.
  dismiss       "not a drop": never offered again within two beats.
  add           the whole sequence, his; re-detection never touches it.

EDITING (phase 4). Every edit is one locked read-modify-write of this
song's entry that returns HIS EDITS before and after (`EditResult`):
{"overrides", "added"} — the detection is never part of it. That pair is
the whole of undo/redo: `restore_edits` puts one side back, and refuses
(`EditConflict`) when his edits are no longer the other side (changed in
another tab), so an undo can never silently overwrite a newer edit.
`resolve_review` answers the "the analysis moved it" question (keep his
place, or take the new one). A whole-sequence move is ONE edit
(`set_handles`). Nothing here fires anything: drop_firing.py decides that.

KEYS SURVIVE RE-DETECTION. A re-detected sequence keeps an override whose
key's drop lies within MATCH_BEATS (two beats) of its new drop — nearest
first, one override per detection. An override nothing matches any more
is kept as a fact he stated: a dismissal stays a dismissal; a confirmed
or edited sequence stays HIS, drawn from the snapshot taken when he first
touched it plus his own handle times (`detection_lost`, `needs_review`).

HIS OWN TRIGGERS WIN (report section 7.2). A detected sequence whose drop
sits within MATCH_BEATS of one of his own enabled charge, lull or drop
triggers stands down as `matches_yours` — even when confirmed, because his
own trigger already fires there. An added sequence is his and never stands
down.

STATES, in precedence order: dismissed > matches_yours > edited >
confirmed > confident | suggested; and added. This module only says what
each sequence IS; what fires, and the protected window around each, is
spectra/services/drop_firing.py (phase 5).

EVERY TIME IS SONG TIME, the frame his triggers are in.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import os
import tempfile
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

import numpy as np

from spectra import config
from spectra.services import analysis_reader, drop_detector

logger = logging.getLogger(__name__)

MATCH_BEATS = 2.0
"""Two beats: how near a re-detected drop must sit to keep his override,
how near a detection may come to a dismissal before it is blocked, and how
near one of his own phase triggers must sit for a detection to stand down."""

REVIEW_BEATS = 1.0
"""A confirmed or edited sequence whose detection has since moved further
than this asks him to keep his or take the new place."""

NEAR_BEATS = 1.0
"""What of his sits "here" — the review list's "you have a flare here"."""

AUTHORED_REACH_MS = 45_000
"""Grouping his own charge/lull/drop into sequences: a lull or charge
belongs to the next drop within this reach (the testbed's own grouping)."""

STATE_CONFIDENT = drop_detector.TIER_CONFIDENT
STATE_SUGGESTED = drop_detector.TIER_SUGGESTED
STATE_CONFIRMED = "confirmed"
STATE_EDITED = "edited"
STATE_ADDED = "added"
STATE_MATCHES_YOURS = "matches_yours"
STATE_DISMISSED = "dismissed"

HANDLES = ("charge", "lull", "drop")
PHASE_CLASSES = ("charge", "lull", "drop")


# ── the file ───────────────────────────────────────────────────────────────

_lock = threading.RLock()
_cache: Optional[tuple[Optional[tuple], dict]] = None


def _signature() -> Optional[tuple]:
    try:
        st = os.stat(config.DROP_SEQUENCES_FILE)
        return (str(config.DROP_SEQUENCES_FILE), st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _read() -> dict:
    """The whole file, parsed — cached on the file's own stat, READ-ONLY:
    a writer deep-copies before changing anything."""
    global _cache
    sig = _signature()
    if _cache is not None and _cache[0] == sig and sig is not None:
        return _cache[1]
    data: dict = {}
    if sig is not None:
        try:
            with open(config.DROP_SEQUENCES_FILE, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            data = raw if isinstance(raw, dict) else {}
        except Exception:                                # noqa: BLE001
            logger.exception("drop sequences: unreadable store %s",
                             config.DROP_SEQUENCES_FILE)
            data = {}
    _cache = (sig, data)
    return data


def _write(data: dict) -> None:
    global _cache
    path = str(config.DROP_SEQUENCES_FILE)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".",
                               prefix=".drop_sequences", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    _cache = (_signature(), data)


def _now_ms() -> int:
    return int(time.time() * 1000)


def revision() -> Optional[tuple]:
    """The store's revision (its file stat), for a reader that caches a
    view between ticks (trigger_engine): any edit or detection changes it."""
    return _signature()


def all_stored() -> dict:
    """Every song's raw entry, {uri: entry}. Read-only."""
    return _read()


def stored(uri: str) -> dict:
    """This song's raw entry ({} when there is none). Read-only."""
    entry = _read().get(uri)
    return entry if isinstance(entry, dict) else {}


def _mutate(uri: str, fn) -> Any:
    """Read-modify-write one song's entry under the lock. `fn(entry)`
    changes the (copied) entry in place and returns the caller's result."""
    return _mutate_tracked(uri, fn).result


@dataclass
class EditResult:
    """What one edit returned, plus HIS EDITS before and after it — the
    pair an undo/redo puts back (`restore_edits`)."""
    result: Any
    before: dict
    after: dict


def edits_of(entry: dict) -> dict:
    """HIS edits in an entry: overrides and added sequences, never the
    detection (a regenerable cache). Always both keys."""
    return {"overrides": copy.deepcopy(entry.get("overrides") or {}),
            "added": copy.deepcopy(entry.get("added") or [])}


def edits_rev(edits: dict) -> str:
    """A short fingerprint of his edits, so an undo can say "only if
    nothing changed since"."""
    norm = {"overrides": edits.get("overrides") or {}, "added": edits.get("added") or []}
    blob = json.dumps(norm, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha1(blob).hexdigest()[:16]


def _mutate_tracked(uri: str, fn) -> EditResult:
    with _lock:
        data = copy.deepcopy(_read())
        entry = data.get(uri)
        if not isinstance(entry, dict):
            entry = {}
        before = edits_of(entry)
        result = fn(entry)
        after = edits_of(entry)
        if entry:
            data[uri] = entry
        else:
            data.pop(uri, None)
        _write(data)
        return EditResult(result=result, before=before, after=after)


# ── the stamp ──────────────────────────────────────────────────────────────

def _thresholds(controls: Any = None) -> tuple[float, float]:
    if controls is None:
        from spectra.services import room_controls
        controls = room_controls.load_room_controls()
    return (float(controls.drop_confident_score), float(controls.drop_suggested_score))


def song_inputs(uri: str) -> dict:
    """The song-specific half of the stamp: content values of what
    detection reads. Raises drop_detector.Unavailable."""
    stem = analysis_reader.stem_for_uri(uri)
    if stem is None:
        raise drop_detector.Unavailable("this song has no captured audio shape yet")
    npz_path = config.AUDIO_SHAPES_DIR / f"{stem}.npz"
    doc = analysis_reader.librosa_analysis_for_stem(stem)
    if not doc:
        raise drop_detector.Unavailable("this song has no beat analysis yet")
    try:
        z = np.load(npz_path)
        t = z["timestamps_ms"]
        low = z["rms_low"]
        shape = [int(len(t)), int(t[0]) if len(t) else None,
                 int(t[-1]) if len(t) else None, round(float(np.sum(low)), 4)]
    except Exception as exc:                             # noqa: BLE001
        raise drop_detector.Unavailable(
            f"this song's audio shape could not be read ({exc})") from exc
    sidecar = analysis_reader.capture_sidecar(uri) or {}
    return {
        "analyzed_at": doc.get("analyzed_at"),
        "tempo_bpm": doc.get("tempo_bpm"),
        "n_beats": len(doc.get("beats") or []),
        "shape": shape,
        "duration_ms": sidecar.get("duration_ms"),
    }


def stamp_for(uri: str, controls: Any = None, *,
              inputs: Optional[dict] = None) -> str:
    """THE stamp a detection of `uri` made right now carries: 16 hex chars
    of a SHA-1 over the detector version, the two thresholds and the
    song's own inputs. Raises drop_detector.Unavailable."""
    confident, suggested = _thresholds(controls)
    payload = {
        "version": drop_detector.DETECTOR_VERSION,
        "settings": {"confident": confident, "suggested": suggested},
        "song": inputs if inputs is not None else song_inputs(uri),
    }
    blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha1(blob).hexdigest()[:16]


# ── detection, stored ──────────────────────────────────────────────────────

_detect_lock = threading.Lock()


def ensure_detected(uri: str, controls: Any = None, *, force: bool = False) -> dict:
    """Detect `uri` when it has no stored detection or its stamp is stale
    (or always, with `force` — the review list's "Re-detect"), and store
    the result (one write; his overrides and added sequences are never
    touched). Returns {"status": "fresh" | "detected" | "unavailable",
    ...}. Synchronous file and analysis I/O — call it off the event
    loop."""
    with _detect_lock:
        try:
            with analysis_reader.memoized_reads():
                inputs = song_inputs(uri)
                stamp = stamp_for(uri, controls, inputs=inputs)
                current = stored(uri).get("detected") or {}
                if current.get("stamp") == stamp and not force:
                    return {"uri": uri, "status": "fresh", "stamp": stamp}
                confident, suggested = _thresholds(controls)
                det = drop_detector.detect_uri(
                    uri, confident_score=confident, suggested_score=suggested)
        except drop_detector.Unavailable as exc:
            return {"uri": uri, "status": "unavailable", "reason": str(exc)}
        record = {**det.as_dict(), "stamp": stamp, "detected_at": _now_ms()}

        def put(entry: dict) -> None:
            entry["detected"] = record
        _mutate(uri, put)
    _changed(uri)
    logger.info("drop detection: %s — %d sequence(s) under stamp %s",
                uri, len(det.sequences), stamp)
    return {"uri": uri, "status": "detected", "stamp": stamp,
            "sequences": len(det.sequences)}


_in_flight: set[str] = set()


def on_song_played(uri: Optional[str]) -> None:
    """The song-change edge (services/engine.py): detect in a worker
    thread, fire-and-forget — never awaited, never raises into the engine.
    A song already detected under a fresh stamp costs one stamp check."""
    if not uri or uri in _in_flight:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    _in_flight.add(uri)

    async def run() -> None:
        try:
            await asyncio.to_thread(ensure_detected, uri)
        except Exception:                                # noqa: BLE001
            logger.exception("drop detection failed for %s", uri)
        finally:
            _in_flight.discard(uri)
    loop.create_task(run())


def reset() -> None:
    """Tests."""
    global _cache
    _cache = None
    _in_flight.clear()


# ── his edits ──────────────────────────────────────────────────────────────

class SequenceNotFound(LookupError):
    """No sequence answers to that key on this song."""


class InvalidEdit(ValueError):
    """The edit would break charge < lull < drop or name a bad handle."""


def _beat_ms(entry: dict) -> float:
    det = entry.get("detected") or {}
    try:
        b = float(det.get("beat_ms") or 0.0)
    except (TypeError, ValueError):
        b = 0.0
    return b if b > 0 else 500.0


def _detected_list(entry: dict) -> list[dict]:
    return list((entry.get("detected") or {}).get("sequences") or [])


def _snapshot(seq: dict) -> dict:
    return {k: seq.get(k) for k in ("drop_ms", "lull_ms", "charge_ms", "score", "tier")}


def _resolve_detected_key(entry: dict, key: str) -> tuple[str, Optional[dict]]:
    """The override key an edit to `key` belongs to, and the detection it
    is made against (None when only an override answers). An existing
    override within MATCH_BEATS wins, so one detection never carries two."""
    k_ms = drop_detector.key_ms(key)
    if k_ms is None:
        raise SequenceNotFound(f"not a detection key: {key!r}")
    reach = MATCH_BEATS * _beat_ms(entry)
    overrides = entry.get("overrides") or {}
    okey = key if key in overrides else None
    if okey is None:
        near = sorted((abs(drop_detector.key_ms(k) - k_ms), k) for k in overrides
                      if drop_detector.key_ms(k) is not None
                      and abs(drop_detector.key_ms(k) - k_ms) <= reach)
        okey = near[0][1] if near else None
    dets = _detected_list(entry)
    target_ms = drop_detector.key_ms(okey) if okey else k_ms
    near_det = sorted((abs(int(d["drop_ms"]) - target_ms), i) for i, d in enumerate(dets)
                      if abs(int(d["drop_ms"]) - target_ms) <= reach)
    det = dets[near_det[0][1]] if near_det else None
    if okey is None and det is None:
        raise SequenceNotFound(f"no sequence at {key!r} on this song")
    return (okey or (det["key"] if det else key)), det


def _effective(base: dict, ov: dict) -> dict:
    out = {}
    for h in HANDLES:
        v = ov.get(f"{h}_ms")
        out[h] = int(v) if v is not None else base.get(f"{h}_ms")
    for h in ("lull", "charge"):
        if ov.get(f"{h}_off"):
            out[h] = None
    return out


def _check_order(times: dict) -> None:
    present = [(h, times[h]) for h in HANDLES if times.get(h) is not None]
    for (h1, t1), (h2, t2) in zip(present, present[1:]):
        if t2 - t1 < drop_detector.RAMP_FLOOR_MS:
            raise InvalidEdit(
                f"{h1} must sit at least {drop_detector.RAMP_FLOOR_MS} ms before {h2}")
    if times.get("drop") is None:
        raise InvalidEdit("a sequence needs its drop")


class EditConflict(RuntimeError):
    """An undo/redo found his edits changed since (another tab, another
    edit): nothing is restored."""


def _override(entry: dict, key: str) -> tuple[str, Optional[dict], dict]:
    """The override an edit to detected `key` lands in (created on first
    touch, with a snapshot of the detection it was made against)."""
    okey, det = _resolve_detected_key(entry, key)
    ovs = entry.setdefault("overrides", {})
    ov = ovs.setdefault(okey, {"detected": _snapshot(det) if det else None})
    return okey, det, ov


def _is_added(key: str) -> bool:
    return isinstance(key, str) and key.startswith("added:")


def _op_confirm(entry: dict, key: str) -> str:
    if _is_added(key):
        _find_added(entry, key)
        return key                      # an added sequence is his already
    okey, _det, ov = _override(entry, key)
    ov["state"] = STATE_CONFIRMED
    ov["at"] = _now_ms()
    return okey


def _op_dismiss(entry: dict, key: str) -> str:
    """"Not a drop". On a sequence he added himself, it removes it."""
    if _is_added(key):
        if not _op_remove_added(entry, key):
            raise SequenceNotFound(f"no added sequence {key!r} on this song")
        return key
    okey, _det, ov = _override(entry, key)
    ov["state"] = STATE_DISMISSED
    ov["at"] = _now_ms()
    return okey


def _op_reset(entry: dict, key: str) -> bool:
    try:
        okey, _ = _resolve_detected_key(entry, key)
    except SequenceNotFound:
        return False
    ovs = entry.get("overrides") or {}
    if okey not in ovs:
        return False
    ovs.pop(okey)
    if not ovs:
        entry.pop("overrides", None)
    return True


def _check_handle_values(handles: dict) -> dict:
    out = {}
    for h, ms in handles.items():
        if h not in HANDLES:
            raise InvalidEdit(f"handle must be one of {HANDLES}")
        if ms is not None and int(ms) < 0:
            raise InvalidEdit("a handle cannot sit before the song starts")
        out[h] = int(ms) if ms is not None else None
    if not out:
        raise InvalidEdit("name at least one handle to move")
    return out


def _op_set_handles(entry: dict, key: str, handles: dict) -> str:
    """Move one or more handles of a sequence in ONE edit. `None` for a
    handle = back to the detector's place (on an added sequence: remove
    that member; the drop can never be removed). The rest stay as they
    are. Order is enforced: charge < lull < drop, RAMP_FLOOR_MS apart."""
    handles = _check_handle_values(handles)
    if _is_added(key):
        rec = _find_added(entry, key)
        trial = {h: rec.get(f"{h}_ms") for h in HANDLES}
        offs = {h: bool(rec.get(f"{h}_off")) for h in ("lull", "charge")}
        for h, ms in handles.items():
            if h == "drop" and ms is None:
                raise InvalidEdit("a sequence needs its drop")
            trial[h] = ms
            if h in offs and ms is not None:
                offs[h] = False
        eff = dict(trial)
        for h, off in offs.items():
            if off:
                eff[h] = None
        _check_order(eff)
        for h in HANDLES:
            rec[f"{h}_ms"] = trial[h]
        for h, off in offs.items():
            if off:
                rec[f"{h}_off"] = True
            else:
                rec.pop(f"{h}_off", None)
        rec["at"] = _now_ms()
        return key
    okey, det, ov = _override(entry, key)
    base = det or ov.get("detected") or {}
    trial_ov = dict(ov)
    for h, ms in handles.items():
        trial_ov[f"{h}_ms"] = ms
        if ms is not None and h in ("lull", "charge"):
            trial_ov[f"{h}_off"] = False
    _check_order(_effective(base, trial_ov))
    ov.update(trial_ov)
    ov["at"] = _now_ms()
    return okey


def _op_member_off(entry: dict, key: str, handle: str, off: bool) -> str:
    if handle not in ("lull", "charge"):
        raise InvalidEdit("only the lull or the charge can be switched off")
    if _is_added(key):
        rec = _find_added(entry, key)
        if not off:
            eff = {h: rec.get(f"{h}_ms") for h in HANDLES}
            other = "charge" if handle == "lull" else "lull"
            if rec.get(f"{other}_off"):
                eff[other] = None
            if eff[handle] is None:
                raise InvalidEdit(f"this sequence has no {handle} to switch on — add one")
            _check_order(eff)
            rec.pop(f"{handle}_off", None)
        else:
            rec[f"{handle}_off"] = True
        rec["at"] = _now_ms()
        return key
    okey, det, ov = _override(entry, key)
    if not off:
        base = det or ov.get("detected") or {}
        trial = {**ov, f"{handle}_off": False}
        eff = _effective(base, trial)
        if eff[handle] is None:
            raise InvalidEdit(f"this sequence has no {handle} to switch on — add one")
        _check_order(eff)
    ov[f"{handle}_off"] = bool(off)
    ov["at"] = _now_ms()
    return okey


def _find_added(entry: dict, key: str) -> dict:
    for rec in entry.get("added") or []:
        if rec.get("id") == key:
            return rec
    raise SequenceNotFound(f"no added sequence {key!r} on this song")


def _op_remove_added(entry: dict, key: str) -> bool:
    recs = entry.get("added") or []
    keep = [r for r in recs if r.get("id") != key]
    if len(keep) == len(recs):
        return False
    if keep:
        entry["added"] = keep
    else:
        entry.pop("added", None)
    return True


def _op_resolve_review(entry: dict, key: str, choice: str) -> str:
    """"The analysis moved it": `keep` pins his place (the times he last
    saw) and stops asking; `take` moves his sequence to where the analysis
    puts it now (his confirm and his lull/charge off stay). On a sequence
    the analysis no longer finds, `take` lets it go (the override is
    forgotten)."""
    if choice not in ("keep", "take"):
        raise InvalidEdit("choose keep or take")
    okey, det = _resolve_detected_key(entry, key)
    ovs = entry.get("overrides") or {}
    ov = ovs.get(okey)
    if not isinstance(ov, dict):
        raise SequenceNotFound(f"nothing of yours to review at {key!r}")
    old = ov.get("detected") or {}
    if det is None:                                    # the analysis lost it
        if choice == "take":
            ovs.pop(okey)
            if not ovs:
                entry.pop("overrides", None)
        else:
            ov["kept"] = True
            ov["at"] = _now_ms()
        return okey
    if choice == "keep":
        pinned = []
        for h in HANDLES:
            if ov.get(f"{h}_ms") is None and old.get(f"{h}_ms") is not None:
                ov[f"{h}_ms"] = int(old[f"{h}_ms"])
                pinned.append(h)
        try:
            _check_order(_effective(det, ov))
        except InvalidEdit:
            # an old automatic lull/charge no longer fits: pin only the drop
            for h in pinned:
                if h != "drop":
                    ov.pop(f"{h}_ms", None)
    else:
        for h in HANDLES:
            ov.pop(f"{h}_ms", None)
    ov["detected"] = _snapshot(det)
    ov.pop("kept", None)
    ov["at"] = _now_ms()
    return okey


def _place(uri: str, entry: dict, handle: str, drop_ms: int,
           lull_ms: Optional[int]) -> Optional[int]:
    """Where the detector's own placement rules put a lull or a charge for
    this drop (report section 6), or None when the song cannot be read.
    A lull with no break before the drop falls back to two beats before
    it, snapped to a beat."""
    try:
        analysis = drop_detector.analyse(uri)
    except drop_detector.Unavailable:
        return None
    if handle == "lull":
        got = drop_detector.place_lull(analysis.prep, drop_ms)
        if got is None:
            got = drop_detector._to_beat(analysis.song, drop_ms - 2 * analysis.song.beat_len)
        return int(got)
    return int(drop_detector.place_charge(analysis.prep, lull_ms if lull_ms is not None else drop_ms))


def _op_fill(entry: dict, key: str, handle: str, placed: Optional[int]) -> str:
    """Add a lull or a charge the detector's own rules placed (`_place`).
    This is HIS explicit press — unlike `_added_record`'s automatic fill
    (which quietly leaves a too-close member out), a placement that would
    not hold the order rule is refused and names why, rather than silently
    doing nothing to a press he made on purpose."""
    if handle not in ("lull", "charge"):
        raise InvalidEdit("only a lull or a charge can be added to a sequence")
    if placed is None:
        raise InvalidEdit("this song's audio shape cannot be read to place one")
    if handle == "lull":
        drop_ms = _current_times(entry, key).get("drop")
        if drop_ms is not None and int(drop_ms) - int(placed) < drop_detector.RAMP_FLOOR_MS:
            raise InvalidEdit(
                "there is no room for a lull before this drop: it would sit "
                f"closer than {drop_detector.RAMP_FLOOR_MS} ms")
    return _op_set_handles(entry, key, {handle: placed})


def _current_times(entry: dict, key: str) -> dict:
    if _is_added(key):
        rec = _find_added(entry, key)
        out = {h: rec.get(f"{h}_ms") for h in HANDLES}
        for h in ("lull", "charge"):
            if rec.get(f"{h}_off"):
                out[h] = None
        return out
    okey, det = _resolve_detected_key(entry, key)
    ov = (entry.get("overrides") or {}).get(okey) or {}
    return _effective(det or ov.get("detected") or {}, ov)


def _op_add(entry: dict, rec: dict) -> str:
    _check_order({h: rec[f"{h}_ms"] for h in HANDLES})
    entry.setdefault("added", []).append(rec)
    return rec["id"]


def _added_record(uri: str, drop_ms: int, lull_ms: Optional[int],
                  charge_ms: Optional[int], fill: bool) -> dict:
    drop_ms = int(drop_ms)
    if drop_ms < 0:
        raise InvalidEdit("a drop cannot sit before the song starts")
    if fill and (lull_ms is None or charge_ms is None):
        try:
            analysis = drop_detector.analyse(uri)
            if lull_ms is None:
                lull_ms = drop_detector.place_lull(analysis.prep, drop_ms)
            if charge_ms is None:
                charge_ms = drop_detector.place_charge(
                    analysis.prep, lull_ms if lull_ms is not None else drop_ms)
        except drop_detector.Unavailable:
            pass
    # A filled lull or charge never reaches back past the drop before this
    # one (a quick re-drop): the build would start inside the previous
    # sequence's payoff. Left out rather than overlapped — his to add.
    if fill:
        prev = _previous_drop_ms(uri, drop_ms)
        if prev is not None:
            if lull_ms is not None and int(lull_ms) <= prev:
                lull_ms = None
            if charge_ms is not None and int(charge_ms) <= prev:
                charge_ms = None
    # a filled lull that lands too near the drop itself is left out, not
    # refused — a high-tempo song's own break can legally sit closer to
    # the drop than the engine's own ramp floor
    if lull_ms is not None and fill:
        if drop_ms - int(lull_ms) < drop_detector.RAMP_FLOOR_MS:
            lull_ms = None
    # a filled charge that lands too near its partner is left out, not refused
    if charge_ms is not None:
        upper = lull_ms if lull_ms is not None else drop_ms
        if upper - int(charge_ms) < drop_detector.RAMP_FLOOR_MS and fill:
            charge_ms = None
    return {"id": f"added:{uuid.uuid4().hex[:10]}", "drop_ms": drop_ms,
            "lull_ms": int(lull_ms) if lull_ms is not None else None,
            "charge_ms": int(charge_ms) if charge_ms is not None else None,
            "at": _now_ms()}


def _previous_drop_ms(uri: str, drop_ms: int) -> Optional[int]:
    """The latest drop before `drop_ms` on this song — a detected or added
    sequence that is not dismissed, or one of his own drop triggers."""
    try:
        v = view(uri)
    except Exception:                                    # noqa: BLE001
        return None
    drops = [int(s["drop_ms"]) for s in v.get("sequences") or []
             if s.get("state") != STATE_DISMISSED]
    drops += [int(g["drop"]["timestamp_ms"]) for g in v.get("authored") or [] if g.get("drop")]
    earlier = [d for d in drops if d < drop_ms - drop_detector.RAMP_FLOOR_MS]
    return max(earlier) if earlier else None


def _confident_keys(uri: str) -> list[str]:
    return [s["key"] for s in view(uri)["sequences"]
            if s["origin"] == "detected" and s["state"] == STATE_CONFIDENT]


def _op_restore(entry: dict, edits: dict, expect_rev: Optional[str]) -> str:
    current = edits_of(entry)
    if expect_rev is not None and edits_rev(current) != expect_rev:
        raise EditConflict("your drop-sequence edits on this song changed since — "
                           "nothing was undone; reload and try again")
    ovs = edits.get("overrides") if isinstance(edits, dict) else None
    added = edits.get("added") if isinstance(edits, dict) else None
    if not isinstance(ovs, dict) or not isinstance(added, list):
        raise InvalidEdit("edits must carry an overrides object and an added list")
    if ovs:
        entry["overrides"] = copy.deepcopy(ovs)
    else:
        entry.pop("overrides", None)
    if added:
        entry["added"] = copy.deepcopy(added)
    else:
        entry.pop("added", None)
    return edits_rev(edits_of(entry))


# ── the public edits (each one locked read-modify-write) ──────────────────

def confirm(uri: str, key: str) -> str:
    """"This one is confirmed", against the drop it was found at. Returns
    the override key."""
    return _mutate(uri, lambda e: _op_confirm(e, key))


def dismiss(uri: str, key: str) -> str:
    """"Not a drop": never offered again within two beats."""
    return _mutate(uri, lambda e: _op_dismiss(e, key))


def reset_to_detected(uri: str, key: str) -> bool:
    """"Back to detected": forget every edit to this detection."""
    return _mutate(uri, lambda e: _op_reset(e, key))


def set_handle(uri: str, key: str, handle: str, ms: Optional[int]) -> str:
    """Move one handle (see `set_handles`)."""
    return _mutate(uri, lambda e: _op_set_handles(e, key, {handle: ms}))


def set_handles(uri: str, key: str, handles: dict) -> str:
    """Move one or more handles in one edit (a whole-sequence move)."""
    return _mutate(uri, lambda e: _op_set_handles(e, key, handles))


def set_member_off(uri: str, key: str, handle: str, off: bool) -> str:
    """Lull off / charge off (and back on) on a detected or added sequence."""
    return _mutate(uri, lambda e: _op_member_off(e, key, handle, off))


def add(uri: str, drop_ms: int, *, lull_ms: Optional[int] = None,
        charge_ms: Optional[int] = None, fill: bool = True) -> str:
    """A sequence he places himself. With `fill`, a missing lull and charge
    are placed by the detector's own rules from the song's audio shape
    (the lull is left out when there is no break before his drop, and the
    charge then builds to the drop; both are left out when the song cannot
    be analysed). Returns its key ("added:<id>")."""
    rec = _added_record(uri, drop_ms, lull_ms, charge_ms, fill)
    return _mutate(uri, lambda e: _op_add(e, rec))


def remove_added(uri: str, key: str) -> bool:
    return _mutate(uri, lambda e: _op_remove_added(e, key))


def edits(uri: str) -> dict:
    """His edits on this song: {"overrides", "added", "rev"}."""
    out = edits_of(stored(uri))
    out["rev"] = edits_rev(out)
    return out


def _changed(uri: str) -> None:
    """The song's sequences changed (a detection or one of his edits): the
    trigger clock re-plans its analysed flares around the new protected
    windows (drop_firing.py). Its drop-sequence view itself follows the
    store's revision on its own. Never raises.

    THREAD SAFETY: both call sites (ensure_detected, apply_edit) run inside
    an asyncio.to_thread worker (see spectra/api/drop_sequences.py), off
    the event loop tick() reads trigger_engine's _flare_* state on. Calling
    invalidate_analysed_plan directly from there would race tick() (see
    trigger_engine.TriggerEngine.loop's own docstring) — so a call made off
    the engine's remembered loop is marshalled onto it via
    call_soon_threadsafe instead of applied in this thread. A call already
    on that loop (or made before the engine has ever run, loop is None)
    applies directly, matching every test that calls this synchronously."""
    try:
        from spectra.services.trigger_engine import trigger_engine
        loop = trigger_engine.loop
        if loop is None:
            trigger_engine.invalidate_analysed_plan(uri)
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            trigger_engine.invalidate_analysed_plan(uri)
        else:
            loop.call_soon_threadsafe(trigger_engine.invalidate_analysed_plan, uri)
    except Exception:                                    # noqa: BLE001
        logger.exception("drop sequences: could not re-plan %s", uri)


def apply_edit(uri: str, op: str, **kw) -> EditResult:
    """THE edit entry point the API and Sonic use: one named edit, locked,
    with his edits before and after it (the undo pair). Raises
    SequenceNotFound, InvalidEdit or EditConflict, writing nothing."""
    res = _apply_edit(uri, op, **kw)
    _changed(uri)
    return res


def _apply_edit(uri: str, op: str, **kw) -> EditResult:
    key = kw.get("key")
    if op == "confirm":
        return _mutate_tracked(uri, lambda e: _op_confirm(e, key))
    if op == "dismiss":
        return _mutate_tracked(uri, lambda e: _op_dismiss(e, key))
    if op == "revert":
        return _mutate_tracked(uri, lambda e: _op_reset(e, key))
    if op == "handles":
        return _mutate_tracked(uri, lambda e: _op_set_handles(e, key, kw["handles"]))
    if op == "member":
        return _mutate_tracked(uri, lambda e: _op_member_off(e, key, kw["handle"], kw["off"]))
    if op == "review":
        return _mutate_tracked(uri, lambda e: _op_resolve_review(e, key, kw["choice"]))
    if op == "fill":
        handle = kw["handle"]
        times = _current_times(stored(uri), key)
        placed = _place(uri, stored(uri), handle, int(times["drop"]),
                        times.get("lull") if handle == "charge" else None)
        return _mutate_tracked(uri, lambda e: _op_fill(e, key, handle, placed))
    if op == "add":
        rec = _added_record(uri, kw["drop_ms"], kw.get("lull_ms"), kw.get("charge_ms"),
                            kw.get("fill", True))
        return _mutate_tracked(uri, lambda e: _op_add(e, rec))
    if op == "confirm_all":
        keys = _confident_keys(uri)

        def fn(entry):
            done = []
            for k in keys:
                try:
                    done.append(_op_confirm(entry, k))
                except SequenceNotFound:
                    continue
            return done
        return _mutate_tracked(uri, fn)
    if op == "restore":
        return _mutate_tracked(uri, lambda e: _op_restore(e, kw["edits"], kw.get("expect")))
    raise InvalidEdit(f"unknown edit {op!r}")


# ── his own triggers ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class HisMark:
    id: str
    kind: str             # event_class for fire_response, else the action kind
    timestamp_ms: int     # timestamp + its own trigger offset: where it fires


def his_marks(triggers: list) -> list[HisMark]:
    """Every enabled authored trigger, by the moment it fires."""
    out = []
    for t in triggers:
        if getattr(t, "source", "authored") != "authored" or not getattr(t, "enabled", True):
            continue
        a = t.action
        kind = (getattr(a, "event_class", None) if a.kind == "fire_response" else a.kind)
        out.append(HisMark(id=t.id, kind=str(kind),
                           timestamp_ms=int(t.timestamp_ms + (t.trigger_offset_ms or 0))))
    return sorted(out, key=lambda m: m.timestamp_ms)


def group_authored(marks: list[HisMark]) -> tuple[list[dict], list[dict]]:
    """His charge/lull/drop triggers grouped into drop-anchored sequences
    (a lull or charge belongs to the next drop within AUTHORED_REACH_MS
    when no other drop sits between), plus the phase triggers no drop
    claims (a lone charge is an effect of its own for him)."""
    phase = [m for m in marks if m.kind in PHASE_CLASSES]
    used: set[str] = set()
    groups = []
    prev = -1
    for d in [m for m in phase if m.kind == "drop"]:
        lull = max((m for m in phase if m.kind == "lull" and prev < m.timestamp_ms < d.timestamp_ms
                    and d.timestamp_ms - m.timestamp_ms <= AUTHORED_REACH_MS),
                   key=lambda m: m.timestamp_ms, default=None)
        upper = lull.timestamp_ms if lull else d.timestamp_ms
        charge = max((m for m in phase if m.kind == "charge" and prev < m.timestamp_ms < upper
                      and d.timestamp_ms - m.timestamp_ms <= AUTHORED_REACH_MS),
                     key=lambda m: m.timestamp_ms, default=None)
        for m in (d, lull, charge):
            if m is not None:
                used.add(m.id)
        groups.append({h: (asdict(m) if m else None)
                       for h, m in (("charge", charge), ("lull", lull), ("drop", d))})
        prev = d.timestamp_ms
    lone = [asdict(m) for m in phase if m.id not in used]
    return groups, lone


# ── the merged view ────────────────────────────────────────────────────────

@dataclass
class SequenceView:
    key: str
    origin: str                          # "detected" | "added"
    state: str
    charge_ms: Optional[int]
    lull_ms: Optional[int]
    drop_ms: int
    tier: Optional[str] = None           # the detector's tier, when detected
    detected_key: Optional[str] = None   # the current detection's own key
    auto: Optional[dict] = None          # where the detector puts each handle
    moved: dict = field(default_factory=dict)
    lull_off: bool = False
    charge_off: bool = False
    score: Optional[float] = None
    break_beats: Optional[float] = None
    step: Optional[float] = None
    rise: Optional[float] = None
    path: Optional[str] = None
    loud_before: Optional[bool] = None
    capped: bool = False
    notes: list[str] = field(default_factory=list)
    needs_review: bool = False
    detection_lost: bool = False
    matches: list[dict] = field(default_factory=list)
    his_marks_near: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def _near(marks: list[HisMark], at_ms: int, reach: float,
          kinds: Optional[tuple] = None) -> list[dict]:
    return [asdict(m) for m in marks
            if abs(m.timestamp_ms - at_ms) <= reach and (kinds is None or m.kind in kinds)]


def _detected_view(seq: dict, ov: Optional[dict], okey: Optional[str],
                   beat: float) -> SequenceView:
    ov = ov or {}
    eff = _effective(seq, ov)
    auto = {"charge_ms": seq.get("charge_ms"), "lull_ms": seq.get("lull_ms"),
            "drop_ms": seq.get("drop_ms")}
    moved = {h: ov.get(f"{h}_ms") is not None for h in HANDLES}
    edited = any(moved.values()) or bool(ov.get("lull_off")) or bool(ov.get("charge_off"))
    if ov.get("state") == STATE_DISMISSED:
        state = STATE_DISMISSED
    elif edited:
        state = STATE_EDITED
    elif ov.get("state") == STATE_CONFIRMED:
        state = STATE_CONFIRMED
    else:
        state = seq.get("tier") or STATE_SUGGESTED
    v = SequenceView(
        key=okey or seq["key"], origin="detected", state=state,
        charge_ms=eff["charge"], lull_ms=eff["lull"], drop_ms=int(eff["drop"]),
        tier=seq.get("tier"), detected_key=seq.get("key"), auto=auto, moved=moved,
        lull_off=bool(ov.get("lull_off")), charge_off=bool(ov.get("charge_off")),
        score=seq.get("score"), break_beats=seq.get("break_beats"), step=seq.get("step"),
        rise=seq.get("rise"), path=seq.get("path"), loud_before=seq.get("loud_before"),
        capped=bool(seq.get("capped")), notes=list(seq.get("notes") or []))
    if okey and state in (STATE_CONFIRMED, STATE_EDITED):
        snap = ov.get("detected") or {}
        was = snap.get("drop_ms")
        if was is None:
            was = drop_detector.key_ms(okey)
        if was is not None and abs(int(seq["drop_ms"]) - int(was)) > REVIEW_BEATS * beat:
            v.needs_review = True
            v.notes.append(f"the analysis now finds this drop at {seq['drop_ms']} ms, "
                           f"not {was} ms: keep yours, or take the new place")
    _drop_automatic_out_of_order(v)
    return v


def _orphan_view(okey: str, ov: dict) -> Optional[SequenceView]:
    snap = ov.get("detected") or {}
    base = {"drop_ms": snap.get("drop_ms", drop_detector.key_ms(okey)),
            "lull_ms": snap.get("lull_ms"), "charge_ms": snap.get("charge_ms")}
    if base["drop_ms"] is None:
        return None
    eff = _effective(base, ov)
    moved = {h: ov.get(f"{h}_ms") is not None for h in HANDLES}
    edited = any(moved.values()) or bool(ov.get("lull_off")) or bool(ov.get("charge_off"))
    if ov.get("state") == STATE_DISMISSED:
        state = STATE_DISMISSED
    elif edited:
        state = STATE_EDITED
    elif ov.get("state") == STATE_CONFIRMED:
        state = STATE_CONFIRMED
    else:
        return None
    v = SequenceView(
        key=okey, origin="detected", state=state, charge_ms=eff["charge"],
        lull_ms=eff["lull"], drop_ms=int(eff["drop"]), tier=snap.get("tier"),
        auto=base, moved=moved, lull_off=bool(ov.get("lull_off")),
        charge_off=bool(ov.get("charge_off")), score=snap.get("score"),
        detection_lost=True,
        needs_review=state != STATE_DISMISSED and not ov.get("kept"))
    if state != STATE_DISMISSED:
        v.notes.append("the analysis no longer finds this drop; it stays yours "
                       "as you left it")
    _drop_automatic_out_of_order(v)
    return v


def _drop_automatic_out_of_order(v: SequenceView) -> None:
    """His times always win: an AUTOMATIC lull or charge that no longer
    sits before his own handle (RAMP_FLOOR_MS apart) is left out, and
    says so."""
    floor = drop_detector.RAMP_FLOOR_MS
    if v.lull_ms is not None and not v.moved.get("lull") and v.lull_ms > v.drop_ms - floor:
        v.notes.append("automatic lull left out: it no longer sits before your drop")
        v.lull_ms = None
    upper = v.lull_ms if v.lull_ms is not None else v.drop_ms
    if v.charge_ms is not None and not v.moved.get("charge") and v.charge_ms > upper - floor:
        v.notes.append("automatic charge left out: it no longer sits before the lull or drop")
        v.charge_ms = None


def view(uri: str, *, triggers: Optional[list] = None) -> dict:
    """Detected sequences merged with his edits and his own triggers — the
    read the Timeline (phase 3) draws. Never detects: the stored detection
    is what it shows (`status: "not_detected"` when there is none yet).
    `triggers`: this song's stored triggers, when the caller already
    holds them."""
    entry = stored(uri)
    if triggers is None:
        from spectra.services import trigger_store
        triggers = trigger_store.list_for_song(uri)
    marks = his_marks(triggers)
    groups, lone = group_authored(marks)
    det = entry.get("detected")
    out: dict = {"uri": uri, "authored": groups, "authored_lone": lone}
    if not isinstance(det, dict):
        out.update({"status": "not_detected", "reason": "this song has not been "
                    "analysed for drops yet (it is, the first time it plays)",
                    "detector": None, "song": None, "sequences": [], "excluded": [],
                    "counts": {}})
        _add_added(out, entry, marks, 500.0)
        out["counts"] = _counts(out["sequences"])
        return out
    beat = _beat_ms(entry)
    reach = MATCH_BEATS * beat
    seqs = _detected_list(entry)
    overrides = entry.get("overrides") or {}

    pairs = []
    for okey in overrides:
        k = drop_detector.key_ms(okey)
        if k is None:
            continue
        for i, s in enumerate(seqs):
            d = abs(int(s["drop_ms"]) - k)
            if d <= reach:
                pairs.append((d, okey, i))
    pairs.sort()
    by_seq: dict[int, str] = {}
    used: set[str] = set()
    for _, okey, i in pairs:
        if okey in used or i in by_seq:
            continue
        used.add(okey)
        by_seq[i] = okey

    views: list[SequenceView] = []
    for i, s in enumerate(seqs):
        okey = by_seq.get(i)
        views.append(_detected_view(s, overrides.get(okey) if okey else None, okey, beat))
    for okey, ov in overrides.items():
        if okey in used or not isinstance(ov, dict):
            continue
        v = _orphan_view(okey, ov)
        if v is not None:
            views.append(v)

    phase_marks = [m for m in marks if m.kind in PHASE_CLASSES]
    for v in views:
        v.his_marks_near = _near(marks, v.drop_ms, NEAR_BEATS * beat)
        if v.state == STATE_DISMISSED:
            continue
        v.matches = _near(phase_marks, v.drop_ms, reach)
        if v.matches:
            v.state = STATE_MATCHES_YOURS

    out.update({
        "status": "ok", "reason": None,
        "detector": {"version": det.get("detector_version"), "stamp": det.get("stamp"),
                     "detected_at": det.get("detected_at"),
                     "confident_score": det.get("confident_score"),
                     "suggested_score": det.get("suggested_score")},
        "song": {k: det.get(k) for k in ("tempo_bpm", "beat_ms", "captured_from_ms",
                                         "captured_to_ms", "duration_ms")},
        "sequences": [v.as_dict() for v in views],
        "excluded": det.get("excluded") or [],
    })
    _add_added(out, entry, marks, beat)
    out["sequences"].sort(key=lambda s: s["drop_ms"])
    out["counts"] = _counts(out["sequences"])
    return out


def _add_added(out: dict, entry: dict, marks: list[HisMark], beat: float) -> None:
    for rec in entry.get("added") or []:
        try:
            lull_off = bool(rec.get("lull_off"))
            charge_off = bool(rec.get("charge_off"))
            v = SequenceView(
                key=rec["id"], origin="added", state=STATE_ADDED,
                charge_ms=None if charge_off else rec.get("charge_ms"),
                lull_ms=None if lull_off else rec.get("lull_ms"),
                drop_ms=int(rec["drop_ms"]), lull_off=lull_off, charge_off=charge_off,
                # an added sequence keeps its switched-off member's time, so
                # the Timeline can draw where it was and switch it back on
                auto={"charge_ms": rec.get("charge_ms"), "lull_ms": rec.get("lull_ms"),
                      "drop_ms": int(rec["drop_ms"])} if (lull_off or charge_off) else None)
        except (KeyError, TypeError, ValueError):
            continue
        v.his_marks_near = _near(marks, v.drop_ms, NEAR_BEATS * beat)
        out["sequences"].append(v.as_dict())


def _counts(seqs: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for s in seqs:
        counts[s["state"]] = counts.get(s["state"], 0) + 1
    return counts


def snap_rails(uri: str) -> dict:
    """THE SNAP RAILS (drop-detection plan, phase 3): what the Timeline
    draws under the sequence layer and, in phase 4, what a dragged handle
    snaps to — every BASS SPIKE the detector counts (song ms and its rise,
    the height a rail tick is drawn at: taller = harder) and every BEAT
    (song ms and whether it is a downbeat). Read straight from the
    detector's own analysis, so a rail tick is exactly a spike the
    detector could have chosen — never a second definition of one.
    Read-only: no detection is stored and nothing is written."""
    try:
        analysis = drop_detector.analyse(uri)
    except drop_detector.Unavailable as exc:
        return {"uri": uri, "status": "unavailable", "reason": str(exc),
                "beat_ms": None, "captured_from_ms": None, "spikes": [], "beats": []}
    song = analysis.song
    doc = analysis_reader.librosa_analysis_for_stem(song.stem) or {}
    flags = [bool(b.get("is_downbeat")) for b in doc.get("beats") or []]
    beats = [[int(round(float(ms))), 1 if i < len(flags) and flags[i] else 0]
             for i, ms in enumerate(song.beat_ms)]
    spikes = [[int(ms), round(float(rise), 3)]
              for ms, rise in zip(analysis.prep.att_ms, analysis.prep.att_rise)]
    return {"uri": uri, "status": "ok", "reason": None,
            "beat_ms": round(song.beat_len, 3), "captured_from_ms": int(song.t[0]),
            "spikes": spikes, "beats": beats}


def view_with_detection(uri: str) -> dict:
    """Read-through: detect when missing or stale, then the merged view.
    Synchronous — call it off the event loop."""
    result = ensure_detected(uri)
    body = view(uri)
    body["detection"] = result
    if result.get("status") == "unavailable" and body.get("status") == "not_detected":
        body["status"] = "unavailable"
        body["reason"] = result.get("reason")
    return body
