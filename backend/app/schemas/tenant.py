from datetime import datetime

from pydantic import BaseModel


class TenantRead(BaseModel):
    id: str
    name: str
    slug: str
    is_active: bool
    created_at: datetime


class TenantCreate(BaseModel):
    name: str
    slug: str


class TenantMembershipRead(BaseModel):
    id: str
    tenant_id: str
    user_id: str
    role: str
    is_default: bool
