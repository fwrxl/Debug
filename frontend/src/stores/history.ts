import type { Session } from "../types";

const STORAGE_KEY = "znew_sessions";
const MAX_SESSIONS = 50;

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

export function getSessions(): Session[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    return JSON.parse(raw) as Session[];
  } catch {
    return [];
  }
}

export function saveSessions(sessions: Session[]): void {
  const trimmed = sessions.slice(-MAX_SESSIONS);
  localStorage.setItem(STORAGE_KEY, JSON.stringify(trimmed));
}

export function createSession(firstUserContent: string): Session {
  return {
    id: generateId(),
    title: firstUserContent.slice(0, 20) + (firstUserContent.length > 20 ? "..." : ""),
    createdAt: new Date().toISOString(),
    messages: [{ role: "user", content: firstUserContent }],
  };
}

export function updateSession(sessions: Session[], session: Session): Session[] {
  const idx = sessions.findIndex((s) => s.id === session.id);
  if (idx >= 0) {
    const next = [...sessions];
    next[idx] = session;
    return next;
  }
  return [...sessions, session];
}
