"""PDF dos contratos de locação do Parque das Acácias (ReportLab + pypdf).

- montar_contrato(): o contrato em si, com o texto do modelo da Loja
  (secretaria/MODELO DE CONTRATO PARQUE DAS ACÁCIAS.docx) e os dados do cadastro.
- anexo_vistoria(): "ANEXO I – REGISTRO FOTOGRÁFICO DE VISTORIA" (2 fotos por linha).
- carimbar_rubrica(): estampa a rubrica do contratante no campo de assinatura e no rodapé de
  todas as páginas.
- manifesto(): "MANIFESTO DE ASSINATURA ELETRÔNICA E TRILHA DE AUDITORIA" com QR Code.
"""
import hashlib
import io
from xml.sax.saxutils import escape

import qrcode
from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfgen import canvas
from reportlab.platypus import Flowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer

from .config import LOJA, PARQUE
from .util import fmt_cep, fmt_cpf_cnpj, fmt_moeda, fmt_tel, reais_por_extenso

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


# ---------------------------------------------------------------- contrato (modelo da Loja)
# Texto de secretaria/MODELO DE CONTRATO PARQUE DAS ACÁCIAS.docx. Os trechos entre colchetes do modelo
# são preenchidos com os dados do contrato; os condicionais (vistoria, piscina, Pix) seguem o modelo.

MESES_EXTENSO = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro",
                 "outubro", "novembro", "dezembro"]
FORMAS_NA_FRASE = {"Pix": "Pix", "Dinheiro": "dinheiro", "Cartão de crédito": "cartão de crédito",
                   "Abatimento em crédito": "abatimento em crédito"}

_CORPO = ParagraphStyle("corpo", fontName="Helvetica", fontSize=10, leading=14, alignment=TA_JUSTIFY, spaceAfter=6)
_ITEM = ParagraphStyle("item", parent=_CORPO, leftIndent=8 * mm)
_CLAUSULA = ParagraphStyle("clausula", parent=_CORPO, fontName="Helvetica-Bold", alignment=TA_LEFT,
                           spaceBefore=8, spaceAfter=4, keepWithNext=1)
_TITULO = ParagraphStyle("titulo", fontName="Helvetica-Bold", fontSize=13, leading=16, alignment=TA_CENTER,
                         spaceAfter=12)


def _e(valor) -> str:
    """Texto do contrato vindo do cadastro, protegido para o ReportLab."""
    return escape(str(valor)) if valor not in (None, "") else "—"


def _data_extenso(iso: str | None) -> str:
    if not iso:
        return "—"
    a, m, d = iso.split("-")
    return f"{int(d):02d} de {MESES_EXTENSO[int(m) - 1]} de {a}"


def _hora(h: str | None) -> str:
    return h.replace(":", "h") if h else "—"


def _lista(itens: list[str]) -> str:
    return itens[0] if len(itens) == 1 else ", ".join(itens[:-1]) + " e " + itens[-1]


def _qualificacao_locadora(contrato: dict) -> str:
    loc = contrato.get("locadora") or {}
    texto = (f"<b>LOCADORA/CONTRATADA:</b> {_e((LOJA['titulo'] + ' ' + LOJA['nome']).upper())}, pessoa jurídica de "
             f"direito privado inscrita no CNPJ sob o nº {LOJA['cnpj']}, com sede na {_e(PARQUE['sede_locadora'])}")
    if loc.get("nome"):
        texto += (f", neste ato representada por seu representante legal, o Venerável Mestre {_e(loc['nome'])}, "
                  f"brasileiro, CPF nº {_e(fmt_cpf_cnpj(loc.get('cpf')))}, residente e domiciliado na "
                  f"{_e(loc.get('endereco'))}")
    return texto + "; e, de outro lado:"


