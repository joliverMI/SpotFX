/** Double-click / tap a flare kind card → rename, delete, or copy it. Mirrors
 * SpectraTriggerDialog.tsx's overlay/card shape. Deliberately does NOT edit
 * type/jump/params/gain/hold_ms — those stay agent-adjustable (ResponseTab's
 * existing "tell the agent to change it" convention); rename/delete/copy are
 * STRUCTURAL/identity operations, not program-behavior tuning, so a small
 * direct control here doesn't reopen the no-settings-form-sprawl question.
 *
 * ONE TYPE HAS NOTHING TO TUNE (Word Shapes row W2.1): a `word_shape` kind's
 * form, hold and release are the ROOM's own `word_shape_*` settings, paced by
 * the sung word's Energy, and the model REFUSES params/gain/hold_ms on it
 * (spectra/models/scene.py FlareKind._shape). So this box says that plainly
 * instead of offering "tell the agent to retune those", which would send him
 * after a knob that does not exist — and the Words tab's own "+ Word Shape
 * kind" button (flareKindOps.newWordShapeKind) is where one is declared. */
import { useState } from 'react';
import HelpLink from '../../help/HelpLink';
import { copyFlareKind } from '../../lib/flareClipboard';
import { useToast } from '../../components/Toast';
import type { FlareKind, SceneV2 } from '../../types';
import { countKindUsages } from './flareKindOps';

export default function FlareKindEditDialog({
  scene, sceneName, kind, onClose, onRename, onDelete,
}: {
  scene: SceneV2;
  sceneName: string;
  kind: FlareKind;
  onClose: () => void;
  onRename: (newName: string) => string | null;   // returns an error string, or null on success
  onDelete: () => void;
}) {
  const toast = useToast();
  const [name, setName] = useState(kind.name);
  const [error, setError] = useState<string | null>(null);

  const usages = countKindUsages(scene, kind.name);

  const doRename = () => {
    const trimmed = name.trim();
    if (trimmed === kind.name) { onClose(); return; }
    const err = onRename(trimmed);
    if (err) setError(err);
    else onClose();
  };

  const doDelete = () => {
    const msg = usages
      ? `Delete "${kind.name}"? It's attached in ${usages} place${usages === 1 ? '' : 's'} — those will detach too.`
      : `Delete "${kind.name}"?`;
    if (!confirm(msg)) return;
    onDelete();
    onClose();
  };

  const doCopy = () => {
    copyFlareKind(kind, sceneName, Date.now());
    toast(`Copied "${kind.name}" — paste it on any scene's Flares/Responses tab`, 'success');
    onClose();
  };

  return (
    <div onClick={onClose}
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 100,
               display: 'flex', alignItems: 'flex-start', justifyContent: 'center', paddingTop: '14vh' }}>
      <div className="card" onClick={(e) => e.stopPropagation()}
        style={{ width: 360, maxWidth: '92vw', margin: 0 }}>
        <div className="card-title">
          Edit flare kind <HelpLink topic="flare-kind-edit-box" />
        </div>

        <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6, fontSize: 13 }}>
          <span style={{ width: 60, color: 'var(--text-muted)' }}>Name</span>
          <input type="text" value={name} style={{ flex: 1 }}
            onChange={(e) => { setName(e.target.value); setError(null); }}
            onKeyDown={(e) => e.key === 'Enter' && doRename()} />
        </label>
        {error && <div style={{ fontSize: 11, color: 'var(--danger)', marginBottom: 6 }}>{error}</div>}
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 12 }}>
          Attached in {usages} band{usages === 1 ? '' : 's'} right now.{' '}
          {kind.type === 'word_shape' ? (
            <>
              A Word Shape kind has <b>no knobs</b> — the form, hold and release are the
              room's own Word shape settings, paced by the sung word's Energy. Only a
              Words band fires it. <HelpLink topic="word-shapes" title="Word shapes" />
            </>
          ) : (
            <>Type/params/gain/hold stay agent-adjustable — tell the agent to retune those.</>
          )}
        </div>

        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button className="primary" onClick={doRename} disabled={!name.trim()}>Rename</button>
          <button onClick={doCopy}>⧉ Copy</button>
          <button className="danger" onClick={doDelete}>Delete</button>
          <span style={{ flex: 1 }} />
          <button onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
}
