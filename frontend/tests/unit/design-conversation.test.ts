import assert from "node:assert/strict";
import test from "node:test";

import { hydrateDesignConversation } from "../../lib/design-conversation.ts";

test("historical dangling tools hydrate as interrupted instead of queued", () => {
  const history = hydrateDesignConversation([
    {
      role: "assistant",
      content: [{ type: "tool_use", id: "rewrite-1", name: "rewrite_design", input: {} }],
    },
  ]);

  assert.equal(history[0]?.kind, "assistant");
  if (history[0]?.kind !== "assistant") return;
  assert.equal(history[0].toolCalls[0]?.status, "error");
  assert.equal(history[0].toolCalls[0]?.isError, true);
});
