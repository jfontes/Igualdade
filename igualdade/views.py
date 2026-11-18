"""Telas do obreiro: painel, minhas informações, familiares, aniversariantes e quadro."""
import json
from datetime import date

from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)
from flask_login import current_user, login_required

from . import fotos
from .auth import pode_editar
from .db import get_db
from .util import (DATAS_HONORIFICAS, DATAS_MACONICAS, DATAS_OPCIONAIS, MESES, PARENTESCOS, UFS, cpf_valido, ler_data,
                   ler_data_nasc, ler_email, ler_telefone, so_digitos, validar_cronologia)

bp = Blueprint("main", __name__)

CAMPOS_PESSOAIS = ["nome", "data_nascimento", "data_iniciacao", "data_elevacao",
                   "data_exaltacao", "data_filiacao", "data_instalacao",
                   "email", "telefone", "cep", "logradouro", "numero", "bairro", "cidade", "estado"]
CAMPOS_ADMIN = ["cim", "cpf", "data_emerito", "data_vm_honra", "data_afastamento"]


# ---------------------------------------------------------------- helpers

def buscar_obreiro(obreiro_id: int):
    row = get_db().execute("SELECT * FROM obreiro WHERE id = ?", (obreiro_id,)).fetchone()
    if row is None:
        abort(404)
    return row


ROTULOS_DATAS = dict(DATAS_MACONICAS) | dict(DATAS_HONORIFICAS) | {"data_afastamento": "Afastamento"}


def ler_form_obreiro(form, completo: bool, obreiro_id: int | None = None,
                     campos: list[str] | None = None, base=None):
    """Lê e valida o formulário de obreiro. `completo` inclui CIM, CPF e afastamento (admin).

    `campos` limita a leitura a parte dos campos pessoais (assistente de primeiro acesso);
    `base` traz os dados atuais do obreiro, para validar a ordem das datas com o conjunto todo.
    """
    if campos is None:
        campos = CAMPOS_PESSOAIS + (CAMPOS_ADMIN if completo else [])
    dados, erros = {}, []
    for campo in campos:
        valor = (form.get(campo) or "").strip()
        if campo == "data_nascimento":
            try:
                valor = ler_data_nasc(form, campo)
            except ValueError as e:
                erros.append(f"Data de nascimento inválida ({e}).")
                valor = None
        elif campo.startswith("data_"):
            try:
                valor = ler_data(valor)
            except ValueError:
                rotulo = ROTULOS_DATAS.get(campo, campo.removeprefix("data_"))
                erros.append(f"A data de {rotulo} está incompleta ou é inválida.")
                valor = None
        elif campo == "email":
            try:
                valor = ler_email(valor)
            except ValueError:
                erros.append("E-mail inválido.")
                valor = None
        elif campo == "telefone":
            try:
                valor = ler_telefone(valor)
            except ValueError:
                erros.append("Telefone inválido: informe DDD + número, ex.: (68) 99999-9999.")
                valor = None
        elif campo in ("cim", "cpf", "cep"):
            valor = so_digitos(valor) or None
        elif campo in ("nome", "logradouro", "bairro", "cidade"):
            valor = " ".join(valor.upper().split()) or None
        elif campo == "estado":
            valor = valor.upper() if valor.upper() in UFS else None
        else:
            valor = valor or None
        dados[campo] = valor

    if "nome" in dados and not dados["nome"]:
        erros.append("Informe o nome completo.")
    if dados.get("cep") and len(dados["cep"]) != 8:
        erros.append("CEP deve ter 8 dígitos.")
    if completo:
        if not dados["cim"]:
            erros.append("Informe o CIM.")
        if not cpf_valido(dados["cpf"] or ""):
            erros.append("CPF inválido.")
        # RN01 — unicidade de CIM e CPF
        db = get_db()
        for campo, rotulo in (("cim", "CIM"), ("cpf", "CPF")):
            if dados[campo]:
                outro = db.execute(f"SELECT nome FROM obreiro WHERE {campo} = ? AND id IS NOT ?",
                                   (dados[campo], obreiro_id)).fetchone()
                if outro:
                    erros.append(f"Este {rotulo} já está cadastrado para {outro['nome']}.")
    erros += validar_cronologia({**(dict(base) if base else {}), **dados})
    return dados, erros


def contexto_form():
    return {"UFS": UFS, "DATAS_MACONICAS": DATAS_MACONICAS, "DATAS_HONORIFICAS": DATAS_HONORIFICAS}


