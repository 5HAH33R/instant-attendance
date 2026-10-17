import type { AttendanceStats } from "./types";

/** How long a loaded dashboard may be restored after a refresh (2 minutes). */
export const SESSION_TTL_MS = 120_000;

const STORAGE_KEY = "ia_session";

/**
 * What a student is allowed to keep across a refresh.
 * NOTE: the password is deliberately NEVER part of this - restored sessions
 * carry an empty password and no dashboard action requires it.
 */
export interface StoredSession {
  savedAt: number;
  token: string;
  id: string;
  stats: AttendanceStats;
}

export type SessionCheck =
  | { status: "none" }
  | { status: "expired"; token: string }
  | { status: "fresh"; session: StoredSession };

export function saveSession(token: string, id: string, stats: AttendanceStats): void {
  const entry: StoredSession = { savedAt: Date.now(), token, id, stats };
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(entry));
  } catch {
    // Storage unavailable/full - the dashboard just won't survive a refresh.
  }
}

export function clearSession(): void {
  try {
    sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // Ignore - nothing to clean up.
  }
}

/**
 * Read the stored session. Checks happen ONLY here (on page load/refresh):
 * - fresh  -> restore the same dashboard instantly, 0 network requests
 * - expired-> caller should best-effort POST /api/logout, then show login
 * - none   -> caller shows the normal login screen
 *
 * There is deliberately no timer: the dashboard never force-logs-out a
 * student who is actively viewing it, no matter how long they stay.
 */
export function checkSession(): SessionCheck {
  let raw: string | null = null;
  try {
    raw = sessionStorage.getItem(STORAGE_KEY);
  } catch {
    return { status: "none" };
  }
  if (!raw) return { status: "none" };

  try {
    const entry = JSON.parse(raw) as Partial<StoredSession>;
    if (
      typeof entry?.savedAt !== "number" ||
      typeof entry?.token !== "string" ||
      !entry.stats ||
      !Array.isArray(entry.stats.courses)
    ) {
      clearSession();
      return { status: "none" };
    }
    if (Date.now() - entry.savedAt >= SESSION_TTL_MS) {
      clearSession();
      return { status: "expired", token: entry.token };
    }
    return {
      status: "fresh",
      session: {
        savedAt: entry.savedAt,
        token: entry.token,
        id: typeof entry.id === "string" ? entry.id : "",
        stats: entry.stats,
      },
    };
  } catch {
    clearSession();
    return { status: "none" };
  }
}
