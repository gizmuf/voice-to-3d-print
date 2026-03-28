"use client";

import { useState } from "react";
import Link from "next/link";
import ModelViewer from "../components/ModelViewer";
import VoicePanel from "../components/VoicePanel";

export default function Home() {
  const [modelUrl, setModelUrl] = useState<string | null>(null);
  const [stlUrl, setStlUrl] = useState<string | null>(null);
  const [gcodeUrl, setGcodeUrl] = useState<string | null>(null);
  const [bundleUrl, setBundleUrl] = useState<string | null>(null);

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
          <p className="eyebrow">Voice → Confirm → Preview → Export</p>
          <h1>
            Build practical prints from
            <span className="highlight"> spoken ideas</span>.
          </h1>
          <p className="hero-body">
            Useful Object mode now leads with voice, confirms dimensions and
            assumptions, drafts a preview, and exports a validated STL. Creative
            Object mode stays available as a beta path for mesh generation.
          </p>
        </div>
        <div className="hero-card">
          <div className="hero-stat">
            <span>Pipeline</span>
            <strong>Voice-first</strong>
          </div>
          <div className="hero-stat">
            <span>Primary mode</span>
            <strong>Useful Object</strong>
          </div>
          <div className="hero-stat">
            <span>Output</span>
            <strong>Validated STL</strong>
          </div>
        </div>
      </header>

      <div className="grid">
        <VoicePanel
          onModelUrl={setModelUrl}
          onStlUrl={setStlUrl}
          onGcodeUrl={setGcodeUrl}
          onBundleUrl={setBundleUrl}
        />

        <section className="panel model-panel">
          <div className="panel-header">
            <p className="eyebrow">3D Preview</p>
            <h2>Inspect the current revision</h2>
            <p className="panel-subtitle">
              Rotate, zoom, and validate the geometry before exporting the
              STL bundle.
            </p>
          </div>

          <div className="model-shell">
            <ModelViewer src={modelUrl} label="Generated object" />
          </div>

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
    </main>
  );
}
