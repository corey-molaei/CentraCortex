from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "CentraCortex"
    app_env: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_base_url: str = "http://localhost:8000"
    ui_base_url: str = "http://localhost:5173"

    log_level: str = "INFO"
    prompt_debug_logging_enabled: bool = True
    prompt_debug_logging_max_chars_per_message: int = 8000
    request_id_header: str = "X-Request-ID"
    security_headers_enabled: bool = True
    csp_policy: str = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; "
        "font-src 'self' data:; "
        "connect-src 'self' http://localhost:8000 ws: wss:; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 240
    request_signing_enabled: bool = False
    request_signing_secret: str = "change-me-signing-secret"
    request_signing_max_age_seconds: int = 300

    secret_key: str = "change-me"
    encryption_key: str = "change-me-32-byte-base64-key"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 14
    password_reset_token_expire_minutes: int = 30

    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "centracortex"
    postgres_user: str = "centracortex"
    postgres_password: str = "centracortex"
    database_url: str = "postgresql+psycopg2://centracortex:centracortex@postgres:5432/centracortex"

    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/1"
    celery_result_backend: str = "redis://redis:6379/2"

    qdrant_url: str = "http://qdrant:6333"

    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_secure: bool = False
    minio_bucket_raw_documents: str = "raw-documents"
    raw_documents_local_path: str = "/tmp/centracortex-raw-documents"

    slack_client_id: str | None = None
    slack_client_secret: str | None = None
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_auth_scopes: str = "openid profile email"
    google_auth_allowed_domains: str = ""
    google_auth_default_tenant_name: str = "My Workspace"
    google_oauth_scopes: str = (
        "https://www.googleapis.com/auth/userinfo.email,"
        "https://www.googleapis.com/auth/userinfo.profile,"
        "https://www.googleapis.com/auth/gmail.readonly,"
        "https://www.googleapis.com/auth/gmail.modify,"
        "https://www.googleapis.com/auth/calendar,"
        "https://www.googleapis.com/auth/calendar.events,"
        "https://www.googleapis.com/auth/drive.readonly,"
        "https://www.googleapis.com/auth/spreadsheets"
    )
    codex_client_id: str | None = None
    codex_oauth_scopes: str = "openid profile email offline_access"

    embedding_dimension: int = 384
    chunk_size_chars: int = 1200
    chunk_overlap_chars: int = 150
    qdrant_timeout_seconds: float = 5.0
    retrieval_min_hybrid_score_abs: float = 0.06
    retrieval_min_relative_ratio: float = 0.60
    retrieval_fallback_min_score: float = 0.04
    retrieval_min_token_overlap: int = 1
    retrieval_max_citations: int = 5
    email_tool_llm_intent_parser_enabled: bool = True
    email_tool_llm_intent_parser_temperature: float = 0.1
    email_tool_llm_intent_parser_max_tokens: int = 220
    email_tool_llm_parser_enabled: bool = True
    email_tool_llm_parser_temperature: float = 0.1
    email_tool_llm_parser_max_tokens: int = 300
    email_tool_subject_max_len: int = 160
    calendar_tool_llm_parser_enabled: bool = True
    calendar_tool_llm_parser_temperature: float = 0.1
    calendar_tool_llm_parser_max_tokens: int = 400
    calendar_tool_default_duration_minutes: int = 60
    calendar_tool_max_duration_minutes: int = 480
    langgraph_checkpoint_ttl_hours: int = 168

    skip_external_healthchecks: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
