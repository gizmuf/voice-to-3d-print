import { expect, test } from "@playwright/test";

test.use({
  userAgent:
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Codex/1.0 Electron/37",
});

test("Google login is popup-compatible and explains embedded-browser fallback", async ({ page }) => {
  await page.route("http://localhost:8000/auth/config", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "access-control-allow-origin": "*" },
      body: JSON.stringify({ required: true, google_client_id: "test.apps.googleusercontent.com" }),
    });
  });
  await page.route("http://localhost:8000/auth/session", async (route) => {
    await route.fulfill({
      status: 401,
      contentType: "application/json",
      headers: {
        "access-control-allow-origin": "http://127.0.0.1:3100",
        "access-control-allow-credentials": "true",
      },
      body: JSON.stringify({ detail: "Not authenticated" }),
    });
  });
  await page.route("https://accounts.google.com/gsi/client", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/javascript",
      body: `
        window.google = { accounts: { id: {
          initialize: () => {},
          renderButton: (element) => {
            const button = document.createElement("button");
            button.textContent = "Continue with Google";
            element.appendChild(button);
          },
          disableAutoSelect: () => {},
        } } };
      `,
    });
  });

  const response = await page.goto("/design");
  expect(response?.headers()["cross-origin-opener-policy"]).toBe("same-origin-allow-popups");
  await expect(page.getByRole("button", { name: "Continue with Google" })).toBeVisible();
  await expect(page.getByRole("note")).toContainText("Open in external browser");
});
