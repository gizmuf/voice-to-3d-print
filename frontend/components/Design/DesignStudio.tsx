"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import ChatMessage from "../Chat/ChatMessage";
import ModelViewer from "../ModelViewer";
import SelectionChip from "../SelectionChip";
import RevisionTimeline from "./RevisionTimeline";
import { resolveBackendUrl, resolveUrl } from "../../lib/backend";
import { useDesignStream } from "../../lib/useDesignStream";
import type { Design, DesignTemplate, ManufacturabilityIssue } from "../../types/design";
import type { SelectionPayload } from "../ModelViewer";

const TEMPLATE_PROMPTS: { label: string; prompt: string }[] = [
  { label: "Speaker grill 200mm", prompt: "speaker grill 200mm with 8 rings" },
  { label: "Phone stand", prompt: "phone stand 65 degrees, cable hole" },
  { label: "Pen holder", prompt: "cylindrical pen holder 60mm wide" },
  { label: "Box 80x60x30", prompt: "simple box 80x60x30, wall 3mm" },
];

export default function DesignStudio() {
  const backendUrl = resolveBackendUrl();
  const [templates, setTemplates] = useState<DesignTemplate[]>([]);
  const [design, setDesign] = useState<Design | null>(null);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [prompt, setPrompt] = useState("");
  const [process, setProcess] = useState<"fdm" | "cnc" | "either">("fdm");
  const reloadAfterRef = useRef<string | null>(null);
  // After /design/create returns, we may want Claude to actually *shape* the
  // model from the user's prompt — not just seed a template. We can't call
  // useDesignStream.send until the hook sees the new design id, so we queue
  // the prompt here and let an effect fire it on the next render.
  const [pendingFirstPrompt, setPendingFirstPrompt] = useState<string | null>(null);
  const firstPromptFiredForRef = useRef<string | null>(null);
  const [updatingParam, setUpdatingParam] = useState<string | null>(null);
  const [livePreview, setLivePreview] = useState<boolean>(false);
  const [selectedFeatureId, setSelectedFeatureId] = useState<string | null>(null);
  const [selectedFeaturePoint, setSelectedFeaturePoint] = useState<{ x: number; y: number; z: number } | null>(null);
  const [selectedManufacturabilityIssueIndex, setSelectedManufacturabilityIssueIndex] = useState<number | null>(null);
  const [makePrintable, setMakePrintable] = useState<{
    busy: boolean;
    summary?: string;
    bundleUrl?: string;
    status?: "safe" | "warn" | "unprintable";
    remainingIssues?: ManufacturabilityIssue[];
    slicerReady?: boolean;
    error?: string;
  }>({ busy: false });
  const liveDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [flagships, setFlagships] = useState<{ id: string; name: string; description: string }[]>([]);
  const [recentDesigns, setRecentDesigns] = useState<
    {
      design_id: string;
      revision_id: string;
      name: string;
      process: string;
      parameter_count: number;
      feature_count: number;
    }[]
  >([]);

  useEffect(() => {
    fetch(`${backendUrl}/design/flagship`)
      .then((r) => (r.ok ? r.json() : null))
      .then((p) => {
        if (p?.flagships) setFlagships(p.flagships);
      })
      .catch(() => undefined);
  }, [backendUrl]);

  // Pull the user's recent designs whenever the studio is on the empty state.
  // Designs are persisted to disk; this just surfaces them for one-click reopen.
  useEffect(() => {
    if (design) return;
    let cancelled = false;
    fetch(`${backendUrl}/design`)
      .then((r) => (r.ok ? r.json() : null))
      .then((p) => {
        if (cancelled || !p) return;
        setRecentDesigns(p.designs ?? []);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [backendUrl, design]);

  const openDesign = useCallback(
    async (designId: string) => {
      setCreating(true);
      setCreateError(null);
      try {
        const res = await fetch(`${backendUrl}/design/${designId}`);
        if (!res.ok) throw new Error(`Open failed: ${res.status}`);
        const payload = await res.json();
        setDesign({
          design_id: payload.design_id,
          revision_id: payload.revision_id,
          name: payload.name,
          process: payload.process ?? "either",
          script: payload.script,
          parameters: payload.parameters ?? [],
          features: payload.features ?? [],
          latest_build: payload.latest_build ?? null,
        });
        if (typeof window !== "undefined") {
          const url = new URL(window.location.href);
          url.searchParams.set("design", designId);
          window.history.replaceState({}, "", url.toString());
        }
      } catch (error) {
        setCreateError(
          error instanceof Error ? error.message : "Could not open design.",
        );
      } finally {
        setCreating(false);
      }
    },
    [backendUrl],
  );

  const deleteDesign = useCallback(
    async (designId: string) => {
      if (!window.confirm(`Delete this design and its history? This can't be undone.`)) return;
      try {
        const res = await fetch(`${backendUrl}/design/${designId}`, {
          method: "DELETE",
        });
        if (res.ok) {
          setRecentDesigns((prev) => prev.filter((d) => d.design_id !== designId));
        }
      } catch {
        // ignore
      }
    },
    [backendUrl],
  );

  const returnToStart = useCallback(() => {
    setDesign(null);
    setCreateError(null);
    setPendingFirstPrompt(null);
    firstPromptFiredForRef.current = null;
    reloadAfterRef.current = null;
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      url.searchParams.delete("design");
      window.history.replaceState({}, "", url.toString());
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  }, []);

  const onForkFlagship = useCallback(
    async (flagshipId: string) => {
      setCreating(true);
      setCreateError(null);
      try {
        const res = await fetch(`${backendUrl}/design/flagship/fork`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ flagship_id: flagshipId }),
        });
        if (!res.ok) throw new Error(`Fork failed: ${res.status}`);
        const payload = (await res.json()) as Design;
        setDesign({
          design_id: payload.design_id,
          revision_id: payload.revision_id,
          name: payload.name,
          process: payload.process ?? process,
          script: payload.script,
          parameters: payload.parameters ?? [],
          features: payload.features ?? [],
          latest_build: (payload as any).initial_build ?? null,
        });
      } catch (error) {
        setCreateError(
          error instanceof Error ? error.message : "Failed to fork flagship.",
        );
      } finally {
        setCreating(false);
      }
    },
    [backendUrl, process],
  );

  useEffect(() => {
    fetch(`${backendUrl}/design/templates`)
      .then((res) => (res.ok ? res.json() : null))
      .then((payload) => {
        if (payload?.templates) setTemplates(payload.templates);
      })
      .catch(() => undefined);
  }, [backendUrl]);

  // Deep-link: ?design=<id> auto-loads an existing design (and its chat
  // history). Lets users bookmark / share work in progress.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const id = new URLSearchParams(window.location.search).get("design");
    if (!id) return;
    setCreating(true);
    fetch(`${backendUrl}/design/${id}`)
      .then((res) => (res.ok ? res.json() : null))
      .then((payload) => {
        if (!payload) return;
        setDesign({
          design_id: payload.design_id,
          revision_id: payload.revision_id,
          name: payload.name,
          process: payload.process ?? "either",
          script: payload.script,
          parameters: payload.parameters ?? [],
          features: payload.features ?? [],
          latest_build: payload.latest_build ?? null,
        });
      })
      .catch(() => undefined)
      .finally(() => setCreating(false));
    // Run once on mount; subsequent changes go through onCreate / onImportSTL.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const refreshDesign = useCallback(
    async (designId: string) => {
      try {
        const res = await fetch(`${backendUrl}/design/${designId}`);
        if (!res.ok) return;
        const payload = (await res.json()) as Design & {
          editable_model?: unknown;
        };
        setDesign(payload);
      } catch {
        // silent
      }
    },
    [backendUrl],
  );

  const stream = useDesignStream(design?.design_id ?? null);
  const lastRevision = stream.latestRevisionId;

  useEffect(() => {
    if (!design || !lastRevision) return;
    if (reloadAfterRef.current === lastRevision) return;
    if (lastRevision !== design.revision_id) {
      reloadAfterRef.current = lastRevision;
      refreshDesign(design.design_id);
    }
  }, [design, lastRevision, refreshDesign]);

  const selectedFeature = useMemo(() => {
    if (!design || !selectedFeatureId) return null;
    return design.features.find((f) => f.id === selectedFeatureId) ?? null;
  }, [design, selectedFeatureId]);

  useEffect(() => {
    if (!design || !selectedFeatureId) return;
    if (!design.features.some((f) => f.id === selectedFeatureId)) {
      setSelectedFeatureId(null);
      setSelectedFeaturePoint(null);
    }
  }, [design, selectedFeatureId]);

  const selectFeature = useCallback(
    (featureId: string, point?: { x: number; y: number; z: number } | null) => {
      if (!design) return;
      setSelectedFeatureId(featureId);
      setSelectedFeaturePoint(point ?? featureAnchorForDesign(design, featureId));
      setSelectedManufacturabilityIssueIndex(null);
    },
    [design]
  );

  // Auto-fire the user's free-form prompt as the first chat turn, so Claude
  // actually shapes the seeded design to match the request (not just routes
  // to a template). Fires once per design id.
  useEffect(() => {
    if (!design || !pendingFirstPrompt) return;
    if (firstPromptFiredForRef.current === design.design_id) return;
    firstPromptFiredForRef.current = design.design_id;
    const queued = pendingFirstPrompt;
    setPendingFirstPrompt(null);
    stream.send(queued);
  }, [design, pendingFirstPrompt, stream]);

  const onCreate = useCallback(
    async (creationPrompt: string, templateId?: string | null) => {
      setCreating(true);
      setCreateError(null);
      try {
        const body: Record<string, unknown> = { process };
        if (templateId) body.template_id = templateId;
        else body.prompt = creationPrompt;
        const res = await fetch(`${backendUrl}/design/create`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!res.ok) {
          let detail = `Create failed: ${res.status}`;
          try {
            const payload = await res.json();
            const d = payload?.detail;
            detail =
              typeof d === "string"
                ? d
                : (d?.message ?? JSON.stringify(d) ?? detail);
          } catch {
            // keep
          }
          throw new Error(detail);
        }
        const payload = (await res.json()) as Design & {
          design_id: string;
        };
        setDesign({
          design_id: payload.design_id,
          revision_id: payload.revision_id,
          name: payload.name,
          process: payload.process ?? process,
          script: payload.script,
          parameters: payload.parameters ?? [],
          features: payload.features ?? [],
          latest_build: (payload as any).initial_build ?? null,
        });
        // If the user typed a free-form prompt (not a one-click template),
        // queue it as the first chat turn so Claude actually applies the
        // user's intent to the seed (e.g. "make the holes hexagonal").
        if (!templateId && creationPrompt && creationPrompt.trim()) {
          setPendingFirstPrompt(creationPrompt.trim());
        }
      } catch (error) {
        setCreateError(
          error instanceof Error ? error.message : "Failed to create design.",
        );
      } finally {
        setCreating(false);
      }
    },
    [backendUrl, process],
  );

  const onImportSTL = useCallback(
    async (file: File) => {
      setCreating(true);
      setCreateError(null);
      try {
        const fd = new FormData();
        fd.append("model", file);
        fd.append("process", process);
        if (file.name) fd.append("name", file.name);
        const res = await fetch(`${backendUrl}/design/import-stl`, {
          method: "POST",
          body: fd,
        });
        if (!res.ok) {
          let detail = `Import failed: ${res.status}`;
          try {
            const payload = await res.json();
            const d = payload?.detail;
            detail =
              typeof d === "string"
                ? d
                : (d?.message ?? JSON.stringify(d) ?? detail);
          } catch {
            // keep
          }
          throw new Error(detail);
        }
        const payload = await res.json();
        setDesign({
          design_id: payload.design_id,
          revision_id: payload.revision_id,
          name: payload.name,
          process,
          script: payload.script,
          parameters: payload.parameters ?? [],
          features: payload.features ?? [],
          latest_build: payload.initial_build ?? null,
        });
      } catch (error) {
        setCreateError(
          error instanceof Error ? error.message : "Failed to import STL.",
        );
      } finally {
        setCreating(false);
      }
    },
    [backendUrl, process],
  );

  const buildArtifactUrl = useMemo(() => {
    const glb = design?.latest_build?.artifacts?.glb as
      | { url?: string }
      | string
      | undefined;
    const raw = typeof glb === "string" ? glb : glb?.url;
    if (!raw) return null;
    const resolved = resolveUrl(backendUrl, raw);
    if (!resolved) return null;
    // Cache-bust by mesh hash. The backend overwrites the GLB at the same
    // URL on every rebuild, so without this the browser keeps showing the
    // cached old geometry even though the build was successful.
    const v = design?.latest_build?.mesh_hash || design?.revision_id;
    if (!v) return resolved;
    return resolved.includes("?") ? `${resolved}&v=${v}` : `${resolved}?v=${v}`;
  }, [
    backendUrl,
    design?.latest_build?.artifacts?.glb,
    design?.latest_build?.mesh_hash,
    design?.revision_id,
  ]);

  const issues = design?.latest_build?.manufacturability?.issues ?? [];
  const status = design?.latest_build?.manufacturability?.status;
  const selectedManufacturabilityIssue =
    selectedManufacturabilityIssueIndex === null ? null : issues[selectedManufacturabilityIssueIndex] ?? null;
  const selectedManufacturabilityPoint = selectedManufacturabilityIssue?.location
    ? {
        x: selectedManufacturabilityIssue.location[0],
        y: selectedManufacturabilityIssue.location[1],
        z: selectedManufacturabilityIssue.location[2],
      }
    : null;

  useEffect(() => {
    setSelectedManufacturabilityIssueIndex(null);
  }, [design?.revision_id]);

  const activeMarkerPoint = selectedManufacturabilityPoint ?? selectedFeaturePoint;
  const activeMarkerLabel = selectedManufacturabilityIssue?.code ?? selectedFeature?.name ?? "selection";

  const handleViewerSelect = useCallback(
    (payload: SelectionPayload) => {
      if (!design) return;
      const featureId = inferFeatureFromPoint(design, payload.point);
      if (featureId) {
        selectFeature(featureId, payload.point);
      } else {
        setSelectedFeaturePoint(payload.point);
        setSelectedManufacturabilityIssueIndex(null);
      }
    },
    [design, selectFeature]
  );

  if (!design) {
    return (
      <main style={shellStyle}>
        <header style={headerStyle}>
          <div>
            <p style={eyebrowStyle}>PULSAI · DESIGN STUDIO (BETA)</p>
            <h1 style={titleStyle}>Code-driven CAD with Claude</h1>
            <p style={subtitleStyle}>
              Describe the part. Pulsai writes a build123d Python script,
              executes it in a sandbox, and shows you a printable / millable
              model. Edit by chatting; every change rewrites or patches the
              script.
            </p>
          </div>
        </header>

        <section style={createCardStyle}>
          <h2 style={{ margin: 0, fontSize: 18 }}>Start a new design</h2>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            rows={3}
            placeholder="E.g. 'speaker grill 240mm, 10 rings, 4mm holes'"
            style={textareaStyle}
            disabled={creating}
          />
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <label style={{ fontSize: 12, opacity: 0.75 }}>
              Target process:
              <select
                value={process}
                onChange={(e) => setProcess(e.target.value as typeof process)}
                style={{ marginLeft: 6 }}
              >
                <option value="fdm">3D printing (FDM)</option>
                <option value="cnc">CNC milling</option>
                <option value="either">Either</option>
              </select>
            </label>
            <button
              type="button"
              onClick={() => onCreate(prompt)}
              disabled={creating || !prompt.trim()}
              style={primaryButtonStyle}
            >
              {creating ? "Generating…" : "Generate"}
            </button>
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {TEMPLATE_PROMPTS.map((p) => (
              <button
                key={p.label}
                type="button"
                onClick={() => {
                  setPrompt(p.prompt);
                  onCreate(p.prompt);
                }}
                disabled={creating}
                style={chipButtonStyle}
              >
                {p.label}
              </button>
            ))}
          </div>

          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              flexWrap: "wrap",
              padding: "10px 12px",
              borderRadius: 10,
              background: "rgba(33,150,243,0.10)",
              border: "1px dashed rgba(33,150,243,0.45)",
            }}
          >
            <strong style={{ fontSize: 13 }}>Or import an existing CAD file</strong>
            <span style={{ fontSize: 12, opacity: 0.7 }}>
              <code>.stl</code> for mesh edits, <code>.step</code>/<code>.stp</code> for B-rep parts. Edit by chat — transform, boolean cuts, mounting holes, etc.
            </span>
            <label style={{ ...chipButtonStyle, marginLeft: "auto", cursor: creating ? "wait" : "pointer" }}>
              {creating ? "Importing…" : "Choose file"}
              <input
                type="file"
                accept=".stl,.step,.stp,application/sla,model/stl,application/STEP,application/x-step"
                disabled={creating}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) onImportSTL(file);
                  e.target.value = "";
                }}
                style={{ display: "none" }}
              />
            </label>
          </div>
          {flagships.length > 0 ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <span style={{ fontSize: 11, opacity: 0.65 }}>
                Or fork a real-world starter:
              </span>
              <div style={flagshipGridStyle}>
                {flagships.map((f) => (
                  <button
                    key={f.id}
                    type="button"
                    onClick={() => onForkFlagship(f.id)}
                    disabled={creating}
                    style={flagshipCardStyle}
                    title={f.description}
                  >
                    <span style={flagshipNameStyle}>{f.name}</span>
                    <span style={flagshipDescStyle}>{f.description}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : null}
          {templates.length > 0 ? (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 4 }}>
              <span style={{ fontSize: 11, opacity: 0.6, alignSelf: "center" }}>
                Or a primitive template:
              </span>
              {templates.map((t) => (
                <button
                  key={t.template_id}
                  type="button"
                  onClick={() => onCreate("", t.template_id)}
                  disabled={creating}
                  style={chipButtonStyle}
                >
                  {t.name}
                </button>
              ))}
            </div>
          ) : null}
          {createError ? (
            <p style={{ color: "rgba(244,67,54,0.95)", fontSize: 12 }}>
              {createError}
            </p>
          ) : null}
        </section>

        {recentDesigns.length > 0 ? (
          <section style={createCardStyle}>
            <h2 style={{ margin: 0, fontSize: 16 }}>Your designs</h2>
            <p style={{ margin: 0, fontSize: 12, opacity: 0.65 }}>
              {recentDesigns.length} saved on this device. Click to reopen — your edit history travels with each one.
            </p>
            <div style={recentGridStyle}>
              {recentDesigns.slice(0, 12).map((d) => (
                <div key={d.design_id} style={{ position: "relative" }}>
                  <button
                    type="button"
                    onClick={() => openDesign(d.design_id)}
                    style={recentCardStyle}
                    title={`${d.name} · ${d.parameter_count} params · ${d.feature_count} features`}
                  >
                    <span style={recentNameStyle}>{d.name || "untitled"}</span>
                    <span style={recentMetaStyle}>
                      {d.parameter_count} params · {d.feature_count} features
                    </span>
                    <span style={recentIdStyle}>
                      {d.design_id.slice(0, 8)}
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      deleteDesign(d.design_id);
                    }}
                    aria-label="Delete design"
                    title="Delete design"
                    style={recentDeleteStyle}
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
            {recentDesigns.length > 12 ? (
              <span style={{ fontSize: 11, opacity: 0.5 }}>
                + {recentDesigns.length - 12} more (older). Use the URL ?design=&lt;id&gt; to open a specific one.
              </span>
            ) : null}
          </section>
        ) : null}

        <section style={infoCardStyle}>
          <strong>Why this is different</strong>
          <ul style={{ margin: "6px 0 0", paddingLeft: 18, lineHeight: 1.55 }}>
            <li>The design is a build123d Python script Claude can read and rewrite — no fixed templates.</li>
            <li>Triangular holes, hex grids, fillets, shells, threads — anything build123d expresses, the AI can build.</li>
            <li>Outputs STL + GLB + STEP + DXF. STEP/DXF go straight into Fusion or your CAM tool.</li>
            <li>Manufacturability runs after every build, FDM and CNC modes both supported.</li>
            <li>Scripts run in a sandbox (AST audit, no network, no env passthrough, CPU/memory limits).</li>
          </ul>
        </section>
      </main>
    );
  }

  return (
    <main style={shellStyle}>
      <style>{responsiveCss}</style>
      <header style={headerStyle}>
        <div>
          <p style={eyebrowStyle}>PULSAI · DESIGN STUDIO</p>
          <h1 style={titleStyle}>{design.name}</h1>
          <p style={subtitleStyle}>
            revision <code>{design.revision_id.slice(0, 8)}</code> ·
            {" "}
            {design.parameters.length} parameters · {design.features.length} feature
            blocks · target: <strong>{design.process}</strong>
          </p>
        </div>
        <button type="button" style={backButtonStyle} onClick={returnToStart}>
          ← Back to designs
        </button>
      </header>

      <RevisionTimeline
        designId={design.design_id}
        currentRevisionId={design.revision_id}
        onRestore={() => refreshDesign(design.design_id)}
        refreshKey={design.revision_id}
      />

      <section style={threePaneStyle}>
        <aside style={parametersPaneStyle}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <h3 style={{ ...paneHeaderStyle, margin: "0 0 4px" }}>Parameters</h3>
            <label style={liveToggleStyle} title="Live preview re-renders the model on slider drag (uses more compute)">
              <input
                type="checkbox"
                checked={livePreview}
                onChange={(e) => setLivePreview(e.target.checked)}
              />
              live
            </label>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {design.parameters.map((p) => (
              <ParameterControl
                key={p.name}
                param={p}
                disabled={updatingParam === p.name || Boolean(p.locked)}
                livePreview={livePreview}
                onToggleLock={async (locked) => {
                  setUpdatingParam(p.name);
                  try {
                    const res = await fetch(`${backendUrl}/design/${design.design_id}/parameter-lock`, {
                      method: "POST",
                      headers: { "content-type": "application/json" },
                      body: JSON.stringify({ name: p.name, locked }),
                    });
                    if (res.ok) await refreshDesign(design.design_id);
                  } finally {
                    setUpdatingParam(null);
                  }
                }}
                onLiveChange={(val) => {
                  if (!livePreview) return;
                  if (liveDebounceRef.current) clearTimeout(liveDebounceRef.current);
                  liveDebounceRef.current = setTimeout(() => {
                    fetch(`${backendUrl}/design/${design.design_id}/parameter`, {
                      method: "POST",
                      headers: { "content-type": "application/json" },
                      body: JSON.stringify({ name: p.name, value: val }),
                    }).then((res) => {
                      if (res.ok) refreshDesign(design.design_id);
                    });
                  }, 250);
                }}
                onChange={async (val) => {
                  setUpdatingParam(p.name);
                  try {
                    const res = await fetch(`${backendUrl}/design/${design.design_id}/parameter`, {
                      method: "POST",
                      headers: { "content-type": "application/json" },
                      body: JSON.stringify({ name: p.name, value: val }),
                    });
                    if (res.ok) await refreshDesign(design.design_id);
                  } finally {
                    setUpdatingParam(null);
                  }
                }}
              />
            ))}
            {design.parameters.length === 0 ? (
              <span style={{ fontSize: 12, opacity: 0.55 }}>
                The script declared no parameters via <code>pulsai.param</code>.
              </span>
            ) : null}
          </div>

          <h3 style={paneHeaderStyle}>Features</h3>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {design.features.map((f) => (
              <button
                key={f.id || f.name}
                type="button"
                onClick={() => selectFeature(f.id)}
                style={{
                  ...paramRowStyle,
                  cursor: "pointer",
                  textAlign: "left",
                  border:
                    selectedFeatureId === f.id
                      ? "1px solid rgba(33,150,243,0.7)"
                      : "1px solid transparent",
                }}
                title={`Select ${f.name} for the next chat edit`}
              >
                <span style={{ fontSize: 12, fontWeight: 600 }}>{f.name}</span>
                <span style={{ fontSize: 11, opacity: 0.55 }}>
                  {f.kind} · {f.id}
                </span>
              </button>
            ))}
            {design.features.length === 0 ? (
              <span style={{ fontSize: 12, opacity: 0.55 }}>(no @feature blocks)</span>
            ) : null}
          </div>

          <h3 style={paneHeaderStyle}>Manufacturability</h3>
          {status ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <span style={statusBadgeStyle(status)}>{status}</span>
              {issues.map((issue, i) => {
                const fixDisabled =
                  stream.state.status === "streaming" || makePrintable.busy;
                const fixThisIssue = () => {
                  if (fixDisabled) return;
                  const loc = issue.location
                    ? ` at (x=${issue.location[0].toFixed(1)}, y=${issue.location[1].toFixed(1)}, z=${issue.location[2].toFixed(1)})`
                    : "";
                  const message =
                    `Fix this manufacturability issue: ${issue.code} (${issue.severity}) — ${issue.message}${loc}.` +
                    (issue.suggestion ? ` Suggested approach: ${issue.suggestion}.` : "") +
                    ` Pick the smallest edit that resolves it (a parameter tweak first, a feature replacement only if needed). After the change, run a build and re-check manufacturability so we can confirm the issue is gone.`;
                  stream.send(message, {
                    selectedFeatureId: selectedFeature?.id ?? null,
                    selectedFeatureLabel: selectedFeature?.name ?? null,
                  });
                };
                return (
                  <div key={i} style={issueStyle(issue.severity)}>
                    <strong>{issue.code}</strong>: {issue.message}
                    {issue.suggestion ? (
                      <em style={{ display: "block", opacity: 0.7 }}>
                        → {issue.suggestion}
                      </em>
                    ) : null}
                    <div style={issueMetaRowStyle}>
                      {issue.location ? (
                        <span>
                          x {issue.location[0].toFixed(1)} · y {issue.location[1].toFixed(1)} · z{" "}
                          {issue.location[2].toFixed(1)}
                        </span>
                      ) : (
                        <span />
                      )}
                      <div style={{ display: "flex", gap: 6 }}>
                        {issue.location ? (
                          <button
                            type="button"
                            style={issueLocateButtonStyle}
                            onClick={() => {
                              setSelectedManufacturabilityIssueIndex(i);
                              setSelectedFeaturePoint(null);
                            }}
                          >
                            Locate
                          </button>
                        ) : null}
                        <button
                          type="button"
                          style={issueFixButtonStyle(fixDisabled)}
                          disabled={fixDisabled}
                          title="Ask Pulsai to fix this issue via chat"
                          onClick={fixThisIssue}
                        >
                          {stream.state.status === "streaming"
                            ? "Asking…"
                            : "Fix this"}
                        </button>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <span style={{ fontSize: 12, opacity: 0.55 }}>No build yet.</span>
          )}
          <button
            type="button"
            style={primaryButtonStyle}
            disabled={makePrintable.busy}
            onClick={async () => {
              setMakePrintable({ busy: true });
              try {
                const res = await fetch(`${backendUrl}/design/${design.design_id}/print-bundle`, {
                  method: "POST",
                  headers: { "content-type": "application/json" },
                  body: JSON.stringify({ expected_revision_id: design.revision_id }),
                });
                const payload = await res.json().catch(() => null);
                if (!res.ok) throw new Error(payload?.detail ?? `FDM export failed: ${res.status}`);
                setMakePrintable({
                  busy: false,
                  summary: payload.summary,
                  bundleUrl: payload.bundle_url ? resolveUrl(backendUrl, payload.bundle_url) ?? undefined : undefined,
                  status: payload.status,
                  remainingIssues: payload.remaining_issues ?? [],
                  slicerReady: payload.slicer_ready,
                });
              } catch (error) {
                setMakePrintable({
                  busy: false,
                  error: error instanceof Error ? error.message : "FDM export failed.",
                });
              }
            }}
          >
            {makePrintable.busy ? "Exporting…" : "Export FDM ZIP"}
          </button>
          <span style={exportHintStyle}>
            Download only. Use “Fix this” to ask Pulsai to change geometry.
          </span>
          {makePrintable.summary ? (
            <span style={makePrintableResultStyle(makePrintable.status)}>
              {makePrintable.summary}
              {makePrintable.bundleUrl ? (
                <>
                  {" "}
                  <a href={makePrintable.bundleUrl} target="_blank" rel="noopener noreferrer">
                    Download ZIP
                  </a>
                </>
              ) : null}
            </span>
          ) : null}
          {makePrintable.remainingIssues?.length ? (
            <div style={makePrintableIssueListStyle}>
              {makePrintable.remainingIssues.slice(0, 2).map((issue, index) => (
                <span key={`${issue.code}-${index}`}>
                  <strong>{issue.code}</strong>
                  {issue.suggestion ? ` — ${issue.suggestion}` : issue.message ? ` — ${issue.message}` : null}
                </span>
              ))}
            </div>
          ) : null}
          {makePrintable.error ? (
            <span style={{ ...makePrintableResultStyle("unprintable"), color: "rgba(183,28,28,0.95)" }}>
              {makePrintable.error}
            </span>
          ) : null}

          {design.latest_build?.print_estimate ? (
            <>
              <h3 style={paneHeaderStyle}>Print estimate</h3>
              <PrintEstimatePanel estimate={design.latest_build.print_estimate} />
            </>
          ) : null}
        </aside>

        <section style={canvasPaneStyle}>
          {buildArtifactUrl ? (
            <ModelViewer
              src={buildArtifactUrl}
              label={design.name}
              defaultCameraPreset="iso"
              onSelect={handleViewerSelect}
              onClearSelection={() => {
                setSelectedFeatureId(null);
                setSelectedFeaturePoint(null);
                setSelectedManufacturabilityIssueIndex(null);
              }}
              selectionMarker={
                activeMarkerPoint
                  ? {
                      point: activeMarkerPoint,
                      label: activeMarkerLabel,
                    }
                  : null
              }
              focusTarget={
                activeMarkerPoint
                  ? {
                      point: activeMarkerPoint,
                      distance: 42,
                    }
                  : null
              }
              selectionChip={
                selectedFeature ? (
                  <SelectionChip
                    eyebrow="Selected feature"
                    title={selectedFeature.name}
                    value={`Next chat edit targets ${selectedFeature.id}`}
                    onDismiss={() => {
                      setSelectedFeatureId(null);
                      setSelectedFeaturePoint(null);
                    }}
                  />
                ) : null
              }
            />
          ) : (
            <div style={emptyCanvasStyle}>Build artifact missing.</div>
          )}
          <div style={artifactBarStyle}>
            <ExportMenu
              designId={design.design_id}
              revisionId={design.revision_id}
              backendUrl={backendUrl}
            />
            {design.latest_build?.artifacts ? (
              Object.entries(design.latest_build.artifacts).map(([kind, art]) => {
                const raw =
                  typeof art === "string"
                    ? art
                    : (art as { url?: string } | null)?.url;
                const url = raw ? resolveUrl(backendUrl, raw) : null;
                if (!url) return null;
                return (
                  <a
                    key={kind}
                    href={url}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={downloadLinkStyle}
                  >
                    {kind.toUpperCase()}
                  </a>
                );
              })
            ) : null}
          </div>
        </section>

        <aside style={chatPaneStyle}>
          <h3 style={paneHeaderStyle}>Chat with Pulsai</h3>
          <div style={historyStyle}>
            {stream.history.length === 0 ? (
              <p style={{ fontSize: 12, opacity: 0.6 }}>
                Ask for any geometry change. Examples: <em>"hexagonal holes"</em>,{" "}
                <em>"add a 4mm fillet to the top edge"</em>,{" "}
                <em>"shell with 2mm wall, top open"</em>.
              </p>
            ) : (
              stream.history.map((entry, idx) => (
                <ChatMessage key={idx} entry={entry} />
              ))
            )}
          </div>
          <DesignChatInput
            disabled={stream.state.status === "streaming"}
            selectedFeature={selectedFeature}
            parameters={design.parameters}
            onCancel={stream.cancel}
            onSend={(text) =>
              stream.send(text, {
                selectedFeatureId: selectedFeature?.id ?? null,
                selectedFeatureLabel: selectedFeature?.name ?? null,
              })
            }
            isStreaming={stream.state.status === "streaming"}
          />
          {stream.state.status === "error" ? (
            <p style={{ color: "rgba(244,67,54,0.95)", fontSize: 12 }}>
              {stream.state.errorMessage}
            </p>
          ) : null}
        </aside>
      </section>

      <details style={{ marginTop: 12 }}>
        <summary style={{ cursor: "pointer", fontSize: 12, opacity: 0.65 }}>
          Show generated script ({design.script.split("\n").length} lines)
        </summary>
        <pre style={preStyle}>{design.script}</pre>
      </details>
    </main>
  );
}

function ParameterControl({
  param,
  disabled,
  onChange,
  livePreview = false,
  onLiveChange,
  onToggleLock,
}: {
  param: import("../../types/design").DesignParameter;
  disabled: boolean;
  onChange: (val: number | string | boolean) => void;
  livePreview?: boolean;
  onLiveChange?: (val: number | string | boolean) => void;
  onToggleLock?: (locked: boolean) => void;
}) {
  const [draft, setDraft] = useState<string>(String(param.value));
  const lastEmittedRef = useRef<string>(String(param.value));

  useEffect(() => {
    setDraft(String(param.value));
    lastEmittedRef.current = String(param.value);
  }, [param.value, param.name]);

  const isNumeric = ["length_mm", "count", "angle_deg", "ratio"].includes(param.type);
  const isBool = param.type === "boolean";
  const minN = typeof param.min === "number" ? param.min : isNumeric ? 0 : undefined;
  const maxN =
    typeof param.max === "number"
      ? param.max
      : param.type === "count"
        ? 100
        : param.type === "ratio"
          ? 5
          : param.type === "angle_deg"
            ? 360
            : 1000;
  const step =
    typeof param.step === "number"
      ? param.step
      : param.type === "count"
        ? 1
        : 0.1;

  const commit = (raw: string) => {
    if (lastEmittedRef.current === raw) return;
    lastEmittedRef.current = raw;
    if (isBool) {
      onChange(raw === "true");
      return;
    }
    if (isNumeric) {
      const v = Number(raw);
      if (Number.isFinite(v)) onChange(v);
      return;
    }
    onChange(raw);
  };

  return (
    <div style={paramRowStyle}>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 8 }}>
        <span style={{ fontSize: 12, opacity: 0.85 }}>{param.name}</span>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={paramValueStyle}>{String(param.value)}{param.type === "length_mm" ? " mm" : param.type === "angle_deg" ? "°" : ""}</span>
          <button
            type="button"
            onClick={() => onToggleLock?.(!param.locked)}
            style={lockButtonStyle(Boolean(param.locked))}
            title={param.locked ? "Unlock parameter" : "Lock parameter"}
          >
            {param.locked ? "Locked" : "Lock"}
          </button>
        </div>
      </div>
      {isBool ? (
        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12 }}>
          <input
            type="checkbox"
            checked={Boolean(param.value)}
            disabled={disabled}
            onChange={(e) => onChange(e.target.checked)}
          />
          {Boolean(param.value) ? "true" : "false"}
        </label>
      ) : isNumeric ? (
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <input
            type="range"
            min={minN}
            max={maxN}
            step={step}
            value={Number.isFinite(Number(draft)) ? Number(draft) : 0}
            disabled={disabled}
            onChange={(e) => {
              setDraft(e.target.value);
              if (livePreview && onLiveChange) {
                const v = Number(e.target.value);
                if (Number.isFinite(v)) onLiveChange(v);
              }
            }}
            onMouseUp={() => commit(draft)}
            onTouchEnd={() => commit(draft)}
            onKeyUp={() => commit(draft)}
            style={{ flex: 1 }}
          />
          <input
            type="number"
            value={draft}
            disabled={disabled}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={() => commit(draft)}
            onKeyDown={(e) => {
              if (e.key === "Enter") (e.target as HTMLInputElement).blur();
            }}
            min={minN}
            max={maxN}
            step={step}
            style={{ width: 70, fontSize: 12, padding: "2px 6px" }}
          />
        </div>
      ) : (
        <input
          type="text"
          value={draft}
          disabled={disabled}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => commit(draft)}
          onKeyDown={(e) => {
            if (e.key === "Enter") (e.target as HTMLInputElement).blur();
          }}
          style={{ width: "100%", fontSize: 12, padding: "2px 6px" }}
        />
      )}
      {param.doc ? <span style={paramDocStyle}>{param.doc}</span> : null}
      {disabled ? <span style={{ ...paramDocStyle, color: "rgba(33,150,243,0.85)" }}>updating…</span> : null}
    </div>
  );
}


