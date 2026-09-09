/** /testbed — the music-analysis test bed (data/spotfx-music-analysis-plan/
 * report.md, Part 3: "the actual deliverable he asked for"). His real
 * marks, the waveform, and every candidate engine's detected marks on one
 * shared timeline, with precision/recall/F1 computed the same way the
 * report computes them — a comparison page, not an authoring one. Extends
 * the ported timeline surface family (ReviewPage's ReviewLaneBar pattern),
 * per SpotFX AGENTS.md's own "don't invent a parallel one" rule.
 *
 * The ONLY write this page can make is push-to-real, and only through
 * PromotionReviewDialog's own explicit confirm step (see that component
 * and spectra/services/testbed_promote.py). */
import { useEffect, useMemo, useState } from 'react';
import HelpLink from '../help/HelpLink';
import {
  useTestbedAudioPin, useTestbedAudioUnpin, useTestbedEngineMarks, useTestbedMarks,
  useTestbedPromotions, useTestbedSongs, useTestbedWaveform,
} from '../queries';
import type {
  TestbedEngineMarks, TestbedEstimateMark, TestbedMetrics, TestbedReferenceMark, TestbedSong,
} from '../types';
import PromotionReviewDialog from './components/PromotionReviewDialog';
import TestbedLaneBar from './components/TestbedLaneBar';
import TestbedMetricsPanel from './components/TestbedMetricsPanel';
import { matchMarks } from './metrics';

const ENGINE_MARK_KINDS: Record<string, { label: string; kinds: { key: string; label: string }[] }> = {
  librosa: {
    label: 'Current (librosa)',
    kinds: [
      { key: 'section_boundary', label: 'Section boundaries' },
      { key: 'beat', label: 'Beats' },
      { key: 'downbeat', label: 'Downbeats' },
    ],
  },
  beat_this: {
    label: 'beat_this (CPJKU 2024)',
    kinds: [
      { key: 'beat', label: 'Beats' },
      { key: 'downbeat', label: 'Downbeats' },
    ],
  },
};

/** Labels come off the /songs listing itself (title/artist read from the
 * editor-copy profile in the same one-pass scan that reads provenance) —
 * never a per-song profile query, which at his corpus size is ~850
 * simultaneous requests through the reverse proxy on first mount. */
function SongPickerButton({ song, active, onClick }: { song: TestbedSong; active: boolean; onClick: () => void }) {
  const label = song.title
    ? `${song.title}${song.artist ? ` — ${song.artist}` : ''}`
    : song.uri.split(':').pop()?.slice(0, 14) ?? song.uri;
  return (
    <button className={active ? 'primary' : ''} onClick={onClick} title={song.uri}>
      {label}
    </button>
  );
}

/** P/R/F1 + matched pairs for one engine lane against the active reference
 * set, computed locally with the byte-for-byte port of the server's
 * matcher — the indices in `matches` are into exactly these two arrays,
 * which is what the lanes' tinting reads. null = engine not computed, or
 * nothing of his to compare against (a 0% score over zero marks would be
 * a claim about the engine that the data cannot make). */
function localMetrics(
  engineMarks: TestbedEngineMarks | undefined,
  referenceMarks: TestbedReferenceMark[],
  toleranceMs: number,
): TestbedMetrics | null {
  if (!engineMarks?.available || referenceMarks.length === 0) return null;
  return matchMarks(
    referenceMarks.map((m) => m.timestamp_ms),
    engineMarks.estimate.map((m) => m.time_ms),
    toleranceMs,
  );
}

