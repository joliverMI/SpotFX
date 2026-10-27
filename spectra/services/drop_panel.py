"""THE HOME DROPS PANEL'S WRITES (2026-10-26, predrop plan step 1 —
/home/javi/fleet-spotfx/data/predrop-plan/report.md section 3.6). One place
for every edit the panel and Sonic make to a drop: a part's toggle, the
double tick, Remove, switching one of his drops back on, and the undo that
puts any of them back. The panel's rows are of three kinds, and each kind's
writes land in its own store:

  a detection, or a drop he ADDED
      drop_sequences.py (storage/spectra/drop_sequences.json) — `parts`,
      `approve`, `remove` (a detection is dismissed, an added drop deleted).
  one of HIS OWN drops ("his:<drop trigger id>", the view's `yours` rows)
      his song profile, through the root process's narrow route (routers/
      profiles.py `POST /api/profiles/triggers/edit`, services/
      profile_trigger_edit.py): a part switched off, or Remove, DELETES a
      trigger he placed by hand and SWITCHES OFF an imported one (the
      Admiral's answer 6: "it can remove ones i manually added and disables
      imported ones"). The route runs the whole-song sync, so the copy
      SPECTRA fires from follows, and the root process decides which is
      which — the rule lives beside the profile it reads. A trigger of his
      BORN ON SPECTRA'S OWN TRIGGER CARD (in the fired copy, never seen in
      any profile: profile_sync_ledger.py's conservative reading) has no
      profile row to change, so it is written in the fired copy directly —
      it was placed by hand, so it is deleted (none of his charge/lull/drop
      triggers is card-born today, 2026-10-25; the plan's own rule).

WHY HIS ROWS ALSO WRITE THE DROP STORE. Under "analysed" — his room's mode —
his own charge/lull/drop triggers never fire; the detection standing in for
his drop does (drop_firing.py's Pop Off fallback). So switching his drop off,
or removing it, also DISMISSES the detection(s) the row stood in for, with
the override as it was kept beside it (`drop_sequences._op_dismiss_for`), and
switching his drop back on puts them back; switching his charge or lull off
also switches that part off on the standing detection. That is what makes
"off" mean silent in every mode, as he asked: "Don't play ones that have
been 'removed' or disabled, even in testing."

ONE UNDO STEP ACROSS BOTH STORES. Every write answers the drop store's own
before/after pair (drop_sequences.EditResult) PLUS the rows of his triggers
it changed (`profile`: [{id, before, after, index, did}], a card-born one
marked `store: "fired"`). `restore` takes the pair and those rows the other
way round: it checks the drop store has not changed since (`expect`),
restores his trigger rows (each must still be what the edit left), then the
drop store; a later write that fails after an earlier one succeeded is
compensated by putting the earlier rows back, so a refusal leaves every
store as it was. The order between stores on an edit is his triggers first
(profile, then fired copy): a root process that does not answer refuses the
whole edit (`ProfileUnavailable`), and nothing is written anywhere.

SPECTRA reaches the root process over HTTP (spectra/ imports nothing from
the root app — scripts/check_process_split.py), the lock_console.py
precedent; `http` is injectable for tests (no live access, ever).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from spectra.services import drop_sequences as ds

logger = logging.getLogger(__name__)

HIS_PREFIX = "his:"
HTTP_TIMEOUT_S = 15.0           # the route runs a whole-song sync (~0.2 s)


class ProfileUnavailable(RuntimeError):
    """The root process did not answer: nothing was changed."""


class ProfileRefused(RuntimeError):
    """The root process refused the profile write (unknown id, a trigger
    that is not a charge/lull/drop, a stale restore)."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


# ── the transport (lock_console.py's shape) ───────────────────────────────

def _base_url() -> str:
    try:
        from spectra.services import engine
        return engine.bridge.http_url
    except Exception:                                    # noqa: BLE001
        from spectra.services.bridge import default_http_url
        return default_http_url()


