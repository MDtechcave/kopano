"""Sales-side rules: what sales can and cannot do, stock checks and the pipeline."""
from tests.conftest import quote_body


# ---- sales cannot shop -----------------------------------------------------
def test_sales_cannot_create_quote_requests(client, sales):
    assert client.post("/api/quotes", json=quote_body(), headers=sales).status_code == 403


def new_quote(client, headers, lines=None):
    body = quote_body(lines=lines or [{"product_code": "SPL540W", "quantity": 10}, {"product_code": "INDY5000", "quantity": 2}])
    return client.post("/api/quotes", json=body, headers=headers).json()


# ---- stock check and pipeline ---------------------------------------------
def test_sales_see_stock_shortfalls_on_a_request(client, client_a, sales):
    # We hold 1 unit of ACCB50KW, so asking for 5 is 4 short.
    quote = new_quote(client, client_a, lines=[{"product_code": "ACCB50KW", "quantity": 5}])
    view = client.get(f"/api/quotes/{quote['id']}", headers=sales).json()
    assert view["has_stock_shortfall"] is True
    assert view["lines"][0]["stock_on_hand"] == 1
    assert view["lines"][0]["shortfall"] == 4

    # Clients do not get the stock-check fields.
    mine = client.get(f"/api/quotes/{quote['id']}", headers=client_a).json()
    assert "shortfall" not in mine["lines"][0]


def test_pipeline_summary_is_sales_only_and_adds_up(client, client_a, sales):
    assert client.get("/api/sales/summary", headers=client_a).status_code == 403
    assert client.get("/api/sales/summary").status_code == 401

    summary = client.get("/api/sales/summary", headers=sales).json()
    all_quotes = client.get("/api/quotes", headers=sales).json()
    assert sum(summary["by_status"].values()) == len(all_quotes)
    by = summary["by_status"]
    assert summary["waiting_for_sales"] == by["new"] + by["in_review"] + by["draft"]
    assert any(item["product_code"] == "ACCB50KW" for item in summary["stock_shortfalls"])
