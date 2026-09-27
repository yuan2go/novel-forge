export const API_BASE = process.env.NEXT_PUBLIC_NOVEL_FORGE_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(message: string, readonly status: number) { super(message); }
}

export async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    const body = await response.text();
    throw new ApiError(body || `${response.status} ${response.statusText}`, response.status);
  }
  return response.json() as Promise<T>;
}

export function postJson(path: string, body: Record<string, unknown>) {
  return fetchJson(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
}
