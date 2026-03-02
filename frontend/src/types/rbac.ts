export type Role = {
  id: string;
  tenant_id: string | null;
  name: string;
  description: string | null;
  is_system: boolean;
  created_at: string;
};

export type Group = {
  id: string;
  tenant_id: string;
  name: string;
  description: string | null;
  created_at: string;
};

export type UserListItem = {
  id: string;
  email: string;
  full_name: string | null;
  role: string;
};

export type UserDetail = {
  id: string;
  email: string;
  full_name: string | null;
  role: string;
  groups: Group[];
  custom_roles: Role[];
};

export type Policy = {
  id: string;
  tenant_id: string;
  name: string;
  policy_type: "document" | "tool" | "data_source";
  resource_id: string;
  allow_all: boolean;
  allowed_user_ids: string[];
  allowed_group_ids: string[];
  allowed_role_names: string[];
  active: boolean;
  created_at: string;
};

export type InviteResponse = {
  invitation_id: string;
  invite_token: string;
  status: string;
};
