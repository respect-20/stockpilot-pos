"""Business logic: alerts, demand analysis, profit/loss, stock, refunds."""
import csv
import io
from datetime import datetime, timedelta

from sqlalchemy import func

from config import Config
from models import db, Product, Sale, SaleItem, Stock, StockAdjustment, Location, User
from notifications import notify_admin
import payments


def get_or_create_default_location():
    loc = Location.query.first()
    if not loc:
        loc = Location(name="Main Store")
        db.session.add(loc)
        db.session.commit()
    return loc


def stock_for(product_id, location_id):
    return Stock.query.filter_by(product_id=product_id, location_id=location_id).first()


def get_or_create_stock(product_id, location_id):
    s = stock_for(product_id, location_id)
    if not s:
        s = Stock(product_id=product_id, location_id=location_id, quantity=0)
        db.session.add(s)
        db.session.flush()
    return s


def adjust_stock(product_id, location_id, delta, reason, note=None, user_id=None, check=True):
    """Apply a signed quantity change and record an audit entry.

    Pass check=False when batching several adjustments (e.g. a multi-item
    checkout) and call check_low_stock() once yourself afterwards.
    """
    s = get_or_create_stock(product_id, location_id)
    s.quantity = max(0, s.quantity + delta)
    db.session.add(StockAdjustment(
        product_id=product_id, location_id=location_id, delta=delta,
        reason=reason, note=note, user_id=user_id,
    ))
    db.session.commit()
    if check:
        check_low_stock()
    return s


def check_low_stock(force=False):
    """Alert admin about products at or below the low-stock threshold.

    Sends one alert per product+location when it first drops to/below the
    threshold (tracked via `low_stock_alerted`) so the admin is not spammed.
    Re-arms automatically once restocked above the threshold.
    """
    threshold = Config.LOW_STOCK_THRESHOLD
    triggered = []
    for s in Stock.query.all():
        if s.quantity > threshold and s.low_stock_alerted:
            s.low_stock_alerted = False  # restocked, allow future alerts
        if s.quantity <= threshold and (force or not s.low_stock_alerted):
            p = s.product
            loc_name = s.location.name if s.location else "?"
            msg = (f"⚠️ LOW STOCK: '{p.name}' (SKU {p.sku}) at {loc_name} is down to "
                   f"{s.quantity} units (threshold {threshold}). Reorder soon.")
            notify_admin("low_stock", msg)
            s.low_stock_alerted = True
            triggered.append(f"{p.name} @ {loc_name}")
    db.session.commit()
    return triggered


def demand_report(days=None, min_units=None):
    """Return products in demand within the recent window."""
    days = days or Config.DEMAND_WINDOW_DAYS
    min_units = min_units or Config.DEMAND_MIN_UNITS
    since = datetime.utcnow() - timedelta(days=days)
    rows = (db.session.query(
                SaleItem.product_id,
                SaleItem.product_name,
                func.sum(SaleItem.quantity).label("units"),
                func.sum((SaleItem.unit_price - SaleItem.unit_cost)
                         * SaleItem.quantity).label("profit"))
            .join(Sale, Sale.id == SaleItem.sale_id)
            .filter(SaleItem.created_at >= since, Sale.status == "completed")
            .group_by(SaleItem.product_id, SaleItem.product_name)
            .order_by(func.sum(SaleItem.quantity).desc())
            .all())
    result = []
    for r in rows:
        result.append({
            "product": r.product_name,
            "units": int(r.units or 0),
            "profit": round(float(r.profit or 0), 2),
            "on_demand": (r.units or 0) >= min_units,
        })
    return result


def profit_loss(days=None):
    """Aggregate revenue, cost and profit within the window (completed sales only)."""
    days = days or Config.DEMAND_WINDOW_DAYS
    since = datetime.utcnow() - timedelta(days=days)
    items = (SaleItem.query.join(Sale, Sale.id == SaleItem.sale_id)
             .filter(SaleItem.created_at >= since, Sale.status == "completed").all())
    revenue = sum(i.unit_price * i.quantity for i in items)
    cost = sum(i.unit_cost * i.quantity for i in items)
    profit = revenue - cost
    return {
        "window_days": days,
        "revenue": round(revenue, 2),
        "cost": round(cost, 2),
        "profit": round(profit, 2),
        "status": "PROFIT" if profit > 0 else ("LOSS" if profit < 0 else "BREAK-EVEN"),
    }


