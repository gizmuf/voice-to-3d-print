"use client";

import type { BodyNode } from "../types/editable-model";

export type EditableParamEntry = {
  key: string;
  value: string | number | boolean;
  type: "boolean" | "number" | "text";
};

export const formatParamLabel = (key: string) => key.replace(/^_/, "").replace(/_/g, " ");

export function getEditableParamEntries(body: BodyNode, limit?: number): EditableParamEntry[] {
  const entries = Object.entries(body.params)
    .filter(([key]) => !key.startsWith("_"))
    .map(([key, value]) => ({
      key,
      value,
      type: typeof value === "boolean" ? "boolean" : typeof value === "number" ? "number" : "text",
    } satisfies EditableParamEntry));

  return typeof limit === "number" ? entries.slice(0, limit) : entries;
}
