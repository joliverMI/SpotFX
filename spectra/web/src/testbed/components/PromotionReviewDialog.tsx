/** Push-to-real — the ONE write the music-analysis test bed can make
 * (data/spotfx-music-analysis-plan/report.md, "Two decisions" #2,
 * Admiral-approved 2026-09-09). This dialog IS the review step: it is the
 * only component wired to usePromoteToReal, and it only ever calls that
 * mutation with confirmed: true, from its own explicit "Confirm & push"
 * button — never from the click that opened it. See
 * spectra/services/testbed_promote.py's module docstring for the server
 * side of this gate.
 *
 * IT ALSO DISCLOSES THE CONSEQUENCE BEFORE HE PRESSES. Under scene-change
 * mode "My triggers only" the rule is PER SONG (spectra/services/
 * trigger_engine.py's _effective_mode_for_song): a song holding at least
 * one authored trigger fires ONLY authored triggers — its automatic
 * transition fire and every analysed mid-song change go quiet for that
 * song. So on a song with none yet, this one push does not ADD a mark, it
 * REPLACES the song's whole automatic show with it. That is said plainly
 * here. It is DISCLOSURE, never a gate: Confirm stays enabled, nothing
 * about room_controls or the firing rules is touched. */
import { useState } from 'react';
import HelpLink from '../../help/HelpLink';
import {
  useRoomControls, useScenes, useSpotColorSets, usePromoteToReal, useTestbedMarks,
} from '../../queries';
import { RESPONSE_CLASSES } from '../../types';
import type { ResponseClass, TriggerAction, TriggerActionKind } from '../../types';

const KIND_LABEL: Record<TriggerActionKind, string> = {
  fire_scene: 'Fire Scene', fire_response: 'Fire Response',
  select_color_set: 'Select Colours', fire_scene_update: 'Fire Update',
};

function blankAction(kind: TriggerActionKind): TriggerAction {
  if (kind === 'fire_scene') return { kind, scene_id: null, intensity: 0.5, color_set_id: null };
  if (kind === 'fire_response') return { kind, event_class: 'flare', intensity: 0.5 };
  if (kind === 'fire_scene_update') return { kind, intensity: 0.5 };
  return { kind, set_id: '' };
}

