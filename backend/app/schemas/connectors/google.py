from pydantic import BaseModel, Field

from app.schemas.connectors.common import ConnectorStatus


class GoogleAccountCreate(BaseModel):
    label: str | None = None
    enabled: bool = True
    is_workspace_default: bool = False
    gmail_enabled: bool = True
    gmail_labels: list[str] = Field(default_factory=lambda: ["INBOX", "SENT"])
    gmail_sync_mode: str = "last_n_days"
    gmail_last_n_days: int | None = 30
    gmail_max_messages: int | None = None
    gmail_query: str | None = None
    calendar_enabled: bool = True
    calendar_ids: list[str] = Field(default_factory=lambda: ["primary"])
    calendar_sync_mode: str = "range_days"
    calendar_days_back: int | None = 30
    calendar_days_forward: int | None = 90
    calendar_max_events: int | None = None
    drive_enabled: bool = False
    drive_folder_ids: list[str] = Field(default_factory=list)
    drive_file_ids: list[str] = Field(default_factory=list)
    sheets_enabled: bool = False
    sheets_targets: list[dict] = Field(default_factory=list)
    contacts_enabled: bool = False
    contacts_sync_mode: str = "all"
    contacts_group_ids: list[str] = Field(default_factory=list)
    contacts_max_count: int | None = None
    meet_enabled: bool = True
    crm_sheet_spreadsheet_id: str | None = None
    crm_sheet_tab_name: str | None = None
    sync_scope_configured: bool = False


class GoogleAccountUpdate(BaseModel):
    label: str | None = None
    enabled: bool | None = None
    is_primary: bool | None = None
    is_workspace_default: bool | None = None
    gmail_enabled: bool | None = None
    gmail_labels: list[str] | None = None
    gmail_sync_mode: str | None = None
    gmail_last_n_days: int | None = None
    gmail_max_messages: int | None = None
    gmail_query: str | None = None
    calendar_enabled: bool | None = None
    calendar_ids: list[str] | None = None
    calendar_sync_mode: str | None = None
    calendar_days_back: int | None = None
    calendar_days_forward: int | None = None
    calendar_max_events: int | None = None
    drive_enabled: bool | None = None
    drive_folder_ids: list[str] | None = None
    drive_file_ids: list[str] | None = None
    sheets_enabled: bool | None = None
    sheets_targets: list[dict] | None = None
    contacts_enabled: bool | None = None
    contacts_sync_mode: str | None = None
    contacts_group_ids: list[str] | None = None
    contacts_max_count: int | None = None
    meet_enabled: bool | None = None
    crm_sheet_spreadsheet_id: str | None = None
    crm_sheet_tab_name: str | None = None
    sync_scope_configured: bool | None = None


class GoogleAccountRead(BaseModel):
    id: str
    tenant_id: str
    user_id: str
    label: str | None = None
    google_account_email: str | None = None
    google_account_sub: str | None = None
    is_oauth_connected: bool
    is_primary: bool
    is_workspace_default: bool
    scopes: list[str] = Field(default_factory=list)
    gmail_enabled: bool
    gmail_labels: list[str]
    gmail_sync_mode: str
    gmail_last_n_days: int | None = None
    gmail_max_messages: int | None = None
    gmail_query: str | None = None
    calendar_enabled: bool
    calendar_ids: list[str]
    calendar_sync_mode: str
    calendar_days_back: int | None = None
    calendar_days_forward: int | None = None
    calendar_max_events: int | None = None
    drive_enabled: bool
    drive_folder_ids: list[str]
    drive_file_ids: list[str]
    sheets_enabled: bool
    sheets_targets: list[dict]
    contacts_enabled: bool
    contacts_sync_mode: str
    contacts_group_ids: list[str]
    contacts_max_count: int | None = None
    meet_enabled: bool
    crm_sheet_spreadsheet_id: str | None = None
    crm_sheet_tab_name: str | None = None
    sync_scope_configured: bool
    status: ConnectorStatus


class GoogleCalendarEventUpsert(BaseModel):
    calendar_id: str = "primary"
    summary: str
    description: str | None = None
    location: str | None = None
    start_datetime: str
    end_datetime: str
    timezone: str | None = "UTC"
    attendees: list[str] = Field(default_factory=list)


class GoogleCalendarEventRead(BaseModel):
    id: str
    calendar_id: str
    status: str
    html_link: str | None = None
    summary: str | None = None
    start_datetime: str | None = None
    end_datetime: str | None = None


class GoogleCalendarListItem(BaseModel):
    id: str
    summary: str
    primary: bool = False
    access_role: str | None = None
    selected: bool = False


class GoogleSyncOptionsUpdate(BaseModel):
    gmail_sync_mode: str | None = None
    gmail_last_n_days: int | None = None
    gmail_max_messages: int | None = None
    gmail_query: str | None = None
    calendar_sync_mode: str | None = None
    calendar_days_back: int | None = None
    calendar_days_forward: int | None = None
    calendar_max_events: int | None = None
    drive_enabled: bool | None = None
    drive_folder_ids: list[str] | None = None
    drive_file_ids: list[str] | None = None
    sheets_enabled: bool | None = None
    sheets_targets: list[dict] | None = None
    contacts_enabled: bool | None = None
    contacts_sync_mode: str | None = None
    contacts_group_ids: list[str] | None = None
    contacts_max_count: int | None = None


class GoogleDriveFolderItem(BaseModel):
    id: str
    name: str


class GoogleDriveFileItem(BaseModel):
    id: str
    name: str
    mime_type: str | None = None


class GoogleSheetItem(BaseModel):
    spreadsheet_id: str
    title: str


class GoogleSheetTabItem(BaseModel):
    title: str
    sheet_id: int | None = None


class GoogleContactGroupItem(BaseModel):
    resource_name: str
    name: str
