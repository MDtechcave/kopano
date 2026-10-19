"""Create the FIRST administrator. Every salesperson after that is added by an administrator
from inside the site (POST /api/team). Also useful for recovering admin access.

Usage:   python -m app.create_admin_user admin@example.com "Full Name"
The password is asked for in the terminal (or read from ADMIN_PASSWORD).
"""
import getpass
import os
import sys

from sqlalchemy import select

from app.database import ROLE_SALES, SessionLocal, User, create_tables
from app.security import hash_password


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit('Usage: python -m app.create_admin_user email "Full Name"')

    email, full_name = sys.argv[1].strip().lower(), sys.argv[2]
    password = os.getenv("ADMIN_PASSWORD") or getpass.getpass("Password (min 8 characters): ")
    if len(password) < 8:
        sys.exit("Password must be at least 8 characters.")

    create_tables()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        if user:
            # Existing account: make it an administrator and reset the password.
            user.role, user.is_admin, user.is_active = ROLE_SALES, True, True
            user.company_id = None
            user.password_hash = hash_password(password)
            user.must_change_password = False
            print(f"Updated {email} to an administrator.")
        else:
            db.add(User(email=email, password_hash=hash_password(password), full_name=full_name,
                        role=ROLE_SALES, is_admin=True))
            print(f"Created administrator account for {email}.")
        db.commit()


if __name__ == "__main__":
    main()
