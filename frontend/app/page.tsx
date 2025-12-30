"use client";

import { useState } from "react";
import ModelViewer from "../components/ModelViewer";
import VoicePanel from "../components/VoicePanel";

export default function Home() {
  const [modelUrl, setModelUrl] = useState<string | null>(null);
  const [gcodeUrl, setGcodeUrl] = useState<string | null>(null);

  return (
    <main className="page">
      <header className="hero">
        <div>
          <p className="eyebrow">Voice → Model → Print</p>
          <h1>
            Turn spoken ideas into
            <span className="highlight"> printable objects</span>.
          </h1>
          <p className="hero-body">
            This prototype orchestrates real-time speech, LLM intent
            extraction, cloud 3D generation, mesh repair, and slicing — all
            without local GPU compute.
          </p>
        </div>
        <div className="hero-card">
          <div className="hero-stat">
            <span>Pipeline</span>
            <strong>Serverless</strong>
          </div>
          <div className="hero-stat">
            <span>3D Generation</span>
            <strong>Meshy (default)</strong>
          </div>
          <div className="hero-stat">
            <span>Output</span>
            <strong>GLB + G-code</strong>
          </div>
        </div>
      </header>

      <div className="grid">
        <VoicePanel onModelUrl={setModelUrl} onGcodeUrl={setGcodeUrl} />

        <section className="panel model-panel">
          <div className="panel-header">
            <p className="eyebrow">3D Preview</p>
            <h2>Inspect the generated model</h2>
            <p className="panel-subtitle">
              Rotate, zoom, and validate the geometry before downloading
              the print-ready G-code.
            </p>
          </div>

          <div className="model-shell">
            <ModelViewer src={modelUrl} label="Generated object" />
          </div>

          <div className="actions">
            <a
              className={`download-button ${gcodeUrl ? "" : "disabled"}`}
              href={gcodeUrl || "#"}
              download
              aria-disabled={!gcodeUrl}
            >
              Download G-code
            </a>
            <span className="hint">
              {gcodeUrl
                ? "Ready for your slicer or printer queue."
                : "G-code link appears after slicing."}
            </span>
          </div>
        </section>
      </div>
    </main>
  );
}
