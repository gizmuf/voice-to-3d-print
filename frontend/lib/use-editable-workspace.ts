"use client";

import { useCallback, useState } from "react";

import { resolveBackendUrl, resolveUrl } from "./backend";
import type { BodyNode, EditableModel, SelectionState, WorkspaceResponse } from "../types/editable-model";

type CreatePayload = {
  prompt?: string;
  structured_spec?: Record<string, unknown>;
  editable_model?: EditableModel;
  project_id?: string | null;
  source?: "native" | "step_import" | "stl_reconstructed";
};

type MutationPayload = {
  body_updates?: Array<{ body_id: string; params: Record<string, number | string | boolean> }>;
  selection?: SelectionState | null;
};

type PreviewResponse = {
  workspace_id: string;
  revision_id: string;
  glb_url: string;
  validation: Record<string, unknown>;
};

type BuildResponse = {
  workspace_id: string;
  revision_id: string;
  glb_url: string;
  stl_url: string;
  gcode_url?: string | null;
  bundle_url?: string | null;
  validation: Record<string, unknown>;
};

export function useEditableWorkspace() {
  const backendUrl = resolveBackendUrl();
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [editableModel, setEditableModel] = useState<EditableModel | null>(null);
  const [latestPreview, setLatestPreview] = useState<WorkspaceResponse["latest_preview"]>(null);
  const [latestBuild, setLatestBuild] = useState<WorkspaceResponse["latest_build"]>(null);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const hydrate = useCallback((payload: WorkspaceResponse) => {
    setWorkspaceId(payload.workspace_id);
    setEditableModel(payload.editable_model);
    setLatestPreview(payload.latest_preview ?? null);
    setLatestBuild(payload.latest_build ?? null);
  }, []);

  const createWorkspace = useCallback(async (payload: CreatePayload) => {
    setIsBusy(true);
    setError(null);
    try {
      const response = await fetch(`${backendUrl}/workspace/create`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) throw new Error("Could not create the design workspace.");
      const data = (await response.json()) as WorkspaceResponse;
      hydrate(data);
      return data;
    } finally {
      setIsBusy(false);
    }
  }, [backendUrl, hydrate]);

  const refreshWorkspace = useCallback(async (id = workspaceId) => {
    if (!id) return null;
    const response = await fetch(`${backendUrl}/workspace/${id}`);
    if (!response.ok) throw new Error("Could not refresh the workspace.");
    const data = (await response.json()) as WorkspaceResponse;
    hydrate(data);
    return data;
  }, [backendUrl, hydrate, workspaceId]);

  const mutate = useCallback(async (payload: MutationPayload) => {
    if (!workspaceId || !editableModel) return null;
    setError(null);
    const requestBody = {
      expected_revision_id: editableModel.revision_id,
      body_updates: payload.body_updates ?? [],
      selection: payload.selection ?? editableModel.selection ?? null,
    };
    const response = await fetch(`${backendUrl}/workspace/${workspaceId}/mutate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestBody),
    });
    if (response.status === 409) {
      const stale = await response.json();
      if (stale?.detail?.editable_model) {
        setEditableModel(stale.detail.editable_model as EditableModel);
      }
      throw new Error("Workspace changed while editing. Try again.");
    }
    if (!response.ok) throw new Error("Could not apply the edit.");
    const data = (await response.json()) as WorkspaceResponse;
    hydrate(data);
    return data;
  }, [backendUrl, editableModel, hydrate, workspaceId]);

  const updateBody = useCallback(async (bodyId: string, params: BodyNode["params"]) => {
    return mutate({
      body_updates: [{ body_id: bodyId, params }],
    });
  }, [mutate]);

  const selectFeature = useCallback(async (selection: SelectionState | null) => {
    return mutate({ selection });
  }, [mutate]);

  const preview = useCallback(async () => {
    if (!workspaceId || !editableModel) return null;
    setIsBusy(true);
    setError(null);
    try {
      const response = await fetch(`${backendUrl}/workspace/${workspaceId}/preview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_revision_id: editableModel.revision_id }),
      });
      if (response.status === 409) {
        await refreshWorkspace(workspaceId);
        throw new Error("Workspace changed before preview could run.");
      }
      if (!response.ok) throw new Error("Could not preview the current revision.");
      const data = (await response.json()) as PreviewResponse;
      setLatestPreview({
        revision_id: data.revision_id,
        glb_url: data.glb_url,
        validation: data.validation,
      });
      return {
        ...data,
        glb_url: resolveUrl(backendUrl, data.glb_url),
      };
    } finally {
      setIsBusy(false);
    }
  }, [backendUrl, editableModel, refreshWorkspace, workspaceId]);

  const build = useCallback(async () => {
    if (!workspaceId || !editableModel) return null;
    setIsBusy(true);
    setError(null);
    try {
      const response = await fetch(`${backendUrl}/workspace/${workspaceId}/build`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_revision_id: editableModel.revision_id }),
      });
      if (response.status === 409) {
        await refreshWorkspace(workspaceId);
        throw new Error("Workspace changed before export could run.");
      }
      if (!response.ok) throw new Error("Could not export the current revision.");
      const data = (await response.json()) as BuildResponse;
      setLatestBuild({
        revision_id: data.revision_id,
        glb_url: data.glb_url,
        stl_url: data.stl_url,
        gcode_url: data.gcode_url,
        bundle_url: data.bundle_url,
        validation: data.validation,
      });
      return {
        ...data,
        glb_url: resolveUrl(backendUrl, data.glb_url),
        stl_url: resolveUrl(backendUrl, data.stl_url),
        gcode_url: resolveUrl(backendUrl, data.gcode_url),
        bundle_url: resolveUrl(backendUrl, data.bundle_url),
      };
    } finally {
      setIsBusy(false);
    }
  }, [backendUrl, editableModel, refreshWorkspace, workspaceId]);

  return {
    workspaceId,
    editableModel,
    latestPreview,
    latestBuild,
    isBusy,
    error,
    setError,
    createWorkspace,
    refreshWorkspace,
    mutate,
    updateBody,
    selectFeature,
    preview,
    build,
  };
}

