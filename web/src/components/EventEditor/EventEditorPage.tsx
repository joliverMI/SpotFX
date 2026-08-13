import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  closestCorners,
  pointerWithin,
  useSensor,
  useSensors,
  type CollisionDetection,
  type DragEndEvent,
  type DragStartEvent,
} from '@dnd-kit/core';
import { useColorSets, useDeleteEvent, useEvents, useFireEvent, useSaveEvent } from '../../api/queries';
import { SCENE_EVENT_TYPES, type MusicEvent } from '../../types/events';
import { ACTION_ICONS, summarizeAction, type SummaryContext } from '../../types/summaries';
import { SummaryProvider } from '../SummaryCtx';
import { useEditorStore, useIsDirty } from '../../store/editorStore';
import { findByUid } from '../../lib/paths';
import { newAction, newEvent } from '../../lib/defaults';
import { uuid } from '../../lib/uid';
import EventMetaPanel from './EventMetaPanel';
import RootSlot from './RootSlot';
import PreviewButton from '../PreviewButton';
import { previewEvent } from '../../lib/preview';
import EditableActionContainer from '../tracks/EditableActionContainer';
import EditableSequenceTrack from '../tracks/EditableSequenceTrack';
import EditableParallelLanes, { PhaseCycleButton } from '../tracks/EditableParallelLanes';
import BeatSequenceTrack from '../tracks/BeatSequenceTrack';
import ParallelLanes from '../tracks/ParallelLanes';
import DeviceTargetsTrack from '../tracks/DeviceTargetsTrack';
import SceneGroupTrack from '../tracks/SceneGroupTrack';

/** Event types with full track editing; the rest render read-only tracks. */
const EDITABLE_TYPES = ['single', 'sequence', 'morph_set', 'scene_update', 'composite', 'scene_group'];

const collision: CollisionDetection = (args) => {
  const within = pointerWithin(args);
  return within.length ? within : closestCorners(args);
};

