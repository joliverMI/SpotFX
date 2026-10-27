/** THE JUKEBOX'S SIMULATE TAB (phase 3 PR 3.4; the plan's "party simulator
 * in the master view"): a model party night under his SAVED credits
 * settings, played back in five minutes so he can watch the economy before
 * a party — the line, the price at the back of it, every guest's credits,
 * what each guest does — and the average of twenty such nights beside the
 * tuned settings, with the plan's promises checked.
 *
 * The night is the server's (services/jukebox/simulator.py — the plan's own
 * model with the real price rules; guests and songs are a model, no Spotify,
 * no live room). The words and the playback arithmetic are jukeboxSim.ts. */
import { useEffect, useMemo, useRef, useState } from 'react';
import Icon from '../components/Icon';
import InfoTip from '../components/InfoTip';
import { useToast } from '../components/Toast';
import {
  chartGeometry, chartPoints, checkLine, clock, DEFAULT_PLAY_SECONDS, DEFAULT_SIM_GUESTS, eventLine,
  eventsUpTo, frameAt, guestName, here, nowView, PLAY_SECONDS, playedBy, playLabel, pointAt, presetHint,
  resultLine, rowCells, SIM_GUESTS,
} from './jukeboxSim';
import { useSimulate } from './queries';
import type { SimNight, SimResult } from './types';

function errText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

const TICK_MS = 100;

export default function SimulateTab() {
  const toast = useToast();
  const sim = useSimulate();
  const [guests, setGuests] = useState<number>(DEFAULT_SIM_GUESTS);
  const [source, setSource] = useState<'saved' | 'preset'>('saved');
  const [seed, setSeed] = useState(1);
  const [result, setResult] = useState<SimResult | null>(null);
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [playSeconds, setPlaySeconds] = useState<number>(DEFAULT_PLAY_SECONDS);

  const run = (nextSeed: number) => {
    setSeed(nextSeed);
    sim.mutate({ guests, seed: nextSeed, program: source }, {
      onSuccess: (r) => { setResult(r); setT(0); setPlaying(true); },
      onError: (e) => toast(errText(e), 'error'),
    });
  };

  const minutes = result?.night.minutes ?? 240;
  useEffect(() => {
    if (!playing) return;
    const perTick = (minutes / playSeconds) * (TICK_MS / 1000);
    const id = window.setInterval(() => {
      setT((x) => {
        const nx = x + perTick;
        if (nx >= minutes) { setPlaying(false); return minutes; }
        return nx;
      });
    }, TICK_MS);
    return () => window.clearInterval(id);
  }, [playing, minutes, playSeconds]);

  return (
    <div className="jukebox-grid">
      <section className="card jukebox-card jukebox-list-card" data-testid="jukebox-sim-controls">
        <div className="jukebox-card-head">
          <InfoTip topic="jukebox-simulator"
            text="A model party night under your saved credits settings, played back in five minutes: guests arrive, vote, add songs, skip, tip and go to jail by the plan's own model of how people behave. Nothing reaches Spotify or the room.">
            <span className="card-title jukebox-card-title">Party simulator</span>
          </InfoTip>
          <span className="jukebox-muted">a model night — no Spotify, no lights</span>
        </div>
        <div className="jukebox-sim-controls">
          <label className="jukebox-guests">
            <span>Guests</span>
            <select aria-label="Simulated guests" value={guests} onChange={(e) => setGuests(Number(e.target.value))}>
              {SIM_GUESTS.map((g) => <option key={g} value={g}>{g}</option>)}
            </select>
          </label>
          <div className="jukebox-modes" role="group" aria-label="Program for the simulated night">
            <button aria-pressed={source === 'saved'} className={source === 'saved' ? 'on' : ''}
              onClick={() => setSource('saved')}>Your program</button>
            <button aria-pressed={source === 'preset'} className={source === 'preset' ? 'on' : ''}
              onClick={() => setSource('preset')}>The preset for this size</button>
          </div>
          <button className="jukebox-sim-run" disabled={sim.isPending} onClick={() => run(seed)}>
            <Icon name="play" size={14} /> {sim.isPending ? 'Working…' : 'Run the night'}
          </button>
          <button disabled={sim.isPending || !result} onClick={() => run(seed + 1)}>Another night</button>
        </div>
        {result && <p className="jukebox-rule" data-testid="jukebox-sim-what">{resultLine(result)}</p>}
        {!result && !sim.isPending && (
          <p className="jukebox-muted">Pick a party size and run a night to watch it play out.</p>
        )}
      </section>

      {result && (
        <>
          <Playback night={result.night} t={t} setT={setT} playing={playing} setPlaying={setPlaying}
            playSeconds={playSeconds} setPlaySeconds={setPlaySeconds} />
          <NightChart night={result.night} t={t} onSeek={(x) => { setT(x); }} />
          <Guests night={result.night} t={t} />
          <Happenings night={result.night} t={t} />
          <Averages result={result} />
        </>
      )}
    </div>
  );
}

