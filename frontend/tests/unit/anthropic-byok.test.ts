import assert from "node:assert/strict";
import test from "node:test";

import {
  ANTHROPIC_BYOK_HEADER,
  anthropicByokHeaders,
  looksLikeAnthropicApiKey,
} from "../../lib/anthropic-byok.ts";

test("adds BYOK only as the dedicated request header", () => {
  const key = "sk-ant-api03-customer-secret";
  const headers = anthropicByokHeaders(`  ${key}  `);

  assert.deepEqual(headers, { [ANTHROPIC_BYOK_HEADER]: key });
  assert.equal(JSON.stringify({ message: "make a bracket" }).includes(key), false);
});

test("omits empty BYOK and validates the expected prefix", () => {
  assert.deepEqual(anthropicByokHeaders(""), {});
  assert.equal(looksLikeAnthropicApiKey("sk-ant-api03-customer-secret"), true);
  assert.equal(looksLikeAnthropicApiKey("not-a-key"), false);
});
