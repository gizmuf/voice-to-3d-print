"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import ModelViewer from "../../components/ModelViewer";

const defaultBackendUrl = "http://localhost:8000";

const resolveUrl = (base: string, value?: string | null) => {
  if (!value) return null;
  if (value.startsWith("http")) return value;
  return `${base.replace(/\/$/, "")}${value.startsWith("/") ? "" : "/"}${value}`;
};

type ProjectSummary = {
  id?: string;
  project_id: string;
  name?: string;
  current_job_id?: string;
  updated_at?: unknown;
};

type JobSummary = {
  id?: string;
  job_id?: string;
  status?: string;
  provider?: string;
  input?: {
    prompt_final?: string;
    prompt_raw?: string;
    transcript?: string;
    type?: string;
    image_name?: string;
  };
  artifacts?: {
    glb_url?: string;
    stl_url?: string;
    gcode_url?: string;
  };
  created_at?: unknown;
  updated_at?: unknown;
};

const normalizeJobId = (job: JobSummary) => job.job_id || job.id || "";

const formatDate = (value?: unknown) => {
  if (!value) return "—";
  if (typeof value === "string") return new Date(value).toLocaleString();
  if (typeof value === "number") return new Date(value * 1000).toLocaleString();
  if (typeof value === "object") {
    const seconds = (value as { seconds?: number; _seconds?: number }).seconds ??
      (value as { _seconds?: number })._seconds;
    if (seconds) return new Date(seconds * 1000).toLocaleString();
  }
  return "—";
};

