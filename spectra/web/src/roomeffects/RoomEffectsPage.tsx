/** ROOM EFFECTS (/room-effects) — the one built field kind, Dim Wave, over
 * a room's MEASURED light map.
 *
 * FUNCTION FIRST. Three knobs, a device chip row, and one button that holds
 * the room and runs the wave. There is no effect-kind picker: the field
 * interface serves four kinds from day one (his instruction) but only Dim
 * Wave drives lights in this slice, and offering the other three would be
 * offering something that cannot run.
 *
 * WHAT PRESSING RUN DOES: the wave rides ON TOP of whatever the show is
 * already doing — the per-emitter gain multiplies onto the show's own
 * brightness at the one write seam, exactly the way the room's brightness
 * dimmer does, so the fish keeps swimming underneath. It runs under the
 * same held-room machinery as every preview in this app, which means the
 * room is snapshotted, the page must keep a heartbeat alive, and the whole
 * thing has a hard three-minute ceiling — a forgotten wave is a nuisance,
 * never a lost show. */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import HelpLink from '../help/HelpLink';
import { apiDel, apiGet, apiPost } from '../api/client';
import { useToast } from '../components/Toast';

type Room = {
  id: string; name: string; carrier_ids: string[];
  /** every EMITTER with a footprint — several per carrier once a strip is
   * mapped per segment, so "is this carrier mapped" is `mapped_carriers`. */
  mapped_ids: string[];
  mapped_carriers: string[];
};
type Effect = {
  id: string; room_id: string; name: string; kind: string;
  wavelength: number; speed: number; depth: number; carrier_ids: string[];
};
type Status = {
  running: boolean; live: boolean; room_id: string; effect: Effect | null;
  emitters: string[]; gains: Record<string, number>; held_params: string[];
  masks: Record<string, { pixels: number; min: number; max: number }>;
  last_error: string;
  /** The render-side mask engine's own counter. A mask whose length does not
   * match the frame is SKIPPED (never resampled — a stretched gain is a wave
   * at the wrong wavelength), which means that virtual is silently not being
   * driven. It was counted here and shown nowhere until the reason sweep. */
  mask_engine?: { skipped_length_mismatch?: number;
                  last_mismatch?: { virtual_id: string; mask: number; frame: number } | null };
  cost: {
    samples: number; virtuals_per_tick: number; ticks: number; writes: number;
    written_per_tick: number; masked_per_tick: number;
    per_tick_ms: { p50: number; p95: number; max: number };
    target_tick_hz: number; achieved_tick_hz: number; writes_per_s: number;
  };
};

const HEARTBEAT_MS = 4000;

