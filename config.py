"""Configuration for Dhingani Investment.

All secrets are read from environment variables (see .env.example).
Nothing sensitive is hard-coded.
"""
import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-change-me")
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL", "sqlite:///" + os.path.join(BASE_DIR, "stockpilot.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ---- Inventory / alert rules ----
    # Low stock alert fires when quantity <= this number.
    LOW_STOCK_THRESHOLD = int(os.getenv("LOW_STOCK_THRESHOLD", "10"))
    # A product is "on demand" if it sold at least this many units
    # within the demand window.
    DEMAND_WINDOW_DAYS = int(os.getenv("DEMAND_WINDOW_DAYS", "7"))
    DEMAND_MIN_UNITS = int(os.getenv("DEMAND_MIN_UNITS", "5"))

    # ---- Checkout ----
    TAX_RATE = float(os.getenv("TAX_RATE", "0"))  # e.g. 0.075 for 7.5%

    # ---- Paynow (Zimbabwe payment gateway: card, EcoCash, OneMoney) ----
    # Get these from https://www.paynow.co.zw -> Create Advanced Integration.
    # New integrations start in Test Mode automatically - no real money moves
    # until you request to go live. Leave blank to disable card/mobile payments
    # (cash/other keep working either way).
    PAYNOW_INTEGRATION_ID = os.getenv("PAYNOW_INTEGRATION_ID", "")
    PAYNOW_INTEGRATION_KEY = os.getenv("PAYNOW_INTEGRATION_KEY", "")
    PAYNOW_MERCHANT_EMAIL = os.getenv("PAYNOW_MERCHANT_EMAIL", "")
    # Base URL Paynow redirects back to / is told to notify (must be publicly
    # reachable for the result_url webhook; 127.0.0.1 only works for the
    # polling flow, which is what this app relies on).
    APP_BASE_URL = os.getenv("APP_BASE_URL", "http://127.0.0.1:5000")

    # ---- Admin contact (who receives alerts) ----
    # One number, or several comma-separated - every one gets every alert.
    ADMIN_WHATSAPP = os.getenv("ADMIN_WHATSAPP", "")   # e.g. +2348012345678,+2348087654321
    ADMIN_SMS = os.getenv("ADMIN_SMS", "")             # e.g. +2348012345678,+2348087654321

    # ---- Twilio credentials (optional) ----
    TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
    TWILIO_SMS_FROM = os.getenv("TWILIO_SMS_FROM", "")          # e.g. +15005550006
    TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM", "")  # e.g. whatsapp:+14155238886

    # ---- Automated digest ----
    # Hour of day (0-23, server local time) the digest auto-sends. Blank disables.
    DIGEST_HOUR = os.getenv("DIGEST_HOUR", "")

    # ---- Pagination ----
    PAGE_SIZE = int(os.getenv("PAGE_SIZE", "20"))