# ---------------------------------------------------------------- painel

@bp.route("/")
@login_required
def painel():
    db = get_db()
    mes = date.today().strftime("%m")
    total_ativos = db.execute(
        "SELECT COUNT(*) FROM obreiro WHERE data_afastamento IS NULL").fetchone()[0]
    aniversarios = len(consultar_aniversariantes(mes))
    from .sessoes import proxima_sessao
    from .tesouraria import resumo_obreiro
    proxima, cancelada = proxima_sessao()
    return render_template("painel.html", total_ativos=total_ativos, aniversarios=aniversarios,
                           mes_nome=MESES[int(mes) - 1], proxima=proxima, cancelada=cancelada,
                           hoje=date.today().isoformat(), tesouraria=resumo_obreiro(current_user.id))


# ---------------------------------------------------------------- RF03

@bp.route("/minhas-informacoes", methods=["GET", "POST"])
@login_required
def minhas_informacoes():
    obreiro = buscar_obreiro(current_user.id)
    if request.method == "POST":
        dados, erros = ler_form_obreiro(request.form, completo=False, obreiro_id=obreiro["id"])
        if not erros:
            dados["foto"], erro_foto = fotos.processar_upload(request.form, request.files, obreiro["foto"])
            if erro_foto:
                erros.append(erro_foto)
        if erros:
            for e in erros:
                flash(e, "erro")
            if dados.get("foto") not in (None, obreiro["foto"]):
                fotos.apagar(dados["foto"])
            return render_template("obreiro_form.html",
                                   o=dados | {k: obreiro[k] for k in CAMPOS_ADMIN + ["id", "foto"]},
                                   modo="proprio", **contexto_form())
        sets = ", ".join(f"{c} = ?" for c in dados)
        get_db().execute(f"UPDATE obreiro SET {sets} WHERE id = ?", (*dados.values(), obreiro["id"]))
        get_db().commit()
        if dados["foto"] != obreiro["foto"]:
            fotos.apagar(obreiro["foto"])
        flash("Suas informações foram atualizadas.", "ok")
        return redirect(url_for("main.minhas_informacoes"))
    return render_template("obreiro_form.html", o=obreiro, modo="proprio", **contexto_form())


# ---------------------------------------------------------------- RF06 / RF07

@bp.route("/familiares")
@login_required
def meus_familiares():
    return redirect(url_for("main.familiares", obreiro_id=current_user.id))


@bp.route("/obreiros/<int:obreiro_id>/familiares")
@login_required
def familiares(obreiro_id):
    if not pode_editar(obreiro_id):
        abort(403)
    obreiro = buscar_obreiro(obreiro_id)
    lista = get_db().execute(
        "SELECT * FROM familiar WHERE obreiro_id = ? ORDER BY nome",
        (obreiro_id,)).fetchall()
    return render_template("familiares.html", obreiro=obreiro, familiares=lista)


def ler_form_familiar(form):
    dados = {
        "nome": " ".join((form.get("nome") or "").upper().split()),
        "parentesco": (form.get("parentesco") or "").strip(),
        "data_nascimento": None,
    }
    erros = []
    try:
        dados["data_nascimento"] = ler_data_nasc(form, "data_nascimento")
    except ValueError as e:
        erros.append(f"Data de nascimento inválida ({e}).")
    if dados["data_nascimento"] and dados["data_nascimento"] > date.today().isoformat():
        erros.append("A data de nascimento não pode estar no futuro.")
    if not dados["nome"]:
        erros.append("Informe o nome do familiar.")
    if dados["parentesco"] not in PARENTESCOS:
        erros.append("Selecione o grau de parentesco.")
    return dados, erros


def buscar_familiar(obreiro_id: int, familiar_id: int):
    row = get_db().execute("SELECT * FROM familiar WHERE id = ? AND obreiro_id = ?",
                           (familiar_id, obreiro_id)).fetchone()
    if row is None:
        abort(404)
    return row


