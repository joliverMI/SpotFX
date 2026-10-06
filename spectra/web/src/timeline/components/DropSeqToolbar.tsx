/** The drop-sequence EDIT TOOLBAR under the Timeline's audio-shape graph
 * (drop-detection plan, phase 4 — plan.html's mock toolbar): add a drop,
 * undo/redo, and for the selected sequence confirm / not a drop / back to
 * detected; the keyboard cue (lit while a sequence has the keyboard), and
 * the last thing that happened or went wrong. Every action goes through
 * ../hooks/useDropEditor.ts; nothing here fires anything yet. */
import HelpLink from '../../help/HelpLink';
import { fmtTenths, type DisplaySeq } from '../dropSequences';
import { editable } from '../dropEdit';
import type { DropEditor } from '../hooks/useDropEditor';
import { DROP_FOCUS_ATTR } from '../hooks/useDropSeqInteractions';

export default function DropSeqToolbar({
  editor, selected, adding, setAdding, focus, onShowDetail,
}: {
  editor: DropEditor;
  selected: DisplaySeq | null;
  adding: boolean;
  setAdding: (on: boolean) => void;
  focus: boolean;
  onShowDetail: () => void;
}) {
  const can = selected && editable(selected);
  const isAdded = selected?.look === 'added';
  const confirmable = selected && (selected.look === 'confident' || selected.look === 'suggested');
  const revertible = selected && selected.view?.origin === 'detected'
    && (selected.look === 'confirmed' || selected.look === 'edited' || selected.look === 'dismissed');
  const what = selected ? fmtTenths(selected.drop) : '';
  return (
    <div className="drop-toolbar" {...{ [DROP_FOCUS_ATTR]: '' }} data-testid="drop-seq-toolbar">
      <button type="button" className={adding ? 'primary' : ''} aria-pressed={adding}
        title={adding ? 'Adding: click a bass spike on the graph (Esc cancels)'
          : 'Add a drop: then click a bass spike on the graph — the lull and charge are filled in for you'}
        onClick={() => setAdding(!adding)}>
        ＋ Add a drop
      </button>
      <button type="button" disabled={!editor.canUndo || editor.busy}
        title={editor.undoLabel ? `Undo: ${editor.undoLabel} (Ctrl+Z)` : 'Nothing to undo'}
        onClick={() => void editor.undo()}>↶ Undo</button>
      <button type="button" disabled={!editor.canRedo || editor.busy}
        title={editor.redoLabel ? `Redo: ${editor.redoLabel} (Ctrl+Y)` : 'Nothing to redo'}
        onClick={() => void editor.redo()}>↷ Redo</button>
      {selected && (
        <span className="drop-toolbar-sel">
          <button type="button" className="link-button" onClick={onShowDetail} title="Show this sequence's details">
            {selected.look === 'mine' ? 'your triggers' : 'selected'} · {what}
          </button>
          {confirmable && (
            <button type="button" className="primary" disabled={editor.busy}
              title="Confirm: it is yours now and stays through re-analysis (Enter)"
              onClick={() => void editor.confirm(selected.key, what)}>✓ Confirm</button>
          )}
          {can && (
            <button type="button" className="danger" disabled={editor.busy}
              title={isAdded ? 'Remove this drop you added (Delete)' : 'Not a drop: hidden, and never offered again here (Delete)'}
              onClick={() => void editor.dismiss(selected.key, what)}>
              ✕ {isAdded ? 'Remove' : 'Not a drop'}
            </button>
          )}
          {revertible && (
            <button type="button" disabled={editor.busy}
              title="Forget your edits to this one: back to where the analysis puts it"
              onClick={() => void editor.revert(selected.key, what)}>↺ Back to detected</button>
          )}
        </span>
      )}
      <span className={`drop-keys${focus ? ' on' : ''}`}
        title={focus ? 'The keyboard is on this sequence: C L D pick a handle · ← → step it to the next snap point (Shift: 10 ms) · Enter confirms · Delete dismisses · N P next/previous · Ctrl+Z undo · Esc lets go'
          : 'Click a sequence to give it the keyboard'}>
        ⌨ C L D · ← → · Enter · Del · N P
      </span>
      <HelpLink topic="drop-sequence-keys" title="Drop-sequence keyboard" />
      <HelpLink topic="drop-sequence-editing" title="Editing drop sequences" />
      {editor.error ? (
        <span className="drop-toolbar-msg error" role="alert">
          {editor.error}
          <button type="button" className="link-button" aria-label="Dismiss the message" onClick={editor.clearError}>✕</button>
        </span>
      ) : editor.note ? (
        <span className="drop-toolbar-msg">{editor.busy ? 'saving…' : editor.note}</span>
      ) : editor.busy ? <span className="drop-toolbar-msg">saving…</span> : null}
    </div>
  );
}
