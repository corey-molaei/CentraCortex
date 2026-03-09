"""google connector unification and sync scope controls

Revision ID: 20260309_0018
Revises: 20260305_0017
Create Date: 2026-03-09
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa

from alembic import op

revision = "20260309_0018"
down_revision = "20260305_0017"
branch_labels = None
depends_on = None


def _add_columns() -> None:
    op.add_column(
        "google_user_connectors",
        sa.Column("is_workspace_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    op.add_column(
        "google_user_connectors",
        sa.Column("gmail_sync_mode", sa.String(length=32), nullable=False, server_default=sa.text("'last_n_days'")),
    )
    op.add_column(
        "google_user_connectors",
        sa.Column("gmail_last_n_days", sa.Integer(), nullable=True, server_default=sa.text("30")),
    )
    op.add_column("google_user_connectors", sa.Column("gmail_max_messages", sa.Integer(), nullable=True))
    op.add_column("google_user_connectors", sa.Column("gmail_query", sa.String(length=1000), nullable=True))

    op.add_column(
        "google_user_connectors",
        sa.Column("calendar_sync_mode", sa.String(length=32), nullable=False, server_default=sa.text("'range_days'")),
    )
    op.add_column(
        "google_user_connectors",
        sa.Column("calendar_days_back", sa.Integer(), nullable=True, server_default=sa.text("30")),
    )
    op.add_column(
        "google_user_connectors",
        sa.Column("calendar_days_forward", sa.Integer(), nullable=True, server_default=sa.text("90")),
    )
    op.add_column("google_user_connectors", sa.Column("calendar_max_events", sa.Integer(), nullable=True))

    op.add_column("google_user_connectors", sa.Column("drive_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("google_user_connectors", sa.Column("drive_folder_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")))
    op.add_column("google_user_connectors", sa.Column("drive_file_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")))

    op.add_column("google_user_connectors", sa.Column("sheets_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("google_user_connectors", sa.Column("sheets_targets", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")))

    op.add_column(
        "google_user_connectors",
        sa.Column("contacts_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "google_user_connectors",
        sa.Column("contacts_sync_mode", sa.String(length=32), nullable=False, server_default=sa.text("'all'")),
    )
    op.add_column(
        "google_user_connectors",
        sa.Column("contacts_group_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
    )
    op.add_column("google_user_connectors", sa.Column("contacts_max_count", sa.Integer(), nullable=True))

    op.add_column("google_user_connectors", sa.Column("meet_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")))

    op.add_column("google_user_connectors", sa.Column("crm_sheet_spreadsheet_id", sa.String(length=255), nullable=True))
    op.add_column("google_user_connectors", sa.Column("crm_sheet_tab_name", sa.String(length=255), nullable=True))

    op.add_column(
        "google_user_connectors",
        sa.Column("sync_scope_configured", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    op.create_index(
        op.f("ix_google_user_connectors_is_workspace_default"),
        "google_user_connectors",
        ["is_workspace_default"],
        unique=False,
    )


def _drop_column_defaults() -> None:
    for column_name in [
        "is_workspace_default",
        "gmail_sync_mode",
        "gmail_last_n_days",
        "calendar_sync_mode",
        "calendar_days_back",
        "calendar_days_forward",
        "drive_enabled",
        "drive_folder_ids",
        "drive_file_ids",
        "sheets_enabled",
        "sheets_targets",
        "contacts_enabled",
        "contacts_sync_mode",
        "contacts_group_ids",
        "meet_enabled",
        "sync_scope_configured",
    ]:
        op.alter_column("google_user_connectors", column_name, server_default=None)


def _tenant_actor_user_id(bind, tenant_id: str) -> str | None:
    return bind.execute(
        sa.text(
            """
            SELECT user_id
            FROM tenant_memberships
            WHERE tenant_id = :tenant_id
            ORDER BY
              CASE role
                WHEN 'Owner' THEN 0
                WHEN 'Admin' THEN 1
                ELSE 2
              END,
              created_at ASC
            LIMIT 1
            """
        ),
        {"tenant_id": tenant_id},
    ).scalar_one_or_none()


def _has_primary_for_user(bind, tenant_id: str, user_id: str) -> bool:
    count = bind.execute(
        sa.text(
            """
            SELECT count(*)
            FROM google_user_connectors
            WHERE tenant_id = :tenant_id AND user_id = :user_id AND is_primary = true
            """
        ),
        {"tenant_id": tenant_id, "user_id": user_id},
    ).scalar_one()
    return bool(count)


def _backfill_workspace_integrations() -> None:
    bind = op.get_bind()

    bind.execute(sa.text("UPDATE google_user_connectors SET sync_scope_configured = true"))

    rows = bind.execute(
        sa.text(
            """
            SELECT
              id,
              tenant_id,
              google_account_email,
              google_account_sub,
              access_token_encrypted,
              refresh_token_encrypted,
              token_expires_at,
              scopes,
              gmail_enabled,
              gmail_labels,
              calendar_enabled,
              calendar_ids,
              drive_enabled,
              drive_folder_ids,
              sheets_enabled,
              sheets_targets,
              crm_sheet_spreadsheet_id,
              crm_sheet_tab_name,
              sync_cursor,
              enabled,
              last_sync_at,
              last_items_synced,
              last_error
            FROM workspace_google_integrations
            """
        )
    ).mappings().all()

    for row in rows:
        matched_id = bind.execute(
            sa.text(
                """
                SELECT id
                FROM google_user_connectors
                WHERE tenant_id = :tenant_id
                  AND (
                    (:sub IS NOT NULL AND google_account_sub = :sub)
                    OR (:email IS NOT NULL AND google_account_email = :email)
                  )
                ORDER BY created_at ASC
                LIMIT 1
                """
            ),
            {
                "tenant_id": row["tenant_id"],
                "sub": row["google_account_sub"],
                "email": row["google_account_email"],
            },
        ).scalar_one_or_none()

        if matched_id:
            bind.execute(
                sa.text(
                    """
                    UPDATE google_user_connectors
                    SET
                      drive_enabled = :drive_enabled,
                      drive_folder_ids = :drive_folder_ids,
                      sheets_enabled = :sheets_enabled,
                      sheets_targets = :sheets_targets,
                      crm_sheet_spreadsheet_id = :crm_sheet_spreadsheet_id,
                      crm_sheet_tab_name = :crm_sheet_tab_name,
                      is_workspace_default = true,
                      sync_scope_configured = true
                    WHERE id = :id
                    """
                ),
                {
                    "id": matched_id,
                    "drive_enabled": row["drive_enabled"],
                    "drive_folder_ids": row["drive_folder_ids"],
                    "sheets_enabled": row["sheets_enabled"],
                    "sheets_targets": row["sheets_targets"],
                    "crm_sheet_spreadsheet_id": row["crm_sheet_spreadsheet_id"],
                    "crm_sheet_tab_name": row["crm_sheet_tab_name"],
                },
            )
            continue

        actor_user_id = _tenant_actor_user_id(bind, row["tenant_id"])
        if not actor_user_id:
            continue

        is_primary = not _has_primary_for_user(bind, row["tenant_id"], actor_user_id)
        bind.execute(
            sa.text(
                """
                INSERT INTO google_user_connectors (
                  id,
                  tenant_id,
                  user_id,
                  label,
                  google_account_email,
                  google_account_sub,
                  access_token_encrypted,
                  refresh_token_encrypted,
                  token_expires_at,
                  scopes,
                  gmail_enabled,
                  gmail_labels,
                  calendar_enabled,
                  calendar_ids,
                  drive_enabled,
                  drive_folder_ids,
                  sheets_enabled,
                  sheets_targets,
                  crm_sheet_spreadsheet_id,
                  crm_sheet_tab_name,
                  sync_cursor,
                  enabled,
                  last_sync_at,
                  last_items_synced,
                  last_error,
                  is_primary,
                  is_workspace_default,
                  sync_scope_configured
                ) VALUES (
                  :id,
                  :tenant_id,
                  :user_id,
                  :label,
                  :google_account_email,
                  :google_account_sub,
                  :access_token_encrypted,
                  :refresh_token_encrypted,
                  :token_expires_at,
                  :scopes,
                  :gmail_enabled,
                  :gmail_labels,
                  :calendar_enabled,
                  :calendar_ids,
                  :drive_enabled,
                  :drive_folder_ids,
                  :sheets_enabled,
                  :sheets_targets,
                  :crm_sheet_spreadsheet_id,
                  :crm_sheet_tab_name,
                  :sync_cursor,
                  :enabled,
                  :last_sync_at,
                  :last_items_synced,
                  :last_error,
                  :is_primary,
                  true,
                  true
                )
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "tenant_id": row["tenant_id"],
                "user_id": actor_user_id,
                "label": "Workspace Google",
                "google_account_email": row["google_account_email"],
                "google_account_sub": row["google_account_sub"],
                "access_token_encrypted": row["access_token_encrypted"],
                "refresh_token_encrypted": row["refresh_token_encrypted"],
                "token_expires_at": row["token_expires_at"],
                "scopes": row["scopes"] or [],
                "gmail_enabled": row["gmail_enabled"],
                "gmail_labels": row["gmail_labels"] or ["INBOX", "SENT"],
                "calendar_enabled": row["calendar_enabled"],
                "calendar_ids": row["calendar_ids"] or ["primary"],
                "drive_enabled": row["drive_enabled"],
                "drive_folder_ids": row["drive_folder_ids"] or [],
                "sheets_enabled": row["sheets_enabled"],
                "sheets_targets": row["sheets_targets"] or [],
                "crm_sheet_spreadsheet_id": row["crm_sheet_spreadsheet_id"],
                "crm_sheet_tab_name": row["crm_sheet_tab_name"],
                "sync_cursor": row["sync_cursor"] or {},
                "enabled": row["enabled"],
                "last_sync_at": row["last_sync_at"],
                "last_items_synced": row["last_items_synced"] or 0,
                "last_error": row["last_error"],
                "is_primary": is_primary,
            },
        )

    tenant_ids = bind.execute(sa.text("SELECT DISTINCT tenant_id FROM google_user_connectors")).scalars().all()
    for tenant_id in tenant_ids:
        has_workspace_default = bind.execute(
            sa.text(
                """
                SELECT count(*)
                FROM google_user_connectors
                WHERE tenant_id = :tenant_id AND is_workspace_default = true
                """
            ),
            {"tenant_id": tenant_id},
        ).scalar_one()
        if has_workspace_default:
            continue
        candidate_id = bind.execute(
            sa.text(
                """
                SELECT id
                FROM google_user_connectors
                WHERE tenant_id = :tenant_id
                ORDER BY is_primary DESC, created_at ASC
                LIMIT 1
                """
            ),
            {"tenant_id": tenant_id},
        ).scalar_one_or_none()
        if candidate_id:
            bind.execute(
                sa.text("UPDATE google_user_connectors SET is_workspace_default = true WHERE id = :id"),
                {"id": candidate_id},
            )


