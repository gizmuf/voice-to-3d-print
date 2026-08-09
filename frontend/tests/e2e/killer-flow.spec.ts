import { expect, test } from "@playwright/test";

/**
 * Killer flow smoke test.
 *
 * Anonymous user lands → seeds a perforated-disc workspace → has a multi-turn
 * chat → exports a ZIP bundle. Asserts the manifest is well-formed, the
 * editability badge is shown, and the export succeeds.
 *
 * Requires:
 *   - Frontend running (Playwright config starts `npm run dev` by default).
 *   - Backend running on localhost:8000 with ANTHROPIC_API_KEY set
 *     and PrusaSlicer + CadQuery available.
 *
 * Run:  npx playwright test killer-flow.spec.ts
 */

const BACKEND_URL = process.env.PLAYWRIGHT_BACKEND_URL ?? "http://localhost:8000";

test("anonymous user creates, edits, and exports a perforated disc bundle", async ({
  page,
  request,
}) => {
  // 1. Backend health check — fail fast if the API isn't up.
  const health = await request.get(`${BACKEND_URL}/health`);
  expect(health.ok()).toBeTruthy();

  // 2. Seed a workspace deterministically by hitting the backend directly. The
  // frontend hero flow exercises the same path; we skip the UI dance to keep
  // this test fast and focused on the chat + export contract.
  const previewResp = await request.post(`${BACKEND_URL}/preview-useful`, {
    data: {
      structured_spec: {
        template_id: "perforated_disc",
        object_label: "Speaker grill",
        dimensions_mm: { outer_diameter: 320, thickness: 5 },
        constraints: {
          center_hole_diameter_mm: 16,
          hole_diameter_mm: 7,
          ring_count: 12,
          radial_spacing_mm: 18,
          tangential_spacing_mm: 14,
          edge_margin_mm: 6,
        },
        source_inputs: { text: "speaker grill 320mm" },
      },
    },
  });
  expect(previewResp.ok()).toBeTruthy();
  const preview = await previewResp.json();
  const workspaceId: string = preview.preview_id ?? preview.job_id;
  expect(workspaceId).toBeTruthy();

  // 3. Editability badge contract.
  const editResp = await request.get(
    `${BACKEND_URL}/workspace/${workspaceId}/editability`,
  );
  expect(editResp.ok()).toBeTruthy();
  const editPayload = await editResp.json();
  expect(editPayload.assessment.level).toBe("editable");
  expect(editPayload.assessment.export_allowed).toBeTruthy();
  expect(editPayload.assessment.export_mode).toBe("rebuilt");

  // 4. Chat turn 1: change hole diameter via the agent.
  const chatTurn1 = await streamOneTurn(request, workspaceId, "make the holes 9mm");
  expect(chatTurn1.tool_calls.some((t) => t.name === "mutate_parameter" && !t.is_error))
    .toBeTruthy();

  // 5. Confirm revision rolled forward and matches.
  const wsAfter = await request
    .get(`${BACKEND_URL}/workspace/${workspaceId}`)
    .then((r) => r.json());
  const expectedRevisionId = wsAfter.editable_model.revision_id;
  expect(expectedRevisionId).not.toEqual(preview.editable_model?.revision_id);

  // 6. Export the bundle, validating the revision-truth check by passing the
  //    fresh revision id.
  const bundleResp = await request.post(
    `${BACKEND_URL}/workspace/${workspaceId}/export-bundle`,
    {
      data: { expected_revision_id: expectedRevisionId },
    },
  );
  expect(bundleResp.ok()).toBeTruthy();
  const bundle = await bundleResp.json();
  expect(bundle.bundle_url).toBeTruthy();
  expect(bundle.manifest.editability_level).toBe("editable");
  expect(bundle.manifest.export_mode).toBe("rebuilt");
  expect(bundle.manifest.revision_id).toBe(expectedRevisionId);
  expect(bundle.manifest.printer_profile.id).toBe("prusa_mk4_default");
  expect(bundle.manifest.parameter_values).toBeTruthy();
  expect(bundle.manifest.software_version).toContain("pulsai-3d/");

  // 7. Stale revision must be rejected by the export gate.
  const staleResp = await request.post(
    `${BACKEND_URL}/workspace/${workspaceId}/export-bundle`,
    { data: { expected_revision_id: "deadbeef" } },
  );
  expect(staleResp.status()).toBe(409);

  // 8. Frontend renders the editability badge near the model title.
  await page.goto(`/?workspace=${workspaceId}`);
  await expect(
    page.locator(".editability-badge").first(),
  ).toBeVisible({ timeout: 30_000 });
});

