export type WorkspaceAllowedActions = {
  email_send: boolean;
  email_reply: boolean;
  calendar_create: boolean;
  calendar_update: boolean;
  calendar_delete: boolean;
};

export type WorkspaceSettings = {
  tenant_id: string;
  business_name: string | null;
  timezone: string;
  default_email_signature: string | null;
  fallback_contact: string | null;
  escalation_email: string | null;
  working_hours_json: Record<string, unknown>;
  allowed_actions: WorkspaceAllowedActions;
  updated_at: string | null;
};

export type WorkspaceSettingsUpdate = {
  business_name?: string | null;
  timezone?: string | null;
  default_email_signature?: string | null;
  fallback_contact?: string | null;
  escalation_email?: string | null;
  working_hours_json?: Record<string, unknown> | null;
  allowed_actions?: WorkspaceAllowedActions;
};

export type ConnectorStatus = {
  enabled: boolean;
  last_sync_at: string | null;
  last_items_synced: number;
  last_error: string | null;
};

export type WorkspaceGoogleIntegration = {
  id: string;
  tenant_id: string;
  google_account_email: string | null;
  google_account_sub: string | null;
  is_oauth_connected: boolean;
  scopes: string[];
  enabled: boolean;
  gmail_enabled: boolean;
  gmail_labels: string[];
  calendar_enabled: boolean;
  calendar_ids: string[];
  drive_enabled: boolean;
  drive_folder_ids: string[];
  sheets_enabled: boolean;
  sheets_targets: Array<Record<string, unknown>>;
  crm_sheet_spreadsheet_id: string | null;
  crm_sheet_tab_name: string | null;
  status: ConnectorStatus;
};

export type WorkspaceGoogleIntegrationUpdate = {
  enabled?: boolean;
  gmail_enabled?: boolean;
  gmail_labels?: string[];
  calendar_enabled?: boolean;
  calendar_ids?: string[];
  drive_enabled?: boolean;
  drive_folder_ids?: string[];
  sheets_enabled?: boolean;
  sheets_targets?: Array<Record<string, unknown>>;
  crm_sheet_spreadsheet_id?: string | null;
  crm_sheet_tab_name?: string | null;
};

export type KnowledgeHealthItem = {
  source_type: string;
  documents: number;
  indexed: number;
  pending: number;
  retry: number;
  failed: number;
  last_source_update_at: string | null;
};

export type KnowledgeHealthResponse = {
  tenant_id: string;
  total_documents: number;
  total_chunks: number;
  latest_sync_at: string | null;
  sources: KnowledgeHealthItem[];
  recent_errors: string[];
};

export type Recipe = {
  id: string;
  key: string;
  name: string;
  description: string;
  default_config_json: Record<string, unknown>;
};

export type WorkspaceRecipeState = {
  id: string;
  tenant_id: string;
  recipe_id: string;
  enabled: boolean;
  config_json: Record<string, unknown>;
  updated_at: string;
};

export type ChannelConnector = {
  id: string;
  tenant_id: string;
  channel: "telegram" | "whatsapp" | "facebook";
  enabled: boolean;
  configured: boolean;
  last_error: string | null;
  config_json: Record<string, unknown>;
};
