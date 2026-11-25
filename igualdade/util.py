"""Validações e formatações."""
import re
from datetime import date

MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho",
         "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]

UFS = ["AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
       "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
       "SP", "SE", "TO"]

PARENTESCOS = ["Esposa", "Esposo", "Companheira", "Companheiro", "Filho", "Filha",
               "Pai", "Mãe", "Enteado", "Enteada", "Neto", "Neta", "Outro"]

# Ordem e rótulos das datas maçônicas (RN03)
DATAS_MACONICAS = [
    ("data_iniciacao", "Iniciação"),
    ("data_elevacao", "Elevação"),
    ("data_exaltacao", "Exaltação"),
    ("data_filiacao", "Filiação"),
    ("data_instalacao", "Instalação"),
]


# Títulos honoríficos: registrados só pela Secretaria e exibidos só quando informados
DATAS_HONORIFICAS = [
    ("data_emerito", "Emérito"),
    ("data_vm_honra", "Venerável Mestre de Honra"),
]

# Datas que são exceção: só aparecem nas telas de visualização quando informadas
DATAS_OPCIONAIS = {"data_filiacao", "data_emerito", "data_vm_honra"}


def so_digitos(valor: str | None) -> str:
    return re.sub(r"\D", "", valor or "")


def cpf_valido(cpf: str) -> bool:
    cpf = so_digitos(cpf)
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    for n in (9, 10):
        soma = sum(int(cpf[i]) * (n + 1 - i) for i in range(n))
        dv = (soma * 10) % 11 % 10
        if dv != int(cpf[n]):
            return False
    return True


def ler_data(valor: str | None) -> str | None:
    """Converte 'dd/mm/aaaa' (campo com máscara) ou 'aaaa-mm-dd' (<input type=date>) em ISO;
    vazio → None. Lança ValueError se inválida."""
    valor = (valor or "").strip()
    if not valor:
        return None
    if "/" in valor:
        d, m, a = valor.split("/")
        if len(a) != 4:
            raise ValueError("ano com 4 números")
        return date(int(a), int(m), int(d)).isoformat()
    return date.fromisoformat(valor).isoformat()


def ler_data_nasc(form, campo: str) -> str | None:
    """Lê os campos <campo>_dia, <campo>_mes e <campo>_ano (ano opcional).

    Retorna 'AAAA-MM-DD', '--MM-DD' (sem ano) ou None. Lança ValueError se inválida.
    """
    dia = so_digitos(form.get(f"{campo}_dia"))
    mes = so_digitos(form.get(f"{campo}_mes"))
    ano = so_digitos(form.get(f"{campo}_ano"))
    if not (dia or mes or ano):
        return None
    if not (dia and mes):
        raise ValueError("informe dia e mês")
    if ano:
        if not 1900 <= int(ano) <= date.today().year:
            raise ValueError("ano inválido")
        return date(int(ano), int(mes), int(dia)).isoformat()
    date(2000, int(mes), int(dia))  # valida dia/mês (2000 é bissexto, aceita 29/02)
    return f"--{int(mes):02d}-{int(dia):02d}"


def tem_ano(iso: str | None) -> bool:
    return bool(iso) and not iso.startswith("--")


def partes_data(iso: str | None) -> dict:
    """Separa uma data (completa ou --MM-DD) para preencher os campos dia/mês/ano."""
    if not iso:
        return {"dia": "", "mes": "", "ano": ""}
    if iso.startswith("--"):
        ano, mes, dia = "", iso[2:4], iso[5:7]
    else:
        ano, mes, dia = iso.split("-")
    return {"dia": int(dia), "mes": int(mes), "ano": ano}


def fmt_data(iso: str | None) -> str:
    if not iso:
        return ""
    if iso.startswith("--"):
        return f"{iso[5:7]}/{iso[2:4]}"
    a, m, d = iso.split("-")
    return f"{d}/{m}/{a}"


def campo_data(valor) -> str:
    """Valor para o campo de data com máscara: '2027-03-20' → '20/03/2027'; texto digitado volta igual."""
    valor = (str(valor) if valor else "").strip()
    if len(valor) == 10 and valor[4] == "-" and valor[7] == "-":
        return f"{valor[8:]}/{valor[5:7]}/{valor[:4]}"
    return valor


def fmt_data_extenso(iso: str | None) -> str:
    """'2027-02-08' → '8 de fevereiro'."""
    if not iso or iso.startswith("--"):
        return fmt_data(iso)
    return f"{int(iso[8:10])} de {MESES[int(iso[5:7]) - 1].lower()}"


def fmt_cpf(cpf: str | None) -> str:
    c = so_digitos(cpf)
    return f"{c[:3]}.{c[3:6]}.{c[6:9]}-{c[9:]}" if len(c) == 11 else (cpf or "")