export default function PromotionReviewDialog({
  uri, timestampMs, sourceEngine, sourceMarkKind, onClose,
}: {
  uri: string;
  timestampMs: number;
  sourceEngine: string;
  sourceMarkKind: string;
  onClose: () => void;
}) {
  const { data: scenes } = useScenes();
  const { data: colorSets } = useSpotColorSets();
  const { data: roomControls } = useRoomControls();
  const { data: marks } = useTestbedMarks(uri);
  const promote = usePromoteToReal();

  // Every authored trigger, PROMOTED ONES INCLUDED — the trigger engine's
  // own per-song test counts them all; the scoring set's exclusion is a
  // different question and must not be borrowed here.
  const authoredCount = marks
    ? marks.transitions.length + marks.flares.length
    : null;
  const silencesTheSong = roomControls?.scene_change_mode === 'triggers_only'
    && authoredCount === 0;

  const [action, setAction] = useState<TriggerAction>(blankAction('fire_response'));
  const [offsetMs, setOffsetMs] = useState(0);

  const setKind = (kind: TriggerActionKind) => setAction(blankAction(kind));
  const confirmable = action.kind !== 'select_color_set' || !!action.set_id;

  const handleConfirm = () => {
    promote.mutate({
      uri, timestamp_ms: timestampMs, action,
      source_engine: sourceEngine, source_mark_kind: sourceMarkKind,
      trigger_offset_ms: offsetMs,
      confirmed: true,
    }, { onSuccess: onClose });
  };

  return (
    <div className="testbed-promote-dialog-backdrop" onClick={onClose}>
      <div className="testbed-promote-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="card-title" style={{ marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
          Push suggestion to your real triggers? <HelpLink topic="testbed-promotion" title="What push-to-real does" />
        </div>
        <div className="testbed-promote-dialog-warn">
          This writes a real, fireable trigger into your live show
          (storage/spectra/triggers.json) at the moment you confirm below —
          it never happens silently.
        </div>
        {silencesTheSong && (
          <div className="testbed-promote-dialog-consequence">
            <strong>This song has no triggers of your own yet.</strong> Scene
            changes are set to “My triggers only”, so the moment you push this
            one, this song plays <strong>only your own triggers — this one</strong>.
            Its automatic scene change and every analysed mid-song change stop
            for this song until you place more. Every other song is unaffected,
            and deleting this trigger puts the song back the way it is now.
          </div>
        )}
        <p style={{ fontSize: 13, color: 'var(--text-muted)' }}>
          Suggested by <strong>{sourceEngine}</strong> ({sourceMarkKind}) at{' '}
          <strong>{(timestampMs / 1000).toFixed(2)}s</strong>. Review and, if
          needed, adjust the action it will fire before confirming.
        </p>

        <div style={{ marginBottom: 8 }}>
          <label>Action kind</label>
          <select value={action.kind} onChange={(e) => setKind(e.target.value as TriggerActionKind)}>
            {(Object.keys(KIND_LABEL) as TriggerActionKind[]).map((k) => (
              <option key={k} value={k}>{KIND_LABEL[k]}</option>
            ))}
          </select>
        </div>

        {action.kind === 'fire_scene' && (
          <div style={{ marginBottom: 8 }}>
            <label>Scene (leave unset for automatic pick)</label>
            <select
              value={action.scene_id ?? ''}
              onChange={(e) => setAction({ ...action, scene_id: e.target.value || null })}
            >
              <option value="">— automatic —</option>
              {(scenes ?? []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
            <label>Intensity: {action.intensity.toFixed(2)}</label>
            <input type="range" min={0} max={1} step={0.01} value={action.intensity}
              onChange={(e) => setAction({ ...action, intensity: Number(e.target.value) })} />
          </div>
        )}

        {action.kind === 'fire_response' && (
          <div style={{ marginBottom: 8 }}>
            <label>Response class</label>
            <select
              value={action.event_class}
              onChange={(e) => setAction({ ...action, event_class: e.target.value as ResponseClass })}
            >
              {RESPONSE_CLASSES.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
            <label>Intensity: {action.intensity.toFixed(2)}</label>
            <input type="range" min={0} max={1} step={0.01} value={action.intensity}
              onChange={(e) => setAction({ ...action, intensity: Number(e.target.value) })} />
          </div>
        )}

        {action.kind === 'select_color_set' && (
          <div style={{ marginBottom: 8 }}>
            <label>Colour set</label>
            <select value={action.set_id} onChange={(e) => setAction({ ...action, set_id: e.target.value })}>
              <option value="">— choose —</option>
              {(colorSets ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </div>
        )}

        {action.kind === 'fire_scene_update' && (
          <div style={{ marginBottom: 8 }}>
            <label>Intensity: {action.intensity.toFixed(2)}</label>
            <input type="range" min={0} max={1} step={0.01} value={action.intensity}
              onChange={(e) => setAction({ ...action, intensity: Number(e.target.value) })} />
          </div>
        )}

        <div style={{ marginBottom: 12 }}>
          <label>Trigger offset (ms, negative = fire earlier)</label>
          <input type="number" value={offsetMs} min={-60000} max={60000}
            onChange={(e) => setOffsetMs(Number(e.target.value))} />
        </div>

        {promote.isError && (
          <p style={{ color: 'var(--danger)', fontSize: 12 }}>
            {(promote.error as Error).message}
          </p>
        )}

        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button onClick={onClose} disabled={promote.isPending}>Cancel</button>
          <button
            className="primary"
            onClick={handleConfirm}
            disabled={promote.isPending || !confirmable}
            title={confirmable ? undefined : 'Choose a colour set first'}
          >
            {promote.isPending ? 'Pushing…' : 'Confirm & push to real triggers'}
          </button>
        </div>
      </div>
    </div>
  );
}
