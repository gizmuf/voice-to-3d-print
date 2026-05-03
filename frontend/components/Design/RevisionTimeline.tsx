"use client";

import { useEffect, useState } from "react";

import { resolveBackendUrl, resolveUrl } from "../../lib/backend";

type RevisionSummary = {
  revision_id: string;
  mesh_hash: string | null;
  bounding_box_mm: [number, number, number] | null;
  manufacturability_status: "safe" | "warn" | "unprintable" | null;
  duration_ms: number | null;
  glb_url: string | null;
  stat_mtime: number;
};

type RevisionDiff = {
  parameter_changes?: Array<{ name: string; before: unknown; after: unknown }>;
  features_added?: Array<{ id: string; name: string; kind: string }>;
  features_removed?: Array<{ id: string; name: string; kind: string }>;
  locked_added?: string[];
  locked_removed?: string[];
  duration_ms?: number | null;
};

export default function RevisionTimeline({
  designId,
  currentRevisionId,
  onRestore,
  refreshKey,
}: {
  designId: string | null;
  currentRevisionId: string | null;
  onRestore: () => void;
  refreshKey?: string | number;
}) {
  const backendUrl = resolveBackendUrl();
  const [revisions, setRevisions] = useState<RevisionSummary[]>([]);
  const [restoring, setRestoring] = useState<string | null>(null);
  const [hovering, setHovering] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [diffs, setDiffs] = useState<Record<string, RevisionDiff | "loading" | "error">>({});

  useEffect(() => {
    if (!designId) {
      setRevisions([]);
      setDiffs({});
      return;
    }
    let cancelled = false;
    fetch(`${backendUrl}/design/${designId}/revisions`)
      .then((r) => (r.ok ? r.json() : null))
      .then((payload) => {
        if (cancelled || !payload) return;
        const nextRevisions = payload.revisions ?? [];
        setRevisions(nextRevisions);
        const validIds = new Set(nextRevisions.map((r: RevisionSummary) => r.revision_id));
        setDiffs((prev) =>
          Object.fromEntries(Object.entries(prev).filter(([revisionId]) => validIds.has(revisionId))),
        );
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [backendUrl, designId, refreshKey]);

  useEffect(() => {
    if (!designId || !hovering || diffs[hovering]) return;
    setDiffs((prev) => ({ ...prev, [hovering]: "loading" }));
    fetch(`${backendUrl}/design/${designId}/revisions/${hovering}/diff`)
      .then((r) => (r.ok ? r.json() : null))
      .then((payload) => {
        setDiffs((prev) => ({ ...prev, [hovering]: payload ?? "error" }));
      })
      .catch(() => {
        setDiffs((prev) => ({ ...prev, [hovering]: "error" }));
      });
  }, [backendUrl, designId, diffs, hovering]);

  if (!designId || revisions.length <= 1) return null;

  const restore = async (revisionId: string) => {
    if (!designId || restoring) return;
    setRestoring(revisionId);
    try {
      const res = await fetch(`${backendUrl}/design/${designId}/revisions/restore`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ revision_id: revisionId }),
      });
      if (res.ok) onRestore();
    } finally {
      setRestoring(null);
    }
  };

  const remove = async (revisionId: string) => {
    if (!designId || deleting) return;
    if (!window.confirm(`Delete revision ${revisionId.slice(0, 8)}? This can't be undone.`)) {
      return;
    }
    setDeleting(revisionId);
    try {
      const res = await fetch(`${backendUrl}/design/${designId}/revisions/${revisionId}`, {
        method: "DELETE",
      });
      if (res.ok) {
        // Optimistic local update; the parent's onRestore re-fetches the design
        // anyway, but we also drop it from the visible strip immediately.
        setRevisions((prev) => prev.filter((r) => r.revision_id !== revisionId));
        setDiffs((prev) => {
          const next = { ...prev };
          delete next[revisionId];
          return next;
        });
        onRestore();
      } else {
        const payload = await res.json().catch(() => null);
        const message = payload?.detail ?? `Delete failed: ${res.status}`;
        alert(typeof message === "string" ? message : JSON.stringify(message));
      }
    } finally {
      setDeleting(null);
    }
  };

  return (
    <div style={shellStyle}>
      <span style={labelStyle}>HISTORY</span>
      <div style={stripStyle}>
        {revisions.map((r) => {
          const isCurrent = r.revision_id === currentRevisionId;
          const isRestoring = restoring === r.revision_id;
          const ago = formatAgo(r.stat_mtime);
          const tooltip =
            `revision ${r.revision_id.slice(0, 8)}\n` +
            `${ago}\n` +
            (r.bounding_box_mm
              ? `${r.bounding_box_mm.map((v) => v.toFixed(1)).join(" × ")} mm\n`
              : "") +
            `mesh ${(r.mesh_hash ?? "").slice(0, 10)}` +
            (r.manufacturability_status ? ` · ${r.manufacturability_status}` : "");
          const url = r.glb_url ? resolveUrl(backendUrl, r.glb_url) : null;
          const baseStyle = { ...thumbStyle };
          if (isCurrent) {
            baseStyle.border = "2px solid rgba(33,150,243,0.85)";
            baseStyle.opacity = 1;
          }
          const isHovering = hovering === r.revision_id;
          const isDeleting = deleting === r.revision_id;
          return (
            <div
              key={r.revision_id}
              style={{ position: "relative" }}
              onMouseEnter={() => setHovering(r.revision_id)}
              onMouseLeave={() => setHovering((h) => (h === r.revision_id ? null : h))}
            >
              <button
                type="button"
                onClick={() => !isCurrent && restore(r.revision_id)}
                disabled={isCurrent || isRestoring || isDeleting}
                title={tooltip}
                style={baseStyle}
                aria-label={`Revision ${r.revision_id.slice(0, 8)}, ${ago}`}
              >
                <div style={glbHolderStyle}>
                  {url ? (
                    <span
                      style={{
                        ...statusSwatchStyle(r.manufacturability_status),
                      }}
                      aria-hidden
                    />
                  ) : (
                    <span style={statusSwatchStyle(null)} aria-hidden />
                  )}
                </div>
                <span style={revLabelStyle}>{r.revision_id.slice(0, 6)}</span>
                <span style={agoStyle}>{ago}</span>
                {isRestoring ? <span style={restoringStyle}>…</span> : null}
                {isDeleting ? <span style={restoringStyle}>×</span> : null}
              </button>
              {!isCurrent && isHovering && !isDeleting ? (
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    remove(r.revision_id);
                  }}
                  title="Delete this revision"
                  aria-label="Delete revision"
                  style={deleteButtonStyle}
                >
                  ×
                </button>
              ) : null}
              {isHovering ? (
                <RevisionDiffPopover
                  diff={diffs[r.revision_id]}
                  fallback={tooltip}
                />
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function RevisionDiffPopover({
  diff,
  fallback,
}: {
  diff: RevisionDiff | "loading" | "error" | undefined;
  fallback: string;
}) {
  if (!diff || diff === "loading") {
    return <div style={diffPopoverStyle}>Loading diff…</div>;
  }
  if (diff === "error") {
    return <div style={diffPopoverStyle}>{fallback}</div>;
  }
  const params = diff.parameter_changes ?? [];
  const added = diff.features_added ?? [];
  const removed = diff.features_removed ?? [];
  const lockedAdded = diff.locked_added ?? [];
  const lockedRemoved = diff.locked_removed ?? [];
  const empty =
    params.length === 0 &&
    added.length === 0 &&
    removed.length === 0 &&
    lockedAdded.length === 0 &&
    lockedRemoved.length === 0;
  return (
    <div style={diffPopoverStyle}>
      {empty ? <div>No structured changes detected.</div> : null}
      {params.slice(0, 4).map((p) => (
        <div key={p.name}>
          <strong>{p.name}</strong>: {String(p.before)} → {String(p.after)}
        </div>
      ))}
      {added.slice(0, 3).map((f) => (
        <div key={`add-${f.id}`}>+ {f.name}</div>
      ))}
      {removed.slice(0, 3).map((f) => (
        <div key={`remove-${f.id}`}>- {f.name}</div>
      ))}
      {lockedAdded.slice(0, 3).map((name) => (
        <div key={`lock-${name}`}>🔒 locked {name}</div>
      ))}
      {lockedRemoved.slice(0, 3).map((name) => (
        <div key={`unlock-${name}`}>🔓 unlocked {name}</div>
      ))}
      {diff.duration_ms ? (
        <div style={{ opacity: 0.65, marginTop: 4 }}>rebuild {Math.round(diff.duration_ms)} ms</div>
      ) : null}
    </div>
  );
}

function formatAgo(mtime: number): string {
  const dt = Date.now() / 1000 - mtime;
  if (dt < 60) return `${Math.floor(dt)}s ago`;
  if (dt < 3600) return `${Math.floor(dt / 60)}m ago`;
  if (dt < 86400) return `${Math.floor(dt / 3600)}h ago`;
  return `${Math.floor(dt / 86400)}d ago`;
}

function statusSwatchStyle(status: string | null): React.CSSProperties {
  const palette: Record<string, string> = {
    safe: "rgba(76,175,80,0.85)",
    warn: "rgba(255,193,7,0.85)",
    unprintable: "rgba(244,67,54,0.85)",
  };
  return {
    width: 32,
    height: 32,
    borderRadius: 6,
    background: palette[status ?? ""] ?? "rgba(0,0,0,0.2)",
    display: "block",
  };
}

const shellStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 10,
  padding: "8px 12px",
  background: "rgba(255,255,255,0.85)",
  border: "1px solid rgba(0,0,0,0.08)",
  borderRadius: 12,
  marginBottom: 10,
  overflowX: "auto",
};

const labelStyle: React.CSSProperties = {
  fontSize: 11,
  letterSpacing: 1,
  textTransform: "uppercase",
  opacity: 0.65,
  flex: "none",
};

const stripStyle: React.CSSProperties = {
  display: "flex",
  gap: 6,
  flexWrap: "nowrap",
};

const thumbStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  gap: 2,
  padding: 4,
  background: "rgba(0,0,0,0.04)",
  border: "1px solid rgba(0,0,0,0.10)",
  borderRadius: 6,
  cursor: "pointer",
  font: "inherit",
  minWidth: 48,
  flex: "none",
  opacity: 0.85,
};

const glbHolderStyle: React.CSSProperties = {
  width: 32,
  height: 32,
};

const revLabelStyle: React.CSSProperties = {
  fontSize: 10,
  fontFamily:
    "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace",
  opacity: 0.8,
};

const agoStyle: React.CSSProperties = {
  fontSize: 9,
  opacity: 0.55,
};

const restoringStyle: React.CSSProperties = {
  position: "absolute",
  fontSize: 14,
  color: "rgba(33,150,243,0.95)",
};

const deleteButtonStyle: React.CSSProperties = {
  position: "absolute",
  top: -6,
  right: -6,
  width: 18,
  height: 18,
  borderRadius: 999,
  border: "1px solid rgba(244,67,54,0.7)",
  background: "rgba(255,255,255,0.95)",
  color: "rgba(244,67,54,0.95)",
  cursor: "pointer",
  fontSize: 14,
  fontWeight: 700,
  lineHeight: 1,
  padding: 0,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  boxShadow: "0 1px 3px rgba(0,0,0,0.18)",
};

const diffPopoverStyle: React.CSSProperties = {
  position: "absolute",
  left: 0,
  top: "calc(100% + 6px)",
  zIndex: 20,
  width: 240,
  padding: "8px 10px",
  background: "rgba(255,255,255,0.98)",
  border: "1px solid rgba(0,0,0,0.14)",
  borderRadius: 8,
  boxShadow: "0 10px 24px rgba(0,0,0,0.16)",
  fontSize: 11,
  lineHeight: 1.45,
  pointerEvents: "none",
  whiteSpace: "normal",
};
