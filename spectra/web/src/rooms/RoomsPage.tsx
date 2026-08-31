/** ROOM BUILDER (/rooms) — name a room, pick its devices, calibrate its
 * axis with two taps on the live camera, and run a mapping sync.
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

type Footprint = {
  emitter_id: string;
  label: string;
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
  device_ids: string[];
  axis: { kind: string; floor: { x: number; y: number } | null; ceiling: { x: number; y: number } | null };
  footprints: Footprint[];
  mapped_ids: string[];
  unmapped_ids: string[];
};
type DeviceRow = { id: string; name: string; type: string; in_use: boolean; virtuals: string[] };
type EmitterResult = {
  emitter_id: string; mapped: boolean; reason: string; weight: number;
  dark_frames: number; lit_frames: number; saturated_fraction: number; seconds: number;
};
type RunResult = { ok: boolean; reason: string; seconds: number; emitters: EmitterResult[]; room?: Room };

const EMPTY_AXIS = { kind: 'vertical', floor: null, ceiling: null };

export default function RoomsPage() {
  const toast = useToast();
  const [rooms, setRooms] = useState<Room[]>([]);
  const [devices, setDevices] = useState<DeviceRow[]>([]);
  const [showAll, setShowAll] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [draftName, setDraftName] = useState('');
  const [busy, setBusy] = useState(false);
  const [run, setRun] = useState<RunResult | null>(null);

  // capture
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const captureRef = useRef<MappingCapture | null>(null);
  const clientRef = useRef<MappingClient | null>(null);
  const [lock, setLock] = useState<LockState | null>(null);
  const [refusal, setRefusal] = useState<string | null>(null);
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
    void apiGet<{ devices: DeviceRow[] }>('/rooms/devices')
      .then((b) => setDevices(b.devices))
      .catch(() => setDevices([]));
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
          device_ids: patch.device_ids ?? [], axis: patch.axis ?? EMPTY_AXIS,
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

  const toggleDevice = useCallback((deviceId: string) => {
    const id = selected;
    if (!id) return;
    void saveRoom((current) => {
      if (!current) return null;
      const next = current.device_ids.includes(deviceId)
        ? current.device_ids.filter((d) => d !== deviceId)
        : [...current.device_ids, deviceId];
      return { ...current, device_ids: next };
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

  const mapRoom = useCallback(async () => {
    if (!room) return;
    setBusy(true);
    setRun(null);
    try {
      const result = await apiPost<RunResult>(`/rooms/${room.id}/map`);
      setRun(result);
      if (result.room) setRooms((rs) => rs.map((r) => (r.id === result.room!.id ? result.room! : r)));
      toast(result.ok ? `Mapped ${result.emitters.filter((e) => e.mapped).length} emitter(s) in ${result.seconds}s`
                      : result.reason, result.ok ? 'success' : 'error');
    } catch (err) {
      toast(String(err), 'error');
    } finally {
      setBusy(false);
    }
  }, [room, toast]);

  const visibleDevices = showAll ? devices : devices.filter((d) => d.in_use);
  const axisReady = !!(room?.axis.floor && room?.axis.ceiling);

  return (
    <div className="rooms-page">
      <h2>
        Rooms <HelpLink topic="room-builder" />
      </h2>
      <p className="muted rooms-lede">
        A room is a set of fixtures and a MEASURED map of where each one&apos;s light lands.
        Mapping takes the room dark, lights one fixture at a time for about two seconds, and
        photographs the result — the show comes back between every fixture.
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
                {r.mapped_ids.length}/{r.device_ids.length} mapped
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
                  name: draftName.trim(), device_ids: [], axis: EMPTY_AXIS }));
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
                Devices <HelpLink topic="room-builder-devices" />
              </h4>
              <p className="muted small">
                Only the devices this room actually uses are listed. The two sconces on one wall
                are two emitters; their spill onto the ceiling and floor is captured in their
                footprints, so those need no fixtures of their own.
              </p>
              <div className="device-chips">
                {visibleDevices.map((d) => (
                  <button
                    key={d.id}
                    className={`chip ${room.device_ids.includes(d.id) ? 'on' : ''}`}
                    onClick={() => void toggleDevice(d.id)}
                    title={`${d.type} · ${d.virtuals.length} virtual(s)`}
                  >
                    {d.name}
                  </button>
                ))}
                {!visibleDevices.length && <span className="muted">no devices</span>}
              </div>
              <button className="link-button" onClick={() => setShowAll((v) => !v)}>
                {showAll ? 'Show only the devices in use' : `Show all ${devices.length} devices`}
              </button>

              <h4>
                Emitters <HelpLink topic="room-builder-what" />
              </h4>
              <div className="emitter-grid">
                {room.device_ids.map((id) => {
                  const fp = room.footprints.find((f) => f.emitter_id === id);
                  return (
                    <div key={id} className="emitter-card">
                      <HeatThumbnail
                        grid={fp?.thumbnail ?? []}
                        title={fp ? `weight ${fp.weight.toFixed(1)}` : 'not mapped'}
                      />
                      <div className="emitter-meta">
                        <strong>{id}</strong>
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
                {!room.device_ids.length && <span className="muted">pick some devices first</span>}
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

          <button
            className="primary"
            disabled={!room || !cameraOn || busy || !!refusal || !room.device_ids.length}
            onClick={() => void mapRoom()}
          >
            {busy ? 'Mapping…' : 'Map this room'}
          </button>
          <p className="muted small">
            The room goes dark for about {Math.max(1, (room?.device_ids.length ?? 1) * 4)} seconds.
            Hold the phone still: every footprint in a map is only comparable to the others taken
            from the same position.
          </p>

          {run && (
            <div className="run-result">
              <strong>{run.ok ? 'Mapped' : 'Refused'}</strong>
              {run.reason && <p className="warn small">{run.reason}</p>}
              <ul>
                {run.emitters.map((e) => (
                  <li key={e.emitter_id} className={e.mapped ? 'ok' : 'warn'}>
                    {e.emitter_id}: {e.mapped
                      ? `weight ${e.weight} · ${e.dark_frames}+${e.lit_frames} frames · ${e.seconds}s`
                      : e.reason}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
