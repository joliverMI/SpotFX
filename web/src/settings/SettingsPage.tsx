/** Settings — global config editor (port of frontend/settings.html).
 * Draft-based: fields edit a local copy, "Save Settings" PATCHes /settings.
 * Advanced-only cards follow the live "Show advanced controls" checkbox. */
import { useEffect, useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, apiGet, apiPost } from '../api/client';
import { useToast } from '../components/Toast';
import HelpLink from '../help/HelpLink';
import { useLongPress } from '../lib/useLongPress';
import { buildGradientCss, parseCssGradient, type Stop } from '../colorsets/GradientModal';
import { useGradientMutations, useGradients } from '../colorsets/queries';

type Draft = Record<string, unknown>;

function Field({ label, children }: { label: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="field">
      <label>{label}</label>
      {children}
    </div>
  );
}

export default function SettingsPage() {
  const toast = useToast();
  const { data: settings } = useQuery({
    queryKey: ['settings'],
    queryFn: () => apiGet<Record<string, unknown>>('/settings'),
    staleTime: 0,
  });
  const qc = useQueryClient();
  const { data: categories = [] } = useQuery({
    queryKey: ['device-categories'],
    queryFn: () => apiGet<{ id: string; name: string }[]>('/device-categories'),
  });

  const [draft, setDraft] = useState<Draft | null>(null);
  useEffect(() => {
    if (settings && !draft) setDraft({ ...settings });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settings]);

  const [savedFlash, setSavedFlash] = useState(false);
  const longPress = useLongPress(500);
  const [restarting, setRestarting] = useState(false);
  const [holdingRestart, setHoldingRestart] = useState(false);

  const set = (k: string, v: unknown) => setDraft((d) => (d ? { ...d, [k]: v } : d));
  const str = (k: string, fb = '') => String(draft?.[k] ?? fb);
  const num = (k: string, fb = 0) => Number(draft?.[k] ?? fb);
  const bool = (k: string, fb = false) => Boolean(draft?.[k] ?? fb);

  const advanced = bool('show_advanced');
  const songSource = str('song_source', 'spotify');
  const sourceChanged = settings && songSource !== String(settings.song_source ?? 'spotify');

  // Ambient stored value may be a category id or (legacy) name — match either.
  const ambientCatId = useMemo(() => {
    const stored = str('ambient_target_category');
    return categories.find((c) => c.id === stored || c.name === stored)?.id ?? '';
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft?.ambient_target_category, categories]);

  const save = async () => {
    if (!draft) return;
    try {
      await api('PATCH', '/settings', {
        audio_latency_ms: num('audio_latency_ms'),
        ledfx_trigger_buffer_ms: num('ledfx_trigger_buffer_ms'),
        builder_zoom_window_s: num('builder_zoom_window_s'),
        builder_future_buffer_s: num('builder_future_buffer_s'),
        audio_input_device: str('audio_input_device'),
        song_source: songSource,
        spotify_device_name: str('spotify_device_name'),
        spotipy_client_id: str('spotipy_client_id'),
        spotipy_client_secret: str('spotipy_client_secret'),
        spotipy_redirect_uri: str('spotipy_redirect_uri'),
        lastfm_api_key: str('lastfm_api_key'),
        lastfm_username: str('lastfm_username'),
        ledfx_host: str('ledfx_host'),
        ledfx_port: num('ledfx_port'),
        shape_scale_overall: num('shape_scale_overall', 1),
        shape_scale_total: num('shape_scale_total', 1),
        shape_scale_bass: num('shape_scale_bass', 1),
        shape_scale_mid: num('shape_scale_mid', 1),
        shape_scale_high: num('shape_scale_high', 1),
        audio_analysis_max_songs: num('audio_analysis_max_songs'),
        audio_wav_max_songs: num('audio_wav_max_songs', 50),
        shape_average_window_ms: num('shape_average_window_ms', 500),
        smooth_ramp_ms: num('smooth_ramp_ms'),
        auto_generate_mode: str('auto_generate_mode', 'embedded'),
        show_ai_triggers: bool('show_ai_triggers'),
        show_advanced: bool('show_advanced'),
        suppress_triggers_during_capture: bool('suppress_triggers_during_capture', true),
        xcorr_monitor_enabled: bool('xcorr_monitor_enabled', true),
        ambient_target_category: ambientCatId,
        ambient_color_mode: str('ambient_color_mode', 'white'),
        ambient_kelvin: num('ambient_kelvin', 2700),
        ambient_color: str('ambient_color', '#ffffff'),
        ambient_brightness: num('ambient_brightness', 100),
      });
      void qc.invalidateQueries({ queryKey: ['settings'] });
      setSavedFlash(true);
      setTimeout(() => setSavedFlash(false), 2000);
    } catch (e) {
      toast(`Save failed: ${e instanceof Error ? e.message : e}`, 'error');
    }
  };

  if (!draft) return <p className="empty-note">Loading settings…</p>;

  return (
    <>
      <div className="card">
        <div className="card-title">Navigation</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 13 }}>
            <input type="checkbox" checked={bool('show_ai_triggers')}
              onChange={(e) => set('show_ai_triggers', e.target.checked)} />
            Show AI Triggers page
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 13 }}>
            <input type="checkbox" checked={advanced}
              onChange={(e) => set('show_advanced', e.target.checked)} />
            Show advanced controls
          </label>
        </div>
      </div>

      <div className="card">
        <div className="card-title">Latency &amp; Timing</div>
        <Field label="Audio Latency (ms) — offset between captured audio and Spotify timestamp">
          <input type="number" step={50} value={num('audio_latency_ms')}
            onChange={(e) => set('audio_latency_ms', parseInt(e.target.value) || 0)} />
        </Field>
        <Field label="LedFX Trigger Buffer (ms) — positive = fire earlier, negative = later">
          <input type="number" step={10} value={num('ledfx_trigger_buffer_ms')}
            onChange={(e) => set('ledfx_trigger_buffer_ms', parseInt(e.target.value) || 0)} />
        </Field>
        <Field label="Smooth ramp duration (ms) — global default for brightness & effect ramps; 0 = instant">
          <input type="number" step={50} min={0} value={num('smooth_ramp_ms')}
            onChange={(e) => set('smooth_ramp_ms', parseInt(e.target.value) || 0)} />
        </Field>
        {advanced && (
          <Field label="Auto-generate mode — method used when audio capture completes">
            <select value={str('auto_generate_mode', 'embedded')}
              onChange={(e) => set('auto_generate_mode', e.target.value)}>
              <option value="embedded">Embedded (free, local KNN — auto-applies triggers)</option>
              <option value="claude">Claude AI (paid API — saves suggestion set for review)</option>
            </select>
          </Field>
        )}
      </div>

      {advanced && (
        <div className="card">
          <div className="card-title">Builder</div>
          <Field label="Zoom Window (seconds)">
            <input type="number" min={5} max={120} value={num('builder_zoom_window_s')}
              onChange={(e) => set('builder_zoom_window_s', parseInt(e.target.value) || 0)} />
          </Field>
          <Field label="Lookahead after playhead in zoom mode (seconds)">
            <input type="number" min={1} max={30} value={num('builder_future_buffer_s')}
              onChange={(e) => set('builder_future_buffer_s', parseInt(e.target.value) || 0)} />
          </Field>
        </div>
      )}

      {advanced && (
        <div className="card">
          <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            Audio Shape Display Scales
            <HelpLink topic="settings-timing" title="Graph scale help" />
          </div>
          {([['shape_scale_overall', 'Overall (applies to all layers)'], ['shape_scale_total', 'Total'],
             ['shape_scale_bass', 'Bass'], ['shape_scale_mid', 'Mids'], ['shape_scale_high', 'Highs']] as const)
            .map(([k, label]) => (
              <Field key={k} label={label}>
                <input type="number" min={0.1} max={20} step={0.1} value={num(k, 1)}
                  onChange={(e) => set(k, parseFloat(e.target.value) || 1)} />
              </Field>
            ))}
        </div>
      )}

      {advanced && (
        <div className="card">
          <div className="card-title">Audio Capture</div>
          <Field label={'Audio Input Device ("default" or device name/index)'}>
            <input type="text" value={str('audio_input_device')} style={{ width: '100%' }}
              onChange={(e) => set('audio_input_device', e.target.value)} />
          </Field>
          <Field label="Audio Analysis Max Songs per Session (0 = unlimited)">
            <input type="number" min={0} step={1} value={num('audio_analysis_max_songs')}
              onChange={(e) => set('audio_analysis_max_songs', parseInt(e.target.value) || 0)} />
          </Field>
          <Field label="WAV Files Retained (oldest deleted past this count; 0 = unlimited)">
            <input type="number" min={0} step={1} value={num('audio_wav_max_songs', 50)}
              onChange={(e) => set('audio_wav_max_songs', parseInt(e.target.value) || 0)} />
          </Field>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 13, marginBottom: 8 }}>
            <input type="checkbox" checked={bool('suppress_triggers_during_capture', true)}
              onChange={(e) => set('suppress_triggers_during_capture', e.target.checked)} />
            Suppress Triggers During Capture
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 13 }}>
            <input type="checkbox" checked={bool('xcorr_monitor_enabled', true)}
              onChange={(e) => set('xcorr_monitor_enabled', e.target.checked)} />
            Whole-song Sync Monitor (auto re-lock on drift)
          </label>
        </div>
      )}

      {advanced && (
        <div className="card">
          <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            Audio Shape Graph Averaging
            <HelpLink topic="settings-timing" title="Graph averaging help" />
          </div>
          <Field label="Average Window (ms)">
            <input type="number" min={50} max={5000} step={50} value={num('shape_average_window_ms', 500)}
              onChange={(e) => set('shape_average_window_ms', parseInt(e.target.value) || 500)} />
          </Field>
        </div>
      )}

      <div className="card">
        <div className="card-title">Song Source</div>
        <div style={{ display: 'flex', gap: 8, marginBottom: 14 }}>
          <button type="button" className={`toggle-btn ${songSource === 'spotify' ? 'active' : ''}`}
            onClick={() => set('song_source', 'spotify')}>
            Spotify API
          </button>
          <button type="button" className={`toggle-btn ${songSource === 'ledfx' ? 'active' : ''}`}
            onClick={() => set('song_source', 'ledfx')}>
            LedFX <span style={{ fontSize: 10, opacity: 0.7 }}>event-driven</span>
          </button>
        </div>
        {sourceChanged && (
          <p style={{ fontSize: 12, color: '#e6a817', margin: '0 0 10px' }}>
            Restart SpotFX for this change to take effect.
          </p>
        )}
        {songSource === 'spotify' ? (
          <>
            <Field label="Target Device Name">
              <input type="text" value={str('spotify_device_name')} style={{ width: '100%' }}
                onChange={(e) => set('spotify_device_name', e.target.value)} />
            </Field>
            <Field label="Client ID">
              <input type="text" placeholder="From Spotify Developer Dashboard" value={str('spotipy_client_id')} style={{ width: '100%' }}
                onChange={(e) => set('spotipy_client_id', e.target.value)} />
            </Field>
            <Field label="Client Secret">
              <input type="password" placeholder="From Spotify Developer Dashboard" value={str('spotipy_client_secret')} style={{ width: '100%' }}
                onChange={(e) => set('spotipy_client_secret', e.target.value)} />
            </Field>
            <Field label="Redirect URI">
              <input type="text" placeholder="http://127.0.0.1:8000/api/spotify/callback" value={str('spotipy_redirect_uri')} style={{ width: '100%' }}
                onChange={(e) => set('spotipy_redirect_uri', e.target.value)} />
            </Field>
          </>
        ) : (
          <>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 10 }}>
              Genres are sourced from Last.fm when not using the Spotify API.
            </div>
            <Field label={
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                Last.fm API Key
                <HelpLink topic="settings-lastfm" title="How to get a key" />
              </span>
            }>
              <input type="text" placeholder="Paste your API key here" value={str('lastfm_api_key')} style={{ width: '100%' }}
                onChange={(e) => set('lastfm_api_key', e.target.value)} />
            </Field>
            <Field label={<>Last.fm Username <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>(optional)</span></>}>
              <input type="text" placeholder="Your Last.fm username" value={str('lastfm_username')} style={{ width: '100%' }}
                onChange={(e) => set('lastfm_username', e.target.value)} />
            </Field>
          </>
        )}
      </div>

      <div className="card">
        <div className="card-title">LedFX</div>
        <Field label="Host (e.g. http://localhost)">
          <input type="text" value={str('ledfx_host')} style={{ width: '100%' }}
            onChange={(e) => set('ledfx_host', e.target.value)} />
        </Field>
        <Field label="Port">
          <input type="number" value={num('ledfx_port')}
            onChange={(e) => set('ledfx_port', parseInt(e.target.value) || 0)} />
        </Field>
        <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
          LedFX base URL: {String(settings?.ledfx_base_url ?? '')}
        </div>
      </div>

      <div className="card">
        <div className="card-title">Ambient Mode</div>
        <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>
          When the front-page (or Home Assistant) "Ambient" toggle is on, the chosen device
          category is held at this color at full brightness via the Hue REST API and excluded
          from music triggers.
        </div>
        <Field label="Target device category">
          <select value={ambientCatId} onChange={(e) => set('ambient_target_category', e.target.value)}>
            <option value="">— none —</option>
            {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </Field>
        <Field label="Color mode">
          <select value={str('ambient_color_mode', 'white')}
            onChange={(e) => set('ambient_color_mode', e.target.value)}>
            <option value="white">White temperature</option>
            <option value="color">Color</option>
          </select>
        </Field>
        {str('ambient_color_mode', 'white') === 'white' ? (
          <Field label={`White temperature (K): ${num('ambient_kelvin', 2700)}`}>
            <input type="range" min={2000} max={6500} step={100} value={num('ambient_kelvin', 2700)}
              style={{ width: '100%', accentColor: 'var(--accent)' }}
              onChange={(e) => set('ambient_kelvin', parseInt(e.target.value))} />
          </Field>
        ) : (
          <Field label="Color">
            <input type="color" value={str('ambient_color', '#ffffff')} style={{ width: 48, height: 30, padding: 1 }}
              onChange={(e) => set('ambient_color', e.target.value)} />
          </Field>
        )}
        <Field label={`Brightness (%): ${num('ambient_brightness', 100)}`}>
          <input type="range" min={1} max={100} step={1} value={num('ambient_brightness', 100)}
            style={{ width: '100%', accentColor: 'var(--accent)' }}
            onChange={(e) => set('ambient_brightness', parseInt(e.target.value))} />
        </Field>
      </div>

      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginBottom: 16 }}>
        <button className="primary" onClick={() => void save()}>Save Settings</button>
        {savedFlash && <span style={{ fontSize: 13, color: 'var(--accent)' }}>Saved!</span>}
        <RestartButton
          restarting={restarting}
          holding={holdingRestart}
          setHolding={setHoldingRestart}
          longPress={longPress}
          onFire={async () => {
            setHoldingRestart(false);
            setRestarting(true);
            try { await apiPost('/settings/restart'); } catch { /* server going down */ }
          }}
        />
      </div>

      <GradientProfiles />

    </>
  );
}