def _qualificacao_locataria(contrato: dict, q: dict) -> str:
    """Pessoa física: nacionalidade, estado civil, profissão, CPF, RG e residência.
    Pessoa jurídica: razão social, CNPJ, sede e o representante (com a qualificação dele)."""
    endereco = ", ".join(x for x in [q.get("logradouro"), q.get("numero"), q.get("complemento"), q.get("bairro")] if x)
    cidade = "/".join(x for x in [q.get("cidade"), q.get("estado")] if x)
    local = (f"{endereco or '—'}{', ' + cidade if cidade else ''}"
             f"{', CEP ' + fmt_cep(q['cep']) if q.get('cep') else ''}")
    contato = f"telefone {_e(fmt_tel(q.get('telefone')))}, e-mail {_e(contrato['contratante_email'])}"
    nome = q.get("nome") or contrato["contratante_nome"]
    doc = fmt_cpf_cnpj(contrato["contratante_cpf_cnpj"])
    if q.get("tipo_pessoa") == "PJ":
        r = q.get("representante") or {}
        return (f"<b>LOCATÁRIA/CONTRATANTE:</b> {_e(nome)}, pessoa jurídica de direito privado inscrita no CNPJ sob "
                f"o nº {doc}, com sede na {_e(local)}, {contato}, neste ato representada por {_e(r.get('nome'))}, "
                f"{_e(r.get('cargo'))}, {_e(r.get('nacionalidade'))}, {_e(r.get('estado_civil'))}, "
                f"{_e(r.get('profissao'))}, CPF nº {_e(fmt_cpf_cnpj(r.get('cpf')))}, RG nº {_e(r.get('rg'))};")
    return (f"<b>LOCATÁRIA/CONTRATANTE:</b> {_e(nome)}, {_e(q.get('nacionalidade'))}, {_e(q.get('estado_civil'))}, "
            f"{_e(q.get('profissao'))}, CPF nº {doc}, RG nº {_e(q.get('rg'))}, residente e domiciliado(a) na "
            f"{_e(local)}, {contato};")


