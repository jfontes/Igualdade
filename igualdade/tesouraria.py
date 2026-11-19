"""Tesouraria: lançamento das percapitas (contribuição semestral) e registro de pagamentos.

Regras (definidas pela Loja):
- O Tesoureiro faz um lançamento anual: 2 percapitas (1º e 2º semestre) de mesmo valor
  para cada obreiro ativo que deve contribuir. Afastados não geram percapita.
- Ingresso (iniciação ou filiação): passa a dever no semestre SEGUINTE ao ingresso.
- Emérito (= Remido): isento a partir do semestre SEGUINTE ao título. Ao gravar a data de
  Emérito, o sistema isenta automaticamente o saldo em aberto desses semestres.
- Quem entra depois do lançamento anual é lançado manual e individualmente.
- Vencimento: 5º dia útil de fevereiro (1º semestre) e de julho (2º semestre).
- O pagamento é registrado no ano e distribuído: primeiro o 1º semestre, o excedente vai
  para o 2º. Nunca pode passar do saldo do ano.
- Nada é apagado: percapitas são canceladas e pagamentos estornados, com motivo e autor.
- Lançam e registram: Tesoureiro e Venerável Mestre da gestão vigente.
"""
from datetime import date, datetime, timedelta
from functools import wraps

from flask import (Blueprint, abort, flash, g, redirect, render_template, request,
                   url_for)
from flask_login import current_user, login_required

from .db import get_db
from .feriados import dias_sem_sessao
from .util import fmt_data, fmt_moeda, ler_data, ler_moeda

bp = Blueprint("tesouraria", __name__, url_prefix="/tesouraria")

FORMAS = ["PIX", "Dinheiro", "Cartão", "Abatimento em crédito", "Isenção"]
FORMA_PADRAO = "PIX"
FORMAS_CAIXA = {"PIX", "Dinheiro", "Cartão"}       # entram no caixa / extrato bancário
ISENCAO = "Isenção"
CARGOS_TESOURARIA = {"tesoureiro", "veneravel"}     # lançam e registram pagamentos
MES_VENCIMENTO = {1: 2, 2: 7}                       # fevereiro e julho
DIA_UTIL_VENCIMENTO = 5

SITUACOES = {
    "paga": ("Paga", "🟢"),
    "isenta": ("Isenta", "🟢"),
    "parcial": ("Parcial", "🟡"),
    "aberta": ("Em aberto", "⚪"),
    "vencida": ("Vencida", "🔴"),
    "cancelada": ("Cancelada", "⚫"),
}


def agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def hoje() -> str:
    return date.today().isoformat()


# ---------------------------------------------------------------- permissões

def cargos_atuais() -> set[str]:
    """Cargos do usuário logado na gestão vigente da Diretoria (guardado durante a requisição)."""
    if "cargos_atuais" not in g:
        cargos = set()
        if current_user.is_authenticated:
            from .diretoria import gestao_vigente
            gestao = gestao_vigente()
            if gestao:
                cargos = {r["cargo"] for r in get_db().execute(
                    "SELECT cargo FROM diretoria WHERE gestao_id = ? AND obreiro_id = ?",
                    (gestao["id"], current_user.id))}
        g.cargos_atuais = cargos
    return g.cargos_atuais


def gere_tesouraria() -> bool:
    """Tesoureiro, Venerável ou Administrador: lança percapitas e registra pagamentos."""
    if current_user.is_authenticated and getattr(current_user, "admin_cadastro", False):
        return True
    return bool(cargos_atuais() & CARGOS_TESOURARIA)


def ve_relatorios() -> bool:
    """Tesoureiro, Secretário, Venerável e Administrador: relatórios e consulta da tesouraria."""
    return current_user.is_authenticated and (current_user.admin or gere_tesouraria())


def tesoureiro_required(view):
    @wraps(view)
    @login_required
    def wrapper(*args, **kwargs):
        if not gere_tesouraria():
            abort(403)
        return view(*args, **kwargs)
    return wrapper


