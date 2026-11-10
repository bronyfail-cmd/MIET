import csv
import functools
import io
import json
import re

from flask import (Blueprint, Response, abort, current_app, flash, g, jsonify,
                   redirect, render_template, request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from .collector import collect_from_methods
from .db import get_db
from .engine import Survey
from .validator import validate

NAME_RE  = re.compile(r"^[А-Яа-яЁёA-Za-z]+(?:[ -][А-Яа-яЁёA-Za-z]+)+$")
GROUP_RE = re.compile(r"^[А-ЯA-Za-z0-9]+(?:-[А-ЯA-Za-z0-9]+)*$")

bp = Blueprint("web", __name__)


@bp.app_template_filter()
def num(value):
    if value is None:
        return ""
    f = float(value)
    return str(int(f)) if f == int(f) else f"{f:.1f}"


# ---------- вспомогательное ----------
@bp.before_app_request
def load_user():
    uid = session.get("user_id")
    g.user = None
    if uid is not None:
        g.user = get_db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()


def login_required(view):
    @functools.wraps(view)
    def wrapped(*a, **kw):
        if g.user is None:
            return redirect(url_for("web.login", next=request.path))
        return view(*a, **kw)
    return wrapped


def teacher_required(view):
    @functools.wraps(view)
    def wrapped(*a, **kw):
        if g.user is None:
            return redirect(url_for("web.login", next=request.path))
        if g.user["role"] != "teacher":
            abort(403)
        return view(*a, **kw)
    return wrapped


def method_order():
    return current_app.config["METHOD_ORDER"] or list(current_app.methods)


def get_attempt(attempt_id):
    """Попытка доступна владельцу и преподавателю."""
    row = get_db().execute("SELECT * FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
    if row is None:
        abort(404)
    if row["user_id"] != g.user["id"] and g.user["role"] != "teacher":
        abort(403)
    return row


def load_survey(attempt):
    rows = get_db().execute(
        "SELECT question_id, value FROM answers WHERE attempt_id = ?", (attempt["id"],)).fetchall()
    return Survey(current_app.methods, method_order(),
                  answers={r["question_id"]: r["value"] for r in rows},
                  position=attempt["position"])


def save_answer(attempt_id, survey, qid, value):
    method_id = survey._find(qid)["method_id"]
    db = get_db()
    db.execute(
        "INSERT INTO answers (attempt_id, question_id, method_id, value) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(attempt_id, question_id) DO UPDATE SET value = excluded.value",
        (attempt_id, qid, method_id, value))


# ---------- общие страницы ----------
@bp.route("/")
def index():
    if g.user:
        return redirect(url_for("web.cabinet"))
    return render_template("index.html")


@bp.route("/health")
def health():
    report = validate(current_app.methods, current_app.method_errors)
    return jsonify(status="ok" if report["ok"] else "degraded", methods=report["methods"])


# ---------- аккаунты ----------
@bp.route("/register", methods=("GET", "POST"))
def register():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        name = request.form.get("full_name", "").strip()
        group = request.form.get("study_group", "").strip()
        password = request.form.get("password", "")
        error = None
        if "@" not in email or len(email) < 5:
            error = "Введите корректный e-mail."
        elif len(name) < 3:
            error = "Введите ФИО."
        elif not NAME_RE.match(name):
            error = "ФИО: минимум два слова, только буквы."
        elif group and not GROUP_RE.match(group):
            error = "Группа: буквы/цифры/дефис, например ИС-25-21С."
        elif len(password) < 6:
            error = "Пароль должен быть не короче 6 символов."
        if error is None:
            db = get_db()
            try:
                db.execute(
                    "INSERT INTO users (email, full_name, study_group, password_hash) VALUES (?, ?, ?, ?)",
                    (email, name, group, generate_password_hash(password)))
                db.commit()
            except Exception:
                error = "Пользователь с таким e-mail уже есть."
            else:
                flash("Регистрация прошла успешно, войдите.", "ok")
                return redirect(url_for("web.login"))
        flash(error, "error")
    return render_template("register.html")


@bp.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user is None or not check_password_hash(user["password_hash"], request.form.get("password", "")):
            flash("Неверный e-mail или пароль.", "error")
        else:
            session.clear()
            session["user_id"] = user["id"]
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("web.cabinet"))
    return render_template("login.html")


@bp.route("/logout", methods=("POST",))
def logout():
    session.clear()
    return redirect(url_for("web.index"))


# ---------- личный кабинет ----------
@bp.route("/cabinet")
@login_required
def cabinet():
    attempts = get_db().execute(
        "SELECT * FROM attempts WHERE user_id = ? ORDER BY id DESC", (g.user["id"],)).fetchall()
    return render_template("cabinet.html", attempts=attempts, methods=current_app.methods)


@bp.route("/survey/start", methods=("POST",))
@login_required
def survey_start():
    db = get_db()
    open_attempt = db.execute(
        "SELECT id FROM attempts WHERE user_id = ? AND status = 'in_progress' ORDER BY id DESC LIMIT 1",
        (g.user["id"],)).fetchone()
    if open_attempt:
        return render_template("instruction.html", attempt_id=open_attempt["id"])
    cur = db.execute("INSERT INTO attempts (user_id) VALUES (?)", (g.user["id"],))
    db.commit()
    return render_template("instruction.html", attempt_id=cur.lastrowid)


@bp.route("/survey/<int:attempt_id>/continue", methods=("GET", "POST"))
@login_required
def interstitial(attempt_id):
    attempt = get_attempt(attempt_id)
    if attempt["user_id"] != g.user["id"]:
        abort(403)
    if attempt["status"] == "finished":
        return redirect(url_for("web.result", attempt_id=attempt_id))
    if request.method == "POST":
        sv = load_survey(attempt)
        q = sv.current()
        if (q is not None and not sv.is_last()
                and sv.is_last_in_method() and q["id"] in sv.answers):
            sv.next()
            db = get_db()
            db.execute("UPDATE attempts SET position = ? WHERE id = ?",
                       (sv.position, attempt_id))
            db.commit()
        return redirect(url_for("web.survey", attempt_id=attempt_id))
    return render_template("interstitial.html", attempt_id=attempt_id)


# ---------- прохождение опроса ----------
@bp.route("/survey/<int:attempt_id>", methods=("GET", "POST"))
@login_required
def survey(attempt_id):
    attempt = get_attempt(attempt_id)
    if attempt["user_id"] != g.user["id"]:
        abort(403)
    if attempt["status"] == "finished":
        return redirect(url_for("web.result", attempt_id=attempt_id))
    sv = load_survey(attempt)
    if sv.total == 0:
        return render_template("error.html", message="Нет доступных вопросов: ни один блок не ответил.",
                               errors=sv.errors), 503

    if request.method == "POST":
        action = request.form.get("action", "next")
        qid = request.form.get("question_id", "")
        raw = request.form.get("value", "")
        try:
            if action in ("next", "finish") and raw != "":
                sv.answer(qid, int(raw))
                save_answer(attempt_id, sv, qid, int(raw))
            elif action in ("next", "finish") and raw == "" and qid not in sv.answers:
                flash("Выберите один из вариантов ответа.", "error")
                return redirect(url_for("web.survey", attempt_id=attempt_id))
        except (ValueError, KeyError):
            flash("Некорректный ответ.", "error")
            return redirect(url_for("web.survey", attempt_id=attempt_id))

        if action == "skip":
            sv.skip(qid)
            save_answer(attempt_id, sv, qid, None)
            if sv.is_last_in_method() and not sv.is_last():
                db = get_db()
                db.execute("UPDATE attempts SET position = ? WHERE id = ?",
                           (sv.position, attempt_id))
                db.commit()
                return redirect(url_for("web.interstitial", attempt_id=attempt_id))
            sv.next()
            db = get_db()
            db.execute("UPDATE attempts SET position = ? WHERE id = ?", (sv.position, attempt_id))
            db.commit()
            return redirect(url_for("web.survey", attempt_id=attempt_id))

        if action == "prev":
            sv.prev()
        elif action == "finish":
            return finish_attempt(attempt, sv)
        elif action == "next":
            if sv.is_last_in_method() and not sv.is_last():
                db = get_db()
                db.execute("UPDATE attempts SET position = ? WHERE id = ?",
                           (sv.position, attempt_id))
                db.commit()
                return redirect(url_for("web.interstitial", attempt_id=attempt_id))
            sv.next()
        db = get_db()
        db.execute("UPDATE attempts SET position = ? WHERE id = ?", (sv.position, attempt_id))
        db.commit()
        return redirect(url_for("web.survey", attempt_id=attempt_id))

    question = sv.current()
    return render_template("survey.html", attempt=attempt, q=question,
                           current_answer=sv.answers.get(question["id"]),
                           progress=sv.progress(), is_last=sv.is_last(),
                           position=sv.position, total=sv.total, block_errors=sv.errors)


def finish_attempt(attempt, sv):
    portrait = collect_from_methods(
        current_app.methods, sv.grouped_answers(),
        person={"name": g.user["full_name"], "group": g.user["study_group"]})
    portrait["summary"]["block_errors"] = sv.errors
    db = get_db()
    db.execute("DELETE FROM results WHERE attempt_id = ?", (attempt["id"],))
    for s in portrait["sections"]:
        db.execute(
            "INSERT INTO results (attempt_id, method_id, title, score, max_score, percent, level, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (attempt["id"], s["method_id"],
             s.get("title") or current_app.methods[s["method_id"]].title,
             s.get("score"), s.get("max_score"), s.get("percent"), s.get("level"), s["status"]))
    db.execute(
        "UPDATE attempts SET status = 'finished', finished_at = datetime('now'), portrait = ? WHERE id = ?",
        (json.dumps(portrait, ensure_ascii=False), attempt["id"]))
    db.commit()
    return redirect(url_for("web.result", attempt_id=attempt["id"]))