def cashier_performance(days=None):
    """Per-cashier sales count, revenue and average sale within the window.

    Completed sales only, so a sale that's still pending_payment or was
    later refunded doesn't inflate (or distort) anyone's numbers.
    """
    days = days or Config.DEMAND_WINDOW_DAYS
    since = datetime.utcnow() - timedelta(days=days)

    rows = (db.session.query(
                Sale.user_id,
                func.count(Sale.id).label("sales_count"),
                func.sum(Sale.total).label("revenue"),
                func.sum(Sale.profit).label("profit"))
            .filter(Sale.created_at >= since, Sale.status == "completed")
            .group_by(Sale.user_id)
            .all())

    usernames = {u.id: u.username for u in User.query.all()}

    result = []
    for row in rows:
        revenue = round(float(row.revenue or 0), 2)
        sales_count = row.sales_count
        result.append({
            "user_id": row.user_id,
            "username": usernames.get(row.user_id, "Unknown"),
            "sales_count": sales_count,
            "revenue": revenue,
            "profit": round(float(row.profit or 0), 2),
            "avg_sale": round(revenue / sales_count, 2) if sales_count else 0.0,
        })
    result.sort(key=lambda r: r["sales_count"], reverse=True)
    return result


def send_admin_digest():
    """Compose and send the on-demand + profit/loss digest to the admin."""
    demand = [d for d in demand_report() if d["on_demand"]]
    pl = profit_loss()
    top = ", ".join(f"{d['product']} ({d['units']}u)" for d in demand[:5]) or "none yet"
    msg = (f"\U0001f4ca Dhingani Investment digest ({pl['window_days']}d)\n"
           f"Status: {pl['status']} | Revenue {pl['revenue']} | "
           f"Cost {pl['cost']} | Profit {pl['profit']}\n"
           f"On demand: {top}")
    notify_admin("digest", msg)
    return {"demand": demand, "profit_loss": pl}


def refund_sale(sale, reason, user):
    """Void a completed sale: restore stock, mark refunded, log it."""
    if sale.status != "completed":
        return False
    for item in sale.items:
        if sale.location_id:
            adjust_stock(item.product_id, sale.location_id, item.quantity,
                         reason="refund", note=f"Refund of sale #{sale.id}",
                         user_id=user.id if user else None, check=False)
    check_low_stock()
    sale.status = "refunded"
    sale.refunded_at = datetime.utcnow()
    sale.refunded_by_id = user.id if user else None
    sale.refund_reason = reason
    db.session.commit()
    notify_admin("refund", f"↩️ Sale #{sale.id} refunded ({sale.total}). Reason: {reason or 'n/a'}")
    return True


PAYNOW_FAILURE_STATUSES = {"cancelled", "disputed", "error"}


def finalize_pending_sale(sale):
    """Poll Paynow for a pending_payment sale and settle it if the gateway has a verdict.

    Idempotent: calling this on an already-settled sale just reports its
    current status without touching stock again. Stock is only ever
    decremented here, once, on the transition into 'completed'.
    """
    if sale.status != "pending_payment":
        return {"status": sale.status}
    if not sale.paynow_poll_url:
        return {"status": sale.status, "error": "No payment in progress for this sale."}

    result = payments.poll_status(sale.paynow_poll_url)
    if not result["ok"]:
        return {"status": "pending", "error": result["error"]}

    if result["paid"]:
        for item in sale.items:
            adjust_stock(item.product_id, sale.location_id, -item.quantity,
                        reason="sale", note=f"Sale #{sale.id} (Paynow)",
                        user_id=sale.user_id, check=False)
        sale.status = "completed"
        sale.paynow_reference = result.get("paynow_reference")
        db.session.commit()
        check_low_stock()
        return {"status": "completed"}

    if result["status"] in PAYNOW_FAILURE_STATUSES:
        sale.status = "failed"
        sale.payment_error = f"Payment {result['status']}."
        db.session.commit()
        return {"status": "failed", "error": sale.payment_error}

    return {"status": "pending"}


def sales_csv(start=None, end=None):
    """Return a CSV string of sales (and their line items) in the given range."""
    q = Sale.query.order_by(Sale.created_at.asc())
    if start:
        q = q.filter(Sale.created_at >= start)
    if end:
        q = q.filter(Sale.created_at <= end)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["sale_id", "date", "location", "cashier", "product", "quantity",
               "unit_price", "unit_cost", "line_total", "payment_method", "status"])
    for s in q.all():
        for item in s.items:
            w.writerow([
                s.id, s.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                s.location.name if s.location else "",
                s.cashier.username if s.cashier else "",
                item.product_name, item.quantity, item.unit_price, item.unit_cost,
                item.line_total, s.payment_method, s.status,
            ])
    return buf.getvalue()
