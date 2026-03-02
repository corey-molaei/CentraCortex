from pydantic import BaseModel, Field

from app.schemas.connectors.common import ConnectorStatus


class GoogleAccountCreate(BaseModel):
    label: str | None = None
    enabled: bool = True
    gmail_enabled: bool = True
    gmail_labels: list[str] = Field(default_factory=lambda: ["INBOX", "SENT"])
    calendar_enabled: bool = True
    calendar_ids: list[str] = Field(default_factory=lambda: ["primary"])


class GoogleAccountUpdate(BaseModel):
    label: str | None = None
    enabled: bool | None = None
    is_primary: bool | None = None
    gmail_enabled: bool | None = None
    gmail_labels: list[str] | None = None
    calendar_enabled: bool | None = None
    calendar_ids: list[str] | None = None


class GoogleAccountRead(BaseModel):
    id: str
    tenant_id: str
    user_id: str
    label: str | None = None
    google_account_email: str | None = None
    google_account_sub: str | None = None
    is_oauth_connected: bool
    is_primary: bool
    scopes: list[str] = Field(default_factory=list)
    gmail_enabled: bool
    gmail_labels: list[str]
    calendar_enabled: bool
    calendar_ids: list[str]
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
