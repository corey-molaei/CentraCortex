import type { LoginResponse } from "../types/auth";

const ACCESS_KEY = "cc_access_token";
const REFRESH_KEY = "cc_refresh_token";
const TENANT_KEY = "cc_tenant_id";

export const sessionStore = {
  save(login: LoginResponse) {
    localStorage.setItem(ACCESS_KEY, login.access_token);
    localStorage.setItem(REFRESH_KEY, login.refresh_token);
    if (login.tenant_id) {
      localStorage.setItem(TENANT_KEY, login.tenant_id);
    }
  },
  getAccessToken() {
    return localStorage.getItem(ACCESS_KEY);
  },
  getRefreshToken() {
    return localStorage.getItem(REFRESH_KEY);
  },
  getTenantId() {
    return localStorage.getItem(TENANT_KEY);
  },
  setTenantId(tenantId: string) {
    localStorage.setItem(TENANT_KEY, tenantId);
  },
  setAccessToken(token: string) {
    localStorage.setItem(ACCESS_KEY, token);
  },
  clear() {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
    localStorage.removeItem(TENANT_KEY);
  }
};
