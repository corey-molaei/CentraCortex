from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import MetaData, Table, create_engine, select, text
from sqlalchemy.orm import Session

from app.core.security import decrypt_secret
from app.models.connectors.db_connector import DBConnector
from app.services.connectors.common import finish_sync_run, start_sync_run, upsert_document


def test_connection(connector: DBConnector) -> tuple[bool, str]:
    uri = decrypt_secret(connector.connection_uri_encrypted)
    try:
        engine = create_engine(uri)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, "Connected to database successfully"
    except Exception as exc:
        return False, f"Database connector test failed: {exc}"


def sync_connector(db: Session, connector: DBConnector) -> int:
    run = start_sync_run(db, connector.tenant_id, "db", connector.id)
    uri = decrypt_secret(connector.connection_uri_encrypted)

    try:
        engine = create_engine(uri)
        metadata = MetaData()
        total = 0
        cursor = dict(connector.sync_cursor or {})

        with engine.connect() as conn:
            for table_name in connector.table_allowlist:
                table = Table(table_name, metadata, autoload_with=engine)
                last_pk = cursor.get(table_name)

                stmt = select(table).limit(200)
                if last_pk is not None and "id" in table.c:
                    stmt = stmt.where(table.c.id > last_pk)

                rows = conn.execute(stmt).mappings().all()
                max_pk = last_pk

                for row in rows:
                    source_id = f"{table_name}:{row.get('id', total)}"
                    row_text = "\n".join(f"{k}: {v}" for k, v in row.items())

                    upsert_document(
                        db,
                        tenant_id=connector.tenant_id,
                        source_type="db",
                        source_id=source_id,
                        url=None,
                        title=f"{table_name} row {row.get('id', 'n/a')}",
                        author="db-connector",
                        source_created_at=datetime.now(timezone.utc),
                        source_updated_at=datetime.now(timezone.utc),
                        raw_text=row_text,
                        metadata_json={"table": table_name, "row": dict(row)},
                    )
                    total += 1
                    if row.get("id") is not None:
                        max_pk = row["id"] if max_pk is None else max(max_pk, row["id"])

                cursor[table_name] = max_pk

        connector.sync_cursor = cursor
        connector.last_sync_at = datetime.now(timezone.utc)
        connector.last_items_synced = total
        connector.last_error = None
        db.commit()

        finish_sync_run(db, run, status="success", items_synced=total)
        return total
    except Exception as exc:
        connector.last_error = str(exc)
        db.commit()
        finish_sync_run(db, run, status="failed", items_synced=0, error_message=str(exc))
        raise
