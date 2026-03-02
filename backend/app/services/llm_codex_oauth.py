from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decrypt_secret, encrypt_secret
from app.models.connector_oauth_state import ConnectorOAuthState
from app.models.tenant_codex_oauth_token import TenantCodexOAuthToken

CODEX_OAUTH_AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize"
CODEX_OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
CODEX_OAUTH_USERINFO_URL = "https://auth.openai.com/oauth/userinfo"
CODEX_OAUTH_SCOPES = ["openid", "profile", "email", "offline_access"]
CODEX_CONNECTOR_TYPE = "codex_llm"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_scopes(raw_scope: str | None) -> list[str]:
    if not raw_scope:
        return _configured_scopes()
    return [token for token in str(raw_scope).split() if token]


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _decode_jwt_payload(token: str) -> dict:
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    try:
        payload_raw = _b64url_decode(parts[1])
        payload = json.loads(payload_raw.decode("utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _extract_organization_id(source: dict | None) -> str | None:
    if not isinstance(source, dict):
        return None

    direct = source.get("organization_id") or source.get("org_id")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    organizations = source.get("organizations")
    if isinstance(organizations, list):
        for item in organizations:
            if isinstance(item, str) and item.strip():
                return item.strip()
            if isinstance(item, dict):
                org_id = item.get("organization_id") or item.get("org_id") or item.get("id")
                if isinstance(org_id, str) and org_id.strip():
                    return org_id.strip()
    return None


def _pkce_code_verifier(state_token: str) -> str:
    # Deterministic verifier derived from state + server secret avoids schema changes.
    digest = hmac.new(settings.secret_key.encode("utf-8"), state_token.encode("utf-8"), hashlib.sha256).digest()
    return _b64url(digest)


def _pkce_code_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    return _b64url(digest)


def _codex_request(
    *,
    method: str,
    url: str,
    data: dict | None = None,
    access_token: str | None = None,
) -> dict:
    headers: dict[str, str] = {}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"

    with httpx.Client(timeout=30) as client:
        response = client.request(method, url, headers=headers, data=data)

    if response.status_code >= 400:
        detail = response.text
        try:
            payload = response.json()
            detail = str(payload.get("error_description") or payload.get("error") or payload)
        except Exception:
            pass
        raise ValueError(f"Codex OAuth request failed: {detail}")

    if response.status_code == 204 or not response.content:
        return {}

    try:
        return response.json()
    except Exception as exc:
        raise ValueError("Codex OAuth returned non-JSON response") from exc


def _configured_scopes() -> list[str]:
    raw = settings.codex_oauth_scopes.strip()
    if not raw:
        return CODEX_OAUTH_SCOPES.copy()
    normalized = raw.replace(",", " ")
    parsed = [token for token in normalized.split() if token]
    return parsed or CODEX_OAUTH_SCOPES.copy()


def _platform_client_id() -> str:
    client_id = (settings.codex_client_id or "").strip()
    if not client_id:
        raise ValueError(
            "Codex OAuth client is not configured. Set CODEX_CLIENT_ID in platform config."
        )
    return client_id


def _exchange_subject_token_for_api_key(
    *,
    client_id: str,
    subject_token: str,
    subject_token_type: str,
    organization_id: str | None = None,
) -> str:
    exchange_data = {
        "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
        "resource": "https://api.openai.com/",
        "subject_token": subject_token,
        "subject_token_type": subject_token_type,
        "requested_token_type": "urn:openai:params:oauth:token-type:api_key",
    }
    if organization_id:
        exchange_data["organization_id"] = organization_id

    try:
        payload = _codex_request(
            method="POST",
            url=CODEX_OAUTH_TOKEN_URL,
            data=exchange_data,
        )
    except ValueError:
        # Backward-compatible fallback for environments that still expect this shape.
        fallback_data = {
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "subject_token": subject_token,
            "subject_token_type": subject_token_type,
            "requested_token": "openai-api-key",
            "client_id": client_id,
        }
        if organization_id:
            fallback_data["organization_id"] = organization_id
        payload = _codex_request(
            method="POST",
            url=CODEX_OAUTH_TOKEN_URL,
            data=fallback_data,
        )
    api_key = payload.get("access_token")
    if not api_key:
        raise ValueError("Codex API key exchange did not return an API key")
    return str(api_key)


def get_oauth_status(db: Session, tenant_id: str) -> TenantCodexOAuthToken | None:
    return db.execute(
        select(TenantCodexOAuthToken).where(TenantCodexOAuthToken.tenant_id == tenant_id)
    ).scalar_one_or_none()


def get_oauth_start_url(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    redirect_uri: str,
) -> tuple[str, str]:
    client_id = _platform_client_id()

    state = secrets.token_hex(16)
    code_verifier = _pkce_code_verifier(state)
    code_challenge = _pkce_code_challenge(code_verifier)
    db.add(
        ConnectorOAuthState(
            tenant_id=tenant_id,
            user_id=user_id,
            connector_type=CODEX_CONNECTOR_TYPE,
            connector_config_id=None,
            state_token=state,
            redirect_uri=redirect_uri,
            expires_at=_utcnow() + timedelta(minutes=10),
        )
    )
    db.commit()

    params = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(_configured_scopes()),
            "state": state,
            "id_token_add_organizations": "true",
            "codex_cli_simplified_flow": "true",
            "originator": "pi",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{CODEX_OAUTH_AUTHORIZE_URL}?{params}", state


def complete_oauth_callback(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    code: str,
    state: str,
) -> TenantCodexOAuthToken:
    state_row = db.execute(
        select(ConnectorOAuthState).where(
            ConnectorOAuthState.tenant_id == tenant_id,
            ConnectorOAuthState.user_id == user_id,
            ConnectorOAuthState.connector_type == CODEX_CONNECTOR_TYPE,
            ConnectorOAuthState.state_token == state,
        )
    ).scalar_one_or_none()
    if state_row is None:
        raise ValueError("Invalid OAuth state")
    if (_coerce_utc(state_row.expires_at) or _utcnow()) < _utcnow():
        db.delete(state_row)
        db.commit()
        raise ValueError("OAuth state has expired")

    client_id = _platform_client_id()
    code_verifier = _pkce_code_verifier(state_row.state_token)

    token_payload = _codex_request(
        method="POST",
        url=CODEX_OAUTH_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "redirect_uri": state_row.redirect_uri,
            "code_verifier": code_verifier,
        },
    )

    access_token = token_payload.get("access_token")
    if not access_token:
        raise ValueError("Codex token exchange did not return an access token")
    id_token = token_payload.get("id_token")
    if not id_token:
        raise ValueError("Codex token exchange did not return an id_token required for API key exchange")

    profile_payload: dict = {}
    try:
        profile_payload = _codex_request(
            method="GET",
            url=CODEX_OAUTH_USERINFO_URL,
            access_token=str(access_token),
        )
    except Exception:
        profile_payload = {}

    jwt_payload = _decode_jwt_payload(str(id_token))
    organization_id = (
        _extract_organization_id(token_payload)
        or _extract_organization_id(jwt_payload)
        or _extract_organization_id(profile_payload)
    )
    exchange_errors: list[str] = []
    subject_candidates = [
        (str(id_token), "urn:ietf:params:oauth:token-type:id_token"),
        (str(access_token), "urn:ietf:params:oauth:token-type:access_token"),
    ]
    api_key: str | None = None
    for token_value, token_type in subject_candidates:
        try:
            api_key = _exchange_subject_token_for_api_key(
                client_id=client_id,
                subject_token=token_value,
                subject_token_type=token_type,
                organization_id=organization_id,
            )
            break
        except ValueError as exc:
            exchange_errors.append(str(exc))
    using_fallback_oauth_access_token = api_key is None

    token_row = get_oauth_status(db, tenant_id)
    if token_row is None:
        token_row = TenantCodexOAuthToken(
            tenant_id=tenant_id,
            access_token_encrypted="",
            scopes=[],
        )
        db.add(token_row)

    if using_fallback_oauth_access_token:
        token_row.access_token_encrypted = encrypt_secret(str(access_token))
        token_row.token_expires_at = _utcnow() + timedelta(seconds=int(token_payload.get("expires_in", 3600)))
    else:
        token_row.access_token_encrypted = encrypt_secret(api_key)
        token_row.token_expires_at = None
    refresh_token = token_payload.get("refresh_token")
    if refresh_token:
        token_row.refresh_token_encrypted = encrypt_secret(str(refresh_token))
    token_row.scopes = _parse_scopes(token_payload.get("scope"))
    token_row.subject = str(profile_payload.get("sub") or profile_payload.get("id") or "") or None
    token_row.connected_email = str(profile_payload.get("email") or "") or None

    db.delete(state_row)
    db.commit()
    db.refresh(token_row)
    return token_row


def _refresh_access_token(db: Session, tenant_id: str) -> str:
    client_id = _platform_client_id()

    token_row = get_oauth_status(db, tenant_id)
    if token_row is None:
        raise ValueError("Codex is not connected. Connect it in Tenant Settings / AI Models.")
    if not token_row.refresh_token_encrypted:
        raise ValueError("Codex refresh token is missing. Reconnect Codex in Tenant Settings / AI Models.")

    payload = _codex_request(
        method="POST",
        url=CODEX_OAUTH_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": decrypt_secret(token_row.refresh_token_encrypted),
            "client_id": client_id,
        },
    )
    id_token = payload.get("id_token")
    if not id_token:
        raise ValueError("Codex refresh flow did not return id_token required for API key exchange")

    profile_payload: dict = {}
    access_token = payload.get("access_token")
    if access_token:
        try:
            profile_payload = _codex_request(
                method="GET",
                url=CODEX_OAUTH_USERINFO_URL,
                access_token=str(access_token),
            )
        except Exception:
            profile_payload = {}

    jwt_payload = _decode_jwt_payload(str(id_token))
    organization_id = (
        _extract_organization_id(payload)
        or _extract_organization_id(jwt_payload)
        or _extract_organization_id(profile_payload)
    )
    exchange_errors: list[str] = []
    subject_candidates: list[tuple[str, str]] = [
        (str(id_token), "urn:ietf:params:oauth:token-type:id_token"),
    ]
    if access_token:
        subject_candidates.append((str(access_token), "urn:ietf:params:oauth:token-type:access_token"))

    api_key: str | None = None
    for token_value, token_type in subject_candidates:
        try:
            api_key = _exchange_subject_token_for_api_key(
                client_id=client_id,
                subject_token=token_value,
                subject_token_type=token_type,
                organization_id=organization_id,
            )
            break
        except ValueError as exc:
            exchange_errors.append(str(exc))
    if not api_key:
        if not access_token:
            if not organization_id and any("invalid_subject_token" in err for err in exchange_errors):
                raise ValueError(
                    "Codex OAuth refresh failed: OpenAI token has no organization_id. "
                    "Reconnect using an account with API organization access."
                )
            raise ValueError(
                "Codex OAuth refresh failed: "
                + "; ".join(exchange_errors[:2] or ["unknown token exchange error"])
            )
        token_row.access_token_encrypted = encrypt_secret(str(access_token))
        token_row.token_expires_at = _utcnow() + timedelta(seconds=int(payload.get("expires_in", 3600)))
        if payload.get("refresh_token"):
            token_row.refresh_token_encrypted = encrypt_secret(str(payload.get("refresh_token")))
        if payload.get("scope"):
            token_row.scopes = _parse_scopes(payload.get("scope"))
        db.commit()
        return str(access_token)

    token_row.access_token_encrypted = encrypt_secret(api_key)
    token_row.token_expires_at = None
    if payload.get("refresh_token"):
        token_row.refresh_token_encrypted = encrypt_secret(str(payload.get("refresh_token")))
    if payload.get("scope"):
        token_row.scopes = _parse_scopes(payload.get("scope"))
    db.commit()
    return api_key


def get_valid_access_token(db: Session, tenant_id: str) -> str:
    token_row = get_oauth_status(db, tenant_id)
    if token_row is None:
        raise ValueError("Codex is not connected. Connect it in Tenant Settings / AI Models.")

    expires_at = _coerce_utc(token_row.token_expires_at)
    if expires_at is not None and expires_at <= _utcnow() + timedelta(seconds=30):
        return _refresh_access_token(db, tenant_id)

    if not token_row.access_token_encrypted:
        return _refresh_access_token(db, tenant_id)

    return decrypt_secret(token_row.access_token_encrypted)


def disconnect(db: Session, tenant_id: str) -> bool:
    token_row = get_oauth_status(db, tenant_id)
    if token_row is None:
        return False

    db.delete(token_row)
    db.commit()
    return True