function DesignChatInput({
  onSend,
  onCancel,
  disabled,
  isStreaming,
  selectedFeature,
  parameters,
}: {
  onSend: (text: string) => void;
  onCancel: () => void;
  disabled: boolean;
  isStreaming: boolean;
  selectedFeature: Design["features"][number] | null;
  parameters: Design["parameters"];
}) {
  const [draft, setDraft] = useState("");
  const [routeBadge, setRouteBadge] = useState<{
    label: string;
    title: string;
    tone: "free" | "cheap" | "full" | "answer";
  } | null>(null);

  useEffect(() => {
    const text = draft.trim();
    if (!text) {
      setRouteBadge(null);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      const badge = classifyDesignEditBadge(text, parameters);
      if (!cancelled) setRouteBadge(badge);
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [draft, parameters]);

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (!draft.trim() || disabled) return;
        onSend(draft.trim());
        setDraft("");
      }}
      style={{ display: "flex", flexDirection: "column", gap: 6 }}
    >
      <textarea
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        rows={2}
        placeholder="Describe an edit…"
        disabled={disabled}
        style={textareaStyle}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && draft.trim() && !disabled) {
            onSend(draft.trim());
            setDraft("");
          }
        }}
      />
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ fontSize: 11, opacity: 0.55 }}>
          {selectedFeature ? `Target: ${selectedFeature.name}` : "⌘/Ctrl+Enter to send."}
        </span>
        {routeBadge ? (
          <span style={routeBadgeStyle(routeBadge.tone)} title={routeBadge.title}>
            {routeBadge.label}
          </span>
        ) : null}
        {isStreaming ? (
          <button type="button" onClick={onCancel} style={secondaryButtonStyle}>
            Stop
          </button>
        ) : (
          <button type="submit" disabled={disabled || !draft.trim()} style={primaryButtonStyle}>
            Send
          </button>
        )}
      </div>
    </form>
  );
}

