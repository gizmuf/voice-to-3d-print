"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import ExistingModelPanel from "../components/ExistingModelPanel";
import ModelViewer from "../components/ModelViewer";
import type { SelectionPayload, ViewerSelectionMarker } from "../components/ModelViewer";
import VoicePanel from "../components/VoicePanel";

export default function Home() {
  const [workflowMode, setWorkflowMode] = useState<"useful" | "creative" | "edit">("useful");
  const [modelUrl, setModelUrl] = useState<string | null>(null);
  const [sourceModelUrl, setSourceModelUrl] = useState<string | null>(null);
  const [ghostModelUrl, setGhostModelUrl] = useState<string | null>(null);
  const [stlUrl, setStlUrl] = useState<string | null>(null);
  const [gcodeUrl, setGcodeUrl] = useState<string | null>(null);
  const [bundleUrl, setBundleUrl] = useState<string | null>(null);
  const [isPreviewUpdating, setIsPreviewUpdating] = useState(false);
  const [showChanges, setShowChanges] = useState(true);
  const [showOriginalReference, setShowOriginalReference] = useState(false);
  const [editViewerSelection, setEditViewerSelection] = useState<SelectionPayload | null>(null);
  const [editSelectionMarker, setEditSelectionMarker] = useState<ViewerSelectionMarker | null>(null);
  const workflowModeRef = useRef(workflowMode);

  useEffect(() => {
    workflowModeRef.current = workflowMode;
  }, [workflowMode]);

  useEffect(() => {
    setGhostModelUrl(null);
    setIsPreviewUpdating(false);
    setModelUrl(null);
    setSourceModelUrl(null);
    setStlUrl(null);
    setGcodeUrl(null);
    setBundleUrl(null);
    setShowOriginalReference(false);
    setEditViewerSelection(null);
    setEditSelectionMarker(null);
  }, [workflowMode]);

  const createModeGuard = useMemo(() => {
    return (
      allowedModes: Array<"useful" | "creative" | "edit">,
      setter: (value: string | null) => void
    ) => {
      return (value: string | null) => {
        if (!allowedModes.includes(workflowModeRef.current)) return;
        setter(value);
      };
    };
  }, []);

  const createPreviewFlagGuard = useMemo(() => {
    return (allowedModes: Array<"useful" | "creative" | "edit">) => {
      return (value: boolean) => {
        if (!allowedModes.includes(workflowModeRef.current)) return;
        setIsPreviewUpdating(value);
      };
    };
  }, []);

  const heroCopy =
    workflowMode === "edit"
      ? {
          eyebrow: "Upload → Select → Preview → Export",
          title: "Modify real printable parts with",
          highlight: " precise STL edits",
          body: "Edit Existing Model mode imports STL files, detects planar faces and openings, previews exact local modifications, and exports a validated STL revision.",
          pipeline: "Precision editing",
          primary: "Existing Model",
        }
      : workflowMode === "creative"
        ? {
            eyebrow: "Prompt → Generate → Repair → Export",
            title: "Build imaginative prints from",
            highlight: " creative prompts",
            body: "Creative Object mode keeps the mesh-generation path available for figurines, decorative objects, and image-led concepts while preserving STL-first output.",
            pipeline: "Creative beta",
            primary: "Creative Object",
          }
        : {
            eyebrow: "Voice → Confirm → Preview → Export",
            title: "Build practical prints from",
            highlight: " spoken ideas",
            body: "Useful Object mode leads with voice, confirms dimensions and assumptions, drafts a preview, and exports a validated STL for real-world prints.",
            pipeline: "Voice-first",
            primary: "Useful Object",
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
              className={`mode-chip ${workflowMode === "useful" ? "active" : ""}`}
              onClick={() => {
                setWorkflowMode("useful");
                setSourceModelUrl(null);
              }}
            >
              Useful Object
            </button>
            <button
              type="button"
              className={`mode-chip ${workflowMode === "creative" ? "active" : ""}`}
              onClick={() => {
                setWorkflowMode("creative");
                setSourceModelUrl(null);
              }}
            >
              Creative Object (Beta)
            </button>
            <button
              type="button"
              className={`mode-chip ${workflowMode === "edit" ? "active" : ""}`}
              onClick={() => setWorkflowMode("edit")}
            >
              Edit Existing Model
            </button>
          </div>
          <h1>
            {heroCopy.title}
            <span className="highlight"> {heroCopy.highlight}</span>.
          </h1>
          <p className="hero-body">{heroCopy.body}</p>
        </div>
        <div className="hero-card">
          <div className="hero-stat">
            <span>Pipeline</span>
            <strong>{heroCopy.pipeline}</strong>
          </div>
          <div className="hero-stat">
            <span>Primary mode</span>
            <strong>{heroCopy.primary}</strong>
          </div>
          <div className="hero-stat">
            <span>Output</span>
            <strong>Validated STL</strong>
          </div>
        </div>
      </header>

      <div className="grid workspace-grid">
        <div className="workspace-column workspace-column-editor">
          {workflowMode === "edit" ? (
            <ExistingModelPanel
              onModelUrl={createModeGuard(["edit"], setModelUrl)}
              onSourceModelUrl={createModeGuard(["edit"], setSourceModelUrl)}
              onStlUrl={createModeGuard(["edit"], setStlUrl)}
              onGcodeUrl={createModeGuard(["edit"], setGcodeUrl)}
              onBundleUrl={createModeGuard(["edit"], setBundleUrl)}
              onSelectionMarker={setEditSelectionMarker}
              viewerSelectionHint={editViewerSelection}
            />
          ) : (
            <VoicePanel
              onModelUrl={createModeGuard(["useful", "creative"], setModelUrl)}
              onGhostModelUrl={createModeGuard(["useful", "creative"], setGhostModelUrl)}
              onPreviewUpdating={createPreviewFlagGuard(["useful", "creative"])}
              onStlUrl={createModeGuard(["useful", "creative"], setStlUrl)}
              onGcodeUrl={createModeGuard(["useful", "creative"], setGcodeUrl)}
              onBundleUrl={createModeGuard(["useful", "creative"], setBundleUrl)}
              workflowMode={workflowMode}
              hideModeSwitch
            />
          )}
        </div>

        <div className="workspace-column workspace-column-preview">
        <section className="panel model-panel">
          <div className="panel-header">
            <p className="eyebrow">3D Preview</p>
            <h2>{workflowMode === "edit" ? "Inspect the original and edited revision" : "Inspect the current revision"}</h2>
            <p className="panel-subtitle">
              {workflowMode === "edit"
                ? "Use the original model as a stable reference while previewing the current edited revision."
                : "Rotate, zoom, and validate the geometry before exporting the STL bundle."}
            </p>
          </div>

          {workflowMode === "edit" ? (
            <div className="model-toolbar">
              <button
                type="button"
                className="mode-chip"
                onClick={() => setShowOriginalReference((prev) => !prev)}
                disabled={!sourceModelUrl}
              >
                {showOriginalReference ? "Hide original reference" : "Show original reference"}
              </button>
            </div>
          ) : null}

          {workflowMode === "edit" && sourceModelUrl && showOriginalReference ? (
            <div className="compare-grid">
              <div className="model-stack">
                <div className="status-label">Original import</div>
                <div className="model-shell">
                  <ModelViewer
                    src={sourceModelUrl}
                    label="Imported STL"
                    defaultInteractionMode="pan"
                  />
                </div>
              </div>
              <div className="model-stack">
                <div className="status-label">Current revision</div>
                <div className="model-shell">
                  <ModelViewer
                    src={modelUrl || sourceModelUrl}
                    label="Edited STL"
                    defaultInteractionMode="pan"
                    onSelect={setEditViewerSelection}
                    selectionMarker={editSelectionMarker}
                  />
                </div>
              </div>
            </div>
          ) : (
            <>
              {workflowMode === "useful" ? (
                <div className="model-toolbar">
                  <button
                    type="button"
                    className="mode-chip"
                    onClick={() => setShowChanges((prev) => !prev)}
                    disabled={!ghostModelUrl}
                  >
                    {showChanges ? "Hide changes" : "Show changes"}
                  </button>
                  {isPreviewUpdating ? <span className="chip chip-warm">Updating preview</span> : null}
                </div>
              ) : null}
              <div className="model-shell">
                <ModelViewer
                  src={modelUrl}
                  ghostModelUrl={workflowMode === "useful" ? ghostModelUrl : null}
                  showChanges={workflowMode === "useful" ? showChanges : false}
                  isUpdating={workflowMode === "useful" ? isPreviewUpdating : false}
                  label={workflowMode === "edit" ? "Edited STL" : "Generated object"}
                  defaultInteractionMode={workflowMode === "edit" ? "pan" : "orbit"}
                  onSelect={workflowMode === "edit" ? setEditViewerSelection : () => undefined}
                  selectionMarker={workflowMode === "edit" ? editSelectionMarker : null}
                />
              </div>
            </>
          )}

          <div className="actions">
            <a
              className={`download-button ${stlUrl ? "" : "disabled"}`}
              href={stlUrl || "#"}
              download
              aria-disabled={!stlUrl}
            >
              Download STL
            </a>
            <a
              className={`download-button ${bundleUrl ? "" : "disabled"}`}
              href={bundleUrl || "#"}
              download
              aria-disabled={!bundleUrl}
            >
              Download bundle
            </a>
            <span className="hint">
              {stlUrl
                ? "Validated STL ready for your slicer."
                : "Generate a preview or final build to unlock exports."}
            </span>
          </div>
        </section>
        </div>
      </div>
    </main>
  );
}
