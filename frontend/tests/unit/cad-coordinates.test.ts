import assert from "node:assert/strict";
import test from "node:test";

import { cadPointToViewer } from "../../lib/cad-coordinates.ts";

test("converts CAD Z-up coordinates to the GLB Y-up viewer", () => {
  assert.deepEqual(
    cadPointToViewer({ x: -28, y: -27.3, z: 96.3 }),
    { x: -28, y: 96.3, z: 27.3 },
  );
});

