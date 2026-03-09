import { sessionStore } from "./session";
import { API_BASE_URL } from "./base";
import type {
  ChatV2Response,
  CodexOAuthStatus,
  ConversationDetail,
  ConversationSummary,
  LLMLog,
  LLMProvider,
} from "../types/llm";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = sessionStore.getAccessToken();
  const tenantId = sessionStore.getTenantId();
  const headers = new Headers(init?.headers);
  headers.set("Content-Type", "application/json");
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  if (tenantId) {
    headers.set("X-Tenant-ID", tenantId);
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers
  });

  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json() as Promise<T>;
}

export function listProviders() {
  return request<LLMProvider[]>("/api/v1/tenant-settings/ai/providers");
}

export function createProvider(payload: {
  name: string;
  provider_type: "openai" | "vllm" | "ollama" | "other" | "codex";
  base_url: string;
  api_key?: string;
  model_name: string;
  is_default: boolean;
  is_fallback: boolean;
  rate_limit_rpm: number;
}) {
  return request<LLMProvider>("/api/v1/tenant-settings/ai/providers", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function updateProvider(
  providerId: string,
  payload: {
    name?: string;
    base_url?: string;
    api_key?: string;
    model_name?: string;
    is_default?: boolean;
    is_fallback?: boolean;
    rate_limit_rpm?: number;
    config_json?: Record<string, unknown>;
  }
) {
  return request<LLMProvider>(`/api/v1/tenant-settings/ai/providers/${providerId}`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export function deleteProvider(providerId: string) {
  return request<{ message: string }>(`/api/v1/tenant-settings/ai/providers/${providerId}`, {
    method: "DELETE"
  });
}

export function codexOAuthStart(redirectUri: string) {
  const encoded = encodeURIComponent(redirectUri);
  return request<{ auth_url: string; state: string }>(`/api/v1/tenant-settings/ai/codex/oauth/start?redirect_uri=${encoded}`);
}

export function codexOAuthCallback(code: string, state: string) {
  return request<{ message: string }>(
    `/api/v1/tenant-settings/ai/codex/oauth/callback?code=${encodeURIComponent(code)}&state=${encodeURIComponent(state)}`
  );
}

export function getCodexOAuthStatus() {
  return request<CodexOAuthStatus>("/api/v1/tenant-settings/ai/codex/oauth/status");
}

export function disconnectCodexOAuth() {
  return request<{ message: string }>("/api/v1/tenant-settings/ai/codex/oauth/disconnect", {
    method: "POST"
  });
}

export function testProvider(providerId: string) {
  return request<{ success: boolean; message: string }>(
    `/api/v1/tenant-settings/ai/providers/${providerId}/test`,
    { method: "POST" }
  );
}

export function listLLMLogs() {
  return request<LLMLog[]>("/api/v1/tenant-settings/ai/logs");
}

export function completeChat(payload: {
  messages: { role: string; content: string }[];
  temperature?: number;
  provider_id_override?: string;
  conversation_id?: string;
  retrieval_limit?: number;
  client_timezone?: string;
  client_now_iso?: string;
}) {
  return request<ChatV2Response>("/api/v2/chat/complete", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function confirmChatAction(payload: {
  conversation_id: string;
  confirm: boolean;
  provider_id_override?: string;
  retrieval_limit?: number;
  temperature?: number;
  client_timezone?: string;
  client_now_iso?: string;
}) {
  return request<ChatV2Response>("/api/v2/chat/actions/confirm", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function selectChatAction(payload: {
  conversation_id: string;
  selection: string;
  provider_id_override?: string;
  retrieval_limit?: number;
  temperature?: number;
  client_timezone?: string;
  client_now_iso?: string;
}) {
  return request<ChatV2Response>("/api/v2/chat/actions/select", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function listConversations() {
  return request<ConversationSummary[]>("/api/v1/chat/conversations");
}

export function getConversation(conversationId: string) {
  return request<ConversationDetail>(`/api/v1/chat/conversations/${conversationId}`);
}

export function deleteConversation(conversationId: string) {
  return request<{ message: string }>(`/api/v1/chat/conversations/${conversationId}`, {
    method: "DELETE"
  });
}

export function reportAnswer(conversationId: string, messageId: string, note: string) {
  return request<{ status: string; feedback_id: string }>(
    `/api/v1/chat/conversations/${conversationId}/messages/${messageId}/report`,
    {
      method: "POST",
      body: JSON.stringify({ note })
    }
  );
}
