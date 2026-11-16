"""Sistema de Gestão de Obreiros e Familiares — Igualdade Acreana Nº 2."""
import os
import secrets
from datetime import timedelta
from pathlib import Path

from flask import Flask, flash, redirect, request, send_from_directory
from flask_wtf.csrf import CSRFProtect

from . import db, util
from .config import LOJA

csrf = CSRFProtect()


def _secret_key(instance: Path) -> str:
    """Usa SECRET_KEY do ambiente ou gera uma e guarda em instance/secret_key."""
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    arquivo = instance / "secret_key"
    if not arquivo.exists():
        arquivo.write_text(secrets.token_hex(32), encoding="utf-8")
    return arquivo.read_text(encoding="utf-8").strip()


def create_app() -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    instance = Path(app.instance_path)
    instance.mkdir(parents=True, exist_ok=True)

    app.config.update(
        SECRET_KEY=_secret_key(instance),
        DATABASE=os.environ.get("DATABASE", str(instance / "igualdade.db")),
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
        REMEMBER_COOKIE_DURATION=timedelta(days=30),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        # Em produção (HTTPS) defina COOKIE_SEGURO=1 no wsgi.py
        SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SEGURO") == "1",
        REMEMBER_COOKIE_SECURE=os.environ.get("COOKIE_SEGURO") == "1",
        MAX_CONTENT_LENGTH=20 * 1024 * 1024,  # fotos de celular chegam a ~10 MB
    )

    db.init_app(app)
    csrf.init_app(app)

    from . import auth, views, admin, fotos
    auth.init_app(app)
    app.register_blueprint(fotos.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(views.bp)
    app.register_blueprint(admin.bp)
    app.cli.add_command(admin.criar_admin_command)

    app.jinja_env.filters["data"] = util.fmt_data
    app.jinja_env.filters["cpf"] = util.fmt_cpf
    app.jinja_env.filters["cep"] = util.fmt_cep
    app.jinja_env.filters["tel"] = util.fmt_tel
    app.jinja_env.filters["partes"] = util.partes_data
    app.jinja_env.tests["com_ano"] = util.tem_ano

    @app.context_processor
    def globais():
        return {"LOJA": LOJA}

    # O service worker precisa ser servido na raiz para controlar o site todo (PWA)
    @app.route("/sw.js")
    def service_worker():
        resp = send_from_directory(app.static_folder, "sw.js", mimetype="application/javascript")
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    @app.route("/manifest.webmanifest")
    def manifest():
        return send_from_directory(app.static_folder, "manifest.webmanifest",
                                   mimetype="application/manifest+json")

    @app.errorhandler(413)
    def arquivo_grande(_e):
        flash("A foto é grande demais (máximo 20 MB). Escolha outra imagem.", "erro")
        return redirect(request.full_path)

    @app.after_request
    def cabecalhos_seguranca(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        return resp

    return app