def _clausulas(contrato: dict, contratante: dict, evento: dict, com_vistoria: bool) -> list:
    piscina = bool(evento.get("inclui_piscina"))
    valor = evento.get("valor_total")
    formas = evento.get("formas_pagamento") or []
    if formas:
        pagamento = f"O pagamento será efetuado por meio de {_lista([FORMAS_NA_FRASE.get(f, f) for f in formas])}"
        if "Pix" in formas:
            pagamento += f", para a chave PIX CNPJ {LOJA['cnpj']}, de titularidade da LOCADORA"
        if evento.get("condicoes_pagamento"):
            pagamento += f", observando-se a seguinte condição: {_e(evento['condicoes_pagamento'])}"
        pagamento += "."
    else:  # contratos antigos: pagamento em texto livre
        pagamento = f"O pagamento será efetuado da seguinte forma: {_e(evento.get('forma_pagamento'))}."
    espacos = ("Salão de festas coberta com estrutura de palco; banheiro masculino e feminino; cozinha de apoio e "
               "churrasqueira; área de estacionamento"
               + ("; área da piscina e seu entorno imediato (valor com piscina inclusa)" if piscina else "") + ".")
    P, C, I = (lambda t: Paragraph(t, _CORPO)), (lambda t: Paragraph(t, _CLAUSULA)), (lambda t: Paragraph(t, _ITEM))
    itens = [
        Paragraph("CONTRATO DE LOCAÇÃO", _TITULO),
        P("Pelo presente instrumento particular de locação de espaço físico por diária, de um lado:"),
        P(_qualificacao_locadora(contrato)),
        P(_qualificacao_locataria(contrato, contratante)),
        P("têm entre si justo e contratado o presente Contrato de Locação de Espaço por Diária, que se regerá pelas "
          "cláusulas e condições a seguir expostas e pela legislação brasileira aplicável."),

        C("CLÁUSULA PRIMEIRA – DA NATUREZA JURÍDICA E FUNDAMENTAÇÃO LEGAL"),
        P("<b>1.1.</b> O presente contrato tem natureza de locação de espaço físico não residencial por curtíssima "
          "duração (diária para realização de evento), sendo regido precipuamente pelas disposições do Código Civil "
          "Brasileiro, em especial pelos arts. 565 a 578, arts. 421 a 480, arts. 408 a 416 e arts. 186, 187 e 927, "
          "aplicando-se a Lei nº 8.245/1991 (Lei do Inquilinato) apenas de forma subsidiária, no que não conflitar "
          "com a natureza temporária e eventual desta contratação."),

        C("CLÁUSULA SEGUNDA – DO OBJETO E DOS ESPAÇOS INCLUSOS NA LOCAÇÃO"),
        P(f"<b>2.1.</b> O objeto do presente contrato é a locação temporária, por diária, do espaço físico denominado "
          f"{_e(PARQUE['espaco_contrato'])}, situado na {_e(PARQUE['endereco_espaco'])}, destinado exclusivamente à "
          f"realização do evento {_e(evento.get('tipo_evento'))}."),
        P("<b>2.2.</b> <b>Espaços inclusos no valor da locação:</b> Ficam expressamente compreendidos no direito de uso "
          "pela LOCATÁRIA e seus convidados/prestadores de serviço, durante o período contratado"
          f"{' e em conformidade com a vistoria anexa' if com_vistoria else ''}, os seguintes ambientes e "
          f"estruturas: {espacos}"),
        P("<b>2.3.</b> <b>Espaços excluídos:</b> Não estão abrangidos nesta locação áreas administrativas, templos, "
          "depósitos fechados, salas privativas da LOCADORA ou quaisquer dependências não listadas na subcláusula "
          "2.2, cujo acesso permanece vedado durante o evento."),

        C("CLÁUSULA TERCEIRA – DA DATA, PRAZO E HORÁRIOS DA DIÁRIA"),
        P(f"<b>3.1.</b> A locação vigorará exclusivamente para o dia {_data_extenso(evento.get('data'))}, "
          f"compreendendo o período das {_hora(evento.get('hora_inicio'))} até as {_hora(evento.get('hora_fim'))} "
          "do mesmo dia."),
        P("<b>3.2.</b> O acesso às dependências do salão por parte de decoradores, equipe de buffet, sonorização e "
          "demais profissionais contratados pela LOCATÁRIA será liberado a partir das 07h00 da data do evento."),
        P("<b>3.3.</b> A locação encerra-se de pleno direito ao término do horário pactuado na subcláusula 3.1, "
          "independentemente de notificação judicial ou extrajudicial, devendo o imóvel ser desocupado de pessoas, "
          "equipamentos e itens de terceiros até o horário limite, admitida tolerância máxima de "
          f"{int(evento.get('tolerancia_min') or 30)} minutos exclusivamente para desmontagem e retirada de "
          "materiais, salvo ajuste diverso por escrito."),

        C("CLÁUSULA QUARTA – DO VALOR E DAS FORMAS DE PAGAMENTO"),
        P("<b>4.1.</b> Pela locação do espaço físico e demais áreas descritas na Cláusula Segunda, a LOCATÁRIA pagará à "
          f"LOCADORA o valor total de R$ {fmt_moeda(valor, simbolo=False) or '—'} ({reais_por_extenso(valor)})."),
        P(f"<b>4.2.</b> {pagamento}"),
        P("<b>4.3.</b> O(s) comprovante(s) de pagamento(s) servirão como recibo e prova de quitação dos valores pagos, "
          "devendo ser enviado ao contato oficial da LOCADORA. A confirmação da reserva e a entrega das chaves/acesso "
          "ao imóvel ficam condicionadas à quitação integral do valor ajustado antes do início da diária."),

        C("CLÁUSULA QUINTA – DAS CONDIÇÕES DE RECEBIMENTO, USO E DEVOLUÇÃO DO IMÓVEL"),
        P("<b>5.1.</b> <b>Recebimento e Vistoria Inicial:</b> A LOCADORA obriga-se a entregar o imóvel na data e "
          "horário pactuados em perfeitas condições de uso, limpeza, segurança, funcionamento elétrico e hidráulico"
          + (", bem como com a piscina devidamente limpa e tratada" if piscina else "")
          + ", nos termos do art. 566, I, do Código Civil. No ato da assinatura do contrato, as partes poderão firmar "
          "registro fotográfico compartilhado de vistoria, atestando o estado dos bens e instalações."),
        P("<b>5.2.</b> <b>Regras de Uso e Execução Musical:</b> A LOCATÁRIA compromete-se a utilizar o imóvel "
          "exclusivamente para a finalidade ajustada (art. 569, I, do Código Civil). Em caso de execução musical "
          "mecânica e/ou ao vivo, deverão ser rigorosamente observados os limites de volume sonoro e horários fixados "
          "pela legislação municipal vigente de Rio Branco/AC, pelas normas técnicas da ABNT (NBR 10.151) e pelo "
          "art. 42 da Lei das Contravenções Penais, bem como a eventual regularidade de taxas de direitos autorais "
          "(ECAD), se aplicáveis ao tipo de evento."),
        P("<b>5.3.</b> <b>Limpeza Pós-Evento:</b> Fica sob responsabilidade da LOCATÁRIA a limpeza pós-evento do espaço "
          "utilizado, devendo o local ser entregue livre de resíduos sólidos, restos de alimentos, bebidas e "
          "materiais de decoração, acondicionados nos recipientes adequados (salvo se contratada taxa adicional de "
          "limpeza junto à LOCADORA)."),
        P("<b>5.4.</b> <b>Devolução e Vistoria Final:</b> Ao término da locação, o imóvel deverá ser restituído no "
          "mesmo estado em que foi recebido, ressalvado o desgaste natural decorrente do uso regular (art. 569, IV, "
          "do Código Civil). Eventuais danos materiais ou avarias causados diretamente às instalações da LOCADORA "
          "serão apurados mediante registro fotográfico e realizado orçamento idôneo para o ressarcimento por parte "
          "da LOCATÁRIA."),

        C("CLÁUSULA SEXTA – DA RESPONSABILIDADE CIVIL E ISENÇÃO POR ACIDENTES A TERCEIROS"),
        P("<b>6.1.</b> <b>Isenção da LOCADORA por Acidentes a Terceiros por Mau Uso:</b> A LOCADORA fica expressamente "
          "isenta de responsabilidade civil, indenizatória ou regressiva por acidentes, lesões corporais, danos "
          "morais ou materiais sofridos por terceiros ou convidados em decorrência do mau uso individual das "
          "dependências, da área da piscina ou dos equipamentos do espaço por culpa exclusiva da própria vítima ou "
          "de terceiros (art. 927 e excludentes de nexo causal do Código Civil)."),

        C("CLÁUSULA SÉTIMA – DAS MULTAS POR DESCUMPRIMENTO CONTRATUAL"),
        P("<b>7.1.</b> <b>Multa por Descumprimento de Obrigações:</b> O descumprimento, por qualquer das partes, de "
          "quaisquer obrigações estabelecidas neste contrato sujeitará a parte infratora ao pagamento de multa não "
          "compensatória equivalente a 10% (dez por cento) sobre o valor total do contrato, nos termos dos arts. 408 "
          "a 416 do Código Civil, sem prejuízo da exigência do cumprimento da obrigação e de eventual indenização por "
          "perdas e danos comprovados."),
        P("<b>7.2.</b> <b>Atraso no Pagamento:</b> O atraso na quitação de qualquer parcela ou valor devido sujeitará a "
          "parte devedora a multa moratória de 5% (cinco por cento) sobre o valor em atraso, acrescida de juros de "
          "mora de 1% (um por cento) ao mês (pro rata die) e correção monetária pelo IPCA/IBGE até a data do efetivo "
          "pagamento."),
        P("<b>7.3.</b> <b>Excesso de Horário na Devolução:</b> Ultrapassado o horário limite de desocupação previsto na "
          "Cláusula Terceira (incluída a tolerância), a LOCATÁRIA pagará à LOCADORA taxa adicional equivalente a 10% "
          "do valor da diária — ou R$ 150,00 por hora excedente ou fração superior a 15 (quinze) minutos."),
        P("<b>7.4.</b> <b>Descumprimento da Limpeza Pós-Evento:</b> Caso o espaço seja devolvido sem a limpeza básica "
          "pactuada na subcláusula 5.3, incidirá taxa compensatória de limpeza no valor fixo de R$ 200,00 (duzentos "
          "reais), mediante registro fotográfico comprovando o estado de entrega."),

        C("CLÁUSULA OITAVA – DA RESCISÃO CONTRATUAL E RESPECTIVA MULTA"),
        P("<b>8.1.</b> <b>Rescisão Imotivada pela LOCATÁRIA:</b> A desistência ou cancelamento imotivado do evento pela "
          "LOCATÁRIA deverá ser comunicado formalmente (por escrito ou meio eletrônico com confirmação de "
          "recebimento), aplicando-se multa rescisória proporcional ao prazo de antecedência em relação à data do "
          "evento:"),
        I("a) Comunicação com antecedência igual ou superior a 30 (trinta) dias: isenção de multa, com devolução "
          "integral do saldo pago em até 5 dias úteis;"),
        I("b) Comunicação entre 15 (quinze) e 29 (vinte e nove) dias de antecedência: multa rescisória de 25% (vinte e "
          "cinco por cento) sobre o valor total do contrato;"),
        I("c) Comunicação com antecedência inferior a 15 (quinze) dias ou não comparecimento (no-show): multa "
          "rescisória de 50% (cinquenta por cento) sobre o valor total do contrato."),
        P("<b>8.2.</b> <b>Rescisão Imotivada pela LOCADORA:</b> Caso a LOCADORA rescinda unilateralmente o contrato sem "
          "justa causa, ou deixe de disponibilizar o imóvel na data pactuada em condições de uso, obrigar-se-á à "
          "restituição imediata e integral de todos os valores recebidos, sem prejuízo de eventual perdas e danos "
          "comprovados."),
        P("<b>8.3.</b> <b>Caso Fortuito ou Força Maior:</b> Nenhuma multa rescisória será devida por qualquer das partes "
          "na hipótese de impossibilidade de realização do evento por caso fortuito, força maior ou determinação do "
          "Poder Público (art. 393 do Código Civil), devendo as partes priorizar o reagendamento da data em comum "
          "acordo, no prazo de até 90 dias, ou, sendo inviável, a restituição integral dos valores pagos sem "
          "penalidades."),

        C("CLÁUSULA NONA – DA ASSINATURA ELETRÔNICA E DISPENSA DE RECONHECIMENTO EM CARTÓRIO"),
        P("<b>9.1.</b> As partes reconhecem expressamente a plena validade jurídica, autenticidade, integridade e força "
          "vinculante da assinatura eletrônica aposta neste contrato — seja ela qualificada (certificado digital "
          "ICP-Brasil), avançada ou simples realizada por meio de plataforma de assinatura digital/eletrônica — nos "
          "termos do art. 10, §§ 1º e 2º, da Medida Provisória nº 2.200-2/2001 e da Lei nº 14.063/2020."),
        P("<b>9.2.</b> As partes dispensam expressamente o reconhecimento de firma em cartório, bem como a impressão de "
          "vias físicas, reconhecendo o documento eletrônico assinado como título executivo extrajudicial plenamente "
          "exigível, dispensada inclusive a assinatura de testemunhas quando a integridade do documento for "
          "conferida por provedor de assinatura eletrônica, conforme disposto no art. 784, § 4º, do Código de "
          "Processo Civil (incluído pela Lei nº 14.620/2023)."),

        C("CLÁUSULA DÉCIMA – DAS DISPOSIÇÕES GERAIS E DO FORO"),
        P("<b>10.1.</b> A eventual tolerância de uma das partes quanto ao descumprimento de qualquer cláusula pela outra "
          "constituirá mera liberalidade, não implicando novação, renúncia de direitos ou alteração contratual."),
        P("<b>10.2.</b> Qualquer aditamento ou alteração a este instrumento somente terá validade se formalizado por "
          "escrito e assinado por ambas as partes, inclusive por meio eletrônico."),
        P(f"<b>10.3.</b> Para dirimir quaisquer controvérsias oriundas do presente contrato, as partes elegem o Foro da "
          f"Comarca de {_e(PARQUE['foro'])}, com renúncia expressa a qualquer outro, por mais privilegiado que seja."),
    ]
    if evento.get("observacoes"):
        itens.append(P(f"<b>10.4.</b> <b>Observações ajustadas entre as partes:</b> {_e(evento['observacoes'])}"))
    itens.append(P("E, por estarem justas e contratadas, as partes assinam o presente instrumento em meio eletrônico, "
                   "para que produza todos os efeitos legais."))
    return itens