type DesignEditBadge = {
  label: string;
  title: string;
  tone: "free" | "cheap" | "full" | "answer";
};

function classifyDesignEditBadge(
  text: string,
  parameters: Design["parameters"],
): DesignEditBadge {
  const lower = text.toLowerCase();
  const normalized = lower.replace(/[^a-z0-9_]+/g, " ").replace(/\s+/g, " ").trim();
  const questionLike =
    /^(why|what|how|can|does|do|is|are|where|which|explain|show|tell|count|measure|analyze|check)\b/.test(
      normalized,
    ) || (lower.includes("?") && !/\b(make|set|change|add|remove|delete|split|repair|orient)\b/.test(normalized));

  if (questionLike) {
    return {
      label: "Answer only",
      title: "Likely explanation or inspection; should not rebuild unless the agent needs a check.",
      tone: "answer",
    };
  }

  const hasEditVerb = /\b(make|set|change|increase|decrease|reduce|shrink|enlarge|scale|thicken|thin|add|remove|delete|drill|cut|replace|move|rotate|fillet|chamfer)\b/.test(
    normalized,
  );
  const hasNumericIntent = /\d/.test(normalized) || /\b(twice|double|half|smaller|larger|bigger|thicker|thinner|more|less)\b/.test(normalized);
  const mentionsParam = parameters.some((p) => {
    const name = p.name.toLowerCase();
    const spaced = name.replaceAll("_", " ");
    return (` ${normalized} `.includes(` ${name} `) || ` ${normalized} `.includes(` ${spaced} `));
  });
  if (mentionsParam && hasEditVerb && hasNumericIntent) {
    return {
      label: "Direct param",
      title: "Likely direct parameter update; no full agent rewrite expected.",
      tone: "free",
    };
  }

  if (/\b(split|repair|orient|orientation|support|smooth|mirror|offset|inflate|press fit|hole|holes|drill|detect)\b/.test(normalized)) {
    return {
      label: "Tool edit",
      title: "Likely routed to a focused CAD or mesh tool.",
      tone: "cheap",
    };
  }

  return {
    label: "Agent edit",
    title: "Likely needs the full design-agent loop.",
    tone: "full",
  };
}

