"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import ChatMessage from "../Chat/ChatMessage";
import ModelViewer from "../ModelViewer";
import SelectionChip from "../SelectionChip";
import SpeechToTextButton, { type VoiceState } from "../SpeechToTextButton";
import RevisionTimeline from "./RevisionTimeline";
import { resolveBackendUrl, resolveUrl } from "../../lib/backend";
import { displayModelName, formatUsd } from "../../lib/ai-cost";
import { cadPointToViewer } from "../../lib/cad-coordinates";
import { uiText, useUiLanguage, type UiLanguage } from "../../lib/ui-language";
import { useDesignStream } from "../../lib/useDesignStream";
import { useHealth } from "../../lib/useHealth";
import { usePrinterProfiles } from "../../lib/usePrinterProfiles";
import type { Design, DesignTemplate, ManufacturabilityIssue } from "../../types/design";
import type { SelectionPayload } from "../ModelViewer";

const TEMPLATE_PROMPTS: { labelPl: string; labelEn: string; prompt: string }[] = [
  { labelPl: "Maskownica głośnika 200 mm", labelEn: "Speaker grille 200 mm", prompt: "speaker grill 200mm with 8 rings" },
  { labelPl: "Stojak na telefon", labelEn: "Phone stand", prompt: "phone stand 65 degrees, cable hole" },
  { labelPl: "Pojemnik na długopisy", labelEn: "Pen holder", prompt: "cylindrical pen holder 60mm wide" },
  { labelPl: "Pudełko 80×60×30", labelEn: "Box 80×60×30", prompt: "simple box 80x60x30, wall 3mm" },
];

const JEWELRY_CONTEXTS = [
  "Brooch",
  "Charm",
  "Earring",
  "Medallion",
  "Pendant",
  "Relief plate",
  "Freeform jewelry",
];

const JEWELRY_TRACE_MODES = [
  { value: "auto", label: "Auto trace" },
  { value: "bright_metal_connected", label: "Shop photo" },
  { value: "bright_metal", label: "Bright metal" },
  { value: "dark_ink", label: "Clean sketch" },
];

const JEWELRY_TRACE_DETAILS = [
  { value: "fine", label: "Fine" },
  { value: "medium", label: "Medium" },
  { value: "bold", label: "Bold" },
];

type JewelryRole = "base_metal" | "cutout" | "raised_relief" | "engraving" | "ignore";

type JewelryContour = {
  id: string;
  role: JewelryRole;
  points: number[][];
  parent_id?: string | null;
  area_mm2?: number;
  min_width_mm?: number;
};

type JewelryTracePreview = {
  trace_id: string;
  context: string;
  brief: string;
  profile_id: string;
  reference_mm: number;
  reference_label: string;
  contours: JewelryContour[];
  graph: {
    nodes: { id: string; role: string; parent_id?: string | null; children?: string[]; disconnected?: boolean; min_width_mm?: number }[];
    edges: { from: string; to: string; type: string; distance_mm?: number }[];
  };
  attachments: Record<string, unknown>[];
  warnings: { severity: string; code: string; contour_id?: string; message: string; suggestion?: string }[];
  repair_suggestions: { id: string; label: string }[];
  score: { value: number; reasons: string[] };
  preview_svg?: string;
  trace_mode?: string;
  trace_detail?: string;
  trace_polygon_count?: number;
};

type JewelryProfile = {
  id: string;
  label: string;
  build_intent: string;
  min_width_mm: number;
  min_cutout_mm: number;
  base_thickness_mm: number;
};

type JewelryConcept = {
  id: string;
  image_url: string;
  prompt: string;
  score?: { value: number; reasons: string[] } | null;
  score_reasons?: string[];
};

const fetchWithTimeout = async (
  url: string,
  options: RequestInit | undefined,
  timeoutMs: number,
) => {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timeoutId);
  }
};

const resolveArtifactUrl = (
  backendUrl: string,
  artifact: { url?: string } | string | undefined,
) => {
  const raw = typeof artifact === "string" ? artifact : artifact?.url;
  return raw ? resolveUrl(backendUrl, raw) : null;
};

