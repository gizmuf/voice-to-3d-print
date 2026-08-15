import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

import { isLikelyEmbeddedBrowser } from "../../lib/embedded-browser.ts";

const require = createRequire(import.meta.url);
const nextConfig = require("../../next.config.js");

test("recognizes embedded browser user agents without flagging regular browsers", () => {
  assert.equal(isLikelyEmbeddedBrowser("Mozilla/5.0 Codex/1.0 Electron/37"), true);
  assert.equal(isLikelyEmbeddedBrowser("Mozilla/5.0 (Linux; Android 15; wv)"), true);
  assert.equal(
    isLikelyEmbeddedBrowser(
      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/140 Safari/537.36",
    ),
    false,
  );
});

test("serves the headers required for Google popup communication", async () => {
  const routes = await nextConfig.headers();
  const allHeaders = routes.flatMap(
    (route: { headers: Array<{ key: string; value: string }> }) => route.headers,
  );
  const headers = Object.fromEntries(
    allHeaders.map(({ key, value }: { key: string; value: string }) => [key.toLowerCase(), value]),
  );

  assert.equal(headers["cross-origin-opener-policy"], "same-origin-allow-popups");
  assert.equal(headers["referrer-policy"], "strict-origin-when-cross-origin");
});
