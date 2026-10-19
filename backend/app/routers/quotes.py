"""Quote requests (RFQs) and the quotations sales send back.

Who can do what:
  - a CLIENT can submit a request, see their own COMPANY's requests, and accept
    or decline a quotation once it has been sent
  - the SALES team cannot submit requests. They work them: open, price (draft),
    send, and watch the client's answer

A request moves through these steps:

    new  ->  in_review  ->  draft  ->  sent  ->  accepted
                                          \\->  declined

    new        the client has just submitted it
    in_review  a salesperson has opened it
    draft      prices are saved but only sales can see them
    sent       the client can now see prices, VAT and the total
    accepted / declined   the client's answer (final)
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from app import pricing
from app.catalogue import Catalogue
from app.database import (
    PRICE_VISIBLE_STATUSES,
    QUOTE_STATUSES,
    ROLE_SALES,
    QuoteLine,
    QuoteRequest,
    User,
    get_db,
    record_event,
    utc_now,
)
from app.schemas import DeclineQuote, EventOut, QuoteCreate, QuoteDraft, QuoteOut, SalesQuoteOut, WithdrawQuote
from app.security import get_current_user, require_client, require_sales

router = APIRouter(prefix="/api/quotes", tags=["quotes"])

# Statuses in which sales may still change the prices.
EDITABLE_STATUSES = {"new", "in_review", "draft"}


# ---- helpers ---------------------------------------------------------------
def merge_duplicate_lines(lines) -> dict[str, int]:
    """If the same product appears twice, add the quantities together."""
    totals: dict[str, int] = {}
    for line in lines:
        totals[line.product_code] = totals.get(line.product_code, 0) + line.quantity
    return totals


def client_view(quote: QuoteRequest) -> QuoteOut:
    """The client's version of a quote.

    Prices, discounts, VAT, totals, the validity date and our notes are removed until
    the quotation has been SENT. A draft therefore looks, to the client, exactly like
    a request that nobody has priced yet.
    """
    view = QuoteOut.model_validate(quote)
    view.history = [EventOut.model_validate(e) for e in quote.history if e.client_visible]

    if quote.status in PRICE_VISIBLE_STATUSES:
        view.is_expired = quote.is_expired
        return view

    view.status = "submitted"  # new / in_review / draft all read the same to a client
    view.subtotal = view.vat_rate = view.vat_amount = view.total = None
    view.validity_date = view.quotation_notes = view.sent_at = None
    view.revision = 0
    view.is_expired = False
    for line in view.lines:
        line.unit_price = line.discount_percent = line.line_total = None
    return view


def sales_view(quote: QuoteRequest, catalogue: Catalogue) -> SalesQuoteOut:
    """The sales team's version: everything, plus stock checks for each line."""
    view = SalesQuoteOut.model_validate(quote)
    view.is_expired = quote.is_expired
    for line in view.lines:
        product = catalogue.get(line.product_code)
        if product is not None:
            line.stock_on_hand = product.quantity
            line.shortfall = max(0, line.quantity - (product.quantity or 0))
    view.has_stock_shortfall = any(line.shortfall > 0 for line in view.lines)
    return view


def find_quote_or_404(db: Session, quote_id: int, user: User) -> QuoteRequest:
    quote = db.get(QuoteRequest, quote_id)
    # A client asking for another company's quote gets "not found", the same as a
    # quote that does not exist, so they cannot even tell it is there.
    if quote is None or (user.role != ROLE_SALES and quote.company_id != user.company_id):
        raise HTTPException(404, "Quote request not found.")
    return quote


def reference_to_id(text: str) -> int | None:
    """'RFQ-00012', 'rfq 12' and '12' all mean request number 12."""
    digits = text.lower().replace("rfq", "").strip(" -")
    return int(digits) if digits.isdigit() else None


