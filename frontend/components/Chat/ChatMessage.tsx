"use client";

import type { ChatTurnEntry } from "../../types/chat";
import { displayModelName, formatUsd, tokenCostUsd } from "../../lib/ai-cost";

import ToolCallCard from "./ToolCallCard";

export default function ChatMessage({ entry }: { entry: ChatTurnEntry }) {
  if (entry.kind === "user") {
    return (
      <div style={userStyle} className="chat-message chat-message-user">
        {entry.text}
      </div>
    );
  }
  return (
    <div style={assistantRowStyle} className="chat-message chat-message-assistant">
      <div style={avatarStyle} aria-hidden>P</div>
      <div style={assistantStyle}>
        <div style={assistantLabelStyle}>
          {displayModelName(entry.model)}
          {entry.billingSource === "customer_byok" ? " · Twój klucz" : ""}
        </div>
        {entry.toolCalls.length ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {entry.toolCalls.map((call) => (
              <ToolCallCard key={call.id} call={call} />
            ))}
          </div>
        ) : null}
        {entry.text ? (
          <div style={{ whiteSpace: "pre-wrap", lineHeight: 1.55 }}>{entry.text}</div>
        ) : null}
        {entry.tokens ? (
          <div style={tokensStyle}>
            {tokensSummary(entry.tokens)} · {formatUsd(tokenCostUsd(entry.tokens, entry.model))}
            {entry.revisionIdAfter ? ` · rev ${entry.revisionIdAfter.slice(0, 8)}` : ""}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function tokensSummary(t: { input: number; output: number; cacheRead: number }) {
  return `${t.input} in / ${t.output} out${t.cacheRead ? ` · ${t.cacheRead} cached` : ""}`;
}

const baseStyle: React.CSSProperties = {
  padding: "9px 12px",
  borderRadius: 16,
  fontSize: 13,
};

const userStyle: React.CSSProperties = {
  ...baseStyle,
  background: "rgba(255,255,255,0.10)",
  border: "1px solid rgba(255,255,255,0.08)",
  alignSelf: "flex-end",
  maxWidth: "88%",
  borderBottomRightRadius: 5,
};

const assistantRowStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "24px minmax(0, 1fr)",
  alignItems: "flex-start",
  gap: 8,
};

const avatarStyle: React.CSSProperties = {
  width: 24,
  height: 24,
  display: "grid",
  placeItems: "center",
  borderRadius: 8,
  background: "linear-gradient(145deg, #70c6ff, #56b9a8)",
  color: "#0d1720",
  fontSize: 11,
  fontWeight: 900,
};

const assistantStyle: React.CSSProperties = {
  minWidth: 0,
  display: "flex",
  flexDirection: "column",
  gap: 7,
  padding: "2px 2px 10px",
};

const assistantLabelStyle: React.CSSProperties = {
  color: "rgba(232,240,247,0.64)",
  fontSize: 10,
  fontWeight: 700,
};

const tokensStyle: React.CSSProperties = {
  fontSize: 10,
  opacity: 0.48,
};
