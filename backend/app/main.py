
"""The FastAPI app. Run it with: uvicorn app.main:app --reload"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import config
from app.catalogue import Catalogue, load_products
from app.database import create_tables
from app.routers import auth, portal, products, quotes, sales, team


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs once when the server starts."""
    create_tables()
    product_list, report = load_products(config.CSV_PATH)
    app.state.catalogue = Catalogue(product_list, report)
    yield


app = FastAPI(
    title=f"{config.BUSINESS_NAME} API",
    description="B2B catalogue and quote requests built from the supplied inventory report.",
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
    """Settings the website needs, so the business name and VAT rate live in one place."""
    return {
        "business_name": config.BUSINESS_NAME,
        "vat_rate": float(config.VAT_RATE),
        "stock_as_at": config.STOCK_AS_AT,
    }
