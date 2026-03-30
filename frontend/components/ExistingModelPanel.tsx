"use client";

import type { ChangeEvent, FormEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { SelectionPayload, ViewerSelectionMarker } from "./ModelViewer";
import { resolveBackendUrl, resolveUrl } from "../lib/backend";
import { parseEditSpec } from "../lib/edit-spec";

type ExistingModelPanelProps = {
  onModelUrl: (url: string | null) => void;
  onSourceModelUrl: (url: string | null) => void;
  onStlUrl: (url: string | null) => void;
  onGcodeUrl: (url: string | null) => void;
  onBundleUrl: (url: string | null) => void;
  onSelectionMarker?: (marker: ViewerSelectionMarker | null) => void;
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

export default function ExistingModelPanel({
  onModelUrl,
  onSourceModelUrl,
  onStlUrl,
  onGcodeUrl,
  onBundleUrl,
  onSelectionMarker,
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
  const selectedTargetHeadline = activeFeatureGroup
    ? applyToSimilar && activeFeatureGroup.count > 1
      ? `${activeFeatureGroup.count} similar ${selectedTypeLabel}s selected`
      : `1 ${selectedTypeLabel} selected from a repeated group`
    : selectedFeature
      ? `1 ${selectedTypeLabel} selected`
      : "No feature selected yet";
  const selectedTargetDetail = selectedFeature
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
    () =>
      JSON.stringify({
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
      }),
    [
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
      widthMm,
    ]
  );
  const hasPendingPreview =
    Boolean(imported && selectedFeature) &&
    currentDraftSignature !== lastPreviewSignature;

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
    const matchedGroup = analysis.groups?.find((group) => group.id === match.groupId);
    setViewerSelectionMessage(
      matchedGroup && match.scope === "group"
        ? `Picked ${matchedGroup.count} similar ${matchedGroup.type} features from the 3D view.`
        : `Picked ${match.openingId} from the 3D view.`
    );
  }, [analysis, lastSelectionHintKey, viewerSelectionHint]);

  useEffect(() => {
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
  }, [onSelectionMarker, selectedCluster, selectedFeature, viewerSelectionLabel]);

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
      setFeatureSelection(null);
      onSelectionMarker?.(null);
      setLastPreviewSignature(null);
      setSelectedClusterId("");
      setSelectedOpeningId("");
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
    const scopedFeatureIds =
      applyToSimilar && activeFeatureGroup?.feature_ids?.length ? activeFeatureGroup.feature_ids : undefined;
    const scopedOpeningIds =
      applyToSimilar && activeFeatureGroup?.opening_ids?.length ? activeFeatureGroup.opening_ids : undefined;
    return {
      model_id: imported?.model_id,
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
    ? `${selectedCluster.area_mm2.toFixed(0)} mm² editable face · ${selectedCluster.openings.length} detected openings`
    : "Import an STL to detect editable features";

  return (
    <section className="panel">
      <div className="panel-header">
        <p className="eyebrow">Precision STL Editor</p>
        <h2>Select a target and edit it precisely</h2>
        <p className="panel-subtitle">
          Upload an STL, pick a detected feature or repeated-hole group, adjust the dimensions, preview the result, and export the revised STL.
        </p>
      </div>

      <div className="panel-body">
        <div className="status-card">
          <div className="status-label">Current stage</div>
          <div className="status-value">{humanStatus(status)}</div>
          <div className="intent muted">
            {selectedCluster
              ? `${selectedTargetHeadline}. ${selectionSummary}.`
              : "Upload an STL first, then choose a detected feature to edit."}
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
              <div className="muted">Detected editable faces and openings are ready.</div>
            )}
          </div>
        ) : null}

        {analysis ? (
          <div className="project-summary">
            <div className="status-label">Quick target</div>
            {selectedCluster ? (
              <>
                <div className="muted">
                  Editing {describeCluster(selectedCluster)}. Choose the kind of feature you want to change.
                </div>
                {selectedFeatureGroups.length ? (
                  <div className="target-group-list">
                    {selectedFeatureGroups.map((group) => (
                      <button
                        key={group.id}
                        type="button"
                        className={`target-group-card ${activeFeatureGroup?.id === group.id ? "active" : ""}`}
                        onClick={() => {
                          const representativeFeature = analysis?.features?.find(
                            (feature) => feature.id === group.representative_feature_id
                          );
                          if (!representativeFeature) return;
                          setFeatureSelection({
                            featureId: representativeFeature.id,
                            groupId: group.id,
                            scope: group.count > 1 ? "group" : "one",
                          });
                          setSelectedClusterId(group.cluster_id);
                          setSelectedOpeningId(representativeFeature.opening_id);
                        }}
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
                {activeFeatureGroup ? (
                  <div className="project-summary">
                    <div className="status-label">Scope</div>
                    <div className="text-input-actions">
                      <button
                        type="button"
                        className={`text-submit ${!applyToSimilar ? "secondary-action" : ""}`}
                        onClick={() =>
                          setFeatureSelection((current) =>
                            current ? { ...current, scope: "one" } : current
                          )
                        }
                        disabled={isProcessing}
                      >
                        Change one opening
                      </button>
                      <button
                        type="button"
                        className={`text-submit ${applyToSimilar ? "" : "secondary-action"}`}
                        onClick={() =>
                          setFeatureSelection((current) =>
                            current ? { ...current, scope: "group", groupId: activeFeatureGroup.id } : current
                          )
                        }
                        disabled={isProcessing || !isRepeatedGroup}
                      >
                        Change all similar openings
                      </button>
                    </div>
                    <div className="muted">{scopeSummary}</div>
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
            </details>
          </div>
        ) : null}

        {selectedCluster ? (
          <div className="project-summary">
            <div className="status-label">Selected target</div>
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
                  {selectedTargetHeadline}. Centered near {selectedOpening.center_mm.x}, {selectedOpening.center_mm.y} mm
                  {" · "}detected as {selectedFeature?.type || selectedOpening.shape_guess}{" "}
                  {selectedOpening.width_mm.toFixed(2)} × {selectedOpening.height_mm.toFixed(2)} mm.
                </div>
                <div className="muted">{scopeSummary}</div>
              </div>
            ) : (
              <div className="muted">
                No feature selected yet. Pick a quick target card or click a supported opening in the preview.
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
          <div className="project-summary">
            <div className="status-label">Describe change</div>
            <div className="validation-headline">{selectedTargetHeadline}</div>
            <div className="muted">{selectedTargetDetail}</div>
            {hasPendingPreview ? (
              <div className="chip chip-warm">
                Draft changed. Click Preview to update the 3D view.
              </div>
            ) : null}
            {diameterLikelyTooLarge ? (
              <div className="warning-chip">
                {`This repeated pattern will likely fail above about ${estimatedMaxDiameter} mm. ${diameterMm} mm is too large for the current spacing.`}
              </div>
            ) : null}
          </div>

          <div className="spec-grid">
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
              <span>Through all</span>
              <select value={throughAll ? "true" : "false"} onChange={(event) => setThroughAll(event.target.value === "true")} disabled={isProcessing}>
                <option value="true">True</option>
                <option value="false">False</option>
              </select>
            </label>
          </div>

          <details className="advanced-panel">
            <summary>Advanced edit controls</summary>
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
                <span>Depth mm</span>
                <input type="number" inputMode="decimal" step="any" value={depthMm} onChange={(event) => setDepthMm(event.target.value)} disabled={isProcessing || throughAll} />
              </label>
              {showCornerRadiusField ? (
                <label className="field-row compact-field">
                  <span>Corner radius mm</span>
                  <input type="number" inputMode="decimal" step="any" value={cornerRadiusMm} onChange={(event) => setCornerRadiusMm(event.target.value)} disabled={isProcessing} />
                </label>
              ) : null}
            </div>
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
              {hasPendingPreview ? "Preview changes" : "Preview"}
            </button>
            <button
              type="button"
              className="text-submit"
              onClick={handleApplyEdit}
              disabled={!imported || !selectedClusterId || isProcessing}
            >
              Export STL
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
