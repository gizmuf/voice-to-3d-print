"use client";

import { useEffect, useRef, useState } from "react";

import { useChatStream } from "../../lib/useChatStream";

import ChatMessage from "./ChatMessage";

export type ChatPanelProps = {
  workspaceId: string | null;
  disabled?: boolean;
  onRevisionChange?: (revisionId: string) => void;
  selectedFeatureLabel?: string | null;
  selectedFeatureId?: string | null;
};

export default function ChatPanel({
  workspaceId,
  disabled,
  onRevisionChange,
  selectedFeatureLabel,
  selectedFeatureId,
}: ChatPanelProps) {
  const { history, state, latestRevisionId, send, cancel } =
    useChatStream(workspaceId);
  const [draft, setDraft] = useState("");
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const lastNotifiedRevisionRef = useRef<string | null>(null);

  useEffect(() => {
    if (!latestRevisionId) return;
    if (lastNotifiedRevisionRef.current === latestRevisionId) return;
    lastNotifiedRevisionRef.current = latestRevisionId;
    onRevisionChange?.(latestRevisionId);
  }, [latestRevisionId, onRevisionChange]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [history.length, state.status]);

  const isStreaming = state.status === "streaming";
  const canSubmit =
    !disabled && !isStreaming && Boolean(workspaceId) && draft.trim().length > 0;

  const handleSubmit = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!canSubmit) return;
    const message = draft.trim();
    setDraft("");
    await send(message, {
      selectedFeatureId: selectedFeatureId ?? null,
      selectedFeatureLabel: selectedFeatureLabel ?? null,
    });
  };

  return (
    <div style={panelStyle} className="chat-panel">
      <div style={headerStyle}>
        <strong style={{ fontSize: 13 }}>Pulsai assistant</strong>
        {state.status === "error" && state.errorMessage ? (
          <span style={errorTagStyle}>error</span>
        ) : isStreaming ? (
          <button type="button" onClick={cancel} style={cancelStyle}>
            stop
          </button>
        ) : null}
      </div>
      <div ref={scrollRef} style={historyStyle}>
        {history.length === 0 ? (
          <p style={emptyStyle}>
            Ask for an edit. Examples: <em>“make the holes 7mm”</em>,{" "}
            <em>“twice as many rings”</em>, <em>“thicker walls”</em>.
          </p>
        ) : (
          history.map((entry, idx) => (
            <ChatMessage key={idx} entry={entry} />
          ))
        )}
      </div>
      <form onSubmit={handleSubmit} style={formStyle}>
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          rows={2}
          placeholder={
            workspaceId
              ? "Describe an edit…"
              : "Create or import a model first."
          }
          disabled={disabled || !workspaceId || isStreaming}
          style={textareaStyle}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              handleSubmit();
            }
          }}
        />
        <div style={formFooterStyle}>
          <span style={hintStyle}>
            ⌘/Ctrl+Enter to send. Edits are bounded by the capability matrix.
          </span>
          <button type="submit" disabled={!canSubmit} style={submitStyle}>
            {isStreaming ? "…" : "Send"}
          </button>
        </div>
        {state.status === "error" && state.errorMessage ? (
          <p style={errorMsgStyle}>{state.errorMessage}</p>
        ) : null}
      </form>
    </div>
  );
}

const panelStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 10,
  height: "100%",
  minHeight: 320,
};

const headerStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  padding: "0 2px",
};

const historyStyle: React.CSSProperties = {
  flex: 1,
  display: "flex",
  flexDirection: "column",
  gap: 8,
  overflowY: "auto",
  padding: 4,
  minHeight: 200,
  maxHeight: 540,
};

const emptyStyle: React.CSSProperties = {
  margin: 0,
  fontSize: 12,
  opacity: 0.6,
  lineHeight: 1.4,
};

const formStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 6,
};

const textareaStyle: React.CSSProperties = {
  width: "100%",
  resize: "vertical",
  background: "rgba(255,255,255,0.04)",
  border: "1px solid rgba(255,255,255,0.12)",
  borderRadius: 8,
  padding: "8px 10px",
  color: "inherit",
  font: "inherit",
  fontSize: 13,
};

const formFooterStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 8,
};

const hintStyle: React.CSSProperties = {
  fontSize: 11,
  opacity: 0.55,
};

const submitStyle: React.CSSProperties = {
  background: "rgba(33,150,243,0.7)",
  color: "white",
  border: "none",
  borderRadius: 8,
  padding: "6px 14px",
  cursor: "pointer",
  fontSize: 12,
  fontWeight: 600,
};

const cancelStyle: React.CSSProperties = {
  background: "transparent",
  color: "rgba(255,193,7,0.85)",
  border: "1px solid rgba(255,193,7,0.55)",
  borderRadius: 999,
  padding: "0 8px",
  fontSize: 11,
  cursor: "pointer",
};

const errorTagStyle: React.CSSProperties = {
  background: "rgba(244,67,54,0.2)",
  color: "rgba(244,67,54,0.9)",
  padding: "0 8px",
  borderRadius: 999,
  fontSize: 11,
};

const errorMsgStyle: React.CSSProperties = {
  margin: 0,
  fontSize: 11,
  color: "rgba(244,67,54,0.9)",
};
