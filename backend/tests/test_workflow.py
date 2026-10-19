"""The connected flow: submit -> open -> draft -> send -> accept/decline, plus the money maths."""
from datetime import timedelta
from decimal import Decimal

import jwt

from app import config
from app.database import QuoteRequest, SessionLocal, User, ROLE_CLIENT
from app.pricing import line_total, quote_totals, today_in_south_africa
from app.security import hash_password
from tests.conftest import price_body, quote_body, register, sign_in

TWO_LINES = [{"product_code": "SPL540W", "quantity": 10}, {"product_code": "INDY5000", "quantity": 2}]


def make_quote(client, headers, lines=None):
    return client.post("/api/quotes", json=quote_body(lines=lines or TWO_LINES), headers=headers).json()


def save_and_send(client, sales, quote_id, **overrides):
    body = price_body([("SPL540W", "1000.00", "10"), ("INDY5000", "9000.00", "0")], **overrides)
    assert client.put(f"/api/quotes/{quote_id}/draft", json=body, headers=sales).status_code == 200
    return client.post(f"/api/quotes/{quote_id}/send", headers=sales)


# ---- the maths -------------------------------------------------------------
def test_line_total_applies_discount():
    assert line_total(Decimal("1000.00"), 10, Decimal("10")) == Decimal("9000.00")
    assert line_total(Decimal("19.99"), 3, Decimal("0")) == Decimal("59.97")
    assert line_total(None, 3, Decimal("0")) is None


def test_vat_is_fifteen_percent_of_the_discounted_subtotal():
    totals = quote_totals([Decimal("9000.00"), Decimal("18000.00")], Decimal("0.15"))
    assert totals == {"subtotal": Decimal("27000.00"), "vat": Decimal("4050.00"), "total": Decimal("31050.00")}


def test_vat_rounds_to_the_cent():
    totals = quote_totals([Decimal("0.10")], Decimal("0.15"))  # 0.015 -> 0.02
    assert totals["vat"] == Decimal("0.02")


def test_no_totals_while_a_line_is_unpriced():
    assert quote_totals([Decimal("5.00"), None], Decimal("0.15")) is None


# ---- the full journey ------------------------------------------------------
def test_full_journey_from_rfq_to_accepted(client, client_a, sales):
    quote = make_quote(client, client_a)
    assert quote["status"] == "submitted"

    # Sales open it.
    opened = client.post(f"/api/quotes/{quote['id']}/start-review", headers=sales).json()
    assert opened["status"] == "in_review"

    # Saving a draft: sales can see it, the client cannot.
    draft = client.put(f"/api/quotes/{quote['id']}/draft",
                       json=price_body([("SPL540W", "1000.00", "10"), ("INDY5000", "9000.00", "0")]), headers=sales).json()
    assert draft["status"] == "draft"
    assert draft["subtotal"] == 27000.0 and draft["vat_amount"] == 4050.0 and draft["total"] == 31050.0
    hidden = client.get(f"/api/quotes/{quote['id']}", headers=client_a).json()
    assert hidden["total"] is None and all(line["unit_price"] is None for line in hidden["lines"])
    assert all(q["id"] != quote["id"] for q in client.get("/api/portal/received-quotes", headers=client_a).json())

    # Sending makes it visible, with every figure.
    sent = client.post(f"/api/quotes/{quote['id']}/send", headers=sales)
    assert sent.status_code == 200 and sent.json()["status"] == "sent"
    seen = client.get(f"/api/quotes/{quote['id']}", headers=client_a).json()
    assert seen["status"] == "sent"
    assert seen["subtotal"] == 27000.0 and seen["vat_rate"] == 0.15
    assert seen["vat_amount"] == 4050.0 and seen["total"] == 31050.0
    assert seen["lines"][0]["discount_percent"] == 10.0 and seen["lines"][0]["line_total"] == 9000.0
    assert seen["quotation_notes"] == "Delivery to be confirmed with the order."
    assert "sales_notes" not in seen
    received = client.get("/api/portal/received-quotes", headers=client_a).json()
    assert any(q["id"] == quote["id"] for q in received)

    # The client accepts; sales see it.
    accepted = client.post(f"/api/quotes/{quote['id']}/accept", headers=client_a)
    assert accepted.status_code == 200 and accepted.json()["status"] == "accepted"
    assert client.get(f"/api/quotes/{quote['id']}", headers=sales).json()["status"] == "accepted"

    # History: sales see every step, the client only their own steps (no draft saves).
    sales_actions = [e["action"] for e in client.get(f"/api/quotes/{quote['id']}", headers=sales).json()["history"]]
    assert sales_actions == ["submitted", "review_started", "draft_saved", "sent", "accepted"]
    client_actions = [e["action"] for e in client.get(f"/api/quotes/{quote['id']}", headers=client_a).json()["history"]]
    assert client_actions == ["submitted", "sent", "accepted"]


