/** Drift — the scene's declared slow mechanisms as readable cards, adjusted
 * by telling the agent. The one graphical piece is a follow map's curve (a
 * shape — the honest carve-out); creep cards are plain language. The colour
 * journey card lives here too: room-level walk by default, per-scene
 * OVERRIDE first-class, custody semantics stated on the card. When the S2
 * engine is running THIS scene, each card also shows its live legs. */
import { useState } from 'react';
import CurveEditor, { type CurvePoint } from '../../components/CurveEditor';
import HelpLink from '../../help/HelpLink';
import { useDriftProfiles, useEngineStatus, useRoomJourney, useSaveDriftProfiles } from '../../queries';
import { useToast } from '../../components/Toast';
import type { DriftRef, DriftSpec, SceneV2 } from '../../types';

function creepText(spec: DriftSpec): string {
  const dir = spec.motion === 'bounce' ? 'bouncing between' : 'wrapping through';
  return `wanders on its own at ~${spec.rate_per_min}/min, ${dir} ${spec.lo} and ${spec.hi}`;
}

export default function DriftTab({ scene, setScene }: {
  scene: SceneV2;
  setScene: (s: SceneV2) => void;
}) {
  const toast = useToast();
  const { data: room } = useRoomJourney();
  const { data: profiles = {} } = useDriftProfiles();
  const { data: engine } = useEngineStatus();
  const saveProfiles = useSaveDriftProfiles();
  const [draft, setDraft] = useState<{ key: string; points: CurvePoint[] } | null>(null);

  const engineActive = engine?.conductor.active_scene?.id === scene.id;
  const liveMechs = (param: string) =>
    engineActive
      ? (engine?.conductor.mechanisms ?? []).filter((m) => m.param === param)
      : [];

  const cards: { devIdx: number; entry: string; param: string; ref: DriftRef }[] = [];
  scene.devices.forEach((dev, devIdx) => {
    for (const [param, ref] of Object.entries(dev.drift ?? {})) {
      cards.push({ devIdx, entry: dev.target || 'All Devices', param, ref });
    }
  });

  const journey = scene.color_journey;
  const roomPace = room?.journey.degrees_per_min ?? 0;

  const setInlinePoints = (devIdx: number, param: string, points: CurvePoint[]) => {
    const devices = scene.devices.map((d, i) => {
      if (i !== devIdx) return d;
      const ref = d.drift[param];
      if (!ref?.inline) return d;
      return {
        ...d,
        drift: {
          ...d.drift,
          [param]: { ...ref, inline: { ...ref.inline, inline_points: points } },
        },
      };
    });
    setScene({ ...scene, devices });
  };

  const saveProfilePoints = async (profileId: string, points: CurvePoint[]) => {
    const p = profiles[profileId];
    if (!p) return;
    try {
      await saveProfiles.mutateAsync({
        ...profiles,
        [profileId]: { ...p, spec: { ...p.spec, inline_points: points, curve_ref: null } },
      });
      toast(`Profile "${p.name}" curve saved — every scene using it follows`, 'success');
    } catch (e) {
      toast(`Save failed: ${e}`, 'error');
    }
  };

  return (
    <div>
      {/* ── Colour journey ── */}
      <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        Colour journey <HelpLink topic="color-journey" />
      </div>
      <div style={{ background: 'var(--surface2)', padding: 12, borderRadius: 'var(--radius)', fontSize: 13, lineHeight: 1.6, marginBottom: 14 }}>
        {journey.mode === 'inherit' ? (
          <>
            <span className="badge badge-gray" style={{ marginRight: 8 }}>inherits the room</span>
            The room's palette always heads for a <b>destination</b> colour set (picked by the
            selector: curve × genre × wheel-travel) at a reference pace of <b>{roomPace}°/min</b>
            — the destination fixes its own travel speed from how far away it is, and on
            arrival the next destination is picked
            {journey.pace_factor !== 1 && (
              <> — this scene scales the pace <b>×{journey.pace_factor}</b>
                {journey.pace_factor === 0 && ' (holds the walk while it shows)'}</>
            )}.
          </>
        ) : (
          <>
            <span className="badge badge-purple" style={{ marginRight: 8 }}>OVERRIDE</span>
            While this scene shows, it steers the wheel itself — same destination model,
            but destinations are picked <b>within this scene's own palette bounds</b> (its
            accepted sets), at its own reference pace of{' '}
            <b>{Math.abs(journey.journey?.degrees_per_min ?? 0)}°/min</b>.
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 6 }}>
              Custody, not a fork: entering, this journey continues from wherever the room's
              walk had reached and picks its own destination; leaving, the room's own walk
              resumes from wherever this scene left the wheel. No snap in either direction.
            </div>
          </>
        )}
      </div>

      {/* ── Param drift cards ── */}
      <div className="card-title">Parameter drift</div>
      {!cards.length && (
        <div className="empty-note" style={{ marginBottom: 8 }}>
          No drift declared — every value holds still between fires. Tell the agent what
          should creep (bounded wander) or follow (track the music's energy arc), naming
          a shared profile or describing a one-off.
        </div>
      )}
      {cards.map(({ devIdx, entry, param, ref }) => {
        const spec = ref.inline ?? profiles[ref.profile ?? '']?.spec ?? null;
        const profileName = ref.profile ? profiles[ref.profile]?.name ?? ref.profile : null;
        const key = `${devIdx}:${param}`;
        const points = draft?.key === key ? draft.points
          : spec?.inline_points ?? [{ x: 0, y: spec?.lo ?? 0 }, { x: 1, y: spec?.hi ?? 1 }];
        return (
          <div key={key} style={{ background: 'var(--surface2)', padding: 10, borderRadius: 'var(--radius)', marginBottom: 8, fontSize: 13 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <b>{entry} · {param}</b>
              {profileName
                ? <span className="chip accent" title="A named profile — one edit retunes every scene using it">{profileName}</span>
                : <span className="chip">inline one-off</span>}
              {spec && <span className="badge badge-gray">{spec.kind}</span>}
              {liveMechs(param).map((m) => (
                <span key={m.virtual_id} className="chip accent"
                  title="The engine is running this leg now (recorded — dark against real lights until S3)">
                  ● {m.virtual_id}{m.kind === 'creep' && m.position != null
                    ? ` @ ${m.position.toFixed(3)}` : ''}
                </span>
              ))}
            </div>
            {spec?.kind === 'creep' && (
              <div style={{ color: 'var(--text-muted)', marginTop: 4 }}>{creepText(spec)}.</div>
            )}
            {spec?.kind === 'follow' && (
              <div style={{ marginTop: 4 }}>
                <div style={{ color: 'var(--text-muted)', marginBottom: 4 }}>
                  follows the music's energy arc through this map, gliding over ~{spec.slew_s}s:
                </div>
                <CurveEditor points={points} height={160}
                  onChange={(pts) => setDraft({ key, points: pts })} />
                {draft?.key === key && (
                  <span style={{ display: 'inline-flex', gap: 8 }}>
                    <button className="primary" style={{ fontSize: 11, padding: '2px 10px' }}
                      onClick={() => {
                        if (ref.inline) setInlinePoints(devIdx, param, draft.points);
                        else if (ref.profile) void saveProfilePoints(ref.profile, draft.points);
                        setDraft(null);
                      }}>
                      Save curve
                    </button>
                    <button style={{ fontSize: 11, padding: '2px 8px' }} onClick={() => setDraft(null)}>Discard</button>
                  </span>
                )}
              </div>
            )}
            {!spec && (
              <div style={{ color: 'var(--danger)', marginTop: 4 }}>
                names profile "{ref.profile}", which no longer exists — tell the agent.
              </div>
            )}
          </div>
        );
      })}
      <p style={{ fontSize: 11, color: 'var(--text-muted)' }}>
        The S2 engine executes these declarations — legs every {engine?.conductor.leg_s ?? 20}s,
        surges re-baselining drift, the journey walking the room's wheel. It runs
        DARK (computed and recorded, no light writes) until the S3 handover; the
        Engine strip on this page shows it live. Cards are adjusted by telling the
        agent — the curve above is the one graphical piece.
      </p>
    </div>
  );
}
