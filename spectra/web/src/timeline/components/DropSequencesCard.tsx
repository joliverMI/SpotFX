/** THE DROP-SEQUENCE REVIEW LIST and DETAIL BOX (drop-detection plan,
 * phase 3; plan.html's "Review list" and "the detail box"). Every sequence
 * on the song in time order — its time, its break length in beats, and what
 * of his is already there ("matches your drop", "you have a flare here") —
 * with a jump that zooms the big graph to it. Selecting one (here, on the
 * graph or on the strip) opens its detail box: the three times, why it was
 * found, its score, what the room does with it, and whether it fires.
 *
 * READ-ONLY. The edit buttons are drawn where they will be, DISABLED and
 * labelled as coming with editing (phase 4); nothing detected fires yet
 * (phase 5). ../dropSequences.ts holds every word and number shown here. */
import HelpLink from '../../help/HelpLink';
import { fmtAgo } from '../../lib/time';
import {
  PHASE_COLOR, fireLine, fmtHundredths, fmtTenths, handleRows, reviewStatus, roomLines,
  sequenceFires, whyFound, type DisplaySeq, type DropSequencesResponse, type Handle,
} from '../dropSequences';

const fmtScore = (v: number | null | undefined) => (v == null ? '—' : v.toFixed(1));

const NEXT_PHASE = 'Arrives with editing, the next step of the drop-sequence build — read-only for now';

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

function Detail({ s, confidentScore, onJump, onClose }: {
  s: DisplaySeq;
  confidentScore: number | null;
  onJump: () => void;
  onClose: () => void;
}) {
  const why = whyFound(s.view, confidentScore);
  const rows = handleRows(s);
  const detNotes = s.look === 'mine' ? [] : s.view?.notes ?? [];
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
          <span className={`drop-detail-time${r.ms == null ? ' empty' : ''}`}>
            {r.ms != null ? fmtHundredths(r.ms) : '—'}
          </span>
          <span className="drop-detail-steps">
            {STEP_LABEL[r.handle].map((label) => (
              <button key={label} type="button" disabled title={NEXT_PHASE}>{label}</button>
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
      {s.look === 'mine' ? (
        <p className="drop-detail-soon">
          These are your own triggers: move or edit them on the SPECTRA triggers strip above,
          as you always have.
        </p>
      ) : (<>
      <div className="drop-detail-tools">
        <button type="button" className="primary" disabled title={NEXT_PHASE}>✓ Confirm</button>
        <button type="button" disabled title={NEXT_PHASE}>Lull off</button>
        <button type="button" disabled title={NEXT_PHASE}>Charge off</button>
        <button type="button" disabled title={NEXT_PHASE}>Make it my triggers</button>
        <button type="button" className="danger" disabled title={NEXT_PHASE}>✕ Not a drop</button>
      </div>
      <p className="drop-detail-soon">
        Editing comes next: confirm, dismiss, drag and snap, switch the lull or charge off.
        For now this is read-only, and nothing detected fires yet.
      </p>
      </>)}
    </div>
  );
}

export default function DropSequencesCard({
  resp, loading, error, seqs, selectedKey, onSelect, onJump, showDismissed, setShowDismissed,
  analysedApplies, analysedReason,
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
}) {
  const selected = seqs.find((s) => s.key === selectedKey) ?? null;
  const dismissedCount = resp?.counts?.dismissed ?? 0;
  const firing = seqs.filter(sequenceFires).length;
  const suggestions = seqs.filter((s) => s.fire === 'waits').length;
  const det = resp?.detector;
  const ageS = det?.detected_at ? Math.max(0, (Date.now() - det.detected_at) / 1000) : null;
  const lone = resp?.authored_lone ?? [];
  const excluded = resp?.excluded ?? [];

  let statusLine: string | null = null;
  if (loading && !resp) statusLine = 'Reading this song\'s drop sequences…';
  else if (error) statusLine = `Could not read the drop sequences: ${error}`;
  else if (resp && resp.status !== 'ok') statusLine = resp.reason ?? 'This song has not been analysed for drops yet.';

  return (
    <div className="drop-review">
      <p className="drop-readonly-note">
        <span className="chip accent">read-only</span>
        {' '}You can look, not edit yet — and nothing detected fires yet. Your own charge, lull and drop
        triggers fire exactly as before.
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
                {(s.fire === 'waits' || s.fire === 'muted') && (
                  <>
                    <button type="button" disabled title={`Confirm — ${NEXT_PHASE}`} aria-label="Confirm">✓</button>
                    <button type="button" disabled title={`Not a drop — ${NEXT_PHASE}`} aria-label="Not a drop">✕</button>
                  </>
                )}
              </span>
            </div>
          ))}
          {resp?.status === 'ok' && !seqs.length && (
            <p className="empty-note">No drop sequences found on this song.</p>
          )}
          <div className="drop-review-foot">
            <button type="button" disabled title={NEXT_PHASE}>Confirm all confident</button>
            <button type="button" disabled title={NEXT_PHASE}>Re-detect</button>
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
              onJump={() => onJump(selected.key)} onClose={() => onSelect(null)} />
          ) : (
            <div className="drop-detail placeholder">
              <div className="card-title" style={{ marginBottom: 4 }}>
                Detail box <HelpLink topic="drop-sequence-states" title="What each look means" />
              </div>
              <p className="muted" style={{ fontSize: 13 }}>
                Click a sequence — its handles on the big graph, its pill on the strip, or a row here —
                to see its times, why it was found, its score and what the room does with it.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
