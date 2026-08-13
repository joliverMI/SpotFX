/** Small shared form inputs (spot-effects contract, SPECTRA tokens). */
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
      style={{ width, padding: '5px 8px', fontSize: 13 }}
      onChange={(e) => {
        const raw = e.target.value;
        if (raw === '') return onChange(nullable ? null : 0);
        const n = Number(raw);
        if (!Number.isNaN(n)) onChange(n);
      }}
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
      style={{ width: width ?? 220, fontSize: 13 }}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

export function Checkbox({ value, onChange, label, title }: {
  value: boolean;
  onChange: (v: boolean) => void;
  label?: string;
  title?: string;
}) {
  return (
    <label title={title} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, cursor: 'pointer' }}>
      <input type="checkbox" checked={value} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

/** Comma-separated labels ⇄ string[] */
export function LabelsInput({ value, onChange, placeholder }: {
  value: string[];
  onChange: (v: string[]) => void;
  placeholder?: string;
}) {
  return (
    <input
      type="text"
      defaultValue={value.join(', ')}
      key={value.join(',')}
      placeholder={placeholder ?? 'label1, label2'}
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