function Playback({ night, t, setT, playing, setPlaying, playSeconds, setPlaySeconds }: {
  night: SimNight; t: number; setT: (t: number) => void; playing: boolean; setPlaying: (p: boolean) => void;
  playSeconds: number; setPlaySeconds: (s: number) => void;
}) {
  const now = nowView(night, t);
  return (
    <section className="card jukebox-card" data-testid="jukebox-sim-now">
      <div className="jukebox-card-head">
        <span className="card-title jukebox-card-title">Now</span>
        <span className="jukebox-sim-clock" data-testid="jukebox-sim-clock">
          {clock(t)} <span className="jukebox-muted">of {clock(night.minutes)}</span>
        </span>
      </div>
      <div className="jukebox-sim-transport">
        <button aria-label={playing ? 'Pause' : 'Play'} onClick={() => {
          if (!playing && t >= night.minutes) setT(0);
          setPlaying(!playing);
        }}>
          <Icon name={playing ? 'pause' : 'play'} size={14} />
        </button>
        <input type="range" aria-label="Party time" min={0} max={night.minutes} step={0.5}
          value={Math.min(t, night.minutes)} onChange={(e) => setT(Number(e.target.value))} />
        <select aria-label="Playback length" value={playSeconds} onChange={(e) => setPlaySeconds(Number(e.target.value))}>
          {PLAY_SECONDS.map((s) => <option key={s} value={s}>night in {playLabel(s)}</option>)}
        </select>
      </div>
      <div className="jukebox-now-title jukebox-sim-song" data-testid="jukebox-sim-song">{now.songLine}</div>
      <div className="jukebox-prices">
        <div className="jukebox-price-group">
          <div className="jukebox-price-row"><span>Guests here</span><span className="jukebox-price-value">{now.present}</span></div>
          <div className="jukebox-price-row"><span>Songs in the line</span><span className="jukebox-price-value">{now.line}</span></div>
          <div className="jukebox-price-row"><span>Back of the line</span><span className="jukebox-price-value">{Math.round(now.back)} min</span></div>
        </div>
        <div className="jukebox-price-group">
          <div className="jukebox-price-row"><span>Add price at the back</span><span className="jukebox-price-value">{now.price}</span></div>
          <div className="jukebox-price-row"><span>Credits held per guest</span><span className="jukebox-price-value">{now.heldPerGuest == null ? '–' : now.heldPerGuest.toFixed(1)}</span></div>
          <div className="jukebox-price-row"><span>In jail</span><span className="jukebox-price-value">{now.jailed}</span></div>
        </div>
      </div>
      {t >= night.last_call && t < night.minutes && <p className="jukebox-muted">Last call — no new songs.</p>}
    </section>
  );
}

const H = 200;

/** The chart draws in its box's own pixels (the viewBox follows the
 * measured width), so its labels stay legible on a phone. The wrap is a
 * state-backed callback ref: it mounts with the result, after the first
 * render. */
