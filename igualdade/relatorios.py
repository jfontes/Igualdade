"""Relatórios da Secretaria e da Tesouraria: tela (com impressão / PDF) e Excel.

Cada relatório monta um dicionário com título, filtros, resumo e tabelas. O mesmo conteúdo
é usado na tela (template genérico) e na planilha, para os dois sempre baterem.
Acesso: Secretaria (admin), Tesoureiro e Venerável Mestre da gestão vigente.
"""
import io
import re
import unicodedata
from datetime import date, datetime

from flask import Blueprint, abort, render_template, request, send_file
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from .config import LOJA
from .db import get_db
from .tesouraria import (FORMAS, FORMAS_CAIXA, ISENCAO, anos_com_registro, pagamentos_do_obreiro, percapitas,
                         relatorios_required, rotulo_semestre, totais_do_ano)
from .util import fmt_data, fmt_moeda, grau_do_obreiro, ler_data

bp = Blueprint("relatorios", __name__, url_prefix="/relatorios")

GRAUS = ["Mestre", "Companheiro", "Aprendiz"]

# (chave, título, descrição, ícone, grupo)
RELATORIOS = [
    ("obreiros-ativos", "Obreiros ativos", "Grau, Mestre Instalado, Emérito e VM de Honra", "🏛️", "Secretaria"),
    ("situacao", "Situação do ano", "Percapitas de cada obreiro no ano: 1º e 2º semestre e saldo", "📋", "Tesouraria"),
    ("inadimplentes", "Inadimplentes", "Quem tem percapita vencida, do maior para o menor valor", "🔴", "Tesouraria"),
    ("recebimentos", "Recebimentos por período", "Pagamentos entre duas datas, com total por forma", "💵", "Tesouraria"),
    ("resumo", "Resumo anual", "Lançado, recebido, isentado e a receber por semestre", "📊", "Tesouraria"),
    ("extrato", "Extrato individual", "Histórico completo de percapitas e pagamentos de um obreiro", "🧾", "Tesouraria"),
]
TITULOS = {r[0]: r[1] for r in RELATORIOS}


def _ano() -> int:
    try:
        return min(max(int(request.args.get("ano") or date.today().year), 2000), 2100)
    except ValueError:
        return date.today().year


def _filtro_ano(ano: int) -> dict:
    return {"nome": "ano", "rotulo": "Ano", "tipo": "select", "valor": str(ano),
            "opcoes": [(str(a), str(a)) for a in anos_com_registro(ano)]}


def _sim_data(d):
    return d or ""


# ---------------------------------------------------------------- relatórios

def rel_obreiros_ativos() -> dict:
    grau = request.args.get("grau", "")
    rows = get_db().execute("SELECT * FROM obreiro WHERE data_afastamento IS NULL ORDER BY nome").fetchall()
    linhas, cont = [], {g: 0 for g in GRAUS}
    titulos = {"mi": 0, "emerito": 0, "vm": 0}
    for o in rows:
        g = grau_do_obreiro(o)
        if grau and g != grau:
            continue
        cont[g] = cont.get(g, 0) + 1
        titulos["mi"] += bool(o["data_instalacao"])
        titulos["emerito"] += bool(o["data_emerito"])
        titulos["vm"] += bool(o["data_vm_honra"])
        linhas.append([o["nome"], o["cim"], g or "—", _sim_data(o["data_instalacao"]),
                       _sim_data(o["data_emerito"]), _sim_data(o["data_vm_honra"])])
    resumo = [("Total", str(len(linhas)))] + [(g + "s", str(cont[g])) for g in GRAUS if not grau or g == grau]
    resumo += [("Mestres Instalados", str(titulos["mi"])), ("Eméritos", str(titulos["emerito"])),
               ("VM de Honra", str(titulos["vm"]))]
    return {
        "subtitulo": f"Posição em {fmt_data(date.today().isoformat())}" + (f" · somente {grau}s" if grau else ""),
        "filtros": [{"nome": "grau", "rotulo": "Grau", "tipo": "select", "valor": grau,
                     "opcoes": [("", "Todos os graus")] + [(g, g) for g in GRAUS]}],
        "resumo": resumo,
        "tabelas": [{
            "colunas": [("Nome", "texto"), ("CIM", "centro"), ("Grau", "texto"), ("Mestre Instalado", "data"),
                        ("Emérito", "data"), ("VM de Honra", "data")],
            "linhas": linhas,
        }],
        "nota": "Nas colunas de títulos aparece a data em que o título foi conferido.",
    }


