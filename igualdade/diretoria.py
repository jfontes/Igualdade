"""Diretoria da Loja: gestões e quadro de oficiais (base da mesa do balaústre)."""
import unicodedata
from datetime import date

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import login_required

from .auth import admin_required
from .config import CARGOS, CARGOS_MESA
from .db import get_db
from .util import ler_data, nome_proprio

bp = Blueprint("diretoria", __name__)

NOMES_CARGOS = dict(CARGOS)


# ---------------------------------------------------------------- consultas

def _chave(nome: str) -> str:
    """Compara nomes sem acento, caixa ou espaços duplicados."""
    sem_acento = unicodedata.normalize("NFKD", nome or "").encode("ascii", "ignore").decode()
    return " ".join(sem_acento.lower().split())


def obreiros_ativos():
    """[(id, nome no padrão do balaústre)] dos obreiros ativos, para as listas de sugestão."""
    return [(r["id"], nome_proprio(r["nome"])) for r in get_db().execute(
        "SELECT id, nome FROM obreiro WHERE data_afastamento IS NULL ORDER BY nome")]


def gestao_vigente(data_iso: str | None = None):
    data_iso = data_iso or date.today().isoformat()
    return get_db().execute(
        "SELECT * FROM gestao WHERE inicio <= ? AND fim >= ? ORDER BY inicio DESC, id DESC LIMIT 1",
        (data_iso, data_iso)).fetchone()


def cargos_da_gestao(gestao_id: int) -> dict:
    """{cargo: linha da tabela diretoria}"""
    return {r["cargo"]: r for r in get_db().execute(
        "SELECT * FROM diretoria WHERE gestao_id = ?", (gestao_id,))}


def mesa_na_data(data_iso: str) -> dict | None:
    """Mesa (Venerável, Vigilantes, Orador e Secretário) da gestão vigente na data, ou None."""
    gestao = gestao_vigente(data_iso)
    if gestao is None:
        return None
    cargos = cargos_da_gestao(gestao["id"])
    return {c: (cargos[c]["nome"] if c in cargos else "") for c in CARGOS_MESA}


def _periodo(g) -> str:
    return f"{g['inicio'][:4]}–{g['fim'][:4]}" if g["inicio"][:4] != g["fim"][:4] else g["inicio"][:4]


# ---------------------------------------------------------------- consulta (todos os obreiros)

@bp.route("/diretoria")
@login_required
def ver():
    db = get_db()
    gestoes = db.execute("SELECT * FROM gestao ORDER BY inicio DESC, id DESC").fetchall()
    escolhida = None
    if request.args.get("gestao"):
        escolhida = next((g for g in gestoes if str(g["id"]) == request.args["gestao"]), None)
        if escolhida is None:
            abort(404)
    vigente = gestao_vigente()
    escolhida = escolhida or vigente or (gestoes[0] if gestoes else None)
    cargos = cargos_da_gestao(escolhida["id"]) if escolhida else {}
    return render_template("diretoria.html", gestoes=gestoes, g=escolhida, vigente=vigente,
                           cargos=cargos, CARGOS=CARGOS, periodo=_periodo)


# ---------------------------------------------------------------- cadastro (Secretaria)

def _ler_form(form):
    erros = {}
    dados = {"observacao": " ".join((form.get("observacao") or "").split()) or None}
    for campo in ("inicio", "fim"):
        try:
            dados[campo] = ler_data(form.get(campo))
        except ValueError:
            dados[campo] = None
        if not dados[campo]:
            erros[campo] = "Informe a data."
    if dados["inicio"] and dados["fim"] and dados["fim"] < dados["inicio"]:
        erros["fim"] = "O fim da gestão deve ser depois do início."

    ativos = {_chave(n): (i, n) for i, n in obreiros_ativos()}
    nomes = {}
    for cargo, _rotulo in CARGOS:
        digitado = " ".join((form.get(f"cargo_{cargo}") or "").split())
        if not digitado:
            continue
        obreiro_id, nome = ativos.get(_chave(digitado), (None, nome_proprio(digitado)))
        nomes[cargo] = {"obreiro_id": obreiro_id, "nome": nome}
    for cargo in CARGOS_MESA:
        if cargo not in nomes:
            erros[f"cargo_{cargo}"] = "Cargo obrigatório: compõe a mesa do balaústre."
    return dados, nomes, erros


