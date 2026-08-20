import { expect, test, type Page } from "@playwright/test";

test.use({
  userAgent:
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Codex/1.0 Electron/37",
});

async function mockUnauthenticatedGoogle(page: Page) {
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
}

test("Google login is popup-compatible and explains embedded-browser fallback in English", async ({ page }) => {
  await mockUnauthenticatedGoogle(page);

  const response = await page.goto("/design");
  expect(response?.headers()["cross-origin-opener-policy"]).toBe("same-origin-allow-popups");
  await expect(page.getByRole("button", { name: "Continue with Google" })).toBeVisible();
  await expect(page.getByText("Sign in with Google so your projects and files remain private to your account.")).toBeVisible();
  await expect(page.getByRole("note")).toContainText("This is an embedded browser.");
  await expect(page.getByRole("link", { name: "Privacy" })).toHaveAttribute("href", "/privacy");
  await expect(page.getByRole("link", { name: "Terms" })).toHaveAttribute("href", "/terms");
  await expect(page.getByRole("link", { name: "Source" })).toHaveAttribute("href", "https://github.com/gizmuf/voice-to-3d-print");
});

test("Google login is readable in Polish for a Polish browser locale", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(window.navigator, "language", { configurable: true, value: "pl-PL" });
    Object.defineProperty(window.navigator, "languages", { configurable: true, value: ["pl-PL", "pl"] });
  });
  await mockUnauthenticatedGoogle(page);

  await page.goto("/design");
  await expect(page.getByText("Zaloguj się przez Google, aby projekty i pliki były widoczne tylko dla Ciebie.")).toBeVisible();
  await expect(page.getByRole("note")).toContainText("To jest przeglądarka osadzona.");
  await expect(page.getByRole("link", { name: "Privacy" })).toHaveAttribute("href", "/privacy");
});

test("Google login honors a stored UI language preference", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.setItem("pulsai:ui-language", "pl"));
  await mockUnauthenticatedGoogle(page);

  await page.goto("/design");
  await expect(page.getByText("Zaloguj się przez Google, aby projekty i pliki były widoczne tylko dla Ciebie.")).toBeVisible();
});
