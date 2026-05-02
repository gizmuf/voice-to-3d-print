"use client";

import type { ChatTurnEntry } from "../../types/chat";

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
    <div style={assistantStyle} className="chat-message chat-message-assistant">
      {entry.toolCalls.length ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {entry.toolCalls.map((call) => (
            <ToolCallCard key={call.id} call={call} />
          ))}
        </div>
      ) : null}
      {entry.text ? (
        <div style={{ whiteSpace: "pre-wrap", lineHeight: 1.45 }}>{entry.text}</div>
      ) : null}
      {entry.tokens ? (
        <div style={tokensStyle}>
          {tokensSummary(entry.tokens)} · {dollarSummary(entry.tokens)}
          {entry.revisionIdAfter ? ` · rev ${entry.revisionIdAfter.slice(0, 8)}` : ""}
        </div>
      ) : null}
    </div>
  );
}

function tokensSummary(t: { input: number; output: number; cacheRead: number }) {
  return `${t.input} in / ${t.output} out${t.cacheRead ? ` · ${t.cacheRead} cached` : ""}`;
}

function dollarSummary(t: {
  input: number;
  output: number;
  cacheRead: number;
  cacheCreation: number;
}) {
  // Sonnet 4.6 published rates (verify on the Anthropic console for your account).
  const inputCost = (t.input / 1_000_000) * 3;
  const outputCost = (t.output / 1_000_000) * 15;
  const cacheReadCost = (t.cacheRead / 1_000_000) * 0.3;
  const cacheWriteCost = (t.cacheCreation / 1_000_000) * 3.75;
  const total = inputCost + outputCost + cacheReadCost + cacheWriteCost;
  if (total < 0.001) return "<$0.001";
  return `$${total.toFixed(total < 0.01 ? 4 : total < 1 ? 3 : 2)}`;
}

const baseStyle: React.CSSProperties = {
  padding: "10px 12px",
  borderRadius: 10,
  fontSize: 13,
};

const userStyle: React.CSSProperties = {
  ...baseStyle,
  background: "rgba(33,150,243,0.18)",
  border: "1px solid rgba(33,150,243,0.45)",
  alignSelf: "flex-end",
  maxWidth: "85%",
};

const assistantStyle: React.CSSProperties = {
  ...baseStyle,
  background: "rgba(255,255,255,0.04)",
  border: "1px solid rgba(255,255,255,0.08)",
  display: "flex",
  flexDirection: "column",
  gap: 8,
};

const tokensStyle: React.CSSProperties = {
  fontSize: 11,
  opacity: 0.55,
};