export default function RoomEffectsPage() {
  const toast = useToast();
  const [rooms, setRooms] = useState<Room[]>([]);
  const [effects, setEffects] = useState<Effect[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [busy, setBusy] = useState(false);
  const beat = useRef<number | null>(null);

  const effect = useMemo(() => effects.find((e) => e.id === selected) ?? null, [effects, selected]);
  const room = useMemo(() => rooms.find((r) => r.id === effect?.room_id) ?? null, [rooms, effect]);

  const reload = useCallback(async () => {
    const [r, e] = await Promise.all([
      apiGet<{ rooms: Room[] }>('/rooms'),
      apiGet<{ effects: Effect[] }>('/room-effects'),
    ]);
    setRooms(r.rooms);
    setEffects(e.effects);
    setSelected((cur) => cur ?? e.effects[0]?.id ?? null);
  }, []);

  useEffect(() => { void reload(); }, [reload]);

  useEffect(() => {
    const t = window.setInterval(() => {
      void apiGet<Status>('/room-effects/status').then(setStatus).catch(() => undefined);
    }, 1000);
    return () => window.clearInterval(t);
  }, []);

  /** The heartbeat IS the safety: stop sending it and the held room lets go
   * on its own, with no route ever being called. Cleared on unmount, and a
   * beacon on unload, the same shape ColorSetsPage's own preview uses. */
  const startBeat = useCallback(() => {
    if (beat.current !== null) return;
    beat.current = window.setInterval(() => {
      void apiPost('/room-effects/heartbeat').catch(() => undefined);
    }, HEARTBEAT_MS);
  }, []);
  const stopBeat = useCallback(() => {
    if (beat.current !== null) window.clearInterval(beat.current);
    beat.current = null;
  }, []);

  useEffect(() => {
    const bye = () => navigator.sendBeacon?.('/spectra/api/room-effects/stop');
    window.addEventListener('beforeunload', bye);
    return () => {
      window.removeEventListener('beforeunload', bye);
      stopBeat();
      void apiPost('/room-effects/stop').catch(() => undefined);
    };
  }, [stopBeat]);

  const save = useCallback(async (patch: Effect) => {
    try {
      const saved = await apiPost<Effect>('/room-effects', patch);
      setEffects((es) => es.map((e) => (e.id === saved.id ? saved : e)));
      return saved;
    } catch (err) {
      toast(String(err), 'error');
      return null;
    }
  }, [toast]);

  const setKnob = useCallback((key: 'wavelength' | 'speed' | 'depth', value: number) => {
    if (!effect) return;
    const next = { ...effect, [key]: value };
    setEffects((es) => es.map((e) => (e.id === next.id ? next : e)));
    void save(next);
  }, [effect, save]);

  const run = useCallback(async () => {
    if (!effect) return;
    setBusy(true);
    try {
      const result = await apiPost<{
        running: boolean; reason?: string; emitters: string[]; unmapped: string[];
        masked_virtuals?: string[];
      }>(`/room-effects/${effect.id}/start`);
      // A refusal is a stated outcome, not an exception — say WHY rather
      // than reporting "running on 0 emitters", which reads as success.
      if (!result.running) {
        toast(result.reason || 'the wave did not start', 'error');
        return;
      }
      startBeat();
      const perPixel = result.masked_virtuals?.length
        ? `, ${result.masked_virtuals.length} driven per pixel` : '';
      toast(`Running on ${result.emitters.length} emitter(s)${perPixel}`, 'success');
      if (result.unmapped?.length) {
        toast(`Not mapped, so not driven: ${result.unmapped.join(', ')}`, 'error');
      }
    } catch (err) {
      toast(String(err), 'error');
    } finally {
      setBusy(false);
    }
  }, [effect, startBeat, toast]);

  const stop = useCallback(async () => {
    stopBeat();
    await apiPost('/room-effects/stop').catch(() => undefined);
  }, [stopBeat]);

  const running = !!status?.running;

  return (
    <div className="room-effects-page">
      <h2>Room effects <HelpLink topic="room-effects" /></h2>
      <p className="muted rooms-lede">
        A Dim Wave is a sine travelling along the room&apos;s floor-to-ceiling axis. Each fixture&apos;s
        brightness is the wave AVERAGED over everything that fixture actually lights — so a wide
        wall sconce swells softly and a narrow one snaps, without a smoothing knob.
      </p>

      <div className="rooms-layout">
        <section className="rooms-list card">
          <h3>Effects <HelpLink topic="room-effects-kinds" /></h3>
          {effects.map((e) => (
            <button key={e.id} className={`room-row ${e.id === selected ? 'active' : ''}`}
                    onClick={() => setSelected(e.id)}>
              <span className="room-row-name">{e.name}</span>
              <span className="muted">{rooms.find((r) => r.id === e.room_id)?.name ?? '—'}</span>
            </button>
          ))}
          <div className="room-new">
            <select id="new-effect-room" defaultValue="">
              <option value="" disabled>Room…</option>
              {rooms.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
            </select>
            <button
              disabled={!rooms.length}
              onClick={async () => {
                const sel = document.getElementById('new-effect-room') as HTMLSelectElement | null;
                const roomId = sel?.value || rooms[0]?.id;
                if (!roomId) return;
                try {
                  const made = await apiPost<Effect>('/room-effects', { room_id: roomId, name: 'Dim Wave', kind: 'dim_wave' });
                  await reload();
                  setSelected(made.id);
                } catch (err) { toast(String(err), 'error'); }
              }}
            >+ Dim Wave</button>
          </div>
        </section>

        <section className="room-detail card">
          {!effect && <p className="muted">Create a Dim Wave to begin.</p>}
          {effect && (
            <>
              <div className="room-detail-head">
                <input className="room-name-input" value={effect.name}
                       onChange={(e) => setEffects((es) => es.map((x) => (x.id === effect.id ? { ...x, name: e.target.value } : x)))}
                       onBlur={() => void save(effect)} />
                <button className="danger" onClick={async () => {
                  await apiDel(`/room-effects/${effect.id}`);
                  setSelected(null);
                  await reload();
                }}>Delete</button>
              </div>

              <h4>Shape <HelpLink topic="room-effects-knobs" /></h4>
              <label className="knob">
                <span>Wavelength <em>{effect.wavelength.toFixed(2)}</em></span>
                <input type="range" min={0.1} max={3} step={0.05} value={effect.wavelength}
                       onChange={(e) => setKnob('wavelength', Number(e.target.value))} />
                <small className="muted">1.00 = one full cycle from floor to ceiling. Smaller = more waves at once.</small>
              </label>
              <label className="knob">
                <span>Speed <em>{effect.speed.toFixed(2)}</em></span>
                <input type="range" min={-2} max={2} step={0.05} value={effect.speed}
                       onChange={(e) => setKnob('speed', Number(e.target.value))} />
                <small className="muted">Cycles per second. Positive travels toward the ceiling; 0 is a standing wave.</small>
              </label>
              <label className="knob">
                <span>Depth <em>{effect.depth.toFixed(2)}</em></span>
                <input type="range" min={0} max={1} step={0.05} value={effect.depth}
                       onChange={(e) => setKnob('depth', Number(e.target.value))} />
                <small className="muted">How far the trough dips. 0 changes nothing at all; 1 reaches black.</small>
              </label>

              <h4>Fixtures</h4>
              <p className="muted small">
                Empty means every mapped fixture in the room. A fixture with no measured footprint
                cannot be driven — map it on the Rooms page first. A fixture mapped in PARTS is
                driven per pixel, so the wave runs ALONG it rather than dimming all of it at once.
              </p>
              <div className="device-chips">
                {(room?.carrier_ids ?? []).map((d) => {
                  const on = !effect.carrier_ids.length || effect.carrier_ids.includes(d);
                  const mapped = (room?.mapped_carriers ?? room?.mapped_ids ?? []).includes(d);
                  return (
                    <button key={d} className={`chip ${on ? 'on' : ''} ${mapped ? '' : 'unmapped'}`}
                            title={mapped ? undefined : 'not mapped'}
                            onClick={() => {
                              const cur = effect.carrier_ids.length ? effect.carrier_ids : (room?.carrier_ids ?? []);
                              const next = cur.includes(d) ? cur.filter((x) => x !== d) : [...cur, d];
                              void save({ ...effect, carrier_ids: next });
                              setEffects((es) => es.map((x) => (x.id === effect.id ? { ...x, carrier_ids: next } : x)));
                            }}>
                      {d}{mapped ? '' : ' ⛔'}
                    </button>
                  );
                })}
              </div>
            </>
          )}
        </section>

        <section className="room-capture card">
          <h3>Run <HelpLink topic="room-effects-run" /></h3>
          <p className="muted small">
            The wave multiplies onto the show that is already playing — it never replaces it.
            While it runs the room is HELD, so keep this page open; a closed tab hands the room
            back on its own, and there is a hard three-minute ceiling either way.
          </p>
          {!running ? (
            <button className="primary" disabled={!effect || busy} onClick={() => void run()}>
              {busy ? 'Starting…' : '▶ Run on the room'}
            </button>
          ) : (
            <button className="danger" onClick={() => void stop()}>■ Stop and hand the room back</button>
          )}

          {status && (
            <dl className="capture-status">
              <dt>State</dt>
              <dd className={running ? 'ok' : ''}>{running ? (status.live ? 'running (room held)' : 'stopping') : 'idle'}</dd>
              <dt>Driving</dt>
              <dd>{status.emitters.join(', ') || '—'}</dd>
              <dt>Gains</dt>
              <dd>{Object.entries(status.gains).map(([v, g]) => `${v} ${g.toFixed(2)}`).join(' · ') || '—'}</dd>
              <dt>
                Per-pixel <HelpLink topic="room-effects-along-a-strip" title="A wave along one fixture" />
              </dt>
              <dd className="small">
                {Object.entries(status.masks ?? {})
                  .map(([v, m]) => `${v}: ${m.pixels}px ${m.min.toFixed(2)}–${m.max.toFixed(2)}`)
                  .join(' · ') || 'none — every driven fixture takes one gain'}
              </dd>
              <dt>Held for the watchdog</dt>
              <dd className="small">{status.held_params.join(', ') || '—'}</dd>
              <dt>Write cost</dt>
              <dd className="small">
                {status.cost.samples
                  ? `${status.cost.per_tick_ms.p50.toFixed(1)} ms p50 / ${status.cost.per_tick_ms.p95.toFixed(1)} ms p95 per tick
                     · ${status.cost.achieved_tick_hz} Hz of ${status.cost.target_tick_hz}
                     · ${status.cost.writes_per_s} writes/s over ${status.cost.virtuals_per_tick} virtual(s)
                     (${status.cost.written_per_tick} written, ${status.cost.masked_per_tick} per-pixel)`
                  : 'not measured yet'}
              </dd>
              {status.mask_engine?.skipped_length_mismatch
                ? (
                  <>
                    <dt>Masks skipped</dt>
                    <dd className="warn small">
                      {status.mask_engine.skipped_length_mismatch} frame(s) — a gain was the
                      wrong length for the strip it was built for and was dropped rather than
                      stretched, so that fixture is not being driven
                      {status.mask_engine.last_mismatch
                        ? ` (last: ${status.mask_engine.last_mismatch.virtual_id}, mask
                            ${status.mask_engine.last_mismatch.mask} vs frame
                            ${status.mask_engine.last_mismatch.frame}) — re-map it`
                        : ''}
                    </dd>
                  </>
                ) : null}
              {status.last_error && <><dt>Last error</dt><dd className="warn small">{status.last_error}</dd></>}
            </dl>
          )}
        </section>
      </div>
    </div>
  );
}