/** Hold-to-restart: composes the long-press handlers with the fill animation. */
function RestartButton({ restarting, holding, setHolding, longPress, onFire }: {
  restarting: boolean;
  holding: boolean;
  setHolding: (v: boolean) => void;
  longPress: ReturnType<typeof useLongPress>;
  onFire: () => void;
}) {
  const lp = longPress(onFire);
  return (
    <button
      className="danger"
      disabled={restarting}
      title="Hold 500ms to restart the SpotFX service"
      style={{
        position: 'relative', overflow: 'hidden', userSelect: 'none',
        backgroundImage: 'linear-gradient(var(--danger), var(--danger))',
        backgroundRepeat: 'no-repeat',
        backgroundSize: holding ? '100% 100%' : '0% 100%',
        transition: holding ? 'background-size 500ms linear' : 'background-size 150ms linear',
        color: holding ? '#fff' : undefined,
      }}
      {...lp}
      onPointerDown={(e) => { setHolding(true); lp.onPointerDown(e); }}
      onPointerUp={(e) => { setHolding(false); lp.onPointerUp(); void e; }}
      onPointerLeave={(e) => { setHolding(false); lp.onPointerLeave(); void e; }}
    >
      {restarting ? 'Restarting…' : 'Restart SpotFX'}
    </button>
  );
}