def test_client_can_decline_with_a_reason(client, client_a, sales):
    quote = make_quote(client, client_a)
    save_and_send(client, sales, quote["id"])
    declined = client.post(f"/api/quotes/{quote['id']}/decline", json={"reason": "Found it cheaper"}, headers=client_a)
    assert declined.status_code == 200 and declined.json()["status"] == "declined"
    history = client.get(f"/api/quotes/{quote['id']}", headers=sales).json()["history"]
    assert history[-1]["action"] == "declined" and history[-1]["detail"] == "Found it cheaper"


def test_an_answer_is_final(client, client_a, sales):
    quote = make_quote(client, client_a)
    save_and_send(client, sales, quote["id"])
    client.post(f"/api/quotes/{quote['id']}/accept", headers=client_a)
    assert client.post(f"/api/quotes/{quote['id']}/decline", headers=client_a).status_code == 409
    assert client.post(f"/api/quotes/{quote['id']}/accept", headers=client_a).status_code == 409


# ---- rules around draft / send --------------------------------------------
def test_cannot_answer_before_it_is_sent(client, client_a, sales):
    quote = make_quote(client, client_a)
    assert client.post(f"/api/quotes/{quote['id']}/accept", headers=client_a).status_code == 409
    client.put(f"/api/quotes/{quote['id']}/draft", json=price_body([("SPL540W", "1", "0"), ("INDY5000", "1", "0")]), headers=sales)
    assert client.post(f"/api/quotes/{quote['id']}/accept", headers=client_a).status_code == 409  # a draft is not a quotation


def test_cannot_send_without_a_saved_draft(client, client_a, sales):
    quote = make_quote(client, client_a)
    assert client.post(f"/api/quotes/{quote['id']}/send", headers=sales).status_code == 409


def test_cannot_send_with_unpriced_lines_or_without_validity_date(client, client_a, sales):
    quote = make_quote(client, client_a)
    partial = price_body([("SPL540W", "100", "0"), ("INDY5000", None, "0")])
    assert client.put(f"/api/quotes/{quote['id']}/draft", json=partial, headers=sales).status_code == 200  # drafts may be incomplete
    response = client.post(f"/api/quotes/{quote['id']}/send", headers=sales)
    assert response.status_code == 422 and "INDY5000" in response.json()["detail"]

    complete = price_body([("SPL540W", "100", "0"), ("INDY5000", "200", "0")], validity_date=None)
    client.put(f"/api/quotes/{quote['id']}/draft", json=complete, headers=sales)
    assert client.post(f"/api/quotes/{quote['id']}/send", headers=sales).status_code == 422


def test_cannot_send_with_a_validity_date_in_the_past(client, client_a, sales):
    quote = make_quote(client, client_a)
    yesterday = (today_in_south_africa() - timedelta(days=1)).isoformat()
    body = price_body([("SPL540W", "100", "0"), ("INDY5000", "200", "0")], validity_date=yesterday)
    client.put(f"/api/quotes/{quote['id']}/draft", json=body, headers=sales)
    assert client.post(f"/api/quotes/{quote['id']}/send", headers=sales).status_code == 422


def test_sent_quotation_can_no_longer_be_edited(client, client_a, sales):
    quote = make_quote(client, client_a)
    save_and_send(client, sales, quote["id"])
    again = price_body([("SPL540W", "1", "0"), ("INDY5000", "1", "0")])
    assert client.put(f"/api/quotes/{quote['id']}/draft", json=again, headers=sales).status_code == 409
    assert client.post(f"/api/quotes/{quote['id']}/send", headers=sales).status_code == 409


def test_bad_prices_and_discounts_are_rejected(client, client_a, sales):
    quote = make_quote(client, client_a, lines=[{"product_code": "SPL540W", "quantity": 1}])
    for price, discount in [("0", "0"), ("-5", "0"), ("100", "-1"), ("100", "101")]:
        body = price_body([("SPL540W", price, discount)])
        assert client.put(f"/api/quotes/{quote['id']}/draft", json=body, headers=sales).status_code == 422


