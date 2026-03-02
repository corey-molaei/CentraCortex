export type AgentSpecTool = {
  name: string;
  purpose: string;
  requires_approval: boolean;
};

export type AgentSpecDataSource = {
  source_key: string;
  description: string;
};

export type AgentSpecTone = {
  voice: string;
  formality: "low" | "medium" | "high";
  style_rules: string[];
  few_shot_examples: string[];
};

export type AgentSpecOutputContract = {
  format: string;
  max_length: number;
  include_citations: boolean;
};

export type AgentSpec = {
  name: string;
  goal: string;
  system_prompt: string;
  agent_type: "knowledge" | "comms" | "ops" | "sql" | "guard";
  risk_level: "low" | "medium" | "high" | "critical";
  tools: AgentSpecTool[];
  data_sources: AgentSpecDataSource[];
  tone: AgentSpecTone;
  guardrails: string[];
  output_contract: AgentSpecOutputContract;
};

export type GeneratedTestCase = {
  prompt: string;
  expected_behavior: string;
  policy_focus: string;
};

export type SpecVersion = {
  id: string;
  tenant_id: string;
  agent_id: string;
  version_number: number;
  status: string;
  source_prompt: string;
  spec_json: AgentSpec;
  risk_level: string;
  selected_tools_json: string[];
  selected_data_sources_json: string[];
  tone_profile_json: Record<string, unknown>;
  generated_tests_json: GeneratedTestCase[];
  created_by_user_id: string | null;
  created_at: string;
  deployed_at: string | null;
  rollback_note: string | null;
};

export type StyleExample = {
  id: string;
  filename: string | null;
  content: string;
  profile_json: Record<string, unknown>;
  created_at: string;
};

export type SpecVersionDetail = {
  version: SpecVersion;
  style_examples: StyleExample[];
};
