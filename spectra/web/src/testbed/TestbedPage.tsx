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
import { useEffect, useMemo, useRef, useState } from 'react';
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
import { filterAndSortSongs } from './songSearch';

/** Render cap for the song-picker list — a search narrows ~920 songs down
 * to a handful almost every time, but the box starts empty, so the
 * unfiltered list still needs a hard ceiling to stay fast. Not true
 * virtualization (this app carries no such dependency, and it doesn't
 * need one at this cap) — the count line says when the list is truncated. */
const SONG_LIST_CAP = 150;

/** Pretty labels for the mark kinds the registry emits — a DISPLAY lookup
 * only. Which engines exist, what they are called and which kinds each one
 * emits all come off the /songs payload (spectra/services/testbed_engines.py's
 * own ENGINES registry): a third engine registered server-side has to show
 * up in this picker without a frontend edit, which is the whole point of a
 * test bed. An unknown kind falls back to its raw key rather than
 * disappearing. */
const MARK_KIND_LABEL: Record<string, string> = {
  section_boundary: 'Section boundaries',
  beat: 'Beats',
  downbeat: 'Downbeats',
};

const markKindLabel = (kind: string) => MARK_KIND_LABEL[kind] ?? kind;

const TOLERANCE_MIN_MS = 100;
const TOLERANCE_MAX_MS = 3000;
/** Below half a beat, for beat/downbeat lanes — at 500ms (the old flat
 * default) the beat lane cannot lose on any song above 120 BPM and the
 * downbeat lane cannot tell a downbeat from the beat next to it
 * (data/music-analysis-octave-scout/report.md, "Work that should ship" #2:
 * El Apagón librosa downbeat F1 0.46 at 500ms vs 0.07 at 150ms, median
 * signed offset +470ms on a 499ms beat). Section boundaries are not a
 * beat-level phenomenon and keep the flat default. */
function laneDefaultToleranceMs(kind: string, tempoBpm: number | null): number {
  if (kind !== 'beat' && kind !== 'downbeat') return 500;
  if (!tempoBpm || tempoBpm <= 0) return 200;
  const beatMs = 60000 / tempoBpm;
  const raw = Math.min(200, Math.round(0.4 * beatMs));
  return Math.min(TOLERANCE_MAX_MS, Math.max(TOLERANCE_MIN_MS, raw));
}

/** The page has one shared tolerance slider across both A/B lanes (not a
 * control per lane), so its default is the TIGHTEST of the active lanes'
 * own defaults — a beat/downbeat lane picked for either slot must never
 * be scored at a default too loose to tell its phase, even when the other
 * slot is a section-boundary lane. */
function effectiveDefaultToleranceMs(kinds: string[], tempoBpm: number | null): number {
  if (kinds.length === 0) return 500;
  return Math.min(...kinds.map((k) => laneDefaultToleranceMs(k, tempoBpm)));
}

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
  scoredMarks: TestbedReferenceMark[],
  toleranceMs: number,
): TestbedMetrics | null {
  if (!engineMarks?.available || scoredMarks.length === 0) return null;
  return matchMarks(
    scoredMarks.map((m) => m.timestamp_ms),
    engineMarks.estimate.map((m) => m.time_ms),
    toleranceMs,
  );
}

