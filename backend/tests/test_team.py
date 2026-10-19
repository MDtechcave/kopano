"""Staff management: only an administrator adds, deactivates or resets staff."""
from tests.conftest import quote_body, sign_in


def add_member(client, admin, email, name="New Rep"):
    response = client.post("/api/team", json={"email": email, "full_name": name}, headers=admin)
    assert response.status_code == 201, response.text
    return response.json()


def test_admin_adds_a_salesperson_who_must_change_the_temporary_password(client, admin):
    created = add_member(client, admin, "rep.one@example.com")
    assert created["is_admin"] is False and created["must_change_password"] is True
    assert created["added_by_name"] == "Admin Person"

    login = client.post("/api/auth/login", json={"email": "rep.one@example.com", "password": created["temporary_password"]})
    assert login.status_code == 200
    assert login.json()["user"]["role"] == "sales" and login.json()["user"]["must_change_password"] is True
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    # Until the password is changed they can do nothing else.
    blocked = client.get("/api/quotes", headers=headers)
    assert blocked.status_code == 403 and blocked.headers["X-Auth-Error"] == "password_change_required"
    assert client.get("/api/auth/me", headers=headers).status_code == 200

    body = {"current_password": created["temporary_password"], "new_password": "my-own-password"}
    assert client.post("/api/auth/change-password", json=body, headers=headers).status_code == 204
    assert client.get("/api/quotes", headers=headers).status_code == 200


def test_salespeople_cannot_add_invite_or_list_staff(client, sales, client_a):
    body = {"email": "sneaky.rep@example.com", "full_name": "Sneaky Rep"}
    assert client.post("/api/team", json=body, headers=sales).status_code == 403
    assert client.get("/api/team", headers=sales).status_code == 403
    assert client.post("/api/team", json=body, headers=client_a).status_code == 403
    assert client.post("/api/team", json=body).status_code == 401
    # The old invitation endpoints are gone.
    assert client.post("/api/sales/invitations", json=body, headers=sales).status_code in (404, 405)


def test_admin_can_do_sales_work_but_not_submit_rfqs(client, admin, client_a):
    quote = client.post("/api/quotes", json=quote_body(), headers=client_a).json()
    assert client.get(f"/api/quotes/{quote['id']}", headers=admin).status_code == 200
    assert client.post(f"/api/quotes/{quote['id']}/start-review", headers=admin).status_code == 200
    assert client.post("/api/quotes", json=quote_body(), headers=admin).status_code == 403
    assert client.get("/api/sales/summary", headers=admin).status_code == 200


def test_clients_cannot_reach_the_team_area(client, client_a):
    assert client.get("/api/team", headers=client_a).status_code == 403


def test_deactivation_locks_out_an_existing_session_at_once(client, admin):
    created = add_member(client, admin, "rep.two@example.com")
    first = client.post("/api/auth/login", json={"email": "rep.two@example.com", "password": created["temporary_password"]}).json()
    headers = {"Authorization": f"Bearer {first['access_token']}"}
    client.post("/api/auth/change-password", json={"current_password": created["temporary_password"], "new_password": "my-own-password"}, headers=headers)
    assert client.get("/api/quotes", headers=headers).status_code == 200

    off = client.patch(f"/api/team/{created['id']}", json={"is_active": False}, headers=admin)
    assert off.status_code == 200 and off.json()["is_active"] is False

    # The token they already hold stops working immediately...
    locked = client.get("/api/quotes", headers=headers)
    assert locked.status_code == 401 and locked.headers["X-Auth-Error"] == "deactivated"
    # ...and they cannot sign in again (but only after proving they know the password).
    assert client.post("/api/auth/login", json={"email": "rep.two@example.com", "password": "my-own-password"}).status_code == 403
    assert client.post("/api/auth/login", json={"email": "rep.two@example.com", "password": "wrong-guess"}).status_code == 401

    # Reactivating restores access.
    assert client.patch(f"/api/team/{created['id']}", json={"is_active": True}, headers=admin).status_code == 200
    assert client.get("/api/quotes", headers=headers).status_code == 200


def test_admin_cannot_deactivate_themselves_or_another_admin_or_a_client(client, admin, client_a):
    me = client.get("/api/auth/me", headers=admin).json()
    assert client.patch(f"/api/team/{me['id']}", json={"is_active": False}, headers=admin).status_code == 409
    client_id = client.get("/api/auth/me", headers=client_a).json()["id"]
    assert client.patch(f"/api/team/{client_id}", json={"is_active": False}, headers=admin).status_code == 404


def test_admin_can_reset_a_forgotten_password(client, admin):
    created = add_member(client, admin, "rep.three@example.com")
    reset = client.post(f"/api/team/{created['id']}/reset-password", headers=admin)
    assert reset.status_code == 200
    new_temp = reset.json()["temporary_password"]
    assert new_temp != created["temporary_password"]
    assert client.post("/api/auth/login", json={"email": "rep.three@example.com", "password": created["temporary_password"]}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "rep.three@example.com", "password": new_temp}).status_code == 200


def test_cannot_add_someone_who_already_has_an_account(client, admin, client_a):
    body = {"email": "client.a@example.com", "full_name": "Client A"}
    assert client.post("/api/team", json=body, headers=admin).status_code == 409


def test_team_list_shows_who_is_active(client, admin):
    add_member(client, admin, "rep.four@example.com", "Rep Four")
    team = client.get("/api/team", headers=admin).json()
    assert any(m["email"] == "rep.four@example.com" and m["is_active"] for m in team)
    assert all("password" not in m and "password_hash" not in m for m in team)
    assert any(m["is_admin"] for m in team)


def test_nobody_can_become_admin_through_the_api(client, admin):
    created = add_member(client, admin, "rep.five@example.com")
    assert created["is_admin"] is False
    response = client.post("/api/team", json={"email": "rep.six@example.com", "full_name": "Rep Six", "is_admin": True}, headers=admin)
    assert response.json()["is_admin"] is False
