"""Gerenciar as sessões de um ano.

Lista, em modo leitura, as sessões cadastradas e as sugestões do gerador (segundas-feiras,
regra dos graus, feriados e recessos) para as datas livres. Cada sessão tem um lápis que abre
a tela da sessão; o "+" de cada mês abre a inclusão de uma sessão naquele mês. As sugestões
marcadas são criadas com "Incluir na agenda".

A planilha carregada aparece como prévia (linhas destacadas) e também só é gravada com
"Incluir na agenda". Esta tela não exclui sessões.

Proteções:
- ano que já tem sessões: as sugestões vêm desmarcadas (não recria o que foi tirado de propósito);
- cada sessão cadastrada leva uma "versão"; se outra pessoa a alterou depois que a prévia foi
  aberta, ela não é sobrescrita e a linha avisa para recarregar.
"""
import calendar
import hashlib
from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for

from .auth import admin_required
from .db import get_db
from .feriados import recesso
from .planilha import ler_planilha
from .sessoes import GRAUS, ORDEM_MAX, TIPOS, planejar_ano
from .util import MESES

bp = Blueprint("gerenciar", __name__, url_prefix="/admin/sessoes")

CAMPOS = ["tipo", "grau", "ordem_do_dia", "cancelada", "motivo_cancelamento"]
ORDEM_ESTADO = {"cadastrada": 0, "sugestao": 1, "nova": 2}


def versao(s) -> str:
    texto = "|".join("" if s[c] is None else str(s[c]) for c in ["data"] + CAMPOS)
    return hashlib.sha1(texto.encode("utf-8")).hexdigest()[:12]


def _ano() -> int:
    hoje = date.today()
    try:
        ano = int(request.values.get("ano", hoje.year))
        if not 2000 <= ano <= 2100:
            raise ValueError
    except ValueError:
        ano = hoje.year
    return ano


def _valores(s) -> dict:
    return {c: s[c] for c in CAMPOS}


def montar_linhas(ano: int) -> list[dict]:
    """Sessões cadastradas do ano + sugestões do gerador para as datas livres."""
    cadastradas = get_db().execute(
        "SELECT * FROM sessao WHERE substr(data, 1, 4) = ? ORDER BY data, id", (f"{ano:04d}",)).fetchall()
    linhas = [{"origem": "cadastrada", "id": s["id"], "versao": versao(s), "data": s["data"],
               "incluir": True, "original": _valores(s), **_valores(s)} for s in cadastradas]
    marcar = not cadastradas  # ano já salvo: sugestões desmarcadas
    for mes in planejar_ano(ano):
        for item in mes["itens"]:
            if item["situacao"] != "nova":
                continue
            linhas.append({"origem": "sugestao", "data": item["data"], "incluir": marcar,
                           "tipo": "Ordinária", "grau": item["grau"], "ordem_do_dia": None,
                           "cancelada": 1 if item["cancelada"] else 0,
                           "motivo_cancelamento": item["motivo"] if item["cancelada"] else None})
    return linhas


def _mudou(linha) -> bool:
    return linha["origem"] == "cadastrada" and any(linha[c] != linha["original"][c] for c in CAMPOS)


def _render(ano: int, linhas: list[dict], avisos=(), previa=False):
    meses = []
    for m in range(1, 13):
        ultimo = calendar.monthrange(ano, m)[1]
        do_mes = [l for l in linhas if int(l["data"][5:7]) == m]
        do_mes.sort(key=lambda l: (l["data"], ORDEM_ESTADO[l["origem"]]))
        inteiro = recesso(date(ano, m, 1)) if recesso(date(ano, m, 1)) == recesso(date(ano, m, ultimo)) else None
        meses.append({"mes": m, "nome": MESES[m - 1], "linhas": do_mes, "recesso": inteiro,
                      "cadastradas": sum(l["origem"] == "cadastrada" for l in do_mes)})
    for n, linha in enumerate(l for m in meses for l in m["linhas"]):
        linha["n"] = n
        linha["alterada"] = _mudou(linha)
    return render_template("gerenciar.html", ano=ano, meses=meses, avisos=avisos, previa=previa,
                           voltar=url_for("gerenciar.gerenciar", ano=ano),
                           ano_tem_sessoes=any(l["origem"] == "cadastrada" for l in linhas))


