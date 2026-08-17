/** Mode bar: Live / Auto-Wait, song search (standard mode), engine mode
 * toggles (Capture / Analyze / Genre Blend — states mirrored from the WS
 * state message), Verified flag, setlist slot select, track info. */
import { useEffect, useMemo, useState } from 'react';
import { apiPost } from '../../api/spotfx';
import { useToast } from '../../components/Toast';
import { useSticky } from '../../lib/useSticky';
import { useBuilderStore } from '../store';
import { useProfilesList, useSetlists } from '../queries';

// Per-song Set List "slot" trigger override authoring retired 2026-08-17 on
// the Admiral's word — "don't delete the data but yes, retire that function
// for now" (docs/SPECTRA_SPEC.md OQ-5/§41). His setlist_triggers data is
// untouched on disk; this flag just stops the slot picker from being
// offered (and stops a stale sticky slot selection from reactivating on
// load). Flip back to true to restore, no other changes needed here.
const SETLIST_SLOTS_ENABLED = false;

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
  const modes = useBuilderStore((s) => s.modes);
  const slotId = useBuilderStore((s) => s.slotId);
  const setSlot = useBuilderStore((s) => s.setSlot);
  const mutateProfile = useBuilderStore((s) => s.mutateProfile);
  const toast = useToast();

  const { data: profiles } = useProfilesList();
  const { data: setlists } = useSetlists();
  const [q, setQ] = useState('');

  // Sticky global slot; the store is the live copy the rest of the page reads.
  const [stickySlot, setStickySlot] = useSticky('setlistSlot', '');
  useEffect(() => {
    if (SETLIST_SLOTS_ENABLED) setSlot(stickySlot);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stickySlot]);

  const results = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle || !profiles) return [];
    return profiles
      .filter((p) => `${p.title} ${p.artist}`.toLowerCase().includes(needle))
      .slice(0, 12);
  }, [q, profiles]);

  const post = (path: string, err: string) =>
    apiPost(path).catch(() => toast(err, 'error'));

  const shownTitle = liveMode ? track?.title : profile?.title;
  const shownArtist = liveMode ? track?.artist : profile?.artist;
  const slotHasOverride = !!slotId && !!profile?.setlist_triggers[slotId];

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
            style={{ width: 220 }}
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

      <span style={{ width: 1, height: 20, background: 'var(--border)' }} />
      <button className={`chip filter ${modes.analysis ? 'active' : ''}`}
        title="Toggle audio capture/analysis"
        onClick={() => void post('/analysis/toggle', 'Capture toggle failed')}>
        Capture{modes.recaptureRemaining > 0 ? ` (${modes.recaptureRemaining})` : ''}
      </button>
      <button className={`chip filter ${modes.autoGen ? 'active' : ''}`}
        title="Auto-generate AI triggers for unseen songs"
        onClick={() => void post(`/control/auto-generate?enabled=${!modes.autoGen}`, 'Auto-gen toggle failed')}>
        Analyze
      </button>
      <button className={`chip filter ${modes.genreBlend ? 'active' : ''}`}
        title="Blend genre defaults into sparse profiles"
        onClick={() => void post('/genre-blending/toggle', 'Genre-blend toggle failed')}>
        Genre
      </button>
      <button className={`chip filter ${profile?.verified ? 'active' : ''}`}
        disabled={!profile}
        title="Mark this profile's timing as human-verified"
        onClick={() => mutateProfile((p) => { p.verified = !p.verified; })}>
        {profile?.verified ? '✓ Verified' : 'Verified'}
      </button>

      {SETLIST_SLOTS_ENABLED && (
        <>
          <span style={{ width: 1, height: 20, background: 'var(--border)' }} />
          <select
            value={slotId}
            onChange={(e) => setStickySlot(e.target.value)}
            title={slotHasOverride
              ? 'This slot has its own trigger list'
              : slotId ? 'Slot shows Default until first edit (then copies it)' : 'Editing the Default trigger list'}
            style={{ fontSize: 12, maxWidth: 150,
                     borderColor: slotHasOverride ? 'var(--accent)' : undefined }}
          >
            <option value="">Default</option>
            {(setlists ?? []).map((sl) => (
              <option key={sl.id} value={sl.id}>
                {sl.name}{profile?.setlist_triggers[sl.id] ? ' •' : ''}
              </option>
            ))}
          </select>
        </>
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
