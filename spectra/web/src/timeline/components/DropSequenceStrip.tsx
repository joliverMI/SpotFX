/** THE DROP-SEQUENCE STRIP — the whole song at a glance, under his SPECTRA
 * triggers strip (drop-detection plan, phase 3; plan.html's "New strip
 * below it"). Gold and blue segments are each sequence's build and lull; a
 * numbered pink pill is a sequence that fires (his own triggers today, or
 * one that will once detected drops go live); a dashed "?" is a suggestion
 * waiting for his confirm; an outlined "✦" is a confident detection this
 * song will not play. Clicking a pill selects it and zooms the big graph
 * from two bars before the charge to two bars after the drop. Read-only:
 * nothing here moves or edits a sequence. */
import type { Win } from '../canvas/frame';
import { PHASE_COLOR, stripTitle, type DisplaySeq } from '../dropSequences';

export default function DropSequenceStrip({
  seqs, durationMs, capturedFromMs, selectedKey, getWin, getNowMs, onPick,
}: {
  seqs: DisplaySeq[];
  durationMs: number;
  capturedFromMs: number | null;
  selectedKey: string | null;
  getWin: () => Win;
  getNowMs: () => number | null;
  onPick: (key: string) => void;
}) {
  const dur = Math.max(1, durationMs);
  const pct = (ms: number) => `${Math.max(0, Math.min(100, (ms / dur) * 100))}%`;
  const width = (a: number, b: number) => `${Math.max(0, ((b - a) / dur) * 100)}%`;
  const win = getWin();
  const now = getNowMs();
  const faded = (s: DisplaySeq) => s.fire === 'waits' || s.fire === 'stands_down' || s.fire === 'dismissed';
  return (
    <div className="drop-strip" role="list" aria-label="Drop sequences across the song">
      {capturedFromMs != null && capturedFromMs >= 1000 && (
        <div className="drop-strip-uncaptured" style={{ width: width(0, capturedFromMs) }}
          title="Not captured: the recording of this song starts here, so nothing before it can be analysed" />
      )}
      {now !== null && (
        <div className="drop-strip-played" style={{ width: pct(now) }} />
      )}
      <div className="drop-strip-window" style={{
        left: pct(win.startMs), width: `${Math.max(0.5, ((win.endMs - win.startMs) / dur) * 100)}%` }} />
      {seqs.map((s) => (
        <span key={`seg-${s.key}`}>
          {s.charge != null && (
            <span className={`drop-strip-seg${faded(s) ? ' faded' : ''}`}
              style={{ left: pct(s.charge), width: width(s.charge, s.lull ?? s.drop), background: PHASE_COLOR.charge }} />
          )}
          {s.lull != null && (
            <span className={`drop-strip-seg${faded(s) ? ' faded' : ''}`}
              style={{ left: pct(s.lull), width: width(s.lull, s.drop), background: PHASE_COLOR.lull }} />
          )}
        </span>
      ))}
      {seqs.map((s) => (
        <button
          key={s.key}
          type="button"
          role="listitem"
          className={`drop-pill ${s.fire}${s.key === selectedKey ? ' selected' : ''}`}
          style={{ left: pct(s.drop) }}
          title={stripTitle(s)}
          aria-label={stripTitle(s)}
          onClick={() => onPick(s.key)}
        >
          {s.badge}
        </button>
      ))}
      {!seqs.length && (
        <span className="drop-strip-empty">no drop sequences on this song</span>
      )}
    </div>
  );
}