async def _http(method: str, path: str, *, params: Optional[dict] = None,
                json: Any = None):
    import httpx
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_S) as client:
        return await client.request(method, f"{_base_url()}{path}",
                                    params=params, json=json)


#: injectable for tests
http = _http


async def _root(method: str, path: str, **kw) -> dict:
    try:
        resp = await http(method, path, **kw)
    except Exception as exc:                             # noqa: BLE001
        raise ProfileUnavailable(
            f"SpotFX (the root process, which keeps his song profiles) did not "
            f"answer: {exc}") from exc
    if resp.status_code >= 500:
        raise ProfileUnavailable(f"SpotFX answered HTTP {resp.status_code}")
    try:
        body = resp.json()
    except Exception:                                    # noqa: BLE001
        body = {}
    if resp.status_code >= 400:
        detail = body.get("detail") if isinstance(body, dict) else None
        raise ProfileRefused(resp.status_code, str(detail or resp.text or resp.status_code))
    return body if isinstance(body, dict) else {}


async def provenance(uri: str) -> dict:
    """His phase triggers in this song's profile: each one placed by hand or
    imported, and what Remove would do to it."""
    return await _root("GET", "/api/profiles/triggers/provenance", params={"uri": uri})


async def panel_provenance(uri: str) -> dict:
    """What Remove (or a part switched off) would do to each charge/lull/drop
    trigger of his on this song — the root's answer for his song profile
    plus the ones born on SPECTRA's own trigger card (`card_born_rows`).
    The panel's route and Sonic share it. A song with no profile is
    `status: "no_profile"` (its card-born rows still named); a root that
    does not answer is `status: "unknown"` with the reason, never a guess.
    Any other refusal raises (ProfileRefused)."""
    card = await asyncio.to_thread(card_born_rows, uri)
    try:
        body = await provenance(uri)
    except ProfileRefused as exc:
        if exc.status != 404:
            raise
        return {"uri": uri, "imported_profile": None, "triggers": card,
                "status": "no_profile"}
    except ProfileUnavailable as exc:
        return {"uri": uri, "imported_profile": None, "triggers": card,
                "status": "unknown", "reason": str(exc)}
    held = {str(t.get("id")) for t in body.get("triggers") or []}
    return {**body, "triggers": [*(body.get("triggers") or []),
                                 *(t for t in card if t["id"] not in held)]}


def card_born_rows(uri: str) -> list[dict]:
    """His charge/lull/drop triggers born on SPECTRA's own trigger card, in
    the provenance answer's own shape: each was placed by hand, so Remove
    deletes it (module docstring). Read from the fired copy — call it off
    the event loop."""
    from spectra.services import trigger_store
    marks, enabled, _offsets = ds._all_phase_marks(trigger_store.list_for_song(uri))
    card = _card_born(uri, [m.id for m in marks])
    return [{"id": m.id, "event_id": None, "timestamp_ms": m.timestamp_ms,
             "enabled": enabled.get(m.id, True), "imported": False,
             "why": "spectra_card", "remove_would": "delete"}
            for m in marks if m.id in card]


async def _profile_edit(uri: str, **ops) -> list[dict]:
    """The root route's write. When its whole-song sync did not land, every
    changed row says so (`unsynced`: the sync's own status word) — his
    profile changed, but the copy the room fires from has not caught up
    (an explicit Timeline save of the song brings it level; the automatic
    catch-up is upsert-only, so a deletion waits for that save)."""
    body = await _root("POST", "/api/profiles/triggers/edit", json={"uri": uri, **ops})
    changes = list(body.get("changed") or [])
    sync = body.get("spectra_sync") or {}
    if changes and sync.get("status") != "ok":
        for c in changes:
            c["unsynced"] = str(sync.get("status") or "unknown")
    return changes


# ── his triggers: the song profile, or the fired copy (card-born) ────────

FIRED = "fired"
"""A change record's `store` when the row is in the fired copy only (a
trigger born on SPECTRA's own trigger card — module docstring)."""


