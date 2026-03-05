export type LLMProvider = {
  id: string;
  tenant_id: string;
  name: string;
  provider_type: "openai" | "vllm" | "ollama" | "other" | "codex";
  base_url: string;
  model_name: string;
  is_default: boolean;
  is_fallback: boolean;
  rate_limit_rpm: number;
  config_json: Record<string, unknown>;
  has_api_key: boolean;
  requires_oauth: boolean;
  oauth_connected: boolean;
  created_at: string;
};

export type CodexOAuthStatus = {
  connected: boolean;
  connected_email: string | null;
  token_expires_at: string | null;
  scopes: string[];
};

export type LLMLog = {
  id: string;
  provider_id: string | null;
  model_name: string;
  status: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cost_usd: number;
  response_ms: number;
  error_message: string | null;
  created_at: string;
};

export type ChatResponse = {
  conversation_id: string;
  assistant_message_id: string;
  provider_id: string;
  provider_name: string;
  model_name: string;
  answer: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cost_usd: number;
  blocked: boolean;
  safety_flags: string[];
  citations: Citation[];
};

export type ChatInteractionType =
  | "answer"
  | "confirmation_required"
  | "selection_required"
  | "execution_result"
  | "error";

export type ChatActionOption = {
  id: string;
  label: string;
};

export type ChatActionContext = {
  action_type: string;
  status?: string | null;
  account_id?: string | null;
  account_label?: string | null;
  pending_action_id?: string | null;
};

export type ChatV2Response = ChatResponse & {
  interaction_type: ChatInteractionType;
  action_context: ChatActionContext | null;
  options: ChatActionOption[];
};

export type Citation = {
  document_id: string;
  document_title: string;
  document_url: string | null;
  source_type: string;
  chunk_id: string;
  chunk_index: number;
  snippet: string;
};

export type ConversationMessage = {
  id: string;
  role: "user" | "assistant" | string;
  content: string;
  created_at: string;
  citations: Citation[];
  safety_flags: string[];
  provider_name: string | null;
  model_name: string | null;
};

export type ConversationSummary = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  last_message_at: string;
  pinned_provider_id?: string | null;
  pinned_provider_name?: string | null;
  pinned_model_name?: string | null;
  pinned_at?: string | null;
};

export type ConversationDetail = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  last_message_at: string;
  pinned_provider_id?: string | null;
  pinned_provider_name?: string | null;
  pinned_model_name?: string | null;
  pinned_at?: string | null;
  messages: ConversationMessage[];
};