export default function ProjectsPage() {
  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || defaultBackendUrl;
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [selectedProject, setSelectedProject] = useState<ProjectSummary | null>(null);
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [modelUrl, setModelUrl] = useState<string | null>(null);
  const [gcodeUrl, setGcodeUrl] = useState<string | null>(null);
  const [isLoadingProjects, setIsLoadingProjects] = useState(false);
  const [isLoadingJobs, setIsLoadingJobs] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadProjects = async (keepSelection = true) => {
    setIsLoadingProjects(true);
    setError(null);
    try {
      const response = await fetch(`${backendUrl}/projects`);
      if (!response.ok) throw new Error("Failed to load projects");
      const data = await response.json();
      const items = (data.items || []) as ProjectSummary[];
      setProjects(items);
      const stillExists = keepSelection && selectedProjectId
        ? items.some((item) => item.project_id === selectedProjectId)
        : false;
      if (!stillExists) {
        setSelectedProjectId(items[0]?.project_id ?? null);
      }
    } catch (err) {
      console.error(err);
      setError("Could not load projects.");
    } finally {
      setIsLoadingProjects(false);
    }
  };

  const loadProject = async (projectId: string) => {
    setIsLoadingJobs(true);
    setError(null);
    try {
      const response = await fetch(`${backendUrl}/projects/${projectId}`);
      if (!response.ok) throw new Error("Failed to load project");
      const data = await response.json();
      const project = data.project as ProjectSummary;
      const items = (data.jobs || []) as JobSummary[];
      setSelectedProject(project);
      setJobs(items);
      const nextJobId = project?.current_job_id || normalizeJobId(items[0] || {});
      setSelectedJobId(nextJobId || null);
    } catch (err) {
      console.error(err);
      setError("Could not load project details.");
    } finally {
      setIsLoadingJobs(false);
    }
  };

  const selectedJob = useMemo(() => {
    if (!selectedJobId) return null;
    return jobs.find((job) => normalizeJobId(job) === selectedJobId) || null;
  }, [jobs, selectedJobId]);

  useEffect(() => {
    void loadProjects(true);
  }, [backendUrl]);

  useEffect(() => {
    if (!selectedProjectId) {
      setSelectedProject(null);
      setJobs([]);
      setSelectedJobId(null);
      return;
    }
    void loadProject(selectedProjectId);
  }, [backendUrl, selectedProjectId]);

  useEffect(() => {
    if (!selectedJob) {
      setModelUrl(null);
      setGcodeUrl(null);
      return;
    }
    setModelUrl(resolveUrl(backendUrl, selectedJob.artifacts?.glb_url));
    setGcodeUrl(resolveUrl(backendUrl, selectedJob.artifacts?.gcode_url));
  }, [backendUrl, selectedJob]);

  const setProjectCurrent = async (jobId: string) => {
    if (!selectedProjectId) return;
    try {
      const response = await fetch(`${backendUrl}/projects/${selectedProjectId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current_job_id: jobId })
      });
      if (!response.ok) throw new Error("Failed to update project");
      const data = await response.json();
      const project = data.project as ProjectSummary;
      setSelectedProject(project);
      setProjects((prev) =>
        prev.map((item) =>
          item.project_id === project.project_id ? { ...item, ...project } : item
        )
      );
    } catch (err) {
      console.error(err);
      setError("Could not set current revision.");
    }
  };

  return (
    <main className="page projects-page">
      <nav className="topbar">
        <div className="brand">3dprint</div>
        <div className="topbar-links">
          <Link className="topbar-link" href="/">Generator</Link>
        </div>
      </nav>

      <header className="hero hero-compact">
        <div>
          <p className="eyebrow">Project Library</p>
          <h1>
            Review previous
            <span className="highlight"> 3D experiments</span>.
          </h1>
          <p className="hero-body">
            Browse your project history, reload a past model, and restore a
            revision to continue iterating.
          </p>
        </div>
        <div className="hero-card">
          <div className="hero-stat">
            <span>Projects</span>
            <strong>{projects.length}</strong>
          </div>
          <div className="hero-stat">
            <span>Revisions</span>
            <strong>{jobs.length}</strong>
          </div>
        </div>
      </header>

      <div className="grid projects-grid">
        <section className="panel project-panel">
          <div className="panel-header">
            <p className="eyebrow">Projects</p>
            <h2>Pick a project</h2>
            <p className="panel-subtitle">
              Each project tracks a chain of prompts, model generations, and
              printable outputs.
            </p>
          </div>

          <div className="project-actions">
            <button
              className="text-submit"
              onClick={() => setSelectedProjectId(null)}
              disabled={isLoadingProjects}
            >
              Clear selection
            </button>
            <button
              className="text-submit"
              onClick={() => loadProjects(true)}
              disabled={isLoadingProjects}
            >
              Refresh list
            </button>
          </div>

          {error ? <div className="muted">{error}</div> : null}

          <div className="project-list">
            {isLoadingProjects ? (
              <div className="muted">Loading projects...</div>
            ) : projects.length === 0 ? (
              <div className="muted">No projects yet. Generate a model first.</div>
            ) : (
              projects.map((project) => (
                <button
                  key={project.project_id}
                  className={`project-item ${
                    project.project_id === selectedProjectId ? "active" : ""
                  }`}
                  onClick={() => setSelectedProjectId(project.project_id)}
                >
                  <div>
                    <strong>{project.name || "Untitled project"}</strong>
                    <span className="muted">
                      Updated {formatDate(project.updated_at)}
                    </span>
                  </div>
                  {project.current_job_id ? (
                    <span className="chip">Current set</span>
                  ) : null}
                </button>
              ))
            )}
          </div>

          <div className="project-summary">
            <div className="status-label">Selected project</div>
            <div className="status-value">
              {selectedProject?.name || "—"}
            </div>
            <div className="intent muted">
              {selectedProjectId ? selectedProjectId : "No project selected."}
            </div>
          </div>

          <div className="project-summary">
            <div className="status-label">Revision history</div>
            {isLoadingJobs ? (
              <div className="muted">Loading revisions...</div>
            ) : jobs.length === 0 ? (
              <div className="muted">No revisions for this project yet.</div>
            ) : (
              <div className="job-list">
                {jobs.map((job) => {
                  const jobId = normalizeJobId(job);
                  const isCurrent = selectedProject?.current_job_id === jobId;
                  return (
                    <div key={jobId} className="job-item">
                      <div className="job-main">
                        <div className="job-title">
                          <strong>{job.input?.prompt_final || job.input?.prompt_raw || job.input?.transcript || "Untitled prompt"}</strong>
                          {isCurrent ? <span className="chip">Current</span> : null}
                        </div>
                        <span className="muted">
                          {job.status || "unknown"} · {job.provider || "provider"} ·{" "}
                          {formatDate(job.created_at)}
                        </span>
                      </div>
                      <div className="job-actions">
                        <button
                          className="text-submit"
                          onClick={() => setSelectedJobId(jobId)}
                          disabled={!job.artifacts?.glb_url}
                        >
                          Load model
                        </button>
                        <button
                          className="text-submit"
                          onClick={() => setProjectCurrent(jobId)}
                          disabled={!jobId}
                        >
                          Set as current
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </section>

        <section className="panel model-panel">
          <div className="panel-header">
            <p className="eyebrow">3D Preview</p>
            <h2>Inspect the revision</h2>
            <p className="panel-subtitle">
              Load a past model to verify it before continuing edits.
            </p>
          </div>

          <div className="model-shell">
            <ModelViewer src={modelUrl} label="Stored 3D model" />
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
                : "Select a revision that has G-code."}
            </span>
          </div>

          <div className="project-summary">
            <div className="status-label">Selected revision</div>
            <div className="status-value">
              {selectedJob?.input?.prompt_final ||
                selectedJob?.input?.prompt_raw ||
                selectedJob?.input?.transcript ||
                "—"}
            </div>
            <div className="intent muted">
              {selectedJob?.job_id || selectedJob?.id || "No revision selected."}
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
