"use client";

import type { ChangeEvent, FormEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { SelectionPayload } from "./ModelViewer";
import { resolveBackendUrl, resolveUrl } from "../lib/backend";
import { parseEditSpec } from "../lib/edit-spec";

type ExistingModelPanelProps = {
  onModelUrl: (url: string | null) => void;
  onSourceModelUrl: (url: string | null) => void;
  onStlUrl: (url: string | null) => void;
  onGcodeUrl: (url: string | null) => void;
  onBundleUrl: (url: string | null) => void;
  viewerSelectionHint?: SelectionPayload | null;
};

type LocalFrame = {
  x_axis: number[];
  y_axis: number[];
  z_axis: number[];
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
  local_frame?: LocalFrame;
  local_bounds_mm: {
    min_x: number;
    max_x: number;
    min_y: number;
    max_y: number;
  };
  openings: OpeningSummary[];
};

type OpeningGroup = {
  id: string;
  title: string;
  summary: string;
  representativeOpeningId: string;
  openingIds: string[];
  count: number;
  avgWidth: number;
  avgHeight: number;
  shapeGuess: string;
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

const dot = (left: number[], right: number[]) => {
  return left.reduce((sum, value, index) => sum + value * (right[index] ?? 0), 0);
};

const projectPointToCluster = (point: SelectionPayload["point"], cluster: PlanarFaceCluster) => {
  if (!cluster.local_frame) {
    return null;
  }
  const origin = cluster.origin_mm;
  const shifted = [point.x - origin[0], point.y - origin[1], point.z - origin[2]];
  return {
    x: dot(shifted, cluster.local_frame.x_axis),
    y: dot(shifted, cluster.local_frame.y_axis),
    z: dot(shifted, cluster.local_frame.z_axis),
  };
};

const findNearestOpeningSelection = (
  point: SelectionPayload["point"],
  clusters: PlanarFaceCluster[]
) => {
  let bestMatch: { clusterId: string; openingId: string; score: number } | null = null;

  for (const cluster of clusters) {
    const localPoint = projectPointToCluster(point, cluster);
    if (!localPoint) continue;
    const planeDistance = Math.abs(localPoint.z);

    for (const opening of cluster.openings) {
      const openingBounds = opening.bounds_mm;
      const insideOpening =
        localPoint.x >= openingBounds.min_x - 3 &&
        localPoint.x <= openingBounds.max_x + 3 &&
        localPoint.y >= openingBounds.min_y - 3 &&
        localPoint.y <= openingBounds.max_y + 3;
      const centerDistance = Math.hypot(
        localPoint.x - opening.center_mm.x,
        localPoint.y - opening.center_mm.y
      );
      const score = centerDistance + planeDistance * 8 + (insideOpening ? 0 : 16);
      if (!bestMatch || score < bestMatch.score) {
        bestMatch = {
          clusterId: cluster.cluster_id,
          openingId: opening.opening_id,
          score,
        };
      }
    }
  }

  return bestMatch;
};

const clusterSortScore = (cluster: PlanarFaceCluster) => {
  return cluster.openings.length * 100000 + cluster.area_mm2;
};

const describeCluster = (cluster: PlanarFaceCluster) => {
  if (cluster.openings.length >= 8) {
    return `${cluster.cluster_id} · perforated face · ${cluster.openings.length} openings`;
  }
  if (cluster.openings.length >= 1) {
    return `${cluster.cluster_id} · face with openings · ${cluster.openings.length} openings`;
  }
  return `${cluster.cluster_id} · solid face`;
};

const buildOpeningGroups = (openings: OpeningSummary[]): OpeningGroup[] => {
  const groups: Array<{
    shapeGuess: string;
    openings: OpeningSummary[];
    avgWidth: number;
    avgHeight: number;
  }> = [];

  for (const opening of openings) {
    const match = groups.find(
      (group) =>
        group.shapeGuess === opening.shape_guess &&
        Math.abs(group.avgWidth - opening.width_mm) <= 1.5 &&
        Math.abs(group.avgHeight - opening.height_mm) <= 1.5
    );
    if (!match) {
      groups.push({
        shapeGuess: opening.shape_guess,
        openings: [opening],
        avgWidth: opening.width_mm,
        avgHeight: opening.height_mm,
      });
      continue;
    }
    match.openings.push(opening);
    match.avgWidth = match.openings.reduce((sum, item) => sum + item.width_mm, 0) / match.openings.length;
    match.avgHeight = match.openings.reduce((sum, item) => sum + item.height_mm, 0) / match.openings.length;
  }

  return groups
    .map((group, index) => {
      const representative = group.openings.reduce((best, candidate) => {
        const bestDistance = Math.hypot(best.width_mm - group.avgWidth, best.height_mm - group.avgHeight);
        const candidateDistance = Math.hypot(
          candidate.width_mm - group.avgWidth,
          candidate.height_mm - group.avgHeight
        );
        return candidateDistance < bestDistance ? candidate : best;
      }, group.openings[0]);
      const avgSize = (group.avgWidth + group.avgHeight) / 2;
      const title =
        group.openings.length > 1
          ? avgSize <= 12
            ? "Small repeated holes"
            : "Repeated openings"
          : avgSize > 15
            ? "Large opening"
            : "Single opening";
      return {
        id: `group-${index + 1}`,
        title,
        summary: `${group.shapeGuess} · ${group.openings.length} opening${group.openings.length === 1 ? "" : "s"} · ${group.avgWidth.toFixed(1)} × ${group.avgHeight.toFixed(1)} mm`,
        representativeOpeningId: representative.opening_id,
        openingIds: group.openings.map((opening) => opening.opening_id),
        count: group.openings.length,
        avgWidth: group.avgWidth,
        avgHeight: group.avgHeight,
        shapeGuess: group.shapeGuess,
      } satisfies OpeningGroup;
    })
    .sort((left, right) => {
      if (right.count !== left.count) return right.count - left.count;
      return left.avgWidth + left.avgHeight - (right.avgWidth + right.avgHeight);
    });
};

export default function ExistingModelPanel({
  onModelUrl,
  onSourceModelUrl,
  onStlUrl,
  onGcodeUrl,
  onBundleUrl,
  viewerSelectionHint,
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
  const [lastSelectionHintKey, setLastSelectionHintKey] = useState<string | null>(null);
  const [viewerSelectionMessage, setViewerSelectionMessage] = useState<string | null>(null);
  const [applyToSimilar, setApplyToSimilar] = useState(true);
  const lastHydratedSelectionKey = useRef<string | null>(null);

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

  const sortedClusters = useMemo(() => {
    return [...(analysis?.planar_face_clusters || [])].sort((left, right) => clusterSortScore(right) - clusterSortScore(left));
  }, [analysis]);

  const selectedOpeningGroups = useMemo(() => {
    return selectedCluster ? buildOpeningGroups(selectedCluster.openings) : [];
  }, [selectedCluster]);

  const activeOpeningGroup = useMemo(() => {
    if (!selectedOpeningId) return null;
    return selectedOpeningGroups.find((group) => group.openingIds.includes(selectedOpeningId)) || null;
  }, [selectedOpeningGroups, selectedOpeningId]);

  const inferredTargetShape = useMemo(() => {
    if (operation === "replace_rectangle_with_circle") return "circle";
    if (operation === "replace_hole_with_slot") return "rounded_slot";
    if (operation === "replace_hole_with_rectangle" || operation === "replace_slot_with_rectangle") {
      return "rectangle";
    }
    if (operation === "resize_cutout") {
      if (selectedOpening?.shape_guess === "circle") return "circle";
      if (selectedOpening?.shape_guess === "slot") return "rounded_slot";
      return targetShape;
    }
    return targetShape;
  }, [operation, selectedOpening?.shape_guess, targetShape]);

  const isRepeatedGroup = Boolean(activeOpeningGroup && activeOpeningGroup.count > 1);
  const usesDiameterField = inferredTargetShape === "circle";
  const usesWidthHeightFields = inferredTargetShape !== "circle";
  const showCornerRadiusField =
    inferredTargetShape === "rectangle" &&
    (operation === "replace_cutout_shape" ||
      operation === "replace_hole_with_rectangle" ||
      operation === "replace_slot_with_rectangle");

  useEffect(() => {
    if (!sortedClusters.length) return;
    if (!selectedClusterId || !sortedClusters.some((cluster) => cluster.cluster_id === selectedClusterId)) {
      setSelectedClusterId(sortedClusters[0].cluster_id);
    }
  }, [selectedClusterId, sortedClusters]);

  useEffect(() => {
    if (!selectedCluster) return;
    if (!selectedCluster.openings.length) {
      setSelectedOpeningId("");
      return;
    }
    if (!selectedOpeningId || !selectedCluster.openings.some((opening) => opening.opening_id === selectedOpeningId)) {
      const preferredGroup = buildOpeningGroups(selectedCluster.openings)[0];
      setSelectedOpeningId(preferredGroup?.representativeOpeningId || selectedCluster.openings[0].opening_id);
    }
  }, [selectedCluster, selectedOpeningId]);

  useEffect(() => {
    if (!selectedOpening) return;
    const selectionKey = `${selectedClusterId}:${selectedOpening.opening_id}`;
    if (lastHydratedSelectionKey.current === selectionKey) {
      return;
    }
    lastHydratedSelectionKey.current = selectionKey;
    setCenterX(String(selectedOpening.center_mm.x));
    setCenterY(String(selectedOpening.center_mm.y));
    setWidthMm(String(selectedOpening.width_mm));
    setHeightMm(String(selectedOpening.height_mm));
    setDiameterMm(String(Math.min(selectedOpening.width_mm, selectedOpening.height_mm)));
    if (selectedOpening.shape_guess === "circle") {
      setOperation("resize_cutout");
      setTargetShape("circle");
    } else if (selectedOpening.shape_guess === "slot") {
      setOperation("resize_cutout");
      setTargetShape("rounded_slot");
    } else {
      setOperation("resize_cutout");
      setTargetShape("rectangle");
    }
  }, [selectedClusterId, selectedOpening]);

  useEffect(() => {
    setApplyToSimilar(Boolean(activeOpeningGroup && activeOpeningGroup.count > 1));
  }, [activeOpeningGroup?.id]);

  useEffect(() => {
    if (!viewerSelectionHint || !analysis?.planar_face_clusters?.length) return;
    const hintKey = [
      viewerSelectionHint.point.x,
      viewerSelectionHint.point.y,
      viewerSelectionHint.point.z,
    ].join(":");
    if (hintKey === lastSelectionHintKey) return;
    setLastSelectionHintKey(hintKey);

    const match = findNearestOpeningSelection(
      viewerSelectionHint.point,
      analysis.planar_face_clusters as PlanarFaceCluster[]
    );

    if (!match) {
      setViewerSelectionMessage("Clicked area did not map cleanly to a detected opening.");
      return;
    }

    setSelectedClusterId(match.clusterId);
    setSelectedOpeningId(match.openingId);
    setViewerSelectionMessage(`Picked ${match.openingId} from the 3D view.`);
  }, [analysis, lastSelectionHintKey, viewerSelectionHint]);

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
      lastHydratedSelectionKey.current = null;
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
    const scopedOpeningIds =
      applyToSimilar && activeOpeningGroup?.openingIds?.length ? activeOpeningGroup.openingIds : undefined;
    return {
      model_id: imported?.model_id,
      preview_revision_id: previewJobId,
      selection: {
        planar_face_id: selectedClusterId,
        opening_id: selectedOpeningId || null,
        opening_ids: scopedOpeningIds,
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
            className="sr-only-file-input"
            accept=".stl,model/stl"
            onChange={(event: ChangeEvent<HTMLInputElement>) => setModelFile(event.target.files?.[0] || null)}
            disabled={isProcessing}
          />
          <div className="file-picker-row">
            <label
              htmlFor="model-upload"
              className={`text-submit upload-trigger ${isProcessing ? "disabled" : ""}`}
              aria-disabled={isProcessing}
            >
              Choose STL file
            </label>
            <span className="muted file-picker-name">
              {modelFile ? modelFile.name : "No STL selected yet."}
            </span>
          </div>
          <span className="muted">STL only for the precision editor in v1.</span>
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
          <div className="project-summary">
            <div className="status-label">Quick target</div>
            {selectedCluster ? (
              <>
                <div className="muted">
                  Editing {describeCluster(selectedCluster)}. Choose the kind of opening you want to change.
                </div>
                {selectedOpeningGroups.length ? (
                  <div className="target-group-list">
                    {selectedOpeningGroups.map((group) => (
                      <button
                        key={group.id}
                        type="button"
                        className={`target-group-card ${activeOpeningGroup?.id === group.id ? "active" : ""}`}
                        onClick={() => setSelectedOpeningId(group.representativeOpeningId)}
                        disabled={isProcessing}
                      >
                        <strong>{group.title}</strong>
                        <span>{group.summary}</span>
                      </button>
                    ))}
                  </div>
                ) : (
                  <div className="muted">This face has no detected openings to target.</div>
                )}
                {activeOpeningGroup ? (
                  <div className="project-summary">
                    <div className="status-label">Scope</div>
                    <div className="text-input-actions">
                      <button
                        type="button"
                        className={`text-submit ${!applyToSimilar ? "secondary-action" : ""}`}
                        onClick={() => setApplyToSimilar(false)}
                        disabled={isProcessing}
                      >
                        Change one opening
                      </button>
                      <button
                        type="button"
                        className={`text-submit ${applyToSimilar ? "" : "secondary-action"}`}
                        onClick={() => setApplyToSimilar(true)}
                        disabled={isProcessing || !isRepeatedGroup}
                      >
                        Change all similar openings
                      </button>
                    </div>
                    <div className="muted">
                      {applyToSimilar && isRepeatedGroup
                        ? `Preview will update ${activeOpeningGroup.count} similar openings on this face.`
                        : "Preview will update only the representative opening."}
                    </div>
                  </div>
                ) : null}
              </>
            ) : (
              <div className="muted">Import an STL to detect editable openings.</div>
            )}

            <details className="advanced-panel">
              <summary>Advanced selection</summary>
              <div className="selection-grid advanced-selection-grid">
                <label className="field-row">
                  <span>Planar face</span>
                  <select
                    value={selectedClusterId}
                    onChange={(event) => setSelectedClusterId(event.target.value)}
                    disabled={isProcessing}
                  >
                    <option value="">Choose a planar face</option>
                    {sortedClusters.map((cluster) => (
                      <option key={cluster.cluster_id} value={cluster.cluster_id}>
                        {describeCluster(cluster)}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="field-row">
                  <span>Representative opening</span>
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
            </details>
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
              <div className="selection-detail-stack">
                <div className="muted">
                  Editing {selectedOpening.opening_id} at {selectedOpening.center_mm.x}, {selectedOpening.center_mm.y} mm
                  {" · "}
                  detected as {selectedOpening.shape_guess} {selectedOpening.width_mm.toFixed(2)} × {selectedOpening.height_mm.toFixed(2)} mm
                </div>
                <div className="muted">
                  {applyToSimilar && isRepeatedGroup
                    ? `The settings below will update ${activeOpeningGroup?.count} similar openings on this face.`
                    : "The settings below will change only this opening."}
                </div>
              </div>
            ) : (
              <div className="muted">
                No opening selected. The cut will use the current center coordinates on this planar face.
              </div>
            )}
            {viewerSelectionMessage ? (
              <div className="chip chip-warm">{viewerSelectionMessage}</div>
            ) : null}
          </div>
        ) : null}

        <form
          className="field-row"
          onSubmit={(event: FormEvent<HTMLFormElement>) => {
            event.preventDefault();
            void handlePreviewEdit();
          }}
        >
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
            {usesWidthHeightFields ? (
              <>
                <label className="field-row compact-field">
                  <span>Width mm</span>
                  <input type="number" inputMode="decimal" step="any" value={widthMm} onChange={(event) => setWidthMm(event.target.value)} disabled={isProcessing} />
                </label>
                <label className="field-row compact-field">
                  <span>Height mm</span>
                  <input type="number" inputMode="decimal" step="any" value={heightMm} onChange={(event) => setHeightMm(event.target.value)} disabled={isProcessing} />
                </label>
              </>
            ) : null}
            {usesDiameterField ? (
              <label className="field-row compact-field">
                <span>Diameter mm</span>
                <input type="number" inputMode="decimal" step="any" value={diameterMm} onChange={(event) => setDiameterMm(event.target.value)} disabled={isProcessing} />
              </label>
            ) : null}
            <label className="field-row compact-field">
              <span>Depth mm</span>
              <input type="number" inputMode="decimal" step="any" value={depthMm} onChange={(event) => setDepthMm(event.target.value)} disabled={isProcessing || throughAll} />
            </label>
            {showCornerRadiusField ? (
              <label className="field-row compact-field">
                <span>Corner radius mm</span>
                <input type="number" inputMode="decimal" step="any" value={cornerRadiusMm} onChange={(event) => setCornerRadiusMm(event.target.value)} disabled={isProcessing} />
              </label>
            ) : null}
            <label className="field-row compact-field">
              <span>Through all</span>
              <select value={throughAll ? "true" : "false"} onChange={(event) => setThroughAll(event.target.value === "true")} disabled={isProcessing}>
                <option value="true">True</option>
                <option value="false">False</option>
              </select>
            </label>
          </div>

          <details className="advanced-panel">
            <summary>Advanced edit controls</summary>
            <label htmlFor="edit-prompt">Describe the change</label>
            <textarea
              id="edit-prompt"
              rows={3}
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              disabled={isProcessing}
              placeholder="Make the selected holes larger"
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
                <span>Center X mm</span>
                <input type="number" inputMode="decimal" step="any" value={centerX} onChange={(event) => setCenterX(event.target.value)} disabled={isProcessing || applyToSimilar} />
              </label>
              <label className="field-row compact-field">
                <span>Center Y mm</span>
                <input type="number" inputMode="decimal" step="any" value={centerY} onChange={(event) => setCenterY(event.target.value)} disabled={isProcessing || applyToSimilar} />
              </label>
              <label className="field-row compact-field">
                <span>Pattern</span>
                <select value={pattern} onChange={(event) => setPattern(event.target.value)} disabled={isProcessing || applyToSimilar}>
                  <option value="none">None</option>
                  <option value="linear">Linear</option>
                  <option value="circular">Circular</option>
                </select>
              </label>
              <label className="field-row compact-field">
                <span>Count</span>
                <input type="number" inputMode="numeric" min="1" step="1" value={count} onChange={(event) => setCount(event.target.value)} disabled={isProcessing || applyToSimilar} />
              </label>
              <label className="field-row compact-field">
                <span>Spacing mm</span>
                <input type="number" inputMode="decimal" step="any" value={spacingMm} onChange={(event) => setSpacingMm(event.target.value)} disabled={isProcessing || applyToSimilar} />
              </label>
              <label className="field-row compact-field">
                <span>Array radius mm</span>
                <input type="number" inputMode="decimal" step="any" value={arrayRadiusMm} onChange={(event) => setArrayRadiusMm(event.target.value)} disabled={isProcessing || applyToSimilar} />
              </label>
              <label className="field-row compact-field">
                <span>Tolerance mm</span>
                <input type="number" inputMode="decimal" step="any" value={toleranceMm} onChange={(event) => setToleranceMm(event.target.value)} disabled={isProcessing} />
              </label>
            </div>

            <label htmlFor="edit-spec">Structured edit spec</label>
            <textarea
              id="edit-spec"
              rows={6}
              value={specText}
              onChange={(event) => setSpecText(event.target.value)}
              disabled={isProcessing}
              placeholder={`operation: resize_cutout\ndiameter_mm: 8\nthrough_all: true`}
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
                Supports JSON or flat <code>key: value</code> lines.
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
          </details>

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