# ---- clients: submit and read ---------------------------------------------
@router.post("", response_model=QuoteOut, status_code=status.HTTP_201_CREATED)
def create_quote(
    data: QuoteCreate,
    request: Request,
    user: User = Depends(require_client),
    db: Session = Depends(get_db),
):
    catalogue: Catalogue = request.app.state.catalogue
    quote = QuoteRequest(
        user_id=user.id,
        company_id=user.company_id,
        company_name=data.company_name,
        contact_name=data.contact_name,
        email=data.email,
        phone=data.phone,
        delivery_city=data.delivery_city,
        vat_number=data.vat_number or None,
        notes=data.notes or None,
        popia_consent=data.popia_consent,
        status="new",
    )

    for code, quantity in merge_duplicate_lines(data.lines).items():
        product = catalogue.get(code)
        if product is None:
            raise HTTPException(422, f"Unknown product code: {code}")
        # Keep a copy of the description so the quote still reads correctly later.
        quote.lines.append(QuoteLine(product_code=code, description=product.description, quantity=quantity))

    record_event(quote, user, "submitted", f"{len(quote.lines)} product(s), {quote.total_units} units")
    db.add(quote)
    db.commit()
    db.refresh(quote)
    return client_view(quote)


@router.get("")
def list_quotes(
    request: Request,
    status_filter: str | None = Query(None, alias="status"),
    q: str | None = Query(None, max_length=100, description="Search reference, company, contact or product code"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Sales: every request (searchable). Clients: their own company's requests."""
    query = select(QuoteRequest).order_by(QuoteRequest.created_at.desc(), QuoteRequest.id.desc())

    if user.role == ROLE_SALES:
        if status_filter:
            if status_filter not in QUOTE_STATUSES:
                raise HTTPException(422, f"Status must be one of: {', '.join(QUOTE_STATUSES)}")
            query = query.where(QuoteRequest.status == status_filter)
        if q and q.strip():
            text = q.strip()
            matches = [
                QuoteRequest.company_name.ilike(f"%{text}%"),
                QuoteRequest.contact_name.ilike(f"%{text}%"),
                QuoteRequest.email.ilike(f"%{text}%"),
                exists().where(QuoteLine.quote_id == QuoteRequest.id, QuoteLine.product_code.ilike(f"%{text}%")),
            ]
            number = reference_to_id(text)
            if number is not None:
                matches.append(QuoteRequest.id == number)
            query = query.where(or_(*matches))
        catalogue: Catalogue = request.app.state.catalogue
        return [sales_view(quote, catalogue) for quote in db.scalars(query).all()]

    # Clients: filter by company in the database query, so other companies'
    # requests are never even loaded.
    query = query.where(QuoteRequest.company_id == user.company_id)
    return [client_view(quote) for quote in db.scalars(query).all()]


@router.get("/{quote_id}")
def get_quote(
    quote_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    quote = find_quote_or_404(db, quote_id, user)
    if user.role == ROLE_SALES:
        return sales_view(quote, request.app.state.catalogue)
    return client_view(quote)


# ---- sales: open, price, send ---------------------------------------------
@router.post("/{quote_id}/start-review", response_model=SalesQuoteOut)
def start_review(
    quote_id: int,
    request: Request,
    sales: User = Depends(require_sales),
    db: Session = Depends(get_db),
):
    """A salesperson opens a new request. (Does nothing if it has already moved on.)"""
    quote = find_quote_or_404(db, quote_id, sales)
    if quote.status == "new":
        quote.status = "in_review"
        record_event(quote, sales, "review_started", client_visible=False)
        db.commit()
        db.refresh(quote)
    return sales_view(quote, request.app.state.catalogue)


@router.put("/{quote_id}/draft", response_model=SalesQuoteOut)
def save_draft(
    quote_id: int,
    data: QuoteDraft,
    request: Request,
    sales: User = Depends(require_sales),
    db: Session = Depends(get_db),
):
    """Save the pricing screen as it stands. Prices may be incomplete. The client sees nothing."""
    quote = find_quote_or_404(db, quote_id, sales)
    if quote.status not in EDITABLE_STATUSES:
        raise HTTPException(409, "This quotation has already been sent, so it can no longer be edited.")

    sent_codes = [line.product_code for line in data.lines]
    requested_codes = {line.product_code for line in quote.lines}
    if len(sent_codes) != len(set(sent_codes)) or set(sent_codes) != requested_codes:
        raise HTTPException(422, "The draft must list every product on the request exactly once.")

    by_code = {line.product_code: line for line in data.lines}
    for line in quote.lines:
        line.unit_price = by_code[line.product_code].unit_price
        line.discount_percent = by_code[line.product_code].discount_percent

    quote.validity_date = data.validity_date
    quote.quotation_notes = data.quotation_notes or None
    quote.sales_notes = data.sales_notes or None
    quote.status = "draft"
    record_event(quote, sales, "draft_saved", client_visible=False)

    db.commit()
    db.refresh(quote)
    return sales_view(quote, request.app.state.catalogue)


@router.post("/{quote_id}/send", response_model=SalesQuoteOut)
def send_quote(
    quote_id: int,
    request: Request,
    sales: User = Depends(require_sales),
    db: Session = Depends(get_db),
):
    """Send the saved draft to the client. From this moment they can see the prices."""
    quote = find_quote_or_404(db, quote_id, sales)

    if quote.status in PRICE_VISIBLE_STATUSES:
        raise HTTPException(409, "This quotation has already been sent.")
    if quote.status != "draft":
        raise HTTPException(409, "Save a draft with prices before sending.")

    unpriced = [line.product_code for line in quote.lines if line.unit_price is None]
    if unpriced:
        raise HTTPException(422, f"Every line needs a price before sending (missing: {', '.join(unpriced)}).")
    if quote.validity_date is None:
        raise HTTPException(422, "Add a validity date before sending.")
    if quote.validity_date < pricing.today_in_south_africa():
        raise HTTPException(422, "The validity date has already passed.")

    quote.status = "sent"
    quote.revision += 1
    quote.sent_at = utc_now()
    quote.sent_by_name = sales.full_name
    record_event(quote, sales, "sent", f"Version {quote.revision}. Valid until {quote.validity_date.isoformat()}")

    db.commit()
    db.refresh(quote)
    return sales_view(quote, request.app.state.catalogue)


@router.post("/{quote_id}/withdraw", response_model=SalesQuoteOut)
def withdraw_quote(
    quote_id: int,
    data: WithdrawQuote,
    request: Request,
    sales: User = Depends(require_sales),
    db: Session = Depends(get_db),
):
    """Mistakes happen: take a sent quotation back, fix it and send it again.

    Only possible while the client has not answered. The prices disappear from the client's
    view straight away, they are told why, and the quotation goes back to a draft. The next
    send becomes version 2 (then 3...), so everyone can see which one is current.
    """
    quote = find_quote_or_404(db, quote_id, sales)
    if quote.status in {"accepted", "declined"}:
        raise HTTPException(409, f"The client has already {quote.status} this quotation, so it can no longer be withdrawn.")
    if quote.status != "sent":
        raise HTTPException(409, "Only a quotation that has been sent can be withdrawn.")

    quote.status = "draft"
    record_event(quote, sales, "withdrawn", data.reason)  # client-visible: they were told it was sent
    db.commit()
    db.refresh(quote)
    return sales_view(quote, request.app.state.catalogue)


# ---- clients: answer a quotation ------------------------------------------
def find_sent_quote(db: Session, quote_id: int, user: User) -> QuoteRequest:
    quote = find_quote_or_404(db, quote_id, user)
    if quote.status in {"accepted", "declined"}:
        raise HTTPException(409, f"This quotation has already been {quote.status}.")
    if quote.status != "sent":
        # Never reveal that a draft exists: to the client it is simply not a quotation yet.
        raise HTTPException(409, "There is no quotation to answer yet.")
    return quote


@router.post("/{quote_id}/accept", response_model=QuoteOut)
def accept_quote(
    quote_id: int,
    user: User = Depends(require_client),
    db: Session = Depends(get_db),
):
    quote = find_sent_quote(db, quote_id, user)
    if quote.is_expired:
        raise HTTPException(
            409, f"This quotation expired on {quote.validity_date.isoformat()}. Please ask for a new one."
        )
    quote.status = "accepted"
    record_event(quote, user, "accepted")
    db.commit()
    db.refresh(quote)
    return client_view(quote)


@router.post("/{quote_id}/decline", response_model=QuoteOut)
def decline_quote(
    quote_id: int,
    data: DeclineQuote | None = None,
    user: User = Depends(require_client),
    db: Session = Depends(get_db),
):
    quote = find_sent_quote(db, quote_id, user)
    quote.status = "declined"
    record_event(quote, user, "declined", data.reason if data and data.reason else None)
    db.commit()
    db.refresh(quote)
    return client_view(quote)
