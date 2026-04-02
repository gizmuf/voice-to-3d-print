"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";

import BodyTreeInspector from "../components/BodyTreeInspector";
import ElementAiInput from "../components/ElementAiInput";
import FloatingQuickEditor from "../components/FloatingQuickEditor";
import ExistingModelPanel, {
  type WorkspaceImportContext,
} from "../components/ExistingModelPanel";
import ModelViewer, { type SelectionPayload, type ViewerFocusTarget } from "../components/ModelViewer";
import PerforatedDiscDesigner from "../components/PerforatedDiscDesigner";
import PlanarFaceEditor from "../components/PlanarFaceEditor";
import SemanticAnnotations from "../components/SemanticAnnotations";
import VoicePanel from "../components/VoicePanel";
import { resolveBackendUrl, resolveUrl } from "../lib/backend";
import {
  classifyPerforatedDiscClick,
  getPerforatedDiscAnnotations,
  getPerforatedDiscFocusTarget,
  type SemanticAnnotation,
} from "../lib/perforated-disc-geometry";
import { useEditableWorkspace } from "../lib/use-editable-workspace";
import type { BodyNode, EditableModel, WorkspacePresentationMode, WorkspaceResponse } from "../types/editable-model";

const STORAGE_KEY = "3dprint:workspace-shell";

type StoredWorkspaceShell = {
  workspaceId?: string;
  context?: Pick<WorkspaceImportContext, "mode" | "sourceModelUrl" | "sourceStlUrl" | "message"> | null;
};

const flattenBodies = (bodies: BodyNode[]): BodyNode[] =>
  bodies.flatMap((body) => [body, ...flattenBodies(body.children)]);

const findBodyById = (bodies: BodyNode[], bodyId: string | null) =>
  bodyId ? flattenBodies(bodies).find((body) => body.id === bodyId) ?? null : null;

const firstEditableFeatureId = (model: EditableModel | null) =>
  model ? flattenBodies(model.bodies).find((body) => body.editable)?.id ?? null : null;

const coerceParamValue = (current: number | string | boolean | undefined, nextRaw: string) => {
  if (typeof current === "boolean") {
    return nextRaw === "true";
  }
  if (typeof current === "number") {
    const parsed = Number(nextRaw);
    return Number.isFinite(parsed) ? parsed : 0;
  }
  return nextRaw;
};

const inferPresentationMode = (model: EditableModel | null): WorkspacePresentationMode => {
  if (!model) return "native";
  if (model.source === "step_import") return "step_reference";
  if (model.source === "stl_reconstructed") return "stl_reconstruction";
  return "native";
};

const isEditablePresentation = (mode: WorkspacePresentationMode | null) =>
  mode === "native" || mode === "step_editable" || mode === "stl_reconstruction";

const isPerforatedDiscModel = (model: EditableModel | null) =>
  Boolean(model?.bodies[0]?.params?._template_id === "perforated_disc");

const toAbsolute = (backendUrl: string, value?: string | null) => resolveUrl(backendUrl, value);

type FloatingEditorContext = {
  point: { x: number; y: number; z: number };
  mode: "floating" | "docked";
} | null;

