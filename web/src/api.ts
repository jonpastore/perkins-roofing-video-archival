import { getIdToken } from "./auth";

const BASE = import.meta.env.VITE_API_BASE as string;

// Fetch the API with the Firebase ID token. If the token has expired (401), force a
// refresh and retry once — so a long-open tab never gets stuck on stale-token 401s.
export async function apiFetch(
  path: string,
  options: RequestInit = {}
): Promise<Response> {
  const call = async (forceRefresh: boolean) => {
    const token = await getIdToken(forceRefresh);
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      ...(options.headers as Record<string, string>),
    };
    if (token) headers["Authorization"] = `Bearer ${token}`;
    return fetch(`${BASE}${path}`, { ...options, headers });
  };

  let res = await call(false);
  if (res.status === 401) res = await call(true); // token likely expired — refresh + retry
  return res;
}

/** Like apiFetch but does NOT set Content-Type — required for multipart/form-data uploads
 *  so the browser can set the boundary automatically. */
export async function apiFetchMultipart(
  path: string,
  options: RequestInit = {}
): Promise<Response> {
  const call = async (forceRefresh: boolean) => {
    const token = await getIdToken(forceRefresh);
    const headers: Record<string, string> = {
      ...(options.headers as Record<string, string>),
    };
    if (token) headers["Authorization"] = `Bearer ${token}`;
    return fetch(`${BASE}${path}`, { ...options, headers });
  };

  let res = await call(false);
  if (res.status === 401) res = await call(true);
  return res;
}
