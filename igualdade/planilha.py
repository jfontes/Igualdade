"""Planilha Excel (.xlsx) da agenda da Loja: sessões e eventos (sem aniversários).

Uma única aba, uma linha por compromisso, em ordem de data. Na coluna Tipo, "Evento" indica
um evento (nome na coluna "Ordem do dia / Evento"); os demais tipos são sessões.

A leitura não grava nada: as linhas são carregadas na tela de gerenciar, onde a Secretaria
confere e grava com "Incluir na agenda". Balaústres e descrição dos eventos não entram na planilha.
"""
import io
import re
import unicodedata
import zipfile
from datetime import date, datetime, time

from flask import Blueprint, request, send_file
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils.exceptions import InvalidFileException
from openpyxl.worksheet.datavalidation import DataValidation

from .auth import admin_required
from .db import get_db
from .sessoes import GRAUS, ORDEM_MAX, TIPOS

bp = Blueprint("planilha", __name__, url_prefix="/admin/sessoes")

EVENTO = "Evento"
TIPOS_PLANILHA = TIPOS + [EVENTO]
COLUNAS = ["Data", "Tipo", "Grau", "Ordem do dia / Evento", "Hora", "Local", "Cancelada", "Motivo do cancelamento"]
CAMPOS = ["data", "tipo", "grau", "ordem_do_dia", "hora", "local", "cancelada", "motivo_cancelamento"]
OBRIGATORIAS = {"data", "tipo", "grau", "ordem_do_dia", "cancelada"}  # planilhas antigas não têm Hora/Local
LARGURAS = [13, 16, 14, 60, 8, 24, 11, 34]
LINHAS_VALIDACAO = 400
TITULO_MAX = 120
SIM = {"sim", "s", "x", "1", "true", "verdadeiro"}
NAO = {"", "nao", "n", "0", "false", "falso"}


def _norm(valor) -> str:
    """Texto sem acento, minúsculo e sem espaços extras (para comparar cabeçalhos e opções)."""
    t = unicodedata.normalize("NFKD", str(valor or "")).encode("ascii", "ignore").decode()
    return " ".join(t.lower().split())


CABECALHOS = {_norm(c): campo for c, campo in zip(COLUNAS, CAMPOS)}
CABECALHOS.update({"motivo": "motivo_cancelamento", "ordem": "ordem_do_dia", "ordem do dia": "ordem_do_dia",
                   "evento": "ordem_do_dia", "cancelado": "cancelada"})
TIPOS_NORM = {_norm(t): t for t in TIPOS_PLANILHA}
GRAUS_NORM = {_norm(g): g for g in GRAUS}


# ---------------------------------------------------------------- exportar

