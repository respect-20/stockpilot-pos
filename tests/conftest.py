import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from models import db, User, Location


@pytest.fixture()
def app():
    fd, path = tempfile.mkstemp(suffix=".db")
    flask_app = create_app({
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{path}",
        "TESTING": True,
        "LOW_STOCK_THRESHOLD": 10,
        "TAX_RATE": 0.1,
        "DIGEST_HOUR": "",
    })
    with flask_app.app_context():
        yield flask_app
    os.close(fd)
    os.unlink(path)


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def location(app):
    return Location.query.first()


def make_user(username, role, password="pw123"):
    u = User(username=username, role=role)
    u.set_password(password)
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture()
def admin(app):
    return make_user("admin1", "admin")


@pytest.fixture()
def cashier(app):
    return make_user("cashier1", "cashier")


def login(client, username, password="pw123"):
    return client.post("/login", data={"username": username, "password": password},
                       follow_redirects=True)
