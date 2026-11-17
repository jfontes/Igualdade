"""Feriados e recessos usados pelo gerador de sessões.

Nacionais são calculados (inclusive os móveis, a partir da Páscoa). Estaduais, municipais
e recessos ficam em config.py, para a Secretaria ajustar quando a lei ou a Loja mudar.
"""
from datetime import date, timedelta

from .config import DIAS_SEM_SESSAO, RECESSOS

NACIONAIS_FIXOS = [
    (1, 1, "Confraternização Universal"),
    (4, 21, "Tiradentes"),
    (5, 1, "Dia do Trabalho"),
    (9, 7, "Independência do Brasil"),
    (10, 12, "Nossa Senhora Aparecida"),
    (11, 2, "Finados"),
    (11, 15, "Proclamação da República"),
    (11, 20, "Dia Nacional de Zumbi e da Consciência Negra"),
    (12, 25, "Natal"),
]


def pascoa(ano: int) -> date:
    """Domingo de Páscoa (algoritmo de Meeus/Jones/Butcher, calendário gregoriano)."""
    a, b, c = ano % 19, ano // 100, ano % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = (h + l - 7 * m + 114) % 31 + 1
    return date(ano, mes, dia)


def dias_sem_sessao(ano: int) -> dict[date, str]:
    """Data → motivo do cancelamento (feriados nacionais, locais, Carnaval e Corpus Christi)."""
    p = pascoa(ano)
    dias = {date(ano, m, d): f"Feriado: {nome}" for m, d, nome in NACIONAIS_FIXOS}
    dias[p - timedelta(days=2)] = "Feriado: Sexta-feira Santa"
    dias.setdefault(p - timedelta(days=48), "Carnaval")
    dias.setdefault(p - timedelta(days=47), "Carnaval")
    dias.setdefault(p + timedelta(days=60), "Corpus Christi")
    for m, d, nome in DIAS_SEM_SESSAO:
        dias.setdefault(date(ano, m, d), f"Feriado: {nome}")
    return dias


def recesso(dia: date) -> str | None:
    for (m1, d1), (m2, d2), nome in RECESSOS:
        if date(dia.year, m1, d1) <= dia <= date(dia.year, m2, d2):
            return nome
    return None