function WorkspaceEditor({
  editableModel,
  presentationMode,
  importContext,
  isBusy,
  selectedFeatureId,
  referenceImageUrl,
  onSelectFeature,
  onBodyParamChange,
  onPlanarSelection,
}: {
  editableModel: EditableModel | null;
  presentationMode: WorkspacePresentationMode | null;
  importContext: WorkspaceImportContext | null;
  isBusy: boolean;
  selectedFeatureId: string | null;
  referenceImageUrl: string | null;
  onSelectFeature: (featureId: string, source?: "tree" | "designer" | "planar" | "viewer") => void;
  onBodyParamChange: (featureId: string, key: string, value: string) => void;
  onPlanarSelection: (selection: { kind: "pattern" } | { kind: "feature"; featureId: string } | { kind: "center_hole"; featureId?: string }) => void;
}) {
  const selectedBody = editableModel ? findBodyById(editableModel.bodies, selectedFeatureId) : null;
  const flattenedBodies = useMemo(
    () => (editableModel ? flattenBodies(editableModel.bodies) : []),
    [editableModel]
  );
  const stlTarget = useMemo(() => {
    if (presentationMode !== "stl_reconstruction" || !importContext?.analysis?.targets || !selectedBody) {
      return null;
    }
    return (
      importContext.analysis.targets.find(
        (target) =>
          target.id === selectedBody.id &&
          target.type !== "unsupported" &&
          Boolean(target.editable)
      ) ?? null
    );
  }, [editableModel, importContext?.analysis?.targets, presentationMode, selectedBody]);

  const planarParams = useMemo(() => {
    if (!stlTarget || !selectedBody) return null;
    if (stlTarget.type === "planar_pattern_face") {
      return {
        hole_diameter: String(selectedBody.params.hole_diameter_mm ?? ""),
        width: String(selectedBody.params.width_mm ?? ""),
        height: String(selectedBody.params.height_mm ?? ""),
        spacing_x: String(selectedBody.params.tangential_spacing_mm ?? ""),
        spacing_y: String(selectedBody.params.spacing_y_mm ?? ""),
        count_x: String(selectedBody.params.count_x ?? ""),
        count_y: String(selectedBody.params.count_y ?? ""),
        radial_spacing: String(selectedBody.params.radial_spacing_mm ?? ""),
        ring_count: String(selectedBody.params.ring_count ?? ""),
        margin: String(selectedBody.params.edge_margin_mm ?? ""),
        center_hole_diameter: "",
      };
    }
    return {
      hole_diameter: String(selectedBody.params.diameter_mm ?? selectedBody.params.hole_diameter_mm ?? ""),
      width: String(selectedBody.params.width_mm ?? ""),
      height: String(selectedBody.params.height_mm ?? ""),
      spacing_x: "",
      spacing_y: "",
      count_x: "",
      count_y: "",
      radial_spacing: "",
      ring_count: "",
      margin: "",
      center_hole_diameter: "",
    };
  }, [selectedBody, stlTarget]);

  if (!editableModel) {
    if (!importContext) return null;
    return (
      <section className="panel workspace-editor-panel">
        <div className="panel-header">
          <p className="eyebrow">Workspace State</p>
          <h2>{importContext.mode === "stl_locked" ? "Locked mesh" : "Reference model"}</h2>
          <p className="panel-subtitle">{importContext.message || "This model is view-only in the current mode."}</p>
        </div>
        {importContext.analysis?.unsupported_reasons?.length ? (
          <div className="warning-list">
            {importContext.analysis.unsupported_reasons.map((reason) => (
              <span key={reason} className="warning-chip">{reason}</span>
            ))}
          </div>
        ) : null}
      </section>
    );
  }

  if (!isEditablePresentation(presentationMode)) {
    return (
      <section className="panel workspace-editor-panel">
        <div className="panel-header">
          <p className="eyebrow">Workspace State</p>
          <h2>Reference-only model</h2>
          <p className="panel-subtitle">
            {importContext?.message || "This imported model is available for inspection only. The current workspace intentionally does not expose editable controls."}
          </p>
        </div>

        <div className="project-summary">
          <div className="status-label">Detected structure</div>
          <div className="muted">
            The semantic tree is preserved for labeling and future recognition work, but no parameters are editable in this mode.
          </div>
        </div>

        <div className="target-group-list">
          {flattenedBodies.map((body) => (
            <div key={body.id} className="target-group-card disabled-card">
              <strong>{body.label}</strong>
              <span>{body.kind.replace(/_/g, " ")}</span>
              {!body.editable ? <span>Locked</span> : null}
              {body.unsupported_reason ? <span>{body.unsupported_reason}</span> : null}
            </div>
          ))}
        </div>

        <div className="warning-list">
          {editableModel.manufacturability.messages.map((message) => (
            <span key={message} className="warning-chip">
              {message}
            </span>
          ))}
        </div>
      </section>
    );
  }

  const selectedBodyId = selectedBody?.id ?? null;
  const showDiscDesigner = presentationMode === "native" && isPerforatedDiscModel(editableModel);

  return (
    <section className="panel workspace-editor-panel">
      <div className="panel-header">
        <p className="eyebrow">Semantic Workspace</p>
        <h2>Inspector, constraints, and precision editing</h2>
        <p className="panel-subtitle">
          All edits mutate the canonical workspace model. Preview and export operate on the current revision only.
        </p>
      </div>

      {importContext?.message ? (
        <div className="warning-list">
          <span className="warning-chip subtle">{importContext.message}</span>
        </div>
      ) : null}

      {referenceImageUrl ? (
        <div className="reference-image-card">
          <div className="status-label">Reference image</div>
          <img src={referenceImageUrl} alt="Workspace reference" className="reference-image-preview" />
        </div>
      ) : null}

      <BodyTreeInspector
        model={editableModel}
        selectedFeatureId={selectedBodyId}
        onSelect={(featureId) => onSelectFeature(featureId, "tree")}
        onParamChange={onBodyParamChange}
        disabled={isBusy || !isEditablePresentation(presentationMode)}
      />

      {showDiscDesigner && editableModel.bodies[0] ? (
        <PerforatedDiscDesigner
          rootBody={editableModel.bodies[0]}
          selectedFeatureId={selectedBodyId}
          disabled={isBusy}
          onSelectFeature={(featureId) => onSelectFeature(featureId, "designer")}
          onParamChange={onBodyParamChange}
        />
      ) : null}

      {presentationMode === "stl_reconstruction" && stlTarget && planarParams ? (
        <PlanarFaceEditor
          target={stlTarget as Parameters<typeof PlanarFaceEditor>[0]["target"]}
          params={planarParams}
          disabled={isBusy}
          onParamChange={(key, value) => {
            if (!selectedBody) return;
            const bodyId = selectedBody.id;
            const mapping: Record<string, { bodyId: string; paramKey: string }> = {
              hole_diameter: { bodyId, paramKey: selectedBody.kind === "hole" ? "diameter_mm" : "hole_diameter_mm" },
              width: { bodyId, paramKey: "width_mm" },
              height: { bodyId, paramKey: "height_mm" },
              spacing_x: { bodyId, paramKey: "tangential_spacing_mm" },
              spacing_y: { bodyId, paramKey: "spacing_y_mm" },
              count_x: { bodyId, paramKey: "count_x" },
              count_y: { bodyId, paramKey: "count_y" },
              radial_spacing: { bodyId, paramKey: "radial_spacing_mm" },
              ring_count: { bodyId, paramKey: "ring_count" },
              margin: { bodyId, paramKey: "edge_margin_mm" },
            };
            const targetMapping = mapping[key];
            if (targetMapping) {
              onBodyParamChange(targetMapping.bodyId, targetMapping.paramKey, value);
            }
          }}
          onParamReset={(key) => {
            if (!stlTarget || !selectedBody) return;
            const defaults: Record<string, string> = {
              hole_diameter:
                stlTarget.type === "single_planar_feature"
                  ? String(stlTarget.measured?.diameter ?? "")
                  : typeof stlTarget.measured?.feature_size === "number"
                    ? String(stlTarget.measured.feature_size)
                    : "",
              width:
                stlTarget.type === "single_planar_feature"
                  ? String(stlTarget.measured?.width ?? "")
                  : typeof stlTarget.measured?.feature_size === "object"
                    ? String(stlTarget.measured.feature_size.width)
                    : "",
              height:
                stlTarget.type === "single_planar_feature"
                  ? String(stlTarget.measured?.height ?? "")
                  : typeof stlTarget.measured?.feature_size === "object"
                    ? String(stlTarget.measured.feature_size.height)
                    : "",
              spacing_x: String(stlTarget.measured?.spacing_x ?? ""),
              spacing_y: String(stlTarget.measured?.spacing_y ?? ""),
              count_x: String(stlTarget.measured?.count_x ?? ""),
              count_y: String(stlTarget.measured?.count_y ?? ""),
              radial_spacing: String(stlTarget.measured?.radial_spacing ?? ""),
              ring_count: String(stlTarget.measured?.ring_count ?? ""),
              margin: String(stlTarget.measured?.margin ?? ""),
            };
            if (defaults[key] != null) {
              onBodyParamChange(selectedBody.id, key === "hole_diameter"
                ? selectedBody.kind === "hole" ? "diameter_mm" : "hole_diameter_mm"
                : key === "width"
                  ? "width_mm"
                  : key === "height"
                    ? "height_mm"
                    : key === "spacing_x"
                      ? "tangential_spacing_mm"
                      : key === "spacing_y"
                        ? "spacing_y_mm"
                        : key === "count_x"
                          ? "count_x"
                          : key === "count_y"
                            ? "count_y"
                            : key === "radial_spacing"
                              ? "radial_spacing_mm"
                              : key === "ring_count"
                                ? "ring_count"
                                : "edge_margin_mm", defaults[key]);
            }
          }}
          onSelectElement={onPlanarSelection}
        />
      ) : null}

      <div className="warning-list">
        {editableModel.manufacturability.messages.map((message) => (
          <span key={message} className={`warning-chip ${editableModel.manufacturability.status === "safe" ? "subtle" : ""}`}>
            {message}
          </span>
        ))}
      </div>
    </section>
  );
}

