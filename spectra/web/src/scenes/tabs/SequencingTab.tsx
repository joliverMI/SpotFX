/** Sequencing — as shipped in the sequencer increment. The GRAPHICAL half:
 * which likelihood curve the scene carries (named profile / inline / flat /
 * not sequenced) and the curve's shape. Relationships and durations (genre,
 * dwell, affinity) render read-only — adjusted by telling the agent.
 *
 * Curve window UX (his ask, verbatim): the tile grid stays collapsed on
 * open — clicking a tile is what expands the curve into an editable
 * "window" (a modal, not an inline expand — an inline expand is exactly
 * the shape that stretched the device-preview strip off his phone; a
 * modal's own maxWidth/maxHeight+scroll keeps it phone-safe by
 * construction). Tiles are a flat list keyed by curve id — grouping/tabs
 * later (his "in the future") is just a groupBy over this same list, no
 * new data model needed now.
 *
 * THE SAFETY RULE: dragging a point only ever writes to local `draft`
 * state — no code path in this file writes an edited point into
 * `curves[existingId]` except `SaveCurveDialog`'s own confirmed submit,
 * which itself refuses to reuse an existing name without the caller
 * having answered its overwrite-warning stage first. Every other write
 * (`applyOneOff`) targets this scene's own `inline_points` — never the
 * shared profile — so editing a shared curve is structurally incapable of
 * retuning any other scene's copy of it; only an explicit named save,
 * confirmed past a warning on a collision, can touch the shared store.
 */
import { useEffect, useState } from 'react';
import CurveEditor, { type CurvePoint } from '../../components/CurveEditor';
import CurveThumbnail from '../../components/CurveThumbnail';
import { useToast } from '../../components/Toast';
import HelpLink from '../../help/HelpLink';
import {
  useAttachCurve, useIntensityHistogram, useSaveCurves, useSequencerConfig,
  useSequencerCurves,
} from '../../queries';
import type { CurveProfile } from '../../queries';
import type { SceneV2 } from '../../types';

const FLAT: CurvePoint[] = [{ x: 0, y: 1 }];

