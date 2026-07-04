import { useEffect, useMemo, useRef, useState } from 'react';

export interface SearchOption {
  value: string;
  label: string;
  /** optional group heading shown as a prefix chip (e.g. "category" / "virtual") */
  group?: string;
}

/** Searchable dropdown: shows the selected label, filters options as you type.
 * Replaces plain <select> everywhere a list is long (events, scenes, params…). */
export default function SearchSelect({
  value,
  onChange,
  options,
  placeholder = '— pick —',
  width = 260,
  allowEmpty = true,
}: {
  value: string;
  onChange: (v: string) => void;
  options: SearchOption[];
  placeholder?: string;
  width?: number | string;
  allowEmpty?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const [hi, setHi] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const selected = options.find((o) => o.value === value);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, []);

  const visible = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const filtered = needle
      ? options.filter(
          (o) => o.label.toLowerCase().includes(needle) || o.value.toLowerCase().includes(needle),
        )
      : options;
    return filtered.slice(0, 200);
  }, [q, options]);

  const pick = (v: string) => {
    onChange(v);
    setOpen(false);
    setQ('');
  };

  return (
    <div ref={rootRef} style={{ position: 'relative', width, maxWidth: '100%' }}>
      <input
        ref={inputRef}
        type="text"
        value={open ? q : selected?.label ?? (value || '')}
        placeholder={selected?.label ?? placeholder}
        onFocus={() => {
          setOpen(true);
          setQ('');
          setHi(0);
        }}
        onChange={(e) => {
          setQ(e.target.value);
          setHi(0);
          if (!open) setOpen(true);
        }}
        onKeyDown={(e) => {
          if (!open) return;
          if (e.key === 'ArrowDown') { e.preventDefault(); setHi((h) => Math.min(h + 1, visible.length - 1)); }
          else if (e.key === 'ArrowUp') { e.preventDefault(); setHi((h) => Math.max(h - 1, 0)); }
          else if (e.key === 'Enter') { e.preventDefault(); if (visible[hi]) pick(visible[hi].value); }
          else if (e.key === 'Escape') { setOpen(false); inputRef.current?.blur(); }
        }}
        style={{ width: '100%' }}
      />
      {open && (
        <div
          style={{
            position: 'absolute', zIndex: 60, top: '100%', left: 0, right: 0, marginTop: 2,
            background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8,
            maxHeight: 260, overflowY: 'auto', boxShadow: '0 6px 20px rgba(0,0,0,0.5)',
          }}
        >
          {allowEmpty && !q && (
            <div
              onMouseDown={(e) => { e.preventDefault(); pick(''); }}
              style={{ padding: '6px 10px', fontSize: 13, cursor: 'pointer', color: 'var(--text-muted)' }}
            >
              {placeholder}
            </div>
          )}
          {visible.map((o, i) => (
            <div
              key={o.value}
              onMouseDown={(e) => { e.preventDefault(); pick(o.value); }}
              onMouseEnter={() => setHi(i)}
              style={{
                padding: '6px 10px', fontSize: 13, cursor: 'pointer',
                display: 'flex', alignItems: 'center', gap: 8,
                background: i === hi ? 'var(--surface2)' : undefined,
                color: o.value === value ? 'var(--accent)' : 'var(--text)',
              }}
            >
              {o.group && <span className="chip" style={{ fontSize: 10 }}>{o.group}</span>}
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{o.label}</span>
            </div>
          ))}
          {!visible.length && (
            <div style={{ padding: '6px 10px', fontSize: 13, color: 'var(--text-muted)' }}>No matches.</div>
          )}
        </div>
      )}
    </div>
  );
}
