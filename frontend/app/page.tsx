"use client";

import { useEffect, useMemo, useRef, useState, type RefObject } from "react";
import Link from "next/link";

import BodyTreeInspector from "../components/BodyTreeInspector";
import CanvasTabBar, { type CanvasTab } from "../components/CanvasTabBar";
import ChatPanel from "../components/Chat/ChatPanel";
import EditabilityBadge from "../components/EditabilityBadge";
import ExistingModelPanel, {
  type WorkspaceImportContext,
} from "../components/ExistingModelPanel";
import ModelViewer, {
  type SelectionPayload,
  type ViewerFocusTarget,
} from "../components/ModelViewer";
import PerforatedDiscDesigner from "../components/PerforatedDiscDesigner";
import PlanarFaceEditor from "../components/PlanarFaceEditor";
import SelectionChip from "../components/SelectionChip";
import SemanticAnnotations from "../components/SemanticAnnotations";
import VoicePanel from "../components/VoicePanel";
import { resolveBackendUrl, resolveUrl } from "../lib/backend";
import {
  classifyPerforatedDiscClick,
  DISC_PICK_CONFIDENCE,
  getPerforatedDiscAnnotations,
  getPerforatedDiscFocusTarget,
  type SemanticAnnotation,
} from "../lib/perforated-disc-geometry";
import {
  formatParamDisplayValue,
  getEditableParamEntries,
} from "../lib/param-editor-utils";
import { useEditableWorkspace } from "../lib/use-editable-workspace";
import type {
  BodyNode,
  EditableModel,
  WorkspacePresentationMode,
} from "../types/editable-model";

const STORAGE_KEY = "3dprint:workspace-shell";
const HISTORY_LIMIT = 40;

type StoredWorkspaceShell = {
  workspaceId?: string;
  context?: Pick<
    WorkspaceImportContext,
    "mode" | "sourceModelUrl" | "sourceStlUrl" | "message"
  > | null;
};

type HistoryEntry = {
  model: EditableModel;
  selectedFeatureId: string | null;
};

type MutationPayload = {
  body_updates?: Array<{
    body_id: string;
    params: Record<string, number | string | boolean>;
  }>;
  selection?: {
    feature_id: string;
    scope: "one" | "all_similar" | "body";
  } | null;
};

const flattenBodies = (bodies: BodyNode[]): BodyNode[] =>
  bodies.flatMap((body) => [body, ...flattenBodies(body.children)]);

const findBodyById = (bodies: BodyNode[], bodyId: string | null) =>
  bodyId ? flattenBodies(bodies).find((body) => body.id === bodyId) ?? null : null;

const firstEditableFeatureId = (model: EditableModel | null) =>
  model ? flattenBodies(model.bodies).find((body) => body.editable)?.id ?? null : null;

const coerceParamValue = (
  current: number | string | boolean | undefined,
  nextRaw: string
) => {
  if (typeof current === "boolean") {
    return nextRaw === "true";
  }
  if (typeof current === "number") {
    const parsed = Number(nextRaw);
    return Number.isFinite(parsed) ? parsed : 0;
  }
  return nextRaw;
};

const inferPresentationMode = (
  model: EditableModel | null
): WorkspacePresentationMode => {
  if (!model) return "native";
  if (model.source === "step_import") return "step_reference";
  if (model.source === "stl_reconstructed") return "stl_reconstruction";
  return "native";
};

const isEditablePresentation = (mode: WorkspacePresentationMode | null) =>
  mode === "native" || mode === "step_editable" || mode === "stl_reconstruction";

const isPerforatedDiscModel = (model: EditableModel | null) =>
  Boolean(model?.bodies[0]?.params?._template_id === "perforated_disc");

const toAbsolute = (backendUrl: string, value?: string | null) =>
  resolveUrl(backendUrl, value);

const cloneEditableModel = (model: EditableModel): EditableModel =>
  JSON.parse(JSON.stringify(model)) as EditableModel;

const pushHistoryEntry = (history: HistoryEntry[], entry: HistoryEntry) => {
  const next = [...history, entry];
  return next.slice(Math.max(0, next.length - HISTORY_LIMIT));
};

const buildHistoryMutation = (
  currentModel: EditableModel,
  targetModel: EditableModel,
  targetSelectedFeatureId: string | null
): MutationPayload | null => {
  const currentBodies = flattenBodies(currentModel.bodies);
  const targetBodies = flattenBodies(targetModel.bodies);
  if (currentBodies.length !== targetBodies.length) return null;

  const currentMap = new Map(currentBodies.map((body) => [body.id, body]));
  const updates = targetBodies.flatMap((targetBody) => {
    const currentBody = currentMap.get(targetBody.id);
    if (!currentBody) {
      return [];
    }
    return JSON.stringify(currentBody.params) === JSON.stringify(targetBody.params)
      ? []
      : [{ body_id: targetBody.id, params: targetBody.params }];
  });

  const currentSelection = currentModel.selection?.feature_id ?? null;
  const selection =
    targetSelectedFeatureId && findBodyById(targetModel.bodies, targetSelectedFeatureId)
      ? { feature_id: targetSelectedFeatureId, scope: "one" as const }
      : null;

  if (!updates.length && currentSelection === (selection?.feature_id ?? null)) {
    return null;
  }

  return {
    body_updates: updates,
    selection,
  };
};

