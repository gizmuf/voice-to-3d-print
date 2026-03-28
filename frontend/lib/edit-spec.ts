"use client";

export const EDIT_OPERATION_VALUES = [
  "replace_cutout_shape",
  "resize_cutout",
  "replace_hole_with_slot",
  "replace_hole_with_rectangle",
  "replace_slot_with_rectangle",
  "replace_rectangle_with_circle",
  "array_selected_cutout",
] as const;

export const EDIT_TARGET_SHAPE_VALUES = ["rectangle", "rounded_slot", "circle"] as const;
export const EDIT_PATTERN_VALUES = ["none", "linear", "circular"] as const;

export type EditOperation = (typeof EDIT_OPERATION_VALUES)[number];
export type EditTargetShape = (typeof EDIT_TARGET_SHAPE_VALUES)[number];
export type EditPattern = (typeof EDIT_PATTERN_VALUES)[number];

export type ParsedEditFields = {
  operation?: EditOperation;
  target_shape?: EditTargetShape;
  width_mm?: number;
  height_mm?: number;
  diameter_mm?: number;
  depth_mm?: number;
  corner_radius_mm?: number;
  through_all?: boolean;
  pattern?: EditPattern;
  count?: number;
  spacing_mm?: number;
  array_radius_mm?: number;
  tolerance_mm?: number;
  center_x_mm?: number;
  center_y_mm?: number;
};

export type ParseEditSpecResult = {
  applied: ParsedEditFields;
  appliedSummary: string[];
  warnings: string[];
  leftoverPrompt: string;
};

const NUMERIC_KEYS = new Set<keyof ParsedEditFields>([
  "width_mm",
  "height_mm",
  "diameter_mm",
  "depth_mm",
  "corner_radius_mm",
  "count",
  "spacing_mm",
  "array_radius_mm",
  "tolerance_mm",
  "center_x_mm",
  "center_y_mm",
]);

const BOOLEAN_KEYS = new Set<keyof ParsedEditFields>(["through_all"]);

const ENUM_VALUES: Partial<Record<keyof ParsedEditFields, readonly string[]>> = {
  operation: EDIT_OPERATION_VALUES,
  target_shape: EDIT_TARGET_SHAPE_VALUES,
  pattern: EDIT_PATTERN_VALUES,
};

const KNOWN_KEYS = new Set<keyof ParsedEditFields>([
  "operation",
  "target_shape",
  "width_mm",
  "height_mm",
  "diameter_mm",
  "depth_mm",
  "corner_radius_mm",
  "through_all",
  "pattern",
  "count",
  "spacing_mm",
  "array_radius_mm",
  "tolerance_mm",
  "center_x_mm",
  "center_y_mm",
]);

const toBoolean = (value: string) => {
  if (value === "true") return true;
  if (value === "false") return false;
  return null;
};

const parseFlatLines = (source: string) => {
  const entries: Array<{ key: string; value: string }> = [];
  const leftoverLines: string[] = [];

  for (const rawLine of source.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) continue;
    const separatorIndex = line.indexOf(":");
    if (separatorIndex <= 0) {
      leftoverLines.push(line);
      continue;
    }
    const key = line.slice(0, separatorIndex).trim();
    const value = line.slice(separatorIndex + 1).trim();
    entries.push({ key, value });
  }

  return { entries, leftoverPrompt: leftoverLines.join("\n") };
};

const parseInput = (raw: string) => {
  const trimmed = raw.trim();
  if (!trimmed) return { entries: [] as Array<{ key: string; value: unknown }>, leftoverPrompt: "" };

  if (trimmed.startsWith("{")) {
    try {
      const parsed = JSON.parse(trimmed) as Record<string, unknown>;
      return {
        entries: Object.entries(parsed).map(([key, value]) => ({ key, value })),
        leftoverPrompt: "",
      };
    } catch {
      return {
        entries: [],
        leftoverPrompt: trimmed,
      };
    }
  }

  const flat = parseFlatLines(trimmed);
  return {
    entries: flat.entries.map(({ key, value }) => ({ key, value })),
    leftoverPrompt: flat.leftoverPrompt,
  };
};

export const parseEditSpec = (raw: string): ParseEditSpecResult => {
  const { entries, leftoverPrompt } = parseInput(raw);
  const applied: ParsedEditFields = {};
  const appliedSummary: string[] = [];
  const warnings: string[] = [];
  const promptFragments = leftoverPrompt ? [leftoverPrompt] : [];

  for (const entry of entries) {
    const key = entry.key.trim() as keyof ParsedEditFields;
    if (!KNOWN_KEYS.has(key)) {
      warnings.push(`Ignored unknown key "${entry.key}".`);
      promptFragments.push(`${entry.key}: ${String(entry.value).trim()}`);
      continue;
    }

    if (BOOLEAN_KEYS.has(key)) {
      const parsed = toBoolean(String(entry.value).trim().toLowerCase());
      if (parsed === null) {
        warnings.push(`Expected true/false for "${entry.key}".`);
        continue;
      }
      (applied as Record<string, unknown>)[key] = parsed;
      appliedSummary.push(`${key.replace(/_/g, " ")} ${parsed}`);
      continue;
    }

    if (NUMERIC_KEYS.has(key)) {
      const parsed = Number(String(entry.value).trim());
      if (!Number.isFinite(parsed)) {
        warnings.push(`Expected a number for "${entry.key}".`);
        continue;
      }
      (applied as Record<string, unknown>)[key] = parsed;
      appliedSummary.push(`${key.replace(/_/g, " ")} ${parsed}`);
      continue;
    }

    const normalized = String(entry.value).trim();
    const allowed = ENUM_VALUES[key];
    if (allowed && !allowed.includes(normalized)) {
      warnings.push(`Invalid value "${normalized}" for "${entry.key}".`);
      continue;
    }
    (applied as Record<string, unknown>)[key] = normalized;
    appliedSummary.push(`${key.replace(/_/g, " ")} ${normalized}`);
  }

  return {
    applied,
    appliedSummary,
    warnings,
    leftoverPrompt: promptFragments.filter(Boolean).join("\n"),
  };
};
