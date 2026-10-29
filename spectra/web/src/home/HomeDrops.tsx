/** THE DROPS PANEL ON HOME (predrop plan step 1 — /home/javi/fleet-spotfx/
 * data/predrop-plan/report.md section 3.6). A third card beside Quick
 * sequences and Quick actions, the same shape, listing the drops of the
 * song Home is showing (his answer 5). ./dropsPanel.ts decides every row,
 * part look and word; this file draws them and sends the taps.
 *
 * ONE HORIZONTAL BAR OF TOGGLE BUTTONS PER DROP (his words: "All on the
 * horizontal bar, just toggle buttons, essentially"): the double tick
 * (approve every part not off), one button per part — charge, lull,
 * pre-drop, drop — a tap going waiting → on → off → on, Remove, and the
 * pencil (the editor in place; on a drop of his he switched off, the power
 * button that switches it back on).
 *
 * TESTING is the icon-only toggle in the card's head (`drop_testing`):
 * while it glows every detected drop plays, approved or not. Removed and
 * switched-off never play, even then — the server's rule.
 *
 * JUST PLAYED, NEXT, JUMP (2026-10-28, his Q1-Q5, every mode): the rows
 * stay in time order. The drop that just played (the `drop_played` push, or
 * the engine status poll's `triggers.last_drop` as its backstop) is
 * highlighted in amber IN PLACE until the next one plays; the drop that
 * plays next (dropsPanel.nextDropKey, the server's own "plays") wears a
 * purple outline and a countdown in the top bar's style — tenths of a
 * second, a fill and glow over the last 3 s, a flash as it fires — to the
 * moment it FIRES (`fireMs`, mark + drop timing). Its own rAF loop writes
 * the countdown straight to the DOM (no React render a frame, SongNextBox's
 * rule). The list scrolls inside the card, never the page, to keep both in
 * view. A row's time is its JUMP button: it moves the audio shape to show
 * the whole drop and turns Follow off.
 *
 * DOUBLE-TAP (his Q9): a second tap on the same part within
 * dropsPanel.DOUBLE_TAP_MS switches it off, whatever it was. The first tap
 * has already acted (taps feel instant); the second waits behind it in the
 * editor's queue and folds into its undo step (`parts(..., {merge: true})`)
 * — the pair is one undo.
 *
 * THE PRE-DROP's button wears its kind's glyph (`preDrop` for a spike,
 * `preDropVoice` for a vocal intro); on one of his own drops its tap goes
 * through the same `parts` call, since its state lives in the drop store,
 * never his song profile. One that plays fades the drop's colour change
 * across it (dropsPanel.PRE_DROP_IN_THE_ROOM).
 *
 * TIE-INS (components/songTimelineView.tsx): a tap on a drop pill on the
 * song timeline, or on a sequence on Home's audio shape, selects the drop
 * here and scrolls it into view; selecting one zooms the shared window,
 * and so Home's audio shape, to it. */
import { useEffect, useMemo, useRef, useState } from 'react';
import { countdownParts, FINAL_STRETCH_MS } from '../components/songStrip';
import { getShowClockMs } from '../lib/showClock';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { apiGet, apiPut } from '../api/client';
import { onSpectraMessage } from '../api/spectraWs';
import Icon from '../components/Icon';
import type { IconName } from '../components/iconRegistry';
import InfoTip from '../components/InfoTip';
import { useSongTimelineView } from '../components/songTimelineView';
import { useEngineStatus, useRoomControls } from '../queries';
import { useDropSequences } from '../timeline/queries';
import { useDropEditor } from '../timeline/hooks/useDropEditor';
import { PARTS, zoomWindow, type PartKey } from '../timeline/dropSequences';
import { editErrorText } from '../timeline/dropEdit';
import type { LastDrop, RoomControlState } from '../types';
import HomeDropEditor from './HomeDropEditor';
import {
  buildPanelRows, DOUBLE_TAP_MS, fmtDropTime, nextDropKey, nextPartState, PART_COLOR, PART_LABEL,
  partTitle, removeTitle, rowNear, toReview, type PanelRow, type ProvenanceResponse,
} from './dropsPanel';

const PART_ICON: Record<PartKey, IconName> = {
  charge: 'phaseCharge', lull: 'phaseLull', pre_drop: 'preDrop', drop: 'phaseDrop',
};

