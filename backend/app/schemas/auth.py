from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class TenantMembershipSummary(BaseModel):
    tenant_id: str
    tenant_name: str
    role: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    tenant_id: str | None = None
    memberships: list[TenantMembershipSummary] = Field(default_factory=list)


class RefreshRequest(BaseModel):
    refresh_token: str


class SwitchTenantRequest(BaseModel):
    tenant_id: str


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirmRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8)


class PasswordResetRequestResponse(BaseModel):
    message: str
    token: str | None = None


class AccessTokenOnly(BaseModel):
    access_token: str
    token_type: str = "bearer"
    tenant_id: str


class SessionInfo(BaseModel):
    user_id: str
    email: str
    full_name: str | None = None
    tenant_id: str | None = None
    memberships: list[TenantMembershipSummary]
    issued_at: datetime
