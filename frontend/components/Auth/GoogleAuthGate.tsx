"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { usePathname } from "next/navigation";

import { resolveBackendUrl } from "../../lib/backend";
import { isLikelyEmbeddedBrowser } from "../../lib/embedded-browser";
import { uiText, useUiLanguage, type UiLanguage } from "../../lib/ui-language";

type AuthConfig = {
  required: boolean;
  google_client_id: string;
};

type GoogleCredentialResponse = { credential?: string };

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (options: {
            client_id: string;
            callback: (response: GoogleCredentialResponse) => void;
            auto_select?: boolean;
          }) => void;
          renderButton: (
            element: HTMLElement,
            options: Record<string, string | number | boolean>,
          ) => void;
          disableAutoSelect: () => void;
        };
      };
    };
  }
}

export default function GoogleAuthGate({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const backendUrl = resolveBackendUrl();
  const { language } = useUiLanguage();
  const t = (polish: string, english: string) => uiText(language, polish, english);
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const [credential, setCredential] = useState("");
  const [sessionChecked, setSessionChecked] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);
  const [error, setError] = useState("");
  const [embeddedBrowser] = useState(
    () => typeof window !== "undefined" && isLikelyEmbeddedBrowser(window.navigator.userAgent),
  );
  const buttonRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetch(`${backendUrl}/auth/config`)
      .then(async (response) => {
        if (!response.ok) throw new Error(`Auth configuration failed: ${response.status}`);
        return response.json() as Promise<AuthConfig>;
      })
      .then(setConfig)
      .catch(() =>
        setError(
          uiText(
            language,
            "Nie udało się sprawdzić konfiguracji logowania.",
            "Could not verify the sign-in configuration.",
          ),
        ),
      );
  }, [backendUrl, language]);

  useEffect(() => {
    if (!config) return;
    if (!config.required) {
      setAuthenticated(true);
      setSessionChecked(true);
      return;
    }
    fetch(`${backendUrl}/auth/session`, { credentials: "include" })
      .then((response) => setAuthenticated(response.ok))
      .catch(() => setAuthenticated(false))
      .finally(() => setSessionChecked(true));
  }, [backendUrl, config]);

  useEffect(() => {
    if (!config?.required || !config.google_client_id || !sessionChecked || authenticated) return;
    const initialize = () => {
      if (!window.google || !buttonRef.current) return;
      window.google.accounts.id.initialize({
        client_id: config.google_client_id,
        auto_select: false,
        callback: async (response) => {
          if (!response.credential) {
            setError(
              uiText(
                language,
                "Google nie zwrócił ważnej sesji.",
                "Google did not return a valid session.",
              ),
            );
            return;
          }
          try {
            const session = await fetch(`${backendUrl}/auth/session`, {
              method: "POST",
              headers: { authorization: `Bearer ${response.credential}` },
              credentials: "include",
            });
            if (!session.ok) throw new Error("session rejected");
            setError("");
            setCredential(response.credential);
            setAuthenticated(true);
          } catch {
            setError(
              uiText(
                language,
                "Nie udało się utworzyć bezpiecznej sesji. Spróbuj ponownie.",
                "Could not create a secure session. Please try again.",
              ),
            );
          }
        },
      });
      buttonRef.current.replaceChildren();
      window.google.accounts.id.renderButton(buttonRef.current, {
        type: "standard",
        theme: "outline",
        size: "large",
        text: "continue_with",
        shape: "pill",
        width: 280,
      });
    };
    const existing = document.querySelector<HTMLScriptElement>("script[data-pulsai-google-login]");
    if (existing) {
      if (window.google) initialize();
      else existing.addEventListener("load", initialize, { once: true });
      return;
    }
    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.defer = true;
    script.dataset.pulsaiGoogleLogin = "true";
    script.addEventListener("load", initialize, { once: true });
    script.addEventListener(
      "error",
      () =>
        setError(
          uiText(
            language,
            "Nie udało się wczytać Google Login.",
            "Could not load Google Login.",
          ),
        ),
      { once: true },
    );
    document.head.appendChild(script);
  }, [authenticated, backendUrl, config, language, sessionChecked]);

  useEffect(() => {
    // Local development deliberately runs without auth. Installing the
    // credentialed fetch wrapper there would make wildcard-CORS responses
    // invalid in browsers (`*` cannot be combined with credentials).
    if (!config?.required || !authenticated) return;
    const originalFetch = window.fetch.bind(window);
    const backendOrigin = new URL(backendUrl, window.location.href).origin;
    window.fetch = async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const rawUrl = input instanceof Request ? input.url : String(input);
      const target = new URL(rawUrl, window.location.href);
      if (target.origin !== backendOrigin) return originalFetch(input, init);
      const headers = new Headers(input instanceof Request ? input.headers : undefined);
      new Headers(init.headers).forEach((value, key) => headers.set(key, value));
      if (credential) headers.set("authorization", `Bearer ${credential}`);
      else headers.set("x-pulsai-csrf", "same-origin");
      const response = await originalFetch(input, { ...init, headers, credentials: "include" });
      if (response.status === 401) {
        setCredential("");
        setAuthenticated(false);
        window.google?.accounts.id.disableAutoSelect();
      }
      return response;
    };
    return () => {
      window.fetch = originalFetch;
    };
  }, [authenticated, backendUrl, config?.required, credential]);

  // Google requires the homepage and privacy policy linked from OAuth branding
  // to remain publicly accessible, including before a user signs in.
  if (pathname === "/privacy" || pathname === "/terms") {
    return <AppWithSource>{children}</AppWithSource>;
  }
  if (error) {
    return (
      <AuthShell
        message={error}
        buttonRef={buttonRef}
        embeddedBrowser={embeddedBrowser}
        language={language}
      />
    );
  }
  if (!config) {
    return (
      <AuthShell
        message={t("Sprawdzam bezpieczne logowanie…", "Checking secure sign-in…")}
        language={language}
      />
    );
  }
  if (!config.required) return <AppWithSource>{children}</AppWithSource>;
  if (!config.google_client_id) {
    return (
      <AuthShell
        message={t(
          "Google Login nie jest jeszcze skonfigurowany po stronie serwera.",
          "Google Login is not configured on the server yet.",
        )}
        language={language}
      />
    );
  }
  if (!sessionChecked) {
    return (
      <AuthShell
        message={t("Sprawdzam istniejącą sesję Google…", "Checking your existing Google session…")}
        language={language}
      />
    );
  }
  if (!authenticated) {
    return (
      <AuthShell
        message={t(
          "Zaloguj się przez Google, aby projekty i pliki były widoczne tylko dla Ciebie.",
          "Sign in with Google so your projects and files remain private to your account.",
        )}
        buttonRef={buttonRef}
        embeddedBrowser={embeddedBrowser}
        language={language}
      />
    );
  }
  return <AppWithSource>{children}</AppWithSource>;
}

