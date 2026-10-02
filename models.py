"""Database models for Dhingani Investment."""
from datetime import datetime
from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(60), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default="cashier")  # admin | cashier
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return check_password_hash(self.password_hash, raw)

    @property
    def is_admin(self):
        return self.role == "admin"

    def get_id(self):
        return str(self.id)

    @property
    def is_active(self):
        return self.active


class Location(db.Model):
    __tablename__ = "locations"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Product(db.Model):
    __tablename__ = "products"
    id = db.Column(db.Integer, primary_key=True)
    sku = db.Column(db.String(40), unique=True, nullable=False)
    barcode = db.Column(db.String(64), unique=True, nullable=True)
    name = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(80), default="General")
    cost_price = db.Column(db.Float, default=0.0)   # what you pay
    sell_price = db.Column(db.Float, default=0.0)   # what customer pays
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    stocks = db.relationship("Stock", backref="product", cascade="all, delete-orphan")

    @property
    def margin(self):
        return round(self.sell_price - self.cost_price, 2)

    @property
    def quantity(self):
        """Total quantity across all locations."""
        return sum(s.quantity for s in self.stocks)

    def quantity_at(self, location_id):
        for s in self.stocks:
            if s.location_id == location_id:
                return s.quantity
        return 0

    def to_dict(self, location_id=None):
        qty = self.quantity_at(location_id) if location_id else self.quantity
        return {
            "id": self.id, "sku": self.sku, "barcode": self.barcode or "",
            "name": self.name, "category": self.category,
            "cost_price": self.cost_price, "sell_price": self.sell_price,
            "quantity": qty, "margin": self.margin,
        }


class Stock(db.Model):
    """Per-location quantity on hand for a product."""
    __tablename__ = "stocks"
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey("locations.id"), nullable=False)
    quantity = db.Column(db.Integer, default=0)
    low_stock_alerted = db.Column(db.Boolean, default=False)

    location = db.relationship("Location")

    __table_args__ = (db.UniqueConstraint("product_id", "location_id", name="uq_stock_product_location"),)


class StockAdjustment(db.Model):
    """Audit log of manual stock changes (receiving, corrections, etc.)."""
    __tablename__ = "stock_adjustments"
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey("locations.id"), nullable=False)
    delta = db.Column(db.Integer, nullable=False)  # positive = received, negative = correction/loss
    reason = db.Column(db.String(40))  # received | correction | damage | other
    note = db.Column(db.String(255))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    product = db.relationship("Product")
    location = db.relationship("Location")
    user = db.relationship("User")


class Sale(db.Model):
    __tablename__ = "sales"
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    location_id = db.Column(db.Integer, db.ForeignKey("locations.id"), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    subtotal = db.Column(db.Float, default=0.0)
    discount_amount = db.Column(db.Float, default=0.0)
    tax_amount = db.Column(db.Float, default=0.0)
    total = db.Column(db.Float, default=0.0)
    profit = db.Column(db.Float, default=0.0)
    payment_method = db.Column(db.String(20), default="cash")  # cash | card | ecocash | onemoney | other
    status = db.Column(db.String(20), default="completed")  # pending_payment | completed | failed | refunded
    refunded_at = db.Column(db.DateTime, nullable=True)
    refunded_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    refund_reason = db.Column(db.String(255), nullable=True)

    # Paynow (Zimbabwe gateway) fields - only set for card/ecocash/onemoney sales
    paynow_poll_url = db.Column(db.String(500), nullable=True)
    paynow_reference = db.Column(db.String(100), nullable=True)
    mobile_number = db.Column(db.String(30), nullable=True)
    payment_error = db.Column(db.String(255), nullable=True)

    items = db.relationship("SaleItem", backref="sale", cascade="all, delete-orphan")
    location = db.relationship("Location", foreign_keys=[location_id])
    cashier = db.relationship("User", foreign_keys=[user_id])
    refunded_by = db.relationship("User", foreign_keys=[refunded_by_id])


class SaleItem(db.Model):
    __tablename__ = "sale_items"
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey("sales.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    product_name = db.Column(db.String(120))
    quantity = db.Column(db.Integer, default=1)
    unit_price = db.Column(db.Float, default=0.0)
    unit_cost = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def line_profit(self):
        return round((self.unit_price - self.unit_cost) * self.quantity, 2)

    @property
    def line_total(self):
        return round(self.unit_price * self.quantity, 2)


class Notification(db.Model):
    __tablename__ = "notifications"
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    kind = db.Column(db.String(40))       # low_stock | demand | profit_loss | digest
    channel = db.Column(db.String(20))    # whatsapp | sms | log
    recipient = db.Column(db.String(60))
    message = db.Column(db.Text)
    status = db.Column(db.String(20))     # sent | failed | logged
