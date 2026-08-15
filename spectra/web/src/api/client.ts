/** Fetch wrappers. SPECTRA's own API lives under /spectra/api; the two
 * spotfx* helpers reach the spot-effects app's supported surface (colour
 * sets read + the global opt-out toggle) while the apps share an origin —
 * the S2 bridge formalizes that feed. */

async function call<T>(method: string, url: string, body?: unknown): Promise<T> {
  const opts: RequestInit = { method, headers: { 'Content-Type': 'application/json' } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch(url, opts);
  if (!res.ok) {
    const detail = await errorDetail(res);
    throw new Error(`${method} ${url} → ${res.status}${detail ? `: ${detail}` : ''}`);
  }
  return res.json() as Promise<T>;
}

async function errorDetail(res: Response): Promise<string> {
  const data = (await res.json().catch(() => null)) as
    { detail?: unknown; error?: unknown } | null;
  // FastAPI's default HTTPException body uses "detail"; the ownership/
  // handover route's own JSONResponse (HandoverRefused/HandoverFailed,
  // 412/502) uses "error" instead — without this fallback those named
  // refusals ("spot-effects activation not verified — 2 virtual(s)...")
  // were silently dropped and the toast showed only a bare status code.
  const detail = data?.detail ?? data?.error;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => (typeof (d as { msg?: unknown })?.msg === 'string' ? (d as { msg: string }).msg : JSON.stringify(d)))
      .join('; ');
  }
  return '';
}

export const apiGet = <T = unknown>(path: string) => call<T>('GET', '/spectra/api' + path);
export const apiPost = <T = unknown>(path: string, body?: unknown) => call<T>('POST', '/spectra/api' + path, body);
export const apiPut = <T = unknown>(path: string, body?: unknown) => call<T>('PUT', '/spectra/api' + path, body);
export const apiDel = <T = unknown>(path: string) => call<T>('DELETE', '/spectra/api' + path);

/** Multipart upload — only the settings-console voice seam uses this today
 * (POST /settings-console/transcribe, an audio blob). */
export async function apiPostForm<T = unknown>(path: string, form: FormData): Promise<T> {
  const url = '/spectra/api' + path;
  const res = await fetch(url, { method: 'POST', body: form });
  if (!res.ok) {
    const detail = await errorDetail(res);
    throw new Error(`POST ${url} → ${res.status}${detail ? `: ${detail}` : ''}`);
  }
  return res.json() as Promise<T>;
}

export const spotfxGet = <T = unknown>(path: string) => call<T>('GET', '/api' + path);
export const spotfxPost = <T = unknown>(path: string, body?: unknown) => call<T>('POST', '/api' + path, body);
