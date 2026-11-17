"""Agenda da Loja: sessões (cadastro pela Secretaria, gerador anual e próxima sessão)."""
import calendar
from datetime import date, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from .auth import admin_required
from .config import DIA_DA_SESSAO
from .db import get_db
from .feriados import dias_sem_sessao, recesso
from .util import MESES, ler_data

bp = Blueprint("sessoes", __name__, url_prefix="/admin/sessoes")

TIPOS = ["Ordinária", "Magna", "Extraordinária"]
GRAUS = ["Aprendiz", "Companheiro", "Mestre"]
ORDEM_MAX = 500


# ---------------------------------------------------------------- consultas

def sessoes_do_mes(ano: int, mes: int):
    return get_db().execute(
        "SELECT s.*, b.id AS balaustre_id, b.dados AS balaustre_dados FROM sessao s LEFT JOIN balaustre b ON b.sessao_id = s.id "
        "WHERE substr(s.data, 1, 7) = ? ORDER BY s.data, s.id",
        (f"{ano:04d}-{mes:02d}",)).fetchall()


def proxima_sessao():
    """Próxima sessão que vai acontecer e, se houver, a cancelada que vem antes dela.

    Retorna (proxima, cancelada) — qualquer um dos dois pode ser None.
    """
    hoje = date.today().isoformat()
    proxima = cancelada = None
    for s in get_db().execute("SELECT * FROM sessao WHERE data >= ? ORDER BY data, id LIMIT 20", (hoje,)):
        if s["cancelada"]:
            cancelada = cancelada or s
            continue
        proxima = s
        break
    return proxima, cancelada


def proximo_dia_de_sessao(hoje: date | None = None) -> date:
    """Próxima segunda-feira depois de hoje (se hoje for segunda, a da semana seguinte)."""
    hoje = hoje or date.today()
    return hoje + timedelta(days=(DIA_DA_SESSAO - hoje.weekday() - 1) % 7 + 1)


# ---------------------------------------------------------------- gerador anual

def grau_pela_posicao(posicao: int, total: int) -> str:
    """Regra da Loja: última sessão do mês é de Mestre, penúltima de Companheiro, demais de Aprendiz."""
    if posicao == total - 1:
        return "Mestre"
    if posicao == total - 2:
        return "Companheiro"
    return "Aprendiz"


def planejar_ano(ano: int):
    """Monta a lista de sessões do ano (sem gravar). Cada item traz a situação para a prévia."""
    sem_sessao = dias_sem_sessao(ano)
    existentes = {r["data"] for r in get_db().execute(
        "SELECT data FROM sessao WHERE substr(data, 1, 4) = ?", (f"{ano:04d}",))}
    meses = []
    for mes in range(1, 13):
        itens = []
        for semana in calendar.Calendar().monthdatescalendar(ano, mes):
            dia = semana[DIA_DA_SESSAO]
            if dia.month != mes:
                continue
            item = {"data": dia.isoformat(), "dia": dia.day, "grau": None,
                    "cancelada": False, "motivo": None, "situacao": "nova"}
            if (nome := recesso(dia)):
                item.update(situacao="recesso", motivo=nome)
            elif dia in sem_sessao:
                item.update(cancelada=True, motivo=sem_sessao[dia])
            if item["data"] in existentes:
                item["situacao"] = "existente"
            itens.append(item)
        realizadas = [i for i in itens if i["situacao"] != "recesso" and not i["cancelada"]]
        for pos, item in enumerate(realizadas):
            item["grau"] = grau_pela_posicao(pos, len(realizadas))
        meses.append({"mes": mes, "nome": MESES[mes - 1], "itens": itens})
    return meses


# ---------------------------------------------------------------- formulário

def _ler_form(form):
    erros = {}  # campo → mensagem (exibida ao lado do campo)
    dados = {
        "tipo": form.get("tipo") or "Ordinária",
        "grau": form.get("grau") or None,
        "ordem_do_dia": " ".join((form.get("ordem_do_dia") or "").split()) or None,
        "cancelada": 1 if form.get("cancelada") else 0,
        "motivo_cancelamento": " ".join((form.get("motivo_cancelamento") or "").split()) or None,
    }
    try:
        dados["data"] = ler_data(form.get("data"))
    except ValueError:
        dados["data"] = None
    if not dados["data"]:
        erros["data"] = "Informe a data da sessão."
    if dados["tipo"] not in TIPOS:
        erros["tipo"] = "Escolha o tipo da sessão."
    if dados["grau"] not in GRAUS + [None]:
        dados["grau"] = None
    if not dados["cancelada"] and not dados["grau"]:
        erros["grau"] = "Escolha o grau da sessão."
    if dados["cancelada"] and not dados["motivo_cancelamento"]:
        erros["motivo_cancelamento"] = "Informe o motivo do cancelamento (ex.: Feriado)."
    if not dados["cancelada"]:
        dados["motivo_cancelamento"] = None
    if dados["ordem_do_dia"] and len(dados["ordem_do_dia"]) > ORDEM_MAX:
        erros["ordem_do_dia"] = f"A ordem do dia pode ter no máximo {ORDEM_MAX} caracteres."
    return dados, erros


