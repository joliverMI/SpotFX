/** Ambient Mode toggle with a long-press Hue-group picker.
 * Short press: toggle all groups on/off. Long-press (500ms): pick which Hue
 * groups are held — each checkbox applies immediately (POST /control/ambient-mode
 * with groups=<id>). Held state comes live from the WS store; the group list
 * (names) from GET /control/ambient-groups. */
import { useEffect, useRef, useState } from 'react';
import { apiPost } from '../api/client';
import { useAmbientGroups } from '../api/queries';
import HelpLink from '../help/HelpLink';
import { useLongPress } from '../lib/useLongPress';
import { useLiveStore } from '../live/liveStore';

export default function AmbientButton({ compact = false }: { compact?: boolean }) {
  const ambient = useLiveStore((s) => s.ambient);
  const held = useLiveStore((s) => s.ambientGroups);
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const longPress = useLongPress();
  const groupsQ = useAmbientGroups();
  const groups = groupsQ.data?.groups ?? [];

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);

  const heldSet = new Set(held);
  const partial = ambient && groups.length > 0 && held.length > 0 && held.length < groups.length;

  return (
    <div ref={rootRef} style={{ position: 'relative', display: 'inline-block' }}>
      <button
        className={compact ? `icon-btn ${ambient ? 'active' : ''}` : `toggle-btn ${ambient ? 'active' : ''}`}
        title={`Ambient Mode${partial ? ` (${held.length}/${groups.length} groups)` : ''} — hold the Hue groups at a static full-brightness color; long-press to pick groups`}
        {...longPress(() => setOpen(true))}
        onClick={() => void apiPost(`/control/ambient-mode?enabled=${!ambient}`)}
      >
        {compact ? '💡' : `Ambient${partial ? ` ${held.length}/${groups.length}` : ''}`}
      </button>
      {open && (
        <div
          style={{
            position: 'absolute', zIndex: 60, top: '100%', left: 0, marginTop: 4, minWidth: 190,
            background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8,
            boxShadow: '0 6px 20px rgba(0,0,0,0.5)', padding: '8px 10px',
          }}
        >
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6, display: 'flex', alignItems: 'center', gap: 4 }}>
            Ambient Hue groups <HelpLink topic="ambient-groups" />
          </div>
          {groupsQ.isLoading && <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>loading…</div>}
          {groups.map((g) => {
            const on = heldSet.has(g.id);
            return (
              <label
                key={g.id}
                style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0', fontSize: 13, cursor: 'pointer', whiteSpace: 'nowrap' }}
              >
                <input
                  type="checkbox"
                  checked={on}
                  onChange={() => void apiPost(`/control/ambient-mode?enabled=${!on}&groups=${encodeURIComponent(g.id)}`)}
                />
                {g.name}
              </label>
            );
          })}
          {!groupsQ.isLoading && !groups.length && (
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>No Hue groups found</div>
          )}
        </div>
      )}
    </div>
  );
}
