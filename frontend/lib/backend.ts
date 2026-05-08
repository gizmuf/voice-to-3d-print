"use client";

const localBackendUrl = "http://localhost:8000";
const productionBackendUrl =
  process.env.NEXT_PUBLIC_BACKEND_URL ||
  "https://pulsai-3d-backend-efopwinsfq-uc.a.run.app";

export const resolveBackendUrl = () => {
  if (process.env.NEXT_PUBLIC_BACKEND_URL) return process.env.NEXT_PUBLIC_BACKEND_URL;
  if (typeof window !== "undefined") {
    const host = window.location.hostname;
    if (host && host !== "localhost" && host !== "127.0.0.1") {
      return productionBackendUrl;
    }
  }
  return localBackendUrl;
};

export const resolveUrl = (base: string, value?: string | null) => {
  if (!value) return null;
  if (value.startsWith("http")) return value;
  return `${base.replace(/\/$/, "")}${value.startsWith("/") ? "" : "/"}${value}`;
};

/**
 * Normalize a fetch failure into a user-readable string.
 *
 * Both chat hooks (workspace + design) used to inline this; the design
 * version translated `TypeError: Failed to fetch` into a friendly
 * "couldn't reach the backend" message, the workspace version did not.
 * Sharing the helper means both surfaces reach the same wording.
 */
export function normalizeFetchError(error: unknown, backendUrl: string): string {
  if (error instanceof DOMException && error.name === "AbortError") {
    return "Cancelled.";
  }
  if (error instanceof TypeError && /fetch/i.test(error.message)) {
    return `Could not reach the backend at ${backendUrl}. Is the FastAPI server running?`;
  }
  return error instanceof Error ? error.message : "Unknown error.";
}
