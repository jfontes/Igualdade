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