export default function DesignStudio() {
  const backendUrl = resolveBackendUrl();
  const { language: uiLanguage, setLanguage: setUiLanguage } = useUiLanguage();
  const tx = useCallback(
    (polish: string, english: string) => uiText(uiLanguage, polish, english),
    [uiLanguage],
  );
  const health = useHealth();
  const printerCatalog = usePrinterProfiles();
  const [templates, setTemplates] = useState<DesignTemplate[]>([]);
  const [design, setDesign] = useState<Design | null>(null);
  const [creating, setCreating] = useState(false);
  const [openingDeepLink, setOpeningDeepLink] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [prompt, setPrompt] = useState("");
  const [jewelryContext, setJewelryContext] = useState(JEWELRY_CONTEXTS[0]);
  const [jewelryBrief, setJewelryBrief] = useState("");
  const [jewelryReferenceLabel, setJewelryReferenceLabel] = useState("overall width");
  const [jewelryReferenceMm, setJewelryReferenceMm] = useState("");
  const [jewelryReferenceImage, setJewelryReferenceImage] = useState<File | null>(null);
  const [jewelryReferencePreview, setJewelryReferencePreview] = useState<string | null>(null);
  const [jewelryStatus, setJewelryStatus] = useState<"idle" | "concepts" | "tracing" | "creating">("idle");
  const [jewelryError, setJewelryError] = useState<string | null>(null);
  const [jewelryProfiles, setJewelryProfiles] = useState<JewelryProfile[]>([]);
  const [jewelryProfileId, setJewelryProfileId] = useState("resin_print");
  const [jewelryTrace, setJewelryTrace] = useState<JewelryTracePreview | null>(null);
  const [jewelryConcepts, setJewelryConcepts] = useState<JewelryConcept[]>([]);
  const [jewelryRepairs, setJewelryRepairs] = useState<string[]>([]);
  const [jewelryTraceMode, setJewelryTraceMode] = useState("auto");
  const [jewelryTraceDetail, setJewelryTraceDetail] = useState("bold");
  const [onshapeStatus, setOnshapeStatus] = useState<{
    configured: boolean;
    api_key_configured: boolean;
    oauth_configured: boolean;
    mode: string;
  } | null>(null);
  const [onshapeUrl, setOnshapeUrl] = useState("");
  const [onshapeElementKind, setOnshapeElementKind] = useState<"partstudio" | "assembly">("partstudio");
  const [onshapeImporting, setOnshapeImporting] = useState(false);
  const [onshapeError, setOnshapeError] = useState<string | null>(null);
  const [process, setProcess] = useState<"fdm" | "cnc" | "either">("fdm");
  const reloadAfterRef = useRef<string | null>(null);
  const chatEndRef = useRef<HTMLDivElement | null>(null);
  // After /design/create returns, we may want Claude to actually *shape* the
  // model from the user's prompt — not just seed a template. We can't call
  // useDesignStream.send until the hook sees the new design id, so we queue
  // the prompt here and let an effect fire it on the next render.
  const [pendingFirstPrompt, setPendingFirstPrompt] = useState<string | null>(null);
  const firstPromptFiredForRef = useRef<string | null>(null);
  const [updatingParam, setUpdatingParam] = useState<string | null>(null);
  const [livePreview, setLivePreview] = useState<boolean>(false);
  const [showAllParameters, setShowAllParameters] = useState(false);
  const [selectedFeatureId, setSelectedFeatureId] = useState<string | null>(null);
  const [selectedFeaturePoint, setSelectedFeaturePoint] = useState<{ x: number; y: number; z: number } | null>(null);
  const [selectedTopologyRef, setSelectedTopologyRef] = useState<string | null>(null);
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
  // Cancel any pending live-preview debounce on unmount or when the design
  // changes; otherwise the timer fires after the studio is gone and tries to
  // fetch parameters for a stale design id.
  useEffect(() => {
    return () => {
      if (liveDebounceRef.current) {
        clearTimeout(liveDebounceRef.current);
        liveDebounceRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    setJewelryTrace(null);
    if (!jewelryReferenceImage) {
      setJewelryReferencePreview(null);
      return;
    }
    const objectUrl = URL.createObjectURL(jewelryReferenceImage);
    setJewelryReferencePreview(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [jewelryReferenceImage]);

  useEffect(() => {
    setJewelryTrace(null);
  }, [jewelryTraceMode, jewelryTraceDetail, jewelryReferenceLabel, jewelryReferenceMm, jewelryContext]);
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
          printer_profile_id: payload.printer_profile_id ?? null,
          spec_compliance: payload.spec_compliance ?? null,
          motion_report: payload.motion_report ?? null,
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
          printer_profile_id: payload.printer_profile_id ?? null,
          spec_compliance: payload.spec_compliance ?? null,
          motion_report: payload.motion_report ?? null,
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

  useEffect(() => {
    fetch(`${backendUrl}/integrations/onshape/status`)
      .then((res) => (res.ok ? res.json() : null))
      .then((payload) => {
        if (payload) setOnshapeStatus(payload);
      })
      .catch(() => undefined);
  }, [backendUrl]);

  useEffect(() => {
    fetch(`${backendUrl}/design/jewelry/profiles`)
      .then((res) => (res.ok ? res.json() : null))
      .then((payload) => {
        if (payload?.profiles) setJewelryProfiles(payload.profiles);
        if (payload?.default) setJewelryProfileId(payload.default);
      })
      .catch(() => undefined);
  }, [backendUrl]);

  // Deep-link: ?design=<id> auto-loads an existing design (and its chat
  // history). Lets users bookmark / share work in progress.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const id = new URLSearchParams(window.location.search).get("design");
    if (!id) return;
    setOpeningDeepLink(true);
    fetch(`${backendUrl}/design/${id}`)
      .then((res) => {
        if (res.ok) return res.json();
        if (res.status === 404) {
          const url = new URL(window.location.href);
          url.searchParams.delete("design");
          window.history.replaceState({}, "", url.toString());
          return null;
        }
        throw new Error(`Open failed: ${res.status}`);
      })
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
          printer_profile_id: payload.printer_profile_id ?? null,
          spec_compliance: payload.spec_compliance ?? null,
          motion_report: payload.motion_report ?? null,
        });
      })
      .catch((error) => {
        setCreateError(error instanceof Error ? error.message : "Could not open design.");
      })
      .finally(() => setOpeningDeepLink(false));
    // Run once on mount; subsequent changes go through onCreate / onImportCAD.
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

  const stream = useDesignStream(design?.design_id ?? null, uiLanguage);
  const lastRevision = stream.latestRevisionId;
  const [externalSessionCost, setExternalSessionCost] = useState(0);
  useEffect(() => setExternalSessionCost(0), [design?.design_id]);
  const sessionCost = useMemo(
    () => externalSessionCost + stream.lifetimeCost,
    [externalSessionCost, stream.lifetimeCost],
  );

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ block: "nearest" });
  }, [stream.history]);

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
      setSelectedTopologyRef(null);
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
    async (
      creationPrompt: string,
      templateId?: string | null,
      processOverride?: typeof process,
    ) => {
      setCreating(true);
      setCreateError(null);
      try {
        const targetProcess = processOverride ?? process;
        const body: Record<string, unknown> = { process: targetProcess };
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
          requires_agent?: boolean;
        };
        setDesign({
          design_id: payload.design_id,
          revision_id: payload.revision_id,
          name: payload.name,
          process: payload.process ?? targetProcess,
          script: payload.script,
          parameters: payload.parameters ?? [],
          features: payload.features ?? [],
          latest_build: (payload as any).initial_build ?? null,
          spec_compliance: payload.spec_compliance ?? null,
          motion_report: payload.motion_report ?? null,
        });
        // If the user typed a free-form prompt (not a one-click template),
        // queue it as the first chat turn so Claude actually applies the
        // user's intent to the seed (e.g. "make the holes hexagonal").
        if (
          !templateId
          && creationPrompt
          && creationPrompt.trim()
          && payload.requires_agent !== false
        ) {
          setPendingFirstPrompt(creationPrompt.trim());
        }
        setPrompt("");
        if (typeof window !== "undefined") {
          const url = new URL(window.location.href);
          url.searchParams.set("design", payload.design_id);
          window.history.replaceState({}, "", url.toString());
        }
        return true;
      } catch (error) {
        setCreateError(
          error instanceof Error ? error.message : "Failed to create design.",
        );
        return false;
      } finally {
        setCreating(false);
      }
    },
    [backendUrl, process],
  );

  const onImportCAD = useCallback(
    async (file: File) => {
      setCreating(true);
      setCreateError(null);
      try {
        const fd = new FormData();
        fd.append("model", file);
        fd.append("process", process);
        if (file.name) fd.append("name", file.name);
        const res = await fetch(`${backendUrl}/design/import-cad`, {
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
          error instanceof Error ? error.message : "Failed to import CAD file.",
        );
      } finally {
        setCreating(false);
      }
    },
    [backendUrl, process],
  );

  const onImportOnshape = useCallback(async () => {
    const url = onshapeUrl.trim();
    if (!url) {
      setOnshapeError("Paste an Onshape Part Studio or Assembly URL first.");
      return;
    }
    setOnshapeImporting(true);
    setCreateError(null);
    setOnshapeError(null);
    try {
      const res = await fetch(`${backendUrl}/integrations/onshape/import-step`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          url,
          element_kind: onshapeElementKind,
          process,
        }),
      });
      if (!res.ok) {
        let detail = `Onshape import failed: ${res.status}`;
        try {
          const payload = await res.json();
          detail = typeof payload?.detail === "string" ? payload.detail : detail;
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
      setOnshapeUrl("");
    } catch (error) {
      setOnshapeError(
        error instanceof Error ? error.message : "Failed to import from Onshape.",
      );
    } finally {
    setOnshapeImporting(false);
    }
  }, [backendUrl, onshapeElementKind, onshapeUrl, process]);

  const onTraceJewelrySketch = useCallback(async (repairsOverride?: string[]) => {
    const referenceMm = Number(jewelryReferenceMm);
    setJewelryError(null);
    setCreateError(null);
    if (!jewelryReferenceImage) {
      setJewelryError("Upload a sketch/photo or generate a concept first.");
      return;
    }
    if (!Number.isFinite(referenceMm) || referenceMm <= 0) {
      setJewelryError("Add one real measurement in millimeters before tracing.");
      return;
    }

    const form = new FormData();
    form.append("image", jewelryReferenceImage);
    form.append("reference_mm", String(referenceMm));
    form.append("reference_label", jewelryReferenceLabel.trim() || "overall width");
    form.append("context", jewelryContext.trim() || "Freeform jewelry");
    form.append("brief", jewelryBrief.trim() || prompt.trim());
    form.append("profile_id", jewelryProfileId);
    form.append("repairs", (repairsOverride ?? jewelryRepairs).join(","));
    form.append("trace_mode", jewelryTraceMode);
    form.append("detail", jewelryTraceDetail);
    setJewelryStatus("tracing");
    try {
      const res = await fetchWithTimeout(
        `${backendUrl}/design/jewelry/trace-preview`,
        { method: "POST", body: form },
        60000,
      );
      if (!res.ok) {
        let detail = `Jewelry trace failed: ${res.status}`;
        try {
          const payload = await res.json();
          detail =
            typeof payload?.detail === "string"
              ? payload.detail
              : payload?.detail?.message ?? detail;
        } catch {
          // keep status detail
        }
        throw new Error(detail);
      }
      setJewelryTrace((await res.json()) as JewelryTracePreview);
    } catch (error) {
      setJewelryTrace(null);
      setJewelryError(error instanceof Error ? error.message : "Failed to trace jewelry sketch.");
    } finally {
      setJewelryStatus("idle");
    }
  }, [
    backendUrl,
    jewelryBrief,
    jewelryContext,
    jewelryProfileId,
    jewelryReferenceImage,
    jewelryReferenceLabel,
    jewelryReferenceMm,
    jewelryRepairs,
    jewelryTraceDetail,
    jewelryTraceMode,
    prompt,
  ]);

  const onGenerateJewelryConcepts = useCallback(async () => {
    const brief = jewelryBrief.trim() || prompt.trim();
    setJewelryError(null);
    if (!brief) {
      setJewelryError("Describe the jewelry idea first.");
      return;
    }
    setJewelryStatus("concepts");
    try {
      const res = await fetchWithTimeout(
        `${backendUrl}/design/jewelry/concepts`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            prompt: brief,
            context: jewelryContext,
            profile_id: jewelryProfileId,
            count: 3,
          }),
        },
        150000,
      );
      if (!res.ok) {
        let detail = `Concept generation failed: ${res.status}`;
        try {
          const payload = await res.json();
          detail = typeof payload?.detail === "string" ? payload.detail : detail;
        } catch {
          // keep
        }
        throw new Error(detail);
      }
      const payload = await res.json();
      if (payload.configured === false) {
        throw new Error(payload.message || "OpenAI image generation is not configured.");
      }
      setJewelryConcepts(payload.concepts ?? []);
    } catch (error) {
      setJewelryError(error instanceof Error ? error.message : "Failed to generate concepts.");
    } finally {
      setJewelryStatus("idle");
    }
  }, [backendUrl, jewelryBrief, jewelryContext, jewelryProfileId, prompt]);

  const onUseJewelryConcept = useCallback(async (concept: JewelryConcept) => {
    try {
      const res = await fetch(concept.image_url);
      const blob = await res.blob();
      const file = new File([blob], `${concept.id}.png`, { type: blob.type || "image/png" });
      setJewelryReferenceImage(file);
      setJewelryTrace(null);
    } catch {
      setJewelryError("Could not load the generated concept as a trace image.");
    }
  }, []);

  const onApplyJewelryRepair = useCallback(
    async (repairId: string) => {
      const next = Array.from(new Set([...jewelryRepairs, repairId]));
      setJewelryRepairs(next);
      await onTraceJewelrySketch(next);
    },
    [jewelryRepairs, onTraceJewelrySketch],
  );

  const onSetContourRole = useCallback((contourId: string, role: JewelryRole) => {
    setJewelryTrace((current) =>
      current
        ? {
            ...current,
            contours: current.contours.map((contour) =>
              contour.id === contourId ? { ...contour, role } : contour,
            ),
          }
        : current,
    );
  }, []);

  const onCreateJewelryCad = useCallback(async () => {
    if (!jewelryTrace) return;
    setJewelryStatus("creating");
    setCreating(true);
    setJewelryError(null);
    try {
      const res = await fetch(`${backendUrl}/design/jewelry/create-from-trace`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          trace: jewelryTrace,
          process: "either",
          name: `${jewelryContext || "Jewelry"} relief`,
        }),
      });
      if (!res.ok) {
        let detail = `Jewelry CAD creation failed: ${res.status}`;
        try {
          const payload = await res.json();
          detail =
            typeof payload?.detail === "string"
              ? payload.detail
              : payload?.detail?.message ?? detail;
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
        process: payload.process ?? "either",
        script: payload.script,
        parameters: payload.parameters ?? [],
        features: payload.features ?? [],
        latest_build: payload.initial_build ?? null,
        printer_profile_id: payload.printer_profile_id ?? null,
      });
      if (typeof window !== "undefined") {
        const url = new URL(window.location.href);
        url.searchParams.set("design", payload.design_id);
        window.history.replaceState({}, "", url.toString());
      }
    } catch (error) {
      setJewelryError(error instanceof Error ? error.message : "Failed to create jewelry CAD.");
    } finally {
      setCreating(false);
      setJewelryStatus("idle");
    }
  }, [backendUrl, jewelryContext, jewelryTrace]);

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
    const artifactVersion = design?.latest_build?.mesh_hash || design?.revision_id;
    const v = artifactVersion ? `${artifactVersion}-assembly-v1` : null;
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
  const hardPrintIssues = issues.filter((issue) => issue.severity === "error");
  const autoHandledPrintIssues = issues.filter((issue) => issue.severity !== "error");
  const controlParameters = useMemo(() => {
    const priority = [
      "wheel_diameter",
      "track_width",
      "rung_count",
      "spoke_count",
      "tread_thickness",
    ];
    return [...(design?.parameters ?? [])].sort((left, right) => {
      const leftIndex = priority.indexOf(left.name);
      const rightIndex = priority.indexOf(right.name);
      if (leftIndex === -1 && rightIndex === -1) return 0;
      if (leftIndex === -1) return 1;
      if (rightIndex === -1) return -1;
      return leftIndex - rightIndex;
    });
  }, [design?.parameters]);
  const selectedManufacturabilityIssue =
    selectedManufacturabilityIssueIndex === null ? null : issues[selectedManufacturabilityIssueIndex] ?? null;
  const selectedManufacturabilityPoint = selectedManufacturabilityIssue?.location
    ? cadPointToViewer({
        x: selectedManufacturabilityIssue.location[0],
        y: selectedManufacturabilityIssue.location[1],
        z: selectedManufacturabilityIssue.location[2],
      })
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
      setSelectedTopologyRef(payload.topologyRef);
      if (featureId) {
        setSelectedFeatureId(featureId);
        setSelectedFeaturePoint(payload.point);
        setSelectedManufacturabilityIssueIndex(null);
      } else {
        setSelectedFeatureId(null);
        setSelectedFeaturePoint(payload.point);
        setSelectedManufacturabilityIssueIndex(null);
      }
    },
    [design]
  );

  if (!design) {
    return (
      <main style={shellStyle}>
        <style>{responsiveCss}</style>
        <header style={headerStyle}>
          <div>
            <p style={eyebrowStyle}>PULSAI · DESIGN STUDIO (BETA)</p>
            <h1 style={titleStyle}>{tx("Zaprojektuj. Zobacz. Wydrukuj.", "Design. Preview. Print.")}</h1>
            <p style={subtitleStyle}>
              {tx(
                "Rozmawiaj z Pulsai jak z projektantem. Model, rozmowa i parametry pozostają razem od pierwszego pomysłu do wydruku.",
                "Talk to Pulsai like a designer. Your model, conversation and parameters stay together from the first idea to the final print.",
              )}
            </p>
          </div>
          <div style={headerActionsStyle}>
            <LanguageSwitcher language={uiLanguage} onChange={setUiLanguage} />
          </div>
        </header>

        <details style={{ ...jewelryCardStyle, order: 2 }}>
          <summary style={advancedSummaryStyle}>Jewelry, relief and sketch workflow</summary>
          <div style={jewelryHeaderStyle}>
            <div>
              <p style={eyebrowStyle}>JEWELRY / RELIEF CAD</p>
              <h2 style={{ margin: 0, fontSize: 18 }}>Sketch or concept to editable relief</h2>
            </div>
            <span style={jewelryBadgeStyle}>Preview before CAD</span>
          </div>
          <p style={{ margin: 0, fontSize: 12, opacity: 0.72, lineHeight: 1.45 }}>
            Use this for pendants, charms, earrings, medallions, brooches, and flat relief art. Confirm the 2D trace before Pulsai creates the 3D model.
          </p>

          <div style={jewelryGridStyle}>
            <label style={fieldLabelStyle}>
              Type
              <select value={jewelryContext} onChange={(e) => setJewelryContext(e.target.value)} style={compactInputStyle} disabled={creating}>
                {JEWELRY_CONTEXTS.map((context) => (
                  <option key={context} value={context}>{context}</option>
                ))}
              </select>
            </label>
            <label style={fieldLabelStyle}>
              Profile
              <select value={jewelryProfileId} onChange={(e) => setJewelryProfileId(e.target.value)} style={compactInputStyle} disabled={creating}>
                {(jewelryProfiles.length ? jewelryProfiles : [{ id: "resin_print", label: "Resin print", build_intent: "resin_print", min_width_mm: 0.8, min_cutout_mm: 0.6, base_thickness_mm: 2 }]).map((profile) => (
                  <option key={profile.id} value={profile.id}>{profile.label}</option>
                ))}
              </select>
            </label>
            <label style={fieldLabelStyle}>
              Reference
              <input value={jewelryReferenceLabel} onChange={(e) => setJewelryReferenceLabel(e.target.value)} style={compactInputStyle} disabled={creating} />
            </label>
            <label style={fieldLabelStyle}>
              mm
              <input value={jewelryReferenceMm} onChange={(e) => setJewelryReferenceMm(e.target.value)} inputMode="decimal" placeholder="35" style={compactInputStyle} disabled={creating} />
            </label>
          </div>

          <textarea
            value={jewelryBrief}
            onChange={(e) => setJewelryBrief(e.target.value)}
            rows={2}
            placeholder="Art nouveau tree pendant with flowers, readable at 35mm, strong connected branches"
            style={textareaStyle}
            disabled={creating}
          />

          <div style={jewelryUploadRowStyle}>
            <label style={{ ...chipButtonStyle, cursor: creating ? "wait" : "pointer" }}>
              {jewelryReferenceImage ? "Change image" : "Upload sketch/photo"}
              <input
                type="file"
                accept="image/*"
                disabled={creating}
                onChange={(e) => {
                  setJewelryReferenceImage(e.target.files?.[0] ?? null);
                  setJewelryTrace(null);
                  e.target.value = "";
                }}
                style={{ display: "none" }}
              />
            </label>
            <button type="button" onClick={onGenerateJewelryConcepts} disabled={creating || jewelryStatus !== "idle"} style={chipButtonStyle}>
              {jewelryStatus === "concepts" ? "Generating…" : "Generate concepts"}
            </button>
            {jewelryReferenceImage ? (
              <>
                <select
                  value={jewelryTraceMode}
                  onChange={(e) => setJewelryTraceMode(e.target.value)}
                  disabled={creating || jewelryStatus !== "idle"}
                  style={compactInputStyle}
                  aria-label="Trace mode"
                >
                  {JEWELRY_TRACE_MODES.map((mode) => (
                    <option key={mode.value} value={mode.value}>
                      {mode.label}
                    </option>
                  ))}
                </select>
                <select
                  value={jewelryTraceDetail}
                  onChange={(e) => setJewelryTraceDetail(e.target.value)}
                  disabled={creating || jewelryStatus !== "idle"}
                  style={compactInputStyle}
                  aria-label="Trace detail"
                >
                  {JEWELRY_TRACE_DETAILS.map((detail) => (
                    <option key={detail.value} value={detail.value}>
                      {detail.label}
                    </option>
                  ))}
                </select>
              </>
            ) : null}
            <button type="button" onClick={() => onTraceJewelrySketch()} disabled={!jewelryReferenceImage || creating || jewelryStatus !== "idle"} style={primaryButtonStyle}>
              {jewelryStatus === "tracing" ? "Tracing…" : "Trace preview"}
            </button>
            {jewelryReferenceImage ? (
              <button type="button" onClick={() => { setJewelryReferenceImage(null); setJewelryTrace(null); }} disabled={creating} style={chipButtonStyle}>
                Remove image
              </button>
            ) : null}
          </div>

          {jewelryConcepts.length > 0 ? (
            <div style={conceptGridStyle}>
              {jewelryConcepts.map((concept) => (
                <button key={concept.id} type="button" onClick={() => onUseJewelryConcept(concept)} style={conceptCardStyle}>
                  <img src={concept.image_url} alt="Generated jewelry concept" style={conceptImageStyle} />
                  <span>Use concept</span>
                </button>
              ))}
            </div>
          ) : null}

          {jewelryTrace ? (
            <div style={tracePreviewPanelStyle}>
              <div style={tracePreviewMetaStyle}>
                <strong>Score {jewelryTrace.score.value}/100</strong>
                <span>{jewelryTrace.contours.length} contours</span>
                <span>{jewelryTrace.graph.nodes.filter((n) => n.disconnected).length} islands</span>
                {jewelryTrace.trace_mode ? <span>{jewelryTrace.trace_mode.replaceAll("_", " ")}</span> : null}
                {jewelryTrace.trace_detail ? <span>{jewelryTrace.trace_detail}</span> : null}
              </div>
              <JewelryTraceSvg trace={jewelryTrace} />
              {jewelryTrace.warnings.length > 0 ? (
                <div style={traceWarningListStyle}>
                  {jewelryTrace.warnings.slice(0, 3).map((warning, idx) => (
                    <span key={`${warning.code}-${idx}`}>{warning.message}</span>
                  ))}
                </div>
              ) : (
                <p style={jewelryStatusStyle}>Trace looks usable for the selected profile.</p>
              )}
              <div style={jewelryUploadRowStyle}>
                {jewelryTrace.repair_suggestions.map((repair) => (
                  <button key={repair.id} type="button" onClick={() => onApplyJewelryRepair(repair.id)} disabled={creating || jewelryStatus !== "idle"} style={chipButtonStyle}>
                    {repair.label}
                  </button>
                ))}
                <button type="button" onClick={onCreateJewelryCad} disabled={creating || jewelryStatus !== "idle"} style={primaryButtonStyle}>
                  {jewelryStatus === "creating" ? "Creating CAD…" : "Create editable CAD"}
                </button>
              </div>
              <div style={contourRoleGridStyle}>
                {jewelryTrace.contours.slice(0, 10).map((contour) => (
                  <label key={contour.id} style={contourRoleStyle}>
                    <span>{contour.id}</span>
                    <select value={contour.role} onChange={(e) => onSetContourRole(contour.id, e.target.value as JewelryRole)} style={compactInputStyle}>
                      <option value="base_metal">metal</option>
                      <option value="cutout">cutout</option>
                      <option value="raised_relief">raised</option>
                      <option value="engraving">engrave</option>
                      <option value="ignore">ignore</option>
                    </select>
                  </label>
                ))}
              </div>
            </div>
          ) : null}

          {jewelryStatus !== "idle" ? (
            <p style={jewelryStatusStyle}>
              {jewelryStatus === "concepts" ? "Generating clean black/white concept cards." : jewelryStatus === "tracing" ? "Extracting semantic contours." : "Building editable 2.5D CAD."}
            </p>
          ) : null}

          {jewelryError ? <p style={jewelryErrorStyle}>{jewelryError}</p> : null}

          {jewelryReferencePreview ? (
            <img src={jewelryReferencePreview} alt="Jewelry sketch reference" style={jewelryPreviewStyle} />
          ) : null}
        </details>

        <div className="pulsai-start-studio-grid" style={startStudioGridStyle}>
        <section className="pulsai-start-chat-pane" style={startChatPaneStyle}>
          <div>
            <p style={{ ...eyebrowStyle, color: "#70c6ff", opacity: 1 }}>PULSAI COPILOT</p>
            <h2 style={{ margin: "5px 0 5px", fontSize: 22 }}>{tx("Co chcesz zaprojektować?", "What do you want to design?")}</h2>
            <p style={{ margin: 0, fontSize: 12, color: "rgba(238,243,247,0.66)", lineHeight: 1.45 }}>
              {tx("Napisz lub powiedz, czego potrzebujesz. Możesz użyć dowolnego języka.", "Type or say what you need. You can use any language.")}
            </p>
          </div>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            rows={4}
            placeholder={tx("Np. uchwyt na telefon szeroki na 80 mm, z otworem na kabel…", "E.g. an 80 mm phone holder with a cable opening…")}
            style={startChatTextareaStyle}
            disabled={creating}
          />
          <div style={startChatFooterStyle}>
            <SpeechToTextButton
              disabled={creating}
              language={uiLanguage}
              onTranscript={(text) => setPrompt((current) => [current.trim(), text].filter(Boolean).join(" "))}
            />
            <label style={{ fontSize: 11, color: "rgba(238,243,247,0.62)" }}>
              {tx("Wykonanie", "Process")}
              <select
                value={process}
                onChange={(e) => setProcess(e.target.value as typeof process)}
                style={startDarkSelectStyle}
              >
                <option value="fdm">{tx("Druk 3D", "3D printing")}</option>
                <option value="cnc">CNC</option>
                <option value="either">{tx("Jeszcze nie wiem", "Not sure yet")}</option>
              </select>
            </label>
            <button
              type="button"
              onClick={() => onCreate(prompt)}
              disabled={creating || !prompt.trim()}
              style={primaryButtonStyle}
            >
              {creating ? tx("Projektuję…", "Designing…") : tx("Utwórz model", "Create model")}
            </button>
          </div>
          <div style={{ display: "none" }}>
            {TEMPLATE_PROMPTS.map((p) => (
              <button
                key={p.labelEn}
                type="button"
                onClick={() => {
                  setPrompt(p.prompt);
                  onCreate(p.prompt);
                }}
                disabled={creating}
                style={chipButtonStyle}
              >
                {uiLanguage === "pl" ? p.labelPl : p.labelEn}
              </button>
            ))}
          </div>

          <details style={{ display: "none" }}>
            <summary style={advancedSummaryStyle}>Import STEP/STL or connect CAD</summary>
            <div style={advancedStartBodyStyle}>
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 8,
              padding: "10px 12px",
              borderRadius: 10,
              background: "rgba(43,140,122,0.08)",
              border: "1px dashed rgba(43,140,122,0.35)",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
              <strong style={{ fontSize: 13 }}>Import from Onshape</strong>
              <span style={{ fontSize: 11, opacity: 0.65 }}>
                {onshapeStatus?.configured
                  ? `Configured: ${onshapeStatus.mode}`
                  : "Backend needs Onshape API keys or OAuth config"}
              </span>
            </div>
            <span style={{ fontSize: 12, opacity: 0.7 }}>
              Paste a Part Studio or Assembly URL. Pulsai exports STEP from Onshape, then imports it as editable CAD reference.
            </span>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 8, alignItems: "center" }}>
              <input
                value={onshapeUrl}
                onChange={(e) => setOnshapeUrl(e.target.value)}
                placeholder="https://cad.onshape.com/documents/d/.../w/.../e/..."
                style={compactInputStyle}
                disabled={onshapeImporting || creating}
              />
              <select
                value={onshapeElementKind}
                onChange={(e) => setOnshapeElementKind(e.target.value as typeof onshapeElementKind)}
                style={compactInputStyle}
                disabled={onshapeImporting || creating}
              >
                <option value="partstudio">Part Studio</option>
                <option value="assembly">Assembly</option>
              </select>
              <button
                type="button"
                onClick={onImportOnshape}
                disabled={
                  onshapeImporting ||
                  creating ||
                  !onshapeUrl.trim() ||
                  onshapeStatus?.configured === false
                }
                style={primaryButtonStyle}
              >
                {onshapeImporting ? "Importing…" : "Import"}
              </button>
            </div>
            {onshapeError ? (
              <p style={{ color: "rgba(244,67,54,0.95)", fontSize: 12, margin: 0 }}>
                {onshapeError}
              </p>
            ) : null}
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
            <strong style={{ fontSize: 13 }}>Or import an editable CAD file</strong>
            <span style={{ fontSize: 12, opacity: 0.7 }}>
              Ask designers for <code>.step</code>/<code>.stp</code>. STL is a final print mesh, so edits are limited to reconstruction or mesh booleans.
            </span>
            <label style={{ ...chipButtonStyle, marginLeft: "auto", cursor: creating ? "wait" : "pointer" }}>
              {creating ? "Importing…" : "Choose file"}
              <input
                type="file"
                accept=".step,.stp,.stl,application/STEP,application/x-step,application/sla,model/stl"
                disabled={creating}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) onImportCAD(file);
                  e.target.value = "";
                }}
                style={{ display: "none" }}
              />
            </label>
          </div>
            </div>
          </details>
          <details style={{ display: "none" }}>
            <summary style={advancedSummaryStyle}>Browse templates and starter models</summary>
            <div style={advancedStartBodyStyle}>
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
            </div>
          </details>
          {createError ? (
            <p style={{ color: "#ff9d9d", fontSize: 12 }}>
              {createError}
            </p>
          ) : null}
        </section>

        <section className="pulsai-start-viewer-pane" style={startViewerPaneStyle} aria-label={tx("Podgląd modelu 3D", "3D model preview")}>
          <div style={startViewerGridStyle} aria-hidden="true" />
          <div style={startViewerAxisStyle} aria-hidden="true">
            <span style={{ color: "#ff7676" }}>X</span>
            <span style={{ color: "#71d28d" }}>Y</span>
            <span style={{ color: "#6ea8ff" }}>Z</span>
          </div>
          {creating ? (
            <div style={startCreatingStyle} role="status" aria-live="polite">
              <span style={startCreatingSpinnerStyle} aria-hidden />
              <strong>{tx("Buduję parametryczny model…", "Building a parametric model…")}</strong>
              <span>{tx("Interpretuję wymiary, tworzę geometrię i przygotowuję podgląd GLB.", "Interpreting dimensions, creating geometry and preparing the 3D preview.")}</span>
              <small>{tx("Przy złożonych częściach może to potrwać kilkadziesiąt sekund.", "Complex parts may take several dozen seconds.")}</small>
            </div>
          ) : openingDeepLink ? (
            <div style={startCreatingStyle} role="status" aria-live="polite">
              <span style={startCreatingSpinnerStyle} aria-hidden />
              <strong>{tx("Otwieram zapisany projekt…", "Opening saved design…")}</strong>
            </div>
          ) : (
            <div style={startViewerEmptyStyle}>
              <div style={startViewerObjectStyle} aria-hidden="true" />
              <strong>{tx("Tu pojawi się Twój model", "Your model will appear here")}</strong>
              <span>{tx("Podgląd pozostaje widoczny podczas całej rozmowy i każdej poprawki.", "The preview stays visible throughout the conversation and every edit.")}</span>
            </div>
          )}
          <span style={startViewerModeStyle}>{tx("TRYB: ORBITA", "MODE: ORBIT")}</span>
        </section>

        <aside className="pulsai-start-tools-pane" style={startToolsPaneStyle}>
          <div>
            <p style={eyebrowStyle}>{tx("SZYBKI START", "QUICK START")}</p>
            <h3 style={{ margin: "4px 0 3px", fontSize: 17 }}>{tx("Przykładowe projekty", "Example designs")}</h3>
            <p style={{ margin: 0, fontSize: 11, opacity: 0.58 }}>{tx("Kliknij przykład albo opisz własny pomysł w czacie.", "Choose an example or describe your own idea in chat.")}</p>
          </div>
          <div style={startToolsListStyle}>
            {TEMPLATE_PROMPTS.map((item) => (
              <button
                key={item.labelEn}
                type="button"
                onClick={() => setPrompt(item.prompt)}
                disabled={creating}
                style={startToolButtonStyle}
              >
                <span>{uiLanguage === "pl" ? item.labelPl : item.labelEn}</span><span aria-hidden="true">→</span>
              </button>
            ))}
          </div>
          <details style={startToolsDetailsStyle}>
            <summary style={advancedSummaryStyle}>{tx("Importuj STEP lub STL", "Import STEP or STL")}</summary>
            <div style={advancedStartBodyStyle}>
              <label style={{ ...startToolButtonStyle, cursor: creating ? "wait" : "pointer" }}>
                {creating ? tx("Importuję…", "Importing…") : tx("Wybierz plik CAD", "Choose CAD file")}
                <input
                  type="file"
                  accept=".step,.stp,.stl,application/STEP,application/x-step,application/sla,model/stl"
                  disabled={creating}
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    if (file) onImportCAD(file);
                    event.target.value = "";
                  }}
                  style={{ display: "none" }}
                />
              </label>
            </div>
          </details>
          <details style={startToolsDetailsStyle}>
            <summary style={advancedSummaryStyle}>{tx("Szablony parametryczne", "Parametric templates")}</summary>
            <div style={advancedStartBodyStyle}>
              {templates.map((template) => (
                <button key={template.template_id} type="button" onClick={() => onCreate("", template.template_id)} disabled={creating} style={startToolButtonStyle}>
                  {template.name}
                </button>
              ))}
            </div>
          </details>
          {recentDesigns.length > 0 ? (
            <button type="button" onClick={() => openDesign(recentDesigns[0].design_id)} style={startRecentButtonStyle}>
              <span>{tx("Ostatni projekt", "Latest design")}</span>
              <strong>{recentDesigns[0].name || tx("Bez nazwy", "Untitled")}</strong>
            </button>
          ) : null}
        </aside>
        </div>

        {recentDesigns.length > 0 ? (
          <section style={{ ...createCardStyle, order: 3 }}>
            <h2 style={{ margin: 0, fontSize: 16 }}>{tx("Twoje projekty", "Your designs")}</h2>
            <p style={{ margin: 0, fontSize: 12, opacity: 0.65 }}>
              {tx(
                `${recentDesigns.length} zapisanych na tym urządzeniu. Kliknij, aby otworzyć wraz z historią zmian.`,
                `${recentDesigns.length} saved on this device. Click to reopen with its edit history.`,
              )}
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

        <section style={{ ...infoCardStyle, order: 4 }}>
          <strong>{tx("Co wyróżnia Pulsai", "Why this is different")}</strong>
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
            {tx("wersja", "revision")} <code>{design.revision_id.slice(0, 8)}</code> ·
            {" "}
            {design.parameters.length} {tx("parametrów", "parameters")} · {design.features.length} {tx("cech", "features")} · {tx("proces", "target")}: <strong>{design.process}</strong>
          </p>
        </div>
        <div style={headerActionsStyle}>
          <LanguageSwitcher language={uiLanguage} onChange={setUiLanguage} />
          {printerCatalog && printerCatalog.profiles.length > 0 ? (
            <label style={printerPickerStyle} title="Manufacturability checks and slicer profile use this printer.">
              <span style={printerPickerLabelStyle}>{tx("Drukarka", "Printer")}</span>
              <select
                value={
                  design.printer_profile_id || printerCatalog.defaultId || ""
                }
                onChange={async (e) => {
                  const profileId = e.target.value;
                  try {
                    const res = await fetch(
                      `${backendUrl}/design/${design.design_id}/printer`,
                      {
                        method: "POST",
                        headers: { "content-type": "application/json" },
                        body: JSON.stringify({ profile_id: profileId }),
                      },
                    );
                    if (res.ok) {
                      const payload = await res.json().catch(() => null);
                      setDesign((current) =>
                        current && current.design_id === design.design_id
                          ? {
                              ...current,
                              printer_profile_id: profileId,
                              latest_build: payload?.build ?? current.latest_build,
                            }
                          : current,
                      );
                      await refreshDesign(design.design_id);
                    }
                  } catch {
                    // Network blip — leave the dropdown showing the previous value
                    // on next render via refreshDesign.
                  }
                }}
                style={printerSelectStyle}
              >
                {printerCatalog.profiles.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label}
                  </option>
                ))}
              </select>
              <span style={printerPickerHintStyle}>
                {tx("Nie ma Twojej? Wybierz najbliższy rozmiar stołu i dyszy.", "Missing yours? Pick the closest bed and nozzle size.")}
              </span>
            </label>
          ) : null}
          <button type="button" style={backButtonStyle} onClick={returnToStart}>
            {tx("Nowy szkic biżuterii", "New jewelry sketch")}
          </button>
          <button type="button" style={backButtonStyle} onClick={returnToStart}>
            {tx("← Wróć do projektów", "← Back to designs")}
          </button>
        </div>
      </header>

      <section style={threePaneStyle} className="pulsai-studio-grid">
        <aside style={parametersPaneStyle} className="pulsai-parameters-pane">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div>
              <h3 style={{ ...paneHeaderStyle, margin: "0 0 2px" }}>{tx("Parametry", "Controls")}</h3>
              <span style={paneHintStyle}>{tx("Zmień model bez pisania promptu.", "Change the model without writing a prompt.")}</span>
            </div>
            <label style={liveToggleStyle} title="Live preview re-renders the model on slider drag (uses more compute)">
              <input
                type="checkbox"
                checked={livePreview}
                onChange={(e) => setLivePreview(e.target.checked)}
              />
              {tx("na żywo", "live")}
            </label>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {controlParameters.slice(0, showAllParameters ? controlParameters.length : 4).map((p) => (
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
            {design.parameters.length > 4 ? (
              <button
                type="button"
                onClick={() => setShowAllParameters((current) => !current)}
                style={showMoreParametersStyle}
              >
                {showAllParameters
                  ? tx("Pokaż mniej", "Show fewer controls")
                  : tx(`Pokaż jeszcze ${design.parameters.length - 4}`, `Show ${design.parameters.length - 4} more controls`)}
              </button>
            ) : null}
          </div>

          <h3 style={paneHeaderStyle}>{tx("Cechy modelu", "Features")}</h3>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {design.features.map((f) => {
              const isSelected = selectedFeatureId === f.id;
              return (
                <button
                  key={f.id || f.name}
                  type="button"
                  onClick={() => selectFeature(f.id)}
                  style={{
                    ...paramRowStyle,
                    cursor: "pointer",
                    textAlign: "left",
                    border: isSelected
                      ? "1px solid rgba(33,150,243,0.7)"
                      : "1px solid transparent",
                  }}
                  title={`${f.name} — kind ${f.kind}, id ${f.id}. Click to scope the next chat edit.`}
                  aria-label={`Feature ${f.name}, kind ${f.kind}`}
                  aria-pressed={isSelected}
                >
                  <span style={{ fontSize: 12, fontWeight: 600 }}>{f.name}</span>
                </button>
              );
            })}
            {design.features.length === 0 ? (
              <span style={{ fontSize: 12, opacity: 0.55 }}>(no @feature blocks)</span>
            ) : null}
          </div>

          <h3 style={paneHeaderStyle}>{tx("Przygotowanie do druku", "Print readiness")}</h3>
          {health && !health.slicer_ready ? (
            <div style={slicerHintStyle} role="note">
              Przygotowanie G-code jest chwilowo niedostępne. Nadal możesz pobrać STL.
            </div>
          ) : null}
          {(() => {
            const orient = design.latest_build?.manufacturability?.suggested_orientation;
            const current = design.latest_build?.manufacturability?.current_overhang_fraction;
            if (!orient || current == null) return null;
            const askDisabled = stream.state.status === "streaming" || makePrintable.busy;
            return (
              <div style={orientationHintStyle} role="note">
                <div>
                  Current orientation has{" "}
                  <strong>~{Math.round(current * 100)}% overhang</strong>.
                  Reorienting (<em>{orient.label}</em>,
                  Euler {orient.euler_deg.map((d) => `${d.toFixed(0)}°`).join(", ")})
                  would drop it to{" "}
                  <strong>~{Math.round(orient.overhang_fraction * 100)}%</strong>.
                </div>
                <button
                  type="button"
                  disabled={askDisabled}
                  style={orientationActionStyle(askDisabled)}
                  onClick={() => {
                    if (askDisabled) return;
                    const [rx, ry, rz] = orient.euler_deg;
                    const message =
                      `Apply this print-orientation suggestion: rotate the part using Euler ` +
                      `XYZ (${rx.toFixed(0)}°, ${ry.toFixed(0)}°, ${rz.toFixed(0)}°) so its overhang ` +
                      `drops from ~${Math.round((current ?? 0) * 100)}% to ~${Math.round(orient.overhang_fraction * 100)}%. ` +
                      `Use auto_orient_for_fdm or insert a rotation in the script — pick the smallest edit. ` +
                      `Then rebuild and re-check manufacturability.`;
                    stream.send(message, {
                      selectedFeatureId: selectedFeature?.id ?? null,
                      selectedFeatureLabel: selectedFeature?.name ?? null,
                      selectedTopologyRef,
                    });
                  }}
                >
                  Try this orientation
                </button>
              </div>
            );
          })()}
          {status ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <span style={statusBadgeStyle(status)}>{printStatusLabel(status)}</span>
              <span style={printReadinessCopyStyle}>
                {status === "safe"
                  ? "Model przeszedł kontrolę i jest gotowy do przygotowania."
                  : status === "warn"
                    ? `Możesz drukować. Pulsai obsłuży ${autoHandledPrintIssues.length === 1 ? "to ostrzeżenie" : "te ostrzeżenia"} w ustawieniach slicera.`
                    : "Jeszcze nie drukuj. Pulsai musi najpierw usunąć błąd geometrii."}
              </span>
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
                    selectedTopologyRef,
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
                            {tx("Pokaż", "Locate")}
                          </button>
                        ) : null}
                        {issue.severity === "error" ? (
                          <button
                            type="button"
                            style={issueFixButtonStyle(fixDisabled)}
                            disabled={fixDisabled}
                            title="Poproś Pulsai o kontrolowaną poprawkę"
                            onClick={fixThisIssue}
                          >
                            {stream.state.status === "streaming" ? "Naprawiam…" : "Napraw"}
                          </button>
                        ) : null}
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
            disabled={makePrintable.busy || stream.state.status === "streaming"}
            onClick={async () => {
              if (status === "unprintable" && hardPrintIssues.length > 0) {
                const problemList = hardPrintIssues
                  .map((issue) => `${issue.code}: ${issue.message}`)
                  .join("; ");
                stream.send(
                  `Przygotuj model do bezpiecznego druku i usuń te potwierdzone błędy: ${problemList}. ` +
                    `Najpierw wybierz najmniejszą odwracalną poprawkę. Nie zmieniaj wymiarów funkcjonalnych ani przeznaczenia modelu bez mojej zgody; jeśli to konieczne, wyjaśnij krótko zmianę i zapytaj przed jej wykonaniem. Po poprawce zbuduj model raz i ponownie sprawdź drukowalność.`,
                );
                return;
              }
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
                await refreshDesign(design.design_id);
              } catch (error) {
                setMakePrintable({
                  busy: false,
                  error: error instanceof Error ? error.message : "FDM export failed.",
                });
              }
            }}
          >
            {makePrintable.busy
              ? "Przygotowuję…"
              : status === "unprintable"
                ? "Napraw przed drukiem"
                : "Przygotuj do druku"}
          </button>
          <span style={exportHintStyle}>
            {status === "warn"
              ? "Automatycznie dodam potrzebne podpory, wygeneruję G-code oraz podam czas i materiał."
              : "Sprawdzę model, wygeneruję G-code oraz podam czas i zużycie materiału."}
          </span>
          {makePrintable.summary ? (
            <span style={makePrintableResultStyle(makePrintable.status)}>
              {makePrintable.summary}
              {makePrintable.bundleUrl ? (
                <>
                  {" "}
                  <a href={makePrintable.bundleUrl} target="_blank" rel="noopener noreferrer">
                    Pobierz pakiet
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
              <h3 style={paneHeaderStyle}>{tx("Szacowany wydruk", "Print estimate")}</h3>
              <PrintEstimatePanel estimate={design.latest_build.print_estimate} language={uiLanguage} />
            </>
          ) : null}
        </aside>

        <section style={canvasPaneStyle} className="pulsai-canvas-pane">
          {buildArtifactUrl ? (
            <ModelViewer
              src={buildArtifactUrl}
              label={design.name}
              motionReport={design.motion_report}
              isUpdating={Boolean(stream.state.previewUpdating)}
              language={uiLanguage}
              defaultCameraPreset="iso"
              onSelect={handleViewerSelect}
              onClearSelection={() => {
                setSelectedFeatureId(null);
                setSelectedFeaturePoint(null);
                setSelectedTopologyRef(null);
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
                selectedManufacturabilityPoint
                  ? { point: selectedManufacturabilityPoint }
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
                      setSelectedTopologyRef(null);
                    }}
                  />
                ) : null
              }
            />
          ) : (
            <div style={emptyCanvasStyle}>Build artifact missing.</div>
          )}
          {design.latest_build?.print_estimate ? (
            <PrintResultCard
              estimate={design.latest_build.print_estimate}
              language={uiLanguage}
              gcodeUrl={resolveArtifactUrl(backendUrl, design.latest_build.artifacts?.gcode)}
              bundleUrl={makePrintable.bundleUrl}
            />
          ) : null}
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

        <aside style={chatPaneStyle} className="pulsai-chat-pane">
          <div style={chatPaneHeaderStyle}>
            <div style={chatIdentityStyle}>
              <span style={chatBrandMarkStyle} aria-hidden>P</span>
              <div>
                <strong style={chatTitleStyle}>Pulsai</strong>
                <span style={chatSubtitleStyle}>{tx("Projektant CAD", "CAD designer")}</span>
              </div>
            </div>
            <div style={chatHeaderMetaStyle}>
              <span style={sessionCostStyle} title="Dokładny koszt tokenów Claude w tej sesji">
                {tx("Sesja", "Session")} {formatUsd(sessionCost)}
              </span>
              <span style={chatOnlineStyle} role="status" aria-live="polite">
                {stream.state.status === "streaming" ? tx("pracuje", "working") : stream.state.status === "error" ? tx("błąd", "error") : tx("gotowy", "ready")}
              </span>
            </div>
          </div>
          {stream.state.status === "streaming" ? (
            <div style={agentProgressStyle} role="status" aria-live="polite">
              <span style={agentProgressDotStyle} aria-hidden />
              <strong>{displayModelName(stream.state.model)}</strong>
              <span style={{ opacity: 0.62 }}>·</span>
              <span>{stream.state.activity ?? tx("Pracuję nad projektem…", "Working on the design…")}</span>
            </div>
          ) : null}
          <div style={historyStyle}>
            {!stream.hydrated ? (
              <div style={emptyChatStyle} role="status">
                <span style={agentProgressDotStyle} aria-hidden />
                <p>{tx("Wczytuję rozmowę…", "Loading conversation…")}</p>
              </div>
            ) : stream.history.length === 0 ? (
              <div style={emptyChatStyle}>
                <span style={emptyChatMarkStyle} aria-hidden>P</span>
                <strong>{tx("Co zmieniamy?", "What should we change?")}</strong>
                <p>{tx("Opisz zmianę, wskaż element w modelu albo dodaj zdjęcie referencyjne.", "Describe a change, select a model feature, or add a reference image.")}</p>
              </div>
            ) : (
              stream.history.map((entry, idx) => (
                <ChatMessage key={idx} entry={entry} />
              ))
            )}
            <div ref={chatEndRef} />
          </div>
          <DesignChatInput
            backendUrl={backendUrl}
            designId={design.design_id}
            onExternalCost={(cost) => setExternalSessionCost((current) => current + cost)}
            disabled={stream.state.status === "streaming"}
            selectedFeature={selectedFeature}
            parameters={design.parameters}
            language={uiLanguage}
            onCancel={stream.cancel}
            onSend={(text) =>
              stream.send(text, {
                selectedFeatureId: selectedFeature?.id ?? null,
                selectedFeatureLabel: selectedFeature?.name ?? null,
                selectedTopologyRef,
              })
            }
            onApplyDirect={async (text, edit) => {
              const before = design.parameters.find((p) => p.name === edit.name)?.value;
              try {
                const res = await fetch(`${backendUrl}/design/${design.design_id}/parameter`, {
                  method: "POST",
                  headers: { "content-type": "application/json" },
                  body: JSON.stringify({ name: edit.name, value: edit.value }),
                });
                const payload = await res.json().catch(() => null);
                if (!res.ok) {
                  const detail =
                    (payload && typeof payload.detail === "object" && payload.detail.message) ||
                    payload?.detail ||
                    `Direct apply failed: ${res.status}`;
                  stream.appendLocalTurn(text, `✕ ${detail}`);
                  return;
                }
                const newRev = payload?.revision_id ?? null;
                stream.appendLocalTurn(
                  text,
                  `✓ ${edit.name}: ${String(before ?? "?")} → ${edit.value} (direct, $0)`,
                  newRev,
                );
                await refreshDesign(design.design_id);
              } catch (error) {
                stream.appendLocalTurn(
                  text,
                  `✕ ${error instanceof Error ? error.message : "Direct apply failed."}`,
                );
              }
            }}
            isStreaming={stream.state.status === "streaming"}
          />
          {stream.state.status === "error" ? (
            <p style={{ color: "rgba(244,67,54,0.95)", fontSize: 12 }}>
              {stream.state.errorMessage}
            </p>
          ) : null}
        </aside>
      </section>

      <RevisionTimeline
        designId={design.design_id}
        currentRevisionId={design.revision_id}
        onRestore={() => refreshDesign(design.design_id)}
        refreshKey={design.revision_id}
      />

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
        <span style={{ fontSize: 12, opacity: 0.9 }} title={param.name}>
          {humanizeParameterName(param.name)}
        </span>
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
  backendUrl,
  designId,
  onExternalCost,
  onSend,
  onCancel,
  onApplyDirect,
  disabled,
  isStreaming,
  selectedFeature,
  parameters,
  language,
}: {
  backendUrl: string;
  designId: string;
  onExternalCost: (costUsd: number) => void;
  onSend: (text: string) => void;
  onCancel: () => void;
  onApplyDirect: (text: string, edit: { name: string; value: number | boolean | string }) => Promise<void> | void;
  disabled: boolean;
  isStreaming: boolean;
  selectedFeature: Design["features"][number] | null;
  parameters: Design["parameters"];
  language: UiLanguage;
}) {
  const [draft, setDraft] = useState("");
  const [applying, setApplying] = useState(false);
  const [routeBadge, setRouteBadge] = useState<DesignEditBadge | null>(null);
  const [voiceHint, setVoiceHint] = useState<string | null>(null);
  const [referenceImage, setReferenceImage] = useState<File | null>(null);
  const [referencePreview, setReferencePreview] = useState<string | null>(null);
  const [imageState, setImageState] = useState<"idle" | "analyzing" | "ready" | "error">("idle");
  const [imageMessage, setImageMessage] = useState<string | null>(null);
  const imageInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!referenceImage) {
      setReferencePreview(null);
      return;
    }
    const url = URL.createObjectURL(referenceImage);
    setReferencePreview(url);
    return () => URL.revokeObjectURL(url);
  }, [referenceImage]);

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

  const handleApplyDirect = async () => {
    if (!routeBadge?.directEdit || !draft.trim() || disabled || applying) return;
    setApplying(true);
    try {
      await onApplyDirect(draft.trim(), routeBadge.directEdit);
      setDraft("");
    } finally {
      setApplying(false);
    }
  };

  const analyzeReferenceImage = async (file: File) => {
    setReferenceImage(file);
    setImageState("analyzing");
    setImageMessage("Gemini 3.5 Flash-Lite · analizuje zdjęcie");
    try {
      if (!file.type.startsWith("image/")) throw new Error("Wybierz plik obrazu.");
      if (file.size > 12 * 1024 * 1024) throw new Error("Zdjęcie może mieć maksymalnie 12 MB.");
      const form = new FormData();
      form.append("image", file);
      form.append("input_type", "cad_reference");
      form.append("design_id", designId);
      const response = await fetch(`${backendUrl}/image-intent`, { method: "POST", body: form });
      const payload = (await response.json().catch(() => null)) as {
        prompt?: string;
        model?: string;
        input_tokens?: number;
        output_tokens?: number;
        cost_usd?: number;
        detail?: string;
      } | null;
      if (!response.ok || !payload?.prompt) {
        throw new Error(payload?.detail || "Nie udało się przeanalizować zdjęcia.");
      }
      setDraft((current) => {
        const description = `Na podstawie zdjęcia referencyjnego: ${payload.prompt}`;
        return current.trim() ? `${current.trim()}\n\n${description}` : description;
      });
      setImageState("ready");
      const cost = Number(payload.cost_usd ?? 0);
      if (Number.isFinite(cost) && cost > 0) onExternalCost(cost);
      setImageMessage(
        `${displayModelName(payload.model)} opisał zdjęcie${cost > 0 ? ` · ${formatUsd(cost)}` : ""} — sprawdź opis`,
      );
    } catch (error) {
      setImageState("error");
      setImageMessage(error instanceof Error ? error.message : "Nie udało się przeanalizować zdjęcia.");
    }
  };

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (!draft.trim() || disabled) return;
        onSend(draft.trim());
        setDraft("");
        setReferenceImage(null);
        setImageState("idle");
        setImageMessage(null);
      }}
      style={{ display: "flex", flexDirection: "column", gap: 6 }}
    >
      <div style={chatComposerShellStyle}>
        {referenceImage ? (
          <div style={imageAttachmentStyle}>
            {referencePreview ? <img src={referencePreview} alt="Zdjęcie referencyjne" style={imageThumbStyle} /> : null}
            <div style={{ minWidth: 0, flex: 1 }}>
              <strong style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis" }}>{referenceImage.name}</strong>
              <span style={{ color: imageState === "error" ? "#ff8b8b" : "rgba(232,240,247,0.58)" }}>
                {imageMessage}
              </span>
            </div>
            <button
              type="button"
              aria-label="Usuń zdjęcie"
              title="Usuń zdjęcie"
              style={composerIconButtonStyle}
              onClick={() => {
                setReferenceImage(null);
                setImageState("idle");
                setImageMessage(null);
              }}
            >
              ×
            </button>
          </div>
        ) : null}
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          rows={3}
          placeholder={uiText(language, "Napisz do Pulsai…", "Message Pulsai…")}
          disabled={applying}
          aria-describedby={isStreaming ? "chat-streaming-hint" : undefined}
          style={chatTextareaStyle}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && draft.trim() && !disabled) {
              e.preventDefault();
              onSend(draft.trim());
              setDraft("");
              setReferenceImage(null);
              setImageState("idle");
              setImageMessage(null);
            }
          }}
        />
        <div style={chatComposerFooterStyle}>
          <div style={composerToolsStyle}>
            <input
              ref={imageInputRef}
              type="file"
              accept="image/*"
              hidden
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void analyzeReferenceImage(file);
                event.target.value = "";
              }}
            />
            <button
              type="button"
              style={composerIconButtonStyle}
              onClick={() => imageInputRef.current?.click()}
              disabled={applying || imageState === "analyzing"}
              aria-label="Dodaj zdjęcie referencyjne"
              title="Dodaj zdjęcie referencyjne"
            >
              +
            </button>
          <SpeechToTextButton
            compact
            disabled={applying}
            language={language}
            onTranscript={(text) => {
              setDraft((current) => [current.trim(), text].filter(Boolean).join(" "));
              setVoiceHint(uiText(language, "Gotowe — kliknij Wyślij", "Ready — click Send"));
            }}
            onStateChange={(state: VoiceState, message?: string) => {
              if (message) setVoiceHint(message);
              else if (state === "requesting") setVoiceHint(uiText(language, "Uruchamiam mikrofon…", "Starting microphone…"));
              else if (state === "recording") setVoiceHint(uiText(language, "Słucham — kliknij, aby zakończyć", "Listening — click to stop"));
              else if (state === "transcribing") setVoiceHint(uiText(language, "Przepisuję mowę…", "Transcribing…"));
              else setVoiceHint((current) => current?.startsWith("Gotowe") || current?.startsWith("Ready") ? current : null);
            }}
          />
          </div>
          <span style={chatComposerHintStyle}>
            {imageState === "analyzing" ? imageMessage : voiceHint ? voiceHint : selectedFeature ? `Cel: ${selectedFeature.name}` : routeBadge?.label}
          </span>
          {isStreaming ? (
            <button type="button" onClick={onCancel} style={composerSendButtonStyle} aria-label={uiText(language, "Zatrzymaj", "Stop")} title={uiText(language, "Zatrzymaj", "Stop")}>
              ■
            </button>
          ) : routeBadge?.directEdit ? (
            <button
              type="button"
              onClick={handleApplyDirect}
              disabled={disabled || applying || !draft.trim()}
              style={applyDirectButtonStyle}
              title={`${routeBadge.directEdit.name} = ${routeBadge.directEdit.value}, bez wywołania modelu`}
            >
              {applying ? "…" : "$0 · Zastosuj"}
            </button>
          ) : (
            <button
              type="submit"
              disabled={disabled || !draft.trim() || imageState === "analyzing"}
              style={composerSendButtonStyle}
              aria-label={uiText(language, "Wyślij", "Send")}
              title={uiText(language, "Wyślij", "Send")}
            >
              ↑
            </button>
          )}
        </div>
        {isStreaming ? (
          <span id="chat-streaming-hint" style={composerBelowHintStyle}>{uiText(language, "Możesz przygotować następną wiadomość w trakcie pracy.", "You can prepare the next message while Pulsai works.")}</span>
        ) : routeBadge && !routeBadge.directEdit ? (
          <span style={composerBelowHintStyle}>{routeBadge.title} · ok. {routeBadge.costEstimate}</span>
        ) : null}
      </div>
    </form>
  );
}

