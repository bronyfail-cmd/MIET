import pytest

from app import create_app


@pytest.fixture
def app(tmp_path):
    return create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.sqlite3")})


@pytest.fixture
def client(app):
    return app.test_client()


def register_and_login(client, email="stud@example.com", group="ИС-25-21С", name="Иванов Иван"):
    client.post("/register", data={"email": email, "full_name": name,
                                   "study_group": group, "password": "secret12"})
    client.post("/login", data={"email": email, "password": "secret12"})
