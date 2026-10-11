// Thin typed client for the GHOSTTRACE API. Demo-only auth header; never real credentials.

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";
const TOKEN = (import.meta.env.VITE_GT_DEMO_TOKEN as string | undefined) ?? "dev-demo-token";

export class ApiError extends Error {
  status: number;
  code: string;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

let workspace = "demo";
export function setWorkspace(ws: string) {
  workspace = ws;
}
export function getWorkspace() {
  return workspace;
}

async function req<T>(method: string, path: string, body?: unknown, raw = false): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    method,
    headers: {
      "X-GT-Demo-Token": TOKEN,
      "X-GT-Workspace": workspace,
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (raw) {
    if (!r.ok) throw new ApiError(r.status, "error", await r.text());
    return (await r.text()) as unknown as T;
  }
  let j: any = null;
  try {
    j = await r.json();
  } catch {
    throw new ApiError(r.status, "bad_response", `HTTP ${r.status}`);
  }
  if (!r.ok) throw new ApiError(r.status, j?.error?.code ?? "error", j?.error?.message ?? `HTTP ${r.status}`);
  return (j.data ?? j) as T;
}

export const api = {
  get: <T,>(p: string) => req<T>("GET", p),
  post: <T,>(p: string, b?: unknown) => req<T>("POST", p, b ?? {}),
  text: (p: string) => req<string>("GET", p, undefined, true),
  ready: async () => {
    const r = await fetch(`${BASE}/ready`);
    return (await r.json()) as { status: string; checks: Record<string, unknown> };
  },
};

export function qs(params: Record<string, string | number | boolean | undefined | null>) {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") u.set(k, String(v));
  const s = u.toString();
  return s ? `?${s}` : "";
}

export const isoOf = (ms: number) => new Date(ms).toISOString().replace(".000Z", "Z");
export const fmt = (iso?: string | null) => (iso ? iso.replace("T", " ").replace(":00Z", "Z") : "—");