function humanizeParameterName(name: string) {
  return name
    .replace(/_mm$/i, "")
    .replace(/_deg$/i, " angle")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

type DesignEditBadge = {
  label: string;
  title: string;
  tone: "free" | "cheap" | "full" | "answer";
  /** Rough per-tone cost shown next to the label. Order-of-magnitude, not exact. */
  costEstimate: string;
  /**
   * Set when the input parses cleanly to a single-parameter mutation.
   * The Apply-directly button consumes this to skip the LLM round-trip.
   */
  directEdit?: { name: string; value: number | boolean | string };
};

/**
 * Order-of-magnitude cost per tone. Sourced from observed median per-turn
 * spend in the eval harness (Sonnet 5, routine thinking disabled). Refresh
 * quarterly or when we change the model.
 *  - answer: Claude reads the design, answers in text, no tool calls.
 *  - free:   direct-apply path bypasses the LLM entirely.
 *  - cheap:  one macro tool call (mesh ops, parameter mutation via agent).
 *  - full:   multi-tool agent loop, possibly a rewrite_design.
 */
const COST_BY_TONE: Record<DesignEditBadge["tone"], string> = {
  answer: "$0.01",
  free: "$0.00",
  cheap: "$0.02",
  full: "$0.05",
};

function classifyDesignEditBadge(
  text: string,
  parameters: Design["parameters"],
): DesignEditBadge {
  const lower = text.toLowerCase();
  const normalized = lower.replace(/[^\p{L}\p{N}_%]+/gu, " ").replace(/\s+/g, " ").trim();
  const questionLike =
    /^(why|what|how|can|does|do|is|are|where|which|explain|show|tell|count|measure|analyze|check|dlaczego|co|jak|czy|gdzie|który|która|pokaż|wyjaśnij|zmierz|sprawdź)\b/.test(
      normalized,
    ) || (lower.includes("?") && !/\b(make|set|change|add|remove|delete|split|repair|orient|ustaw|zmień|dodaj|usuń|napraw|obróć)\b/.test(normalized));

  if (questionLike) {
    return {
      label: "Odpowiedź AI",
      title: "Likely explanation or inspection; should not rebuild unless the agent needs a check.",
      tone: "answer",
      costEstimate: COST_BY_TONE.answer,
    };
  }

  const hasEditVerb = /\b(make|set|change|increase|decrease|reduce|shrink|enlarge|scale|thicken|thin|add|remove|delete|drill|cut|replace|move|rotate|fillet|chamfer|ustaw|zmień|zwiększ|zmniejsz|powiększ|pomniejsz|poszerz|zwęż|pogrub|dodaj|usuń|wytnij|zastąp|przesuń|obróć)\b/.test(
    normalized,
  );
  const hasNumericIntent = /\d/.test(normalized) || /\b(twice|double|half|smaller|larger|bigger|thicker|thinner|more|less|podwój|podwójnie|połowę|mniejszy|mniejsza|większy|większa|grubszy|cieńszy|więcej|mniej)\b/.test(normalized);
  const mentionsParam = parameters.some((p) => parameterMatches(normalized, p.name));
  if (mentionsParam && hasEditVerb && hasNumericIntent) {
    const directEdit = parseDirectParamEdit(normalized, parameters);
    return {
      label: "Bez AI",
      title: directEdit
        ? `Ustawi ${directEdit.name} na ${directEdit.value} bez wywołania modelu.`
        : "Prawdopodobnie bezpośrednia zmiana parametru.",
      tone: "free",
      costEstimate: COST_BY_TONE.free,
      ...(directEdit ? { directEdit } : {}),
    };
  }

  if (/\b(split|repair|orient|orientation|support|smooth|mirror|offset|inflate|press fit|hole|holes|drill|detect)\b/.test(normalized)) {
    return {
      label: "Szybka edycja AI",
      title: "Skieruję polecenie do wyspecjalizowanego narzędzia CAD.",
      tone: "cheap",
      costEstimate: COST_BY_TONE.cheap,
    };
  }

  return {
    label: "Edycja AI",
    title: "Ta zmiana prawdopodobnie wymaga pełnego agenta projektowego.",
    tone: "full",
    costEstimate: COST_BY_TONE.full,
  };
}

/**
 * Try to extract a single-parameter mutation from `normalized` text. We only
 * commit to a result when the parse is unambiguous; everything else falls back
 * to the agent path so we never silently apply the wrong value.
 */
function parseDirectParamEdit(
  normalized: string,
  parameters: Design["parameters"],
): { name: string; value: number | boolean | string } | null {
  const scoredParams = parameters
    .map((param) => ({ param, score: parameterMatchScore(normalized, param.name) }))
    .filter((candidate) => candidate.score > 0);
  const bestScore = Math.max(0, ...scoredParams.map((candidate) => candidate.score));
  const paramHits = scoredParams.filter((candidate) => candidate.score === bestScore).map((candidate) => candidate.param);
  if (paramHits.length !== 1) return null;
  const param = paramHits[0];
  const current = param.value;

  // Boolean toggles: "set X true / false / on / off / yes / no"
  if (typeof current === "boolean") {
    const onMatch = /\b(true|on|yes|enable[d]?)\b/.test(normalized);
    const offMatch = /\b(false|off|no|disable[d]?)\b/.test(normalized);
    if (onMatch && !offMatch) return { name: param.name, value: true };
    if (offMatch && !onMatch) return { name: param.name, value: false };
    return null;
  }

  // Relative phrasing first: works without an explicit number.
  if (/\b(double|twice|podwój|podwójnie)\b/.test(normalized) && typeof current === "number") {
    return { name: param.name, value: roundLikely(current * 2) };
  }
  if (/\b(half|połowę|połowa)\b/.test(normalized) && typeof current === "number") {
    return { name: param.name, value: roundLikely(current / 2) };
  }

  // Absolute numeric token. Take the first number near the param mention.
  const match = normalized.match(/-?\d+(?:\.\d+)?/);
  if (!match) return null;
  if (normalized.includes("%")) return null;
  let num = Number(match[0]);
  if (!Number.isFinite(num)) return null;
  if (param.type === "length_mm" && /\b(cm|centymetr|centymetry|centymetrów)\b/.test(normalized)) {
    num *= 10;
  }

  if (typeof current === "number") {
    return { name: param.name, value: num };
  }
  if (typeof current === "string") {
    return { name: param.name, value: match[0] };
  }
  return null;
}

const PARAM_ALIASES: Record<string, string[]> = {
  diameter: ["średnica", "średnicę"],
  width: ["szerokość", "szerokością"],
  height: ["wysokość", "wysokością"],
  depth: ["głębokość", "głębokością"],
  thickness: ["grubość", "grubością"],
  count: ["liczba", "ilość"],
  hole: ["otwór", "otworu", "dziura", "dziury"],
  holes: ["otwory", "otworów", "dziury"],
  wheel: ["kołowrotek", "kołowrotka"],
  track: ["bieżnia", "bieżni", "tor"],
  rung: ["szczebelek", "szczebelki", "szczebelków"],
  spoke: ["szprycha", "szprychy", "szprych"],
  wall: ["ścianka", "ścianki", "ściany"],
  base: ["podstawa", "podstawy"],
};

function parameterMatches(normalized: string, name: string): boolean {
  return parameterMatchScore(normalized, name) > 0;
}

function parameterMatchScore(normalized: string, name: string): number {
  const tokens = name.toLowerCase().replace(/_mm$|_deg$/i, "").split("_");
  const haystack = ` ${normalized} `;
  const exactPhrases = [name.toLowerCase(), tokens.join(" ")];
  if (exactPhrases.some((phrase) => haystack.includes(` ${phrase} `))) return 100;
  const specific = new Set<string>();
  if (tokens.includes("rung") && tokens.includes("count")) specific.add("liczba szczebelków");
  if (tokens.includes("spoke") && tokens.includes("count")) specific.add("liczba szprych");
  if (tokens.includes("hole") && tokens.includes("diameter")) specific.add("średnica otworu");
  if (tokens.includes("wheel") && tokens.includes("diameter")) specific.add("średnica kołowrotka");
  if (tokens.includes("track") && tokens.includes("width")) specific.add("szerokość bieżni");
  if ([...specific].some((phrase) => haystack.includes(` ${phrase} `))) return 80;
  let score = 0;
  for (const token of tokens) {
    if (haystack.includes(` ${token} `)) score += 12;
    if ((PARAM_ALIASES[token] ?? []).some((alias) => haystack.includes(` ${alias} `))) score += 10;
  }
  return score;
}

function roundLikely(n: number): number {
  // Match the precision of typical mm parameters (1 decimal). Avoids 30 → 60.0000001.
  return Math.round(n * 100) / 100;
}

function paramNumber(design: Design, name: string, fallback: number): number {
  const value = design.parameters.find((p) => p.name === name)?.value;
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function featureAnchorForDesign(design: Design, featureId: string): { x: number; y: number; z: number } | null {
  const id = featureId.toLowerCase();
  const bbox = design.latest_build?.bounding_box_mm;
  const outerRadius = paramNumber(design, "outer_diameter", bbox?.[0] ?? 40) / 2;
  const height = paramNumber(design, "height", paramNumber(design, "knob_height", bbox?.[2] ?? 10));
  const holeZ = height * paramNumber(design, "hole_zone_fraction", 0.75);
  const insertRadius = paramNumber(design, "insert_diameter", 0) / 2;

  if (id.includes("knurl")) {
    return { x: outerRadius, y: 0, z: height / 2 };
  }
  if (id.includes("hole")) {
    return { x: outerRadius, y: 0, z: holeZ };
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
  const height = paramNumber(design, "height", paramNumber(design, "knob_height", design.latest_build?.bounding_box_mm?.[2] ?? 10));
  const holeZ = height * paramNumber(design, "hole_zone_fraction", 0.75);
  const insertRadius = paramNumber(design, "insert_diameter", 0) / 2;
  const knurlDepth = paramNumber(design, "knurl_depth", 1);
  const radialDistance = Math.hypot(point.x, point.y);

  if (insertRadius > 0 && radialDistance <= insertRadius + 1 && point.z <= height * 0.55) {
    return findFeature("insert", "pocket");
  }
  if (radialDistance >= Math.max(0, outerRadius - Math.max(knurlDepth * 2, 2))) {
    return findFeature("knurl");
  }
  if (Math.abs(point.z - holeZ) <= Math.max(4, height * 0.08) && radialDistance >= outerRadius * 0.65) {
    return findFeature("hole");
  }
  return findFeature("cylinder", "body") ?? features[0]?.id ?? null;
}

function JewelryTraceSvg({ trace }: { trace: JewelryTracePreview }) {
  if (trace.contours.length === 0) {
    return (
      <svg viewBox="-20 -20 40 40" style={tracePreviewSvgStyle} role="img" aria-label="Jewelry semantic trace preview">
        <rect x="-20" y="-20" width="40" height="40" fill="#151515" />
      </svg>
    );
  }
  const boxes = trace.contours.map((contour) => {
    const xs = contour.points.map((p) => p[0]);
    const ys = contour.points.map((p) => p[1]);
    return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
  });
  const minX = Math.min(...boxes.map((b) => b[0]));
  const minY = Math.min(...boxes.map((b) => b[1]));
  const maxX = Math.max(...boxes.map((b) => b[2]));
  const maxY = Math.max(...boxes.map((b) => b[3]));
  const pad = Math.max(2, Math.max(maxX - minX, maxY - minY) * 0.08);
  const colors: Record<JewelryRole, string> = {
    base_metal: "#f7f3e8",
    cutout: "#151515",
    raised_relief: "#f2c14e",
    engraving: "none",
    ignore: "#cccccc",
  };
  const strokes: Record<JewelryRole, string> = {
    base_metal: "#2f3432",
    cutout: "#000000",
    raised_relief: "#7a5300",
    engraving: "#1f6f62",
    ignore: "#888888",
  };
  return (
    <svg
      viewBox={`${minX - pad} ${-maxY - pad} ${maxX - minX + pad * 2} ${maxY - minY + pad * 2}`}
      style={tracePreviewSvgStyle}
      role="img"
      aria-label="Jewelry semantic trace preview"
    >
      <rect x={minX - pad} y={-maxY - pad} width={maxX - minX + pad * 2} height={maxY - minY + pad * 2} fill="#151515" />
      {trace.contours.map((contour) => (
        <polygon
          key={contour.id}
          points={contour.points.map((p) => `${p[0]},${-p[1]}`).join(" ")}
          fill={colors[contour.role]}
          stroke={strokes[contour.role]}
          strokeWidth={contour.role === "engraving" ? 0.28 : 0.16}
          opacity={contour.role === "ignore" ? 0.35 : 1}
        />
      ))}
    </svg>
  );
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

const fieldLabelStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 6,
  fontSize: 12,
  fontWeight: 700,
  opacity: 0.82,
};

const compactInputStyle: React.CSSProperties = {
  border: "1px solid rgba(0,0,0,0.12)",
  borderRadius: 10,
  padding: "9px 10px",
  fontSize: 13,
  fontFamily: "inherit",
  background: "rgba(255,255,255,0.92)",
};

const jewelryCardStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 12,
  padding: 18,
  background: "linear-gradient(180deg, rgba(255,255,255,0.92), rgba(247,251,249,0.86))",
  border: "1px solid rgba(43,140,122,0.22)",
  borderRadius: 14,
};

const jewelryHeaderStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "flex-start",
  justifyContent: "space-between",
  gap: 12,
};

const jewelryBadgeStyle: React.CSSProperties = {
  padding: "6px 9px",
  borderRadius: 999,
  background: "rgba(43,140,122,0.1)",
  color: "#1f6f62",
  fontSize: 11,
  fontWeight: 800,
  whiteSpace: "nowrap",
};

const jewelryGridStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))",
  gap: 10,
};

