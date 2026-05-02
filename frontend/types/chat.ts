export type EditabilityLevel =
  | "editable"
  | "partially_editable"
  | "reference_only"
  | "locked_unsafe";

export type ExportMode = "rebuilt" | "as_is" | "blocked";

export type EditabilityAssessment = {
  level: EditabilityLevel;
  reasons: string[];
  editable_node_ids: string[];
  locked_node_ids: string[];
  export_allowed: boolean;
  export_mode: ExportMode;
  repair_required: boolean;
};

export type ToolCallStatus = "pending" | "running" | "done" | "error";

export type ToolCall = {
  id: string;
  name: string;
  input: Record<string, unknown>;
  status: ToolCallStatus;
  result?: unknown;
  isError?: boolean;
};

export type ChatTurnEntry =
  | { kind: "user"; text: string }
  | {
      kind: "assistant";
      text: string;
      toolCalls: ToolCall[];
      revisionIdAfter?: string;
      tokens?: {
        input: number;
        output: number;
        cacheRead: number;
        cacheCreation: number;
      };
    };
