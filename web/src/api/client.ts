/** Fetch wrappers — port of frontend/js/app.js api helpers. All paths are relative to /api. */

export async function api<T = unknown>(method: string, path: string, body?: unknown): Promise<T> {
  const opts: RequestInit = { method, headers: { 'Content-Type': 'application/json' } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch('/api' + path, opts);
  if (!res.ok) throw new Error(`${method} ${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

export const apiGet = <T = unknown>(path: string) => api<T>('GET', path);
export const apiPost = <T = unknown>(path: string, body?: unknown) => api<T>('POST', path, body);
export const apiDel = <T = unknown>(path: string) => api<T>('DELETE', path);
