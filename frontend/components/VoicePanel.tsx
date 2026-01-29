"use client";

import type { ChangeEvent, FormEvent, MouseEvent } from "react";
import { useEffect, useRef, useState } from "react";

const localBackendUrl = "http://localhost:8000";
const prodBackendUrl = "https://pulsai-3d-backend-37089211614.us-central1.run.app";

const resolveBackendUrl = () => {
  if (process.env.NEXT_PUBLIC_BACKEND_URL) return process.env.NEXT_PUBLIC_BACKEND_URL;
  if (typeof window !== "undefined") {
    const host = window.location.hostname;
    if (host && host !== "localhost" && host !== "127.0.0.1") {
      return prodBackendUrl;
    }
  }
  return localBackendUrl;
};

const resolveUrl = (base: string, value?: string | null) => {
  if (!value) return null;
  if (value.startsWith("http")) return value;
  return `${base.replace(/\/$/, "")}${value.startsWith("/") ? "" : "/"}${value}`;
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

type VoicePanelProps = {
  onModelUrl: (url: string | null) => void;
  onGcodeUrl: (url: string | null) => void;
  onBundleUrl: (url: string | null) => void;
};

type LibraryItem = {
  id: string;
  title: string;
  tags?: string[];
  glb_url?: string;
  source?: string;
  license?: string;
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
  sketchfab_enabled?: boolean;
  providers?: Record<string, ProviderInfo>;
  warnings?: string[];
};

type RunContext = {
  text: string;
  source: "voice" | "text" | "image";
  provider: string;
  librarySource?: string;
  prompt?: string;
  projectId?: string | null;
  parentJobId?: string | null;
  editMode?: string;
  inputType?: "voice" | "text" | "image" | "library";
  jobId?: string;
  glbUrl?: string;
  libraryItem?: LibraryItem;
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
  intent: 20000,
  library: 15000,
  resolve: 20000,
  generate: 180000,
  process: 180000,
  image: 300000,
};

const promptChips = [
  "box 80x40x20 mm, hollow, wall 3 mm",
  "cylinder dia 40 mm height 60 mm, hole 10 mm",
  "sphere 50 mm, rounded 2 mm",
  "phone stand angle 65 deg, base 120x70x6 mm",
];

export default function VoicePanel({ onModelUrl, onGcodeUrl, onBundleUrl }: VoicePanelProps) {
  const [isListening, setIsListening] = useState(false);
  const [status, setStatus] = useState("idle");
  const [intent, setIntent] = useState<string | null>(null);
  const [transcripts, setTranscripts] = useState<string[]>([]);
  const [interim, setInterim] = useState<string | null>(null);
  const [provider, setProvider] = useState("parametric");
  const [sttProvider, setSttProvider] = useState("browser");
  const [librarySource, setLibrarySource] = useState("local");
  const [libraryResults, setLibraryResults] = useState<LibraryItem[]>([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const [manualText, setManualText] = useState("");
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [imageLabel, setImageLabel] = useState<string | null>(null);
  const [pendingJobId, setPendingJobId] = useState<string | null>(null);
  const [pendingSource, setPendingSource] = useState<"image" | "text" | null>(null);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [activeProjectId, setActiveProjectId] = useState<string | null>(null);
  const [isLoadingProjects, setIsLoadingProjects] = useState(false);
  const [speechSupport, setSpeechSupport] = useState(false);
  const [recordingSupport, setRecordingSupport] = useState(false);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [lastRun, setLastRun] = useState<RunContext | null>(null);
  const [lastError, setLastError] = useState<string | null>(null);
  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const slicingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const backendUrl = resolveBackendUrl();

  const createJobId = () => {
    if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
      return crypto.randomUUID();
    }
    return `job-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  };

  useEffect(() => {
    if (typeof window === "undefined") return;
    const supportsSpeech =
      !!(window as Window).SpeechRecognition || !!(window as Window).webkitSpeechRecognition;
    const supportsRecording =
      typeof MediaRecorder !== "undefined" && !!navigator.mediaDevices?.getUserMedia;
    setSpeechSupport(supportsSpeech);
    setRecordingSupport(supportsRecording);
  }, []);

  useEffect(() => {
    void refreshProjects();
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const loadHealth = async () => {
      try {
        const response = await fetchWithTimeout(
          `${backendUrl}/health`,
          undefined,
          TIMEOUTS.health
        );
        if (!response.ok) throw new Error("Health check failed");
        const data = (await response.json()) as HealthResponse;
        setHealth(data);
      } catch (error) {
        console.warn("Health check failed", error);
        setHealth(null);
      }
    };
    void loadHealth();
  }, [backendUrl]);

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

      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
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
        setInterim(null);
        handleFinalTranscript(finalTranscript.trim(), "voice");
      }
    };

    recognition.onerror = () => {
      setStatus("error");
      setIsListening(false);
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
      setProjects((data.items || []) as ProjectSummary[]);
    } catch (error) {
      console.error(error);
    } finally {
      setIsLoadingProjects(false);
    }
  };

  const createProject = async (name?: string) => {
    try {
      const response = await fetchWithTimeout(
        `${backendUrl}/projects`,
        {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name })
        },
        TIMEOUTS.projects
      );
      if (!response.ok) throw new Error("Project create failed");
      const data = await response.json();
      return data.project as ProjectSummary;
    } catch (error) {
      console.error(error);
      return null;
    }
  };

  const ensureProjectContext = async (label?: string) => {
    const activeProject = projects.find((item) => item.project_id === activeProjectId);
    if (activeProject) return activeProject;
    const name = label?.trim() ? label.trim().slice(0, 60) : "New 3D Project";
    const created = await createProject(name);
    if (created) {
      setProjects((prev) => [created, ...prev]);
      setActiveProjectId(created.project_id);
    }
    return created;
  };

  const handleFinalTranscript = async (text: string, source: "voice" | "text") => {
    setTranscripts((prev) => [...prev.slice(-5), text]);
    await runPipeline(text, source);
  };

  const handleManualSubmit = async (
    event?: FormEvent<HTMLFormElement> | MouseEvent<HTMLButtonElement>
  ) => {
    event?.preventDefault();
    const trimmed = manualText.trim();
    if (!trimmed || isProcessing) return;
    const source = pendingSource ?? "text";
    const jobId = pendingJobId ?? undefined;
    setPendingJobId(null);
    setPendingSource(null);
    setManualText("");
    await runPipeline(trimmed, source, jobId);
  };

  const handleImageSelect = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] || null;
    setImageFile(file);
  };

  const runPipeline = async (
    text: string,
    source: "voice" | "text" | "image",
    jobIdOverride?: string,
    providerOverride?: string
  ) => {
    if (isProcessing) return;
    setIsProcessing(true);
    const activeProvider = providerOverride ?? provider;
    setStatus("queued");
    setLastError(null);
    onBundleUrl(null);
    const project = await ensureProjectContext(text);
    const jobId = jobIdOverride ?? createJobId();
    const parentJobId = project?.current_job_id;
    const editMode = parentJobId ? "prompt_only" : undefined;
    setIntent(null);
    setLibraryResults([]);

    try {
      if (activeProvider === "llama-mesh") {
        setStatus("not-configured");
        setIntent("Llama-Mesh local setup not installed.");
        return;
      }
      if (activeProvider === "triposr" && source !== "image") {
        setStatus("image-only");
        setIntent("TripoSR requires an image input. Upload an image to run.");
        return;
      }
      const shouldExtract =
        activeProvider !== "parametric" && activeProvider !== "library" && source !== "image";
      let prompt = text;
      if (shouldExtract) {
        setStatus("extracting");
        try {
          const extracted = await fetchIntent(
            text,
            jobId,
            source as "voice" | "text",
            project?.project_id
          );
          if (extracted) {
            prompt = extracted;
          }
        } catch (error) {
          console.warn("Intent extraction failed; using raw text.", error);
        }
      }
      prompt = prompt.trim();
      if (!prompt) throw new Error("No prompt available");

      setIntent(prompt);
      setLastRun({
        text,
        source,
        provider: activeProvider,
        librarySource,
        prompt,
        projectId: project?.project_id ?? null,
        parentJobId,
        editMode,
        inputType: source,
        jobId
      });

      if (activeProvider === "library") {
        setStatus("library-search");
        const results = await searchLibrary(prompt, librarySource);
        setLibraryResults(results);
        setIsProcessing(false);
        return;
      }

      setStatus("generating");
      const generation = await generateModel(
        prompt,
        activeProvider,
        jobId,
        source,
        text,
        project?.project_id,
        parentJobId,
        editMode
      );
      setLastRun((prev) =>
        prev ? { ...prev, glbUrl: generation.glb_url, jobId } : prev
      );

      setStatus("repairing");
      if (slicingTimerRef.current) {
        clearTimeout(slicingTimerRef.current);
      }
      slicingTimerRef.current = setTimeout(() => {
        setStatus((current) => (current === "repairing" ? "slicing" : current));
      }, 4000);
      const processed = await processModel(generation.glb_url, jobId, {
        provider: activeProvider,
        input_type: source,
        prompt,
        project_id: project?.project_id,
        parent_job_id: parentJobId,
        edit_mode: editMode
      });

      onModelUrl(resolveUrl(backendUrl, processed.glb_url));
      onGcodeUrl(resolveUrl(backendUrl, processed.gcode_url));
      setStatus(processed.gcode_url ? "gcode-ready" : "preview-ready");
      if (jobId) {
        await fetchBundleUrl(jobId);
      }
      void refreshProjects();
    } catch (error) {
      console.error(error);
      if (error instanceof TimeoutError || (error as DOMException)?.name === "AbortError") {
        setStatus("timeout");
      } else {
        setStatus("error");
      }
      setLastError((error as Error)?.message ?? "Something went wrong.");
    } finally {
      if (slicingTimerRef.current) {
        clearTimeout(slicingTimerRef.current);
        slicingTimerRef.current = null;
      }
      setIsProcessing(false);
    }
  };

  const fetchIntent = async (
    transcript: string,
    jobId: string,
    inputType: "voice" | "text",
    projectId?: string | null
  ): Promise<string | null> => {
    const response = await fetchWithTimeout(
      `${backendUrl}/intent`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          transcript,
          job_id: jobId,
          input_type: inputType,
          project_id: projectId
        })
      },
      TIMEOUTS.intent
    );
    if (!response.ok) throw new Error("Intent extraction failed");
    const data = await response.json();
    return data.prompt ?? null;
  };

  const generateModel = async (
    prompt: string,
    providerName: string,
    jobId: string,
    inputType: "voice" | "text" | "image",
    promptRaw: string,
    projectId?: string | null,
    parentJobId?: string | null,
    editMode?: string
  ) => {
    const response = await fetchWithTimeout(
      `${backendUrl}/generate`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt,
          provider: providerName,
          job_id: jobId,
          input_type: inputType,
          prompt_raw: promptRaw,
          project_id: projectId,
          parent_job_id: parentJobId,
          edit_mode: editMode
        })
      },
      TIMEOUTS.generate
    );
    if (!response.ok) throw new Error("Generation failed");
    return response.json();
  };

  const processModel = async (
    glbUrl: string,
    jobId?: string | null,
    metadata?: {
      provider?: string;
      input_type?: string;
      prompt?: string;
      library_id?: string;
      library_source?: string;
      library_title?: string;
      project_id?: string;
      parent_job_id?: string;
      edit_mode?: string;
    }
  ) => {
    const response = await fetchWithTimeout(
      `${backendUrl}/process-model`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          glb_url: glbUrl,
          job_id: jobId,
          ...metadata
        })
      },
      TIMEOUTS.process
    );
    if (!response.ok) throw new Error("Processing failed");
    return response.json();
  };

  const fetchBundleUrl = async (jobId: string) => {
    try {
      const response = await fetchWithTimeout(
        `${backendUrl}/bundle/${encodeURIComponent(jobId)}`,
        undefined,
        TIMEOUTS.process
      );
      if (!response.ok) {
        onBundleUrl(null);
        return;
      }
      const data = await response.json();
      onBundleUrl(resolveUrl(backendUrl, data.url));
    } catch (error) {
      console.warn("Bundle fetch failed", error);
      onBundleUrl(null);
    }
  };

  const generateFromImage = async () => {
    if (!imageFile || isProcessing) return;
    setIsProcessing(true);
    setLastError(null);
    const project = await ensureProjectContext(imageLabel ?? "Image reference");
    const jobId = createJobId();
    const parentJobId = project?.current_job_id;
    const editMode = parentJobId ? "image" : undefined;
    setStatus("uploading-image");
    setIntent(`Image to model (${provider})`);
    setLibraryResults([]);
    setLastRun({
      text: imageLabel ?? "Image reference",
      source: "image",
      provider,
      prompt: `Image to model (${provider})`,
      projectId: project?.project_id ?? null,
      parentJobId,
      editMode,
      inputType: "image",
      jobId
    });
    try {
      const formData = new FormData();
      formData.append("image", imageFile);
      formData.append("job_id", jobId);
      formData.append("input_type", "image");
      if (project?.project_id) {
        formData.append("project_id", project.project_id);
      }
      if (parentJobId) {
        formData.append("parent_job_id", parentJobId);
      }
      if (editMode) {
        formData.append("edit_mode", editMode);
      }
      const response = await fetchWithTimeout(
        `${backendUrl}/generate-image?provider=${encodeURIComponent(provider)}`,
        {
          method: "POST",
          body: formData
        },
        TIMEOUTS.image
      );
      if (!response.ok) throw new Error("Image generation failed");
      const generation = await response.json();
      setLastRun((prev) => (prev ? { ...prev, glbUrl: generation.glb_url, jobId } : prev));
      setStatus("repairing");
      if (slicingTimerRef.current) {
        clearTimeout(slicingTimerRef.current);
      }
      slicingTimerRef.current = setTimeout(() => {
        setStatus((current) => (current === "repairing" ? "slicing" : current));
      }, 4000);
      const processed = await processModel(generation.glb_url, jobId, {
        provider,
        input_type: "image",
        project_id: project?.project_id,
        parent_job_id: parentJobId,
        edit_mode: editMode
      });
      onModelUrl(resolveUrl(backendUrl, processed.glb_url));
      onGcodeUrl(resolveUrl(backendUrl, processed.gcode_url));
      setStatus(processed.gcode_url ? "gcode-ready" : "preview-ready");
      if (jobId) {
        await fetchBundleUrl(jobId);
      }
      void refreshProjects();
    } catch (error) {
      console.error(error);
      if (error instanceof TimeoutError || (error as DOMException)?.name === "AbortError") {
        setStatus("timeout");
      } else {
        setStatus("error");
      }
      setLastError((error as Error)?.message ?? "Something went wrong.");
    } finally {
      if (slicingTimerRef.current) {
        clearTimeout(slicingTimerRef.current);
        slicingTimerRef.current = null;
      }
      setIsProcessing(false);
    }
  };

  const generatePromptFromImage = async () => {
    if (!imageFile || isProcessing) return;
    setIsProcessing(true);
    setLastError(null);
    const project = await ensureProjectContext(imageLabel ?? "Image reference");
    const jobId = createJobId();
    const parentJobId = project?.current_job_id;
    const editMode = parentJobId ? "image" : undefined;
    setPendingJobId(jobId);
    setPendingSource("image");
    setStatus("extracting-image");
    setIntent(null);
    try {
      const formData = new FormData();
      formData.append("image", imageFile);
      formData.append("job_id", jobId);
      formData.append("input_type", "image");
      if (project?.project_id) {
        formData.append("project_id", project.project_id);
      }
      if (parentJobId) {
        formData.append("parent_job_id", parentJobId);
      }
      if (editMode) {
        formData.append("edit_mode", editMode);
      }
      const response = await fetchWithTimeout(
        `${backendUrl}/image-intent`,
        {
          method: "POST",
          body: formData
        },
        TIMEOUTS.intent
      );
      if (!response.ok) throw new Error("Image prompt failed");
      const data = await response.json();
      const prompt = data.prompt || "";
      setManualText(prompt);
      setIntent(prompt || null);
      setStatus("image-prompt-ready");
    } catch (error) {
      console.error(error);
      setPendingJobId(null);
      setPendingSource(null);
      if (error instanceof TimeoutError || (error as DOMException)?.name === "AbortError") {
        setStatus("timeout");
      } else {
        setStatus("error");
      }
      setLastError((error as Error)?.message ?? "Something went wrong.");
    } finally {
      setIsProcessing(false);
    }
  };

  const searchLibrary = async (query: string, source: string) => {
    const response = await fetchWithTimeout(
      `${backendUrl}/library/search?query=${encodeURIComponent(query)}&provider=${source}`,
      undefined,
      TIMEOUTS.library
    );
    if (!response.ok) throw new Error("Library search failed");
    const data = await response.json();
    return (data.items || []) as LibraryItem[];
  };

  const resolveLibraryItem = async (item: LibraryItem): Promise<string | null> => {
    if (item.glb_url) return item.glb_url;
    const response = await fetchWithTimeout(
      `${backendUrl}/library/resolve?uid=${encodeURIComponent(item.id)}&provider=${librarySource}`,
      undefined,
      TIMEOUTS.resolve
    );
    if (!response.ok) throw new Error("Library item download failed");
    const data = await response.json();
    return data.glb_url ?? null;
  };

  const useLibraryItem = async (item: LibraryItem) => {
    try {
      const project = await ensureProjectContext(item.title);
      const jobId = createJobId();
      const parentJobId = project?.current_job_id;
      const editMode = parentJobId ? "library" : undefined;
      setLastRun({
        text: item.title,
        source: "text",
        provider: "library",
        librarySource,
        prompt: intent ?? item.title,
        projectId: project?.project_id ?? null,
        parentJobId,
        editMode,
        inputType: "library",
        jobId,
        libraryItem: item
      });
      setStatus("fetching-model");
      const resolvedUrl = await resolveLibraryItem(item);
      if (!resolvedUrl) {
        throw new Error("No downloadable GLB available");
      }
      setLastRun((prev) => (prev ? { ...prev, glbUrl: resolvedUrl } : prev));
      onModelUrl(resolvedUrl);
      onGcodeUrl(null);
      setStatus("preview-ready");
      const processed = await processModel(resolvedUrl, jobId, {
        provider: "library",
        input_type: "library",
        prompt: intent || undefined,
        library_id: item.id,
        library_source: librarySource,
        library_title: item.title,
        project_id: project?.project_id,
        parent_job_id: parentJobId,
        edit_mode: editMode
      });
      onModelUrl(resolveUrl(backendUrl, processed.glb_url) || resolvedUrl);
      onGcodeUrl(resolveUrl(backendUrl, processed.gcode_url));
      setStatus(processed.gcode_url ? "gcode-ready" : "preview-ready");
      if (jobId) {
        await fetchBundleUrl(jobId);
      }
      void refreshProjects();
    } catch (error) {
      console.error(error);
      if (error instanceof TimeoutError || (error as DOMException)?.name === "AbortError") {
        setStatus("timeout");
      } else {
        setStatus("error");
      }
      setLastError((error as Error)?.message ?? "Something went wrong.");
    }
  };

  const startListening = async () => {
    if (isProcessing) return;
    if (sttProvider === "browser") {
      if (!recognitionRef.current) return;
      setStatus("listening");
      setIsListening(true);
      recognitionRef.current.start();
      return;
    }

    if (!recordingSupport) {
      setStatus("error");
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const mimeTypes = [
        "audio/webm;codecs=opus",
        "audio/webm",
        "audio/mp4"
      ];
      const mimeType = mimeTypes.find((type) => MediaRecorder.isTypeSupported(type));
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      chunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) {
          chunksRef.current.push(event.data);
        }
      };
      recorder.onstop = async () => {
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType });
        await sendToDeepgram(blob);
      };
      recorderRef.current = recorder;
      setStatus("recording");
      setIsListening(true);
      recorder.start();
    } catch (error) {
      console.error(error);
      setStatus("error");
      setIsListening(false);
    }
  };

  const stopListening = () => {
    if (sttProvider === "browser") {
      recognitionRef.current?.stop();
      setIsListening(false);
      return;
    }

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
        {
          method: "POST",
          body: formData
        },
        TIMEOUTS.intent
      );
      if (!response.ok) throw new Error("STT failed");
      const data = await response.json();
      if (data.transcript) {
        await handleFinalTranscript(data.transcript, "voice");
      } else {
        setStatus("error");
      }
    } catch (error) {
      console.error(error);
      setStatus("error");
      setLastError((error as Error)?.message ?? "Something went wrong.");
    }
  };

  const retryPipeline = async () => {
    if (!lastRun || isProcessing) return;
    if (lastRun.provider !== provider) {
      setProvider(lastRun.provider);
    }
    if (lastRun.provider === "library" && lastRun.libraryItem) {
      await useLibraryItem(lastRun.libraryItem);
      return;
    }
    await runPipeline(lastRun.text, lastRun.source, undefined, lastRun.provider);
  };

  const retrySlicing = async () => {
    if (!lastRun?.glbUrl || isProcessing) return;
    setIsProcessing(true);
    setStatus("repairing");
    setLastError(null);
    const jobId = createJobId();
    try {
      if (slicingTimerRef.current) {
        clearTimeout(slicingTimerRef.current);
      }
      slicingTimerRef.current = setTimeout(() => {
        setStatus((current) => (current === "repairing" ? "slicing" : current));
      }, 4000);
      const processed = await processModel(lastRun.glbUrl, jobId, {
        provider: lastRun.provider,
        input_type: lastRun.inputType ?? lastRun.source,
        prompt: lastRun.prompt,
        library_id: lastRun.libraryItem?.id,
        library_source: lastRun.librarySource,
        library_title: lastRun.libraryItem?.title,
        project_id: lastRun.projectId ?? undefined,
        parent_job_id: lastRun.parentJobId ?? undefined,
        edit_mode: lastRun.editMode
      });
      onModelUrl(resolveUrl(backendUrl, processed.glb_url));
      onGcodeUrl(resolveUrl(backendUrl, processed.gcode_url));
      setStatus(processed.gcode_url ? "gcode-ready" : "preview-ready");
      await fetchBundleUrl(jobId);
      void refreshProjects();
    } catch (error) {
      console.error(error);
      if (error instanceof TimeoutError || (error as DOMException)?.name === "AbortError") {
        setStatus("timeout");
      } else {
        setStatus("error");
      }
      setLastError((error as Error)?.message ?? "Something went wrong.");
    } finally {
      if (slicingTimerRef.current) {
        clearTimeout(slicingTimerRef.current);
        slicingTimerRef.current = null;
      }
      setIsProcessing(false);
    }
  };

  return (
    <section className="panel">
      <div className="panel-header">
        <p className="eyebrow">Live Voice Session</p>
        <h2>Speak your design intent</h2>
        <p className="panel-subtitle">
          Push to talk and describe the object you want to print. The system
          will extract a prompt, generate a 3D model, repair it, and slice it
          for G-code.
        </p>
      </div>

      <div className="panel-body">
        <div className="field-row">
          <label htmlFor="project">Project</label>
          <select
            id="project"
            value={activeProjectId || ""}
            onChange={(event) =>
              setActiveProjectId(event.target.value ? event.target.value : null)
            }
          >
            <option value="">New project (auto)</option>
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
              onClick={() => {
                setActiveProjectId(null);
                setPendingJobId(null);
                setPendingSource(null);
                setManualText("");
              }}
              disabled={isProcessing}
            >
              New project
            </button>
            <button
              type="button"
              className="text-submit"
              onClick={refreshProjects}
              disabled={isLoadingProjects || isProcessing}
            >
              {isLoadingProjects ? "Refreshing..." : "Refresh list"}
            </button>
          </div>
          {activeProjectId ? (
            <span className="muted">Edits will be saved to the selected project.</span>
          ) : (
            <span className="muted">A new project is created on first run.</span>
          )}
        </div>

        <div className="field-row">
          <label htmlFor="stt">Speech input</label>
          <select
            id="stt"
            value={sttProvider}
            onChange={(event) => setSttProvider(event.target.value)}
          >
            <option value="browser">Browser STT (free)</option>
            <option value="deepgram" disabled={!recordingSupport}>
              Deepgram STT (server)
            </option>
          </select>
          {!speechSupport && sttProvider === "browser" ? (
            <span className="muted">Browser STT not supported here.</span>
          ) : null}
          {!recordingSupport && sttProvider === "deepgram" ? (
            <span className="muted">Recording not supported in this browser.</span>
          ) : null}
        </div>

        <div className="field-row">
          <label htmlFor="provider">3D provider</label>
          <select
            id="provider"
            value={provider}
            onChange={(event) => setProvider(event.target.value)}
          >
            <option value="parametric">Parametric (free)</option>
            <option value="meshy">
              Meshy (paid){health?.providers?.meshy?.enabled === false ? " — key missing" : ""}
            </option>
            <option value="tripo">
              Tripo (paid){health?.providers?.tripo?.enabled === false ? " — key missing" : ""}
            </option>
            <option value="trellis2">
              Trellis2 (image-to-3D)
              {health?.providers?.trellis2?.enabled === false ? " — endpoint missing" : ""}
            </option>
            <option value="triposr">
              TripoSR (local, image-to-3D)
              {health?.providers?.triposr?.enabled === false ? " — not configured" : ""}
            </option>
            <option value="library">Model library</option>
            <option value="llama-mesh">Llama-Mesh (local, not installed)</option>
          </select>
          {health ? (
            health.warnings?.length ? (
              <div className="health-card warning">
                <div className="status-label">Provider readiness</div>
                <div className="health-body">
                  {health.warnings.map((warning) => (
                    <span key={warning} className="warning-chip">{warning}</span>
                  ))}
                </div>
                <span className="muted">Add API keys in Cloud Run env vars to enable providers.</span>
              </div>
            ) : (
              <span className="muted">Providers are ready.</span>
            )
          ) : (
            <span className="muted">Health check unavailable.</span>
          )}
        </div>

        {provider === "llama-mesh" ? (
          <div className="field-row">
            <span className="muted">
              Llama-Mesh requires a local install and a dedicated GPU. This
              prototype does not install it automatically.
            </span>
          </div>
        ) : null}

        {provider === "library" ? (
          <div className="field-row">
            <label htmlFor="library">Library source</label>
            <select
              id="library"
              value={librarySource}
              onChange={(event) => setLibrarySource(event.target.value)}
            >
              <option value="local">Local catalog</option>
              <option value="sketchfab">
                Sketchfab (token)
                {health?.providers?.library_sketchfab?.enabled === false ? " — token missing" : ""}
              </option>
            </select>
          </div>
        ) : null}

        {provider === "trellis2" ? (
          <div className="field-row">
            <span className="muted">
              Trellis2 runs image-to-3D on a GPU service. Prompt-only runs require a
              custom text endpoint.
            </span>
          </div>
        ) : null}

        {provider === "triposr" ? (
          <div className="field-row">
            <span className="muted">
              TripoSR is image-to-3D only and runs locally. Use the image upload
              flow to test quality.
            </span>
          </div>
        ) : null}

        {provider === "tripo" || provider === "meshy" || provider === "trellis2" || provider === "triposr" ? (
          <div className="field-row">
            <label htmlFor="image-upload">
              Image to model (
              {provider === "meshy"
                ? "Meshy"
                : provider === "tripo"
                  ? "Tripo"
                  : provider === "trellis2"
                    ? "Trellis2"
                    : "TripoSR"}
              )
            </label>
            <input
              id="image-upload"
              type="file"
              accept="image/png,image/jpeg,image/webp"
              onChange={handleImageSelect}
              disabled={isProcessing}
            />
            {imageLabel ? (
              <span className="muted">Selected: {imageLabel}</span>
            ) : (
              <span className="muted">JPEG/PNG/WebP, max 20MB.</span>
            )}
            <div className="text-input-actions">
              <button
                type="button"
                className="text-submit"
                onClick={generateFromImage}
                disabled={!imageFile || isProcessing}
              >
                Generate from image
              </button>
              <button
                type="button"
                className="text-submit"
                onClick={generatePromptFromImage}
                disabled={!imageFile || isProcessing}
              >
                Generate prompt from image
              </button>
              <span className="muted">
                Use image-to-3D directly or extract a prompt first.
              </span>
            </div>
          </div>
        ) : null}

        <form className="field-row" onSubmit={handleManualSubmit}>
          <label htmlFor="manual-text">Text prompt (optional)</label>
          <textarea
            id="manual-text"
            rows={3}
            placeholder="Describe the object you want to print..."
            value={manualText}
            onChange={(event) => setManualText(event.target.value)}
            disabled={isProcessing}
          />
          {provider === "parametric" ? (
            <div className="parametric-hint">
              Examples: “box 80x40x20 mm, hollow, wall 3 mm”, “cylinder dia 40
              mm height 60 mm, hole 10 mm”, “sphere 50 mm, rounded 2 mm”, “phone
              stand angle 65 deg”.
            </div>
          ) : null}
          {provider === "parametric" ? (
            <div className="prompt-chips">
              {promptChips.map((chip) => (
                <button
                  key={chip}
                  type="button"
                  className="prompt-chip"
                  onClick={() => setManualText(chip)}
                  disabled={isProcessing}
                >
                  {chip}
                </button>
              ))}
            </div>
          ) : null}
          <div className="text-input-actions">
            <button
              type="submit"
              className="text-submit"
              disabled={!manualText.trim() || isProcessing}
              onClick={handleManualSubmit}
            >
              Generate from text
            </button>
            <span className="muted">Uses the same pipeline as voice.</span>
          </div>
        </form>

        <button
          className={`talk-button ${isListening ? "active" : ""}`}
          onPointerDown={startListening}
          onPointerUp={stopListening}
          onPointerLeave={stopListening}
          aria-pressed={isListening}
          disabled={
            sttProvider === "browser" ? !speechSupport : !recordingSupport
          }
        >
          {sttProvider === "browser"
            ? speechSupport
              ? isListening
                ? "Listening..."
                : "Push to Talk"
              : "Speech not supported"
            : recordingSupport
              ? isListening
                ? "Recording..."
                : "Push to Record"
              : "Recording not supported"}
        </button>

        <div className="status-card">
          <div className="status-label">Pipeline Status</div>
          <div className="status-value">{status}</div>
          <div className="status-steps">
            {[
              "queued",
              "extracting",
              "generating",
              "repairing",
              "slicing",
              "ready"
            ].map((step) => {
              const normalized =
                status === "gcode-ready" || status === "preview-ready"
                  ? "ready"
                  : status === "uploading-image" || status === "extracting-image" || status === "image-prompt-ready"
                    ? "extracting"
                    : status === "library-search" || status === "fetching-model"
                      ? "generating"
                      : status === "transcribing" || status === "listening" || status === "recording"
                        ? "queued"
                        : status;
              const order = ["queued", "extracting", "generating", "repairing", "slicing", "ready"];
              const currentIndex = order.indexOf(normalized);
              const stepIndex = order.indexOf(step);
              const isDone = currentIndex >= stepIndex && currentIndex !== -1;
              const isActive = currentIndex === stepIndex;
              return (
                <span
                  key={step}
                  className={`status-step ${isDone ? "done" : ""} ${isActive ? "active" : ""}`}
                >
                  {step}
                </span>
              );
            })}
          </div>
          {intent ? (
            <div className="intent">Prompt: {intent}</div>
          ) : (
            <div className="intent muted">Prompt will appear here.</div>
          )}
          {interim ? (
            <div className="intent muted">Hearing: {interim}</div>
          ) : null}
          {status === "error" || status === "timeout" ? (
            <div className="status-error">
              <div className="muted">{lastError || "Something went wrong."}</div>
              <div className="retry-actions">
                <button type="button" className="text-submit" onClick={retryPipeline}>
                  Retry pipeline
                </button>
                <button
                  type="button"
                  className="text-submit"
                  onClick={retrySlicing}
                  disabled={!lastRun?.glbUrl}
                >
                  Retry slicing
                </button>
              </div>
            </div>
          ) : null}
        </div>

        {provider === "library" ? (
          <div className="library-card">
          <div className="status-label">Library results</div>
          {libraryResults.length === 0 ? (
            <p className="muted">No matches yet. Speak or type a prompt to search.</p>
          ) : (
            <div className="library-list">
                {libraryResults.map((item) => (
                  <button
                    key={item.id}
                    className="library-item"
                    onClick={() => useLibraryItem(item)}
                  >
                    <div>
                      <strong>{item.title}</strong>
                      <span className="muted">{item.source}</span>
                    </div>
                    <span className="chip">Use model</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : null}

        <div className="transcript-card">
          <div className="status-label">Live Transcript</div>
          <div className="transcript-list">
            {transcripts.length === 0 ? (
              <div className="muted">Waiting for input...</div>
            ) : (
              transcripts.map((line, index) => (
                <p key={`${line}-${index}`}>{line}</p>
              ))
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