function paramNumber(design: Design, name: string, fallback: number): number {
  const value = design.parameters.find((p) => p.name === name)?.value;
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function featureAnchorForDesign(design: Design, featureId: string): { x: number; y: number; z: number } | null {
  const id = featureId.toLowerCase();
  const bbox = design.latest_build?.bounding_box_mm;
  const outerRadius = paramNumber(design, "outer_diameter", bbox?.[0] ?? 40) / 2;
  const height = paramNumber(design, "knob_height", bbox?.[2] ?? 10);
  const insertRadius = paramNumber(design, "insert_diameter", 0) / 2;

  if (id.includes("knurl")) {
    return { x: outerRadius, y: 0, z: height / 2 };
  }
  if (id.includes("hole")) {
    return { x: outerRadius * 0.5, y: 0, z: height };
  }
  if (id.includes("insert") || id.includes("pocket")) {
    return { x: Math.max(insertRadius * 0.4, 0), y: 0, z: 0 };
  }
  if (id.includes("cylinder") || id.includes("body")) {
    return { x: 0, y: 0, z: height };
  }
  return bbox ? { x: 0, y: 0, z: bbox[2] / 2 } : null;
}

function inferFeatureFromPoint(design: Design, point: { x: number; y: number; z: number }): string | null {
  const features = design.features;
  if (!features.length) return null;

  const findFeature = (...needles: string[]) =>
    features.find((feature) => {
      const haystack = `${feature.id} ${feature.name}`.toLowerCase();
      return needles.some((needle) => haystack.includes(needle));
    })?.id ?? null;

  const outerRadius = paramNumber(design, "outer_diameter", design.latest_build?.bounding_box_mm?.[0] ?? 40) / 2;
  const height = paramNumber(design, "knob_height", design.latest_build?.bounding_box_mm?.[2] ?? 10);
  const insertRadius = paramNumber(design, "insert_diameter", 0) / 2;
  const knurlDepth = paramNumber(design, "knurl_depth", 1);
  const radialDistance = Math.hypot(point.x, point.y);

  if (insertRadius > 0 && radialDistance <= insertRadius + 1 && point.z <= height * 0.55) {
    return findFeature("insert", "pocket");
  }
  if (radialDistance >= Math.max(0, outerRadius - Math.max(knurlDepth * 2, 2))) {
    return findFeature("knurl");
  }
  if (point.z >= height * 0.75 && radialDistance > insertRadius + 1 && radialDistance < outerRadius * 0.82) {
    return findFeature("hole");
  }
  return findFeature("cylinder", "body") ?? features[0]?.id ?? null;
}

const shellStyle: React.CSSProperties = {
  minHeight: "100vh",
  padding: "24px 32px",
  display: "flex",
  flexDirection: "column",
  gap: 18,
  background: "linear-gradient(180deg, #fff8eb 0%, #fff 100%)",
  color: "#19120a",
};

const headerStyle: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "flex-end",
  gap: 16,
};

