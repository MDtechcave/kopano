"""Checks the API, with most of the weight on who is allowed to see what."""
from tests.conftest import quote_body, register


# ---- browsing --------------------------------------------------------------
def test_visitor_sees_stock_band_but_not_exact_quantity(client):
    data = client.get("/api/products", params={"q": "SPL540W"}).json()
    product = data["items"][0]
    assert product["stock_label"] == "Bulk stock"
    assert product["quantity"] is None


def test_signed_in_user_sees_exact_quantity(client, client_a):
    data = client.get("/api/products", params={"q": "SPL540W"}, headers=client_a).json()
    assert data["items"][0]["quantity"] == 1479


def test_search_filter_and_paging(client):
    assert client.get("/api/products", params={"q": "deye inverter"}).json()["total"] > 0
    batteries = client.get("/api/products", params={"category": "Batteries"}).json()
    assert batteries["total"] == 29
    page = client.get("/api/products", params={"page_size": 10, "page": 2}).json()
    assert len(page["items"]) == 10


def test_product_code_with_a_slash_works(client):
    response = client.get("/api/products/PB8IN/4OUT")
    assert response.status_code == 200
    assert response.json()["code"] == "PB8IN/4OUT"


def test_unknown_product_is_404(client):
    assert client.get("/api/products/NOPE").status_code == 404


# ---- accounts --------------------------------------------------------------
def test_registering_cannot_create_a_sales_user(client):
    response = client.post(
        "/api/auth/register",
        json={"email": "sneaky@example.com", "password": "password123", "full_name": "Sneaky",
              "company": "Sneaky Co", "role": "sales"},
    )
    assert response.json()["user"]["role"] == "client"


def test_wrong_password_is_rejected(client, client_a):
    response = client.post("/api/auth/login", json={"email": "client.a@example.com", "password": "wrong-password"})
    assert response.status_code == 401


def test_forgot_password_resets_the_account_and_requires_a_new_password(client):
    reset = client.post("/api/auth/forgot-password", json={"email": "client.a@example.com"})
    assert reset.status_code == 200, reset.text
    temp_password = reset.json()["temporary_password"]
    assert temp_password

    login = client.post("/api/auth/login", json={"email": "client.a@example.com", "password": temp_password})
    assert login.status_code == 200, login.text
    assert login.json()["user"]["must_change_password"] is True

    change = client.post(
        "/api/auth/change-password",
        json={"current_password": temp_password, "new_password": "new-password-123"},
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert change.status_code == 204, change.text

    final_login = client.post("/api/auth/login", json={"email": "client.a@example.com", "password": "new-password-123"})
    assert final_login.status_code == 200, final_login.text


# ---- quotes: who can see what ---------------------------------------------
def test_must_be_signed_in_to_request_a_quote(client):
    assert client.post("/api/quotes", json=quote_body()).status_code == 401


def test_consent_is_required(client, client_a):
    response = client.post("/api/quotes", json=quote_body(popia_consent=False), headers=client_a)
    assert response.status_code == 422


def test_unknown_product_in_quote_is_rejected(client, client_a):
    body = quote_body(lines=[{"product_code": "MADE-UP", "quantity": 1}])
    assert client.post("/api/quotes", json=body, headers=client_a).status_code == 422


def test_duplicate_lines_are_merged(client, client_a):
    body = quote_body(lines=[{"product_code": "SPL540W", "quantity": 5}, {"product_code": "SPL540W", "quantity": 7}])
    quote = client.post("/api/quotes", json=body, headers=client_a).json()
    assert len(quote["lines"]) == 1
    assert quote["lines"][0]["quantity"] == 12
    assert quote["reference"].startswith("RFQ-")


def test_client_only_sees_their_own_quotes(client, client_a, client_b):
    mine = client.post("/api/quotes", json=quote_body(company_name="A Only Co"), headers=client_a).json()

    b_list = client.get("/api/quotes", headers=client_b).json()
    assert all(q["company_name"] != "A Only Co" for q in b_list)

    # Direct access by id is blocked too, and looks the same as "does not exist".
    assert client.get(f"/api/quotes/{mine['id']}", headers=client_b).status_code == 404
    assert client.get(f"/api/quotes/{mine['id']}", headers=client_a).status_code == 200


def test_sales_sees_everything_and_clients_never_see_internal_notes(client, client_a, sales):
    from tests.conftest import price_body

    mine = client.post("/api/quotes", json=quote_body(), headers=client_a).json()
    client.put(f"/api/quotes/{mine['id']}/draft", json=price_body([("SPL540W", "100", "0")]), headers=sales)

    all_quotes = client.get("/api/quotes", headers=sales).json()
    assert len(all_quotes) >= 2
    assert "sales_notes" in all_quotes[0]

    client_view = client.get(f"/api/quotes/{mine['id']}", headers=client_a).json()
    assert "sales_notes" not in client_view
    # A draft looks, to the client, like a request nobody has priced yet.
    assert client_view["status"] == "submitted"
    assert client_view["total"] is None and client_view["quotation_notes"] is None


def test_client_cannot_use_sales_actions(client, client_a):
    mine = client.post("/api/quotes", json=quote_body(), headers=client_a).json()
    for method, path in [("post", "start-review"), ("put", "draft"), ("post", "send")]:
        response = getattr(client, method)(f"/api/quotes/{mine['id']}/{path}", json={}, headers=client_a)
        assert response.status_code == 403, path
    # And the old free-for-all status edit no longer exists at all.
    assert client.patch(f"/api/quotes/{mine['id']}", json={"status": "accepted"}, headers=client_a).status_code == 405


def test_forged_token_is_rejected(client):
    response = client.get("/api/quotes", headers={"Authorization": "Bearer not.a.real.token"})
    assert response.status_code == 401
