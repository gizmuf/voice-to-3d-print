const EMBEDDED_BROWSER_MARKERS = [
  "codex",
  "openai",
  "chatgpt",
  "electron",
  "; wv",
  " webview",
  "fban",
  "fbav",
  "instagram",
  "line/",
];

export function isLikelyEmbeddedBrowser(userAgent: string): boolean {
  const normalized = userAgent.toLowerCase();
  return EMBEDDED_BROWSER_MARKERS.some((marker) => normalized.includes(marker));
}
