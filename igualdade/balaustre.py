"""Balaústre (ata) da sessão: preenchimento pela Secretaria e geração do .docx oficial.

O documento é montado por secretaria/gerar_balaustre.py sobre secretaria/modelo_balaustre.docx,
os mesmos arquivos usados pelo assistente de balaústre do Claude.
"""
import importlib.util
import io
import json
import re
from datetime import datetime
from pathlib import Path

from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user

from .auth import admin_required
from .config import CARGOS_MESA
from .db import get_db
from .diretoria import NOMES_CARGOS, mesa_na_data, obreiros_ativos
from .util import nome_proprio

bp = Blueprint("balaustre", __name__, url_prefix="/admin/sessoes")

SECRETARIA = Path(__file__).resolve().parent.parent / "secretaria"
MODELO = SECRETARIA / "modelo_balaustre.docx"
TEXTO_MAX = 4000
HORA_RE = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")

# Campos que o assistente do Claude trata com "trava de segurança": gerar sem eles exige confirmação
ESSENCIAIS = {"landmark": "Landmark do dia", "ordem_do_dia": "Ordem do dia", "tronco": "Tronco de Solidariedade"}


def _gerador():
    spec = importlib.util.spec_from_file_location("gerar_balaustre", SECRETARIA / "gerar_balaustre.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _sessao(sessao_id):
    s = get_db().execute("SELECT * FROM sessao WHERE id = ?", (sessao_id,)).fetchone()
    if s is None:
        abort(404)
    return s


def _gravado(sessao_id):
    row = get_db().execute("SELECT * FROM balaustre WHERE sessao_id = ?", (sessao_id,)).fetchone()
    return (json.loads(row["dados"]), row) if row else (None, None)


def _padrao(sessao, mesa):
    return {
        "data": sessao["data"],
        "hora_abertura": "20:00",
        "hora_encerramento": "",
        "grau": (sessao["grau"] or "Aprendiz").lower(),
        "tipo_sessao": sessao["tipo"],
        "mesa": mesa,
        "balaustre_anterior": "lido e aprovado sem restrições",
        "expediente": "não houve",
        "landmark": "",
        "bolsa": {"colunas": 0, "descricao": ""},
        "ordem_do_dia": sessao["ordem_do_dia"] or "",
        "tronco": "",
        "visitantes": False,
        "palavra": {"sul": "", "norte": "", "oriente": "", "trono": ""},
    }


def _texto(form, campo):
    return " ".join((form.get(campo) or "").split())[:TEXTO_MAX]


def _ler_form(form, sessao):
    erros = {}
    d = {"data": sessao["data"], "grau": (sessao["grau"] or "Aprendiz").lower(),
         "tipo_sessao": sessao["tipo"]}
    for campo in ("hora_abertura", "hora_encerramento"):
        d[campo] = (form.get(campo) or "").strip()
        if d[campo] and not HORA_RE.match(d[campo]):
            erros[campo] = "Use o formato HH:MM."
    if not d["hora_abertura"]:
        erros["hora_abertura"] = "Informe o horário de abertura."
    d["mesa"] = {c: nome_proprio(_texto(form, f"mesa_{c}")) for c in CARGOS_MESA}
    for c in CARGOS_MESA:
        if not d["mesa"][c]:
            erros[f"mesa_{c}"] = f"Informe o {NOMES_CARGOS[c]}."
    for campo in ("balaustre_anterior", "expediente", "ordem_do_dia"):
        d[campo] = _texto(form, campo)
    lm = re.sub(r"\D", "", form.get("landmark") or "")
    d["landmark"] = f"{int(lm)}º" if lm else ""
    if lm and not 1 <= int(lm) <= 25:
        erros["landmark"] = "São 25 Landmarks: informe um número de 1 a 25."
    try:
        colunas = int(form.get("bolsa_colunas") or 0)
        if colunas < 0:
            raise ValueError
    except ValueError:
        colunas = 0
        erros["bolsa_colunas"] = "Informe um número inteiro."
    d["bolsa"] = {"colunas": colunas, "descricao": _texto(form, "bolsa_descricao") if colunas else ""}
    if colunas and not d["bolsa"]["descricao"]:
        erros["bolsa_descricao"] = "Descreva o que foi colhido na Bolsa."
    tronco = (form.get("tronco") or "").replace("R$", "").strip()
    if tronco:
        try:
            tronco = _gerador().valor_reais(tronco)[0]
        except ValueError:
            erros["tronco"] = "Informe o valor em reais (ex.: 125,00)."
    d["tronco"] = tronco
    d["visitantes"] = bool(form.get("visitantes"))
    d["palavra"] = {r: _texto(form, f"palavra_{r}") for r in ("sul", "norte", "oriente", "trono")}
    return d, erros


@bp.route("/<int:sessao_id>/balaustre", methods=["GET", "POST"])
@admin_required
def form(sessao_id):
    sessao = _sessao(sessao_id)
    if sessao["cancelada"]:
        flash("Sessão cancelada não tem balaústre.", "aviso")
        return redirect(url_for("sessoes.form", sessao_id=sessao_id))
    mesa = mesa_na_data(sessao["data"])
    dados, registro = _gravado(sessao_id)
    if mesa is None and dados is None:
        # A mesa vem da diretoria: ela precisa existir antes do primeiro balaústre
        flash("Cadastre a diretoria da gestão que inclui esta data antes de lavrar o balaústre.", "aviso")
        return redirect(url_for("diretoria.form", voltar=url_for("balaustre.form", sessao_id=sessao_id)))

    erros, faltando = {}, []
    if request.method == "POST":
        dados, erros = _ler_form(request.form, sessao)
        acao = request.form.get("acao", "salvar")
        if not erros:
            db = get_db()
            db.execute(
                "INSERT INTO balaustre (sessao_id, dados, atualizado_em, atualizado_por) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(sessao_id) DO UPDATE SET dados = excluded.dados, "
                "atualizado_em = excluded.atualizado_em, atualizado_por = excluded.atualizado_por",
                (sessao_id, json.dumps(dados, ensure_ascii=False),
                 datetime.now().isoformat(timespec="seconds"), current_user.id))
            db.commit()
            if acao == "salvar":
                flash("Balaústre salvo.", "ok")
                return redirect(url_for("balaustre.form", sessao_id=sessao_id))
            if not dados["hora_encerramento"]:
                erros["hora_encerramento"] = "Informe o horário de encerramento para gerar o documento."
            else:
                faltando = [r for c, r in ESSENCIAIS.items() if not dados[c]]
                if not faltando or acao == "gerar_confirmado":
                    return redirect(url_for("balaustre.baixar", sessao_id=sessao_id))
        if erros:
            flash("Corrija o campo destacado abaixo." if len(erros) == 1
                  else "Corrija os campos destacados abaixo.", "erro")
    elif dados is None:
        dados = _padrao(sessao, mesa)
    return render_template("balaustre_form.html", s=sessao, d=dados, registro=registro, erros=erros,
                           faltando=faltando, mesa_diretoria=mesa, CARGOS_MESA=CARGOS_MESA,
                           NOMES_CARGOS=NOMES_CARGOS, ativos=obreiros_ativos(),
                           modelo_ok=MODELO.exists())


@bp.route("/<int:sessao_id>/balaustre.docx")
@admin_required
def baixar(sessao_id):
    _sessao(sessao_id)
    dados, _ = _gravado(sessao_id)
    if dados is None or not dados.get("hora_encerramento"):
        flash("Preencha e salve o balaústre, com o horário de encerramento, antes de gerar o documento.", "aviso")
        return redirect(url_for("balaustre.form", sessao_id=sessao_id))
    gerador = _gerador()
    dados = {**dados, "tronco": dados.get("tronco") or "0,00"}
    saida = io.BytesIO()
    gerador.gerar(MODELO, dados, saida)
    saida.seek(0)
    return send_file(saida, as_attachment=True, download_name=gerador.nome_padrao(dados),
                     mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