const jewelryUploadRowStyle: React.CSSProperties = {
  display: "flex",
  gap: 8,
  alignItems: "center",
  flexWrap: "wrap",
};

const jewelryPreviewStyle: React.CSSProperties = {
  width: "100%",
  maxHeight: 180,
  objectFit: "cover",
  borderRadius: 12,
  border: "1px solid rgba(0,0,0,0.1)",
};

const tracePreviewPanelStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(160px, 1fr)",
  gap: 8,
  padding: 10,
  borderRadius: 12,
  border: "1px solid rgba(43,140,122,0.22)",
  background: "rgba(255,255,255,0.72)",
};

const tracePreviewMetaStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  flexWrap: "wrap",
  fontSize: 12,
  color: "#255f57",
};

const tracePreviewSvgStyle: React.CSSProperties = {
  width: "100%",
  height: 220,
  background: "#151515",
  borderRadius: 8,
  border: "1px solid rgba(0,0,0,0.08)",
};

const conceptGridStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))",
  gap: 8,
};

const conceptCardStyle: React.CSSProperties = {
  border: "1px solid rgba(0,0,0,0.1)",
  borderRadius: 10,
  padding: 8,
  background: "rgba(255,255,255,0.82)",
  display: "flex",
  flexDirection: "column",
  gap: 6,
  alignItems: "center",
  cursor: "pointer",
  fontWeight: 800,
};