def _card_born(uri: str, ids) -> set[str]:
    """The ids among `ids` born on SPECTRA's own trigger card: in the copy
    SPECTRA fires from but never seen in his song profile — the sync
    ledger's conservative reading (profile_sync_ledger.py's docstring)."""
    from spectra.services import profile_sync_ledger
    known = profile_sync_ledger.for_song(profile_sync_ledger.load(), uri)
    return {str(i) for i in ids if str(i) not in known}


def _fired_rows(data: dict, uri: str) -> list:
    rows = data.get(uri)
    return rows if isinstance(rows, list) else []


def _fired_edit(uri: str, remove: list, enable: list, move: list) -> list[dict]:
    """The card-born half of a write, in the fired copy, in ONE locked
    read+write (trigger_store's write_lock and its load_raw/save_raw pair,
    so every other row stays exactly as it sits on disk). Every id is
    checked before anything is written. A removed card-born trigger was
    placed by hand, so it is deleted (answer 6)."""
    from spectra.services import trigger_store
    if not (remove or enable or move):
        return []
    with trigger_store.write_lock:
        data = trigger_store.load_raw()
        rows = _fired_rows(data, uri)
        index = {str(r.get("id")): i for i, r in enumerate(rows) if isinstance(r, dict)}
        for tid in [*remove, *enable, *(m["id"] for m in move)]:
            if str(tid) not in index:
                raise ds.SequenceNotFound(f"no trigger {tid!r} of yours on this song")
        for m in move:
            if int(m["timestamp_ms"]) < 0:
                raise ds.InvalidEdit("a trigger cannot sit before the song starts")
        changes: list[dict] = []
        for m in move:
            i = index[str(m["id"])]
            before = dict(rows[i])
            rows[i] = {**rows[i], "timestamp_ms": int(m["timestamp_ms"])}
            changes.append({"id": str(m["id"]), "before": before, "after": dict(rows[i]),
                            "index": i, "did": "moved", "store": FIRED})
        for tid in enable:
            i = index[str(tid)]
            before = dict(rows[i])
            rows[i] = {**rows[i], "enabled": True}
            changes.append({"id": str(tid), "before": before, "after": dict(rows[i]),
                            "index": i, "did": "switched_on", "store": FIRED})
        gone = sorted((index[str(t)] for t in remove), reverse=True)
        for i in gone:
            changes.append({"id": str(rows[i].get("id")), "before": dict(rows[i]),
                            "after": None, "index": i, "did": "deleted", "store": FIRED})
            del rows[i]
        if rows:
            data[uri] = rows
        else:
            data.pop(uri, None)
        trigger_store.save_raw(data)
    return changes


def _fired_restore(uri: str, records: list[dict]) -> list[dict]:
    """Put card-born rows back (`from` → `to`, None = absent), each only if
    it is still what the write left: otherwise nothing is restored."""
    from spectra.services import trigger_store
    if not records:
        return []
    with trigger_store.write_lock:
        data = trigger_store.load_raw()
        rows = _fired_rows(data, uri)
        by_id = {str(r.get("id")): r for r in rows if isinstance(r, dict)}
        for rec in records:
            if by_id.get(str(rec["id"])) != rec.get("from"):
                raise ds.EditConflict(
                    f"your trigger {rec['id']!r} changed since — nothing was undone; "
                    "reload and try again")
        changes: list[dict] = []
        # removals first (each found by its id); then the rows put back,
        # lowest recorded index first, each at its old place
        for rec in records:
            if rec.get("to") is None:
                cur = by_id[str(rec["id"])]
                i = rows.index(cur)
                changes.append({"id": str(rec["id"]), "before": dict(cur), "after": None,
                                "index": i, "did": "restored", "store": FIRED})
                del rows[i]
        for rec in sorted((r for r in records if r.get("to") is not None),
                          key=lambda r: (r.get("index") is None, r.get("index") or 0)):
            cur = by_id.get(str(rec["id"]))
            to = dict(rec["to"])
            if cur is not None:
                i = rows.index(cur)
                rows[i] = to
            else:
                i = rec.get("index")
                i = len(rows) if not isinstance(i, int) else max(0, min(i, len(rows)))
                rows.insert(i, to)
            changes.append({"id": str(rec["id"]), "before": None if cur is None else dict(cur),
                            "after": dict(to), "index": i, "did": "restored", "store": FIRED})
        if rows:
            data[uri] = rows
        else:
            data.pop(uri, None)
        trigger_store.save_raw(data)
    return changes