export default function EventEditorPage() {
  const { id } = useParams<{ id: string }>();
  const [search] = useSearchParams();
  const navigate = useNavigate();
  const { data: events, isLoading } = useEvents();
  const { data: colorSets } = useColorSets();
  const fire = useFireEvent();
  const save = useSaveEvent();
  const del = useDeleteEvent();

  const draft = useEditorStore((s) => s.draft);
  const load = useEditorStore((s) => s.load);
  const serialize = useEditorStore((s) => s.serialize);
  const markSaved = useEditorStore((s) => s.markSaved);
  const moveByUid = useEditorStore((s) => s.moveByUid);
  const undo = useEditorStore((s) => s.undo);
  const redo = useEditorStore((s) => s.redo);
  const dirty = useIsDirty();

  const [dragUid, setDragUid] = useState<string | null>(null);
  const [fired, setFired] = useState(false);
  const isNew = id === 'new';

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }));

  // Load the event into the store when the route target changes.
  useEffect(() => {
    if (isNew) {
      const t = (search.get('type') as MusicEvent['event_type']) || 'composite';
      const ev = newEvent(t);
      const rootKind = search.get('root');
      if (t === 'composite' && rootKind) {
        ev.root = newAction(rootKind as Parameters<typeof newAction>[0]);
      }
      load(ev);
      return;
    }
    const ev = events?.find((e) => e.id === id);
    if (ev && useEditorStore.getState().draft?.id !== ev.id) load(ev);
  }, [id, isNew, events, load, search]);

  // Undo/redo keys + warn on close with unsaved changes.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
        e.preventDefault();
        if (e.shiftKey) redo();
        else undo();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [undo, redo]);

  useEffect(() => {
    const onUnload = (e: BeforeUnloadEvent) => {
      if (useEditorStore.getState().draft && dirty) e.preventDefault();
    };
    window.addEventListener('beforeunload', onUnload);
    return () => window.removeEventListener('beforeunload', onUnload);
  }, [dirty]);

  const ctx: SummaryContext = useMemo(
    () => ({
      events: Object.fromEntries((events ?? []).map((e) => [e.id, e])),
      colorSetNames: Object.fromEntries((colorSets ?? []).map((c) => [c.id, c.name])),
    }),
    [events, colorSets],
  );

  if (isLoading && !isNew) return <p className="empty-note">Loading…</p>;
  if (!draft) return <p className="empty-note">Event not found. <Link to="/">Back to list</Link></p>;

  // Meta edits are safe for every non-fixed event (payload round-trips untouched);
  // track editing is gated per type until later phases.
  const metaEditable = !draft.fixed;
  const editable = metaEditable && EDITABLE_TYPES.includes(draft.event_type);

  const onDragStart = (e: DragStartEvent) => setDragUid(String(e.active.id));
  const onDragEnd = (e: DragEndEvent) => {
    setDragUid(null);
    const { active, over } = e;
    if (!over || active.id === over.id) return;
    const overId = String(over.id);
    if (overId.startsWith('container:')) {
      const path = overId.slice('container:'.length);
      const dst = findByUid(draft, String(active.id));
      if (dst?.kind === 'action') moveByUid(String(active.id), path, Number.MAX_SAFE_INTEGER);
      return;
    }
    const target = findByUid(draft, overId);
    if (!target) return;
    moveByUid(String(active.id), target.containerPath, target.index);
  };

  const doSave = () => {
    const body = serialize();
    save.mutate(body, {
      onSuccess: () => {
        markSaved();
        if (isNew) navigate(`/event/${body.id}`, { replace: true });
      },
    });
  };

  const doDuplicate = () => {
    const body = serialize();
    body.id = uuid();
    body.name = `${body.name} - Copy`;
    body.fixed = false;
    save.mutate(body, { onSuccess: () => navigate(`/event/${body.id}`) });
  };

  const doDelete = () => {
    if (!confirm(`Delete event “${draft.name}”?`)) return;
    del.mutate(draft.id, { onSuccess: () => navigate('/') });
  };

  const onFire = () => {
    setFired(true);
    fire.mutate(draft.id, { onSettled: () => setTimeout(() => setFired(false), 800) });
  };

  const dragged = dragUid ? findByUid(draft, dragUid) : null;

  return (
    <SummaryProvider value={ctx}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16, flexWrap: 'wrap' }}>
        <Link to="/">← Events</Link>
        <span className="color-dot" style={{ background: draft.color }} />
        <h2 style={{ flex: 1, minWidth: 0, fontSize: 20 }}>
          {draft.fixed && '🔒 '}
          {draft.name}
          {dirty && <span title="Unsaved changes" style={{ color: 'var(--accent2)', marginLeft: 8 }}>●</span>}
        </h2>
        {metaEditable && (
          <button className="primary" onClick={doSave} disabled={!dirty && !isNew}>
            {save.isPending ? 'Saving…' : 'Save'}
          </button>
        )}
        <button onClick={onFire} disabled={isNew || dirty} title={dirty ? 'Save first — fire uses the stored event' : 'Test-fire'}>
          {fired ? '✔ Fired' : '▶ Fire'}
        </button>
        {!isNew && !draft.fixed && <button onClick={doDuplicate}>⧉ Duplicate</button>}
        <PreviewButton label="Preview" style={{ padding: '6px 12px', fontSize: 14 }}
          title="Fire the current draft as-is, without saving"
          run={() => previewEvent(serialize())} />
        {!isNew && !draft.fixed && <button className="danger" onClick={doDelete}>Delete</button>}
      </div>

      {save.isError && <p style={{ color: 'var(--danger)', fontSize: 13 }}>Save failed: {String(save.error)}</p>}

      {editable ? (
        <>
          <EventMetaPanel event={draft} />
          <DndContext sensors={sensors} collisionDetection={collision} onDragStart={onDragStart} onDragEnd={onDragEnd}>
            {draft.event_type === 'single' && (
              <div className="track">
                <div className="track-header">
                  <span>🎲</span>
                  <span>Random pick — one of {draft.actions.length} (weighted)</span>
                </div>
                <EditableActionContainer containerPath="actions" actions={draft.actions} />
              </div>
            )}
            {draft.event_type === 'sequence' && <EditableSequenceTrack event={draft} />}
            {(draft.event_type === 'morph_set' || draft.event_type === 'scene_update') && (
              <EditableParallelLanes event={draft} />
            )}
            {draft.event_type === 'composite' && <RootSlot event={draft} />}
            {draft.event_type === 'scene_group' && <SceneGroupTrack event={draft} />}
            <DragOverlay>
              {dragged?.kind === 'action' && (
                <div className="action-card" style={{ boxShadow: '0 4px 16px rgba(0,0,0,0.5)' }}>
                  <div className="action-card-row">
                    <span className="action-card-icon">{ACTION_ICONS[dragged.action.type]}</span>
                    <span className="action-card-summary">{summarizeAction(dragged.action, ctx)}</span>
                  </div>
                </div>
              )}
            </DragOverlay>
          </DndContext>
        </>
      ) : (
        <>
          <EventMetaPanel event={draft} />
          {draft.event_type === 'beat_sequence' && <BeatSequenceTrack event={draft} />}
          {draft.event_type === 'device_settings' && <DeviceTargetsTrack targets={draft.device_targets} />}
          {(draft.event_type === 'morph_set' || (SCENE_EVENT_TYPES as string[]).includes(draft.event_type)) && (
            <ParallelLanes lanes={draft.morph_lanes} />
          )}
          {['charge', 'lull', 'drop'].includes(draft.event_type) && (
            <div style={{ margin: '8px 0' }}><PhaseCycleButton /></div>
          )}
          <p className="empty-note">
            {draft.fixed
              ? 'Built-in event — read-only.'
              : `Settings above are editable; ${draft.event_type} track editing lands in a later phase — use the classic editor meanwhile.`}
          </p>
        </>
      )}
    </SummaryProvider>
  );
}