def _situacao_txt(p) -> str:
    if p is None:
        return "—"
    txt = p["rotulo"]
    if p["situacao"] in ("parcial", "vencida") and p["pago"]:
        txt += f" · pago {fmt_moeda(p['pago'])}"
    return txt


def rel_situacao() -> dict:
    ano = _ano()
    lista = percapitas("p.ano = ?", (ano,))
    por_obreiro: dict[int, dict] = {}
    for p in lista:
        d = por_obreiro.setdefault(p["obreiro_id"], {"nome": p["nome"], "cim": p["cim"],
                                                     "afastado": bool(p["data_afastamento"]), 1: None, 2: None})
        d[p["semestre"]] = p
    linhas, tot = [], [0, 0, 0]
    for d in sorted(por_obreiro.values(), key=lambda x: x["nome"]):
        ativas = [d[s] for s in (1, 2) if d[s] and not d[s]["cancelada"]]
        lancado = sum(p["valor"] for p in ativas)
        pago = sum(p["pago"] for p in ativas)
        saldo = sum(p["saldo"] for p in ativas)
        tot = [tot[0] + lancado, tot[1] + pago, tot[2] + saldo]
        linhas.append([d["nome"] + (" (afastado)" if d["afastado"] else ""), d["cim"],
                       {"situacao": d[1]["situacao"] if d[1] else None, "texto": _situacao_txt(d[1])},
                       {"situacao": d[2]["situacao"] if d[2] else None, "texto": _situacao_txt(d[2])},
                       lancado, pago, saldo])
    t = totais_do_ano(ano, lista)
    return {
        "subtitulo": f"Ano {ano} · posição em {fmt_data(date.today().isoformat())}",
        "filtros": [_filtro_ano(ano)],
        "resumo": [("Obreiros", str(t["qtd_obreiros"])), ("Em dia", str(t["qtd_em_dia"])),
                   ("Lançado", fmt_moeda(t["lancado"])), ("Quitado", f"{fmt_moeda(t['quitado'])} ({t['perc_quitado']}%)"),
                   ("A receber", fmt_moeda(t["a_receber"])), ("Vencido", fmt_moeda(t["vencido"]))],
        "tabelas": [{
            "colunas": [("Obreiro", "texto"), ("CIM", "centro"), ("1º semestre", "situacao"),
                        ("2º semestre", "situacao"), ("Lançado", "moeda"), ("Pago", "moeda"), ("Saldo", "moeda")],
            "linhas": linhas,
            "rodape": ["Total", "", "", "", *tot],
        }],
        "nota": "“Pago” inclui abatimentos em crédito e isenções. Percapitas canceladas não entram nos totais.",
    }


def rel_inadimplentes() -> dict:
    hoje = date.today().isoformat()
    vencidas = [p for p in percapitas("p.cancelada = 0") if p["situacao"] == "vencida"]
    por_obreiro: dict[int, dict] = {}
    for p in vencidas:
        d = por_obreiro.setdefault(p["obreiro_id"], {"nome": p["nome"], "cim": p["cim"],
                                                     "afastado": bool(p["data_afastamento"]),
                                                     "semestres": [], "total": 0})
        d["semestres"].append(f"{p['semestre']}º/{p['ano']} ({fmt_moeda(p['saldo'])})")
        d["total"] += p["saldo"]
    ordenados = sorted(por_obreiro.values(), key=lambda d: (-d["total"], d["nome"]))
    linhas = [[d["nome"], d["cim"], "Afastado" if d["afastado"] else "Ativo", "; ".join(d["semestres"]),
               d["total"]] for d in ordenados]
    total = sum(d["total"] for d in ordenados)
    return {
        "subtitulo": f"Percapitas vencidas e não quitadas em {fmt_data(hoje)}",
        "filtros": [],
        "resumo": [("Obreiros", str(len(linhas))), ("Percapitas vencidas", str(len(vencidas))),
                   ("Total vencido", fmt_moeda(total))],
        "tabelas": [{
            "colunas": [("Obreiro", "texto"), ("CIM", "centro"), ("Situação", "texto"),
                        ("Semestres vencidos (saldo)", "texto"), ("Total vencido", "moeda")],
            "linhas": linhas,
            "rodape": ["Total", "", "", "", total],
        }],
    }


