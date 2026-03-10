#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.connectors.google_user_connector import GoogleUserConnector  # noqa: E402


def _normalized_email(value: str | None) -> str:
    return (value or "").strip().lower()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Cleanup stale duplicate Google connector rows where the same tenant/user/email has "
            "one connected row and one or more unconnected rows."
        )
    )
    parser.add_argument("--apply", action="store_true", help="Apply deletes. Default mode is dry-run.")
    args = parser.parse_args()

    with SessionLocal() as db:
        accounts = db.execute(
            select(GoogleUserConnector).where(
                GoogleUserConnector.google_account_email.is_not(None),
            )
        ).scalars().all()

        groups: dict[tuple[str, str, str], list[GoogleUserConnector]] = defaultdict(list)
        for row in accounts:
            email = _normalized_email(row.google_account_email)
            if not email:
                continue
            groups[(row.tenant_id, row.user_id, email)].append(row)

        total_deleted = 0
        for (tenant_id, user_id, email), rows in groups.items():
            if len(rows) < 2:
                continue
            connected = [r for r in rows if r.google_account_sub or r.access_token_encrypted]
            if len(connected) != 1:
                continue
            keep = connected[0]
            to_delete = [r for r in rows if r.id != keep.id and not (r.google_account_sub or r.access_token_encrypted)]
            if not to_delete:
                continue

            print(
                f"tenant={tenant_id} user={user_id} email={email} keep={keep.id} "
                f"delete={[row.id for row in to_delete]}"
            )
            if args.apply:
                for row in to_delete:
                    db.delete(row)
                total_deleted += len(to_delete)

        if args.apply:
            db.commit()
            print(f"Deleted duplicate rows: {total_deleted}")
        else:
            print("Dry-run complete. Re-run with --apply to delete duplicates.")


if __name__ == "__main__":
    main()