class _Assinaturas(Flowable):
    """Bloco de assinaturas: LOCADORA à esquerda (assinatura padronizada do Venerável) e LOCATÁRIA à direita.
    Ao ser desenhado, anota em `destino` onde a rubrica do contratante deve ser estampada."""

    def __init__(self, largura, esquerda, direita, imagem_esquerda, destino):
        super().__init__()
        self.largura, self.esquerda, self.direita = largura, esquerda, direita
        self.imagem_esquerda, self.destino = imagem_esquerda, destino

    def wrap(self, *_):
        return self.largura, 50 * mm

    def draw(self):
        c = self.canv
        col = (self.largura - 20 * mm) / 2
        linha = 20 * mm
        c.setStrokeColor(colors.black)
        c.line(0, linha, col, linha)
        c.line(col + 20 * mm, linha, self.largura, linha)
        if self.imagem_esquerda:
            img = ImageReader(io.BytesIO(self.imagem_esquerda))
            iw, ih = img.getSize()
            escala = min(col / iw, 22 * mm / ih)
            c.drawImage(img, (col - iw * escala) / 2, linha + 2, iw * escala, ih * escala, mask="auto")
        for x, linhas in ((col / 2, self.esquerda), (col + 20 * mm + col / 2, self.direita)):
            for n, texto in enumerate(linhas):
                c.setFont("Helvetica-Bold" if n == 0 else "Helvetica", 9 if n == 0 else 8)
                c.drawCentredString(x, linha - 12 - n * 10, texto[:70])
        x_abs, y_abs = c.absolutePosition(col + 20 * mm, linha)
        self.destino.update({"pagina": c.getPageNumber() - 1, "x": x_abs, "y": y_abs + 2,
                             "largura": col, "altura": 22 * mm})


