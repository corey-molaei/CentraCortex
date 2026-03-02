export type ConnectorStatus = {
  enabled: boolean;
  last_sync_at: string | null;
  last_items_synced: number;
  last_error: string | null;
};

export type SyncRun = {
  id: string;
  connector_type: string;
  connector_config_id: string;
  status: string;
  items_synced: number;
  error_message: string | null;
  started_at: string;
  finished_at: string | null;
};

export type ConnectionTestResult = {
  success: boolean;
  message: string;
};
