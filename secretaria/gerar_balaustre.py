#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gerador de Balaústre — A∴ B∴ L∴ S∴ Igualdade Acreana nº 2 (GLEAC)

Usa o arquivo .docx de MODELO como base e substitui APENAS:
  1) o título (data), 2) o subtítulo (grau), 3) o parágrafo único do corpo
  e 4) o título do presidente na tabela de assinaturas (Ven∴ M∴ / Resp∴ M∴).
Cabeçalho (brasão), rodapé, margens, tabelas e estilos ficam byte a byte
idênticos ao modelo. Usa apenas a biblioteca padrão do Python.

Uso:
    python gerar_balaustre.py modelo.docx dados.json [saida.docx]
"""
import json, re, sys, zipfile, datetime
from xml.sax.saxutils import escape

# ----------------------------------------------------------------------------
# QUADRO DE OFICIAIS (padrão da mesa)
# ----------------------------------------------------------------------------
MESA_PADRAO = {
    "veneravel": "Jaime Fontes Vasconcelos",
    "vig1": "Mipis Eclesiastes Costa de Araújo",
    "vig2": "Calurino Ferraz Miranda",
    "orador": "Paulo Roberto Viana de Araújo",
    "secretario": "Jefferson Lunardelli Cogo",
}

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro"]

# ----------------------------------------------------------------------------
# NÚMEROS POR EXTENSO (pt-BR)
# ----------------------------------------------------------------------------
_UN = ["zero", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito",
       "nove", "dez", "onze", "doze", "treze", "quatorze", "quinze",
       "dezesseis", "dezessete", "dezoito", "dezenove"]
_DZ = ["", "", "vinte", "trinta", "quarenta", "cinquenta", "sessenta",
       "setenta", "oitenta", "noventa"]
_CT = ["", "cento", "duzentos", "trezentos", "quatrocentos", "quinhentos",
       "seiscentos", "setecentos", "oitocentos", "novecentos"]


def _ate_999(n, fem=False):
    if n == 0:
        return ""
    if n == 100:
        return "cem"
    partes = []
    c, r = divmod(n, 100)
    if c:
        ct = _CT[c]
        if fem and c >= 2:
            ct = ct.replace("entos", "entas")
        partes.append(ct)
    if r:
        if r < 20:
            u = _UN[r]
        else:
            d, un = divmod(r, 10)
            u = _DZ[d] + (" e " + _UN[un] if un else "")
        if fem:
            u = re.sub(r"\bum$", "uma", u)
            u = re.sub(r"\bdois$", "duas", u)
        partes.append(u)
    return " e ".join(partes)


def extenso(n, fem=False):
    n = int(n)
    if n == 0:
        return "zero"
    mil, resto = divmod(n, 1000)
    if mil == 0:
        return _ate_999(resto, fem)
    txt_mil = "mil" if mil == 1 else _ate_999(mil) + " mil"
    if resto == 0:
        return txt_mil
    sep = " e " if (resto < 100 or resto % 100 == 0) else " "
    return txt_mil + sep + _ate_999(resto, fem)


_ORD_UN = ["", "primeiro", "segundo", "terceiro", "quarto", "quinto", "sexto",
           "sétimo", "oitavo", "nono"]
_ORD_DZ = ["", "décimo", "vigésimo", "trigésimo"]


def ordinal_dia(n):
    d, u = divmod(n, 10)
    return " ".join(p for p in (_ORD_DZ[d], _ORD_UN[u]) if p)


def valor_reais(txt):
    """'125,00' -> ('125,00', 'Cento e vinte e cinco reais')"""
    s = str(txt).strip().replace("R$", "").replace(" ", "")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    v = round(float(s), 2)
    reais = int(v)
    cent = int(round((v - reais) * 100))
    partes = []
    if reais:
        partes.append(extenso(reais) + (" real" if reais == 1 else " reais"))
    if cent:
        partes.append(extenso(cent) + (" centavo" if cent == 1 else " centavos"))
    if not partes:
        partes = ["zero real"]
    por_ext = " e ".join(partes)
    fmt = f"{reais:,}".replace(",", ".") + f",{cent:02d}"
    return fmt, por_ext[0].upper() + por_ext[1:]


# ----------------------------------------------------------------------------
# DATA, HORA E GRAU
# ----------------------------------------------------------------------------
def deduzir_grau(data):
    """Última segunda = mestre; penúltima = companheiro; demais = aprendiz."""
    segundas = [datetime.date(data.year, data.month, d)
                for d in range(1, 32)
                if _data_valida(data.year, data.month, d)
                and datetime.date(data.year, data.month, d).weekday() == 0]
    if data in segundas:
        if data == segundas[-1]:
            return "mestre"
        if len(segundas) >= 2 and data == segundas[-2]:
            return "companheiro"
    return "aprendiz"


def _data_valida(a, m, d):
    try:
        datetime.date(a, m, d)
        return True
    except ValueError:
        return False


def fmt_hora(h):
    """'20:00' / '20h' / '2000' -> '20h00min'"""
    nums = re.findall(r"\d+", str(h))
    if len(nums) == 1 and len(nums[0]) in (3, 4):
        hh, mm = nums[0][:-2], nums[0][-2:]
    else:
        hh = nums[0]
        mm = nums[1] if len(nums) > 1 else "00"
    return f"{int(hh):02d}h{int(mm):02d}min"


# ----------------------------------------------------------------------------
# MONTAGEM DE RUNS (reproduz exatamente a formatação do modelo)
# ----------------------------------------------------------------------------
ARIAL = '<w:rFonts w:eastAsia="Arial" w:cs="Arial" w:ascii="Arial" w:hAnsi="Arial"/>'
CAMBRIA = ('<w:rFonts w:eastAsia="Cambria Math" w:cs="Cambria Math" '
           'w:ascii="Cambria Math" w:hAnsi="Cambria Math"/>')
TAM = '<w:sz w:val="24"/><w:szCs w:val="24"/>'


def _run(texto, negrito, fonte):
    rpr = f"<w:rPr>{fonte}{'<w:b/>' if negrito else ''}{TAM}</w:rPr>"
    sp = ' xml:space="preserve"' if texto != texto.strip() else ""
    return f"<w:r>{rpr}<w:t{sp}>{escape(texto)}</w:t></w:r>"


def runs(segmentos):
    """segmentos: lista de (texto, negrito). '∴' sai em Cambria Math,
    o resto em Arial 12 — idêntico ao modelo. Aceita **negrito** no texto."""
    saida = []
    for texto, negrito in segmentos:
        for i, parte in enumerate(re.split(r"\*\*", texto)):
            b = negrito or (i % 2 == 1)
            for pedaco in re.split(r"(∴)", parte):
                if not pedaco:
                    continue
                saida.append(_run(pedaco, b, CAMBRIA if pedaco == "∴" else ARIAL))
    return "".join(saida)


def frase(txt, padrao):
    """Normaliza um trecho: usa o padrão se vazio e garante ponto final."""
    t = (txt or "").strip() or padrao
    t = t.rstrip()
    if not t.endswith((".", "!", "?")):
        t += "."
    return t


# ----------------------------------------------------------------------------
# TEXTO DO BALAÚSTRE
# ----------------------------------------------------------------------------
def montar(d):
    data = datetime.date.fromisoformat(d["data"])
    grau = (d.get("grau") or deduzir_grau(data)).lower()
    mesa = {**MESA_PADRAO, **(d.get("mesa") or {})}
    mestre = grau.startswith("mestre")
    pres = "Resp∴ M∴" if mestre else "Ven∴ M∴"
    grau_abrev = {"aprendiz": "Apr∴ M∴", "companheiro": "Comp∴ M∴",
                  "mestre": "M∴ M∴"}[grau.split()[0]]
    grau_nome = {"aprendiz": "APRENDIZ MAÇOM", "companheiro": "COMPANHEIRO MAÇOM",
                 "mestre": "MESTRE MAÇOM"}[grau.split()[0]]
    tipo = d.get("tipo_sessao", "Ordinária")
    mes = MESES[data.month - 1]
    dia_ord = ordinal_dia(data.day)

    titulo = f"BALAÚSTRE DO DIA {data.day:02d} DE {mes.upper()} DE {data.year} DA E∴V∴"
    subtitulo = f"SESSÃO {tipo.upper()} DO GRAU DE {grau_nome}"

    if mestre:
        oficiais = ("Venerab∴ IIr∴ 1º e 2º VVig∴, Ven∴ Ir∴ Orad∴ e Ven∴ Ir∴ Sec∴, "
                    "os respectivos Ven∴ IIr∴ ")
    else:
        oficiais = "1º e 2º VVig∴, Orad∴ e Sec∴, os respectivos IIr∴ "

    # Bolsa de Propostas e Informações
    bolsa = d.get("bolsa") or {}
    n_col = int(bolsa.get("colunas") or 0)
    if n_col == 0:
        txt_bolsa = ("circulou com formalidades a Bolsa de Propostas e Informações "
                     "e colheu apenas os bons fluídos emitidos pelos irmãos.")
    else:
        palavra = "coluna gravada que foi decifrada" if n_col == 1 else \
                  "colunas gravadas que foram decifradas"
        txt_bolsa = ("a Bolsa de Propostas e Informações circulou com formalidades e "
                     "colheu, além dos bons fluídos emanados pelos irmãos, "
                     f"{extenso(n_col, fem=True)} ({n_col}) {palavra} como sendo: "
                     + frase(bolsa.get("descricao"), "[descrição não informada]"))

    # Tronco de Solidariedade
    val, val_ext = valor_reais(d.get("tronco") or "0")
    txt_tronco = (f"circulou com formalidades a Bolsa de Ben∴ para o Tr∴ de Sol∴ e "
                  f"rendeu a quantia de R$ {val} ({val_ext}) em quilos de medalhas "
                  "cunhadas, as quais foram debitadas à Tes∴ e creditadas à Hosp∴.")

    vis = d.get("visitantes")
    txt_vis = ("o Ir∴ Orador saudou os visitantes na forma de estilo."
               if vis in (True, "sim", "Sim") else "Não houve.")

    pal = d.get("palavra") or {}
    silencio = "reinou silêncio"

    lm = str(d.get("landmark") or "").strip()
    txt_lm = f"Foi lido o {lm} Landmark." if lm else "não houve leitura."

    seg = [
        (f"Ao {dia_ord} dia do mês de {mes} de {extenso(data.year)} da E∴ V∴, "
         f"precisamente às {fmt_hora(d['hora_abertura'])}, sobre os auspícios da "
         "Sereníssima Grande Loja Maçônica do Estado do Acre – GLEAC, teve início a "
         f"Sessão {tipo} do Grau de {grau_abrev}, da ", False),
        ("Augusta e Benemérita Loja Simbólica IGUALDADE ACREANA N° 2", True),
        (", do Rito Escocês Antigo e Aceito, situada na Avenida Epaminondas Jácome "
         "n° 3031, Centro - T∴ próprio, Oriente de Rio Branco-AC, presidida pelo "
         f"{pres} {mesa['veneravel']} e tendo como {oficiais}{mesa['vig1']}, "
         f"{mesa['vig2']}, {mesa['orador']} e {mesa['secretario']}. Estando a Loja "
         "composta e preenchidos os lugares com o número legal de obreiros, o "
         f"{pres}, abriu os trabalhos na forma do ritual. ", False),
        ("BALAÚSTRE", True),
        (": " + frase(d.get("balaustre_anterior"), "lido e aprovado sem restrições") + " ", False),
        ("EXPEDIENTE: ", True),
        (frase(d.get("expediente"), "não houve") + " ", False),
        ("LEITURA DO LANDMARK DO DIA: ", True),
        (txt_lm + " ", False),
        ("BOLSA DE PROPOSTAS E INFORMAÇÕES", True),
        (": " + txt_bolsa + " ", False),
        ("ORDEM DO DIA", True),
        (": " + frase(d.get("ordem_do_dia"), "não houve") + " ", False),
        ("TRONCO DE SOLIDARIEDADE", True),
        (": " + txt_tronco + " ", False),
        ("VISITANTES", True),
        (": " + txt_vis + " ", False),
        ("PALAVRA A BEM DA ORDEM EM GERAL E DO QUADRO EM PARTICULAR", True),
        (": Na ", False), ("Col∴ do Sul:", True),
        (" " + frase(pal.get("sul"), silencio) + " Na ", False), ("Col∴ do Norte", True),
        (": " + frase(pal.get("norte"), silencio) + " No ", False), ("Oriente:", True),
        (" " + frase(pal.get("oriente"), silencio) + " No ", False), ("Trono", True),
        (": " + frase(pal.get("trono"), silencio) + " ", False),
        ("ENCERRAMENTO DOS TRABALHOS: ", True),
        (f"o {pres} encerrou os trabalhos conforme ritualística de estilo exatamente "
         f"às {fmt_hora(d['hora_encerramento'])}. Nada mais havendo a registrar, eu, "
         f"{mesa['secretario']}, Secretário, lavrei o presente balaústre que depois de "
         "decifrado e aprovado será devidamente assinado por quem de direito. Dado e "
         f"traçado no Oriente de Rio Branco, ao {dia_ord} dia do mês de {mes} de "
         f"{data.year} da E∴V∴.", False),
    ]
    return titulo, subtitulo, seg, pres, data


# ----------------------------------------------------------------------------
# APLICAÇÃO NO MODELO
# ----------------------------------------------------------------------------
P_RE = re.compile(r"<w:p>(?:(?!<w:p>).)*?</w:p>", re.S)


def _troca_conteudo(par_xml, novos_runs):
    """Mantém o <w:pPr> original do parágrafo e troca só os runs."""
    m = re.match(r"(<w:p>(?:<w:pPr>.*?</w:pPr>)?)", par_xml, re.S)
    return m.group(1) + novos_runs + "</w:p>"


def gerar(modelo, dados, saida):
    titulo, subtitulo, seg, pres, data = montar(dados)
    with zipfile.ZipFile(modelo) as zin:
        xml = zin.read("word/document.xml").decode("utf-8")
        corpo_ini = xml.index("<w:body>") + len("<w:body>")
        pars = list(P_RE.finditer(xml, corpo_ini))
        p_tit, p_sub, p_corpo = pars[0], pars[1], pars[2]
        p_ven = next(p for p in pars[3:] if re.search(r">Ven</w:t>|>Ven∴|>Resp", p.group(0)))

        trocas = [
            (p_tit, runs([(titulo, True)])),
            (p_sub, runs([(subtitulo, True)])),
            (p_corpo, runs(seg)),
            (p_ven, runs([(pres, False)])),
        ]
        for m, novos in sorted(trocas, key=lambda t: t[0].start(), reverse=True):
            xml = xml[:m.start()] + _troca_conteudo(m.group(0), novos) + xml[m.end():]

        with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                conteudo = xml.encode("utf-8") if item.filename == "word/document.xml" \
                    else zin.read(item.filename)
                zout.writestr(item, conteudo)
    return saida


def nome_padrao(dados):
    data = datetime.date.fromisoformat(dados["data"])
    return f"Balaústre_sessão_{data.day:02d}_de_{MESES[data.month-1].capitalize()}_{data.year}.docx"


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    with open(sys.argv[2], encoding="utf-8") as f:
        dados = json.load(f)
    destino = sys.argv[3] if len(sys.argv) > 3 else nome_padrao(dados)
    print("Gerado:", gerar(sys.argv[1], dados, destino))