@bp.route("/exportar")
@admin_required
def exportar():
    try:
        ano = int(request.args.get("ano", date.today().year))
    except ValueError:
        ano = date.today().year
    db = get_db()
    linhas = [(s["data"], 0, [date.fromisoformat(s["data"]), s["tipo"], s["grau"] or "", s["ordem_do_dia"] or "",
                              "", "", "Sim" if s["cancelada"] else "Não", s["motivo_cancelamento"] or ""])
              for s in db.execute("SELECT * FROM sessao WHERE substr(data, 1, 4) = ? ORDER BY data, id",
                                  (f"{ano:04d}",))]
    linhas += [(e["data"], 1, [date.fromisoformat(e["data"]), EVENTO, "", e["titulo"], e["hora"] or "",
                               e["local"] or "", "Sim" if e["cancelado"] else "Não", e["motivo_cancelamento"] or ""])
               for e in db.execute("SELECT * FROM evento WHERE substr(data, 1, 4) = ? ORDER BY data, hora, id",
                                   (f"{ano:04d}",))]
    linhas.sort(key=lambda x: (x[0], x[1]))

    wb = Workbook()
    ws = wb.active
    ws.title = f"Agenda {ano}"
    ws.append(COLUNAS)
    amarelo = PatternFill("solid", fgColor="FFF3BF")
    for _, eh_evento, valores in linhas:
        ws.append(valores)
        if eh_evento:
            for celula in ws[ws.max_row]:
                celula.fill = amarelo

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
    for coluna, opcoes in (("B", TIPOS_PLANILHA), ("C", GRAUS), ("G", ["Sim", "Não"])):
        dv = DataValidation(type="list", formula1='"' + ",".join(opcoes) + '"', allow_blank=True)
        dv.error, dv.errorTitle = "Escolha um valor da lista.", "Valor inválido"
        ws.add_data_validation(dv)
        dv.add(f"{coluna}2:{coluna}{LINHAS_VALIDACAO}")

    ajuda = wb.create_sheet("Como usar")
    for texto in [
        "Como usar esta planilha",
        "",
        "• Cada linha é um compromisso da agenda da Loja: uma sessão ou um evento (aniversários não entram).",
        "",
        "Sessões",
        f"• Tipo: {', '.join(TIPOS)} (em branco = Ordinária).",
        "• A DATA identifica a sessão: se já existe sessão nessa data, ela é atualizada; senão, é incluída.",
        f"• Grau: {', '.join(GRAUS)}. Obrigatório, exceto nas sessões canceladas.",
        f"• Ordem do dia: até {ORDEM_MAX} caracteres. Hora e Local não se aplicam às sessões.",
        "",
        "Eventos (linhas em amarelo)",
        "• Tipo: Evento. Escreva o NOME do evento na coluna \"Ordem do dia / Evento\" (ex.: Dia das Mães).",
        "• Grau fica em branco. Hora (ex.: 19:30) e Local são opcionais.",
        "• DATA + NOME identificam o evento: se já existe, ele é atualizado; senão, é incluído.",
        "  Um evento pode cair no mesmo dia de uma sessão.",
        "• A descrição detalhada do evento é editada no sistema e não é alterada pela planilha.",
        "",
        "Para todos",
        "• Cancelada: Sim ou Não. Quando Sim, informe o motivo (ex.: Feriado).",
        "• Nada que não está na planilha é apagado.",
        "• Não mude os títulos da primeira linha da aba da agenda.",
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
    return send_file(saida, as_attachment=True, download_name=f"agenda_{ano}.xlsx",
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


def _ler_hora(valor):
    """'19:30', '19h30', 19:30 (célula de hora do Excel) → '19:30'. Vazio → None. Inválida → False."""
    if valor is None or valor == "":
        return None
    if isinstance(valor, datetime):
        valor = valor.time()
    if isinstance(valor, time):
        return f"{valor.hour:02d}:{valor.minute:02d}"
    if isinstance(valor, (int, float)) and 0 <= valor < 1:  # fração do dia
        minutos = round(valor * 24 * 60)
        return f"{minutos // 60:02d}:{minutos % 60:02d}"
    m = re.fullmatch(r"(\d{1,2})\s*[:hH]\s*(\d{2})?", str(valor).strip())
    if not m or int(m.group(1)) > 23 or int(m.group(2) or 0) > 59:
        return False
    return f"{int(m.group(1)):02d}:{int(m.group(2) or 0):02d}"


def _texto(valor) -> str:
    return " ".join(str(valor if valor is not None else "").split())


def chave_evento(data_iso: str, titulo: str) -> tuple[str, str]:
    """Identidade do evento na planilha: data + nome (sem acento, caixa ou espaços extras)."""
    return data_iso, _norm(titulo)


def ler_planilha(arquivo):
    """Lê a planilha sem gravar.

    Retorna (linhas, avisos): linhas = [(nº da linha, dados, problemas)], em que `dados["evento"]`
    diz se é evento ou sessão e `problemas` descreve o que precisa ser corrigido; `avisos` são
    linhas que não puderam ser carregadas (data inválida ou repetida) e problemas do arquivo.
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
    faltam = [c for c, campo in zip(COLUNAS, CAMPOS) if campo in OBRIGATORIAS and campo not in posicoes]
    if faltam:
        return [], [f"A primeira linha não tem as colunas: {', '.join(faltam)}. Use a planilha exportada pelo sistema."]

    linhas, avisos, datas_sessao, chaves_evento = [], [], {}, {}
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

        problemas = []
        tipo_txt = _texto(pega("tipo"))
        tipo = TIPOS_NORM.get(_norm(tipo_txt)) if tipo_txt else "Ordinária"
        if tipo is None:
            problemas.append(f"tipo \"{tipo_txt}\" não existe")
        cancelada_txt = _norm(pega("cancelada"))
        if cancelada_txt not in SIM | NAO:
            problemas.append(f"Cancelada \"{_texto(pega('cancelada'))}\" deve ser Sim ou Não")
        cancelada = cancelada_txt in SIM
        motivo = (_texto(pega("motivo_cancelamento")) or None) if cancelada else None
        descricao = _texto(pega("ordem_do_dia")) or None

        if tipo == EVENTO:
            if not descricao:
                avisos.append(f"Linha {n}: evento sem nome (coluna \"Ordem do dia / Evento\"). A linha não foi carregada.")
                continue
            chave = chave_evento(data_iso, descricao)
            if chave in chaves_evento:
                avisos.append(f"Linha {n}: evento repetido (também na linha {chaves_evento[chave]}). "
                              "A linha não foi carregada.")
                continue
            chaves_evento[chave] = n
            hora = _ler_hora(pega("hora"))
            if hora is False:
                problemas.append(f"hora \"{_texto(pega('hora'))}\" inválida (use HH:MM)")
                hora = None
            if len(descricao) > TITULO_MAX:
                problemas.append(f"o nome do evento passa de {TITULO_MAX} caracteres")
            linhas.append((n, {"evento": True, "data": data_iso, "titulo": descricao[:TITULO_MAX], "hora": hora,
                               "local": (_texto(pega("local")) or None), "cancelado": 1 if cancelada else 0,
                               "motivo_cancelamento": motivo}, problemas))
            continue

        if data_iso in datas_sessao:
            avisos.append(f"Linha {n}: sessão com data repetida (também na linha {datas_sessao[data_iso]}). "
                          "A linha não foi carregada.")
            continue
        datas_sessao[data_iso] = n
        grau_txt = _texto(pega("grau"))
        grau = GRAUS_NORM.get(_norm(grau_txt).split(" ")[0]) if grau_txt else None
        if grau_txt and grau is None:
            problemas.append(f"grau \"{grau_txt}\" não existe")
        linhas.append((n, {
            "evento": False, "data": data_iso, "tipo": tipo, "grau": grau, "ordem_do_dia": descricao,
            "cancelada": 1 if cancelada else 0, "motivo_cancelamento": motivo,
        }, problemas))
    if not linhas and not avisos:
        avisos.append("A planilha não tem nenhuma sessão ou evento.")
    return linhas, avisos
