"use client";

import type { ChangeEvent, FormEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { resolveBackendUrl, resolveUrl } from "../lib/backend";
import { stableStringify } from "../lib/stable-json";

type VoicePanelProps = {
  onModelUrl: (url: string | null) => void;
  onGhostModelUrl?: (url: string | null) => void;
  onPreviewUpdating?: (updating: boolean) => void;
  onStlUrl: (url: string | null) => void;
  onGcodeUrl: (url: string | null) => void;
  onBundleUrl: (url: string | null) => void;
  workflowMode?: "useful" | "creative";
  hideModeSwitch?: boolean;
};

type ProjectSummary = {
  project_id: string;
  name?: string;
  current_job_id?: string;
};

type ProviderInfo = {
  enabled: boolean;
  cost?: string;
  modes?: string[];
};

type HealthResponse = {
  ok: boolean;
  warnings?: string[];
  providers?: Record<string, ProviderInfo>;
  router_ready?: boolean;
  cad_ready?: boolean;
  preview_ready?: boolean;
  slicer_ready?: boolean;
};

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
  job_id: string;
  mode: "useful" | "creative";
  provider: string;
  route_reason: string;
  confidence: number;
  prompt: string;
  confirmation_required: boolean;
  structured_spec?: StructuredSpec | null;
};

type UsefulPreviewResponse = {
  job_id: string;
  preview_id: string;
  glb_url: string;
  structured_spec: StructuredSpec;
};

type ValidationResponse = {
  validation_status?: string;
  warnings?: string[];
  dimensions_mm?: number[];
  estimated_print_risk?: string;
  stl_ready?: boolean;
  gcode_status?: string;
};

type UsefulBuildResponse = {
  job_id: string;
  glb_url: string;
  stl_url: string;
  gcode_url?: string | null;
  validation: ValidationResponse;
  bundle_url?: string | null;
  structured_spec: StructuredSpec;
};

type ProcessResponse = {
  job_id: string;
  glb_url: string;
  stl_url: string;
  gcode_url?: string | null;
  validation?: ValidationResponse;
  bundle_url?: string | null;
};

type LibraryItem = {
  id: string;
  title: string;
  glb_url?: string;
};

type PendingPreview = {
  spec: StructuredSpec;
  specKey: string;
};

class TimeoutError extends Error {
  name = "TimeoutError";

  constructor(message: string) {
    super(message);
  }
}

const TIMEOUTS = {
  health: 10000,
  projects: 10000,
  route: 25000,
  intent: 25000,
  preview: 120000,
  build: 180000,
  generate: 180000,
  image: 300000,
  process: 180000,
};

