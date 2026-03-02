from datetime import datetime

from pydantic import BaseModel, EmailStr


class UserRead(BaseModel):
    id: str
    email: EmailStr
    full_name: str | None = None
    is_active: bool
    created_at: datetime


class UserProfileUpdate(BaseModel):
    full_name: str | None = None
