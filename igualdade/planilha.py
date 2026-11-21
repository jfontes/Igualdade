"""Planilha Excel (.xlsx) das sessões: exportação e leitura para a tela "Gerenciar" da agenda.

A leitura não grava nada: as linhas são carregadas na tela de gerenciar, onde a Secretaria
confere e grava com "Incluir na agenda". Balaústres não entram na planilha.
"""
import io
import unicodedata
import zipfile
from datetime import date, datetime

from flask import Blueprint, request, send_file
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils.exceptions import InvalidFileException
from openpyxl.worksheet.datavalidation import DataValidation

from .auth import admin_required
from .db import get_db
from .sessoes import GRAUS, ORDEM_MAX, TIPOS

bp = Blueprint("planilha", __name__, url_prefix="/admin/sessoes")

COLUNAS = ["Data", "Tipo", "Grau", "Ordem do dia", "Cancelada", "Motivo do cancelamento"]
CAMPOS = ["data", "tipo", "grau", "ordem_do_dia", "cancelada", "motivo_cancelamento"]
LARGURAS = [13, 16, 14, 60, 11, 34]
LINHAS_VALIDACAO = 400
SIM = {"sim", "s", "x", "1", "true", "verdadeiro"}
NAO = {"", "nao", "n", "0", "false", "falso"}


def _norm(valor) -> str:
    """Texto sem acento, minúsculo e sem espaços extras (para comparar cabeçalhos e opções)."""
    t = unicodedata.normalize("NFKD", str(valor or "")).encode("ascii", "ignore").decode()
    return " ".join(t.lower().split())


CABECALHOS = {_norm(c): campo for c, campo in zip(COLUNAS, CAMPOS)}
CABECALHOS.update({"motivo": "motivo_cancelamento", "ordem": "ordem_do_dia"})
TIPOS_NORM = {_norm(t): t for t in TIPOS}
GRAUS_NORM = {_norm(g): g for g in GRAUS}


# ---------------------------------------------------------------- exportar

