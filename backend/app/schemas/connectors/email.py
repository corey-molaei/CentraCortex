from pydantic import BaseModel, Field

from app.schemas.connectors.common import ConnectorStatus


class EmailAccountCreate(BaseModel):
    label: str | None = None
    email_address: str
    username: str
    password: str
    imap_host: str
    imap_port: int = 993
    use_ssl: bool = True
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_use_starttls: bool = True
    folders: list[str] = Field(default_factory=lambda: ["INBOX", "Sent"])
    enabled: bool = True


class EmailAccountUpdate(BaseModel):
    label: str | None = None
    email_address: str | None = None
    username: str | None = None
    password: str | None = None
    imap_host: str | None = None
    imap_port: int | None = None
    use_ssl: bool | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_use_starttls: bool | None = None
    folders: list[str] | None = None
    enabled: bool | None = None
    is_primary: bool | None = None


class EmailAccountRead(BaseModel):
    id: str
    tenant_id: str
    user_id: str
    label: str | None = None
    email_address: str
    username: str
    imap_host: str
    imap_port: int
    use_ssl: bool
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_use_starttls: bool
    folders: list[str]
    is_primary: bool
    status: ConnectorStatus
