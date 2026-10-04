"""Dhingani Investment - a lightweight point-of-sale + inventory app.

Run:  python app.py   (serves on http://127.0.0.1:5000)
"""
import os
from datetime import datetime
from functools import wraps

from flask import (Flask, Response, render_template, request, redirect,
                   url_for, jsonify, flash, session, abort)
from flask_login import (LoginManager, login_user, logout_user,
                         login_required, current_user)

from config import Config
from models import (db, User, Location, Product, Stock, StockAdjustment,
                    Sale, SaleItem, Notification)
import services
import payments


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return fn(*args, **kwargs)
    return wrapper


def create_app(config_overrides=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if config_overrides:
        app.config.update(config_overrides)
    db.init_app(app)

    login_manager = LoginManager()
    login_manager.login_view = "login"
    login_manager.init_app(app)

    @app.template_filter("usd")
    def usd_filter(value):
        try:
            value = float(value or 0)
        except (TypeError, ValueError):
            value = 0.0
        sign = "-" if value < 0 else ""
        return f"{sign}${abs(value):,.2f}"

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    with app.app_context():
        db.create_all()
        services.get_or_create_default_location()

    register_routes(app)
    start_scheduler(app)
    return app


def current_location():
    """The location the current user is operating from (session-selected).

    Admins get a sensible default (first location) if they haven't picked
    one yet, since they're free to switch anytime. Cashiers never get an
    implicit default here - the require_location_for_cashiers before_request
    hook forces them through /choose-location first, so by the time any
    route body runs, a cashier's session already has one set.
    """
    loc_id = session.get("location_id")
    loc = db.session.get(Location, loc_id) if loc_id else None
    if not loc and current_user.is_authenticated and current_user.is_admin:
        loc = Location.query.order_by(Location.id).first()
        if loc:
            session["location_id"] = loc.id
    return loc


def register_routes(app):

    @app.context_processor
    def inject_globals():
        return {
            "locations": Location.query.order_by(Location.name).all(),
            "active_location": current_location(),
        }

    @app.before_request
    def require_location_for_cashiers():
        """Cashiers must pick a store before doing anything else, and stay
        locked to it until they log out. Admins are exempt - they keep the
        free-switching dropdown they already have."""
        if not current_user.is_authenticated or current_user.is_admin:
            return
        if request.endpoint in ("choose_location", "logout", "static"):
            return
        if "location_id" in session:
            return
        locations = Location.query.order_by(Location.id).all()
        if len(locations) <= 1:
            # Nothing to choose between - assign the only store and move on.
            if locations:
                session["location_id"] = locations[0].id
            return
        return redirect(url_for("choose_location"))

    # ---------- Auth ----------
    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            user = User.query.filter_by(username=username).first()
            if user and user.active and user.check_password(password):
                login_user(user)
                flash(f"Welcome back, {user.username}.")
                return redirect(request.args.get("next") or url_for("dashboard"))
            flash("Invalid username or password.")
        return render_template("login.html")

    @app.route("/logout")
    @login_required
    def logout():
        # Cashiers re-pick their store on next login; clearing it here is
        # what makes "log out to switch stores" actually true.
        session.pop("location_id", None)
        logout_user()
        return redirect(url_for("login"))

    @app.route("/choose-location", methods=["GET", "POST"])
    @login_required
    def choose_location():
        locations = Location.query.order_by(Location.name).all()
        if request.method == "POST":
            loc = db.session.get(Location, request.form.get("location_id", type=int))
            if loc:
                session["location_id"] = loc.id
                return redirect(url_for("dashboard"))
            flash("Pick a store to continue.")
        return render_template("choose_location.html", locations=locations)

    @app.route("/set-location", methods=["POST"])
    @login_required
    @admin_required
    def set_location():
        loc_id = request.form.get("location_id", type=int)
        if db.session.get(Location, loc_id):
            session["location_id"] = loc_id
        return redirect(request.referrer or url_for("dashboard"))

    # ---------- Dashboard ----------
    @app.route("/")
    @login_required
    def dashboard():
        pl = services.profit_loss()
        demand = services.demand_report()
        low_stocks = (Stock.query.join(Product)
                     .filter(Stock.quantity <= app.config["LOW_STOCK_THRESHOLD"])
                     .order_by(Stock.quantity).all())
        return render_template("dashboard.html", pl=pl, demand=demand,
                               low=low_stocks, threshold=app.config["LOW_STOCK_THRESHOLD"])

    # ---------- Products ----------
    @app.route("/products")
    @login_required
    @admin_required
    def products():
        q = request.args.get("q", "").strip()
        page = request.args.get("page", 1, type=int)
        query = Product.query
        if q:
            like = f"%{q}%"
            query = query.filter(db.or_(Product.name.ilike(like),
                                        Product.sku.ilike(like),
                                        Product.barcode.ilike(like)))
        pager = query.order_by(Product.name).paginate(
            page=page, per_page=app.config["PAGE_SIZE"], error_out=False)
        return render_template("products.html", pager=pager, products=pager.items,
                               threshold=app.config["LOW_STOCK_THRESHOLD"], q=q)

    @app.route("/products/save", methods=["POST"])
    @login_required
    @admin_required
    def save_product():
        pid = request.form.get("id")
        p = db.session.get(Product, int(pid)) if pid else Product()
        p.sku = request.form["sku"].strip()
        p.barcode = (request.form.get("barcode") or "").strip() or None
        p.name = request.form["name"].strip()
        p.category = request.form.get("category", "General").strip() or "General"
        p.cost_price = float(request.form.get("cost_price", 0) or 0)
        p.sell_price = float(request.form.get("sell_price", 0) or 0)
        p.updated_by_id = current_user.id
        is_new = not pid
        if is_new:
            db.session.add(p)
            db.session.flush()
            init_qty = int(request.form.get("quantity", 0) or 0)
            loc = current_location()
            if loc and init_qty:
                services.adjust_stock(p.id, loc.id, init_qty, reason="received",
                                      note="Initial stock on product creation",
                                      user_id=current_user.id)
        db.session.commit()
        services.check_low_stock()
        flash(f"Saved '{p.name}'.")
        return redirect(url_for("products"))

    @app.route("/products/<int:pid>/delete", methods=["POST"])
    @login_required
    @admin_required
    def delete_product(pid):
        p = db.session.get(Product, pid) or abort(404)
        db.session.delete(p)
        db.session.commit()
        flash(f"Deleted '{p.name}'.")
        return redirect(url_for("products"))

    @app.route("/products/<int:pid>/adjust", methods=["POST"])
    @login_required
    @admin_required
    def adjust_stock_route(pid):
        p = db.session.get(Product, pid) or abort(404)
        delta = int(request.form.get("delta", 0) or 0)
        reason = request.form.get("reason", "correction")
        note = request.form.get("note", "").strip() or None
        loc = current_location()
        if delta and loc:
            services.adjust_stock(p.id, loc.id, delta, reason, note, current_user.id)
            if request.headers.get("X-Requested-With") != "fetch":
                flash(f"Adjusted '{p.name}' by {delta:+d} at {loc.name}.")
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify({"ok": True})
        return redirect(url_for("products"))

    @app.route("/api/products/barcode/<code>")
    @login_required
    def lookup_barcode(code):
        p = Product.query.filter_by(barcode=code).first()
        if not p:
            return jsonify({"error": "not found"}), 404
        loc = current_location()
        return jsonify(p.to_dict(location_id=loc.id if loc else None))

    # ---------- Sales / checkout ----------
    @app.route("/sales")
    @login_required
    def sales():
        loc = current_location()
        products_list = Product.query.order_by(Product.name).all()
        available = [p for p in products_list if not loc or p.quantity_at(loc.id) > 0]
        recent_q = Sale.query.order_by(Sale.created_at.desc())
        if not current_user.is_admin:
            recent_q = recent_q.filter_by(user_id=current_user.id)
        return render_template("sales.html", products=available, recent=recent_q.limit(10).all(),
                               tax_rate=app.config["TAX_RATE"])

    GATEWAY_METHODS = {"card", "ecocash", "onemoney"}

    @app.route("/api/checkout", methods=["POST"])
    @login_required
    def checkout():
        data = request.get_json(force=True)
        cart = data.get("items", [])
        payment_method = data.get("payment_method", "cash")
        mobile_number = (data.get("mobile_number") or "").strip()
        discount_amount = max(0.0, float(data.get("discount_amount", 0) or 0))
        loc = current_location()
        if not cart:
            return jsonify({"error": "Cart is empty"}), 400
        if not loc:
            return jsonify({"error": "No location configured"}), 400

        is_gateway = payment_method in GATEWAY_METHODS
        if is_gateway and not payments.configured():
            return jsonify({"error": "Card/mobile money payments aren't configured. "
                                     "Set PAYNOW_INTEGRATION_ID and PAYNOW_INTEGRATION_KEY in .env."}), 400
        if payment_method in ("ecocash", "onemoney") and not mobile_number:
            return jsonify({"error": "A phone number is required for EcoCash/OneMoney."}), 400

        sale = Sale(location_id=loc.id, user_id=current_user.id, payment_method=payment_method,
                   mobile_number=mobile_number or None,
                   status="pending_payment" if is_gateway else "completed")
        db.session.add(sale)
        subtotal = profit = 0.0
        for line in cart:
            p = db.session.get(Product, int(line["product_id"]))
            qty = int(line["quantity"])
            if not p or qty <= 0:
                continue
            stock = services.stock_for(p.id, loc.id)
            on_hand = stock.quantity if stock else 0
            if qty > on_hand:
                return jsonify({"error": f"Not enough stock for {p.name}"}), 400
            item = SaleItem(sale=sale, product_id=p.id, product_name=p.name,
                            quantity=qty, unit_price=p.sell_price,
                            unit_cost=p.cost_price)
            db.session.add(item)
            subtotal += p.sell_price * qty
            profit += (p.sell_price - p.cost_price) * qty

        discount_amount = min(discount_amount, subtotal)
        taxable = max(0.0, subtotal - discount_amount)
        tax_amount = round(taxable * app.config["TAX_RATE"], 2)
        total = round(taxable + tax_amount, 2)
        profit = round(profit - discount_amount, 2)

        sale.subtotal = round(subtotal, 2)
        sale.discount_amount = round(discount_amount, 2)
        sale.tax_amount = tax_amount
        sale.total = total
        sale.profit = profit
        db.session.flush()

        if not is_gateway:
            # Cash/other: payment already happened in person, settle immediately.
            for item in sale.items:
                services.adjust_stock(item.product_id, loc.id, -item.quantity,
                                      reason="sale", note=f"Sale #{sale.id}",
                                      user_id=current_user.id, check=False)
            db.session.commit()
            triggered = services.check_low_stock()
            return jsonify({"ok": True, "sale_id": sale.id, "total": sale.total,
                            "profit": sale.profit, "low_stock_alerts": triggered})

        # Card/EcoCash/OneMoney: nothing is charged yet and stock is NOT
        # reserved - Paynow confirms (or doesn't) via polling, and only
        # then does finalize_pending_sale() touch stock.
        if payment_method == "card":
            result = payments.start_card_payment(sale)
        else:
            result = payments.start_mobile_payment(sale, mobile_number, payment_method)

        if not result["success"]:
            sale.status = "failed"
            sale.payment_error = str(result["error"])[:255]
            db.session.commit()
            return jsonify({"error": f"Payment could not be started: {result['error']}"}), 400

        sale.paynow_poll_url = result["poll_url"]
        db.session.commit()

        if payment_method == "card":
            return jsonify({"ok": True, "pending": True, "sale_id": sale.id,
                            "redirect_url": result["redirect_url"]})
        return jsonify({"ok": True, "pending": True, "sale_id": sale.id,
                        "instructions": result["instructions"]})

    @app.route("/payments/<int:sid>/status")
    @login_required
    def payment_status(sid):
        sale = db.session.get(Sale, sid) or abort(404)
        if not current_user.is_admin and sale.user_id != current_user.id:
            abort(403)
        result = services.finalize_pending_sale(sale)
        return jsonify(result)

    @app.route("/sales/<int:sid>/payment-return")
    @login_required
    def payment_return(sid):
        sale = db.session.get(Sale, sid) or abort(404)
        if not current_user.is_admin and sale.user_id != current_user.id:
            abort(403)
        services.finalize_pending_sale(sale)
        return redirect(url_for("receipt", sid=sale.id))

    @app.route("/payments/webhook", methods=["POST"])
    def payment_webhook():
        # Best-effort fast path for a publicly-deployed instance - this app
        # never depends on it firing (see payments.py). Not login-protected
        # since Paynow calls it directly; verified by hash instead.
        data = request.form.to_dict()
        if not payments.verify_webhook_hash(data):
            return "", 400
        reference = data.get("reference", "")
        if not reference.startswith("sale-"):
            return "", 400
        try:
            sale_id = int(reference.split("-", 1)[1])
        except ValueError:
            return "", 400
        sale = db.session.get(Sale, sale_id)
        if sale:
            services.finalize_pending_sale(sale)
        return "", 200

    @app.route("/sales/<int:sid>/receipt")
    @login_required
    def receipt(sid):
        sale = db.session.get(Sale, sid) or abort(404)
        if not current_user.is_admin and sale.user_id != current_user.id:
            abort(403)
        return render_template("receipt.html", sale=sale)

    @app.route("/sales/<int:sid>/refund", methods=["POST"])
    @login_required
    @admin_required
    def refund(sid):
        sale = db.session.get(Sale, sid) or abort(404)
        reason = request.form.get("reason", "").strip()
        if services.refund_sale(sale, reason, current_user):
            flash(f"Sale #{sale.id} refunded.")
        else:
            flash(f"Sale #{sale.id} can't be refunded (status: {sale.status}).")
        return redirect(url_for("receipt", sid=sale.id))

    # ---------- Reports ----------
    @app.route("/reports")
    @login_required
    @admin_required
    def reports():
        days = int(request.args.get("days", app.config["DEMAND_WINDOW_DAYS"]))
        page = request.args.get("page", 1, type=int)
        notif_pager = (Notification.query.order_by(Notification.created_at.desc())
                      .paginate(page=page, per_page=app.config["PAGE_SIZE"], error_out=False))
        return render_template("reports.html",
                               pl=services.profit_loss(days),
                               demand=services.demand_report(days),
                               cashiers=services.cashier_performance(days),
                               notif_pager=notif_pager,
                               notifications=notif_pager.items,
                               days=days)

    @app.route("/reports/export.csv")
    @login_required
    @admin_required
    def export_csv():
        csv_data = services.sales_csv()
        return Response(csv_data, mimetype="text/csv", headers={
            "Content-Disposition": f"attachment; filename=stockpilot-sales-{datetime.utcnow().date()}.csv"
        })

    @app.route("/api/send-digest", methods=["POST"])
    @login_required
    @admin_required
    def send_digest():
        return jsonify(services.send_admin_digest())

    @app.route("/api/check-stock", methods=["POST"])
    @login_required
    @admin_required
    def api_check_stock():
        return jsonify({"alerted": services.check_low_stock(force=True)})

    # ---------- Locations ----------
    @app.route("/locations", methods=["GET", "POST"])
    @login_required
    @admin_required
    def locations():
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            if name and not Location.query.filter_by(name=name).first():
                db.session.add(Location(name=name))
                db.session.commit()
                flash(f"Added location '{name}'.")
            return redirect(url_for("locations"))
        return render_template("locations.html", locations=Location.query.order_by(Location.name).all())

    # ---------- Users ----------
    @app.route("/users", methods=["GET", "POST"])
    @login_required
    @admin_required
    def users():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            role = request.form.get("role", "cashier")
            if not username or not password:
                flash("Username and password are required.")
            elif User.query.filter_by(username=username).first():
                flash("That username already exists.")
            else:
                u = User(username=username, role=role)
                u.set_password(password)
                db.session.add(u)
                db.session.commit()
                flash(f"Created user '{username}'.")
            return redirect(url_for("users"))
        return render_template("users.html", users=User.query.order_by(User.username).all())

    @app.route("/users/<int:uid>/toggle", methods=["POST"])
    @login_required
    @admin_required
    def toggle_user(uid):
        u = db.session.get(User, uid) or abort(404)
        if u.id == current_user.id:
            flash("You cannot deactivate your own account.")
        else:
            u.active = not u.active
            db.session.commit()
            flash(f"{u.username} is now {'active' if u.active else 'inactive'}.")
        return redirect(url_for("users"))

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("error.html", code=403,
                               message="You don't have permission to view this page."), 403


def start_scheduler(app):
    """Optionally auto-send the admin digest daily at DIGEST_HOUR.

    The WERKZEUG_RUN_MAIN check below only guards against Flask's own dev
    reloader spawning this twice - it does nothing under a WSGI server like
    gunicorn, which never sets that variable. Running more than one gunicorn
    worker would start one of these schedulers per worker and fire the
    digest multiple times, so deployment must use a single worker
    (see Dockerfile: `gunicorn -w 1 ...`).
    """
    if not app.config["DIGEST_HOUR"]:
        return
    if os.environ.get("WERKZEUG_RUN_MAIN") not in (None, "true"):
        return
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        print("[scheduler] apscheduler not installed; skipping automated digest.")
        return

    hour = int(app.config["DIGEST_HOUR"])
    scheduler = BackgroundScheduler(daemon=True)

    def job():
        with app.app_context():
            services.send_admin_digest()

    scheduler.add_job(job, "cron", hour=hour, id="daily_digest", replace_existing=True)
    scheduler.start()


app = create_app()

if __name__ == "__main__":
    # Bind to localhost only.
    app.run(host="127.0.0.1", port=5000, debug=True)
