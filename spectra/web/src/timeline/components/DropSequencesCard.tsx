/** THE DROP-SEQUENCE REVIEW LIST and DETAIL BOX (drop-detection plan,
 * phase 3; plan.html's "Review list" and "the detail box"). Every sequence
 * on the song in time order — its time, its break length in beats, and what
 * of his is already there ("matches your drop", "you have a flare here") —
 * with a jump that zooms the big graph to it. Selecting one (here, on the
 * graph or on the strip) opens its detail box: the three times, why it was
 * found, its score, what the room does with it, and whether it fires.
 *
 * EDITING (phase 4): confirm, "not a drop", back to detected, lull/charge
 * off and on, a lull or charge added by the placement rules, the
 * previous/next snap steps for each handle, and the "the analysis moved
 * it" question — all through ../hooks/useDropEditor.ts, each one an undo
 * step. "Make it my triggers" stays for later (shown disabled, saying so).
 * Nothing detected fires yet (phase 5). ../dropSequences.ts holds every
 * word and number shown here. */
import HelpLink from '../../help/HelpLink';
import { fmtAgo } from '../../lib/time';
import {
  PHASE_COLOR, fireLine, fmtHundredths, fmtTenths, handleRows, reviewStatus, roomLines,
  sequenceFires, whyFound, type DisplaySeq, type DropSequencesResponse, type Handle,
} from '../dropSequences';
import { editable } from '../dropEdit';
import type { DropEditor } from '../hooks/useDropEditor';
import { DROP_FOCUS_ATTR } from '../hooks/useDropSeqInteractions';

const fmtScore = (v: number | null | undefined) => (v == null ? '—' : v.toFixed(1));

const LATER = 'Comes later: turning a sequence into three of your own triggers, through the same review you use for test-bed suggestions';

const HANDLE_LABEL: Record<Handle, string> = { charge: 'Charge', lull: 'Lull', drop: 'Drop' };
const STEP_LABEL: Record<Handle, [string, string]> = {
  charge: ['◀ beat', 'beat ▶'], lull: ['◀ spike', 'spike ▶'], drop: ['◀ spike', 'spike ▶'],
};

export function SeqBadge({ s }: { s: DisplaySeq }) {
  return <span className={`drop-badge ${s.fire}`} aria-hidden>{s.badge}</span>;
}

function PhaseSwatch({ h }: { h: Handle }) {
  return <span className={`drop-swatch ${h}`} style={{ color: PHASE_COLOR[h] }} aria-hidden />;
}

function breakText(s: DisplaySeq): string | null {
  const b = s.view?.break_beats;
  return b != null ? `break ${b.toFixed(1)} beats` : null;
}

function title(s: DisplaySeq): string {
  if (s.look === 'mine') return `Sequence ${s.number} · your triggers`;
  if (s.number != null) return `Sequence ${s.number} · ${s.look === 'confident' ? 'detected' : s.look}`;
  if (s.fire === 'muted') return 'Detected · not played on this song';
  if (s.look === 'dismissed') return 'Dismissed';
  if (s.fire === 'stands_down') return 'Stands down · yours fires';
  return 'Suggestion';
}

