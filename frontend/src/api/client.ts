import type { LoginResponse, Tenant, UserProfile, UserSession } from "../types/auth";
import { sessionStore } from "./session";
import { API_BASE_URL } from "./base";

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
    let detail = await response.text();
    try {
      const parsed = JSON.parse(detail) as { detail?: string; message?: string };
      detail = parsed.detail || parsed.message || detail;
    } catch {
      // keep raw detail when payload is not json
    }
    throw new Error(detail || `Request failed (${response.status})`);
  }

  return response.json() as Promise<T>;
}

export async function login(email: string, password: string): Promise<LoginResponse> {
  return request<LoginResponse>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password })
  });
}

export async function googleLoginStart(redirectUri: string): Promise<{ auth_url: string; state: string }> {
  return request<{ auth_url: string; state: string }>(
    `/api/v1/auth/google/start?redirect_uri=${encodeURIComponent(redirectUri)}`
  );
}

export async function googleLoginCallback(code: string, state: string): Promise<LoginResponse> {
  return request<LoginResponse>(`/api/v1/auth/google/callback?code=${encodeURIComponent(code)}&state=${encodeURIComponent(state)}`);
}

export async function refreshToken(): Promise<LoginResponse> {
  const refresh = sessionStore.getRefreshToken();
  if (!refresh) {
    throw new Error("No refresh token available");
  }

  return request<LoginResponse>("/api/v1/auth/refresh", {
    method: "POST",
    body: JSON.stringify({ refresh_token: refresh })
  });
}

export async function switchTenant(tenantId: string): Promise<{ access_token: string; tenant_id: string }> {
  return request<{ access_token: string; tenant_id: string }>("/api/v1/auth/switch-tenant", {
    method: "POST",
    body: JSON.stringify({ tenant_id: tenantId })
  });
}

export async function getSession(): Promise<UserSession> {
  return request<UserSession>("/api/v1/auth/me");
}

export async function getUserProfile(): Promise<UserProfile> {
  return request<UserProfile>("/api/v1/users/me");
}

export async function updateUserProfile(fullName: string): Promise<UserProfile> {
  return request<UserProfile>("/api/v1/users/me", {
    method: "PATCH",
    body: JSON.stringify({ full_name: fullName })
  });
}

export async function listMyTenants(): Promise<Tenant[]> {
  return request<Tenant[]>("/api/v1/tenants/mine");
}

export async function getCurrentTenant(): Promise<Tenant> {
  return request<Tenant>("/api/v1/tenants/current");
}
