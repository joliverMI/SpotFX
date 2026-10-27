"""DROP SEQUENCES FIRE (drop-detection plan, phase 5 — report section 7.2,
the Admiral's approved decisions 2 and 3). Read this before touching
anything that decides whether a detected or added charge/lull/drop fires,
or where an analysed scene change or flare may land around one.

drop_sequences.py says what each sequence IS (detected, suggested,
confirmed, edited, added, matches yours, dismissed). This module is the
ONE answer to four questions about the same merged view, all pure (no
I/O, the view is handed in):

  WHAT FIRES (`firing_sequences`, gated by `fires_here`)
    confident            fires on a song that plays the analysed show — the
                         analysed flares' own rule (analysed_flares.
                         analysed_flares_allowed: effective mode "analysed",
                         or "full" on a song with no authored trigger).
    confirmed / edited / added
                         HIS (decision 3): fires wherever his triggers fire
                         ("full", "triggers_only") AND wherever the analysed
                         show plays — a sequence he confirmed is still the
                         analysed show's drop. Never under "transitions".
                         A sequence of his does NOT count as an authored
                         trigger for the "My triggers only" per-song
                         fallback: confirming one drop must not silence the
                         rest of a song's analysed show (the reason the plan
                         kept sequences out of triggers.json at all).
    suggested            never — it waits for his confirm. DROP TESTING
                         (RoomControlState.drop_testing, the Home Drops
                         panel's icon-only toggle) lifts that wait: while
                         it is on a suggestion fires exactly where a
                         confident one would (the analysed show's rule) —
                         Testing lifts the approval, never the mode.
    dismissed            never — and never in Testing either.
    PARTS (drop_sequences.py's PARTS): a sequence whose DROP part is off
                         never fires (listed, silent), in Testing too; a
                         charge or lull part that is off never fires; one
                         still WAITING fires with its sequence's tier (a
                         confident detection, or Testing) and only when its
                         drop fires. A view without `parts` (an older
                         caller) fires every member, as before.
    matches yours        stands down ONLY when his own trigger can actually
                         fire there — `his_applies(effective_mode)`, true
                         under "full"/"triggers_only" (the view's rule: one
                         of his charge/lull/drop within two beats of the
                         drop). Under any other mode — "analysed" is the
                         real case, report data/popoff-drops-not-firing/
                         report.md: his hand-authored trigger never fires
                         there under that mode either, so BOTH doors were
                         silent — it falls back to the sequence's OWN
                         classification instead: a confident detection
                         fires exactly as an unmatched confident one would
                         (as the analysed show); a suggestion still waits
                         for his confirm, matched or not; a confirmed/
                         edited/added sequence fires wherever the analysed
                         show plays (decision 3's own rule — see
                         `fires_here`; the fallback and decision 3 agree
                         here, both land on `analysed`, so a matched
                         confirmed/edited sequence needs no separate case).
                         An ADDED sequence sitting on one of his own phase
                         triggers stands down the same way (and falls back
                         the same way), and so does a single member of any
                         firing sequence that lands within two beats of his
                         own trigger of the same class — gated by the
                         SAME `his_applies(effective_mode)` rule, in
                         `FiringSequence.members`/`gap_ms` rather than in
                         `firing_sequences` itself (that function only ever
                         FLAGS a member in `stood_down`, mode-independent,
                         so it can stay memoisable without the room's
                         mode): nothing double-fires where his trigger
                         genuinely fires there, and nothing goes silent
                         where it can't (the same Pop Off shape one level
                         down — a matched charge/lull used to be excluded
                         unconditionally, even under "analysed", where his
                         trigger was never going to cover it either). Two
                         firing sequences on one drop keep his (added,
                         confirmed, edited) over a detection — deduped
                         unconditionally, never only when neither of them
                         `matches_his`.

  HOW EACH MEMBER FIRES
    as the existing charge, lull and drop responses — the same
    engine.fire_response_event path his own triggers take, never a scene
    change and never a flare. A charge builds to its OWN lull (or its drop
    with no lull), a lull to its own drop: phase_partner.build_target over
    the sequence's own members, the phase-1 rule, one function. Intensity
    is the drop's measured step up (`sequence_intensity`), the same for all
    three members, then the trigger clock's ordinary render scaling.

  THE PROTECTED WINDOW (`windows_from_view`)
    from the sequence's first member to two bars (TAIL_BEATS) after its
    drop. No analysed SCENE CHANGE lands inside it; no analysed FLARE fires
    during its lull (lull to drop) or at the drop itself (within two beats
    of it — the drop moment leaves the scene-change ranking altogether).
    Flares during the charge, and in the tail after the drop, are fine.
    Every sequence that is or may be fired is protected — confident,
    confirmed, edited, added — and so is each of HIS OWN grouped
    charge/lull/drop (the view's `authored` groups): a generated scene cue
    inside one of his sequences would break his build exactly as it would
    a detected one (plan section 2.3, Pop Off). Suggested and dismissed
    sequences protect nothing. The windows do not depend on the room's
    mode, so the planner (midsong_generator) can stamp them into stored
    cues; the trigger clock applies the same windows again at fire time,
    which covers a plan made before an edit or before detection landed.

  WHERE EACH PHASE IS (`phase_moments`)
    every moment this song plays a charge, a lull or a drop — the firing
    sequences' own members plus his own authored phase triggers, his
    winning a collision — read by a Light Show arm waiting for "the next
    drop / lull / charge" (spectra/services/show_arms.py's PHASE
    TRIGGERS). Mode-independent, like the High/Low cues it sits beside,
    and NOT relocated by the drop timing offset: see that function.

Every time is SONG time, the frame his triggers and the view are in.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Iterable, Optional

from spectra.services import (analysed_flares, drop_detector, drop_sequences,
                               drop_timing, phase_partner)

ID_PREFIX = "drop-seq:"
"""Synthetic trigger ids the trigger clock fires members under:
"drop-seq:<sequence key>:<charge|lull|drop>"."""

TAIL_BEATS = drop_detector.TAIL_BEATS
MATCH_BEATS = drop_sequences.MATCH_BEATS
DEFAULT_BEAT_MS = 500.0

HIS_STATES = (drop_sequences.STATE_CONFIRMED, drop_sequences.STATE_EDITED,
              drop_sequences.STATE_ADDED)
ANALYSED_STATES = (drop_sequences.STATE_CONFIDENT,)
PROTECTED_STATES = HIS_STATES + ANALYSED_STATES

HIS_MODES = ("full", "triggers_only")
"""The modes a hand-authored phase trigger of his actually fires under
(trigger_engine._trigger_allowed) — NOT "analysed": an authored charge,
lull or drop never fires there, which is exactly why a detection that
stood down to one under "analysed" used to go silent on both doors (the
Pop Off report). `analysed` show-plays-the-drop-anyway is a SEPARATE
condition (`analysed_flares.analysed_flares_allowed`), already ORed in
wherever this is consulted — see `fires_here`."""

# THE INTENSITY a sequence fires at, from the drop's measured step up (the
# detector's `step`, its contrast). Mapped linearly so the range his own
# drops carry comes out (his authored drops: median 0.78, quartiles
# 0.66-0.92): a step of STEP_LOW fires at INTENSITY_LOW, STEP_HIGH at 1.0,
# clamped. A sequence with no measured step (one he added) fires at
# DEFAULT_INTENSITY, his own median drop.
STEP_LOW = 0.4
STEP_HIGH = 1.2
INTENSITY_LOW = 0.6
DEFAULT_INTENSITY = 0.8


def sequence_intensity(step: Optional[float]) -> float:
    if step is None:
        return DEFAULT_INTENSITY
    try:
        s = float(step)
    except (TypeError, ValueError):
        return DEFAULT_INTENSITY
    frac = (s - STEP_LOW) / (STEP_HIGH - STEP_LOW)
    return round(max(INTENSITY_LOW, min(1.0, INTENSITY_LOW + frac * (1.0 - INTENSITY_LOW))), 4)


def beat_ms_of(view: dict) -> float:
    try:
        b = float(((view or {}).get("song") or {}).get("beat_ms") or 0.0)
    except (TypeError, ValueError):
        b = 0.0
    return b if b > 0 else DEFAULT_BEAT_MS


@dataclass(frozen=True)
class FiringSequence:
    """One sequence that may fire, with the members that survive the
    stand-down rules. `his` is True for confirmed, edited and added.

    `matches_his` is True when this sequence's DROP sits within two beats
    of one of his own enabled charge/lull/drop triggers — computed here
    unconditionally (mode-independent, like the rest of this function), so
    `firing_sequences` stays safe to memoise without the room's mode (the
    trigger clock does exactly that). The MODE-DEPENDENT decision — stand
    down because his trigger actually fires there, or fall back to this
    sequence's own tier because it doesn't — lives in `fires_here` for the
    sequence as a whole, and in `members`/`gap_ms`'s own `effective_mode`
    argument for one member standing down alone (a same-class authored
    mark near a member of a sequence that otherwise still fires): a member
    in `stood_down` is excluded ONLY when `effective_mode` is given and
    `his_applies(effective_mode)` is True — his own trigger can actually
    fire there. Without a mode (or whenever his trigger can't fire there),
    every declared member comes back, because nothing else will cover it.
    `charge_ms`/`lull_ms`/`drop_ms` always carry the sequence's OWN
    unmodified values — `stood_down` is a flag, never a mutation of them."""
    key: str
    state: str
    origin: str
    his: bool
    drop_ms: int
    lull_ms: Optional[int]
    charge_ms: Optional[int]
    intensity: float
    beat_ms: float
    # a member standing down alone because one of his own triggers of that
    # class fires within two beats of it: {"charge": his trigger id, ...}.
    # Only excluded from `members()`/`gap_ms()` when the caller names a
    # mode his trigger actually fires under — see the class docstring.
    stood_down: dict = field(default_factory=dict)
    matches_his: bool = False
    # Where this sequence's PRE-DROP plays, when it has one that may play
    # (PRE_DROPS_PLAY) — the moment the drop colour change starts its fade
    # (trigger_engine's THE DROP COLOUR CHANGE). Never a member: nothing
    # but the colour fade reads it yet.
    pre_drop_ms: Optional[int] = None

    def members(self, effective_mode: Optional[str] = None) -> list[tuple[str, int]]:
        exclude = (set(self.stood_down)
                  if effective_mode is not None and his_applies(effective_mode)
                  else set())
        out = []
        for cls, ms in (("charge", self.charge_ms), ("lull", self.lull_ms),
                        ("drop", self.drop_ms)):
            if ms is not None and cls not in exclude:
                out.append((cls, int(ms)))
        return out

    def trigger_id(self, cls: str) -> str:
        return f"{ID_PREFIX}{self.key}:{cls}"

    def gap_ms(self, cls: str, effective_mode: Optional[str] = None,
               drop_offset_ms: int = 0) -> Optional[int]:
        """How long `cls`'s build runs: to its own partner in this sequence
        (phase_partner's rule and reach). None for the drop. `effective_mode`
        resolves the same mode-aware member set `members()` does, so a
        stood-down neighbour never counts as `cls`'s partner in a mode
        where that neighbour isn't actually firing alongside it.
        `drop_offset_ms` is the room's drop timing offset (drop_timing.py):
        a build ending on the drop runs to where the drop FIRES, so its
        ramp and the breath-hold end on the shifted mark."""
        members = self.members(effective_mode)
        start = dict(members).get(cls)
        if start is None or cls not in phase_partner.BUILD_CLASSES:
            return None
        later = [(ms, c) for c, ms in members if c != cls]
        target = phase_partner.build_target(cls, start, later)
        return drop_timing.build_gap_ms(start, target.ms, target.target_class,
                                        drop_offset_ms)

    def build_start_ms(self, effective_mode: Optional[str] = None) -> Optional[int]:
        """The member the drop's build starts from — its lull, else its
        charge — for drop_timing's clamp."""
        members = dict(self.members(effective_mode))
        return members.get("lull", members.get("charge"))

    def resolved_stood_down(self, effective_mode: str) -> dict:
        """`stood_down`, but only when his own trigger actually fires in
        `effective_mode` — the display-field twin of `members()`'s own
        exclusion rule, for `annotate()`: a member the Timeline should show
        as standing down only when it genuinely isn't firing here."""
        return dict(self.stood_down) if his_applies(effective_mode) else {}


@dataclass(frozen=True)
class Window:
    """A protected window (module docstring). `source` is "sequence" for a
    detected or added sequence, "yours" for one of his own grouped
    charge/lull/drop."""
    key: str
    source: str
    start_ms: int
    lull_ms: Optional[int]
    drop_ms: int
    end_ms: int
    beat_ms: float

    def holds_scene_change(self, t: int) -> bool:
        return self.start_ms <= t <= self.end_ms

    def at_drop(self, t: int) -> bool:
        return abs(t - self.drop_ms) <= MATCH_BEATS * self.beat_ms

    def silences_flare(self, t: int) -> bool:
        if self.lull_ms is not None and self.lull_ms <= t < self.drop_ms:
            return True
        return self.at_drop(t)

    def as_list(self) -> list:
        return [self.start_ms, self.lull_ms, self.drop_ms, self.end_ms]


def _his_phase_marks(view: dict) -> list[tuple[str, int, str]]:
    """(class, ms, trigger id) for every one of his enabled phase triggers
    the view grouped (in a sequence or lone)."""
    out = []
    for g in (view or {}).get("authored") or []:
        for cls in ("charge", "lull", "drop"):
            m = g.get(cls)
            if m:
                out.append((cls, int(m["timestamp_ms"]), str(m.get("id"))))
    for m in (view or {}).get("authored_lone") or []:
        if m.get("kind") in phase_partner.PHASE_ORDER:
            out.append((m["kind"], int(m["timestamp_ms"]), str(m.get("id"))))
    return out


def _recovered_state(s: dict) -> Optional[str]:
    """For a sequence the view marked `matches_yours` (drop_sequences.py's
    own "even when confirmed" rule), what it would be WITHOUT that
    override — the fallback `_candidates` and `firing_sequences` need so a
    mode that does not actually fire his own trigger there (`his_applies`
    False) can still let the sequence fire by its own tier, instead of
    going silent on both doors (the Pop Off report). Recovered from fields
    the view already carries, never a second read of the store: a moved
    handle or a switched-off lull/charge means EDITED (his); otherwise a
    confident detector tier stands in for "fires via the analysed show".
    Returns None for a plain, unconfirmed, unedited SUGGESTED detection
    that happens to match one of his marks — it still only waits for his
    confirm, matched or not.

    THE ONE GAP, named rather than hidden: a bare `confirm` with no handle
    edit on a tier-SUGGESTED detection that also matches one of his own
    marks cannot be told apart here from an unconfirmed suggestion (the
    view exposes no "confirmed" flag once `matches_yours` has overwritten
    `state`). It is treated as the unconfirmed case — it waits — which is
    the conservative direction (it costs him a redundant confirm press on
    a sequence his own hand-authored trigger already covers in every mode
    that fires that trigger; it never double-fires)."""
    moved = s.get("moved") or {}
    if (any(moved.values()) or s.get("lull_off") or s.get("charge_off")
            or s.get("pre_drop_off")):
        return drop_sequences.STATE_EDITED
    if s.get("tier") == drop_detector.TIER_CONFIDENT:
        return drop_sequences.STATE_CONFIDENT
    return None


def _member_ms(s: dict, cls: str, testing: bool) -> Optional[int]:
    """`cls`'s time when that part may play (module docstring's PARTS):
    present, not off, and approved — or still waiting on a sequence whose
    tier plays on its own, or in Testing. A view without `parts` plays
    every member it has, as before parts existed."""
    ms = s.get(f"{cls}_ms")
    if ms is None:
        return None
    part = (s.get("parts") or {}).get(cls)
    if part == drop_sequences.PART_OFF:
        return None
    if part == drop_sequences.PART_WAITING and not (
            testing or s.get("tier") == drop_detector.TIER_CONFIDENT):
        return None
    return int(ms)


# THE PRE-DROP HAS NO ENGINE YET (predrop plan, steps 3-5): a sequence's
# pre-drop time is read into FiringSequence.pre_drop_ms only while this is
# True, and the step that builds the pre-drop engine (plan step 5) turns it
# on. Until then the view may carry pre-drop times (steps 3-4 detect, draw
# and edit them) and nothing plays from them: the drop colour change stays
# instant on every drop, its fade across the pre-drop built and tested but
# dormant (tests/test_drop_colour.py switches this on to prove it).
PRE_DROPS_PLAY = False


def _candidates(view: dict, testing: bool = False) -> list[FiringSequence]:
    beat = beat_ms_of(view)
    out = []
    for s in (view or {}).get("sequences") or []:
        state = s.get("state")
        if state == drop_sequences.STATE_DISMISSED:
            continue
        if (s.get("parts") or {}).get("drop") == drop_sequences.PART_OFF:
            continue                     # listed, silent — in Testing too
        if state == drop_sequences.STATE_MATCHES_YOURS:
            state = _recovered_state(s)
            if state is None:
                if not testing:
                    continue
                state = drop_sequences.STATE_SUGGESTED
        elif state == drop_sequences.STATE_SUGGESTED:
            if not testing:
                continue
        elif state not in PROTECTED_STATES:
            continue
        try:
            out.append(FiringSequence(
                key=str(s["key"]), state=state, origin=str(s.get("origin")),
                his=state in HIS_STATES, drop_ms=int(s["drop_ms"]),
                lull_ms=_member_ms(s, "lull", testing),
                charge_ms=_member_ms(s, "charge", testing),
                intensity=sequence_intensity(s.get("step")), beat_ms=beat,
                pre_drop_ms=(_member_ms(s, "pre_drop", testing)
                             if PRE_DROPS_PLAY else None)))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def firing_sequences(view: dict, testing: bool = False) -> list[FiringSequence]:
    """Every sequence in the view that may fire on its own terms (module
    docstring's WHAT FIRES, before the room's mode), flagged for the
    stand-down rules, in drop order. The mode gate is `fires_here`;
    `FiringSequence.members`/`gap_ms` resolve the per-member stand-down for
    a given mode.

    A sequence whose drop coincides with one of his own phase marks is
    KEPT here, flagged `matches_his=True`, never excluded outright — this
    function must stay mode-independent (the trigger clock memoises its
    result without the room's mode in the key), so the actual stand-down-
    or-fall-back decision is `fires_here`'s alone, not this one's. The SAME
    rule applies one level down: a single member within reach of a
    same-class authored mark is only ever FLAGGED in `stood_down` here,
    never excluded from `charge_ms`/`lull_ms` — excluding it unconditionally
    would silence it in every mode, including one where his own trigger
    can't fire there either (the Pop Off report's own shape: "analysed"
    stood a matched charge/lull down to a door that was never open).

    Two kept sequences near the same drop are deduped UNCONDITIONALLY
    (never skipped just because one of them `matches_his`) — his own
    authored mark only decides which of them wins when his sort already
    put it first (`kept` never holds two near one drop); it is not a
    license to let two independently-kept sequences fire on top of each
    other because they happen to both sit near the same mark.

    `testing` is RoomControlState.drop_testing (module docstring): it adds
    the suggestions, and the waiting parts of any detection."""
    reach = MATCH_BEATS * beat_ms_of(view)
    marks = _his_phase_marks(view)
    kept: list[FiringSequence] = []
    # his first, so a detection on the same drop yields to his
    for seq in sorted(_candidates(view, testing), key=lambda s: (not s.his, s.drop_ms)):
        if any(abs(seq.drop_ms - k.drop_ms) <= reach for k in kept):
            continue                     # another firing sequence owns this drop
        matches_his = any(abs(seq.drop_ms - ms) <= reach for _cls, ms, _id in marks)
        stood = {}
        for cls, ms, tid in marks:
            if cls == "lull" and seq.lull_ms is not None and abs(seq.lull_ms - ms) <= reach:
                stood["lull"] = tid
            if cls == "charge" and seq.charge_ms is not None and abs(seq.charge_ms - ms) <= reach:
                stood["charge"] = tid
        kept.append(replace(seq, stood_down=stood, matches_his=matches_his))
    return sorted(kept, key=lambda s: s.drop_ms)


def his_applies(effective_mode: str) -> bool:
    return effective_mode in HIS_MODES


def fires_here(seq: FiringSequence, effective_mode: str, song_has_authored: bool) -> bool:
    """The room's gate for one sequence (module docstring's WHAT FIRES).
    `effective_mode` is trigger_engine._effective_mode_for_song's answer;
    `song_has_authored` is whether the song carries any authored trigger
    (sequences of his never count toward it).

    A sequence that matches one of his own marks (`matches_his`) stands
    down ONLY while his own trigger actually fires there
    (`his_applies(effective_mode)`); otherwise it falls back to firing on
    its own terms, same as an unmatched sequence of the same kind — which
    is exactly `analysed` here, since `his_applies` is false in that
    branch by construction (`seq.his`'s own `analysed or his_applies`
    reduces to plain `analysed` the moment `his_applies` is false), so a
    matched confident, confirmed, edited or added sequence all land on the
    identical boolean once standing down is off the table."""
    analysed = analysed_flares.analysed_flares_allowed(effective_mode, song_has_authored)
    if seq.matches_his and his_applies(effective_mode):
        return False
    if seq.his:
        return analysed or his_applies(effective_mode)
    return analysed


def windows_from_view(view: dict, testing: bool = False) -> list[Window]:
    """The protected windows for one song (module docstring), in time
    order. Mode-independent. `testing` protects the suggestions Testing
    fires too — the trigger clock passes it at fire time; the planner
    (`protected_windows`) never does, so switching Testing on or off never
    re-plans a song's stored cues: a cue planned into a suggestion's window
    is held back at fire time instead, the existing safety net."""
    beat = beat_ms_of(view)
    tail = int(round(TAIL_BEATS * beat))
    out: list[Window] = []
    for s in _candidates(view, testing):
        start = s.charge_ms if s.charge_ms is not None else (
            s.lull_ms if s.lull_ms is not None else s.drop_ms)
        out.append(Window(s.key, "sequence", int(start), s.lull_ms, s.drop_ms,
                          s.drop_ms + tail, beat))
    for g in (view or {}).get("authored") or []:
        d = g.get("drop")
        if not d:
            continue
        drop = int(d["timestamp_ms"])
        lull = int(g["lull"]["timestamp_ms"]) if g.get("lull") else None
        charge = int(g["charge"]["timestamp_ms"]) if g.get("charge") else None
        start = charge if charge is not None else (lull if lull is not None else drop)
        out.append(Window(f"his:{d.get('id')}", "yours", start, lull, drop, drop + tail, beat))
    return sorted(out, key=lambda w: (w.start_ms, w.drop_ms))


PHASE_CLASSES = tuple(phase_partner.PHASE_ORDER)
"""The three phase classes, in the order a sequence runs them — read off
phase_partner's own ordering rather than re-typed."""


@dataclass(frozen=True)
class PhaseMoment:
    """One moment this song plays a charge, a lull or a drop — the unit a
    Light Show arm on "the next drop / lull / charge" waits for
    (show_arms.PHASE_TRIGGERS).

    `source` is "yours" for one of his own authored phase triggers and
    "sequence" for a drop-sequence member; `key` is that trigger's id
    (prefixed "his:") or the sequence's own key, so a caller can say which
    shape on the Timeline a moment belongs to."""
    cls: str
    ms: int
    source: str
    key: str


def phase_moments(view: dict, testing: bool = False) -> list[PhaseMoment]:
    """Every moment this song plays a charge / lull / drop, in time order —
    the same shapes the Timeline draws as phases, MODE-INDEPENDENTLY.

    THE RULE, and why it is not `fires_here`'s: a Light Show arm on "the
    next drop" waits for a moment in the MUSIC, the same way an arm on the
    next High Trigger does (show_cues.py's own "a cue exists on every
    analysed song, his own triggers or not"). So this reads every sequence
    `firing_sequences` keeps — which is already the mode-independent
    candidate set: a confident detection, or one he confirmed, edited or
    added, a SUGGESTED one excluded because it waits for his confirm and a
    DISMISSED one because he said no — plus his own authored phase
    triggers, grouped or lone. A member `stood_down` because one of his
    own marks sits on it is still a moment (his own mark supplies it), so
    `members()` is asked WITHOUT a mode: nothing here is narrowed by the
    room's scene-change tier, and nothing here does I/O.

    HIS OWN MARK WINS A COLLISION. A detection that matches one of his
    triggers would otherwise yield the same drop twice, a beat apart, so
    moments of one class within MATCH_BEATS of an already-kept one are
    dropped — his first (the sort), exactly as `firing_sequences` keeps
    his sequence over a detection on the same drop.

    NOT RELOCATED BY THE DROP TIMING OFFSET (drop_timing.py, default
    -400 ms), deliberately: these are the marks the Timeline draws and the
    drop-sequence data carries, the offset is resolved per fire from the
    room AND the SHOWING scene (so it is neither constant nor knowable
    without I/O on the trigger clock's own tick), and an arm landing on
    the mark rather than 400 ms before the particle burst is the honest
    reading of "the next drop" — see show_arms.py's own PHASE TRIGGERS
    section."""
    reach = MATCH_BEATS * beat_ms_of(view)
    cands: list[PhaseMoment] = []
    for cls, ms, tid in _his_phase_marks(view):
        if cls in PHASE_CLASSES:
            cands.append(PhaseMoment(cls=cls, ms=int(ms), source="yours",
                                     key=f"his:{tid}"))
    for seq in firing_sequences(view, testing):
        for cls, ms in seq.members():
            cands.append(PhaseMoment(cls=cls, ms=int(ms), source="sequence",
                                     key=seq.key))
    out: list[PhaseMoment] = []
    # his first within each class, then in time order, so a detection on
    # one of his own marks yields to it
    for m in sorted(cands, key=lambda m: (m.cls, m.source != "yours", m.ms)):
        if any(o.cls == m.cls and abs(o.ms - m.ms) <= reach for o in out):
            continue
        out.append(m)
    return sorted(out, key=lambda m: (m.ms, phase_partner.PHASE_ORDER.get(m.cls, 9)))


def holding_window(windows: Iterable[Window], t: int) -> Optional[Window]:
    """The window that keeps a scene change off moment `t`, if any."""
    return next((w for w in windows if w.holds_scene_change(t)), None)


def silencing_window(windows: Iterable[Window], t: int) -> Optional[Window]:
    """The window that keeps an analysed flare off moment `t`, if any."""
    return next((w for w in windows if w.silences_flare(t)), None)


def protected_windows(uri: str, triggers: Optional[list] = None) -> list[Window]:
    """The song's windows read from the store — for the planner and the
    API. Never raises: an unreadable store protects nothing (and says so
    in the log), it never stops a song being planned."""
    import logging
    try:
        return windows_from_view(drop_sequences.view(uri, triggers=triggers))
    except Exception:                                    # noqa: BLE001
        logging.getLogger(__name__).exception(
            "drop sequences: windows unreadable for %s", uri)
        return []


def annotate(view: dict, effective_mode: str, song_has_authored: bool,
             testing: bool = False) -> dict:
    """The view with what fires HERE, for the Timeline: each sequence gains
    `fires` (bool) and `fires_reason`; the body gains `firing` (the room's
    gate for the two kinds) and `windows`. Returns a new dict.

    A `matches_yours` sequence is no longer an automatic "never": it looks
    itself up in `firing_sequences` (which now recovers one, flagged
    `matches_his`, whenever its own tier/edit would otherwise make it a
    candidate — `_recovered_state`) and lets `fires_here` decide. Only a
    `matches_yours` sequence `firing_sequences` could not recover (a bare,
    unconfirmed, unedited SUGGESTED one — `f is None`) or one `fires_here`
    stood down because his trigger genuinely fires there this mode
    (`f.matches_his` and not firing) still reports `"matches_yours"`.

    PARTS AND TESTING: a sequence whose drop part is off reports
    `"switched_off"`; a suggestion fires only with `testing` (reason
    `"testing"`); a firing sequence's `playing` names the members that
    actually fire here (an off or still-waiting part left out)."""
    seqs = {s.key: s for s in firing_sequences(view, testing)}
    # THE DROP-LED SWITCH's decisions this play (spectra/services/
    # drop_switch.py) — what each sequence did or will do to the scene,
    # named on the Timeline's drop strip. Absent until the clock decides.
    from spectra.services import drop_switch
    switches = {p.key: p.as_dict()
                for p in drop_switch.plans_for((view or {}).get("uri"))}
    analysed = analysed_flares.analysed_flares_allowed(effective_mode, song_has_authored)
    his = analysed or his_applies(effective_mode)
    out_seqs = []
    for s in (view or {}).get("sequences") or []:
        s = dict(s)
        f = seqs.get(s.get("key"))
        state = s.get("state")
        if state == drop_sequences.STATE_DISMISSED:
            fires, why = False, "dismissed"
        elif (s.get("parts") or {}).get("drop") == drop_sequences.PART_OFF:
            fires, why = False, "switched_off"
        elif state == drop_sequences.STATE_SUGGESTED and not testing:
            fires, why = False, "waits_for_confirm"
        elif f is None:
            fires, why = False, "matches_yours"
        elif fires_here(f, effective_mode, song_has_authored):
            fires = True
            why = ("his" if f.his else
                   "testing" if f.state == drop_sequences.STATE_SUGGESTED else "analysed_show")
            s["stood_down"] = f.resolved_stood_down(effective_mode)
            s["intensity"] = f.intensity
            s["playing"] = [cls for cls, _ms in f.members(effective_mode)]
        elif f.matches_his:
            fires, why = False, "matches_yours"
        else:
            fires, why = False, ("transitions_only" if effective_mode == "transitions"
                                 else "analysed_show_off")
        s["fires"] = fires
        s["fires_reason"] = why
        if s.get("key") in switches:
            s["switch"] = switches[s["key"]]
        out_seqs.append(s)
    out = dict(view or {})
    out["sequences"] = out_seqs
    out["firing"] = {"effective_mode": effective_mode, "has_authored": song_has_authored,
                     "analysed_applies": analysed, "his_applies": his,
                     "testing": bool(testing)}
    out["windows"] = [{"key": w.key, "source": w.source, "start_ms": w.start_ms,
                       "lull_ms": w.lull_ms, "drop_ms": w.drop_ms, "end_ms": w.end_ms}
                      for w in windows_from_view(view, testing)]
    return out


def annotated_view(uri: str, view: Optional[dict] = None,
                   triggers: Optional[list] = None) -> dict:
    """`annotate` against the room as it is now: this song's stored
    triggers, the room's scene-change setting, resolved per song exactly
    as the trigger clock does (trigger_engine._effective_mode_for_song),
    and drop Testing. Reads the trigger store and room controls — call it
    off the event loop."""
    if triggers is None:
        from spectra.services import trigger_store
        triggers = trigger_store.list_for_song(uri)
    if view is None:
        view = drop_sequences.view(uri, triggers=triggers)
    from spectra.services.room_controls import load_room_controls
    from spectra.services.trigger_engine import TriggerEngine
    controls = load_room_controls()
    mode = TriggerEngine._effective_mode_for_song(controls.scene_change_mode, triggers)
    has_authored = any(getattr(t, "source", None) == "authored" for t in triggers)
    return annotate(view, mode, has_authored, testing=bool(controls.drop_testing))
