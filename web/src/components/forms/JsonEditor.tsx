import { useState } from 'react';
import type { Action } from '../../types/events';
import { stripUids } from '../../lib/uid';

/** Raw-JSON escape hatch: full-fidelity editing for fields the simplified forms don't cover yet. */
export default function JsonEditor({
  action,
  onApply,
}: {
  action: Action;
  onApply: (parsed: Record<string, unknown>) => void;
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState('');
  const [err, setErr] = useState('');

  if (!open) {
    return (
      <button
        style={{ fontSize: 11, padding: '3px 8px' }}
        onClick={() => {
          setText(JSON.stringify(stripUids(action), null, 2));
          setOpen(true);
        }}
      >
        {'{ } Edit as JSON'}
      </button>
    );
  }

  return (
    <div style={{ marginTop: 8 }}>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        spellCheck={false}
        style={{
          width: '100%',
          minHeight: 180,
          background: 'var(--bg)',
          color: 'var(--text)',
          border: '1px solid var(--border)',
          borderRadius: 6,
          padding: 8,
          fontFamily: 'monospace',
          fontSize: 12,
        }}
      />
      {err && <p style={{ color: 'var(--danger)', fontSize: 12 }}>{err}</p>}
      <div style={{ display: 'flex', gap: 8, marginTop: 6 }}>
        <button
          className="primary"
          onClick={() => {
            try {
              const parsed = JSON.parse(text);
              if (parsed.type !== action.type) throw new Error(`type must stay "${action.type}"`);
              onApply(parsed);
              setOpen(false);
              setErr('');
            } catch (e) {
              setErr(String(e));
            }
          }}
        >
          Apply
        </button>
        <button onClick={() => { setOpen(false); setErr(''); }}>Cancel</button>
      </div>
    </div>
  );
}
