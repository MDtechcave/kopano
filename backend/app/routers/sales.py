"""Sales-team-only tools: see the sales pipeline at a glance."""
from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalogue import Catalogue
from app.database import QUOTE_STATUSES, WORKING_STATUSES, QuoteRequest, User, as_utc, get_db, utc_now
from app.security import require_sales

router = APIRouter(prefix="/api/sales", tags=["sales"])



# ---- the pipeline ----------------------------------------------------------
@router.get("/summary")
def pipeline_summary(
    request: Request, _sales: User = Depends(require_sales), db: Session = Depends(get_db)
):
    """Numbers for the sales dashboard."""
    catalogue: Catalogue = request.app.state.catalogue
    quotes = db.scalars(select(QuoteRequest).order_by(QuoteRequest.created_at)).all()

    by_status = {name: 0 for name in QUOTE_STATUSES}
    sent_value = Decimal("0")  # sent to clients, waiting for an answer (incl. VAT)
    accepted_value = Decimal("0")
    expired_unanswered = 0
    requested: dict[str, int] = {}  # units wanted, across requests still being worked on

    for quote in quotes:
        by_status[quote.status] += 1
        if quote.status == "sent" and quote.total is not None:
            sent_value += quote.total
            expired_unanswered += 1 if quote.is_expired else 0
        if quote.status == "accepted" and quote.total is not None:
            accepted_value += quote.total
        if quote.status in WORKING_STATUSES:
            for line in quote.lines:
                requested[line.product_code] = requested.get(line.product_code, 0) + line.quantity

    answered = by_status["accepted"] + by_status["declined"]

    # Oldest unanswered requests first: these are the ones going cold.
    waiting = [q for q in quotes if q.status in WORKING_STATUSES]
    needs_attention = [
        {
            "id": q.id,
            "reference": q.reference,
            "company_name": q.company_name,
            "status": q.status,
            "hours_waiting": int((utc_now() - as_utc(q.created_at)).total_seconds() // 3600),
            "total_units": q.total_units,
        }
        for q in waiting[:5]
    ]

    # Products people want more of than we hold. Useful before promising anything.
    shortfalls = []
    for code, wanted in requested.items():
        product = catalogue.get(code)
        on_hand = product.quantity if product else 0
        if wanted > on_hand:
            shortfalls.append(
                {
                    "product_code": code,
                    "description": product.description if product else code,
                    "requested": wanted,
                    "on_hand": on_hand,
                    "short_by": wanted - on_hand,
                }
            )
    shortfalls.sort(key=lambda item: -item["short_by"])

    top_requested = sorted(requested.items(), key=lambda item: -item[1])[:5]

    return {
        "by_status": by_status,
        "waiting_for_sales": len(waiting),
        "sent_value": float(sent_value),
        "accepted_value": float(accepted_value),
        "expired_unanswered": expired_unanswered,
        "acceptance_rate": round(by_status["accepted"] / answered, 2) if answered else None,
        "needs_attention": needs_attention,
        "top_requested": [
            {
                "product_code": code,
                "description": catalogue.get(code).description if catalogue.get(code) else code,
                "units": units,
            }
            for code, units in top_requested
        ],
        "stock_shortfalls": shortfalls,
    }

