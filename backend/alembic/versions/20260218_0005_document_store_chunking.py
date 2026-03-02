"""document store and chunking

Revision ID: 20260218_0005
Revises: 20260217_0004
Create Date: 2026-02-18
"""

from alembic import op
import sqlalchemy as sa


revision = "20260218_0005"
down_revision = "20260217_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("tags_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
    op.add_column("documents", sa.Column("raw_object_key", sa.String(length=512), nullable=True))
    op.add_column("documents", sa.Column("current_chunk_version", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("documents", sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("documents", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))

    op.create_index("ix_documents_deleted_at", "documents", ["deleted_at"])
    op.create_index("ix_documents_acl_policy_id", "documents", ["acl_policy_id"])
    op.create_index("ix_documents_source_type", "documents", ["source_type"])
    op.create_index("ix_documents_created_at", "documents", ["created_at"])
    op.create_index("ix_documents_updated_at", "documents", ["updated_at"])
    op.create_unique_constraint("uq_documents_tenant_source", "documents", ["tenant_id", "source_type", "source_id"])

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("embedding_model", sa.String(length=100), nullable=False, server_default="hash-v1"),
        sa.Column("embedding_vector", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("acl_policy_id", sa.String(length=36), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["acl_policy_id"], ["acl_policies.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "chunk_version", "chunk_index", name="uq_document_chunk_version_index"),
    )
    op.create_index("ix_document_chunks_tenant_id", "document_chunks", ["tenant_id"])
    op.create_index("ix_document_chunks_document_id", "document_chunks", ["document_id"])
    op.create_index("ix_document_chunks_acl_policy_id", "document_chunks", ["acl_policy_id"])
    op.create_index("ix_document_chunks_chunk_version", "document_chunks", ["chunk_version"])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX ix_document_chunks_content_bm25 ON document_chunks USING GIN (to_tsvector('english', content))"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_document_chunks_content_bm25")

    op.drop_index("ix_document_chunks_chunk_version", table_name="document_chunks")
    op.drop_index("ix_document_chunks_acl_policy_id", table_name="document_chunks")
    op.drop_index("ix_document_chunks_document_id", table_name="document_chunks")
    op.drop_index("ix_document_chunks_tenant_id", table_name="document_chunks")
    op.drop_table("document_chunks")

    op.drop_constraint("uq_documents_tenant_source", "documents", type_="unique")
    op.drop_index("ix_documents_updated_at", table_name="documents")
    op.drop_index("ix_documents_created_at", table_name="documents")
    op.drop_index("ix_documents_source_type", table_name="documents")
    op.drop_index("ix_documents_acl_policy_id", table_name="documents")
    op.drop_index("ix_documents_deleted_at", table_name="documents")

    op.drop_column("documents", "deleted_at")
    op.drop_column("documents", "indexed_at")
    op.drop_column("documents", "current_chunk_version")
    op.drop_column("documents", "raw_object_key")
    op.drop_column("documents", "tags_json")
