import type { UiLanguage } from "./ui-language";

const copy = {
  retry: {
    pl: "Nie udało się dokończyć tej wiadomości. Projekt pozostał bez zmian — spróbuj wysłać ją ponownie.",
    en: "This message could not be completed. Your design is unchanged — please try sending it again.",
  },
  busy: {
    pl: "Projektant AI jest teraz zajęty. Odczekaj chwilę i spróbuj ponownie.",
    en: "The AI designer is busy right now. Wait a moment and try again.",
  },
  unavailable: {
    pl: "Projektant AI jest chwilowo niedostępny. Projekt pozostał bez zmian — spróbuj ponownie za moment.",
    en: "The AI designer is temporarily unavailable. Your design is unchanged — try again shortly.",
  },
  byokInvalid: {
    pl: "Własny klucz Anthropic jest nieprawidłowy. Sprawdź format, ważność i uprawnienia klucza.",
    en: "Your Anthropic key is invalid. Check its format, expiration, and permissions.",
  },
} as const;

export function friendlyChatError(
  data: Record<string, unknown>,
  language: UiLanguage,
): string {
  const code = String(data.code ?? "");
  const raw = String(data.message ?? "");
  if (code === "ai_rate_limited" || /rate.?limit|429/i.test(raw)) {
    return copy.busy[language];
  }
  if (code === "byok_invalid" || code === "byok_auth_error") {
    return copy.byokInvalid[language];
  }
  if (code === "ai_unavailable" || code === "ai_auth_error" || code === "ai_circuit_open") {
    return copy.unavailable[language];
  }
  if (
    code === "ai_invalid_request" ||
    code === "cad_retry_exhausted" ||
    /Anthropic call failed|invalid_request|Field required|thinking/i.test(raw)
  ) {
    return copy.retry[language];
  }
  return raw && raw.length <= 240 ? raw : copy.retry[language];
}
