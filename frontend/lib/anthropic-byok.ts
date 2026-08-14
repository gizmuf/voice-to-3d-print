export const ANTHROPIC_BYOK_HEADER = "x-pulsai-anthropic-key";

export function anthropicByokHeaders(apiKey?: string): Record<string, string> {
  const key = apiKey?.trim();
  return key ? { [ANTHROPIC_BYOK_HEADER]: key } : {};
}

export function looksLikeAnthropicApiKey(apiKey: string): boolean {
  const key = apiKey.trim();
  return key.length <= 512 && key.startsWith("sk-ant-");
}
