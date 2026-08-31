/** ROOM BUILDER (/rooms) — name a room, pick its CARRIERS (the things he
 * runs effects on), calibrate its axis with two taps on the live camera,
 * and run a mapping sync.
 *
 * A CARRIER, not a fixture: his tv-mapper reaches a backlight and both
 * sconces, so a fixture-keyed picker could not name what he calibrates.
 * spectra/services/carriers.py is the criterion, and the /devices page —
 * which answers a different question, "does this back something driven" —
 * is untouched by it.
 *
 * FUNCTION FIRST, his standing order. There is no room visualisation here
 * and deliberately no placement sketch: the map is MEASURED, and a drawing
 * of where he thinks a fixture is would be the first step toward solving
 * for fixture coordinates, which this whole design exists not to do. Each
 * emitter's state is shown as what it actually is — a small heat thumbnail
 * of its measured footprint, or the words "not mapped".
 *
 * WHAT PRESSING "Map this room" DOES TO HIS ROOM, said on the page and not
 * only in the help: the whole room goes dark, one fixture at a time comes
 * up full white for about two seconds, and the show comes back between
 * every emitter. It runs on the same held-room machinery every preview in
 * this app uses, so a dropped phone or a closed tab hands the room back on
 * its own.
 *
 * THE CAMERA STAYS ON THIS DEVICE. The page reduces each frame to a 320x180
 * greyscale image and sends only those bytes; nothing else leaves the
 * phone, and the server stores only the derived map (numbers). */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import HelpLink from '../help/HelpLink';
import { apiDel, apiGet, apiPost } from '../api/client';
import { useToast } from '../components/Toast';
import HeatThumbnail from './HeatThumbnail';
import { MappingCapture, MappingClient, type LockState, secureContextProblem } from './mappingCapture';

type PixelRange = { virtual_id: string; start: number; end: number };
type Footprint = {
  emitter_id: string;
  label: string;
  carrier_id: string;
  whole_carrier: boolean;
  ranges: PixelRange[];
  virtual_ids: string[];
  mapped: boolean;
  weight: number;
  axis_profile: number[];
  thumbnail: number[][];
  capture: Record<string, unknown>;
};
type Room = {
  id: string;
  name: string;
  carrier_ids: string[];
  axis: { kind: string; floor: { x: number; y: number } | null; ceiling: { x: number; y: number } | null };
  granularity: string;
  block_pixels: number;
  footprints: Footprint[];
  mapped_ids: string[];
  mapped_carriers: string[];
  unmapped_ids: string[];
};
type PlanEmitter = {
  emitter_id: string; carrier_id: string; label: string;
  virtual_ids: string[]; ranges: PixelRange[]; whole_carrier: boolean; note: string;
};
type RunPlan = {
  granularity: string; block_pixels: number; count: number;
  estimated_seconds: number; truncated: boolean; problems: string[];
  warnings?: string[];
  per_carrier: Record<string, string>; emitters: PlanEmitter[];
  sub_device: boolean; spectra_owns: boolean;
};
type CarrierRow = { id: string; devices: string[]; device_names: string[]; device_types: string[] };
type HiddenRow = { id: string; all_devices: string[]; reason: string };
type EmitterResult = {
  emitter_id: string; mapped: boolean; reason: string; weight: number;
  dark_frames: number; lit_frames: number; saturated_fraction: number; seconds: number;
  carrier_id: string; label: string; ranges: PixelRange[];
};
type RunResult = {
  ok: boolean; reason: string; seconds: number; emitters: EmitterResult[];
  granularity: string; block_pixels: number;
  per_carrier: Record<string, string>; problems: string[]; room?: Room;
  refusal?: string; partial?: boolean; warnings?: string[];
};

const EMPTY_AXIS = { kind: 'vertical', floor: null, ceiling: null };

/** What one capture run treats as an emitter. His own correction: a strip
 * wrapped round a television has to be mappable in PARTS, or a wave can
 * only ever dim the whole television at once. "Auto" is the shipped
 * default and resolves PER CARRIER — segments for a strip, the whole
 * carrier for a Hue bulb — so this is a choice for THIS run, never a
 * setting the system carries around. */
