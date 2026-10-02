"""Notification layer for Dhingani Investment.

Sends WhatsApp + SMS alerts through Twilio when credentials are configured.
If Twilio is not configured (or a send fails), the message is still recorded
in the database and printed to the console, so the app keeps working offline.
"""
from config import Config
from models import db, Notification

try:
    from twilio.rest import Client
except Exception:  # twilio not installed
    Client = None


def _twilio_client():
    if Client and Config.TWILIO_ACCOUNT_SID and Config.TWILIO_AUTH_TOKEN:
        try:
            return Client(Config.TWILIO_ACCOUNT_SID, Config.TWILIO_AUTH_TOKEN)
        except Exception as exc:  # bad creds, etc.
            print(f"[notify] could not init Twilio: {exc}")
    return None


def _record(kind, channel, recipient, message, status):
    db.session.add(Notification(
        kind=kind, channel=channel, recipient=recipient,
        message=message, status=status,
    ))
    db.session.commit()


def _send_sms(client, to, body):
    client.messages.create(body=body, from_=Config.TWILIO_SMS_FROM, to=to)


def _send_whatsapp(client, to, body):
    to_wa = to if to.startswith("whatsapp:") else f"whatsapp:{to}"
    client.messages.create(
        body=body, from_=Config.TWILIO_WHATSAPP_FROM, to=to_wa
    )


def notify_admin(kind, message):
    """Send `message` to the admin over WhatsApp and SMS.

    Returns a list of per-channel result dicts. Always records to the DB.
    """
    client = _twilio_client()
    results = []

    targets = [
        ("whatsapp", Config.ADMIN_WHATSAPP, Config.TWILIO_WHATSAPP_FROM, _send_whatsapp),
        ("sms", Config.ADMIN_SMS, Config.TWILIO_SMS_FROM, _send_sms),
    ]

    for channel, to, sender, fn in targets:
        if not to:
            continue
        if client and sender:
            try:
                fn(client, to, message)
                _record(kind, channel, to, message, "sent")
                results.append({"channel": channel, "to": to, "status": "sent"})
                continue
            except Exception as exc:
                print(f"[notify] {channel} send failed: {exc}")
                _record(kind, channel, to, message, "failed")
                results.append({"channel": channel, "to": to, "status": "failed"})
                continue
        # No live sending available -> log only
        _record(kind, channel, to, message, "logged")
        results.append({"channel": channel, "to": to, "status": "logged"})

    # If no admin contact configured at all, still keep a log entry.
    if not results:
        _record(kind, "log", "(no admin contact set)", message, "logged")
        results.append({"channel": "log", "to": None, "status": "logged"})

    print(f"[notify:{kind}] {message}")
    return results
