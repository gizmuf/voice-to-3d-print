"use client";

import { useEffect, useRef, useState } from "react";
import { PipecatClient } from "@pipecat-ai/client";

const defaultPipecatUrl = "http://localhost:7860";

const defaultBackendUrl = "http://localhost:8000";

const resolveUrl = (base: string, value?: string | null) => {
  if (!value) return null;
  if (value.startsWith("http")) return value;
  return `${base.replace(/\/$/, "")}${value.startsWith("/") ? "" : "/"}${value}`;
};

type AppMessage = {
  type?: string;
  [key: string]: any;
};

type VoicePanelProps = {
  onModelUrl: (url: string | null) => void;
  onGcodeUrl: (url: string | null) => void;
};

export default function VoicePanel({ onModelUrl, onGcodeUrl }: VoicePanelProps) {
  const [isTalking, setIsTalking] = useState(false);
  const [status, setStatus] = useState("idle");
  const [intent, setIntent] = useState<string | null>(null);
  const [transcripts, setTranscripts] = useState<string[]>([]);
  const clientRef = useRef<PipecatClient | null>(null);

  const pipecatUrl =
    process.env.NEXT_PUBLIC_PIPECAT_URL || defaultPipecatUrl;
  const backendUrl =
    process.env.NEXT_PUBLIC_BACKEND_URL || defaultBackendUrl;

  const handleMessage = (message: AppMessage) => {
    const payload = message?.message ?? message;
    if (!payload?.type) return;

    if (payload.type === "transcript") {
      if (payload.is_final && payload.text) {
        setTranscripts((prev) => [...prev.slice(-5), payload.text]);
      }
    }

    if (payload.type === "intent") {
      setIntent(payload.prompt ?? null);
    }

    if (payload.type === "status") {
      setStatus(payload.stage ?? "working");
    }

    if (payload.type === "model") {
      const resolved = resolveUrl(backendUrl, payload.glb_url);
      onModelUrl(resolved ?? null);
      setStatus("model-ready");
    }

    if (payload.type === "gcode") {
      const resolved = resolveUrl(backendUrl, payload.gcode_url);
      onGcodeUrl(resolved ?? null);
      setStatus("gcode-ready");
    }

    if (payload.type === "error") {
      setStatus("error");
    }
  };

  const connect = async () => {
    if (clientRef.current) return;
    const client = new PipecatClient({
      url: pipecatUrl,
      transport: "webrtc"
    });
    client.on("app-message", handleMessage);
    client.on("message", handleMessage);
    await client.connect();
    clientRef.current = client;
  };

  const disconnect = () => {
    clientRef.current?.disconnect();
    clientRef.current = null;
  };

  useEffect(() => {
    connect();
    return () => disconnect();
  }, []);

  const startTalk = async () => {
    setIsTalking(true);
    await clientRef.current?.startAudio();
  };

  const stopTalk = async () => {
    setIsTalking(false);
    await clientRef.current?.stopAudio();
  };

  return (
    <section className="panel">
      <div className="panel-header">
        <p className="eyebrow">Live Voice Session</p>
        <h2>Speak your design intent</h2>
        <p className="panel-subtitle">
          Push to talk and describe the object you want to print. The
          system will extract a prompt, generate a 3D model, repair it, and
          slice it for G-code.
        </p>
      </div>

      <div className="panel-body">
        <button
          className={`talk-button ${isTalking ? "active" : ""}`}
          onPointerDown={startTalk}
          onPointerUp={stopTalk}
          onPointerLeave={stopTalk}
          aria-pressed={isTalking}
        >
          {isTalking ? "Listening..." : "Push to Talk"}
        </button>

        <div className="status-card">
          <div className="status-label">Pipeline Status</div>
          <div className="status-value">{status}</div>
          {intent ? (
            <div className="intent">Prompt: {intent}</div>
          ) : (
            <div className="intent muted">Prompt will appear here.</div>
          )}
        </div>

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