const GRANULARITIES: { value: string; label: string; hint: string }[] = [
  { value: 'auto', label: 'Auto', hint: 'segments for a strip, the whole fixture for a bulb' },
  { value: 'whole', label: 'Whole carrier', hint: 'one measurement each — the fastest run' },
  { value: 'segment', label: 'Segments', hint: 'one per configured run of the strip' },
  { value: 'block', label: 'Blocks', hint: 'cut every strip into equal pixel blocks' },
];

export default function RoomsPage() {
  const toast = useToast();
  const [rooms, setRooms] = useState<Room[]>([]);
  const [carriers, setCarriers] = useState<CarrierRow[]>([]);
  const [hidden, setHidden] = useState<HiddenRow[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [draftName, setDraftName] = useState('');
  const [busy, setBusy] = useState(false);
  const [run, setRun] = useState<RunResult | null>(null);
  const [plan, setPlan] = useState<RunPlan | null>(null);

  // capture
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const captureRef = useRef<MappingCapture | null>(null);
  const clientRef = useRef<MappingClient | null>(null);
  const [lock, setLock] = useState<LockState | null>(null);
  const [refusal, setRefusal] = useState<string | null>(null);
  /** A REFUSAL SENTENCE from the mapping route, shown where the run's own
   * result lands rather than as a toast: "the lights are released, take the
   * room back" is an instruction, and an instruction that scrolls away in
   * three seconds is not one. */
  const [mapRefusal, setMapRefusal] = useState<string | null>(null);
  const [cameraOn, setCameraOn] = useState(false);
  const [frames, setFrames] = useState(0);
  const [tapping, setTapping] = useState<'floor' | 'ceiling' | null>(null);

  const room = useMemo(() => rooms.find((r) => r.id === selected) ?? null, [rooms, selected]);
  const insecure = secureContextProblem();

  const loadRooms = useCallback(async () => {
    const body = await apiGet<{ rooms: Room[] }>('/rooms');
    setRooms(body.rooms);
    setSelected((cur) => cur ?? body.rooms[0]?.id ?? null);
  }, []);

  useEffect(() => {
    void loadRooms();
    void apiGet<{ carriers: CarrierRow[]; hidden: HiddenRow[] }>('/rooms/carriers')
      .then((b) => { setCarriers(b.carriers); setHidden(b.hidden ?? []); })
      .catch(() => { setCarriers([]); setHidden([]); });
  }, [loadRooms]);

  useEffect(() => () => {
    captureRef.current?.stop();
    clientRef.current?.close();
  }, []);

  const startCamera = useCallback(async () => {
    if (cameraOn) return;
    try {
      const client = new MappingClient();
      await client.connect();
      clientRef.current = client;
      client.onMessage((m) => {
        if (typeof m.refusal === 'string' || m.refusal === null) setRefusal((m.refusal as string) ?? null);
      });
      const capture = new MappingCapture(videoRef.current!, {
        onFrame: (f) => {
          setFrames((n) => n + 1);
          client.send({
            type: 'frame', mime: 'image/grey8', width: f.width, height: f.height,
            captured_at_ms: f.capturedAtMs, data: f.b64, lock: capture.lock,
          });
        },
        onLock: (l) => setLock(l),
        onError: (msg) => toast(msg, 'error'),
      });
      captureRef.current = capture;
      await capture.start(5);
      client.send({
        type: 'hello', user_agent: navigator.userAgent,
        secure_context: window.isSecureContext, lock: capture.lock,
      });
      setLock(capture.lock);
      setCameraOn(true);
    } catch (err) {
      toast(String(err), 'error');
    }
  }, [cameraOn, toast]);

  const stopCamera = useCallback(() => {
    captureRef.current?.stop();
    clientRef.current?.close();
    captureRef.current = null;
    clientRef.current = null;
    setCameraOn(false);
    setLock(null);
    setRefusal(null);
  }, []);

  /** Every save is SERIALIZED through one chain and reads the room state
   * that exists when its turn comes, not the render closure that queued it.
   * Two quick taps on two device chips used to lose the first: both handlers
   * closed over the same pre-save `room`, and the second POST overwrote the
   * first with a device list that never had it. Found by walking this page
   * in a real browser, not by reading it. */
  const roomsRef = useRef<Room[]>([]);
  roomsRef.current = rooms;
  const saveChain = useRef<Promise<unknown>>(Promise.resolve());

  const saveRoom = useCallback((
    build: (current: Room | null) => (Partial<Room> & { name: string }) | null,
    roomId?: string | null,
  ): Promise<Room | null> => {
    const next = saveChain.current.then(async () => {
      const current = roomId ? roomsRef.current.find((r) => r.id === roomId) ?? null : null;
      const patch = build(current);
      if (!patch) return null;
      setBusy(true);
      try {
        const saved = await apiPost<Room>('/rooms', {
          id: patch.id ?? roomId ?? null, name: patch.name,
          carrier_ids: patch.carrier_ids ?? [], axis: patch.axis ?? EMPTY_AXIS,
          granularity: patch.granularity ?? null,
          block_pixels: patch.block_pixels ?? null,
        });
        const body = await apiGet<{ rooms: Room[] }>('/rooms');
        roomsRef.current = body.rooms;
        setRooms(body.rooms);
        setSelected(saved.id);
        return saved;
      } catch (err) {
        toast(String(err), 'error');
        return null;
      } finally {
        setBusy(false);
      }
    });
    saveChain.current = next.catch(() => undefined);
    return next as Promise<Room | null>;
  }, [toast]);

  const toggleCarrier = useCallback((carrierId: string) => {
    const id = selected;
    if (!id) return;
    void saveRoom((current) => {
      if (!current) return null;
      const next = current.carrier_ids.includes(carrierId)
        ? current.carrier_ids.filter((c) => c !== carrierId)
        : [...current.carrier_ids, carrierId];
      return { ...current, carrier_ids: next };
    }, id);
  }, [selected, saveRoom]);

  /** The axis calibration: two taps on the live preview. Stored in
   * NORMALIZED frame coordinates, which is all the map ever wants — a
   * direction in the picture, never a height in metres. */
  const onPreviewTap = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    const which = tapping;
    const id = selected;
    if (!which || !id) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const point = {
      x: Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width)),
      y: Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height)),
    };
    setTapping(which === 'floor' ? 'ceiling' : null);
    void saveRoom((current) => (current
      ? { ...current, axis: { ...current.axis, kind: current.axis.kind || 'vertical', [which]: point } }
      : null), id);
  }, [tapping, selected, saveRoom]);

  const granularity = room?.granularity ?? 'auto';
  const blockPixels = room?.block_pixels ?? 30;

  /** The plan is a READ: it says how many emitters the current granularity
   * produces and how long the room will be dark, before he presses. A
   * nineteen-emitter run is a different act from a two-emitter one and he
   * should not learn that from a progress bar. */
  const refreshPlan = useCallback(async (id: string, g: string, block: number) => {
    try {
      setPlan(await apiGet<RunPlan>(
        `/rooms/${id}/plan?granularity=${encodeURIComponent(g)}&block_pixels=${block}`));
    } catch {
      setPlan(null);
    }
  }, []);

  useEffect(() => {
    if (!room) { setPlan(null); return; }
    void refreshPlan(room.id, granularity, blockPixels);
  }, [room?.id, room?.carrier_ids.join(','), granularity, blockPixels, refreshPlan]);

  const setGranularity = useCallback((value: string) => {
    const id = selected;
    if (!id) return;
    void saveRoom((current) => (current ? { ...current, granularity: value } : null), id);
  }, [selected, saveRoom]);

  const setBlockPixels = useCallback((value: number) => {
    const id = selected;
    if (!id || !Number.isFinite(value)) return;
    void saveRoom((current) => (
      current ? { ...current, block_pixels: Math.max(1, Math.round(value)) } : null), id);
  }, [selected, saveRoom]);

  const mapRoom = useCallback(async () => {
    if (!room) return;
    setBusy(true);
    setRun(null);
    setMapRefusal(null);
    try {
      const result = await apiPost<RunResult>(`/rooms/${room.id}/map`, {
        granularity, block_pixels: blockPixels,
      });
      setRun(result);
      if (result.reason && !result.ok) setMapRefusal(result.reason);
      if (result.room) setRooms((rs) => rs.map((r) => (r.id === result.room!.id ? result.room! : r)));
      const mapped = result.emitters.filter((e) => e.mapped).length;
      if (result.ok) toast(`Mapped ${mapped} emitter(s) in ${result.seconds}s`, 'success');
      else if (result.partial) toast(`Stopped after ${mapped} emitter(s) — the reason is on the page`, 'error');
      else toast('Mapping was refused — the reason is on the page', 'error');
    } catch (err) {
      // A named refusal arrives as `detail` on a 409 and client.ts folds it
      // into the Error message; show the sentence itself, never the code.
      const text = String(err);
      const named = text.includes(': ') ? text.slice(text.indexOf(': ') + 2) : text;
      setMapRefusal(named);
      toast('Mapping was refused — the reason is on the page', 'error');
    } finally {
      setBusy(false);
    }
  }, [room, granularity, blockPixels, toast]);

  const axisReady = !!(room?.axis.floor && room?.axis.ceiling);

  return (
    <div className="rooms-page">
      <h2>
        Rooms <HelpLink topic="room-builder" />
      </h2>
      <p className="muted rooms-lede">
        A room is the set of things you run effects on, and a MEASURED map of where each
        one&apos;s light lands. Mapping takes the room dark, lights one at a time for about
        two seconds, and photographs the result — the show comes back between every one.
      </p>

      <div className="rooms-layout">
        {/* ── rooms list ── */}
        <section className="rooms-list card">
          <h3>Rooms</h3>
          {rooms.map((r) => (
            <button
              key={r.id}
              className={`room-row ${r.id === selected ? 'active' : ''}`}
              onClick={() => { setSelected(r.id); setRun(null); }}
            >
              <span className="room-row-name">{r.name}</span>
              <span className="muted">
                {/* DEVICES, not emitters: a strip mapped per segment carries
                  * several emitter ids, and "3/1 mapped" would read as a bug. */}
                {(r.mapped_carriers ?? r.mapped_ids).length}/{r.carrier_ids.length} mapped
                {r.mapped_ids.length > (r.mapped_carriers ?? r.mapped_ids).length
                  ? ` · ${r.mapped_ids.length} emitters` : ''}
              </span>
            </button>
          ))}
          <div className="room-new">
            <input
              value={draftName}
              placeholder="New room name…"
              onChange={(e) => setDraftName(e.target.value)}
            />
            <button
              disabled={!draftName.trim() || busy}
              onClick={async () => {
                const saved = await saveRoom(() => ({
                  name: draftName.trim(), carrier_ids: [], axis: EMPTY_AXIS }));
                if (saved) setDraftName('');
              }}
            >
              + Create
            </button>
          </div>
        </section>

        {/* ── the selected room ── */}
        <section className="room-detail card">
          {!room && <p className="muted">Create a room to begin.</p>}
          {room && (
            <>
              <div className="room-detail-head">
                <input
                  className="room-name-input"
                  value={room.name}
                  onChange={(e) => setRooms((rs) => rs.map((r) => (r.id === room.id ? { ...r, name: e.target.value } : r)))}
                  onBlur={() => void saveRoom((c) => (c ? { ...c, name: room.name } : null), room.id)}
                />
                <button
                  className="danger"
                  onClick={async () => {
                    await apiDel(`/rooms/${room.id}`);
                    setSelected(null);
                    await loadRooms();
                  }}
                >
                  Delete room
                </button>
              </div>

              <h4>
                What you run effects on <HelpLink topic="room-builder-devices" />
              </h4>
              <p className="muted small">
                These are the things you address in SPECTRA — one of them can span several
                fixtures (the TV mapper reaches the backlight and both sconces), and that is
                what gets calibrated. Their spill onto the ceiling and floor is captured in
                their footprints, so those need nothing of their own.
              </p>
              <div className="device-chips">
                {carriers.map((c) => (
                  <button
                    key={c.id}
                    className={`chip ${room.carrier_ids.includes(c.id) ? 'on' : ''}`}
                    onClick={() => void toggleCarrier(c.id)}
                    title={c.device_names.length
                      ? `lights: ${c.device_names.join(', ')}`
                      : 'no fixture'}
                  >
                    {c.id}
                  </button>
                ))}
                {!carriers.length && <span className="muted">nothing to map</span>}
              </div>
              {hidden.length > 0 && (
                <p className="muted small">
                  Not listed: {hidden.map((h) => h.id).join(', ')} — nothing in its chain emits
                  light, so a camera has nothing to photograph. The Devices page still lists it.
                </p>
              )}

              <h4>
                Emitters <HelpLink topic="room-builder-what" />
              </h4>
              {/* One card per EMITTER, grouped under the carrier it belongs to.
                * A carrier mapped whole has one; a strip mapped per segment has
                * one for each pixel range, and the range is shown because it
                * is the addressing fact that distinguishes them — never a
                * position in the room. */}
              {room.carrier_ids.map((carrierId) => {
                const fps = room.footprints.filter(
                  (f) => (f.carrier_id || f.emitter_id) === carrierId);
                return (
                  <div key={carrierId} className="emitter-device">
                    {fps.length > 1 && (
                      <p className="muted small emitter-device-name">
                        {carrierId} — {fps.length} emitters
                      </p>
                    )}
                    <div className="emitter-grid">
                      {(fps.length ? fps : [null]).map((fp, i) => {
                        const range = fp?.ranges?.[0];
                        return (
                          <div key={fp?.emitter_id ?? `${carrierId}-${i}`} className="emitter-card">
                            <HeatThumbnail
                              grid={fp?.thumbnail ?? []}
                              title={fp ? `weight ${fp.weight.toFixed(1)}` : 'not mapped'}
                            />
                            <div className="emitter-meta">
                              <strong>
                                {range ? `px ${range.start}–${range.end}` : carrierId}
                              </strong>
                              {fp?.mapped ? (
                                <>
                                  <span className="muted small">weight {fp.weight.toFixed(1)}</span>
                                  {Number(fp.capture.saturated_fraction) > 0.02 && (
                                    <span className="warn small">
                                      ⚠ {(Number(fp.capture.saturated_fraction) * 100).toFixed(0)}% of frames clipped —
                                      shape is fine, weight understates this fixture
                                    </span>
                                  )}
                                </>
                              ) : (
                                <span className="muted small">not mapped</span>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
              <div className="emitter-grid">
                {!room.carrier_ids.length && <span className="muted">pick something first</span>}
              </div>
            </>
          )}
        </section>

        {/* ── the camera ── */}
        <section className="room-capture card">
          <h3>
            Capture <HelpLink topic="room-mapping-run" />
          </h3>
          {insecure && <p className="warn">{insecure}</p>}
          <div className="capture-preview" onClick={onPreviewTap}>
            {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
            <video ref={videoRef} playsInline muted />
            {room?.axis.floor && (
              <div className="axis-mark floor" style={{ left: `${room.axis.floor.x * 100}%`, top: `${room.axis.floor.y * 100}%` }}>
                floor
              </div>
            )}
            {room?.axis.ceiling && (
              <div className="axis-mark ceiling" style={{ left: `${room.axis.ceiling.x * 100}%`, top: `${room.axis.ceiling.y * 100}%` }}>
                ceiling
              </div>
            )}
            {tapping && <div className="tap-hint">tap the {tapping}</div>}
          </div>

          <div className="capture-controls">
            {!cameraOn ? (
              <button onClick={() => void startCamera()} disabled={!!insecure}>Start camera</button>
            ) : (
              <button onClick={stopCamera}>Stop camera</button>
            )}
            <button
              disabled={!room || !cameraOn}
              onClick={() => setTapping('floor')}
            >
              {axisReady ? 'Re-calibrate axis' : 'Calibrate axis (2 taps)'}
            </button>
            <HelpLink topic="room-mapping-axis" title="How the axis is calibrated" />
          </div>

          <dl className="capture-status">
            <dt>
              Camera <HelpLink topic="room-mapping-privacy" title="Where the camera goes" />
            </dt>
            <dd>{cameraOn ? `${frames} frames sent` : 'off'}</dd>
            <dt>Exposure</dt>
            <dd className={lock?.exposure_locked ? 'ok' : 'warn'}>
              {lock ? (lock.exposure_locked ? 'locked' : `${lock.exposure_mode || 'unknown'} — NOT locked`) : '—'}
            </dd>
            <dt>White balance</dt>
            <dd className={lock?.white_balance_locked ? 'ok' : 'warn'}>
              {lock ? (lock.white_balance_locked ? 'locked' : `${lock.white_balance_mode || 'unknown'} — NOT locked`) : '—'}
            </dd>
            <dt>Axis</dt>
            <dd className={axisReady ? 'ok' : 'warn'}>{axisReady ? 'calibrated' : 'not calibrated'}</dd>
          </dl>

          {refusal && <p className="warn refusal">{refusal}</p>}

          <div className="map-granularity">
            <label>
              Map in
              <select
                value={granularity}
                disabled={!room || busy}
                onChange={(e) => setGranularity(e.target.value)}
              >
                {GRANULARITIES.map((g) => (
                  <option key={g.value} value={g.value}>{g.label}</option>
                ))}
              </select>
            </label>
            <HelpLink topic="room-mapping-granularity" title="What each granularity maps" />
            {granularity === 'block' && (
              <label>
                every
                <input
                  type="number" min={1} max={4096} step={1} value={blockPixels}
                  disabled={!room || busy}
                  onChange={(e) => setBlockPixels(Number(e.target.value))}
                />
                pixels
              </label>
            )}
            <span className="muted small">
              {GRANULARITIES.find((g) => g.value === granularity)?.hint}
            </span>
          </div>

          {/* THE PLAN READOUT, ABOVE the button and sized to be read by
            * someone already reaching for it. A CHECK BEFORE THE COST BEATS
            * A MESSAGE AFTER IT: pressing this takes his room dark for up to
            * a minute, and the two facts that decide which button he wants —
            * how many pieces, how long — cannot be small grey text he passes
            * on the way past. A one-piece map for a multi-pixel strip is not
            * a smaller number but a DIFFERENT OUTCOME (no wave can travel
            * along it), so the whole panel goes to the warning state, colour
            * and sentence together, rather than reporting "1" quietly. */}
          {plan ? (
            <div className={`plan-readout${plan.warnings?.length ? ' warn-state' : ''}`}>
              <span className="plan-readout-count">
                {plan.count} piece{plan.count === 1 ? '' : 's'}
              </span>
              <span className="plan-readout-cost">
                dark for about {Math.round(plan.estimated_seconds)}s
              </span>
              {plan.warnings?.length ? (
                plan.warnings.map((w) => (
                  <span key={w} className="plan-readout-note">⚠ {w}</span>
                ))
              ) : (
                <span className="plan-readout-note muted">
                  Hold the phone still: every footprint in a map is only comparable to the
                  others taken from the same position.
                </span>
              )}
              {plan.sub_device && !plan.spectra_owns && (
                <span className="plan-readout-note warn">
                  SPECTRA is not driving the lights, so this run would be refused.
                </span>
              )}
            </div>
          ) : (
            <p className="muted small">
              The room goes dark for about {Math.max(1, (room?.carrier_ids.length ?? 1) * 4)} seconds.
              Hold the phone still: every footprint in a map is only comparable to the others taken
              from the same position.
            </p>
          )}

          <button
            className="primary"
            disabled={!room || !cameraOn || busy || !!refusal || !room.carrier_ids.length}
            onClick={() => void mapRoom()}
          >
            {busy ? 'Mapping…' : 'Map this room'}
          </button>
          {plan?.problems?.length ? (
            <ul className="warn small">
              {plan.problems.map((p) => <li key={p}>{p}</li>)}
            </ul>
          ) : null}

          {mapRefusal && !run && (
            <div className="run-result">
              <strong>Refused</strong>
              <p className="warn">{mapRefusal}</p>
            </div>
          )}
          {run && (
            <div className="run-result">
              <strong>{run.ok ? 'Mapped' : run.partial ? 'Stopped part-way' : 'Refused'}</strong>
              {run.reason && !run.ok && <p className="warn">{run.reason}</p>}
              <ul>
                {run.emitters.map((e) => (
                  <li key={e.emitter_id} className={e.mapped ? 'ok' : 'warn'}>
                    {e.label || e.emitter_id}: {e.mapped
                      ? `weight ${e.weight} · ${e.dark_frames}+${e.lit_frames} frames · ${e.seconds}s`
                      : e.reason}
                  </li>
                ))}
              </ul>
              {run.warnings?.length ? (
                <ul className="warn">
                  {run.warnings.map((w) => <li key={w}>{w}</li>)}
                </ul>
              ) : null}
              {run.problems?.length ? (
                <ul className="warn small">
                  {run.problems.map((p) => <li key={p}>{p}</li>)}
                </ul>
              ) : null}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