function SaveCurveDialog({
  initialName, curves, usedBy, onCancel, onConfirm,
}: {
  initialName: string;
  curves: Record<string, CurveProfile>;
  usedBy: (profileId: string) => string[];
  onCancel: () => void;
  onConfirm: (name: string, overwriteId: string | null) => void;
}) {
  const [name, setName] = useState(initialName);
  const [pending, setPending] = useState<CurveProfile | null>(null);

  const submit = () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    const existing = Object.values(curves).find(
      (c) => c.name.trim().toLowerCase() === trimmed.toLowerCase());
    if (existing) setPending(existing);
    else onConfirm(trimmed, null);
  };

  return (
    <div onClick={onCancel}
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 110,
               display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}>
      <div className="card" onClick={(e) => e.stopPropagation()}
        style={{ width: 380, maxWidth: '92vw', margin: 0 }}>
        {!pending ? (
          <>
            <div className="card-title">Save as named curve</div>
            <label style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>
              Name
            </label>
            <input type="text" autoFocus value={name} onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') submit(); }}
              placeholder="e.g. High-energy ramp" style={{ width: '100%', marginBottom: 12 }} />
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button onClick={onCancel}>Cancel</button>
              <button className="primary" disabled={!name.trim()} onClick={submit}>Save</button>
            </div>
          </>
        ) : (
          <>
            <div className="card-title">Overwrite existing curve?</div>
            <p style={{ fontSize: 13, marginTop: -4 }}>
              A curve named <b>"{pending.name}"</b> already exists
              {usedBy(pending.id).length > 0
                ? <> — used by <b>{usedBy(pending.id).length}</b> other scene{usedBy(pending.id).length === 1 ? '' : 's'}: {usedBy(pending.id).join(', ')}</>
                : ''}. Saving will overwrite it for every scene using it.
            </p>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button onClick={() => setPending(null)}>Back</button>
              <button className="danger" onClick={() => onConfirm(name.trim(), pending.id)}>
                Overwrite
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default function SequencingTab({ scene, scenes }: {
  scene: SceneV2;
  scenes: SceneV2[];
}) {
  const toast = useToast();
  const { data: curves = {} } = useSequencerCurves();
  const { data: config } = useSequencerConfig();
  const { data: hist } = useIntensityHistogram();
  const attachMut = useAttachCurve();
  const saveCurvesMut = useSaveCurves();

  const entry = config?.entries?.[scene.id];
  const attachment: string = !entry ? 'none'
    : entry.curve_ref ? entry.curve_ref
    : entry.inline_points ? 'inline'
    : 'flat';
  const profile = entry?.curve_ref ? curves[entry.curve_ref] : undefined;

  // openId: which tile's curve window is expanded — null (collapsed grid
  // only) whenever this tab mounts or the scene changes, never derived
  // from the server's current attachment. draft: local, uncommitted edit
  // buffer — never written to `curves` by any path but the save dialog.
  const [openId, setOpenId] = useState<string | null>(null);
  const [draft, setDraft] = useState<CurvePoint[] | null>(null);
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);

  useEffect(() => {
    setOpenId(null);
    setDraft(null);
    setSaveDialogOpen(false);
  }, [scene.id]);

  const points = draft ?? (profile ? profile.points : entry?.inline_points ?? FLAT);

  const sceneName = (id: string) => scenes.find((s) => s.id === id)?.name ?? id;
  const usedBy = (profileId: string) =>
    Object.entries(config?.entries ?? {})
      .filter(([, e]) => e.curve_ref === profileId)
      .map(([sid]) => sceneName(sid));
  // For the overwrite-warning dialog: which OTHER scenes ride this
  // profile — this scene's own membership isn't the concern there.
  const otherUsers = (profileId: string) =>
    Object.entries(config?.entries ?? {})
      .filter(([sid, e]) => e.curve_ref === profileId && sid !== scene.id)
      .map(([sid]) => sceneName(sid));

  const attach = async (value: string): Promise<boolean> => {
    try {
      if (value === 'none') await attachMut.mutateAsync({ sceneId: scene.id, attachment: { kind: 'none' } });
      else if (value === 'flat') await attachMut.mutateAsync({ sceneId: scene.id, attachment: { kind: 'flat' } });
      else if (value === 'inline') {
        await attachMut.mutateAsync({
          sceneId: scene.id,
          attachment: { kind: 'inline', points: profile ? profile.points : points },
        });
      } else {
        await attachMut.mutateAsync({ sceneId: scene.id, attachment: { kind: 'profile', profileId: value } });
      }
      toast('Curve attachment saved', 'success');
      return true;
    } catch (e) {
      toast(`Attach failed: ${e}`, 'error');
      return false;
    }
  };

  // Click a tile: select it (persists the scene's attachment, as before)
  // and, for a curve that actually has a shape to show (a named profile or
  // the inline one-off), expand its window. Flat/none stay collapsed —
  // neither has a scene-owned shape of its own to edit yet.
  const selectTile = async (value: string) => {
    setDraft(null);
    const ok = await attach(value);
    if (!ok) return;
    setOpenId(value === 'inline' || curves[value] ? value : null);
  };

  const requestClose = () => {
    if (draft && !window.confirm('Discard unsaved edits to this curve?')) return;
    setOpenId(null);
    setDraft(null);
    setSaveDialogOpen(false);
  };

  // The ONLY write this makes is to THIS scene's own inline_points — never
  // to `curves`, so it can never retune another scene sharing a profile.
  const applyOneOff = async () => {
    const pts = draft ?? points;
    try {
      await attachMut.mutateAsync({ sceneId: scene.id, attachment: { kind: 'inline', points: pts } });
      setDraft(null);
      setOpenId('inline');
      toast('Applied as one-off — this scene only', 'success');
    } catch (e) {
      toast(`Apply failed: ${e}`, 'error');
    }
  };

  // The ONLY path in this file that can write into curves[existingId] —
  // and only after SaveCurveDialog's own overwrite-warning stage has been
  // explicitly confirmed by a collision (see its submit()).
  const saveNamed = async (name: string, overwriteId: string | null) => {
    const id = overwriteId ?? crypto.randomUUID();
    const pts = draft ?? points;
    try {
      await saveCurvesMut.mutateAsync({ ...curves, [id]: { id, name, points: pts } });
      await attach(id);
      setOpenId(id);
      setDraft(null);
      setSaveDialogOpen(false);
      toast(`Saved as "${name}"${overwriteId ? ' (overwritten)' : ''}`, 'success');
    } catch (e) {
      toast(`Save failed: ${e}`, 'error');
    }
  };

  const users = profile ? usedBy(profile.id) : [];
  const affinityEdges = (config?.affinity ?? []).filter(
    (e) => e.from_id === scene.id || e.to_id === scene.id);

  // Grid tiles: each one is either a fixed choice (none/flat/inline) or a
  // named shared profile, paired with the SAME points its curve editor
  // would draw — the thumbnail is the real shape, not a stand-in for the
  // name. Inline's tile previews what it would start from if picked right
  // now (mirrors attach()'s own seed: the currently-attached profile, or
  // the scene's current curve), since a not-yet-detached scene has no
  // fixed inline shape of its own yet.
  const tiles: { value: string; label: string; points: CurvePoint[] | null; badge?: string }[] = [
    { value: 'none', label: '— not sequenced —', points: null },
    { value: 'flat', label: 'Flat 1.0 (no curve)', points: FLAT },
    ...Object.values(curves)
      .sort((a, b) => a.name.localeCompare(b.name))
      .map((p) => {
        const n = usedBy(p.id).length;
        return { value: p.id, label: p.name, points: p.points, badge: n > 1 ? `${n} scenes` : undefined };
      }),
    { value: 'inline', label: 'Inline one-off…', points: profile ? profile.points : points },
  ];

  const windowOpen = openId !== null;
  const editing = draft !== null;
  const statusLine = editing
    ? 'Editing — one-off, not yet applied. Nothing shared is affected.'
    : profile
      ? `Shared profile "${profile.name}"${users.length > 1 ? ` — changes every scene using it (${users.join(', ')})` : ''}`
      : 'Inline one-off — this scene only';

  return (
    <div>
      <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        Sequencing <HelpLink topic="tab-sequencing" />
      </div>

      <div style={{ marginBottom: 6 }}>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>
          Likelihood curve — click a tile to open and edit it
        </div>
        <div style={{ maxHeight: 260, overflowY: 'auto', paddingRight: 4 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(112px, 1fr))', gap: 6 }}>
            {tiles.map((t) => (
              <button
                key={t.value}
                type="button"
                aria-label={t.label}
                aria-pressed={attachment === t.value}
                title={t.label}
                onClick={() => void selectTile(t.value)}
                style={{
                  display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 3,
                  padding: 5, borderRadius: 'var(--radius)', background: 'var(--surface2)',
                  border: attachment === t.value ? '2px solid var(--accent2)' : '1px solid var(--border)',
                  cursor: 'pointer',
                }}
              >
                {t.points ? <CurveThumbnail points={t.points} /> : (
                  <div style={{
                    width: 96, height: 48, display: 'flex', alignItems: 'center',
                    justifyContent: 'center', color: 'var(--text-muted)', fontSize: 16,
                  }}>—</div>
                )}
                <span style={{
                  fontSize: 11, textAlign: 'center', overflow: 'hidden',
                  textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 106,
                }}>{t.label}</span>
                {t.badge && <span style={{ fontSize: 9, color: 'var(--text-muted)' }}>{t.badge}</span>}
              </button>
            ))}
          </div>
        </div>
      </div>

      {attachment === 'none' && (
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6 }}>
          Not in the sequencer — attach a curve to make this scene a candidate
          when the sequencer rolls at song transitions.
        </div>
      )}
      {attachment === 'flat' && (
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6 }}>
          Eligible everywhere at weight 1.0. Pick a named profile (or an inline
          one-off) to shape it over intensity.
        </div>
      )}

      {windowOpen && (
        <div onClick={requestClose}
          style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 100,
                   display: 'flex', alignItems: 'flex-start', justifyContent: 'center', paddingTop: '8vh' }}>
          <div className="card" onClick={(e) => e.stopPropagation()}
            style={{ width: 560, maxWidth: '92vw', maxHeight: '86vh', overflowY: 'auto', margin: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
              <div className="card-title" style={{ margin: 0, flex: 1 }}>
                {profile ? profile.name : attachment === 'inline' ? 'Inline one-off' : 'Flat 1.0'}
              </div>
              <button style={{ fontSize: 11, padding: '2px 8px' }} onClick={requestClose}>✕ Close</button>
            </div>

            <CurveEditor points={points} onChange={setDraft} histogram={hist?.counts} />

            <div style={{ fontSize: 11, color: 'var(--text-muted)', margin: '6px 0 10px' }}>
              {statusLine}
            </div>

            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {(profile || editing) && (
                <button style={{ fontSize: 11, padding: '2px 8px' }}
                  title="Copy the current curve into this scene's own one-off — never touches the shared profile"
                  onClick={() => void applyOneOff()}>
                  {editing ? 'Apply edited one-off to this scene' : 'Detach — edit just this scene'}
                </button>
              )}
              {editing && (
                <button style={{ fontSize: 11, padding: '2px 8px' }} onClick={() => setDraft(null)}>
                  Discard edits
                </button>
              )}
              <span style={{ flex: 1 }} />
              <button className="primary" style={{ fontSize: 11, padding: '2px 10px' }}
                title="Save this curve under a name — creates a new shared profile, or overwrites an existing one after a warning"
                onClick={() => setSaveDialogOpen(true)}>
                Save as named curve…
              </button>
            </div>
          </div>
        </div>
      )}

      {saveDialogOpen && (
        <SaveCurveDialog
          initialName={profile?.name ?? ''}
          curves={curves}
          usedBy={otherUsers}
          onCancel={() => setSaveDialogOpen(false)}
          onConfirm={(name, overwriteId) => void saveNamed(name, overwriteId)}
        />
      )}

      {entry && (
        <div style={{ background: 'var(--surface2)', padding: 8, borderRadius: 'var(--radius)', marginTop: 8, fontSize: 11 }}>
          <div style={{ color: 'var(--text-muted)', marginBottom: 4 }}>
            Relationships & pace — read-only; adjust these by telling the agent.
          </div>
          <div>
            Dwell weight <b>{entry.dwell_weight}</b>
            {' '}(≈ {entry.dwell_weight} song{entry.dwell_weight === 1 ? '' : 's'} per stay)
            {Object.keys(entry.genre_mult).length > 0 && (
              <> · genre {Object.entries(entry.genre_mult)
                .map(([g, m]) => `${g} ×${m}`).join(', ')}</>
            )}
          </div>
          {affinityEdges.length > 0 && (
            <div style={{ marginTop: 2 }}>
              {affinityEdges.map((e, i) => (
                <div key={i}>
                  {sceneName(e.from_id)} → {sceneName(e.to_id)} ×{e.mult}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
