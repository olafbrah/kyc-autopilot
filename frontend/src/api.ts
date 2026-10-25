export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T = unknown>(path: string, opts: { method?: string; body?: unknown } = {}): Promise<T> {
  const r = await fetch(path, {
    method: opts.method ?? (opts.body === undefined ? "GET" : "POST"),
    credentials: "include",
    headers: opts.body === undefined ? {} : { "Content-Type": "application/json" },
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
  });
  const data = r.status === 204 ? null : await r.json().catch(() => null);
  if (!r.ok) {
    const detail = data?.detail;
    throw new ApiError(r.status, typeof detail === "string" ? detail : r.statusText);
  }
  return data as T;
}