const eyebrowStyle: React.CSSProperties = {
  margin: 0,
  fontSize: 11,
  letterSpacing: 1.5,
  fontWeight: 700,
  opacity: 0.65,
};

const titleStyle: React.CSSProperties = {
  margin: "4px 0",
  fontSize: 26,
  fontWeight: 700,
};

const subtitleStyle: React.CSSProperties = {
  margin: 0,
  opacity: 0.7,
  fontSize: 13,
};

const createCardStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 10,
  padding: 18,
  background: "rgba(255,255,255,0.8)",
  border: "1px solid rgba(0,0,0,0.08)",
  borderRadius: 14,
};

const infoCardStyle: React.CSSProperties = {
  padding: 14,
  background: "rgba(0,0,0,0.04)",
  borderRadius: 12,
  fontSize: 13,
};

const threePaneStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "260px 1fr 360px",
  gap: 16,
  flex: 1,
  minHeight: 540,
};

// CSS injected via a <style> tag — three-column on desktop, single column
// on mobile, with the viewer first so a phone visit shows the model.
const responsiveCss = `
@media (max-width: 900px) {
  main { padding: 16px !important; }
  section[style*="grid-template-columns"] {
    grid-template-columns: 1fr !important;
  }
  /* Stack: viewer first, then chat, then parameters (collapsible later) */
  aside { max-height: none !important; }
}
@media (max-width: 600px) {
  h1 { font-size: 20px !important; }
  .editability-badge { font-size: 10px !important; }
}
`;