const conceptImageStyle: React.CSSProperties = {
  width: "100%",
  aspectRatio: "1 / 1",
  objectFit: "cover",
  borderRadius: 8,
  background: "#f7f7f7",
};

const traceWarningListStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 4,
  padding: "8px 10px",
  borderRadius: 10,
  color: "#8a5c00",
  background: "rgba(255,193,7,0.12)",
  fontSize: 12,
  fontWeight: 700,
};

const contourRoleGridStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
  gap: 6,
};

const contourRoleStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "1fr 96px",
  alignItems: "center",
  gap: 6,
  fontSize: 11,
  fontWeight: 800,
  color: "rgba(0,0,0,0.62)",
};

const jewelryStatusStyle: React.CSSProperties = {
  margin: 0,
  padding: "9px 10px",
  borderRadius: 10,
  background: "rgba(33,150,243,0.08)",
  color: "#185a9d",
  fontSize: 12,
  fontWeight: 700,
};

const jewelryErrorStyle: React.CSSProperties = {
  margin: 0,
  padding: "9px 10px",
  borderRadius: 10,
  background: "rgba(244,67,54,0.08)",
  color: "rgba(180,30,30,0.95)",
  fontSize: 12,
  fontWeight: 700,
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

const startComposerStyle: React.CSSProperties = {
  width: "min(860px, 100%)",
  alignSelf: "center",
  padding: 24,
  gap: 14,
  borderRadius: 20,
  boxShadow: "0 18px 50px rgba(56, 43, 30, 0.09)",
};

const startStudioGridStyle: React.CSSProperties = {
  order: 1,
  display: "grid",
  gridTemplateColumns: "minmax(290px, 0.82fr) minmax(440px, 1.65fr) minmax(280px, 0.9fr)",
  gap: 12,
  minHeight: 620,
};

const startChatPaneStyle: React.CSSProperties = {
  gridColumn: "1",
  gridRow: "1",
  background: "linear-gradient(180deg, #1a222c 0%, #121820 100%)",
  color: "#eef3f7",
  border: "1px solid rgba(255,255,255,0.08)",
  borderRadius: 12,
  display: "flex",
  flexDirection: "column",
  minHeight: 620,
  maxHeight: "none",
  padding: 18,
  gap: 16,
  boxShadow: "0 16px 36px rgba(19,29,40,0.14)",
};

const startChatTextareaStyle: React.CSSProperties = {
  width: "100%",
  flex: 1,
  minHeight: 260,
  resize: "none",
  border: "1px solid rgba(255,255,255,0.12)",
  borderRadius: 14,
  padding: "15px 16px",
  background: "rgba(255,255,255,0.055)",
  color: "#f3f7fa",
  font: "inherit",
  fontSize: 14,
  lineHeight: 1.5,
  outlineColor: "#4aa3ff",
};

const startChatFooterStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 9,
  flexWrap: "wrap",
};

