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
own trigger fires there in a mode that fires his triggers. An added
sequence is his and never stands down. That LAST CLAUSE is load-bearing
(data/popoff-drops-not-firing/report.md): "analysed" never fires a
hand-authored trigger (trigger_engine._trigger_allowed only lets one
through under "full"/"triggers_only"), so a `matches_yours` sequence on a
song in "analysed" mode would otherwise stand down to a trigger that never
actually fires, going silent on both doors. This module still only marks
the state — mode-independent, as the rest of this docstring says — the
mode-aware fallback (confident fires anyway, suggested still waits,
confirmed/edited fire wherever the analysed show plays) is
spectra/services/drop_firing.py's `fires_here`, not here. The SAME
mode-aware fallback governs a single stood-down member one level down
(a sequence's own charge/lull sitting on a same-class authored mark, even
when the whole sequence fires) — `drop_firing.FiringSequence.members`/
`gap_ms` take the mode and only exclude that member when his trigger can
actually fire in it, never unconditionally. Two sequences kept near one
authored mark always dedupe to one of them (his own `matches_his` sort
order decides WHICH, never WHETHER the dedup runs).

STATES, in precedence order: dismissed > matches_yours > edited >
confirmed > confident | suggested; and added. This module only says what
each sequence IS; what fires, and the protected window around each, is
spectra/services/drop_firing.py (phase 5).

PARTS (2026-10-26, predrop plan step 1 — the Home Drops panel's per-drop
toggle bar; the Admiral: "tap the double checkmark button to approve the
lull, charge, drop, and predrop. Or, an icon for each individual one, to
toggle them"). Every view sequence carries `parts`, one state per part:
  on       approved: it plays (with its drop);
  waiting  not approved yet: it follows the sequence's tier — a confident
           detection plays on its own, a suggested one waits (or plays
           while drop Testing is on, drop_firing.py);
  off      never plays, not even in Testing;
  absent   the drop has no such part (a lull or charge it never had; a
           pre-drop the rules did not find and he has not placed).
A charge, lull or pre-drop leads into its drop, so it plays only when its
drop plays (drop_firing.py); a drop switched off keeps the sequence listed
but silent, which is not a dismissal. Stored as `overrides[key].parts`
({part: "on" | "off"}, absent = waiting; the lull's and charge's "off" stay
the existing `lull_off`/`charge_off` flags), and on an added sequence as
its own `parts` (only "drop": "off" — everything he placed is on).

TWO MODES, so nothing he already did changes meaning. An override WITHOUT
a `parts` dict is the legacy shape: confirmed or edited means the whole
sequence is his (every part on), exactly as before parts existed. The
first part edit on a sequence creates the dict, seeded from that legacy
reading (`_ensure_parts`), and from then on every part's approval is
explicit: approving the drop alone confirms it and leaves the charge and
lull waiting. The drop part "on" and the override's confirmed state move
together. The Timeline's Confirm in parts mode approves every part that is
not off, the same as the panel's double tick.

HIS OWN ROWS. `yours` in the view groups ALL his charge/lull/drop triggers
(enabled or switched off, unlike `authored`, which feeds the firing and
the "matches yours" rule and stays enabled-only) into drop-anchored rows,
each member carrying `enabled` and its own `offset_ms` (its time is the
moment it fires: stored time plus that offset), and names the detection
the row stands in for. What Remove does to them (delete if placed by hand, switch off if
imported, answer 6) is spectra/services/drop_panel.py; when a removal
dismisses the detection a row stood in for, that dismissal is recorded
`dismissed_for` his drop trigger with the override as it was before
(`prior`), so switching his drop back on puts the detection back.

PRE-DROPS (predrop plan step 3; spectra/services/predrop_detector.py is
the binding statement for the two rules). A detected sequence carries the
pre-drop the rules find before its drop (`pre_drop`: ms, kind, lead_ms,
score, tier), and the view names it: `pre_drop_ms`, `pre_drop_kind`
("spike" | "intro"), `pre_drop_auto` (where the detector puts it, as
`auto` is for the handles), `pre_drop_tier`, `pre_drop_score`. His OWN
grouped drops (`authored`) carry one computed against his drop's own
moment: `pre_drop` on the group, memoised per song, detection stamp and
drop time, and worked out only on the read-through path
(`view_with_detection`, a worker thread) — a plain `view()` is the trigger
clock's, which must never analyse, so it shows only what is memoised and
leaves the key out where nothing is ("not worked out yet", never "none").
Nothing plays from a pre-drop yet (drop_firing.PRE_DROPS_PLAY), and an
added sequence has none until he places one.

EDITING A PRE-DROP (predrop plan step 4: its orange handle on the Timeline
and in the panel's editor, its panel button, Sonic's set_pre_drop /
switch_pre_drop). `pre_drop` is a handle (`EDIT_HANDLES`): a drag keeps
its kind (`pre_drop_ms` + `pre_drop_kind`), None goes back to the
detector's place and kind; `member` switches it off (`pre_drop_off`, the
view's `pre_drop_was` where it comes back); `pre_drop_kind` switches it
between a spike and a vocal intro; `fill` (＋ Pre-drop) places one where
`predrop_detector.place` puts it; `parts` approves it. The view's
`moved.pre_drop` is "he placed it", and the detector's tier and score
show only while it has not. TWO RULES, and where each holds: a pre-drop's
LEAD must fit its kind's range (`predrop_detector.lead_range`, its search
window) — checked on the pre-drop's own edits only, so dragging the drop
never trips on it; and one he placed must stay RAMP_FLOOR_MS before its
drop — the order rule, which holds a drop move back (a move carrying the
pre-drop too is checked against where it is GOING), while an automatic
one a move leaves behind is left out with a note, as an automatic lull is.
A drag or a switch-off counts as "edited" (`_legacy_his`), like a lull's;
a kind switch alone does not (it relabels the moment, it does not place
it). In parts mode it is approved only by its own toggle, the double tick or
Confirm; in the legacy reading only one he placed is his — one found since
his confirm waits (`_part_states`).

