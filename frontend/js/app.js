/**
 * SpotFX — Shared utilities and WebSocket client.
 * Imported by every page.
 */

// ── WebSocket ──────────────────────────────────────────────────────────────
const WS_URL = `ws://${location.host}/ws`;
let _ws = null;
const _listeners = {};

export function onMessage(type, fn) {
  if (!_listeners[type]) _listeners[type] = [];
  _listeners[type].push(fn);
}

function _dispatch(msg) {
  const fns = _listeners[msg.type] || [];
  fns.forEach(fn => fn(msg));
}

export function connectWS() {
  _ws = new WebSocket(WS_URL);

  _ws.onopen = () => {
    console.log('[WS] connected');
    setWsIndicator(true);
  };

  _ws.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data);
      _dispatch(msg);
    } catch (err) {
      console.warn('[WS] bad message', e.data);
    }
  };

  _ws.onclose = () => {
    setWsIndicator(false);
    // Reconnect after 3 s
    setTimeout(connectWS, 3000);
  };

  _ws.onerror = () => _ws.close();
}

export function setWsIndicator(connected) {
  const dot = document.getElementById('ws-dot');
  if (dot) dot.classList.toggle('connected', connected);
}

// ── Time formatting ────────────────────────────────────────────────────────
export function fmtMs(ms) {
  if (ms == null || isNaN(ms)) return '--:--';
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

export function fmtCountdown(ms) {
  if (ms == null || isNaN(ms) || ms < 0) return '';
  if (ms >= 10000) return `${Math.floor(ms / 1000)}s`;
  return `${(ms / 1000).toFixed(1)}s`;
}

// ── UUID (works in non-secure contexts, e.g. local IP) ─────────────────────
export function uuid() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID();
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
    const r = Math.random() * 16 | 0;
    return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16);
  });
}

// ── API helpers ────────────────────────────────────────────────────────────
export async function api(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch('/api' + path, opts);
  if (!res.ok) throw new Error(`${method} ${path} → ${res.status}`);
  return res.json();
}

export const GET  = (path)       => api('GET',    path);
export const POST = (path, body) => api('POST',   path, body);
export const DEL  = (path)       => api('DELETE', path);
export const PATCH= (path, body) => api('PATCH',  path, body);

// ── Nav active state ───────────────────────────────────────────────────────
export function markActiveNav() {
  const current = location.pathname.replace(/^\//, '') || 'index.html';
  document.querySelectorAll('nav a').forEach(a => {
    const href = a.getAttribute('href').replace(/^\//, '');
    a.classList.toggle('active', href === current || (current === '' && href === 'index.html'));
  });
}

// ── Conditional nav visibility ─────────────────────────────────────────────
GET('/settings').then(s => {
  const aiLink = document.querySelector('.nav-ai-triggers');
  if (aiLink && !s?.show_ai_triggers) aiLink.style.display = 'none';
}).catch(() => {});

// ── Toast notifications ────────────────────────────────────────────────────
export function showToast(msg, type = 'info') {
  const el = document.createElement('div');
  el.textContent = msg;
  const bg = type === 'success' ? '#2e7d32' : type === 'error' ? '#c62828' : '#1565c0';
  el.style.cssText = `position:fixed;bottom:16px;left:50%;transform:translateX(-50%);
    padding:8px 16px;border-radius:6px;font-size:13px;z-index:9999;
    background:${bg};color:#fff;box-shadow:0 2px 8px rgba(0,0,0,.4);
    white-space:nowrap;max-width:90vw;overflow:hidden;text-overflow:ellipsis;`;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

// ── Trigger flash ──────────────────────────────────────────────────────────
let _flashTimeout = null;
export function flashTrigger(color = '#FFD700') {
  const el = document.getElementById('trigger-flash');
  if (!el) return;
  el.style.background = color;
  el.style.boxShadow = `0 0 12px ${color}`;
  el.classList.add('active');
  clearTimeout(_flashTimeout);
  _flashTimeout = setTimeout(() => {
    el.classList.remove('active');
    el.style.background = '';
    el.style.boxShadow = '';
  }, 400);
}
