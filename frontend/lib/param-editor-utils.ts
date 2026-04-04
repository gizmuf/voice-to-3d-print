"use client";

import type { BodyNode } from "../types/editable-model";

export type EditableParamEntry = {
  key: string;
  value: string | number | boolean;
  type: "boolean" | "number" | "text";
};

const MM_PARAM_EXACT = new Set([
  "outer_diameter",
  "thickness",
  "diameter",
  "width",
  "height",
  "depth",
]);

const INTEGER_PARAM_PATTERN = /(count|holes_per_ring|quantity|index)$/;

export const isMillimeterParam = (key: string) =>
  key.endsWith("_mm") || MM_PARAM_EXACT.has(key) || key.endsWith("_diameter");

export const isIntegerParam = (key: string) => INTEGER_PARAM_PATTERN.test(key);

export const formatParamLabel = (key: string) => {
  const normalized = key.replace(/^_/, "").replace(/_mm$/, "").replace(/_/g, " ");
  return isMillimeterParam(key) ? `${normalized} mm` : normalized;
};

export const getParamInputStep = (key: string, value: EditableParamEntry["value"]) => {
  if (typeof value !== "number") return undefined;
  if (isIntegerParam(key)) return "1";
  if (isMillimeterParam(key)) return "0.01";
  return "0.1";
};

export const formatParamDisplayValue = (key: string, value: EditableParamEntry["value"]) => {
  if (typeof value === "boolean") {
    return value ? "True" : "False";
  }
  if (typeof value === "number") {
    const formatted = isIntegerParam(key)
      ? String(Math.round(value))
      : value.toFixed(isMillimeterParam(key) ? 2 : 3).replace(/\.?0+$/, "");
    return isMillimeterParam(key) ? `${formatted} mm` : formatted;
  }
  return String(value);
};

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
