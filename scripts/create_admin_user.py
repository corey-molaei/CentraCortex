#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.security import get_password_hash
from app.db.session import SessionLocal
from app.models.tenant import Tenant
from app.models.tenant_membership import TenantMembership
from app.models.user import User


def main() -> None:
    parser = argparse.ArgumentParser(description="Create admin user and assign tenant")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--tenant-slug", required=True)
    parser.add_argument("--full-name", default="Admin User")
    args = parser.parse_args()

    with SessionLocal() as db:
        tenant = db.query(Tenant).filter(Tenant.slug == args.tenant_slug).first()
        if not tenant:
            raise SystemExit(f"Tenant '{args.tenant_slug}' not found")

        user = db.query(User).filter(User.email == args.email).first()
        if not user:
            user = User(email=args.email, full_name=args.full_name, hashed_password=get_password_hash(args.password))
            db.add(user)
            db.flush()

        membership = (
            db.query(TenantMembership)
            .filter(TenantMembership.user_id == user.id, TenantMembership.tenant_id == tenant.id)
            .first()
        )
        if not membership:
            membership = TenantMembership(user_id=user.id, tenant_id=tenant.id, role="Owner", is_default=True)
            db.add(membership)

        db.commit()
        print(f"Admin user ready: {user.email} -> tenant {tenant.slug}")


if __name__ == "__main__":
    main()