const parametersPaneStyle: React.CSSProperties = {
  background: "rgba(255,255,255,0.85)",
  border: "1px solid rgba(0,0,0,0.08)",
  borderRadius: 12,
  padding: 12,
  display: "flex",
  flexDirection: "column",
  gap: 6,
  overflowY: "auto",
  maxHeight: "70vh",
};

const canvasPaneStyle: React.CSSProperties = {
  position: "relative",
  background: "rgba(0,0,0,0.04)",
  border: "1px solid rgba(0,0,0,0.08)",
  borderRadius: 12,
  overflow: "hidden",
  minHeight: 540,
};

const chatPaneStyle: React.CSSProperties = {
  background: "rgba(255,255,255,0.85)",
  border: "1px solid rgba(0,0,0,0.08)",
  borderRadius: 12,
  padding: 12,
  display: "flex",
  flexDirection: "column",
  gap: 8,
  maxHeight: "70vh",
};

const paneHeaderStyle: React.CSSProperties = {
  margin: "10px 0 4px",
  fontSize: 12,
  letterSpacing: 1,
  textTransform: "uppercase",
  opacity: 0.7,
};

const paramRowStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 2,
  padding: "6px 8px",
  background: "rgba(0,0,0,0.04)",
  borderRadius: 6,
};

