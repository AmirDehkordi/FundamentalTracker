import type { ErrorOut } from "@/api/contracts";

export type ApiErrorKind = "http" | "network" | "parse";

/** A normalized API failure. `status` is the HTTP code, or 0 for network/parse failures. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
    readonly kind: ApiErrorKind,
  ) {
    super(detail);
    this.name = "ApiError";
  }

  /** 501 = a registered-but-unimplemented stub route — a calm "not ready yet", not a real failure. */
  get notReady(): boolean {
    return this.status === 501;
  }
}

// Empty base URL on purpose: the Vite dev proxy forwards /api to the API server, and the prod build
// is served same-origin by FastAPI. The app only ever calls relative /api paths.
const BASE = "";

/** Typed GET/POST against the API, normalizing every failure mode to an {@link ApiError}. */
export async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  let res: Response;
  try {
    res = await fetch(BASE + path, {
      ...init,
      headers: { Accept: "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError(0, "Network error — is the API reachable?", "network");
  }

  if (!res.ok) {
    // 501 stubs and 4xx both send ErrorOut { detail }; fall back to statusText for anything else.
    let detail = res.statusText || `Request failed (${res.status})`;
    try {
      const body = (await res.json()) as Partial<ErrorOut>;
      if (typeof body.detail === "string" && body.detail) detail = body.detail;
    } catch {
      // non-JSON error body — keep statusText
    }
    throw new ApiError(res.status, detail, "http");
  }

  if (res.status === 204) return undefined as T;

  try {
    return (await res.json()) as T;
  } catch {
    throw new ApiError(0, "Malformed JSON in API response", "parse");
  }
}
