import { expect, test } from "@playwright/test";

test("provider settings accept multiple memory-only keys and routing choices", async ({ page }) => {
  await page.route("http://localhost:8000/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown = {};
    if (path === "/auth/config") body = { required: false, google_client_id: "" };
    else if (path === "/health") body = { slicer_ready: true, platform_ai_spend_enabled: false, warnings: [] };
    else if (path === "/account/ai-settings") body = {
      anthropic: { platform_access: false, billing_source: "customer_byok", model: "claude-sonnet-5" },
      keys_persisted: false,
    };
    else if (path === "/design/templates") body = { templates: [] };
    else if (path === "/design/recent") body = { designs: [] };
    else if (path === "/printers") body = { profiles: [], default_id: null };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });

  await page.goto("/design");
  await page.locator("summary").filter({ hasText: /AI:/ }).click();

  await page.locator('input[name="pulsai-anthropic-byok"]').fill("sk-ant-example");
  await page.locator('input[name="pulsai-openai-byok"]').fill("sk-example");
  await page.getByLabel("Organic models").selectOption("tripo");
  await page.getByLabel("Quality / cost").selectOption("quality");

  await expect(page.locator('input[name="pulsai-anthropic-byok"]')).toHaveValue("sk-ant-example");
  await expect(page.locator('input[name="pulsai-openai-byok"]')).toHaveValue("sk-example");
  await expect(page.locator("summary").filter({ hasText: /AI:/ })).toContainText("2 keys");
  await expect(page.getByText(/Keys stay only in this tab's memory/)).toBeVisible();
});

test("organic prompt uses Tripo, repairs the mesh, and imports it into Design Studio", async ({ page }) => {
  const calls: string[] = [];
  await page.route("http://localhost:8000/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    calls.push(path);
    if (path === "/auth/config") return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ required: false, google_client_id: "" }) });
    if (path === "/health") return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ slicer_ready: true, platform_ai_spend_enabled: false, warnings: [] }) });
    if (path === "/account/ai-settings") return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ anthropic: { platform_access: false, billing_source: "customer_byok", model: "claude-sonnet-5" }, keys_persisted: false }) });
    if (path === "/route-intent") return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ mode: "creative", provider: "meshy", prompt: "figurka motoparalotniarza" }) });
    if (path === "/generate") {
      const payload = route.request().postDataJSON();
      expect(payload.provider).toBe("tripo");
      expect(route.request().headers()["x-pulsai-tripo-key"]).toBe("tsk_1234567890123456");
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ job_id: "a".repeat(32), provider: "tripo", task_id: "task", glb_url: "https://provider.example/model.glb" }) });
    }
    if (path === "/process-model") return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ job_id: "a".repeat(32), glb_url: "/artifacts/a/model.glb", stl_url: "/artifacts/a/model.stl", gcode_url: null }) });
    if (path === "/artifacts/a/model.stl") return route.fulfill({ status: 200, contentType: "model/stl", body: "solid organic\nendsolid organic\n" });
    if (path === "/design/import-cad") return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ design_id: "b".repeat(32), revision_id: "revision-1", name: "Figurka motoparalotniarza", process: "fdm", script: "", parameters: [], features: [], initial_build: null }) });
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({}) });
  });

  await page.goto("/design");
  await page.locator("summary").filter({ hasText: /AI:/ }).click();
  await page.locator('input[name="pulsai-tripo-byok"]').fill("tsk_1234567890123456");
  await page.getByPlaceholder(/phone holder|uchwyt na telefon/i).fill("figurka motoparalotniarza");
  await page.getByRole("button", { name: /Create model|Utwórz model/ }).click();

  await expect(page.getByRole("heading", { name: "Figurka motoparalotniarza" })).toBeVisible();
  expect(calls).toEqual(expect.arrayContaining(["/route-intent", "/generate", "/process-model", "/design/import-cad"]));
});
