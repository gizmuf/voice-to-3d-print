"use client";

import type { ChangeEvent, FormEvent } from "react";
import { useMemo, useState } from "react";

import { resolveBackendUrl, resolveUrl } from "../lib/backend";
import type { EditableModel, WorkspaceResponse, WorkspacePresentationMode } from "../types/editable-model";

export type Point2D = [number, number];

export type ExistingModelTarget = {
  id: string;
  type: "planar_pattern_face" | "single_planar_feature" | "unsupported";
  confidence: number;
  editable?: boolean;
  label: string;
  summary: string;
  warnings: string[];
  unsupported_reason?: string | null;
  topology?: "rectangular" | "radial";
  face_polygon_2d?: Point2D[];
  feature_geometry_2d?: Array<{
    id: string;
    center: Point2D;
    outline?: Point2D[];
  }>;
  feature_outline_2d?: Point2D[];
  feature_kind?: "circular_hole" | "slot" | "rectangular_cutout";
  measured?: {
    feature_size?: number | { width: number; height: number };
    spacing_x?: number;
    spacing_y?: number;
    count_x?: number;
    count_y?: number;
    radial_spacing?: number;
    ring_count?: number;
    holes_per_ring?: number[];
    margin?: number;
    center_hole_diameter?: number | null;
    diameter?: number;
    width?: number;
    height?: number;
  };
  fit?: {
    center_x?: number;
    center_y?: number;
    ring_radii?: number[];
    holes_per_ring?: number[];
    center_hole_feature_id?: string;
  };
};

export type ModelAnalysis = {
  extents_mm: number[];
  warnings: string[];
  targets?: ExistingModelTarget[];
  unsupported_reasons?: string[];
};

export type WorkspaceImportContext = {
  mode: WorkspacePresentationMode;
  sourceModelUrl: string | null;
  sourceStlUrl: string | null;
  analysis?: ModelAnalysis | null;
  message?: string | null;
};

type ImportStepResponse = {
  workspace_id: string;
  editable_model: EditableModel;
  glb_url: string;
  import_mode: "reference" | "editable";
};

type ImportModelResponse = {
  source_stl_url: string;
  source_glb_url: string;
  analysis: ModelAnalysis;
  reconstruction_mode: "reconstruction" | "reference" | "locked" | null;
  editable_model?: EditableModel | null;
};

type ExistingModelPanelProps = {
  createWorkspace: (payload: {
    editable_model?: EditableModel;
    source?: "native" | "step_import" | "stl_reconstructed";
  }) => Promise<WorkspaceResponse | null>;
  loadWorkspace: (id: string) => Promise<WorkspaceResponse | null>;
  hydrateWorkspace: (payload: WorkspaceResponse) => void;
  resetWorkspace: () => void;
  onPresentationChange: (context: WorkspaceImportContext | null) => void;
};

const fetchWithTimeout = async (
  url: string,
  options: RequestInit | undefined,
  timeoutMs: number
) => {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timeoutId);
  }
};

const importErrorMessage = async (response: Response, fallback: string) => {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (typeof payload.detail === "string" && payload.detail.trim()) {
      return payload.detail;
    }
  } catch {
    // Keep the caller's fallback when the backend did not return JSON.
  }
  return fallback;
};

const normalizeImportError = (error: unknown, backendUrl: string) => {
  if (error instanceof DOMException && error.name === "AbortError") {
    return "Import timed out. The model may be too large or the backend is still processing.";
  }
  if (error instanceof TypeError && /fetch/i.test(error.message)) {
    return `Could not reach the 3D backend at ${backendUrl}. Start the FastAPI backend, then retry.`;
  }
  return (error as Error).message || "Import failed.";
};

