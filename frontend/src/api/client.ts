import { useCallback, useEffect, useRef, useState } from "react";

const BASE = "/api/v1";

/* ---------------------------------------------------------------------------
   The session token.

   Held in localStorage so a refresh does not sign the trader out, and read
   through a function rather than captured once - a token issued after this
   module loaded must be the one that gets sent.
   --------------------------------------------------------------------------- */

const TOKEN_KEY = "steeldesk.token";

export const token = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (value: string) => localStorage.setItem(TOKEN_KEY, value),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

/** Called when the server says a session is over, so the app can react once
 *  rather than every failing request handling it separately. */
let onSessionExpired: (() => void) | null = null;
export function setSessionExpiredHandler(handler: () => void) {
  onSessionExpired = handler;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const auth = token.get();
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(auth ? { Authorization: `Bearer ${auth}` } : {}),
      ...(init?.headers ?? {}),
    },
  });

  if (response.status === 401) {
    // The token is gone, expired, or was invalidated by a password change.
    // Clearing it here means no later request retries with a token the
    // server has already rejected.
    token.clear();
    onSessionExpired?.();
  }

  if (!response.ok) {
    // FastAPI puts the useful message in `detail`; surface it rather than
    // a bare status code, because these are messages meant for the reviewer.
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* keep the fallback */
    }
    throw new ApiError(detail, response.status);
  }

  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

export const api = {
  get: <T,>(path: string) => request<T>(path),
  post: <T,>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: JSON.stringify(body ?? {}) }),
  put: <T,>(path: string, body?: unknown) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(body ?? {}) }),
  patch: <T,>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body ?? {}) }),
  del: <T,>(path: string) => request<T>(path, { method: "DELETE" }),
};

interface ApiState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

/** Fetch on mount and whenever `path` changes, with a manual reload. */
export function useApi<T>(path: string | null, pollMs?: number): ApiState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(Boolean(path));
  const [tick, setTick] = useState(0);
  const active = useRef(true);

  const reload = useCallback(() => setTick((n) => n + 1), []);

  useEffect(() => {
    active.current = true;
    if (!path) {
      setLoading(false);
      return;
    }

    setLoading(true);
    api
      .get<T>(path)
      .then((result) => {
        if (active.current) {
          setData(result);
          setError(null);
        }
      })
      .catch((err: Error) => active.current && setError(err.message))
      .finally(() => active.current && setLoading(false));

    return () => {
      active.current = false;
    };
  }, [path, tick]);

  useEffect(() => {
    if (!pollMs || !path) return;
    const timer = setInterval(reload, pollMs);
    return () => clearInterval(timer);
  }, [pollMs, path, reload]);

  return { data, error, loading, reload };
}

/** Build a query string, omitting empty values. */
export function query(params: Record<string, string | number | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const encoded = search.toString();
  return encoded ? `?${encoded}` : "";
}
