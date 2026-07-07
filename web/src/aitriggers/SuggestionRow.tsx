/** One AI suggestion: editable timestamp + event, confidence bar, labels,
 * feedback comment, approve/reject. */
import { useState } from 'react';
import type { EventOption } from '../builder/types';
import { confColor, fmtTs, isModified, parseTsInput, type Suggestion } from './types';

export default function SuggestionRow({
  idx, sug, events, highlighted, onHighlight, onChange,
}: {
  idx: number;
  sug: Suggestion;
  events: EventOption[];
  highlighted: boolean;
  onHighlight: () => void;
  onChange: (next: Suggestion, resort?: boolean) => void;
}) {
  const [commentOpen, setCommentOpen] = useState(!!sug.comment);
  const [tsDraft, setTsDraft] = useState<string | null>(null);

  const modified = !sug.manually_added && isModified(sug);
  const borderColor = sug.approved === true ? '#4caf50'
    : sug.approved === false ? '#ef5350'
    : modified ? '#ff9800' : 'var(--border)';
  const fillW = Math.round((sug.manually_added ? 1 : sug.confidence) * 100);

  return (
    <div id={`sug-${idx}`} style={{
      border: `1px solid ${sug.approved !== null ? borderColor : 'var(--border)'}`,
      borderLeft: `3px solid ${borderColor}`,
      borderRadius: 6, padding: '10px 12px', marginBottom: 8,
      opacity: sug.approved === false ? 0.55 : 1,
      outline: highlighted ? '2px solid rgba(255,255,255,0.4)' : undefined,
      background: highlighted ? 'rgba(255,255,255,0.04)' : undefined,
      transition: 'border-color .15s, opacity .15s',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', cursor: 'pointer' }}
        onClick={onHighlight}>
        {sug.manually_added && (
          <span style={{ fontSize: 10, fontWeight: 700, padding: '1px 5px', borderRadius: 8, background: '#1565c0', color: '#fff' }}>+ manual</span>
        )}
        {modified && sug.approved !== false && (
          <span style={{ fontSize: 10, fontWeight: 700, padding: '1px 5px', borderRadius: 8, background: '#e65100', color: '#fff' }}>◆ edited</span>
        )}
        <input
          value={tsDraft ?? fmtTs(sug.timestamp_ms)}
          title="Edit timestamp (m:ss.t)"
          style={{
            fontSize: 14, fontWeight: 600, width: 70, background: 'transparent',
            border: 'none', borderBottom: '1px dashed var(--text-muted)', borderRadius: 0,
            color: 'var(--text)', padding: 0,
          }}
          onClick={(e) => e.stopPropagation()}
          onFocus={(e) => { setTsDraft(fmtTs(sug.timestamp_ms)); e.target.select(); }}
          onChange={(e) => setTsDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }}
          onBlur={() => {
            if (tsDraft === null) return;
            const ms = parseTsInput(tsDraft);
            setTsDraft(null);
            if (ms !== null && ms !== sug.timestamp_ms) onChange({ ...sug, timestamp_ms: ms }, true);
          }}
        />
        <select value={sug.event_id} style={{ fontSize: 12, padding: '2px 6px' }}
          onClick={(e) => e.stopPropagation()}
          onChange={(e) => onChange({ ...sug, event_id: e.target.value })}>
          {events.map((ev) => <option key={ev.id} value={ev.id}>{ev.name}</option>)}
        </select>
        <div style={{ flex: 1, height: 6, background: 'var(--border)', borderRadius: 3, minWidth: 60 }}>
          <div style={{
            height: '100%', borderRadius: 3, width: `${fillW}%`,
            background: sug.manually_added ? '#1565c0' : confColor(sug.confidence),
          }} />
        </div>
        <span style={{ fontSize: 11, color: 'var(--text-muted)', minWidth: 32 }}>
          {sug.manually_added ? 'manual' : `${fillW}%`}
        </span>
      </div>

      {!sug.manually_added && !!sug.reasoning && (
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 5 }}>{sug.reasoning}</div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginTop: 6 }}>
        <label style={{ fontSize: 10, color: 'var(--text-muted)', whiteSpace: 'nowrap', marginBottom: 0 }}>Labels:</label>
        <input type="text" placeholder="comma-separated"
          defaultValue={sug.labels.join(', ')}
          style={{
            flex: 1, fontSize: 11, background: 'transparent', border: 'none',
            borderBottom: '1px dashed transparent', borderRadius: 0, color: 'var(--text)', padding: 0,
          }}
          onChange={(e) => onChange({
            ...sug,
            labels: e.target.value.split(',').map((s) => s.trim()).filter(Boolean),
          })} />
      </div>

      <div style={{ marginTop: 5 }}>
        <span style={{ fontSize: 10, color: 'var(--text-muted)', cursor: 'pointer', userSelect: 'none' }}
          onClick={() => setCommentOpen((o) => !o)}>
          {commentOpen || sug.comment ? '▾ Feedback' : '▸ Add feedback'}
        </span>
        {(commentOpen || !!sug.comment) && (
          <textarea
            placeholder="Why approve/reject? What did Claude get wrong?"
            defaultValue={sug.comment}
            style={{ width: '100%', marginTop: 4, fontSize: 11, resize: 'vertical', minHeight: 40 }}
            onChange={(e) => onChange({ ...sug, comment: e.target.value })} />
        )}
      </div>

      <div style={{ display: 'flex', gap: 6, marginTop: 8, alignItems: 'center' }}>
        <button style={{ background: '#2e7d32', color: '#fff', border: 'none', borderRadius: 4, padding: '4px 12px', fontSize: 12 }}
          onClick={() => onChange({ ...sug, approved: true })}>
          ✓ Approve
        </button>
        <button style={{ background: 'transparent', color: 'var(--text-muted)', borderRadius: 4, padding: '4px 12px', fontSize: 12 }}
          onClick={() => {
            onChange({ ...sug, approved: false });
            setCommentOpen(true);
          }}>
          ✕ Reject
        </button>
      </div>
    </div>
  );
}