def _split_records(records: list[dict]) -> tuple[list[dict], list[dict]]:
    root = [r for r in records if r.get("store") != FIRED]
    fired = [r for r in records if r.get("store") == FIRED]
    strip = lambda r: {k: v for k, v in r.items() if k != "store"}   # noqa: E731
    return [strip(r) for r in root], fired


async def _his_write(uri: str, *, remove=(), enable=(), move=()) -> list[dict]:
    """His triggers' half of one write (module docstring): a trigger from his
    song profile through the root route, a card-born one in the fired copy.
    The profile goes first; a fired-copy write that fails after it is
    compensated, so a refusal leaves both as they were."""
    remove, enable, move = list(remove), list(enable), list(move)
    card = await asyncio.to_thread(
        _card_born, uri, [*remove, *enable, *(m["id"] for m in move)])
    if card:
        # the ledger never saw these in a profile; a row his profile does
        # hold after all is still his profile's (a fired-copy-only write
        # would come back with his next Timeline save)
        try:
            held = {str(t.get("id")) for t in (await provenance(uri)).get("triggers") or []}
        except ProfileRefused as exc:
            if exc.status != 404:
                raise
            held = set()                 # no profile at all for this song
        card -= held
    ops = {"remove": [i for i in remove if str(i) not in card],
           "enable": [i for i in enable if str(i) not in card],
           "move": [m for m in move if str(m["id"]) not in card]}
    ops = {k: v for k, v in ops.items() if v}
    changes = await _profile_edit(uri, **ops) if ops else []
    try:
        changes += await asyncio.to_thread(
            _fired_edit, uri, [i for i in remove if str(i) in card],
            [i for i in enable if str(i) in card],
            [m for m in move if str(m["id"]) in card])
    except Exception:
        await _put_back(uri, changes)
        raise
    return changes


async def _his_restore(uri: str, records: list[dict]) -> list[dict]:
    """Restore records for his trigger rows, each to its own store (profile
    first); a fired-copy restore that fails puts the profile rows back."""
    root, fired = _split_records(records)
    changes = await _profile_edit(uri, restore=root) if root else []
    try:
        changes += await asyncio.to_thread(_fired_restore, uri, fired)
    except Exception:
        await _put_back(uri, changes)
        raise
    return changes


async def _put_back(uri: str, changes: list[dict]) -> None:
    """Best-effort compensation: undo `changes` (his trigger rows) after a
    later write in the same step was refused."""
    if not changes:
        return
    root, fired = _split_records(_reverse(changes))
    try:
        if fired:
            await asyncio.to_thread(_fired_restore, uri, fired)
        if root:
            await _profile_edit(uri, restore=root)
    except Exception:                                    # noqa: BLE001
        logger.exception("drop panel: could not put back %s's trigger rows after a "
                         "refused write", uri)


# ── results ───────────────────────────────────────────────────────────────

