import type { ChatTurnEntry, ToolCall } from "../types/chat";

export type ServerMessage = {
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

export function hydrateDesignConversation(messages: ServerMessage[]): ChatTurnEntry[] {
  const entries: ChatTurnEntry[] = [];
  for (const message of messages) {
    if (message.role === "user" && typeof message.content === "string") {
      entries.push({ kind: "user", text: message.content });
      continue;
    }
    if (message.role === "user" && Array.isArray(message.content)) {
      const toolResults = message.content.filter((block) => block.type === "tool_result");
      if (!toolResults.length) continue;
      for (let index = entries.length - 1; index >= 0; index -= 1) {
        const entry = entries[index];
        if (entry.kind !== "assistant") continue;
        entry.toolCalls = entry.toolCalls.map((call) => {
          const match = toolResults.find((result) => result.tool_use_id === call.id);
          if (!match) return call;
          let parsed: unknown = match.content;
          try {
            parsed = match.content ? JSON.parse(match.content) : null;
          } catch {
            // Keep non-JSON legacy result text.
          }
          return {
            ...call,
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
  return entries.map((entry) =>
    entry.kind === "assistant"
      ? {
          ...entry,
          toolCalls: entry.toolCalls.map((call) =>
            call.status === "pending"
              ? {
                  ...call,
                  status: "error" as const,
                  isError: true,
                  result: { error: "operation_interrupted" },
                }
              : call,
          ),
        }
      : entry,
  );
}
