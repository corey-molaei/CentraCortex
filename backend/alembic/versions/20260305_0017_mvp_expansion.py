"""mvp expansion core tables

Revision ID: 20260305_0017
Revises: 20260303_0016
Create Date: 2026-03-05
"""

from alembic import op
import sqlalchemy as sa


revision = "20260305_0017"
down_revision = "20260303_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_settings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("business_name", sa.String(length=255), nullable=True),
        sa.Column("timezone", sa.String(length=128), nullable=False),
        sa.Column("default_email_signature", sa.String(length=2000), nullable=True),
        sa.Column("fallback_contact", sa.String(length=255), nullable=True),
        sa.Column("escalation_email", sa.String(length=320), nullable=True),
        sa.Column("working_hours_json", sa.JSON(), nullable=False),
        sa.Column("allowed_actions_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id"),
    )
    op.create_index(op.f("ix_workspace_settings_tenant_id"), "workspace_settings", ["tenant_id"], unique=False)

    op.create_table(
        "user_identities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("provider_subject", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "provider_subject", name="uq_user_identity_provider_subject"),
    )
    op.create_index(op.f("ix_user_identities_user_id"), "user_identities", ["user_id"], unique=False)
    op.create_index(op.f("ix_user_identities_provider"), "user_identities", ["provider"], unique=False)
    op.create_index(op.f("ix_user_identities_provider_subject"), "user_identities", ["provider_subject"], unique=False)

    op.create_table(
        "auth_oauth_states",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("state_token", sa.String(length=128), nullable=False),
        sa.Column("redirect_uri", sa.String(length=1024), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("state_token"),
    )
    op.create_index(op.f("ix_auth_oauth_states_provider"), "auth_oauth_states", ["provider"], unique=False)
    op.create_index(op.f("ix_auth_oauth_states_state_token"), "auth_oauth_states", ["state_token"], unique=False)

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
    op.create_index(op.f("ix_workspace_google_integrations_google_account_sub"), "workspace_google_integrations", ["google_account_sub"], unique=False)

    for table_name in [
        "channel_telegram_connectors",
        "channel_whatsapp_connectors",
        "channel_facebook_connectors",
    ]:
        op.create_table(
            table_name,
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("tenant_id", sa.String(length=36), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("config_json", sa.JSON(), nullable=False),
            sa.Column("last_error", sa.String(length=2000), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tenant_id"),
        )
        op.create_index(op.f(f"ix_{table_name}_tenant_id"), table_name, ["tenant_id"], unique=False)

    op.add_column("channel_telegram_connectors", sa.Column("bot_token_encrypted", sa.String(length=4096), nullable=True))
    op.add_column("channel_telegram_connectors", sa.Column("webhook_secret", sa.String(length=255), nullable=True))

    op.add_column("channel_whatsapp_connectors", sa.Column("access_token_encrypted", sa.String(length=4096), nullable=True))
    op.add_column("channel_whatsapp_connectors", sa.Column("phone_number_id", sa.String(length=255), nullable=True))
    op.add_column("channel_whatsapp_connectors", sa.Column("business_account_id", sa.String(length=255), nullable=True))
    op.add_column("channel_whatsapp_connectors", sa.Column("verify_token", sa.String(length=255), nullable=True))

    op.add_column("channel_facebook_connectors", sa.Column("page_access_token_encrypted", sa.String(length=4096), nullable=True))
    op.add_column("channel_facebook_connectors", sa.Column("page_id", sa.String(length=255), nullable=True))
    op.add_column("channel_facebook_connectors", sa.Column("app_id", sa.String(length=255), nullable=True))
    op.add_column("channel_facebook_connectors", sa.Column("app_secret_encrypted", sa.String(length=4096), nullable=True))
    op.add_column("channel_facebook_connectors", sa.Column("verify_token", sa.String(length=255), nullable=True))

    op.create_table(
        "workspace_contacts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("channel", sa.String(length=50), nullable=False),
        sa.Column("external_user_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=64), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "channel", "external_user_id", name="uq_workspace_contact_channel_external"),
    )
    op.create_index(op.f("ix_workspace_contacts_tenant_id"), "workspace_contacts", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_workspace_contacts_channel"), "workspace_contacts", ["channel"], unique=False)
    op.create_index(op.f("ix_workspace_contacts_external_user_id"), "workspace_contacts", ["external_user_id"], unique=False)

    op.create_table(
        "conversation_contact_links",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("contact_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["chat_conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contact_id"], ["workspace_contacts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id", "contact_id", name="uq_conversation_contact"),
    )
    op.create_index(op.f("ix_conversation_contact_links_tenant_id"), "conversation_contact_links", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_conversation_contact_links_conversation_id"), "conversation_contact_links", ["conversation_id"], unique=False)
    op.create_index(op.f("ix_conversation_contact_links_contact_id"), "conversation_contact_links", ["contact_id"], unique=False)

    op.create_table(
        "automation_recipes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=False),
        sa.Column("default_config_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_index(op.f("ix_automation_recipes_key"), "automation_recipes", ["key"], unique=False)

    op.create_table(
        "workspace_recipe_states",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("recipe_id", sa.String(length=36), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recipe_id"], ["automation_recipes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "recipe_id", name="uq_workspace_recipe"),
    )
    op.create_index(op.f("ix_workspace_recipe_states_tenant_id"), "workspace_recipe_states", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_workspace_recipe_states_recipe_id"), "workspace_recipe_states", ["recipe_id"], unique=False)

    op.create_table(
        "action_undo_logs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("conversation_id", sa.String(length=36), nullable=True),
        sa.Column("action_type", sa.String(length=100), nullable=False),
        sa.Column("resource_type", sa.String(length=100), nullable=False),
        sa.Column("resource_id", sa.String(length=255), nullable=True),
        sa.Column("undo_payload_json", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("undone", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["conversation_id"], ["chat_conversations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_action_undo_logs_tenant_id"), "action_undo_logs", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_action_undo_logs_user_id"), "action_undo_logs", ["user_id"], unique=False)
    op.create_index(op.f("ix_action_undo_logs_conversation_id"), "action_undo_logs", ["conversation_id"], unique=False)
    op.create_index(op.f("ix_action_undo_logs_action_type"), "action_undo_logs", ["action_type"], unique=False)
    op.create_index(op.f("ix_action_undo_logs_resource_type"), "action_undo_logs", ["resource_type"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_action_undo_logs_resource_type"), table_name="action_undo_logs")
    op.drop_index(op.f("ix_action_undo_logs_action_type"), table_name="action_undo_logs")
    op.drop_index(op.f("ix_action_undo_logs_conversation_id"), table_name="action_undo_logs")
    op.drop_index(op.f("ix_action_undo_logs_user_id"), table_name="action_undo_logs")
    op.drop_index(op.f("ix_action_undo_logs_tenant_id"), table_name="action_undo_logs")
    op.drop_table("action_undo_logs")

    op.drop_index(op.f("ix_workspace_recipe_states_recipe_id"), table_name="workspace_recipe_states")
    op.drop_index(op.f("ix_workspace_recipe_states_tenant_id"), table_name="workspace_recipe_states")
    op.drop_table("workspace_recipe_states")

    op.drop_index(op.f("ix_automation_recipes_key"), table_name="automation_recipes")
    op.drop_table("automation_recipes")

    op.drop_index(op.f("ix_conversation_contact_links_contact_id"), table_name="conversation_contact_links")
    op.drop_index(op.f("ix_conversation_contact_links_conversation_id"), table_name="conversation_contact_links")
    op.drop_index(op.f("ix_conversation_contact_links_tenant_id"), table_name="conversation_contact_links")
    op.drop_table("conversation_contact_links")

    op.drop_index(op.f("ix_workspace_contacts_external_user_id"), table_name="workspace_contacts")
    op.drop_index(op.f("ix_workspace_contacts_channel"), table_name="workspace_contacts")
    op.drop_index(op.f("ix_workspace_contacts_tenant_id"), table_name="workspace_contacts")
    op.drop_table("workspace_contacts")

    for table_name in ["channel_facebook_connectors", "channel_whatsapp_connectors", "channel_telegram_connectors"]:
        op.drop_index(op.f(f"ix_{table_name}_tenant_id"), table_name=table_name)
        op.drop_table(table_name)

    op.drop_index(op.f("ix_workspace_google_integrations_google_account_sub"), table_name="workspace_google_integrations")
    op.drop_index(op.f("ix_workspace_google_integrations_tenant_id"), table_name="workspace_google_integrations")
    op.drop_table("workspace_google_integrations")

    op.drop_index(op.f("ix_auth_oauth_states_state_token"), table_name="auth_oauth_states")
    op.drop_index(op.f("ix_auth_oauth_states_provider"), table_name="auth_oauth_states")
    op.drop_table("auth_oauth_states")

    op.drop_index(op.f("ix_user_identities_provider_subject"), table_name="user_identities")
    op.drop_index(op.f("ix_user_identities_provider"), table_name="user_identities")
    op.drop_index(op.f("ix_user_identities_user_id"), table_name="user_identities")
    op.drop_table("user_identities")

    op.drop_index(op.f("ix_workspace_settings_tenant_id"), table_name="workspace_settings")
    op.drop_table("workspace_settings")
