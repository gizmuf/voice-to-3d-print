"use client";

const localBackendUrl = "http://localhost:8000";
const productionBackendUrl =
  process.env.NEXT_PUBLIC_BACKEND_URL ||
  "https://pulsai-3d-backend-efopwinsfq-uc.a.run.app";

export const resolveBackendUrl = () => {
  if (process.env.NEXT_PUBLIC_BACKEND_URL) return process.env.NEXT_PUBLIC_BACKEND_URL;
  if (typeof window !== "undefined") {
    const host = window.location.hostname;
    if (host && host !== "localhost" && host !== "127.0.0.1") {
      return productionBackendUrl;
    }
  }
  return localBackendUrl;
};

export const resolveUrl = (base: string, value?: string | null) => {
  if (!value) return null;
  if (value.startsWith("http")) return value;
  return `${base.replace(/\/$/, "")}${value.startsWith("/") ? "" : "/"}${value}`;
};
