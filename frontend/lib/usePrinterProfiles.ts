"use client";

import { useEffect, useState } from "react";

import { resolveBackendUrl } from "./backend";
import type { PrinterProfile } from "../types/design";

export type PrinterCatalog = {
  profiles: PrinterProfile[];
  defaultId: string;
};

let cached: PrinterCatalog | null = null;
let inflight: Promise<PrinterCatalog | null> | null = null;

async function fetchProfiles(): Promise<PrinterCatalog | null> {
  if (cached) return cached;
  if (inflight) return inflight;
  const backendUrl = resolveBackendUrl();
  inflight = fetch(`${backendUrl}/printer-profiles`)
    .then((r) => (r.ok ? r.json() : null))
    .then((payload) => {
      if (!payload) return null;
      cached = {
        profiles: Array.isArray(payload.profiles) ? payload.profiles : [],
        defaultId: typeof payload.default === "string" ? payload.default : "",
      };
      return cached;
    })
    .catch(() => null)
    .finally(() => {
      inflight = null;
    });
  return inflight;
}

/**
 * One-shot fetch of the printer catalog. The list is static for a given
 * backend version, so a single in-memory cache covers the studio lifetime.
 * Components mounting later get the cache synchronously; the first mount
 * pays the network round-trip and re-renders when it arrives.
 */
export function usePrinterProfiles(): PrinterCatalog | null {
  const [snapshot, setSnapshot] = useState<PrinterCatalog | null>(cached);
  useEffect(() => {
    if (cached) return;
    let alive = true;
    fetchProfiles().then((s) => {
      if (alive && s) setSnapshot(s);
    });
    return () => {
      alive = false;
    };
  }, []);
  return snapshot;
}
