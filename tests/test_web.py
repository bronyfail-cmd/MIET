import json

from conftest import register_and_login
from app.db import get_db
from werkzeug.security import generate_password_hash


def complete_survey(client, app, answer_for=lambda q: q["options"][-1]["value"]):
    client.post("/survey/start")
    attempt_id = 1
    from app.engine import Survey
    flow = Survey(app.methods, list(app.methods)).flow
    for i, q in enumerate(flow):
        action = "finish" if i == len(flow) - 1 else "next"
        client.post(f"/survey/{attempt_id}", data={"question_id": q["id"], "value": answer_for(q), "action": action})
    return attempt_id


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


def test_skip_and_back_and_resume(client, app):
    register_and_login(client)
    client.post("/survey/start")
    first = next(iter(app.methods.values())).questions()[0]
    client.post("/survey/1", data={"question_id": first["id"], "action": "skip"})
    page = client.get("/survey/1")
    assert "Вопрос 2 из".encode() in page.data
    client.post("/survey/1", data={"question_id": "x", "action": "prev"})
    assert "Вопрос 1 из".encode() in client.get("/survey/1").data
    # повторный старт продолжает ту же попытку
    assert client.post("/survey/start").headers["Location"].endswith("/survey/1")


def test_next_without_answer_is_rejected(client, app):
    register_and_login(client)
    client.post("/survey/start")
    q = next(iter(app.methods.values())).questions()[0]
    r = client.post("/survey/1", data={"question_id": q["id"], "action": "next"}, follow_redirects=True)
    assert "Выберите ответ".encode() in r.data
    assert "Вопрос 1 из".encode() in r.data


def test_invalid_answer_rejected(client, app):
    register_and_login(client)
    client.post("/survey/start")
    q = next(iter(app.methods.values())).questions()[0]
    r = client.post("/survey/1", data={"question_id": q["id"], "value": "999", "action": "next"}, follow_redirects=True)
    assert "Некорректный".encode() in r.data
    r = client.post("/survey/1", data={"question_id": q["id"], "value": "abc", "action": "next"})
    assert r.status_code in (302, 500) and r.status_code != 500


def test_finish_with_everything_skipped(client, app):
    register_and_login(client)
    client.post("/survey/start")
    from app.engine import Survey
    flow = Survey(app.methods, list(app.methods)).flow
    for q in flow:
        client.post("/survey/1", data={"question_id": q["id"], "action": "skip"})
    client.post("/survey/1", data={"question_id": flow[-1]["id"], "action": "finish"})
    r = client.get("/result/1")
    assert r.status_code == 200 and "неполный".encode() in r.data


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
    assert f"Найдено строк: {n}".encode() in client.get("/admin").data
    assert "Найдено строк: 0".encode() in client.get("/admin?group=ИС-99").data
    one = client.get("/admin?method=critical_thinking").data
    assert "Найдено строк: 1".encode() in one
    assert "Найдено строк: 1".encode() in client.get("/admin?q=Аааа&method=cognitive_reflection").data
    assert "Найдено строк: 0".encode() in client.get("/admin?date_from=2999-01-01").data
    csv_data = client.get("/admin/export.csv?method=critical_thinking").data.decode("utf-8-sig")
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
