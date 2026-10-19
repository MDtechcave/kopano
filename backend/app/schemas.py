"""The shapes of data that go in and out of the API."""
import re
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _check_email(value: str) -> str:
    value = value.strip().lower()
    if not EMAIL_PATTERN.match(value):
        raise ValueError("Please enter a valid email address.")
    return value


# ---- accounts --------------------------------------------------------------
class RegisterRequest(BaseModel):
    # Notice there is no "role" field: people can only ever register as clients.
    email: str
    password: str = Field(min_length=8, max_length=100)
    full_name: str = Field(min_length=2, max_length=120)
    company: str = Field(min_length=2, max_length=160)

    _email = field_validator("email")(_check_email)


class LoginRequest(BaseModel):
    email: str
    password: str

    _email = field_validator("email")(_check_email)


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    phone: str | None = None
    company: str
    role: str
    is_admin: bool = False
    must_change_password: bool = False

    model_config = {"from_attributes": True}


class AccountUpdate(BaseModel):
    """What a person may change about themselves. Email, company and role are not here:
    they cannot be edited through this form."""

    full_name: str | None = Field(default=None, min_length=2, max_length=120)
    phone: str | None = Field(default=None, min_length=7, max_length=40)


class ChangePassword(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=100)


class ForgotPasswordRequest(BaseModel):
    email: str

    _email = field_validator("email")(_check_email)


class ForgotPasswordOut(BaseModel):
    message: str
    temporary_password: str | None = None


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ---- team management (administrator only) --------------------------------
class TeamMemberCreate(BaseModel):
    email: str
    full_name: str = Field(min_length=2, max_length=120)

    _email = field_validator("email")(_check_email)


class TeamMemberOut(BaseModel):
    id: int
    email: str
    full_name: str
    is_admin: bool
    is_active: bool
    must_change_password: bool
    added_by_name: str | None
    created_at: datetime
    last_login_at: datetime | None

    model_config = {"from_attributes": True}


class TeamMemberCreated(TeamMemberOut):
    """The only time the temporary password is ever shown. The admin passes it on."""

    temporary_password: str


class TeamMemberUpdate(BaseModel):
    is_active: bool


# ---- quotes ----------------------------------------------------------------
class QuoteLineIn(BaseModel):
    product_code: str
    quantity: int = Field(ge=1, le=100000)


class QuoteCreate(BaseModel):
    company_name: str = Field(min_length=2, max_length=160)
    contact_name: str = Field(min_length=2, max_length=120)
    email: str
    phone: str = Field(min_length=7, max_length=40)
    delivery_city: str = Field(min_length=2, max_length=120)
    vat_number: str | None = Field(default=None, max_length=40)
    notes: str | None = Field(default=None, max_length=2000)
    popia_consent: bool
    lines: list[QuoteLineIn] = Field(min_length=1, max_length=200)

    _email = field_validator("email")(_check_email)

    @field_validator("popia_consent")
    @classmethod
    def consent_required(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Consent is needed so we can use your details to respond to this request.")
        return value


class QuoteLineOut(BaseModel):
    product_code: str
    description: str
    quantity: int
    # Rand, per unit, before discount. All three price fields stay empty for a client
    # until sales have SENT the quotation.
    unit_price: float | None = None
    discount_percent: float | None = None
    line_total: float | None = None  # after discount, excluding VAT

    model_config = {"from_attributes": True}


class EventOut(BaseModel):
    created_at: datetime
    actor_name: str
    actor_role: str
    action: str
    detail: str | None

    model_config = {"from_attributes": True}


class QuoteOut(BaseModel):
    """What a client sees about their own company's request."""

    id: int
    reference: str
    status: str  # clients see: submitted, sent, accepted or declined
    created_at: datetime
    company_name: str
    contact_name: str
    email: str
    phone: str
    delivery_city: str
    vat_number: str | None
    notes: str | None
    total_units: int
    lines: list[QuoteLineOut]

    # Only filled in after sales have sent the quotation (amounts in rand).
    subtotal: float | None = None
    vat_rate: float | None = None
    vat_amount: float | None = None
    total: float | None = None
    validity_date: date | None = None
    is_expired: bool = False
    quotation_notes: str | None = None
    revision: int = 0  # 1 = first version sent; 2+ = corrected and sent again
    sent_at: datetime | None = None

    history: list[EventOut] = []

    model_config = {"from_attributes": True}


class SalesQuoteLineOut(QuoteLineOut):
    """For sales: shows how much we hold, so they can spot lines we cannot fully supply."""

    stock_on_hand: int | None = None
    shortfall: int = 0  # how many units short of the request (0 = fully covered)


class SalesQuoteOut(QuoteOut):
    """What the sales team sees. Internal notes are never sent to clients."""

    status: str  # the real status: new, in_review, draft, sent, accepted, declined
    vat_rate: float | None = None
    lines: list[SalesQuoteLineOut]
    sales_notes: str | None
    client_email: str  # the account that submitted it, which may differ from the contact email
    sent_by_name: str | None
    has_stock_shortfall: bool = False


class DraftLine(BaseModel):
    product_code: str
    unit_price: Decimal | None = Field(default=None, gt=0, le=Decimal("100000000"), decimal_places=2)
    discount_percent: Decimal = Field(default=Decimal("0"), ge=0, le=100, decimal_places=2)


class QuoteDraft(BaseModel):
    """Everything on the sales pricing screen. Saving a draft keeps it private to sales."""

    lines: list[DraftLine] = Field(min_length=1)
    validity_date: date | None = None
    quotation_notes: str | None = Field(default=None, max_length=2000)  # the client will read this
    sales_notes: str | None = Field(default=None, max_length=2000)  # internal only


class WithdrawQuote(BaseModel):
    reason: str = Field(min_length=3, max_length=500)  # the client is shown this


class DeclineQuote(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)