test("validated hamster wheel rotates independently with zero-cost local edits", async ({
  page,
  request,
}) => {
  const create = await request.post(`${BACKEND_URL}/design/create`, {
    data: {
      prompt:
        "Kołowrotek dla chomika: średnica kołowrotka 12 cm, szerokość bieżnika 4 cm, dokładnie 24 szczebelki",
      process: "fdm",
    },
    timeout: 180_000,
  });
  expect(create.ok()).toBeTruthy();
  const seeded = await create.json();
  const designId = seeded.design_id as string;

  try {
    expect(seeded.requires_agent).toBeFalsy();
    expect(seeded.spec_compliance.status).toBe("passed");
    expect(seeded.motion_report.status).toBe("safe");
    expect(seeded.parameters.filter((parameter: { name: string }) => parameter.name === "rung_count"))
      .toHaveLength(1);

    const localEdit = await streamOneDesignTurn(
      request,
      designId,
      "zmień średnicę kołowrotka na 150 mm oraz szerokość bieżnika na 50 mm",
    );
    expect(localEdit.final.model).toBe("local");
    expect(localEdit.final.cost_usd).toBe(0);
    expect(localEdit.compliance.status).toBe("passed");

    await page.goto(`/design?design=${designId}`);
    const motionButton = page.getByRole("button", { name: /Test rotation|Test obrotu/ });
    await expect(motionButton).toBeVisible({ timeout: 30_000 });
    const canvas = page.locator("canvas").first();
    await expect(canvas).toBeVisible();
    const before = await canvas.screenshot();

    await motionButton.click();
    await expect(page.locator('[data-motion-running="true"]')).toBeVisible();
    await expect(page.getByText(/Motion geometry: OK|Geometria ruchu: OK/)).toBeVisible();
    await page.waitForTimeout(700);
    const after = await canvas.screenshot();

    expect(after.equals(before)).toBeFalsy();
  } finally {
    await request.delete(`${BACKEND_URL}/design/${designId}`);
  }
});

type ToolCallEvent = {
  name: string;
  result?: Record<string, unknown>;
  is_error?: boolean;
};

async function streamOneTurn(
  request: import("@playwright/test").APIRequestContext,
  workspaceId: string,
  message: string,
): Promise<{ tool_calls: ToolCallEvent[]; assistant_text: string }> {
  const response = await request.post(
    `${BACKEND_URL}/workspace/${workspaceId}/chat`,
    {
      data: { message },
      timeout: 120_000,
    },
  );
  expect(response.ok()).toBeTruthy();
  const body = await response.text();
  const tool_calls: ToolCallEvent[] = [];
  let assistant_text = "";
  for (const block of body.split("\n\n")) {
    if (!block.trim()) continue;
    let event = "message";
    let data = "";
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data += line.slice(5).trim();
    }
    if (!data) continue;
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(data);
    } catch {
      continue;
    }
    if (event === "tool_call_end") {
      tool_calls.push({
        name: String(parsed.name),
        result: parsed.result as Record<string, unknown>,
        is_error: Boolean(parsed.is_error),
      });
    } else if (event === "assistant_text") {
      assistant_text += String(parsed.text ?? "");
    }
  }
  return { tool_calls, assistant_text };
}

async function streamOneDesignTurn(
  request: import("@playwright/test").APIRequestContext,
  designId: string,
  message: string,
): Promise<{ final: Record<string, unknown>; compliance: Record<string, unknown> }> {
  const response = await request.post(`${BACKEND_URL}/design/${designId}/chat`, {
    data: { message },
    timeout: 180_000,
  });
  expect(response.ok()).toBeTruthy();
  const body = await response.text();
  let final: Record<string, unknown> = {};
  let compliance: Record<string, unknown> = {};
  for (const block of body.split("\n\n")) {
    let event = "";
    let data = "";
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data += line.slice(5).trim();
    }
    if (!data) continue;
    const parsed = JSON.parse(data) as Record<string, unknown>;
    if (event === "turn_end") final = parsed;
    if (event === "compliance_report") compliance = parsed;
  }
  return { final, compliance };
}
