import type {
  ChannelConnector,
  KnowledgeHealthResponse,
  Recipe,
  WorkspaceGoogleIntegration,
  WorkspaceGoogleIntegrationUpdate,
  WorkspaceRecipeState,
  WorkspaceSettings,
  WorkspaceSettingsUpdate
} from "../types/workspace";
import { sessionStore } from "./session";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = sessionStore.getAccessToken();
  const tenantId = sessionStore.getTenantId();
  const headers = new Headers(init?.headers);
  if (!(init?.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
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
    let message = await response.text();
    try {
      const parsed = JSON.parse(message) as { detail?: string; message?: string };
      message = parsed.detail || parsed.message || message;
    } catch {
      // keep raw response text
    }
    throw new Error(message || `Request failed (${response.status})`);
  }

  return response.json() as Promise<T>;
}

export function getWorkspaceSettings() {
  return request<WorkspaceSettings>("/api/v1/workspace/settings");
}

export function updateWorkspaceSettings(payload: WorkspaceSettingsUpdate) {
  return request<WorkspaceSettings>("/api/v1/workspace/settings", {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export function getKnowledgeHealth() {
  return request<KnowledgeHealthResponse>("/api/v1/knowledge/health");
}

export function listRecipes() {
  return request<Recipe[]>("/api/v1/recipes");
}

export function listRecipeStates() {
  return request<WorkspaceRecipeState[]>("/api/v1/recipes/states");
}

export function updateRecipeState(recipeId: string, payload: { enabled: boolean; config_json: Record<string, unknown> }) {
  return request<WorkspaceRecipeState>(`/api/v1/recipes/${encodeURIComponent(recipeId)}/state`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export function getWorkspaceGoogleConfig() {
  return request<WorkspaceGoogleIntegration>("/api/v1/connectors/google-workspace/config");
}

export function updateWorkspaceGoogleConfig(payload: WorkspaceGoogleIntegrationUpdate) {
  return request<WorkspaceGoogleIntegration>("/api/v1/connectors/google-workspace/config", {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export function startWorkspaceGoogleOAuth(redirectUri: string) {
  return request<{ auth_url: string; state: string }>(
    `/api/v1/connectors/google-workspace/oauth/start?redirect_uri=${encodeURIComponent(redirectUri)}`
  );
}

export function completeWorkspaceGoogleOAuth(code: string, state: string) {
  return request<{ message: string }>(
    `/api/v1/connectors/google-workspace/oauth/callback?code=${encodeURIComponent(code)}&state=${encodeURIComponent(state)}`
  );
}

export function testWorkspaceGoogle() {
  return request<{ success: boolean; message: string }>("/api/v1/connectors/google-workspace/test", { method: "POST" });
}

export function syncWorkspaceGoogle() {
  return request<{ status: string; items_synced: number; message: string }>("/api/v1/connectors/google-workspace/sync", {
    method: "POST"
  });
}

export function workspaceGoogleStatus() {
  return request<{
    enabled: boolean;
    last_sync_at: string | null;
    last_items_synced: number;
    last_error: string | null;
  }>("/api/v1/connectors/google-workspace/status");
}

export function listChannelConnectors() {
  return request<ChannelConnector[]>("/api/v1/channels/status");
}

export function updateTelegramConnector(payload: { enabled?: boolean; bot_token?: string | null; webhook_secret?: string | null }) {
  return request<ChannelConnector>("/api/v1/channels/telegram", {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export function updateWhatsAppConnector(payload: {
  enabled?: boolean;
  access_token?: string | null;
  phone_number_id?: string | null;
  business_account_id?: string | null;
  verify_token?: string | null;
}) {
  return request<ChannelConnector>("/api/v1/channels/whatsapp", {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export function updateFacebookConnector(payload: {
  enabled?: boolean;
  page_access_token?: string | null;
  page_id?: string | null;
  app_id?: string | null;
  app_secret?: string | null;
  verify_token?: string | null;
}) {
  return request<ChannelConnector>("/api/v1/channels/facebook", {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

export function testTelegramConnector() {
  return request<{ success: boolean; message: string }>("/api/v1/channels/telegram/test", { method: "POST" });
}

export function testWhatsAppConnector() {
  return request<{ success: boolean; message: string }>("/api/v1/channels/whatsapp/test", { method: "POST" });
}

export function testFacebookConnector() {
  return request<{ success: boolean; message: string }>("/api/v1/channels/facebook/test", { method: "POST" });
}

export function undoAction(actionId: string) {
  return request<{ status: string; message: string }>(`/api/v1/actions/${encodeURIComponent(actionId)}/undo`, {
    method: "POST"
  });
}
