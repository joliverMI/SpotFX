/** THE JUKEBOX (/jukebox, Engine ▾ Jukebox) — the master view of the host's
 * set list with jukebox slots (data/jukebox-plan/report.md §5, phase 1 PR
 * 1.3). The engine is SpotFX's services/jukebox/night.py, reached
 * same-origin through its own /api/jukebox routes; SPECTRA's backend is not
 * involved.
 *
 * FOUR TABS:
 *   Set list  the editor: link the set playlist, choose where the jukebox
 *             slots go (Auto · Jukebox first · Manual), what happens when
 *             the set runs out; the program bar for one pass; the set
 *             itself, draggable (writes the playlist order to Spotify — only
 *             two or more ahead of the playing song during a night), with
 *             each song's slots after it. In Manual, click a set song for a
 *             slot after it, a slot for another right after it, × to remove.
 *   Live      the night, what is playing, the next 20 program items with
 *             when they start, the jukebox line, the log — read-only except
 *             for the line itself, which drags to reorder the same way the
 *             Guests tab's own line does (§7.2: both host views carry it).
 *   Credits   the party-size presets, the price check, and every credits
 *             setting (CreditsTab.tsx, phase 3.3).
 *   Simulate  the party simulator: a model night under the saved settings,
 *             played back in five minutes, beside the tuned settings
 *             (SimulateTab.tsx, phase 3.4).
 * Above both: the Spotify sign-in line (PR 1.2) when a warning is due —
 * every night stops if the sign-in lapses.
 *
 * The floating 💬 Sonic (spectra/services/jukebox_console.py) is the same
 * chat as everywhere, scoped by its help topic to `sonic-jukebox`; it
 * reaches these very routes and asks before every change.
 *
 * Every sentence is decided in jukeboxEditor.ts; WHERE the slots are is the
 * server's projection (`lap_items`), never re-derived here. No visible help
 * circle: each card's title explains itself on hover / long-press and
 * carries its own topic; the menu row's "?" opens `jukebox`. */
import { useState } from 'react';
import Icon from '../components/Icon';
import InfoTip from '../components/InfoTip';
import SonicChatPopover from '../components/SonicChatPopover';
import { useToast } from '../components/Toast';
import SortableList from '../lightshow/SortableList';
import CreditsTab from './CreditsTab';
import GuestsTab from './GuestsTab';
import JukeboxLine from './JukeboxLine';
import SimulateTab from './SimulateTab';
import {
  activityLine, creditsLine, eventWords, freePlayLine, liveLineWords, priceRows, roomLine,
} from './jukeboxEconomy';
import { compareCells, creditFacts, endLine, nightFacts } from './jukeboxReport';
import {
  barSegments, canMove, clickSetSong, clickSlot, countLine, GUEST_COUNTS, itemView,
  mmss, MODE_LABEL, nightLine, nightWarnings, nowLine, removeSlot, ruleLine, RUN_OUT_LABEL,
  signInView, slotsAfter, slotsByIndex, startsIn,
} from './jukeboxEditor';
import {
  useGuests, useJukeboxConfig, useJukeboxEconomy, useJukeboxPreview, useJukeboxReport, useJukeboxStatus,
  useMoveEntry, useMoveSetSong, useReloadSet, useSaveJukeboxConfig,
} from './queries';
import type { JukeboxPreview, JukeboxStatus, ProgramConfig, RunOut, SetItem, SlotMode } from './types';

