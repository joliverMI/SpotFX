/** Colour Sets — the scene's two-way set filter with TYPE-TO-FILTER search.
 * Accept-all vs an explicit per-set list (groups expand to members — the
 * API enforces it); wheel dot / 🌈 per set; the global opt-out lives on the
 * shared colour library (spot-effects surface) behind a confirm. The filter
 * never drops contents it didn't display. */
import { useMemo, useState } from 'react';
import HelpLink from '../../help/HelpLink';
import ColorSetPreferenceToggle from '../../components/ColorSetPreferenceToggle';
import { useToast } from '../../components/Toast';
import { useSpotColorSets, useToggleSetOptOut, useWheelPositions } from '../../queries';
import type { SceneV2 } from '../../types';

const MARK_ICON: Record<string, string> = { dark: '☾', light: '☀' };
const MARK_TITLE: Record<string, string> = {
  dark: 'This set is marked Dark (ColorSetsPage → Colours)',
  light: 'This set is marked Light (ColorSetsPage → Colours)',
};

export default function ColorSetsTab({ scene, setScene }: {
  scene: SceneV2;
  setScene: (s: SceneV2) => void;
}) {
  const toast = useToast();
  const { data: cards = [] } = useSpotColorSets();
  const { data: wheel = {} } = useWheelPositions();
  const optOutMut = useToggleSetOptOut();
  const [filter, setFilter] = useState('');

  const sets = useMemo(() => cards.filter((c) => c.kind === 'set'), [cards]);
  const visible = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return sets;
    return sets.filter((c) => c.name.toLowerCase().includes(q));
  }, [sets, filter]);

  const acceptedCount = scene.accept_all_sets
    ? sets.filter((c) => !c.scene_v2_opt_out).length
    : scene.accepted_set_ids.filter((id) => {
        const c = sets.find((s) => s.id === id);
        return c && !c.scene_v2_opt_out;
      }).length;

  const toggleAccepted = (setId: string) => {
    const has = scene.accepted_set_ids.includes(setId);
    setScene({
      ...scene,
      accepted_set_ids: has
        ? scene.accepted_set_ids.filter((x) => x !== setId)
        : [...scene.accepted_set_ids, setId],
    });
  };

  const toggleGlobalOptOut = async (setId: string) => {
    const card = cards.find((c) => c.id === setId);
    if (!card) return;
    // This confirm STAYS — deliberate asymmetry with the confirm-free Fire
    // button (owner's order, 2026-08-13): opting out silently changes every
    // scene in the house; a fire touches only the scene he is looking at.
    if (!card.scene_v2_opt_out && !confirm(
      `Opt "${card.name}" out of ALL scenes?\n\nThis is global — every scene (SPECTRA and legacy) stops accepting this set until it is re-enabled.`)) return;
    try {
      await optOutMut.mutateAsync(card);
      toast(card.scene_v2_opt_out ? 'Set re-enabled for scenes' : 'Set opted out of all scenes', 'success');
    } catch (e) {
      toast(`Update failed: ${e}`, 'error');
    }
  };

  return (
    <div>
      <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        Colour Set filter <HelpLink topic="tab-color-sets" />
        <span className="chip accent">{acceptedCount} accepted</span>
      </div>
      <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12, cursor: 'pointer', marginBottom: 6 }}>
        <input type="checkbox" checked={scene.accept_all_sets}
          onChange={(e) => setScene({ ...scene, accept_all_sets: e.target.checked })} />
        Accept every Colour Set (that hasn't opted out globally)
      </label>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, marginBottom: 8 }}>
        <span style={{ color: 'var(--text-muted)' }}>Prefers</span>
        <ColorSetPreferenceToggle value={scene.preferred_color_set_mode ?? 'default'}
          onChange={(v) => setScene({ ...scene, preferred_color_set_mode: v })} />
        <HelpLink topic="scene-colorset-preference" />
      </div>
      <input type="search" placeholder="Type to filter sets…" value={filter}
        style={{ width: '100%', marginBottom: 6 }}
        onChange={(e) => setFilter(e.target.value)} />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2, maxHeight: 420, overflowY: 'auto' }}>
        {visible.map((c) => {
          const w = wheel[c.id];
          const optedOut = !!c.scene_v2_opt_out;
          const checked = scene.accept_all_sets || scene.accepted_set_ids.includes(c.id);
          return (
            <div key={c.id} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, padding: '2px 4px', opacity: optedOut ? 0.5 : 1 }}>
              <input type="checkbox" checked={checked && !optedOut}
                disabled={scene.accept_all_sets || optedOut}
                title={optedOut ? 'Opted out of all scenes' : undefined}
                onChange={() => toggleAccepted(c.id)} />
              <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c.name}</span>
              {c.display_availability && MARK_ICON[c.display_availability] && (
                <span title={MARK_TITLE[c.display_availability]}>{MARK_ICON[c.display_availability]}</span>
              )}
              {w?.rainbow && <span title={`Rainbow set — hues span ${w.span_deg}°, no single wheel position (never moves the room's wheel)`}>🌈</span>}
              {w && !w.rainbow && w.position_deg != null && (
                <span title={`Wheel position ${w.position_deg}° (span ${w.span_deg}°, R=${w.resultant})`}
                  style={{
                    width: 14, height: 14, borderRadius: '50%', flexShrink: 0,
                    border: '1px solid var(--border)',
                    background: `hsl(${w.position_deg}, 85%, 55%)`,
                  }} />
              )}
              <button style={{ fontSize: 10, padding: '1px 6px' }}
                title={optedOut
                  ? 'This set has opted out of ALL scenes — click to re-enable'
                  : 'Opt this set out of ALL scenes (global, affects every scene)'}
                onClick={() => void toggleGlobalOptOut(c.id)}>
                {optedOut ? '🚫 opted out' : 'opt out'}
              </button>
            </div>
          );
        })}
        {!visible.length && (
          <div className="empty-note">No sets match “{filter}”.</div>
        )}
      </div>
    </div>
  );
}