// ── Gradient Profiles (shared /gradients library, inline editor) ─────────────
function GradientProfiles() {
  const toast = useToast();
  const { data: gradients = [] } = useGradients();
  const { create, update, remove } = useGradientMutations();

  const [editId, setEditId] = useState<string | null | 'new'>(null);
  const [name, setName] = useState('');
  const [dir, setDir] = useState('90');
  const [stops, setStops] = useState<Stop[]>([]);

  const openEdit = (id: string) => {
    const g = gradients.find((x) => x.id === id);
    if (!g) return;
    setEditId(id);
    setName(g.name);
    const dm = g.value.match(/linear-gradient\((\d+)deg/);
    setDir(dm ? dm[1] : '90');
    setStops(parseCssGradient(g.value));
  };
  const openNew = () => {
    setEditId('new');
    setName('');
    setDir('90');
    setStops([{ color: '#ff0000', pos: 0 }, { color: '#0000ff', pos: 100 }]);
  };

  const css = buildGradientCss(dir, stops);
  const setStop = (i: number, patch: Partial<Stop>) =>
    setStops((s) => s.map((st, j) => (j === i ? { ...st, ...patch } : st)));

  const saveGrad = async () => {
    if (!name.trim()) { toast('Enter a gradient name.', 'error'); return; }
    try {
      if (editId && editId !== 'new') await update.mutateAsync({ id: editId, name: name.trim(), value: css });
      else await create.mutateAsync({ name: name.trim(), value: css });
      setEditId(null);
    } catch (e) {
      toast(`Save failed: ${e}`, 'error');
    }
  };
  const deleteGrad = async () => {
    if (!editId || editId === 'new' || !confirm('Delete this gradient?')) return;
    await remove.mutateAsync(editId);
    setEditId(null);
  };

  return (
    <div className="card" style={{ marginTop: 16 }}>
      <div className="card-title">Gradient Profiles</div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, alignItems: 'start' }}>
        <div>
          <button className="primary" style={{ fontSize: 12 }} onClick={openNew}>+ New Gradient</button>
          <div style={{ marginTop: 10 }}>
            {!gradients.length && (
              <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>No gradients saved yet.</div>
            )}
            {gradients.map((g) => (
              <div key={g.id} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                <div style={{ width: 70, height: 24, borderRadius: 3, background: g.value, flexShrink: 0, border: '1px solid var(--border)' }} />
                <span style={{ flex: 1, fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{g.name}</span>
                <button style={{ fontSize: 12 }} onClick={() => openEdit(g.id)}>Edit</button>
              </div>
            ))}
          </div>
        </div>
        {editId !== null && (
          <div>
            <Field label="Name">
              <input type="text" placeholder="e.g. Red to Blue" value={name} style={{ width: '100%' }}
                onChange={(e) => setName(e.target.value)} />
            </Field>
            <Field label="Direction">
              <select value={dir} onChange={(e) => setDir(e.target.value)} style={{ width: '100%' }}>
                <option value="90">→ Horizontal (90°)</option>
                <option value="0">↑ Vertical (0°)</option>
                <option value="45">↘ Diagonal (45°)</option>
                <option value="135">↙ Diagonal (135°)</option>
                <option value="180">← Reverse (180°)</option>
              </select>
            </Field>
            <Field label="Color Stops">
              <>
                {stops.map((st, i) => (
                  <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                    <input type="color" value={st.color} style={{ width: 40, height: 28, padding: 1 }}
                      onChange={(e) => setStop(i, { color: e.target.value })} />
                    <input type="number" value={st.pos} min={0} max={100} style={{ width: 60 }}
                      onChange={(e) => setStop(i, { pos: parseInt(e.target.value) || 0 })} />
                    <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>%</span>
                    <button className="danger" style={{ fontSize: 11, padding: '2px 8px' }}
                      onClick={() => setStops((sx) => sx.filter((_, j) => j !== i))}>✕</button>
                  </div>
                ))}
                <button style={{ fontSize: 12, marginTop: 6 }}
                  onClick={() => setStops((sx) => [...sx, { color: '#ffffff', pos: 50 }])}>
                  + Add Stop
                </button>
              </>
            </Field>
            <Field label="Preview">
              <div style={{ height: 40, borderRadius: 'var(--radius)', border: '1px solid var(--border)', background: css }} />
            </Field>
            <Field label="CSS Value (read-only)">
              <input type="text" readOnly value={css} style={{ width: '100%', fontSize: 11, color: 'var(--text-muted)' }} />
            </Field>
            <div style={{ display: 'flex', gap: 8, marginTop: 8, alignItems: 'center' }}>
              <button className="primary" style={{ fontSize: 12 }} onClick={() => void saveGrad()}>Save</button>
              <button style={{ fontSize: 12 }} onClick={() => setEditId(null)}>Cancel</button>
              {editId !== 'new' && (
                <button className="danger" style={{ fontSize: 12, marginLeft: 'auto' }} onClick={() => void deleteGrad()}>Delete</button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
