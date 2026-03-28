"use client";

import type { ChangeEvent, FormEvent } from "react";
import { useEffect, useMemo, useState } from "react";
import { resolveBackendUrl, resolveUrl } from "../lib/backend";
import { parseEditSpec } from "../lib/edit-spec";

type ExistingModelPanelProps = {
  onModelUrl: (url: string | null) => void;
  onSourceModelUrl: (url: string | null) => void;
  onStlUrl: (url: string | null) => void;
  onGcodeUrl: (url: string | null) => void;
  onBundleUrl: (url: string | null) => void;
};

type ProjectSummary = {
  project_id: string;
  name?: string;
};

type OpeningSummary = {
  opening_id: string;
  area_mm2: number;
  center_mm: {
    x: number;
    y: number;
  };
  bounds_mm: {
    min_x: number;
    max_x: number;
    min_y: number;
    max_y: number;
  };
  width_mm: number;
  height_mm: number;
  shape_guess: string;
};

type PlanarFaceCluster = {
  cluster_id: string;
  face_count: number;
  area_mm2: number;
  normal: number[];
  origin_mm: number[];
  local_bounds_mm: {
    min_x: number;
    max_x: number;
    min_y: number;
    max_y: number;
  };
  openings: OpeningSummary[];
};

type ModelAnalysis = {
  bounds_mm: number[][];
  extents_mm: number[];
  watertight: boolean;
  winding_consistent: boolean;
  face_count: number;
  vertex_count: number;
  warnings: string[];
  planar_face_clusters: PlanarFaceCluster[];
};

type ImportModelResponse = {
  job_id: string;
  model_id: string;
  source_stl_url: string;
  source_glb_url: string;
  analysis: ModelAnalysis;
};

type AnalyzeModelResponse = {
  model_id: string;
  analysis: ModelAnalysis;
};

type ValidationResponse = {
  validation_status?: string;
  warnings?: string[];
  dimensions_mm?: number[];
  estimated_print_risk?: string;
  stl_ready?: boolean;
  gcode_status?: string;
};

type PreviewEditResponse = {
  job_id: string;
  preview_id: string;
  model_id: string;
  glb_url: string;
  stl_url: string;
  analysis: ModelAnalysis;
  structured_edit: Record<string, unknown>;
  validation: ValidationResponse;
  warnings: string[];
};

type ApplyEditResponse = {
  job_id: string;
  model_id: string;
  glb_url: string;
  stl_url: string;
  gcode_url?: string | null;
  validation: ValidationResponse;
  bundle_url?: string | null;
  analysis: ModelAnalysis;
  structured_edit: Record<string, unknown>;
  warnings: string[];
};

class TimeoutError extends Error {
  name = "TimeoutError";

  constructor(message: string) {
    super(message);
  }
}

const TIMEOUTS = {
  import: 120000,
  analyze: 30000,
  preview: 120000,
  apply: 120000,
  projects: 10000,
};

const editPromptExamples = [
  "Replace the selected hole with a rectangular cutout",
  "Resize the selected slot but keep its center",
  "Convert the selected circular opening into a rounded slot",
  "Create 12 rectangular cutouts around the same center on this face",
];

const fetchWithTimeout = async (
  url: string,
  options: RequestInit | undefined,
  timeoutMs: number
) => {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } catch (error) {
    if (controller.signal.aborted) {
      throw new TimeoutError(`Request timed out after ${timeoutMs}ms`);
    }
    throw error;
  } finally {
    clearTimeout(timeoutId);
  }
};

const humanStatus = (status: string) => {
  switch (status) {
    case "importing":
      return "Upload your part";
    case "selecting":
      return "Select the area to modify";
    case "previewing":
      return "Preview the update";
    case "applying":
      return "Export printable STL";
    case "ready":
      return "Ready to export";
    case "error":
      return "Something needs attention";
    default:
      return "Upload an STL to begin";
  }
};