export default function TestbedPage() {
  const { data: songs } = useTestbedSongs();
  const [uri, setUri] = useState<string | null>(null);
  const [reference, setReference] = useState<'transitions' | 'flares'>('transitions');
  const [engineA, setEngineA] = useState<{ engine: string; kind: string }>({ engine: 'librosa', kind: 'section_boundary' });
  const [engineB, setEngineB] = useState<{ engine: string; kind: string } | null>(
    { engine: 'beat_this', kind: 'downbeat' },
  );
  const [toleranceMs, setToleranceMs] = useState(500);
  const [promoteTarget, setPromoteTarget] = useState<
    { timestampMs: number; sourceEngine: string; sourceMarkKind: string } | null
  >(null);

  useEffect(() => {
    if (uri !== null || !songs || songs.length === 0) return;
    setUri(songs[0].uri);
  }, [songs, uri]);

  const song = songs?.find((s) => s.uri === uri) ?? null;
  const { data: marks } = useTestbedMarks(uri);
  const { data: waveform } = useTestbedWaveform(uri);
  const { data: engineMarksA } = useTestbedEngineMarks(uri, engineA.engine, engineA.kind);
  const { data: engineMarksB } = useTestbedEngineMarks(
    uri, engineB?.engine ?? null, engineB?.kind ?? null,
  );
  const { data: promotions } = useTestbedPromotions(uri);

  const pin = useTestbedAudioPin();
  const unpin = useTestbedAudioUnpin();

  const referenceMarks = marks?.transitions ?? [];
  const flareMarks = marks?.flares ?? [];
  const activeReferenceMarks = reference === 'transitions' ? referenceMarks : flareMarks;
  const noAuthoredMarks = !!marks && referenceMarks.length === 0 && flareMarks.length === 0;
  const referenceEmptyNote = !marks ? undefined
    : noAuthoredMarks
      ? `no authored marks yet for this song${marks.n_generated ? ` — only ${marks.n_generated} machine-generated trigger${marks.n_generated === 1 ? '' : 's'}, which are never used as ground truth` : ''}`
      : activeReferenceMarks.length === 0
        ? `no authored ${reference} for this song`
        : undefined;
  const durationMs = useMemo(() => {
    const fromWaveform = waveform?.duration_ms ?? 0;
    const fromNpz = waveform?.timestamps_ms?.length
      ? waveform.timestamps_ms[waveform.timestamps_ms.length - 1] : 0;
    const fromMarks = Math.max(
      0,
      ...[...referenceMarks, ...flareMarks].map((m: TestbedReferenceMark) => m.timestamp_ms),
    );
    const fromEngines = Math.max(
      0,
      ...(engineMarksA?.estimate ?? []).map((m) => m.time_ms),
      ...(engineMarksB?.estimate ?? []).map((m) => m.time_ms),
    );
    return Math.max(fromWaveform, fromNpz, fromMarks * 1.05, fromEngines * 1.02, 1);
  }, [waveform, referenceMarks, flareMarks, engineMarksA, engineMarksB]);

  const metricsA = useMemo(
    () => localMetrics(engineMarksA, activeReferenceMarks, toleranceMs),
    [engineMarksA, activeReferenceMarks, toleranceMs],
  );
  const metricsB = useMemo(
    () => localMetrics(engineMarksB, activeReferenceMarks, toleranceMs),
    [engineMarksB, activeReferenceMarks, toleranceMs],
  );

  const engineLanes = [
    {
      key: 'a', label: ENGINE_MARK_KINDS[engineA.engine]?.label ?? engineA.engine,
      estimate: (engineMarksA?.estimate ?? []) as TestbedEstimateMark[],
      metrics: metricsA,
    },
    ...(engineB ? [{
      key: 'b', label: ENGINE_MARK_KINDS[engineB.engine]?.label ?? engineB.engine,
      estimate: (engineMarksB?.estimate ?? []) as TestbedEstimateMark[],
      metrics: metricsB,
    }] : []),
  ];

  return (
    <div>
      <div className="card">
        <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          Music-Analysis Test Bed <HelpLink topic="analysis-testbed" />
        </div>
        {!songs ? (
          <p className="empty-note">Loading…</p>
        ) : songs.length === 0 ? (
          <div className="empty-card">
            <span className="empty-card-icon">🎵</span>
            <div>
              <div className="empty-card-title">No songs with stored triggers yet</div>
              <p style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                Place at least one trigger on the Timeline page for a song to appear here.
              </p>
            </div>
          </div>
        ) : (
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {songs.map((s) => (
              <SongPickerButton key={s.uri} song={s} active={s.uri === uri} onClick={() => setUri(s.uri)} />
            ))}
          </div>
        )}
      </div>

      {uri && song && (
        <>
          <div className="card">
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, alignItems: 'flex-start' }}>
              <div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Ground-truth caveat</div>
                <div style={{ fontSize: 13 }}>
                  {marks?.provenance.found ? (
                    <>
                      {marks.provenance.ai_generated && <span className="badge-amber" style={{ marginRight: 6 }}>AI-assisted</span>}
                      {!marks.provenance.verified && <span className="badge-amber">unverified</span>}
                      {!marks.provenance.ai_generated && marks.provenance.verified && (
                        <span style={{ color: 'var(--ok)' }}>hand-placed, verified</span>
                      )}
                      <span style={{ color: 'var(--text-muted)', marginLeft: 8 }}>
                        (editor copy carries {marks.provenance.editor_trigger_count} triggers)
                      </span>
                    </>
                  ) : (
                    <span style={{ color: 'var(--text-muted)' }}>no editor-copy profile found for this song</span>
                  )}
                </div>
              </div>
              <div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 6 }}>
                  Retained audio <HelpLink topic="testbed-audio-retention" title="Pinning a song's audio" />
                </div>
                {song.audio.pinned ? (
                  <button onClick={() => unpin.mutate(uri)} disabled={unpin.isPending}>
                    ⛓ Pinned — unpin
                  </button>
                ) : (
                  <button
                    onClick={() => pin.mutate(uri)}
                    disabled={pin.isPending || !song.audio.has_source_wav}
                    title={song.audio.has_source_wav ? undefined
                      : 'No captured WAV to pin from right now — play/recapture the song first'}
                  >
                    {pin.isPending ? 'Pinning…' : 'Pin WAV for this song'}
                  </button>
                )}
              </div>
              <div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Reference set</div>
                <select value={reference} onChange={(e) => setReference(e.target.value as 'transitions' | 'flares')}>
                  <option value="transitions">Transitions ({song.n_transitions})</option>
                  <option value="flares">Flares ({song.n_flares})</option>
                </select>
              </div>
            </div>
          </div>

          <div className="card">
            <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              Engines (A/B) <HelpLink topic="testbed-engines" title="Engines" />
            </div>
            <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginBottom: 12 }}>
              <EnginePicker
                label="Engine A" value={engineA}
                onChange={(v) => { if (v) setEngineA(v); }}
                song={song}
              />
              <EnginePicker
                label="Engine B (optional)"
                value={engineB} onChange={setEngineB} song={song} clearable
              />
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
              Lanes <HelpLink topic="testbed-lanes-and-tolerance" title="Lanes, tinting, and the tolerance slider" />
            </div>
            <TestbedLaneBar
              durationMs={durationMs}
              waveform={waveform}
              transitions={referenceMarks}
              flares={flareMarks}
              reference={reference}
              referenceLabel={reference}
              referenceEmptyNote={referenceEmptyNote}
              engineLanes={engineLanes}
              toleranceMs={toleranceMs}
              onEstimateMarkClick={(engineKey, mark) => {
                const eng = engineKey === 'a' ? engineA : engineB;
                if (!eng) return;
                setPromoteTarget({
                  timestampMs: Math.round(mark.time_ms), sourceEngine: eng.engine, sourceMarkKind: eng.kind,
                });
              }}
            />
          </div>

          <div className="card">
            <div className="card-title">Metrics</div>
            <TestbedMetricsPanel
              rows={[
                { key: 'a', label: engineLanes[0].label, metrics: metricsA, available: !!engineMarksA?.available },
                ...(engineB ? [{ key: 'b', label: engineLanes[1]?.label ?? 'Engine B', metrics: metricsB, available: !!engineMarksB?.available }] : []),
              ]}
              toleranceMs={toleranceMs}
              onToleranceChange={setToleranceMs}
              emptyNote={referenceEmptyNote}
            />
          </div>

          {promotions && promotions.length > 0 && (
            <div className="card">
              <div className="card-title">Promotion history <HelpLink topic="testbed-promotion" title="What push-to-real does" /></div>
              <table className="testbed-metrics-table">
                <thead>
                  <tr><th>When</th><th>Engine</th><th>Kind</th><th>Status</th></tr>
                </thead>
                <tbody>
                  {promotions.slice().reverse().slice(0, 20).map((p, i) => (
                    <tr key={i}>
                      <td style={{ textAlign: 'left' }}>{new Date(p.at * 1000).toLocaleString()}</td>
                      <td>{p.source_engine}</td>
                      <td>{p.source_mark_kind}</td>
                      <td style={{ color: p.status === 'promoted' ? 'var(--ok)' : 'var(--danger)' }}>
                        {p.status}{p.reason ? ` (${p.reason})` : ''}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {promoteTarget && uri && (
        <PromotionReviewDialog
          uri={uri}
          timestampMs={promoteTarget.timestampMs}
          sourceEngine={promoteTarget.sourceEngine}
          sourceMarkKind={promoteTarget.sourceMarkKind}
          onClose={() => setPromoteTarget(null)}
        />
      )}
    </div>
  );
}

function EnginePicker({
  label, value, onChange, song, clearable,
}: {
  label: string;
  value: { engine: string; kind: string } | null;
  onChange: (v: { engine: string; kind: string } | null) => void;
  song: { engines: Record<string, { available: boolean }> };
  clearable?: boolean;
}) {
  return (
    <div>
      <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{label}</div>
      <select
        value={value ? `${value.engine}:${value.kind}` : ''}
        onChange={(e) => {
          if (!e.target.value) { onChange(null); return; }
          const [engine, kind] = e.target.value.split(':');
          onChange({ engine, kind });
        }}
      >
        {clearable && <option value="">— none —</option>}
        {Object.entries(ENGINE_MARK_KINDS).map(([engineKey, meta]) => (
          <optgroup key={engineKey} label={`${meta.label}${song.engines[engineKey]?.available ? '' : ' (not computed)'}`}>
            {meta.kinds.map((k) => (
              <option key={k.key} value={`${engineKey}:${k.key}`}>{k.label}</option>
            ))}
          </optgroup>
        ))}
      </select>
    </div>
  );
}
