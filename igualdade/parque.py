"""Parque das Acácias: contratos de locação da área de eventos (painel do administrador do Parque).

Fluxo: cadastro do contrato → (vistoria fotográfica pelo caseiro, se exigida) → link de assinatura
para o contratante (válido por 7 dias) → assinatura → PDF consolidado + e-mail.

Acesso: Administrador do Parque (marcação no cadastro do obreiro), Venerável da gestão vigente e
Administrador do sistema. O caseiro usa uma página separada (/vistoria) com código de acesso.

Arquivos ficam em instance/contratos/<id>/ (fora de static/); o banco guarda caminho e SHA-256.
"""
import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

from flask import (Blueprint, abort, current_app, flash, redirect, render_template, request,
                   send_file, url_for)
from flask_login import current_user, login_required
from werkzeug.security import check_password_hash, generate_password_hash

from . import email_service
from .config import LOJA, PARQUE
from .db import get_db
from .util import (cpf_cnpj_valido, fmt_cpf_cnpj, fmt_data, fmt_moeda, ler_data, ler_email, ler_moeda,
                   so_digitos)

bp = Blueprint("parque", __name__, url_prefix="/parque")

AGUARDANDO_VISTORIA = "AGUARDANDO_VISTORIA"
AGUARDANDO_ASSINATURA = "AGUARDANDO_ASSINATURA"
ASSINADO = "ASSINADO"
CANCELADO = "CANCELADO"
STATUS = {
    AGUARDANDO_VISTORIA: ("Aguardando vistoria", "🔍"),
    AGUARDANDO_ASSINATURA: ("Aguardando assinatura", "✍️"),
    ASSINADO: ("Assinado", "✅"),
    CANCELADO: ("Cancelado", "⚫"),
}
ALFABETO_CODIGO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sem 0/O, 1/I


def agora_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------- permissões

def gere_parque() -> bool:
    if not current_user.is_authenticated:
        return False
    from .auth import cargos_vigentes
    return bool(getattr(current_user, "admin_cadastro", False) or getattr(current_user, "admin_parque", False)
                or "veneravel" in cargos_vigentes().get(current_user.id, set()))


def parque_required(view):
    @wraps(view)
    @login_required
    def wrapper(*args, **kwargs):
        if not gere_parque():
            abort(403)
        return view(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------- arquivos (instance/contratos/<id>/)

def pasta_contratos() -> Path:
    p = Path(current_app.instance_path) / "contratos"
    p.mkdir(parents=True, exist_ok=True)
    return p


def salvar_arquivo(contrato_id: int, nome: str, dados: bytes) -> tuple[str, str]:
    """Grava e devolve (caminho relativo, sha256)."""
    pasta = pasta_contratos() / str(contrato_id)
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / nome).write_bytes(dados)
    return f"{contrato_id}/{nome}", hashlib.sha256(dados).hexdigest()


def ler_arquivo(relativo: str | None) -> bytes | None:
    if not relativo:
        return None
    caminho = (pasta_contratos() / relativo).resolve()
    if pasta_contratos().resolve() not in caminho.parents or not caminho.is_file():
        return None
    return caminho.read_bytes()


def apagar_arquivo(relativo: str | None):
    if relativo:
        try:
            (pasta_contratos() / relativo).unlink(missing_ok=True)
        except OSError as e:
            current_app.logger.warning("Não foi possível apagar %s: %s", relativo, e)


# ---------------------------------------------------------------- consultas

def buscar(contrato_id: int):
    c = get_db().execute("SELECT * FROM contrato WHERE id = ?", (contrato_id,)).fetchone()
    if c is None:
        abort(404)
    return c


def detalhar(c) -> dict:
    d = dict(c)
    d["evento"] = json.loads(c["evento_dados_json"] or "{}")
    d["contratante"] = json.loads(c["contratante_dados_json"] or "{}")
    d["status_rotulo"], d["status_icone"] = STATUS[c["status"]]
    d["link_expirado"] = (c["status"] == AGUARDANDO_ASSINATURA and c["token_expira_em"]
                          and c["token_expira_em"] < iso(agora_utc()))
    return d


