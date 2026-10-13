import sqlite3

import click
from flask import current_app, g
from werkzeug.security import generate_password_hash

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL,
    study_group TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'student' CHECK (role IN ('student', 'teacher')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'in_progress' CHECK (status IN ('in_progress', 'finished')),
    position INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT,
    portrait TEXT
);

-- value NULL = вопрос пропущен
CREATE TABLE IF NOT EXISTS answers (
    attempt_id INTEGER NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
    question_id TEXT NOT NULL,
    method_id TEXT NOT NULL,
    value INTEGER,
    PRIMARY KEY (attempt_id, question_id)
);

CREATE TABLE IF NOT EXISTS results (
    attempt_id INTEGER NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
    method_id TEXT NOT NULL,
    title TEXT NOT NULL,
    score REAL,
    max_score REAL,
    percent REAL,
    level TEXT,
    status TEXT NOT NULL,
    PRIMARY KEY (attempt_id, method_id)
);

CREATE INDEX IF NOT EXISTS idx_attempts_user ON attempts(user_id);
CREATE INDEX IF NOT EXISTS idx_results_method ON results(method_id, level);
"""


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript(SCHEMA)
    db.commit()


@click.command("init-db")
def init_db_command():
    """Создать таблицы."""
    init_db()
    click.echo("База данных инициализирована.")


@click.command("create-teacher")
@click.argument("email")
@click.argument("full_name")
@click.password_option()
def create_teacher_command(email, full_name, password):
    """Создать учётную запись преподавателя (доступ к разделу фильтрации)."""
    init_db()
    db = get_db()
    db.execute(
        "INSERT INTO users (email, full_name, password_hash, role) VALUES (?, ?, ?, 'teacher')",
        (email.lower(), full_name, generate_password_hash(password)),
    )
    db.commit()
    click.echo("Преподаватель создан.")


def init_app(app):
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
    app.cli.add_command(create_teacher_command)
