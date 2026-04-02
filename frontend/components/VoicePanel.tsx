"use client";

import type { FormEvent } from "react";
import { useEffect, useMemo, useState } from "react";

import ImageReferenceUpload from "./ImageReferenceUpload";
import { resolveBackendUrl, resolveUrl } from "../lib/backend";
import type { WorkspaceResponse } from "../types/editable-model";

type StructuredSpec = {
  mode: "useful";
  template_id: string;
  object_label: string;
  dimensions_mm: Record<string, number>;
  constraints: Record<string, string | number | boolean>;
  assumptions: string[];
  confidence: number;
  source_inputs: {
    text: string;
    source: string;
  };
  revision_notes: string[];
};

type RouteIntentResponse = {
  mode: "useful" | "creative";
  provider: string;
  route_reason: string;
  confidence: number;
  prompt: string;
  structured_spec?: StructuredSpec | null;
};

type HealthResponse = {
  ok: boolean;
  warnings?: string[];
  cad_ready?: boolean;
  preview_ready?: boolean;
  slicer_ready?: boolean;
};

type ProcessResponse = {
  glb_url: string;
  stl_url: string;
  gcode_url?: string | null;
  bundle_url?: string | null;
};

type VoicePanelProps = {
  workflowMode: "workspace" | "creative";
  onCreateNativeWorkspace: (payload: { structured_spec: Record<string, unknown>; source: "native" }) => Promise<WorkspaceResponse | null>;
  onReferenceImageChange?: (url: string | null) => void;
  onCreativeModelUrl?: (url: string | null) => void;
  onCreativeStlUrl?: (url: string | null) => void;
  onCreativeGcodeUrl?: (url: string | null) => void;
  onCreativeBundleUrl?: (url: string | null) => void;
};

const usefulPromptExamples = [
  "Perforated disc 340 mm diameter, 15 mm thick, 7 mm holes, 33 mm center hole",
  "Phone stand 12 cm tall, 65 degree angle, cable hole",
  "Desk tray 160x90x22 mm with rounded corners",
  "Wall hook 80 mm tall, thick enough for a bag",
  "Simple box 120x80x40 mm, wall 3 mm",
];

const creativePromptExamples = [
  "A stylized dragon statue with folded wings",
  "A toy robot with chunky legs and a friendly face",
  "A decorative moon lantern with star cutouts",
];

class TimeoutError extends Error {
  name = "TimeoutError";

  constructor(message: string) {
    super(message);
  }
}

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

