"""Paynow (card/EcoCash/OneMoney) checkout flow.

Never calls the real Paynow API - `payments.start_card_payment`,
`payments.start_mobile_payment` and `payments.poll_status` are monkeypatched
per-test, since app.py and services.py both `import payments` (not
`from payments import x`), so patching attributes on the module object
affects both call sites.
"""
from tests.conftest import login
from models import db, Product, Sale
import payments
import services


def seed_product(location, qty=20, cost=10, sell=20):
    p = Product(sku="SKU-1", name="Widget", cost_price=cost, sell_price=sell)
    db.session.add(p)
    db.session.flush()
    services.adjust_stock(p.id, location.id, qty, reason="received")
    return p


def test_card_checkout_rejected_when_paynow_not_configured(client, admin, location, monkeypatch):
    monkeypatch.setattr(payments, "configured", lambda: False)
    login(client, "admin1")
    p = seed_product(location)
    res = client.post("/api/checkout", json={
        "items": [{"product_id": p.id, "quantity": 1}], "payment_method": "card",
    })
    assert res.status_code == 400
    assert "aren't configured" in res.get_json()["error"]
    assert Product.query.get(p.id).quantity == 20  # untouched


def test_ecocash_requires_mobile_number(client, admin, location, monkeypatch):
    monkeypatch.setattr(payments, "configured", lambda: True)
    login(client, "admin1")
    p = seed_product(location)
    res = client.post("/api/checkout", json={
        "items": [{"product_id": p.id, "quantity": 1}], "payment_method": "ecocash",
    })
    assert res.status_code == 400
    assert "phone number" in res.get_json()["error"]


def test_card_checkout_creates_pending_sale_without_touching_stock(client, admin, location, monkeypatch):
    monkeypatch.setattr(payments, "configured", lambda: True)
    monkeypatch.setattr(payments, "start_card_payment", lambda sale: {
        "success": True, "redirect_url": "https://paynow.co.zw/pay/abc", "poll_url": "https://paynow.co.zw/poll/abc",
    })
    login(client, "admin1")
    p = seed_product(location)
    res = client.post("/api/checkout", json={
        "items": [{"product_id": p.id, "quantity": 2}], "payment_method": "card",
    })
    data = res.get_json()
    assert data["ok"] is True
    assert data["pending"] is True
    assert data["redirect_url"] == "https://paynow.co.zw/pay/abc"

    sale = Sale.query.get(data["sale_id"])
    assert sale.status == "pending_payment"
    assert sale.paynow_poll_url == "https://paynow.co.zw/poll/abc"
    assert Product.query.get(p.id).quantity == 20  # not decremented yet


def test_poll_confirms_payment_and_settles_sale(client, admin, location, monkeypatch):
    monkeypatch.setattr(payments, "configured", lambda: True)
    monkeypatch.setattr(payments, "start_card_payment", lambda sale: {
        "success": True, "redirect_url": "https://paynow.co.zw/pay/abc", "poll_url": "https://paynow.co.zw/poll/abc",
    })
    login(client, "admin1")
    p = seed_product(location)
    res = client.post("/api/checkout", json={
        "items": [{"product_id": p.id, "quantity": 2}], "payment_method": "card",
    })
    sale_id = res.get_json()["sale_id"]

    monkeypatch.setattr(payments, "poll_status", lambda poll_url: {
        "ok": True, "paid": True, "status": "paid", "paynow_reference": "PN-999",
    })
    res = client.get(f"/payments/{sale_id}/status")
    data = res.get_json()
    assert data["status"] == "completed"

    sale = Sale.query.get(sale_id)
    assert sale.status == "completed"
    assert sale.paynow_reference == "PN-999"
    assert Product.query.get(p.id).quantity == 18  # decremented exactly once


def test_poll_cancelled_marks_failed_and_never_touches_stock(client, admin, location, monkeypatch):
    monkeypatch.setattr(payments, "configured", lambda: True)
    monkeypatch.setattr(payments, "start_card_payment", lambda sale: {
        "success": True, "redirect_url": "https://paynow.co.zw/pay/abc", "poll_url": "https://paynow.co.zw/poll/abc",
    })
    login(client, "admin1")
    p = seed_product(location)
    res = client.post("/api/checkout", json={
        "items": [{"product_id": p.id, "quantity": 2}], "payment_method": "card",
    })
    sale_id = res.get_json()["sale_id"]

    monkeypatch.setattr(payments, "poll_status", lambda poll_url: {
        "ok": True, "paid": False, "status": "cancelled", "paynow_reference": None,
    })
    res = client.get(f"/payments/{sale_id}/status")
    assert res.get_json()["status"] == "failed"
    assert Product.query.get(p.id).quantity == 20  # never reserved, nothing to restore


def test_poll_still_in_progress_keeps_sale_pending(client, admin, location, monkeypatch):
    monkeypatch.setattr(payments, "configured", lambda: True)
    monkeypatch.setattr(payments, "start_card_payment", lambda sale: {
        "success": True, "redirect_url": "https://paynow.co.zw/pay/abc", "poll_url": "https://paynow.co.zw/poll/abc",
    })
    login(client, "admin1")
    p = seed_product(location)
    res = client.post("/api/checkout", json={
        "items": [{"product_id": p.id, "quantity": 1}], "payment_method": "card",
    })
    sale_id = res.get_json()["sale_id"]

    monkeypatch.setattr(payments, "poll_status", lambda poll_url: {
        "ok": True, "paid": False, "status": "created", "paynow_reference": None,
    })
    res = client.get(f"/payments/{sale_id}/status")
    assert res.get_json()["status"] == "pending"
    assert Sale.query.get(sale_id).status == "pending_payment"


def test_mobile_payment_start_failure_marks_sale_failed(client, admin, location, monkeypatch):
    monkeypatch.setattr(payments, "configured", lambda: True)
    monkeypatch.setattr(payments, "start_mobile_payment", lambda sale, phone, method: {
        "success": False, "error": "Insufficient balance",
    })
    login(client, "admin1")
    p = seed_product(location)
    res = client.post("/api/checkout", json={
        "items": [{"product_id": p.id, "quantity": 1}],
        "payment_method": "ecocash", "mobile_number": "0771111111",
    })
    assert res.status_code == 400
    assert "Insufficient balance" in res.get_json()["error"]

    sale = Sale.query.filter_by(location_id=location.id).order_by(Sale.id.desc()).first()
    assert sale.status == "failed"
    assert Product.query.get(p.id).quantity == 20


def test_cannot_refund_a_pending_sale(client, admin, location, monkeypatch):
    monkeypatch.setattr(payments, "configured", lambda: True)
    monkeypatch.setattr(payments, "start_card_payment", lambda sale: {
        "success": True, "redirect_url": "https://paynow.co.zw/pay/abc", "poll_url": "https://paynow.co.zw/poll/abc",
    })
    login(client, "admin1")
    p = seed_product(location)
    res = client.post("/api/checkout", json={
        "items": [{"product_id": p.id, "quantity": 1}], "payment_method": "card",
    })
    sale_id = res.get_json()["sale_id"]

    res = client.post(f"/sales/{sale_id}/refund", data={"reason": "test"}, follow_redirects=True)
    assert res.status_code == 200
    sale = Sale.query.get(sale_id)
    assert sale.status == "pending_payment"  # refund_sale refused, no state change
    assert Product.query.get(p.id).quantity == 20
