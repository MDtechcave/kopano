"""The signed-in client's own pages: an overview, and the quotations they have received.

Everything here is scoped to the client's COMPANY, in the database query itself.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import PRICE_VISIBLE_STATUSES, WORKING_STATUSES, QuoteEvent, QuoteRequest, User, get_db
from app.routers.quotes import client_view
from app.schemas import QuoteOut
from app.security import require_client

router = APIRouter(prefix="/api/portal", tags=["client portal"])


@router.get("/overview")
def overview(user: User = Depends(require_client), db: Session = Depends(get_db)):
    quotes = db.scalars(select(QuoteRequest).where(QuoteRequest.company_id == user.company_id)).all()

    sent = [q for q in quotes if q.status == "sent"]
    counts = {
        "total_requests": len(quotes),
        "awaiting_quotation": sum(1 for q in quotes if q.status in WORKING_STATUSES),
        "awaiting_your_decision": sum(1 for q in sent if not q.is_expired),
        "expired": sum(1 for q in sent if q.is_expired),
        "accepted": sum(1 for q in quotes if q.status == "accepted"),
        "declined": sum(1 for q in quotes if q.status == "declined"),
    }

    # Recent activity: only steps the client is allowed to know about (no "draft saved").
    events = db.execute(
        select(QuoteEvent, QuoteRequest)
        .join(QuoteRequest, QuoteEvent.quote_id == QuoteRequest.id)
        .where(QuoteRequest.company_id == user.company_id, QuoteEvent.client_visible.is_(True))
        .order_by(QuoteEvent.created_at.desc(), QuoteEvent.id.desc())
        .limit(8)
    ).all()
    recent_activity = [
        {
            "quote_id": quote.id,
            "reference": quote.reference,
            "action": event.action,
            "detail": event.detail,
            "actor_name": event.actor_name,
            "created_at": event.created_at,
        }
        for event, quote in events
    ]

    return {"company": user.company, "counts": counts, "recent_activity": recent_activity}


@router.get("/received-quotes", response_model=list[QuoteOut])
def received_quotes(user: User = Depends(require_client), db: Session = Depends(get_db)):
    """Quotations sales have sent to this company (including ones already answered)."""
    query = (
        select(QuoteRequest)
        .where(QuoteRequest.company_id == user.company_id, QuoteRequest.status.in_(PRICE_VISIBLE_STATUSES))
        .order_by(QuoteRequest.sent_at.desc(), QuoteRequest.id.desc())
    )
    return [client_view(quote) for quote in db.scalars(query).all()]
