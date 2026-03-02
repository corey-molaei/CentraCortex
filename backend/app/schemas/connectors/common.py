from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ConnectorStatus(BaseModel):
    enabled: bool
    last_sync_at: datetime | None = None
    last_items_synced: int = 0
    last_error: str | None = None


class SyncRunRead(BaseModel):
    id: str
    connector_type: str
    connector_config_id: str
    status: str
    items_synced: int
    error_message: str | None = None
    started_at: datetime
    finished_at: datetime | None = None


class ConnectionTestResult(BaseModel):
    success: bool
    message: str


class OAuthStartResponse(BaseModel):
    auth_url: str
    state: str


class SyncResponse(BaseModel):
    status: str
    items_synced: int
    message: str


class DocumentMappingPreview(BaseModel):
    source_type: str
    source_id: str
    title: str
    url: str | None = None
    author: str | None = None
    raw_text_preview: str
    metadata_json: dict[str, Any] = Field(default_factory=dict)
