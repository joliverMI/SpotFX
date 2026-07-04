import { useEffect, useState, type CSSProperties } from 'react';
import type { MorphScope } from '../../types/events';
import { useParamConfig } from '../../api/queries';
import SearchSelect from './SearchSelect';

export const emptyScope = (): MorphScope => ({ virtual_ids: [], categories: [], roles: [] });

const isEmpty = (s: MorphScope | null | undefined) =>
  !s || (!s.virtual_ids.length && !s.categories.length && !s.roles.length);

/** Encode a single-selection scope as 'cat:X' / 'vid:Y'; '' = none. Returns
 * null when the scope holds more than one entry (built outside this picker). */
function encode(s: MorphScope | null | undefined): string | null {
  if (isEmpty(s)) return '';
  const total = s!.virtual_ids.length + s!.categories.length + s!.roles.length;
  if (total > 1 || s!.roles.length) return null;
  if (s!.categories.length) return `cat:${s!.categories[0]}`;
  return `vid:${s!.virtual_ids[0]}`;
}

function decode(v: string): MorphScope | null {
  if (!v) return null;
  const s = emptyScope();
  if (v.startsWith('cat:')) s.categories = [v.slice(4)];
  else if (v.startsWith('vid:')) s.virtual_ids = [v.slice(4)];
  return s;
}

/** One searchable field over categories + virtuals (auto-populated from the
 * effect-params catalog). Blank = no target. */
export function ScopeSelect({
  scope,
  onChange,
  width = 260,
}: {
  scope: MorphScope | null | undefined;
  onChange: (s: MorphScope | null) => void;
  width?: number;
}) {
  const { data: config } = useParamConfig();
  const cats = Object.keys(config?.categories ?? {});
  const vids = [...new Set(cats.flatMap((c) => config?.categories[c]?.virtuals ?? []))].sort();
  const options = [
    ...cats.map((c) => ({ value: `cat:${c}`, label: c, group: 'category' })),
    ...vids.map((v) => ({ value: `vid:${v}`, label: v, group: 'virtual' })),
  ];

  const enc = encode(scope);
  if (enc === null) {
    // Multi-entry / role scope built elsewhere (e.g. JSON editor) — don't clobber it.
    const parts = [...(scope?.virtual_ids ?? []), ...(scope?.categories ?? []), ...(scope?.roles ?? [])];
    return (
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
        <span className="chip accent" title="Complex scope — edit via JSON">{parts.join(', ')}</span>
        <button style={{ fontSize: 11, padding: '2px 7px' }} onClick={() => onChange(null)}>clear</button>
      </span>
    );
  }
  return (
    <SearchSelect
      value={enc}
      onChange={(v) => onChange(decode(v))}
      options={options}
      placeholder="— all devices —"
      width={width}
    />
  );
}

/** Parent/Override toggle + ScopeSelect: null scope = "parent" (inherit the
 * nearest group/lane Target); set = override. Keeps the UI clean by hiding
 * the picker until override is chosen. */
export function ParentScopeToggle({
  scope,
  onChange,
  parentLabel = 'parent',
}: {
  scope: MorphScope | null | undefined;
  onChange: (s: MorphScope | null) => void;
  parentLabel?: string;
}) {
  // Toggle is local UI state: an override with nothing picked yet stays null
  // in the model (the engine treats empty scope as inherit anyway).
  const [override, setOverride] = useState(!isEmpty(scope));
  useEffect(() => {
    if (!isEmpty(scope)) setOverride(true);
  }, [scope]);

  const btn = (active: boolean): CSSProperties => ({
    fontSize: 11, padding: '3px 10px', border: 'none', borderRadius: 0,
    background: active ? 'var(--accent)' : 'transparent',
    color: active ? '#06130a' : 'var(--text-muted)',
  });
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
      <span style={{ display: 'inline-flex', border: '1px solid var(--border)', borderRadius: 999, overflow: 'hidden' }}>
        <button style={btn(!override)} title="Inherit the nearest group/lane Target"
          onClick={() => { setOverride(false); onChange(null); }}>
          {parentLabel}
        </button>
        <button style={btn(override)} title="Target a specific device or category"
          onClick={() => setOverride(true)}>
          override
        </button>
      </span>
      {override && <ScopeSelect scope={scope} onChange={onChange} />}
    </span>
  );
}
