"use client";

import { useEffect, useRef, useState } from "react";

import { resolveBackendUrl } from "../lib/backend";

type SpeechToTextButtonProps = {
  disabled?: boolean;
  onTranscript: (text: string) => void;
  compact?: boolean;
  language?: "pl" | "en" | "multi";
};

type VoiceState = "idle" | "recording" | "transcribing";

const MAX_RECORDING_MS = 90_000;

export default function SpeechToTextButton({
  disabled = false,
  onTranscript,
  compact = false,
  language = "pl",
}: SpeechToTextButtonProps) {
  const backendUrl = resolveBackendUrl();
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const stopTimerRef = useRef<number | null>(null);
  const [supported, setSupported] = useState(true);
  const [voiceState, setVoiceState] = useState<VoiceState>("idle");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setSupported(window.isSecureContext);
    return () => {
      if (stopTimerRef.current) window.clearTimeout(stopTimerRef.current);
      if (recorderRef.current && recorderRef.current.state !== "inactive") {
        recorderRef.current.onstop = null;
        recorderRef.current.stop();
      }
      streamRef.current?.getTracks().forEach((track) => track.stop());
    };
  }, []);

  const releaseMicrophone = () => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    recorderRef.current = null;
    if (stopTimerRef.current) window.clearTimeout(stopTimerRef.current);
    stopTimerRef.current = null;
  };

  const uploadRecording = async (blob: Blob) => {
    setVoiceState("transcribing");
    try {
      const form = new FormData();
      const extension = blob.type.includes("ogg") ? "ogg" : "webm";
      form.append("audio", blob, `pulsai-recording.${extension}`);
      form.append("language", language);
      const response = await fetch(`${backendUrl}/stt`, { method: "POST", body: form });
      const payload = (await response.json().catch(() => null)) as
        | { transcript?: string; detail?: string }
        | null;
      if (!response.ok) throw new Error(payload?.detail || "Nie udało się rozpoznać nagrania.");
      const transcript = payload?.transcript?.trim();
      if (!transcript) throw new Error("Nie usłyszałem wyraźnej komendy. Spróbuj ponownie.");
      onTranscript(transcript);
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : "Nie udało się rozpoznać nagrania.");
    } finally {
      releaseMicrophone();
      setVoiceState("idle");
    }
  };

  const stop = () => {
    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
  };

  const start = async () => {
    if (disabled || voiceState !== "idle") return;
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      const preferredMimeType = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus"].find(
        (candidate) => MediaRecorder.isTypeSupported(candidate),
      );
      const recorder = preferredMimeType
        ? new MediaRecorder(stream, { mimeType: preferredMimeType })
        : new MediaRecorder(stream);
      streamRef.current = stream;
      recorderRef.current = recorder;
      chunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      };
      recorder.onerror = () => {
        setError("Nagrywanie zostało przerwane. Spróbuj ponownie.");
        releaseMicrophone();
        setVoiceState("idle");
      };
      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
        chunksRef.current = [];
        if (blob.size === 0) {
          setError("Nagranie jest puste. Spróbuj ponownie.");
          releaseMicrophone();
          setVoiceState("idle");
          return;
        }
        void uploadRecording(blob);
      };
      recorder.start(250);
      setVoiceState("recording");
      stopTimerRef.current = window.setTimeout(stop, MAX_RECORDING_MS);
    } catch (microphoneError) {
      releaseMicrophone();
      setVoiceState("idle");
      setError(
        microphoneError instanceof DOMException && microphoneError.name === "NotAllowedError"
          ? "Zezwól Pulsai na dostęp do mikrofonu."
          : "Nie udało się uruchomić mikrofonu.",
      );
    }
  };

  const label =
    voiceState === "recording"
      ? "Zatrzymaj i przepisz"
      : voiceState === "transcribing"
        ? "Przepisuję nagranie"
        : "Powiedz po polsku";

  return (
    <div style={wrapperStyle}>
      <button
        type="button"
        onClick={voiceState === "recording" ? stop : start}
        disabled={disabled || !supported || voiceState === "transcribing"}
        aria-label={label}
        title={supported ? `${label} — model Nova-3, język polski` : "Nagrywanie audio jest niedostępne w tej przeglądarce"}
        style={buttonStyle(voiceState, compact)}
      >
        <MicrophoneIcon />
        {compact ? null : <span>{voiceState === "recording" ? "Zakończ" : voiceState === "transcribing" ? "Przepisuję…" : "Mów"}</span>}
      </button>
      {voiceState === "recording" ? <span style={statusStyle}>Słucham po polsku…</span> : null}
      {error ? <span style={errorStyle}>{error}</span> : null}
    </div>
  );
}

function MicrophoneIcon() {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect x="9" y="3" width="6" height="11" rx="3" stroke="currentColor" strokeWidth="1.8" />
      <path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3M8.5 21h7" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

const wrapperStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 7,
  minWidth: 0,
  flexWrap: "wrap",
};

const buttonStyle = (state: VoiceState, compact: boolean): React.CSSProperties => ({
  minWidth: compact ? 38 : 86,
  height: 38,
  border: `1px solid ${state === "recording" ? "rgba(248,113,113,0.72)" : "rgba(90,170,255,0.58)"}`,
  borderRadius: compact ? 10 : 999,
  background: state === "recording" ? "rgba(248,113,113,0.16)" : "rgba(25,118,210,0.16)",
  color: state === "recording" ? "#ff9d9d" : "#82bdff",
  padding: compact ? "0 10px" : "0 14px",
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  gap: 7,
  font: "inherit",
  fontSize: 12,
  fontWeight: 800,
  cursor: state === "transcribing" ? "wait" : "pointer",
  opacity: state === "transcribing" ? 0.72 : 1,
});

const statusStyle: React.CSSProperties = { color: "#9bc9ff", fontSize: 10, lineHeight: 1.2 };
const errorStyle: React.CSSProperties = { color: "#ff9d9d", fontSize: 10, lineHeight: 1.2, maxWidth: 220 };
