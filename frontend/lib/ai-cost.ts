export type TokenUsage = {
  input: number;
  output: number;
  cacheRead: number;
  cacheCreation: number;
};

type ClaudeRates = {
  input: number;
  output: number;
  cacheRead: number;
  cacheWrite: number;
};

const SONNET_5_PROMO_END = Date.UTC(2026, 8, 1);

export function claudeRates(model?: string, now = Date.now()): ClaudeRates {
  if ((model ?? "").includes("sonnet-5") && now < SONNET_5_PROMO_END) {
    return { input: 2, output: 10, cacheRead: 0.2, cacheWrite: 2.5 };
  }
  if ((model ?? "").includes("opus-5")) {
    return { input: 5, output: 25, cacheRead: 0.5, cacheWrite: 6.25 };
  }
  return { input: 3, output: 15, cacheRead: 0.3, cacheWrite: 3.75 };
}

export function tokenCostUsd(usage: TokenUsage, model?: string): number {
  const rates = claudeRates(model);
  return (
    usage.input * rates.input +
    usage.output * rates.output +
    usage.cacheRead * rates.cacheRead +
    usage.cacheCreation * rates.cacheWrite
  ) / 1_000_000;
}

export function formatUsd(value: number): string {
  if (value <= 0) return "$0.00";
  if (value < 0.001) return "<$0.001";
  return `$${value.toFixed(value < 0.01 ? 4 : value < 1 ? 3 : 2)}`;
}

export function displayModelName(model?: string): string {
  if (!model) return "Pulsai";
  if (model.includes("sonnet-5")) return "Sonnet 5";
  if (model.includes("opus-5")) return "Opus 5";
  if (model.includes("gemini-3.5-flash-lite")) return "Gemini 3.5 Flash-Lite";
  if (model === "local") return "Lokalnie";
  return model;
}
