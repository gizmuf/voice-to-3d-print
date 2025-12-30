"use client";

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
  glb_url: string;
  source?: string;
  license?: string;
};

export default function VoicePanel({ onModelUrl, onGcodeUrl }: VoicePanelProps) {
  const [isListening, setIsListening] = useState(false);
  const [status, setStatus] = useState("idle");
  const [intent, setIntent] = useState<string | null>(null);
  const [transcripts, setTranscripts] = useState<string[]>([]);
  const [interim, setInterim] = useState<string | null>(null);
  const [provider, setProvider] = useState("meshy");
  const [libraryResults, setLibraryResults] = useState<LibraryItem[]>([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const recognitionRef = useRef<SpeechRecognition | null>(null);

  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || defaultBackendUrl;

  const supportsSpeech = typeof window !== "undefined" &&
    ((window as Window).SpeechRecognition || (window as Window).webkitSpeechRecognition);

  useEffect(() => {
    if (!supportsSpeech) return;

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
        handleFinalTranscript(finalTranscript.trim());
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
  }, [supportsSpeech]);

  const handleFinalTranscript = async (text: string) => {
    setTranscripts((prev) => [...prev.slice(-5), text]);
    await runPipeline(text);
  };

  const runPipeline = async (text: string) => {
    if (isProcessing) return;
    setIsProcessing(true);
    setStatus("extracting");
    setIntent(null);
    setLibraryResults([]);

    try {
      const prompt = await fetchIntent(text);
      if (!prompt) throw new Error("No prompt extracted");

      setIntent(prompt);

      if (provider === "library") {
        setStatus("library-search");
        const results = await searchLibrary(prompt);
        setLibraryResults(results);
        setIsProcessing(false);
        return;
      }

      setStatus("generating");
      const generation = await generateModel(prompt, provider);

      setStatus("slicing");
      const processed = await processModel(generation.glb_url);

      onModelUrl(resolveUrl(backendUrl, processed.glb_url));
      onGcodeUrl(resolveUrl(backendUrl, processed.gcode_url));
      setStatus("gcode-ready");
    } catch (error) {
      console.error(error);
      setStatus("error");
    } finally {
      setIsProcessing(false);
    }
  };

  const fetchIntent = async (transcript: string): Promise<string | null> => {
    const response = await fetch(`${backendUrl}/intent`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ transcript })
    });
    if (!response.ok) throw new Error("Intent extraction failed");
    const data = await response.json();
    return data.prompt ?? null;
  };

  const generateModel = async (prompt: string, providerName: string) => {
    const response = await fetch(`${backendUrl}/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt, provider: providerName })
    });
    if (!response.ok) throw new Error("Generation failed");
    return response.json();
  };

  const processModel = async (glbUrl: string) => {
    const response = await fetch(`${backendUrl}/process-model`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ glb_url: glbUrl })
    });
    if (!response.ok) throw new Error("Processing failed");
    return response.json();
  };

  const searchLibrary = async (query: string) => {
    const response = await fetch(
      `${backendUrl}/library/search?query=${encodeURIComponent(query)}`
    );
    if (!response.ok) throw new Error("Library search failed");
    const data = await response.json();
    return (data.items || []) as LibraryItem[];
  };

  const useLibraryItem = async (item: LibraryItem) => {
    try {
      setStatus("slicing");
      const processed = await processModel(item.glb_url);
      onModelUrl(resolveUrl(backendUrl, processed.glb_url));
      onGcodeUrl(resolveUrl(backendUrl, processed.gcode_url));
      setStatus("gcode-ready");
    } catch (error) {
      console.error(error);
      setStatus("error");
    }
  };

  const startListening = () => {
    if (!recognitionRef.current || isProcessing) return;
    setStatus("listening");
    setIsListening(true);
    recognitionRef.current.start();
  };

  const stopListening = () => {
    recognitionRef.current?.stop();
    setIsListening(false);
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
          <label htmlFor="provider">3D provider</label>
          <select
            id="provider"
            value={provider}
            onChange={(event) => setProvider(event.target.value)}
          >
            <option value="meshy">Meshy (paid)</option>
            <option value="tripo">Tripo (paid)</option>
            <option value="library">Model library (free)</option>
          </select>
        </div>

        <button
          className={`talk-button ${isListening ? "active" : ""}`}
          onPointerDown={startListening}
          onPointerUp={stopListening}
          onPointerLeave={stopListening}
          aria-pressed={isListening}
          disabled={!supportsSpeech}
        >
          {supportsSpeech
            ? isListening
              ? "Listening..."
              : "Push to Talk"
            : "Speech not supported"}
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
              <p className="muted">No matches yet. Speak a prompt to search.</p>
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
              <div className="muted">Waiting for speech...</div>
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