def montar_contrato(contrato: dict, contratante: dict, evento: dict, assinatura_locadora: bytes | None = None,
                    com_vistoria: bool = False) -> tuple[bytes, dict]:
    """Gera o contrato. Devolve (pdf, campo) — `campo` é onde a rubrica do contratante entra:
    {"pagina": índice 0-based, "x", "y", "largura", "altura"} em pontos."""
    buf = io.BytesIO()
    codigo = contrato["codigo_verificador"]

    def moldura(c, _doc):
        c.saveState()
        c.setFillColor(BORDO)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(MARGEM, ALT - 14 * mm, f"{LOJA['titulo']} {LOJA['nome']}")
        c.setFillColor(CINZA)
        c.setFont("Helvetica", 8)
        c.drawString(MARGEM, ALT - 18 * mm, f"CNPJ {LOJA['cnpj']} · {PARQUE['espaco_contrato']}")
        c.setStrokeColor(BORDO)
        c.line(MARGEM, ALT - 20 * mm, LARG - MARGEM, ALT - 20 * mm)
        c.setFont("Helvetica", 7)
        c.drawCentredString(LARG / 2, 4.5 * mm, f"Contrato {codigo}")
        c.restoreState()

    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=MARGEM, rightMargin=MARGEM, topMargin=28 * mm,
                            bottomMargin=24 * mm, title=f"Contrato de locação {codigo}",
                            author=f"{LOJA['titulo']} {LOJA['nome']}")
    loc = contrato.get("locadora") or {}
    rep = contratante.get("representante") or {}
    pj = contratante.get("tipo_pessoa") == "PJ"
    campo: dict = {}
    fecho = [
        Paragraph(f"{_e(PARQUE['cidade_assinatura'])}, na data da assinatura eletrônica registrada no Manifesto de "
                  "Assinatura anexo.", _CORPO),
        Spacer(1, 4 * mm),
        _Assinaturas(LARG - 2 * MARGEM,
                     ["LOCADORA", f"{LOJA['titulo']} {LOJA['nome']}"]
                     + ([f"{loc['nome']} — Venerável Mestre"] if loc.get("nome") else []),
                     ["LOCATÁRIA" if pj else "LOCATÁRIO(A)", contrato["contratante_nome"]]
                     + ([f"p/ {rep['nome']}"] if pj and rep.get("nome") else []),
                     assinatura_locadora, campo),
        Paragraph("Assinatura eletrônica conforme o Manifesto de Assinatura anexo.",
                  ParagraphStyle("nota", parent=_CORPO, fontSize=8, textColor=CINZA, alignment=TA_CENTER)),
    ]
    doc.build(_clausulas(contrato, contratante, evento, com_vistoria) + [KeepTogether(fecho)],
              onFirstPage=moldura, onLaterPages=moldura)
    return buf.getvalue(), campo