@dataclass
class PanelResult:
    """What one panel write did: the drop store's undo pair, the profile
    rows changed, and a sentence for the toast."""
    result: Any
    before: dict
    after: dict
    profile: list = field(default_factory=list)
    said: str = ""


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def said_profile(changes: list[dict]) -> str:
    deleted = sum(1 for c in changes if c.get("did") == "deleted")
    off = sum(1 for c in changes if c.get("did") == "switched_off")
    on = sum(1 for c in changes if c.get("did") == "switched_on")
    moved = sum(1 for c in changes if c.get("did") == "moved")
    parts = []
    if deleted:
        parts.append(f"deleted {_plural(deleted, 'trigger', 'triggers')} you placed by hand")
    if off:
        parts.append(f"switched off {_plural(off, 'imported trigger', 'imported triggers')}")
    if on:
        parts.append(f"switched {_plural(on, 'trigger', 'triggers')} back on")
    if moved:
        parts.append(f"moved {_plural(moved, 'trigger', 'triggers')}")
    lag = next((c["unsynced"] for c in changes if c.get("unsynced")), None)
    if lag:
        # never a silent half: his profile changed, the room's copy did not
        parts.append(f"your song profile changed, but the copy the room fires from "
                     f"has not caught up (sync: {lag}) — saving this song on the "
                     "Timeline brings it level")
    return ", ".join(parts)


def _join(*bits: str) -> str:
    return "; ".join(b for b in bits if b) or "nothing changed"


def is_his(key: str) -> bool:
    return isinstance(key, str) and key.startswith(HIS_PREFIX)


def _view(uri: str) -> dict:
    return ds.view(uri)


def _his_row(uri: str, key: str) -> dict:
    for row in _view(uri).get("yours") or []:
        if row.get("key") == key:
            return row
    raise ds.SequenceNotFound(f"no drop of yours at {key!r} on this song")


def _live_detections(view: dict, keys: list[str]) -> list[dict]:
    by_key = {s.get("key"): s for s in view.get("sequences") or []}
    return [by_key[k] for k in keys if k in by_key
            and by_key[k].get("state") != ds.STATE_DISMISSED]


# ── the writes ────────────────────────────────────────────────────────────

async def set_parts(uri: str, key: str, parts: dict) -> PanelResult:
    """A part's toggle. `parts`: {part: "on" | "off"}."""
    if not is_his(key):
        res = await asyncio.to_thread(ds.apply_edit, uri, "parts", key=key, parts=parts)
        words = ", ".join(f"{p.replace('_', '-')} {'approved' if v == ds.PART_ON else 'off'}"
                          for p, v in parts.items())
        return PanelResult(res.result, res.before, res.after, [], words)
    if len(parts) != 1:
        raise ds.InvalidEdit("switch one part of your own drop at a time")
    (part, value), = parts.items()
    if part == ds.PRE_DROP:
        if value not in (ds.PART_ON, ds.PART_OFF):
            raise ds.InvalidEdit("a part is switched on or off")
        return await _his_pre_drop(uri, key, {"part": value},
                                   f"your pre-drop {'approved' if value == ds.PART_ON else 'off'}")
    if part not in ds.HANDLES or value not in (ds.PART_ON, ds.PART_OFF):
        raise ds.InvalidEdit("a part is the charge, lull or drop, switched on or off")
    view = await asyncio.to_thread(_view, uri)
    row = next((r for r in view.get("yours") or [] if r.get("key") == key), None)
    if row is None:
        raise ds.SequenceNotFound(f"no drop of yours at {key!r} on this song")
    member = row.get(part)
    if member is None:
        raise ds.InvalidEdit(f"this drop of yours has no {part}")
    want_on = value == ds.PART_ON
    if bool(member.get("enabled")) == want_on:
        edits = await asyncio.to_thread(ds.edits, uri)
        bare = {"overrides": edits["overrides"], "added": edits["added"]}
        return PanelResult(key, bare, bare, [], f"your {part} is already {value}")
    drop_id = row["drop"]["id"]
    standing = _live_detections(view, row.get("detections") or [])
    steps: list[dict] = []
    if want_on:
        changes = await _his_write(uri, enable=[member["id"]])
        if part == "drop":
            steps.append({"op": "undismiss_for", "his_id": drop_id})
        else:
            steps += [{"op": "part", "key": d["key"], "part": part, "value": ds.PART_ON}
                      for d in standing if (d.get("parts") or {}).get(part) == ds.PART_OFF]
    else:
        changes = await _his_write(uri, remove=[member["id"]])
        if part == "drop":
            if standing:
                steps.append({"op": "dismiss_for", "keys": [d["key"] for d in standing],
                              "his_id": drop_id})
        else:
            steps += [{"op": "part", "key": d["key"], "part": part, "value": ds.PART_OFF}
                      for d in standing
                      if (d.get("parts") or {}).get(part) not in (ds.PART_OFF, ds.PART_ABSENT)]
    res = await _drop_steps(uri, steps, changes)
    said = _join(said_profile(changes),
                 _said_steps(res.result if isinstance(res.result, list) else [], steps))
    return PanelResult(key, res.before, res.after, changes, said)


