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


def cargos_vigentes() -> dict[int, set[str]]:
    """{obreiro_id: {cargos}} na gestão vigente da Diretoria (guardado durante a requisição)."""
    from flask import g
    if "cargos_vigentes" not in g:
        from datetime import date
        hoje = date.today().isoformat()
        db = get_db()
        gestao = db.execute("SELECT id FROM gestao WHERE inicio <= ? AND fim >= ? "
                            "ORDER BY inicio DESC, id DESC LIMIT 1", (hoje, hoje)).fetchone()
        cargos: dict[int, set[str]] = {}
        if gestao:
            for r in db.execute("SELECT obreiro_id, cargo FROM diretoria WHERE gestao_id = ? "
                                "AND obreiro_id IS NOT NULL", (gestao["id"],)):
                cargos.setdefault(r["obreiro_id"], set()).add(r["cargo"])
        g.cargos_vigentes = cargos
    return g.cargos_vigentes


def secretaria_vigente_ids() -> set[int]:
    """Obreiros com acesso de Secretaria pelo cargo (Secretário e Venerável) na gestão vigente."""
    from .config import CARGOS_SECRETARIA
    return {i for i, cargos in cargos_vigentes().items() if cargos & set(CARGOS_SECRETARIA)}


class Usuario(UserMixin):
    def __init__(self, row):
        self.id = row["id"]
        self.nome = row["nome"]
        # Acesso de Secretaria: Administrador OU Secretário/Venerável da gestão vigente.
        # Administrador tem o mesmo acesso do Venerável (inclusive a Tesouraria).
        self.admin_cadastro = bool(row["admin"])
        self.secretaria_por_cargo = self.id in secretaria_vigente_ids()
        self.admin = self.admin_cadastro or self.secretaria_por_cargo
        self.admin_parque = bool(row["admin_parque"]) if "admin_parque" in row.keys() else False
        self.trocar_senha = bool(row["trocar_senha"])
        # Primeiro acesso: o assistente aparece uma única vez, até ser concluído
        self.cadastro_pendente = self.trocar_senha and not row["cadastro_confirmado"]

    @property
    def primeiro_nome(self):
        return self.nome.split()[0].title() if self.nome else ""


@login_manager.user_loader
def carregar_usuario(user_id):
    row = get_db().execute(
        "SELECT id, nome, admin, admin_parque, trocar_senha, cadastro_confirmado, data_afastamento "
        "FROM obreiro WHERE id = ?",
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

    @app.context_processor
    def secretaria_vigente():
        # Selos exibidos no quadro e no perfil: cargos de gestão da gestão vigente
        nomes = {"veneravel": "Venerável Mestre", "secretario": "Secretário", "tesoureiro": "Tesoureiro"}
        selos = {i: [nomes[c] for c in nomes if c in cargos] for i, cargos in cargos_vigentes().items()}
        return {"selos_cargo": {i: s for i, s in selos.items() if s}}

    @app.before_request
    def exigir_primeiro_acesso():
        if not (current_user.is_authenticated and current_user.trocar_senha):
            return None
        livres = {"auth.logout", "static", "service_worker", "manifest",
                  "fotos.obreiro", "fotos.familiar"}
        ep = request.endpoint or ""
        if ep in livres:
            return None
        if current_user.cadastro_pendente:
            # Primeiro acesso: passo a passo (conferir dados, completar, familiares, senha)
            if ep.startswith("assistente."):
                return None
            return redirect(url_for("assistente.inicio"))
        # Senha redefinida pela Secretaria: só a troca de senha
        if ep != "auth.trocar_senha":
            if ep != "auth.login":
                flash("Defina uma nova senha pessoal para continuar.", "aviso")
            return redirect(url_for("auth.trocar_senha"))
        return None