export default function VoicePanel({
  workflowMode,
  onCreateNativeWorkspace,
  onReferenceImageChange,
  onCreativeModelUrl,
  onCreativeStlUrl,
  onCreativeGcodeUrl,
  onCreativeBundleUrl,
}: VoicePanelProps) {
  const backendUrl = resolveBackendUrl();
  const [manualText, setManualText] = useState("");
  const [status, setStatus] = useState<"idle" | "understanding" | "creating" | "generating" | "ready" | "error">("idle");
  const [lastError, setLastError] = useState<string | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [referenceImageFile, setReferenceImageFile] = useState<File | null>(null);
  const [referenceImageUrl, setReferenceImageUrl] = useState<string | null>(null);

  useEffect(() => {
    const loadHealth = async () => {
      try {
        const response = await fetchWithTimeout(`${backendUrl}/health`, undefined, 10000);
        if (!response.ok) throw new Error("Health check failed.");
        setHealth((await response.json()) as HealthResponse);
      } catch {
        setHealth(null);
      }
    };
    void loadHealth();
  }, [backendUrl]);

  useEffect(() => {
    setStatus("idle");
    setLastError(null);
  }, [workflowMode]);

  useEffect(() => {
    if (!referenceImageFile) {
      if (referenceImageUrl) {
        URL.revokeObjectURL(referenceImageUrl);
      }
      setReferenceImageUrl(null);
      onReferenceImageChange?.(null);
      return;
    }
    const objectUrl = URL.createObjectURL(referenceImageFile);
    setReferenceImageUrl(objectUrl);
    onReferenceImageChange?.(objectUrl);
    return () => {
      URL.revokeObjectURL(objectUrl);
    };
  }, [onReferenceImageChange, referenceImageFile]);

  const examplePrompts = workflowMode === "creative" ? creativePromptExamples : usefulPromptExamples;

  const readinessCopy = useMemo(() => {
    if (!health) return null;
    if (workflowMode === "creative") {
      return health.preview_ready ? "Creative mesh generation is ready." : "Creative generation is degraded.";
    }
    if (!health.cad_ready) return "CadQuery is unavailable. Native semantic rebuild will fail until backend CAD support is restored.";
    return "Semantic workspace backend is ready.";
  }, [health, workflowMode]);

  const handleSubmit = async (event?: FormEvent<HTMLFormElement>) => {
    event?.preventDefault();
    const prompt = manualText.trim();
    if (!prompt) return;

    setLastError(null);
    if (workflowMode === "creative") {
      setStatus("generating");
      try {
        const generateResponse = await fetchWithTimeout(
          `${backendUrl}/generate`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              prompt,
              prompt_raw: prompt,
              provider: "meshy",
              input_type: "text",
            }),
          },
          180000
        );
        if (!generateResponse.ok) throw new Error("Creative generation failed.");
        const generation = await generateResponse.json();

        const processResponse = await fetchWithTimeout(
          `${backendUrl}/process-model`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              glb_url: generation.glb_url,
              provider: "meshy",
              input_type: "text",
              prompt,
              mode: "creative",
            }),
          },
          180000
        );
        if (!processResponse.ok) throw new Error("Could not make the creative object printable.");
        const processed = (await processResponse.json()) as ProcessResponse;
        onCreativeModelUrl?.(resolveUrl(backendUrl, processed.glb_url));
        onCreativeStlUrl?.(resolveUrl(backendUrl, processed.stl_url));
        onCreativeGcodeUrl?.(resolveUrl(backendUrl, processed.gcode_url));
        onCreativeBundleUrl?.(resolveUrl(backendUrl, processed.bundle_url));
        setStatus("ready");
      } catch (error) {
        setStatus("error");
        setLastError((error as Error).message || "Creative generation failed.");
      }
      return;
    }

    setStatus("understanding");
    try {
      let promptForRouting = prompt;
      if (referenceImageFile) {
        const imageForm = new FormData();
        imageForm.append("image", referenceImageFile);
        imageForm.append("input_type", "image");
        const imageIntentResponse = await fetchWithTimeout(
          `${backendUrl}/image-intent`,
          {
            method: "POST",
            body: imageForm,
          },
          45000
        );
        if (!imageIntentResponse.ok) throw new Error("Could not understand the reference image.");
        const imageIntent = (await imageIntentResponse.json()) as { prompt: string };
        promptForRouting = imageIntent.prompt?.trim()
          ? `${prompt}\nReference image: ${imageIntent.prompt.trim()}`
          : prompt;
      }

      const response = await fetchWithTimeout(
        `${backendUrl}/route-intent`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            raw_text: promptForRouting,
            source: "text",
            mode_hint: "useful",
            has_image: Boolean(referenceImageFile),
          }),
        },
        25000
      );
      if (!response.ok) throw new Error("Could not understand your idea.");
      const routed = (await response.json()) as RouteIntentResponse;
      if (routed.mode !== "useful" || !routed.structured_spec) {
        throw new Error("This prompt was routed away from Design Workspace. Use Creative mode for non-semantic prompts.");
      }

      setStatus("creating");
      await onCreateNativeWorkspace({
        structured_spec: routed.structured_spec,
        source: "native",
      });
      setStatus("ready");
    } catch (error) {
      setStatus("error");
      setLastError((error as Error).message || "Could not create the workspace.");
    }
  };

  const openFlagshipDesigner = async () => {
    setManualText("Perforated disc designer");
    setStatus("creating");
    setLastError(null);
    try {
      await onCreateNativeWorkspace({
        structured_spec: {
          mode: "useful",
          template_id: "perforated_disc",
          object_label: "Perforated disc",
          dimensions_mm: {
            outer_diameter: 340,
            thickness: 15,
          },
          constraints: {
            hole_diameter_mm: 7.08,
            center_hole_diameter_mm: 32.93,
            ring_count: 12,
            radial_spacing_mm: 9.387,
            tangential_spacing_mm: 7,
            edge_margin_mm: 12.421,
          },
          assumptions: ["Hole counts per ring are derived automatically from tangential spacing."],
          confidence: 0.98,
          source_inputs: {
            text: "Perforated disc designer",
            source: "designer",
          },
          revision_notes: [],
        },
        source: "native",
      });
      setStatus("ready");
    } catch (error) {
      setStatus("error");
      setLastError((error as Error).message || "Could not open the perforated disc workspace.");
    }
  };

  return (
    <section className="panel voice-panel">
      <div className="panel-header">
        <p className="eyebrow">{workflowMode === "creative" ? "Creative Mode" : "Design Workspace"}</p>
        <h2>
          {workflowMode === "creative"
            ? "Create decorative or imaginative objects"
            : "Describe the physical design you want to build"}
        </h2>
        <p className="panel-subtitle">
          {workflowMode === "creative"
            ? "Creative mode keeps the mesh-generation path available. It is separate from the semantic CAD workspace."
            : "Prompt understanding only decides the starting template. After that, every edit happens through the semantic workspace model."}
        </p>
      </div>

      {readinessCopy ? (
        <div className="warning-list">
          <span className={`warning-chip ${health?.cad_ready === false && workflowMode === "workspace" ? "" : "subtle"}`}>
            {readinessCopy}
          </span>
        </div>
      ) : null}

      <form className="field-stack" onSubmit={handleSubmit}>
        <label className="field-row">
          <span>{workflowMode === "creative" ? "Creative prompt" : "Describe your object"}</span>
          <textarea
            value={manualText}
            onChange={(event) => setManualText(event.target.value)}
            placeholder={examplePrompts[0]}
            rows={4}
          />
        </label>

        <div className="example-chip-row">
          {examplePrompts.map((example) => (
            <button key={example} type="button" className="example-chip" onClick={() => setManualText(example)}>
              {example}
            </button>
          ))}
        </div>

        {workflowMode === "workspace" ? (
          <ImageReferenceUpload
            disabled={status === "understanding" || status === "creating"}
            imagePreviewUrl={referenceImageUrl}
            onChange={setReferenceImageFile}
            onRemove={() => setReferenceImageFile(null)}
          />
        ) : null}

        <div className="actions">
          <button type="submit" className="download-button action-button" disabled={status === "understanding" || status === "creating" || status === "generating"}>
            {workflowMode === "creative"
              ? status === "generating"
                ? "Generating"
                : "Generate creative preview"
              : status === "understanding" || status === "creating"
                ? "Creating workspace"
                : "Understand my idea"}
          </button>
          {workflowMode === "workspace" ? (
            <button type="button" className="mode-chip" onClick={openFlagshipDesigner} disabled={status === "understanding" || status === "creating"}>
              Open perforated disc designer
            </button>
          ) : null}
          <span className="hint">
            {workflowMode === "creative"
              ? "Creative mode does not participate in the semantic workspace."
              : "Native workspaces are persisted and can be restored by workspace ID."}
          </span>
        </div>
      </form>

      {lastError ? <div className="warning-chip">{lastError}</div> : null}
      {status === "ready" ? (
        <div className="project-summary">
          <div className="status-label">Ready</div>
          <div className="muted">
            {workflowMode === "creative"
              ? "Creative output was generated."
              : "Workspace created. Continue editing in the shared semantic inspector below."}
          </div>
        </div>
      ) : null}
    </section>
  );
}
