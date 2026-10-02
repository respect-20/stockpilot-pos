import json

from tests.conftest import login
from models import db, Product, Sale
import services


def seed_product(app, location, qty=20, cost=10, sell=20):
    p = Product(sku="SKU-1", name="Widget", cost_price=cost, sell_price=sell)
    db.session.add(p)
    db.session.flush()
    services.adjust_stock(p.id, location.id, qty, reason="received")
    return p


def test_checkout_decrements_stock_and_computes_tax(client, admin, location, app):
    login(client, "admin1")
    p = seed_product(app, location, qty=20, cost=10, sell=20)
    res = client.post("/api/checkout", json={
        "items": [{"product_id": p.id, "quantity": 3}],
        "discount_amount": 5,
        "payment_method": "cash",
    })
    data = res.get_json()
    assert data["ok"] is True
    # subtotal 60, discount 5 -> taxable 55, tax 10% -> 5.5, total 60.5
    assert data["total"] == 60.5
    assert Product.query.get(p.id).quantity == 17
    sale = Sale.query.get(data["sale_id"])
    assert sale.payment_method == "cash"
    assert sale.discount_amount == 5


def test_checkout_rejects_insufficient_stock(client, admin, location, app):
    login(client, "admin1")
    p = seed_product(app, location, qty=2)
    res = client.post("/api/checkout", json={"items": [{"product_id": p.id, "quantity": 5}]})
    assert res.status_code == 400
    assert "Not enough stock" in res.get_json()["error"]
    assert Product.query.get(p.id).quantity == 2


def test_checkout_rejects_empty_cart(client, admin):
    login(client, "admin1")
    res = client.post("/api/checkout", json={"items": []})
    assert res.status_code == 400


def test_low_stock_alert_fires_on_checkout(client, admin, location, app):
    login(client, "admin1")
    p = seed_product(app, location, qty=11)  # threshold is 10
    res = client.post("/api/checkout", json={"items": [{"product_id": p.id, "quantity": 2}]})
    data = res.get_json()
    assert any("Widget" in name for name in data["low_stock_alerts"])


def test_cashier_can_checkout(client, cashier, location, app):
    login(client, "cashier1")
    p = seed_product(app, location, qty=10)
    res = client.post("/api/checkout", json={"items": [{"product_id": p.id, "quantity": 1}]})
    assert res.get_json()["ok"] is True