def test_draft_must_cover_every_line_once(client, client_a, sales):
    quote = make_quote(client, client_a)
    only_one = price_body([("SPL540W", "100", "0")])
    assert client.put(f"/api/quotes/{quote['id']}/draft", json=only_one, headers=sales).status_code == 422
    made_up = price_body([("SPL540W", "100", "0"), ("MADE-UP", "1", "0")])
    assert client.put(f"/api/quotes/{quote['id']}/draft", json=made_up, headers=sales).status_code == 422


def test_expired_quotation_cannot_be_accepted(client, client_a, sales):
    quote = make_quote(client, client_a)
    save_and_send(client, sales, quote["id"])
    with SessionLocal() as db:
        db.get(QuoteRequest, quote["id"]).validity_date = today_in_south_africa() - timedelta(days=1)
        db.commit()
    seen = client.get(f"/api/quotes/{quote['id']}", headers=client_a).json()
    assert seen["is_expired"] is True
    assert client.post(f"/api/quotes/{quote['id']}/accept", headers=client_a).status_code == 409
    assert client.post(f"/api/quotes/{quote['id']}/decline", headers=client_a).status_code == 200


# ---- company scoping -------------------------------------------------------
def test_colleagues_share_a_company_and_strangers_do_not(client, client_a, client_b, sales):
    quote = make_quote(client, client_a)
    save_and_send(client, sales, quote["id"])

    # A second person at Company A (made directly: joining a company is by invitation, not built yet).
    with SessionLocal() as db:
        owner = db.query(User).filter_by(email="client.a@example.com").one()
        db.add(User(email="colleague.a@example.com", password_hash=hash_password("password123"),
                    full_name="Colleague A", role=ROLE_CLIENT, company_id=owner.company_id))
        db.commit()
    colleague = sign_in(client, "colleague.a@example.com")

    assert client.get(f"/api/quotes/{quote['id']}", headers=colleague).status_code == 200
    assert client.post(f"/api/quotes/{quote['id']}/accept", headers=colleague).status_code == 200

    # Company B cannot see, answer or even confirm the existence of it.
    assert client.get(f"/api/quotes/{quote['id']}", headers=client_b).status_code == 404
    assert client.post(f"/api/quotes/{quote['id']}/decline", headers=client_b).status_code == 404
    assert all(q["id"] != quote["id"] for q in client.get("/api/quotes", headers=client_b).json())
    assert all(q["id"] != quote["id"] for q in client.get("/api/portal/received-quotes", headers=client_b).json())


def test_same_company_name_does_not_grant_access(client, client_a):
    quote = make_quote(client, client_a)
    copycat = register(client, "copycat@example.com", company="Company A")  # same NAME, new account
    assert client.get(f"/api/quotes/{quote['id']}", headers=copycat).status_code == 404


# ---- portal ----------------------------------------------------------------
def test_portal_is_clients_only_and_overview_adds_up(client, client_a, sales):
    assert client.get("/api/portal/overview").status_code == 401
    assert client.get("/api/portal/overview", headers=sales).status_code == 403

    quote = make_quote(client, client_a)
    save_and_send(client, sales, quote["id"])
    data = client.get("/api/portal/overview", headers=client_a).json()
    mine = client.get("/api/quotes", headers=client_a).json()
    counts = data["counts"]
    assert counts["total_requests"] == len(mine)
    assert counts["awaiting_quotation"] + counts["awaiting_your_decision"] + counts["expired"] \
        + counts["accepted"] + counts["declined"] == len(mine)
    assert data["recent_activity"] and "draft_saved" not in {a["action"] for a in data["recent_activity"]}


# ---- sales search and filter -----------------------------------------------
def test_sales_can_search_and_filter(client, client_a, sales):
    quote = make_quote(client, client_a, lines=[{"product_code": "ACCB50KW", "quantity": 1}])
    by_ref = client.get("/api/quotes", params={"q": quote["reference"]}, headers=sales).json()
    assert [q["id"] for q in by_ref] == [quote["id"]]
    by_code = client.get("/api/quotes", params={"q": "ACCB50KW"}, headers=sales).json()
    assert quote["id"] in [q["id"] for q in by_code]
    assert client.get("/api/quotes", params={"q": "zzz-nothing"}, headers=sales).json() == []
    assert all(q["status"] == "new" for q in client.get("/api/quotes", params={"status": "new"}, headers=sales).json())
    assert client.get("/api/quotes", params={"status": "banana"}, headers=sales).status_code == 422


