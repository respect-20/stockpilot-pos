# Dhingani Investment

A lightweight point-of-sale + inventory web app (a fresh take on the classic
retail POS). It tracks products across multiple locations, records sales
with tax/discount/payment method, prints receipts, and automatically alerts
the admin over **WhatsApp and SMS** when stock runs low — plus a digest of
which products are in demand and whether the business is making a **profit
or loss**.

## Features
- **Login required**, with two roles: **admin** (full access) and **cashier**
  (Dashboard + Sell only, can only see their own sales/receipts)
- Product & inventory management (SKU, barcode, cost price, sell price, margin)
- **Multi-location** inventory — per-location stock levels, switch location from the top bar
- **Barcode scanning** at checkout (scan or type a code + Enter to add to cart)
- Touch-friendly checkout screen with **tax, discounts, and payment method** (cash, card, EcoCash, OneMoney, or other)
- **Real card/EcoCash/OneMoney payments via Paynow** (Zimbabwe) — checkout waits on actual payment confirmation before completing the sale and reserving stock
- **Printable receipts**, and **refunds/voids** that restore stock and are logged
- **Stock adjustments** (receive stock, corrections, damage) with a full audit trail — who, when, why
- **Low-stock alerts** to the admin via WhatsApp + SMS (threshold defaults to 10), per product per location
- **Demand tracking** – ranks best-selling products and flags "HOT" items
- **Profit / loss** reporting per time window (refunded sales excluded)
- **Admin digest** – one message combining on-demand products + profit/loss status, sendable on demand or **automatically on a daily schedule**
- **CSV export** of sales history, from Reports
- Search + pagination on the products list and notification log
- Notification log so you can see every alert that was sent
- Runs offline: if Twilio is not configured, alerts are logged instead of sent

## Quick start
```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # then edit .env
python seed.py                  # load demo locations, users, products (optional)
python app.py                   # open http://127.0.0.1:5000
```

Seeded demo accounts (from `seed.py`):

| Username | Password | Role |
|---|---|---|
| `admin` | `admin123` | admin |
| `cashier` | `cashier123` | cashier |

Change these before using the app for anything real — see **Users** in the nav (admin only).

## Enabling real WhatsApp + SMS alerts
Alerts are sent through [Twilio](https://www.twilio.com/) (which supports both
SMS and WhatsApp). Fill these in your `.env`:

| Variable | Meaning |
|---|---|
| `ADMIN_WHATSAPP` | Admin WhatsApp number, e.g. `+2348012345678` |
| `ADMIN_SMS` | Admin phone number for SMS |
| `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` | Your Twilio credentials |
| `TWILIO_SMS_FROM` | A Twilio SMS-capable number |
| `TWILIO_WHATSAPP_FROM` | Your Twilio WhatsApp sender, e.g. `whatsapp:+14155238886` |

If you leave the Twilio fields blank, the app still runs and records every
alert in the notification log (visible under **Reports**) – handy for testing.

