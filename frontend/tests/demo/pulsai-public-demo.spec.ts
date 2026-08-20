import { expect, test } from "@playwright/test";

const BACKEND_URL = process.env.PLAYWRIGHT_BACKEND_URL ?? "http://127.0.0.1:8000";

const pause = (page: import("@playwright/test").Page, milliseconds: number) =>
  page.waitForTimeout(milliseconds);

test("records flagship CAD edit to print-bundle flow", async ({ page, request }) => {
  test.setTimeout(300_000);

  await page.addInitScript(() => {
    window.localStorage.setItem("pulsai:ui-language", "en");
  });

  const health = await request.get(`${BACKEND_URL}/health`);
  expect(health.ok()).toBeTruthy();
  const healthPayload = await health.json();
  expect(healthPayload.platform_ai_spend_enabled).toBe(false);

  // Briefly show the real product start screen, then create the reviewed
  // phone-stand flagship through the same backend endpoint used by the UI.
  // Calling the endpoint directly avoids depending on a responsive-layout
  // card that may be off-screen in headless capture while preserving the
  // exact production design/build path.
  await page.goto("/design");
  await pause(page, 1_400);

  const forkResponse = await request.post(`${BACKEND_URL}/design/flagship/fork`, {
    data: {
      flagship_id: "phone_stand",
      name: "Phone stand — public demo",
    },
  });
  expect(forkResponse.ok()).toBeTruthy();
  const forked = await forkResponse.json();
  const designId = String(forked.design_id ?? "");
  expect(designId).toMatch(/^[a-f0-9]{32}$/);

  await page.goto(`/design?design=${designId}`);

  try {
    const canvas = page.locator("canvas").first();
    await expect(canvas).toBeVisible({ timeout: 60_000 });
    await pause(page, 2_500);

    const initialResponse = await request.get(`${BACKEND_URL}/design/${designId}`);
    expect(initialResponse.ok()).toBeTruthy();
    const initial = await initialResponse.json();
    const initialRevision = String(initial.revision_id);
    const initialMeshHash = String(initial.latest_build.mesh_hash);

    const chat = page.getByPlaceholder(/Napisz do Pulsai|Message Pulsai/i);
    await chat.fill("set the stand angle to 75 degrees");
    const freeApply = page.getByRole("button", { name: /\$0 · Zastosuj/i });
    await expect(freeApply).toBeVisible({ timeout: 20_000 });
    await pause(page, 900);
    await freeApply.click();

    await expect
      .poll(
        async () => {
          const response = await request.get(`${BACKEND_URL}/design/${designId}`);
          if (!response.ok()) return null;
          const payload = await response.json();
          return {
            revision: String(payload.revision_id),
            meshHash: String(payload.latest_build?.mesh_hash ?? ""),
          };
        },
        { timeout: 120_000 },
      )
      .not.toEqual({ revision: initialRevision, meshHash: initialMeshHash });

    await pause(page, 2_300);

    const box = await canvas.boundingBox();
    if (box) {
      const centerX = box.x + box.width * 0.55;
      const centerY = box.y + box.height * 0.52;
      await page.mouse.move(centerX, centerY);
      await page.mouse.down();
      await page.mouse.move(centerX + 150, centerY - 45, { steps: 18 });
      await page.mouse.up();
      await pause(page, 1_400);
    }

    const printRequest = page.waitForResponse(
      (response) =>
        response.url().endsWith(`/design/${designId}/print-bundle`) &&
        response.request().method() === "POST",
      { timeout: 180_000 },
    );
    await page.getByRole("button", { name: /Przygotuj do druku/i }).click();
    const printResponse = await printRequest;
    expect(printResponse.ok()).toBeTruthy();

    await expect(page.getByText(/Gotowe do druku|Ready to print/i)).toBeVisible({
      timeout: 60_000,
    });
    await pause(page, 3_000);

    await page.screenshot({
      path: "../demo-output/pulsai-demo-poster.png",
      fullPage: false,
    });
    await pause(page, 1_200);
  } finally {
    await request.delete(`${BACKEND_URL}/design/${designId}`);
  }
});
