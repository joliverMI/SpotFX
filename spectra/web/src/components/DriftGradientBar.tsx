/** Top-bar control for the two-dimensional drift gradient (owner ask
 * 2026-08-20) — "click the preview, it expands, pick another saved one or
 * make a new one/edit the current one and save as new or overwrite,"
 * reusing the curve selector's own storage/picking SHAPE (see
 * spectra/services/gradient2d_store.py — same named-profile pattern as
 * spectra/services/drift_profiles.py) without reusing CurveAttachmentEditor
 * itself: a drift gradient has exactly ONE room-level attachment point
 * (RoomControlState.active_gradient_id), not a per-entry map, so the
 * "inline one-off vs shared profile" machinery that shape needs doesn't
 * apply here — editing is a local draft; Save writes it back to its own id
 * ("overwrite"), Save as new… forks a fresh id, matching his literal
 * "save as new or overwrite" wording as two plain buttons rather than a
 * detach/revert dance.
 *
 * Sits in the same grouped-button row as Mode/Ambient/Scenes
 * (RoomControlsBar.tsx), tap-to-open like Scenes (no cycle behaviour to
 * protect). Also carries the Rainbow select intensity limit — a small,
 * closely related setting with no other natural home in the top bar. */
import { useEffect, useState } from 'react';
import GradientEditor2D, { type XMode } from './GradientEditor2D';
import GradientSquarePreview from './GradientSquarePreview';
import TopBarGroupButton from './TopBarGroupButton';
import { useToast } from './Toast';
import { uuid } from '../lib/uid';
import {
  useGradient2dProfiles, useRoomControls, useSaveGradient2dProfiles, useSaveRoomControls,
} from '../queries';
import type { DriftGradientProfile } from '../queries';

const newProfile = (): DriftGradientProfile => ({
  id: uuid(), name: 'New Gradient', top: '#ffff00', bottom: '#0000ff', x_mode: 'loop',
});