def fotos_da_vistoria(contrato_id: int):
    return get_db().execute("SELECT * FROM vistoria_foto WHERE contrato_id = ? ORDER BY id", (contrato_id,)).fetchall()


def url_externa(endpoint: str, **kw) -> str:
    """Endereço completo para e-mail, QR Code e link enviado ao contratante."""
    base = os.environ.get("SITE_URL")
    if base:
        return base.rstrip("/") + url_for(endpoint, **kw)
    url = url_for(endpoint, _external=True, **kw)
    if os.environ.get("COOKIE_SEGURO") == "1" and url.startswith("http://"):
        url = "https://" + url[len("http://"):]
    return url


def resumo_evento(evento: dict) -> str:
    return f"{evento.get('tipo_evento') or 'Evento'} em {fmt_data(evento.get('data'))}"


# ---------------------------------------------------------------- código de acesso do caseiro

def codigo_caseiro_definido() -> bool:
    return bool(get_db().execute("SELECT 1 FROM parque_config WHERE chave = 'codigo_caseiro'").fetchone())


def conferir_codigo_caseiro(codigo: str) -> bool:
    row = get_db().execute("SELECT valor FROM parque_config WHERE chave = 'codigo_caseiro'").fetchone()
    return bool(row and check_password_hash(row["valor"], so_digitos(codigo)))


def definir_codigo_caseiro(codigo: str):
    db = get_db()
    db.execute("INSERT INTO parque_config (chave, valor, atualizado_em) VALUES ('codigo_caseiro', ?, ?) "
               "ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor, atualizado_em = excluded.atualizado_em",
               (generate_password_hash(codigo), iso(agora_utc())))
    db.commit()


# ---------------------------------------------------------------- liberação do link de assinatura

def liberar_para_assinatura(contrato_id: int) -> tuple[str, bool, str]:
    """Gera um novo token (7 dias), muda o status e tenta enviar o e-mail. Devolve (link, enviou, motivo)."""
    db = get_db()
    token = secrets.token_urlsafe(24)
    expira = agora_utc() + timedelta(days=PARQUE["dias_validade_link"])
    db.execute("UPDATE contrato SET status = ?, token_assinatura = ?, token_expira_em = ?, link_enviado_em = ?, "
               "pdf_pre_arquivo = NULL, hash_pre_assinatura = NULL WHERE id = ?",
               (AGUARDANDO_ASSINATURA, token, iso(expira), iso(agora_utc()), contrato_id))
    db.commit()
    c = detalhar(buscar(contrato_id))
    link = url_externa("assinatura.inicio", token=token)
    texto = (f"Olá, {c['contratante_nome'].split()[0].title()}.\n\n"
             f"A {LOJA['titulo']} {LOJA['nome']} enviou o contrato de locação da área de eventos do "
             f"{PARQUE['nome']} para a sua assinatura eletrônica:\n\n"
             f"  {resumo_evento(c['evento'])}\n  Valor: {fmt_moeda(c['evento'].get('valor_total'))}\n\n"
             f"Para conferir os dados, ler o contrato e assinar pelo celular, acesse:\n{link}\n\n"
             f"O link é pessoal e vale até {fmt_data(expira.date().isoformat())}. Na assinatura serão pedidas "
             "uma foto do rosto (selfie) e a sua assinatura na tela.\n\n"
             f"Dúvidas: responda a este e-mail.\n\n{LOJA['titulo']} {LOJA['nome']}\n{PARQUE['nome']}")
    ok, motivo = email_service.enviar([c["contratante_email"]], f"Contrato de locação para assinatura – {PARQUE['nome']}",
                                      texto)
    return link, ok, motivo


# ---------------------------------------------------------------- formulário do contrato