HIS OWN DROPS' PRE-DROPS live in THIS store, never in his song profile (a
pre-drop is not one of his triggers): `overrides["mine:<his drop trigger
id>"]`, edited through `apply_edit("mine_pre_drop", drop_ms=, pre=,
step=)` with the moment his drop fires and the rules' pre-drop against it
(`his_pre_drop_ctx`; drop_panel.py maps the panel's "his:" keys onto it).
A mine: override holds only pre-drop fields; it is dropped the moment
nothing of his is left in it. `authored` groups and `yours` rows carry the
result as `pre_drop` (`_his_pre_drop_view`: ms, kind, auto, off, was,
moved, lead_ms, score, tier, part — None when there is none).

THE SNAP RAILS (`snap_rails`) also carry `hits` (every high-band attack,
[ms, strength] — a dragged spike snaps to these) and `entries` (every
mid-band entry passing the vocal intro's first three tests — a dragged
vocal intro snaps to these), from `predrop_detector.rails`.

A DROP THE RE-ANCHOR MOVED keeps its overrides: a detection carries
`reanchored_from` (where the first-spike rule put it), and an override
made against that drop pairs with it at that distance (`_det_distance`).
A confirmed or edited drop does not ask for review when the analysis has
moved to where HIS drop already is (Eyes Cut Deeper drop 1: he moved it to
70,350 by hand and the re-anchor puts it there).

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
from spectra.services import analysis_reader, drop_detector, predrop_detector

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

PARTS = ("charge", "lull", "pre_drop", "drop")
"""The parts of a drop, in the order they play (module docstring's PARTS).
The pre-drop is one, absent on a drop that has none."""
PRE_DROP = "pre_drop"
EDIT_HANDLES = HANDLES + (PRE_DROP,)
"""What one `handles` edit can move: the three phases and the pre-drop."""
MEMBERS = ("lull", "charge", PRE_DROP)
"""What can be switched off, or added where the detector's rules put it."""
MINE_PREFIX = "mine:"
"""His own drops' pre-drop edits live under overrides["mine:<his drop
trigger id>"] (module docstring's PRE-DROPS) — never in his song profile."""
NO_PRE_DROP = "this drop has no pre-drop — add one first (＋ Pre-drop)"
PART_ON = "on"
PART_WAITING = "waiting"
PART_OFF = "off"
PART_ABSENT = "absent"


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

def _thresholds(controls: Any = None) -> tuple[float, float, float]:
    if controls is None:
        from spectra.services import room_controls
        controls = room_controls.load_room_controls()
    return (float(controls.drop_confident_score), float(controls.drop_suggested_score),
            float(controls.drop_floor))


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
    of a SHA-1 over the detector and pre-drop versions, the two tier
    thresholds, the drop floor and the song's own inputs. Raises
    drop_detector.Unavailable."""
    confident, suggested, floor = _thresholds(controls)
    payload = {
        "version": drop_detector.DETECTOR_VERSION,
        "predrop_version": predrop_detector.PREDROP_VERSION,
        "settings": {"confident": confident, "suggested": suggested, "floor": floor},
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
                confident, suggested, floor = _thresholds(controls)
                det = drop_detector.detect_uri(
                    uri, confident_score=confident, suggested_score=suggested,
                    drop_floor=floor)
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
    with _his_pre_drops_lock:
        _his_pre_drops.clear()


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


def _det_distance(seq: dict, ms: int) -> int:
    """How far a detection sits from `ms` (an override key's drop): from
    its drop, or — when the re-anchor moved it (`reanchored_from`) — from
    where the detector first found it, whichever is nearer, so an override
    made against the drop as it was keeps pairing with the drop as it is."""
    d = abs(int(seq["drop_ms"]) - int(ms))
    was = seq.get("reanchored_from")
    if was is not None:
        d = min(d, abs(int(was) - int(ms)))
    return d


def _resolve_detected_key(entry: dict, key: str) -> tuple[str, Optional[dict]]:
    """The override key an edit to `key` belongs to, and the detection it
    is made against (None when only an override answers). An existing
    override within MATCH_BEATS wins, so one detection never carries two."""
    k_ms = drop_detector.key_ms(key)
    if k_ms is None:
        raise SequenceNotFound(f"not a detection key: {key!r}")
    reach = MATCH_BEATS * _beat_ms(entry)
    overrides = entry.get("overrides") or {}
    dets = _detected_list(entry)
    okey = key if key in overrides else None
    if okey is None:
        # a key naming a detection measures from that detection (its first
        # place too, when the re-anchor moved it)
        anchor = next((d for d in dets if d.get("key") == key), None) or {"drop_ms": k_ms}
        near = sorted((_det_distance(anchor, drop_detector.key_ms(k)), k) for k in overrides
                      if drop_detector.key_ms(k) is not None
                      and _det_distance(anchor, drop_detector.key_ms(k)) <= reach)
        okey = near[0][1] if near else None
    target_ms = drop_detector.key_ms(okey) if okey else k_ms
    near_det = sorted((_det_distance(d, target_ms), i) for i, d in enumerate(dets)
                      if _det_distance(d, target_ms) <= reach)
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
    pre = times.get(PRE_DROP)
    if pre is not None and int(times["drop"]) - int(pre) < drop_detector.RAMP_FLOOR_MS:
        raise InvalidEdit(f"the pre-drop must sit at least {drop_detector.RAMP_FLOOR_MS} ms "
                          "before its drop")


# ── the pre-drop (module docstring's PRE-DROPS) ────────────────────────────

def _base_pre(base: Optional[dict]) -> Optional[dict]:
    """The detector's pre-drop in a detection (or the rules' for one of his
    drops), None when it found none."""
    pre = (base or {}).get("pre_drop")
    return pre if isinstance(pre, dict) and pre.get("ms") is not None else None


def _pre_drop_of(base_pre: Optional[dict], rec: dict) -> dict:
    """THE EFFECTIVE PRE-DROP from the detector's (`base_pre`) and his edits
    in `rec` (an override, an added record or a mine: override): `ms` where
    it plays (None when there is none or it is switched off), `kind`, `auto`
    the detector's place, `off`, `was` where an off one comes back, `moved`
    he placed it (a drag, or ＋ Pre-drop). His place always wins."""
    auto = int(base_pre["ms"]) if base_pre else None
    placed = rec.get("pre_drop_ms")
    moved = placed is not None
    at = int(placed) if moved else auto
    if at is None:
        return {"ms": None, "kind": None, "auto": auto, "off": False, "was": None,
                "moved": False}
    kind = rec.get("pre_drop_kind") or (base_pre or {}).get("kind")
    if kind not in predrop_detector.KINDS:
        kind = predrop_detector.KIND_SPIKE
    off = bool(rec.get("pre_drop_off"))
    return {"ms": None if off else at, "kind": kind, "auto": auto, "off": off,
            "was": at if off else None, "moved": moved}


def _kind_word(kind: str) -> str:
    return "spike" if kind == predrop_detector.KIND_SPIKE else "vocal intro"


def _check_pre_drop_lead(kind: str, ms: int, drop_ms: Optional[int]) -> None:
    """A pre-drop of `kind` sits inside its kind's lead range (its search
    window, as wide as any scene may set): outside it no scene could ever
    play it. Checked on the pre-drop's own edits only."""
    if drop_ms is None:
        return
    lo, hi = predrop_detector.lead_range(kind)
    lead = int(drop_ms) - int(ms)
    if not lo <= lead <= hi:
        raise InvalidEdit(f"a {_kind_word(kind)} pre-drop sits {lo}-{hi} ms before its drop; "
                          f"this one would sit {lead} ms before it")


