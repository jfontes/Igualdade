"""Eventos da Loja na agenda (previsão): cadastro pela Secretaria.

Eventos não são sessões: não têm grau, balaústre nem mesa, e podem cair no mesmo dia de uma
sessão. Aparecem na agenda em amarelo.
"""
import re
from datetime import date

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from .auth import admin_required
from .db import get_db
from .sessoes import _destino_voltar, _limites_mes, conferir_mes
from .util import ler_data

bp = Blueprint("eventos", __name__, url_prefix="/admin/eventos")

TITULO_MAX = 120


def eventos_do_mes(ano: int, mes: int):
    return get_db().execute("SELECT * FROM evento WHERE substr(data, 1, 7) = ? ORDER BY data, hora, id",
                            (f"{ano:04d}-{mes:02d}",)).fetchall()


def eventos_do_ano(ano: int):
    return get_db().execute("SELECT * FROM evento WHERE substr(data, 1, 4) = ? ORDER BY data, hora, id",
                            (f"{ano:04d}",)).fetchall()


def proximo_evento():
    return get_db().execute("SELECT * FROM evento WHERE data >= ? AND cancelado = 0 ORDER BY data, hora, id LIMIT 1",
                            (date.today().isoformat(),)).fetchone()


def _texto(form, campo, limite):
    return " ".join((form.get(campo) or "").split())[:limite] or None


def _ler_form(form):
    erros = {}
    dados = {
        "titulo": _texto(form, "titulo", TITULO_MAX),
        "hora": (form.get("hora") or "").strip() or None,
        "local": _texto(form, "local", TITULO_MAX),
        "cancelado": 1 if form.get("cancelado") else 0,
        "motivo_cancelamento": _texto(form, "motivo_cancelamento", TITULO_MAX),
    }
    try:
        dados["data"] = ler_data(form.get("data"))
        if not dados["data"]:
            erros["data"] = "Informe a data do evento."
    except ValueError:
        dados["data"] = None
        erros["data"] = "Data inválida. Use dd/mm/aaaa."
    if not dados["titulo"]:
        erros["titulo"] = "Informe o nome do evento (ex.: Dia das Mães)."
    if dados["hora"] and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", dados["hora"]):
        erros["hora"] = "Hora inválida (use HH:MM)."
    if dados["cancelado"] and not dados["motivo_cancelamento"]:
        erros["motivo_cancelamento"] = "Informe o motivo do cancelamento."
    if not dados["cancelado"]:
        dados["motivo_cancelamento"] = None
    return dados, erros


def _voltar(data_iso: str | None):
    if (destino := _destino_voltar()):
        return redirect(destino)
    if data_iso:
        return redirect(url_for("main.agenda", ano=int(data_iso[:4]), mes=int(data_iso[5:7])))
    return redirect(url_for("main.agenda"))


@bp.route("/novo", methods=["GET", "POST"])
@bp.route("/<int:evento_id>", methods=["GET", "POST"])
@admin_required
def form(evento_id=None):
    db = get_db()
    evento = None
    if evento_id is not None:
        evento = db.execute("SELECT * FROM evento WHERE id = ?", (evento_id,)).fetchone()
        if evento is None:
            abort(404)
    erros = {}
    if request.method == "POST":
        dados, erros = _ler_form(request.form)
        conferir_mes(dados, erros)
        if not erros:
            colunas = list(dados)
            if evento is None:
                db.execute(f"INSERT INTO evento ({', '.join(colunas)}) VALUES ({', '.join('?' for _ in colunas)})",
                           tuple(dados.values()))
                flash(f"Evento “{dados['titulo']}” incluído na agenda.", "ok")
            else:
                db.execute(f"UPDATE evento SET {', '.join(c + ' = ?' for c in colunas)} WHERE id = ?",
                           (*dados.values(), evento_id))
                flash("Evento atualizado.", "ok")
            db.commit()
            return _voltar(dados["data"])
        flash("Corrija o campo destacado abaixo." if len(erros) == 1 else "Corrija os campos destacados abaixo.",
              "erro")
        evento = dados | {"id": evento_id}
    elif evento is None:
        evento = {"data": request.args.get("data", ""), "cancelado": 0}
    return render_template("evento_form.html", e=evento, evento_id=evento_id, erros=erros,
                           voltar=_destino_voltar(), limites=_limites_mes(request.values.get("mes")),
                           mes=request.values.get("mes"))


@bp.route("/<int:evento_id>/excluir", methods=["POST"])
@admin_required
def excluir(evento_id):
    db = get_db()
    row = db.execute("SELECT data, titulo FROM evento WHERE id = ?", (evento_id,)).fetchone()
    if row is None:
        abort(404)
    db.execute("DELETE FROM evento WHERE id = ?", (evento_id,))
    db.commit()
    flash(f"Evento “{row['titulo']}” excluído da agenda.", "ok")
    return _voltar(row["data"])
