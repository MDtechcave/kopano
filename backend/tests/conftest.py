"""Shared test setup: every test run gets a brand-new empty database."""
import os
import tempfile

# These must be set BEFORE the app is imported, because config reads them on import.
_temp_dir = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_temp_dir}/test.db"
os.environ["SECRET_KEY"] = "test-secret-that-is-long-enough-for-hs256-signing"

import pytest
from fastapi.testclient import TestClient

from app.database import ROLE_SALES, SessionLocal, User
from app.main import app
from app.security import hash_password


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:  # "with" runs the startup code
        yield test_client


def register(client, email, company="Test Co"):
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "full_name": "Test Person", "company": company},
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture(scope="session")
def client_a(client):
    return register(client, "client.a@example.com", "Company A")


@pytest.fixture(scope="session")
def client_b(client):
    return register(client, "client.b@example.com", "Company B")


@pytest.fixture(scope="session")
def sales(client):
    with SessionLocal() as db:
        db.add(User(email="sales@example.com", password_hash=hash_password("password123"),
                    full_name="Sales Person", role=ROLE_SALES))
        db.commit()
    response = client.post("/api/auth/login", json={"email": "sales@example.com", "password": "password123"})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture(scope="session")
def admin(client):
    with SessionLocal() as db:
        db.add(User(email="admin@example.com", password_hash=hash_password("password123"),
                    full_name="Admin Person", role=ROLE_SALES, is_admin=True))
        db.commit()
    response = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "password123"})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def quote_body(**overrides):
    body = {
        "company_name": "Test Co",
        "contact_name": "Test Person",
        "email": "test@example.com",
        "phone": "0211234567",
        "delivery_city": "Cape Town",
        "popia_consent": True,
        "lines": [{"product_code": "SPL540W", "quantity": 10}],
    }
    body.update(overrides)
    return body


def sign_in(client, email, password="password123"):
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def price_body(lines, **overrides):
    """A pricing-screen body: lines is a list of (code, unit_price, discount_percent)."""
    from datetime import timedelta

    from app.pricing import today_in_south_africa

    body = {
        "lines": [{"product_code": c, "unit_price": p, "discount_percent": d} for c, p, d in lines],
        "validity_date": (today_in_south_africa() + timedelta(days=14)).isoformat(),
        "quotation_notes": "Delivery to be confirmed with the order.",
        "sales_notes": "Margin 12%",
    }
    body.update(overrides)
    return body