CAMPOS_EVENTO = ["data", "hora_inicio", "hora_fim", "tipo_evento", "valor_total", "forma_pagamento",
                 "inclui_piscina", "observacoes"]


def _ler_form(form) -> tuple[dict, dict]:
    erros = {}
    d = {"contratante_nome": " ".join((form.get("contratante_nome") or "").upper().split()),
         "contratante_cpf_cnpj": so_digitos(form.get("contratante_cpf_cnpj")),
         "exige_vistoria": 1 if form.get("exige_vistoria") else 0}
    if not d["contratante_nome"]:
        erros["contratante_nome"] = "Informe o nome ou a razão social."
    if not cpf_cnpj_valido(d["contratante_cpf_cnpj"]):
        erros["contratante_cpf_cnpj"] = "CPF ou CNPJ inválido."
    try:
        d["contratante_email"] = ler_email(form.get("contratante_email"))
        if not d["contratante_email"]:
            erros["contratante_email"] = "Informe o e-mail do contratante (o link de assinatura vai para ele)."
    except ValueError:
        d["contratante_email"] = (form.get("contratante_email") or "").strip()
        erros["contratante_email"] = "E-mail inválido."
    ev = {"tipo_evento": " ".join((form.get("tipo_evento") or "").split())[:120] or None,
          "hora_inicio": (form.get("hora_inicio") or "").strip() or None,
          "hora_fim": (form.get("hora_fim") or "").strip() or None,
          "forma_pagamento": " ".join((form.get("forma_pagamento") or "").split())[:300] or None,
          "inclui_piscina": bool(form.get("inclui_piscina")),
          "observacoes": (form.get("observacoes") or "").strip()[:1000] or None}
    try:
        ev["data"] = ler_data(form.get("data"))
    except ValueError:
        ev["data"] = None
    if not ev["data"]:
        erros["data"] = "Informe a data do evento."
    if not ev["tipo_evento"]:
        erros["tipo_evento"] = "Informe o tipo de evento (ex.: casamento, aniversário)."
    if not (ev["hora_inicio"] and ev["hora_fim"]):
        erros["horario"] = "Informe o horário de início e de fim."
    try:
        ev["valor_total"] = ler_moeda(form.get("valor_total"))
        if ev["valor_total"] is None:
            erros["valor_total"] = "Informe o valor total."
    except ValueError:
        ev["valor_total"] = None
        erros["valor_total"] = "Valor inválido."
    if not ev["forma_pagamento"]:
        erros["forma_pagamento"] = "Informe a forma e as condições de pagamento."
    d["evento"] = ev
    return d, erros


def _novo_codigo() -> str:
    while True:
        bruto = "".join(secrets.choice(ALFABETO_CODIGO) for _ in range(8))
        codigo = f"IGA-{bruto[:4]}-{bruto[4:]}"
        if not get_db().execute("SELECT 1 FROM contrato WHERE codigo_verificador = ?", (codigo,)).fetchone():
            return codigo


# ---------------------------------------------------------------- telas

@bp.route("/")
@parque_required
def lista():
    filtro = request.args.get("status", "")
    sql = "SELECT * FROM contrato"
    params = []
    if filtro in STATUS:
        sql += " WHERE status = ?"
        params.append(filtro)
    contratos = [detalhar(c) for c in get_db().execute(sql + " ORDER BY id DESC", params)]
    contratos.sort(key=lambda c: (c["status"] in (ASSINADO, CANCELADO), c["evento"].get("data") or ""))
    return render_template("parque/lista.html", contratos=contratos, filtro=filtro, STATUS=STATUS,
                           codigo_definido=codigo_caseiro_definido(), email_ok=email_service.configurado())


