"""Public catalogue endpoints. Anyone can browse; signed-in users also see exact quantities."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app import config
from app.catalogue import Catalogue, Product
from app.database import User
from app.security import get_optional_user

router = APIRouter(prefix="/api", tags=["catalogue"])


def get_catalogue(request: Request) -> Catalogue:
    return request.app.state.catalogue


def prepare_for_viewer(product: Product, user: User | None) -> Product:
    """Visitors who are not signed in only see the stock band, not the exact number."""
    if user is not None:
        return product
    return product.model_copy(update={"quantity": None})


@router.get("/products")
def list_products(
    q: str = "",
    category: str | None = None,
    brand: str | None = None,
    stock_band: str | None = None,
    sort: str = Query("code", pattern="^(code|name|stock_desc|stock_asc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    catalogue: Catalogue = Depends(get_catalogue),
    user: User | None = Depends(get_optional_user),
):
    matches = catalogue.search(q, category, brand, stock_band, sort)

    start = (page - 1) * page_size
    page_items = matches[start : start + page_size]

    return {
        "total": len(matches),
        "page": page,
        "page_size": page_size,
        "items": [prepare_for_viewer(p, user) for p in page_items],
    }


@router.get("/products/{code:path}")
def get_product(
    code: str,
    catalogue: Catalogue = Depends(get_catalogue),
    user: User | None = Depends(get_optional_user),
):
    # ":path" because some real codes contain a slash, e.g. PB8IN/4OUT.
    product = catalogue.get(code)
    if product is None:
        raise HTTPException(404, "We could not find that product.")
    return prepare_for_viewer(product, user)


@router.get("/filters")
def get_filters(catalogue: Catalogue = Depends(get_catalogue)):
    """Everything the filter sidebar needs, with counts."""
    return {
        **catalogue.facets(),
        "total_products": len(catalogue.products),
        "stock_as_at": config.STOCK_AS_AT,
    }
