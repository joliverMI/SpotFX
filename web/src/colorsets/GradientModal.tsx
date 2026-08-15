/** Gradient editor modal — the shared library's name/save chrome around
 * LedFX's own picker (`react-gcolor-picker`), which does the actual stop
 * editing, angle, and live preview. "Update current" overwrites the loaded
 * library gradient everywhere it's used; "Save as new" adds a named one. */
import { useMemo, useState } from 'react';
import ReactGPicker from 'react-gcolor-picker';
import { useToast } from '../components/Toast';
import { normalizeGradientAngle } from '../components/ColorGradientPicker';
import { useGradientMutations } from './queries';
import type { SavedGradient } from './types';

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
  const [css, setCss] = useState(initialCss || '#ffffff');

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
          <label>Colour / gradient</label>
          <ReactGPicker
            value={css}
            format="hex"
            showAlpha={false}
            debounce
            debounceMS={200}
            solid
            gradient
            defaultColors={gradients.map((g) => g.value)}
            onChange={(next: string) => setCss(normalizeGradientAngle(next))}
          />
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