function AppWithSource({ children }: { children: ReactNode }) {
  return (
    <>
      {children}
      <a
        href="https://github.com/gizmuf/voice-to-3d-print"
        target="_blank"
        rel="noreferrer"
        style={{ position: "fixed", right: 12, bottom: 8, zIndex: 2000, fontSize: 11, opacity: 0.62 }}
      >
        Source · AGPL-3.0
      </a>
    </>
  );
}

function AuthShell({
  message,
  buttonRef,
  embeddedBrowser = false,
  language,
}: {
  message: string;
  buttonRef?: React.RefObject<HTMLDivElement | null>;
  embeddedBrowser?: boolean;
  language: UiLanguage;
}) {
  return (
    <main style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: 24 }}>
      <section style={{ width: "min(440px, 100%)", padding: 32, border: "1px solid rgba(0,0,0,.12)", borderRadius: 20, background: "rgba(255,255,255,.9)", textAlign: "center", boxShadow: "0 20px 60px rgba(23,34,44,.12)" }}>
        <strong style={{ display: "block", fontSize: 24, marginBottom: 12 }}>Pulsai 3D</strong>
        <p style={{ lineHeight: 1.55, opacity: 0.75 }}>{message}</p>
        {buttonRef ? (
          <>
            <div ref={buttonRef} style={{ display: "flex", justifyContent: "center", marginTop: 20 }} />
            <p
              role="note"
              style={{ margin: "14px auto 0", maxWidth: 340, fontSize: 12, lineHeight: 1.5, opacity: 0.68 }}
            >
              {embeddedBrowser
                ? uiText(
                    language,
                    "To jest przeglądarka osadzona. Google może blokować w niej logowanie. W menu tej karty wybierz „Open in external browser” i zaloguj się w Chrome lub Safari.",
                    "This is an embedded browser. Google may block sign-in here. Use this tab's menu to choose ‘Open in external browser’, then sign in with Chrome or Safari.",
                  )
                : uiText(
                    language,
                    "Puste okno logowania? Otwórz tę stronę w Chrome lub Safari.",
                    "Blank sign-in window? Open this page in Chrome or Safari.",
                  )}
            </p>
          </>
        ) : null}
        <nav style={{ display: "flex", justifyContent: "center", gap: 16, marginTop: 22, fontSize: 12 }}>
          <a href="/privacy">Privacy</a>
          <a href="/terms">Terms</a>
          <a href="https://github.com/gizmuf/voice-to-3d-print" target="_blank" rel="noreferrer">Source</a>
        </nav>
      </section>
    </main>
  );
}