def rel_recebimentos() -> dict:
    hoje = date.today()
    try:
        de = ler_data(request.args.get("de")) or hoje.replace(day=1).isoformat()
        ate = ler_data(request.args.get("ate")) or hoje.isoformat()
    except ValueError:
        de, ate = hoje.replace(day=1).isoformat(), hoje.isoformat()
    if de > ate:
        de, ate = ate, de
    db = get_db()
    rows = db.execute(
        "SELECT x.*, o.nome, o.cim FROM pagamento x JOIN obreiro o ON o.id = x.obreiro_id "
        "WHERE x.estornado = 0 AND x.data BETWEEN ? AND ? ORDER BY x.data, o.nome", (de, ate)).fetchall()
    linhas, por_forma = [], {f: 0 for f in FORMAS}
    for r in rows:
        partes = [rotulo_semestre(p["ano"], p["semestre"]) for p in db.execute(
            "SELECT c.ano, c.semestre FROM pagamento_parte pp JOIN percapita c ON c.id = pp.percapita_id "
            "WHERE pp.pagamento_id = ? ORDER BY c.semestre", (r["id"],))]
        por_forma[r["forma"]] += r["valor"]
        linhas.append([r["data"], r["nome"], r["cim"], " + ".join(partes), r["forma"], r["valor"],
                       r["observacao"] or ""])
    caixa = sum(v for f, v in por_forma.items() if f in FORMAS_CAIXA)
    nao_caixa = sum(v for f, v in por_forma.items() if f not in FORMAS_CAIXA)
    resumo = [(f, fmt_moeda(por_forma[f])) for f in FORMAS if por_forma[f]]
    resumo += [("Entrou no caixa", fmt_moeda(caixa)), ("Abatido / isentado", fmt_moeda(nao_caixa))]
    return {
        "subtitulo": f"De {fmt_data(de)} a {fmt_data(ate)}",
        "filtros": [{"nome": "de", "rotulo": "De", "tipo": "date", "valor": de},
                    {"nome": "ate", "rotulo": "Até", "tipo": "date", "valor": ate}],
        "resumo": resumo,
        "tabelas": [
            {"colunas": [("Data", "data"), ("Obreiro", "texto"), ("CIM", "centro"), ("Referência", "texto"),
                         ("Forma", "texto"), ("Valor", "moeda"), ("Observação", "texto")],
             "linhas": linhas,
             "rodape": ["Total", "", "", "", "", caixa + nao_caixa, ""]},
            {"titulo": "Total por forma de pagamento",
             "colunas": [("Forma", "texto"), ("Entra no caixa", "centro"), ("Total", "moeda")],
             "linhas": [[f, "Sim" if f in FORMAS_CAIXA else "Não", por_forma[f]] for f in FORMAS],
             "rodape": ["Total", "", caixa + nao_caixa]},
        ],
        "nota": "Pagamentos estornados não aparecem. Abatimento em crédito e Isenção quitam a percapita, "
                "mas não entram no caixa.",
    }


def rel_resumo() -> dict:
    ano = _ano()
    lista = percapitas("p.ano = ? AND p.cancelada = 0", (ano,))
    formas = {(r["semestre"], r["forma"]): r["total"] for r in get_db().execute(
        "SELECT c.semestre, x.forma, SUM(pp.valor) AS total FROM pagamento_parte pp "
        "JOIN pagamento x ON x.id = pp.pagamento_id JOIN percapita c ON c.id = pp.percapita_id "
        "WHERE x.estornado = 0 AND c.ano = ? AND c.cancelada = 0 GROUP BY c.semestre, x.forma", (ano,))}
    linhas, soma = [], [0] * 7
    for s in (1, 2):
        ps = [p for p in lista if p["semestre"] == s]
        lancado = sum(p["valor"] for p in ps)
        caixa = sum(v for (sem, f), v in formas.items() if sem == s and f in FORMAS_CAIXA)
        abatido = formas.get((s, "Abatimento em crédito"), 0)
        isentado = formas.get((s, ISENCAO), 0)
        a_receber = sum(p["saldo"] for p in ps)
        vencido = sum(p["saldo"] for p in ps if p["situacao"] == "vencida")
        valores = [len(ps), lancado, caixa, abatido, isentado, a_receber, vencido]
        soma = [a + b for a, b in zip(soma, valores)]
        quitado = lancado - a_receber
        linhas.append([f"{s}º semestre", *valores, f"{100 * quitado / lancado:.1f}%" if lancado else "—"])
    quitado_total = soma[1] - soma[5]
    t = totais_do_ano(ano)
    return {
        "subtitulo": f"Ano {ano} · posição em {fmt_data(date.today().isoformat())}",
        "filtros": [_filtro_ano(ano)],
        "resumo": [("Lançado", fmt_moeda(soma[1])), ("Recebido no caixa", fmt_moeda(soma[2])),
                   ("A receber", fmt_moeda(soma[5])), ("Obreiros em dia", f"{t['qtd_em_dia']} de {t['qtd_obreiros']}")],
        "tabelas": [{
            "colunas": [("Semestre", "texto"), ("Percapitas", "centro"), ("Lançado", "moeda"),
                        ("Recebido (caixa)", "moeda"), ("Abatido", "moeda"), ("Isentado", "moeda"),
                        ("A receber", "moeda"), ("Vencido", "moeda"), ("% quitado", "centro")],
            "linhas": linhas,
            "rodape": ["Ano", *soma, f"{100 * quitado_total / soma[1]:.1f}%" if soma[1] else "—"],
        }],
    }


