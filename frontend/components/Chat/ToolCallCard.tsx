"use client";

import type { ToolCall } from "../../types/chat";

const STATUS_LABELS: Record<ToolCall["status"], string> = {
  pending: "queued",
  running: "running…",
  done: "done",
  error: "error",
};

const STATUS_COLORS: Record<ToolCall["status"], string> = {
  pending: "rgba(255,255,255,0.4)",
  running: "rgba(33,150,243,0.85)",
  done: "rgba(76,175,80,0.85)",
  error: "rgba(244,67,54,0.85)",
};

export default function ToolCallCard({ call }: { call: ToolCall }) {
  const summary = summariseCall(call);
  const resultLine = summariseResult(call);

  return (
    <div className="tool-call-card" style={cardStyle(call.status)}>
      <div style={headerStyle}>
        <span style={dotStyle(call.status)} />
        <span style={{ fontWeight: 600 }}>{call.name}</span>
        <span style={{ flex: 1, opacity: 0.8, marginLeft: 6 }}>{summary}</span>
        <span style={{ opacity: 0.7, fontSize: 11 }}>{STATUS_LABELS[call.status]}</span>
      </div>
      {resultLine ? (
        <div style={resultLineStyle(call.status)}>{resultLine}</div>
      ) : null}
    </div>
  );
}

function summariseResult(call: ToolCall): string | null {
  if (call.status !== "done" && call.status !== "error") return null;
  const r = call.result as Record<string, unknown> | undefined;
  if (!r) return null;
  if (call.isError || r.error) {
    return "✕ Nie udało się bezpiecznie zastosować tej operacji. Projekt pozostał bez zmian.";
  }
  if (call.name === "update_parameter") {
    const name = call.input.name as string | undefined;
    const newV = (r as { new_value?: unknown }).new_value;
    return `✓ ${name} → ${formatValue(newV)}`;
  }
  if (call.name === "replace_feature") {
    const fname = call.input.feature_name as string | undefined;
    const fc = (r as { feature_count?: number }).feature_count;
    return `✓ replaced feature \`${fname}\` (${fc ?? "?"} feature blocks now)`;
  }
  if (call.name === "append_feature") {
    const fname = call.input.name as string | undefined;
    return `✓ added feature \`${fname}\``;
  }
  if (call.name === "rewrite_design") {
    const pc = (r as { parameter_count?: number }).parameter_count;
    const fc = (r as { feature_count?: number }).feature_count;
    return `✓ rewrote design (${pc ?? "?"} parameters, ${fc ?? "?"} feature blocks)`;
  }
  if (call.name === "run_build") {
    const bbox = (r as { bounding_box_mm?: number[] }).bounding_box_mm;
    const mesh = String((r as { mesh_hash?: string }).mesh_hash ?? "").slice(0, 10);
    const mfg = (r as { manufacturability?: { status?: string } }).manufacturability?.status;
    const bboxStr = bbox && bbox.length >= 3
      ? `${bbox[0].toFixed(1)}×${bbox[1].toFixed(1)}×${bbox[2].toFixed(1)} mm`
      : "?";
    return `✓ built · ${bboxStr} · mesh ${mesh}…${mfg ? ` · ${mfg}` : ""}`;
  }
  if (call.name === "check_manufacturability") {
    const status = (r as { report?: { status?: string; issues?: unknown[] } }).report?.status;
    const issues = (r as { report?: { issues?: unknown[] } }).report?.issues ?? [];
    return `✓ ${status ?? "?"} · ${issues.length} issue(s)`;
  }
  if (call.name === "query_library") {
    const n = (r as { match_count?: number }).match_count ?? 0;
    return `✓ ${n} snippet(s) returned`;
  }
  if (call.name === "read_design") {
    const n = (r as { parameters?: unknown[] }).parameters?.length ?? 0;
    const f = (r as { features?: unknown[] }).features?.length ?? 0;
    return `✓ ${n} parameters, ${f} features`;
  }
  return r.ok ? "✓ done" : null;
}

function formatValue(v: unknown): string {
  if (typeof v === "number") return String(v);
  if (typeof v === "boolean") return v ? "true" : "false";
  if (v === null || v === undefined) return "(none)";
  return JSON.stringify(v);
}

function summariseCall(call: ToolCall): string {
  if (call.name === "rewrite_design") return "przebudowa modelu CAD";
  if (call.name === "run_build") return "budowanie i kontrola artefaktów";
  if (call.name === "update_parameter") {
    const name = String(call.input.name ?? "parametr");
    const value = call.input.new_value;
    return `${name} → ${formatValue(value)}`;
  }
  if (call.name === "mutate_parameter") {
    const node = call.input.node_id;
    const param = call.input.param_name;
    const value = call.input.new_value;
    return `${node}.${param} → ${value}`;
  }
  if (call.name === "run_preview") return "rebuilding preview";
  if (call.name === "check_manufacturability") return "checking printability";
  if (call.name === "query_tree") {
    const kind = call.input.node_kind;
    const label = call.input.label_contains;
    if (kind) return `kind=${kind}`;
    if (label) return `label~"${label}"`;
    return "scanning tree";
  }
  if (call.name === "add_feature" || call.name === "remove_feature") {
    return "(refused in Phase 1)";
  }
  return "";
}

function cardStyle(status: ToolCall["status"]): React.CSSProperties {
  return {
    border: `1px solid ${STATUS_COLORS[status]}`,
    borderRadius: 8,
    background: "rgba(255,255,255,0.03)",
    overflow: "hidden",
    fontSize: 12,
  };
}

const headerStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  width: "100%",
  border: "none",
  background: "transparent",
  color: "inherit",
  padding: "6px 10px",
  cursor: "default",
  textAlign: "left",
};

function dotStyle(status: ToolCall["status"]): React.CSSProperties {
  return {
    width: 8,
    height: 8,
    borderRadius: 999,
    background: STATUS_COLORS[status],
    flex: "none",
  };
}

function resultLineStyle(status: ToolCall["status"]): React.CSSProperties {
  const isError = status === "error";
  return {
    padding: "4px 10px 6px",
    fontSize: 12,
    color: isError ? "rgba(244,67,54,0.95)" : "rgba(76,175,80,0.95)",
    fontFamily:
      "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace",
    borderTop: "1px solid rgba(255,255,255,0.05)",
    background: isError ? "rgba(244,67,54,0.05)" : "rgba(76,175,80,0.05)",
  };
}
