import os
import secrets

import click
from flask import Flask, abort, request, session

from . import db
from .methods.base import DATA_DIR, load_methodologies
from .validator import validate


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-me"),
        DATABASE=os.path.join(app.instance_path, "app.sqlite3"),
        # Порядок методик в опросе. None = все найденные в app/methods/data.
        METHOD_ORDER=None,
        MIN_METHODS=1,
    )
    if test_config:
        app.config.update(test_config)
    os.makedirs(app.instance_path, exist_ok=True)

    app.methods, app.method_errors = load_methodologies(app.config.get("METHODS_DIR") or DATA_DIR)

    db.init_app(app)
    with app.app_context():
        db.init_db()

    @app.before_request
    def csrf_protect():
        if request.method == "POST":
            token = session.get("_csrf")
            if app.config.get("TESTING") and not app.config.get("CSRF_IN_TESTS"):
                return
            if not token or token != request.form.get("_csrf"):
                abort(400, "Неверный CSRF-токен")

    @app.context_processor
    def inject_csrf():
        if "_csrf" not in session:
            session["_csrf"] = secrets.token_hex(16)
        return {"csrf_token": session["_csrf"]}

    from . import web
    app.register_blueprint(web.bp)

    @app.cli.command("validate")
    def validate_command():
        """Проверить целостность модуля до запуска."""
        report = validate(app.methods, app.method_errors, min_methods=app.config["MIN_METHODS"])
        for issue in report["issues"]:
            click.echo(f"[{issue['level']}] {issue['method']} / {issue['check']}: {issue['message']}")
        click.echo("OK" if report["ok"] else "ЕСТЬ ОШИБКИ")
        raise SystemExit(0 if report["ok"] else 1)

    return app