def _conflito(dados, gestao_id):
    """Outra gestão com período sobreposto deixaria a mesa ambígua."""
    return get_db().execute(
        "SELECT * FROM gestao WHERE inicio <= ? AND fim >= ? AND id IS NOT ? LIMIT 1",
        (dados["fim"], dados["inicio"], gestao_id)).fetchone()


@bp.route("/admin/diretoria/nova", methods=["GET", "POST"])
@bp.route("/admin/diretoria/<int:gestao_id>", methods=["GET", "POST"])
@admin_required
def form(gestao_id=None):
    db = get_db()
    gestao = None
    if gestao_id is not None:
        gestao = db.execute("SELECT * FROM gestao WHERE id = ?", (gestao_id,)).fetchone()
        if gestao is None:
            abort(404)
    erros = {}
    if request.method == "POST":
        dados, nomes, erros = _ler_form(request.form)
        if not erros and (outra := _conflito(dados, gestao_id)):
            erros["inicio"] = f"O período coincide com a gestão {_periodo(outra)}. Ajuste as datas."
        if not erros:
            if gestao is None:
                gestao_id = db.execute("INSERT INTO gestao (inicio, fim, observacao) VALUES (?, ?, ?)",
                                       (dados["inicio"], dados["fim"], dados["observacao"])).lastrowid
                flash("Diretoria cadastrada.", "ok")
            else:
                db.execute("UPDATE gestao SET inicio = ?, fim = ?, observacao = ? WHERE id = ?",
                           (dados["inicio"], dados["fim"], dados["observacao"], gestao_id))
                flash("Diretoria atualizada.", "ok")
            db.execute("DELETE FROM diretoria WHERE gestao_id = ?", (gestao_id,))
            db.executemany(
                "INSERT INTO diretoria (gestao_id, cargo, obreiro_id, nome) VALUES (?, ?, ?, ?)",
                [(gestao_id, c, v["obreiro_id"], v["nome"]) for c, v in nomes.items()])
            db.commit()
            destino = request.args.get("voltar")
            if destino and destino.startswith("/") and not destino.startswith("//"):
                return redirect(destino)
            return redirect(url_for("diretoria.ver", gestao=gestao_id))
        flash("Corrija o campo destacado abaixo." if len(erros) == 1
              else "Corrija os campos destacados abaixo.", "erro")
        g = dados
        valores = {c: v["nome"] for c, v in nomes.items()}
    elif gestao is not None:
        g = dict(gestao)
        valores = {c: r["nome"] for c, r in cargos_da_gestao(gestao_id).items()}
    else:
        # Nova gestão: começa com os nomes da gestão mais recente (só os cargos que mudam são digitados)
        ano = date.today().year
        g = {"inicio": f"{ano}-01-01", "fim": f"{ano + 1}-12-31"}
        ultima = db.execute("SELECT id FROM gestao ORDER BY inicio DESC, id DESC LIMIT 1").fetchone()
        valores = {c: r["nome"] for c, r in cargos_da_gestao(ultima["id"]).items()} if ultima else {}
    return render_template("diretoria_form.html", g=g, gestao_id=gestao_id, valores=valores,
                           CARGOS=CARGOS, CARGOS_MESA=CARGOS_MESA, erros=erros,
                           ativos=obreiros_ativos())


@bp.route("/admin/diretoria/<int:gestao_id>/excluir", methods=["POST"])
@admin_required
def excluir(gestao_id):
    db = get_db()
    db.execute("DELETE FROM gestao WHERE id = ?", (gestao_id,))
    db.commit()
    flash("Diretoria excluída.", "ok")
    return redirect(url_for("diretoria.ver"))