export default function DriftGradientBar() {
  const toast = useToast();
  const { data: room } = useRoomControls();
  const { data: profiles = {} } = useGradient2dProfiles();
  const saveRoom = useSaveRoomControls();
  const saveProfiles = useSaveGradient2dProfiles();

  const [draft, setDraft] = useState<DriftGradientProfile | null>(null);

  const activeId = room?.active_gradient_id ?? null;
  const activeProfile = activeId ? profiles[activeId] : undefined;

  useEffect(() => {
    // Seed (or clear) the editing draft whenever the active gradient
    // changes underneath us — a fresh copy, never a live binding to the
    // library entry, so unsaved edits can't leak into other viewers.
    //
    // Guarded on the CURRENT draft's own id, not just re-run on every
    // activeId/activeProfile change: startNew() sets a brand-new,
    // not-yet-saved draft and only THEN activates its id (the comment on
    // startNew explains why — "not yet in the library, Save inserts it").
    // That activation round-trips through room-controls (PUT + refetch),
    // which fires this effect while profiles[activeId] is still
    // undefined — an unguarded reseed nulled the draft the instant the
    // PUT resolved, closing the editor out from under him before he could
    // touch it (his report: "the dialog closes automatically, I can not
    // do anything"). A draft already showing this exact id is always the
    // freshest copy (created here, or previously seeded from
    // activeProfile) — never re-derive over it.
    setDraft((prev) => (prev?.id === activeId
      ? prev
      : (activeProfile ? { ...activeProfile } : null)));
  }, [activeId, activeProfile]);

  const setActive = async (id: string | null) => {
    if (!room) return;
    try {
      await saveRoom.mutateAsync({ ...room, active_gradient_id: id });
    } catch (e) {
      toast(`Failed to set active gradient: ${e}`, 'error');
    }
  };

  const startNew = () => {
    const p = newProfile();
    setDraft(p);
    void setActive(p.id);   // not yet in the library — Save inserts it
  };

  const save = async (target: DriftGradientProfile, andActivate: boolean) => {
    try {
      await saveProfiles.mutateAsync({ ...profiles, [target.id]: target });
      if (andActivate) await setActive(target.id);
      toast(`Saved "${target.name}"`, 'success');
    } catch (e) {
      toast(`Save failed: ${e}`, 'error');
    }
  };

  const saveAsNew = async () => {
    if (!draft) return;
    const name = window.prompt('Save as new gradient, name:', `${draft.name} copy`);
    if (!name) return;
    const forked: DriftGradientProfile = { ...draft, id: uuid(), name };
    setDraft(forked);
    await save(forked, true);
  };

  const del = async () => {
    if (!draft || !profiles[draft.id]) return;
    if (!window.confirm(`Delete "${draft.name}"? This can't be undone.`)) return;
    const { [draft.id]: _removed, ...rest } = profiles;
    try {
      await saveProfiles.mutateAsync(rest);
      if (activeId === draft.id) await setActive(null);
      toast('Deleted', 'success');
    } catch (e) {
      toast(`Delete failed: ${e}`, 'error');
    }
  };

  const swatch = draft
    ? <GradientSquarePreview top={draft.top} bottom={draft.bottom} size={26} />
    : <div style={{ width: 26, height: 26, borderRadius: 4, border: '1px solid var(--border)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: 10, color: 'var(--text-muted)' }}>off</div>;

  return (
    <TopBarGroupButton
      holdToExpand={false}
      title="Drift gradient — the two-dimensional colour space the room drifts through"
      ariaLabel="Drift gradient"
      panelTitle="Drift gradient"
      panel={
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, width: 300 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(64px, 1fr))', gap: 6 }}>
            <button type="button" title="Off — the wheel-based colour journey drives the room"
              onClick={() => void setActive(null)}
              style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 3,
                       padding: 5, borderRadius: 'var(--radius)', background: 'var(--surface2)',
                       border: activeId === null ? '2px solid var(--accent2)' : '1px solid var(--border)' }}>
              <div style={{ width: 48, height: 48, display: 'flex', alignItems: 'center',
                           justifyContent: 'center', color: 'var(--text-muted)', fontSize: 16 }}>—</div>
              <span style={{ fontSize: 10 }}>Off</span>
            </button>
            {Object.values(profiles).sort((a, b) => a.name.localeCompare(b.name)).map((p) => (
              <button key={p.id} type="button" title={p.name}
                onClick={() => void setActive(p.id)}
                style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 3,
                         padding: 5, borderRadius: 'var(--radius)', background: 'var(--surface2)',
                         border: activeId === p.id ? '2px solid var(--accent2)' : '1px solid var(--border)' }}>
                <GradientSquarePreview top={p.top} bottom={p.bottom} size={48} />
                <span style={{ fontSize: 10, maxWidth: 60, overflow: 'hidden',
                              textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.name}</span>
              </button>
            ))}
            <button type="button" title="Make a new gradient" onClick={startNew}
              style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 3,
                       padding: 5, borderRadius: 'var(--radius)', background: 'var(--surface2)',
                       border: '1px dashed var(--border)' }}>
              <div style={{ width: 48, height: 48, display: 'flex', alignItems: 'center',
                           justifyContent: 'center', fontSize: 20 }}>+</div>
              <span style={{ fontSize: 10 }}>New…</span>
            </button>
          </div>

          {draft && (
            <div style={{ borderTop: '1px solid var(--border)', paddingTop: 8 }}>
              <input type="text" value={draft.name}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                style={{ width: '100%', fontSize: 12, marginBottom: 6 }} placeholder="Gradient name" />
              <GradientEditor2D
                top={draft.top} bottom={draft.bottom} xMode={draft.x_mode as XMode}
                onChangeTop={(v) => setDraft({ ...draft, top: v })}
                onChangeBottom={(v) => setDraft({ ...draft, bottom: v })}
                onChangeXMode={(v) => setDraft({ ...draft, x_mode: v })}
              />
              <div style={{ display: 'flex', gap: 6, marginTop: 8, flexWrap: 'wrap' }}>
                <button className="primary" style={{ fontSize: 11, padding: '2px 8px' }}
                  onClick={() => void save(draft, true)}>
                  {profiles[draft.id] ? 'Save (overwrite)' : 'Save'}
                </button>
                <button style={{ fontSize: 11, padding: '2px 8px' }} onClick={() => void saveAsNew()}>
                  Save as new…
                </button>
                {profiles[draft.id] && (
                  <button className="danger" style={{ fontSize: 11, padding: '2px 8px' }}
                    onClick={() => void del()}>✕ Delete</button>
                )}
              </div>
            </div>
          )}

          <div style={{ borderTop: '1px solid var(--border)', paddingTop: 8,
                       display: 'flex', alignItems: 'center', gap: 8 }}>
            <label style={{ fontSize: 11, color: 'var(--text-muted)', flex: 1 }}
              title="Above this intensity, colour-set selection is restricted to rainbow-marked sets only; at or below it, to single (non-rainbow) sets only.">
              Rainbow select limit
            </label>
            <input
              type="number" min={0} max={1} step={0.05}
              style={{ width: 60, fontSize: 12 }}
              value={room?.rainbow_select_limit ?? 0.9}
              onChange={(e) => {
                if (!room) return;
                const v = Math.max(0, Math.min(1, Number(e.target.value)));
                void saveRoom.mutateAsync({ ...room, rainbow_select_limit: v });
              }}
            />
          </div>
        </div>
      }
    >
      {swatch}
    </TopBarGroupButton>
  );
}