@dataclass
class _Slot:
    """Where a pre-drop edit lands: the record holding his edits (an
    override, an added sequence, or a mine: override), the detector's own
    pre-drop, and the effective charge/lull/drop it must keep in order."""
    rec: dict
    base_pre: Optional[dict]
    times: dict
    kind: str                       # "detected" | "added" | "mine"
    okey: str


def _is_mine(key: str) -> bool:
    return isinstance(key, str) and key.startswith(MINE_PREFIX)


def _added_times(rec: dict) -> dict:
    out = {h: rec.get(f"{h}_ms") for h in HANDLES}
    for h in ("lull", "charge"):
        if rec.get(f"{h}_off"):
            out[h] = None
    return out


def _slot(entry: dict, key: str, ctx: Optional[dict] = None) -> _Slot:
    """`ctx` names one of his own drops for a mine: key: {"drop_ms": the
    moment his drop fires, "pre": the rules' pre-drop against it}."""
    if _is_mine(key):
        if not ctx or ctx.get("drop_ms") is None:
            raise InvalidEdit("a pre-drop of your own drop needs its drop's moment")
        rec = entry.setdefault("overrides", {}).setdefault(key, {})
        return _Slot(rec, _base_pre({"pre_drop": ctx.get("pre")}),
                     {"charge": None, "lull": None, "drop": int(ctx["drop_ms"])}, "mine", key)
    if _is_added(key):
        rec = _find_added(entry, key)
        return _Slot(rec, None, _added_times(rec), "added", key)
    okey, det, ov = _override(entry, key)
    base = det or ov.get("detected") or {}
    return _Slot(ov, _base_pre(base), _effective(base, ov), "detected", okey)


def _pre_move(slot: _Slot, ms: Optional[int]) -> None:
    """Move the pre-drop (a drag). None = back to the detector's place: a
    pre-drop he placed where the detector found none goes."""
    if ms is None:
        for k in ("pre_drop_ms", "pre_drop_kind"):
            slot.rec.pop(k, None)
        if slot.base_pre is None:
            slot.rec.pop("pre_drop_off", None)
        return
    cur = _pre_drop_of(slot.base_pre, slot.rec)
    if cur["ms"] is None and cur["was"] is None:
        raise InvalidEdit(NO_PRE_DROP)
    _check_pre_drop_lead(cur["kind"], ms, slot.times.get("drop"))
    _check_order({**slot.times, PRE_DROP: int(ms)})
    slot.rec["pre_drop_ms"] = int(ms)
    slot.rec["pre_drop_kind"] = cur["kind"]           # a dragged pre-drop keeps its kind
    slot.rec.pop("pre_drop_off", None)


def _pre_off(slot: _Slot, off: bool) -> None:
    cur = _pre_drop_of(slot.base_pre, slot.rec)
    if off:
        if cur["ms"] is None and not cur["off"]:
            raise InvalidEdit("this drop has no pre-drop to switch off")
        slot.rec["pre_drop_off"] = True
        return
    if not cur["off"]:
        if cur["ms"] is None:
            raise InvalidEdit(NO_PRE_DROP)
        return
    _check_order({**slot.times, PRE_DROP: int(cur["was"])})
    slot.rec.pop("pre_drop_off", None)


def _pre_kind(slot: _Slot, kind: str) -> None:
    if kind not in predrop_detector.KINDS:
        raise InvalidEdit(f"a pre-drop's kind is one of {predrop_detector.KINDS}")
    cur = _pre_drop_of(slot.base_pre, slot.rec)
    at = cur["ms"] if cur["ms"] is not None else cur["was"]
    if at is None:
        raise InvalidEdit(NO_PRE_DROP)
    _check_pre_drop_lead(kind, at, slot.times.get("drop"))
    if kind == (slot.base_pre or {}).get("kind") and not cur["moved"]:
        slot.rec.pop("pre_drop_kind", None)
    else:
        slot.rec["pre_drop_kind"] = kind


def _pre_fill(slot: _Slot, placed: Optional[tuple[int, str]], why: Optional[str]) -> None:
    """＋ Pre-drop: one where the rules put it (predrop_detector.place)."""
    cur = _pre_drop_of(slot.base_pre, slot.rec)
    if cur["off"]:
        raise InvalidEdit("this drop's pre-drop is switched off — switch it back on")
    if cur["ms"] is not None:
        raise InvalidEdit("this drop already has a pre-drop — drag it to move it")
    if placed is None:
        raise InvalidEdit(why or "the rules find no hit or vocal entry to put a pre-drop on "
                                 "before this drop")
    ms, kind = int(placed[0]), str(placed[1])
    _check_pre_drop_lead(kind, ms, slot.times.get("drop"))
    _check_order({**slot.times, PRE_DROP: ms})
    slot.rec["pre_drop_ms"] = ms
    slot.rec["pre_drop_kind"] = kind
    slot.rec.pop("pre_drop_off", None)


def _pre_part(slot: _Slot, value: str) -> None:
    """The pre-drop's toggle: "on" approves it (switching it back on when it
    was off), "off" switches it off. An added drop's parts are all his."""
    cur = _pre_drop_of(slot.base_pre, slot.rec)
    if value == PART_OFF:
        _pre_off(slot, True)
        if isinstance(slot.rec.get("parts"), dict):
            slot.rec["parts"].pop(PRE_DROP, None)
            if slot.kind == "mine" and not slot.rec["parts"]:
                slot.rec.pop("parts")
        return
    if cur["off"]:
        _pre_off(slot, False)
    elif cur["ms"] is None:
        raise InvalidEdit("this drop has no pre-drop — add one in its editor")
    if slot.kind != "added":
        slot.rec.setdefault("parts", {})[PRE_DROP] = PART_ON


def place_pre_drop(uri: str, drop_ms: int) -> tuple[Optional[tuple[int, str]], Optional[str]]:
    """Where ＋ Pre-drop puts one for the drop at `drop_ms`, and why not
    when it cannot (predrop_detector.place over the song's own shape)."""
    try:
        analysis = drop_detector.analyse(uri)
    except drop_detector.Unavailable:
        return None, "this song's audio shape cannot be read to place a pre-drop"
    got = predrop_detector.place(analysis.shape, int(drop_ms))
    if got is None:
        return None, ("the rules find no hit or vocal entry to put a pre-drop on in the "
                      f"{predrop_detector.INTRO_SEARCH_MS[1] / 1000:g} s before this drop")
    return got, None


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
    okey, det, ov = _override(entry, key)
    if (not isinstance(ov.get("parts"), dict)
            and _pre_drop_of(_base_pre(det or ov.get("detected")), ov)["ms"] is not None):
        # a pre-drop he can see: Confirm approves it too, which takes PARTS MODE
        okey, det, ov = _ensure_parts(entry, key)
    ov["state"] = STATE_CONFIRMED
    if isinstance(ov.get("parts"), dict):
        # PARTS MODE (module docstring): a confirm approves every part that
        # is not off, and the drop itself — "this is a drop, play it".
        _approve_parts(ov, det)
        ov["parts"]["drop"] = PART_ON
    ov["at"] = _now_ms()
    return okey


