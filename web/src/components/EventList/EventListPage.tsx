import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useEvents, useFireEvent } from '../../api/queries';
import { EVENT_TYPE_LABELS, SCENE_EVENT_TYPES, type EventType, type MusicEvent } from '../../types/events';

type Filter = 'all' | 'single' | 'sequence' | 'beat_sequence' | 'morph_set' | 'scene' | 'device_settings';

const FILTERS: { key: Filter; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'single', label: 'Single' },
  { key: 'sequence', label: 'Sequence' },
  { key: 'beat_sequence', label: 'Beat Seq' },
  { key: 'morph_set', label: 'Morphs' },
  { key: 'scene', label: 'Scenes' },
  { key: 'device_settings', label: 'Devices' },
];

function matchesFilter(ev: MusicEvent, f: Filter): boolean {
  if (f === 'all') return true;
  if (f === 'scene') return SCENE_EVENT_TYPES.includes(ev.event_type);
  return ev.event_type === (f as EventType);
}

export default function EventListPage() {
  const { data: events, isLoading, error } = useEvents();
  const fire = useFireEvent();
  const navigate = useNavigate();
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState<Filter>('all');
  const [firedId, setFiredId] = useState<string | null>(null);

  const visible = useMemo(() => {
    if (!events) return [];
    const q = search.trim().toLowerCase();
    return events
      .filter((ev) => matchesFilter(ev, filter))
      .filter(
        (ev) =>
          !q ||
          ev.name.toLowerCase().includes(q) ||
          ev.labels.some((l) => l.toLowerCase().includes(q)),
      )
      .sort((a, b) => Number(a.fixed) - Number(b.fixed) || a.name.localeCompare(b.name));
  }, [events, search, filter]);

  const onFire = (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    setFiredId(id);
    fire.mutate(id, { onSettled: () => setTimeout(() => setFiredId(null), 600) });
  };

  if (isLoading) return <p className="empty-note">Loading events…</p>;
  if (error) return <p className="empty-note">Failed to load events: {String(error)}</p>;

  return (
    <>
      <div className="card">
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <input
            type="search"
            placeholder="Search events by name or label…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{ flex: 1, minWidth: 220 }}
            autoFocus
          />
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {FILTERS.map((f) => (
              <span
                key={f.key}
                className={`chip filter ${filter === f.key ? 'active' : ''}`}
                onClick={() => setFilter(f.key)}
              >
                {f.label}
              </span>
            ))}
          </div>
          <span style={{ display: 'flex', gap: 6 }}>
            <button className="primary" onClick={() => navigate('/event/new?type=single')}>+ Single</button>
            <button className="primary" onClick={() => navigate('/event/new?type=sequence')}>+ Sequence</button>
            <button className="primary" onClick={() => navigate('/event/new?type=morph_set')}>+ Morph Set</button>
          </span>
        </div>
      </div>

      {visible.map((ev) => (
        <div key={ev.id} className="event-row" onClick={() => navigate(`/event/${ev.id}`)}>
          <span className="color-dot" style={{ background: ev.color }} />
          <span style={{ fontWeight: 600, flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {ev.fixed && <span title="Built-in (read-only)" style={{ marginRight: 6 }}>🔒</span>}
            {ev.name}
          </span>
          <span className="chip">{EVENT_TYPE_LABELS[ev.event_type] ?? ev.event_type}</span>
          {ev.energy_level != null && <span className="chip accent">⚡ {ev.energy_level}</span>}
          {ev.labels.slice(0, 3).map((l) => (
            <span key={l} className="chip">{l}</span>
          ))}
          {ev.ai_exposed && <span className="chip" title="Exposed to AI trigger generation">AI</span>}
          <button onClick={(e) => onFire(e, ev.id)} title="Test-fire this event">
            {firedId === ev.id ? '✔' : '▶'}
          </button>
        </div>
      ))}
      {!visible.length && <p className="empty-note">No events match.</p>}
    </>
  );
}
