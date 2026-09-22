/** Thin client for the backend's cookie-based session auth (see
 * backend/web_trx/auth.py). `credentials: "same-origin"` is what makes
 * the httpOnly session cookie actually get sent/stored -- fetch() drops
 * cookies by default. */

export async function checkSession(): Promise<boolean> {
  const res = await fetch("/session", { credentials: "same-origin" });
  if (!res.ok) return false;
  const data = (await res.json()) as { authenticated: boolean };
  return data.authenticated === true;
}

export async function login(password: string): Promise<void> {
  const res = await fetch("/login", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });
  if (!res.ok) {
    throw new Error(res.status === 401 ? "Falsches Passwort" : `Login fehlgeschlagen (${res.status})`);
  }
}

export async function logout(): Promise<void> {
  await fetch("/logout", { method: "POST", credentials: "same-origin" });
}

export interface TxLogEntry {
  id: number;
  started_at: number;
  ended_at: number | null;
  mode: string;
  freq_hz: number | null;
  device_type: string | null;
  connection: string | null;
  params: Record<string, unknown>;
}

export async function fetchTxLog(limit = 20): Promise<TxLogEntry[]> {
  const res = await fetch(`/tx-log?limit=${limit}`, { credentials: "same-origin" });
  if (!res.ok) return [];
  return (await res.json()) as TxLogEntry[];
}
