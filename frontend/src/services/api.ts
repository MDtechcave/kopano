const API = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '');
export const TOKEN_KEY = 'tradeline_access_token';

export async function api<T>(path: string, options: RequestInit = {}, token?: string | null): Promise<T> {
  const headers = new Headers(options.headers || {});
  if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  if (token) headers.set('Authorization', `Bearer ${token}`);
  let response: Response;
  try { response = await fetch(`${API}${path}`, { ...options, headers }); }
  catch { throw new Error('Could not reach the Kopano API. Make sure the backend is running at http://localhost:8000.'); }
  if (!response.ok) {
    let message = `Request failed (${response.status}).`;
    try { const body = await response.json(); message = typeof body.detail === 'string' ? body.detail : Array.isArray(body.detail) ? body.detail.map((x: { msg?: string }) => x.msg).join(' ') : message; } catch { /* response had no JSON */ }
    if (response.status === 401 && token) { localStorage.removeItem(TOKEN_KEY); window.dispatchEvent(new Event('tradeline:session-expired')); }
    throw new Error(message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