const usefulPromptExamples = [
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

const DIMENSION_ORDER: Record<string, string[]> = {
  phone_stand: ["height", "width", "depth"],
  simple_box: ["width", "depth", "height"],
  tray: ["width", "depth", "height"],
  hook: ["height", "depth", "width"],
  cable_organizer: ["width", "depth", "height"],
  bracket: ["width", "height", "depth"],
  cylindrical_holder: ["height", "diameter"],
  wall_mount: ["height", "width", "depth"],
};

const CONSTRAINT_ORDER: Record<string, string[]> = {
  phone_stand: [
    "angle_deg",
    "base_thickness_mm",
    "back_thickness_mm",
    "lip_height_mm",
    "cable_hole_diameter_mm",
    "slot_width_mm",
    "slot_depth_mm",
  ],
  simple_box: ["wall_thickness_mm", "open_top", "hollow", "fillet_mm"],
  tray: ["wall_thickness_mm", "fillet_mm"],
  hook: ["hook_thickness_mm", "hook_gap_mm", "plate_thickness_mm"],
  cable_organizer: ["slot_count", "slot_width_mm", "wall_thickness_mm"],
  bracket: ["thickness_mm", "hole_diameter_mm"],
  cylindrical_holder: ["wall_thickness_mm", "base_thickness_mm"],
  wall_mount: ["plate_thickness_mm", "arm_thickness_mm", "arm_drop_mm"],
};

const sortKeys = (keys: string[], preferred: string[] | undefined) => {
  const preferredOrder = preferred || [];
  return [...keys].sort((left, right) => {
    const leftIndex = preferredOrder.indexOf(left);
    const rightIndex = preferredOrder.indexOf(right);
    if (leftIndex === -1 && rightIndex === -1) return left.localeCompare(right);
    if (leftIndex === -1) return 1;
    if (rightIndex === -1) return -1;
    return leftIndex - rightIndex;
  });
};

const humanStatus = (status: string) => {
  switch (status) {
    case "listening":
      return "Listening for your idea";
    case "recording":
      return "Capturing your voice";
    case "transcribing":
    case "understanding":
      return "Understanding your idea";
    case "confirming":
      return "Check the detected details";
    case "drafting":
      return "Drafting your object";
    case "making-printable":
    case "building":
      return "Making it printable";
    case "ready":
    case "preview-ready":
      return "Ready to export";
    case "error":
      return "Something needs attention";
    default:
      return "Ready to capture";
  }
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
  onModelUrl,
  onGhostModelUrl,
  onPreviewUpdating,
  onStlUrl,
  onGcodeUrl,
  onBundleUrl,
  workflowMode,
  hideModeSwitch = false,
}: VoicePanelProps) {
  const backendUrl = resolveBackendUrl();
  const [mode, setMode] = useState<"useful" | "creative">(workflowMode || "useful");
  const [status, setStatus] = useState("idle");
  const [manualText, setManualText] = useState("");
  const [routeResult, setRouteResult] = useState<RouteIntentResponse | null>(null);
  const [structuredSpec, setStructuredSpec] = useState<StructuredSpec | null>(null);
  const [previewJobId, setPreviewJobId] = useState<string | null>(null);
  const [buildJobId, setBuildJobId] = useState<string | null>(null);
  const [validation, setValidation] = useState<ValidationResponse | null>(null);
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [imageLabel, setImageLabel] = useState<string | null>(null);
  const [revisionNote, setRevisionNote] = useState("");
  const [isBusy, setIsBusy] = useState(false);
  const [isPreviewUpdating, setIsPreviewUpdating] = useState(false);
  const [lastError, setLastError] = useState<string | null>(null);
  const [speechSupport, setSpeechSupport] = useState(false);
  const [recordingSupport, setRecordingSupport] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [interim, setInterim] = useState<string | null>(null);
  const [transcripts, setTranscripts] = useState<string[]>([]);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [activeProjectId, setActiveProjectId] = useState<string | null>(null);
  const [isLoadingProjects, setIsLoadingProjects] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [creativeProvider, setCreativeProvider] = useState("meshy");
  const [libraryResults, setLibraryResults] = useState<LibraryItem[]>([]);
  const [lastSuccessfulSpec, setLastSuccessfulSpec] = useState<StructuredSpec | null>(null);
  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const isMountedRef = useRef(true);
  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const previewInFlightRef = useRef(false);
  const queuedPreviewRef = useRef<PendingPreview | null>(null);
  const latestPreviewTokenRef = useRef(0);
  const lastRequestedSpecKeyRef = useRef<string | null>(null);
  const lastPreviewedSpecKeyRef = useRef<string | null>(null);
  const currentModelUrlRef = useRef<string | null>(null);

  const createJobId = () => {
    if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
      return crypto.randomUUID();
    }
    return `job-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  };

  const syncPreviewUpdating = (updating: boolean) => {
    if (!isMountedRef.current) return;
    setIsPreviewUpdating(updating);
    onPreviewUpdating?.(updating);
  };

  const invalidatePreviewRequests = () => {
    latestPreviewTokenRef.current += 1;
    previewInFlightRef.current = false;
    queuedPreviewRef.current = null;
    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current);
      debounceTimerRef.current = null;
    }
    syncPreviewUpdating(false);
  };

  const resetOutputs = () => {
    onStlUrl(null);
    onGcodeUrl(null);
    onBundleUrl(null);
    setValidation(null);
  };

  const resetViewer = () => {
    onModelUrl(null);
    onGhostModelUrl?.(null);
    currentModelUrlRef.current = null;
  };

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      invalidatePreviewRequests();
    };
  }, []);

  useEffect(() => {
    if (workflowMode) {
      setMode(workflowMode);
    }
  }, [workflowMode]);

  useEffect(() => {
    invalidatePreviewRequests();
    setRouteResult(null);
    setStructuredSpec(null);
    setPreviewJobId(null);
    setBuildJobId(null);
    setLastSuccessfulSpec(null);
    setLastError(null);
    setStatus("idle");
    resetOutputs();
    resetViewer();
  }, [mode]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    setSpeechSupport(
      !!(window as Window).SpeechRecognition || !!(window as Window).webkitSpeechRecognition
    );
    setRecordingSupport(
      typeof MediaRecorder !== "undefined" && !!navigator.mediaDevices?.getUserMedia
    );
  }, []);

  useEffect(() => {
    if (!speechSupport) return;
    const SpeechRecognitionCtor =
      (window as Window).SpeechRecognition || (window as Window).webkitSpeechRecognition;
    if (!SpeechRecognitionCtor) return;

    const recognition = new SpeechRecognitionCtor();
    recognition.lang = "en-US";
    recognition.interimResults = true;
    recognition.continuous = false;

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      let finalTranscript = "";
      let interimTranscript = "";
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index];
        const chunk = result[0]?.transcript ?? "";
        if (result.isFinal) {
          finalTranscript += chunk;
        } else {
          interimTranscript += chunk;
        }
      }
      if (interimTranscript) {
        setInterim(interimTranscript.trim());
      }
      if (finalTranscript.trim()) {
        const transcript = finalTranscript.trim();
        setManualText(transcript);
        setInterim(null);
        setTranscripts((prev) => [...prev.slice(-4), transcript]);
        void handleIdeaSubmit(transcript, "voice");
      }
    };

    recognition.onerror = () => {
      setIsListening(false);
      setStatus("error");
    };

    recognition.onend = () => {
      setIsListening(false);
    };

    recognitionRef.current = recognition;

    return () => {
      recognition.stop();
    };
  }, [speechSupport]);

  useEffect(() => {
    if (!imageFile) {
      setImageLabel(null);
      return;
    }
    setImageLabel(imageFile.name);
  }, [imageFile]);

  useEffect(() => {
    const loadHealth = async () => {
      try {
        const response = await fetchWithTimeout(
          `${backendUrl}/health`,
          undefined,
          TIMEOUTS.health
        );
        if (!response.ok) throw new Error("Health check failed");
        if (!isMountedRef.current) return;
        setHealth((await response.json()) as HealthResponse);
      } catch (error) {
        console.warn("Health check failed", error);
        if (isMountedRef.current) {
          setHealth(null);
        }
      }
    };
    void loadHealth();
  }, [backendUrl]);

  useEffect(() => {
    void refreshProjects();
  }, [backendUrl]);

  const refreshProjects = async () => {
    setIsLoadingProjects(true);
    try {
      const response = await fetchWithTimeout(
        `${backendUrl}/projects`,
        undefined,
        TIMEOUTS.projects
      );
      if (!response.ok) throw new Error("Projects fetch failed");
      const data = await response.json();
      if (!isMountedRef.current) return;
      setProjects((data.items || []) as ProjectSummary[]);
    } catch (error) {
      console.warn("Project refresh failed", error);
    } finally {
      if (isMountedRef.current) {
        setIsLoadingProjects(false);
      }
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
    if (!isMountedRef.current) return null;
    const project = data.project as ProjectSummary;
    setProjects((prev) => [project, ...prev]);
    setActiveProjectId(project.project_id);
    return project;
  };

  const dispatchUsefulPreview = async (spec: StructuredSpec, specKey: string) => {
    if (!isMountedRef.current || mode !== "useful") return;

    previewInFlightRef.current = true;
    lastRequestedSpecKeyRef.current = specKey;
    const previewToken = latestPreviewTokenRef.current + 1;
    latestPreviewTokenRef.current = previewToken;
    syncPreviewUpdating(true);
    setLastError(null);
    setStatus("drafting");

    try {
      const project = await ensureProjectContext(spec.object_label);
      if (!isMountedRef.current || previewToken !== latestPreviewTokenRef.current) {
        return;
      }

      const response = await fetchWithTimeout(
        `${backendUrl}/preview-useful`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            structured_spec: spec,
            job_id: createJobId(),
            project_id: project?.project_id,
            parent_job_id: previewJobId,
            revision_note: revisionNote || null,
          }),
        },
        TIMEOUTS.preview
      );
      if (!response.ok) throw new Error("Could not draft a preview");

      const preview = (await response.json()) as UsefulPreviewResponse;
      if (!isMountedRef.current || previewToken !== latestPreviewTokenRef.current) {
        return;
      }

      const nextUrl = resolveUrl(backendUrl, preview.glb_url);
      const previousUrl = currentModelUrlRef.current;
      if (previousUrl && previousUrl !== nextUrl) {
        onGhostModelUrl?.(previousUrl);
      }
      currentModelUrlRef.current = nextUrl;
      setPreviewJobId(preview.preview_id);
      setStructuredSpec(preview.structured_spec);
      setLastSuccessfulSpec(preview.structured_spec);
      lastPreviewedSpecKeyRef.current = specKey;
      onModelUrl(nextUrl);
      setStatus("preview-ready");
      void refreshProjects();
    } catch (error) {
      console.error(error);
      if (!isMountedRef.current || previewToken !== latestPreviewTokenRef.current) {
        return;
      }
      setLastError((error as Error).message || "Something went wrong.");
      setStatus("error");
    } finally {
      if (!isMountedRef.current || previewToken !== latestPreviewTokenRef.current) {
        return;
      }
      previewInFlightRef.current = false;
      syncPreviewUpdating(false);
      const queued = queuedPreviewRef.current;
      queuedPreviewRef.current = null;
      if (queued && queued.specKey !== lastPreviewedSpecKeyRef.current) {
        void dispatchUsefulPreview(queued.spec, queued.specKey);
      }
    }
  };

  const scheduleUsefulPreview = (
    nextSpec: StructuredSpec,
    options?: { immediate?: boolean; force?: boolean }
  ) => {
    const immediate = options?.immediate || false;
    const force = options?.force || false;
    const specKey = stableStringify(nextSpec);

    if (!force) {
      if (specKey === lastPreviewedSpecKeyRef.current || specKey === lastRequestedSpecKeyRef.current) {
        return;
      }
    }

    const enqueue = () => {
      if (!isMountedRef.current || mode !== "useful") return;
      if (previewInFlightRef.current) {
        queuedPreviewRef.current = { spec: nextSpec, specKey };
        return;
      }
      void dispatchUsefulPreview(nextSpec, specKey);
    };

    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current);
      debounceTimerRef.current = null;
    }

    if (immediate) {
      enqueue();
      return;
    }

    debounceTimerRef.current = setTimeout(() => {
      debounceTimerRef.current = null;
      enqueue();
    }, 300);
  };

  useEffect(() => {
    if (mode !== "useful" || !structuredSpec) return;
    scheduleUsefulPreview(structuredSpec);
  }, [mode, structuredSpec]);

  const handleIdeaSubmit = async (
    textOverride?: string,
    source: "text" | "voice" = "text"
  ) => {
    const rawText = (textOverride ?? manualText).trim();
    if (!rawText || isBusy) return;
    setIsBusy(true);
    setLastError(null);
    setLibraryResults([]);
    resetOutputs();
    const project = await ensureProjectContext(rawText.slice(0, 48));

    try {
      setStatus("understanding");
      const response = await fetchWithTimeout(
        `${backendUrl}/route-intent`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            raw_text: rawText,
            source,
            mode_hint: mode,
            has_image: !!imageFile,
            project_id: project?.project_id,
            existing_spec: structuredSpec,
          }),
        },
        TIMEOUTS.route
      );
      if (!response.ok) throw new Error("Could not understand your idea");
      const routed = (await response.json()) as RouteIntentResponse;
      if (!isMountedRef.current) return;
      setRouteResult(routed);

      if (routed.mode === "useful" && routed.structured_spec) {
        setStructuredSpec(routed.structured_spec);
        setStatus("confirming");
        return;
      }

      await runCreativePipeline(routed.prompt || rawText, source, project?.project_id ?? null);
    } catch (error) {
      console.error(error);
      if (!isMountedRef.current) return;
      setStatus("error");
      setLastError((error as Error).message || "Something went wrong.");
    } finally {
      if (isMountedRef.current) {
        setIsBusy(false);
      }
    }
  };

  const runCreativePipeline = async (
    prompt: string,
    source: "voice" | "text",
    projectId?: string | null
  ) => {
    const jobId = createJobId();
    setStatus("drafting");
    const generateResponse = await fetchWithTimeout(
      `${backendUrl}/generate`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt,
          prompt_raw: manualText || prompt,
          provider: creativeProvider,
          job_id: jobId,
          input_type: source,
          project_id: projectId,
        }),
      },
      TIMEOUTS.generate
    );
    if (!generateResponse.ok) throw new Error("Creative generation failed");
    const generation = await generateResponse.json();

    setStatus("making-printable");
    const processedResponse = await fetchWithTimeout(
      `${backendUrl}/process-model`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          glb_url: generation.glb_url,
          job_id: jobId,
          provider: creativeProvider,
          input_type: source,
          prompt,
          project_id: projectId,
          mode: "creative",
        }),
      },
      TIMEOUTS.process
    );
    if (!processedResponse.ok) throw new Error("Could not make the creative object printable");
    const processed = (await processedResponse.json()) as ProcessResponse;
    if (!isMountedRef.current) return;
    const nextUrl = resolveUrl(backendUrl, processed.glb_url);
    currentModelUrlRef.current = nextUrl;
    onGhostModelUrl?.(null);
    onModelUrl(nextUrl);
    onStlUrl(resolveUrl(backendUrl, processed.stl_url));
    onGcodeUrl(resolveUrl(backendUrl, processed.gcode_url));
    onBundleUrl(resolveUrl(backendUrl, processed.bundle_url));
    setValidation(processed.validation || null);
    setStatus("ready");
    void refreshProjects();
  };

  const handleGenerateFromImage = async () => {
    if (!imageFile || isBusy) return;
    setIsBusy(true);
    setLastError(null);
    resetOutputs();
    const project = await ensureProjectContext(imageLabel || "Image concept");

    try {
      const jobId = createJobId();
      const formData = new FormData();
      formData.append("image", imageFile);
      formData.append("job_id", jobId);
      formData.append("input_type", "image");
      formData.append("project_id", project?.project_id || "");

      setStatus("drafting");
      const response = await fetchWithTimeout(
        `${backendUrl}/generate-image?provider=${encodeURIComponent(creativeProvider)}`,
        {
          method: "POST",
          body: formData,
        },
        TIMEOUTS.image
      );
      if (!response.ok) throw new Error("Image generation failed");
      const generation = await response.json();

      setStatus("making-printable");
      const processedResponse = await fetchWithTimeout(
        `${backendUrl}/process-model`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            glb_url: generation.glb_url,
            job_id: jobId,
            provider: creativeProvider,
            input_type: "image",
            prompt: manualText || imageLabel,
            project_id: project?.project_id,
            mode: "creative",
          }),
        },
        TIMEOUTS.process
      );
      if (!processedResponse.ok) throw new Error("Could not process creative image result");
      const processed = (await processedResponse.json()) as ProcessResponse;
      if (!isMountedRef.current) return;
      const nextUrl = resolveUrl(backendUrl, processed.glb_url);
      currentModelUrlRef.current = nextUrl;
      onGhostModelUrl?.(null);
      onModelUrl(nextUrl);
      onStlUrl(resolveUrl(backendUrl, processed.stl_url));
      onGcodeUrl(resolveUrl(backendUrl, processed.gcode_url));
      onBundleUrl(resolveUrl(backendUrl, processed.bundle_url));
      setValidation(processed.validation || null);
      setStatus("ready");
      void refreshProjects();
    } catch (error) {
      console.error(error);
      if (!isMountedRef.current) return;
      setStatus("error");
      setLastError((error as Error).message || "Something went wrong.");
    } finally {
      if (isMountedRef.current) {
        setIsBusy(false);
      }
    }
  };

  const handleDescribeImage = async () => {
    if (!imageFile || isBusy) return;
    setIsBusy(true);
    setLastError(null);
    try {
      const formData = new FormData();
      formData.append("image", imageFile);
      formData.append("input_type", "image");
      const response = await fetchWithTimeout(
        `${backendUrl}/image-intent`,
        { method: "POST", body: formData },
        TIMEOUTS.intent
      );
      if (!response.ok) throw new Error("Could not describe the image");
      const data = await response.json();
      if (!isMountedRef.current) return;
      setManualText((prev) =>
        prev.trim() ? `${prev.trim()}. Reference image: ${data.prompt}` : data.prompt
      );
      setStatus("confirming");
    } catch (error) {
      console.error(error);
      if (!isMountedRef.current) return;
      setStatus("error");
      setLastError((error as Error).message || "Something went wrong.");
    } finally {
      if (isMountedRef.current) {
        setIsBusy(false);
      }
    }
  };

  const updateDimension = (key: string, value: string) => {
    if (!structuredSpec) return;
    resetOutputs();
    setStructuredSpec({
      ...structuredSpec,
      dimensions_mm: {
        ...structuredSpec.dimensions_mm,
        [key]: Number(value) || 0,
      },
    });
  };

  const updateConstraint = (key: string, value: string) => {
    if (!structuredSpec) return;
    resetOutputs();
    const current = structuredSpec.constraints[key];
    let next: string | number | boolean = value;
    if (typeof current === "boolean") {
      next = value === "true";
    } else if (typeof current === "number") {
      next = Number(value) || 0;
    }
    setStructuredSpec({
      ...structuredSpec,
      constraints: {
        ...structuredSpec.constraints,
        [key]: next,
      },
    });
  };

  const handlePreviewUseful = async () => {
    if (!structuredSpec || isBusy) return;
    resetOutputs();
    scheduleUsefulPreview(structuredSpec, { immediate: true, force: true });
  };

  const handleBuildUseful = async () => {
    if (!structuredSpec || isBusy) return;
    setIsBusy(true);
    setLastError(null);
    invalidatePreviewRequests();
    try {
      setStatus("building");
      const project = await ensureProjectContext(structuredSpec.object_label);
      const response = await fetchWithTimeout(
        `${backendUrl}/build-useful`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            structured_spec: structuredSpec,
            preview_revision_id: previewJobId,
            job_id: createJobId(),
            project_id: project?.project_id,
            parent_job_id: buildJobId,
            revision_note: revisionNote || null,
          }),
        },
        TIMEOUTS.build
      );
      if (!response.ok) throw new Error("Could not export a printable STL");
      const build = (await response.json()) as UsefulBuildResponse;
      if (!isMountedRef.current) return;
      const nextUrl = resolveUrl(backendUrl, build.glb_url);
      currentModelUrlRef.current = nextUrl;
      onGhostModelUrl?.(null);
      onModelUrl(nextUrl);
      onStlUrl(resolveUrl(backendUrl, build.stl_url));
      onGcodeUrl(resolveUrl(backendUrl, build.gcode_url));
      onBundleUrl(resolveUrl(backendUrl, build.bundle_url));
      setBuildJobId(build.job_id);
      setValidation(build.validation);
      setStatus("ready");
      void refreshProjects();
    } catch (error) {
      console.error(error);
      if (!isMountedRef.current) return;
      setStatus("error");
      setLastError((error as Error).message || "Something went wrong.");
    } finally {
      if (isMountedRef.current) {
        setIsBusy(false);
      }
    }
  };

  const startListening = async () => {
    if (isBusy) return;
    if (recognitionRef.current) {
      setStatus("listening");
      setIsListening(true);
      recognitionRef.current.start();
      return;
    }
    if (!recordingSupport) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) {
          chunksRef.current.push(event.data);
        }
      };
      recorder.onstop = async () => {
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
        await sendToDeepgram(blob);
      };
      recorderRef.current = recorder;
      recorder.start();
      setIsListening(true);
      setStatus("recording");
    } catch (error) {
      console.error(error);
      setStatus("error");
    }
  };

  const stopListening = () => {
    recognitionRef.current?.stop();
    recorderRef.current?.stop();
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    setIsListening(false);
  };

  const sendToDeepgram = async (blob: Blob) => {
    setStatus("transcribing");
    try {
      const formData = new FormData();
      formData.append("audio", blob, "audio.webm");
      const response = await fetchWithTimeout(
        `${backendUrl}/stt`,
        { method: "POST", body: formData },
        TIMEOUTS.intent
      );
      if (!response.ok) throw new Error("Speech transcription failed");
      const data = await response.json();
      if (data.transcript) {
        setManualText(data.transcript);
        setTranscripts((prev) => [...prev.slice(-4), data.transcript]);
        await handleIdeaSubmit(data.transcript, "voice");
      }
    } catch (error) {
      console.error(error);
      if (!isMountedRef.current) return;
      setStatus("error");
      setLastError((error as Error).message || "Something went wrong.");
    }
  };

  const promptExamples = mode === "useful" ? usefulPromptExamples : creativePromptExamples;
  const orderedDimensionEntries = useMemo(() => {
    if (!structuredSpec) return [];
    const keys = sortKeys(
      Object.keys(structuredSpec.dimensions_mm),
      DIMENSION_ORDER[structuredSpec.template_id]
    );
    return keys.map((key) => [key, structuredSpec.dimensions_mm[key]] as const);
  }, [structuredSpec]);
  const orderedConstraintEntries = useMemo(() => {
    if (!structuredSpec) return [];
    const keys = sortKeys(
      Object.keys(structuredSpec.constraints),
      CONSTRAINT_ORDER[structuredSpec.template_id]
    );
    return keys.map((key) => [key, structuredSpec.constraints[key]] as const);
  }, [structuredSpec]);

  return (
    <section className="panel">
      <div className="panel-header">
        <p className="eyebrow">Voice-First Designer</p>
        <h2>Describe the object you want to print</h2>
        <p className="panel-subtitle">
          Speak first, confirm what the system detected, refine the live preview,
          and then export a printable STL.
        </p>
      </div>

      <div className="panel-body">
        {!hideModeSwitch ? (
          <div className="mode-switch" role="tablist" aria-label="Object type">
            <button
              type="button"
              className={`mode-chip ${mode === "useful" ? "active" : ""}`}
              onClick={() => setMode("useful")}
            >
              Useful Object
            </button>
            <button
              type="button"
              className={`mode-chip ${mode === "creative" ? "active" : ""}`}
              onClick={() => setMode("creative")}
            >
              Creative Object (Beta)
            </button>
          </div>
        ) : null}

        <div className="status-card">
          <div className="status-label">Current stage</div>
          <div className="status-value">{humanStatus(status)}</div>
          <div className="intent muted">
            {routeResult?.route_reason ||
              (mode === "useful"
                ? "Use voice first for stands, holders, trays, hooks, and other practical prints."
                : "Creative mode keeps the mesh-generation path available for figurines and decorative objects.")}
          </div>
          {mode === "useful" && structuredSpec ? (
            <div className="status-chip-row">
              <span className="chip">Auto preview on</span>
              {isPreviewUpdating ? <span className="chip chip-warm">Updating</span> : null}
              {lastSuccessfulSpec ? <span className="chip">Live preview ready</span> : null}
            </div>
          ) : null}
        </div>

        <div className="voice-surface">
          <div>
            <div className="voice-title">Push to talk</div>
            <div className="muted">Voice is the fastest path into the Useful Object flow.</div>
          </div>
          <div className="voice-actions">
            <button
              type="button"
              className={`voice-button ${isListening ? "active" : ""}`}
              onClick={isListening ? stopListening : startListening}
              disabled={isBusy || (!speechSupport && !recordingSupport)}
            >
              {isListening ? "Stop listening" : "Start talking"}
            </button>
          </div>
        </div>

        {interim ? <div className="interim-card">"{interim}"</div> : null}

        <div className="field-row">
          <label htmlFor="project">Project</label>
          <select
            id="project"
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
              disabled={isBusy}
            >
              New project
            </button>
            <button
              type="button"
              className="text-submit"
              onClick={refreshProjects}
              disabled={isLoadingProjects || isBusy}
            >
              {isLoadingProjects ? "Refreshing..." : "Refresh projects"}
            </button>
          </div>
        </div>

        <form
          className="field-row"
          onSubmit={(event: FormEvent<HTMLFormElement>) => {
            event.preventDefault();
            void handleIdeaSubmit();
          }}
        >
          <label htmlFor="manual-text">Describe your object</label>
          <textarea
            id="manual-text"
            rows={4}
            value={manualText}
            onChange={(event) => setManualText(event.target.value)}
            placeholder={
              mode === "useful"
                ? "Make me a phone stand, 12 cm tall, angled, with a cable hole"
                : "Describe the creative object you want to generate"
            }
            disabled={isBusy}
          />
          <div className="prompt-chips">
            {promptExamples.map((chip) => (
              <button
                key={chip}
                type="button"
                className="prompt-chip"
                onClick={() => setManualText(chip)}
                disabled={isBusy}
              >
                {chip}
              </button>
            ))}
          </div>
          <div className="text-input-actions">
            <button type="submit" className="text-submit" disabled={!manualText.trim() || isBusy}>
              {mode === "useful" ? "Understand my idea" : "Generate creative object"}
            </button>
            {transcripts.length ? (
              <span className="muted">Last heard: {transcripts[transcripts.length - 1]}</span>
            ) : null}
          </div>
        </form>

        <div className="field-row">
          <label htmlFor="image-upload">Reference image</label>
          <input
            id="image-upload"
            type="file"
            accept="image/png,image/jpeg,image/webp"
            onChange={(event: ChangeEvent<HTMLInputElement>) =>
              setImageFile(event.target.files?.[0] || null)
            }
            disabled={isBusy}
          />
          <span className="muted">
            {imageLabel
              ? `Selected: ${imageLabel}`
              : "Optional reference. Helpful for creative mode and useful-object clarification."}
          </span>
          <div className="text-input-actions">
            <button
              type="button"
              className="text-submit"
              onClick={handleDescribeImage}
              disabled={!imageFile || isBusy}
            >
              Describe image
            </button>
            {mode === "creative" ? (
              <button
                type="button"
                className="text-submit"
                onClick={handleGenerateFromImage}
                disabled={!imageFile || isBusy}
              >
                Generate from image
              </button>
            ) : null}
          </div>
        </div>

        <details className="advanced-panel" open={showAdvanced}>
          <summary onClick={() => setShowAdvanced((prev) => !prev)}>
            Advanced options
          </summary>
          <div className="field-row">
            <label htmlFor="provider">Creative provider override</label>
            <select
              id="provider"
              value={creativeProvider}
              onChange={(event) => setCreativeProvider(event.target.value)}
            >
              <option value="meshy">Meshy</option>
              <option value="tripo">Tripo</option>
              <option value="trellis2">Trellis2</option>
              <option value="triposr">TripoSR</option>
            </select>
            <span className="muted">
              Provider choice stays secondary to the workflow. Useful Object mode still routes
              into the template-backed CAD path.
            </span>
          </div>
          {health?.warnings?.length ? (
            <div className="health-card warning">
              <div className="status-label">Readiness</div>
              <div className="health-body">
                {health.warnings.map((warning) => (
                  <span key={warning} className="warning-chip">
                    {warning}
                  </span>
                ))}
              </div>
            </div>
          ) : null}
        </details>

        {structuredSpec ? (
          <div className="spec-panel">
            <div className="panel-header">
              <p className="eyebrow">Confirm Intent</p>
              <h2>{structuredSpec.object_label}</h2>
              <p className="panel-subtitle">
                Confidence {Math.round(structuredSpec.confidence * 100)}%. Edit the dimensions
                and parameters below. Preview updates automatically.
              </p>
            </div>

            <div className="parametric-hint">
              Live preview updates after you stop typing. Build stays explicit so slicing only
              happens when you export the printable STL.
            </div>

            <div className="spec-grid">
              {orderedDimensionEntries.map(([key, value]) => (
                <label key={key} className="field-row compact-field">
                  <span>{key.replace(/_/g, " ")}</span>
                  <input
                    type="number"
                    value={value}
                    onChange={(event) => updateDimension(key, event.target.value)}
                    disabled={isBusy}
                  />
                </label>
              ))}
              {orderedConstraintEntries.map(([key, value]) => (
                <label key={key} className="field-row compact-field">
                  <span>{key.replace(/_/g, " ")}</span>
                  {typeof value === "boolean" ? (
                    <select
                      value={value ? "true" : "false"}
                      onChange={(event) => updateConstraint(key, event.target.value)}
                      disabled={isBusy}
                    >
                      <option value="true">True</option>
                      <option value="false">False</option>
                    </select>
                  ) : (
                    <input
                      type="number"
                      value={String(value)}
                      onChange={(event) => updateConstraint(key, event.target.value)}
                      disabled={isBusy}
                    />
                  )}
                </label>
              ))}
            </div>

            <div className="project-summary">
              <div className="status-label">Assumptions</div>
              {structuredSpec.assumptions.length ? (
                <div className="warning-list">
                  {structuredSpec.assumptions.map((assumption) => (
                    <span key={assumption} className="warning-chip subtle">
                      {assumption}
                    </span>
                  ))}
                </div>
              ) : (
                <div className="muted">No hidden defaults beyond the current parameter values.</div>
              )}
            </div>

            <div className="field-row">
              <label htmlFor="revision-note">Edit note</label>
              <textarea
                id="revision-note"
                rows={2}
                value={revisionNote}
                onChange={(event) => setRevisionNote(event.target.value)}
                placeholder="Optional note such as make it taller or thicken the base"
                disabled={isBusy}
              />
            </div>

            <div className="text-input-actions">
              <button
                type="button"
                className="text-submit"
                onClick={handlePreviewUseful}
                disabled={isBusy}
              >
                Draft preview
              </button>
              <button
                type="button"
                className="text-submit"
                onClick={handleBuildUseful}
                disabled={isBusy}
              >
                Export printable STL
              </button>
            </div>
          </div>
        ) : null}

        {validation ? (
          <div className="validation-card">
            <div className="status-label">Printability report</div>
            <div className="validation-headline">
              {validation.validation_status || "unknown"} · risk {validation.estimated_print_risk || "unknown"}
            </div>
            {validation.dimensions_mm?.length ? (
              <div className="muted">
                Final size: {validation.dimensions_mm.join(" × ")} mm
              </div>
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

        {mode === "creative" && libraryResults.length > 0 ? (
          <div className="project-summary">
            <div className="status-label">Library results</div>
            <div className="muted">{libraryResults.length} results available.</div>
          </div>
        ) : null}
      </div>
    </section>
  );
}
