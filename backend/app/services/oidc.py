from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class OIDCUserInfo:
    subject: str
    email: str
    full_name: str | None = None


class OIDCProvider(Protocol):
    def exchange_code(self, code: str, redirect_uri: str) -> dict:
        """Exchange authorization code for tokens."""

    def parse_userinfo(self, token_response: dict) -> OIDCUserInfo:
        """Resolve normalized user info from provider response."""