def _legacy_his(ov: dict) -> bool:
    """The legacy reading of an override without a `parts` dict: confirmed
    or edited means the whole sequence is his."""
    moved = any(ov.get(f"{h}_ms") is not None for h in EDIT_HANDLES)
    edited = (moved or bool(ov.get("lull_off")) or bool(ov.get("charge_off"))
              or bool(ov.get("pre_drop_off")))
    return ov.get("state") == STATE_CONFIRMED or edited


def _ensure_parts(entry: dict, key: str) -> tuple[str, Optional[dict], dict]:
    """The override a part edit lands in, switched to PARTS MODE: the first
    part edit seeds `parts` from the legacy reading, so a sequence he had
    already confirmed or edited stays wholly approved (module docstring)."""
    okey, det, ov = _override(entry, key)
    if not isinstance(ov.get("parts"), dict):
        parts: dict = {}
        if ov.get("state") != STATE_DISMISSED and _legacy_his(ov):
            eff = _effective(det or ov.get("detected") or {}, ov)
            for h in ("charge", "lull"):
                if eff.get(h) is not None:
                    parts[h] = PART_ON
            # a pre-drop he placed himself was his; one found since waits
            pre = _pre_drop_of(_base_pre(det or ov.get("detected")), ov)
            if pre["moved"] and pre["ms"] is not None:
                parts[PRE_DROP] = PART_ON
            parts["drop"] = PART_ON
            ov["state"] = STATE_CONFIRMED
        ov["parts"] = parts
    return okey, det, ov


def _approve_parts(ov: dict, det: Optional[dict]) -> None:
    """Every charge/lull/pre-drop part that exists and is not off → on."""
    eff = _effective(det or ov.get("detected") or {}, ov)
    parts = ov.setdefault("parts", {})
    for h in ("charge", "lull"):
        if eff.get(h) is not None and not ov.get(f"{h}_off"):
            parts[h] = PART_ON
    if _pre_drop_of(_base_pre(det or ov.get("detected")), ov)["ms"] is not None:
        parts[PRE_DROP] = PART_ON


def _refuse_dismissed(ov: dict) -> None:
    if ov.get("state") == STATE_DISMISSED:
        raise InvalidEdit("this drop was removed — undo it, or bring it back on the Timeline")


def _op_part(entry: dict, key: str, part: str, value: str) -> str:
    """One part's toggle (the panel's charge/lull/pre-drop/drop buttons):
    `value` "on" approves it, "off" switches it off. The drop part "on"
    confirms the sequence; "off" keeps it listed but silent."""
    if part not in PARTS:
        raise InvalidEdit(f"part must be one of {PARTS}")
    if value not in (PART_ON, PART_OFF):
        raise InvalidEdit("a part is switched on or off")
    if part == PRE_DROP:
        if _is_added(key):
            _pre_part(_slot(entry, key), value)
            _find_added(entry, key)["at"] = _now_ms()
            return key
        okey, _det, ov = _ensure_parts(entry, key)
        _refuse_dismissed(ov)
        _pre_part(_slot(entry, key), value)
        ov["at"] = _now_ms()
        return okey
    if _is_added(key):
        if part in ("lull", "charge"):
            return _op_member_off(entry, key, part, value == PART_OFF)
        rec = _find_added(entry, key)
        parts = rec.setdefault("parts", {})
        if value == PART_OFF:
            parts["drop"] = PART_OFF
        else:
            parts.pop("drop", None)
        if not parts:
            rec.pop("parts", None)
        rec["at"] = _now_ms()
        return key
    okey, det, ov = _ensure_parts(entry, key)
    _refuse_dismissed(ov)
    parts = ov["parts"]
    if part in ("lull", "charge"):
        if value == PART_OFF:
            _op_member_off(entry, key, part, True)
            parts.pop(part, None)
        else:
            if ov.get(f"{part}_off"):
                _op_member_off(entry, key, part, False)
            elif _effective(det or ov.get("detected") or {}, ov).get(part) is None:
                raise InvalidEdit(f"this drop has no {part} — add one in its editor")
            parts[part] = PART_ON
    elif value == PART_ON:
        parts["drop"] = PART_ON
        ov["state"] = STATE_CONFIRMED
    else:
        parts["drop"] = PART_OFF
        if ov.get("state") == STATE_CONFIRMED:
            ov.pop("state")
    ov["at"] = _now_ms()
    return okey


def _op_approve(entry: dict, key: str) -> str:
    """The double tick: approve every part that is not off — the charge,
    the lull, the pre-drop and the drop. A drop he switched off stays off
    (an off part is his explicit "never"); tap the drop itself to bring
    it back."""
    if _is_added(key):
        _find_added(entry, key)
        return key                      # everything he placed is on already
    okey, det, ov = _ensure_parts(entry, key)
    _refuse_dismissed(ov)
    _approve_parts(ov, det)
    if ov["parts"].get("drop") != PART_OFF:
        ov["parts"]["drop"] = PART_ON
        ov["state"] = STATE_CONFIRMED
    ov["at"] = _now_ms()
    return okey


def _op_remove(entry: dict, key: str) -> str:
    """Remove a detected or added sequence completely: a detection is
    dismissed, a sequence he added is deleted. (His own rows go through
    spectra/services/drop_panel.py, which also writes his song profile.)"""
    if _is_added(key):
        if not _op_remove_added(entry, key):
            raise SequenceNotFound(f"no added sequence {key!r} on this song")
        return key
    return _op_dismiss(entry, key)


def _op_dismiss_for(entry: dict, key: str, his_id: str) -> Optional[str]:
    """Dismiss the detection one of his own rows stood in for, remembering
    the override as it was (`prior`) so `_op_undismiss_for` can put it
    back when his drop is switched on again. A detection he had dismissed
    himself is left exactly as it is. None when no detection answers."""
    try:
        okey, det = _resolve_detected_key(entry, key)
    except SequenceNotFound:
        return None
    ovs = entry.setdefault("overrides", {})
    current = ovs.get(okey)
    if isinstance(current, dict) and current.get("state") == STATE_DISMISSED:
        if not current.get("dismissed_for"):
            return okey
    prior = copy.deepcopy(current) if isinstance(current, dict) else None
    if isinstance(prior, dict) and prior.get("dismissed_for"):
        prior = prior.get("prior")
    ov = {"detected": (_snapshot(det) if det else (prior or {}).get("detected")),
          "state": STATE_DISMISSED, "dismissed_for": str(his_id), "prior": prior,
          "at": _now_ms()}
    ovs[okey] = ov
    return okey


