/** Small shared form inputs used by every action form. */
import { useState } from 'react';
import type { CSSProperties, ReactNode } from 'react';

export function Row({ label, children, help }: { label: string; children: ReactNode; help?: string }) {
  return (
    <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, fontSize: 13 }} title={help}>
      <span style={{ width: 130, color: 'var(--text-muted)', flex: 'none' }}>{label}</span>
      {children}
    </label>
  );
}

export function NumberInput({
  value,
  onChange,
  nullable,
  min,
  max,
  step,
  placeholder,
  width = 110,
}: {
  value: number | null;
  onChange: (v: number | null) => void;
  nullable?: boolean;
  min?: number;
  max?: number;
  step?: number;
  placeholder?: string;
  width?: number;
}) {
  return (
    <input
      type="number"
      value={value ?? ''}
      min={min}
      max={max}
      step={step ?? 'any'}
      placeholder={placeholder ?? (nullable ? '—' : undefined)}
      style={{
        width,
        background: 'var(--bg)',
        color: 'var(--text)',
        border: '1px solid var(--border)',
        borderRadius: 6,
        padding: '5px 8px',
        fontSize: 13,
      }}
      onChange={(e) => {
        const raw = e.target.value;
        if (raw === '') return onChange(nullable ? null : 0);
        const n = Number(raw);
        if (!Number.isNaN(n)) onChange(n);
      }}
    />
  );
}

export function TextInput({
  value,
  onChange,
  placeholder,
  width,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  width?: number | string;
}) {
  return (
    <input
      type="text"
      value={value}
      placeholder={placeholder}
      style={{ width: width ?? '100%', maxWidth: 360 }}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

export function Select({
  value,
  onChange,
  options,
  width,
}: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  width?: number | string;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      style={{
        width: width ?? 220,
        background: 'var(--bg)',
        color: 'var(--text)',
        border: '1px solid var(--border)',
        borderRadius: 6,
        padding: '6px 8px',
        fontSize: 13,
      }}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

export function Checkbox({ value, onChange, label, title }: { value: boolean; onChange: (v: boolean) => void; label?: string; title?: string }) {
  return (
    <label title={title} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, cursor: 'pointer' }}>
      <input type="checkbox" checked={value} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

export function ColorInput({
  value,
  onChange,
  nullable,
}: {
  value: string | null;
  onChange: (v: string | null) => void;
  nullable?: boolean;
}) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <input
        type="color"
        value={value && /^#[0-9a-fA-F]{6}$/.test(value) ? value : '#ffffff'}
        onChange={(e) => onChange(e.target.value)}
        style={{ width: 34, height: 26, padding: 0, border: '1px solid var(--border)', borderRadius: 4, background: 'none', cursor: 'pointer' }}
      />
      <input
        type="text"
        value={value ?? ''}
        placeholder={nullable ? '— unchanged' : '#rrggbb'}
        style={{ width: 120 }}
        onChange={(e) => onChange(e.target.value === '' && nullable ? null : e.target.value)}
      />
    </span>
  );
}

/** Comma-separated labels ⇄ string[] */
export function LabelsInput({ value, onChange, placeholder }: { value: string[]; onChange: (v: string[]) => void; placeholder?: string }) {
  return (
    <input
      type="text"
      defaultValue={value.join(', ')}
      key={value.join(',')}
      placeholder={placeholder ?? 'label1, label2, -not-this'}
      style={{ width: '100%', maxWidth: 360 }}
      onBlur={(e) =>
        onChange(
          e.target.value
            .split(',')
            .map((s) => s.trim())
            .filter(Boolean),
        )
      }
    />
  );
}

/** Comma-separated list ⇄ string[] that commits on every keystroke.
 *
 * Buffers the raw text while focused: parsing and re-joining on each change
 * would drop a trailing "," (empty segment) and strip the space after it, so
 * the caret jumped to the end and the separator could never be typed. */
export function CsvInput({ value, onChange, placeholder, style }: {
  value: string[];
  onChange: (v: string[]) => void;
  placeholder?: string;
  style?: CSSProperties;
}) {
  const joined = (value ?? []).join(', ');
  const [text, setText] = useState(joined);
  const [editing, setEditing] = useState(false);
  return (
    <input
      type="text"
      placeholder={placeholder}
      style={style}
      value={editing ? text : joined}
      onFocus={() => { setText(joined); setEditing(true); }}
      onBlur={() => setEditing(false)}
      onChange={(e) => {
        setText(e.target.value);
        onChange(e.target.value.split(',').map((s) => s.trim()).filter(Boolean));
      }}
    />
  );
}

/** Comma-separated scope list editor (virtual ids / categories / roles). */
export function ScopeListInput({ value, onChange, placeholder }: { value: string[]; onChange: (v: string[]) => void; placeholder: string }) {
  return <LabelsInput value={value} onChange={onChange} placeholder={placeholder} />;
}
