from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.middleware.mcp_auth import MCPAuthMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.request_context import RequestContextMiddleware
from app.middleware.request_signing import RequestSigningMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.routers import (
    actions,
    admin_groups,
    admin_policies,
    admin_roles,
    admin_users,
    agent_builder,
    agents,
    ai_models,
    auth,
    channels,
    chat,
    chat_v2,
    documents,
    governance,
    health,
    knowledge,
    recipes,
    retrieval,
    tenants,
    tools,
    users,
    workspace_settings,
)
from app.routers.connectors import (
    code_repo,
    confluence,
    db,
    email,
    file_upload,
    google,
    jira,
    logs,
    sharepoint,
    slack,
)
from app.services.mcp_server import get_mcp_asgi_app, start_mcp_server, stop_mcp_server

configure_logging()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    openapi_url="/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
)
app.state.db_session_factory = SessionLocal

app.add_middleware(RequestContextMiddleware)
app.add_middleware(MCPAuthMiddleware)
app.add_middleware(RequestSigningMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
allowed_ui_origins = list(
    {
        settings.ui_base_url,
        "http://localhost:5173",
        "http://localhost:1455",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:1455",
    }
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_ui_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router, prefix="/api/v1")
app.include_router(tenants.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")
app.include_router(admin_users.router, prefix="/api/v1")
app.include_router(admin_groups.router, prefix="/api/v1")
app.include_router(admin_roles.router, prefix="/api/v1")
app.include_router(admin_policies.router, prefix="/api/v1")
app.include_router(retrieval.router, prefix="/api/v1")
app.include_router(documents.router, prefix="/api/v1")
app.include_router(tools.router, prefix="/api/v1")
app.include_router(ai_models.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(agents.router, prefix="/api/v1")
app.include_router(agent_builder.router, prefix="/api/v1")
app.include_router(governance.router, prefix="/api/v1")
app.include_router(workspace_settings.router, prefix="/api/v1")
app.include_router(knowledge.router, prefix="/api/v1")
app.include_router(recipes.router, prefix="/api/v1")
app.include_router(actions.router, prefix="/api/v1")
app.include_router(channels.router, prefix="/api/v1")
app.include_router(jira.router, prefix="/api/v1")
app.include_router(slack.router, prefix="/api/v1")
app.include_router(google.router, prefix="/api/v1")
app.include_router(email.router, prefix="/api/v1")
app.include_router(code_repo.router, prefix="/api/v1")
app.include_router(confluence.router, prefix="/api/v1")
app.include_router(sharepoint.router, prefix="/api/v1")
app.include_router(db.router, prefix="/api/v1")
app.include_router(logs.router, prefix="/api/v1")
app.include_router(file_upload.router, prefix="/api/v1")
app.include_router(chat_v2.router, prefix="/api/v2")
app.mount("/api/v1/mcp", get_mcp_asgi_app())


@app.on_event("startup")
async def startup_mcp_runtime() -> None:
    app.state.mcp_runtime_cm = await start_mcp_server()


@app.on_event("shutdown")
async def shutdown_mcp_runtime() -> None:
    await stop_mcp_server(getattr(app.state, "mcp_runtime_cm", None))
    app.state.mcp_runtime_cm = None


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "CentraCortex API online"}
