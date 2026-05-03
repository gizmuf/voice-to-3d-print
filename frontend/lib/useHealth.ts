"use client";

import { useEffect, useState } from "react";

import { resolveBackendUrl } from "./backend";

export type HealthSnapshot = {
  slicer_ready: boolean;
  warnings: string[];
};

let cached: HealthSnapshot | null = null;
let inflight: Promise<HealthSnapshot | null> | null = null;

async function fetchHealth(): Promise<HealthSnapshot | null> {
  if (cached) return cached;
  if (inflight) return inflight;
  const backendUrl = resolveBackendUrl();
  inflight = fetch(`${backendUrl}/health`)
    .then((r) => (r.ok ? r.json() : null))
    .then((payload) => {
      if (!payload) return null;
      cached = {
        slicer_ready: Boolean(payload.slicer_ready),
        warnings: Array.isArray(payload.warnings) ? payload.warnings : [],
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
 * One-shot fetch of /health, cached process-wide. The server health doesn't
 * change at runtime in normal sessions, so a single fetch covers the studio
 * lifetime. Components mounting later get the cached snapshot synchronously.
 */
export function useHealth(): HealthSnapshot | null {
  const [snapshot, setSnapshot] = useState<HealthSnapshot | null>(cached);
  useEffect(() => {
    if (cached) return;
    let alive = true;
    fetchHealth().then((s) => {
      if (alive && s) setSnapshot(s);
    });
    return () => {
      alive = false;
    };
  }, []);
  return snapshot;
}
