import assert from "node:assert/strict";
import test from "node:test";

import { resolveUrl } from "../../lib/backend.ts";

test("export bundle urls stay downloadable through the authenticated backend", () => {
  const backendUrl = "https://api.3d.pulsai.app";
  const relative = "/cloud-artifacts/three-d/designs/abc/exports/fdm/model.zip";
  const absolute = "https://api.3d.pulsai.app/cloud-artifacts/three-d/designs/abc/exports/fdm/model.zip";

  assert.equal(resolveUrl(backendUrl, relative), absolute);
  assert.equal(resolveUrl(backendUrl, absolute), absolute);
  assert.equal(resolveUrl(backendUrl, null), null);
});

test("tester guide no longer promises a guaranteed STL/STEP/GLB picker", async () => {
  const { readFile } = await import("node:fs/promises");
  const guide = await readFile(new URL("../../../docs/HELP_WITHOUT_CODING.md", import.meta.url), "utf8");
  assert.match(guide, /Chrome or Safari/);
  assert.match(guide, /Sign in with Google/);
  assert.match(guide, /Napisz do Pulsai/);
  assert.match(guide, /Non-coder feedback/);
  assert.match(guide, /If the sliders return to the first values, stop/);
});
