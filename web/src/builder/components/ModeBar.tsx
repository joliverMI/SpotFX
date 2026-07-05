/** Mode bar: Live / Auto-Wait toggles + song search (standard mode) + track
 * info. Capture/Analyze/Genre-Blend/Verified wiring lands in Phase 5. */
import { useMemo, useState } from 'react';
import { useBuilderStore } from '../store';
import { useProfilesList } from '../queries';

export default function ModeBar() {
  const track = useBuilderStore((s) => s.track);
  const manualUri = useBuilderStore((s) => s.manualUri);
  const liveMode = useBuilderStore((s) => s.liveMode);
  const autoWait = useBuilderStore((s) => s.autoWait);
  const setLiveMode = useBuilderStore((s) => s.setLiveMode);
  const setAutoWait = useBuilderStore((s) => s.setAutoWait);
  const setManualUri = useBuilderStore((s) => s.setManualUri);
  const profile = useBuilderStore((s) => s.profile);
  const dirty = useBuilderStore((s) => s.dirty);

  const { data: profiles } = useProfilesList();
  const [q, setQ] = useState('');

  const results = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle || !profiles) return [];
    return profiles
      .filter((p) => `${p.title} ${p.artist}`.toLowerCase().includes(needle))
      .slice(0, 12);
  }, [q, profiles]);

  const shownTitle = liveMode ? track?.title : profile?.title;
  const shownArtist = liveMode ? track?.artist : profile?.artist;

  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
      <button className={liveMode ? 'primary' : ''} onClick={() => setLiveMode(!liveMode)}
        title="Follow the currently playing track">
        {liveMode ? '● Live' : 'Live'}
      </button>
      <button className={autoWait ? 'primary' : ''} onClick={() => setAutoWait(!autoWait)}
        title="Freeze on the current song until it changes">
        Auto Wait
      </button>
      {!liveMode && (
        <span style={{ position: 'relative' }}>
          <input
            type="search"
            placeholder="Search songs…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            style={{ width: 260 }}
          />
          {results.length > 0 && (
            <div style={{
              position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 50, marginTop: 2,
              background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8,
              maxHeight: 280, overflowY: 'auto', boxShadow: '0 6px 20px rgba(0,0,0,0.5)',
            }}>
              {results.map((p) => (
                <div key={p.spotify_uri}
                  onMouseDown={(e) => { e.preventDefault(); setManualUri(p.spotify_uri); setQ(''); }}
                  style={{ padding: '6px 10px', fontSize: 13, cursor: 'pointer' }}>
                  <b>{p.title}</b> <span style={{ color: 'var(--text-muted)' }}>{p.artist}</span>
                  {p.verified && ' ✓'}
                </div>
              ))}
            </div>
          )}
        </span>
      )}
      <span style={{ flex: 1 }} />
      <span style={{ minWidth: 0, textAlign: 'right' }}>
        <div style={{ fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {shownTitle ?? '—'}
          {dirty && <span title="Saving…" style={{ color: 'var(--accent2)', marginLeft: 6 }}>●</span>}
          {profile?.verified && <span title="Verified" style={{ marginLeft: 6 }}>✓</span>}
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
          {shownArtist ?? (liveMode ? 'waiting for playback…' : manualUri ? '' : 'search a song')}
        </div>
      </span>
    </div>
  );
}
