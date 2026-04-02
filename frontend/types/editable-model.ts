export type BodyKind =
  | "body"
  | "rim"
  | "hole"
  | "slot"
  | "pocket"
  | "boss"
  | "linear_pattern"
  | "circular_pattern"
  | "fillet"
  | "chamfer"
  | "thickness";

export type ConstraintNode = {
  kind: "concentric" | "aligned" | "symmetric" | "patterned" | "min_wall" | "inside_boundary";
  targets: string[];
  value?: number | null;
};

export type SelectionState = {
  feature_id: string;
  scope: "one" | "all_similar" | "body";
};

export type Manufacturability = {
  status: "safe" | "risk" | "invalid";
  messages: string[];
};

export type BodyNode = {
  id: string;
  kind: BodyKind;
  label: string;
  editable: boolean;
  confidence: number;
  params: Record<string, number | string | boolean>;
  children: BodyNode[];
  unsupported_reason?: string | null;
};

export type EditableModel = {
  id: string;
  source: "native" | "step_import" | "stl_reconstructed";
  revision_id: string;
  units: "mm";
  bodies: BodyNode[];
  constraints: ConstraintNode[];
  selection?: SelectionState | null;
  manufacturability: Manufacturability;
};

export type WorkspaceResponse = {
  workspace_id: string;
  editable_model: EditableModel;
  latest_preview?: {
    revision_id: string;
    glb_url: string;
    stl_url?: string | null;
    validation: Record<string, unknown>;
  } | null;
  latest_build?: {
    revision_id: string;
    glb_url: string;
    stl_url: string;
    gcode_url?: string | null;
    bundle_url?: string | null;
    validation: Record<string, unknown>;
  } | null;
};

export type WorkspacePresentationMode =
  | "native"
  | "step_reference"
  | "step_editable"
  | "stl_reconstruction"
  | "stl_reference"
  | "stl_locked";
