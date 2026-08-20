import { expect, test } from "@playwright/test";

const BACKEND_URL = process.env.PLAYWRIGHT_BACKEND_URL ?? "http://127.0.0.1:8000";

const pause = (page: import("@playwright/test").Page, milliseconds: number) =>
  page.waitForTimeout(milliseconds);

test("records prompt to editable CAD to print-bundle flow", async ({ page, request }) => {
  test.setTimeout(300_000);

  await page.addInitScript(() => {
    window.localStorage.setItem("pulsai:ui-language", "en");
  });

  const health = await request.get(`${BACKEND_URL}/health`);
  expect(health.ok()).toBeTruthy();
  const healthPayload = await health.json();
  expect(healthPayload.platform_ai_spend_enabled).toBe(false);

  await page.goto("/design");
  await pause(page, 1_200);

  const createPrompt = page.getByPlaceholder(/uchwyt na telefon|phone holder/i);
  await createPrompt.fill("phone stand 65 degrees, cable hole");
  await pause(page, 900);
  await page.getByRole("button", { name: /Utwórz model|Create model/i }).click();
  await expect(page).toHaveURL(/\?design=[a-zA-Z0-9_-]+/, { timeout: 120_000 });

  const designId = new URL(page.url()).searchParams.get("design");
  expect(designId).toBeTruthy();

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
    if (designId) {
      await request.delete(`${BACKEND_URL}/design/${designId}`);
    }
  }
});