async def approve(uri: str, key: str) -> PanelResult:
    """The double tick: approve every part that is not off. On one of his
    own drops that is only its pre-drop — the rest of it is his already."""
    if is_his(key):
        row = await asyncio.to_thread(_his_row, uri, key)
        ctx = await asyncio.to_thread(ds.his_pre_drop_ctx, uri, row["drop"]["id"],
                                      int(row["drop"]["timestamp_ms"]))
        pre = await asyncio.to_thread(ds.his_pre_drop_now, uri, ctx)
        if pre is not None and pre["part"] == ds.PART_WAITING:
            return await _his_pre_drop(uri, key, {"part": ds.PART_ON},
                                       "your pre-drop approved")
        edits = await asyncio.to_thread(ds.edits, uri)
        bare = {"overrides": edits["overrides"], "added": edits["added"]}
        return PanelResult(key, bare, bare, [], "your own drop is approved already")
    res = await asyncio.to_thread(ds.apply_edit, uri, "approve", key=key)
    return PanelResult(res.result, res.before, res.after, [], "approved")


async def remove(uri: str, key: str) -> PanelResult:
    """Remove a drop completely: a detection is dismissed, a drop he added is
    deleted, and one of his own follows answer 6 (module docstring) — the
    detections it stood in for dismissed with it."""
    if not is_his(key):
        res = await asyncio.to_thread(ds.apply_edit, uri, "remove", key=key)
        said = "removed your added drop" if key.startswith("added:") else "not a drop: removed"
        return PanelResult(res.result, res.before, res.after, [], said)
    view = await asyncio.to_thread(_view, uri)
    row = next((r for r in view.get("yours") or [] if r.get("key") == key), None)
    if row is None:
        raise ds.SequenceNotFound(f"no drop of yours at {key!r} on this song")
    ids = [row[h]["id"] for h in ds.HANDLES if row.get(h) and row[h].get("enabled")]
    changes = await _his_write(uri, remove=ids) if ids else []
    standing = _live_detections(view, row.get("detections") or [])
    steps = ([{"op": "dismiss_for", "keys": [d["key"] for d in standing],
               "his_id": row["drop"]["id"]}] if standing else [])
    res = await _drop_steps(uri, steps, changes)
    return PanelResult(key, res.before, res.after, changes,
                       _join(said_profile(changes),
                             _said_steps(res.result if isinstance(res.result, list) else [],
                                         steps)))


async def switch_on(uri: str, key: str) -> PanelResult:
    """His drop switched back on (the power button on a dimmed row of his):
    every switched-off member back on, and the detections dismissed for it
    put back."""
    if not is_his(key):
        raise ds.InvalidEdit("only a drop of yours is switched back on this way — "
                             "tap its drop to bring a detection back")
    view = await asyncio.to_thread(_view, uri)
    row = next((r for r in view.get("yours") or [] if r.get("key") == key), None)
    if row is None:
        raise ds.SequenceNotFound(f"no drop of yours at {key!r} on this song")
    ids = [row[h]["id"] for h in ds.HANDLES if row.get(h) and not row[h].get("enabled")]
    changes = await _his_write(uri, enable=ids) if ids else []
    res = await _drop_steps(uri, [{"op": "undismiss_for", "his_id": row["drop"]["id"]}],
                            changes)
    return PanelResult(key, res.before, res.after, changes,
                       _join(said_profile(changes),
                             _said_steps(res.result if isinstance(res.result, list) else [],
                                         [{"op": "undismiss_for"}])))


