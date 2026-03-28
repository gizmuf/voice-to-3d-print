"use client";

type JsonLike =
  | null
  | boolean
  | number
  | string
  | JsonLike[]
  | { [key: string]: JsonLike };

const normalizeValue = (value: unknown): JsonLike => {
  if (value === null) return null;
  if (typeof value === "boolean" || typeof value === "number" || typeof value === "string") {
    return value;
  }
  if (Array.isArray(value)) {
    return value.map((item) => normalizeValue(item));
  }
  if (typeof value === "object") {
    return Object.keys(value as Record<string, unknown>)
      .sort()
      .reduce<{ [key: string]: JsonLike }>((acc, key) => {
        acc[key] = normalizeValue((value as Record<string, unknown>)[key]);
        return acc;
      }, {});
  }
  return String(value);
};

export const stableStringify = (value: unknown) => JSON.stringify(normalizeValue(value));