const startDarkSelectStyle: React.CSSProperties = {
  marginLeft: 6,
  border: "1px solid rgba(255,255,255,0.14)",
  borderRadius: 8,
  background: "#252f3b",
  color: "#eef3f7",
  padding: "6px 7px",
  font: "inherit",
  fontSize: 11,
};

const startViewerPaneStyle: React.CSSProperties = {
  position: "relative",
  minHeight: 620,
  overflow: "hidden",
  borderRadius: 12,
  border: "1px solid rgba(15,23,32,0.24)",
  background: "radial-gradient(circle at 50% 42%, #283542 0%, #18232e 46%, #111820 100%)",
  boxShadow: "0 16px 36px rgba(19,29,40,0.14)",
};

const startViewerGridStyle: React.CSSProperties = {
  position: "absolute",
  inset: 0,
  opacity: 0.34,
  backgroundImage:
    "linear-gradient(rgba(117,151,180,.28) 1px, transparent 1px), linear-gradient(90deg, rgba(117,151,180,.28) 1px, transparent 1px)",
  backgroundSize: "58px 58px",
  transform: "perspective(520px) rotateX(58deg) scale(1.35)",
  transformOrigin: "center 68%",
};

const startViewerEmptyStyle: React.CSSProperties = {
  position: "absolute",
  inset: 0,
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  justifyContent: "center",
  gap: 10,
  padding: 32,
  textAlign: "center",
  color: "#e8eef3",
};