export default function ExistingModelPanel({
  createWorkspace,
  loadWorkspace,
  hydrateWorkspace,
  resetWorkspace,
  onPresentationChange,
}: ExistingModelPanelProps) {
  const backendUrl = resolveBackendUrl();
  const [modelFile, setModelFile] = useState<File | null>(null);
  const [status, setStatus] = useState<"idle" | "importing" | "ready" | "error">("idle");
  const [lastError, setLastError] = useState<string | null>(null);
  const [modeMessage, setModeMessage] = useState<string | null>(null);
  const [lastImportedName, setLastImportedName] = useState<string | null>(null);

  const acceptedLabel = useMemo(() => ".step, .stp, .stl", []);

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] ?? null;
    setModelFile(file);
    setLastError(null);
    setModeMessage(null);
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!modelFile) return;

    setStatus("importing");
    setLastError(null);
    setModeMessage(null);

    try {
      const isStep = modelFile.name.toLowerCase().endsWith(".step") || modelFile.name.toLowerCase().endsWith(".stp");
      const formData = new FormData();
      formData.append("model", modelFile);

      if (isStep) {
        const response = await fetchWithTimeout(`${backendUrl}/import-step`, { method: "POST", body: formData }, 120000);
        if (!response.ok) throw new Error(await importErrorMessage(response, "STEP import failed."));
        const imported = (await response.json()) as ImportStepResponse;
        const workspace = await loadWorkspace(imported.workspace_id);
        if (!workspace) throw new Error("STEP import succeeded but workspace could not be loaded.");
        const hydrated = {
          ...workspace,
          latest_preview:
            workspace.latest_preview ??
            {
              revision_id: workspace.editable_model.revision_id,
              glb_url: imported.glb_url,
              validation: { status: imported.import_mode },
            },
        } satisfies WorkspaceResponse;
        hydrateWorkspace(hydrated);
        onPresentationChange({
          mode: imported.import_mode === "editable" ? "step_editable" : "step_reference",
          sourceModelUrl: resolveUrl(backendUrl, imported.glb_url),
          sourceStlUrl: workspace.latest_preview?.stl_url ? resolveUrl(backendUrl, workspace.latest_preview.stl_url) : null,
          message:
            imported.import_mode === "editable"
              ? "Supported STEP features are editable in the shared workspace."
              : "STEP import is currently reference-only until semantic feature recognition is available for this model.",
        });
        setModeMessage(imported.import_mode === "editable" ? "STEP editable workspace loaded." : "STEP loaded in reference mode.");
        setLastImportedName(modelFile.name);
        setStatus("ready");
        return;
      }

      const response = await fetchWithTimeout(`${backendUrl}/import-model`, { method: "POST", body: formData }, 120000);
      if (!response.ok) throw new Error(await importErrorMessage(response, "STL import failed."));
      const imported = (await response.json()) as ImportModelResponse;
      const sourceModelUrl = resolveUrl(backendUrl, imported.source_glb_url);
      const sourceStlUrl = resolveUrl(backendUrl, imported.source_stl_url);

      if (imported.reconstruction_mode === "reconstruction" && imported.editable_model) {
        const created = await createWorkspace({
          editable_model: imported.editable_model,
          source: "stl_reconstructed",
        });
        if (!created) throw new Error("STL reconstruction workspace could not be created.");
        hydrateWorkspace({
          ...created,
          latest_preview: {
            revision_id: created.editable_model.revision_id,
            glb_url: imported.source_glb_url,
            stl_url: imported.source_stl_url,
            validation: { status: "reference" },
          },
        });
        onPresentationChange({
          mode: "stl_reconstruction",
          sourceModelUrl,
          sourceStlUrl,
          analysis: imported.analysis,
          message: "Supported planar regions were reconstructed into the semantic workspace.",
        });
        setModeMessage("STL reconstruction workspace loaded.");
        setLastImportedName(modelFile.name);
        setStatus("ready");
        return;
      }

      resetWorkspace();
      onPresentationChange({
        mode: imported.reconstruction_mode === "locked" ? "stl_locked" : "stl_reference",
        sourceModelUrl,
        sourceStlUrl,
        analysis: imported.analysis,
        message:
          imported.reconstruction_mode === "locked"
            ? imported.analysis.unsupported_reasons?.[0] || "Reconstruction was attempted, but it was not trustworthy enough for editing."
            : "This STL is available as a visual reference only.",
      });
      setModeMessage(
        imported.reconstruction_mode === "locked"
          ? "STL imported in locked mode."
          : "STL imported in reference mode."
      );
      setLastImportedName(modelFile.name);
      setStatus("ready");
    } catch (error) {
      resetWorkspace();
      onPresentationChange(null);
      setStatus("error");
      setLastError(normalizeImportError(error, backendUrl));
    }
  };

  return (
    <section className="panel">
      <div className="panel-header">
        <p className="eyebrow">Import Model</p>
        <h2>Import editable CAD</h2>
        <p className="panel-subtitle">
          Ask designers for STEP/STP. STL is a final triangle mesh, so editing is limited to reconstruction, reference, or locked modes.
        </p>
      </div>

      <form className="field-stack" onSubmit={handleSubmit}>
        <label className="field-row">
          <span>Model file</span>
          <input type="file" accept={acceptedLabel} onChange={handleFileChange} />
        </label>

        <div className="actions">
          <button type="submit" className="download-button action-button" disabled={!modelFile || status === "importing"}>
            {status === "importing" ? "Importing" : "Import model"}
          </button>
          <span className="hint">Accepted: {acceptedLabel}</span>
        </div>
      </form>

      {lastImportedName ? (
        <div className="project-summary">
          <div className="status-label">Last import</div>
          <div className="muted">{lastImportedName}</div>
        </div>
      ) : null}

      {modeMessage ? (
        <div className="warning-list">
          <span className="warning-chip subtle">{modeMessage}</span>
        </div>
      ) : null}
      {lastError ? <div className="warning-chip">{lastError}</div> : null}
    </section>
  );
}
