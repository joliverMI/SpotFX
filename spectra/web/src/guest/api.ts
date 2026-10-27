// The guest page's five calls, all to the guest app on this same origin
// (jukebox_guest/app.py's /g/ routes — the only ones it answers). The phone
// is named by its cookie; a copy of its code in this phone's own storage
// rides along so a cleared cookie doesn't make it a stranger.
import type { Refusal, SearchResult, View } from './types';

const PHONE_KEY = 'jukebox.phone';

export function storedPhone(): string | null {
  try { return localStorage.getItem(PHONE_KEY); } catch { return null; }
}

export function storePhone(id: string): void {
  try { localStorage.setItem(PHONE_KEY, id); } catch { /* private mode: the cookie still works */ }
}

export interface Found { results: SearchResult[]; more: boolean; next_offset: number; query: string }
export interface Added { entry_id: string; title: string; starts_in_ms: number | null }

export type Answer =
  | { ok: true; view: View; phone?: string; found?: Found; added?: Added }
  | { ok: false; status: number; refusal: Refusal };

const UNREACHABLE: Refusal = {
  status: 'refused', reason: 'unavailable',
  detail: "Can't reach the Jukebox right now. Check your Wi-Fi and try again.",
};

async function call(method: 'GET' | 'POST', path: string, body?: unknown): Promise<Answer> {
  const headers: Record<string, string> = {};
  const phone = storedPhone();
  if (phone) headers['X-Guest-Phone'] = phone;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  let r: Response;
  try {
    r = await fetch(path, {
      method, headers, credentials: 'same-origin', cache: 'no-store',
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    return { ok: false, status: 0, refusal: UNREACHABLE };
  }
  let data: unknown = null;
  try { data = await r.json(); } catch { /* not JSON */ }
  const d = (data ?? {}) as Record<string, unknown>;
  if (r.ok && (d.state === 'idle' || d.status === 'ok')) {
    const view = (d.state === 'idle' ? d : d.view) as View;
    const found = Array.isArray(d.results) ? (d as unknown as Found) : undefined;
    const added = d.added && typeof d.added === 'object' ? (d.added as Added) : undefined;
    return { ok: true, view, phone: typeof d.phone === 'string' ? d.phone : undefined, found, added };
  }
  if (typeof d.reason === 'string' && typeof d.detail === 'string') {
    return { ok: false, status: r.status, refusal: d as unknown as Refusal };
  }
  return { ok: false, status: r.status, refusal: UNREACHABLE };
}

export const api = {
  hello: (token: string | null, phone: string | null) => call('POST', '/g/hello', { token, phone }),
  join: (name?: string) => call('POST', '/g/join', name === undefined ? {} : { name }),
  rename: (name: string | null, shuffle = false) =>
    call('POST', '/g/name', shuffle ? { shuffle: true } : { name }),
  vote: (vote: 'up' | 'down' | 'none') => call('POST', '/g/vote', { vote }),
  search: (q: string, offset = 0) => call('POST', '/g/search', { q, offset }),
  add: (uri: string) => call('POST', '/g/add', { uri }),
  view: () => call('GET', '/g/view'),
};