const startCreatingStyle: React.CSSProperties = {
  position: "absolute",
  inset: 0,
  zIndex: 2,
  width: "min(360px, 82%)",
  height: "fit-content",
  margin: "auto",
  padding: "22px 24px",
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  gap: 8,
  borderRadius: 16,
  border: "1px solid rgba(112,198,255,0.28)",
  background: "rgba(14,24,34,0.82)",
  color: "#eef6fb",
  textAlign: "center",
  boxShadow: "0 18px 48px rgba(0,0,0,0.22)",
};

const startCreatingSpinnerStyle: React.CSSProperties = {
  width: 24,
  height: 24,
  borderRadius: 999,
  border: "3px solid rgba(112,198,255,0.2)",
  borderTopColor: "#70c6ff",
};

const startViewerObjectStyle: React.CSSProperties = {
  width: 130,
  height: 130,
  marginBottom: 8,
  borderRadius: "31% 44% 35% 42%",
  border: "1px solid rgba(174,196,216,0.28)",
  background: "linear-gradient(145deg, rgba(191,207,220,0.34), rgba(95,116,135,0.14))",
  boxShadow: "inset 18px 16px 28px rgba(255,255,255,0.08), 0 28px 48px rgba(0,0,0,0.22)",
  transform: "rotate(-13deg)",
};

const startViewerAxisStyle: React.CSSProperties = {
  position: "absolute",
  left: 16,
  bottom: 14,
  display: "flex",
  gap: 7,
  fontSize: 10,
  fontWeight: 900,
};

const startViewerModeStyle: React.CSSProperties = {
  position: "absolute",
  top: 14,
  right: 14,
  padding: "6px 9px",
  borderRadius: 999,
  background: "rgba(226,242,242,0.92)",
  color: "#24424b",
  fontSize: 10,
  fontWeight: 900,
};

const startToolsPaneStyle: React.CSSProperties = {
  minHeight: 620,
  padding: 16,
  display: "flex",
  flexDirection: "column",
  gap: 12,
  overflowY: "auto",
  borderRadius: 12,
  border: "1px solid rgba(0,0,0,0.08)",
  background: "rgba(255,255,255,0.86)",
};

const startToolsListStyle: React.CSSProperties = { display: "flex", flexDirection: "column", gap: 7 };

const startToolButtonStyle: React.CSSProperties = {
  width: "100%",
  minHeight: 38,
  padding: "9px 11px",
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 8,
  border: "1px solid rgba(0,0,0,0.09)",
  borderRadius: 9,
  background: "rgba(0,0,0,0.025)",
  color: "#27313b",
  font: "inherit",
  fontSize: 12,
  fontWeight: 750,
  textAlign: "left",
  cursor: "pointer",
};

const startToolsDetailsStyle: React.CSSProperties = {
  padding: "10px 11px",
  border: "1px solid rgba(0,0,0,0.08)",
  borderRadius: 10,
  background: "rgba(0,0,0,0.018)",
};

const startRecentButtonStyle: React.CSSProperties = {
  marginTop: "auto",
  padding: "11px 12px",
  display: "flex",
  flexDirection: "column",
  alignItems: "flex-start",
  gap: 3,
  border: "1px solid rgba(25,118,210,0.18)",
  borderRadius: 10,
  background: "rgba(25,118,210,0.06)",
  color: "#214b75",
  font: "inherit",
  fontSize: 11,
  cursor: "pointer",
};

const startTextareaStyle: React.CSSProperties = {
  width: "100%",
  minHeight: 120,
  resize: "vertical",
  border: "1px solid rgba(25, 31, 38, 0.16)",
  borderRadius: 16,
  padding: "16px 18px",
  background: "rgba(255,255,255,0.96)",
  color: "#17202a",
  font: "inherit",
  fontSize: 16,
  lineHeight: 1.45,
  boxShadow: "inset 0 1px 2px rgba(0,0,0,0.03)",
};

const startComposerFooterStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 10,
  flexWrap: "wrap",
};

const advancedStartStyle: React.CSSProperties = {
  border: "1px solid rgba(0,0,0,0.08)",
  borderRadius: 12,
  background: "rgba(0,0,0,0.025)",
  padding: "10px 12px",
};

const starterLibraryStyle: React.CSSProperties = {
  border: "1px solid rgba(0,0,0,0.07)",
  borderRadius: 12,
  background: "rgba(255,255,255,0.58)",
  padding: "10px 12px",
};

const advancedSummaryStyle: React.CSSProperties = {
  cursor: "pointer",
  fontSize: 13,
  fontWeight: 800,
  color: "rgba(25,32,42,0.72)",
};

const advancedStartBodyStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 9,
  paddingTop: 10,
};

const infoCardStyle: React.CSSProperties = {
  padding: 14,
  background: "rgba(0,0,0,0.04)",
  borderRadius: 12,
  fontSize: 13,
};

const threePaneStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(290px, 0.82fr) minmax(440px, 1.65fr) minmax(290px, 0.9fr)",
  gap: 12,
  flex: 1,
  minHeight: 600,
};

// CSS injected via a <style> tag — three-column on desktop, single column
// on mobile, with the viewer first so a phone visit shows the model.
const responsiveCss = `
@media (max-width: 900px) {
  main { padding: 16px !important; }
  .pulsai-studio-grid {
    grid-template-columns: 1fr !important;
  }
  .pulsai-chat-pane { grid-column: 1 !important; grid-row: auto !important; order: 1; }
  .pulsai-canvas-pane { grid-column: 1 !important; grid-row: auto !important; order: 2; min-height: 480px !important; }
  .pulsai-parameters-pane { grid-column: 1 !important; grid-row: auto !important; order: 3; }
  .pulsai-start-studio-grid { grid-template-columns: 1fr !important; }
  .pulsai-start-chat-pane { grid-column: 1 !important; min-height: 480px !important; }
  .pulsai-start-viewer-pane { grid-column: 1 !important; min-height: 480px !important; }
  .pulsai-start-tools-pane { grid-column: 1 !important; min-height: auto !important; }
  aside { max-height: none !important; }
}
@media (max-width: 600px) {
  h1 { font-size: 20px !important; }
  .editability-badge { font-size: 10px !important; }
}
`;

const parametersPaneStyle: React.CSSProperties = {
  gridColumn: "3",
  gridRow: "1",
  background: "rgba(255,255,255,0.85)",
  border: "1px solid rgba(0,0,0,0.08)",
  borderRadius: 12,
  padding: 12,
  display: "flex",
  flexDirection: "column",
  gap: 6,
  overflowY: "auto",
  maxHeight: "76vh",
};

const canvasPaneStyle: React.CSSProperties = {
  gridColumn: "2",
  gridRow: "1",
  position: "relative",
  background: "#11171e",
  border: "1px solid rgba(15,23,32,0.2)",
  borderRadius: 12,
  overflow: "hidden",
  minHeight: 600,
  boxShadow: "0 16px 36px rgba(19,29,40,0.14)",
};

const chatPaneStyle: React.CSSProperties = {
  gridColumn: "1",
  gridRow: "1",
  background: "linear-gradient(180deg, #1a222c 0%, #121820 100%)",
  color: "#eef3f7",
  border: "1px solid rgba(255,255,255,0.08)",
  borderRadius: 12,
  padding: 12,
  display: "flex",
  flexDirection: "column",
  gap: 10,
  maxHeight: "76vh",
  boxShadow: "0 16px 36px rgba(19,29,40,0.14)",
};

const chatPaneHeaderStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 10,
  padding: "2px 2px 10px",
  borderBottom: "1px solid rgba(255,255,255,0.08)",
};

const chatIdentityStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 9,
  minWidth: 0,
};

const chatBrandMarkStyle: React.CSSProperties = {
  width: 30,
  height: 30,
  display: "grid",
  placeItems: "center",
  borderRadius: 9,
  background: "linear-gradient(145deg, #70c6ff, #56b9a8)",
  color: "#0d1720",
  fontSize: 13,
  fontWeight: 900,
};

const chatTitleStyle: React.CSSProperties = {
  display: "block",
  fontSize: 13,
  color: "#f5f7fa",
};

const chatSubtitleStyle: React.CSSProperties = {
  display: "block",
  marginTop: 1,
  fontSize: 10,
  color: "rgba(232,240,247,0.50)",
};

const chatHeaderMetaStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  alignItems: "flex-end",
  gap: 3,
};

const sessionCostStyle: React.CSSProperties = {
  color: "rgba(232,240,247,0.52)",
  fontSize: 9,
  whiteSpace: "nowrap",
};

const chatOnlineStyle: React.CSSProperties = {
  padding: "3px 8px",
  borderRadius: 999,
  background: "rgba(63,183,155,0.14)",
  border: "1px solid rgba(63,183,155,0.28)",
  color: "#7dd3c7",
  fontSize: 10,
  fontWeight: 800,
};

const agentProgressStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
  padding: "6px 8px",
  borderRadius: 8,
  background: "rgba(125,211,199,0.06)",
  color: "#d9f4ef",
  fontSize: 10,
  lineHeight: 1.35,
};

const agentProgressDotStyle: React.CSSProperties = {
  width: 8,
  height: 8,
  marginTop: 0,
  borderRadius: 999,
  background: "#7dd3c7",
  boxShadow: "0 0 0 4px rgba(125,211,199,0.12)",
  flex: "none",
};

const emptyChatStyle: React.CSSProperties = {
  flex: 1,
  display: "grid",
  placeItems: "center",
  alignContent: "center",
  gap: 7,
  padding: "28px 18px",
  textAlign: "center",
  color: "rgba(238,243,247,0.78)",
};

const emptyChatMarkStyle: React.CSSProperties = {
  ...chatBrandMarkStyle,
  width: 36,
  height: 36,
  borderRadius: 11,
};

const paneHintStyle: React.CSSProperties = {
  display: "block",
  maxWidth: 180,
  fontSize: 10,
  lineHeight: 1.3,
  opacity: 0.5,
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

const showMoreParametersStyle: React.CSSProperties = {
  border: "1px solid rgba(0,0,0,0.1)",
  borderRadius: 8,
  padding: "8px 10px",
  background: "rgba(0,0,0,0.03)",
  color: "rgba(0,0,0,0.64)",
  fontSize: 11,
  fontWeight: 800,
  cursor: "pointer",
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

const printReadinessCopyStyle: React.CSSProperties = {
  fontSize: 11,
  lineHeight: 1.4,
  color: "rgba(0,0,0,0.62)",
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

const chatTextareaStyle: React.CSSProperties = {
  width: "100%",
  minHeight: 68,
  maxHeight: 180,
  resize: "none",
  background: "transparent",
  border: "none",
  borderRadius: 0,
  padding: "4px 5px",
  font: "inherit",
  fontSize: 13,
  lineHeight: 1.4,
  color: "#f5f7fa",
  outline: "none",
};

const chatComposerShellStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 7,
  padding: 8,
  border: "1px solid rgba(255,255,255,0.14)",
  borderRadius: 17,
  background: "rgba(255,255,255,0.065)",
  boxShadow: "0 8px 24px rgba(0,0,0,0.16)",
};

const chatComposerFooterStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "auto minmax(0, 1fr) auto",
  alignItems: "center",
  gap: 8,
  minWidth: 0,
};

const composerToolsStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 4,
};

const composerIconButtonStyle: React.CSSProperties = {
  width: 32,
  height: 32,
  display: "grid",
  placeItems: "center",
  padding: 0,
  borderRadius: 999,
  border: "1px solid rgba(255,255,255,0.14)",
  background: "transparent",
  color: "rgba(238,243,247,0.86)",
  fontSize: 18,
  cursor: "pointer",
};

const composerSendButtonStyle: React.CSSProperties = {
  ...composerIconButtonStyle,
  background: "#f2f5f7",
  color: "#111820",
  borderColor: "transparent",
  fontSize: 18,
  fontWeight: 800,
};

const composerBelowHintStyle: React.CSSProperties = {
  padding: "0 5px 2px",
  color: "rgba(232,240,247,0.44)",
  fontSize: 9,
  lineHeight: 1.3,
};

const imageAttachmentStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  padding: 6,
  borderRadius: 11,
  background: "rgba(0,0,0,0.18)",
  fontSize: 9,
};

const imageThumbStyle: React.CSSProperties = {
  width: 42,
  height: 42,
  borderRadius: 8,
  objectFit: "cover",
};

const routeBadgeRowStyle: React.CSSProperties = {
  display: "flex",
  justifyContent: "flex-end",
  minHeight: 17,
};

const chatComposerHintStyle: React.CSSProperties = {
  minWidth: 0,
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
  fontSize: 11,
  opacity: 0.68,
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

const applyDirectButtonStyle: React.CSSProperties = {
  padding: "7px 10px",
  borderRadius: 999,
  background: "rgba(125,211,199,0.14)",
  color: "#9be2d7",
  border: "1px solid rgba(125,211,199,0.28)",
  fontSize: 10,
  fontWeight: 750,
  cursor: "pointer",
};

const slicerHintStyle: React.CSSProperties = {
  fontSize: 11,
  lineHeight: 1.4,
  padding: "8px 10px",
  background: "rgba(255,193,7,0.10)",
  border: "1px solid rgba(255,193,7,0.35)",
  borderRadius: 6,
  color: "rgba(126,87,0,0.95)",
};

const orientationHintStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 6,
  fontSize: 11,
  lineHeight: 1.4,
  padding: "8px 10px",
  background: "rgba(33,150,243,0.10)",
  border: "1px solid rgba(33,150,243,0.30)",
  borderRadius: 6,
  color: "rgba(13,71,161,0.95)",
};

const orientationActionStyle = (disabled: boolean): React.CSSProperties => ({
  alignSelf: "flex-start",
  padding: "4px 10px",
  fontSize: 11,
  fontWeight: 600,
  borderRadius: 999,
  border: "1px solid rgba(33,150,243,0.55)",
  background: disabled ? "rgba(33,150,243,0.18)" : "rgba(33,150,243,0.85)",
  color: disabled ? "rgba(13,71,161,0.6)" : "white",
  cursor: disabled ? "not-allowed" : "pointer",
});

const routeBadgeStyle = (
  tone: "free" | "cheap" | "full" | "answer",
): React.CSSProperties => {
  const colors = {
    answer: ["rgba(33,150,243,0.14)", "rgba(13,71,161,0.9)"],
    free: ["rgba(76,175,80,0.16)", "rgba(46,125,50,0.85)"],
    cheap: ["rgba(255,193,7,0.20)", "rgba(126,87,0,0.9)"],
    full: ["rgba(255,255,255,0.08)", "rgba(238,243,247,0.72)"],
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

const headerActionsStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 12,
  flexShrink: 0,
};

const printerPickerStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 2,
  fontSize: 11,
};

const printerPickerLabelStyle: React.CSSProperties = {
  fontSize: 9,
  letterSpacing: 1,
  textTransform: "uppercase",
  opacity: 0.6,
};

const printerSelectStyle: React.CSSProperties = {
  background: "rgba(255,255,255,0.92)",
  border: "1px solid rgba(0,0,0,0.18)",
  borderRadius: 6,
  padding: "4px 8px",
  fontSize: 12,
  fontWeight: 600,
  cursor: "pointer",
  maxWidth: 240,
};

const printerPickerHintStyle: React.CSSProperties = {
  color: "rgba(0,0,0,0.55)",
  fontSize: 10,
  lineHeight: 1.2,
  maxWidth: 240,
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

const printResultOverlayStyle: React.CSSProperties = {
  position: "absolute",
  left: 14,
  bottom: 14,
  zIndex: 3,
  width: "min(330px, calc(100% - 150px))",
  padding: "10px 12px",
  borderRadius: 12,
  color: "#eef3f7",
  background: "rgba(17,23,30,0.88)",
  border: "1px solid rgba(112,198,255,0.22)",
  boxShadow: "0 12px 28px rgba(0,0,0,0.28)",
  backdropFilter: "blur(12px)",
};

const printResultLinksStyle: React.CSSProperties = {
  display: "flex",
  gap: 12,
  marginTop: 7,
  fontSize: 11,
};

const languageSwitcherStyle: React.CSSProperties = {
  display: "flex",
  padding: 2,
  borderRadius: 999,
  background: "rgba(0,0,0,0.06)",
  border: "1px solid rgba(0,0,0,0.1)",
};

const languageButtonStyle = (active: boolean): React.CSSProperties => ({
  border: 0,
  borderRadius: 999,
  padding: "5px 8px",
  background: active ? "#1a222c" : "transparent",
  color: active ? "#eef3f7" : "rgba(0,0,0,0.58)",
  fontSize: 10,
  fontWeight: 800,
  cursor: "pointer",
});

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
  const menuRef = useRef<HTMLDivElement | null>(null);
  const presets = [
    { id: "fdm", label: "Export for 3D printing", desc: "STL · G-code · manifest" },
    { id: "cnc", label: "Export for CNC", desc: "STEP · DXF · setup notes" },
    { id: "docs", label: "Export for docs", desc: "STL · GLB · manifest" },
    { id: "all", label: "Export everything", desc: "all of the above" },
  ];

  useEffect(() => {
    if (!open) return;
    const closeOutside = (event: PointerEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  useEffect(() => setOpen(false), [designId, revisionId]);

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
    <div ref={menuRef} style={{ position: "relative" }}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
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
          role="menu"
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
  language,
}: {
  estimate: import("../../types/design").PrintEstimate;
  language: UiLanguage;
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
        <span style={estimateLabelStyle}>{uiText(language, "materiał", "material")}</span>
        <span style={estimateValueStyle}>{fmtMass(estimate.filament_g)}</span>
      </div>
      <div style={estimateCellStyle}>
        <span style={estimateLabelStyle}>{uiText(language, "czas", "time")}</span>
        <span style={estimateValueStyle}>{fmtTime(estimate.print_minutes)}</span>
      </div>
      <div style={estimateCellStyle}>
        <span style={estimateLabelStyle}>{uiText(language, "koszt", "cost")}</span>
        <span style={estimateValueStyle}>{fmtCost(estimate.cost_usd)}</span>
      </div>
      {estimate.cost_usd_per_g ? (
        <span style={{ fontSize: 10, opacity: 0.5, gridColumn: "1 / -1" }}>
          @ ${estimate.cost_usd_per_g.toFixed(3)}/g {uiText(language, "filamentu", "filament")}
        </span>
      ) : null}
    </div>
  );
}

function PrintResultCard({
  estimate,
  language,
  gcodeUrl,
  bundleUrl,
}: {
  estimate: import("../../types/design").PrintEstimate;
  language: UiLanguage;
  gcodeUrl: string | null;
  bundleUrl?: string;
}) {
  return (
    <div style={printResultOverlayStyle} role="status" aria-label={uiText(language, "Podsumowanie wydruku", "Print summary")}>
      <strong>{uiText(language, "Gotowe do druku", "Ready to print")}</strong>
      <PrintEstimatePanel estimate={estimate} language={language} />
      <div style={printResultLinksStyle}>
        {gcodeUrl ? (
          <a href={gcodeUrl} target="_blank" rel="noopener noreferrer">
            {uiText(language, "Pobierz G-code", "Download G-code")}
          </a>
        ) : null}
        {bundleUrl ? (
          <a href={bundleUrl} target="_blank" rel="noopener noreferrer">
            {uiText(language, "Pełny pakiet", "Full bundle")}
          </a>
        ) : null}
      </div>
    </div>
  );
}

function LanguageSwitcher({
  language,
  onChange,
}: {
  language: UiLanguage;
  onChange: (language: UiLanguage) => void;
}) {
  return (
    <div style={languageSwitcherStyle} aria-label="Interface language">
      {(["pl", "en"] as const).map((value) => (
        <button
          key={value}
          type="button"
          aria-pressed={language === value}
          onClick={() => onChange(value)}
          style={languageButtonStyle(language === value)}
        >
          {value.toUpperCase()}
        </button>
      ))}
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

function printStatusLabel(status: "safe" | "warn" | "unprintable"): string {
  return {
    safe: "Gotowy",
    warn: "Wymaga przygotowania",
    unprintable: "Wymaga poprawy",
  }[status];
}

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
