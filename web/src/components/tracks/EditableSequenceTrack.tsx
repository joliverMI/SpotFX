import { SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import type { MusicEvent, SequenceStep } from '../../types/events';
import { getUid } from '../../lib/uid';
import { newSequenceStep } from '../../lib/defaults';
import { useEditorStore } from '../../store/editorStore';
import { useEvents } from '../../api/queries';
import { Checkbox, LabelsInput, NumberInput, Row, Select } from '../forms/inputs';
import EditableActionContainer from './EditableActionContainer';
import PreviewButton from '../PreviewButton';
import { previewSequenceStep } from '../../lib/preview';

function StepCard({ step, index }: { step: SequenceStep; index: number }) {
  const uid = getUid(step);
  const mutate = useEditorStore((s) => s.mutate);
  const removeByUid = useEditorStore((s) => s.removeByUid);
  const { data: events } = useEvents();
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: uid });

  const set = (fn: (s: SequenceStep) => void) =>
    mutate((d) => { const s = d.sequence_steps[index]; if (s && getUid(s) === uid) fn(s); });

  const duplicate = () =>
    mutate((d) => {
      const clone = JSON.parse(
        JSON.stringify(d.sequence_steps[index], (k, v) => (k.startsWith('_') ? undefined : v)),
      ) as SequenceStep;
      d.sequence_steps.splice(index + 1, 0, clone);
    });

  const eventOpts = (events ?? [])
    .slice()
    .sort((a, b) => a.name.localeCompare(b.name))
    .map((e) => ({ value: e.id, label: e.name }));

  return (
    <div
      ref={setNodeRef}
      className="action-card"
      style={{ padding: 10, transform: CSS.Transform.toString(transform), transition, opacity: isDragging ? 0.4 : 1 }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8, flexWrap: 'wrap' }}>
        <span {...attributes} {...listeners} title="Drag to reorder"
          style={{ cursor: 'grab', color: 'var(--text-muted)', touchAction: 'none' }}>⠿</span>
        <span className="step-badge">{index + 1}</span>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
          <span style={{ color: 'var(--text-muted)' }}>delay</span>
          <NumberInput value={step.delay_ms} min={0} step={50} width={90}
            onChange={(v) => set((s) => { s.delay_ms = v ?? 0; })} />
          <span style={{ color: 'var(--text-muted)' }}>ms</span>
        </label>
        <Checkbox
          value={step.step_type === 'event'}
          label="event ref"
          onChange={(v) => set((s) => { s.step_type = v ? 'event' : 'action'; })}
        />
        <span style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
          <button title="Duplicate step" style={{ padding: '2px 7px', fontSize: 12 }} onClick={duplicate}>⧉</button>
          <PreviewButton title="Preview — fire this step now (delay skipped)"
            run={() => previewSequenceStep(step)} />
          <button className="danger" title="Delete step" style={{ padding: '2px 7px', fontSize: 12 }}
            onClick={() => removeByUid(uid)}>✕</button>
        </span>
      </div>

      {step.step_type === 'event' ? (
        <Row label="Event">
          <Select value={step.event_id ?? ''} width={280}
            onChange={(v) => set((s) => { s.event_id = v || null; })}
            options={[{ value: '', label: '— pick an event —' }, ...eventOpts]} />
        </Row>
      ) : (
        <div style={{ marginLeft: 26 }}>
          <EditableActionContainer
            containerPath={`sequence_steps.${index}.actions`}
            actions={step.actions}
            emptyNote="No actions — all actions in a step fire concurrently."
          />
        </div>
      )}
      <Row label="Step labels">
        <LabelsInput value={step.labels} onChange={(v) => set((s) => { s.labels = v; })} />
      </Row>
    </div>
  );
}

export default function EditableSequenceTrack({ event }: { event: MusicEvent }) {
  const mutate = useEditorStore((s) => s.mutate);
  const steps = event.sequence_steps;
  const revert = event.revert;

  return (
    <div className="track">
      <div className="track-header">
        <span>➡️</span>
        <span>Sequence — {steps.length} steps</span>
      </div>
      <SortableContext items={steps.map(getUid)} strategy={verticalListSortingStrategy}>
        {steps.map((s, i) => (
          <StepCard key={getUid(s)} step={s} index={i} />
        ))}
      </SortableContext>
      {!steps.length && <p className="empty-note">No steps yet.</p>}
      <button style={{ fontSize: 12 }} onClick={() => mutate((d) => { d.sequence_steps.push(newSequenceStep()); })}>
        + Add step
      </button>

      <div style={{ marginTop: 14, borderTop: '1px solid var(--border)', paddingTop: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <Checkbox
            value={!!revert?.enabled}
            label="↩️ Revert after sequence"
            onChange={(v) =>
              mutate((d) => {
                if (v) d.revert = { enabled: true, delay_ms: d.revert?.delay_ms ?? 0, transition_ms: d.revert?.transition_ms ?? 500 };
                else if (d.revert) d.revert.enabled = false;
              })
            }
          />
          {revert?.enabled && (
            <>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
                <span style={{ color: 'var(--text-muted)' }}>hold</span>
                <NumberInput value={revert.delay_ms} min={0} step={50} width={90}
                  onChange={(v) => mutate((d) => { if (d.revert) d.revert.delay_ms = v ?? 0; })} />
                <span style={{ color: 'var(--text-muted)' }}>ms, ramp</span>
                <NumberInput value={revert.transition_ms} min={0} step={50} width={90}
                  onChange={(v) => mutate((d) => { if (d.revert) d.revert.transition_ms = v ?? 500; })} />
                <span style={{ color: 'var(--text-muted)' }}>ms</span>
              </label>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
