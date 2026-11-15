import { useEffect, useState } from "react";

// localStorage can throw (private mode, sandboxed iframes) — never let it break the app.
function read<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(`finn:${key}`);
    return v ? (JSON.parse(v) as T) : fallback;
  } catch {
    return fallback;
  }
}
function write(key: string, v: unknown) {
  try {
    localStorage.setItem(`finn:${key}`, JSON.stringify(v));
  } catch { /* ignore */ }
}

export function usePersisted<T>(key: string, fallback: T): [T, (v: T | ((p: T) => T)) => void] {
  const [v, setV] = useState<T>(() => read(key, fallback));
  useEffect(() => write(key, v), [key, v]);
  return [v, setV];
}

// "Since you last looked": remember the previous visit, update on every load.
export function lastVisit(): string | null {
  const prev = read<string | null>("lastVisit", null);
  write("lastVisit", new Date().toISOString());
  return prev;
}
