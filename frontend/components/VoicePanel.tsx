"use client";

import type { ChangeEvent, FormEvent, MouseEvent } from "react";
import { useEffect, useRef, useState } from "react";

const defaultBackendUrl = "http://localhost:8000";

const resolveUrl = (base: string, value?: string | null) => {
  if (!value) return null;
  if (value.startsWith("http")) return value;
  return `${base.replace(/\/$/, "")}${value.startsWith("/") ? "" : "/"}${value}`;
};

type VoicePanelProps = {
  onModelUrl: (url: string | null) => void;
  onGcodeUrl: (url: string | null) => void;
};

type LibraryItem = {
  id: string;
  title: string;
  tags?: string[];
  glb_url?: string;
  source?: string;
  license?: string;
};

export default function VoicePanel({ onModelUrl, onGcodeUrl }: VoicePanelProps) {
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
  const [speechSupport, setSpeechSupport] = useState(false);
  const [recordingSupport, setRecordingSupport] = useState(false);
  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || defaultBackendUrl;

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
    jobIdOverride?: string
  ) => {
    if (isProcessing) return;
    setIsProcessing(true);
    const jobId = jobIdOverride ?? createJobId();
    setStatus("extracting");
    setIntent(null);
    setLibraryResults([]);

    try {
      if (provider === "llama-mesh") {
        setStatus("not-configured");
        setIntent("Llama-Mesh local setup not installed.");
        return;
      }
      const shouldExtract = provider !== "parametric" && source !== "image";
      const prompt = shouldExtract
        ? await fetchIntent(text, jobId, source as "voice" | "text")
        : text;
      if (!prompt) throw new Error("No prompt extracted");

      setIntent(prompt);

      if (provider === "library") {
        setStatus("library-search");
        const results = await searchLibrary(prompt, librarySource);
        setLibraryResults(results);
        setIsProcessing(false);
        return;
      }

      setStatus("generating");
      const generation = await generateModel(prompt, provider, jobId, source, text);

      setStatus("slicing");
      const processed = await processModel(generation.glb_url, jobId, {
        provider,
        input_type: source,
        prompt
      });

      onModelUrl(resolveUrl(backendUrl, processed.glb_url));
      onGcodeUrl(resolveUrl(backendUrl, processed.gcode_url));
      setStatus(processed.gcode_url ? "gcode-ready" : "preview-ready");
    } catch (error) {
      console.error(error);
      setStatus("error");
    } finally {
      setIsProcessing(false);
    }
  };

  const fetchIntent = async (
    transcript: string,
    jobId: string,
    inputType: "voice" | "text"
  ): Promise<string | null> => {
    const response = await fetch(`${backendUrl}/intent`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ transcript, job_id: jobId, input_type: inputType })
    });
    if (!response.ok) throw new Error("Intent extraction failed");
    const data = await response.json();
    return data.prompt ?? null;
  };

  const generateModel = async (
    prompt: string,
    providerName: string,
    jobId: string,
    inputType: "voice" | "text" | "image",
    promptRaw: string
  ) => {
    const response = await fetch(`${backendUrl}/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt,
        provider: providerName,
        job_id: jobId,
        input_type: inputType,
        prompt_raw: promptRaw
      })
    });
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
    }
  ) => {
    const response = await fetch(`${backendUrl}/process-model`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        glb_url: glbUrl,
        job_id: jobId,
        ...metadata
      })
    });
    if (!response.ok) throw new Error("Processing failed");
    return response.json();
  };

  const generateFromImage = async () => {
    if (!imageFile || isProcessing) return;
    setIsProcessing(true);
    const jobId = createJobId();
    setStatus("uploading-image");
    setIntent(`Image to model (${provider})`);
    setLibraryResults([]);
    try {
      const formData = new FormData();
      formData.append("image", imageFile);
      formData.append("job_id", jobId);
      formData.append("input_type", "image");
      const response = await fetch(
        `${backendUrl}/generate-image?provider=${encodeURIComponent(provider)}`,
        {
        method: "POST",
        body: formData
        }
      );
      if (!response.ok) throw new Error("Image generation failed");
      const generation = await response.json();
      setStatus("slicing");
      const processed = await processModel(generation.glb_url, jobId, {
        provider,
        input_type: "image"
      });
      onModelUrl(resolveUrl(backendUrl, processed.glb_url));
      onGcodeUrl(resolveUrl(backendUrl, processed.gcode_url));
      setStatus(processed.gcode_url ? "gcode-ready" : "preview-ready");
    } catch (error) {
      console.error(error);
      setStatus("error");
    } finally {
      setIsProcessing(false);
    }
  };

  const generatePromptFromImage = async () => {
    if (!imageFile || isProcessing) return;
    setIsProcessing(true);
    const jobId = createJobId();
    setPendingJobId(jobId);
    setPendingSource("image");
    setStatus("extracting-image");
    setIntent(null);
    try {
      const formData = new FormData();
      formData.append("image", imageFile);
      formData.append("job_id", jobId);
      formData.append("input_type", "image");
      const response = await fetch(`${backendUrl}/image-intent`, {
        method: "POST",
        body: formData
      });
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
      setStatus("error");
    } finally {
      setIsProcessing(false);
    }
  };

  const searchLibrary = async (query: string, source: string) => {
    const response = await fetch(
      `${backendUrl}/library/search?query=${encodeURIComponent(query)}&provider=${source}`
    );
    if (!response.ok) throw new Error("Library search failed");
    const data = await response.json();
    return (data.items || []) as LibraryItem[];
  };

  const resolveLibraryItem = async (item: LibraryItem): Promise<string | null> => {
    if (item.glb_url) return item.glb_url;
    const response = await fetch(
      `${backendUrl}/library/resolve?uid=${encodeURIComponent(item.id)}&provider=${librarySource}`
    );
    if (!response.ok) throw new Error("Library item download failed");
    const data = await response.json();
    return data.glb_url ?? null;
  };

  const useLibraryItem = async (item: LibraryItem) => {
    try {
      const jobId = createJobId();
      setStatus("fetching-model");
      const resolvedUrl = await resolveLibraryItem(item);
      if (!resolvedUrl) {
        throw new Error("No downloadable GLB available");
      }
      onModelUrl(resolvedUrl);
      onGcodeUrl(null);
      setStatus("preview-ready");
      const processed = await processModel(resolvedUrl, jobId, {
        provider: "library",
        input_type: "library",
        prompt: intent || undefined,
        library_id: item.id,
        library_source: librarySource,
        library_title: item.title
      });
      onModelUrl(resolveUrl(backendUrl, processed.glb_url) || resolvedUrl);
      onGcodeUrl(resolveUrl(backendUrl, processed.gcode_url));
      setStatus(processed.gcode_url ? "gcode-ready" : "preview-ready");
    } catch (error) {
      console.error(error);
      setStatus("preview-ready");
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
      const response = await fetch(`${backendUrl}/stt`, {
        method: "POST",
        body: formData
      });
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
            <option value="meshy">Meshy (paid)</option>
            <option value="tripo">Tripo (paid)</option>
            <option value="library">Model library</option>
            <option value="llama-mesh">Llama-Mesh (local, not installed)</option>
          </select>
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
              <option value="sketchfab">Sketchfab (token)</option>
            </select>
          </div>
        ) : null}

        {provider === "tripo" || provider === "meshy" ? (
          <div className="field-row">
            <label htmlFor="image-upload">
              Image to model ({provider === "meshy" ? "Meshy" : "Tripo"})
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
          {intent ? (
            <div className="intent">Prompt: {intent}</div>
          ) : (
            <div className="intent muted">Prompt will appear here.</div>
          )}
          {interim ? (
            <div className="intent muted">Hearing: {interim}</div>
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