@bp.route("/exportar")
@admin_required
def exportar():
    try:
        ano = int(request.args.get("ano", date.today().year))
    except ValueError:
        ano = date.today().year
    sessoes = get_db().execute(
        "SELECT * FROM sessao WHERE substr(data, 1, 4) = ? ORDER BY data, id", (f"{ano:04d}",)).fetchall()

    wb = Workbook()
    ws = wb.active
    ws.title = f"Sessões {ano}"
    ws.append(COLUNAS)
    for s in sessoes:
        ws.append([date.fromisoformat(s["data"]), s["tipo"], s["grau"] or "", s["ordem_do_dia"] or "",
                   "Sim" if s["cancelada"] else "Não", s["motivo_cancelamento"] or ""])

    cabecalho = PatternFill("solid", fgColor="560710")
    for i, largura in enumerate(LARGURAS, start=1):
        celula = ws.cell(row=1, column=i)
        celula.font = Font(bold=True, color="FFFFFF")
        celula.fill = cabecalho
        celula.alignment = Alignment(vertical="center")
        ws.column_dimensions[celula.column_letter].width = largura
    for linha in ws.iter_rows(min_row=2, max_row=max(ws.max_row, LINHAS_VALIDACAO), max_col=len(COLUNAS)):
        linha[0].number_format = "DD/MM/YYYY"
        linha[3].alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"

    # listas de escolha nas colunas Tipo, Grau e Cancelada (facilita a edição no Excel)
    for coluna, opcoes in (("B", TIPOS), ("C", GRAUS), ("E", ["Sim", "Não"])):
        dv = DataValidation(type="list", formula1='"' + ",".join(opcoes) + '"', allow_blank=True)
        dv.error, dv.errorTitle = "Escolha um valor da lista.", "Valor inválido"
        ws.add_data_validation(dv)
        dv.add(f"{coluna}2:{coluna}{LINHAS_VALIDACAO}")

    ajuda = wb.create_sheet("Como usar")
    for texto in [
        "Como usar esta planilha",
        "",
        "• Cada linha é uma sessão. Para incluir uma sessão, preencha uma linha nova.",
        "• A DATA identifica a sessão: se a data já existe no sistema, a sessão é atualizada;",
        "  se não existe, é incluída. Sessões que não estão na planilha não são apagadas.",
        f"• Tipo: {', '.join(TIPOS)} (em branco = Ordinária).",
        f"• Grau: {', '.join(GRAUS)}. Obrigatório, exceto nas sessões canceladas.",
        "• Cancelada: Sim ou Não. Quando Sim, informe o motivo (ex.: Feriado).",
        f"• Ordem do dia: até {ORDEM_MAX} caracteres.",
        "• Não mude os títulos da primeira linha da aba de sessões.",
        "• No sistema: Agenda → Gerenciar → Carregar planilha. As linhas aparecem na tela",
        "  para conferência e só são gravadas ao tocar em \"Incluir na agenda\".",
        "• O balaústre das sessões não faz parte da planilha e não é alterado.",
    ]:
        ajuda.append([texto])
    ajuda["A1"].font = Font(bold=True, size=13)
    ajuda.column_dimensions["A"].width = 100

    saida = io.BytesIO()
    wb.save(saida)
    saida.seek(0)
    return send_file(saida, as_attachment=True, download_name=f"sessoes_{ano}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ---------------------------------------------------------------- leitura (para a tela de gerenciar)

def _ler_data(valor):
    if isinstance(valor, datetime):
        return valor.date().isoformat()
    if isinstance(valor, date):
        return valor.isoformat()
    texto = str(valor or "").strip()
    for formato in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%Y"):
        try:
            return datetime.strptime(texto, formato).date().isoformat()
        except ValueError:
            continue
    return None


def _texto(valor) -> str:
    return " ".join(str(valor if valor is not None else "").split())


def ler_planilha(arquivo):
    """Lê a planilha sem gravar.

    Retorna (linhas, avisos): linhas = [(nº da linha, dados, problemas)], em que `problemas`
    descreve o que precisa ser corrigido na tela; `avisos` são linhas que não puderam ser
    carregadas (data inválida ou repetida) e problemas do arquivo.
    """
    try:
        wb = load_workbook(io.BytesIO(arquivo.read()), read_only=True, data_only=True)
    except (InvalidFileException, zipfile.BadZipFile, KeyError, ValueError, OSError):
        return [], ["O arquivo não é uma planilha Excel (.xlsx) válida."]
    ws = wb.worksheets[0]
    brutas = ws.iter_rows(values_only=True)
    cabecalho = next(brutas, None) or ()
    posicoes = {}
    for i, titulo in enumerate(cabecalho):
        campo = CABECALHOS.get(_norm(titulo))
        if campo and campo not in posicoes:
            posicoes[campo] = i
    faltam = [c for c, campo in zip(COLUNAS, CAMPOS) if campo not in posicoes and campo != "motivo_cancelamento"]
    if faltam:
        return [], [f"A primeira linha não tem as colunas: {', '.join(faltam)}. Use a planilha exportada pelo sistema."]

    linhas, avisos, datas = [], [], {}
    for n, valores in enumerate(brutas, start=2):
        def pega(campo):
            i = posicoes.get(campo)
            return valores[i] if i is not None and i < len(valores) else None

        if all(_texto(v) == "" for v in valores):
            continue  # linha em branco
        data_iso = _ler_data(pega("data"))
        if not data_iso:
            avisos.append(f"Linha {n}: data inválida (use dd/mm/aaaa). A linha não foi carregada.")
            continue
        if data_iso in datas:
            avisos.append(f"Linha {n}: data repetida (também na linha {datas[data_iso]}). A linha não foi carregada.")
            continue
        datas[data_iso] = n

        problemas = []
        tipo_txt = _texto(pega("tipo"))
        tipo = TIPOS_NORM.get(_norm(tipo_txt)) if tipo_txt else "Ordinária"
        if tipo is None:
            problemas.append(f"tipo \"{tipo_txt}\" não existe")
        grau_txt = _texto(pega("grau"))
        grau = GRAUS_NORM.get(_norm(grau_txt).split(" ")[0]) if grau_txt else None
        if grau_txt and grau is None:
            problemas.append(f"grau \"{grau_txt}\" não existe")
        cancelada_txt = _norm(pega("cancelada"))
        if cancelada_txt not in SIM | NAO:
            problemas.append(f"Cancelada \"{_texto(pega('cancelada'))}\" deve ser Sim ou Não")
        cancelada = cancelada_txt in SIM
        linhas.append((n, {
            "data": data_iso, "tipo": tipo, "grau": grau,
            "ordem_do_dia": _texto(pega("ordem_do_dia")) or None,
            "cancelada": 1 if cancelada else 0,
            "motivo_cancelamento": (_texto(pega("motivo_cancelamento")) or None) if cancelada else None,
        }, problemas))
    if not linhas and not avisos:
        avisos.append("A planilha não tem nenhuma sessão.")
    return linhas, avisos