# ---------------------------------------------------------------- Anexo I: fotos da vistoria

def anexo_vistoria(fotos: list, codigo: str, subtitulo: str = "vistoria prévia das condições do espaço") -> bytes:
    """Grade com 2 fotos por linha, 3 linhas por página. Cada item é a foto (bytes) ou
    (foto, legenda); a legenda é o tipo da foto (Salão, Banheiros…) ou "Outras fotos"."""
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
        c.drawCentredString(LARG / 2, ALT - 36 * mm, f"Contrato {codigo} · {subtitulo}")
        c.setFillColor(colors.black)
        topo = ALT - 42 * mm
        for i, item in enumerate(fotos[inicio:inicio + por_pagina]):
            foto, legenda = item if isinstance(item, tuple) else (item, None)
            linha, coluna = divmod(i, 2)
            x = MARGEM + coluna * (cel_l + espaco)
            y = topo - (linha + 1) * cel_a - linha * espaco
            faixa = 6 * mm if legenda else 0  # espaço da legenda, embaixo da foto
            img = ImageReader(io.BytesIO(foto))
            iw, ih = img.getSize()
            escala = min(cel_l / iw, (cel_a - faixa) / ih)
            w, h = iw * escala, ih * escala
            c.drawImage(img, x + (cel_l - w) / 2, y + faixa + (cel_a - faixa - h) / 2, w, h)
            if legenda:
                c.setFont("Helvetica-Bold", 8)
                c.setFillColor(BORDO)
                c.drawCentredString(x + cel_l / 2, y + 2 * mm, legenda[:60])
                c.setFillColor(colors.black)
            c.setStrokeColor(colors.HexColor("#dddddd"))
            c.rect(x, y, cel_l, cel_a)
        c.showPage()
    c.save()
    return buf.getvalue()