async def move_handles(uri: str, key: str, handles: dict) -> PanelResult:
    """A dragged handle (the panel's in-place editor). A detection or an
    added drop moves in the drop store exactly as on the Timeline; one of
    HIS OWN drops moves its trigger in his song profile (the root route's
    `move`; a card-born one in the fired copy), held in charge < lull < drop
    order RAMP_FLOOR_MS apart. `handles` are moments (when it fires); the
    stored time is the moment less the trigger's own `trigger_offset_ms`."""
    if not is_his(key):
        res = await asyncio.to_thread(ds.apply_edit, uri, "handles", key=key, handles=handles)
        return PanelResult(res.result, res.before, res.after, [], "moved")
    handles = dict(handles)
    pre_given = ds.PRE_DROP in handles
    pre_ms = handles.pop(ds.PRE_DROP, None)
    if pre_given and not handles:
        return await _his_pre_drop(uri, key, {"move": pre_ms}, "moved your pre-drop")
    row = await asyncio.to_thread(_his_row, uri, key)
    times = {h: (row.get(h) or {}).get("timestamp_ms") for h in ds.HANDLES}
    moves = []
    for h, ms in handles.items():
        if h not in ds.HANDLES or ms is None:
            raise ds.InvalidEdit("move a charge, lull or drop of yours to a time")
        if row.get(h) is None:
            raise ds.InvalidEdit(f"this drop of yours has no {h}")
        times[h] = int(ms)
        moves.append({"id": row[h]["id"],
                      "timestamp_ms": int(ms) - int(row[h].get("offset_ms") or 0)})
    ds._check_order(times)
    if not moves:
        raise ds.InvalidEdit("name at least one handle to move")
    if pre_given:
        # the pre-drop moves in the drop store, its drop in his song profile:
        # one write each, one undo step (the profile put back if the second fails)
        ctx = await asyncio.to_thread(ds.his_pre_drop_ctx, uri, row["drop"]["id"],
                                      int(times["drop"]))
        changes = await _his_write(uri, move=moves)
        res = await _drop_steps(uri, [{"op": "mine_pre_drop", "key": ctx["key"],
                                       "drop_ms": ctx["drop_ms"], "pre": ctx["pre"],
                                       "step": {"move": pre_ms}}], changes)
        return PanelResult(key, res.before, res.after, changes,
                           _join(said_profile(changes), "moved your pre-drop"))
    changes = await _his_write(uri, move=moves)
    edits = await asyncio.to_thread(ds.edits, uri)
    bare = {"overrides": edits["overrides"], "added": edits["added"]}
    return PanelResult(key, bare, bare, changes, _join(said_profile(changes)))


async def _his_pre_drop(uri: str, key: str, step: dict, said: str) -> PanelResult:
    """A pre-drop edit on one of HIS OWN drops: stored in the drop store
    (overrides["mine:<his drop trigger id>"], drop_sequences.py's PRE-DROPS),
    never in his song profile — the pre-drop is not one of his triggers."""
    row = await asyncio.to_thread(_his_row, uri, key)
    ctx = await asyncio.to_thread(ds.his_pre_drop_ctx, uri, row["drop"]["id"],
                                  int(row["drop"]["timestamp_ms"]))
    res = await asyncio.to_thread(ds.apply_edit, uri, "mine_pre_drop", key=ctx["key"],
                                  drop_ms=ctx["drop_ms"], pre=ctx["pre"], step=step)
    return PanelResult(key, res.before, res.after, [], said)


