"use client";

import type { ChangeEvent, FormEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { SelectionPayload, ViewerCameraNormal, ViewerSelectionMarker } from "./ModelViewer";
import PlanarFaceEditor from "./PlanarFaceEditor";
import { resolveBackendUrl, resolveUrl } from "../lib/backend";
import { parseEditSpec } from "../lib/edit-spec";

type ExistingModelPanelProps = {
  onModelUrl: (url: string | null) => void;
  onSourceModelUrl: (url: string | null) => void;
  onStlUrl: (url: string | null) => void;
  onGcodeUrl: (url: string | null) => void;
  onBundleUrl: (url: string | null) => void;
  onSelectionMarker?: (marker: ViewerSelectionMarker | null) => void;
  onViewNormalChange?: (normal: ViewerCameraNormal | null) => void;
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

type FeatureSummary = {
  id: string;
  type: string;
  face_id: string;
  cluster_id: string;
  opening_id: string;
  center_mm: {
    x: number;
    y: number;
  };
  width_mm?: number;
  height_mm?: number;
  diameter_mm?: number;
  bounds_mm?: OpeningSummary["bounds_mm"];
  group_id?: string | null;
  summary: string;
};

type FeatureGroupSummary = {
  id: string;
  type: string;
  face_id: string;
  cluster_id: string;
  count: number;
  representative_feature_id: string;
  feature_ids: string[];
  opening_ids: string[];
  title: string;
  summary: string;
  avg_width_mm: number;
  avg_height_mm: number;
};

type PlanarFaceCluster = {
  cluster_id: string;
  face_id?: string;
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
  groups?: FeatureGroupSummary[];
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
  features?: FeatureSummary[];
  groups?: FeatureGroupSummary[];
  primary_target_id?: string | null;
  targets?: ExistingModelTarget[];
  unsupported_reasons?: string[];
};

type ExistingModelTarget = {
  id: string;
  type: "planar_pattern_face" | "single_planar_feature" | "unsupported";
  confidence: number;
  editable?: boolean;
  label: string;
  summary: string;
  preview_capability: "supported" | "limited" | "unsupported";
  supported_operations: string[];
  warnings: string[];
  unsupported_reason?: string | null;
  topology?: "rectangular" | "radial";
  face_id?: string;
  face_frame?: {
    origin: [number, number, number];
    x_axis: [number, number, number];
    y_axis: [number, number, number];
    normal: [number, number, number];
  };
  face_polygon_2d?: Array<[number, number]>;
  feature_geometry_2d?: Array<{
    id: string;
    center: [number, number];
    outline?: Array<[number, number]>;
  }>;
  feature_outline_2d?: Array<[number, number]>;
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
  pattern?: {
    element_type: "circular_hole" | "rectangular_cutout";
    count: number;
    spacing_x?: number;
    spacing_y?: number;
    count_x?: number;
    count_y?: number;
    radial_spacing?: number;
    ring_count?: number;
    holes_per_ring?: number[];
    margin?: number;
    center_hole_diameter?: number | null;
  };
  dimensions?: {
    hole_diameter?: number | null;
    width?: number | null;
    height?: number | null;
  };
  feature_type?: "circular_hole" | "slot" | "rectangular_cutout";
  feature_id?: string;
  feature_ids?: string[];
  fit?: {
    center_x?: number;
    center_y?: number;
    x_positions?: number[];
    y_positions?: number[];
    ring_radii?: number[];
    holes_per_ring?: number[];
  };
};

type FeatureSelection = {
  featureId: string;
  groupId: string | null;
  scope: "one" | "group";
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
  "Make the selected holes 1 mm larger",
  "Resize the selected slot but keep its center",
  "Turn this circular hole into a rounded slot",
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

const featureCenterToWorldPoint = (feature: FeatureSummary, cluster: PlanarFaceCluster) => {
  if (!cluster.local_frame) {
    return null;
  }
  const [originX, originY, originZ] = cluster.origin_mm;
  const [xAxisX, xAxisY, xAxisZ] = cluster.local_frame.x_axis;
  const [yAxisX, yAxisY, yAxisZ] = cluster.local_frame.y_axis;
  return {
    x: Number((originX + feature.center_mm.x * xAxisX + feature.center_mm.y * yAxisX).toFixed(3)),
    y: Number((originY + feature.center_mm.x * xAxisY + feature.center_mm.y * yAxisY).toFixed(3)),
    z: Number((originZ + feature.center_mm.x * xAxisZ + feature.center_mm.y * yAxisZ).toFixed(3)),
  };
};

const majorFeatureDimension = (feature: FeatureSummary) => {
  return Math.max(
    feature.width_mm || 0,
    feature.height_mm || 0,
    feature.diameter_mm || 0
  );
};

const estimateGroupMaxDiameter = (
  group: FeatureGroupSummary | null,
  features: FeatureSummary[] | undefined
) => {
  if (!group || group.type !== "circle" || !features?.length) {
    return null;
  }
  const groupFeatures = group.feature_ids
    .map((featureId) => features.find((feature) => feature.id === featureId))
    .filter((feature): feature is FeatureSummary => Boolean(feature));
  if (groupFeatures.length < 2) {
    return null;
  }

  let nearestCenterDistance = Number.POSITIVE_INFINITY;
  for (let index = 0; index < groupFeatures.length; index += 1) {
    const current = groupFeatures[index];
    for (let compareIndex = index + 1; compareIndex < groupFeatures.length; compareIndex += 1) {
      const candidate = groupFeatures[compareIndex];
      const centerDistance = Math.hypot(
        current.center_mm.x - candidate.center_mm.x,
        current.center_mm.y - candidate.center_mm.y
      );
      if (centerDistance > 0 && centerDistance < nearestCenterDistance) {
        nearestCenterDistance = centerDistance;
      }
    }
  }

  if (!Number.isFinite(nearestCenterDistance)) {
    return null;
  }

  return Number(Math.max(nearestCenterDistance - 0.6, 0).toFixed(2));
};

const resolveFeatureSelection = (
  point: SelectionPayload["point"],
  analysis: ModelAnalysis
) => {
  const features = analysis.features || [];
  const groups = analysis.groups || [];
  if (!features.length) return null;

  let bestMatch:
    | {
        feature: FeatureSummary;
        cluster: PlanarFaceCluster;
        score: number;
      }
    | null = null;

  for (const feature of features) {
    const cluster = analysis.planar_face_clusters.find(
      (candidate) => candidate.cluster_id === feature.cluster_id
    );
    if (!cluster) continue;
    const localPoint = projectPointToCluster(point, cluster);
    if (!localPoint) continue;
    const planeDistance = Math.abs(localPoint.z);
    if (planeDistance > 1.5) continue;

    const centerDistance = Math.hypot(
      localPoint.x - feature.center_mm.x,
      localPoint.y - feature.center_mm.y
    );
    const selectionThreshold = Math.max(2.5, 0.75 * Math.max(majorFeatureDimension(feature), 1));
    if (centerDistance > selectionThreshold) continue;

    const score = centerDistance + planeDistance * 8;
    if (!bestMatch || score < bestMatch.score) {
      bestMatch = { feature, cluster, score };
    }
  }

  if (!bestMatch) return null;

  const matchedGroup = bestMatch.feature.group_id
    ? groups.find((group) => group.id === bestMatch.feature.group_id)
    : null;

  return {
    featureId: bestMatch.feature.id,
    groupId: matchedGroup?.id || null,
    scope: matchedGroup && matchedGroup.count > 1 ? ("group" as const) : ("one" as const),
    clusterId: bestMatch.cluster.cluster_id,
    openingId: bestMatch.feature.opening_id,
  };
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

const defaultTargetParams = (target: ExistingModelTarget | null) => {
  if (!target) return {} as Record<string, string>;
  if (target.type === "planar_pattern_face") {
    return {
      hole_diameter: target.dimensions?.hole_diameter != null ? String(target.dimensions.hole_diameter) : "",
      width: target.dimensions?.width != null ? String(target.dimensions.width) : "",
      height: target.dimensions?.height != null ? String(target.dimensions.height) : "",
      spacing_x: target.pattern?.spacing_x != null ? String(target.pattern.spacing_x) : "",
      spacing_y: target.pattern?.spacing_y != null ? String(target.pattern.spacing_y) : "",
      count_x: target.pattern?.count_x != null ? String(target.pattern.count_x) : "",
      count_y: target.pattern?.count_y != null ? String(target.pattern.count_y) : "",
      radial_spacing: target.pattern?.radial_spacing != null ? String(target.pattern.radial_spacing) : "",
      ring_count: target.pattern?.ring_count != null ? String(target.pattern.ring_count) : "",
      margin: target.pattern?.margin != null ? String(target.pattern.margin) : "",
      center_hole_diameter:
        target.pattern?.center_hole_diameter != null ? String(target.pattern.center_hole_diameter) : "",
    };
  }
  return {
    hole_diameter: target.dimensions?.hole_diameter != null ? String(target.dimensions.hole_diameter) : "",
    width: target.dimensions?.width != null ? String(target.dimensions.width) : "",
    height: target.dimensions?.height != null ? String(target.dimensions.height) : "",
  };
};

const buildTargetParamsPayload = (target: ExistingModelTarget, params: Record<string, string>) => {
  const payload: Record<string, unknown> = {};
  const assignNumber = (key: string) => {
    const value = params[key];
    if (value === undefined || value === "") return;
    const parsed = Number(value);
    if (Number.isFinite(parsed)) payload[key] = parsed;
  };
  if (target.type === "planar_pattern_face") {
    if (target.pattern?.element_type === "circular_hole") {
      assignNumber("hole_diameter");
    } else {
      assignNumber("width");
      assignNumber("height");
    }
    if (target.topology === "rectangular") {
      assignNumber("spacing_x");
      assignNumber("spacing_y");
      assignNumber("count_x");
      assignNumber("count_y");
    } else if (target.topology === "radial") {
      assignNumber("radial_spacing");
      assignNumber("ring_count");
    }
    assignNumber("margin");
    assignNumber("center_hole_diameter");
  } else {
    if ((target.feature_kind || target.feature_type) === "circular_hole") {
      assignNumber("hole_diameter");
    } else {
      assignNumber("width");
      assignNumber("height");
    }
  }
  return payload;
};

export default function ExistingModelPanel({
  onModelUrl,
  onSourceModelUrl,
  onStlUrl,
  onGcodeUrl,
  onBundleUrl,
  onSelectionMarker,
  onViewNormalChange,
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
  const [editorState, setEditorState] = useState<
    "idle" | "analyzed" | "target_selected" | "dirty" | "preview_loading" | "preview_ready" | "preview_failed"
  >("idle");
  const [selectedTargetId, setSelectedTargetId] = useState("");
  const [targetParams, setTargetParams] = useState<Record<string, string>>({});
  const [featureSelection, setFeatureSelection] = useState<FeatureSelection | null>(null);
  const [selectedClusterId, setSelectedClusterId] = useState("");
  const [selectedOpeningId, setSelectedOpeningId] = useState("");
  const [prompt, setPrompt] = useState(editPromptExamples[0]);
  const [operation, setOperation] = useState("resize_cutout");
  const [targetShape, setTargetShape] = useState("circle");
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
  const [lastPreviewSignature, setLastPreviewSignature] = useState<string | null>(null);
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

  const selectedFeature = useMemo(() => {
    if (!featureSelection?.featureId) return null;
    return analysis?.features?.find((feature) => feature.id === featureSelection.featureId) || null;
  }, [analysis, featureSelection?.featureId]);

  const selectedCluster = useMemo(() => {
    const targetClusterId = selectedFeature?.cluster_id || selectedClusterId;
    return analysis?.planar_face_clusters.find((cluster) => cluster.cluster_id === targetClusterId) || null;
  }, [analysis, selectedClusterId, selectedFeature?.cluster_id]);

  const selectedOpening = useMemo(() => {
    const targetOpeningId = selectedFeature?.opening_id || selectedOpeningId;
    return selectedCluster?.openings.find((opening) => opening.opening_id === targetOpeningId) || null;
  }, [selectedCluster, selectedFeature?.opening_id, selectedOpeningId]);

  const selectedFeatureGroups = useMemo(() => {
    if (!selectedCluster) return [];
    return (
      analysis?.groups?.filter((group) => group.cluster_id === selectedCluster.cluster_id) ||
      selectedCluster.groups ||
      []
    );
  }, [analysis?.groups, selectedCluster]);

  const supportedTargets = useMemo(
    () => (analysis?.targets || []).filter((target) => target.type !== "unsupported"),
    [analysis?.targets]
  );

  const activeTarget = useMemo(
    () => supportedTargets.find((target) => target.id === selectedTargetId) || null,
    [selectedTargetId, supportedTargets]
  );

  const activeFeatureGroup = useMemo(() => {
    if (!selectedFeature) return null;
    const explicitGroup = featureSelection?.groupId
      ? selectedFeatureGroups.find((group) => group.id === featureSelection.groupId)
      : null;
    if (explicitGroup) return explicitGroup;
    if (selectedFeature.group_id) {
      return selectedFeatureGroups.find((group) => group.id === selectedFeature.group_id) || null;
    }
    return null;
  }, [featureSelection?.groupId, selectedFeature, selectedFeatureGroups]);

  const sortedClusters = useMemo(() => {
    return [...(analysis?.planar_face_clusters || [])].sort((left, right) => clusterSortScore(right) - clusterSortScore(left));
  }, [analysis]);

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

  const isRepeatedGroup = Boolean(activeFeatureGroup && activeFeatureGroup.count > 1);
  const applyToSimilar = featureSelection?.scope === "group";
  const usesDiameterField = inferredTargetShape === "circle";
  const usesWidthHeightFields = inferredTargetShape !== "circle";
  const showCornerRadiusField =
    inferredTargetShape === "rectangle" &&
    (operation === "replace_cutout_shape" ||
      operation === "replace_hole_with_rectangle" ||
      operation === "replace_slot_with_rectangle");

  const selectedTypeLabel =
    selectedFeature?.type === "circle"
      ? "circular hole"
      : selectedFeature?.type === "slot"
        ? "rounded slot"
        : selectedFeature?.type === "rectangle"
          ? "rectangular cutout"
          : "feature";
  const legacySelectedTargetHeadline = activeFeatureGroup
    ? applyToSimilar && activeFeatureGroup.count > 1
      ? `${activeFeatureGroup.count} similar ${selectedTypeLabel}s selected`
      : `1 ${selectedTypeLabel} selected from a repeated group`
    : selectedFeature
      ? `1 ${selectedTypeLabel} selected`
      : "No feature selected yet";
  const legacySelectedTargetDetail = selectedFeature
    ? usesDiameterField
      ? `Current diameter ${Number(diameterMm || 0).toFixed(2)} mm on ${selectedCluster?.face_id || selectedCluster?.cluster_id || "the active face"}.`
      : `Current size ${Number(widthMm || 0).toFixed(2)} × ${Number(heightMm || 0).toFixed(2)} mm on ${selectedCluster?.face_id || selectedCluster?.cluster_id || "the active face"}.`
    : "Choose a quick target card or click a visible opening in the preview.";
  const scopeSummary = applyToSimilar && activeFeatureGroup?.count
    ? `Preview will update ${activeFeatureGroup.count} similar openings on this face.`
    : "Preview will update only the selected feature.";
  const viewerSelectionLabel = applyToSimilar && activeFeatureGroup?.count
    ? `${activeFeatureGroup.count} similar ${selectedTypeLabel}s`
    : selectedFeature
      ? `1 ${selectedTypeLabel}`
      : "";
  const estimatedMaxDiameter = useMemo(
    () => estimateGroupMaxDiameter(activeFeatureGroup, analysis?.features),
    [activeFeatureGroup, analysis?.features]
  );
  const requestedDiameterValue = Number(diameterMm);
  const diameterLikelyTooLarge =
    usesDiameterField &&
    applyToSimilar &&
    estimatedMaxDiameter !== null &&
    Number.isFinite(requestedDiameterValue) &&
    requestedDiameterValue > estimatedMaxDiameter;
  const currentDraftSignature = useMemo(
    () => {
      if (activeTarget) {
        return JSON.stringify({
          targetId: activeTarget.id,
          params: buildTargetParamsPayload(activeTarget, targetParams),
        });
      }
      return JSON.stringify({
        selection: {
          featureId: selectedFeature?.id || null,
          groupId: applyToSimilar ? activeFeatureGroup?.id || null : null,
          scope: applyToSimilar ? "group" : "one",
        },
        edit: {
          operation,
          targetShape,
          widthMm,
          heightMm,
          diameterMm,
          depthMm,
          cornerRadiusMm,
          throughAll,
          pattern,
          count,
          spacingMm,
          arrayRadiusMm,
          toleranceMm,
          centerX,
          centerY,
        },
      });
    },
    [
      activeTarget,
      activeFeatureGroup?.id,
      applyToSimilar,
      arrayRadiusMm,
      centerX,
      centerY,
      cornerRadiusMm,
      count,
      depthMm,
      diameterMm,
      heightMm,
      operation,
      pattern,
      selectedFeature?.id,
      spacingMm,
      targetShape,
      throughAll,
      toleranceMm,
      targetParams,
      widthMm,
    ]
  );
  const hasPendingPreview =
    Boolean(imported && selectedFeature) &&
    currentDraftSignature !== lastPreviewSignature;

  const selectedTargetHeadline = activeTarget
    ? activeTarget.label
    : supportedTargets.length
      ? "Pick a detected target"
      : "No supported target detected yet";
  const selectedTargetDetail = activeTarget
    ? activeTarget.summary
    : analysis?.unsupported_reasons?.[0] || "Import an STL to detect supported editable targets.";
  const targetCountSummary =
    activeTarget?.type === "planar_pattern_face" && activeTarget.pattern
      ? `${activeTarget.pattern.count} repeated openings detected`
      : activeTarget?.type === "single_planar_feature"
        ? "Single editable feature"
        : null;
  const targetDirty =
    Boolean(activeTarget) &&
    JSON.stringify(defaultTargetParams(activeTarget)) !== JSON.stringify(targetParams) &&
    editorState !== "preview_loading";

  useEffect(() => {
    if (!sortedClusters.length) return;
    if (!selectedClusterId || !sortedClusters.some((cluster) => cluster.cluster_id === selectedClusterId)) {
      setSelectedClusterId(sortedClusters[0].cluster_id);
    }
  }, [selectedClusterId, sortedClusters]);

  useEffect(() => {
    if (!analysis) return;
    const availableIds = new Set(supportedTargets.filter((target) => target.editable).map((target) => target.id));
    if (selectedTargetId && availableIds.has(selectedTargetId)) {
      return;
    }
    const nextTargetId =
      (analysis.primary_target_id && availableIds.has(analysis.primary_target_id)
        ? analysis.primary_target_id
        : supportedTargets.find((target) => target.editable)?.id) || "";
    if (nextTargetId) {
      setSelectedTargetId(nextTargetId);
      setEditorState("target_selected");
    }
  }, [analysis, selectedTargetId, supportedTargets]);

  useEffect(() => {
    if (!activeTarget) return;
    setTargetParams(defaultTargetParams(activeTarget));
    setEditorState("target_selected");

    if (activeTarget.face_id && analysis) {
      const cluster = analysis.planar_face_clusters.find((candidate) => candidate.face_id === activeTarget.face_id);
      if (cluster) {
        setSelectedClusterId(cluster.cluster_id);
      }
    }
    if (activeTarget.feature_id && analysis?.features) {
      const feature = analysis.features.find((candidate) => candidate.id === activeTarget.feature_id);
      if (feature) {
        setSelectedOpeningId(feature.opening_id);
        setFeatureSelection({
          featureId: feature.id,
          groupId: feature.group_id || null,
          scope: "one",
        });
      }
    }
  }, [activeTarget?.id]);

  useEffect(() => {
    if (!selectedCluster) return;
    if (!selectedCluster.openings.length) {
      setSelectedOpeningId("");
      setFeatureSelection(null);
      onSelectionMarker?.(null);
      return;
    }
    const currentFeatureBelongsToCluster =
      selectedFeature?.cluster_id === selectedCluster.cluster_id &&
      selectedCluster.openings.some((opening) => opening.opening_id === selectedFeature.opening_id);
    if (!currentFeatureBelongsToCluster) {
      const preferredGroup = selectedFeatureGroups[0];
      if (preferredGroup) {
        const representativeFeature = analysis?.features?.find(
          (feature) => feature.id === preferredGroup.representative_feature_id
        );
        if (representativeFeature) {
          setFeatureSelection({
            featureId: representativeFeature.id,
            groupId: preferredGroup.id,
            scope: preferredGroup.count > 1 ? "group" : "one",
          });
          setSelectedOpeningId(representativeFeature.opening_id);
          return;
        }
      }
      const fallbackOpening = selectedCluster.openings[0];
      const fallbackFeature = analysis?.features?.find(
        (feature) =>
          feature.cluster_id === selectedCluster.cluster_id &&
          feature.opening_id === fallbackOpening.opening_id
      );
      if (fallbackFeature) {
        setFeatureSelection({
          featureId: fallbackFeature.id,
          groupId: fallbackFeature.group_id || null,
          scope: fallbackFeature.group_id ? "group" : "one",
        });
      }
      setSelectedOpeningId(fallbackOpening.opening_id);
    }
  }, [analysis?.features, onSelectionMarker, selectedCluster, selectedFeature, selectedFeatureGroups]);

  useEffect(() => {
    if (!selectedFeature) return;
    const selectionKey = `${selectedFeature.cluster_id}:${selectedFeature.id}:${featureSelection?.scope || "one"}`;
    if (lastHydratedSelectionKey.current === selectionKey) {
      return;
    }
    lastHydratedSelectionKey.current = selectionKey;
    setSelectedClusterId(selectedFeature.cluster_id);
    setSelectedOpeningId(selectedFeature.opening_id);
    setCenterX(String(selectedFeature.center_mm.x));
    setCenterY(String(selectedFeature.center_mm.y));
    setWidthMm(String(selectedFeature.width_mm ?? selectedOpening?.width_mm ?? 0));
    setHeightMm(String(selectedFeature.height_mm ?? selectedOpening?.height_mm ?? 0));
    setDiameterMm(
      String(
        selectedFeature.diameter_mm ??
          Math.min(selectedFeature.width_mm ?? 0, selectedFeature.height_mm ?? 0)
      )
    );
    if (selectedFeature.type === "circle") {
      setOperation("resize_cutout");
      setTargetShape("circle");
    } else if (selectedFeature.type === "slot") {
      setOperation("resize_cutout");
      setTargetShape("rounded_slot");
    } else {
      setOperation("resize_cutout");
      setTargetShape("rectangle");
    }
  }, [featureSelection?.scope, selectedFeature, selectedOpening]);

  useEffect(() => {
    if (!viewerSelectionHint || !analysis?.planar_face_clusters?.length) return;
    const hintKey = [
      viewerSelectionHint.point.x,
      viewerSelectionHint.point.y,
      viewerSelectionHint.point.z,
    ].join(":");
    if (hintKey === lastSelectionHintKey) return;
    setLastSelectionHintKey(hintKey);

    const match = resolveFeatureSelection(viewerSelectionHint.point, analysis);

    if (!match) {
      setViewerSelectionMessage("Clicked area did not map cleanly to a supported editable feature.");
      return;
    }

    setFeatureSelection({
      featureId: match.featureId,
      groupId: match.groupId,
      scope: match.scope,
    });
    setSelectedClusterId(match.clusterId);
    setSelectedOpeningId(match.openingId);
    const matchedTarget =
      analysis.targets?.find((target) => target.feature_id === match.featureId) ||
      analysis.targets?.find((target) => target.feature_ids?.includes(match.featureId));
    if (matchedTarget) {
      if (matchedTarget.editable) {
        setSelectedTargetId(matchedTarget.id);
        setEditorState("target_selected");
      } else {
        setViewerSelectionMessage(
          matchedTarget.confidence < 0.7
            ? "That detected region is too low-confidence for safe editing."
            : "That detected region is visible, but not safe enough to edit."
        );
        return;
      }
    }
    const matchedGroup = analysis.groups?.find((group) => group.id === match.groupId);
    setViewerSelectionMessage(
      matchedTarget
        ? `Picked ${matchedTarget.label.toLowerCase()} from the 3D view.`
        : matchedGroup && match.scope === "group"
          ? `Picked ${matchedGroup.count} similar ${matchedGroup.type} features from the 3D view.`
          : `Picked ${match.openingId} from the 3D view.`
    );
  }, [analysis, lastSelectionHintKey, viewerSelectionHint]);

  useEffect(() => {
    if (!activeTarget?.face_frame?.normal) {
      onViewNormalChange?.(null);
      return;
    }
    const [x, y, z] = activeTarget.face_frame.normal;
    onViewNormalChange?.({ x, y, z });
  }, [activeTarget?.face_frame?.normal, onViewNormalChange]);

  useEffect(() => {
    if (activeTarget?.type === "planar_pattern_face" && activeTarget.feature_ids?.length && analysis?.features?.length) {
      const cluster = analysis.planar_face_clusters.find((candidate) => candidate.face_id === activeTarget.face_id);
      const targetFeatures = activeTarget.feature_ids
        .map((featureId) => analysis.features?.find((feature) => feature.id === featureId))
        .filter((feature): feature is FeatureSummary => Boolean(feature));
      if (cluster && targetFeatures.length) {
        const representative = targetFeatures[Math.floor(targetFeatures.length / 2)];
        const worldPoint = featureCenterToWorldPoint(representative, cluster);
        if (worldPoint) {
          onSelectionMarker?.({
            point: worldPoint,
            label: `${activeTarget.label}${targetCountSummary ? ` · ${targetCountSummary}` : ""}`,
          });
          return;
        }
      }
    }

    if (activeTarget?.type === "single_planar_feature" && activeTarget.feature_id && analysis?.features?.length) {
      const feature = analysis.features.find((candidate) => candidate.id === activeTarget.feature_id);
      const cluster = analysis.planar_face_clusters.find((candidate) => candidate.face_id === activeTarget.face_id || candidate.cluster_id === feature?.cluster_id);
      if (feature && cluster) {
        const worldPoint = featureCenterToWorldPoint(feature, cluster);
        if (worldPoint) {
          onSelectionMarker?.({
            point: worldPoint,
            label: activeTarget.label,
          });
          return;
        }
      }
    }

    if (!selectedFeature || !selectedCluster) {
      onSelectionMarker?.(null);
      return;
    }
    const worldPoint = featureCenterToWorldPoint(selectedFeature, selectedCluster);
    if (!worldPoint) {
      onSelectionMarker?.(null);
      return;
    }
    onSelectionMarker?.({
      point: worldPoint,
      label: viewerSelectionLabel,
    });
  }, [activeTarget, analysis?.features, analysis?.planar_face_clusters, onSelectionMarker, selectedCluster, selectedFeature, targetCountSummary, viewerSelectionLabel]);

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
      setEditorState("analyzed");
      setSelectedTargetId(data.analysis.primary_target_id || "");
      setTargetParams({});
      setFeatureSelection(null);
      onSelectionMarker?.(null);
      setLastPreviewSignature(null);
      setSelectedClusterId("");
      setSelectedOpeningId("");
      lastHydratedSelectionKey.current = null;
      setPreviewJobId(null);
      onSourceModelUrl(resolveUrl(backendUrl, data.source_glb_url));
      onModelUrl(resolveUrl(backendUrl, data.source_glb_url));
      onStlUrl(null);
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
      setEditorState("analyzed");
    } catch (error) {
      console.error(error);
      setStatus("error");
      setLastError((error as Error).message || "Something went wrong.");
    } finally {
      setIsProcessing(false);
    }
  };

  const buildEditPayload = () => {
    const scopedFeatureIds =
      applyToSimilar && activeFeatureGroup?.feature_ids?.length ? activeFeatureGroup.feature_ids : undefined;
    const scopedOpeningIds =
      applyToSimilar && activeFeatureGroup?.opening_ids?.length ? activeFeatureGroup.opening_ids : undefined;
    return {
      model_id: imported?.model_id,
      parent_revision_id: previewJobId,
      preview_revision_id: previewJobId,
      selection: {
        planar_face_id: selectedFeature?.cluster_id || selectedClusterId,
        face_id: selectedCluster?.face_id || selectedFeature?.face_id || null,
        opening_id: selectedFeature?.opening_id || selectedOpeningId || null,
        feature_id: selectedFeature?.id || null,
        group_id: applyToSimilar ? activeFeatureGroup?.id || selectedFeature?.group_id || null : null,
        scope: applyToSimilar ? "group" : "one",
        feature_ids: scopedFeatureIds,
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

  const buildTargetPreviewPayload = () => {
    if (!activeTarget) return null;
    return {
      model_id: imported?.model_id,
      parent_revision_id: previewJobId,
      preview_revision_id: previewJobId,
      target_id: activeTarget.id,
      params: buildTargetParamsPayload(activeTarget, targetParams),
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
    if (!imported || (!selectedClusterId && !activeTarget) || isProcessing) return;
    setIsProcessing(true);
    setLastError(null);
    resetOutputs();
    try {
      setStatus("previewing");
      setEditorState("preview_loading");
      const response = await fetchWithTimeout(
        `${backendUrl}/preview-edit`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(activeTarget ? buildTargetPreviewPayload() : buildEditPayload()),
        },
        TIMEOUTS.preview
      );
      if (!response.ok) {
        const detail = await response
          .json()
          .then((payload) => payload.detail as string | undefined)
          .catch(() => undefined);
        throw new Error(detail || "Could not preview the selected edit");
      }
      const data = (await response.json()) as PreviewEditResponse;
      setPreviewJobId(data.preview_id);
      setAnalysis(data.analysis);
      setLastPreviewSignature(currentDraftSignature);
      setValidation(data.validation);
      onModelUrl(resolveUrl(backendUrl, data.glb_url));
      onStlUrl(resolveUrl(backendUrl, data.stl_url));
      onBundleUrl(null);
      setStatus("ready");
      setEditorState("preview_ready");
      void refreshProjects();
    } catch (error) {
      console.error(error);
      setStatus("error");
      setEditorState("preview_failed");
      setLastError((error as Error).message || "Something went wrong.");
    } finally {
      setIsProcessing(false);
    }
  };

  const handleApplyEdit = async () => {
    if (!imported || (!selectedClusterId && !activeTarget) || isProcessing || !previewJobId) return;
    setIsProcessing(true);
    setLastError(null);
    try {
      setStatus("applying");
      const payload = activeTarget
        ? {
            ...buildTargetPreviewPayload(),
            preview_id: previewJobId,
            preview_revision_id: previewJobId,
          }
        : {
            ...buildEditPayload(),
            preview_id: previewJobId,
            preview_revision_id: previewJobId,
          };
      const response = await fetchWithTimeout(
        `${backendUrl}/apply-edit`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        },
        TIMEOUTS.apply
      );
      if (!response.ok) {
        const detail = await response
          .json()
          .then((payload) => payload.detail as string | undefined)
          .catch(() => undefined);
        throw new Error(detail || "Could not export the edited STL");
      }
      const data = (await response.json()) as ApplyEditResponse;
      setAnalysis(data.analysis);
      setLastPreviewSignature(currentDraftSignature);
      setValidation(data.validation);
      onModelUrl(resolveUrl(backendUrl, data.glb_url));
      onStlUrl(resolveUrl(backendUrl, data.stl_url));
      onGcodeUrl(resolveUrl(backendUrl, data.gcode_url));
      onBundleUrl(resolveUrl(backendUrl, data.bundle_url));
      setStatus("ready");
      setEditorState("preview_ready");
      void refreshProjects();
    } catch (error) {
      console.error(error);
      setStatus("error");
      setEditorState("preview_failed");
      setLastError((error as Error).message || "Something went wrong.");
    } finally {
      setIsProcessing(false);
    }
  };

  const selectionSummary = selectedCluster
    ? `${selectedCluster.area_mm2.toFixed(0)} mm² editable face · ${selectedCluster.openings.length} detected openings`
    : activeTarget?.type === "planar_pattern_face" && activeTarget.pattern
      ? `${activeTarget.pattern.count} detected openings in the selected pattern`
      : "Import an STL to detect editable features";

  const updateTargetParam = (key: string, value: string) => {
    setTargetParams((current) => ({ ...current, [key]: value }));
    setEditorState("dirty");
  };

  const resetTargetParam = (key: string) => {
    if (!activeTarget) return;
    const defaults = defaultTargetParams(activeTarget);
    setTargetParams((current) => ({ ...current, [key]: defaults[key] ?? "" }));
    setEditorState("dirty");
  };

  const resetTargetDraft = () => {
    if (!activeTarget) return;
    setTargetParams(defaultTargetParams(activeTarget));
    setLastError(null);
    setEditorState("target_selected");
  };

  return (
    <section className="panel">
      <div className="panel-header">
        <p className="eyebrow">Supported STL Face Editing</p>
        <h2>Select in 3D. Edit precisely in 2D.</h2>
        <p className="panel-subtitle">
          Import an STL, detect supported planar targets, choose one from the viewer or target list, edit it in a flattened face view, preview it, and export the exact preview revision.
        </p>
      </div>

      <div className="panel-body">
        <div className="status-card">
          <div className="status-label">Current stage</div>
          <div className="status-value">{editorState.replace(/_/g, " ")}</div>
          <div className="intent muted">
            {activeTarget
              ? `${selectedTargetHeadline}. ${selectionSummary}.`
              : analysis
                ? "Choose one of the detected targets to begin editing."
                : "Upload an STL first, then choose a detected target to edit."}
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
              <div className="muted">Detected planar targets are ready for review.</div>
            )}
          </div>
        ) : null}

        {analysis ? (
          <div className="project-summary">
            <div className="status-label">Detected targets</div>
            {supportedTargets.length ? (
              <div className="target-group-list">
                {supportedTargets.map((target) => (
                  <button
                    key={target.id}
                    type="button"
                    className={`target-group-card ${activeTarget?.id === target.id ? "active" : ""} ${target.editable ? "" : "disabled-card"}`}
                    onClick={() => {
                      if (!target.editable) return;
                      setSelectedTargetId(target.id);
                      setEditorState("target_selected");
                    }}
                    disabled={isProcessing || !target.editable}
                  >
                    <strong>{target.label}</strong>
                    <span>{target.summary}</span>
                    <span className="muted">
                      Confidence {Math.round(target.confidence * 100)}% ·{" "}
                      {target.confidence < 0.7
                        ? "view only"
                        : target.confidence < 0.85
                          ? "editable with warning"
                          : "primary candidate"}
                    </span>
                  </button>
                ))}
              </div>
            ) : (
              <div className="warning-list">
                {(analysis.unsupported_reasons?.length
                  ? analysis.unsupported_reasons
                  : ["No supported semantic target detected on this STL."]).map((reason) => (
                  <span key={reason} className="warning-chip">
                    {reason}
                  </span>
                ))}
              </div>
            )}
            {!supportedTargets.length ? (
              <div className="unsupported-guide">
                <span>Try Design Workspace instead for a fresh parametric version.</span>
                <span>Simplify the geometry or isolate a flatter region.</span>
                <span>Use Advanced / Legacy only if you need the old low-level flow.</span>
              </div>
            ) : null}
          </div>
        ) : null}

        {activeTarget ? (
          <div className="project-summary">
            <div className="status-label">Selected target</div>
            <div className="analysis-grid">
              <span>{activeTarget.label}</span>
              <span>
                {activeTarget.type === "planar_pattern_face"
                  ? `${activeTarget.topology} pattern`
                  : activeTarget.feature_kind || activeTarget.feature_type}
              </span>
              {targetCountSummary ? <span>{targetCountSummary}</span> : null}
            </div>
            <div className="muted">{selectedTargetDetail}</div>
            <div className="warning-list">
              <span className="chip">3D selects</span>
              <span className="chip">2D edits</span>
              {!activeTarget.editable ? <span className="warning-chip">Not editable</span> : null}
            </div>
            {activeTarget.warnings?.length ? (
              <div className="warning-list">
                {activeTarget.warnings.map((warning) => (
                  <span key={warning} className="warning-chip">
                    {warning}
                  </span>
                ))}
              </div>
            ) : null}
            {viewerSelectionMessage ? (
              <div className="chip chip-warm">{viewerSelectionMessage}</div>
            ) : null}
          </div>
        ) : null}

        {activeTarget ? (
          <form
            className="field-row"
            onSubmit={(event: FormEvent<HTMLFormElement>) => {
              event.preventDefault();
              void handlePreviewEdit();
            }}
          >
            <div className="project-summary">
              <div className="status-label">Preview state</div>
              <div className="validation-headline">{selectedTargetHeadline}</div>
              <div className="muted">{selectedTargetDetail}</div>
              <div className="warning-list">
                <span className="chip">{editorState.replace(/_/g, " ")}</span>
                {targetCountSummary ? <span className="chip">{targetCountSummary}</span> : null}
                {targetDirty ? <span className="chip chip-warm">Draft changed</span> : null}
                {previewJobId ? <span className="chip">Preview locked</span> : null}
              </div>
              {lastError ? <div className="warning-chip">{lastError}</div> : null}
            </div>
            <PlanarFaceEditor
              target={activeTarget as never}
              params={targetParams}
              onParamChange={updateTargetParam}
              onParamReset={resetTargetParam}
              disabled={isProcessing || !activeTarget.editable}
            />

            <div className="text-input-actions">
              <button
                type="button"
                className="text-submit secondary-action"
                onClick={resetTargetDraft}
                disabled={!activeTarget || isProcessing}
              >
                Reset draft
              </button>
              <button
                type="submit"
                className="text-submit"
                disabled={!imported || !activeTarget || isProcessing || !activeTarget.editable}
              >
                Preview
              </button>
              <button
                type="button"
                className="text-submit"
                onClick={handleApplyEdit}
                disabled={!imported || !activeTarget || isProcessing || editorState !== "preview_ready" || !previewJobId}
              >
                Export STL
              </button>
            </div>
          </form>
        ) : null}

        <details className="advanced-panel">
          <summary>Advanced / Legacy</summary>
          {analysis ? (
            <div className="project-summary">
              <div className="status-label">Advanced selection</div>
              <div className="selection-grid advanced-selection-grid">
                <label className="field-row">
                  <span>Editable face</span>
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
                  <span>Representative feature</span>
                  <select
                    value={selectedOpeningId}
                    onChange={(event) => {
                      setSelectedOpeningId(event.target.value);
                      const representativeFeature = analysis?.features?.find(
                        (feature) =>
                          feature.cluster_id === selectedCluster?.cluster_id &&
                          feature.opening_id === event.target.value
                      );
                      if (!representativeFeature) return;
                      setFeatureSelection({
                        featureId: representativeFeature.id,
                        groupId: representativeFeature.group_id || null,
                        scope: representativeFeature.group_id ? "group" : "one",
                      });
                    }}
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
            </div>
          ) : null}
        </details>

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
