"use client";

import { useEffect, useState } from "react";

import { resolveBackendUrl } from "./backend";

export type HealthSnapshot = {
  slicer_ready: boolean;
  platform_ai_spend_enabled: boolean;
  warnings: string[];
};

export type AccountAiSettings = {
  anthropic: {
    platform_access: boolean;
    billing_source: "platform" | "customer_byok";
    model: string;
  };
  providers?: Partial<Record<"anthropic" | "openai" | "gemini" | "meshy" | "tripo", {
    platform_access: boolean;
  }>>;
  keys_persisted: boolean;
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
        platform_ai_spend_enabled: Boolean(payload.platform_ai_spend_enabled),
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

export function useAccountAiSettings(): AccountAiSettings | null {
  const [settings, setSettings] = useState<AccountAiSettings | null>(null);
  useEffect(() => {
    let alive = true;
    fetch(`${resolveBackendUrl()}/account/ai-settings`, { credentials: "include" })
      .then((response) => (response.ok ? response.json() : null))
      .then((payload) => {
        if (alive && payload) setSettings(payload as AccountAiSettings);
      })
      .catch(() => null);
    return () => {
      alive = false;
    };
  }, []);
  return settings;
}
