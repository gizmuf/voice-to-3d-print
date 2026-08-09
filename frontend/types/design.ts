export type DesignParameter = {
  name: string;
  value: number | string | boolean;
  type: string;
  min?: number | null;
  max?: number | null;
  step?: number | null;
  choices?: string[] | null;
  doc?: string | null;
  locked?: boolean;
};

export type NamedFeature = {
  id: string;
  name: string;
  kind: string;
  source: string;
  parameters_used?: string[];
  parent_feature_ids?: string[];
  created_by?: "user_prompt" | "slider" | "macro" | "import" | "system";
  source_prompt?: string | null;
  revision_id?: string;
  user_words?: string[];
};

export type ManufacturabilityIssue = {
  severity: "info" | "warn" | "error";
  code: string;
  message: string;
  location?: [number, number, number] | null;
  suggestion?: string | null;
  process?: "fdm" | "cnc" | "any";
};

export type OrientationSuggestion = {
  label: string;
  euler_deg: [number, number, number];
  overhang_fraction: number;
};

export type Manufacturability = {
  process: "fdm" | "cnc";
  status: "safe" | "warn" | "unprintable";
  issues: ManufacturabilityIssue[];
  estimated_volume_mm3?: number | null;
  bounding_box_mm?: [number, number, number] | null;
  current_overhang_fraction?: number | null;
  suggested_orientation?: OrientationSuggestion | null;
};

export type PrintEstimate = {
  filament_g?: number | null;
  filament_cm3?: number | null;
  print_minutes?: number | null;
  cost_usd?: number | null;
  cost_usd_per_g?: number | null;
};

export type MotionReport = {
  supported: boolean;
  status: "safe" | "blocked" | "unsupported";
  summary: string;
  rotating_node?: string;
  axis_cad?: [number, number, number];
  axis_viewer?: [number, number, number];
  axle_clearance_mm?: number;
  minimum_static_gap_mm?: number;
  caveat?: string;
  checks?: Array<{ code: string; passed: boolean; message: string }>;
};

export type SpecCompliance = {
  status: "passed" | "needs_repair" | "needs_attention" | "not_applicable";
  summary: string;
  checks: Array<{
    kind: "parameter" | "geometry";
    name: string;
    expected: number | string | boolean;
    actual: number | string | boolean | null;
    tolerance: number;
    passed: boolean;
  }>;
};

export type DesignBuild = {
  revision_id: string;
  mesh_hash: string;
  bounding_box_mm?: [number, number, number] | null;
  artifacts: Record<string, { kind: string; url: string }>;
  manufacturability: Manufacturability | null;
  print_estimate?: PrintEstimate | null;
  duration_ms?: number;
};

export type DesignTemplate = { template_id: string; name: string };

export type DesignSummary = {
  design_id: string;
  revision_id: string;
  name: string;
  process: string;
  parameter_count: number;
  feature_count: number;
};

export type Design = {
  design_id: string;
  revision_id: string;
  name: string;
  process: string;
  script: string;
  parameters: DesignParameter[];
  features: NamedFeature[];
  latest_build: DesignBuild | null;
  printer_profile_id?: string | null;
  spec_compliance?: SpecCompliance | null;
  motion_report?: MotionReport | null;
};

export type PrinterProfile = {
  id: string;
  label: string;
  vendor?: string;
  model?: string;
  bed_size_mm?: [number, number, number];
  nozzle_mm?: number;
  layer_height_mm?: number;
  max_unsupported_overhang_deg?: number;
  clean_overhang_deg?: number;
  min_wall_thickness_mm?: number;
  supports_auto_tree?: boolean;
  material?: string;
  notes?: string | null;
};
