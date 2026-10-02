"""Populate the database with demo locations, users, products and stock."""
from app import app
from models import db, Product, Location, User
import services

DEMO = [
    # sku, barcode, name, category, cost, sell, qty
    ("BEV-001", "6001001000015", "Cola 50cl", "Beverages", 120, 200, 40),
    ("BEV-002", "6001001000022", "Bottled Water 75cl", "Beverages", 60, 120, 8),
    ("SNK-001", "6001001000039", "Potato Chips", "Snacks", 150, 250, 6),
    ("SNK-002", "6001001000046", "Chocolate Bar", "Snacks", 90, 180, 25),
    ("HOU-001", "6001001000053", "Dish Soap 500ml", "Household", 300, 480, 5),
    ("HOU-002", "6001001000060", "Paper Towels", "Household", 220, 400, 30),
    ("GRO-001", "6001001000077", "Rice 1kg", "Groceries", 700, 950, 3),
    ("GRO-002", "6001001000084", "Cooking Oil 1L", "Groceries", 1200, 1600, 15),
]

with app.app_context():
    db.drop_all()
    db.create_all()

    main = Location(name="Main Store")
    branch = Location(name="Branch Store")
    db.session.add_all([main, branch])
    db.session.commit()

    admin = User(username="admin", role="admin")
    admin.set_password("admin123")
    cashier = User(username="cashier", role="cashier")
    cashier.set_password("cashier123")
    db.session.add_all([admin, cashier])
    db.session.commit()

    for sku, barcode, name, cat, cost, sell, qty in DEMO:
        p = Product(sku=sku, barcode=barcode, name=name, category=cat,
                   cost_price=cost, sell_price=sell)
        db.session.add(p)
        db.session.flush()
        services.adjust_stock(p.id, main.id, qty, reason="received", note="Seed data", check=False)

    print(f"Seeded {len(DEMO)} products across 2 locations.")
    print("Login as admin: admin / admin123")
    print("Login as cashier: cashier / cashier123")
    fired = services.check_low_stock()
    print("Low-stock alerts fired for:", fired)