def upgrade() -> None:
    _add_columns()
    _backfill_workspace_integrations()
    _drop_column_defaults()

    op.drop_index(op.f("ix_workspace_google_integrations_google_account_sub"), table_name="workspace_google_integrations")
    op.drop_index(op.f("ix_workspace_google_integrations_tenant_id"), table_name="workspace_google_integrations")
    op.drop_table("workspace_google_integrations")


def downgrade() -> None:
    op.create_table(
        "workspace_google_integrations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("google_account_email", sa.String(length=320), nullable=True),
        sa.Column("google_account_sub", sa.String(length=255), nullable=True),
        sa.Column("access_token_encrypted", sa.Text(), nullable=True),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("gmail_enabled", sa.Boolean(), nullable=False),
        sa.Column("gmail_labels", sa.JSON(), nullable=False),
        sa.Column("calendar_enabled", sa.Boolean(), nullable=False),
        sa.Column("calendar_ids", sa.JSON(), nullable=False),
        sa.Column("drive_enabled", sa.Boolean(), nullable=False),
        sa.Column("drive_folder_ids", sa.JSON(), nullable=False),
        sa.Column("sheets_enabled", sa.Boolean(), nullable=False),
        sa.Column("sheets_targets", sa.JSON(), nullable=False),
        sa.Column("crm_sheet_spreadsheet_id", sa.String(length=255), nullable=True),
        sa.Column("crm_sheet_tab_name", sa.String(length=255), nullable=True),
        sa.Column("sync_cursor", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_items_synced", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(length=2000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id"),
    )
    op.create_index(op.f("ix_workspace_google_integrations_tenant_id"), "workspace_google_integrations", ["tenant_id"], unique=False)
    op.create_index(
        op.f("ix_workspace_google_integrations_google_account_sub"),
        "workspace_google_integrations",
        ["google_account_sub"],
        unique=False,
    )

    op.drop_index(op.f("ix_google_user_connectors_is_workspace_default"), table_name="google_user_connectors")

    for column_name in [
        "sync_scope_configured",
        "crm_sheet_tab_name",
        "crm_sheet_spreadsheet_id",
        "meet_enabled",
        "contacts_max_count",
        "contacts_group_ids",
        "contacts_sync_mode",
        "contacts_enabled",
        "sheets_targets",
        "sheets_enabled",
        "drive_file_ids",
        "drive_folder_ids",
        "drive_enabled",
        "calendar_max_events",
        "calendar_days_forward",
        "calendar_days_back",
        "calendar_sync_mode",
        "gmail_query",
        "gmail_max_messages",
        "gmail_last_n_days",
        "gmail_sync_mode",
        "is_workspace_default",
    ]:
        op.drop_column("google_user_connectors", column_name)
