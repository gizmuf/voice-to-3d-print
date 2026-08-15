import assert from "node:assert/strict";
import test from "node:test";

import {
  looksLikeProviderKey,
  providerKeyHeaders,
  selectMeshProvider,
} from "../../lib/provider-keys.ts";

test("sends only explicitly selected non-empty keys", () => {
  assert.deepEqual(
    providerKeyHeaders({ openai: " sk-test ", tripo: "tsk_1234567890123456" }, ["openai"]),
    { "x-pulsai-openai-key": "sk-test" },
  );
});

test("rejects whitespace and recognizes provider prefixes", () => {
  assert.equal(looksLikeProviderKey("anthropic", "sk-ant-test"), true);
  assert.equal(looksLikeProviderKey("openai", "sk-test value"), false);
  assert.equal(looksLikeProviderKey("gemini", "AIza-test"), true);
});

test("routes organic characters to Tripo when both keys exist", () => {
  const keys = { meshy: "meshy_1234567890123456", tripo: "tsk_1234567890123456" };
  assert.equal(selectMeshProvider("figurka motoparalotniarza", "auto", keys), "tripo");
  assert.equal(selectMeshProvider("decorative vase", "auto", keys), "meshy");
  assert.equal(selectMeshProvider("anything", "meshy", keys), "meshy");
});
