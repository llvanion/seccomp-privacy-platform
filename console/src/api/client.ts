import { authHeaders, resolveUrl, type SidecarKey } from "./config";

export class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.status = status;
    this.body = body;
    this.name = "ApiError";
  }
}

export type RequestOptions = {
  method?: string;
  query?: Record<string, string | number | boolean | null | undefined>;
  json?: unknown;
  signal?: AbortSignal;
  headers?: Record<string, string>;
  accept?: "json" | "text" | "stream";
};

function buildQueryString(query: RequestOptions["query"]): string {
  if (!query) return "";
  const params = new URLSearchParams();
  for (const [key, val] of Object.entries(query)) {
    if (val === undefined || val === null || val === "") continue;
    params.append(key, String(val));
  }
  const s = params.toString();
  return s ? `?${s}` : "";
}

export async function callApi<T>(
  sidecar: SidecarKey,
  path: string,
  opts: RequestOptions = {},
): Promise<T> {
  const url = `${resolveUrl(sidecar, path)}${buildQueryString(opts.query)}`;
  const method = opts.method ?? (opts.json ? "POST" : "GET");
  const headers: Record<string, string> = {
    Accept: opts.accept === "text" ? "text/plain" : "application/json",
    ...authHeaders(sidecar),
    ...opts.headers,
  };
  let body: BodyInit | undefined;
  if (opts.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.json);
  }
  const resp = await fetch(url, { method, headers, body, signal: opts.signal });
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    let parsed: unknown = text;
    try {
      parsed = JSON.parse(text);
    } catch {
      /* keep text */
    }
    const message =
      (parsed && typeof parsed === "object" && "error" in parsed && typeof (parsed as { error?: unknown }).error === "string"
        ? (parsed as { error: string }).error
        : `HTTP ${resp.status} ${resp.statusText}`);
    throw new ApiError(resp.status, message, parsed);
  }
  if (opts.accept === "text") return (await resp.text()) as unknown as T;
  if (resp.status === 204) return undefined as unknown as T;
  const ctype = resp.headers.get("content-type") ?? "";
  if (ctype.includes("application/json")) return (await resp.json()) as T;
  return (await resp.text()) as unknown as T;
}

export const api = {
  get: <T,>(sidecar: SidecarKey, path: string, opts?: Omit<RequestOptions, "method" | "json">) =>
    callApi<T>(sidecar, path, { ...opts, method: "GET" }),
  post: <T,>(sidecar: SidecarKey, path: string, json?: unknown, opts?: Omit<RequestOptions, "method" | "json">) =>
    callApi<T>(sidecar, path, { ...opts, method: "POST", json }),
  put: <T,>(sidecar: SidecarKey, path: string, json?: unknown, opts?: Omit<RequestOptions, "method" | "json">) =>
    callApi<T>(sidecar, path, { ...opts, method: "PUT", json }),
  delete: <T,>(sidecar: SidecarKey, path: string, opts?: Omit<RequestOptions, "method" | "json">) =>
    callApi<T>(sidecar, path, { ...opts, method: "DELETE" }),
};