function useWidth(): [(el: HTMLDivElement | null) => void, number] {
  const [el, setEl] = useState<HTMLDivElement | null>(null);
  const [w, setW] = useState(640);
  useEffect(() => {
    if (!el) return;
    const measure = () => setW(Math.max(280, Math.round(el.clientWidth)));
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [el]);
  return [setEl, w];
}

function NightChart({ night, t, onSeek }: { night: SimNight; t: number; onSeek: (t: number) => void }) {
  const points = useMemo(() => chartPoints(night), [night]);
  const [wrapRef, W] = useWidth();
  const g = useMemo(() => chartGeometry(points, night.minutes, W, H), [points, night.minutes, W]);
  const [hover, setHover] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const toT = (clientX: number) => {
    const r = svgRef.current?.getBoundingClientRect();
    if (!r) return 0;
    const fx = ((clientX - r.left) / r.width) * W;
    return g.tAt(fx);
  };
  const hp = hover == null ? null : pointAt(points, hover);
  const hours = Array.from({ length: Math.floor(night.minutes / 60) + 1 }, (_, i) => i * 60);
  return (
    <section className="card jukebox-card" data-testid="jukebox-sim-chart">
      <div className="jukebox-card-head">
        <span className="card-title jukebox-card-title">Over the night</span>
        <span className="jukebox-sim-legend">
          <span className="jukebox-sim-key price" /> Add price at the back
          <span className="jukebox-sim-key held" /> Credits held per guest
        </span>
      </div>
      <div className="jukebox-sim-chart-wrap" ref={wrapRef}>
        <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} className="jukebox-sim-svg" role="img"
          aria-label="The add price at the back of the line and the credits held per guest, over the night"
          onMouseMove={(e) => setHover(toT(e.clientX))} onMouseLeave={() => setHover(null)}
          onClick={(e) => onSeek(toT(e.clientX))}>
          {g.ticks.map((v) => (
            <g key={v}>
              <line x1={30} x2={W - 8} y1={g.y(v)} y2={g.y(v)} className="jukebox-sim-grid" />
              <text x={26} y={g.y(v) + 3} className="jukebox-sim-axis" textAnchor="end">{Math.round(v)}</text>
            </g>
          ))}
          {hours.map((m) => (
            <text key={m} x={g.x(m)} y={H - 4} className="jukebox-sim-axis"
              textAnchor={m === 0 ? 'start' : m >= night.minutes ? 'end' : 'middle'}>{clock(m)}</text>
          ))}
          <line x1={g.x(night.last_call)} x2={g.x(night.last_call)} y1={8} y2={H - 18} className="jukebox-sim-lastcall" />
          <path d={g.heldPath} className="jukebox-sim-line held" />
          <path d={g.pricePath} className="jukebox-sim-line price" />
          {g.labels.map((l) => (
            <text key={l.key} x={l.x} y={l.y} className="jukebox-sim-label" textAnchor="end">{l.text}</text>
          ))}
          <line x1={g.x(t)} x2={g.x(t)} y1={8} y2={H - 18} className="jukebox-sim-playhead" />
          {hp && (
            <line x1={g.x(hp.t)} x2={g.x(hp.t)} y1={8} y2={H - 18} className="jukebox-sim-hover" />
          )}
        </svg>
        {hp && hover != null && (
          <div className="jukebox-sim-tip" data-testid="jukebox-sim-tip" style={{
            left: `${(g.x(hp.t) / W) * 100}%`,
            transform: `translateX(${g.x(hp.t) / W < 0.2 ? '0' : g.x(hp.t) / W > 0.8 ? '-100%' : '-50%'})`,
          }}>
            <div>{clock(hp.t)}</div>
            <div><span className="jukebox-sim-key price" /> {hp.price} to add at the back</div>
            <div><span className="jukebox-sim-key held" /> {hp.held == null ? '–' : hp.held.toFixed(1)} held per guest</div>
          </div>
        )}
      </div>
      <p className="jukebox-muted">The dashed line is last call. Click the chart to jump there.</p>
    </section>
  );
}

