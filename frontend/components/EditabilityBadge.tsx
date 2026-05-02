"use client";

import { useEffect, useState } from "react";

import { resolveBackendUrl } from "../lib/backend";
import type { EditabilityAssessment, EditabilityLevel } from "../types/chat";

const LEVEL_LABELS: Record<EditabilityLevel, string> = {
  editable: "Editable",
  partially_editable: "Partially editable",
  reference_only: "Reference only",
  locked_unsafe: "Locked",
};

const LEVEL_BACKGROUND: Record<EditabilityLevel, string> = {
  editable: "rgba(76,175,80,0.18)",
  partially_editable: "rgba(255,193,7,0.20)",
  reference_only: "rgba(96,125,139,0.24)",
  locked_unsafe: "rgba(244,67,54,0.22)",
};

const LEVEL_BORDER: Record<EditabilityLevel, string> = {
  editable: "rgba(76,175,80,0.55)",
  partially_editable: "rgba(255,193,7,0.65)",
  reference_only: "rgba(96,125,139,0.55)",
  locked_unsafe: "rgba(244,67,54,0.65)",
};

export type EditabilityBadgeProps = {
  workspaceId: string | null;
  revisionId?: string | null;
};

export default function EditabilityBadge({
  workspaceId,
  revisionId,
}: EditabilityBadgeProps) {
  const [assessment, setAssessment] = useState<EditabilityAssessment | null>(null);
  const [loading, setLoading] = useState(false);
  const backendUrl = resolveBackendUrl();

  useEffect(() => {
    if (!workspaceId) {
      setAssessment(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    fetch(`${backendUrl}/workspace/${workspaceId}/editability`)
      .then((res) => (res.ok ? res.json() : null))
      .then((payload) => {
        if (cancelled || !payload) return;
        setAssessment(payload.assessment as EditabilityAssessment);
      })
      .catch(() => {
        // Silent — badge just won't render.
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [backendUrl, workspaceId, revisionId]);

  if (!workspaceId || (!assessment && !loading)) return null;

  if (loading && !assessment) {
    return (
      <span
        className="editability-badge editability-badge-loading"
        style={badgeStyle("reference_only")}
      >
        …
      </span>
    );
  }

  if (!assessment) return null;

  const tooltip = assessment.reasons.length
    ? assessment.reasons.join(" · ")
    : "Backend-authoritative editability contract.";

  return (
    <span
      className={`editability-badge editability-${assessment.level}`}
      style={badgeStyle(assessment.level)}
      title={tooltip}
      aria-label={`Editability: ${LEVEL_LABELS[assessment.level]}`}
    >
      <span aria-hidden style={dotStyle(assessment.level)} />
      {LEVEL_LABELS[assessment.level]}
      {assessment.repair_required ? " · repair required" : null}
    </span>
  );
}

function badgeStyle(level: EditabilityLevel): React.CSSProperties {
  return {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    padding: "2px 10px",
    borderRadius: 999,
    background: LEVEL_BACKGROUND[level],
    border: `1px solid ${LEVEL_BORDER[level]}`,
    color: "var(--foreground, #f7f7f7)",
    fontSize: 12,
    fontWeight: 500,
    lineHeight: 1.6,
    whiteSpace: "nowrap",
  };
}

function dotStyle(level: EditabilityLevel): React.CSSProperties {
  return {
    width: 6,
    height: 6,
    borderRadius: 999,
    background: LEVEL_BORDER[level],
    flex: "none",
  };
}