const paramValueStyle: React.CSSProperties = {
  fontFamily:
    "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace",
  fontSize: 12,
};

const paramDocStyle: React.CSSProperties = {
  fontSize: 11,
  opacity: 0.6,
};

const lockButtonStyle = (locked: boolean): React.CSSProperties => ({
  border: `1px solid ${locked ? "rgba(33,150,243,0.55)" : "rgba(0,0,0,0.12)"}`,
  background: locked ? "rgba(33,150,243,0.12)" : "rgba(255,255,255,0.65)",
  color: locked ? "rgba(13,71,161,0.95)" : "rgba(0,0,0,0.58)",
  borderRadius: 999,
  padding: "2px 6px",
  fontSize: 10,
  fontWeight: 700,
  cursor: "pointer",
});

const makePrintableResultStyle = (status?: string): React.CSSProperties => ({
  fontSize: 11,
  lineHeight: 1.4,
  color:
    status === "safe"
      ? "rgba(27,94,32,0.95)"
      : status === "unprintable"
        ? "rgba(183,28,28,0.95)"
        : "rgba(158,105,0,0.95)",
});

const makePrintableIssueListStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 4,
  fontSize: 11,
  lineHeight: 1.35,
  color: "rgba(114,74,0,0.95)",
  background: "rgba(255,193,7,0.12)",
  border: "1px solid rgba(255,193,7,0.32)",
  borderRadius: 8,
  padding: "6px 8px",
};

const exportHintStyle: React.CSSProperties = {
  fontSize: 10,
  lineHeight: 1.35,
  color: "rgba(0,0,0,0.48)",
};

const historyStyle: React.CSSProperties = {
  flex: 1,
  display: "flex",
  flexDirection: "column",
  gap: 8,
  overflowY: "auto",
  padding: 4,
  minHeight: 200,
};

const textareaStyle: React.CSSProperties = {
  width: "100%",
  resize: "vertical",
  background: "rgba(0,0,0,0.05)",
  border: "1px solid rgba(0,0,0,0.12)",
  borderRadius: 8,
  padding: "8px 10px",
  font: "inherit",
  fontSize: 13,
  color: "inherit",
};

const primaryButtonStyle: React.CSSProperties = {
  padding: "8px 16px",
  background: "rgba(33,150,243,0.85)",
  color: "white",
  border: "none",
  borderRadius: 8,
  cursor: "pointer",
  fontSize: 13,
  fontWeight: 600,
};

const secondaryButtonStyle: React.CSSProperties = {
  ...primaryButtonStyle,
  background: "rgba(0,0,0,0.08)",
  color: "rgba(0,0,0,0.78)",
  border: "1px solid rgba(0,0,0,0.12)",
};

const routeBadgeStyle = (
  tone: "free" | "cheap" | "full" | "answer",
): React.CSSProperties => {
  const colors = {
    answer: ["rgba(33,150,243,0.14)", "rgba(13,71,161,0.9)"],
    free: ["rgba(76,175,80,0.16)", "rgba(46,125,50,0.85)"],
    cheap: ["rgba(255,193,7,0.20)", "rgba(126,87,0,0.9)"],
    full: ["rgba(244,67,54,0.12)", "rgba(183,28,28,0.9)"],
  }[tone];
  return {
    padding: "3px 8px",
    borderRadius: 999,
    background: colors[0],
    color: colors[1],
    fontSize: 10,
    fontWeight: 700,
    whiteSpace: "nowrap",
  };
};

const chipButtonStyle: React.CSSProperties = {
  padding: "6px 12px",
  background: "rgba(0,0,0,0.06)",
  border: "1px solid rgba(0,0,0,0.12)",
  borderRadius: 999,
  cursor: "pointer",
  fontSize: 12,
};

const backButtonStyle: React.CSSProperties = {
  ...chipButtonStyle,
  flexShrink: 0,
  background: "rgba(255,255,255,0.92)",
  fontWeight: 700,
};

const downloadLinkStyle: React.CSSProperties = {
  padding: "4px 10px",
  background: "rgba(0,0,0,0.7)",
  color: "white",
  borderRadius: 6,
  textDecoration: "none",
  fontSize: 11,
  fontWeight: 600,
};

const artifactBarStyle: React.CSSProperties = {
  position: "absolute",
  bottom: 8,
  right: 8,
  display: "flex",
  gap: 6,
};

const emptyCanvasStyle: React.CSSProperties = {
  width: "100%",
  height: "100%",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  color: "rgba(0,0,0,0.4)",
  fontSize: 13,
};

const preStyle: React.CSSProperties = {
  background: "rgba(0,0,0,0.05)",
  padding: 10,
  borderRadius: 6,
  fontSize: 12,
  whiteSpace: "pre-wrap",
  fontFamily:
    "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace",
  maxHeight: 360,
  overflow: "auto",
};

