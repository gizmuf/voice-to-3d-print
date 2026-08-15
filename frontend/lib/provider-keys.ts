export const PROVIDER_KEY_HEADERS = {
  anthropic: "x-pulsai-anthropic-key",
  openai: "x-pulsai-openai-key",
  gemini: "x-pulsai-gemini-key",
  meshy: "x-pulsai-meshy-key",
  tripo: "x-pulsai-tripo-key",
} as const;

export type ProviderKeyId = keyof typeof PROVIDER_KEY_HEADERS;
export type ProviderKeys = Record<ProviderKeyId, string>;
export type MeshProviderPreference = "auto" | "meshy" | "tripo";
export type GenerationQuality = "draft" | "balanced" | "quality";

export const EMPTY_PROVIDER_KEYS: ProviderKeys = {
  anthropic: "",
  openai: "",
  gemini: "",
  meshy: "",
  tripo: "",
};

export function providerKeyHeaders(
  keys: Partial<ProviderKeys>,
  providers?: ProviderKeyId[],
): Record<string, string> {
  const selected = providers ?? (Object.keys(PROVIDER_KEY_HEADERS) as ProviderKeyId[]);
  return selected.reduce<Record<string, string>>((headers, provider) => {
    const key = keys[provider]?.trim();
    if (key) headers[PROVIDER_KEY_HEADERS[provider]] = key;
    return headers;
  }, {});
}

export function looksLikeProviderKey(provider: ProviderKeyId, value: string): boolean {
  const key = value.trim();
  if (!key || key.length > 1024 || /\s/.test(key)) return false;
  if (provider === "anthropic") return key.startsWith("sk-ant-");
  if (provider === "openai") return key.startsWith("sk-");
  if (provider === "gemini") return key.startsWith("AIza");
  return key.length >= 16;
}

const TRIPO_FRIENDLY = /\b(figur(?:e|ine|ka|ki)|character|posta(?:c|ć)|human|person|pilot|paraglider|motoparalotni|creature|animal|dragon|sculpture|statue)\b/i;

export function selectMeshProvider(
  prompt: string,
  preference: MeshProviderPreference,
  keys: Pick<ProviderKeys, "meshy" | "tripo">,
): "meshy" | "tripo" | null {
  const meshy = looksLikeProviderKey("meshy", keys.meshy);
  const tripo = looksLikeProviderKey("tripo", keys.tripo);
  if (preference === "meshy") return meshy ? "meshy" : null;
  if (preference === "tripo") return tripo ? "tripo" : null;
  if (meshy && tripo) return TRIPO_FRIENDLY.test(prompt) ? "tripo" : "meshy";
  if (tripo) return "tripo";
  if (meshy) return "meshy";
  return null;
}