## Enabling card / EcoCash / OneMoney payments (Paynow)
Card and mobile money checkout go through [Paynow](https://www.paynow.co.zw),
Zimbabwe's payment gateway — it's the only gateway here that covers both card
and EcoCash/OneMoney through one API. Without this configured, "Card",
"EcoCash" and "OneMoney" are disabled at checkout with a clear error; **Cash**
and **Other** always work (they're just labels - no gateway involved).

1. Register at paynow.co.zw and go to **Other Ways To Get Paid → Create/Manage
   Shopping Carts → Create Advanced Integration**.
2. Copy the **Integration ID** it shows you, and email yourself the
   **Integration Key** from the same page.
3. Put them in `.env`:

| Variable | Meaning |
|---|---|
| `PAYNOW_INTEGRATION_ID` / `PAYNOW_INTEGRATION_KEY` | From your Paynow integration |
| `PAYNOW_MERCHANT_EMAIL` | Email Paynow associates with the transaction |
| `APP_BASE_URL` | Where Paynow redirects the customer back to after paying (defaults to `http://127.0.0.1:5000`, which is fine for local testing) |

New integrations start in **Test Mode** automatically — no real money moves
until you explicitly request to go live from the Paynow dashboard. In test
mode, use their documented test phone numbers/card tokens to simulate
success, cancellation, or insufficient-balance outcomes.

**How it actually confirms payment:** the card flow redirects the customer
to Paynow's hosted checkout page and brings them back when done; the EcoCash/
OneMoney flow sends a prompt to their phone and polls for the result. Either
way, stock is only decremented — and the sale only becomes `completed` —
once this app has *confirmed* payment by polling Paynow directly
(`/payments/<sale_id>/status`), not from anything the browser claims. A
Paynow-side webhook route (`/payments/webhook`) exists too for when this is
deployed with a public URL, but the app never depends on it — polling works
the same whether this runs on localhost or in production.

## Alert rules (configurable in `.env`)
- `LOW_STOCK_THRESHOLD` (default **10**) – alert when quantity ≤ this number, per product per location
- `DEMAND_WINDOW_DAYS` (default 7) – window used for demand & profit/loss
- `DEMAND_MIN_UNITS` (default 5) – units sold in the window to be "on demand"
- `TAX_RATE` (default 0) – e.g. `0.075` for 7.5%, applied at checkout after discount
- `DIGEST_HOUR` (blank by default) – hour (0-23, server local time) to auto-send the daily digest; leave blank to only send it manually

## How alerts fire
- **Low stock:** checked after every sale, refund, and stock adjustment. Each
  product+location alerts once when it drops to/below the threshold, and
  re-arms after you restock.
- **Digest (demand + profit/loss):** click **"Send admin digest now"** on the
  dashboard (admin only), or set `DIGEST_HOUR` in `.env` for it to send automatically once a day.

## Roles & permissions
- **Admin:** everything — products, stock adjustments, locations, users, reports, CSV export, refunds, digest.
- **Cashier:** Dashboard and Sell screens only. Can check out sales and view/print their own receipts, but cannot see other cashiers' sales, refund, or reach admin-only pages (a 403 page is shown).

## Multi-location inventory
Each product has a separate quantity per location. Use the location switcher
in the top bar to choose which location you're operating from — checkout,
stock adjustments, and the products/sell screens all use that location.
Manage locations under **Locations** (admin only).

## Running the tests
```bash
source venv/bin/activate
pytest
```
Covers auth/roles, checkout (stock, tax, discount), refunds, stock adjustments,
barcode lookup, CSV export, and the Paynow payment flow (mocked - no real
network calls), all against a throwaway SQLite file per run.

## Deploying (Fly.io)
This repo includes a `Dockerfile`, `.dockerignore` and `fly.toml` already set
up for Fly.io, chosen specifically because its free tier offers a real
**persistent volume** (SQLite data survives redeploys) and can stay running
continuously (needed for the optional digest scheduler) - most free PaaS
tiers offer neither.

1. Install the CLI and sign up/log in (opens your browser):
   ```bash
   brew install flyctl
   fly auth login
   ```
2. From the project root, create the app and its persistent volume (pick a
   region near you with `fly platform regions` if `jnb` isn't ideal):
   ```bash
   fly launch --no-deploy --copy-config   # uses the committed fly.toml; say no to "generate a new config"
   fly volumes create stockpilot_data --region jnb --size 1
   ```
3. Set your real secrets - **never put these in `fly.toml`**, which gets committed:
   ```bash
   fly secrets set SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
   fly secrets set APP_BASE_URL="https://<your-app-name>.fly.dev"
   # Optional, only if you're using them:
   fly secrets set PAYNOW_INTEGRATION_ID=... PAYNOW_INTEGRATION_KEY=... PAYNOW_MERCHANT_EMAIL=...
   fly secrets set TWILIO_ACCOUNT_SID=... TWILIO_AUTH_TOKEN=... TWILIO_SMS_FROM=... TWILIO_WHATSAPP_FROM=...
   fly secrets set ADMIN_WHATSAPP=... ADMIN_SMS=...
   ```
4. Deploy:
   ```bash
   fly deploy
   ```
5. **First deploy only** - the volume starts empty, so there's no database yet.
   SSH in and seed it once:
   ```bash
   fly ssh console -C "python seed.py"
   ```
   This creates the demo admin/cashier accounts and sample products so you
   can log in immediately - change the passwords (or delete the demo
   products) right away under **Users** / **Products**.
   ⚠️ `seed.py` calls `db.drop_all()` first - run it only this once. Running
   it again later on a live app **deletes all real data**.

After that, `fly deploy` redeploys your code changes without touching the
volume, so real data persists across deploys. Logs: `fly logs`. Open the
live app: `fly open`.

## Notes
- Locally, the server binds to `127.0.0.1` only (see `if __name__ ==
  "__main__"` in `app.py`); in Docker/Fly it runs behind gunicorn instead,
  bound to `0.0.0.0` inside the container, with Fly terminating HTTPS.
- Data is stored in a SQLite file - locally at `stockpilot.db`, in
  production on the Fly volume at `/data/stockpilot.db` (set via
  `DATABASE_URL` in `fly.toml`).
- The digest scheduler must run as a single process - don't raise the
  gunicorn worker count above 1 in the `Dockerfile` (see the comment on
  `start_scheduler` in `app.py` for why).
- This is still a small single-store-friendly app, not a certified fiscal
  till — there's no tax-authority integration, and receipts are informational,
  not fiscal documents.
