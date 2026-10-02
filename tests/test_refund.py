from tests.conftest import login
from models import db, Product, Sale
import services


def seed_and_sell(client, location, qty=20):
    p = Product(sku="SKU-1", name="Widget", cost_price=10, sell_price=20)
    db.session.add(p)
    db.session.flush()
    services.adjust_stock(p.id, location.id, qty, reason="received")
    res = client.post("/api/checkout", json={"items": [{"product_id": p.id, "quantity": 3}]})
    sale_id = res.get_json()["sale_id"]
    return p, sale_id


def test_admin_can_refund_and_stock_is_restored(client, admin, location):
    login(client, "admin1")
    p, sale_id = seed_and_sell(client, location, qty=20)
    assert Product.query.get(p.id).quantity == 17
    res = client.post(f"/sales/{sale_id}/refund", data={"reason": "customer changed mind"},
                      follow_redirects=True)
    assert res.status_code == 200
    assert Product.query.get(p.id).quantity == 20
    sale = Sale.query.get(sale_id)
    assert sale.status == "refunded"
    assert sale.refund_reason == "customer changed mind"


def test_cashier_cannot_refund(client, admin, cashier, location):
    login(client, "admin1")
    p, sale_id = seed_and_sell(client, location, qty=20)
    client.get("/logout")
    login(client, "cashier1")
    res = client.post(f"/sales/{sale_id}/refund", data={"reason": "x"})
    assert res.status_code == 403
    assert Sale.query.get(sale_id).status == "completed"


def test_double_refund_is_a_noop(client, admin, location):
    login(client, "admin1")
    _, sale_id = seed_and_sell(client, location, qty=20)
    client.post(f"/sales/{sale_id}/refund", data={"reason": "first"})
    sale = Sale.query.get(sale_id)
    qty_after_first = Product.query.get(sale.items[0].product_id).quantity
    client.post(f"/sales/{sale_id}/refund", data={"reason": "second"})
    assert Product.query.get(sale.items[0].product_id).quantity == qty_after_first