@bp.route("/novo", methods=["GET", "POST"])
@bp.route("/<int:contrato_id>/editar", methods=["GET", "POST"])
@parque_required
def form(contrato_id=None):
    atual = detalhar(buscar(contrato_id)) if contrato_id else None
    if atual and atual["status"] in (ASSINADO, CANCELADO):
        flash("Contrato assinado ou cancelado não pode ser alterado.", "erro")
        return redirect(url_for("parque.detalhe", contrato_id=contrato_id))
    erros = {}
    if request.method == "POST":
        d, erros = _ler_form(request.form)
        if not erros:
            db = get_db()
            evento_json = json.dumps(d["evento"], ensure_ascii=False)
            if atual is None:
                status = AGUARDANDO_VISTORIA if d["exige_vistoria"] else AGUARDANDO_ASSINATURA
                cur = db.execute(
                    "INSERT INTO contrato (codigo_verificador, status, exige_vistoria, contratante_nome, "
                    "contratante_cpf_cnpj, contratante_email, evento_dados_json, criado_em, criado_por) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (_novo_codigo(), status, d["exige_vistoria"], d["contratante_nome"], d["contratante_cpf_cnpj"],
                     d["contratante_email"], evento_json, iso(agora_utc()), current_user.id))
                db.commit()
                novo_id = cur.lastrowid
                if status == AGUARDANDO_ASSINATURA:
                    _avisar_liberacao(novo_id, *liberar_para_assinatura(novo_id))
                else:
                    flash("Contrato cadastrado. Ele aparece na fila de vistoria do caseiro; o link de assinatura "
                          "será enviado ao contratante quando a vistoria for concluída.", "ok")
                return redirect(url_for("parque.detalhe", contrato_id=novo_id))
            # edição: dados mudaram → o PDF de leitura será refeito
            db.execute("UPDATE contrato SET contratante_nome = ?, contratante_cpf_cnpj = ?, contratante_email = ?, "
                       "evento_dados_json = ?, pdf_pre_arquivo = NULL, hash_pre_assinatura = NULL WHERE id = ?",
                       (d["contratante_nome"], d["contratante_cpf_cnpj"], d["contratante_email"], evento_json,
                        contrato_id))
            db.commit()
            apagar_arquivo(atual["pdf_pre_arquivo"])
            flash("Contrato atualizado.", "ok")
            return redirect(url_for("parque.detalhe", contrato_id=contrato_id))
        flash("Corrija os campos destacados.", "erro")
        valores = d | d["evento"]
    elif atual:
        valores = atual | atual["evento"]
        valores["valor_total"] = fmt_moeda(atual["evento"].get("valor_total"), simbolo=False)
    else:
        valores = {"exige_vistoria": 1}
    if request.method == "POST" and isinstance(valores.get("valor_total"), int):
        valores["valor_total"] = fmt_moeda(valores["valor_total"], simbolo=False)
    if valores.get("contratante_cpf_cnpj"):
        valores["contratante_cpf_cnpj"] = fmt_cpf_cnpj(valores["contratante_cpf_cnpj"])
    return render_template("parque/form.html", v=valores, erros=erros, contrato=atual)


def _avisar_liberacao(contrato_id, link, enviou, motivo):
    if enviou:
        flash("Link de assinatura enviado por e-mail ao contratante (válido por 7 dias).", "ok")
    else:
        flash(f"O link de assinatura foi gerado, mas o e-mail não foi enviado ({motivo}). "
              "Copie o link na tela do contrato e envie ao contratante.", "aviso")


@bp.route("/<int:contrato_id>")
@parque_required
def detalhe(contrato_id):
    c = detalhar(buscar(contrato_id))
    link = url_externa("assinatura.inicio", token=c["token_assinatura"]) \
        if c["status"] == AGUARDANDO_ASSINATURA and c["token_assinatura"] else None
    evid = get_db().execute("SELECT * FROM assinatura_evidencia WHERE contrato_id = ?", (contrato_id,)).fetchone()
    return render_template("parque/detalhe.html", c=c, fotos=fotos_da_vistoria(contrato_id), link=link,
                           evid=evid, email_ok=email_service.configurado(),
                           url_validacao=url_externa("assinatura.validar", codigo=c["codigo_verificador"]))


