"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { resolveBackendUrl } from "./backend";
import type { ChatTurnEntry, ToolCall } from "../types/chat";

type SSEvent = { event: string; data: Record<string, unknown> };

type StreamState = {
  status: "idle" | "streaming" | "error";
  errorMessage?: string;
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

export function useDesignStream(designId: string | null) {
  const backendUrl = resolveBackendUrl();
  const [history, setHistory] = useState<ChatTurnEntry[]>([]);
  const [state, setState] = useState<StreamState>({ status: "idle" });
  const [latestRevisionId, setLatestRevisionId] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!designId) {
      setHistory([]);
      setLatestRevisionId(null);
      return;
    }
    let cancelled = false;
    fetch(`${backendUrl}/design/${designId}/conversation`)
      .then((res) => (res.ok ? res.json() : null))
      .then((payload) => {
        if (cancelled || !payload) return;
        setHistory(hydrate(payload.messages || []));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [backendUrl, designId]);

  const send = useCallback(
    async (message: string) => {
      if (!designId || !message.trim()) return;
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      const userEntry: ChatTurnEntry = { kind: "user", text: message };
      const assistantEntry: ChatTurnEntry = { kind: "assistant", text: "", toolCalls: [] };
      setHistory((prev) => [...prev, userEntry, assistantEntry]);
      setState({ status: "streaming" });

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
          body: JSON.stringify({ message }),
          signal: controller.signal,
        });
        if (!response.ok) {
          throw new Error(`Chat request failed: ${response.status}`);
        }
        for await (const ev of parseSSEStream(response)) {
          if (controller.signal.aborted) break;
          handleEvent(ev, { updateAssistant, setLatestRevisionId });
        }
        setState({ status: "idle" });
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
    [backendUrl, designId],
  );

  const cancel = useCallback(() => abortRef.current?.abort(), []);

  return { history, state, latestRevisionId, send, cancel };
}

function normalizeError(error: unknown, backendUrl: string): string {
  if (error instanceof DOMException && error.name === "AbortError") {
    return "Cancelled.";
  }
  if (error instanceof TypeError && /fetch/i.test(error.message)) {
    return `Could not reach the backend at ${backendUrl}. Is the FastAPI server running?`;
  }
  return error instanceof Error ? error.message : "Unknown chat error.";
}

function handleEvent(
  ev: SSEvent,
  helpers: {
    updateAssistant: (
      update: (
        entry: Extract<ChatTurnEntry, { kind: "assistant" }>,
      ) => Extract<ChatTurnEntry, { kind: "assistant" }>,
    ) => void;
    setLatestRevisionId: (rev: string) => void;
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