function ExportMenu({
  designId,
  revisionId,
  backendUrl,
}: {
  designId: string;
  revisionId: string;
  backendUrl: string;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const presets = [
    { id: "fdm", label: "Export for 3D printing", desc: "STL · G-code · manifest" },
    { id: "cnc", label: "Export for CNC", desc: "STEP · DXF · setup notes" },
    { id: "docs", label: "Export for docs", desc: "STL · GLB · manifest" },
    { id: "all", label: "Export everything", desc: "all of the above" },
  ];
  const trigger = async (preset: string) => {
    if (busy) return;
    setBusy(preset);
    try {
      const res = await fetch(`${backendUrl}/design/${designId}/export`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ preset, expected_revision_id: revisionId }),
      });
      if (!res.ok) {
        alert(`Export failed: ${res.status}`);
        return;
      }
      const payload = await res.json();
      const url = `${backendUrl.replace(/\/$/, "")}${payload.bundle_url}`;
      window.open(url, "_blank");
      setOpen(false);
    } finally {
      setBusy(null);
    }
  };
  return (
    <div style={{ position: "relative" }}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        style={{
          padding: "4px 12px",
          background: "rgba(33,150,243,0.85)",
          color: "white",
          border: "none",
          borderRadius: 6,
          fontSize: 11,
          fontWeight: 700,
          cursor: "pointer",
        }}
      >
        {busy ? `${busy.toUpperCase()}…` : "Export ⌄"}
      </button>
      {open ? (
        <div
          style={{
            position: "absolute",
            bottom: "calc(100% + 4px)",
            right: 0,
            display: "flex",
            flexDirection: "column",
            background: "rgba(255,255,255,0.96)",
            border: "1px solid rgba(0,0,0,0.12)",
            borderRadius: 8,
            boxShadow: "0 6px 16px rgba(0,0,0,0.18)",
            minWidth: 240,
            overflow: "hidden",
            zIndex: 10,
          }}
        >
          {presets.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => trigger(p.id)}
              disabled={busy !== null}
              style={{
                padding: "8px 12px",
                border: "none",
                background: "transparent",
                cursor: "pointer",
                textAlign: "left",
                font: "inherit",
              }}
            >
              <div style={{ fontWeight: 600, fontSize: 12 }}>{p.label}</div>
              <div style={{ fontSize: 10, opacity: 0.6 }}>{p.desc}</div>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function PrintEstimatePanel({
  estimate,
}: {
  estimate: import("../../types/design").PrintEstimate;
}) {
  const fmtTime = (m: number | null | undefined) => {
    if (m == null) return "—";
    const h = Math.floor(m / 60);
    const min = Math.floor(m % 60);
    if (h <= 0) return `${min} min`;
    return `${h} h ${min} min`;
  };
  const fmtMass = (g: number | null | undefined) =>
    g == null ? "—" : `${g.toFixed(1)} g`;
  const fmtCost = (c: number | null | undefined) =>
    c == null ? "—" : `$${c.toFixed(2)}`;
  return (
    <div style={estimateGridStyle}>
      <div style={estimateCellStyle}>
        <span style={estimateLabelStyle}>weight</span>
        <span style={estimateValueStyle}>{fmtMass(estimate.filament_g)}</span>
      </div>
      <div style={estimateCellStyle}>
        <span style={estimateLabelStyle}>time</span>
        <span style={estimateValueStyle}>{fmtTime(estimate.print_minutes)}</span>
      </div>
      <div style={estimateCellStyle}>
        <span style={estimateLabelStyle}>cost</span>
        <span style={estimateValueStyle}>{fmtCost(estimate.cost_usd)}</span>
      </div>
      {estimate.cost_usd_per_g ? (
        <span style={{ fontSize: 10, opacity: 0.5, gridColumn: "1 / -1" }}>
          @ ${estimate.cost_usd_per_g.toFixed(3)}/g filament
        </span>
      ) : null}
    </div>
  );
}

const recentGridStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))",
  gap: 8,
};

const recentCardStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  alignItems: "flex-start",
  gap: 2,
  width: "100%",
  padding: "10px 12px",
  background: "rgba(255,255,255,0.85)",
  border: "1px solid rgba(0,0,0,0.10)",
  borderRadius: 10,
  cursor: "pointer",
  textAlign: "left",
  font: "inherit",
};

const recentNameStyle: React.CSSProperties = {
  fontWeight: 600,
  fontSize: 13,
  whiteSpace: "nowrap",
  overflow: "hidden",
  textOverflow: "ellipsis",
  width: "100%",
};

const recentMetaStyle: React.CSSProperties = {
  fontSize: 11,
  opacity: 0.65,
};

const recentIdStyle: React.CSSProperties = {
  fontSize: 10,
  opacity: 0.45,
  fontFamily:
    "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace",
};

const recentDeleteStyle: React.CSSProperties = {
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

const flagshipGridStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))",
  gap: 8,
};

const flagshipCardStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  alignItems: "flex-start",
  gap: 4,
  padding: "10px 12px",
  background: "rgba(255,255,255,0.85)",
  border: "1px solid rgba(0,0,0,0.10)",
  borderRadius: 10,
  cursor: "pointer",
  textAlign: "left",
  font: "inherit",
  transition: "transform 100ms ease, border-color 100ms ease",
};

const flagshipNameStyle: React.CSSProperties = {
  fontWeight: 700,
  fontSize: 13,
};

const flagshipDescStyle: React.CSSProperties = {
  fontSize: 11,
  opacity: 0.65,
  lineHeight: 1.3,
};

const liveToggleStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 4,
  fontSize: 10,
  textTransform: "uppercase",
  letterSpacing: 0.8,
  opacity: 0.7,
  cursor: "pointer",
  userSelect: "none",
};

const estimateGridStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "1fr 1fr 1fr",
  gap: 4,
  padding: "6px 8px",
  background: "rgba(0,0,0,0.04)",
  borderRadius: 6,
};

const estimateCellStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
};

const estimateLabelStyle: React.CSSProperties = {
  fontSize: 10,
  textTransform: "uppercase",
  opacity: 0.55,
  letterSpacing: 0.5,
};

const estimateValueStyle: React.CSSProperties = {
  fontSize: 13,
  fontWeight: 600,
  fontFamily:
    "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace",
};

function statusBadgeStyle(status: "safe" | "warn" | "unprintable"): React.CSSProperties {
  const palette = {
    safe: { bg: "rgba(76,175,80,0.18)", border: "rgba(76,175,80,0.55)" },
    warn: { bg: "rgba(255,193,7,0.20)", border: "rgba(255,193,7,0.65)" },
    unprintable: { bg: "rgba(244,67,54,0.22)", border: "rgba(244,67,54,0.65)" },
  }[status];
  return {
    alignSelf: "flex-start",
    padding: "2px 10px",
    background: palette.bg,
    border: `1px solid ${palette.border}`,
    borderRadius: 999,
    fontSize: 12,
    fontWeight: 600,
    textTransform: "uppercase",
    letterSpacing: 0.5,
  };
}

function issueStyle(severity: "info" | "warn" | "error"): React.CSSProperties {
  const color = severity === "error" ? "rgba(244,67,54,0.95)" : severity === "warn" ? "rgba(199,150,0,0.95)" : "rgba(0,0,0,0.65)";
  return {
    fontSize: 12,
    color,
    padding: "4px 6px",
    background: "rgba(0,0,0,0.04)",
    borderRadius: 6,
  };
}

const issueMetaRowStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 8,
  marginTop: 4,
  fontSize: 11,
  opacity: 0.78,
};

const issueLocateButtonStyle: React.CSSProperties = {
  border: "1px solid rgba(199,150,0,0.35)",
  background: "rgba(255,255,255,0.7)",
  color: "rgba(120,78,0,0.95)",
  borderRadius: 999,
  padding: "2px 8px",
  fontSize: 10,
  fontWeight: 700,
  cursor: "pointer",
};

const issueFixButtonStyle = (disabled: boolean): React.CSSProperties => ({
  border: "none",
  background: disabled ? "rgba(33,150,243,0.35)" : "rgba(33,150,243,0.85)",
  color: "white",
  borderRadius: 999,
  padding: "2px 10px",
  fontSize: 10,
  fontWeight: 700,
  cursor: disabled ? "wait" : "pointer",
});