function Guests({ night, t }: { night: SimNight; t: number }) {
  const f = frameAt(night.frames, t);
  return (
    <section className="card jukebox-card" data-testid="jukebox-sim-guests">
      <div className="jukebox-card-head">
        <span className="card-title jukebox-card-title">The guests</span>
        <span className="jukebox-muted">credits now · songs played so far</span>
      </div>
      <div className="jukebox-sim-guestgrid">
        {night.guests.map((gst) => {
          const isHere = here(gst, t);
          const jailed = !!f?.jailed.includes(gst.id);
          return (
            <div key={gst.id} className={`jukebox-sim-guest ${gst.kind}${isHere ? '' : ' away'}${jailed ? ' jailed' : ''}`}
              title={`${guestName(gst.id)} — ${gst.kind === 'regular' ? 'a regular voter' : gst.kind === 'quiet' ? 'a quiet guest' : 'votes now and then'}${jailed ? ', in jail' : ''}${isHere ? '' : t < gst.arrive ? ', not here yet' : ', gone home'}`}>
              <span className="jukebox-sim-guest-name">{gst.id + 1}</span>
              <span className="jukebox-sim-guest-credits">{isHere || t >= gst.leave ? f?.cr[gst.id] ?? 0 : '·'}</span>
              <span className="jukebox-sim-guest-songs">{playedBy(night, gst.id, t)} ♪{jailed ? ' · jail' : ''}</span>
            </div>
          );
        })}
      </div>
      <p className="jukebox-muted">Outlined: regular voters. Faint: not here yet or gone home.</p>
    </section>
  );
}

function Happenings({ night, t }: { night: SimNight; t: number }) {
  const recent = eventsUpTo(night.events, t, 8);
  return (
    <section className="card jukebox-card" data-testid="jukebox-sim-events">
      <div className="jukebox-card-head">
        <span className="card-title jukebox-card-title">What's happening</span>
      </div>
      {recent.length === 0 ? <p className="jukebox-muted">Nothing yet — the guests are arriving.</p> : (
        <ul className="jukebox-next">
          {recent.map((e, i) => (
            <li key={`${e.t}-${i}`} className="jukebox-item">
              <span className="jukebox-dur">{clock(e.t)}</span>
              <span className="jukebox-item-words">{eventLine(e)}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Averages({ result }: { result: SimResult }) {
  const hint = presetHint(result);
  return (
    <section className="card jukebox-card jukebox-list-card" data-testid="jukebox-sim-averages">
      <div className="jukebox-card-head">
        <InfoTip topic="jukebox-simulator"
          text="Twenty model nights under your settings, beside the same nights under the tuned settings — same guests, same program — so anything you changed shows as a difference.">
          <span className="card-title jukebox-card-title">{result.nights} nights like it</span>
        </InfoTip>
        <span className="jukebox-muted">{result.same_as_tuned ? 'your settings are the tuned ones' : 'yours beside the tuned settings'}</span>
      </div>
      <ul className="jukebox-sim-checks">
        {result.checks.map((c) => {
          const l = checkLine(c);
          return (
            <li key={c.key} className={`jukebox-sim-check ${l.mark}`}>
              <span aria-hidden="true">{l.mark === 'ok' ? '✓' : l.mark === 'bad' ? '✗' : '–'}</span> {l.text}
            </li>
          );
        })}
      </ul>
      {hint && <p className="jukebox-sim-hint" data-testid="jukebox-sim-hint">{hint}</p>}
      <div className={`jukebox-sim-table${result.same_as_tuned ? ' one' : ''}`} role="table" aria-label="The night's numbers">
        <div className="jukebox-sim-tr head" role="row">
          <span role="columnheader">Over {result.nights} nights</span>
          <span role="columnheader">Yours</span>
          {!result.same_as_tuned && <span role="columnheader">Tuned</span>}
        </div>
        {result.rows.map((r) => {
          const c = rowCells(r, result.same_as_tuned);
          return (
            <div key={r.key} className={`jukebox-sim-tr${c.moved ? ' moved' : ''}`} role="row">
              <span role="cell">{c.label}</span>
              <span role="cell" className="jukebox-price-value">{c.yours}</span>
              {c.tuned != null && <span role="cell" className="jukebox-price-value">{c.tuned}</span>}
            </div>
          );
        })}
      </div>
    </section>
  );
}
