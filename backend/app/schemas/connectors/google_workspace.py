from pydantic import BaseModel, Field

from app.schemas.connectors.common import (
    ConnectionTestResult,
    ConnectorStatus,
    OAuthStartResponse,
    SyncResponse,
)


class WorkspaceGoogleIntegrationUpdate(BaseModel):
    enabled: bool | None = None
    gmail_enabled: bool | None = None
    gmail_labels: list[str] | None = None
    calendar_enabled: bool | None = None
    calendar_ids: list[str] | None = None
    drive_enabled: bool | None = None
    drive_folder_ids: list[str] | None = None
    sheets_enabled: bool | None = None
    sheets_targets: list[dict] | None = None
    crm_sheet_spreadsheet_id: str | None = None
    crm_sheet_tab_name: str | None = None


class WorkspaceGoogleIntegrationRead(BaseModel):
    id: str
    tenant_id: str
    google_account_email: str | None = None
    google_account_sub: str | None = None
    is_oauth_connected: bool
    scopes: list[str] = Field(default_factory=list)
    enabled: bool
    gmail_enabled: bool
    gmail_labels: list[str]
    calendar_enabled: bool
    calendar_ids: list[str]
    drive_enabled: bool
    drive_folder_ids: list[str]
    sheets_enabled: bool
    sheets_targets: list[dict]
    crm_sheet_spreadsheet_id: str | None = None
    crm_sheet_tab_name: str | None = None
    status: ConnectorStatus


class WorkspaceGoogleTestResponse(ConnectionTestResult):
    pass


class WorkspaceGoogleOAuthStartResponse(OAuthStartResponse):
    pass


class WorkspaceGoogleSyncResponse(SyncResponse):
    pass