def rel_extrato() -> dict:
    db = get_db()
    opcoes = [(str(r["id"]), f"{r['nome']} (CIM {r['cim']})" + (" — afastado" if r["data_afastamento"] else ""))
              for r in db.execute(
                  "SELECT id, nome, cim, data_afastamento FROM obreiro WHERE data_afastamento IS NULL "
                  "OR id IN (SELECT obreiro_id FROM percapita) ORDER BY nome")]
    escolhido = request.args.get("obreiro", "")
    filtros = [{"nome": "obreiro", "rotulo": "Obreiro", "tipo": "select", "valor": escolhido,
                "opcoes": [("", "Escolha o obreiro…")] + opcoes}]
    o = db.execute("SELECT * FROM obreiro WHERE id = ?", (escolhido,)).fetchone() if escolhido.isdigit() else None
    if o is None:
        return {"subtitulo": "Escolha o obreiro para ver o extrato.", "filtros": filtros, "resumo": [], "tabelas": []}
    lista = percapitas("p.obreiro_id = ?", (o["id"],))
    ativas = [p for p in lista if not p["cancelada"]]
    linhas = [[p["semestre_txt"], p["vencimento"], p["valor"] if not p["cancelada"] else 0, p["pago"], p["saldo"],
               {"situacao": p["situacao"], "texto": p["rotulo"] +
                (f" ({p['motivo_cancelamento']})" if p["cancelada"] else "")}] for p in lista]
    pags = pagamentos_do_obreiro(o["id"])
    linhas_pag = [[x["data"], ", ".join(x["partes"]), x["forma"], x["valor"],
                   (f"ESTORNADO: {x['motivo_estorno']}" if x["estornado"] else "") +
                   (" · " if x["estornado"] and x["observacao"] else "") + (x["observacao"] or "")]
                  for x in sorted(pags, key=lambda x: (x["data"], x["id"]))]
    return {
        "subtitulo": f"{o['nome']} · CIM {o['cim']} · posição em {fmt_data(date.today().isoformat())}",
        "filtros": filtros,
        "resumo": [("Lançado", fmt_moeda(sum(p["valor"] for p in ativas))),
                   ("Pago", fmt_moeda(sum(p["pago"] for p in ativas))),
                   ("Em aberto", fmt_moeda(sum(p["saldo"] for p in ativas))),
                   ("Vencido", fmt_moeda(sum(p["saldo"] for p in ativas if p["situacao"] == "vencida")))]
                  + ([("Emérito desde", fmt_data(o["data_emerito"]))] if o["data_emerito"] else []),
        "tabelas": [
            {"titulo": "Percapitas",
             "colunas": [("Semestre", "texto"), ("Vencimento", "data"), ("Valor", "moeda"), ("Pago", "moeda"),
                         ("Saldo", "moeda"), ("Situação", "situacao")],
             "linhas": linhas,
             "rodape": ["Total", "", sum(p["valor"] for p in ativas), sum(p["pago"] for p in ativas),
                        sum(p["saldo"] for p in ativas), ""]},
            {"titulo": "Pagamentos",
             "colunas": [("Data", "data"), ("Referência", "texto"), ("Forma", "texto"), ("Valor", "moeda"),
                         ("Observação", "texto")],
             "linhas": linhas_pag},
        ],
        "arquivo": f"extrato-{o['cim']}",
    }


GERADORES = {
    "obreiros-ativos": rel_obreiros_ativos,
    "situacao": rel_situacao,
    "inadimplentes": rel_inadimplentes,
    "recebimentos": rel_recebimentos,
    "resumo": rel_resumo,
    "extrato": rel_extrato,
}


# ---------------------------------------------------------------- Excel

