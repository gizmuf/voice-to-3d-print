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

export type Manufacturability = {
  process: "fdm" | "cnc";
  status: "safe" | "warn" | "unprintable";
  issues: ManufacturabilityIssue[];
  estimated_volume_mm3?: number | null;
  bounding_box_mm?: [number, number, number] | null;
};

export type PrintEstimate = {
  filament_g?: number | null;
  filament_cm3?: number | null;
  print_minutes?: number | null;
  cost_usd?: number | null;
  cost_usd_per_g?: number | null;
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
};
