"""Cashiers must pick one store at login and stay locked to it until they
log out; admins keep free switching via the existing dropdown/endpoint."""
from tests.conftest import login
from models import db, Location


def add_second_location(name="Branch Store"):
    loc = Location(name=name)
    db.session.add(loc)
    db.session.commit()
    return loc


def test_cashier_with_multiple_locations_is_sent_to_picker(client, cashier, location):
    add_second_location()
    login(client, "cashier1")
    res = client.get("/sales", follow_redirects=True)
    assert res.status_code == 200
    assert b"Which store are you at?" in res.data


def test_cashier_single_location_skips_picker(client, cashier, location):
    # Only the one default location exists - nothing to choose between.
    login(client, "cashier1")
    res = client.get("/sales")
    assert res.status_code == 200
    assert b"Which store are you at?" not in res.data
    assert b"Sell / Checkout" in res.data


def test_cashier_choosing_a_store_unlocks_the_app(client, cashier, location):
    branch = add_second_location()
    login(client, "cashier1")
    res = client.post("/choose-location", data={"location_id": branch.id}, follow_redirects=True)
    assert res.status_code == 200
    assert b"Dashboard" in res.data

    with client.session_transaction() as sess:
        assert sess["location_id"] == branch.id

    res = client.get("/sales")
    assert b"Which store are you at?" not in res.data


def test_cashier_cannot_switch_store_without_logging_out(client, cashier, location):
    branch = add_second_location()
    login(client, "cashier1")
    client.post("/choose-location", data={"location_id": branch.id})

    # No UI exposes this to a cashier, and the endpoint itself is admin-only.
    res = client.post("/set-location", data={"location_id": location.id})
    assert res.status_code == 403

    with client.session_transaction() as sess:
        assert sess["location_id"] == branch.id  # unchanged


def test_logout_clears_location_so_cashier_rechooses(client, cashier, location):
    branch = add_second_location()
    login(client, "cashier1")
    client.post("/choose-location", data={"location_id": branch.id})
    client.get("/logout")

    login(client, "cashier1")
    res = client.get("/sales", follow_redirects=True)
    assert b"Which store are you at?" in res.data


def test_admin_is_never_forced_to_choose(client, admin, location):
    add_second_location()
    login(client, "admin1")
    res = client.get("/sales")
    assert res.status_code == 200
    assert b"Which store are you at?" not in res.data


def test_admin_can_still_switch_freely(client, admin, location):
    branch = add_second_location()
    login(client, "admin1")
    res = client.post("/set-location", data={"location_id": branch.id}, follow_redirects=True)
    assert res.status_code == 200
    with client.session_transaction() as sess:
        assert sess["location_id"] == branch.id
