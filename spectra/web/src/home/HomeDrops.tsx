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
 * while it glows every detected drop plays, approved or not, and the drop
 * that just played (the `drop_played` push, or the engine status poll's
 * `triggers.last_drop` as its backstop) moves to the top, highlighted.
 * Removed and switched-off never play, even then — the server's rule.
 *
 * TIE-INS (components/songTimelineView.tsx): a tap on a drop pill on the
 * song timeline, or on a sequence on Home's audio shape, selects the drop
 * here and scrolls it into view; selecting one zooms the shared window,
 * and so Home's audio shape, to it. */
import { useEffect, useMemo, useRef, useState } from 'react';
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
  buildPanelRows, fmtDropTime, nextPartState, PART_COLOR, PART_LABEL, partTitle, removeTitle,
  rowNear, toReview, type PanelRow, type ProvenanceResponse,
} from './dropsPanel';

const PART_ICON: Record<PartKey, IconName> = {
  charge: 'phaseCharge', lull: 'phaseLull', pre_drop: 'preDrop', drop: 'phaseDrop',
};

/** The newer of two last-drop records (the push and the poll's backstop). */
function newer(a: LastDrop | null | undefined, b: LastDrop | null | undefined): LastDrop | null {
  if (!a) return b ?? null;
  if (!b) return a;
  return a.at_ms >= b.at_ms ? a : b;
}

export default function HomeDrops() {
  const qc = useQueryClient();
  const { track, win, pushHistory, durationMs, selectedDrop } = useSongTimelineView();
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
  useEffect(() => { setSelected(null); setEditing(null); }, [uri]);

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
  const tapPart = (r: PanelRow, part: PartKey) => {
    const next = nextPartState(r.parts[part]);
    if (!next || !idle()) return;
    void editor.parts(r.key, { [part]: next },
      `${PART_LABEL[part].toLowerCase()} ${next === 'on' ? 'approved' : 'off'} at ${fmtDropTime(r.dropMs)}`);
  };

  const note = testingError ?? editor.error ?? editor.note;

  return (
    <div className={`card home-quick-card home-drops-card${testing ? ' testing' : ''}`}
      aria-label="Drops">
      <div className="home-drops-head">
        <InfoTip topic="drops-panel" className="home-drops-title-tip"
          text="The drops of the song Home is showing. Each row's bar: the double tick approves the whole drop; one button per part (charge, lull, pre-drop, drop) approves it, switches it off, or back on; the cross removes the drop; the pencil edits it here. A green dot means it plays on this song now.">
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
              ? 'Drop testing is ON: every detected drop plays, approved or not, and the one that just played moves to the top for a quick approval. Removed and switched-off drops never play. Tap to switch it off.'
              : 'Drop testing: tap to make every detected drop play, approved or not, so you can watch them in the room and approve the good ones. Removed and switched-off drops never play.'}>
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
      <ul className="home-quick-list home-drops-list">
        {rows.map((r) => {
          const his = r.kind === 'yours';
          const off = r.switchedOff;
          return (
            <li key={r.key} ref={(el) => { if (el) rowRefs.current.set(r.key, el); else rowRefs.current.delete(r.key); }}
              className={`home-drops-row${selected === r.key ? ' sel' : ''}${off ? ' dim' : ''}${r.justPlayed ? ' justplayed' : ''}`}
              data-key={r.key}>
              <div className="home-drops-r1">
                <button type="button" className="home-drops-time" onClick={() => select(r)}
                  title="Show this drop on the timeline and the audio shape">
                  {fmtDropTime(r.dropMs)}
                </button>
                <span className={`home-drops-state${off ? ' off' : ''}`}>{r.stateLine}</span>
                {r.justPlayed && <span className="home-drops-jp">just played</span>}
                <span className={`home-drops-dot ${r.plays ? 'yes' : 'no'}`}
                  title={r.plays ? 'Plays on this song now' : 'Does not play on this song now'}
                  aria-label={r.plays ? 'plays' : 'does not play'} role="img" />
              </div>
              <div className="home-drops-bar" role="group" aria-label={`Drop at ${fmtDropTime(r.dropMs)}`}>
                <button type="button" className="home-drops-btn approve"
                  disabled={!r.canApprove}
                  title={r.canApprove ? 'Approve the whole drop: charge, lull, pre-drop and drop'
                    : his ? 'Your own drop needs no approval' : 'Nothing here is waiting for approval'}
                  aria-label="Approve the whole drop"
                  onClick={() => { if (idle()) void editor.approve(r.key, `the drop at ${fmtDropTime(r.dropMs)}`); }}>
                  <Icon name="checkAll" size={17} />
                </button>
                {PARTS.map((part) => {
                  const state = r.parts[part];
                  const member = his && part !== 'pre_drop' ? r.yours?.[part] : null;
                  const title = partTitle(r, part, state, member ? provById.get(member.id) : null);
                  return (
                    <button key={part} type="button"
                      className={`home-drops-btn part ${part} ${state}`}
                      style={{ ['--part' as string]: PART_COLOR[part] }}
                      disabled={state === 'absent'}
                      aria-pressed={state === 'on'}
                      title={title} aria-label={title}
                      onClick={() => tapPart(r, part)}>
                      <Icon name={PART_ICON[part]} size={16} />
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
                    title="Edit this drop here: drag its charge, lull and drop"
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
