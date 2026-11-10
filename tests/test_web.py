import json
import re

from conftest import register_and_login
from app.db import get_db
from werkzeug.security import generate_password_hash


def complete_survey(client, app, answer_for=None):
    html = client.post("/survey/start").get_data(as_text=True)
    aid = int(re.search(r'href="/survey/(\d+)"', html).group(1))
    while True:
        rv = client.get(f"/survey/{aid}")
        if rv.status_code == 302:
            break
        html = rv.get_data(as_text=True)
        csrf = re.search(r'name="_csrf" value="([^"]+)"', html).group(1)
        qid = re.search(r'name="question_id" value="([^"]+)"', html).group(1)
        opts = [int(v) for v in re.findall(r'name="value" value="(-?\d+)"', html)]
        q = {"options": [{"value": v} for v in opts]}
        value = answer_for(q) if answer_for else opts[0]
        action = "finish" if 'value="finish"' in html else "next"
        rv = client.post(f"/survey/{aid}",
                         data={"_csrf": csrf, "question_id": qid,
                               "value": value, "action": action},
                         follow_redirects=False)
        if "/continue" in rv.headers.get("Location", ""):
            page = client.get(f"/survey/{aid}/continue").get_data(as_text=True)
            csrf2 = re.search(r'name="_csrf" value="([^"]+)"', page).group(1)
            client.post(f"/survey/{aid}/continue", data={"_csrf": csrf2})
    return aid


def test_requires_login(client):
    assert client.get("/cabinet").status_code == 302
    assert client.get("/survey/1").status_code == 302
    assert client.get("/admin").status_code == 302


def test_register_login_cabinet(client):
    register_and_login(client)
    r = client.get("/cabinet")
    assert r.status_code == 200 and "Иванов Иван".encode() in r.data


def test_duplicate_registration_and_bad_password(client):
    register_and_login(client)
    r = client.post("/register", data={"email": "stud@example.com", "full_name": "Иванов Иван", "password": "secret12"})
    assert "уже есть".encode() in r.data
    r = client.post("/register", data={"email": "n@e.com", "full_name": "Имя Имя", "password": "123"})
    assert "не короче".encode() in r.data
    client.post("/logout")
    r = client.post("/login", data={"email": "stud@example.com", "password": "wrong"})
    assert "Неверный".encode() in r.data


def test_full_pass_creates_result(client, app):
    register_and_login(client)
    aid = complete_survey(client, app)
    r = client.get(f"/result/{aid}")
    assert r.status_code == 200
    for m in app.methods.values():
        assert m.title.encode() in r.data
    data = json.loads(client.get(f"/result/{aid}/export.json").data)
    assert data["summary"]["ok"] == len(app.methods)
    csv_data = client.get(f"/result/{aid}/export.csv").data.decode("utf-8-sig")
    assert csv_data.count("\n") >= len(app.methods) + 1


def test_next_without_answer_is_rejected(client, app):
    register_and_login(client)
    client.post("/survey/start")
    q = next(iter(app.methods.values())).questions()[0]
    r = client.post("/survey/1", data={"_csrf": "x", "question_id": q["id"], "action": "next", "value": ""}, follow_redirects=True)
    assert "Выберите один из вариантов ответа".encode() in r.data


def test_invalid_answer_rejected(client, app):
    register_and_login(client)
    client.post("/survey/start")
    q = next(iter(app.methods.values())).questions()[0]
    r = client.post("/survey/1", data={"question_id": q["id"], "value": "999", "action": "next"}, follow_redirects=True)
    assert "Некорректный".encode() in r.data
    r = client.post("/survey/1", data={"question_id": q["id"], "value": "abc", "action": "next"})
    assert r.status_code in (302, 500) and r.status_code != 500


def test_users_cannot_see_each_other(client, app):
    register_and_login(client)
    aid = complete_survey(client, app)
    client.post("/logout")
    register_and_login(client, email="other@example.com", name="Петров Пётр")
    assert client.get(f"/result/{aid}").status_code == 403
    assert client.get(f"/result/{aid}/export.json").status_code == 403
    assert client.get("/admin").status_code == 403


def make_teacher(app):
    with app.app_context():
        db = get_db()
        db.execute("INSERT INTO users (email, full_name, password_hash, role) VALUES (?, ?, ?, 'teacher')",
                   ("t@example.com", "Преподаватель Т", generate_password_hash("teachpass")))
        db.commit()


def test_teacher_filters(client, app):
    register_and_login(client, email="a@e.com", group="ИС-25-21С", name="Аааа Аа")
    complete_survey(client, app, answer_for=lambda q: q["options"][-1]["value"])
    client.post("/logout")
    make_teacher(app)
    client.post("/login", data={"email": "t@example.com", "password": "teachpass"})

    n = len(app.methods)
    finished = 1
    assert f"Найдено строк: {n}".encode() in client.get("/admin").data
    assert "Найдено строк: 0".encode() in client.get("/admin?group=ИС-99").data
    first_method = next(iter(app.methods))
    one = client.get(f"/admin?method={first_method}").data
    assert f"Найдено строк: {finished}".encode() in one
    assert f"Найдено строк: {finished}".encode() in client.get("/admin?q=Аааа&method=cognitive_reflection").data
    assert "Найдено строк: 0".encode() in client.get("/admin?date_from=2999-01-01").data
    csv_data = client.get(f"/admin/export.csv?method={first_method}").data.decode("utf-8-sig")
    assert len(csv_data.strip().splitlines()) == 2
    # SQL-инъекция в фильтре не ломает запрос
    assert client.get("/admin?q=' OR 1=1 --").status_code == 200
    assert client.get("/admin/validate").status_code == 200


def test_csrf_enforced_when_enabled(tmp_path):
    from app import create_app
    app = create_app({"TESTING": True, "CSRF_IN_TESTS": True, "DATABASE": str(tmp_path / "c.sqlite3")})
    c = app.test_client()
    assert c.post("/login", data={"email": "a@b.c", "password": "x"}).status_code == 400


def test_health(client):
    r = client.get("/health")
    assert r.get_json()["status"] == "ok"


def test_open_redirect_blocked(client):
    register_and_login(client)
    client.post("/logout")
    r = client.post("/login?next=//evil.com", data={"email": "stud@example.com", "password": "secret12"})
    assert "evil.com" not in r.headers["Location"]
