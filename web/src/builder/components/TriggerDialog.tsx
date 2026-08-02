/** Trigger edit/create dialog: timestamp (m:ss.t), searchable event
 * (recents-first), filter labels, and the intensity slider + number. */
import { useEffect, useMemo, useState } from 'react';
import HelpLink from '../../help/HelpLink';
import OpenRefLink from '../../components/OpenRefLink';
import SearchSelect from '../../components/forms/SearchSelect';
import { fmtMsTenths, parseMsTenths } from '../../lib/time';
import { readSticky, writeSticky } from '../../lib/useSticky';
import { uuid } from '../../lib/uid';
import { useBuilderStore } from '../store';
import { useColorSets } from '../../api/queries';
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
  const [overrideBlend, setOverrideBlend] = useState(false);
  const [colorGroup, setColorGroup] = useState('');
  const [displayMode, setDisplayMode] = useState<'default' | 'dark' | 'light'>('default');
  const { data: colorSets } = useColorSets();

  useEffect(() => {
    if (!editingId) return;
    if (isNew) {
      setTsText(fmtMsTenths(Number(editingId.slice(4)) || 0));
      setEventId(readSticky<string>('lastEventId', ''));
      setLabels('');
      setIntensity(0.5);
      setOverrideBlend(false);
      setColorGroup('');
      setDisplayMode('default');
    } else if (existing) {
      setTsText(fmtMsTenths(existing.timestamp_ms));
      setEventId(existing.event_id);
      setLabels(existing.labels.join(', '));
      setIntensity(existing.intensity ?? 0.5);
      setOverrideBlend(existing.override_blend ?? false);
      setColorGroup(existing.color_group_override ?? '');
      setDisplayMode(existing.display_mode ?? 'default');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editingId]);

  // Palette key pressed while the dialog is open → assign + save immediately.
  useEffect(() => {
    if (!editingId) return;
    const onAssign = (e: Event) => {
      const evId = String((e as CustomEvent).detail ?? '');
      if (evId) {
        setEventId(evId);
        save(evId);
      }
    };
    window.addEventListener('spotfx:palette-assign', onAssign);
    return () => window.removeEventListener('spotfx:palette-assign', onAssign);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editingId, tsText, labels, intensity]);

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

  const save = (overrideEventId?: string) => {
    const ms = parseMsTenths(tsText);
    const evId = overrideEventId ?? eventId;
    if (ms === null || !evId) return;
    writeSticky('lastEventId', evId);
    writeSticky('recentEvents', [evId, ...recents.filter((r) => r !== evId)].slice(0, 8));
    const labelList = labels.split(',').map((s) => s.trim()).filter(Boolean);
    mutateWorking((triggers) => {
      if (isNew) {
        triggers.push({ id: uuid(), timestamp_ms: ms, event_id: evId,
                        labels: labelList, enabled: true, intensity,
                        override_blend: overrideBlend,
                        color_group_override: colorGroup || null,
                        display_mode: displayMode });
      } else {
        const t = triggers.find((tt) => tt.id === editingId);
        if (t) {
          t.timestamp_ms = ms;
          t.event_id = evId;
          t.labels = labelList;
          t.intensity = intensity;
          t.override_blend = overrideBlend;
          t.color_group_override = colorGroup || null;
          t.display_mode = displayMode;
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
          {eventId && (
            <OpenRefLink
              to={`/event/${eventId}`}
              title={`Open event “${events.find((e) => e.id === eventId)?.name ?? eventId}” in a new tab`}
            />
          )}
        </label>

        <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, fontSize: 13 }}
          title={LABELS_HELP}>
          <span style={{ width: 90, color: 'var(--text-muted)' }}>Labels</span>
          <input type="text" value={labels} onChange={(e) => setLabels(e.target.value)}
            placeholder="chorus, -quiet" style={{ flex: 1 }} />
          <HelpLink topic="filter-labels" title="Label filter syntax" />
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

        <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, fontSize: 13 }}
          title="When this trigger fires a Scene Group, use THIS Color Group instead of the group's designated one. Blank = group's normal colors. Missing/deleted groups fall back to normal.">
          <span style={{ width: 90, color: 'var(--text-muted)' }}>Colors 🖌️</span>
          <SearchSelect value={colorGroup} width={220}
            options={(colorSets ?? []).filter((c) => c.kind === 'group')
              .map((c) => ({ value: c.id, label: c.name }))}
            placeholder="— group's own colors —" allowEmpty
            onChange={(v) => setColorGroup(v ?? '')} />
          <HelpLink topic="trigger-color-override" title="Scene-group color override" />
        </label>

        <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, fontSize: 13 }}
          title="Force Dark or Light mode while this trigger fires. Default defers to the scene group / scene / color levels; the TopBar toggle still outranks this.">
          <span style={{ width: 90, color: 'var(--text-muted)' }}>Mode 🌗</span>
          <select value={displayMode}
            onChange={(e) => setDisplayMode(e.target.value as 'default' | 'dark' | 'light')}
            style={{ width: 160 }}>
            <option value="default">Default (defer)</option>
            <option value="dark">🌙 Dark</option>
            <option value="light">☀️ Light</option>
          </select>
          <HelpLink topic="display-modes" title="Dark / Light mode" />
        </label>

        <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, fontSize: 13 }}
          title="Stretch or compress this event's ramps and delays so it completes exactly at the next enabled trigger (or song end). Beat-timed spacing stays on the beat — only its ramps scale.">
          <span style={{ width: 90, color: 'var(--text-muted)' }}>Blend ⤳</span>
          <input type="checkbox" checked={overrideBlend}
            onChange={(e) => setOverrideBlend(e.target.checked)} />
          <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>
            Override blend — ramp until the next trigger
          </span>
          <HelpLink topic="override-blend" title="Override Blend" />
        </label>

        <div style={{ display: 'flex', gap: 8 }}>
          <button className="primary" onClick={() => save()} disabled={!eventId || parseMsTenths(tsText) === null}>
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