export default function Home() {
  const backendUrl = resolveBackendUrl();
  const workspace = useEditableWorkspace();
  const [workflowMode, setWorkflowMode] = useState<"workspace" | "creative">("workspace");
  const [workspaceEntryMode, setWorkspaceEntryMode] = useState<"native" | "import">("native");
  const [presentationContext, setPresentationContext] = useState<WorkspaceImportContext | null>(null);
  const [creativeModelUrl, setCreativeModelUrl] = useState<string | null>(null);
  const [creativeStlUrl, setCreativeStlUrl] = useState<string | null>(null);
  const [creativeGcodeUrl, setCreativeGcodeUrl] = useState<string | null>(null);
  const [creativeBundleUrl, setCreativeBundleUrl] = useState<string | null>(null);
  const [showOriginalReference, setShowOriginalReference] = useState(false);
  const previewTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const restoredRef = useRef(false);
  const selectionWorkspaceRef = useRef<string | null>(null);
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
    updateBody,
    preview,
    build,
    aiEdit,
  } = workspace;
  const [selectedFeatureId, setSelectedFeatureId] = useState<string | null>(null);
  const [floatingEditorContext, setFloatingEditorContext] = useState<FloatingEditorContext>(null);
  const [referenceImageUrl, setReferenceImageUrl] = useState<string | null>(null);

  useEffect(() => {
    if (restoredRef.current || typeof window === "undefined") return;
    restoredRef.current = true;
    const params = new URLSearchParams(window.location.search);
    const fromQuery = params.get("workspace");
    let parsed: StoredWorkspaceShell | null = null;
    try {
      const fromStorage = window.localStorage.getItem(STORAGE_KEY);
      parsed = fromStorage ? JSON.parse(fromStorage) as StoredWorkspaceShell : null;
    } catch {
      parsed = null;
    }
    const workspaceId = fromQuery || parsed?.workspaceId;
    if (!workspaceId) return;
    void loadWorkspace(workspaceId)
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
        setWorkspaceEntryMode(restoredContext.mode.startsWith("stl") || restoredContext.mode.startsWith("step") ? "import" : "native");
        setWorkflowMode("workspace");
      })
      .catch(() => {
        window.localStorage.removeItem(STORAGE_KEY);
      });
  }, [loadWorkspace]);

  useEffect(() => {
    if (!editableModel) {
      selectionWorkspaceRef.current = null;
      setSelectedFeatureId(null);
      setFloatingEditorContext(null);
      return;
    }

    const allBodies = flattenBodies(editableModel.bodies);
    if (selectionWorkspaceRef.current !== workspaceId) {
      selectionWorkspaceRef.current = workspaceId;
      const restoredSelection =
        editableModel.selection?.feature_id && allBodies.some((body) => body.id === editableModel.selection?.feature_id)
          ? editableModel.selection.feature_id
          : firstEditableFeatureId(editableModel);
      setSelectedFeatureId(restoredSelection);
      if (!restoredSelection) {
        setFloatingEditorContext(null);
      }
      return;
    }

    if (!selectedFeatureId) {
      return;
    }

    const currentStillExists = allBodies.some((body) => body.id === selectedFeatureId);
    if (!currentStillExists) {
      setSelectedFeatureId(null);
      setFloatingEditorContext(null);
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
        // Storage quota should not break the active workspace session.
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
    window.history.replaceState({}, "", `${window.location.pathname}${query ? `?${query}` : ""}`);
  }, [presentationContext, workspaceId]);

  useEffect(() => {
    if (workflowMode !== "workspace" || !editableModel || !isEditablePresentation(presentationContext?.mode ?? inferPresentationMode(editableModel))) {
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
    build,
    editableModel,
    latestBuild?.revision_id,
    latestPreview?.revision_id,
    preview,
    setError,
  ]);

  const selectedFeature =
    editableModel ? findBodyById(editableModel.bodies, selectedFeatureId) : null;
  const workspaceMode = presentationContext?.mode ?? inferPresentationMode(editableModel);
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
  const visibleBundleUrl = creativeModelVisible ? creativeBundleUrl : workspaceBundleUrl;
  const currentHint =
    creativeModelVisible
      ? creativeStlUrl
        ? "Creative STL ready for export."
        : "Generate a creative preview to unlock exports."
      : visibleStlUrl
        ? "Workspace revision is available for download."
        : "Create or import a workspace revision to unlock exports.";

  const handleCreateNativeWorkspace = async (payload: { structured_spec: Record<string, unknown>; source: "native" }) => {
    setWorkflowMode("workspace");
    setWorkspaceEntryMode("native");
    setShowOriginalReference(false);
    setPresentationContext({
      mode: "native",
      sourceModelUrl: null,
      sourceStlUrl: null,
      message: null,
    });
    const created = await createWorkspace(payload);
    if (created) {
      const nextSelection =
        created.editable_model.selection?.feature_id && findBodyById(created.editable_model.bodies, created.editable_model.selection.feature_id)
          ? created.editable_model.selection.feature_id
          : firstEditableFeatureId(created.editable_model);
      setSelectedFeatureId(nextSelection);
    }
    return created;
  };

  const handleFeatureSelect = (featureId: string, source: "tree" | "designer" | "planar" | "viewer" = "tree") => {
    setSelectedFeatureId(featureId);
    if (source !== "viewer") {
      const rootBody = editableModel?.bodies[0];
      if (rootBody && isPerforatedDiscModel(editableModel)) {
        const focus = getPerforatedDiscFocusTarget(rootBody, featureId);
        if (focus) {
          setFloatingEditorContext({
            point: focus.anchorPoint,
            mode: source === "tree" ? "docked" : "floating",
          });
        }
      }
    }
  };

  const handleBodyParamChange = async (bodyId: string, key: string, value: string) => {
    if (!editableModel) return;
    const body = findBodyById(editableModel.bodies, bodyId);
    if (!body) return;
    const nextValue = coerceParamValue(body.params[key], value);
    try {
      await updateBody(bodyId, { [key]: nextValue });
    } catch (error) {
      setError((error as Error).message || "Could not update the selected feature.");
    }
  };

  const handlePlanarSelection = (selection: { kind: "pattern" } | { kind: "feature"; featureId: string } | { kind: "center_hole"; featureId?: string }) => {
    if (!editableModel) return;
    const targets = presentationContext?.analysis?.targets ?? [];
    if (selection.kind === "pattern") {
      const patternTarget = targets.find((target) => target.type === "planar_pattern_face" && target.editable);
      if (patternTarget) {
        handleFeatureSelect(patternTarget.id, "planar");
      }
      return;
    }

    if (!selection.featureId) {
      return;
    }

    const targetId =
      targets.find(
        (target) =>
          target.type === "single_planar_feature" &&
          (target.id === selection.featureId || (target as { feature_id?: string }).feature_id === selection.featureId)
      )?.id ?? selection.featureId;
    handleFeatureSelect(targetId, "planar");
  };

  const focusTarget = useMemo<ViewerFocusTarget | null>(() => {
    if (!editableModel || !selectedFeature || !isEditablePresentation(workspaceMode)) return null;
    if (workspaceMode === "native" && isPerforatedDiscModel(editableModel)) {
      const focus = getPerforatedDiscFocusTarget(editableModel.bodies[0], selectedFeature.id);
      return focus ? { point: focus.anchorPoint, distance: focus.focusDistance } : null;
    }
    return floatingEditorContext ? { point: floatingEditorContext.point, distance: 42 } : null;
  }, [editableModel, floatingEditorContext, selectedFeature, workspaceMode]);

  const selectionMarker = useMemo(() => {
    if (selectedFeature && focusTarget) {
      return { point: focusTarget.point, label: selectedFeature.label };
    }
    return null;
  }, [focusTarget, selectedFeature]);

  const semanticAnnotations = useMemo<SemanticAnnotation[]>(() => {
    if (!editableModel || !selectedFeature || workspaceMode !== "native" || !isPerforatedDiscModel(editableModel)) {
      return [];
    }
    return getPerforatedDiscAnnotations(editableModel.bodies[0], selectedFeature.id);
  }, [editableModel, selectedFeature, workspaceMode]);

  const floatingEditor =
    selectedFeature && isEditablePresentation(workspaceMode) ? (
      <FloatingQuickEditor
        body={selectedFeature}
        disabled={isBusy}
        mode={floatingEditorContext?.mode ?? "docked"}
        onParamChange={handleBodyParamChange}
        onDismiss={() => setFloatingEditorContext(null)}
        aiInput={
          workspaceMode === "native" && isPerforatedDiscModel(editableModel) ? (
            <ElementAiInput
              disabled={isBusy}
              onSubmit={async (prompt) => {
                await aiEdit(selectedFeature.id, prompt);
              }}
            />
          ) : undefined
        }
      />
    ) : null;
  const floatingCanvasEditor = floatingEditorContext?.mode === "floating" ? floatingEditor : null;
  const dockedFloatingEditor = floatingEditorContext?.mode === "docked" ? floatingEditor : null;

  const handleViewerSelect = (payload: SelectionPayload) => {
    if (!editableModel) return;
    if (workspaceMode === "native" && isPerforatedDiscModel(editableModel)) {
      const hit = classifyPerforatedDiscClick(payload.point, editableModel.bodies[0]);
      if (!hit) return;
      const nextFeatureId =
        hit.confidence < 0.88 && !hit.fallbackToOuter ? editableModel.bodies[0].id : hit.featureId;
      setSelectedFeatureId(nextFeatureId);
      setFloatingEditorContext({
        point: hit.anchorPoint,
        mode: typeof window !== "undefined" && window.innerWidth < 1280 ? "docked" : hit.fallbackToOuter ? "docked" : "floating",
      });
      return;
    }
    if (!isEditablePresentation(workspaceMode)) {
      setFloatingEditorContext({
        point: payload.point,
        mode: "docked",
      });
    }
  };

  const isCompareMode =
    workflowMode === "workspace" &&
    workspaceMode === "stl_reconstruction" &&
    Boolean(presentationContext?.sourceModelUrl && workspaceModelUrl && presentationContext.sourceModelUrl !== workspaceModelUrl);

  const heroCopy =
    workflowMode === "creative"
      ? {
          eyebrow: "Prompt → Generate → Repair → Export",
          title: "Build imaginative prints from",
          highlight: " creative prompts",
          body: "Creative mode remains separate from the semantic workspace. Use it for decorative objects and mesh-first concepts.",
        }
      : {
          eyebrow: "Prompt / Import → Semantic Model → Preview → Export",
          title: "Edit one",
          highlight: " semantic workspace",
          body: "Native authoring, STEP import, and supported STL reconstruction now share one canonical workspace state and one preview/export path.",
        };

  return (
    <main className="page">
      <nav className="topbar">
        <div className="brand">3dprint</div>
        <div className="topbar-links">
          <Link className="topbar-link" href="/projects">Projects</Link>
        </div>
      </nav>

      <header className="hero">
        <div>
          <p className="eyebrow">{heroCopy.eyebrow}</p>
          <div className="mode-switch hero-switch" role="tablist" aria-label="Workflow mode">
            <button
              type="button"
              className={`mode-chip ${workflowMode === "workspace" ? "active" : ""}`}
              onClick={() => setWorkflowMode("workspace")}
            >
              Workspace
            </button>
            <button
              type="button"
              className={`mode-chip ${workflowMode === "creative" ? "active" : ""}`}
              onClick={() => setWorkflowMode("creative")}
            >
              Creative
            </button>
          </div>
          <h1>
            {heroCopy.title}
            <span className="highlight"> {heroCopy.highlight}</span>.
          </h1>
          <p className="hero-body">{heroCopy.body}</p>
        </div>
      </header>

      <div className="grid workspace-grid workspace-grid-design">
        <div className="workspace-column workspace-column-editor">
          {workflowMode === "workspace" ? (
            <>
              <section className="panel">
                <div className="panel-header">
                  <p className="eyebrow">Workspace Mode</p>
                  <h2>Select how to enter the semantic workspace</h2>
                  <p className="panel-subtitle">Both native creation and model import feed the same workspace state.</p>
                </div>
                <div className="mode-switch" role="tablist" aria-label="Workspace entry mode">
                  <button
                    type="button"
                    className={`mode-chip ${workspaceEntryMode === "native" ? "active" : ""}`}
                    onClick={() => setWorkspaceEntryMode("native")}
                  >
                    Design
                  </button>
                  <button
                    type="button"
                    className={`mode-chip ${workspaceEntryMode === "import" ? "active" : ""}`}
                    onClick={() => setWorkspaceEntryMode("import")}
                  >
                    Import
                  </button>
                </div>
              </section>

              {workspaceEntryMode === "native" ? (
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
                    setShowOriginalReference(false);
                    setReferenceImageUrl(null);
                    setSelectedFeatureId(null);
                    setFloatingEditorContext(null);
                  }}
                />
              )}

              <WorkspaceEditor
                editableModel={editableModel}
                presentationMode={workspaceMode}
                importContext={presentationContext}
                isBusy={isBusy}
                selectedFeatureId={selectedFeatureId}
                referenceImageUrl={referenceImageUrl}
                onSelectFeature={handleFeatureSelect}
                onBodyParamChange={handleBodyParamChange}
                onPlanarSelection={handlePlanarSelection}
              />

              {editableModel && isEditablePresentation(workspaceMode) ? (
                <section className="panel">
                  <div className="panel-header">
                    <p className="eyebrow">Revision Controls</p>
                    <h2>Preview and export the active workspace revision</h2>
                    <p className="panel-subtitle">
                      Preview runs automatically after edits. Export remains explicit and revision-guarded.
                    </p>
                  </div>
                  <div className="actions">
                    <button
                      type="button"
                      className="download-button action-button"
                      onClick={() => void preview()}
                      disabled={isBusy}
                    >
                      Preview revision
                    </button>
                    <button
                      type="button"
                      className="download-button action-button"
                      onClick={() => void build()}
                      disabled={isBusy}
                    >
                      Export STL
                    </button>
                    <span className="hint">
                      Active revision: {editableModel.revision_id.slice(0, 8)}
                    </span>
                  </div>
                  {error ? <div className="warning-chip">{error}</div> : null}
                </section>
              ) : null}
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
        </div>

        <div className="workspace-column workspace-column-preview">
          <section className="panel model-panel">
            <div className="panel-header">
              <p className="eyebrow">3D Preview</p>
              <h2>
                {workflowMode === "creative"
                  ? "Inspect the creative revision"
                  : isCompareMode && showOriginalReference
                    ? "Inspect the original and rebuilt revision"
                    : "Inspect the current workspace revision"}
              </h2>
              <p className="panel-subtitle">
                {workflowMode === "creative"
                  ? "Creative mode remains mesh-first."
                  : "The preview reflects the active workspace state. 3D stays for context and comparison; precise edits happen in the semantic inspector and 2D editor."}
              </p>
            </div>

            {isCompareMode ? (
              <div className="model-toolbar">
              {isPreviewStale ? <span className="warning-chip subtle">Rebuilding exact preview…</span> : null}
              <button
                type="button"
                className="mode-chip"
                  onClick={() => setShowOriginalReference((value) => !value)}
                >
                  {showOriginalReference ? "Hide original reference" : "Show original reference"}
                </button>
              </div>
            ) : null}

            {!isCompareMode && isPreviewStale ? (
              <div className="model-toolbar">
                <span className="warning-chip subtle">Rebuilding exact preview…</span>
              </div>
            ) : null}

            {isCompareMode && showOriginalReference && presentationContext?.sourceModelUrl ? (
              <div className="compare-grid">
                <div className="model-stack">
                  <div className="status-label">Original import</div>
                  <div className="model-shell">
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
                  <div className="model-shell">
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
              <div className="model-shell">
                <ModelViewer
                  src={visibleModelUrl}
                  label={workflowMode === "creative" ? "Creative object" : "Workspace revision"}
                  defaultInteractionMode={workflowMode === "creative" ? "orbit" : "pan"}
                  defaultCameraPreset={workflowMode === "creative" ? "iso" : "front"}
                  onSelect={workflowMode === "workspace" ? handleViewerSelect : undefined}
                  onClearSelection={() => {
                    setSelectedFeatureId(null);
                    setFloatingEditorContext(null);
                  }}
                  selectionMarker={selectionMarker}
                  focusTarget={focusTarget}
                  floatingPoint={floatingEditorContext?.mode === "floating" ? floatingEditorContext.point : null}
                  floatingEditor={floatingCanvasEditor}
                  annotations={semanticAnnotations.length ? <SemanticAnnotations items={semanticAnnotations} /> : null}
                />
              </div>
            )}

            {dockedFloatingEditor}

            <div className="actions">
              <a
                className={`download-button ${visibleStlUrl ? "" : "disabled"}`}
                href={visibleStlUrl || "#"}
                download
                aria-disabled={!visibleStlUrl}
              >
                Download STL
              </a>
              <a
                className={`download-button ${visibleBundleUrl ? "" : "disabled"}`}
                href={visibleBundleUrl || "#"}
                download
                aria-disabled={!visibleBundleUrl}
              >
                Download bundle
              </a>
              <span className="hint">{currentHint}</span>
            </div>
          </section>
        </div>
      </div>
    </main>
  );
}