const getDefaultCanvasTab = ({
  workflowMode,
  workspaceMode,
  editableModel,
  compareEnabled,
  selectedFeatureId,
  importContext,
}: {
  workflowMode: "workspace" | "creative";
  workspaceMode: WorkspacePresentationMode;
  editableModel: EditableModel | null;
  compareEnabled: boolean;
  selectedFeatureId: string | null;
  importContext: WorkspaceImportContext | null;
}): CanvasTab => {
  if (workflowMode === "creative") return "3d";
  if (workspaceMode === "native" && isPerforatedDiscModel(editableModel)) return "2d";
  if (
    workspaceMode === "stl_reconstruction" &&
    selectedFeatureId &&
    importContext?.analysis?.targets?.some(
      (target) => target.id === selectedFeatureId && target.type !== "unsupported" && Boolean(target.editable)
    )
  ) {
    return "2d";
  }
  if (compareEnabled) return "3d";
  return "3d";
};

const selectionChipValue = (body: BodyNode | null) => {
  if (!body) return null;
  const [entry] = getEditableParamEntries(body, 1);
  if (!entry) return null;
  return formatParamDisplayValue(entry.key, entry.value);
};

const hasEditablePlanarTarget = (
  context: WorkspaceImportContext | null,
  featureId: string
) =>
  Boolean(
    context?.analysis?.targets?.some(
      (target) =>
        target.id === featureId &&
        target.type !== "unsupported" &&
        Boolean(target.editable)
    )
  );

function WorkspaceInspectorPanel({
  editableModel,
  presentationMode,
  importContext,
  isBusy,
  workspaceId,
  selectedFeatureId,
  referenceImageUrl,
  onSelectFeature,
  onBodyParamChange,
  onAiEdit: _onAiEdit,
  inspectorRef,
}: {
  editableModel: EditableModel | null;
  presentationMode: WorkspacePresentationMode | null;
  importContext: WorkspaceImportContext | null;
  isBusy: boolean;
  workspaceId: string | null;
  selectedFeatureId: string | null;
  referenceImageUrl: string | null;
  onSelectFeature: (featureId: string, source?: "tree" | "designer" | "planar" | "viewer") => void;
  onBodyParamChange: (featureId: string, key: string, value: string) => void;
  onAiEdit: (featureId: string, prompt: string) => Promise<void>;
  inspectorRef: RefObject<HTMLDivElement | null>;
}) {
  const selectedBody = editableModel
    ? findBodyById(editableModel.bodies, selectedFeatureId)
    : null;
  const isEditable = isEditablePresentation(presentationMode);

  if (!editableModel) {
    return (
      <section ref={inspectorRef} className="panel rail-panel">
        <div className="panel-header">
          <p className="eyebrow">Inspector</p>
          <h2>No workspace loaded</h2>
          <p className="panel-subtitle">
            Create a semantic model or import a file to unlock selection and precise editing.
          </p>
        </div>
      </section>
    );
  }

  return (
    <section ref={inspectorRef} className="panel rail-panel rail-inspector-panel">
      <div className="panel-header">
        <p className="eyebrow">
          {isEditable ? "Precision editor" : "Inspect-only workspace"}
        </p>
        <h2 style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span>{selectedBody ? selectedBody.label : "Select a feature"}</span>
          <EditabilityBadge
            workspaceId={workspaceId}
            revisionId={editableModel?.revision_id ?? null}
          />
        </h2>
        <p className="panel-subtitle">
          {isEditable
            ? "The left rail is the only full editor. Canvas interaction only selects and orients."
            : importContext?.message ||
              "This mode is intentionally inspect-only. No editable controls or AI commands are exposed here."}
        </p>
      </div>

      {referenceImageUrl ? (
        <div className="reference-image-card">
          <div className="status-label">Reference image</div>
          <img
            src={referenceImageUrl}
            alt="Workspace reference"
            className="reference-image-preview"
          />
        </div>
      ) : null}

      <BodyTreeInspector
        model={editableModel}
        selectedFeatureId={selectedFeatureId}
        onSelect={(featureId) => onSelectFeature(featureId, "tree")}
        onParamChange={onBodyParamChange}
        disabled={isBusy || !isEditable}
        showParamEditor={isEditable}
      />

      {workspaceId ? (
        <div className="project-summary" style={{ display: "flex", flexDirection: "column" }}>
          <div className="status-label">Pulsai chat</div>
          <div className="muted" style={{ marginBottom: 8 }}>
            Multi-turn editing across the whole workspace. The agent calls tools
            scoped by the capability matrix; refused edits surface a reason.
          </div>
          <ChatPanel
            workspaceId={workspaceId}
            disabled={isBusy}
          />
        </div>
      ) : null}

      <div className="project-summary">
        <div className="status-label">Manufacturability</div>
        <div className="warning-list">
          {editableModel.manufacturability.messages.map((message) => (
            <span
              key={message}
              className={`warning-chip ${
                editableModel.manufacturability.status === "safe" ? "subtle" : ""
              }`}
            >
              {message}
            </span>
          ))}
        </div>
      </div>
    </section>
  );
}