/** A part's glyph: the pre-drop's follows its kind. */
function partIcon(r: PanelRow, part: PartKey): IconName {
  if (part === 'pre_drop' && r.preDropKind === 'intro') return 'preDropVoice';
  return PART_ICON[part];
}

/** The newer of two last-drop records (the push and the poll's backstop). */
function newer(a: LastDrop | null | undefined, b: LastDrop | null | undefined): LastDrop | null {
  if (!a) return b ?? null;
  if (!b) return a;
  return a.at_ms >= b.at_ms ? a : b;
}

export default function HomeDrops() {
  const qc = useQueryClient();
  const { track, win, pushHistory, durationMs, selectedDrop, showingLast } = useSongTimelineView();
  const uri = track?.uri ?? null;
  const { data: resp } = useDropSequences(uri);
  const { data: controls } = useRoomControls();
  const testing = !!controls?.drop_testing;
  const { data: status } = useEngineStatus();
  const [pushed, setPushed] = useState<LastDrop | null>(null);
  useEffect(() => onSpectraMessage((msg) => {
    if (msg.type !== 'drop_played') return;
    const { type: _type, ...rec } = msg as Record<string, unknown>;
    setPushed(rec as unknown as LastDrop);
  }), []);
  const lastDrop = newer(pushed, status?.triggers?.last_drop ?? null);

  const editor = useDropEditor(uri);
  // who placed each of his triggers (the root process's rule) — refetched
  // whenever his drops change
  const yoursSig = JSON.stringify((resp?.yours ?? []).map((r) => [
    r.key, r.charge?.enabled, r.lull?.enabled, r.drop.enabled]));
  const { data: provenance } = useQuery({
    queryKey: ['drop-provenance', uri, yoursSig],
    queryFn: () => apiGet<ProvenanceResponse>(`/drop-sequences/provenance?uri=${encodeURIComponent(uri!)}`),
    enabled: !!uri && (resp?.yours?.length ?? 0) > 0,
    staleTime: 60_000,
    retry: false,
  });

  const rows = useMemo(() => buildPanelRows(resp, { testing, lastDrop, provenance }),
    [resp, testing, lastDrop, provenance]);
  const review = toReview(rows);
  const provById = useMemo(() => new Map((provenance?.triggers ?? []).map((t) => [t.id, t])),
    [provenance]);

  const [selected, setSelected] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [busyTesting, setBusyTesting] = useState(false);
  const [testingError, setTestingError] = useState<string | null>(null);
  const rowRefs = useRef(new Map<string, HTMLLIElement>());
  const listRef = useRef<HTMLUListElement>(null);
  useEffect(() => { setSelected(null); setEditing(null); }, [uri]);

  // THE NEXT DROP AND ITS COUNTDOWN (module docstring): which row is next is
  // React state (it changes a few times a song); the countdown itself is
  // written to the DOM by this loop, a frame at a time.
  const [nextKey, setNextKey] = useState<string | null>(null);
  const rowsRef = useRef(rows);
  rowsRef.current = rows;
  // the show clock is the PLAYING song's: no countdown on the last-played one
  const liveRef = useRef(!showingLast);
  liveRef.current = !showingLast;
  const nextKeyRef = useRef<string | null>(null);
  const countRef = useRef<HTMLSpanElement>(null);
  const countValRef = useRef<HTMLSpanElement>(null);
  const countUnitRef = useRef<HTMLElement>(null);
  const countFillRef = useRef<HTMLSpanElement>(null);
  const flashNext = useRef(false);
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const now = liveRef.current ? getShowClockMs() : null;
      const list = rowsRef.current;
      const key = nextDropKey(list, now);
      if (key !== nextKeyRef.current) {
        const was = list.find((r) => r.key === nextKeyRef.current);
        // the one that was next has just fired: the new countdown flashes
        flashNext.current = !!was && now != null && was.fireMs <= now;
        nextKeyRef.current = key;
        setNextKey(key);
      }
      const row = key ? list.find((r) => r.key === key) : null;
      // the chip on screen may still be the last next row's for a frame,
      // until React re-renders: write only to the chip of THIS row
      if (row && now != null && countRef.current && countRef.current.dataset.key === row.key) {
        const remaining = row.fireMs - now;
        const parts = countdownParts(remaining);
        if (countValRef.current) countValRef.current.textContent = parts.value;
        if (countUnitRef.current) countUnitRef.current.textContent = parts.unit ?? '';
        const soon = remaining <= FINAL_STRETCH_MS;
        countRef.current.classList.toggle('soon', soon);
        if (countFillRef.current) {
          countFillRef.current.style.transform =
            `scaleX(${soon ? Math.min(1, 1 - remaining / FINAL_STRETCH_MS) : 0})`;
        }
        if (flashNext.current) {
          flashNext.current = false;
          const el = countRef.current;
          el.classList.remove('flash');
          void el.offsetWidth;
          el.classList.add('flash');
          setTimeout(() => el.classList.remove('flash'), 600);
        }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  // keep the drop that just played and the next one in view — scrolling the
  // card's own list, never the page
  const justKey = rows.find((r) => r.justPlayed)?.key ?? null;
  useEffect(() => {
    const list = listRef.current;
    if (!list || list.scrollHeight <= list.clientHeight) return;
    const els = [justKey, nextKey].map((k) => (k ? rowRefs.current.get(k) : null))
      .filter((el): el is HTMLLIElement => !!el);
    if (!els.length) return;
    // each row's place in the list's own content, wherever the list scrolls
    const base = list.getBoundingClientRect().top - list.scrollTop;
    const topOf = (el: HTMLElement) => el.getBoundingClientRect().top - base;
    const top = Math.min(...els.map(topOf));
    const bottom = Math.max(...els.map((el) => topOf(el) + el.getBoundingClientRect().height));
    if (top >= list.scrollTop && bottom <= list.scrollTop + list.clientHeight) return;
    // both if they fit, else the next one (the one still to come)
    const nextEl = nextKey ? rowRefs.current.get(nextKey) : null;
    const want = bottom - top <= list.clientHeight || !nextEl ? top : topOf(nextEl);
    list.scrollTop = Math.max(0, want - 4);
  }, [justKey, nextKey]);

  /** Select a row: highlight it, and zoom the shared window (and so Home's
   * audio shape) to it — one view-history step. */
  const select = (r: PanelRow) => {
    setSelected(r.key);
    if (durationMs > 0) {
      pushHistory();
      win.setFollow(false);
      win.setManualWin(zoomWindow({ charge: r.chargeMs, lull: r.lullMs, drop: r.dropMs },
        resp?.song?.beat_ms, durationMs));
    }
  };
  const selectRef = useRef(select);
  selectRef.current = select;

  // a tap on a drop pill on the song timeline / a sequence on the shape:
  // the same selection (and zoom) as a tap on the row's own time
  const seenAsk = useRef(0);
  useEffect(() => {
    if (!selectedDrop || selectedDrop.seq === seenAsk.current) return;
    if (selectedDrop.uri && uri && selectedDrop.uri !== uri) return;
    const hit = rowNear(rows, selectedDrop.ms);
    if (!hit) return;
    seenAsk.current = selectedDrop.seq;
    selectRef.current(hit);
    const el = rowRefs.current.get(hit.key);
    if (el && typeof el.scrollIntoView === 'function') {
      el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  }, [selectedDrop, rows, uri]);

  const toggleTesting = async () => {
    setBusyTesting(true);
    try {
      await apiPut('/room-controls', { drop_testing: !testing });
      setTestingError(null);
      qc.setQueryData<RoomControlState>(['spectra-room-controls'], (prev) => (
        prev ? { ...prev, drop_testing: !testing } : prev));
      void qc.invalidateQueries({ queryKey: ['spectra-room-controls'] });
      // what fires changed: every song's view says so
      void qc.invalidateQueries({ queryKey: ['drop-sequences'] });
    } catch (err) {
      // never a silent nothing: the glow stays where the room is
      setTestingError(`Drop testing is still ${testing ? 'on' : 'off'}: ${editErrorText(err)}`);
    } finally {
      setBusyTesting(false);
    }
  };

  // ONE REQUEST AT A TIME, without dimming every toggle on each tap: a tap
  // that lands while one is in flight is ignored (the editor's own queue
  // would run it, but against the row as it was before the first landed)
  const idle = () => !editor.busy;
  const lastTap = useRef<{ key: string; part: PartKey; at: number; next: 'on' | 'off' } | null>(null);
  const tapPart = (r: PanelRow, part: PartKey) => {
    const now = typeof performance !== 'undefined' ? performance.now() : Date.now();
    const prev = lastTap.current;
    const word = `${PART_LABEL[part].toLowerCase()}`;
    if (prev && prev.key === r.key && prev.part === part && now - prev.at < DOUBLE_TAP_MS) {
      // DOUBLE-TAP: off, whatever it was — behind the first tap, one undo step
      lastTap.current = null;
      if (prev.next === 'off') return;           // the first tap already switched it off
      void editor.parts(r.key, { [part]: 'off' },
        `${word} off at ${fmtDropTime(r.dropMs)} (double-tap)`, { merge: true });
      return;
    }
    const next = nextPartState(r.looks[part]);
    if (!next || !idle()) { lastTap.current = null; return; }
    lastTap.current = { key: r.key, part, at: now, next };
    void editor.parts(r.key, { [part]: next },
      `${word} ${next === 'on' ? 'approved' : 'off'} at ${fmtDropTime(r.dropMs)}`);
  };

  const note = testingError ?? editor.error ?? editor.note;

  return (
    <div className={`card home-quick-card home-drops-card${testing ? ' testing' : ''}`}
      aria-label="Drops">
      <div className="home-drops-head">
        <InfoTip topic="drops-panel" className="home-drops-title-tip"
          text="The drops of the song Home is showing. The amber row just played; the purple one plays next, with a countdown to the moment it fires. A row's time jumps the audio shape to it. Each row's bar: the double tick approves the whole drop; one button per part (charge, lull, pre-drop, drop) switches it on or off — any edit approves the drop, and a double-tap switches a part off. A filled part with a dot is high confidence (the detector approved it); a dashed one is a suggestion waiting for you. The cross removes the drop; the pencil edits it here. A green dot means it plays on this song now.">
          <div className="home-quick-title">
            <Icon name="phaseDrop" size={14} />
            <span>Drops{review > 0 ? ` · ${review} to review` : ''}</span>
          </div>
        </InfoTip>
        <div className="home-drops-head-tools">
          <button type="button" className="home-quick-icon-btn home-drops-undo"
            disabled={!editor.canUndo || editor.busy}
            title={editor.undoLabel ? `Undo: ${editor.undoLabel}` : 'Nothing to undo'}
            aria-label={editor.undoLabel ? `Undo: ${editor.undoLabel}` : 'Nothing to undo'}
            onClick={() => void editor.undo()}>
            <Icon name="undo" size={15} />
          </button>
          <InfoTip topic="drop-testing"
            text={testing
              ? 'Drop testing is ON: every detected drop plays, suggestions included, so you can watch them in the room; the one that just played lights up in place for a quick approval. Removed and switched-off drops never play. Tap to switch it off.'
              : 'Drop testing: tap to make every detected drop play, suggestions included, so you can watch them in the room and approve the good ones. Removed and switched-off drops never play.'}>
            <button type="button" className={`home-quick-icon-btn home-drops-testing${testing ? ' on' : ''}`}
              role="switch" aria-checked={testing} disabled={busyTesting}
              aria-label={testing ? 'Drop testing is on — every detected drop plays' : 'Drop testing is off'}
              onClick={() => void toggleTesting()}>
              <Icon name="testDrops" size={16} />
            </button>
          </InfoTip>
        </div>
      </div>
      {note && <div className={`home-drops-note${testingError || editor.error ? ' error' : ''}`} role="status">{note}</div>}
      {!uri && <p className="muted">No song yet.</p>}
      {uri && resp && rows.length === 0 && (
        <p className="muted">
          {resp.status === 'ok' ? 'No drops on this song.'
            : resp.reason ?? 'This song has not been analysed for drops yet.'}
        </p>
      )}
      <ul className="home-quick-list home-drops-list" ref={listRef}>
        {rows.map((r) => {
          const his = r.kind === 'yours';
          const off = r.switchedOff;
          return (
            <li key={r.key} ref={(el) => { if (el) rowRefs.current.set(r.key, el); else rowRefs.current.delete(r.key); }}
              className={`home-drops-row${selected === r.key ? ' sel' : ''}${off ? ' dim' : ''}${r.justPlayed ? ' justplayed' : ''}${nextKey === r.key ? ' next' : ''}`}
              data-key={r.key}>
              <div className="home-drops-r1">
                <button type="button" className="home-drops-time" onClick={() => select(r)}
                  title="Jump: show this whole drop on the audio shape (Follow goes off; tap Follow to come back to now)"
                  aria-label={`Jump the audio shape to the drop at ${fmtDropTime(r.dropMs)}`}>
                  <span className="home-drops-time-text">{fmtDropTime(r.dropMs)}</span>
                  <Icon name="jump" size={12} />
                </button>
                <span className={`home-drops-state${off ? ' off' : ''}`}>{r.stateLine}</span>
                {r.justPlayed && <span className="home-drops-jp">just played</span>}
                {nextKey === r.key && (
                  <span ref={countRef} className="home-drops-count tabular-nums" data-key={r.key}
                    title="Plays next: the countdown runs to the moment it fires (its mark plus your drop timing)"
                    aria-label="plays next">
                    <span ref={countFillRef} className="home-drops-count-fill" />
                    <span className="home-drops-count-txt">
                      <span ref={countValRef}>—</span><small ref={countUnitRef} />
                    </span>
                  </span>
                )}
                <span className={`home-drops-dot ${r.plays ? 'yes' : 'no'}`}
                  title={r.plays ? 'Plays on this song now' : 'Does not play on this song now'}
                  aria-label={r.plays ? 'plays' : 'does not play'} role="img" />
              </div>
              <div className="home-drops-bar" role="group" aria-label={`Drop at ${fmtDropTime(r.dropMs)}`}>
                <button type="button" className={`home-drops-btn approve ${r.approveLook}`}
                  disabled={!r.canApprove}
                  title={r.canApprove
                    ? (his ? 'Approve its pre-drop (your own triggers need no approval)'
                      : 'Approve the whole drop: charge, lull, pre-drop and drop')
                    : his ? 'Your own drop needs no approval' : 'Nothing here is waiting for approval'}
                  aria-label={his && r.canApprove ? 'Approve its pre-drop' : 'Approve the whole drop'}
                  onClick={() => { if (idle()) void editor.approve(r.key, `the drop at ${fmtDropTime(r.dropMs)}`); }}>
                  <Icon name="checkAll" size={17} />
                </button>
                {PARTS.map((part) => {
                  const look = r.looks[part];
                  const member = his && part !== 'pre_drop' ? r.yours?.[part] : null;
                  const title = partTitle(r, part, look, member ? provById.get(member.id) : null);
                  return (
                    <button key={part} type="button"
                      className={`home-drops-btn part ${part} ${look}`}
                      data-kind={part === 'pre_drop' ? (r.preDropKind ?? undefined) : undefined}
                      style={{ ['--part' as string]: PART_COLOR[part] }}
                      disabled={look === 'absent'}
                      aria-pressed={look === 'on' || look === 'confident'}
                      title={title} aria-label={title}
                      onClick={() => tapPart(r, part)}>
                      <Icon name={partIcon(r, part)} size={16} />
                    </button>
                  );
                })}
                <button type="button" className="home-drops-btn remove"
                  title={removeTitle(r, provenance)} aria-label={removeTitle(r, provenance)}
                  onClick={() => {
                    if (!idle()) return;
                    setEditing(null);
                    void editor.remove(r.key, `the drop at ${fmtDropTime(r.dropMs)}`);
                  }}>
                  <Icon name="xMark" size={16} />
                </button>
                {his && off ? (
                  <button type="button" className="home-drops-btn power"
                    title="Switch your drop back on" aria-label="Switch your drop back on"
                    onClick={() => { if (idle()) void editor.switchOn(r.key, `your drop at ${fmtDropTime(r.dropMs)}`); }}>
                    <Icon name="power" size={16} />
                  </button>
                ) : (
                  <button type="button" className={`home-drops-btn edit${editing === r.key ? ' on' : ''}`}
                    aria-expanded={editing === r.key}
                    title="Edit this drop here: drag its charge, lull, pre-drop and drop"
                    aria-label="Edit this drop"
                    onClick={() => { select(r); setEditing(editing === r.key ? null : r.key); }}>
                    <Icon name="edit" size={16} />
                  </button>
                )}
              </div>
              {editing === r.key && uri && (
                <HomeDropEditor row={r} uri={uri} beatMs={resp?.song?.beat_ms ?? 500}
                  editor={editor} onClose={() => setEditing(null)} />
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
