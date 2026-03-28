"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import ModelViewer from "../../components/ModelViewer";
import { resolveBackendUrl, resolveUrl } from "../../lib/backend";

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
  mode?: string;
  template_id?: string;
  input?: {
    prompt_final?: string;
    prompt_raw?: string;
    transcript?: string;
    type?: string;
    image_name?: string;
  };
  structured_spec?: {
    object_label?: string;
  };
  artifacts?: {
    glb_url?: string;
    stl_url?: string;
    gcode_url?: string;
  };
  preview_artifacts?: {
    glb_url?: string;
  };
  validation?: {
    validation_status?: string;
    warnings?: string[];
    estimated_print_risk?: string;
    dimensions_mm?: number[];
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
  const backendUrl = resolveBackendUrl();
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [selectedProject, setSelectedProject] = useState<ProjectSummary | null>(null);
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [modelUrl, setModelUrl] = useState<string | null>(null);
  const [stlUrl, setStlUrl] = useState<string | null>(null);
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
      setStlUrl(null);
      return;
    }
    setModelUrl(
      resolveUrl(
        backendUrl,
        selectedJob.artifacts?.glb_url || selectedJob.preview_artifacts?.glb_url
      )
    );
    setStlUrl(resolveUrl(backendUrl, selectedJob.artifacts?.stl_url));
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
            <span className="highlight"> printable revisions</span>.
          </h1>
          <p className="hero-body">
            Browse drafts, confirmed specs, printability reports, and final STL
            exports across your projects.
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
              Each project tracks routed ideas, previews, build revisions, and
              validation outcomes.
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
                          <strong>
                            {job.structured_spec?.object_label ||
                              job.input?.prompt_final ||
                              job.input?.prompt_raw ||
                              job.input?.transcript ||
                              "Untitled prompt"}
                          </strong>
                          {isCurrent ? <span className="chip">Current</span> : null}
                        </div>
                        <span className="muted">
                          {(job.mode || "mode")} · {job.status || "unknown"} ·{" "}
                          {(job.template_id || job.provider || "route")} ·{" "}
                          {formatDate(job.created_at)}
                        </span>
                        {job.validation?.validation_status ? (
                          <span className="muted">
                            Validation {job.validation.validation_status} · risk{" "}
                            {job.validation.estimated_print_risk || "unknown"}
                          </span>
                        ) : null}
                      </div>
                      <div className="job-actions">
                        <button
                          className="text-submit"
                          onClick={() => setSelectedJobId(jobId)}
                          disabled={!job.artifacts?.glb_url && !job.preview_artifacts?.glb_url}
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
              Load a past draft or build to inspect it before continuing edits.
            </p>
          </div>

          <div className="model-shell">
            <ModelViewer src={modelUrl} label="Stored 3D model" />
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
            <span className="hint">
              {stlUrl
                ? "Validated build artifact ready to export."
                : "Select a build revision that has an STL."}
            </span>
          </div>

          <div className="project-summary">
            <div className="status-label">Selected revision</div>
            <div className="status-value">
              {selectedJob?.structured_spec?.object_label ||
                selectedJob?.input?.prompt_final ||
                selectedJob?.input?.prompt_raw ||
                selectedJob?.input?.transcript ||
                "—"}
            </div>
            <div className="intent muted">
              {selectedJob?.job_id || selectedJob?.id || "No revision selected."}
            </div>
          </div>
          {selectedJob?.validation ? (
            <div className="project-summary">
              <div className="status-label">Printability</div>
              <div className="status-value">
                {selectedJob.validation.validation_status || "unknown"}
              </div>
              <div className="intent muted">
                {selectedJob.validation.dimensions_mm?.length
                  ? `Size ${selectedJob.validation.dimensions_mm.join(" × ")} mm`
                  : "No dimension summary available."}
              </div>
              {selectedJob.validation.warnings?.length ? (
                <div className="warning-list">
                  {selectedJob.validation.warnings.map((warning) => (
                    <span key={warning} className="warning-chip">
                      {warning}
                    </span>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
        </section>
      </div>
    </main>
  );
}
