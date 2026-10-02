from tests.conftest import login
from models import db, Product


def create_product(client, **overrides):
    data = {
        "sku": "SKU-1", "barcode": "12345", "name": "Widget",
        "category": "General", "cost_price": "10", "sell_price": "20", "quantity": "50",
    }
    data.update(overrides)
    return client.post("/products/save", data=data, follow_redirects=True)


def test_cashier_cannot_access_products(client, cashier):
    login(client, "cashier1")
    res = client.get("/products")
    assert res.status_code == 403


def test_admin_can_create_and_list_product(client, admin):
    login(client, "admin1")
    res = create_product(client)
    assert res.status_code == 200
    assert b"Widget" in res.data
    p = Product.query.filter_by(sku="SKU-1").first()
    assert p is not None
    assert p.quantity == 50


def test_admin_can_edit_product(client, admin):
    login(client, "admin1")
    create_product(client)
    p = Product.query.filter_by(sku="SKU-1").first()
    res = client.post("/products/save", data={
        "id": p.id, "sku": "SKU-1", "barcode": "12345", "name": "Widget XL",
        "category": "General", "cost_price": "12", "sell_price": "25",
    }, follow_redirects=True)
    assert b"Widget XL" in res.data
    assert Product.query.get(p.id).sell_price == 25


def test_admin_can_delete_product(client, admin):
    login(client, "admin1")
    create_product(client)
    p = Product.query.filter_by(sku="SKU-1").first()
    client.post(f"/products/{p.id}/delete", follow_redirects=True)
    assert Product.query.get(p.id) is None


def test_barcode_lookup(client, admin):
    login(client, "admin1")
    create_product(client)
    res = client.get("/api/products/barcode/12345")
    assert res.status_code == 200
    assert res.get_json()["name"] == "Widget"


def test_barcode_lookup_missing(client, admin):
    login(client, "admin1")
    res = client.get("/api/products/barcode/nope")
    assert res.status_code == 404


def test_admin_can_adjust_stock(client, admin):
    login(client, "admin1")
    create_product(client)
    p = Product.query.filter_by(sku="SKU-1").first()
    client.post(f"/products/{p.id}/adjust", data={
        "delta": "-5", "reason": "damage", "note": "broken box",
    }, follow_redirects=True)
    assert Product.query.get(p.id).quantity == 45


def test_ajax_adjust_returns_json_without_flash(client, admin):
    login(client, "admin1")
    create_product(client)
    p = Product.query.filter_by(sku="SKU-1").first()
    res = client.post(f"/products/{p.id}/adjust",
                      data={"delta": "3", "reason": "received", "note": "scanned"},
                      headers={"X-Requested-With": "fetch"})
    assert res.status_code == 200
    assert res.get_json() == {"ok": True}
    assert Product.query.get(p.id).quantity == 53
    # No flash message should be queued for the next normal page load.
    with client.session_transaction() as sess:
        assert "_flashes" not in sess


def test_receive_by_barcode_lookup_then_adjust(client, admin):
    login(client, "admin1")
    create_product(client)
    p = Product.query.filter_by(sku="SKU-1").first()

    res = client.get("/api/products/barcode/12345")
    assert res.status_code == 200
    found = res.get_json()
    assert found["quantity"] == 50

    client.post(f"/products/{found['id']}/adjust",
               data={"delta": "1", "reason": "received", "note": "Received via barcode scan"},
               headers={"X-Requested-With": "fetch"})
    assert Product.query.get(p.id).quantity == 51


def test_receive_unknown_barcode_returns_404_for_create_flow(client, admin):
    login(client, "admin1")
    res = client.get("/api/products/barcode/9999999999")
    assert res.status_code == 404