def relatorios_required(view):
    @wraps(view)
    @login_required
    def wrapper(*args, **kwargs):
        if not ve_relatorios():
            abort(403)
        return view(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------- semestres e vencimentos

def indice(ano: int, semestre: int) -> int:
    """Número sequencial do semestre, para comparar (2027/1 < 2027/2 < 2028/1)."""
    return ano * 2 + (semestre - 1)


def semestre_da_data(data_iso: str) -> tuple[int, int]:
    return int(data_iso[:4]), (1 if int(data_iso[5:7]) <= 6 else 2)


def rotulo_semestre(ano: int, semestre: int) -> str:
    return f"{semestre}º semestre/{ano}"


def vencimento(ano: int, semestre: int) -> str:
    """5º dia útil de fevereiro (1º semestre) ou de julho (2º): seg. a sex., sem feriados."""
    feriados = dias_sem_sessao(ano)
    dia, uteis = date(ano, MES_VENCIMENTO[semestre], 1), 0
    while True:
        if dia.weekday() < 5 and dia not in feriados:
            uteis += 1
            if uteis == DIA_UTIL_VENCIMENTO:
                return dia.isoformat()
        dia += timedelta(days=1)


def data_ingresso(o) -> str | None:
    """Ingresso na Loja: a mais recente entre iniciação e filiação."""
    datas = [d for d in (o["data_iniciacao"], o["data_filiacao"]) if d]
    return max(datas) if datas else None


def motivo_isencao(o, ano: int, semestre: int) -> str | None:
    """Por que o obreiro NÃO deve a percapita do semestre (None = deve)."""
    alvo = indice(ano, semestre)
    if o["data_emerito"] and alvo > indice(*semestre_da_data(o["data_emerito"])):
        return f"Emérito desde {fmt_data(o['data_emerito'])}"
    ingresso = data_ingresso(o)
    if ingresso and alvo <= indice(*semestre_da_data(ingresso)):
        return f"Ingresso em {fmt_data(ingresso)} (deve a partir do semestre seguinte)"
    return None


# ---------------------------------------------------------------- consultas

SQL_PERCAPITAS = """
    SELECT p.*, o.nome, o.cim, o.data_afastamento, o.data_emerito,
           IFNULL((SELECT SUM(pp.valor) FROM pagamento_parte pp JOIN pagamento x ON x.id = pp.pagamento_id
                    WHERE pp.percapita_id = p.id AND x.estornado = 0), 0) AS pago,
           IFNULL((SELECT SUM(pp.valor) FROM pagamento_parte pp JOIN pagamento x ON x.id = pp.pagamento_id
                    WHERE pp.percapita_id = p.id AND x.estornado = 0 AND x.forma = 'Isenção'), 0) AS isento,
           EXISTS (SELECT 1 FROM pagamento_parte pp WHERE pp.percapita_id = p.id) AS tem_pagamento
      FROM percapita p JOIN obreiro o ON o.id = p.obreiro_id
"""


def situacao(p, data_ref: str | None = None) -> str:
    data_ref = data_ref or hoje()
    if p["cancelada"]:
        return "cancelada"
    saldo = p["valor"] - p["pago"]
    if saldo <= 0:
        return "isenta" if p["isento"] >= p["valor"] else "paga"
    if p["vencimento"] < data_ref:
        return "vencida"
    return "parcial" if p["pago"] else "aberta"


def enriquecer(p, data_ref: str | None = None) -> dict:
    d = dict(p)
    d["saldo"] = 0 if p["cancelada"] else max(p["valor"] - p["pago"], 0)
    d["situacao"] = situacao(p, data_ref)
    d["rotulo"], d["icone"] = SITUACOES[d["situacao"]]
    if d["situacao"] == "vencida" and p["pago"]:
        d["rotulo"] = "Vencida (parcial)"
    d["semestre_txt"] = rotulo_semestre(p["ano"], p["semestre"])
    return d


def percapitas(where: str = "1=1", params=(), data_ref: str | None = None) -> list[dict]:
    rows = get_db().execute(f"{SQL_PERCAPITAS} WHERE {where} ORDER BY p.ano, p.semestre, o.nome",
                            params).fetchall()
    return [enriquecer(r, data_ref) for r in rows]


def percapitas_do_obreiro(obreiro_id: int) -> list[dict]:
    return percapitas("p.obreiro_id = ?", (obreiro_id,))


def pagamentos_do_obreiro(obreiro_id: int) -> list[dict]:
    db = get_db()
    lista = []
    for r in db.execute(
            "SELECT x.*, r.nome AS registrado_por_nome, e.nome AS estornado_por_nome "
            "FROM pagamento x LEFT JOIN obreiro r ON r.id = x.registrado_por "
            "LEFT JOIN obreiro e ON e.id = x.estornado_por "
            "WHERE x.obreiro_id = ? ORDER BY x.data DESC, x.id DESC", (obreiro_id,)):
        d = dict(r)
        d["partes"] = [rotulo_semestre(p["ano"], p["semestre"]) + f" ({fmt_moeda(p['valor_parte'])})"
                       for p in db.execute(
                           "SELECT c.ano, c.semestre, pp.valor AS valor_parte FROM pagamento_parte pp "
                           "JOIN percapita c ON c.id = pp.percapita_id WHERE pp.pagamento_id = ? "
                           "ORDER BY c.semestre", (r["id"],))]
        lista.append(d)
    return lista


def resumo_obreiro(obreiro_id: int) -> dict:
    """Totais para o painel, o perfil e a Minha Tesouraria."""
    lista = percapitas_do_obreiro(obreiro_id)
    ativas = [p for p in lista if not p["cancelada"]]
    return {
        "percapitas": lista,
        "em_aberto": sum(p["saldo"] for p in ativas),
        "vencido": sum(p["saldo"] for p in ativas if p["situacao"] == "vencida"),
        "qtd_vencidas": sum(1 for p in ativas if p["situacao"] == "vencida"),
        "tem_registros": bool(lista),
    }


def anos_com_registro(extra: int | None = None) -> list[int]:
    anos = {r[0] for r in get_db().execute("SELECT DISTINCT ano FROM percapita")}
    anos |= {r[0] for r in get_db().execute("SELECT ano FROM lancamento_anual")}
    anos.add(date.today().year)
    if extra:
        anos.add(extra)
    return sorted(anos, reverse=True)


def lancamento_do_ano(ano: int):
    return get_db().execute("SELECT * FROM lancamento_anual WHERE ano = ?", (ano,)).fetchone()


def valor_sugerido(ano: int) -> int | None:
    """Valor do semestre: o do lançamento do ano; senão o do ano mais recente (para corrigir)."""
    row = get_db().execute(
        "SELECT valor FROM lancamento_anual WHERE ano <= ? ORDER BY ano DESC LIMIT 1", (ano,)).fetchone()
    if row:
        return row["valor"]
    row = get_db().execute("SELECT valor FROM percapita WHERE ano <= ? ORDER BY ano DESC, id DESC LIMIT 1",
                           (ano,)).fetchone()
    return row["valor"] if row else None


# ---------------------------------------------------------------- lançamento

def previa_lancamento(ano: int) -> dict:
    """Quem recebe percapita no lançamento anual e quem fica de fora (com o motivo)."""
    db = get_db()
    existentes = {(r["obreiro_id"], r["semestre"]) for r in db.execute(
        "SELECT obreiro_id, semestre FROM percapita WHERE ano = ?", (ano,))}
    incluidos, excluidos = [], []
    for o in db.execute("SELECT * FROM obreiro ORDER BY nome"):
        if o["data_afastamento"]:
            continue  # afastados não geram percapita (nem aparecem na lista)
        semestres, motivos = [], []
        for s in (1, 2):
            motivo = motivo_isencao(o, ano, s)
            if motivo:
                motivos.append(f"{s}º sem.: {motivo}")
            elif (o["id"], s) in existentes:
                motivos.append(f"{s}º sem.: já lançada")
            else:
                semestres.append(s)
        if semestres:
            incluidos.append({"o": o, "semestres": semestres, "obs": "; ".join(motivos)})
        else:
            excluidos.append({"o": o, "motivo": "; ".join(motivos)})
    return {"incluidos": incluidos, "excluidos": excluidos,
            "total": sum(len(i["semestres"]) for i in incluidos),
            "vencimentos": {s: vencimento(ano, s) for s in (1, 2)}}


def pode_lancar_ano(ano: int) -> bool:
    """Lançamento geral só para o ano atual ou seguintes; anos anteriores, só individualmente."""
    return ano >= date.today().year


def lancar_ano(ano: int, valor: int) -> int:
    db = get_db()
    if not pode_lancar_ano(ano):
        raise ValueError(f"Não é possível fazer o lançamento geral de {ano}, ano anterior ao atual. "
                         "Lance individualmente, pelo registro de cada obreiro.")
    if lancamento_do_ano(ano):
        raise ValueError(f"As percapitas de {ano} já foram lançadas.")
    previa = previa_lancamento(ano)
    momento = agora()
    db.execute("INSERT INTO lancamento_anual (ano, valor, lancado_em, lancado_por) VALUES (?, ?, ?, ?)",
               (ano, valor, momento, current_user.id))
    for item in previa["incluidos"]:
        for s in item["semestres"]:
            db.execute("INSERT INTO percapita (obreiro_id, ano, semestre, valor, vencimento, lancada_em, lancada_por) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (item["o"]["id"], ano, s, valor, previa["vencimentos"][s], momento, current_user.id))
    db.commit()
    return previa["total"]


def pode_desfazer(ano: int) -> bool:
    """O lançamento anual só pode ser desfeito antes de qualquer pagamento no ano."""
    return bool(lancamento_do_ano(ano)) and not get_db().execute(
        "SELECT 1 FROM pagamento WHERE ano = ? LIMIT 1", (ano,)).fetchone()


def desfazer_lancamento(ano: int) -> int:
    lanc = lancamento_do_ano(ano)
    if not pode_desfazer(ano):
        raise ValueError("Já existem pagamentos neste ano: o lançamento não pode ser desfeito. "
                         "Cancele as percapitas individualmente, se necessário.")
    db = get_db()
    n = db.execute("DELETE FROM percapita WHERE ano = ? AND lancada_em = ?", (ano, lanc["lancado_em"])).rowcount
    db.execute("DELETE FROM lancamento_anual WHERE ano = ?", (ano,))
    db.commit()
    return n


def lancar_individual(obreiro_id: int, ano: int, semestres: list[int], valor: int) -> list[str]:
    """Lança (ou reativa, se cancelada) as percapitas escolhidas. Devolve os semestres lançados."""
    db = get_db()
    feitos, momento = [], agora()
    for s in semestres:
        atual = db.execute("SELECT * FROM percapita WHERE obreiro_id = ? AND ano = ? AND semestre = ?",
                           (obreiro_id, ano, s)).fetchone()
        if atual and not atual["cancelada"]:
            continue
        if atual:  # reativa a percapita cancelada com o novo valor
            db.execute("UPDATE percapita SET valor = ?, vencimento = ?, cancelada = 0, motivo_cancelamento = NULL, "
                       "cancelada_em = NULL, cancelada_por = NULL, lancada_em = ?, lancada_por = ? WHERE id = ?",
                       (valor, vencimento(ano, s), momento, current_user.id, atual["id"]))
        else:
            db.execute("INSERT INTO percapita (obreiro_id, ano, semestre, valor, vencimento, lancada_em, lancada_por) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (obreiro_id, ano, s, valor, vencimento(ano, s), momento, current_user.id))
        feitos.append(rotulo_semestre(ano, s))
    db.commit()
    return feitos


def excluir_percapita(percapita_id: int):
    """Apaga um lançamento que nunca recebeu pagamento (nem estornado). Devolve a linha apagada."""
    p = get_db().execute(f"{SQL_PERCAPITAS} WHERE p.id = ?", (percapita_id,)).fetchone()
    if p is None:
        abort(404)
    if p["tem_pagamento"]:
        raise ValueError("Esta percapita tem pagamentos registrados (mesmo que estornados) e não pode ser "
                         "excluída. Use Cancelar.")
    get_db().execute("DELETE FROM percapita WHERE id = ?", (percapita_id,))
    get_db().commit()
    return p


def cancelar_percapita(percapita_id: int, motivo: str):
    p = get_db().execute(f"{SQL_PERCAPITAS} WHERE p.id = ?", (percapita_id,)).fetchone()
    if p is None:
        abort(404)
    if p["cancelada"]:
        raise ValueError("Esta percapita já está cancelada.")
    if p["pago"]:
        raise ValueError("Esta percapita tem pagamentos. Estorne os pagamentos antes de cancelá-la.")
    get_db().execute("UPDATE percapita SET cancelada = 1, motivo_cancelamento = ?, cancelada_em = ?, "
                     "cancelada_por = ? WHERE id = ?", (motivo, agora(), current_user.id, percapita_id))
    get_db().commit()
    return p


# ---------------------------------------------------------------- pagamentos

def saldo_do_ano(obreiro_id: int, ano: int) -> int:
    return sum(p["saldo"] for p in percapitas("p.obreiro_id = ? AND p.ano = ?", (obreiro_id, ano)))


def registrar_pagamento(obreiro_id: int, ano: int, valor: int, data_pag: str, forma: str,
                        observacao: str | None = None, alvo: list[int] | None = None,
                        automatico: bool = False, commit: bool = True) -> int:
    """Grava o pagamento e distribui o valor pelos semestres em aberto do ano (1º, depois 2º).

    `alvo` limita a distribuição a algumas percapitas (usado na isenção automática do Emérito).
    """
    if forma not in FORMAS:
        raise ValueError("Forma de pagamento inválida.")
    abertas = [p for p in percapitas("p.obreiro_id = ? AND p.ano = ? AND p.cancelada = 0", (obreiro_id, ano))
               if p["saldo"] > 0 and (alvo is None or p["id"] in alvo)]
    abertas.sort(key=lambda p: p["semestre"])
    saldo = sum(p["saldo"] for p in abertas)
    if saldo <= 0:
        raise ValueError(f"Não há saldo em aberto em {ano}.")
    if valor > saldo:
        raise ValueError(f"O valor ({fmt_moeda(valor)}) é maior que o saldo em aberto de {ano} "
                         f"({fmt_moeda(saldo)}).")
    db = get_db()
    cur = db.execute(
        "INSERT INTO pagamento (obreiro_id, ano, data, valor, forma, observacao, automatico, registrado_em, "
        "registrado_por) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (obreiro_id, ano, data_pag, valor, forma, observacao or None, int(automatico), agora(),
         current_user.id if current_user.is_authenticated else None))
    restante = valor
    for p in abertas:
        parte = min(restante, p["saldo"])
        if parte <= 0:
            break
        db.execute("INSERT INTO pagamento_parte (pagamento_id, percapita_id, valor) VALUES (?, ?, ?)",
                   (cur.lastrowid, p["id"], parte))
        restante -= parte
    if commit:
        db.commit()
    return cur.lastrowid


def estornar_pagamento(pagamento_id: int, motivo: str):
    db = get_db()
    pag = db.execute("SELECT * FROM pagamento WHERE id = ?", (pagamento_id,)).fetchone()
    if pag is None:
        abort(404)
    if pag["estornado"]:
        raise ValueError("Este pagamento já foi estornado.")
    db.execute("UPDATE pagamento SET estornado = 1, motivo_estorno = ?, estornado_em = ?, estornado_por = ? "
               "WHERE id = ?", (motivo, agora(), current_user.id, pagamento_id))
    db.commit()
    return pag


def isentar_emerito(obreiro_id: int) -> int:
    """Isenta o saldo em aberto dos semestres seguintes ao título de Emérito.

    Chamada pela Secretaria ao gravar a data de Emérito. Devolve quantas percapitas foram isentadas.
    """
    o = get_db().execute("SELECT * FROM obreiro WHERE id = ?", (obreiro_id,)).fetchone()
    if o is None or not o["data_emerito"]:
        return 0
    limite = indice(*semestre_da_data(o["data_emerito"]))
    por_ano: dict[int, list[dict]] = {}
    for p in percapitas("p.obreiro_id = ? AND p.cancelada = 0", (obreiro_id,)):
        if p["saldo"] > 0 and indice(p["ano"], p["semestre"]) > limite:
            por_ano.setdefault(p["ano"], []).append(p)
    obs = f"Isenção automática: Emérito em {fmt_data(o['data_emerito'])}"
    for ano, lista in por_ano.items():
        registrar_pagamento(obreiro_id, ano, sum(p["saldo"] for p in lista), hoje(), ISENCAO, obs,
                            alvo=[p["id"] for p in lista], automatico=True, commit=False)
    get_db().commit()
    return sum(len(v) for v in por_ano.values())


def tem_movimento_financeiro(obreiro_id: int) -> bool:
    db = get_db()
    return bool(db.execute("SELECT 1 FROM percapita WHERE obreiro_id = ? LIMIT 1", (obreiro_id,)).fetchone()
                or db.execute("SELECT 1 FROM pagamento WHERE obreiro_id = ? LIMIT 1", (obreiro_id,)).fetchone())


# ---------------------------------------------------------------- telas

def _obreiro(obreiro_id: int):
    o = get_db().execute("SELECT * FROM obreiro WHERE id = ?", (obreiro_id,)).fetchone()
    if o is None:
        abort(404)
    return o


def _ano_param(nome: str = "ano", padrao: int | None = None) -> int:
    try:
        ano = int(request.values.get(nome) or (padrao or date.today().year))
    except ValueError:
        ano = padrao or date.today().year
    return min(max(ano, 2000), 2100)


def _por_ano(lista: list[dict]) -> list[tuple[int, list[dict]]]:
    anos: dict[int, list[dict]] = {}
    for p in lista:
        anos.setdefault(p["ano"], []).append(p)
    return sorted(anos.items(), reverse=True)


@bp.route("/")
@login_required
def minha():
    o = _obreiro(current_user.id)
    resumo = resumo_obreiro(o["id"])
    return render_template("tesouraria/minha.html", o=o, resumo=resumo,
                           anos=_por_ano(resumo["percapitas"]),
                           pagamentos=pagamentos_do_obreiro(o["id"]), ano_atual=date.today().year,
                           gere=gere_tesouraria(), relatorios=ve_relatorios())


@bp.route("/gestao")
@relatorios_required
def gestao():
    ano = _ano_param()
    q = (request.args.get("q") or "").strip()
    filtro = request.args.get("filtro", "")
    lista = percapitas("p.ano = ?", (ano,))
    totais = totais_do_ano(ano, lista)
    linhas: dict[int, dict] = {}
    for p in lista:
        linha = linhas.setdefault(p["obreiro_id"], {"id": p["obreiro_id"], "nome": p["nome"], "cim": p["cim"],
                                                    "afastado": bool(p["data_afastamento"]),
                                                    1: None, 2: None, "saldo": 0, "vencido": 0})
        linha[p["semestre"]] = p
        linha["saldo"] += p["saldo"]
        if p["situacao"] == "vencida":
            linha["vencido"] += p["saldo"]
    lista_linhas = sorted(linhas.values(), key=lambda l: l["nome"])
    if q:
        termo = q.upper()
        lista_linhas = [l for l in lista_linhas if termo in l["nome"] or q in l["cim"]]
    if filtro == "devendo":
        lista_linhas = [l for l in lista_linhas if l["saldo"] > 0]
    elif filtro == "vencidos":
        lista_linhas = [l for l in lista_linhas if l["vencido"] > 0]
    return render_template("tesouraria/gestao.html", ano=ano, anos=anos_com_registro(ano), linhas=lista_linhas,
                           totais=totais, lancamento=lancamento_do_ano(ano), q=q, filtro=filtro,
                           gere=gere_tesouraria(), desfazer=pode_desfazer(ano), pode_lancar=pode_lancar_ano(ano))


def totais_do_ano(ano: int, lista: list[dict] | None = None) -> dict:
    lista = lista if lista is not None else percapitas("p.ano = ?", (ano,))
    ativas = [p for p in lista if not p["cancelada"]]
    formas = {f: 0 for f in FORMAS}
    for r in get_db().execute(
            "SELECT x.forma, SUM(pp.valor) AS total FROM pagamento_parte pp "
            "JOIN pagamento x ON x.id = pp.pagamento_id JOIN percapita c ON c.id = pp.percapita_id "
            "WHERE x.estornado = 0 AND c.ano = ? AND c.cancelada = 0 GROUP BY x.forma", (ano,)):
        formas[r["forma"]] = r["total"]
    lancado = sum(p["valor"] for p in ativas)
    quitado = sum(p["pago"] for p in ativas)
    obreiros = {p["obreiro_id"] for p in ativas}
    com_vencido = {p["obreiro_id"] for p in ativas if p["situacao"] == "vencida"}
    return {
        "lancado": lancado,
        "caixa": sum(v for f, v in formas.items() if f in FORMAS_CAIXA),
        "abatido": formas["Abatimento em crédito"],
        "isentado": formas[ISENCAO],
        "quitado": quitado,
        "a_receber": sum(p["saldo"] for p in ativas),
        "vencido": sum(p["saldo"] for p in ativas if p["situacao"] == "vencida"),
        "formas": formas,
        "qtd_percapitas": len(ativas),
        "qtd_obreiros": len(obreiros),
        "qtd_em_dia": len(obreiros - com_vencido),
        "perc_quitado": round(100 * quitado / lancado, 1) if lancado else 0,
    }


@bp.route("/lancar", methods=["GET", "POST"])
@tesoureiro_required
def lancar():
    ano = _ano_param()
    sugerido = valor_sugerido(ano)
    texto_valor = request.values.get("valor", "")
    valor, erro = None, None
    if texto_valor:
        try:
            valor = ler_moeda(texto_valor)
        except ValueError as e:
            erro = f"Valor inválido: {e}."
    if not pode_lancar_ano(ano):
        flash(f"O lançamento geral só pode ser feito para o ano atual ou seguintes. Para {ano}, "
              "lance individualmente, pelo registro de cada obreiro.", "erro")
        return redirect(url_for("tesouraria.gestao", ano=ano))
    if lancamento_do_ano(ano):
        flash(f"As percapitas de {ano} já foram lançadas. Novos obreiros são lançados individualmente, "
              "pelo registro de cada um.", "aviso")
        return redirect(url_for("tesouraria.gestao", ano=ano))
    if request.method == "POST":
        if valor is None:
            flash(erro or "Informe o valor da percapita do semestre.", "erro")
        else:
            try:
                n = lancar_ano(ano, valor)
            except ValueError as e:
                flash(str(e), "erro")
            else:
                flash(f"{n} percapitas de {ano} lançadas ({fmt_moeda(valor)} por semestre).", "ok")
                return redirect(url_for("tesouraria.gestao", ano=ano))
    elif erro:
        flash(erro, "erro")
    previa = previa_lancamento(ano) if valor else None
    return render_template("tesouraria/lancar.html", ano=ano, valor=valor, texto_valor=texto_valor,
                           sugerido=sugerido, previa=previa)


@bp.route("/desfazer/<int:ano>", methods=["POST"])
@tesoureiro_required
def desfazer(ano):
    try:
        n = desfazer_lancamento(ano)
    except ValueError as e:
        flash(str(e), "erro")
    else:
        flash(f"Lançamento de {ano} desfeito: {n} percapitas removidas.", "ok")
    return redirect(url_for("tesouraria.gestao", ano=ano))


@bp.route("/obreiro/<int:obreiro_id>")
@relatorios_required
def obreiro(obreiro_id):
    o = _obreiro(obreiro_id)
    resumo = resumo_obreiro(obreiro_id)
    return render_template("tesouraria/obreiro.html", o=o, resumo=resumo, anos=_por_ano(resumo["percapitas"]),
                           pagamentos=pagamentos_do_obreiro(obreiro_id), ano_atual=date.today().year,
                           gere=gere_tesouraria())


@bp.route("/obreiro/<int:obreiro_id>/pagamento", methods=["GET", "POST"])
@tesoureiro_required
def pagamento(obreiro_id):
    o = _obreiro(obreiro_id)
    abertas = [p for p in percapitas_do_obreiro(obreiro_id) if p["saldo"] > 0]
    anos = sorted({p["ano"] for p in abertas})
    if not anos:
        flash(f"{o['nome']} não tem percapitas em aberto.", "aviso")
        return redirect(url_for("tesouraria.obreiro", obreiro_id=obreiro_id))
    ano = _ano_param(padrao=anos[0])
    if ano not in anos:
        ano = anos[0]
    do_ano = [p for p in abertas if p["ano"] == ano]
    form = {"valor": fmt_moeda(do_ano[0]["saldo"], simbolo=False), "data": hoje(), "forma": FORMA_PADRAO,
            "observacao": ""}
    if request.method == "POST":
        form = {k: (request.form.get(k) or "").strip() for k in form}
        erros = []
        try:
            valor = ler_moeda(form["valor"])
            if valor is None:
                erros.append("Informe o valor pago.")
        except ValueError as e:
            erros.append(f"Valor inválido: {e}.")
        try:
            data_pag = ler_data(form["data"])
            if not data_pag:
                erros.append("Informe a data do pagamento.")
            elif data_pag > hoje():
                erros.append("A data do pagamento não pode ser futura.")
        except ValueError:
            erros.append("Data do pagamento inválida.")
        if form["forma"] not in FORMAS:
            erros.append("Escolha a forma de pagamento.")
        if not erros:
            try:
                registrar_pagamento(obreiro_id, ano, valor, data_pag, form["forma"], form["observacao"][:300])
            except ValueError as e:
                erros.append(str(e))
            else:
                flash(f"Pagamento de {fmt_moeda(valor)} ({form['forma']}) registrado para {o['nome']}.", "ok")
                return redirect(url_for("tesouraria.obreiro", obreiro_id=obreiro_id))
        for e in erros:
            flash(e, "erro")
    return render_template("tesouraria/pagamento.html", o=o, ano=ano, anos=anos, do_ano=do_ano,
                           saldo_ano=sum(p["saldo"] for p in do_ano), form=form, FORMAS=FORMAS, hoje=hoje())


@bp.route("/obreiro/<int:obreiro_id>/lancar", methods=["GET", "POST"])
@tesoureiro_required
def lancar_obreiro(obreiro_id):
    o = _obreiro(obreiro_id)
    ano = _ano_param()
    existentes = {p["semestre"]: p for p in percapitas("p.obreiro_id = ? AND p.ano = ?", (obreiro_id, ano))}
    opcoes = []
    for s in (1, 2):
        atual = existentes.get(s)
        opcoes.append({"semestre": s, "rotulo": rotulo_semestre(ano, s), "vencimento": vencimento(ano, s),
                       "motivo": motivo_isencao(o, ano, s), "atual": atual,
                       "disponivel": atual is None or atual["cancelada"]})
    sugerido = valor_sugerido(ano)
    texto_valor = fmt_moeda(sugerido, simbolo=False) if sugerido else ""
    if request.method == "POST":
        texto_valor = request.form.get("valor", "")
        escolhidos = [s for s in (1, 2) if request.form.get(f"semestre_{s}") and opcoes[s - 1]["disponivel"]]
        try:
            valor = ler_moeda(texto_valor)
        except ValueError as e:
            flash(f"Valor inválido: {e}.", "erro")
        else:
            if valor is None:
                flash("Informe o valor da percapita.", "erro")
            elif not escolhidos:
                flash("Marque ao menos um semestre.", "erro")
            else:
                feitos = lancar_individual(obreiro_id, ano, escolhidos, valor)
                flash(f"Percapita lançada para {o['nome']}: {', '.join(feitos)} ({fmt_moeda(valor)} cada).", "ok")
                return redirect(url_for("tesouraria.obreiro", obreiro_id=obreiro_id))
    return render_template("tesouraria/lancar_obreiro.html", o=o, ano=ano, opcoes=opcoes,
                           texto_valor=texto_valor, anos=sorted({ano - 1, ano, ano + 1, date.today().year}))


def _motivo() -> str | None:
    motivo = " ".join((request.form.get("motivo") or "").split())[:300]
    if not motivo:
        flash("Informe o motivo.", "erro")
    return motivo or None


@bp.route("/percapita/<int:percapita_id>/cancelar", methods=["POST"])
@tesoureiro_required
def cancelar(percapita_id):
    p = get_db().execute("SELECT obreiro_id FROM percapita WHERE id = ?", (percapita_id,)).fetchone()
    if p is None:
        abort(404)
    motivo = _motivo()
    if motivo:
        try:
            c = cancelar_percapita(percapita_id, motivo)
        except ValueError as e:
            flash(str(e), "erro")
        else:
            flash(f"Percapita do {rotulo_semestre(c['ano'], c['semestre'])} cancelada.", "ok")
    return redirect(url_for("tesouraria.obreiro", obreiro_id=p["obreiro_id"]))


@bp.route("/percapita/<int:percapita_id>/excluir", methods=["POST"])
@tesoureiro_required
def excluir(percapita_id):
    p = get_db().execute("SELECT obreiro_id FROM percapita WHERE id = ?", (percapita_id,)).fetchone()
    if p is None:
        abort(404)
    try:
        x = excluir_percapita(percapita_id)
    except ValueError as e:
        flash(str(e), "erro")
    else:
        flash(f"Lançamento do {rotulo_semestre(x['ano'], x['semestre'])} excluído.", "ok")
    return redirect(url_for("tesouraria.obreiro", obreiro_id=p["obreiro_id"]))


@bp.route("/pagamento/<int:pagamento_id>/estornar", methods=["POST"])
@tesoureiro_required
def estornar(pagamento_id):
    pag = get_db().execute("SELECT obreiro_id FROM pagamento WHERE id = ?", (pagamento_id,)).fetchone()
    if pag is None:
        abort(404)
    motivo = _motivo()
    if motivo:
        try:
            x = estornar_pagamento(pagamento_id, motivo)
        except ValueError as e:
            flash(str(e), "erro")
        else:
            flash(f"Pagamento de {fmt_moeda(x['valor'])} estornado.", "ok")
    return redirect(url_for("tesouraria.obreiro", obreiro_id=pag["obreiro_id"]))


def init_app(app):
    app.jinja_env.filters["moeda"] = fmt_moeda

    @app.context_processor
    def permissoes_tesouraria():
        if not current_user.is_authenticated:
            return {}
        return {"pode_tesouraria": gere_tesouraria(), "pode_relatorios": ve_relatorios()}