def fmt_cep(cep: str | None) -> str:
    c = so_digitos(cep)
    return f"{c[:5]}-{c[5:]}" if len(c) == 8 else (cep or "")


def fmt_tel(tel: str | None) -> str:
    """(68) 99999-9999 para celular, (68) 3224-0000 para fixo."""
    t = so_digitos(tel)
    if len(t) == 11:
        return f"({t[:2]}) {t[2:7]}-{t[7:]}"
    if len(t) == 10:
        return f"({t[:2]}) {t[2:6]}-{t[6:]}"
    return tel or ""


def ler_telefone(valor: str | None) -> str | None:
    """Guarda só os dígitos com DDD (10 ou 11). Remove o +55 se vier junto."""
    t = so_digitos(valor)
    if len(t) in (12, 13) and t.startswith("55"):
        t = t[2:]
    if not t:
        return None
    if len(t) not in (10, 11):
        raise ValueError("informe DDD + número")
    return t


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def ler_email(valor: str | None) -> str | None:
    e = (valor or "").strip().lower()
    if not e:
        return None
    if len(e) > 120 or not EMAIL_RE.match(e):
        raise ValueError("e-mail inválido")
    return e


def validar_cronologia(d: dict) -> list[str]:
    """RN03: as datas preenchidas devem seguir a evolução do membro."""
    erros = []
    hoje = date.today().isoformat()
    if not tem_ano(d.get("data_nascimento")):
        d = {**d, "data_nascimento": None}  # sem ano não entra na comparação
    sequencia = [("data_nascimento", "Nascimento"), ("data_iniciacao", "Iniciação"),
                 ("data_elevacao", "Elevação"), ("data_exaltacao", "Exaltação"),
                 ("data_instalacao", "Instalação")]
    anterior = None
    for campo, rotulo in sequencia:
        valor = d.get(campo)
        if not valor:
            continue
        if anterior and valor < anterior[1]:
            erros.append(f"A data de {rotulo} não pode ser anterior à de {anterior[0]}.")
        anterior = (rotulo, valor)
    for campo, rotulo in [("data_nascimento", "Nascimento")] + DATAS_MACONICAS + DATAS_HONORIFICAS:
        if d.get(campo) and d[campo] > hoje:
            erros.append(f"A data de {rotulo} não pode estar no futuro.")
    if d.get("data_filiacao") and d.get("data_nascimento") and d["data_filiacao"] < d["data_nascimento"]:
        erros.append("A data de Filiação não pode ser anterior ao Nascimento.")
    if d.get("data_afastamento") and d.get("data_iniciacao") and d["data_afastamento"] < d["data_iniciacao"]:
        erros.append("A data de Afastamento não pode ser anterior à Iniciação.")
    return erros


_PARTICULAS = {"de", "da", "do", "das", "dos", "e", "d'"}


def nome_proprio(nome: str | None) -> str:
    """'JAIME FONTES DE VASCONCELOS' -> 'Jaime Fontes de Vasconcelos' (forma usada no balaústre)."""
    palavras = " ".join((nome or "").split()).lower().split(" ")
    saida = []
    for i, p in enumerate(palavras):
        if i and p in _PARTICULAS:
            saida.append(p)
        else:
            # mantém apóstrofo e hífen: dell'agnolo -> Dell'Agnolo
            saida.append(re.sub(r"(^|[-'’])(\w)", lambda m: m.group(1) + m.group(2).upper(), p))
    return " ".join(saida).strip()


# ---------------------------------------------------------------- dinheiro (centavos)

def fmt_moeda(centavos: int | None, simbolo: bool = True) -> str:
    """81000 → 'R$ 810,00'; -1550 → '-R$ 15,50'."""
    if centavos is None:
        return ""
    sinal = "-" if centavos < 0 else ""
    reais, cent = divmod(abs(int(centavos)), 100)
    texto = f"{reais:,}".replace(",", ".") + f",{cent:02d}"
    return f"{sinal}R$ {texto}" if simbolo else f"{sinal}{texto}"


def ler_moeda(valor: str | None) -> int | None:
    """'810', '810,00', '1.620,50', 'R$ 135' ou '135.5' → centavos. Vazio → None.

    Lança ValueError se não for um valor positivo com até 2 casas decimais.
    """
    t = (valor or "").replace("R$", "").replace(" ", "").strip()
    if not t:
        return None
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", t):
        t = t.replace(".", "")  # 1.620 = mil seiscentos e vinte
    if not re.fullmatch(r"\d+(\.\d{1,2})?", t):
        raise ValueError("valor inválido")
    inteiro, _, frac = t.partition(".")
    centavos = int(inteiro) * 100 + int((frac + "00")[:2])
    if centavos <= 0:
        raise ValueError("o valor deve ser maior que zero")
    return centavos


