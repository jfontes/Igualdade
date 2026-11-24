"""PDF dos contratos de locação do Parque das Acácias (ReportLab + pypdf).

- montar_contrato(): o contrato em si. Por enquanto é um MODELO DE TESTE; o texto definitivo
  será construído aqui quando a Loja enviar o contrato (mantendo a mesma interface).
- anexo_vistoria(): "ANEXO I – REGISTRO FOTOGRÁFICO DE VISTORIA" (2 fotos por linha).
- carimbar_rubrica(): estampa a rubrica do contratante no campo de assinatura e no rodapé de
  todas as páginas.
- manifesto(): "MANIFESTO DE ASSINATURA ELETRÔNICA E TRILHA DE AUDITORIA" com QR Code.
"""
import hashlib
import io
from datetime import datetime

import qrcode
from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfgen import canvas

from .config import LOJA, PARQUE
from .util import fmt_cpf_cnpj, fmt_data, fmt_moeda

LARG, ALT = A4
MARGEM = 20 * mm
BORDO = colors.HexColor("#560710")
CINZA = colors.HexColor("#555555")


def sha256(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()


def _juntar(*pdfs: bytes) -> bytes:
    escritor = PdfWriter()
    for pdf in pdfs:
        if pdf:
            for pagina in PdfReader(io.BytesIO(pdf)).pages:
                escritor.add_page(pagina)
    saida = io.BytesIO()
    escritor.write(saida)
    return saida.getvalue()


def _paragrafo(c, texto, x, y, largura, fonte="Helvetica", tamanho=10, entrelinha=14):
    """Escreve texto quebrando linhas; devolve o y seguinte."""
    for linha in simpleSplit(texto, fonte, tamanho, largura):
        c.setFont(fonte, tamanho)
        c.drawString(x, y, linha)
        y -= entrelinha
    return y


def _cabecalho(c, titulo):
    c.setFillColor(BORDO)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(MARGEM, ALT - 14 * mm, f"{LOJA['titulo']} {LOJA['nome']}")
    c.setFillColor(CINZA)
    c.setFont("Helvetica", 8)
    c.drawString(MARGEM, ALT - 18 * mm, f"CNPJ {LOJA['cnpj']} · {LOJA['endereco']} · {LOJA['cidade']}")
    c.setStrokeColor(BORDO)
    c.line(MARGEM, ALT - 20 * mm, LARG - MARGEM, ALT - 20 * mm)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(LARG / 2, ALT - 30 * mm, titulo)


# ---------------------------------------------------------------- contrato (modelo de teste)

def montar_contrato(contrato: dict, contratante: dict, evento: dict) -> tuple[bytes, dict]:
    """Gera o contrato. Devolve (pdf, campo) — `campo` é onde a rubrica do contratante entra:
    {"pagina": índice 0-based, "x", "y", "largura", "altura"} em pontos."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"Contrato de locação {contrato['codigo_verificador']}")
    _cabecalho(c, "CONTRATO DE LOCAÇÃO DE ESPAÇO PARA EVENTO")
    c.setFillColor(colors.HexColor("#a3122a"))
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(LARG / 2, ALT - 36 * mm, "MODELO DE TESTE — o texto definitivo do contrato será incluído depois")
    c.setFillColor(colors.black)
    largura = LARG - 2 * MARGEM
    y = ALT - 48 * mm

    endereco = ", ".join(x for x in [contratante.get("logradouro"), contratante.get("numero"),
                                     contratante.get("complemento"), contratante.get("bairro")] if x)
    cidade = " / ".join(x for x in [contratante.get("cidade"), contratante.get("estado")] if x)
    partes = [
        f"LOCADORA: {LOJA['titulo']} {LOJA['nome']}, CNPJ {LOJA['cnpj']}, com sede na {LOJA['endereco']}, "
        f"{LOJA['cidade']}.",
        f"LOCATÁRIO(A): {contratante.get('nome') or contrato['contratante_nome']}, "
        f"{contratante.get('nacionalidade') or '—'}, {contratante.get('estado_civil') or '—'}, "
        f"{contratante.get('profissao') or '—'}, CPF/CNPJ {fmt_cpf_cnpj(contrato['contratante_cpf_cnpj'])}, "
        f"RG {contratante.get('rg') or '—'}, residente em {endereco or '—'}"
        f"{', ' + cidade if cidade else ''}{', CEP ' + contratante['cep'] if contratante.get('cep') else ''}, "
        f"telefone {contratante.get('telefone') or '—'}, e-mail {contrato['contratante_email']}.",
        f"OBJETO: locação da área de eventos do {PARQUE['nome']} ({PARQUE['descricao']})"
        f"{', INCLUINDO a piscina' if evento.get('inclui_piscina') else ', SEM uso da piscina'}.",
        f"EVENTO: {evento.get('tipo_evento') or '—'}, em {fmt_data(evento.get('data'))}, "
        f"das {evento.get('hora_inicio') or '—'} às {evento.get('hora_fim') or '—'}.",
        f"VALOR: {fmt_moeda(evento.get('valor_total'))}. PAGAMENTO: {evento.get('forma_pagamento') or '—'}.",
    ]
    if evento.get("observacoes"):
        partes.append(f"OBSERVAÇÕES: {evento['observacoes']}")
    partes.append("As cláusulas deste modelo de teste não têm valor contratual. Este documento serve apenas "
                  "para testar o fluxo de vistoria, leitura e assinatura eletrônica.")
    for texto in partes:
        y = _paragrafo(c, texto, MARGEM, y, largura) - 8

    # assinaturas
    y = min(y - 20, 95 * mm)
    c.setFont("Helvetica", 10)
    c.drawString(MARGEM, y + 40, f"{LOJA['cidade']}, {datetime.now().strftime('%d/%m/%Y')}.")
    col = (largura - 20 * mm) / 2
    linha_y = y - 25 * mm
    c.line(MARGEM, linha_y, MARGEM + col, linha_y)
    c.line(MARGEM + col + 20 * mm, linha_y, LARG - MARGEM, linha_y)
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(MARGEM + col / 2, linha_y - 12, "LOCADORA")
    c.drawCentredString(LARG - MARGEM - col / 2, linha_y - 12, "LOCATÁRIO(A)")
    c.setFont("Helvetica", 8)
    c.drawCentredString(MARGEM + col / 2, linha_y - 23, f"{LOJA['nome']} — assinatura do locador no modelo")
    c.drawCentredString(LARG - MARGEM - col / 2, linha_y - 23, contrato["contratante_nome"][:60])
    campo = {"pagina": 0, "x": LARG - MARGEM - col, "y": linha_y + 2, "largura": col, "altura": 22 * mm}
    c.showPage()
    c.save()
    return buf.getvalue(), campo


# ---------------------------------------------------------------- Anexo I: fotos da vistoria

def anexo_vistoria(fotos: list[bytes], codigo: str) -> bytes:
    """Grade com 2 fotos por linha, 3 linhas por página, sem legendas."""
    if not fotos:
        return b""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    largura = LARG - 2 * MARGEM
    espaco = 6 * mm
    cel_l = (largura - espaco) / 2
    cel_a = 72 * mm
    por_pagina = 6
    for inicio in range(0, len(fotos), por_pagina):
        _cabecalho(c, "ANEXO I – REGISTRO FOTOGRÁFICO DE VISTORIA")
        c.setFont("Helvetica", 8)
        c.setFillColor(CINZA)
        c.drawCentredString(LARG / 2, ALT - 36 * mm, f"Contrato {codigo} · vistoria prévia das condições do espaço")
        c.setFillColor(colors.black)
        topo = ALT - 42 * mm
        for i, foto in enumerate(fotos[inicio:inicio + por_pagina]):
            linha, coluna = divmod(i, 2)
            x = MARGEM + coluna * (cel_l + espaco)
            y = topo - (linha + 1) * cel_a - linha * espaco
            img = ImageReader(io.BytesIO(foto))
            iw, ih = img.getSize()
            escala = min(cel_l / iw, cel_a / ih)
            w, h = iw * escala, ih * escala
            c.drawImage(img, x + (cel_l - w) / 2, y + (cel_a - h) / 2, w, h)
            c.setStrokeColor(colors.HexColor("#dddddd"))
            c.rect(x, y, cel_l, cel_a)
        c.showPage()
    c.save()
    return buf.getvalue()


def pdf_para_leitura(contrato: dict, contratante: dict, evento: dict, fotos: list[bytes]) -> tuple[bytes, dict]:
    """Contrato + Anexo I (se houver fotos): é o PDF que o contratante lê antes de assinar."""
    pdf, campo = montar_contrato(contrato, contratante, evento)
    return _juntar(pdf, anexo_vistoria(fotos, contrato["codigo_verificador"])), campo


# ---------------------------------------------------------------- rubrica e manifesto

def carimbar_rubrica(pdf: bytes, rubrica_png: bytes, campo: dict, paginas_extra: int = 0) -> bytes:
    """`paginas_extra`: páginas que virão depois (o manifesto), para o "pág. x/y" do rodapé."""
    leitor = PdfReader(io.BytesIO(pdf))
    total = len(leitor.pages) + paginas_extra
    escritor = PdfWriter()
    for n, pagina in enumerate(leitor.pages):
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        img = ImageReader(io.BytesIO(rubrica_png))
        iw, ih = img.getSize()
        if n == campo["pagina"]:
            escala = min(campo["largura"] / iw, campo["altura"] / ih)
            w, h = iw * escala, ih * escala
            c.drawImage(img, campo["x"] + (campo["largura"] - w) / 2, campo["y"], w, h, mask="auto")
        # rubrica no rodapé de todas as páginas
        escala = min(28 * mm / iw, 11 * mm / ih)
        c.drawImage(img, LARG - MARGEM - iw * escala, 8 * mm, iw * escala, ih * escala, mask="auto")
        c.setFont("Helvetica", 6.5)
        c.setFillColor(CINZA)
        c.drawRightString(LARG - MARGEM - 30 * mm, 11 * mm, f"Rubrica do(a) locatário(a) · pág. {n + 1}/{total}")
        c.save()
        pagina.merge_page(PdfReader(buf).pages[0])
        escritor.add_page(pagina)
    saida = io.BytesIO()
    escritor.write(saida)
    return saida.getvalue()


def _qr(url: str) -> ImageReader:
    img = qrcode.make(url, box_size=6, border=1)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return ImageReader(buf)


def manifesto(d: dict, selfie_jpeg: bytes, rubrica_png: bytes) -> bytes:
    """Página de manifesto. `d`: codigo, url_validacao, contratante_nome, contratante_doc,
    contratante_email, evento_resumo, hash_pre, ip, user_agent, geolocalizacao, timestamp_utc, paginas."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    _cabecalho(c, "MANIFESTO DE ASSINATURA ELETRÔNICA E TRILHA DE AUDITORIA")
    largura = LARG - 2 * MARGEM
    y = ALT - 42 * mm
    y = _paragrafo(c, "Este manifesto integra o documento e registra as evidências coletadas no ato da assinatura "
                      "eletrônica pelo(a) locatário(a), por meio do sistema da Loja.", MARGEM, y, largura, tamanho=9) - 6

    linhas = [
        ("Código verificador", d["codigo"]),
        ("Documento", f"Contrato de locação — {d['evento_resumo']}"),
        ("Locadora", f"{LOJA['titulo']} {LOJA['nome']} · CNPJ {LOJA['cnpj']}"),
        ("Signatário(a)", f"{d['contratante_nome']} · CPF/CNPJ {d['contratante_doc']}"),
        ("E-mail do signatário", d["contratante_email"]),
        ("Data e hora (UTC, servidor)", d["timestamp_utc"]),
        ("Endereço IP", d["ip"] or "—"),
        ("Dispositivo (User-Agent)", d["user_agent"] or "—"),
        ("Geolocalização", d["geolocalizacao"] or "não autorizada pelo signatário"),
        ("Páginas do documento assinado", str(d["paginas"])),
        ("SHA-256 pré-assinatura", d["hash_pre"]),
    ]
    for rotulo, valor in linhas:
        c.setFont("Helvetica-Bold", 8.5)
        c.setFillColor(BORDO)
        c.drawString(MARGEM, y, rotulo)
        c.setFillColor(colors.black)
        if rotulo.startswith("SHA-256"):  # hash sem espaços: fonte monoespaçada menor, cabe numa linha
            c.setFont("Courier", 7.2)
            c.drawString(MARGEM + 52 * mm, y, str(valor))
            y -= 15
            continue
        y = _paragrafo(c, str(valor), MARGEM + 52 * mm, y, largura - 52 * mm, tamanho=8.5, entrelinha=11) - 4

    # selfie, rubrica e QR Code
    y -= 4
    caixa = 45 * mm
    c.setFont("Helvetica-Bold", 8.5)
    c.setFillColor(BORDO)
    c.drawString(MARGEM, y, "Foto do signatário no ato")
    c.drawString(MARGEM + caixa + 10 * mm, y, "Assinatura manuscrita")
    c.drawString(LARG - MARGEM - caixa, y, "Validação pública")
    c.setFillColor(colors.black)
    base = y - 4 - caixa
    for img_bytes, x, mascara in ((selfie_jpeg, MARGEM, None), (rubrica_png, MARGEM + caixa + 10 * mm, "auto")):
        img = ImageReader(io.BytesIO(img_bytes))
        iw, ih = img.getSize()
        larg_caixa = caixa if x == MARGEM else LARG - 2 * MARGEM - 2 * caixa - 20 * mm
        escala = min(larg_caixa / iw, caixa / ih)
        c.drawImage(img, x, base + (caixa - ih * escala), iw * escala, ih * escala, mask=mascara)
        c.setStrokeColor(colors.HexColor("#dddddd"))
        c.rect(x, base, larg_caixa, caixa)
    c.drawImage(_qr(d["url_validacao"]), LARG - MARGEM - caixa, base, caixa, caixa)
    y = base - 8
    c.setFont("Helvetica", 7.5)
    c.setFillColor(CINZA)
    y = _paragrafo(c, f"Confira a autenticidade em {d['url_validacao']} ou leia o QR Code. O SHA-256 do arquivo final "
                      "(com este manifesto) é registrado no sistema no momento da assinatura e pode ser conferido na "
                      "página de validação, enviando o próprio PDF.", MARGEM, y, largura, tamanho=7.5, entrelinha=10)
    c.showPage()
    c.save()
    return buf.getvalue()


def pdf_assinado(pdf_leitura: bytes, campo: dict, rubrica_png: bytes, selfie_jpeg: bytes, dados: dict) -> bytes:
    carimbado = carimbar_rubrica(pdf_leitura, rubrica_png, campo, paginas_extra=1)
    dados = dict(dados, paginas=len(PdfReader(io.BytesIO(carimbado)).pages) + 1)
    return _juntar(carimbado, manifesto(dados, selfie_jpeg, rubrica_png))