# ---------- результаты ----------
def portrait_of(attempt):
    if attempt["status"] != "finished" or not attempt["portrait"]:
        abort(404)
    return json.loads(attempt["portrait"])


@bp.route("/result/<int:attempt_id>")
@login_required
def result(attempt_id):
    attempt = get_attempt(attempt_id)
    if attempt["status"] != "finished":
        return redirect(url_for("web.survey", attempt_id=attempt_id))
    return render_template("result.html", attempt=attempt, portrait=portrait_of(attempt))


@bp.route("/result/<int:attempt_id>/export.json")
@login_required
def export_json(attempt_id):
    attempt = get_attempt(attempt_id)
    return Response(json.dumps(portrait_of(attempt), ensure_ascii=False, indent=2),
                    mimetype="application/json",
                    headers={"Content-Disposition": f"attachment; filename=portrait_{attempt_id}.json"})


def rows_to_csv(rows, header):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(header)
    w.writerows(rows)
    return "﻿" + buf.getvalue()  # BOM, чтобы Excel открыл кириллицу


@bp.route("/result/<int:attempt_id>/export.csv")
@login_required
def export_csv(attempt_id):
    attempt = get_attempt(attempt_id)
    portrait = portrait_of(attempt)
    rows = [(s.get("title", s["method_id"]), s.get("score", ""), s.get("max_score", ""),
             f"{s.get('percent', 0) * 100:.0f}%" if "percent" in s else "", s.get("level", ""),
             s.get("interpretation", ""), s["status"]) for s in portrait["sections"]]
    return Response(rows_to_csv(rows, ["Методика", "Балл", "Максимум", "Процент", "Уровень", "Вывод", "Статус"]),
                    mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename=portrait_{attempt_id}.csv"})


# ---------- раздел преподавателя: фильтрация данных ----------
def filtered_results(args):
    sql = ("SELECT a.id AS attempt_id, u.full_name, u.study_group, a.finished_at, "
           "r.method_id, r.title, r.score, r.max_score, r.percent, r.level, r.status "
           "FROM results r JOIN attempts a ON a.id = r.attempt_id JOIN users u ON u.id = a.user_id WHERE 1=1")
    params = []
    if args.get("group"):
        sql += " AND u.study_group = ?"
        params.append(args["group"])
    if args.get("method"):
        sql += " AND r.method_id = ?"
        params.append(args["method"])
    if args.get("level"):
        sql += " AND r.level = ?"
        params.append(args["level"])
    if args.get("status"):
        sql += " AND r.status = ?"
        params.append(args["status"])
    if args.get("q"):
        sql += " AND u.full_name LIKE ?"
        params.append(f"%{args['q']}%")
    if args.get("date_from"):
        sql += " AND date(a.finished_at) >= date(?)"
        params.append(args["date_from"])
    if args.get("date_to"):
        sql += " AND date(a.finished_at) <= date(?)"
        params.append(args["date_to"])
    sql += " ORDER BY a.finished_at DESC, r.method_id"
    return get_db().execute(sql, params).fetchall()


@bp.route("/admin")
@teacher_required
def admin():
    rows = filtered_results(request.args)
    groups = [r[0] for r in get_db().execute(
        "SELECT DISTINCT study_group FROM users WHERE study_group != '' ORDER BY 1")]
    return render_template("admin.html", rows=rows, groups=groups,
                           methods=current_app.methods, args=request.args)


@bp.route("/admin/export.csv")
@teacher_required
def admin_export():
    rows = filtered_results(request.args)
    data = [(r["attempt_id"], r["full_name"], r["study_group"], r["finished_at"], r["title"],
             r["score"], r["max_score"], r["level"], r["status"]) for r in rows]
    return Response(
        rows_to_csv(data, ["Попытка", "ФИО", "Группа", "Завершено", "Методика", "Балл", "Максимум", "Уровень", "Статус"]),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=results.csv"})


@bp.route("/admin/validate")
@teacher_required
def admin_validate():
    report = validate(current_app.methods, current_app.method_errors,
                      min_methods=current_app.config["MIN_METHODS"])
    return render_template("validate.html", report=report)
