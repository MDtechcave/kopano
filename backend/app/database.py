"""Database tables for users and quote requests (products live in the CSV, not here)."""
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from app import config, pricing

# SQLite needs this flag because FastAPI uses several threads.
connect_args = {"check_same_thread": False} if config.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(config.DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False)

ROLE_CLIENT = "client"
ROLE_SALES = "sales"

# The life of a request:
#   new -> in_review (sales opened it) -> draft (priced, saved, NOT yet visible to the client)
#       -> sent (the client can now see prices) -> accepted or declined (final)
QUOTE_STATUSES = ["new", "in_review", "draft", "sent", "accepted", "declined"]
WORKING_STATUSES = {"new", "in_review", "draft"}      # sales are still working on it
PRICE_VISIBLE_STATUSES = {"sent", "accepted", "declined"}  # the client may see prices


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(moment: datetime) -> datetime:
    """SQLite hands dates back without a timezone; treat those as UTC."""
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


class Base(DeclarativeBase):
    pass


class Company(Base):
    """A client company. Requests and quotations belong to the company, so everyone
    at that company sees the same ones, and nobody else does."""

    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    users: Mapped[list["User"]] = relationship(back_populates="company_account")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    role: Mapped[str] = mapped_column(String(20), default=ROLE_CLIENT)
    # An administrator is a sales-side user who can also manage the team. There is no way
    # to become one through the API: the first is made with the create_admin_user script.
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    # Deactivated staff cannot sign in, and any token they already hold stops working.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Set when an admin creates the account or resets the password with a temporary one.
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    added_by_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Clients belong to a company. Sales staff belong to the business itself, so this is empty.
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    company_account: Mapped[Company | None] = relationship(back_populates="users")

    @property
    def company(self) -> str:
        return self.company_account.name if self.company_account else config.BUSINESS_NAME


class QuoteRequest(Base):
    __tablename__ = "quote_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)  # who submitted it
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)  # who may see it

    # Contact details are copied onto the quote so the record stays correct
    # even if the user later changes their profile.
    company_name: Mapped[str] = mapped_column(String(160))
    contact_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str] = mapped_column(String(40))
    delivery_city: Mapped[str] = mapped_column(String(120))
    vat_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    popia_consent: Mapped[bool] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    # The quotation itself. Everything below is private to sales until status is "sent".
    sales_notes: Mapped[str | None] = mapped_column(Text, nullable=True)  # internal, never shown to clients
    quotation_notes: Mapped[str | None] = mapped_column(Text, nullable=True)  # shown to the client
    validity_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # last day the prices hold
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=lambda: config.VAT_RATE)
    # Counts how many times the quotation has been sent: 1 the first time, 2 after a
    # withdrawn quotation is corrected and sent again, and so on.
    revision: Mapped[int] = mapped_column(Integer, default=0)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_by_name: Mapped[str | None] = mapped_column(String(120), nullable=True)

    user: Mapped[User] = relationship()
    lines: Mapped[list["QuoteLine"]] = relationship(
        back_populates="quote", cascade="all, delete-orphan", order_by="QuoteLine.id"
    )
    history: Mapped[list["QuoteEvent"]] = relationship(
        back_populates="quote", cascade="all, delete-orphan", order_by="QuoteEvent.id"
    )

    @property
    def reference(self) -> str:
        """The number staff and clients quote to each other, e.g. RFQ-00012."""
        return f"RFQ-{self.id:05d}"

    @property
    def total_units(self) -> int:
        return sum(line.quantity for line in self.lines)

    @property
    def client_email(self) -> str:
        return self.user.email

    @property
    def totals(self) -> dict[str, Decimal] | None:
        """Subtotal, VAT and total. None until every line has a price."""
        return pricing.quote_totals([line.line_total for line in self.lines], self.vat_rate)

    @property
    def subtotal(self) -> Decimal | None:
        return self.totals["subtotal"] if self.totals else None

    @property
    def vat_amount(self) -> Decimal | None:
        return self.totals["vat"] if self.totals else None

    @property
    def total(self) -> Decimal | None:
        return self.totals["total"] if self.totals else None

    @property
    def is_expired(self) -> bool:
        """A sent quotation whose validity date has passed (and has not been answered)."""
        return (
            self.status == "sent"
            and self.validity_date is not None
            and self.validity_date < pricing.today_in_south_africa()
        )


class QuoteLine(Base):
    __tablename__ = "quote_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    quote_id: Mapped[int] = mapped_column(ForeignKey("quote_requests.id"), index=True)
    product_code: Mapped[str] = mapped_column(String(80))
    # A snapshot of the description at the time of the request.
    description: Mapped[str] = mapped_column(String(500))
    quantity: Mapped[int] = mapped_column(Integer)
    # Set by the sales team when they quote. The inventory report has no prices,
    # so this is empty until a salesperson types a real price in.
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))

    quote: Mapped[QuoteRequest] = relationship(back_populates="lines")

    @property
    def line_total(self) -> Decimal | None:
        return pricing.line_total(self.unit_price, self.quantity, self.discount_percent)


class QuoteEvent(Base):
    """One entry in a request's history: who did what, and when."""

    __tablename__ = "quote_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    quote_id: Mapped[int] = mapped_column(ForeignKey("quote_requests.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    actor_name: Mapped[str] = mapped_column(String(120))
    actor_role: Mapped[str] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(30))  # submitted, review_started, draft_saved, sent, accepted, declined
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Internal steps (opening, saving a draft) are not shown to the client.
    client_visible: Mapped[bool] = mapped_column(Boolean, default=True)

    quote: Mapped[QuoteRequest] = relationship(back_populates="history")


def record_event(quote: QuoteRequest, actor: User, action: str, detail: str | None = None,
                 client_visible: bool = True) -> None:
    quote.history.append(
        QuoteEvent(actor_name=actor.full_name, actor_role=actor.role, action=action,
                   detail=detail, client_visible=client_visible)
    )


def create_tables() -> None:
    Base.metadata.create_all(engine)


def get_db():
    """FastAPI dependency: gives each request its own database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
