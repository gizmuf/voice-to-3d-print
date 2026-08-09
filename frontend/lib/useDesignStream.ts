"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { resolveBackendUrl, normalizeFetchError } from "./backend";
import { friendlyChatError } from "./chat-errors";
import type { UiLanguage } from "./ui-language";
import type { ChatTurnEntry, ToolCall } from "../types/chat";

type SSEvent = { event: string; data: Record<string, unknown> };

type StreamState = {
  status: "idle" | "streaming" | "error";
  errorMessage?: string;
  activity?: string;
  model?: string;
  previewUpdating?: boolean;
};

type SendOptions = {
  selectedFeatureId?: string | null;
  selectedFeatureLabel?: string | null;
  selectedTopologyRef?: string | null;
};

const parseSSEStream = async function* (
  response: Response,
): AsyncGenerator<SSEvent> {
  if (!response.body) return;
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let separator = buffer.indexOf("\n\n");
    while (separator !== -1) {
      const block = buffer.slice(0, separator);
      buffer = buffer.slice(separator + 2);
      separator = buffer.indexOf("\n\n");
      let event = "message";
      let data = "";
      for (const rawLine of block.split("\n")) {
        const line = rawLine.trimEnd();
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (!data) continue;
      try {
        yield { event, data: JSON.parse(data) as Record<string, unknown> };
      } catch {
        // ignore malformed
      }
    }
  }
};

