#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.db.session import SessionLocal
from app.models.tenant import Tenant


def main() -> None:
    parser = argparse.ArgumentParser(description="Create tenant")
    parser.add_argument("--name", required=True)
    parser.add_argument("--slug", required=True)
    args = parser.parse_args()

    with SessionLocal() as db:
        existing = db.query(Tenant).filter(Tenant.slug == args.slug).first()
        if existing:
            print(f"Tenant with slug '{args.slug}' already exists: {existing.id}")
            return

        tenant = Tenant(name=args.name, slug=args.slug)
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
        print(f"Created tenant {tenant.name} ({tenant.id})")


if __name__ == "__main__":
    main()
