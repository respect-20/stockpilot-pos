"""Paynow (Zimbabwe) payment gateway integration.

Card and mobile money (EcoCash/OneMoney) payments go through Paynow
(https://www.paynow.co.zw). New Paynow integrations start in Test Mode
automatically, so no real money moves until the merchant explicitly
requests to go live from their Paynow dashboard.

Paynow's own webhook ("result url") requires a publicly reachable HTTPS
endpoint, which a localhost-only app doesn't have - and the installed
`paynow` SDK's webhook parser (`process_status_update`) is an unimplemented
stub anyway. So this app relies entirely on *polling* Paynow's poll_url to
confirm payment, which works the same whether the app is local or deployed.
The webhook route in app.py is still wired up (with its own hash check,
not the SDK's) as a defensive fast-path for when this is deployed publicly,
but the app never depends on it firing.
"""
import hashlib

from paynow import Paynow as PaynowClient

from config import Config


def _error_message(response):
    """Pull a real error string out of a failed InitResponse.

    The installed paynow SDK has a bug: InitResponse.__init__ returns early
    on failure, before it ever assigns self.error - so response.error is
    left as the class's placeholder attribute (literally the `str` type
    object, not a string). The raw response dict (response.data) is set
    before that early return though, and does contain the real message.
    """
    raw = getattr(response, "data", {}) or {}
    msg = raw.get("error")
    if isinstance(msg, str) and msg:
        return msg
    return f"Payment was rejected (status: {getattr(response, 'status', 'unknown')})."


def configured():
    return bool(Config.PAYNOW_INTEGRATION_ID and Config.PAYNOW_INTEGRATION_KEY)


def _client(result_url, return_url):
    return PaynowClient(Config.PAYNOW_INTEGRATION_ID, Config.PAYNOW_INTEGRATION_KEY,
                        return_url, result_url)


def _urls(sale_id):
    base = Config.APP_BASE_URL.rstrip("/")
    return f"{base}/payments/webhook", f"{base}/sales/{sale_id}/payment-return"


def _build_payment(client, sale):
    payment = client.create_payment(f"sale-{sale.id}", Config.PAYNOW_MERCHANT_EMAIL or "payments@stockpilot.local")
    for item in sale.items:
        payment.add(item.product_name, round(item.unit_price * item.quantity, 2))
    if sale.discount_amount:
        payment.add("Discount", -round(sale.discount_amount, 2))
    if sale.tax_amount:
        payment.add("Tax", round(sale.tax_amount, 2))
    return payment


def start_card_payment(sale):
    """Initiate a web/card payment. Returns dict: success, redirect_url, poll_url, error."""
    result_url, return_url = _urls(sale.id)
    client = _client(result_url, return_url)
    payment = _build_payment(client, sale)
    try:
        response = client.send(payment)
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    if not response.success:
        return {"success": False, "error": _error_message(response)}
    return {"success": True, "redirect_url": response.redirect_url, "poll_url": response.poll_url}


def start_mobile_payment(sale, phone, method):
    """Initiate an EcoCash/OneMoney payment. Returns dict: success, poll_url, instructions, error."""
    result_url, return_url = _urls(sale.id)
    client = _client(result_url, return_url)
    payment = _build_payment(client, sale)
    try:
        response = client.send_mobile(payment, phone, method)
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    if not response.success:
        return {"success": False, "error": _error_message(response)}
    instructions = getattr(response, "instruction", None) or "Check your phone to authorize the payment."
    return {"success": True, "poll_url": response.poll_url, "instructions": instructions}


def poll_status(poll_url):
    """Poll Paynow for the current status of a transaction.

    Returns dict: ok, paid, status, error. `ok` is False only on a network/
    protocol failure - a legitimate 'cancelled' or 'created' status is ok=True.
    """
    client = _client("", "")  # result/return urls aren't used for polling
    try:
        status = client.check_transaction_status(poll_url)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "paid": status.paid, "status": status.status,
            "paynow_reference": getattr(status, "paynow_reference", None)}


def verify_webhook_hash(data):
    """Re-implement Paynow's SHA512 hash check for the result_url webhook.

    The installed SDK's own webhook parser (process_status_update) doesn't
    actually verify or parse anything - it's a stub - so this redoes the
    algorithm from the SDK's (working) response-parsing path by hand.
    """
    if "hash" not in data:
        return False
    out = "".join(str(v) for k, v in data.items() if k.lower() != "hash")
    out += Config.PAYNOW_INTEGRATION_KEY.lower()
    expected = hashlib.sha512(out.encode("utf-8")).hexdigest().upper()
    return expected == data["hash"]