async def pre_drop_member(uri: str, key: str, off: bool) -> PanelResult:
    """The pre-drop switched off, or back on (any drop, his own included)."""
    said = f"pre-drop {'off' if off else 'on'}"
    if is_his(key):
        return await _his_pre_drop(uri, key, {"off": bool(off)}, f"your {said}")
    res = await asyncio.to_thread(ds.apply_edit, uri, "member", key=key,
                                  handle=ds.PRE_DROP, off=bool(off))
    return PanelResult(res.result, res.before, res.after, [], said)


async def pre_drop_fill(uri: str, key: str) -> PanelResult:
    """＋ Pre-drop: one where the detector's rules put it."""
    if is_his(key):
        return await _his_pre_drop(uri, key, {"fill": "rules"}, "added a pre-drop to your drop")
    res = await asyncio.to_thread(ds.apply_edit, uri, "fill", key=key, handle=ds.PRE_DROP)
    return PanelResult(res.result, res.before, res.after, [], "added a pre-drop")


async def pre_drop_kind(uri: str, key: str, kind: str) -> PanelResult:
    """Switch a pre-drop's kind (a spike or a vocal intro)."""
    said = f"pre-drop: {'a spike' if kind == 'spike' else 'a vocal intro'}"
    if is_his(key):
        return await _his_pre_drop(uri, key, {"kind": kind}, f"your {said}")
    res = await asyncio.to_thread(ds.apply_edit, uri, "pre_drop_kind", key=key, kind=kind)
    return PanelResult(res.result, res.before, res.after, [], said)


def _said_steps(done: list, steps: list[dict]) -> str:
    kinds = {s.get("op") for s in steps}
    if not done:
        return ""
    if "dismiss_for" in kinds:
        return f"dismissed {_plural(len(done), 'detection', 'detections')} standing in for it"
    if "undismiss_for" in kinds:
        return f"put back {_plural(len(done), 'detection', 'detections')}"
    return ""


async def _drop_steps(uri: str, steps: list[dict], changes: list[dict]) -> ds.EditResult:
    """The drop store's half of one of his rows' writes, in one locked write
    (one before/after pair). When it fails after the profile half landed,
    the profile rows are put back first, so the refusal leaves both stores
    as they were."""
    try:
        return await asyncio.to_thread(ds.apply_edit, uri, "multi", ops=steps)
    except Exception:
        await _put_back(uri, changes)
        raise


def _record(c: dict, frm, to) -> dict:
    rec = {"id": c["id"], "from": frm, "to": to, "index": c.get("index")}
    if c.get("store") == FIRED:
        rec["store"] = FIRED
    return rec


def _reverse(changes: list[dict]) -> list[dict]:
    """Restore records that undo `changes`: each row from what the edit left
    back to what it was (a card-born row keeps its `store`)."""
    return [_record(c, c.get("after"), c.get("before")) for c in reversed(changes)]


def _forward(changes: list[dict]) -> list[dict]:
    """Restore records that redo `changes`."""
    return [_record(c, c.get("before"), c.get("after")) for c in changes]


async def restore(uri: str, edits: dict, expect: Optional[str],
                  profile: Optional[list[dict]] = None) -> PanelResult:
    """Undo or redo one panel write across both stores (module docstring's
    ONE UNDO STEP). `profile` is restore records ({id, from, to, index}) —
    the caller orients them (`_reverse` to undo, `_forward` to redo)."""
    if expect is not None:
        current = await asyncio.to_thread(ds.edits, uri)
        if current["rev"] != expect:
            raise ds.EditConflict("your drop-sequence edits on this song changed since — "
                                  "nothing was undone; reload and try again")
    changes: list[dict] = []
    if profile:
        changes = await _his_restore(uri, list(profile))
    try:
        res = await asyncio.to_thread(ds.apply_edit, uri, "restore", edits=edits,
                                      expect=expect)
    except Exception:
        await _put_back(uri, changes)
        raise
    return PanelResult(res.result, res.before, res.after, changes,
                       _join(said_profile(changes)) if changes else "undone")