def pdf_para_leitura(contrato: dict, contratante: dict, evento: dict, fotos: list,
                     assinatura_locadora: bytes | None = None) -> tuple[bytes, dict]:
    """Contrato + Anexo I (se houver fotos): é o PDF que o contratante lê antes de assinar."""
    pdf, campo = montar_contrato(contrato, contratante, evento, assinatura_locadora, com_vistoria=bool(fotos))
    leitura = _juntar(pdf, anexo_vistoria(fotos, contrato["codigo_verificador"]))
    if assinatura_locadora:
        leitura = carimbar_rubrica_locadora(leitura, assinatura_locadora)
    return leitura, campo


# ---------------------------------------------------------------- rubrica e manifesto

def carimbar_rubrica_locadora(pdf: bytes, rubrica_png: bytes) -> bytes:
    """Rubrica da LOCADORA (assinatura padronizada do Venerável) no rodapé esquerdo de todas as páginas do
    contrato e do Anexo I. A do contratante entra no rodapé direito, na assinatura."""
    escritor = PdfWriter()
    img = ImageReader(io.BytesIO(rubrica_png))
    iw, ih = img.getSize()
    escala = min(28 * mm / iw, 11 * mm / ih)
    for pagina in PdfReader(io.BytesIO(pdf)).pages:
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        c.drawImage(img, MARGEM, 8 * mm, iw * escala, ih * escala, mask="auto")
        c.setFont("Helvetica", 6.5)
        c.setFillColor(CINZA)
        c.drawString(MARGEM + 30 * mm, 11 * mm, "Rubrica da locadora")
        c.save()
        pagina.merge_page(PdfReader(buf).pages[0])
        escritor.add_page(pagina)
    saida = io.BytesIO()
    escritor.write(saida)
    return saida.getvalue()


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
        ("Signatário(a)", d.get("signatario") or f"{d['contratante_nome']} · CPF/CNPJ {d['contratante_doc']}"),
        ("E-mail do signatário", d["contratante_email"]),
        ("Data e hora (UTC, servidor)", d["timestamp_utc"]),
        ("Endereço IP", d["ip"] or "—"),
        ("Dispositivo (User-Agent)", d["user_agent"] or "—"),
        ("Geolocalização", d["geolocalizacao"] or "não autorizada pelo signatário"),
        ("Páginas do documento assinado", str(d["paginas"])),
        ("SHA-256 pré-assinatura", d["hash_pre"]),
    ]
    if d.get("locadora"):
        linhas.insert(3, ("Assinatura da LOCADORA", d["locadora"]))
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
