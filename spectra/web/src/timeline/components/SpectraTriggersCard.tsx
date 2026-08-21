/** THE KEYSTONE's authoring surface: SPECTRA-native triggers for the
 * currently-loaded song, placed/moved/edited/deleted directly on the ported
 * timeline. Self-contained — its own data hooks and dialog state, no
 * coupling to the legacy MusicTrigger/SongProfile store (the two worlds
 * coexist; this card only ever touches spectra/api/triggers.py). */
import { useState } from 'react';
import CollapsibleCard from '../../components/CollapsibleCard';
import HelpLink from '../../help/HelpLink';
import { useToast } from '../../components/Toast';
import {
  useDeleteSpectraTrigger, useGenerateMidsongTriggers, useSaveSpectraTrigger,
  useScenes, useSpectraTriggers,
} from '../../queries';
import { newTrigger } from '../../types';
import type { SpectraTrigger } from '../../types';
import type { Win } from '../canvas/frame';
import SpectraTriggerBar from './SpectraTriggerBar';
import SpectraTriggerDialog from './SpectraTriggerDialog';

export default function SpectraTriggersCard({
  uri,
  durationMs,
  getWin,
  getNowMs,
}: {
  uri: string | null;
  durationMs: number;
  getWin: () => Win;
  getNowMs: () => number | null;
}) {
  const { data: triggers } = useSpectraTriggers(uri);
  const { data: scenes } = useScenes();
  const saveMutation = useSaveSpectraTrigger(uri);
  const deleteMutation = useDeleteSpectraTrigger(uri);
  const generateMutation = useGenerateMidsongTriggers(uri);
  const toast = useToast();
  const [editing, setEditing] = useState<{ trigger: SpectraTrigger; isNew: boolean } | null>(null);

  if (!uri) return null;

  const list = triggers ?? [];
  const sceneName = (id: string) => scenes?.find((s) => s.id === id)?.name ?? id;

  return (
    <CollapsibleCard
      id="spectra-triggers"
      title="SPECTRA Triggers"
      headerExtra={
        <span style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 12 }}>
          <span style={{ color: 'var(--text-muted)' }}>{list.length} placed</span>
          <button style={{ fontSize: 12 }}
            title="Add a SPECTRA trigger at the current playhead"
            onClick={() => {
              const now = getNowMs() ?? 0;
              setEditing({ trigger: newTrigger(now), isNew: true });
            }}>
            + Add Trigger
          </button>
          <HelpLink topic="spectra-trigger-authoring" title="Placing & editing" />
          <button style={{ fontSize: 12 }}
            title="Seed/refresh mid-song triggers from this song's analysis — idempotent, never touches a trigger you've edited or placed by hand"
            disabled={generateMutation.isPending}
            onClick={() => generateMutation.mutate(undefined, {
              onSuccess: (summary) => toast(
                `Generated: +${summary.added} seeded, ${summary.updated} updated, `
                + `${summary.deleted} removed (stale), ${summary.skipped_authored} of yours left alone`,
                'info'),
              onError: (e) => toast(`Generate failed: ${(e as Error).message}`, 'error'),
            })}>
            {generateMutation.isPending ? 'Generating…' : '⟳ Generate'}
          </button>
          <HelpLink topic="spectra-trigger-generate" title="Generating from analysis" />
          <HelpLink topic="spectra-triggers" title="SPECTRA trigger authoring" />
        </span>
      }
    >
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', fontSize: 11, color: 'var(--text-muted)', marginBottom: 2 }}>
        <span>Marker colours <HelpLink topic="spectra-trigger-colours" title="Marker colours" /></span>
        <span>Fires on the xcorr-synced clock <HelpLink topic="spectra-trigger-sync" title="When a trigger actually fires" /></span>
      </div>
      <SpectraTriggerBar
        durationMs={durationMs}
        triggers={list}
        sceneName={sceneName}
        getWin={getWin}
        getNowMs={getNowMs}
        onEdit={(id) => {
          const t = list.find((tt) => tt.id === id);
          if (t) setEditing({ trigger: t, isNew: false });
        }}
        onMove={(id, ms) => {
          const t = list.find((tt) => tt.id === id);
          if (t) saveMutation.mutate({ ...t, timestamp_ms: ms },
            { onError: (e) => toast(`Move failed: ${(e as Error).message}`, 'error') });
        }}
        onDelete={(id) => deleteMutation.mutate(id, {
          onError: (e) => toast(`Delete failed: ${(e as Error).message}`, 'error'),
        })}
        onCreate={(ms) => setEditing({ trigger: newTrigger(ms), isNew: true })}
      />
      <SpectraTriggerDialog
        trigger={editing?.trigger ?? null}
        isNew={editing?.isNew ?? false}
        uri={uri}
        onClose={() => setEditing(null)}
      />
    </CollapsibleCard>
  );
}
