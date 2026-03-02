export type AgentDefinition = {
  id: string;
  tenant_id: string;
  name: string;
  description: string | null;
  system_prompt: string;
  default_agent_type: "knowledge" | "comms" | "ops" | "sql" | "guard";
  allowed_tools: string[];
  enabled: boolean;
  config_json: Record<string, unknown>;
  created_by_user_id: string | null;
  created_at: string;
  updated_at: string;
};

export type AgentRun = {
  id: string;
  tenant_id: string;
  agent_id: string;
  initiated_by_user_id: string | null;
  status: "running" | "waiting_approval" | "completed" | "failed" | string;
  input_text: string;
  output_text: string | null;
  routed_agent: string | null;
  error_message: string | null;
  metadata_json: Record<string, unknown>;
  started_at: string;
  finished_at: string | null;
};

export type AgentTraceStep = {
  id: string;
  step_order: number;
  agent_name: string;
  step_type: string;
  tool_name: string | null;
  input_json: Record<string, unknown>;
  output_json: Record<string, unknown>;
  reasoning_redacted: string | null;
  status: string;
  created_at: string;
};

export type ToolApproval = {
  id: string;
  run_id: string;
  tool_name: string;
  requested_by_user_id: string | null;
  approved_by_user_id: string | null;
  status: "pending" | "approved" | "rejected" | string;
  request_payload_json: Record<string, unknown>;
  decision_note: string | null;
  created_at: string;
  decided_at: string | null;
};

export type AgentRunDetail = {
  run: AgentRun;
  traces: AgentTraceStep[];
  approvals: ToolApproval[];
};