function errText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export default function JukeboxPage() {
  const [tab, setTab] = useState<'set' | 'live' | 'guests' | 'credits' | 'simulate'>('set');
  const cfgQ = useJukeboxConfig();
  const statusQ = useJukeboxStatus();
  const cfg = cfgQ.data ?? null;
  const status = statusQ.data;
  const linked = !!cfg?.playlist?.trim();
  const previewQ = useJukeboxPreview(linked);
  const sign = signInView(status?.spotify_auth);

  return (
    <div className="jukebox-page">
      <div className="jukebox-head">
        <InfoTip topic="jukebox"
          text="Your set playlist plays as Spotify's own context; jukebox slots between set songs are filled just in time from the jukebox line. Spotify never sees a slot.">
          <h2 className="jukebox-title"><Icon name="note" size={20} /> Jukebox</h2>
        </InfoTip>
        <div className="jukebox-tabs" role="tablist" aria-label="Jukebox views">
          <button role="tab" aria-selected={tab === 'set'} className={tab === 'set' ? 'on' : ''}
            onClick={() => setTab('set')}>Set list</button>
          <button role="tab" aria-selected={tab === 'live'} className={tab === 'live' ? 'on' : ''}
            onClick={() => setTab('live')}>Live</button>
          <button role="tab" aria-selected={tab === 'guests'} className={tab === 'guests' ? 'on' : ''}
            onClick={() => setTab('guests')}>Guests</button>
          <button role="tab" aria-selected={tab === 'credits'} className={tab === 'credits' ? 'on' : ''}
            onClick={() => setTab('credits')}>Credits</button>
          <button role="tab" aria-selected={tab === 'simulate'} className={tab === 'simulate' ? 'on' : ''}
            onClick={() => setTab('simulate')}>Simulate</button>
        </div>
      </div>
      {sign && (
        <InfoTip topic="jukebox-sign-in"
          text="Spotify's sign-in for SpotFX runs out six months after it was made; when it does, every night (and Absorb, and SpotFX's own polling) stops at once.">
          <div className={`card jukebox-sign-in ${sign.tone}`} data-testid="jukebox-sign-in">
            <Icon name="warn" size={16} /> <span>{sign.text}</span>
          </div>
        </InfoTip>
      )}
      {(cfgQ.isError || statusQ.isError) && (
        <div className="card jukebox-error">The Jukebox couldn't be read from SpotFX — is it running?</div>
      )}
      {tab === 'set' && <SetListTab cfg={cfg} preview={previewQ.data} loading={previewQ.isLoading}
        status={status} />}
      {tab === 'live' && <LiveTab status={status} />}
      {tab === 'guests' && <GuestsTab status={status} />}
      {tab === 'credits' && <CreditsTab />}
      {tab === 'simulate' && <SimulateTab />}
      <SonicChatPopover helpTopic="sonic-jukebox" />
    </div>
  );
}

// ── the Set list tab ─────────────────────────────────────────────────────────

