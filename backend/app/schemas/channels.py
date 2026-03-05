from pydantic import BaseModel, Field


class ChannelConnectorRead(BaseModel):
    id: str
    tenant_id: str
    channel: str
    enabled: bool
    configured: bool
    last_error: str | None = None
    config_json: dict = Field(default_factory=dict)


class TelegramConnectorUpdate(BaseModel):
    enabled: bool | None = None
    bot_token: str | None = None
    webhook_secret: str | None = None


class WhatsAppConnectorUpdate(BaseModel):
    enabled: bool | None = None
    access_token: str | None = None
    phone_number_id: str | None = None
    business_account_id: str | None = None
    verify_token: str | None = None


class FacebookConnectorUpdate(BaseModel):
    enabled: bool | None = None
    page_access_token: str | None = None
    page_id: str | None = None
    app_id: str | None = None
    app_secret: str | None = None
    verify_token: str | None = None


class ChannelTestResponse(BaseModel):
    success: bool
    message: str


class ChannelInboundEvent(BaseModel):
    external_user_id: str
    text: str
    name: str | None = None
    phone: str | None = None
    email: str | None = None