def gravar_familiar(obreiro_id: int, familiar=None):
    """Valida o formulário e inclui (familiar=None) ou atualiza o familiar.

    Retorna (dados, erros). Com erros nada é gravado e `dados` serve para reapresentar o formulário.
    """
    dados, erros = ler_form_familiar(request.form)
    foto_atual = familiar["foto"] if familiar else None
    if not erros:
        dados["foto"], erro_foto = fotos.processar_upload(request.form, request.files, foto_atual)
        if erro_foto:
            erros.append(erro_foto)
    if erros:
        if dados.get("foto") not in (None, foto_atual):
            fotos.apagar(dados["foto"])
        return dados | {"id": familiar["id"] if familiar else None, "foto": foto_atual}, erros
    db = get_db()
    if familiar is None:
        db.execute("INSERT INTO familiar (obreiro_id, nome, parentesco, data_nascimento, foto) "
                   "VALUES (?, ?, ?, ?, ?)", (obreiro_id, *dados.values()))
    else:
        db.execute("UPDATE familiar SET nome = ?, parentesco = ?, data_nascimento = ?, foto = ? "
                   "WHERE id = ?", (*dados.values(), familiar["id"]))
    db.commit()
    if dados["foto"] != foto_atual:
        fotos.apagar(foto_atual)
    return dados, []


def remover_familiar(obreiro_id: int, familiar_id: int):
    db = get_db()
    row = db.execute("SELECT foto FROM familiar WHERE id = ? AND obreiro_id = ?",
                     (familiar_id, obreiro_id)).fetchone()
    db.execute("DELETE FROM familiar WHERE id = ? AND obreiro_id = ?", (familiar_id, obreiro_id))
    db.commit()
    if row:
        fotos.apagar(row["foto"])


@bp.route("/obreiros/<int:obreiro_id>/familiares/novo", methods=["GET", "POST"])
@bp.route("/obreiros/<int:obreiro_id>/familiares/<int:familiar_id>", methods=["GET", "POST"])
@login_required
def familiar_form(obreiro_id, familiar_id=None):
    if not pode_editar(obreiro_id):
        abort(403)
    obreiro = buscar_obreiro(obreiro_id)
    familiar = buscar_familiar(obreiro_id, familiar_id) if familiar_id is not None else None
    if request.method == "POST":
        dados, erros = gravar_familiar(obreiro_id, familiar)
        if not erros:
            flash(f"{dados['nome']} incluído(a)." if familiar is None else "Familiar atualizado.", "ok")
            return redirect(url_for("main.familiares", obreiro_id=obreiro_id))
        for e in erros:
            flash(e, "erro")
        familiar = dados
    return render_template("familiar_form.html", obreiro=obreiro, f=familiar,
                           familiar_id=familiar_id, PARENTESCOS=PARENTESCOS)


@bp.route("/obreiros/<int:obreiro_id>/familiares/<int:familiar_id>/excluir", methods=["POST"])
@login_required
def familiar_excluir(obreiro_id, familiar_id):
    if not pode_editar(obreiro_id):
        abort(403)
    remover_familiar(obreiro_id, familiar_id)
    flash("Familiar removido.", "ok")
    return redirect(url_for("main.familiares", obreiro_id=obreiro_id))


# ---------------------------------------------------------------- RF08

def consultar_aniversariantes(mes: str):
    """Obreiros ativos e familiares de obreiros ativos que fazem aniversário no mês (MM).

    Mês e dia são lidos do fim do texto, o que funciona para AAAA-MM-DD e para --MM-DD.
    """
    return get_db().execute("""
        SELECT o.id AS obreiro_id, NULL AS familiar_id, o.foto, o.nome, 'Obreiro' AS vinculo, NULL AS de,
               o.data_nascimento, CAST(substr(o.data_nascimento, -2) AS INTEGER) AS dia
          FROM obreiro o
         WHERE o.data_afastamento IS NULL AND substr(o.data_nascimento, -5, 2) = :mes
        UNION ALL
        SELECT o.id, f.id, f.foto, f.nome, f.parentesco, o.nome,
               f.data_nascimento, CAST(substr(f.data_nascimento, -2) AS INTEGER)
          FROM familiar f JOIN obreiro o ON o.id = f.obreiro_id
         WHERE o.data_afastamento IS NULL AND substr(f.data_nascimento, -5, 2) = :mes
         ORDER BY dia, nome
    """, {"mes": mes}).fetchall()


@bp.route("/aniversariantes")
@login_required
def aniversariantes():
    return redirect(url_for("main.agenda", **request.args))