def _op_undismiss_for(entry: dict, his_id: str) -> list[str]:
    """Put back every detection dismissed on behalf of his drop `his_id`."""
    ovs = entry.get("overrides") or {}
    back = []
    for okey in list(ovs):
        ov = ovs.get(okey)
        if not isinstance(ov, dict) or ov.get("dismissed_for") != str(his_id):
            continue
        prior = ov.get("prior")
        if isinstance(prior, dict):
            ovs[okey] = prior
        else:
            ovs.pop(okey)
        back.append(okey)
    if not ovs:
        entry.pop("overrides", None)
    return back


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
        if h not in EDIT_HANDLES:
            raise InvalidEdit(f"handle must be one of {EDIT_HANDLES}")
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
    are. Order is enforced: charge < lull < drop, RAMP_FLOOR_MS apart, and a
    pre-drop he placed stays RAMP_FLOOR_MS before its drop (an automatic one
    the move leaves behind is simply left out, as an automatic lull is).
    `pre_drop` moves the pre-drop (module docstring's PRE-DROPS) in the same
    edit — a whole-sequence move carries it."""
    handles = _check_handle_values(handles)
    pre_given = PRE_DROP in handles
    pre_ms = handles.pop(PRE_DROP, None)
    # moved together, the order is checked against where the pre-drop is
    # GOING (a whole-sequence move earlier would otherwise trip on where it was)
    done = (_set_phase_handles(entry, key, handles,
                               pre=pre_ms if pre_given else _KEEP_PRE)
            if handles else None)
    if pre_given:
        slot = _slot(entry, key)
        _pre_move(slot, pre_ms)
        slot.rec["at"] = _now_ms()
        return slot.okey
    return done


def _placed_pre(base_pre: Optional[dict], rec: dict) -> Optional[int]:
    """The pre-drop's time for the order rule: only one he placed holds a
    move back (an automatic one is left out instead)."""
    cur = _pre_drop_of(base_pre, rec)
    return cur["ms"] if cur["moved"] else None


_KEEP_PRE = object()


def _set_phase_handles(entry: dict, key: str, handles: dict, pre: Any = _KEEP_PRE) -> str:
    """`pre`: the pre-drop's time to keep the order against, when this edit
    moves it too (None: back to the detector's — automatic, never checked)."""
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
        eff[PRE_DROP] = _placed_pre(None, rec) if pre is _KEEP_PRE else pre
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
    _check_order({**_effective(base, trial_ov),
                  PRE_DROP: _placed_pre(_base_pre(base), ov) if pre is _KEEP_PRE else pre})
    ov.update(trial_ov)
    ov["at"] = _now_ms()
    return okey


def _op_member_off(entry: dict, key: str, handle: str, off: bool) -> str:
    if handle == PRE_DROP:
        slot = _slot(entry, key)
        _pre_off(slot, off)
        slot.rec["at"] = _now_ms()
        return slot.okey
    if handle not in ("lull", "charge"):
        raise InvalidEdit("only the lull, the charge or the pre-drop can be switched off")
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


def _op_pre_drop_fill(entry: dict, key: str, placed: Optional[tuple[int, str]],
                      why: Optional[str], ctx: Optional[dict] = None) -> str:
    slot = _slot(entry, key, ctx)
    if slot.kind == "detected":
        _refuse_dismissed(slot.rec)
    _pre_fill(slot, placed, why)
    slot.rec["at"] = _now_ms()
    return slot.okey


def _op_pre_drop_kind(entry: dict, key: str, kind: str, ctx: Optional[dict] = None) -> str:
    slot = _slot(entry, key, ctx)
    _pre_kind(slot, kind)
    slot.rec["at"] = _now_ms()
    return slot.okey


def _op_mine_pre_drop(entry: dict, key: str, ctx: dict, step: dict) -> str:
    """One of HIS OWN drops' pre-drop edits (module docstring's PRE-DROPS):
    `step` is {"move": ms|None} | {"off": bool} | {"kind": k} | {"part": v}
    | {"fill": (ms, kind) | None, "why": ...}, stored under the mine: key."""
    if not _is_mine(key):
        raise InvalidEdit(f"not a pre-drop of your own drop: {key!r}")
    slot = _slot(entry, key, ctx)
    if "move" in step:
        _pre_move(slot, step["move"])
    elif "off" in step:
        _pre_off(slot, bool(step["off"]))
    elif "kind" in step:
        _pre_kind(slot, step["kind"])
    elif "part" in step:
        if step["part"] not in (PART_ON, PART_OFF):
            raise InvalidEdit("a part is switched on or off")
        _pre_part(slot, step["part"])
    elif "fill" in step:
        _pre_fill(slot, step["fill"], step.get("why"))
    else:
        raise InvalidEdit("name what to do to the pre-drop")
    if any(k != "at" for k in slot.rec):
        slot.rec["at"] = _now_ms()
    else:                                   # nothing of his left: no record at all
        entry["overrides"].pop(key, None)
        if not entry["overrides"]:
            entry.pop("overrides", None)
    return key


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
    if op == "fill" and kw.get("handle") == PRE_DROP:
        times = _current_times(stored(uri), key)
        placed, why = place_pre_drop(uri, int(times["drop"]))
        return _mutate_tracked(uri, lambda e: _op_pre_drop_fill(e, key, placed, why))
    if op == "pre_drop_kind":
        return _mutate_tracked(uri, lambda e: _op_pre_drop_kind(e, key, kw["kind"]))
    if op == "mine_pre_drop":
        ctx = {"drop_ms": int(kw["drop_ms"]), "pre": kw.get("pre")}
        step = dict(kw["step"])
        if step.get("fill") == "rules":
            step["fill"], step["why"] = place_pre_drop(uri, ctx["drop_ms"])
        return _mutate_tracked(uri, lambda e: _op_mine_pre_drop(e, key, ctx, step))
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
    if op == "parts":
        parts = kw["parts"]
        if not isinstance(parts, dict) or not parts:
            raise InvalidEdit("name at least one part to switch")

        def fn(entry):
            done = key
            for part, value in parts.items():
                done = _op_part(entry, key, part, value)
            return done
        return _mutate_tracked(uri, fn)
    if op == "approve":
        return _mutate_tracked(uri, lambda e: _op_approve(e, key))
    if op == "remove":
        return _mutate_tracked(uri, lambda e: _op_remove(e, key))
    if op == "dismiss_for":
        keys = list(kw["keys"])
        his_id = str(kw["his_id"])
        return _mutate_tracked(uri, lambda e: [k for k in (_op_dismiss_for(e, x, his_id)
                                                           for x in keys) if k])
    if op == "undismiss_for":
        return _mutate_tracked(uri, lambda e: _op_undismiss_for(e, str(kw["his_id"])))
    if op == "multi":
        # several of the edits above in ONE locked write, so they share one
        # before/after pair — one undo step (drop_panel.py's own rows)
        steps = list(kw.get("ops") or [])

        def fn(entry):
            out = []
            for st in steps:
                kind = st.get("op")
                if kind == "part":
                    out.append(_op_part(entry, st["key"], st["part"], st["value"]))
                elif kind == "dismiss_for":
                    out.extend(k for k in (_op_dismiss_for(entry, x, str(st["his_id"]))
                                           for x in st["keys"]) if k)
                elif kind == "undismiss_for":
                    out.extend(_op_undismiss_for(entry, str(st["his_id"])))
                elif kind == "mine_pre_drop":
                    ctx = {"drop_ms": int(st["drop_ms"]), "pre": st.get("pre")}
                    out.append(_op_mine_pre_drop(entry, st["key"], ctx, dict(st["step"])))
                else:
                    raise InvalidEdit(f"unknown step {kind!r}")
            return out
        return _mutate_tracked(uri, fn)
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
    # one state per part (module docstring's PARTS): on | waiting | off | absent
    parts: dict = field(default_factory=dict)
    # the pre-drop (module docstring's PRE-DROPS): where, which kind
    # ("spike" | "intro"), where the detector puts it, and how sure
    pre_drop_ms: Optional[int] = None
    pre_drop_kind: Optional[str] = None
    pre_drop_auto: Optional[int] = None
    pre_drop_tier: Optional[str] = None
    pre_drop_score: Optional[float] = None
    # switched off: pre_drop_ms is None and pre_drop_was is where it comes back
    pre_drop_off: bool = False
    pre_drop_was: Optional[int] = None

    def as_dict(self) -> dict:
        return asdict(self)


def _part_states(v: SequenceView, stored: Optional[dict], legacy_his: bool,
                 *, added: bool = False) -> dict:
    """The view's `parts` (module docstring's PARTS and TWO MODES).
    `stored` is the override's (or added record's) `parts` dict, None in
    the legacy shape."""
    out: dict[str, str] = {}
    for h in ("charge", "lull"):
        if getattr(v, f"{h}_off"):
            out[h] = PART_OFF
        elif getattr(v, f"{h}_ms") is None:
            out[h] = PART_ABSENT
        elif added:
            out[h] = PART_ON
        elif stored is not None:
            out[h] = PART_ON if stored.get(h) == PART_ON else PART_WAITING
        else:
            out[h] = PART_ON if legacy_his else PART_WAITING
    if v.pre_drop_off:
        out[PRE_DROP] = PART_OFF
    elif v.pre_drop_ms is None:
        out[PRE_DROP] = PART_ABSENT
    elif added:
        out[PRE_DROP] = PART_ON
    elif stored is not None:
        out[PRE_DROP] = PART_ON if stored.get(PRE_DROP) == PART_ON else PART_WAITING
    else:
        # the legacy reading approves what he could see: a pre-drop he placed
        # himself; one found since waits, following its own tier
        out[PRE_DROP] = PART_ON if (legacy_his and v.moved.get(PRE_DROP)) else PART_WAITING
    if stored is not None and stored.get("drop") == PART_OFF:
        out["drop"] = PART_OFF
    elif added:
        out["drop"] = PART_ON
    elif stored is not None:
        out["drop"] = PART_ON if stored.get("drop") == PART_ON else PART_WAITING
    else:
        out["drop"] = PART_ON if legacy_his else PART_WAITING
    return {p: out[p] for p in PARTS}


def _view_state(ov: dict, edited: bool, tier: Optional[str]) -> Optional[str]:
    """The sequence's state from its override (STATES; PARTS MODE: only an
    approved drop makes it his — confirmed, or edited when a handle moved).
    None when nothing of his makes it anything but its tier."""
    if ov.get("state") == STATE_DISMISSED:
        return STATE_DISMISSED
    parts = ov.get("parts")
    if isinstance(parts, dict):
        if parts.get("drop") == PART_ON:
            return STATE_EDITED if edited else STATE_CONFIRMED
        return tier
    if edited:
        return STATE_EDITED
    if ov.get("state") == STATE_CONFIRMED:
        return STATE_CONFIRMED
    return tier


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
    moved = {h: ov.get(f"{h}_ms") is not None for h in EDIT_HANDLES}
    edited = (any(moved.values()) or bool(ov.get("lull_off")) or bool(ov.get("charge_off"))
              or bool(ov.get("pre_drop_off")))
    state = _view_state(ov, edited, seq.get("tier") or STATE_SUGGESTED)
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
        his = ov.get("drop_ms")
        # moved TO his own drop: there is nothing to choose between
        to_his = his is not None and abs(int(seq["drop_ms"]) - int(his)) <= REVIEW_BEATS * beat
        if (was is not None and not to_his
                and abs(int(seq["drop_ms"]) - int(was)) > REVIEW_BEATS * beat):
            v.needs_review = True
            v.notes.append(f"the analysis now finds this drop at {seq['drop_ms']} ms, "
                           f"not {was} ms: keep yours, or take the new place")
    _set_pre_view(v, _base_pre(seq), ov)
    _drop_automatic_out_of_order(v)
    stored_parts = ov.get("parts") if isinstance(ov.get("parts"), dict) else None
    v.parts = _part_states(v, stored_parts, _legacy_his(ov))
    return v


def _orphan_view(okey: str, ov: dict) -> Optional[SequenceView]:
    snap = ov.get("detected") or {}
    base = {"drop_ms": snap.get("drop_ms", drop_detector.key_ms(okey)),
            "lull_ms": snap.get("lull_ms"), "charge_ms": snap.get("charge_ms")}
    if base["drop_ms"] is None:
        return None
    eff = _effective(base, ov)
    moved = {h: ov.get(f"{h}_ms") is not None for h in EDIT_HANDLES}
    edited = (any(moved.values()) or bool(ov.get("lull_off")) or bool(ov.get("charge_off"))
              or bool(ov.get("pre_drop_off")))
    state = _view_state(ov, edited, None)
    if state is None:
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
    _set_pre_view(v, None, ov)
    _drop_automatic_out_of_order(v)
    stored_parts = ov.get("parts") if isinstance(ov.get("parts"), dict) else None
    v.parts = _part_states(v, stored_parts, _legacy_his(ov))
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
    if v.pre_drop_ms is not None and v.pre_drop_ms > v.drop_ms - floor:
        v.notes.append("your pre-drop left out: the drop now sits before it"
                       if v.moved.get(PRE_DROP) else
                       "automatic pre-drop left out: it no longer sits before your drop")
        v.pre_drop_ms = None


def _set_pre_view(v: SequenceView, base_pre: Optional[dict], rec: dict) -> None:
    """The view's pre-drop fields (module docstring's PRE-DROPS): the
    detector's tier and score only while the pre-drop is the detector's."""
    pre = _pre_drop_of(base_pre, rec)
    v.pre_drop_ms, v.pre_drop_kind, v.pre_drop_auto = pre["ms"], pre["kind"], pre["auto"]
    v.pre_drop_off, v.pre_drop_was = pre["off"], pre["was"]
    v.moved[PRE_DROP] = pre["moved"]
    if base_pre is not None and not pre["moved"]:
        v.pre_drop_tier = base_pre.get("tier")
        v.pre_drop_score = base_pre.get("score")


def _his_pre_drop_view(pre: Optional[dict], ov: Optional[dict], drop_ms: int) -> Optional[dict]:
    """The pre-drop of one of HIS OWN drops: the rules' (`pre`) with his
    edits to it (`ov`, the mine: override). None when it has none — or when
    one he placed no longer sits before his drop (he moved the drop since)."""
    ov = ov if isinstance(ov, dict) else {}
    cur = _pre_drop_of(_base_pre({"pre_drop": pre}), ov)
    at = cur["ms"] if cur["ms"] is not None else cur["was"]
    if at is None:
        return None
    if not cur["off"] and int(drop_ms) - int(at) < drop_detector.RAMP_FLOOR_MS:
        return None
    parts = ov.get("parts") if isinstance(ov.get("parts"), dict) else {}
    part = (PART_OFF if cur["off"]
            else PART_ON if parts.get(PRE_DROP) == PART_ON else PART_WAITING)
    det = pre if (isinstance(pre, dict) and not cur["moved"]) else None
    return {"ms": cur["ms"], "kind": cur["kind"], "auto": cur["auto"], "off": cur["off"],
            "was": cur["was"], "moved": cur["moved"], "lead_ms": int(drop_ms) - int(at),
            "score": det.get("score") if det else None,
            "tier": det.get("tier") if det else None, "part": part}


def _his_pre_drop_for(uri: str, stamp: Optional[str], drop: dict, compute: bool,
                      overrides: Optional[dict]) -> tuple[bool, Optional[dict]]:
    """(set it, the pre-drop) for one of his drops (`drop` its {id,
    timestamp_ms}): set when the rules' answer is known, or when he placed
    one himself; left unset while it is not worked out yet."""
    ms = int(drop["timestamp_ms"])
    ov = (overrides or {}).get(f"{MINE_PREFIX}{drop['id']}")
    known, pre = (his_pre_drop(uri, stamp, ms, compute=compute) if stamp
                  else (False, None))
    if known:
        return True, _his_pre_drop_view(pre, ov, ms)
    if isinstance(ov, dict) and ov.get("pre_drop_ms") is not None:
        return True, _his_pre_drop_view(None, ov, ms)
    return False, None


def his_pre_drop_ctx(uri: str, drop_id: str, drop_ms: int) -> dict:
    """What a pre-drop edit on one of his drops needs (drop_panel.py): the
    moment his drop fires and the rules' pre-drop against it, worked out
    now if it is not memoised (analysis I/O: call it off the event loop)."""
    det = stored(uri).get("detected")
    stamp = str(det["stamp"]) if isinstance(det, dict) and det.get("stamp") else None
    pre = his_pre_drop(uri, stamp, int(drop_ms), compute=True)[1] if stamp else None
    return {"drop_ms": int(drop_ms), "pre": pre, "key": f"{MINE_PREFIX}{drop_id}"}


def his_pre_drop_now(uri: str, ctx: dict) -> Optional[dict]:
    """The pre-drop of one of his drops as the panel shows it now (the
    HisPreDrop dict, None when it has none), from `his_pre_drop_ctx`."""
    ov = (stored(uri).get("overrides") or {}).get(ctx["key"])
    return _his_pre_drop_view(ctx.get("pre"), ov, int(ctx["drop_ms"]))


# His own drops' pre-drops (module docstring's PRE-DROPS): (uri, detection
# stamp, his drop's moment) -> predrop_detector.PreDrop.stored() or None.
_his_pre_drops: "dict[tuple, Optional[dict]]" = {}
_his_pre_drops_lock = threading.Lock()
HIS_PRE_DROPS_MEMO = 512


def his_pre_drop(uri: str, stamp: str, drop_ms: int, *,
                 compute: bool = False) -> tuple[bool, Optional[dict]]:
    """(known, pre-drop) for one of his drops at `drop_ms`: the memoised
    answer, or — with `compute` — the rules' answer against that moment
    (drop_detector.analyse, memoised on its own files). (False, None) when
    it is not worked out yet; (True, None) when it is and there is none."""
    key = (uri, stamp, int(drop_ms))
    with _his_pre_drops_lock:
        if key in _his_pre_drops:
            return True, _his_pre_drops[key]
    if not compute:
        return False, None
    try:
        analysis = drop_detector.analyse(uri)
    except drop_detector.Unavailable:
        found = None
    else:
        pre = predrop_detector.detect(analysis.shape, int(drop_ms))
        found = pre.stored() if pre is not None else None
    with _his_pre_drops_lock:
        _his_pre_drops[key] = found
        while len(_his_pre_drops) > HIS_PRE_DROPS_MEMO:
            _his_pre_drops.pop(next(iter(_his_pre_drops)))
    return True, found


def _attach_his_pre_drops(uri: str, stamp: Optional[str], groups: list[dict],
                          compute: bool, overrides: Optional[dict] = None) -> None:
    """`pre_drop` on each of his grouped drops (or his rows) whose answer is
    known, with his edits to it (the key left out where it is not worked out
    yet)."""
    for g in groups:
        d = g.get("drop")
        if not d:
            continue
        set_it, pre = _his_pre_drop_for(uri, stamp, d, compute, overrides)
        if set_it:
            g["pre_drop"] = pre


def view(uri: str, *, triggers: Optional[list] = None,
         compute_pre_drops: bool = False) -> dict:
    """Detected sequences merged with his edits and his own triggers — the
    read the Timeline (phase 3) draws. Never detects: the stored detection
    is what it shows (`status: "not_detected"` when there is none yet).
    `triggers`: this song's stored triggers, when the caller already
    holds them. `compute_pre_drops`: work out the pre-drops of his own
    grouped drops that are not memoised yet — analysis I/O, so only the
    read-through path (`view_with_detection`, off the event loop) asks."""
    entry = stored(uri)
    if triggers is None:
        from spectra.services import trigger_store
        triggers = trigger_store.list_for_song(uri)
    marks = his_marks(triggers)
    groups, lone = group_authored(marks)
    det = entry.get("detected")
    stamp = str(det["stamp"]) if isinstance(det, dict) and det.get("stamp") else None
    _attach_his_pre_drops(uri, stamp, groups, compute_pre_drops, entry.get("overrides"))
    out: dict = {"uri": uri, "authored": groups, "authored_lone": lone}
    if not isinstance(det, dict):
        out.update({"status": "not_detected", "reason": "this song has not been "
                    "analysed for drops yet (it is, the first time it plays)",
                    "detector": None, "song": None, "sequences": [], "excluded": [],
                    "counts": {}})
        _add_added(out, entry, marks, 500.0)
        out["counts"] = _counts(out["sequences"])
        out["yours"] = yours_rows(triggers, out["sequences"], entry.get("overrides"))
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
            d = _det_distance(s, k)
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
    out["yours"] = yours_rows(triggers, out["sequences"], overrides)
    _attach_his_pre_drops(uri, stamp, out["yours"], compute_pre_drops, overrides)
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
        _set_pre_view(v, None, rec)
        _drop_automatic_out_of_order(v)
        stored_parts = rec.get("parts") if isinstance(rec.get("parts"), dict) else None
        v.parts = _part_states(v, stored_parts, True, added=True)
        out["sequences"].append(v.as_dict())


def _all_phase_marks(triggers: list) -> tuple[list[HisMark], dict[str, bool], dict[str, int]]:
    """Every authored charge/lull/drop trigger of his, enabled OR switched
    off, by the moment it fires — and each one's enabled flag and its own
    `trigger_offset_ms` (the moment it fires is its stored time plus that
    offset, so a drag to a moment moves the stored time by the offset
    less — drop_panel.py's `move_handles`)."""
    marks: list[HisMark] = []
    enabled: dict[str, bool] = {}
    offsets: dict[str, int] = {}
    for t in triggers:
        if getattr(t, "source", "authored") != "authored":
            continue
        a = t.action
        if a.kind != "fire_response":
            continue
        cls = str(getattr(a, "event_class", None))
        if cls not in PHASE_CLASSES:
            continue
        offset = int(getattr(t, "trigger_offset_ms", 0) or 0)
        marks.append(HisMark(id=t.id, kind=cls, timestamp_ms=int(t.timestamp_ms + offset)))
        enabled[t.id] = bool(getattr(t, "enabled", True))
        offsets[t.id] = offset
    return sorted(marks, key=lambda m: m.timestamp_ms), enabled, offsets


def yours_rows(triggers: list, sequences: list[dict], overrides: Optional[dict] = None) -> list[dict]:
    """HIS OWN ROWS (module docstring): his charge/lull/drop triggers,
    enabled or switched off, grouped into drop-anchored rows the way
    `group_authored` groups the enabled ones. Each row: `key`
    ("his:<drop trigger id>", the Timeline's own key for his sequence),
    `charge`/`lull`/`drop` (each {id, kind, timestamp_ms — the moment it
    fires — enabled, offset_ms} or None),
    `enabled` (his drop is on), `detections` — every detection the row
    stands in for: standing down on a member of this row, or dismissed on
    behalf of his drop (`dismissed_for`) — and `detection`, the first."""
    marks, enabled, offsets = _all_phase_marks(triggers)
    groups, _lone = group_authored(marks)
    standing = [s for s in sequences
                if s.get("origin") == "detected" and s.get("state") == STATE_MATCHES_YOURS]
    held_for: dict[str, list[str]] = {}
    for okey, ov in (overrides or {}).items():
        if isinstance(ov, dict) and ov.get("dismissed_for"):
            held_for.setdefault(str(ov["dismissed_for"]), []).append(okey)
    rows = []
    for g in groups:
        members = {}
        for h in PHASE_CLASSES:
            m = g.get(h)
            members[h] = None if m is None else {**m, "enabled": enabled.get(m["id"], True),
                                                 "offset_ms": offsets.get(m["id"], 0)}
        drop = members["drop"]
        if drop is None:
            continue
        ids = {m["id"] for m in members.values() if m is not None}
        dets = [s["key"] for s in standing
                if any(x.get("id") in ids for x in s.get("matches") or [])]
        dets += [k for k in held_for.get(str(drop["id"]), []) if k not in dets]
        rows.append({"key": f"his:{drop['id']}", "charge": members["charge"],
                     "lull": members["lull"], "drop": drop,
                     "enabled": bool(drop["enabled"]), "detections": dets,
                     "detection": dets[0] if dets else None})
    return rows


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
                "beat_ms": None, "captured_from_ms": None, "spikes": [], "beats": [],
                "hits": [], "entries": []}
    song = analysis.song
    doc = analysis_reader.librosa_analysis_for_stem(song.stem) or {}
    flags = [bool(b.get("is_downbeat")) for b in doc.get("beats") or []]
    beats = [[int(round(float(ms))), 1 if i < len(flags) and flags[i] else 0]
             for i, ms in enumerate(song.beat_ms)]
    spikes = [[int(ms), round(float(rise), 3)]
              for ms, rise in zip(analysis.prep.att_ms, analysis.prep.att_rise)]
    # the pre-drop's two rails (predrop plan 3.1): what a dragged spike and
    # a dragged vocal intro snap to — the rules' own attacks and entries
    hits, entries = predrop_detector.rails(analysis.shape)
    return {"uri": uri, "status": "ok", "reason": None,
            "beat_ms": round(song.beat_len, 3), "captured_from_ms": int(song.t[0]),
            "spikes": spikes, "beats": beats, "hits": hits, "entries": entries}


def summary() -> dict:
    """Every song the store holds: what was detected, by tier, and how many
    edits he has made — a store read, never a detection. Factored out of
    spectra/api/drop_sequences.py's own `/summary` route so the route and
    Sonic's drop_console.py share one definition."""
    data = all_stored()
    songs = []
    for uri, entry in sorted(data.items()):
        if not isinstance(entry, dict):
            continue
        det = entry.get("detected") or {}
        tiers: dict[str, int] = {}
        for s in det.get("sequences") or []:
            tiers[s.get("tier")] = tiers.get(s.get("tier"), 0) + 1
        overrides = entry.get("overrides") or {}
        songs.append({
            "uri": uri,
            "detected": bool(det),
            "detected_at": det.get("detected_at"),
            "stamp": det.get("stamp"),
            "tiers": tiers,
            "excluded": len(det.get("excluded") or []),
            "overrides": len(overrides),
            "dismissed": sum(1 for o in overrides.values()
                             if isinstance(o, dict) and o.get("state") == STATE_DISMISSED),
            "added": len(entry.get("added") or []),
        })
    return {"songs": songs}


def view_with_detection(uri: str) -> dict:
    """Read-through: detect when missing or stale, then the merged view.
    Synchronous — call it off the event loop."""
    result = ensure_detected(uri)
    body = view(uri, compute_pre_drops=True)
    body["detection"] = result
    if result.get("status") == "unavailable" and body.get("status") == "not_detected":
        body["status"] = "unavailable"
        body["reason"] = result.get("reason")
    return body
