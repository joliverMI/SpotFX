/** Fetch wrappers — port of frontend/js/app.js api helpers. All paths are relative to /api. */

export async function api<T = unknown>(method: string, path: string, body?: unknown): Promise<T> {
  const opts: RequestInit = { method, headers: { 'Content-Type': 'application/json' } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch('/api' + path, opts);
  if (!res.ok) {
    const detail = await errorDetail(res);
    throw new Error(`${method} ${path} → ${res.status}${detail ? `: ${detail}` : ''}`);
  }
  return res.json() as Promise<T>;
}

/** FastAPI error bodies carry {detail}: a string for HTTPException, an array of
 * {msg, ...} for request-validation (422) errors. */
async function errorDetail(res: Response): Promise<string> {
  const data = (await res.json().catch(() => null)) as { detail?: unknown } | null;
  const detail = data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => (typeof (d as { msg?: unknown })?.msg === 'string' ? (d as { msg: string }).msg : JSON.stringify(d)))
      .join('; ');
  }
  return '';
}

export const apiGet = <T = unknown>(path: string) => api<T>('GET', path);
export const apiPost = <T = unknown>(path: string, body?: unknown) => api<T>('POST', path, body);
export const apiPut = <T = unknown>(path: string, body?: unknown) => api<T>('PUT', path, body);
export const apiDel = <T = unknown>(path: string) => api<T>('DELETE', path);
