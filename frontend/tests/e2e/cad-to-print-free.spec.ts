import { expect, test } from "@playwright/test";

const BACKEND_URL = process.env.PLAYWRIGHT_BACKEND_URL ?? "http://127.0.0.1:8000";

test("user creates, locally edits, previews, and prepares a known-safe FDM design", async ({
  page,
  request,
}) => {
  test.setTimeout(300_000);

  const health = await request.get(`${BACKEND_URL}/health`);
  expect(health.ok()).toBeTruthy();
  const healthPayload = await health.json();
  expect(healthPayload.platform_ai_spend_enabled).toBe(false);

  await page.goto("/design");
  const createPrompt = page.getByPlaceholder(
    /uchwyt na telefon|phone holder/i,
  );
  await createPrompt.fill(
    "Kołowrotek dla chomika: średnica kołowrotka 12 cm, szerokość bieżnika 4 cm, dokładnie 24 szczebelki",
  );
  await page.getByRole("button", { name: /Utwórz model|Create model/i }).click();
  await expect(page).toHaveURL(/\?design=[a-zA-Z0-9_-]+/, { timeout: 120_000 });

  const designId = new URL(page.url()).searchParams.get("design");
  expect(designId).toBeTruthy();

  try {
    const canvas = page.locator("canvas").first();
    await expect(canvas).toBeVisible({ timeout: 60_000 });

    const initialResponse = await request.get(`${BACKEND_URL}/design/${designId}`);
    expect(initialResponse.ok()).toBeTruthy();
    const initial = await initialResponse.json();
    const initialRevision = String(initial.revision_id);
    const initialMeshHash = String(initial.latest_build.mesh_hash);
    const initialGlbUrl = String(initial.latest_build.artifacts.glb.url);
    const initialGlb = await request.get(new URL(initialGlbUrl, BACKEND_URL).toString());
    expect(initialGlb.ok()).toBeTruthy();
    const initialGlbBytes = await initialGlb.body();
    expect(initialGlbBytes.length).toBeGreaterThan(1_000);

    const chat = page.getByPlaceholder(/Napisz do Pulsai|Message Pulsai/i);
    await chat.fill("ustaw średnicę kołowrotka na 150 mm");
    const localApply = page.getByRole("button", { name: /\$0 · Zastosuj/i });
    await expect(localApply).toBeVisible();
    await localApply.click();

    await expect
      .poll(
        async () => {
          const response = await request.get(`${BACKEND_URL}/design/${designId}`);
          if (!response.ok()) return null;
          const payload = await response.json();
          return {
            revision: payload.revision_id,
            meshHash: payload.latest_build?.mesh_hash,
          };
        },
        { timeout: 120_000 },
      )
      .toEqual({
        revision: expect.not.stringMatching(initialRevision),
        meshHash: expect.not.stringMatching(initialMeshHash),
      });

    const editedResponse = await request.get(`${BACKEND_URL}/design/${designId}`);
    const edited = await editedResponse.json();
    expect(edited.revision_id).not.toBe(initialRevision);
    expect(edited.latest_build.mesh_hash).not.toBe(initialMeshHash);
    expect(
      edited.parameters.find((parameter: { name: string }) => parameter.name === "wheel_diameter")
        ?.value,
    ).toBe(150);

    const editedGlbUrl = String(edited.latest_build.artifacts.glb.url);
    const editedGlb = await request.get(new URL(editedGlbUrl, BACKEND_URL).toString());
    expect(editedGlb.ok()).toBeTruthy();
    const editedGlbBytes = await editedGlb.body();
    expect(editedGlbBytes.equals(initialGlbBytes)).toBeFalsy();

    const printRequest = page.waitForResponse(
      (response) =>
        response.url().endsWith(`/design/${designId}/print-bundle`) &&
        response.request().method() === "POST",
      { timeout: 180_000 },
    );
    await page.getByRole("button", { name: /Przygotuj do druku/i }).click();
    const printResponse = await printRequest;
    expect(printResponse.ok()).toBeTruthy();
    const printPayload = await printResponse.json();

    expect(["safe", "warn"]).toContain(printPayload.status);
    expect(printPayload.slicer_ready).toBe(true);
    expect(printPayload.gcode_ready).toBe(true);
    expect(printPayload.revision_id).toBe(edited.revision_id);
    expect(printPayload.manifest.mesh_hash).toBe(edited.latest_build.mesh_hash);
    expect(printPayload.manifest.artifacts.stl).toBeTruthy();
    expect(printPayload.manifest.artifacts.glb).toBeTruthy();
    expect(printPayload.manifest.artifacts.gcode).toBeTruthy();

    await expect(page.getByText(/Gotowe do druku/i)).toBeVisible();
    const bundleLink = page.getByRole("link", { name: /Pobierz pakiet/i });
    await expect(bundleLink).toBeVisible();
    const bundleHref = await bundleLink.getAttribute("href");
    expect(bundleHref).toBeTruthy();
    const bundle = await request.get(new URL(String(bundleHref), BACKEND_URL).toString());
    expect(bundle.ok()).toBeTruthy();
    const bundleBytes = await bundle.body();
    expect(bundleBytes.subarray(0, 2).toString()).toBe("PK");

    for (const kind of ["stl", "gcode"] as const) {
      const artifactUrl = String(printPayload.manifest.artifacts[kind].url);
      const artifact = await request.get(new URL(artifactUrl, BACKEND_URL).toString());
      expect(artifact.ok(), `${kind} artifact should be downloadable`).toBeTruthy();
      expect((await artifact.body()).length).toBeGreaterThan(100);
    }
  } finally {
    if (designId) {
      await request.delete(`${BACKEND_URL}/design/${designId}`);
    }
  }
});
