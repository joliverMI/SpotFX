// The guest page (data/jukebox-plan/report.md §7, phase 2 PR 2.1): what a
// phone sees after opening tonight's party link. It asks the guest app
// (/g/…, the same origin) and draws the one view SpotFX sends back — it
// decides nothing about the night itself.
//
//   loading → idle (no night) | refused (no party link, party full) |
//             welcome (first visit: name + house rules + "Let's go") |
//             the screens (Now · Queue), with the "your song" strip, the
//             "you're next" banner (Android also buzzes), and on iPhone the
//             Add to Home Screen hint.
import { useCallback, useEffect, useRef, useState } from 'react';
import { api, storePhone, storedPhone } from './api';
import type { Refusal, RunningView, StripTone, View } from './types';
import {
  bannerFor, fromAddress, homeScreenAddress, since, stripText, tabsFor, vibration,
  wantsHomeScreenHint, type BannerKind, type Tab,
} from './logic';
import { Sheet } from './bits';
import { AddScreen, NowScreen, QueueScreen, Welcome } from './screens';

const TOKEN_KEY = 'jukebox.token';
const HINT_KEY = 'jukebox.homeHintDone';

function readSession(k: string): string | null {
  try { return sessionStorage.getItem(k); } catch { return null; }
}
function writeSession(k: string, v: string | null): void {
  try { if (v === null) sessionStorage.removeItem(k); else sessionStorage.setItem(k, v); } catch { /* */ }
}
function flag(k: string): boolean {
  try { return localStorage.getItem(k) === '1'; } catch { return false; }
}
function setFlag(k: string): void {
  try { localStorage.setItem(k, '1'); } catch { /* */ }
}

type Phase =
  | { kind: 'loading' }
  | { kind: 'idle'; view: View & { state: 'idle' } }
  | { kind: 'refused'; refusal: Refusal }
  | { kind: 'running'; view: RunningView; receivedAt: number };

const TAB_LABEL: Record<Tab, string> = { now: 'Now', queue: 'Queue', add: 'Add', board: 'Board' };
const TAB_ICON: Record<Tab, string> = { now: '♪', queue: '☰', add: '＋', board: '★' };

