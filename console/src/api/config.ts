// Endpoint configuration for the SPA. By default, the dashboard server proxies
// or co-hosts all sidecar APIs on the same origin; if any sidecar lives on a
// different host:port, override that via the in-browser Settings route. Only
// base URLs are persisted across browser restarts; bearer tokens stay in
// sessionStorage/current-tab state and are cleared when the tab session ends.

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

const BASE_URL_STORAGE_KEY = "seccomp.console.baseUrls.v1";
const TOKEN_STORAGE_KEY = "seccomp.console.tokens.session.v1";
const LEGACY_STORAGE_KEY = "seccomp.console.config.v1";

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

function mergeDefaults(partial: Partial<ConsoleConfig>): ConsoleConfig {
  return {
    operator: { ...DEFAULTS.operator, ...partial.operator },
    metadata: { ...DEFAULTS.metadata, ...partial.metadata },
    query: { ...DEFAULTS.query, ...partial.query },
    audit: { ...DEFAULTS.audit, ...partial.audit },
    health: { ...DEFAULTS.health, ...partial.health },
    recovery: { ...DEFAULTS.recovery, ...partial.recovery },
  };
}

function baseUrlOnly(config: ConsoleConfig): ConsoleConfig {
  return {
    operator: { baseUrl: config.operator.baseUrl },
    metadata: { baseUrl: config.metadata.baseUrl },
    query: { baseUrl: config.query.baseUrl },
    audit: { baseUrl: config.audit.baseUrl },
    health: { baseUrl: config.health.baseUrl },
    recovery: { baseUrl: config.recovery.baseUrl },
  };
}

function tokenOnly(config: ConsoleConfig): Partial<Record<SidecarKey, string>> {
  const tokens: Partial<Record<SidecarKey, string>> = {};
  (Object.keys(DEFAULTS) as SidecarKey[]).forEach((key) => {
    const token = config[key].token?.trim();
    if (token) tokens[key] = token;
  });
  return tokens;
}

function readSessionTokens(): Partial<Record<SidecarKey, string>> {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.sessionStorage.getItem(TOKEN_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Partial<Record<SidecarKey, string>>;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function withSessionTokens(config: ConsoleConfig): ConsoleConfig {
  const tokens = readSessionTokens();
  const next = structuredClone(config);
  (Object.keys(DEFAULTS) as SidecarKey[]).forEach((key) => {
    if (typeof tokens[key] === "string" && tokens[key]) {
      next[key].token = tokens[key];
    }
  });
  return next;
}

function readPersistedBaseUrls(): ConsoleConfig | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(BASE_URL_STORAGE_KEY);
    if (raw) {
      return mergeDefaults(JSON.parse(raw) as Partial<ConsoleConfig>);
    }
    const legacyRaw = window.localStorage.getItem(LEGACY_STORAGE_KEY);
    if (legacyRaw) {
      const migrated = baseUrlOnly(mergeDefaults(JSON.parse(legacyRaw) as Partial<ConsoleConfig>));
      window.localStorage.setItem(BASE_URL_STORAGE_KEY, JSON.stringify(migrated));
      window.localStorage.removeItem(LEGACY_STORAGE_KEY);
      return migrated;
    }
  } catch {
    /* ignore */
  }
  return null;
}

function read(): ConsoleConfig {
  if (cache) return cache;
  if (typeof window === "undefined") {
    cache = DEFAULTS;
    return cache;
  }
  cache = withSessionTokens(readPersistedBaseUrls() ?? DEFAULTS);
  return cache;
}

function write(next: ConsoleConfig) {
  cache = next;
  if (typeof window !== "undefined") {
    window.localStorage.setItem(BASE_URL_STORAGE_KEY, JSON.stringify(baseUrlOnly(next)));
    window.localStorage.removeItem(LEGACY_STORAGE_KEY);
    const tokens = tokenOnly(next);
    if (Object.keys(tokens).length > 0) {
      window.sessionStorage.setItem(TOKEN_STORAGE_KEY, JSON.stringify(tokens));
    } else {
      window.sessionStorage.removeItem(TOKEN_STORAGE_KEY);
    }
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
  if (typeof window !== "undefined") {
    window.localStorage.removeItem(BASE_URL_STORAGE_KEY);
    window.localStorage.removeItem(LEGACY_STORAGE_KEY);
    window.sessionStorage.removeItem(TOKEN_STORAGE_KEY);
  }
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