def _problemas(l: dict, ano: int) -> list[str]:
    """Regras de uma sessão (as mesmas do cadastro individual)."""
    p = []
    if l["tipo"] not in TIPOS:
        p.append("escolha o tipo da sessão")
    if not l["cancelada"] and l["grau"] not in GRAUS:
        p.append("informe o grau")
    if l["cancelada"] and not l["motivo_cancelamento"]:
        p.append("informe o motivo do cancelamento")
    if l["ordem_do_dia"] and len(l["ordem_do_dia"]) > ORDEM_MAX:
        p.append(f"a ordem do dia passa de {ORDEM_MAX} caracteres")
    if l["data"][:4] != str(ano):
        p.append(f"a data deve ser de {ano}")
    return p


# ---------------------------------------------------------------- envio (Incluir na agenda)

def _ler_form(form, ano: int) -> list[dict]:
    """As linhas vêm em campos ocultos (a tela é só de leitura; só a caixa das sugestões muda)."""
    db = get_db()
    indices = sorted({int(k.split("-")[1]) for k in form
                      if k.startswith("r-") and k.endswith("-origem") and k.split("-")[1].isdigit()})
    linhas = []
    for n in indices:
        def g(campo, n=n):
            return (form.get(f"r-{n}-{campo}") or "").strip()

        cancelada = 1 if g("cancelada") else 0
        linha = {"origem": g("origem"), "erros": [], "planilha": bool(g("planilha")), "data": g("data"),
                 "tipo": g("tipo") or None, "grau": g("grau") or None,
                 "ordem_do_dia": " ".join(g("ordem_do_dia").split()) or None, "cancelada": cancelada,
                 "motivo_cancelamento": (" ".join(g("motivo_cancelamento").split()) or None) if cancelada else None}
        if linha["origem"] == "cadastrada":
            s = db.execute("SELECT * FROM sessao WHERE id = ?", (int(g("id") or 0),)).fetchone()
            if s is None:
                continue  # excluída por outra pessoa
            linha.update(id=s["id"], data=s["data"], versao=g("versao"), versao_atual=versao(s),
                         original=_valores(s), incluir=True)
        elif linha["origem"] == "sugestao":
            linha["incluir"] = bool(g("incluir"))
        else:
            linha.update(origem="nova", incluir=True)
        try:
            date.fromisoformat(linha["data"])
        except ValueError:
            continue
        linhas.append(linha)
    return linhas


def _validar(linhas: list[dict], ano: int) -> bool:
    db = get_db()
    novas = set()
    for l in linhas:
        if not l["incluir"] or (l["origem"] == "cadastrada" and not _mudou(l)):
            continue
        l["erros"] += [p[0].upper() + p[1:] + "." for p in _problemas(l, ano)]
        if l["origem"] == "cadastrada":
            if l["versao"] != l["versao_atual"]:
                l["erros"].append("Esta sessão foi alterada por outra pessoa depois que a planilha foi carregada. "
                                  "Carregue a planilha de novo.")
            continue
        if db.execute("SELECT 1 FROM sessao WHERE data = ? LIMIT 1", (l["data"],)).fetchone():
            l["erros"].append("Já existe sessão cadastrada neste dia.")
        elif l["data"] in novas:
            l["erros"].append("Dia repetido.")
        novas.add(l["data"])
    return not any(l["erros"] for l in linhas)