function Detail({ s, confidentScore, onJump, onClose, editor, selHandle, onSelectHandle, onStep }: {
  s: DisplaySeq;
  confidentScore: number | null;
  onJump: () => void;
  onClose: () => void;
  editor: DropEditor;
  selHandle: Handle;
  onSelectHandle: (h: Handle) => void;
  onStep: (h: Handle, dir: 1 | -1) => void;
}) {
  const why = whyFound(s.view, confidentScore);
  const rows = handleRows(s);
  const detNotes = s.look === 'mine' ? [] : s.view?.notes ?? [];
  const can = editable(s);
  const busy = editor.busy;
  const what = fmtTenths(s.drop);
  const isAdded = s.look === 'added';
  const confirmable = s.look === 'confident' || s.look === 'suggested';
  const revertible = s.view?.origin === 'detected'
    && (s.look === 'confirmed' || s.look === 'edited' || s.look === 'dismissed');
  const member = (h: 'lull' | 'charge') => {
    const off = h === 'lull' ? s.off.lull : s.off.charge;
    const name = h === 'lull' ? 'Lull' : 'Charge';
    if (off) {
      return (
        <button type="button" disabled={!can || busy} title={`Switch the ${h} back on`}
          onClick={() => void editor.member(s.key, h, false)}>{name} on</button>
      );
    }
    if (s[h] == null) {
      return (
        <button type="button" disabled={!can || busy}
          title={`Add a ${h}: placed by the same rules the detector uses, then yours to move`}
          onClick={() => void editor.fill(s.key, h)}>＋ {name}</button>
      );
    }
    return (
      <button type="button" disabled={!can || busy}
        title={`Switch the ${h} off: the rest of the sequence stays (it can be switched back on)`}
        onClick={() => void editor.member(s.key, h, true)}>{name} off</button>
    );
  };
  const review = s.view?.needs_review && can;
  const lost = s.view?.detection_lost;
  return (
    <div className="drop-detail" aria-label="Drop sequence details">
      <div className="drop-detail-head">
        <SeqBadge s={s} />
        <b>{title(s)}</b>
        <HelpLink topic="drop-sequence-states" title="What each look means" />
        <span className="drop-detail-sp" />
        <button type="button" onClick={onJump} title="Zoom the big graph to this sequence">↗ Jump to it</button>
        <button type="button" onClick={onClose} aria-label="Close the details">✕</button>
      </div>
      {rows.map((r) => (
        <div key={r.handle} className="drop-detail-row">
          <span className="drop-detail-name"><PhaseSwatch h={r.handle} />{HANDLE_LABEL[r.handle]}</span>
          <span className={`drop-detail-time${r.ms == null ? ' empty' : ''}`}
            style={can && selHandle === r.handle && r.ms != null ? { borderColor: 'var(--accent)' } : undefined}
            onClick={() => { if (can && r.ms != null) onSelectHandle(r.handle); }}
            title={can && r.ms != null ? `Select the ${r.handle} (← → on the keyboard then step it)` : undefined}>
            {r.ms != null ? fmtHundredths(r.ms) : '—'}
          </span>
          <span className="drop-detail-steps">
            {STEP_LABEL[r.handle].map((label, i) => (
              <button key={label} type="button" disabled={!can || r.ms == null || busy}
                title={can ? `Step the ${r.handle} to the ${i === 0 ? 'previous' : 'next'} ${label.replace(/[◀▶ ]/g, '')}`
                  : 'Your own triggers are moved on the SPECTRA triggers strip'}
                onClick={() => onStep(r.handle, i === 0 ? -1 : 1)}>{label}</button>
            ))}
          </span>
          {r.note && <span className="drop-detail-note">{r.note}</span>}
        </div>
      ))}
      <div className="drop-detail-row">
        <span className="drop-detail-name">Strength</span>
        <span className="drop-detail-time wide">
          {s.look === 'mine'
            ? '⚡ your triggers\' own intensities'
            : s.view?.step != null
              ? `⚡ set from the size of the step up (${s.view.step.toFixed(2)})`
              : '⚡ set from the size of the step up'}
        </span>
      </div>
      {why && (
        <p className="drop-detail-p">
          <b>{s.look === 'mine' ? 'The analysis found it too:' : 'Why it was found:'}</b> {why}
        </p>
      )}
      {s.look === 'mine' && !s.view && (
        <p className="drop-detail-p">The analysis did not find this drop — it is yours alone, and it fires as it always has.</p>
      )}
      <p className="drop-detail-p"><b>Fires?</b> {fireLine(s)}</p>
      <div className="drop-detail-p">
        <b>What the room does</b>
        {roomLines(s).map((l) => <div key={l}>{l}</div>)}
      </div>
      {(detNotes.length > 0 || s.view?.needs_review) && (
        <ul className={`drop-detail-notes${s.view?.needs_review ? ' review' : ''}`}>
          {detNotes.map((n) => <li key={n}>{n}</li>)}
        </ul>
      )}
      {review && (
        <div className="drop-review-q" role="group" aria-label="The analysis moved this drop">
          <b>{lost ? 'The analysis no longer finds this drop.' : 'The analysis has moved this drop by more than a beat.'}</b>
          {' '}{lost ? 'Keep yours where you left it, or let it go?' : 'Keep your place, or take the new one?'}
          <HelpLink topic="drop-sequence-review-moved" title="When the analysis moves a sequence" />
          <div className="drop-detail-tools">
            <button type="button" className="primary" disabled={busy}
              onClick={() => void editor.review(s.key, 'keep')}>{lost ? 'Keep it' : 'Keep mine'}</button>
            <button type="button" disabled={busy}
              onClick={() => void editor.review(s.key, 'take')}>{lost ? 'Let it go' : 'Take the new place'}</button>
          </div>
        </div>
      )}
      {s.look === 'mine' ? (
        <p className="drop-detail-soon">
          These are your own triggers: move or edit them on the SPECTRA triggers strip above,
          as you always have.
        </p>
      ) : s.fire === 'stands_down' ? (
        <p className="drop-detail-soon">
          One of your own phase triggers sits here, so this detection stands down and yours fires —
          edit yours on the SPECTRA triggers strip.
        </p>
      ) : (<>
      <div className="drop-detail-tools">
        {confirmable && (
          <button type="button" className="primary" disabled={busy}
            title="Confirm: it is yours now, and it stays through re-analysis (Enter)"
            onClick={() => void editor.confirm(s.key, what)}>✓ Confirm</button>
        )}
        {(s.look === 'confirmed' || s.look === 'edited') && (
          <span className="chip accent" title="Yours: it stays through re-analysis">✓ yours</span>
        )}
        {s.look === 'dismissed' ? (
          <button type="button" className="primary" disabled={busy}
            title="Bring it back: forget the dismissal (it shows as detected again)"
            onClick={() => void editor.revert(s.key, what)}>↺ It is a drop after all</button>
        ) : (<>
          {member('lull')}
          {member('charge')}
          <button type="button" disabled title={LATER}>Make it my triggers</button>
          <button type="button" className="danger" disabled={busy}
            title={isAdded ? 'Remove this drop you added (Delete)'
              : 'Not a drop: hidden, and never offered again within two beats of here (Delete)'}
            onClick={() => void editor.dismiss(s.key, what)}>✕ {isAdded ? 'Remove' : 'Not a drop'}</button>
        </>)}
        {revertible && s.look !== 'dismissed' && (
          <button type="button" disabled={busy}
            title="Forget every edit to this one: back to where the analysis puts it"
            onClick={() => void editor.revert(s.key, what)}>↺ Back to detected</button>
        )}
      </div>
      <p className="drop-detail-soon">
        Drag a handle on the graph (it snaps to bass spikes and beats; Alt places freely), or step it here.
        Every change is one undo step. "Make it my triggers" comes later. Nothing detected fires yet.
        {' '}<HelpLink topic="drop-sequence-editing" title="Editing drop sequences" />
      </p>
      </>)}
    </div>
  );
}