def grau_do_obreiro(o) -> str:
    """Grau simbólico pela última data alcançada."""
    if o["data_exaltacao"]:
        return "Mestre"
    if o["data_elevacao"]:
        return "Companheiro"
    if o["data_iniciacao"]:
        return "Aprendiz"
    return ""


# ---------------------------------------------------------------- CNPJ e máscaras (LGPD)

def cnpj_valido(cnpj: str) -> bool:
    c = so_digitos(cnpj)
    if len(c) != 14 or c == c[0] * 14:
        return False
    def dv(base: str) -> str:
        pesos = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2][-len(base):]
        resto = sum(int(d) * p for d, p in zip(base, pesos)) % 11
        return "0" if resto < 2 else str(11 - resto)
    return c[12] == dv(c[:12]) and c[13] == dv(c[:13])


def cpf_cnpj_valido(doc: str) -> bool:
    d = so_digitos(doc)
    return cpf_valido(d) if len(d) == 11 else cnpj_valido(d) if len(d) == 14 else False


def fmt_cpf_cnpj(doc: str | None) -> str:
    d = so_digitos(doc)
    if len(d) == 14:
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    return fmt_cpf(d) if len(d) == 11 else (doc or "")


def mascarar_doc(doc: str | None) -> str:
    """CPF: ***.456.789-** ; CNPJ: **.345.678/0001-** (mostra só o miolo)."""
    d = so_digitos(doc)
    if len(d) == 11:
        return f"***.{d[3:6]}.{d[6:9]}-**"
    if len(d) == 14:
        return f"**.{d[2:5]}.{d[5:8]}/{d[8:12]}-**"
    return "***"


def mascarar_nome(nome: str | None) -> str:
    """'JOÃO DA SILVA SOUZA' → 'João S*** S***' (primeiro nome e iniciais)."""
    partes = [p for p in (nome or "").split() if p.lower() not in {"da", "de", "do", "das", "dos", "e"}]
    if not partes:
        return "***"
    return " ".join([partes[0].title()] + [p[0].upper() + "***" for p in partes[1:]])


# ---------------------------------------------------------------- números por extenso (contratos)
_UNIDADES = ["zero", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito", "nove", "dez", "onze",
             "doze", "treze", "quatorze", "quinze", "dezesseis", "dezessete", "dezoito", "dezenove"]
_DEZENAS = ["", "", "vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta", "oitenta", "noventa"]
_CENTENAS = ["", "cento", "duzentos", "trezentos", "quatrocentos", "quinhentos", "seiscentos", "setecentos",
             "oitocentos", "novecentos"]


def _ate_999(n: int) -> str:
    if n == 100:
        return "cem"
    partes = []
    c, r = divmod(n, 100)
    if c:
        partes.append(_CENTENAS[c])
    if r:
        if r < 20:
            partes.append(_UNIDADES[r])
        else:
            d, u = divmod(r, 10)
            partes.append(_DEZENAS[d] + (" e " + _UNIDADES[u] if u else ""))
    return " e ".join(partes)


def numero_por_extenso(n: int) -> str:
    """0 a 999.999.999, em português ("mil e quinhentos", "dois milhões e trezentos mil")."""
    n = int(n)
    if n == 0:
        return "zero"
    grupos = []
    milhoes, resto = divmod(n, 1_000_000)
    milhares, unidades = divmod(resto, 1000)
    if milhoes:
        grupos.append(("um milhão" if milhoes == 1 else _ate_999(milhoes) + " milhões", milhoes))
    if milhares:
        grupos.append(("mil" if milhares == 1 else _ate_999(milhares) + " mil", milhares))
    if unidades:
        grupos.append((_ate_999(unidades), unidades))
    texto = grupos[0][0]
    for t, valor in grupos[1:]:
        texto += (" e " if valor < 100 or valor % 100 == 0 else " ") + t
    return texto


def reais_por_extenso(centavos: int | None) -> str:
    """150000 → 'mil e quinhentos reais'; 12550 → 'cento e vinte e cinco reais e cinquenta centavos'."""
    reais, cent = divmod(int(centavos or 0), 100)
    partes = []
    if reais:
        partes.append(numero_por_extenso(reais) + (" real" if reais == 1 else
                                                   " de reais" if reais % 1_000_000 == 0 else " reais"))
    if cent:
        partes.append(numero_por_extenso(cent) + (" centavo" if cent == 1 else " centavos"))
    return " e ".join(partes) or "zero real"
