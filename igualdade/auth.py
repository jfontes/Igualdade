"""Login por CIM + senha, troca de senha obrigatória e controle de permissões."""
from functools import wraps

from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   session, url_for)
from flask_login import (LoginManager, UserMixin, current_user, login_required,
                         login_user, logout_user)
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db
from .util import so_digitos

bp = Blueprint("auth", __name__)
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Entre com seu CIM e senha para continuar."
login_manager.login_message_category = "aviso"

SENHA_MIN = 6


class Usuario(UserMixin):
    def __init__(self, row):
        self.id = row["id"]
        self.nome = row["nome"]
        self.admin = bool(row["admin"])
        self.trocar_senha = bool(row["trocar_senha"])

    @property
    def primeiro_nome(self):
        return self.nome.split()[0].title() if self.nome else ""


@login_manager.user_loader
def carregar_usuario(user_id):
    row = get_db().execute(
        "SELECT id, nome, admin, trocar_senha, data_afastamento FROM obreiro WHERE id = ?",
        (user_id,)).fetchone()
    if row is None or row["data_afastamento"]:
        return None  # afastados perdem o acesso
    return Usuario(row)


def hash_senha(senha: str) -> str:
    return generate_password_hash(senha)


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapper(*args, **kwargs):
        if not current_user.admin:
            abort(403)
        return view(*args, **kwargs)
    return wrapper


def pode_editar(obreiro_id: int) -> bool:
    return current_user.is_authenticated and (current_user.admin or current_user.id == obreiro_id)


def _destino_seguro(destino: str | None) -> str:
    if destino and destino.startswith("/") and not destino.startswith("//"):
        return destino
    return url_for("main.painel")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.painel"))
    if request.method == "POST":
        cim = so_digitos(request.form.get("cim"))
        senha = request.form.get("senha", "")
        row = get_db().execute("SELECT * FROM obreiro WHERE cim = ?", (cim,)).fetchone()
        if row is None or not check_password_hash(row["senha_hash"], senha):
            flash("CIM ou senha incorretos.", "erro")
        elif row["data_afastamento"]:
            flash("Acesso indisponível: cadastro afastado. Procure a Secretaria.", "erro")
        else:
            session.permanent = True
            login_user(Usuario(row), remember=bool(request.form.get("lembrar")))
            return redirect(_destino_seguro(request.args.get("next")))
    return render_template("login.html")


@bp.route("/sair", methods=["POST"])
def logout():
    logout_user()
    flash("Você saiu do sistema.", "ok")
    return redirect(url_for("auth.login"))


@bp.route("/trocar-senha", methods=["GET", "POST"])
@login_required
def trocar_senha():
    if request.method == "POST":
        atual = request.form.get("atual", "")
        nova = request.form.get("nova", "")
        confirma = request.form.get("confirma", "")
        db = get_db()
        row = db.execute("SELECT senha_hash, cpf FROM obreiro WHERE id = ?",
                         (current_user.id,)).fetchone()
        if not check_password_hash(row["senha_hash"], atual):
            flash("Senha atual incorreta.", "erro")
        elif len(nova) < SENHA_MIN:
            flash(f"A nova senha deve ter pelo menos {SENHA_MIN} caracteres.", "erro")
        elif nova != confirma:
            flash("A confirmação não confere com a nova senha.", "erro")
        elif nova in (atual, row["cpf"]):
            flash("Escolha uma senha diferente da atual e do seu CPF.", "erro")
        else:
            db.execute("UPDATE obreiro SET senha_hash = ?, trocar_senha = 0 WHERE id = ?",
                       (hash_senha(nova), current_user.id))
            db.commit()
            flash("Senha alterada com sucesso.", "ok")
            return redirect(url_for("main.painel"))
    return render_template("trocar_senha.html")


def init_app(app):
    login_manager.init_app(app)

    @app.before_request
    def exigir_troca_de_senha():
        livres = {"auth.trocar_senha", "auth.logout", "static", "service_worker", "manifest"}
        if (current_user.is_authenticated and current_user.trocar_senha
                and request.endpoint not in livres):
            if request.endpoint != "auth.login":
                flash("Primeiro acesso: defina uma nova senha pessoal.", "aviso")
            return redirect(url_for("auth.trocar_senha"))
