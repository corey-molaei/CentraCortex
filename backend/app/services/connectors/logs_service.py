from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.connectors.logs_connector import LogsConnector
from app.services.connectors.common import finish_sync_run, start_sync_run, upsert_document


def test_connection(connector: LogsConnector) -> tuple[bool, str]:
    path = Path(connector.folder_path)
    if not path.exists():
        return False, f"Folder does not exist: {path}"
    if not path.is_dir():
        return False, f"Path is not a directory: {path}"
    return True, "Logs folder is accessible"


def _parse_line(parser_type: str, line: str) -> tuple[str, dict]:
    stripped = line.strip()
    if parser_type == "jsonl":
        try:
            parsed = json.loads(stripped)
            return json.dumps(parsed), parsed
        except json.JSONDecodeError:
            return stripped, {"raw": stripped, "parse_error": True}
    return stripped, {"raw": stripped}


def sync_connector(db: Session, connector: LogsConnector) -> int:
    run = start_sync_run(db, connector.tenant_id, "logs", connector.id)

    try:
        folder = Path(connector.folder_path)
        cursor = dict(connector.sync_cursor or {})
        total = 0

        for file_path in folder.glob(connector.file_glob):
            if not file_path.is_file():
                continue

            last_offset = int(cursor.get(str(file_path), 0))
            with file_path.open("r", encoding="utf-8", errors="ignore") as f:
                f.seek(last_offset)
                while True:
                    pos = f.tell()
                    line = f.readline()
                    if not line:
                        cursor[str(file_path)] = pos
                        break

                    text, metadata = _parse_line(connector.parser_type, line)
                    source_id = f"{file_path.name}:{pos}"

                    upsert_document(
                        db,
                        tenant_id=connector.tenant_id,
                        source_type="logs",
                        source_id=source_id,
                        url=None,
                        title=f"Log line {file_path.name}:{pos}",
                        author="logs-connector",
                        source_created_at=datetime.now(timezone.utc),
                        source_updated_at=datetime.now(timezone.utc),
                        raw_text=text,
                        metadata_json={"file": str(file_path), "offset": pos, **metadata},
                    )
                    total += 1

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