@bp.route("/agenda")
@login_required
def agenda():
    """Compromissos do mês: sessões da Loja e aniversários, na mesma lista, por dia."""
    from .sessoes import sessoes_do_mes
    hoje = date.today()
    try:
        mes = int(request.args.get("mes", hoje.month))
        ano = int(request.args.get("ano", hoje.year))
        if not (1 <= mes <= 12 and 2000 <= ano <= 2100):
            raise ValueError
    except ValueError:
        mes, ano = hoje.month, hoje.year
    from .balaustre import concluido
    itens = [{"tipo": "sessao", "dia": int(s["data"][8:]), "s": s,
              "balaustre": bool(s["balaustre_dados"]) and concluido(json.loads(s["balaustre_dados"]))}
             for s in sessoes_do_mes(ano, mes)]
    itens += [{"tipo": "aniversario", "dia": a["dia"], "a": a}
              for a in consultar_aniversariantes(f"{mes:02d}")]
    itens.sort(key=lambda i: (i["dia"], i["tipo"] != "sessao"))
    return render_template("agenda.html", itens=itens, mes=mes, ano=ano, MESES=MESES, hoje=hoje)


# ---------------------------------------------------------------- RF04

@bp.route("/obreiros")
@login_required
def obreiros():
    q = (request.args.get("q") or "").strip()
    situacao = request.args.get("situacao", "ativos")
    sql = "SELECT id, nome, cim, foto, data_exaltacao, data_elevacao, data_iniciacao, data_afastamento, admin, cadastro_confirmado, data_emerito, data_vm_honra FROM obreiro WHERE 1=1"
    params = []
    if situacao == "ativos":
        sql += " AND data_afastamento IS NULL"
    elif situacao == "afastados":
        sql += " AND data_afastamento IS NOT NULL"
    if q:
        sql += " AND (nome LIKE ? OR cim LIKE ?)"
        params += [f"%{q.upper()}%", f"%{so_digitos(q) or q}%"]
    sql += " ORDER BY nome"
    lista = get_db().execute(sql, params).fetchall()
    return render_template("obreiros.html", lista=lista, q=q, situacao=situacao)


# ---------------------------------------------------------------- arquivo histórico

@bp.route("/obreiros-antigos")
@login_required
def historico():
    q = (request.args.get("q") or "").strip()
    situacao = request.args.get("situacao", "")
    db = get_db()
    sql = "SELECT id, cim, nome, situacao, data_iniciacao, data_exaltacao FROM obreiro_historico WHERE 1=1"
    params = []
    if q:
        sql += " AND (nome LIKE ? OR cim = ?)"
        params += [f"%{q.upper()}%", so_digitos(q) or q]
    if situacao:
        sql += " AND IFNULL(situacao, 'Não informada') = ?"
        params.append(situacao)
    lista = db.execute(sql + " ORDER BY nome", params).fetchall()
    situacoes = db.execute(
        "SELECT IFNULL(situacao, 'Não informada') AS s, COUNT(*) AS n FROM obreiro_historico "
        "GROUP BY s ORDER BY n DESC").fetchall()
    total = db.execute("SELECT COUNT(*) FROM obreiro_historico").fetchone()[0]
    return render_template("historico.html", lista=lista, q=q, situacao=situacao,
                           situacoes=situacoes, total=total)


@bp.route("/obreiros-antigos/<int:registro_id>")
@login_required
def historico_detalhe(registro_id):
    h = get_db().execute("SELECT * FROM obreiro_historico WHERE id = ?", (registro_id,)).fetchone()
    if h is None:
        abort(404)
    return render_template("historico_detalhe.html", h=h)


@bp.route("/obreiros/<int:obreiro_id>")
@login_required
def perfil(obreiro_id):
    obreiro = buscar_obreiro(obreiro_id)
    completo = pode_editar(obreiro_id)
    # Nome, parentesco e aniversário dos familiares são visíveis a todos;
    # ano de nascimento, idade e foto, só ao próprio obreiro e à Secretaria.
    familiares = get_db().execute(
        "SELECT * FROM familiar WHERE obreiro_id = ? ORDER BY nome", (obreiro_id,)).fetchall()
    from .tesouraria import resumo_obreiro, ve_relatorios
    tesouraria = resumo_obreiro(obreiro_id) if ve_relatorios() else None
    return render_template("perfil.html", o=obreiro, completo=completo, familiares=familiares, tesouraria=tesouraria,
                           DATAS_MACONICAS=DATAS_MACONICAS + DATAS_HONORIFICAS, DATAS_OPCIONAIS=DATAS_OPCIONAIS)