def _nome_arquivo(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def _valor_excel(valor, tipo):
    if isinstance(valor, dict):
        return valor["texto"]
    if tipo == "moeda" and isinstance(valor, int):
        return valor / 100
    if tipo == "data" and isinstance(valor, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", valor):
        return date.fromisoformat(valor)
    return valor


def gerar_xlsx(titulo: str, rel: dict) -> io.BytesIO:
    wb = Workbook()
    ws = wb.active
    ws.title = titulo[:31]
    bordo = PatternFill("solid", fgColor="560710")
    cinza = PatternFill("solid", fgColor="F3ECEC")
    fina = Side(style="thin", color="D9CACA")
    ws.append([f"{LOJA['titulo']} {LOJA['nome']}"])
    ws.append([titulo])
    ws.append([rel.get("subtitulo", "")])
    ws["A1"].font = Font(bold=True, color="560710")
    ws["A2"].font = Font(bold=True, size=14)
    ws["A3"].font = Font(italic=True, color="6F5F61")
    larguras: dict[int, int] = {}
    for tabela in rel["tabelas"]:
        ws.append([])
        if tabela.get("titulo"):
            ws.append([tabela["titulo"]])
            ws.cell(row=ws.max_row, column=1).font = Font(bold=True, color="560710")
        ws.append([c[0] for c in tabela["colunas"]])
        for i in range(1, len(tabela["colunas"]) + 1):
            cel = ws.cell(row=ws.max_row, column=i)
            cel.font, cel.fill = Font(bold=True, color="FFFFFF"), bordo
            cel.alignment = Alignment(vertical="center", wrap_text=True)
        linhas = list(tabela["linhas"]) + ([tabela["rodape"]] if tabela.get("rodape") else [])
        for n, linha in enumerate(linhas):
            ws.append([_valor_excel(v, c[1]) for v, c in zip(linha, tabela["colunas"])])
            rodape = tabela.get("rodape") and n == len(linhas) - 1
            for i, (v, (rotulo, tipo)) in enumerate(zip(linha, tabela["colunas"]), start=1):
                cel = ws.cell(row=ws.max_row, column=i)
                cel.border = Border(bottom=fina)
                if tipo == "moeda":
                    cel.number_format = '"R$" #,##0.00'
                elif tipo == "data":
                    cel.number_format = "DD/MM/YYYY"
                if tipo == "centro":
                    cel.alignment = Alignment(horizontal="center")
                if rodape:
                    cel.font, cel.fill = Font(bold=True), cinza
                texto = str(_valor_excel(v, tipo) if tipo != "data" else "00/00/0000")
                larguras[i] = max(larguras.get(i, 8), min(len(texto) + 2, 60), len(rotulo) + 2)
    for i, largura in larguras.items():
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = largura
    if rel.get("resumo"):
        ws.append([])
        ws.append(["Resumo"])
        ws.cell(row=ws.max_row, column=1).font = Font(bold=True, color="560710")
        for rotulo, valor in rel["resumo"]:
            ws.append([rotulo, valor])
    ws.append([])
    ws.append([f"Emitido em {datetime.now().strftime('%d/%m/%Y %H:%M')}"])
    ws.cell(row=ws.max_row, column=1).font = Font(italic=True, color="6F5F61")
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


# ---------------------------------------------------------------- telas

@bp.route("/")
@relatorios_required
def index():
    grupos: dict[str, list] = {}
    for chave, titulo, descricao, icone, grupo in RELATORIOS:
        grupos.setdefault(grupo, []).append({"chave": chave, "titulo": titulo, "descricao": descricao,
                                             "icone": icone})
    return render_template("relatorios/index.html", grupos=grupos)


@bp.route("/<chave>")
@relatorios_required
def ver(chave):
    if chave not in GERADORES:
        abort(404)
    titulo = TITULOS[chave]
    rel = GERADORES[chave]()
    if request.args.get("formato") == "xlsx":
        nome = rel.get("arquivo") or _nome_arquivo(f"{titulo} {rel.get('subtitulo', '')[:40]}")
        return send_file(gerar_xlsx(titulo, rel), as_attachment=True, download_name=f"{_nome_arquivo(nome)}.xlsx",
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    args_xlsx = {k: v for k, v in request.args.items() if k != "formato"} | {"formato": "xlsx"}
    return render_template("relatorios/relatorio.html", chave=chave, titulo=titulo, rel=rel, args_xlsx=args_xlsx,
                           emitido=datetime.now().strftime("%d/%m/%Y %H:%M"))
