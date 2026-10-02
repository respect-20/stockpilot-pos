from tests.conftest import login, make_user
from models import db, Product
import services


def seed_product(location, qty=20, cost=10, sell=20, sku="SKU-1"):
    p = Product(sku=sku, name="Widget " + sku, cost_price=cost, sell_price=sell)
    db.session.add(p)
    db.session.flush()
    services.adjust_stock(p.id, location.id, qty, reason="received")
    return p


def test_cashier_cannot_access_reports(client, cashier):
    login(client, "cashier1")
    res = client.get("/reports")
    assert res.status_code == 403


def test_admin_can_view_reports(client, admin):
    login(client, "admin1")
    res = client.get("/reports")
    assert res.status_code == 200


def test_admin_can_export_csv(client, admin, location):
    login(client, "admin1")
    p = Product(sku="SKU-1", name="Widget", cost_price=10, sell_price=20)
    db.session.add(p)
    db.session.flush()
    services.adjust_stock(p.id, location.id, 10, reason="received")
    client.post("/api/checkout", json={"items": [{"product_id": p.id, "quantity": 2}]})

    res = client.get("/reports/export.csv")
    assert res.status_code == 200
    assert res.mimetype == "text/csv"
    body = res.data.decode()
    assert "Widget" in body
    assert "sale_id" in body


def test_cashier_cannot_export_csv(client, cashier):
    login(client, "cashier1")
    res = client.get("/reports/export.csv")
    assert res.status_code == 403


def test_cashier_performance_ranks_by_sales_count(client, cashier, location, app):
    make_user("cashier2", "cashier")
    p = seed_product(location, qty=50)

    login(client, "cashier1")
    client.post("/api/checkout", json={"items": [{"product_id": p.id, "quantity": 1}]})
    client.post("/api/checkout", json={"items": [{"product_id": p.id, "quantity": 1}]})
    client.get("/logout")

    login(client, "cashier2")
    client.post("/api/checkout", json={"items": [{"product_id": p.id, "quantity": 1}]})

    rows = services.cashier_performance()
    # sell price 20, 10% tax (fixture TAX_RATE=0.1) -> 22 per sale
    assert rows[0]["username"] == "cashier1"
    assert rows[0]["sales_count"] == 2
    assert rows[0]["revenue"] == 44.0
    assert rows[0]["avg_sale"] == 22.0
    assert rows[1]["username"] == "cashier2"
    assert rows[1]["sales_count"] == 1


def test_cashier_performance_excludes_non_completed_sales(client, admin, location, monkeypatch):
    import payments
    monkeypatch.setattr(payments, "configured", lambda: True)
    monkeypatch.setattr(payments, "start_mobile_payment", lambda sale, phone, method: {
        "success": False, "error": "Insufficient balance",
    })
    p = seed_product(location, qty=10)
    login(client, "admin1")
    # A failed-to-start payment should not count toward the cashier's stats.
    client.post("/api/checkout", json={
        "items": [{"product_id": p.id, "quantity": 1}],
        "payment_method": "ecocash", "mobile_number": "0774444444",
    })
    rows = services.cashier_performance()
    assert rows == []


def test_reports_page_shows_cashier_table(client, admin, cashier, location):
    p = seed_product(location, qty=10)
    login(client, "cashier1")
    client.post("/api/checkout", json={"items": [{"product_id": p.id, "quantity": 1}]})
    client.get("/logout")

    login(client, "admin1")
    res = client.get("/reports")
    assert b"Cashier performance" in res.data
    assert b"cashier1" in res.data
