export type TenantMembership = {
  tenant_id: string;
  tenant_name: string;
  role: string;
};

export type LoginResponse = {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
  tenant_id: string | null;
  memberships: TenantMembership[];
};

export type UserSession = {
  user_id: string;
  email: string;
  full_name: string | null;
  tenant_id: string | null;
  memberships: TenantMembership[];
  issued_at: string;
};

export type UserProfile = {
  id: string;
  email: string;
  full_name: string | null;
  is_active: boolean;
  created_at: string;
};

export type Tenant = {
  id: string;
  name: string;
  slug: string;
  is_active: boolean;
  created_at: string;
};