export default function ExistingModelPanel({
  onModelUrl,
  onSourceModelUrl,
  onStlUrl,
  onGcodeUrl,
  onBundleUrl,
}: ExistingModelPanelProps) {
  const backendUrl = resolveBackendUrl();
  const [status, setStatus] = useState("idle");
  const [modelFile, setModelFile] = useState<File | null>(null);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [activeProjectId, setActiveProjectId] = useState<string | null>(null);
  const [isLoadingProjects, setIsLoadingProjects] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [lastError, setLastError] = useState<string | null>(null);
  const [imported, setImported] = useState<ImportModelResponse | null>(null);
  const [analysis, setAnalysis] = useState<ModelAnalysis | null>(null);
  const [selectedClusterId, setSelectedClusterId] = useState("");
  const [selectedOpeningId, setSelectedOpeningId] = useState("");
  const [prompt, setPrompt] = useState(editPromptExamples[0]);
  const [operation, setOperation] = useState("replace_hole_with_rectangle");
  const [targetShape, setTargetShape] = useState("rectangle");
  const [widthMm, setWidthMm] = useState("18");
  const [heightMm, setHeightMm] = useState("12");
  const [diameterMm, setDiameterMm] = useState("12");
  const [depthMm, setDepthMm] = useState("");
  const [cornerRadiusMm, setCornerRadiusMm] = useState("1");
  const [throughAll, setThroughAll] = useState(true);
  const [pattern, setPattern] = useState("none");
  const [count, setCount] = useState("1");
  const [spacingMm, setSpacingMm] = useState("12");
  const [arrayRadiusMm, setArrayRadiusMm] = useState("25");
  const [toleranceMm, setToleranceMm] = useState("0.15");
  const [centerX, setCenterX] = useState("0");
  const [centerY, setCenterY] = useState("0");
  const [previewJobId, setPreviewJobId] = useState<string | null>(null);
  const [validation, setValidation] = useState<ValidationResponse | null>(null);
  const [specText, setSpecText] = useState("");
  const [parseSummary, setParseSummary] = useState<string[]>([]);
  const [parseWarnings, setParseWarnings] = useState<string[]>([]);

  useEffect(() => {
    void refreshProjects();
  }, [backendUrl]);

  const refreshProjects = async () => {
    setIsLoadingProjects(true);
    try {
      const response = await fetchWithTimeout(`${backendUrl}/projects`, undefined, TIMEOUTS.projects);
      if (!response.ok) throw new Error("Projects fetch failed");
      const data = await response.json();
      setProjects((data.items || []) as ProjectSummary[]);
    } catch (error) {
      console.warn("Project refresh failed", error);
    } finally {
      setIsLoadingProjects(false);
    }
  };

  const ensureProjectContext = async (name: string) => {
    if (activeProjectId) {
      return projects.find((project) => project.project_id === activeProjectId) || null;
    }
    const response = await fetchWithTimeout(
      `${backendUrl}/projects`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      },
      TIMEOUTS.projects
    );
    if (!response.ok) throw new Error("Project creation failed");
    const data = await response.json();
    const project = data.project as ProjectSummary;
    setProjects((prev) => [project, ...prev]);
    setActiveProjectId(project.project_id);
    return project;
  };

  const selectedCluster = useMemo(() => {
    return analysis?.planar_face_clusters.find((cluster) => cluster.cluster_id === selectedClusterId) || null;
  }, [analysis, selectedClusterId]);

  const selectedOpening = useMemo(() => {
    return selectedCluster?.openings.find((opening) => opening.opening_id === selectedOpeningId) || null;
  }, [selectedCluster, selectedOpeningId]);

  useEffect(() => {
    if (!analysis?.planar_face_clusters?.length) return;
    if (!selectedClusterId) {
      setSelectedClusterId(analysis.planar_face_clusters[0].cluster_id);
    }
  }, [analysis, selectedClusterId]);

  useEffect(() => {
    if (!selectedCluster) return;
    if (!selectedCluster.openings.length) {
      setSelectedOpeningId("");
      return;
    }
    if (!selectedOpeningId || !selectedCluster.openings.some((opening) => opening.opening_id === selectedOpeningId)) {
      setSelectedOpeningId(selectedCluster.openings[0].opening_id);
    }
  }, [selectedCluster, selectedOpeningId]);

  useEffect(() => {
    if (!selectedOpening) return;
    setCenterX(String(selectedOpening.center_mm.x));
    setCenterY(String(selectedOpening.center_mm.y));
    setWidthMm(String(selectedOpening.width_mm));
    setHeightMm(String(selectedOpening.height_mm));
    setDiameterMm(String(Math.min(selectedOpening.width_mm, selectedOpening.height_mm)));
    if (selectedOpening.shape_guess === "circle") {
      setOperation("replace_hole_with_rectangle");
      setTargetShape("rectangle");
    } else if (selectedOpening.shape_guess === "slot") {
      setOperation("resize_cutout");
      setTargetShape("rounded_slot");
    } else {
      setTargetShape("rectangle");
    }
  }, [selectedOpening]);

  const resetOutputs = () => {
    onStlUrl(null);
    onGcodeUrl(null);
    onBundleUrl(null);
    setValidation(null);
  };

  const handleImportModel = async () => {
    if (!modelFile || isProcessing) return;
    setIsProcessing(true);
    setLastError(null);
    resetOutputs();
    try {
      const project = await ensureProjectContext(modelFile.name.replace(/\.stl$/i, ""));
      const formData = new FormData();
      formData.append("model", modelFile);
      if (project?.project_id) {
        formData.append("project_id", project.project_id);
      }
      setStatus("importing");
      const response = await fetchWithTimeout(
        `${backendUrl}/import-model`,
        { method: "POST", body: formData },
        TIMEOUTS.import
      );
      if (!response.ok) throw new Error("Could not import the STL");
      const data = (await response.json()) as ImportModelResponse;
      setImported(data);
      setAnalysis(data.analysis);
      setPreviewJobId(null);
      onSourceModelUrl(resolveUrl(backendUrl, data.source_glb_url));
      onModelUrl(resolveUrl(backendUrl, data.source_glb_url));
      onStlUrl(resolveUrl(backendUrl, data.source_stl_url));
      setStatus("selecting");
      void refreshProjects();
    } catch (error) {
      console.error(error);
      setStatus("error");
      setLastError((error as Error).message || "Something went wrong.");
    } finally {
      setIsProcessing(false);
    }
  };

  const refreshAnalysis = async () => {
    if (!imported || isProcessing) return;
    setIsProcessing(true);
    setLastError(null);
    try {
      const response = await fetchWithTimeout(
        `${backendUrl}/analyze-model`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model_id: imported.model_id }),
        },
        TIMEOUTS.analyze
      );
      if (!response.ok) throw new Error("Could not refresh mesh analysis");
      const data = (await response.json()) as AnalyzeModelResponse;
      setAnalysis(data.analysis);
    } catch (error) {
      console.error(error);
      setStatus("error");
      setLastError((error as Error).message || "Something went wrong.");
    } finally {
      setIsProcessing(false);
    }
  };

  const buildEditPayload = () => {
    return {
      model_id: imported?.model_id,
      preview_revision_id: previewJobId,
      selection: {
        planar_face_id: selectedClusterId,
        opening_id: selectedOpeningId || null,
      },
      edit_request: {
        operation,
        target_shape: targetShape,
        width_mm: Number(widthMm) || 0,
        height_mm: Number(heightMm) || 0,
        diameter_mm: Number(diameterMm) || 0,
        depth_mm: Number(depthMm) || 0,
        corner_radius_mm: Number(cornerRadiusMm) || 0,
        through_all: throughAll,
        pattern,
        count: Number(count) || 1,
        spacing_mm: Number(spacingMm) || 0,
        array_radius_mm: Number(arrayRadiusMm) || 0,
        tolerance_mm: Number(toleranceMm) || 0.15,
        center_x_mm: Number(centerX) || 0,
        center_y_mm: Number(centerY) || 0,
      },
      prompt,
      project_id: activeProjectId,
    };
  };

  const handleApplySpec = () => {
    const parsed = parseEditSpec(specText);
    setParseSummary(parsed.appliedSummary);
    setParseWarnings(parsed.warnings);

    if (parsed.applied.operation) setOperation(parsed.applied.operation);
    if (parsed.applied.target_shape) setTargetShape(parsed.applied.target_shape);
    if (parsed.applied.width_mm !== undefined) setWidthMm(String(parsed.applied.width_mm));
    if (parsed.applied.height_mm !== undefined) setHeightMm(String(parsed.applied.height_mm));
    if (parsed.applied.diameter_mm !== undefined) setDiameterMm(String(parsed.applied.diameter_mm));
    if (parsed.applied.depth_mm !== undefined) setDepthMm(String(parsed.applied.depth_mm));
    if (parsed.applied.corner_radius_mm !== undefined) {
      setCornerRadiusMm(String(parsed.applied.corner_radius_mm));
    }
    if (parsed.applied.through_all !== undefined) setThroughAll(parsed.applied.through_all);
    if (parsed.applied.pattern) setPattern(parsed.applied.pattern);
    if (parsed.applied.count !== undefined) setCount(String(parsed.applied.count));
    if (parsed.applied.spacing_mm !== undefined) setSpacingMm(String(parsed.applied.spacing_mm));
    if (parsed.applied.array_radius_mm !== undefined) {
      setArrayRadiusMm(String(parsed.applied.array_radius_mm));
    }
    if (parsed.applied.tolerance_mm !== undefined) setToleranceMm(String(parsed.applied.tolerance_mm));
    if (parsed.applied.center_x_mm !== undefined) setCenterX(String(parsed.applied.center_x_mm));
    if (parsed.applied.center_y_mm !== undefined) setCenterY(String(parsed.applied.center_y_mm));

    if (parsed.leftoverPrompt.trim()) {
      setPrompt((prev) => {
        const next = prev.trim();
        if (!next) return parsed.leftoverPrompt;
        if (next.includes(parsed.leftoverPrompt.trim())) return prev;
        return `${next}\n${parsed.leftoverPrompt}`.trim();
      });
    }
  };

  const handlePreviewEdit = async () => {
    if (!imported || !selectedClusterId || isProcessing) return;
    setIsProcessing(true);
    setLastError(null);
    resetOutputs();
    try {
      setStatus("previewing");
      const response = await fetchWithTimeout(
        `${backendUrl}/preview-edit`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(buildEditPayload()),
        },
        TIMEOUTS.preview
      );
      if (!response.ok) throw new Error("Could not preview the selected edit");
      const data = (await response.json()) as PreviewEditResponse;
      setPreviewJobId(data.preview_id);
      setAnalysis(data.analysis);
      setValidation(data.validation);
      onModelUrl(resolveUrl(backendUrl, data.glb_url));
      onStlUrl(resolveUrl(backendUrl, data.stl_url));
      onBundleUrl(null);
      setStatus("ready");
      void refreshProjects();
    } catch (error) {
      console.error(error);
      setStatus("error");
      setLastError((error as Error).message || "Something went wrong.");
    } finally {
      setIsProcessing(false);
    }
  };

  const handleApplyEdit = async () => {
    if (!imported || !selectedClusterId || isProcessing) return;
    setIsProcessing(true);
    setLastError(null);
    try {
      setStatus("applying");
      const response = await fetchWithTimeout(
        `${backendUrl}/apply-edit`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(buildEditPayload()),
        },
        TIMEOUTS.apply
      );
      if (!response.ok) throw new Error("Could not export the edited STL");
      const data = (await response.json()) as ApplyEditResponse;
      setAnalysis(data.analysis);
      setValidation(data.validation);
      onModelUrl(resolveUrl(backendUrl, data.glb_url));
      onStlUrl(resolveUrl(backendUrl, data.stl_url));
      onGcodeUrl(resolveUrl(backendUrl, data.gcode_url));
      onBundleUrl(resolveUrl(backendUrl, data.bundle_url));
      setStatus("ready");
      void refreshProjects();
    } catch (error) {
      console.error(error);
      setStatus("error");
      setLastError((error as Error).message || "Something went wrong.");
    } finally {
      setIsProcessing(false);
    }
  };

  const selectionSummary = selectedCluster
    ? `${selectedCluster.area_mm2.toFixed(0)} mm² face · ${selectedCluster.openings.length} openings`
    : "Import an STL and choose a planar face";

  return (
    <section className="panel">
      <div className="panel-header">
        <p className="eyebrow">Precision STL Editor</p>
        <h2>Upload a real part and modify exact openings</h2>
        <p className="panel-subtitle">
          STL import, planar face selection, detected opening targeting, precise mm controls,
          preview, validation, and export.
        </p>
      </div>

      <div className="panel-body">
        <div className="status-card">
          <div className="status-label">Current stage</div>
          <div className="status-value">{humanStatus(status)}</div>
          <div className="intent muted">
            {selectedCluster
              ? `Selected ${selectedCluster.cluster_id}. ${selectionSummary}.`
              : "Upload an STL first, then select a planar face cluster and optional detected opening."}
          </div>
        </div>

        <div className="field-row">
          <label htmlFor="edit-project">Project</label>
          <select
            id="edit-project"
            value={activeProjectId || ""}
            onChange={(event) => setActiveProjectId(event.target.value || null)}
          >
            <option value="">Create project automatically</option>
            {projects.map((project) => (
              <option key={project.project_id} value={project.project_id}>
                {project.name || project.project_id}
              </option>
            ))}
          </select>
          <div className="text-input-actions">
            <button
              type="button"
              className="text-submit"
              onClick={() => setActiveProjectId(null)}
              disabled={isProcessing}
            >
              New project
            </button>
            <button
              type="button"
              className="text-submit"
              onClick={refreshProjects}
              disabled={isProcessing || isLoadingProjects}
            >
              {isLoadingProjects ? "Refreshing..." : "Refresh projects"}
            </button>
          </div>
        </div>

        <div className="field-row">
          <label htmlFor="model-upload">Upload STL</label>
          <input
            id="model-upload"
            type="file"
            className="native-file-input"
            accept=".stl,model/stl"
            onChange={(event: ChangeEvent<HTMLInputElement>) => setModelFile(event.target.files?.[0] || null)}
            disabled={isProcessing}
          />
          <span className="muted">
            {modelFile ? `Selected: ${modelFile.name}` : "STL only for the precision editor in v1."}
          </span>
          <div className="text-input-actions">
            <button
              type="button"
              className="text-submit"
              onClick={handleImportModel}
              disabled={!modelFile || isProcessing}
            >
              Import STL
            </button>
            <button
              type="button"
              className="text-submit"
              onClick={refreshAnalysis}
              disabled={!imported || isProcessing}
            >
              Refresh analysis
            </button>
          </div>
        </div>

        {analysis ? (
          <div className="project-summary">
            <div className="status-label">Mesh Analysis</div>
            <div className="analysis-grid">
              <span>Size: {analysis.extents_mm.join(" × ")} mm</span>
              <span>Faces: {analysis.face_count}</span>
              <span>Vertices: {analysis.vertex_count}</span>
              <span>{analysis.watertight ? "Watertight" : "Needs repair"}</span>
            </div>
            {analysis.warnings.length ? (
              <div className="warning-list">
                {analysis.warnings.map((warning) => (
                  <span key={warning} className="warning-chip">
                    {warning}
                  </span>
                ))}
              </div>
            ) : (
              <div className="muted">Planar face clusters are ready for precise edits.</div>
            )}
          </div>
        ) : null}

        {analysis ? (
          <div className="selection-grid">
            <label className="field-row">
              <span>Planar face cluster</span>
              <select
                value={selectedClusterId}
                onChange={(event) => setSelectedClusterId(event.target.value)}
                disabled={isProcessing}
              >
                <option value="">Choose a planar face</option>
                {analysis.planar_face_clusters.map((cluster) => (
                  <option key={cluster.cluster_id} value={cluster.cluster_id}>
                    {cluster.cluster_id} · {cluster.area_mm2.toFixed(0)} mm² · {cluster.openings.length} openings
                  </option>
                ))}
              </select>
            </label>

            <label className="field-row">
              <span>Detected opening (optional)</span>
              <select
                value={selectedOpeningId}
                onChange={(event) => setSelectedOpeningId(event.target.value)}
                disabled={isProcessing || !selectedCluster}
              >
                <option value="">No specific opening selected</option>
                {selectedCluster?.openings.map((opening) => (
                  <option key={opening.opening_id} value={opening.opening_id}>
                    {opening.shape_guess} · {opening.width_mm.toFixed(2)} × {opening.height_mm.toFixed(2)} mm
                  </option>
                ))}
              </select>
            </label>
          </div>
        ) : null}

        {selectedCluster ? (
          <div className="project-summary">
            <div className="status-label">Selection</div>
            <div className="analysis-grid">
              <span>
                Face bounds: {selectedCluster.local_bounds_mm.min_x} to {selectedCluster.local_bounds_mm.max_x} x
              </span>
              <span>
                {selectedCluster.local_bounds_mm.min_y} to {selectedCluster.local_bounds_mm.max_y} y
              </span>
              <span>Normal: {selectedCluster.normal.join(", ")}</span>
            </div>
            {selectedOpening ? (
              <div className="muted">
                Opening center {selectedOpening.center_mm.x}, {selectedOpening.center_mm.y} mm · shape guess {selectedOpening.shape_guess}
              </div>
            ) : (
              <div className="muted">
                No opening selected. The cut will use the current center coordinates on this planar face.
              </div>
            )}
          </div>
        ) : null}

        <form
          className="field-row"
          onSubmit={(event: FormEvent<HTMLFormElement>) => {
            event.preventDefault();
            void handlePreviewEdit();
          }}
        >
          <label htmlFor="edit-spec">Structured edit spec</label>
          <textarea
            id="edit-spec"
            rows={6}
            value={specText}
            onChange={(event) => setSpecText(event.target.value)}
            disabled={isProcessing}
            placeholder={`operation: replace_hole_with_rectangle\nwidth_mm: 8\nheight_mm: 5\nthrough_all: true`}
          />
          <div className="text-input-actions">
            <button
              type="button"
              className="text-submit"
              onClick={handleApplySpec}
              disabled={!specText.trim() || isProcessing}
            >
              Apply spec
            </button>
            <span className="muted">
              Supports JSON or flat <code>key: value</code> lines. Geometry target stays in the selectors above.
            </span>
          </div>

          {parseSummary.length ? (
            <div className="project-summary">
              <div className="status-label">Applied spec values</div>
              <div className="warning-list">
                {parseSummary.map((item) => (
                  <span key={item} className="chip">
                    {item}
                  </span>
                ))}
              </div>
            </div>
          ) : null}

          {parseWarnings.length ? (
            <div className="project-summary">
              <div className="status-label">Spec warnings</div>
              <div className="warning-list">
                {parseWarnings.map((warning) => (
                  <span key={warning} className="warning-chip">
                    {warning}
                  </span>
                ))}
              </div>
            </div>
          ) : null}

          <label htmlFor="edit-prompt">Describe the change</label>
          <textarea
            id="edit-prompt"
            rows={3}
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            disabled={isProcessing}
            placeholder="Replace the selected hole with a rectangular cutout"
          />
          <div className="prompt-chips">
            {editPromptExamples.map((chip) => (
              <button
                key={chip}
                type="button"
                className="prompt-chip"
                onClick={() => setPrompt(chip)}
                disabled={isProcessing}
              >
                {chip}
              </button>
            ))}
          </div>

          <div className="spec-grid">
            <label className="field-row compact-field">
              <span>Operation</span>
              <select value={operation} onChange={(event) => setOperation(event.target.value)} disabled={isProcessing}>
                <option value="replace_cutout_shape">Replace cutout shape</option>
                <option value="resize_cutout">Resize cutout</option>
                <option value="replace_hole_with_slot">Replace hole with slot</option>
                <option value="replace_hole_with_rectangle">Replace hole with rectangle</option>
                <option value="replace_slot_with_rectangle">Replace slot with rectangle</option>
                <option value="replace_rectangle_with_circle">Replace rectangle with circle</option>
                <option value="array_selected_cutout">Array selected cutout</option>
              </select>
            </label>
            <label className="field-row compact-field">
              <span>Target shape</span>
              <select value={targetShape} onChange={(event) => setTargetShape(event.target.value)} disabled={isProcessing}>
                <option value="rectangle">Rectangle</option>
                <option value="rounded_slot">Rounded slot</option>
                <option value="circle">Circle</option>
              </select>
            </label>
            <label className="field-row compact-field">
              <span>Width mm</span>
              <input type="number" value={widthMm} onChange={(event) => setWidthMm(event.target.value)} disabled={isProcessing} />
            </label>
            <label className="field-row compact-field">
              <span>Height mm</span>
              <input type="number" value={heightMm} onChange={(event) => setHeightMm(event.target.value)} disabled={isProcessing} />
            </label>
            <label className="field-row compact-field">
              <span>Diameter mm</span>
              <input type="number" value={diameterMm} onChange={(event) => setDiameterMm(event.target.value)} disabled={isProcessing} />
            </label>
            <label className="field-row compact-field">
              <span>Depth mm</span>
              <input type="number" value={depthMm} onChange={(event) => setDepthMm(event.target.value)} disabled={isProcessing || throughAll} />
            </label>
            <label className="field-row compact-field">
              <span>Corner radius mm</span>
              <input type="number" value={cornerRadiusMm} onChange={(event) => setCornerRadiusMm(event.target.value)} disabled={isProcessing} />
            </label>
            <label className="field-row compact-field">
              <span>Center X mm</span>
              <input type="number" value={centerX} onChange={(event) => setCenterX(event.target.value)} disabled={isProcessing} />
            </label>
            <label className="field-row compact-field">
              <span>Center Y mm</span>
              <input type="number" value={centerY} onChange={(event) => setCenterY(event.target.value)} disabled={isProcessing} />
            </label>
            <label className="field-row compact-field">
              <span>Pattern</span>
              <select value={pattern} onChange={(event) => setPattern(event.target.value)} disabled={isProcessing}>
                <option value="none">None</option>
                <option value="linear">Linear</option>
                <option value="circular">Circular</option>
              </select>
            </label>
            <label className="field-row compact-field">
              <span>Count</span>
              <input type="number" value={count} onChange={(event) => setCount(event.target.value)} disabled={isProcessing} />
            </label>
            <label className="field-row compact-field">
              <span>Spacing mm</span>
              <input type="number" value={spacingMm} onChange={(event) => setSpacingMm(event.target.value)} disabled={isProcessing} />
            </label>
            <label className="field-row compact-field">
              <span>Array radius mm</span>
              <input type="number" value={arrayRadiusMm} onChange={(event) => setArrayRadiusMm(event.target.value)} disabled={isProcessing} />
            </label>
            <label className="field-row compact-field">
              <span>Tolerance mm</span>
              <input type="number" value={toleranceMm} onChange={(event) => setToleranceMm(event.target.value)} disabled={isProcessing} />
            </label>
            <label className="field-row compact-field">
              <span>Through all</span>
              <select value={throughAll ? "true" : "false"} onChange={(event) => setThroughAll(event.target.value === "true")} disabled={isProcessing}>
                <option value="true">True</option>
                <option value="false">False</option>
              </select>
            </label>
          </div>

          <div className="text-input-actions">
            <button
              type="submit"
              className="text-submit"
              disabled={!imported || !selectedClusterId || isProcessing}
            >
              Preview edit
            </button>
            <button
              type="button"
              className="text-submit"
              onClick={handleApplyEdit}
              disabled={!imported || !selectedClusterId || isProcessing}
            >
              Apply and export STL
            </button>
          </div>
        </form>

        {validation ? (
          <div className="validation-card">
            <div className="status-label">Printability report</div>
            <div className="validation-headline">
              {validation.validation_status || "unknown"} · risk {validation.estimated_print_risk || "unknown"}
            </div>
            {validation.dimensions_mm?.length ? (
              <div className="muted">Current size: {validation.dimensions_mm.join(" × ")} mm</div>
            ) : null}
            {validation.warnings?.length ? (
              <div className="warning-list">
                {validation.warnings.map((warning) => (
                  <span key={warning} className="warning-chip">
                    {warning}
                  </span>
                ))}
              </div>
            ) : (
              <div className="muted">No major validation warnings.</div>
            )}
          </div>
        ) : null}

        {lastError ? <div className="error-card">{lastError}</div> : null}
      </div>
    </section>
  );
}