export default function GuestApp() {
  const [phase, setPhase] = useState<Phase>({ kind: 'loading' });
  const [tab, setTab] = useState<Tab>('now');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [banner, setBanner] = useState<BannerKind | null>(null);
  const [sheet, setSheet] = useState<'name' | 'home' | null>(null);
  const [toast, setToast] = useState('');
  const [nowMs, setNowMs] = useState(() => Date.now());
  const tapped = useRef(false);
  const lastTone = useRef<StripTone | null>(null);
  const phone = useRef<string | null>(null);
  const token = useRef<string | null>(null);
  const timer = useRef<number | undefined>(undefined);
  // how long until the next poll: what the last view asked for (15 s while
  // the page can't join — a refused link doesn't change by itself)
  const pollMs = useRef(3000);

  const show = useCallback((v: View) => {
    pollMs.current = v.poll_ms;
    if (v.state === 'idle') {
      setPhase({ kind: 'idle', view: v });
      lastTone.current = null;
      return;
    }
    const kind = bannerFor(lastTone.current, v.strip.tone);
    lastTone.current = v.strip.tone;
    if (kind) {
      setBanner(kind);
      const pattern = vibration(kind, typeof navigator.vibrate === 'function', tapped.current);
      if (pattern) navigator.vibrate(pattern);
    }
    setPhase({ kind: 'running', view: v, receivedAt: Date.now() });
  }, []);

  const hello = useCallback(async () => {
    const r = await api.hello(token.current, phone.current);
    if (!r.ok) {
      pollMs.current = r.status === 429 || r.status === 503 || r.status === 0 ? 3000 : 15000;
      setPhase({ kind: 'refused', refusal: r.refusal });
      return;
    }
    if (r.phone) {
      phone.current = r.phone;
      storePhone(r.phone);
      writeSession(TOKEN_KEY, null);
      if (window.location.search) window.history.replaceState(null, '', '/');
    }
    show(r.view);
  }, [show]);

  // ONE poll loop for the page's whole life: every poll_ms while the page is
  // visible (the view says how often), at once when it comes back into view.
  const phaseRef = useRef<Phase>(phase);
  phaseRef.current = phase;
  const tick = useCallback(async () => {
    const p = phaseRef.current;
    if (p.kind === 'running') {
      const r = await api.view();
      if (r.ok) { show(r.view); setError(''); }
      else if (r.status === 403) await hello();
      else setError(r.refusal.detail);
    } else if (p.kind !== 'loading') {
      await hello();
    }
  }, [show, hello]);
  const tickRef = useRef(tick);
  tickRef.current = tick;

  useEffect(() => {
    let stopped = false;
    const wait = () => pollMs.current;
    const loop = async () => {
      window.clearTimeout(timer.current);
      if (stopped) return;
      if (document.visibilityState !== 'hidden') await tickRef.current();
      if (!stopped) timer.current = window.setTimeout(() => { void loop(); }, wait());
    };
    const addr = fromAddress(window.location.search);
    token.current = addr.token ?? readSession(TOKEN_KEY);
    if (addr.token) writeSession(TOKEN_KEY, addr.token);
    phone.current = addr.phone ?? storedPhone();
    void hello().then(() => {
      if (!stopped) timer.current = window.setTimeout(() => { void loop(); }, wait());
    });
    const onVis = () => { if (document.visibilityState === 'visible') void loop(); };
    const onTap = () => { tapped.current = true; };
    document.addEventListener('visibilitychange', onVis);
    window.addEventListener('pointerdown', onTap, { passive: true });
    return () => {
      stopped = true;
      window.clearTimeout(timer.current);
      document.removeEventListener('visibilitychange', onVis);
      window.removeEventListener('pointerdown', onTap);
    };
  }, [hello]);

  useEffect(() => {
    const t = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, []);

  useEffect(() => {
    if (!toast) return undefined;
    const t = window.setTimeout(() => setToast(''), 5000);
    return () => window.clearTimeout(t);
  }, [toast]);

  useEffect(() => {
    if (!banner) return undefined;
    const t = window.setTimeout(() => setBanner(null), 9000);
    return () => window.clearTimeout(t);
  }, [banner]);

  const act = useCallback(async (call: () => ReturnType<typeof api.view>): Promise<boolean> => {
    setBusy(true);
    setError('');
    const r = await call();
    setBusy(false);
    if (r.ok) show(r.view);
    else if (r.status === 403 && r.refusal.reason === 'needs_link') setPhase({ kind: 'refused', refusal: r.refusal });
    else setError(r.refusal.detail);
    return r.ok;
  }, [show]);

  if (phase.kind === 'loading') {
    return <div className="g-app g-center"><p className="g-muted">Opening the Jukebox…</p></div>;
  }
  if (phase.kind === 'idle' || phase.kind === 'refused') {
    const text = phase.kind === 'idle' ? phase.view.detail : phase.refusal.detail;
    return (
      <div className="g-app g-center">
        <div className="g-message">
          <div className="g-message-icon" aria-hidden="true">♪</div>
          <h1>Jukebox</h1>
          <p>{text}</p>
          {phase.kind === 'idle' && (
            <>
              <h2 className="g-h2">House rules</h2>
              <ul className="g-rules">{phase.view.house_rules.map((r) => <li key={r}>{r}</li>)}</ul>
            </>
          )}
        </div>
      </div>
    );
  }

  const view = phase.view;
  const elapsed = since(phase.receivedAt, nowMs);
  if (!view.me.joined) {
    return (
      <div className="g-app">
        <Welcome view={view} busy={busy} error={error}
                 onShuffle={() => void act(() => api.rename(null, true))}
                 onGo={(name) => void act(() => api.join(name === view.me.name ? undefined : name))} />
      </div>
    );
  }
  const strip = stripText(view.strip, elapsed, nowMs, view.features.add);
  const tabs = tabsFor(view.features);
  const homeHint = !flag(HINT_KEY) && wantsHomeScreenHint(
    navigator.userAgent, navigator.maxTouchPoints || 0,
    window.matchMedia?.('(display-mode: standalone)').matches
      || (navigator as Navigator & { standalone?: boolean }).standalone === true);
  const openHome = () => {
    if (phone.current) window.history.replaceState(null, '', homeScreenAddress(phone.current, token.current));
    setSheet('home');
  };
  const closeSheet = () => {
    if (sheet === 'home') { window.history.replaceState(null, '', '/'); setFlag(HINT_KEY); }
    setSheet(null);
  };

  return (
    <div className="g-app">
      <header className="g-header">
        <div className="g-brand"><span aria-hidden="true">♪</span> Jukebox</div>
        <button type="button" className="g-name-chip" onClick={() => setSheet('name')}
                aria-label={`Your name: ${view.me.name}. Change it`}>
          {view.me.name}
        </button>
      </header>
      <div className={`g-strip g-strip-${strip.tone}`} role="status">
        <strong>{strip.label}</strong>
        <span>{strip.detail}</span>
      </div>
      {banner && (
        <div className={`g-banner g-banner-${banner}`} role="alert">
          <span>{banner === 'next' ? '🎵 Your song is next!' : '🎉 Your song is playing!'}</span>
          <button type="button" className="g-icon-btn" onClick={() => setBanner(null)} aria-label="Dismiss">✕</button>
        </div>
      )}
      {error && <p className="g-error g-error-bar" role="alert">{error}</p>}
      <main className="g-main">
        {tab === 'now' && (
          <NowScreen view={view} elapsedMs={elapsed} nowMs={nowMs} busy={busy}
                     onVote={(v) => void act(() => api.vote(v))}
                     homeHint={homeHint} onHomeHint={openHome} />
        )}
        {tab === 'queue' && <QueueScreen view={view} elapsedMs={elapsed} nowMs={nowMs} />}
        {tab === 'add' && (
          <AddScreen view={view} onAdded={(v, text) => { show(v); setToast(text); }} />
        )}
      </main>
      {toast && <div className="g-toast" role="status">{toast}</div>}
      <nav className="g-tabbar" aria-label="Screens">
        {tabs.map((t) => (
          <button key={t} type="button" className={`g-tab${tab === t ? ' g-tab-on' : ''}`}
                  aria-current={tab === t ? 'page' : undefined} onClick={() => setTab(t)}>
            <span className="g-tab-icon" aria-hidden="true">{TAB_ICON[t]}</span>
            <span>{TAB_LABEL[t]}</span>
          </button>
        ))}
      </nav>
      {sheet === 'name' && (
        <NameSheet view={view} busy={busy} error={error} onClose={closeSheet}
                   onSave={(name) => { void act(() => api.rename(name)).then((ok) => { if (ok) closeSheet(); }); }}
                   onShuffle={() => void act(() => api.rename(null, true))} />
      )}
      {sheet === 'home' && (
        <Sheet title="Add to Home Screen" onClose={closeSheet}>
          <p>Keep tonight's Jukebox one tap away — and the same name comes with you.</p>
          <ol className="g-steps">
            <li>Tap <strong>Share</strong> <span aria-hidden="true">(the square with an arrow)</span>.</li>
            <li>Tap <strong>Add to Home Screen</strong>, then <strong>Add</strong>.</li>
          </ol>
          <button type="button" className="g-btn g-btn-primary" onClick={closeSheet}>Done</button>
        </Sheet>
      )}
    </div>
  );
}

function NameSheet({ view, busy, error, onClose, onSave, onShuffle }: {
  view: RunningView; busy: boolean; error: string;
  onClose: () => void; onSave: (name: string) => void; onShuffle: () => void;
}) {
  const [name, setName] = useState(view.me.name);
  const left = view.me.name_locked ? 0 : view.me.renames_left;
  return (
    <Sheet title="Your name tonight" onClose={onClose}>
      <input className="g-input" value={name} maxLength={20} autoComplete="off" aria-label="Your name"
             onChange={(e) => setName(e.target.value)} disabled={left === 0 || view.me.name_locked} />
      <p className="g-muted g-small">{view.me.name_locked ? 'The host has set your name for tonight.'
        : left === 0 ? "That's all the name changes for tonight."
        : `${left} change${left === 1 ? '' : 's'} left tonight.`}</p>
      {error && <p className="g-error" role="alert">{error}</p>}
      <div className="g-sheet-actions">
        <button type="button" className="g-btn g-btn-ghost" disabled={busy || left === 0} onClick={onShuffle}>🎲 Shuffle</button>
        <button type="button" className="g-btn g-btn-primary" disabled={busy || left === 0 || name.trim() === view.me.name}
                onClick={() => onSave(name.trim())}>Save</button>
      </div>
    </Sheet>
  );
}
