export type AuditLogItem = {
  id: string;
  tenant_id: string | null;
  user_id: string | null;
  event_type: string;
  resource_type: string;
  resource_id: string | null;
  action: string;
  request_id: string | null;
  ip_address: string | null;
  payload: Record<string, unknown> | null;
  created_at: string;
};

export type ApprovalQueueItem = {
  id: string;
  run_id: string;
  tool_name: string;
  requested_by_user_id: string | null;
  approved_by_user_id: string | null;
  status: string;
  request_payload_json: Record<string, unknown>;
  decision_note: string | null;
  created_at: string;
  decided_at: string | null;
};