export function useDesignStream(designId: string | null, language: UiLanguage = "pl") {
  const backendUrl = resolveBackendUrl();
  const [history, setHistory] = useState<ChatTurnEntry[]>([]);
  const [state, setState] = useState<StreamState>({ status: "idle" });
  const [hydrated, setHydrated] = useState(false);
  const [lifetimeCost, setLifetimeCost] = useState(0);
  const [latestRevisionId, setLatestRevisionId] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!designId) {
      setHistory([]);
      setLatestRevisionId(null);
      setState({ status: "idle" });
      setHydrated(false);
      setLifetimeCost(0);
      return;
    }
    // A newly created design starts with an empty local history. Clear any
    // previous design immediately, but do not let the hydration response
    // overwrite a prompt that is submitted while this request is in flight.
    setHistory([]);
    setLatestRevisionId(null);
    setState({ status: "idle" });
    setHydrated(false);
    setLifetimeCost(0);
    let cancelled = false;
    fetch(`${backendUrl}/design/${designId}/conversation`)
      .then((res) => (res.ok ? res.json() : null))
      .then((payload) => {
        if (cancelled || !payload) return;
        const hydrated = hydrate(payload.messages || []);
        setHistory((current) => (current.length > 0 ? current : hydrated));
        setLifetimeCost(Number(payload.usage_totals?.cost_usd ?? 0));
      })
      .catch(() => undefined)
      .finally(() => {
        if (!cancelled) setHydrated(true);
      });
    return () => {
      cancelled = true;
    };
  }, [backendUrl, designId]);

  const send = useCallback(
    async (message: string, options: SendOptions = {}) => {
      if (!designId || !message.trim()) return;
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      const userEntry: ChatTurnEntry = { kind: "user", text: message };
      const assistantEntry: ChatTurnEntry = { kind: "assistant", text: "", toolCalls: [] };
      setHistory((prev) => [...prev, userEntry, assistantEntry]);
      setState({ status: "streaming", activity: "Understanding your request…" });

      const updateAssistant = (
        update: (
          entry: Extract<ChatTurnEntry, { kind: "assistant" }>,
        ) => Extract<ChatTurnEntry, { kind: "assistant" }>,
      ) =>
        setHistory((prev) => {
          const next = [...prev];
          for (let i = next.length - 1; i >= 0; i -= 1) {
            const entry = next[i];
            if (entry.kind === "assistant") {
              next[i] = update(entry);
              break;
            }
          }
          return next;
        });

      try {
        const response = await fetch(`${backendUrl}/design/${designId}/chat`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            message,
            selected_feature_id: options.selectedFeatureId || null,
            selected_feature_label: options.selectedFeatureLabel || null,
            selected_topology_ref: options.selectedTopologyRef || null,
          }),
          signal: controller.signal,
        });
        if (!response.ok) {
          throw new Error(`Chat request failed: ${response.status}`);
        }
        let streamFailed = false;
        for await (const ev of parseSSEStream(response)) {
          if (controller.signal.aborted) break;
          if (ev.event === "turn_start") {
            const model = typeof ev.data.model === "string" ? ev.data.model : undefined;
            setState({ status: "streaming", activity: "Rozumiem zmianę…", model, previewUpdating: false });
            updateAssistant((entry) => ({ ...entry, model: model ?? entry.model }));
          } else if (ev.event === "model_activity") {
            setState((current) => ({
              status: "streaming",
              activity: String(ev.data.activity ?? "Sprawdzam poprawkę…"),
              model: typeof ev.data.model === "string" ? ev.data.model : current.model,
            }));
          } else if (ev.event === "tool_call_start") {
            const toolName = String(ev.data.name ?? "");
            setState((current) => ({
              status: "streaming",
              activity: activityForTool(toolName),
              model: typeof ev.data.model === "string" ? ev.data.model : current.model,
              previewUpdating: toolUpdatesPreview(toolName) || current.previewUpdating,
            }));
          } else if (ev.event === "tool_call_end") {
            setState((current) => ({
              ...current,
              status: "streaming",
              activity: "Sprawdzam rezultat…",
              previewUpdating: false,
            }));
          }
          if (ev.event === "error") {
            const errorMessage = friendlyChatError(ev.data, language);
            streamFailed = true;
            setState({ status: "error", errorMessage });
            handleEvent(
              { ...ev, data: { ...ev.data, message: errorMessage } },
              { updateAssistant, setLatestRevisionId, setLifetimeCost },
            );
            continue;
          }
          handleEvent(ev, { updateAssistant, setLatestRevisionId, setLifetimeCost });
        }
        if (!streamFailed) setState((current) => ({ status: "idle", model: current.model }));
      } catch (error) {
        if (controller.signal.aborted) {
          setState({ status: "idle" });
          return;
        }
        const errorMessage = normalizeError(error, backendUrl);
        setState({ status: "error", errorMessage });
        updateAssistant((entry) => ({ ...entry, text: entry.text || errorMessage }));
      }
    },
    [backendUrl, designId, language],
  );

  const cancel = useCallback(() => abortRef.current?.abort(), []);

  const appendLocalTurn = useCallback(
    (userText: string, assistantText: string, revisionId?: string | null, model = "local") => {
      const userEntry: ChatTurnEntry = { kind: "user", text: userText };
      const assistantEntry: ChatTurnEntry = {
        kind: "assistant",
        text: assistantText,
        toolCalls: [],
        model,
        ...(revisionId ? { revisionIdAfter: revisionId } : {}),
      };
      setHistory((prev) => [...prev, userEntry, assistantEntry]);
      if (revisionId) setLatestRevisionId(revisionId);
    },
    [],
  );

  return { history, hydrated, lifetimeCost, state, latestRevisionId, send, cancel, appendLocalTurn };
}

function activityForTool(toolName: string): string {
  const labels: Record<string, string> = {
    read_design: "Czytam bieżący projekt…",
    query_library: "Dobieram sprawdzony wzorzec CAD…",
    update_parameter: "Aktualizuję wymiary i model 3D…",
    replace_feature: "Przebudowuję wybrany element…",
    rewrite_design: "Przebudowuję model parametryczny…",
    run_build: "Buduję nowy model 3D…",
    check_manufacturability: "Sprawdzam przygotowanie do druku…",
  };
  return labels[toolName] ?? "Wprowadzam zmianę CAD…";
}

function toolUpdatesPreview(toolName: string): boolean {
  return ["update_parameter", "replace_feature", "append_feature", "rewrite_design", "run_build"].includes(toolName);
}

// `normalizeError` was hoisted to ../lib/backend.ts as `normalizeFetchError`
// so the workspace chat path gets the same friendly fetch-failure copy.
const normalizeError = normalizeFetchError;