export default function TestbedPage() {
  const { data: songs } = useTestbedSongs();
  // Page-local only, per his ask ("no server change") — resets on reload.
  const [songQuery, setSongQuery] = useState('');
  const [uri, setUri] = useState<string | null>(null);
  const [reference, setReference] = useState<'transitions' | 'flares'>('transitions');
  const [engineA, setEngineA] = useState<{ engine: string; kind: string }>({ engine: 'librosa', kind: 'section_boundary' });
  const [engineB, setEngineB] = useState<{ engine: string; kind: string } | null>(
    { engine: 'beat_this', kind: 'downbeat' },
  );
  const [toleranceMs, setToleranceMs] = useState(500);
  // True once he has touched the slider himself for the CURRENT song — the
  // default below stops re-asserting itself over his own choice, but a new
  // song (or a mark-kind change on either lane) still gets its own honest
  // default rather than carrying over a value tuned for a different beat
  // length.
  const [toleranceTouched, setToleranceTouched] = useState(false);
  const lastUriRef = useRef<string | null>(null);
  const [promoteTarget, setPromoteTarget] = useState<
    { timestampMs: number; sourceEngine: string; sourceMarkKind: string } | null
  >(null);

  useEffect(() => {
    if (uri !== null || !songs || songs.length === 0) return;
    setUri(songs[0].uri);
  }, [songs, uri]);

  const song = songs?.find((s) => s.uri === uri) ?? null;
  const visibleSongs = useMemo(
    () => filterAndSortSongs(songs ?? [], songQuery),
    [songs, songQuery],
  );
  const shownSongs = useMemo(() => visibleSongs.slice(0, SONG_LIST_CAP), [visibleSongs]);
  const { data: marks } = useTestbedMarks(uri);
  const { data: waveform } = useTestbedWaveform(uri);
  const { data: engineMarksA } = useTestbedEngineMarks(uri, engineA.engine, engineA.kind);
  const { data: engineMarksB } = useTestbedEngineMarks(
    uri, engineB?.engine ?? null, engineB?.kind ?? null,
  );
  const { data: promotions } = useTestbedPromotions(uri);

  const pin = useTestbedAudioPin();
  const unpin = useTestbedAudioUnpin();

  // A new song resets to ITS OWN honest default rather than carrying over
  // one tuned for a different beat length.
  useEffect(() => {
    if (lastUriRef.current === uri) return;
    lastUriRef.current = uri;
    setToleranceTouched(false);
  }, [uri]);

  const activeMarkKinds = useMemo(
    () => (engineB ? [engineA.kind, engineB.kind] : [engineA.kind]),
    [engineA.kind, engineB],
  );
  const defaultToleranceMs = useMemo(
    () => effectiveDefaultToleranceMs(activeMarkKinds, marks?.tempo_bpm ?? null),
    [activeMarkKinds, marks?.tempo_bpm],
  );
  // Keep tracking the default (a new engine/kind pick, a song's tempo
  // arriving) until he actually moves the slider for this song.
  useEffect(() => {
    if (!toleranceTouched) setToleranceMs(defaultToleranceMs);
  }, [defaultToleranceMs, toleranceTouched]);

  const referenceMarks = marks?.transitions ?? [];
  const flareMarks = marks?.flares ?? [];
  const activeReferenceMarks = reference === 'transitions' ? referenceMarks : flareMarks;
  /** The scoring set: his own marks minus every one this page pushed. Same
   * rule the server applies (spectra/services/testbed_marks.scoring_marks) —
   * a promoted mark sits at the suggesting engine's exact time and would
   * grade that engine on its own suggestion. They stay in the lane, drawn
   * and labelled; only the number leaves them out. */
  const scoredMarks = useMemo(
    () => activeReferenceMarks.filter((m) => !m.promoted),
    [activeReferenceMarks],
  );
  const nPromotedActive = activeReferenceMarks.length - scoredMarks.length;
  const noAuthoredMarks = !!marks && referenceMarks.length === 0 && flareMarks.length === 0;
  const referenceEmptyNote = !marks ? undefined
    : noAuthoredMarks
      ? `no authored marks yet for this song${marks.n_generated ? ` — only ${marks.n_generated} machine-generated trigger${marks.n_generated === 1 ? '' : 's'}, which are never used as ground truth` : ''}`
      : activeReferenceMarks.length === 0
        ? `no authored ${reference} for this song`
        : scoredMarks.length === 0
          ? `every authored ${reference} for this song was pushed from this page — nothing left to score an engine against`
          : undefined;
  /** ONE timebase for every lane, and it is a REAL duration wherever the
   * song has one (the pinned WAV, else the coarse npz envelope). Padding a
   * mark-derived fallback would put a duration on the axis label that the
   * song does not have; a mark or beat past a short capture still widens
   * it, so nothing is ever clamped out of view. */
  const durationMs = useMemo(() => {
    // A pinned WAV's own duration is its LENGTH; it ends at
    // capture_offset_ms + length in SONG time (a capture starts mid-song).
    const fromWaveform = (waveform?.duration_ms ?? 0) > 0
      ? (waveform?.capture_offset_ms ?? 0) + (waveform?.duration_ms ?? 0)
      : 0;
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
    return Math.max(fromWaveform, fromNpz, fromMarks, fromEngines, 1);
  }, [waveform, referenceMarks, flareMarks, engineMarksA, engineMarksB]);

  const metricsA = useMemo(
    () => localMetrics(engineMarksA, scoredMarks, toleranceMs),
    [engineMarksA, scoredMarks, toleranceMs],
  );
  const metricsB = useMemo(
    () => localMetrics(engineMarksB, scoredMarks, toleranceMs),
    [engineMarksB, scoredMarks, toleranceMs],
  );

  const engineLabel = (key: string) => song?.engines[key]?.label ?? key;
  const engineLanes = [
    {
      key: 'a', label: engineLabel(engineA.engine),
      estimate: (engineMarksA?.estimate ?? []) as TestbedEstimateMark[],
      metrics: metricsA,
    },
    ...(engineB ? [{
      key: 'b', label: engineLabel(engineB.engine),
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
          <>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
              Search <HelpLink topic="testbed-song-search" title="Searching the song list" />
            </div>
            <div className="testbed-song-search-row">
              <input
                type="search"
                className="testbed-song-search-input"
                value={songQuery}
                onChange={(e) => setSongQuery(e.target.value)}
                placeholder="Search by artist or title…"
                aria-label="Search songs"
              />
              {songQuery && (
                <button
                  type="button"
                  onClick={() => setSongQuery('')}
                  title="Clear search"
                  aria-label="Clear search"
                >
                  ✕
                </button>
              )}
            </div>
            <div className="testbed-song-search-count">
              {visibleSongs.length} of {songs.length}
              {shownSongs.length < visibleSongs.length
                ? ` — showing first ${shownSongs.length}, narrow your search to see the rest`
                : ''}
            </div>
            {visibleSongs.length === 0 ? (
              <p className="empty-note">No songs match “{songQuery}”.</p>
            ) : (
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {shownSongs.map((s) => (
                  <SongPickerButton key={s.uri} song={s} active={s.uri === uri} onClick={() => setUri(s.uri)} />
                ))}
              </div>
            )}
          </>
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
              {song.n_generated > 0 && (
                <div>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 6 }}>
                    Generated cues (beat-snap) <HelpLink topic="midsong-snap-to-beat" title="Snap generated cues to beat" />
                  </div>
                  <div style={{ fontSize: 13 }}>
                    {song.n_snapped} of {song.n_generated} snapped
                    {Object.keys(song.snap_grid_counts).length > 0 && (
                      <span style={{ color: 'var(--text-muted)', marginLeft: 6 }}>
                        ({Object.entries(song.snap_grid_counts).map(([g, n]) => `${g}: ${n}`).join(', ')})
                      </span>
                    )}
                    {song.n_unsnapped_generated > 0 && (
                      <span style={{ color: 'var(--text-muted)', marginLeft: 6 }}>
                        · {song.n_unsnapped_generated} unsnapped
                      </span>
                    )}
                  </div>
                </div>
              )}
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
              scoredMarks={scoredMarks}
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
            {nPromotedActive > 0 && (
              <p className="empty-note" style={{ fontSize: 12, marginTop: 0 }}>
                {nPromotedActive} of these {reference} were pushed to your real
                triggers from this page — shown in the lane, but left out of the
                scores below, since they sit exactly where the engine put them.
              </p>
            )}
            <TestbedMetricsPanel
              rows={[
                { key: 'a', label: engineLanes[0].label, metrics: metricsA, available: !!engineMarksA?.available },
                ...(engineB ? [{ key: 'b', label: engineLanes[1]?.label ?? 'Engine B', metrics: metricsB, available: !!engineMarksB?.available }] : []),
              ]}
              toleranceMs={toleranceMs}
              onToleranceChange={(ms) => { setToleranceTouched(true); setToleranceMs(ms); }}
              defaultToleranceMs={defaultToleranceMs}
              onResetToDefault={() => { setToleranceTouched(false); setToleranceMs(defaultToleranceMs); }}
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
  song: TestbedSong;
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
        {Object.entries(song.engines).map(([engineKey, meta]) => (
          <optgroup key={engineKey} label={`${meta.label}${meta.available ? '' : ' (not computed)'}`}>
            {meta.kinds.map((kind) => (
              <option key={kind} value={`${engineKey}:${kind}`}>{markKindLabel(kind)}</option>
            ))}
          </optgroup>
        ))}
      </select>
    </div>
  );
}
