/** Trigger edit/create dialog: timestamp (m:ss.t), searchable event
 * (recents-first), filter labels, and the intensity slider + number. */
import { useEffect, useMemo, useState } from 'react';
import SearchSelect from '../../components/forms/SearchSelect';
import { fmtMsTenths, parseMsTenths } from '../../lib/time';
import { readSticky, writeSticky } from '../../lib/useSticky';
import { uuid } from '../../lib/uid';
import { useBuilderStore } from '../store';
import type { EventOption, MusicTrigger } from '../types';

const LABELS_HELP =
  'Comma-separated filter labels passed to the event: "chorus, big" requires a match; "-quiet" excludes. Blank = no filtering.';

export default function TriggerDialog({ events }: { events: EventOption[] }) {
  const editingId = useBuilderStore((s) => s.editingTriggerId);
  const setEditing = useBuilderStore((s) => s.setEditingTrigger);
  const mutateWorking = useBuilderStore((s) => s.mutateWorking);
  const workingTriggers = useBuilderStore((s) => s.workingTriggers);

  const isNew = editingId?.startsWith('new:') ?? false;
  const existing: MusicTrigger | undefined = useMemo(() => {
    if (!editingId || isNew) return undefined;
    return workingTriggers().find((t) => t.id === editingId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editingId]);

  const [tsText, setTsText] = useState('');
  const [eventId, setEventId] = useState('');
  const [labels, setLabels] = useState('');
  const [intensity, setIntensity] = useState(0.5);

  useEffect(() => {
    if (!editingId) return;
    if (isNew) {
      setTsText(fmtMsTenths(Number(editingId.slice(4)) || 0));
      setEventId(readSticky<string>('lastEventId', ''));
      setLabels('');
      setIntensity(0.5);
    } else if (existing) {
      setTsText(fmtMsTenths(existing.timestamp_ms));
      setEventId(existing.event_id);
      setLabels(existing.labels.join(', '));
      setIntensity(existing.intensity ?? 0.5);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editingId]);

  if (!editingId || (!isNew && !existing)) return null;

  const recents = readSticky<string[]>('recentEvents', []);
  const options = [...events]
    .sort((a, b) => {
      const ra = recents.indexOf(a.id);
      const rb = recents.indexOf(b.id);
      if (ra !== rb) return (ra === -1 ? 999 : ra) - (rb === -1 ? 999 : rb);
      return a.name.localeCompare(b.name);
    })
    .map((e) => ({ value: e.id, label: e.name }));

  const close = () => setEditing(null);

  const save = () => {
    const ms = parseMsTenths(tsText);
    if (ms === null || !eventId) return;
    writeSticky('lastEventId', eventId);
    writeSticky('recentEvents', [eventId, ...recents.filter((r) => r !== eventId)].slice(0, 8));
    const labelList = labels.split(',').map((s) => s.trim()).filter(Boolean);
    mutateWorking((triggers) => {
      if (isNew) {
        triggers.push({ id: uuid(), timestamp_ms: ms, event_id: eventId,
                        labels: labelList, enabled: true, intensity });
      } else {
        const t = triggers.find((tt) => tt.id === editingId);
        if (t) {
          t.timestamp_ms = ms;
          t.event_id = eventId;
          t.labels = labelList;
          t.intensity = intensity;
        }
      }
    });
    close();
  };

  const del = () => {
    if (!isNew) {
      mutateWorking((triggers) => {
        const i = triggers.findIndex((tt) => tt.id === editingId);
        if (i >= 0) triggers.splice(i, 1);
      });
    }
    close();
  };

  return (
    <div onClick={close}
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 100,
               display: 'flex', alignItems: 'flex-start', justifyContent: 'center', paddingTop: '14vh' }}>
      <div className="card" onClick={(e) => e.stopPropagation()}
        style={{ width: 420, maxWidth: '92vw', margin: 0 }}>
        <div className="card-title">{isNew ? 'New Trigger' : 'Edit Trigger'}</div>

        <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, fontSize: 13 }}>
          <span style={{ width: 90, color: 'var(--text-muted)' }}>Timestamp</span>
          <input type="text" value={tsText} onChange={(e) => setTsText(e.target.value)}
            placeholder="m:ss.t" style={{ width: 110 }} />
        </label>

        <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, fontSize: 13 }}>
          <span style={{ width: 90, color: 'var(--text-muted)' }}>Event</span>
          <SearchSelect value={eventId} onChange={setEventId} options={options}
            placeholder="— pick an event —" width={260} allowEmpty={false} />
        </label>

        <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, fontSize: 13 }}
          title={LABELS_HELP}>
          <span style={{ width: 90, color: 'var(--text-muted)' }}>Labels</span>
          <input type="text" value={labels} onChange={(e) => setLabels(e.target.value)}
            placeholder="chorus, -quiet" style={{ flex: 1 }} />
        </label>

        <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, fontSize: 13 }}
          title="Per-trigger fire intensity (0–1). Drives values bound to the trigger_intensity signal; also draggable as the circle on the timeline.">
          <span style={{ width: 90, color: 'var(--text-muted)' }}>Intensity ⚡</span>
          <input type="range" min={0} max={1} step={0.01} value={intensity}
            onChange={(e) => setIntensity(Number(e.target.value))} style={{ flex: 1 }} />
          <input type="number" min={0} max={1} step={0.01} value={intensity}
            onChange={(e) => setIntensity(Math.max(0, Math.min(1, Number(e.target.value))))}
            style={{ width: 70, background: 'var(--bg)', color: 'var(--text)',
                     border: '1px solid var(--border)', borderRadius: 6, padding: '5px 8px' }} />
        </label>

        <div style={{ display: 'flex', gap: 8 }}>
          <button className="primary" onClick={save} disabled={!eventId || parseMsTenths(tsText) === null}>
            Save
          </button>
          {!isNew && <button className="danger" onClick={del}>Delete</button>}
          <span style={{ flex: 1 }} />
          <button onClick={close}>Cancel</button>
        </div>
      </div>
    </div>
  );
}