@bp.route("/<int:contrato_id>/reenviar", methods=["POST"])
@parque_required
def reenviar(contrato_id):
    c = buscar(contrato_id)
    if c["status"] != AGUARDANDO_ASSINATURA:
        flash("Só é possível reenviar o link de um contrato aguardando assinatura.", "erro")
    else:
        _avisar_liberacao(contrato_id, *liberar_para_assinatura(contrato_id))
        flash("Um novo link foi gerado; o anterior deixou de valer.", "aviso")
    return redirect(url_for("parque.detalhe", contrato_id=contrato_id))


@bp.route("/<int:contrato_id>/liberar", methods=["POST"])
@parque_required
def liberar_sem_vistoria(contrato_id):
    """Libera para assinatura um contrato que aguardava vistoria (ex.: vistoria dispensada)."""
    c = buscar(contrato_id)
    if c["status"] != AGUARDANDO_VISTORIA:
        abort(400)
    _avisar_liberacao(contrato_id, *liberar_para_assinatura(contrato_id))
    return redirect(url_for("parque.detalhe", contrato_id=contrato_id))


@bp.route("/<int:contrato_id>/cancelar", methods=["POST"])
@parque_required
def cancelar(contrato_id):
    c = buscar(contrato_id)
    motivo = " ".join((request.form.get("motivo") or "").split())[:300]
    if c["status"] in (ASSINADO, CANCELADO):
        flash("Contrato assinado ou já cancelado.", "erro")
    elif not motivo:
        flash("Informe o motivo do cancelamento.", "erro")
    else:
        get_db().execute("UPDATE contrato SET status = ?, cancelado_em = ?, motivo_cancelamento = ?, "
                         "token_assinatura = NULL WHERE id = ?", (CANCELADO, iso(agora_utc()), motivo, contrato_id))
        get_db().commit()
        flash("Contrato cancelado. O link de assinatura deixou de valer.", "ok")
    return redirect(url_for("parque.detalhe", contrato_id=contrato_id))


@bp.route("/<int:contrato_id>/contrato-assinado.pdf")
@parque_required
def pdf_final(contrato_id):
    c = buscar(contrato_id)
    dados = ler_arquivo(c["pdf_final_arquivo"])
    if not dados:
        abort(404)
    import io
    return send_file(io.BytesIO(dados), mimetype="application/pdf", as_attachment=False,
                     download_name=f"contrato-{c['codigo_verificador']}.pdf")


@bp.route("/<int:contrato_id>/foto/<int:foto_id>")
@parque_required
def foto(contrato_id, foto_id):
    return enviar_foto(contrato_id, foto_id)


def enviar_foto(contrato_id, foto_id):
    import io
    f = get_db().execute("SELECT arquivo FROM vistoria_foto WHERE id = ? AND contrato_id = ?",
                         (foto_id, contrato_id)).fetchone()
    dados = ler_arquivo(f["arquivo"]) if f else None
    if not dados:
        abort(404)
    resp = send_file(io.BytesIO(dados), mimetype="image/jpeg")
    resp.headers["Cache-Control"] = "private, max-age=3600"
    return resp


@bp.route("/configuracao", methods=["GET", "POST"])
@parque_required
def configuracao():
    if request.method == "POST":
        codigo = so_digitos(request.form.get("codigo"))
        if len(codigo) != 6:
            flash("O código do caseiro deve ter 6 números.", "erro")
        elif codigo != so_digitos(request.form.get("confirmacao")):
            flash("A confirmação não confere com o código.", "erro")
        else:
            definir_codigo_caseiro(codigo)
            flash("Código de acesso do caseiro atualizado. Informe o novo código a ele.", "ok")
            return redirect(url_for("parque.lista"))
    return render_template("parque/configuracao.html", codigo_definido=codigo_caseiro_definido(),
                           url_vistoria=url_externa("vistoria.entrar"), email_ok=email_service.configurado())