def _voltar_agenda(data_iso: str | None):
    if data_iso:
        return redirect(url_for("main.agenda", ano=int(data_iso[:4]), mes=int(data_iso[5:7])))
    return redirect(url_for("main.agenda"))


@bp.route("/nova", methods=["GET", "POST"])
@bp.route("/<int:sessao_id>", methods=["GET", "POST"])
@admin_required
def form(sessao_id=None):
    db = get_db()
    sessao = None
    if sessao_id is not None:
        sessao = db.execute("SELECT * FROM sessao WHERE id = ?", (sessao_id,)).fetchone()
        if sessao is None:
            abort(404)
    if request.method == "POST":
        dados, erros = _ler_form(request.form)
        if not erros:
            if sessao is None:
                db.execute("INSERT INTO sessao (tipo, grau, ordem_do_dia, cancelada, motivo_cancelamento, data) "
                           "VALUES (?, ?, ?, ?, ?, ?)", tuple(dados.values()))
                flash("Sessão incluída na agenda.", "ok")
            else:
                db.execute("UPDATE sessao SET tipo = ?, grau = ?, ordem_do_dia = ?, cancelada = ?, "
                           "motivo_cancelamento = ?, data = ? WHERE id = ?", (*dados.values(), sessao_id))
                flash("Sessão atualizada.", "ok")
            db.commit()
            return _voltar_agenda(dados["data"])
        flash("Corrija o campo destacado abaixo." if len(erros) == 1
              else "Corrija os campos destacados abaixo.", "erro")
        sessao = dados | {"id": sessao_id}
    elif sessao is None:
        sessao = {"data": request.args.get("data") or proximo_dia_de_sessao().isoformat(),
                  "tipo": "Ordinária", "grau": "Aprendiz"}
    return render_template("sessao_form.html", s=sessao, sessao_id=sessao_id, TIPOS=TIPOS, GRAUS=GRAUS,
                           erros=erros if request.method == "POST" else {})


@bp.route("/<int:sessao_id>/excluir", methods=["POST"])
@admin_required
def excluir(sessao_id):
    db = get_db()
    row = db.execute("SELECT data FROM sessao WHERE id = ?", (sessao_id,)).fetchone()
    db.execute("DELETE FROM sessao WHERE id = ?", (sessao_id,))
    db.commit()
    flash("Sessão excluída da agenda.", "ok")
    return _voltar_agenda(row["data"] if row else None)


@bp.route("/gerar", methods=["GET", "POST"])
@admin_required
def gerar():
    hoje = date.today()
    try:
        ano = int(request.values.get("ano", hoje.year + 1))
        if not 2000 <= ano <= 2100:
            raise ValueError
    except ValueError:
        abort(400)
    meses = planejar_ano(ano)
    novos = [i for m in meses for i in m["itens"] if i["situacao"] == "nova"]
    if request.method == "POST":
        if not novos:
            flash(f"Todas as sessões de {ano} já estavam cadastradas. Nada foi alterado.", "aviso")
            return _voltar_agenda(f"{ano}-02-01")
        db = get_db()
        db.executemany(
            "INSERT INTO sessao (data, tipo, grau, cancelada, motivo_cancelamento) VALUES (?, 'Ordinária', ?, ?, ?)",
            [(i["data"], i["grau"], 1 if i["cancelada"] else 0, i["motivo"] if i["cancelada"] else None)
             for i in novos])
        db.commit()
        flash(f"{len(novos)} sessões de {ano} incluídas na agenda. Confira o grau e preencha a ordem do dia.", "ok")
        primeiro = next((i["data"] for i in novos), f"{ano}-02-01")
        return _voltar_agenda(primeiro)
    return render_template("sessoes_gerar.html", ano=ano, meses=meses, novos=len(novos),
                           hoje=hoje)
