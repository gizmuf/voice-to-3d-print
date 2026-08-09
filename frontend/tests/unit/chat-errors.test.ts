import assert from "node:assert/strict";
import test from "node:test";

import { friendlyChatError } from "../../lib/chat-errors.ts";

test("hides raw Anthropic validation details from Polish users", () => {
  const message = friendlyChatError(
    {
      message: "Anthropic call failed: messages.7.content.0.thinking.thinking: Field required",
    },
    "pl",
  );

  assert.equal(
    message,
    "Nie udało się dokończyć tej wiadomości. Projekt pozostał bez zmian — spróbuj wysłać ją ponownie.",
  );
  assert.doesNotMatch(message, /Anthropic|thinking|Field required/);
});

test("uses a specific retry message for rate limiting", () => {
  assert.equal(
    friendlyChatError({ code: "ai_rate_limited" }, "en"),
    "The AI designer is busy right now. Wait a moment and try again.",
  );
});