export default function DropSequencesCard({
  resp, loading, error, seqs, selectedKey, onSelect, onJump, showDismissed, setShowDismissed,
  analysedApplies, analysedReason, editor, selHandle, onSelectHandle, onStep,
}: {
  resp: DropSequencesResponse | undefined;
  loading: boolean;
  error: string | null;
  seqs: DisplaySeq[];
  selectedKey: string | null;
  onSelect: (key: string | null) => void;
  onJump: (key: string) => void;
  showDismissed: boolean;
  setShowDismissed: (v: boolean) => void;
  analysedApplies: boolean;
  analysedReason: string | null;
  editor: DropEditor;
  selHandle: Handle;
  onSelectHandle: (h: Handle) => void;
  onStep: (h: Handle, dir: 1 | -1) => void;
}) {
  const selected = seqs.find((s) => s.key === selectedKey) ?? null;
  const dismissedCount = resp?.counts?.dismissed ?? 0;
  const firing = seqs.filter(sequenceFires).length;
  const suggestions = seqs.filter((s) => s.fire === 'waits').length;
  const det = resp?.detector;
  const ageS = det?.detected_at ? Math.max(0, (Date.now() - det.detected_at) / 1000) : null;
  const lone = resp?.authored_lone ?? [];
  const confidentLeft = seqs.filter((q) => q.look === 'confident' && q.fire !== 'stands_down').length;
  const excluded = resp?.excluded ?? [];

  let statusLine: string | null = null;
  if (loading && !resp) statusLine = 'Reading this song\'s drop sequences…';
  else if (error) statusLine = `Could not read the drop sequences: ${error}`;
  else if (resp && resp.status !== 'ok') statusLine = resp.reason ?? 'This song has not been analysed for drops yet.';

  return (
    <div className="drop-review" {...{ [DROP_FOCUS_ATTR]: '' }}>
      <p className="drop-readonly-note">
        Confirm the ones you agree with, dismiss the ones that are not drops, drag a handle on the graph to
        move it, or add a drop the analysis missed — each change is one undo step. Nothing detected fires
        yet; your own charge, lull and drop triggers fire exactly as before.
        {' '}<HelpLink topic="drop-sequences" title="Drop sequences" />
      </p>
      {statusLine && <p className="empty-note">{statusLine}</p>}
      {resp?.status === 'ok' && (
        <p className="drop-meta">
          {firing} that fire{firing === 1 ? 's' : ''} · {suggestions} suggestion{suggestions === 1 ? '' : 's'}
          {' · '}confident from {fmtScore(det?.confident_score)}, suggested from {fmtScore(det?.suggested_score)}
          {ageS != null && ` · analysed ${fmtAgo(ageS)}`}
          {!analysedApplies && analysedReason && (
            <> · <span title={analysedReason}>this song does not play the analysed show, so a confident detection would not fire here</span></>
          )}
        </p>
      )}
      <div className="drop-review-grid">
        <div className="drop-review-list" role="list" aria-label="Drop sequences, in song order">
          <div className="card-title" style={{ marginBottom: 4 }}>
            Review list <HelpLink topic="drop-sequence-review" title="The review list" />
          </div>
          {seqs.map((s) => (
            <div
              key={s.key}
              role="listitem"
              className={`drop-q${s.key === selectedKey ? ' selected' : ''}${s.look === 'dismissed' ? ' dismissed' : ''}`}
              onClick={() => onSelect(s.key)}
            >
              <SeqBadge s={s} />
              <span className="drop-q-text">
                <b>{fmtTenths(s.drop)}</b>
                {breakText(s) && <> · {breakText(s)}</>}
                {' · '}<span className="muted">{reviewStatus(s)}</span>
              </span>
              <span className="drop-q-acts" onClick={(e) => e.stopPropagation()}>
                <button type="button" onClick={() => { onSelect(s.key); onJump(s.key); }}
                  title="Zoom the big graph to this sequence">jump</button>
                {(s.look === 'confident' || s.look === 'suggested') && s.fire !== 'stands_down' && (
                  <button type="button" disabled={editor.busy} title="Confirm: it is yours now"
                    aria-label="Confirm" onClick={() => { onSelect(s.key); void editor.confirm(s.key, fmtTenths(s.drop)); }}>✓</button>
                )}
                {editable(s) && (
                  <button type="button" disabled={editor.busy}
                    title={s.look === 'added' ? 'Remove this drop you added' : 'Not a drop: hidden, never offered again here'}
                    aria-label={s.look === 'added' ? 'Remove' : 'Not a drop'}
                    onClick={() => void editor.dismiss(s.key, fmtTenths(s.drop))}>✕</button>
                )}
                {s.look === 'dismissed' && (
                  <button type="button" disabled={editor.busy} title="It is a drop after all: bring it back"
                    aria-label="Bring it back" onClick={() => void editor.revert(s.key, fmtTenths(s.drop))}>↺</button>
                )}
              </span>
            </div>
          ))}
          {resp?.status === 'ok' && !seqs.length && (
            <p className="empty-note">No drop sequences found on this song.</p>
          )}
          <div className="drop-review-foot">
            <button type="button" disabled={!confidentLeft || editor.busy}
              title={confidentLeft ? `Confirm the ${confidentLeft} confident detection${confidentLeft === 1 ? '' : 's'} on this song — one undo step`
                : 'No confident detection left to confirm'}
              onClick={() => void editor.confirmAll()}>Confirm all confident{confidentLeft ? ` (${confidentLeft})` : ''}</button>
            <button type="button" disabled={editor.busy || resp?.status === 'unavailable'}
              title="Run the detection on this song again now. Your confirms, moves, dismissals and added drops are kept."
              onClick={() => void editor.redetect()}>Re-detect</button>
            <button type="button" disabled={!editor.canUndo || editor.busy}
              title={editor.undoLabel ? `Undo: ${editor.undoLabel}` : 'Nothing to undo'}
              onClick={() => void editor.undo()}>↶ Undo</button>
            <button type="button" disabled={!editor.canRedo || editor.busy}
              title={editor.redoLabel ? `Redo: ${editor.redoLabel}` : 'Nothing to redo'}
              onClick={() => void editor.redo()}>↷ Redo</button>
            <label title="Show the sequences you dismissed, greyed, on the graph, the strip and this list">
              <input type="checkbox" checked={showDismissed}
                onChange={(e) => setShowDismissed(e.target.checked)} />
              {' '}Show dismissed{dismissedCount ? ` (${dismissedCount})` : ''}
            </label>
          </div>
          {(excluded.length > 0 || lone.length > 0) && (
            <ul className="drop-review-notes">
              {excluded.length > 0 && (
                <li>
                  {excluded.length} drop{excluded.length === 1 ? '' : 's'} in the song&apos;s first or last 15 s
                  {' '}left out ({excluded.map((e) => fmtTenths(e.drop_ms)).join(', ')}).
                </li>
              )}
              {lone.length > 0 && (
                <li>
                  {lone.length} of your phase triggers belong{lone.length === 1 ? 's' : ''} to no drop
                  {' '}({lone.map((m) => `${m.kind} ${fmtTenths(m.timestamp_ms)}`).join(', ')}) — not drawn as a sequence.
                </li>
              )}
            </ul>
          )}
        </div>
        <div>
          {selected ? (
            <Detail s={selected} confidentScore={det?.confident_score ?? null}
              onJump={() => onJump(selected.key)} onClose={() => onSelect(null)}
              editor={editor} selHandle={selHandle} onSelectHandle={onSelectHandle} onStep={onStep} />
          ) : (
            <div className="drop-detail placeholder">
              <div className="card-title" style={{ marginBottom: 4 }}>
                Detail box <HelpLink topic="drop-sequence-states" title="What each look means" />
              </div>
              <p className="muted" style={{ fontSize: 13 }}>
                Click a sequence — its handles on the big graph, its pill on the strip, or a row here —
                to see its times, why it was found, its score and what the room does with it, and to
                confirm, dismiss or move it.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
