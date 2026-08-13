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

export const apiGet = <T = unknown>(path: string) => call<T>('GET', '/spectra/api' + path);
export const apiPost = <T = unknown>(path: string, body?: unknown) => call<T>('POST', '/spectra/api' + path, body);
export const apiPut = <T = unknown>(path: string, body?: unknown) => call<T>('PUT', '/spectra/api' + path, body);
export const apiDel = <T = unknown>(path: string) => call<T>('DELETE', '/spectra/api' + path);

export const spotfxGet = <T = unknown>(path: string) => call<T>('GET', '/api' + path);
export const spotfxPost = <T = unknown>(path: string, body?: unknown) => call<T>('POST', '/api' + path, body);