function SetListTab({ cfg, preview, loading, status }: {
  cfg: ProgramConfig | null; preview: JukeboxPreview | undefined; loading: boolean;
  status: JukeboxStatus | undefined;
}) {
  const toast = useToast();
  const save = useSaveJukeboxConfig();
  const reload = useReloadSet();
  const move = useMoveSetSong();
  const [link, setLink] = useState<string | null>(null);
  const [guests, setGuests] = useState<number>(15);
  if (!cfg) return <div className="card jukebox-card">Reading the program settings…</div>;

  const running = !!status?.running;
  const put = (patch: Partial<ProgramConfig>) =>
    save.mutate(patch, { onError: (e) => toast(errText(e), 'error') });
  const ok = preview?.status === 'ok';
  const set: SetItem[] = ok ? preview?.set ?? [] : [];
  const lapItems = ok ? preview?.lap_items ?? [] : [];
  const playhead = ok ? preview?.playhead ?? null : null;
  const perSong = slotsByIndex(lapItems, set.length);
  const manual = cfg.mode === 'manual';
  const draft = link ?? cfg.playlist;

  const onReorder = (from: number, to: number) => {
    if (!canMove(from, playhead) || !canMove(to, playhead)) {
      toast('Only set songs at least two ahead of the one playing can move during the night.', 'error');
      return;
    }
    move.mutate({ from_index: from, to_index: to }, {
      onSuccess: (r) => { if (r.status !== 'moved') toast(r.detail || 'Not moved', 'error'); },
      onError: (e) => toast(errText(e), 'error'),
    });
  };

  return (
    <div className="jukebox-grid">
      <section className="card jukebox-card" data-testid="jukebox-set-card">
        <div className="jukebox-card-head">
          <InfoTip topic="jukebox-set-list"
            text="The playlist that is the night's set. It plays in order (shuffle off); reordering a song here writes the new order to the playlist in Spotify.">
            <span className="card-title jukebox-card-title">The set</span>
          </InfoTip>
          {ok && <span className="jukebox-muted">{preview?.playlist_name}</span>}
          {isLinked(cfg) && (
            <button className="jukebox-small" disabled={reload.isPending}
              onClick={() => reload.mutate(undefined, { onError: (e) => toast(errText(e), 'error') })}
              aria-label="Reload the set from Spotify">
              <Icon name="sync" size={14} /> Reload
            </button>
          )}
        </div>
        <form className="jukebox-link" onSubmit={(e) => {
          e.preventDefault();
          put({ playlist: draft.trim() });
          setLink(null);
        }}>
          <input type="text" aria-label="Set playlist link" placeholder="A Spotify playlist link"
            value={draft} onChange={(e) => setLink(e.target.value)} disabled={running} />
          <button type="submit" disabled={running || draft.trim() === cfg.playlist.trim()}>Link</button>
        </form>
        {running && <p className="jukebox-muted">A night is running on this set — stop it to link another playlist.</p>}
        {!isLinked(cfg) && <p className="jukebox-muted">No set playlist yet. Link one to see the program.</p>}
        {isLinked(cfg) && loading && <p className="jukebox-muted">Reading the set from Spotify…</p>}
        {preview && preview.status === 'refused' && <p className="jukebox-bad">{preview.detail}</p>}
        {ok && (
          <>
            <div className="jukebox-count">
              <span data-testid="jukebox-count">{countLine(preview?.lap, guests)}</span>
              <label className="jukebox-guests">
                <span>at</span>
                <select aria-label="Guests" value={guests} onChange={(e) => setGuests(Number(e.target.value))}>
                  {GUEST_COUNTS.map((g) => <option key={g} value={g}>{g}</option>)}
                </select>
                <span>guests</span>
              </label>
            </div>
            <ProgramBar items={lapItems} playhead={playhead} />
            {(preview?.lap?.notes ?? []).map((n) => <p key={n} className="jukebox-muted">{n}</p>)}
          </>
        )}
      </section>

      <section className="card jukebox-card" data-testid="jukebox-slots-card">
        <div className="jukebox-card-head">
          <InfoTip topic="jukebox-slots"
            text="Where the jukebox slots go. About 45 seconds before the song in front of a slot ends, the top waiting song is sent into Spotify's queue; an empty slot passes and the set continues.">
            <span className="card-title jukebox-card-title">Jukebox slots</span>
          </InfoTip>
        </div>
        <div className="jukebox-modes" role="radiogroup" aria-label="Where the slots go">
          {(['auto', 'jukebox_first', 'manual'] as SlotMode[]).map((m) => (
            <button key={m} role="radio" aria-checked={cfg.mode === m}
              className={cfg.mode === m ? 'on' : ''}
              onClick={() => {
                if (cfg.mode === m) return;
                // Auto (or jukebox first) → Manual copies the playing pattern
                if (m === 'manual' && ok) put({ mode: 'manual', manual: preview?.manual_equivalent ?? [] });
                else put({ mode: m });
              }}>{MODE_LABEL[m]}</button>
          ))}
        </div>
        {cfg.mode === 'auto' && (
          <div className="jukebox-auto">
            <label>A slot after every
              <select aria-label="Set songs between slots" value={cfg.every}
                onChange={(e) => put({ every: Number(e.target.value) })}>
                {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
              set song{cfg.every === 1 ? '' : 's'}
            </label>
            <label>
              <select aria-label="Slots in a row" value={cfg.run}
                onChange={(e) => put({ run: Number(e.target.value) })}>
                {[1, 2, 3].map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
              in a row
            </label>
          </div>
        )}
        <p className="jukebox-rule" data-testid="jukebox-rule">{ruleLine(cfg)}</p>
        <label className="jukebox-runout">When the set runs out
          <select aria-label="When the set runs out" value={cfg.run_out}
            onChange={(e) => put({ run_out: e.target.value as RunOut })}>
            {(Object.keys(RUN_OUT_LABEL) as RunOut[]).map((r) => (
              <option key={r} value={r}>{RUN_OUT_LABEL[r]}</option>))}
          </select>
        </label>
      </section>

      {ok && set.length > 0 && (
        <section className="card jukebox-card jukebox-list-card" data-testid="jukebox-set-list">
          <div className="jukebox-card-head">
            <span className="card-title jukebox-card-title">Running order</span>
            <span className="jukebox-muted">
              {manual ? 'Click a song for a slot after it · drag ⠿ to reorder'
                : 'Drag ⠿ to reorder · Manual to place slots by hand'}
            </span>
          </div>
          <SortableList
            className="jukebox-set"
            items={set}
            getId={(it, i) => `${i}:${it.uri}`}
            getLabel={(it, i) => `set song ${i + 1}, ${it.title}`}
            onReorder={onReorder}
            renderItem={(it, i, row) => (
              <div ref={row.rowRef} style={row.rowStyle}
                className={`jukebox-row${row.isDragging ? ' dragging' : ''}${playhead === i ? ' current' : ''}`}>
                <div className="jukebox-song">
                  {canMove(i, playhead) ? row.handle : <span className="jukebox-handle-off" aria-hidden="true">⠿</span>}
                  <span className="jukebox-num">{i + 1}</span>
                  {manual ? (
                    <button className="jukebox-song-btn" data-testid={`set-song-${i}`}
                      aria-label={`Put a jukebox slot after ${it.title}`}
                      onClick={() => put({ manual: clickSetSong(cfg.manual, it.uri) })}>
                      <SongWords it={it} />
                    </button>
                  ) : <div className="jukebox-song-words"><SongWords it={it} /></div>}
                  <span className="jukebox-dur">{mmss(it.duration_ms)}</span>
                </div>
                {perSong[i] > 0 && (
                  <div className="jukebox-slots">
                    {Array.from({ length: manual ? slotsAfter(cfg.manual, it.uri) || perSong[i] : perSong[i] }).map((_, k) => (
                      <span key={k} className={`jukebox-slot${manual ? '' : ' fixed'}`}>
                        {manual ? (
                          <>
                            <button className="jukebox-slot-btn" data-testid={`slot-${i}-${k}`}
                              aria-label="Another jukebox slot right after this one"
                              onClick={() => put({ manual: clickSlot(cfg.manual, it.uri) })}>
                              <Icon name="note" size={12} /> Jukebox
                            </button>
                            <button className="jukebox-slot-x" aria-label="Remove this jukebox slot"
                              onClick={() => put({ manual: removeSlot(cfg.manual, it.uri) })}>×</button>
                          </>
                        ) : <><Icon name="note" size={12} /> Jukebox</>}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )}
          />
        </section>
      )}
    </div>
  );
}

function isLinked(cfg: ProgramConfig): boolean {
  return !!cfg.playlist.trim();
}

function SongWords({ it }: { it: SetItem }) {
  return (
    <>
      <span className="jukebox-song-title">{it.title || it.uri}</span>
      {it.artist && <span className="jukebox-song-artist">{it.artist}</span>}
    </>
  );
}

function ProgramBar({ items, playhead }: { items: JukeboxPreview['lap_items']; playhead: number | null }) {
  const segs = barSegments(items ?? [], playhead);
  if (!segs.length) return null;
  return (
    <div className="jukebox-bar" role="img" aria-label="The program for one pass through the set"
      data-testid="jukebox-bar">
      {segs.map((s, i) => (
        <span key={i} className={`jukebox-bar-seg ${s.kind}${s.current ? ' current' : ''}`}
          style={{ flexGrow: s.weight }} title={s.title} />
      ))}
    </div>
  );
}

// ── the Live tab (read-only except its own draggable line, §7.2) ───────────

function guestsLine(g: JukeboxStatus['guests']): string {
  if (!g || g.phones === 0) return 'Guest page: no phones yet';
  const phones = `${g.phones} phone${g.phones === 1 ? '' : 's'}`;
  return `Guest page: ${phones}, ${g.joined} joined`;
}

function LiveTab({ status }: { status: JukeboxStatus | undefined }) {
  const toast = useToast();
  const onError = (e: unknown) => toast(errText(e), 'error');
  const now = nowLine(status);
  const warnings = nightWarnings(status);
  const line = status?.line ?? [];
  const phones = useGuests(!!status?.running).data?.phones ?? [];
  const move = useMoveEntry();
  return (
    <div className="jukebox-grid">
      <section className="card jukebox-card" data-testid="jukebox-live-card">
        <div className="jukebox-card-head">
          <InfoTip topic="jukebox-live"
            text="What the night is doing: the song playing, the next items in the program and when they start, and the jukebox line, which you can drag to reorder (nothing else here writes).">
            <span className="card-title jukebox-card-title">Live</span>
          </InfoTip>
        </div>
        <p className="jukebox-night" data-testid="jukebox-night">{nightLine(status?.night)}</p>
        {now && (
          <div className="jukebox-now" data-testid="jukebox-now">
            <span className="jukebox-tag">{now.tag}</span>
            <span className="jukebox-now-title">{now.title}</span>
            {status?.remaining_ms != null && status.remaining_ms > 0 && (
              <span className="jukebox-muted">{mmss(status.remaining_ms)} left</span>
            )}
          </div>
        )}
        {warnings.map((w) => <p key={w} className="jukebox-bad">{w}</p>)}
        {status?.running && (
          <InfoTip topic="jukebox-guest-page"
            text="The page guests open on their phones: they vote on every song and see what's coming up. Its own small app, reached only through tonight's party link.">
            <p className="jukebox-muted" data-testid="jukebox-guests">{guestsLine(status.guests)}</p>
          </InfoTip>
        )}
      </section>

      {status?.running && (
        <section className="card jukebox-card" data-testid="jukebox-next">
          <div className="jukebox-card-head">
            <span className="card-title jukebox-card-title">Coming up</span>
            <span className="jukebox-muted">the next {status.next.length}</span>
          </div>
          <ol className="jukebox-next">
            {status.next.map((it, i) => {
              const v = itemView(it);
              return (
                <li key={i} className={`jukebox-item ${v.tone}`}>
                  <span className="jukebox-tag">{v.tag}</span>
                  <span className="jukebox-item-words">
                    <span className="jukebox-song-title">{v.title}</span>
                    {v.sub && <span className="jukebox-song-artist">{v.sub}</span>}
                  </span>
                  <span className="jukebox-dur">{startsIn(it.starts_in_ms)}</span>
                </li>
              );
            })}
          </ol>
        </section>
      )}

      {status?.running && (
        <section className="card jukebox-card" data-testid="jukebox-line">
          <div className="jukebox-card-head">
            <span className="card-title jukebox-card-title">The jukebox line</span>
            <span className="jukebox-muted">{line.length ? `${line.length} song${line.length === 1 ? '' : 's'}` : 'empty — slots pass'}</span>
          </div>
          {line.length > 0 && (
            <JukeboxLine
              items={line}
              getId={(e) => e.id}
              getLabel={(e) => e.title || e.uri}
              getSent={(e) => e.state !== 'queued'}
              onReorder={(id, to) => move.mutate({ id, to }, { onError })}
              renderRow={(e) => (
                <span className="jukebox-item-words">
                  <span className="jukebox-song-title">{e.title || e.uri}</span>
                  <span className="jukebox-song-artist">{[e.artist, liveLineWords(e, phones)].filter(Boolean).join(' · ')}</span>
                </span>
              )}
            />
          )}
        </section>
      )}

      {status?.running && <EconomyCard />}

      {status?.night && <ReportCard nightId={status.night.id} />}

      {(status?.log?.length ?? 0) > 0 && (
        <details className="card jukebox-card jukebox-log">
          <summary>The night's log</summary>
          <pre>{status?.log.join('\n')}</pre>
        </details>
      )}
    </div>
  );
}

// ── the economy right now (read-only; services/jukebox/economy_live.py) ─────

function EconomyCard() {
  const q = useJukeboxEconomy(true);
  const e = q.data;
  return (
    <section className="card jukebox-card jukebox-list-card" data-testid="jukebox-economy">
      <div className="jukebox-card-head">
        <InfoTip topic="jukebox-economy"
          text="The night's economy right now, read-only: the credits guests hold, what they cost, and what has happened lately. The same numbers the post-party report keeps.">
          <span className="card-title jukebox-card-title">The economy right now</span>
        </InfoTip>
      </div>
      {!e?.running ? (
        <p className="jukebox-muted">{q.isError ? 'The economy couldn\'t be read from SpotFX.' : 'Reading…'}</p>
      ) : (
        <>
          <p className="jukebox-muted" data-testid="jukebox-economy-room">{roomLine(e)}</p>
          {!e.credits || !e.prices ? (
            <p className="jukebox-night" data-testid="jukebox-economy-free">{freePlayLine(e)}</p>
          ) : (
            <>
              <p className="jukebox-night" data-testid="jukebox-economy-credits">{creditsLine(e.credits)}</p>
              <p className="jukebox-muted" data-testid="jukebox-economy-activity">{activityLine(e.credits)}</p>
              <dl className="jukebox-economy-prices" data-testid="jukebox-economy-prices">
                {priceRows(e.prices).map((r) => (
                  <div key={r.label}><dt>{r.label}</dt><dd>{r.value}</dd></div>
                ))}
              </dl>
              <span className="card-title jukebox-card-title">Lately</span>
              {(e.events ?? []).length === 0 ? (
                <p className="jukebox-muted">Nothing spent or given yet tonight.</p>
              ) : (
                <ol className="jukebox-next jukebox-economy-events" data-testid="jukebox-economy-events">
                  {(e.events ?? []).map((ev, i) => {
                    const w = eventWords(ev);
                    return (
                      <li key={`${ev.at_ms}-${i}`} className="jukebox-item">
                        <span className="jukebox-dur">{w.when}</span>
                        <span className="jukebox-item-words"><span className="jukebox-song-title">{w.text}</span></span>
                        {w.credits && <span className="jukebox-dur">{w.credits}</span>}
                      </li>
                    );
                  })}
                </ol>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}

// ── the post-party report (read-only; services/jukebox/night_report.py) ─────

const COMPARE_SIZES = [4, 8, 15, 20, 30] as const;

function ReportCard({ nightId }: { nightId: string }) {
  const [size, setSize] = useState<number | null>(null);
  const q = useJukeboxReport(true, size, nightId);
  const r = q.data;
  const n = r?.night;
  const cmp = r?.comparison;
  return (
    <section className="card jukebox-card jukebox-list-card" data-testid="jukebox-report">
      <div className="jukebox-card-head">
        <InfoTip topic="jukebox-report"
          text="The night measured the model's way: what played, the line, the guests' songs and waits, the jail, quiet guests and — in credits mode — the credits, prices and what guests could afford, each beside the model's nights at the same party size, so the next party starts from real numbers.">
          <span className="card-title jukebox-card-title">The night's report</span>
        </InfoTip>
        <label className="jukebox-guests">
          <span>compare with a party of</span>
          <select aria-label="Compare with a party of" value={size ?? ''}
            onChange={(e) => setSize(e.target.value ? Number(e.target.value) : null)}>
            <option value="">{r?.guests_from === 'the ledger' || r?.guests_from === 'the guest book'
              ? `${r.guests} (${r.guests_from})` : '—'}</option>
            {COMPARE_SIZES.map((g) => <option key={g} value={g}>{g}</option>)}
          </select>
        </label>
      </div>
      {!r ? <p className="jukebox-muted">{q.isError ? 'The report couldn\'t be read from SpotFX.' : 'Working the report…'}</p> : (
        <>
          <p className="jukebox-night" data-testid="jukebox-report-summary">{r.summary}</p>
          {n && <p className="jukebox-muted">{endLine(n)}</p>}
          {n && (
            <div className="jukebox-prices">
              <div className="jukebox-price-group">
                {nightFacts(n).map((f) => (
                  <div key={f.label} className="jukebox-price-row"><span>{f.label}</span><span className="jukebox-price-value">{f.value}</span></div>
                ))}
              </div>
              {r.credits && (
                <div className="jukebox-price-group">
                  {creditFacts(r.credits).map((f) => (
                    <div key={f.label} className="jukebox-price-row"><span>{f.label}</span><span className="jukebox-price-value">{f.value}</span></div>
                  ))}
                </div>
              )}
            </div>
          )}
          {(r.integrity ?? []).map((p) => <p key={p} className="jukebox-bad">The ledger: {p}</p>)}
          {cmp ? (
            <div className="jukebox-sim-table" role="table" aria-label="This night beside the model" data-testid="jukebox-report-compare">
              <div className="jukebox-sim-tr head" role="row">
                <span role="columnheader">{cmp.guests} guests, {cmp.program}</span>
                <span role="columnheader">This night</span>
                <span role="columnheader">Model</span>
              </div>
              {cmp.rows.map((row) => {
                const c = compareCells(row);
                return (
                  <div key={row.key} className="jukebox-sim-tr" role="row" title={c.why ?? undefined}>
                    <span role="cell">{c.label}</span>
                    <span role="cell" className="jukebox-price-value">{c.night}</span>
                    <span role="cell" className="jukebox-price-value">{c.model}</span>
                  </div>
                );
              })}
            </div>
          ) : n && <p className="jukebox-muted">Pick a party size to see this night beside the model's nights.</p>}
          {q.isFetching && <p className="jukebox-muted">Working the model's nights…</p>}
        </>
      )}
    </section>
  );
}