function handleEvent(
  ev: SSEvent,
  helpers: {
    updateAssistant: (
      update: (
        entry: Extract<ChatTurnEntry, { kind: "assistant" }>,
      ) => Extract<ChatTurnEntry, { kind: "assistant" }>,
    ) => void;
    setLatestRevisionId: (rev: string) => void;
    setLifetimeCost: (update: (current: number) => number) => void;
  },
) {
  const { event, data } = ev;
  if (event === "assistant_text") {
    helpers.updateAssistant((entry) => ({
      ...entry,
      text: entry.text + String(data.text ?? ""),
    }));
  } else if (event === "tool_call_start") {
    const call: ToolCall = {
      id: String(data.id),
      name: String(data.name),
      input: (data.input as Record<string, unknown>) ?? {},
      status: "running",
    };
    helpers.updateAssistant((entry) => ({
      ...entry,
      toolCalls: [...entry.toolCalls, call],
    }));
  } else if (event === "tool_call_end") {
    const id = String(data.id);
    const isError = Boolean(data.is_error);
    helpers.updateAssistant((entry) => ({
      ...entry,
      toolCalls: entry.toolCalls.map((c) =>
        c.id === id
          ? {
              ...c,
              status: isError ? "error" : "done",
              result: data.result,
              isError,
            }
          : c,
      ),
    }));
    const result = data.result as Record<string, unknown> | undefined;
    const revisionId = typeof result?.new_revision_id === "string" ? result.new_revision_id : null;
    if (revisionId) helpers.setLatestRevisionId(revisionId);
  } else if (event === "turn_end") {
    const revisionId = typeof data.revision_id === "string" ? data.revision_id : null;
    if (revisionId) helpers.setLatestRevisionId(revisionId);
    helpers.updateAssistant((entry) => ({
      ...entry,
      revisionIdAfter: revisionId ?? entry.revisionIdAfter,
      tokens: {
        input: Number(data.input_tokens ?? 0),
        output: Number(data.output_tokens ?? 0),
        cacheRead: Number(data.cache_read_tokens ?? 0),
        cacheCreation: Number(data.cache_creation_tokens ?? 0),
      },
    }));
    const cost = Number(data.cost_usd ?? 0);
    if (Number.isFinite(cost) && cost > 0) {
      helpers.setLifetimeCost((current) => current + cost);
    }
  } else if (event === "error") {
    const message = String(data.message ?? "Unknown error");
    helpers.updateAssistant((entry) => ({
      ...entry,
      text: entry.text ? `${entry.text}\n\n[error] ${message}` : `[error] ${message}`,
    }));
  }
}

type ServerMessage = {
  role: string;
  content:
    | string
    | Array<{
        type: string;
        text?: string;
        id?: string;
        name?: string;
        input?: Record<string, unknown>;
        tool_use_id?: string;
        content?: string;
        is_error?: boolean;
      }>;
};

function hydrate(messages: ServerMessage[]): ChatTurnEntry[] {
  const entries: ChatTurnEntry[] = [];
  for (const message of messages) {
    if (message.role === "user" && typeof message.content === "string") {
      entries.push({ kind: "user", text: message.content });
      continue;
    }
    if (message.role === "user" && Array.isArray(message.content)) {
      const toolResults = message.content.filter((b) => b.type === "tool_result");
      if (!toolResults.length) continue;
      for (let i = entries.length - 1; i >= 0; i -= 1) {
        const entry = entries[i];
        if (entry.kind !== "assistant") continue;
        entry.toolCalls = entry.toolCalls.map((c) => {
          const match = toolResults.find((r) => r.tool_use_id === c.id);
          if (!match) return c;
          let parsed: unknown = match.content;
          try {
            parsed = match.content ? JSON.parse(match.content) : null;
          } catch {
            // keep raw
          }
          return {
            ...c,
            status: match.is_error ? "error" : "done",
            result: parsed,
            isError: match.is_error,
          };
        });
        break;
      }
      continue;
    }
    if (message.role === "assistant" && Array.isArray(message.content)) {
      let text = "";
      const toolCalls: ToolCall[] = [];
      for (const block of message.content) {
        if (block.type === "text" && typeof block.text === "string") text += block.text;
        else if (block.type === "tool_use" && block.id && block.name) {
          toolCalls.push({
            id: block.id,
            name: block.name,
            input: block.input ?? {},
            status: "pending",
          });
        }
      }
      entries.push({ kind: "assistant", text, toolCalls });
    }
  }
  return entries;
}
