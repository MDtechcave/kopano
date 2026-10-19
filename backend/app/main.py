
"""The FastAPI app. Run it with: uvicorn app.main:app --reload"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app import config
from app.catalogue import Catalogue, load_products
from app.database import (
    ROLE_SALES,
    SessionLocal,
    User,
    create_tables,
)
from app.security import hash_password
from app.routers import auth, portal, products, quotes, sales, team


def reset_admin_from_environment():
    """Temporarily reset an administrator using Render environment variables."""
    email = os.getenv("ADMIN_RESET_EMAIL", "").strip().lower()
    password = os.getenv("ADMIN_RESET_PASSWORD", "")
    full_name = os.getenv("ADMIN_RESET_NAME", "").strip()

    # Do nothing unless all three reset variables are configured.
    if not email or not password or not full_name:
        return

    if len(password) < 12:
        raise RuntimeError(
            "Admin reset password must be at least 12 characters."
        )

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))

        if user:
            # Update the existing account.
            user.password_hash = hash_password(password)
            user.role = ROLE_SALES
            user.is_admin = True
            user.is_active = True
            user.company_id = None
            user.must_change_password = False
        else:
            # Create the account only if the supplied email does not exist.
            user = User(
                email=email,
                full_name=full_name,
                password_hash=hash_password(password),
                role=ROLE_SALES,
                is_admin=True,
                is_active=True,
            )
            db.add(user)

        db.commit()

    print("Admin password reset completed.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs once when the server starts."""
    create_tables()

    # TEMPORARY: remove this call after restoring admin access.
    reset_admin_from_environment()

    product_list, report = load_products(config.CSV_PATH)
    app.state.catalogue = Catalogue(product_list, report)

    yield


app = FastAPI(
    title=f"{config.BUSINESS_NAME} API",
    description=(
        "B2B catalogue and quote requests built from "
        "the supplied inventory report."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Auth-Error"],
)

app.include_router(products.router)
app.include_router(auth.router)
app.include_router(quotes.router)
app.include_router(portal.router)
app.include_router(sales.router)
app.include_router(team.router)


@app.get("/api/health")
def health():
    """Hosting services ping this to check the server is alive."""
    return {"status": "ok"}


@app.get("/api/config")
def public_config():
    """Settings the website needs."""
    return {
        "business_name": config.BUSINESS_NAME,
        "vat_rate": float(config.VAT_RATE),
        "stock_as_at": config.STOCK_AS_AT,
    }