export default function Home() {
  const backendUrl = resolveBackendUrl();
  const workspace = useEditableWorkspace();
  const [workflowMode, setWorkflowMode] = useState<"workspace" | "creative">(
    "workspace"
  );
  const [workspaceEntryMode, setWorkspaceEntryMode] = useState<"native" | "import">(
    "native"
  );
  const [presentationContext, setPresentationContext] =
    useState<WorkspaceImportContext | null>(null);
  const [creativeModelUrl, setCreativeModelUrl] = useState<string | null>(null);
  const [creativeStlUrl, setCreativeStlUrl] = useState<string | null>(null);
  const [, setCreativeGcodeUrl] = useState<string | null>(null);
  const [creativeBundleUrl, setCreativeBundleUrl] = useState<string | null>(null);
  const [canvasTab, setCanvasTab] = useState<CanvasTab>("3d");
  const [entryPanelCollapsed, setEntryPanelCollapsed] = useState(false);
  const [selectedFeatureId, setSelectedFeatureId] = useState<string | null>(null);
  const [selectionAnchorPoint, setSelectionAnchorPoint] = useState<{
    x: number;
    y: number;
    z: number;
  } | null>(null);
  const [selectionChipVisible, setSelectionChipVisible] = useState(false);
  const [referenceImageUrl, setReferenceImageUrl] = useState<string | null>(null);
  const [undoStack, setUndoStack] = useState<HistoryEntry[]>([]);
  const [redoStack, setRedoStack] = useState<HistoryEntry[]>([]);

  const previewTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const restoredRef = useRef(false);
  const selectionWorkspaceRef = useRef<string | null>(null);
  const canvasKeyRef = useRef<string | null>(null);
  const inspectorRef = useRef<HTMLDivElement | null>(null);

  const {
    workspaceId,
    editableModel,
    latestPreview,
    latestBuild,
    isBusy,
    error,
    setError,
    createWorkspace,
    loadWorkspace,
    hydrateWorkspace,
    resetWorkspace,
    mutate,
    updateBody,
    preview,
    build,
    aiEdit,
  } = workspace;

  useEffect(() => {
    if (workflowMode !== "workspace") {
      setWorkflowMode("workspace");
    }
  }, [workflowMode]);

  useEffect(() => {
    if (restoredRef.current || typeof window === "undefined") return;
    restoredRef.current = true;
    const params = new URLSearchParams(window.location.search);
    const fromQuery = params.get("workspace");
    let parsed: StoredWorkspaceShell | null = null;
    try {
      const fromStorage = window.localStorage.getItem(STORAGE_KEY);
      parsed = fromStorage ? (JSON.parse(fromStorage) as StoredWorkspaceShell) : null;
    } catch {
      parsed = null;
    }
    const restoredWorkspaceId = fromQuery || parsed?.workspaceId;
    if (!restoredWorkspaceId) return;
    void loadWorkspace(restoredWorkspaceId)
      .then((loaded) => {
        if (!loaded) return;
        const restoredContext =
          parsed?.context ??
          ({
            mode: inferPresentationMode(loaded.editable_model),
            sourceModelUrl: null,
            sourceStlUrl: null,
          } satisfies WorkspaceImportContext);
        setPresentationContext(restoredContext);
        setWorkspaceEntryMode(
          restoredContext.mode.startsWith("stl") ||
            restoredContext.mode.startsWith("step")
            ? "import"
            : "native"
        );
        setWorkflowMode("workspace");
        setEntryPanelCollapsed(true);
      })
      .catch(() => {
        window.localStorage.removeItem(STORAGE_KEY);
      });
  }, [loadWorkspace]);

  useEffect(() => {
    if (!editableModel) {
      selectionWorkspaceRef.current = null;
      setSelectedFeatureId(null);
      setSelectionAnchorPoint(null);
      setSelectionChipVisible(false);
      return;
    }

    const allBodies = flattenBodies(editableModel.bodies);
    if (selectionWorkspaceRef.current !== workspaceId) {
      selectionWorkspaceRef.current = workspaceId;
      const restoredSelection =
        editableModel.selection?.feature_id &&
        allBodies.some((body) => body.id === editableModel.selection?.feature_id)
          ? editableModel.selection.feature_id
          : firstEditableFeatureId(editableModel);
      setSelectedFeatureId(restoredSelection);
      setSelectionChipVisible(false);
      return;
    }

    if (!selectedFeatureId) return;
    const currentStillExists = allBodies.some((body) => body.id === selectedFeatureId);
    if (!currentStillExists) {
      setSelectedFeatureId(null);
      setSelectionAnchorPoint(null);
      setSelectionChipVisible(false);
    }
  }, [editableModel, selectedFeatureId, workspaceId]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    if (workspaceId) {
      params.set("workspace", workspaceId);
      try {
        window.localStorage.setItem(
          STORAGE_KEY,
          JSON.stringify({
            workspaceId,
            context: presentationContext
              ? {
                  mode: presentationContext.mode,
                  sourceModelUrl: presentationContext.sourceModelUrl,
                  sourceStlUrl: presentationContext.sourceStlUrl,
                  message: presentationContext.message ?? null,
                }
              : null,
          } satisfies StoredWorkspaceShell)
        );
      } catch {
        // Ignore storage quota issues; they should not break the active workspace.
      }
    } else {
      params.delete("workspace");
      try {
        window.localStorage.removeItem(STORAGE_KEY);
      } catch {
        // Ignore storage cleanup failures.
      }
    }
    const query = params.toString();
    window.history.replaceState(
      {},
      "",
      `${window.location.pathname}${query ? `?${query}` : ""}`
    );
  }, [presentationContext, workspaceId]);

  useEffect(() => {
    if (
      workflowMode !== "workspace" ||
      !editableModel ||
      !isEditablePresentation(
        presentationContext?.mode ?? inferPresentationMode(editableModel)
      )
    ) {
      if (previewTimerRef.current) {
        clearTimeout(previewTimerRef.current);
        previewTimerRef.current = null;
      }
      return;
    }

    const currentRevision = editableModel.revision_id;
    const previewRevision = latestPreview?.revision_id ?? null;
    const buildRevision = latestBuild?.revision_id ?? null;
    if (previewRevision === currentRevision || buildRevision === currentRevision) {
      return;
    }

    previewTimerRef.current = setTimeout(() => {
      void preview().catch((previewError) => {
        setError((previewError as Error).message || "Preview failed.");
      });
    }, 350);

    return () => {
      if (previewTimerRef.current) {
        clearTimeout(previewTimerRef.current);
        previewTimerRef.current = null;
      }
    };
  }, [
    presentationContext?.mode,
    workflowMode,
    editableModel,
    latestBuild?.revision_id,
    latestPreview?.revision_id,
    preview,
    setError,
  ]);

  useEffect(() => {
    if (!workspaceId) {
      setUndoStack([]);
      setRedoStack([]);
      return;
    }
  }, [workspaceId]);

  useEffect(() => {
    if (!editableModel) {
      setEntryPanelCollapsed(false);
    }
  }, [editableModel]);

  const selectedFeature = editableModel
    ? findBodyById(editableModel.bodies, selectedFeatureId)
    : null;
  const workspaceMode =
    presentationContext?.mode ?? inferPresentationMode(editableModel);
  const isPreviewStale =
    workflowMode === "workspace" &&
    Boolean(editableModel && editableModel.revision_id !== latestPreview?.revision_id);
  const workspaceModelUrl =
    toAbsolute(backendUrl, latestBuild?.glb_url) ??
    toAbsolute(backendUrl, latestPreview?.glb_url) ??
    presentationContext?.sourceModelUrl ??
    null;
  const workspaceStlUrl =
    toAbsolute(backendUrl, latestBuild?.stl_url) ??
    toAbsolute(backendUrl, latestPreview?.stl_url) ??
    presentationContext?.sourceStlUrl ??
    null;
  const workspaceBundleUrl = toAbsolute(backendUrl, latestBuild?.bundle_url) ?? null;
  const creativeModelVisible = workflowMode === "creative";
  const visibleModelUrl = creativeModelVisible ? creativeModelUrl : workspaceModelUrl;
  const visibleStlUrl = creativeModelVisible ? creativeStlUrl : workspaceStlUrl;
  const visibleBundleUrl = creativeModelVisible
    ? creativeBundleUrl
    : workspaceBundleUrl;
  const compareEnabled =
    workflowMode === "workspace" &&
    workspaceMode === "stl_reconstruction" &&
    Boolean(
      presentationContext?.sourceModelUrl &&
        workspaceModelUrl &&
        presentationContext.sourceModelUrl !== workspaceModelUrl
    );

  const defaultCanvasTab = useMemo(
    () =>
      getDefaultCanvasTab({
        workflowMode,
        workspaceMode,
        editableModel,
        compareEnabled,
        selectedFeatureId,
        importContext: presentationContext,
      }),
    [compareEnabled, editableModel, presentationContext, selectedFeatureId, workflowMode, workspaceMode]
  );

  useEffect(() => {
    setSelectionChipVisible(false);
  }, [canvasTab]);

  const stlTarget = useMemo(() => {
    if (
      workspaceMode !== "stl_reconstruction" ||
      !presentationContext?.analysis?.targets ||
      !selectedFeature
    ) {
      return null;
    }
    return (
      presentationContext.analysis.targets.find(
        (target) =>
          target.id === selectedFeature.id &&
          target.type !== "unsupported" &&
          Boolean(target.editable)
      ) ?? null
    );
  }, [presentationContext?.analysis?.targets, selectedFeature, workspaceMode]);

  const planarParams = useMemo(() => {
    if (!stlTarget || !selectedFeature) return null;
    if (stlTarget.type === "planar_pattern_face") {
      return {
        hole_diameter: String(selectedFeature.params.hole_diameter_mm ?? ""),
        width: String(selectedFeature.params.width_mm ?? ""),
        height: String(selectedFeature.params.height_mm ?? ""),
        spacing_x: String(selectedFeature.params.tangential_spacing_mm ?? ""),
        spacing_y: String(selectedFeature.params.spacing_y_mm ?? ""),
        count_x: String(selectedFeature.params.count_x ?? ""),
        count_y: String(selectedFeature.params.count_y ?? ""),
        radial_spacing: String(selectedFeature.params.radial_spacing_mm ?? ""),
        ring_count: String(selectedFeature.params.ring_count ?? ""),
        margin: String(selectedFeature.params.edge_margin_mm ?? ""),
        center_hole_diameter: "",
      };
    }
    return {
      hole_diameter: String(
        selectedFeature.params.diameter_mm ?? selectedFeature.params.hole_diameter_mm ?? ""
      ),
      width: String(selectedFeature.params.width_mm ?? ""),
      height: String(selectedFeature.params.height_mm ?? ""),
      spacing_x: "",
      spacing_y: "",
      count_x: "",
      count_y: "",
      radial_spacing: "",
      ring_count: "",
      margin: "",
      center_hole_diameter: "",
    };
  }, [selectedFeature, stlTarget]);

  const focusTarget = useMemo<ViewerFocusTarget | null>(() => {
    if (!editableModel || !selectedFeature || !isEditablePresentation(workspaceMode)) {
      return null;
    }
    if (workspaceMode === "native" && isPerforatedDiscModel(editableModel)) {
      const focus = getPerforatedDiscFocusTarget(
        editableModel.bodies[0],
        selectedFeature.id
      );
      return focus
        ? { point: focus.anchorPoint, distance: focus.focusDistance }
        : null;
    }
    return selectionAnchorPoint ? { point: selectionAnchorPoint, distance: 42 } : null;
  }, [editableModel, selectedFeature, selectionAnchorPoint, workspaceMode]);

  const selectionMarker = useMemo(() => {
    if (selectedFeature && focusTarget) {
      return { point: focusTarget.point, label: selectedFeature.label };
    }
    return null;
  }, [focusTarget, selectedFeature]);

  const semanticAnnotations = useMemo<SemanticAnnotation[]>(() => {
    if (
      !editableModel ||
      !selectedFeature ||
      workspaceMode !== "native" ||
      !isPerforatedDiscModel(editableModel)
    ) {
      return [];
    }
    return getPerforatedDiscAnnotations(editableModel.bodies[0], selectedFeature.id);
  }, [editableModel, selectedFeature, workspaceMode]);

  const recordMutationHistory = (
    previousModel: EditableModel,
    previousSelectedFeatureId: string | null
  ) => {
    setUndoStack((current) =>
      pushHistoryEntry(current, {
        model: cloneEditableModel(previousModel),
        selectedFeatureId: previousSelectedFeatureId,
      })
    );
    setRedoStack([]);
  };

  const applyHistoryEntry = async (
    entry: HistoryEntry,
    direction: "undo" | "redo"
  ) => {
    if (!editableModel) return;
    const payload = buildHistoryMutation(
      editableModel,
      entry.model,
      entry.selectedFeatureId
    );
    if (!payload) {
      setError(
        "Undo history is no longer compatible with the current feature structure."
      );
      return;
    }

    const currentEntry: HistoryEntry = {
      model: cloneEditableModel(editableModel),
      selectedFeatureId,
    };

    try {
      await mutate(payload);
      setSelectedFeatureId(
        entry.selectedFeatureId && findBodyById(entry.model.bodies, entry.selectedFeatureId)
          ? entry.selectedFeatureId
          : firstEditableFeatureId(entry.model)
      );
      setSelectionChipVisible(false);
      if (direction === "undo") {
        setUndoStack((current) => current.slice(0, -1));
        setRedoStack((current) => pushHistoryEntry(current, currentEntry));
      } else {
        setRedoStack((current) => current.slice(0, -1));
        setUndoStack((current) => pushHistoryEntry(current, currentEntry));
      }
    } catch (mutationError) {
      setError((mutationError as Error).message || "Could not restore that revision.");
    }
  };

  const handleCreateNativeWorkspace = async (payload: {
    structured_spec: Record<string, unknown>;
    source: "native";
  }) => {
    setWorkflowMode("workspace");
    setWorkspaceEntryMode("native");
    setPresentationContext({
      mode: "native",
      sourceModelUrl: null,
      sourceStlUrl: null,
      message: null,
    });
    setSelectionAnchorPoint(null);
    setSelectionChipVisible(false);
    const created = await createWorkspace(payload);
    if (created) {
      const nextSelection =
        created.editable_model.selection?.feature_id &&
        findBodyById(
          created.editable_model.bodies,
          created.editable_model.selection.feature_id
        )
          ? created.editable_model.selection.feature_id
          : firstEditableFeatureId(created.editable_model);
      setSelectedFeatureId(nextSelection);
      setUndoStack([]);
      setRedoStack([]);
      setEntryPanelCollapsed(true);
    }
    return created;
  };

  const handleFeatureSelect = (
    featureId: string,
    source: "tree" | "designer" | "planar" | "viewer" = "tree"
  ) => {
    setSelectedFeatureId(featureId);
    if (editableModel && workspaceMode === "native" && isPerforatedDiscModel(editableModel)) {
      const focus = getPerforatedDiscFocusTarget(editableModel.bodies[0], featureId);
      setSelectionAnchorPoint(focus?.anchorPoint ?? null);
    } else if (source !== "viewer") {
      setSelectionAnchorPoint(null);
    }
    if (
      workspaceMode === "native" &&
      isPerforatedDiscModel(editableModel) &&
      source !== "designer"
    ) {
      setCanvasTab("2d");
    } else if (
      workspaceMode === "stl_reconstruction" &&
      hasEditablePlanarTarget(presentationContext, featureId)
    ) {
      setCanvasTab("2d");
    }
    setSelectionChipVisible(source === "viewer" || source === "designer" || source === "planar");
  };

  const handleBodyParamChange = async (bodyId: string, key: string, value: string) => {
    if (!editableModel) return;
    const body = findBodyById(editableModel.bodies, bodyId);
    if (!body) return;
    const nextValue = coerceParamValue(body.params[key], value);
    const previousModel = cloneEditableModel(editableModel);
    const previousSelection = selectedFeatureId;
    try {
      const result = await updateBody(bodyId, { [key]: nextValue });
      if (result?.editable_model.revision_id !== previousModel.revision_id) {
        recordMutationHistory(previousModel, previousSelection);
      }
    } catch (mutationError) {
      setError(
        (mutationError as Error).message ||
          "Could not update the selected feature."
      );
    }
  };

  const handleAiEdit = async (featureId: string, prompt: string) => {
    if (!editableModel) return;
    const previousModel = cloneEditableModel(editableModel);
    const previousSelection = selectedFeatureId;
    const result = await aiEdit(featureId, prompt);
    if (result?.editable_model.revision_id !== previousModel.revision_id) {
      recordMutationHistory(previousModel, previousSelection);
    }
  };

  const handlePlanarSelection = (
    selection:
      | { kind: "pattern" }
      | { kind: "feature"; featureId: string }
      | { kind: "center_hole"; featureId?: string }
  ) => {
    if (!editableModel) return;
    const targets = presentationContext?.analysis?.targets ?? [];
    if (selection.kind === "pattern") {
      const patternTarget = targets.find(
        (target) => target.type === "planar_pattern_face" && target.editable
      );
      if (patternTarget) {
        handleFeatureSelect(patternTarget.id, "planar");
      }
      return;
    }

    if (!selection.featureId) return;
    const targetId =
      targets.find(
        (target) =>
          target.type === "single_planar_feature" &&
          (target.id === selection.featureId ||
            (target as { feature_id?: string }).feature_id === selection.featureId)
      )?.id ?? selection.featureId;
    handleFeatureSelect(targetId, "planar");
  };

  const handleViewerSelect = (payload: SelectionPayload) => {
    if (!editableModel) return;
    if (workspaceMode === "native" && isPerforatedDiscModel(editableModel)) {
      const hit = classifyPerforatedDiscClick(payload.point, editableModel.bodies[0]);
      if (!hit) return;
      const nextFeatureId =
        hit.confidence < DISC_PICK_CONFIDENCE.minNarrowFeature && !hit.fallbackToOuter
          ? editableModel.bodies[0].id
          : hit.featureId;
      setSelectedFeatureId(nextFeatureId);
      setSelectionAnchorPoint(hit.anchorPoint);
      setSelectionChipVisible(true);
      return;
    }
    if (!isEditablePresentation(workspaceMode)) {
      setSelectionChipVisible(false);
      return;
    }
    setSelectionAnchorPoint(payload.point);
  };

  const selectionChip =
    selectionChipVisible && selectedFeature ? (
      <SelectionChip
        eyebrow={workspaceMode === "native" ? "Selected feature" : "Selected target"}
        title={selectedFeature.label}
        value={selectionChipValue(selectedFeature)}
        actionLabel={
          (workspaceMode === "native" && isPerforatedDiscModel(editableModel)) ||
          (workspaceMode === "stl_reconstruction" &&
            hasEditablePlanarTarget(presentationContext, selectedFeature.id))
            ? "Open edit"
            : "Edit"
        }
        onDismiss={() => setSelectionChipVisible(false)}
        onAction={() => {
          if (
            (workspaceMode === "native" && isPerforatedDiscModel(editableModel)) ||
            (workspaceMode === "stl_reconstruction" &&
              hasEditablePlanarTarget(presentationContext, selectedFeature.id))
          ) {
            setCanvasTab("2d");
          }
          inspectorRef.current?.scrollIntoView({
            behavior: "smooth",
            block: "nearest",
          });
        }}
      />
    ) : null;

  const canvasTabs = useMemo(() => {
    const tabs: Array<{ id: CanvasTab; label: string }> = [];
    if (
      workflowMode === "workspace" &&
      workspaceMode === "native" &&
      isPerforatedDiscModel(editableModel)
    ) {
      tabs.push({ id: "2d", label: "2D" });
    }
    if (
      workflowMode === "workspace" &&
      workspaceMode === "stl_reconstruction" &&
      stlTarget &&
      planarParams
    ) {
      tabs.push({ id: "2d", label: "2D" });
    }
    tabs.push({ id: "3d", label: "3D" });
    if (compareEnabled) {
      tabs.push({ id: "compare", label: "Compare" });
    }
    return tabs;
  }, [compareEnabled, editableModel, planarParams, stlTarget, workflowMode, workspaceMode]);

  useEffect(() => {
    const nextKey = `${workflowMode}:${workspaceId ?? "none"}:${workspaceMode}`;
    if (canvasKeyRef.current !== nextKey) {
      canvasKeyRef.current = nextKey;
      setCanvasTab(defaultCanvasTab);
      setSelectionChipVisible(false);
      return;
    }
    if (canvasTab === "compare" && !compareEnabled) {
      setCanvasTab(defaultCanvasTab);
      return;
    }
    if (!canvasTabs.some((tab) => tab.id === canvasTab)) {
      setCanvasTab(defaultCanvasTab);
    }
  }, [canvasTab, canvasTabs, compareEnabled, defaultCanvasTab, workflowMode, workspaceId, workspaceMode]);

  const currentHint = creativeModelVisible
    ? creativeStlUrl
      ? "Creative STL is ready for download."
      : "Generate a creative preview to unlock exports."
    : visibleStlUrl
    ? isPreviewStale
      ? "Draft changed. Exact preview is rebuilding in the background."
      : "Exact preview and export are in sync."
    : "Create or import a workspace revision to unlock preview and export.";
  const compactWorkspaceEntry = workflowMode === "workspace" && entryPanelCollapsed && Boolean(workspaceId);

  return (
    <main className="cad-page">
      <header className="cad-shell-header">
        <div className="cad-header-main">
          <div>
            <div className="brand">3dprint</div>
            <div className="cad-header-meta">
              <span className="cad-header-mode">
                {workflowMode === "creative" ? "Creative workspace" : "Semantic CAD workspace"}
              </span>
              {workspaceId ? (
                <span className="cad-header-revision">
                  Workspace {workspaceId.slice(0, 8)}
                </span>
              ) : null}
              {selectedFeature ? (
                <span className="cad-header-revision">
                  Selected {selectedFeature.label}
                </span>
              ) : null}
            </div>
          </div>
        </div>
        <div className="cad-header-actions">
          <Link className="topbar-link" href="/projects">
            Projects
          </Link>
        </div>
      </header>

      <div className="cad-shell-body">
        <aside className="cad-left-rail">
          {workflowMode === "workspace" ? (
            <>
              <section
                className={`panel rail-panel rail-mode-panel ${
                  compactWorkspaceEntry ? "compact-entry-panel" : ""
                }`}
              >
                <div className="panel-header">
                  <p className="eyebrow">Workspace entry</p>
                  <h2>{compactWorkspaceEntry ? "Entry mode" : "Create or import"}</h2>
                  <p className="panel-subtitle">
                    {compactWorkspaceEntry
                      ? "Entry controls are collapsed while you edit."
                      : "Both entry paths feed the same semantic workspace shell."}
                  </p>
                </div>
                <div
                  className="mode-switch"
                  role="tablist"
                  aria-label="Workspace entry mode"
                >
                  <button
                    type="button"
                    className={`mode-chip ${
                      workspaceEntryMode === "native" ? "active" : ""
                    }`}
                    onClick={() => {
                      setWorkspaceEntryMode("native");
                      setEntryPanelCollapsed(false);
                    }}
                  >
                    Design
                  </button>
                  <button
                    type="button"
                    className={`mode-chip ${
                      workspaceEntryMode === "import" ? "active" : ""
                    }`}
                    onClick={() => {
                      setWorkspaceEntryMode("import");
                      setEntryPanelCollapsed(false);
                    }}
                  >
                    Import
                  </button>
                </div>
                {compactWorkspaceEntry ? (
                  <div className="actions">
                    <button
                      type="button"
                      className="mode-chip"
                      onClick={() => setEntryPanelCollapsed(false)}
                    >
                      Reopen controls
                    </button>
                  </div>
                ) : null}
              </section>

              {entryPanelCollapsed && workspaceId ? null : workspaceEntryMode === "native" ? (
                <VoicePanel
                  workflowMode="workspace"
                  onCreateNativeWorkspace={handleCreateNativeWorkspace}
                  onReferenceImageChange={setReferenceImageUrl}
                />
              ) : (
                <ExistingModelPanel
                  createWorkspace={createWorkspace}
                  loadWorkspace={loadWorkspace}
                  hydrateWorkspace={hydrateWorkspace}
                  resetWorkspace={resetWorkspace}
                  onPresentationChange={(context) => {
                    setPresentationContext(context);
                    setWorkflowMode("workspace");
                    setWorkspaceEntryMode("import");
                    setReferenceImageUrl(null);
                    setSelectedFeatureId(null);
                    setSelectionAnchorPoint(null);
                    setSelectionChipVisible(false);
                    setUndoStack([]);
                    setRedoStack([]);
                    setEntryPanelCollapsed(Boolean(context));
                  }}
                />
              )}

              <WorkspaceInspectorPanel
                editableModel={editableModel}
                presentationMode={workspaceMode}
                importContext={presentationContext}
                isBusy={isBusy}
                workspaceId={workspaceId ?? null}
                selectedFeatureId={selectedFeatureId}
                referenceImageUrl={referenceImageUrl}
                onSelectFeature={handleFeatureSelect}
                onBodyParamChange={handleBodyParamChange}
                onAiEdit={handleAiEdit}
                inspectorRef={inspectorRef}
              />
            </>
          ) : (
            <VoicePanel
              workflowMode="creative"
              onCreateNativeWorkspace={handleCreateNativeWorkspace}
              onCreativeModelUrl={setCreativeModelUrl}
              onCreativeStlUrl={setCreativeStlUrl}
              onCreativeGcodeUrl={setCreativeGcodeUrl}
              onCreativeBundleUrl={setCreativeBundleUrl}
            />
          )}
        </aside>

        <section className="cad-canvas-area">
          <div className="cad-canvas-header">
            <div>
              <p className="eyebrow">
                {creativeModelVisible ? "Creative canvas" : "Working canvas"}
              </p>
              <h2>
                {creativeModelVisible
                  ? "Inspect the current creative object"
                  : "Select in canvas, edit in rail"}
              </h2>
              <p className="panel-subtitle">
                {creativeModelVisible
                  ? "Creative mode remains mesh-first. It does not participate in the semantic editing contract."
                  : "Canvas interaction selects and frames features. Exact numeric editing stays in the left rail."}
              </p>
            </div>
            <div className="cad-canvas-toolbar">
              {canvasTabs.length > 1 ? (
                <CanvasTabBar
                  tabs={canvasTabs}
                  activeTab={canvasTab}
                  onChange={setCanvasTab}
                />
              ) : null}
              {isPreviewStale && workflowMode === "workspace" ? (
                <span className="warning-chip subtle">Rebuilding exact preview…</span>
              ) : null}
            </div>
          </div>

          <div className="canvas-stage">
            {creativeModelVisible ? (
              <div className="canvas-surface model-shell cad-model-shell">
                <ModelViewer
                  src={visibleModelUrl}
                  label="Creative object"
                  defaultInteractionMode="orbit"
                  defaultCameraPreset="iso"
                />
              </div>
            ) : canvasTab === "2d" &&
              editableModel &&
              workspaceMode === "native" &&
              isPerforatedDiscModel(editableModel) ? (
              <div className="canvas-surface canvas-surface-2d">
                {selectionChip}
                <PerforatedDiscDesigner
                  rootBody={editableModel.bodies[0]}
                  selectedFeatureId={selectedFeatureId}
                  disabled={isBusy}
                  showParams={false}
                  onSelectFeature={(featureId) =>
                    handleFeatureSelect(featureId, "designer")
                  }
                  onParamChange={handleBodyParamChange}
                />
              </div>
            ) : canvasTab === "2d" &&
              workspaceMode === "stl_reconstruction" &&
              stlTarget &&
              planarParams ? (
              <div className="canvas-surface canvas-surface-2d">
                {selectionChip}
                <PlanarFaceEditor
                  target={stlTarget as Parameters<typeof PlanarFaceEditor>[0]["target"]}
                  params={planarParams}
                  disabled={isBusy}
                  showControls={false}
                  onParamChange={(key, value) => {
                    if (!selectedFeature) return;
                    const mapping: Record<
                      string,
                      { bodyId: string; paramKey: string }
                    > = {
                      hole_diameter: {
                        bodyId: selectedFeature.id,
                        paramKey:
                          selectedFeature.kind === "hole"
                            ? "diameter_mm"
                            : "hole_diameter_mm",
                      },
                      width: { bodyId: selectedFeature.id, paramKey: "width_mm" },
                      height: { bodyId: selectedFeature.id, paramKey: "height_mm" },
                      spacing_x: {
                        bodyId: selectedFeature.id,
                        paramKey: "tangential_spacing_mm",
                      },
                      spacing_y: {
                        bodyId: selectedFeature.id,
                        paramKey: "spacing_y_mm",
                      },
                      count_x: { bodyId: selectedFeature.id, paramKey: "count_x" },
                      count_y: { bodyId: selectedFeature.id, paramKey: "count_y" },
                      radial_spacing: {
                        bodyId: selectedFeature.id,
                        paramKey: "radial_spacing_mm",
                      },
                      ring_count: {
                        bodyId: selectedFeature.id,
                        paramKey: "ring_count",
                      },
                      margin: {
                        bodyId: selectedFeature.id,
                        paramKey: "edge_margin_mm",
                      },
                    };
                    const targetMapping = mapping[key];
                    if (targetMapping) {
                      void handleBodyParamChange(
                        targetMapping.bodyId,
                        targetMapping.paramKey,
                        value
                      );
                    }
                  }}
                  onParamReset={() => {
                    // Reset is intentionally disabled in the 2D shell surface.
                  }}
                  onSelectElement={handlePlanarSelection}
                />
              </div>
            ) : canvasTab === "compare" &&
              compareEnabled &&
              presentationContext?.sourceModelUrl ? (
              <div className="compare-grid cad-compare-grid">
                <div className="model-stack">
                  <div className="status-label">Original import</div>
                  <div className="model-shell cad-model-shell">
                    <ModelViewer
                      src={presentationContext.sourceModelUrl}
                      label="Imported STL"
                      defaultInteractionMode="pan"
                      defaultCameraPreset="front"
                    />
                  </div>
                </div>
                <div className="model-stack">
                  <div className="status-label">Current revision</div>
                  <div className="model-shell cad-model-shell">
                    <ModelViewer
                      src={workspaceModelUrl || presentationContext.sourceModelUrl}
                      label="Workspace revision"
                      defaultInteractionMode="pan"
                      defaultCameraPreset="front"
                    />
                  </div>
                </div>
              </div>
            ) : (
              <div className="canvas-surface model-shell cad-model-shell">
                <ModelViewer
                  src={visibleModelUrl}
                  label={creativeModelVisible ? "Creative object" : "Workspace revision"}
                  defaultInteractionMode={creativeModelVisible ? "orbit" : "pan"}
                  defaultCameraPreset={creativeModelVisible ? "iso" : "front"}
                  onSelect={workflowMode === "workspace" ? handleViewerSelect : undefined}
                  onClearSelection={() => {
                    setSelectionChipVisible(false);
                  }}
                  selectionMarker={selectionMarker}
                  focusTarget={focusTarget}
                  selectionChip={selectionChip}
                  annotations={
                    semanticAnnotations.length ? (
                      <SemanticAnnotations items={semanticAnnotations} />
                    ) : null
                  }
                />
              </div>
            )}
          </div>
        </section>
      </div>

      <footer className="cad-bottom-bar">
        <div className="cad-bottom-status">
          <span className="cad-status-label">
            {creativeModelVisible
              ? creativeStlUrl
                ? "Creative output ready"
                : "Awaiting creative generation"
              : isPreviewStale
              ? "Rebuilding exact preview…"
              : editableModel
              ? "Draft updated"
              : "No active workspace"}
          </span>
          <span className="hint">{currentHint}</span>
          {editableModel ? (
            <span className="cad-revision-chip">
              Revision {editableModel.revision_id.slice(0, 8)}
            </span>
          ) : null}
        </div>

        <div className="cad-bottom-actions">
          {workflowMode === "workspace" && editableModel ? (
            <>
              <button
                type="button"
                className="mode-chip"
                onClick={() => void applyHistoryEntry(undoStack[undoStack.length - 1], "undo")}
                disabled={!undoStack.length || isBusy}
              >
                Undo
              </button>
              <button
                type="button"
                className="mode-chip"
                onClick={() => void applyHistoryEntry(redoStack[redoStack.length - 1], "redo")}
                disabled={!redoStack.length || isBusy}
              >
                Redo
              </button>
              <button
                type="button"
                className="mode-chip"
                onClick={() => void preview()}
                disabled={isBusy}
              >
                Preview current
              </button>
              <button
                type="button"
                className="download-button action-button"
                onClick={() => void build()}
                disabled={isBusy}
              >
                Export STL
              </button>
            </>
          ) : null}
          {visibleStlUrl ? (
            <a className="mode-chip" href={visibleStlUrl} download>
              Download STL
            </a>
          ) : null}
          {visibleBundleUrl ? (
            <a className="mode-chip" href={visibleBundleUrl} download>
              Download bundle
            </a>
          ) : null}
        </div>
      </footer>

      {error ? <div className="cad-global-error warning-chip">{error}</div> : null}
    </main>
  );
}
