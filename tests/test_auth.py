from tests.conftest import login


def test_dashboard_requires_login(client):
    res = client.get("/", follow_redirects=True)
    assert b"Log in" in res.data or b"login" in res.request.path.encode()


def test_valid_login_succeeds(client, cashier):
    res = login(client, "cashier1")
    assert res.status_code == 200
    assert b"Welcome back" in res.data or b"Dashboard" in res.data


def test_invalid_password_fails(client, cashier):
    res = client.post("/login", data={"username": "cashier1", "password": "wrong"},
                      follow_redirects=True)
    assert b"Invalid username or password" in res.data


def test_inactive_user_cannot_login(client, cashier, app):
    from models import db
    cashier.active = False
    db.session.commit()
    res = client.post("/login", data={"username": "cashier1", "password": "pw123"},
                      follow_redirects=True)
    assert b"Invalid username or password" in res.data
