// Endpoint configuration for the SPA. By default, the dashboard server proxies
// or co-hosts all sidecar APIs on the same origin; if any sidecar lives on a
// different host:port, override that via the in-browser Settings route (writes
// to localStorage).

import { useSyncExternalStore } from "react";

export type SidecarKey =
  | "operator"
  | "metadata"
  | "query"
  | "audit"
  | "health"
  | "recovery";

export type SidecarConfig = {
  baseUrl: string;
  token?: string;
};

export type ConsoleConfig = Record<SidecarKey, SidecarConfig>;

const STORAGE_KEY = "seccomp.console.config.v1";

const DEFAULTS: ConsoleConfig = {
  operator: { baseUrl: "" },
  metadata: { baseUrl: "" },
  query: { baseUrl: "" },
  audit: { baseUrl: "" },
  health: { baseUrl: "" },
  recovery: { baseUrl: "" },
};

let cache: ConsoleConfig | null = null;
const listeners = new Set<() => void>();

function read(): ConsoleConfig {
  if (cache) return cache;
  if (typeof window === "undefined") {
    cache = DEFAULTS;
    return cache;
  }
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<ConsoleConfig>;
      cache = {
        operator: { ...DEFAULTS.operator, ...parsed.operator },
        metadata: { ...DEFAULTS.metadata, ...parsed.metadata },
        query: { ...DEFAULTS.query, ...parsed.query },
        audit: { ...DEFAULTS.audit, ...parsed.audit },
        health: { ...DEFAULTS.health, ...parsed.health },
        recovery: { ...DEFAULTS.recovery, ...parsed.recovery },
      };
      return cache;
    }
  } catch {
    /* ignore */
  }
  cache = DEFAULTS;
  return cache;
}

function write(next: ConsoleConfig) {
  cache = next;
  if (typeof window !== "undefined") {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  }
  listeners.forEach((fn) => fn());
}

export function getConfig(): ConsoleConfig {
  return read();
}

export function getSidecar(key: SidecarKey): SidecarConfig {
  return read()[key];
}

export function setSidecar(key: SidecarKey, patch: Partial<SidecarConfig>): void {
  const current = read();
  const next: ConsoleConfig = {
    ...current,
    [key]: { ...current[key], ...patch },
  };
  write(next);
}

export function resetConfig(): void {
  write(DEFAULTS);
}

export function useConfig(): ConsoleConfig {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    read,
    () => DEFAULTS,
  );
}

// Resolve the absolute URL for a sidecar request. When baseUrl is empty, the
// path is left as-is so it hits the SPA host (good for same-origin deploys
// where the dashboard server fronts everything).
export function resolveUrl(key: SidecarKey, path: string): string {
  const cfg = getSidecar(key);
  if (!cfg.baseUrl) return path.startsWith("/") ? path : `/${path}`;
  const base = cfg.baseUrl.replace(/\/+$/, "");
  const tail = path.startsWith("/") ? path : `/${path}`;
  return `${base}${tail}`;
}

export function authHeaders(key: SidecarKey): Record<string, string> {
  const cfg = getSidecar(key);
  if (!cfg.token) return {};
  return { Authorization: `Bearer ${cfg.token}` };
}
