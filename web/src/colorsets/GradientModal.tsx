/** Gradient editor modal — port of the color-sets.html grad-modal.
 * "Update current" overwrites the loaded library gradient everywhere it's
 * used; "Save as new" adds a named gradient to the library. */
import { useMemo, useState } from 'react';
import { useToast } from '../components/Toast';
import { useGradientMutations } from './queries';
import type { SavedGradient } from './types';

export interface Stop { color: string; pos: number; }

function hexToRgbStr(hex: string): string {
  const r = parseInt(hex.slice(1, 3), 16), g = parseInt(hex.slice(3, 5), 16), b = parseInt(hex.slice(5, 7), 16);
  return `rgb(${r},${g},${b})`;
}

export function buildGradientCss(dir: string, stops: Stop[]): string {
  const sorted = [...stops].sort((a, b) => a.pos - b.pos);
  if (!sorted.length) return '#ffffff';
  if (sorted.length === 1) return sorted[0].color;
  return `linear-gradient(${dir}deg, ${sorted.map((s) => `${hexToRgbStr(s.color)} ${s.pos}%`).join(', ')})`;
}

export function parseCssGradient(css: string): Stop[] {
  const matches = [...(css || '').matchAll(/rgb\((\d+),\s*(\d+),\s*(\d+)\)\s+(\d+)%/g)];
  if (matches.length) {
    return matches.map((m) => ({
      color: '#' + [m[1], m[2], m[3]].map((n) => parseInt(n).toString(16).padStart(2, '0')).join(''),
      pos: parseInt(m[4]),
    }));
  }
  const hexMatches = [...(css || '').matchAll(/(#[0-9a-fA-F]{6})\s+([\d.]+)%/g)];
  if (hexMatches.length) return hexMatches.map((m) => ({ color: m[1], pos: Math.round(parseFloat(m[2])) }));
  return [{ color: (css || '').startsWith('#') ? css.slice(0, 7) : '#ffffff', pos: 0 }];
}

export default function GradientModal({
  initialCss,
  gradients,
  onApply,
  onClose,
}: {
  initialCss: string;
  gradients: SavedGradient[];
  /** Called with the (saved) gradient CSS to point the originating entry at. */
  onApply: (css: string) => void;
  onClose: () => void;
}) {
  const toast = useToast();
  const { create, update } = useGradientMutations();
  const editing = useMemo(() => gradients.find((g) => g.value === initialCss) ?? null, [gradients, initialCss]);

  const [name, setName] = useState(editing?.name ?? '');
  const dirMatch = initialCss.match(/linear-gradient\((\d+)deg/);
  const [dir, setDir] = useState(dirMatch ? dirMatch[1] : '90');
  const [stops, setStops] = useState<Stop[]>(() => parseCssGradient(initialCss));

  const css = buildGradientCss(dir, stops);
  const setStop = (i: number, patch: Partial<Stop>) =>
    setStops((s) => s.map((st, j) => (j === i ? { ...st, ...patch } : st)));

  const updateCurrent = async () => {
    if (!editing) { toast('Not a saved gradient — use "Save as new"', 'error'); return; }
    try {
      const saved = await update.mutateAsync({ id: editing.id, name: name.trim() || editing.name, value: css });
      onApply(saved.value);
      toast('Gradient updated', 'success');
      onClose();
    } catch (e) {
      toast(`Update failed: ${e}`, 'error');
    }
  };

  const saveNew = async () => {
    if (!name.trim()) { toast('Enter a name for the new gradient', 'error'); return; }
    try {
      const saved = await create.mutateAsync({ name: name.trim(), value: css });
      onApply(saved.value);
      toast('Gradient saved', 'success');
      onClose();
    } catch (e) {
      toast(`Save failed: ${e}`, 'error');
    }
  };

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
    }} onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div style={{
        background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)',
        padding: 16, maxWidth: 420, width: '90vw', maxHeight: '80vh', overflowY: 'auto',
      }}>
        <div className="card-title">Edit Gradient</div>
        <div className="field">
          <label>Name</label>
          <input type="text" placeholder="e.g. Red to Blue" value={name} style={{ width: '100%' }}
            onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="field">
          <label>Direction</label>
          <select value={dir} onChange={(e) => setDir(e.target.value)} style={{ width: '100%' }}>
            <option value="90">→ Horizontal (90°)</option>
            <option value="0">↑ Vertical (0°)</option>
            <option value="45">↘ Diagonal (45°)</option>
            <option value="135">↙ Diagonal (135°)</option>
            <option value="180">← Reverse (180°)</option>
          </select>
        </div>
        <div className="field">
          <label>Color Stops</label>
          {stops.map((s, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
              <input type="color" value={s.color} style={{ width: 40, height: 28, padding: 1 }}
                onChange={(e) => setStop(i, { color: e.target.value })} />
              <input type="number" value={s.pos} min={0} max={100} style={{ width: 64 }}
                onChange={(e) => setStop(i, { pos: parseInt(e.target.value) || 0 })} />
              <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>%</span>
              <button className="danger" style={{ fontSize: 11, padding: '2px 8px' }}
                onClick={() => setStops((st) => st.filter((_, j) => j !== i))}>✕</button>
            </div>
          ))}
          <button style={{ fontSize: 12, marginTop: 6 }}
            onClick={() => setStops((s) => [...s, { color: '#ffffff', pos: 50 }])}>
            + Add Stop
          </button>
        </div>
        <div className="field">
          <label>Preview</label>
          <div style={{ height: 40, borderRadius: 'var(--radius)', border: '1px solid var(--border)', background: css }} />
        </div>
        <div style={{ display: 'flex', gap: 8, marginTop: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <button className="primary" style={{ fontSize: 12, opacity: editing ? 1 : 0.5 }}
            title="Overwrite the selected gradient in the library"
            onClick={() => void updateCurrent()}>
            Update current
          </button>
          <button style={{ fontSize: 12 }} title="Save as a new named gradient"
            onClick={() => void saveNew()}>
            Save as new…
          </button>
          <button style={{ fontSize: 12, marginLeft: 'auto' }} onClick={onClose}>Cancel</button>
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 6 }}>
          {editing
            ? 'Editing saved gradient. "Update current" overwrites it everywhere it is used.'
            : 'This entry uses an unsaved gradient — use "Save as new" to add it to the library.'}
        </div>
      </div>
    </div>
  );
}
