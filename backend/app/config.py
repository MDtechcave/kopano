"""Settings, read from environment variables so nothing secret lives in the code."""
import os
import secrets
from decimal import Decimal
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# The supplied inventory report (the only source of product information).
CSV_PATH = Path(os.getenv("INVENTORY_CSV", BASE_DIR / "data" / "inventory.csv"))

# SQLite is fine for local work. On Render/Railway, set DATABASE_URL to a hosted database.
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'quotes.db'}")

# Used to sign login tokens. If it is not set we make a random one, which is safe
# but logs everyone out whenever the server restarts. Set SECRET_KEY in production.
SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_urlsafe(32)
TOKEN_LIFETIME_HOURS = int(os.getenv("TOKEN_LIFETIME_HOURS", "12"))

# Which websites may call this API from a browser (comma separated).
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",")
    if origin.strip()
]

# The inventory report has no date on it. If the business tells us the date,
# set STOCK_AS_AT (e.g. "2026-10-16") and the site will show it. Until then we say nothing.
STOCK_AS_AT = os.getenv("STOCK_AS_AT") or None

# The trading name shown on the site and on quotations. One setting, so renaming the
# business later is a single change (the frontend reads it from GET /api/config).
BUSINESS_NAME = os.getenv("BUSINESS_NAME", "Kopano Industrial Supply")

# South African VAT. Applied to the discounted subtotal of a quotation.
VAT_RATE = Decimal(os.getenv("VAT_RATE", "0.15"))

# Validity dates are judged by the calendar in South Africa, not the server's.
BUSINESS_TIMEZONE = "Africa/Johannesburg"