# ---- account details -------------------------------------------------------
def test_account_update_cannot_touch_role_email_or_company(client, client_a):
    response = client.patch("/api/auth/me", headers=client_a,
                            json={"full_name": "Renamed Person", "phone": "0821234567", "role": "sales",
                                  "email": "hacker@example.com", "company": "Other Co"})
    assert response.status_code == 200
    me = client.get("/api/auth/me", headers=client_a).json()
    assert me["full_name"] == "Renamed Person" and me["phone"] == "0821234567"
    assert me["role"] == "client" and me["email"] == "client.a@example.com" and me["company"] == "Company A"


def test_change_password_needs_the_current_one(client):
    headers = register(client, "pw.change@example.com")
    body = {"current_password": "wrong-one", "new_password": "brand-new-password"}
    assert client.post("/api/auth/change-password", json=body, headers=headers).status_code == 400
    body["current_password"] = "password123"
    assert client.post("/api/auth/change-password", json=body, headers=headers).status_code == 204
    assert client.post("/api/auth/login", json={"email": "pw.change@example.com", "password": "password123"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "pw.change@example.com", "password": "brand-new-password"}).status_code == 200


# ---- sessions --------------------------------------------------------------
def test_expired_session_says_so(client):
    with SessionLocal() as db:
        user_id = db.query(User).filter_by(email="client.a@example.com").one().id
    from datetime import datetime, timezone
    expired = jwt.encode({"sub": str(user_id), "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
                         config.SECRET_KEY, algorithm="HS256")
    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401
    assert response.headers["X-Auth-Error"] == "session_expired"


def test_signed_out_is_different_from_expired(client):
    assert client.get("/api/auth/me").headers["X-Auth-Error"] == "signed_out"


def test_public_config_has_the_business_name_and_vat(client):
    data = client.get("/api/config").json()
    assert data["business_name"] == config.BUSINESS_NAME and data["vat_rate"] == 0.15


# ---- withdrawing a sent quotation -----------------------------------------
def test_sales_can_withdraw_correct_and_resend(client, client_a, sales):
    quote = make_quote(client, client_a)
    save_and_send(client, sales, quote["id"])
    assert client.get(f"/api/quotes/{quote['id']}", headers=client_a).json()["revision"] == 1

    # A reason is required, because the client is told.
    assert client.post(f"/api/quotes/{quote['id']}/withdraw", json={}, headers=sales).status_code == 422
    withdrawn = client.post(f"/api/quotes/{quote['id']}/withdraw", json={"reason": "Wrong unit price on line 1"}, headers=sales)
    assert withdrawn.status_code == 200 and withdrawn.json()["status"] == "draft"

    # The client loses sight of the figures at once, and cannot accept the old version.
    seen = client.get(f"/api/quotes/{quote['id']}", headers=client_a).json()
    assert seen["status"] == "submitted" and seen["total"] is None
    assert client.post(f"/api/quotes/{quote['id']}/accept", headers=client_a).status_code == 409
    assert seen["history"][-1]["action"] == "withdrawn" and seen["history"][-1]["detail"] == "Wrong unit price on line 1"

    # Sales fix it and send version 2.
    fixed = price_body([("SPL540W", "900.00", "10"), ("INDY5000", "9000.00", "0")])
    assert client.put(f"/api/quotes/{quote['id']}/draft", json=fixed, headers=sales).status_code == 200
    assert client.post(f"/api/quotes/{quote['id']}/send", headers=sales).status_code == 200
    now = client.get(f"/api/quotes/{quote['id']}", headers=client_a).json()
    assert now["revision"] == 2 and now["status"] == "sent"
    assert now["subtotal"] == 8100.0 + 18000.0
    assert client.post(f"/api/quotes/{quote['id']}/accept", headers=client_a).status_code == 200


def test_cannot_withdraw_after_the_client_answered_or_before_sending(client, client_a, sales):
    quote = make_quote(client, client_a)
    assert client.post(f"/api/quotes/{quote['id']}/withdraw", json={"reason": "just testing"}, headers=sales).status_code == 409
    save_and_send(client, sales, quote["id"])
    client.post(f"/api/quotes/{quote['id']}/accept", headers=client_a)
    assert client.post(f"/api/quotes/{quote['id']}/withdraw", json={"reason": "too late now"}, headers=sales).status_code == 409


def test_clients_cannot_withdraw(client, client_a, sales):
    quote = make_quote(client, client_a)
    save_and_send(client, sales, quote["id"])
    assert client.post(f"/api/quotes/{quote['id']}/withdraw", json={"reason": "no thanks"}, headers=client_a).status_code == 403
