"""Informações institucionais exibidas no painel (RF01)."""

LOJA = {
    "nome": "Igualdade Acreana Nº 2",
    "titulo": "Augusta e Benemérita Loja Simbólica",
    "fundacao": "Fundada em 5 de maio de 1906",
    "endereco": "Av. Epaminondas Jácome, 3031 – Centro – CEP 69.900-056",
    "cidade": "Rio Branco – Acre",
    "cnpj": "04.115.416/0001-06",
}

# ---------------------------------------------------------------- agenda de sessões
# As sessões ocorrem às segundas-feiras, às 20h (0 = segunda-feira).
DIA_DA_SESSAO = 0

# Feriados estaduais (Acre) e municipais (Rio Branco): (mês, dia, nome).
# Os nacionais são calculados automaticamente. Confira esta lista a cada ano.
DIAS_SEM_SESSAO = [
    (1, 23, "Dia do Evangélico (AC)"),
    (3, 8, "Dia Internacional da Mulher (AC)"),
    (6, 15, "Aniversário do Acre"),
    (8, 6, "Início da Revolução Acreana (AC)"),
    (9, 5, "Dia da Amazônia (AC)"),
    (11, 17, "Assinatura do Tratado de Petrópolis (AC)"),
    (12, 28, "Aniversário de Rio Branco"),
]

# Períodos de recesso da Loja: ((mês, dia) início, (mês, dia) fim, nome). Não geram sessões.
RECESSOS = [
    ((1, 1), (1, 31), "Recesso de janeiro"),
    ((12, 16), (12, 31), "Recesso de fim de ano"),
]

# ---------------------------------------------------------------- diretoria (quadro de oficiais)
# Cargos na ordem da nominata. A chave é gravada no banco; o nome aparece nas telas.
# Os cinco primeiros compõem a mesa do balaústre.
CARGOS = [
    ("veneravel", "Venerável Mestre"),
    ("vig1", "1º Vigilante"),
    ("vig2", "2º Vigilante"),
    ("orador", "Orador"),
    ("secretario", "Secretário"),
    ("secretario_adj", "Secretário Adjunto"),
    ("tesoureiro", "Tesoureiro"),
    ("chanceler", "Chanceler"),
    ("mestre_cerimonias", "Mestre de Cerimônias"),
    ("hospitaleiro", "Hospitaleiro"),
    ("hospitaleiro_adj", "Hospitaleiro Adjunto"),
    ("guarda_templo", "Guarda do Templo"),
    ("cobridor", "Cobridor Externo"),
    ("diacono1", "1º Diácono"),
    ("diacono2", "2º Diácono"),
    ("experto1", "1º Experto"),
    ("experto2", "2º Experto"),
    ("porta_bandeira", "Porta Bandeira"),
    ("porta_estandarte", "Porta Estandarte"),
    ("arquiteto", "Arquiteto"),
    ("arquiteto_adj", "Arquiteto Adjunto"),
    ("mestre_harmonia", "Mestre de Harmonia"),
    ("mestre_banquete", "Mestre de Banquete"),
    ("mestre_banquete_adj", "Mestre de Banquete Adjunto"),
    ("porta_espada", "Porta Espada"),
    ("bibliotecario", "Bibliotecário"),
]
CARGOS_MESA = ["veneravel", "vig1", "vig2", "orador", "secretario"]
# Obrigatórios ao cadastrar a gestão: a mesa e o Tesoureiro (responsável pelas percapitas)
CARGOS_OBRIGATORIOS = CARGOS_MESA + ["tesoureiro"]
# Cargos da gestão vigente que têm acesso de Secretaria (cadastros, diretoria, balaústres)
CARGOS_SECRETARIA = ["secretario", "veneravel"]
