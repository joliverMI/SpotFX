import { useEffect, useRef, useState } from 'react';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { FLASH_MS } from '../../lib/flashDiff';
import type { Action } from '../../types/events';
import { ACTION_ICONS, ACTION_TYPE_LABELS, addableKeyOf, summarizeAction } from '../../types/summaries';
import { useSummaryCtx } from '../SummaryCtx';
import { useEditorStore } from '../../store/editorStore';
import { getAtPath, findByUid } from '../../lib/paths';
import { getUid } from '../../lib/uid';
import ActionForm from '../forms/ActionForm';
import RandomGroupBody from './RandomGroupBody';
import SequenceGroupBody from './SequenceGroupBody';
import ParallelGroupBody from './ParallelGroupBody';
import IntensityChooserBody from './IntensityChooserBody';
import LightModeChooserBody from './LightModeChooserBody';
import { writeClip } from '../../store/clipboard';
import OpenRefLink from '../OpenRefLink';
import PreviewButton from '../PreviewButton';
import { previewAction } from '../../lib/preview';

/** Editable HA-style card: drag handle, collapsed summary ⇄ expanded form, ⧉/✕ menu. */
export default function EditActionCard({ action }: { action: Action }) {
  const [open, setOpen] = useState(false);
  const ctx = useSummaryCtx();
  const uid = getUid(action);
  const updateAction = useEditorStore((s) => s.updateAction);
  const removeByUid = useEditorStore((s) => s.removeByUid);
  const mutate = useEditorStore((s) => s.mutate);

  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: uid });

  // Freshly created/updated blocks glow accent-green and fade out. Timestamps
  // (not booleans) let a card remounted mid-fade resume at the right point.
  const flashAt = useEditorStore((s) => s.flashes[uid]);
  const cardRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = cardRef.current;
    if (!flashAt || !el) return;
    const elapsed = Date.now() - flashAt;
    if (elapsed >= FLASH_MS) return;
    // rgba(29,185,84,…) = --accent; box-shadow only, so the card bg is untouched
    const anim = el.animate(
      {
        boxShadow: [
          '0 0 0 2px rgba(29, 185, 84, 0.9), 0 0 14px 2px rgba(29, 185, 84, 0.35), inset 0 0 0 999px rgba(29, 185, 84, 0.12)',
          '0 0 0 2px rgba(29, 185, 84, 0), 0 0 14px 2px rgba(29, 185, 84, 0), inset 0 0 0 999px rgba(29, 185, 84, 0)',
        ],
      },
      { duration: FLASH_MS, easing: 'ease-out' },
    );
    anim.currentTime = elapsed;
    return () => anim.cancel();
  }, [flashAt]);

  // Reference-holding actions get a ↗ that opens the referenced thing.
  // New tab on purpose: same-tab navigation would drop the unsaved draft.
  const ref =
    action.type === 'event_ref' && action.event_id
      ? {
          to: `/event/${action.event_id}`,
          title: `Open event “${ctx.events?.[action.event_id]?.name ?? action.event_id}” in a new tab`,
        }
      : action.type === 'set_color' && action.ref_id && !action.ref_id.startsWith('__')
        ? {
            to: `/color-sets?id=${encodeURIComponent(action.ref_id)}`,
            title: `Open “${ctx.colorSetNames?.[action.ref_id] ?? action.ref_id}” in Color Sets (new tab)`,
          }
        : null;

  const duplicate = () =>
    mutate((d) => {
      const loc = findByUid(d, uid);
      if (loc?.kind !== 'action') return;
      const arr = getAtPath(d, loc.containerPath) as Action[];
      const clone = JSON.parse(
        JSON.stringify(arr[loc.index], (k, v) => (k.startsWith('_') ? undefined : v)),
      ) as Action;
      arr.splice(loc.index + 1, 0, clone);
    });

  return (
    <div
      ref={(el) => {
        setNodeRef(el);
        cardRef.current = el;
      }}
      className="action-card"
      style={{
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: isDragging ? 0.4 : 1,
      }}
    >
      <div className="action-card-row" onClick={() => setOpen(!open)}>
        <span
          {...attributes}
          {...listeners}
          onClick={(e) => e.stopPropagation()}
          title="Drag to reorder / move"
          style={{ cursor: 'grab', color: 'var(--text-muted)', flex: 'none', touchAction: 'none' }}
        >
          ⠿
        </span>
        <span className={`caret ${open ? 'open' : ''}`}>▶</span>
        <span className="action-card-icon">{ACTION_ICONS[addableKeyOf(action)] ?? '❓'}</span>
        <span className="action-card-summary">{summarizeAction(action, ctx)}</span>
        {action.weight !== 1 && <span className="chip" title="Weight">w {action.weight}</span>}
        {action.labels.slice(0, 3).map((l) => (
          <span key={l} className="chip">{l}</span>
        ))}
        <span className="action-card-type">{ACTION_TYPE_LABELS[addableKeyOf(action)] ?? action.type}</span>
        {ref && <OpenRefLink to={ref.to} title={ref.title} />}
        <button title="Copy (paste in any track, any event)" style={{ padding: '2px 7px', fontSize: 12 }}
          onClick={(e) => { e.stopPropagation(); writeClip('action', action, summarizeAction(action, ctx)); }}>📋</button>
        <button title="Duplicate" style={{ padding: '2px 7px', fontSize: 12 }}
          onClick={(e) => { e.stopPropagation(); duplicate(); }}>⧉</button>
        <PreviewButton title="Preview — fire this action now" run={() => previewAction(action)} />
        <button className="danger" title="Delete" style={{ padding: '2px 7px', fontSize: 12 }}
          onClick={(e) => { e.stopPropagation(); removeByUid(uid); }}>✕</button>
      </div>
      {open && (
        <div className="action-card-body">
          {action.type === 'random_group' && <RandomGroupBody uid={uid} action={action} />}
          {action.type === 'sequence_group' && <SequenceGroupBody uid={uid} action={action} />}
          {action.type === 'parallel_group' && <ParallelGroupBody uid={uid} action={action} />}
          {action.type === 'intensity_chooser' && (action.source === 'display_mode'
            ? <LightModeChooserBody uid={uid} action={action} />
            : <IntensityChooserBody uid={uid} action={action} />)}
          <ActionForm action={action} update={(fn) => updateAction(uid, fn)} />
        </div>
      )}
    </div>
  );
}