def _gravar(linhas: list[dict]) -> tuple[int, int]:
    db = get_db()
    criadas = atualizadas = 0
    for l in linhas:
        valores = tuple(l[c] for c in CAMPOS)
        if l["origem"] == "cadastrada":
            if _mudou(l):
                db.execute("UPDATE sessao SET tipo = ?, grau = ?, ordem_do_dia = ?, cancelada = ?, "
                           "motivo_cancelamento = ? WHERE id = ?", (*valores, l["id"]))
                atualizadas += 1
        elif l["incluir"]:
            db.execute("INSERT INTO sessao (tipo, grau, ordem_do_dia, cancelada, motivo_cancelamento, data) "
                       "VALUES (?, ?, ?, ?, ?, ?)", (*valores, l["data"]))
            criadas += 1
    db.commit()
    return criadas, atualizadas


# ---------------------------------------------------------------- rotas

@bp.route("/gerenciar", methods=["GET", "POST"])
@admin_required
def gerenciar():
    ano = _ano()
    if request.method == "GET":
        return _render(ano, montar_linhas(ano))
    linhas = _ler_form(request.form, ano)
    if not _validar(linhas, ano):
        flash("Nada foi gravado. Veja as linhas destacadas.", "erro")
        return _render(ano, linhas, previa=any(l["planilha"] for l in linhas))
    criadas, atualizadas = _gravar(linhas)
    if criadas or atualizadas:
        flash(f"Agenda de {ano} atualizada: {criadas} sessão(ões) criada(s), "
              f"{atualizadas} atualizada(s).", "ok")
    else:
        flash("Nenhuma sessão marcada para incluir.", "aviso")
    return redirect(url_for("gerenciar.gerenciar", ano=ano))


@bp.route("/gerenciar/planilha", methods=["POST"])
@admin_required
def carregar_planilha():
    """Prévia da planilha na tela (sem gravar). Se ela for de um único ano, abre esse ano."""
    ano = _ano()
    arquivo = request.files.get("planilha")
    if not arquivo or not arquivo.filename:
        flash("Escolha o arquivo da planilha.", "erro")
        return redirect(url_for("gerenciar.gerenciar", ano=ano))
    if not arquivo.filename.lower().endswith(".xlsx"):
        flash("Envie uma planilha Excel no formato .xlsx.", "erro")
        return redirect(url_for("gerenciar.gerenciar", ano=ano))
    lidas, avisos = ler_planilha(arquivo)
    anos = {d["data"][:4] for _, d, _ in lidas}
    if len(anos) == 1:
        ano = int(anos.pop())
    linhas = montar_linhas(ano)
    por_data = {}
    for l in linhas:
        por_data.setdefault(l["data"], l)
    carregadas = ignoradas = 0
    for n, dados, problemas in lidas:
        if dados["data"][:4] != str(ano):
            ignoradas += 1
            continue
        # junta as regras da sessão sem repetir o que a leitura já apontou (ex.: tipo inexistente)
        ja_citados = {q.split(" ")[0].lower() for q in problemas}
        problemas = problemas + [p for p in _problemas(dados, ano)
                                 if not ({"tipo", "grau"} & ja_citados & set(p.split()))]
        if problemas:
            avisos.append(f"Linha {n} ({dados['data'][8:]}/{dados['data'][5:7]}): {'; '.join(problemas)}. "
                          "Corrija na planilha e carregue de novo.")
            continue
        alvo = por_data.get(dados["data"])
        valores = {c: dados[c] for c in CAMPOS}
        if alvo is None:
            alvo = {"origem": "nova", "data": dados["data"]}
            linhas.append(alvo)
            por_data[dados["data"]] = alvo
        elif alvo["origem"] == "cadastrada" and all(alvo[c] == valores[c] for c in CAMPOS):
            continue  # igual ao que já está gravado
        alvo.update(valores, planilha=True, incluir=True)
        carregadas += 1
    if ignoradas:
        avisos.append(f"{ignoradas} linha(s) de outros anos não foram carregadas. Separe uma planilha por ano.")
    if carregadas:
        flash(f"Planilha carregada: {carregadas} sessão(ões) com novidades, destacadas abaixo. "
              "Nada foi gravado ainda: confira e toque em \"Incluir na agenda\".", "aviso")
    elif lidas:
        flash("A planilha não traz nenhuma novidade em relação à agenda.", "aviso")
    return _render(ano, linhas, avisos, previa=carregadas > 0)
