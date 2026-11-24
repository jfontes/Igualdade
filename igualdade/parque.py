"""Parque das Acácias: contratos de locação da área de eventos (painel do administrador do Parque).

Fluxo: cadastro do contrato → (vistoria fotográfica pelo caseiro, se exigida) → link de assinatura
para o contratante (válido por 7 dias) → assinatura → PDF consolidado + e-mail.

Acesso: Administrador do Parque (marcação no cadastro do obreiro), Venerável da gestão vigente e
Administrador do sistema. O caseiro usa uma página separada (/vistoria) com código de acesso.

Arquivos ficam em instance/contratos/<id>/ (fora de static/); o banco guarda caminho e SHA-256.
"""
import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

from flask import (Blueprint, abort, current_app, flash, redirect, render_template, request,
                   send_file, url_for)
from flask_login import current_user, login_required
from werkzeug.security import check_password_hash, generate_password_hash

from . import email_service
from .config import LOJA, PARQUE
from .db import get_db
from .util import (UFS, cpf_cnpj_valido, fmt_cep, fmt_cpf_cnpj, fmt_data, fmt_moeda, ler_data, ler_email,
                   ler_moeda, ler_telefone, so_digitos)

bp = Blueprint("parque", __name__, url_prefix="/parque")

AGUARDANDO_VISTORIA = "AGUARDANDO_VISTORIA"
AGUARDANDO_ASSINATURA = "AGUARDANDO_ASSINATURA"
ASSINADO = "ASSINADO"
CANCELADO = "CANCELADO"
STATUS = {
    AGUARDANDO_VISTORIA: ("Aguardando vistoria", "🔍"),
    AGUARDANDO_ASSINATURA: ("Aguardando assinatura", "✍️"),
    ASSINADO: ("Assinado", "✅"),
    CANCELADO: ("Cancelado", "⚫"),
}
ALFABETO_CODIGO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sem 0/O, 1/I
ESTADOS_CIVIS = ["Solteiro(a)", "Casado(a)", "União estável", "Separado(a)", "Divorciado(a)", "Viúvo(a)"]
FORMAS_PAGAMENTO = ["Pix", "Dinheiro", "Cartão de crédito", "Abatimento em crédito"]
HORARIO_PADRAO = ("06:00", "23:00")
TOLERANCIAS = [30, 60]  # minutos para desmontagem após o fim do horário (cláusula 3.3)


class PendenciaLocadora(Exception):
    """Falta algo da LOCADORA (representante ou assinatura padronizada) para liberar o contrato."""

    def __init__(self, pendencias: list[str]):
        super().__init__("; ".join(pendencias))
        self.pendencias = pendencias


def agora_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------- permissões

def gere_parque() -> bool:
    if not current_user.is_authenticated:
        return False
    from .auth import cargos_vigentes
    return bool(getattr(current_user, "admin_cadastro", False) or getattr(current_user, "admin_parque", False)
                or "veneravel" in cargos_vigentes().get(current_user.id, set()))


def parque_required(view):
    @wraps(view)
    @login_required
    def wrapper(*args, **kwargs):
        if not gere_parque():
            abort(403)
        return view(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------- arquivos (instance/contratos/<id>/)

def pasta_contratos() -> Path:
    p = Path(current_app.instance_path) / "contratos"
    p.mkdir(parents=True, exist_ok=True)
    return p


def salvar_arquivo(contrato_id: int, nome: str, dados: bytes) -> tuple[str, str]:
    """Grava e devolve (caminho relativo, sha256)."""
    pasta = pasta_contratos() / str(contrato_id)
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / nome).write_bytes(dados)
    return f"{contrato_id}/{nome}", hashlib.sha256(dados).hexdigest()


def ler_arquivo(relativo: str | None) -> bytes | None:
    if not relativo:
        return None
    caminho = (pasta_contratos() / relativo).resolve()
    if pasta_contratos().resolve() not in caminho.parents or not caminho.is_file():
        return None
    return caminho.read_bytes()


def apagar_arquivo(relativo: str | None):
    if relativo:
        try:
            (pasta_contratos() / relativo).unlink(missing_ok=True)
        except OSError as e:
            current_app.logger.warning("Não foi possível apagar %s: %s", relativo, e)


# ---------------------------------------------------------------- consultas

def buscar(contrato_id: int):
    c = get_db().execute("SELECT * FROM contrato WHERE id = ?", (contrato_id,)).fetchone()
    if c is None:
        abort(404)
    return c


def detalhar(c) -> dict:
    d = dict(c)
    d["evento"] = json.loads(c["evento_dados_json"] or "{}")
    d["evento"]["pagamento_texto"] = texto_pagamento(d["evento"])
    d["contratante"] = json.loads(c["contratante_dados_json"] or "{}")
    d["pessoa_juridica"] = d["contratante"].get("tipo_pessoa") == "PJ"
    d["locadora"] = json.loads(c["locadora_json"] or "{}") if "locadora_json" in c.keys() else {}
    d["status_rotulo"], d["status_icone"] = STATUS[c["status"]]
    d["link_expirado"] = (c["status"] == AGUARDANDO_ASSINATURA and c["token_expira_em"]
                          and c["token_expira_em"] < iso(agora_utc()))
    return d


def texto_pagamento(evento: dict) -> str:
    """'Pix e Cartão de crédito — 50% na reserva…' (contratos antigos guardavam um texto livre)."""
    formas = evento.get("formas_pagamento") or []
    if not formas:
        return evento.get("forma_pagamento") or ""
    texto = formas[0] if len(formas) == 1 else ", ".join(formas[:-1]) + " e " + formas[-1]
    return texto + (f" — {evento['condicoes_pagamento']}" if evento.get("condicoes_pagamento") else "")


def fotos_da_vistoria(contrato_id: int):
    """Fotos na ordem dos tipos; "Outras fotos" (sem tipo) no fim."""
    return get_db().execute(
        "SELECT f.*, COALESCE(t.nome, f.tipo_nome) AS legenda FROM vistoria_foto f "
        "LEFT JOIN vistoria_tipo t ON t.id = f.tipo_id WHERE f.contrato_id = ? "
        "ORDER BY f.tipo_id IS NULL, COALESCE(t.ordem, 0), f.id", (contrato_id,)).fetchall()


def tipos_vistoria(somente_ativos: bool = True):
    sql = "SELECT * FROM vistoria_tipo" + (" WHERE ativo = 1" if somente_ativos else "")
    return get_db().execute(sql + " ORDER BY ordem, nome").fetchall()


def tipos_para(piscina: bool):
    """Tipos ativos exigidos num contrato com ou sem piscina."""
    return [t for t in tipos_vistoria() if piscina or not t["so_com_piscina"]]


def tipos_exigidos(contrato_id: int):
    """Tipos ativos exigidos neste contrato: os marcados "só com piscina" entram só se ele incluir a piscina."""
    evento = json.loads(buscar(contrato_id)["evento_dados_json"] or "{}")
    return tipos_para(bool(evento.get("inclui_piscina")))


def _tipos_com_foto(contrato_id: int) -> set[int]:
    return {r["tipo_id"] for r in get_db().execute(
        "SELECT DISTINCT tipo_id FROM vistoria_foto WHERE contrato_id = ? AND tipo_id IS NOT NULL", (contrato_id,))}


def tipos_pendentes(contrato_id: int) -> list[str]:
    """Tipos exigidos sem foto nesta vistoria e sem foto padrão (a padrão já conta como feita)."""
    com_foto = _tipos_com_foto(contrato_id)
    return [t["nome"] for t in tipos_exigidos(contrato_id) if t["id"] not in com_foto and not t["foto_padrao"]]


def padroes_faltando(piscina: bool) -> list[str]:
    """Tipos exigidos (com ou sem piscina) que ainda não têm foto padrão."""
    return [t["nome"] for t in tipos_para(piscina) if not t["foto_padrao"]]


def definir_foto_padrao(tipo_id: int, jpeg: bytes):
    """Troca a foto padrão do tipo (a anterior é apagada: os contratos guardam cópias próprias)."""
    db = get_db()
    anterior = db.execute("SELECT foto_padrao FROM vistoria_tipo WHERE id = ?", (tipo_id,)).fetchone()
    rel, _sha = salvar_arquivo("padrao", f"tipo_{tipo_id}_{secrets.token_hex(4)}.jpg", jpeg)
    db.execute("UPDATE vistoria_tipo SET foto_padrao = ?, foto_padrao_em = ? WHERE id = ?",
               (rel, iso(agora_utc()), tipo_id))
    db.commit()
    if anterior and anterior["foto_padrao"]:
        apagar_arquivo(anterior["foto_padrao"])


def copiar_fotos_padrao(contrato_id: int, so_faltantes: bool = False) -> int:
    """Copia para o contrato as fotos padrão dos tipos exigidos. Com `so_faltantes`, só dos tipos que ainda
    não têm foto (fim da vistoria); sem, substitui todas as fotos por tipo (contrato com fotos padrão)."""
    db = get_db()
    com_foto = _tipos_com_foto(contrato_id)
    if not so_faltantes:
        for f in db.execute("SELECT id, arquivo FROM vistoria_foto WHERE contrato_id = ? AND tipo_id IS NOT NULL",
                            (contrato_id,)).fetchall():
            db.execute("DELETE FROM vistoria_foto WHERE id = ?", (f["id"],))
            apagar_arquivo(f["arquivo"])
        com_foto = set()
    copiadas = 0
    for t in tipos_exigidos(contrato_id):
        dados = ler_arquivo(t["foto_padrao"])
        if t["id"] in com_foto or not dados:
            continue
        cur = db.execute("INSERT INTO vistoria_foto (contrato_id, tipo_id, tipo_nome, arquivo, sha256, enviado_por, "
                         "criado_em) VALUES (?, ?, ?, '', '', 'padrao', ?)",
                         (contrato_id, t["id"], t["nome"], iso(agora_utc())))
        rel, sha = salvar_arquivo(contrato_id, f"vistoria_{cur.lastrowid:05d}.jpg", dados)
        db.execute("UPDATE vistoria_foto SET arquivo = ?, sha256 = ? WHERE id = ?", (rel, sha, cur.lastrowid))
        copiadas += 1
    db.commit()
    return copiadas


def url_externa(endpoint: str, **kw) -> str:
    """Endereço completo para e-mail, QR Code e link enviado ao contratante."""
    base = os.environ.get("SITE_URL")
    if base:
        return base.rstrip("/") + url_for(endpoint, **kw)
    url = url_for(endpoint, _external=True, **kw)
    if os.environ.get("COOKIE_SEGURO") == "1" and url.startswith("http://"):
        url = "https://" + url[len("http://"):]
    return url


def resumo_evento(evento: dict) -> str:
    return f"{evento.get('tipo_evento') or 'Evento'} em {fmt_data(evento.get('data'))}"


# ---------------------------------------------------------------- código de acesso do caseiro

def codigo_caseiro_definido() -> bool:
    return bool(get_db().execute("SELECT 1 FROM parque_config WHERE chave = 'codigo_caseiro'").fetchone())


def conferir_codigo_caseiro(codigo: str) -> bool:
    row = get_db().execute("SELECT valor FROM parque_config WHERE chave = 'codigo_caseiro'").fetchone()
    return bool(row and check_password_hash(row["valor"], so_digitos(codigo)))


def definir_codigo_caseiro(codigo: str):
    db = get_db()
    db.execute("INSERT INTO parque_config (chave, valor, atualizado_em) VALUES ('codigo_caseiro', ?, ?) "
               "ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor, atualizado_em = excluded.atualizado_em",
               (generate_password_hash(codigo), iso(agora_utc())))
    db.commit()


# ---------------------------------------------------------------- representante da LOCADORA

def veneravel_vigente():
    """(gestão, linha do cargo 'veneravel' na diretoria) vigentes hoje, ou (None, None)."""
    from .diretoria import cargos_da_gestao, gestao_vigente
    gestao = gestao_vigente()
    if gestao is None:
        return None, None
    return gestao, cargos_da_gestao(gestao["id"]).get("veneravel")


def assinatura_da_gestao(gestao_id: int):
    return get_db().execute("SELECT * FROM assinatura_locadora WHERE gestao_id = ?", (gestao_id,)).fetchone()


def representante_locadora() -> tuple[dict | None, list[str]]:
    """Dados do Venerável da gestão vigente (nome, CPF, endereço e assinatura padronizada) e o que falta."""
    gestao, ven = veneravel_vigente()
    if gestao is None:
        return None, ["cadastrar a diretoria da gestão atual (Obreiros → Diretoria)"]
    if ven is None or not ven["obreiro_id"]:
        return None, ["indicar na Diretoria o Venerável da gestão atual, escolhendo o nome na lista de obreiros"]
    o = get_db().execute("SELECT * FROM obreiro WHERE id = ?", (ven["obreiro_id"],)).fetchone()
    pendencias = []
    if not o or not o["cpf"]:
        pendencias.append("o CPF do Venerável no cadastro de obreiros")
    if not o or not (o["logradouro"] and o["cidade"]):
        pendencias.append("o endereço do Venerável no cadastro de obreiros")
    assinatura = assinatura_da_gestao(gestao["id"])
    if not assinatura:
        pendencias.append("a assinatura padronizada do Venerável (Parque → Configuração)")
    if not o:
        return None, pendencias
    endereco = ", ".join(x for x in [o["logradouro"], o["numero"], o["bairro"]] if x)
    cidade = "/".join(x for x in [o["cidade"], o["estado"]] if x)
    dados = {
        "gestao_id": gestao["id"], "obreiro_id": o["id"], "nome": o["nome"], "cpf": o["cpf"],
        "endereco": ", ".join(x for x in [endereco, cidade, f"CEP {fmt_cep(o['cep'])}" if o["cep"] else ""] if x),
        "assinatura_arquivo": assinatura["arquivo"] if assinatura else None,
        "assinatura_sha256": assinatura["sha256"] if assinatura else None,
        "assinatura_cadastrada_em": assinatura["criado_em"] if assinatura else None,
    }
    return dados, pendencias


def pendencias_liberacao() -> list[str]:
    return representante_locadora()[1]


# ---------------------------------------------------------------- liberação do link de assinatura

def liberar_para_assinatura(contrato_id: int) -> tuple[str, bool, str]:
    """Gera um novo token (7 dias), muda o status e tenta enviar o e-mail. Devolve (link, enviou, motivo).

    Guarda no contrato o representante da LOCADORA e a assinatura padronizada vigentes agora, que vão
    estampados no PDF. Sem eles, levanta PendenciaLocadora e nada muda.
    """
    locadora, pendencias = representante_locadora()
    if pendencias:
        raise PendenciaLocadora(pendencias)
    db = get_db()
    token = secrets.token_urlsafe(24)
    expira = agora_utc() + timedelta(days=PARQUE["dias_validade_link"])
    atual = buscar(contrato_id)
    db.execute("UPDATE contrato SET status = ?, token_assinatura = ?, token_expira_em = ?, link_enviado_em = ?, "
               "pdf_pre_arquivo = NULL, hash_pre_assinatura = NULL, locadora_json = ? WHERE id = ?",
               (AGUARDANDO_ASSINATURA, token, iso(expira), iso(agora_utc()),
                json.dumps(locadora, ensure_ascii=False), contrato_id))
    apagar_arquivo(atual["pdf_pre_arquivo"])
    db.commit()
    c = detalhar(buscar(contrato_id))
    link = url_externa("assinatura.inicio", token=token)
    texto = (f"Olá, {c['contratante_nome'].split()[0].title()}.\n\n"
             f"A {LOJA['titulo']} {LOJA['nome']} enviou o contrato de locação da área de eventos do "
             f"{PARQUE['nome']} para a sua assinatura eletrônica:\n\n"
             f"  {resumo_evento(c['evento'])}\n  Valor: {fmt_moeda(c['evento'].get('valor_total'))}\n\n"
             f"Para conferir os dados, ler o contrato e assinar pelo celular, acesse:\n{link}\n\n"
             f"O link é pessoal e vale até {fmt_data(expira.date().isoformat())}. Na assinatura serão pedidas "
             "uma foto do rosto (selfie) e a sua assinatura na tela.\n\n"
             f"Dúvidas: responda a este e-mail.\n\n{LOJA['titulo']} {LOJA['nome']}\n{PARQUE['nome']}")
    ok, motivo = email_service.enviar([c["contratante_email"]], f"Contrato de locação para assinatura – {PARQUE['nome']}",
                                      texto)
    return link, ok, motivo


# ---------------------------------------------------------------- formulário do contrato

ENDERECO = ["cep", "logradouro", "numero", "complemento", "bairro", "cidade", "estado"]
QUALIFICACAO_PF = ["rg", "nacionalidade", "estado_civil", "profissao"]
REPRESENTANTE = ["nome", "cpf", "rg", "nacionalidade", "estado_civil", "profissao", "cargo"]


def _texto(form, campo, maiusculas=False, limite=150) -> str:
    t = " ".join((form.get(campo) or "").split())[:limite]
    return t.upper() if maiusculas else t


def _ler_contratante(form, erros: dict) -> dict:
    """Qualificação completa, preenchida pela gestão do Parque (cartão CNPJ e documentos)."""
    tipo = "PJ" if form.get("tipo_pessoa") == "PJ" else "PF"
    q = {"tipo_pessoa": tipo, "telefone": None}
    for campo in ENDERECO:
        q[campo] = _texto(form, campo, maiusculas=campo in ("logradouro", "bairro", "cidade", "complemento"))
    q["cep"] = so_digitos(q["cep"])
    q["estado"] = q["estado"].upper()
    for campo in ("cep", "logradouro", "numero", "bairro", "cidade", "estado"):
        if not q[campo]:
            erros[campo] = "Campo obrigatório."
    if q["cep"] and len(q["cep"]) != 8:
        erros["cep"] = "CEP com 8 números."
    if q["estado"] and q["estado"] not in UFS:
        erros["estado"] = "UF inválida."
    try:
        q["telefone"] = ler_telefone(form.get("telefone"))
        if not q["telefone"]:
            erros["telefone"] = "Campo obrigatório."
    except ValueError:
        q["telefone"] = _texto(form, "telefone")
        erros["telefone"] = "Telefone com DDD (ex.: 68 99999-9999)."
    if tipo == "PF":
        for campo in QUALIFICACAO_PF:
            q[campo] = _texto(form, campo)
            if not q[campo]:
                erros[campo] = "Campo obrigatório."
        if q["estado_civil"] and q["estado_civil"] not in ESTADOS_CIVIS:
            erros["estado_civil"] = "Escolha o estado civil."
    else:
        rep = {c: _texto(form, f"rep_{c}", maiusculas=c == "nome") for c in REPRESENTANTE}
        rep["cpf"] = so_digitos(rep["cpf"])
        for c in REPRESENTANTE:
            if not rep[c]:
                erros[f"rep_{c}"] = "Campo obrigatório."
        if rep["cpf"] and (len(rep["cpf"]) != 11 or not cpf_cnpj_valido(rep["cpf"])):
            erros["rep_cpf"] = "CPF inválido."
        if rep["estado_civil"] and rep["estado_civil"] not in ESTADOS_CIVIS:
            erros["rep_estado_civil"] = "Escolha o estado civil."
        q["representante"] = rep
    return q


def _ler_form(form) -> tuple[dict, dict]:
    erros = {}
    d = {"contratante_nome": " ".join((form.get("contratante_nome") or "").upper().split()),
         "contratante_cpf_cnpj": so_digitos(form.get("contratante_cpf_cnpj")),
         "registro": "padrao" if form.get("registro") == "padrao" else "vistoria"}
    d["exige_vistoria"] = 1 if d["registro"] == "vistoria" else 0
    d["contratante"] = _ler_contratante(form, erros)
    d["contratante"]["nome"] = d["contratante_nome"]
    pj = d["contratante"]["tipo_pessoa"] == "PJ"
    if not d["contratante_nome"]:
        erros["contratante_nome"] = "Informe a razão social." if pj else "Informe o nome completo."
    doc = d["contratante_cpf_cnpj"]
    if not cpf_cnpj_valido(doc) or len(doc) != (14 if pj else 11):
        erros["contratante_cpf_cnpj"] = "CNPJ inválido." if pj else "CPF inválido."
    try:
        d["contratante_email"] = ler_email(form.get("contratante_email"))
        if not d["contratante_email"]:
            erros["contratante_email"] = "Informe o e-mail do contratante (o link de assinatura vai para ele)."
    except ValueError:
        d["contratante_email"] = (form.get("contratante_email") or "").strip()
        erros["contratante_email"] = "E-mail inválido."
    ev = {"tipo_evento": " ".join((form.get("tipo_evento") or "").split())[:120] or None,
          "hora_inicio": (form.get("hora_inicio") or "").strip() or None,
          "hora_fim": (form.get("hora_fim") or "").strip() or None,
          "formas_pagamento": [f for f in FORMAS_PAGAMENTO if f in form.getlist("formas_pagamento")],
          "condicoes_pagamento": " ".join((form.get("condicoes_pagamento") or "").split())[:300] or None,
          "inclui_piscina": bool(form.get("inclui_piscina")),
          "tolerancia_min": form.get("tolerancia_min", type=int) if form.get("tolerancia_min", type=int) in TOLERANCIAS
          else TOLERANCIAS[0],
          "observacoes": (form.get("observacoes") or "").strip()[:1000] or None}
    try:
        ev["data"] = ler_data(form.get("data"))
    except ValueError:
        ev["data"] = None
    if not ev["data"]:
        erros["data"] = "Informe a data do evento."
    if not ev["tipo_evento"]:
        erros["tipo_evento"] = "Informe o tipo de evento (ex.: casamento, aniversário)."
    if not (ev["hora_inicio"] and ev["hora_fim"]):
        erros["horario"] = "Informe o horário de início e de fim."
    try:
        ev["valor_total"] = ler_moeda(form.get("valor_total"))
        if ev["valor_total"] is None:
            erros["valor_total"] = "Informe o valor total."
    except ValueError:
        ev["valor_total"] = None
        erros["valor_total"] = "Valor inválido."
    if not ev["formas_pagamento"]:
        erros["formas_pagamento"] = "Marque ao menos uma forma de pagamento."
    d["evento"] = ev
    return d, erros


def _novo_codigo() -> str:
    while True:
        bruto = "".join(secrets.choice(ALFABETO_CODIGO) for _ in range(8))
        codigo = f"IGA-{bruto[:4]}-{bruto[4:]}"
        if not get_db().execute("SELECT 1 FROM contrato WHERE codigo_verificador = ?", (codigo,)).fetchone():
            return codigo


# ---------------------------------------------------------------- telas

@bp.route("/")
@parque_required
def lista():
    filtro = request.args.get("status", "")
    busca = " ".join((request.args.get("q") or "").split())
    de, ate = (request.args.get("de") or "").strip(), (request.args.get("ate") or "").strip()
    sql = "SELECT * FROM contrato"
    params = []
    if filtro in STATUS:
        sql += " WHERE status = ?"
        params.append(filtro)
    contratos = [detalhar(c) for c in get_db().execute(sql + " ORDER BY id DESC", params)]
    if busca:
        # nome/razão social (sem distinguir maiúsculas) ou CPF/CNPJ (com ou sem pontuação)
        termo, digitos = busca.upper(), so_digitos(busca)
        contratos = [c for c in contratos
                     if termo in c["contratante_nome"].upper()
                     or (digitos and len(digitos) >= 3 and digitos in c["contratante_cpf_cnpj"])]
    if de:
        contratos = [c for c in contratos if (c["evento"].get("data") or "") >= de]
    if ate:
        contratos = [c for c in contratos if (c["evento"].get("data") or "") <= ate]
    contratos.sort(key=lambda c: (c["status"] in (ASSINADO, CANCELADO), c["evento"].get("data") or ""))
    return render_template("parque/lista.html", contratos=contratos, filtro=filtro, STATUS=STATUS,
                           busca=busca, de=de, ate=ate, filtrando=bool(busca or de or ate),
                           codigo_definido=codigo_caseiro_definido(), email_ok=email_service.configurado(),
                           pendencias=pendencias_liberacao())


@bp.route("/novo", methods=["GET", "POST"])
@bp.route("/<int:contrato_id>/editar", methods=["GET", "POST"])
@parque_required
def form(contrato_id=None):
    atual = detalhar(buscar(contrato_id)) if contrato_id else None
    if atual and atual["status"] in (ASSINADO, CANCELADO):
        flash("Contrato assinado ou cancelado não pode ser alterado.", "erro")
        return redirect(url_for("parque.detalhe", contrato_id=contrato_id))
    erros = {}
    if request.method == "POST":
        d, erros = _ler_form(request.form)
        usa_padrao = d["registro"] == "padrao" if atual is None else bool(atual["fotos_padrao"])
        piscina = bool(d["evento"]["inclui_piscina"])
        if usa_padrao and (faltam := padroes_faltando(piscina)):
            erros["registro"] = ("Para usar as fotos padrão, cadastre antes a foto padrão de: " + ", ".join(faltam)
                                 + " (Parque → Configuração). Ou escolha a vistoria pelo caseiro.")
        if not erros and atual is None and usa_padrao and (pend := pendencias_liberacao()):
            # com fotos padrão o link sai ao salvar: a LOCADORA precisa estar pronta antes
            erros["locadora"] = "Para enviar o contrato ao contratante, falta " + "; ".join(pend) + "."
        if not erros:
            db = get_db()
            evento_json = json.dumps(d["evento"], ensure_ascii=False)
            contratante_json = json.dumps(d["contratante"], ensure_ascii=False)
            if atual is None:
                cur = db.execute(
                    "INSERT INTO contrato (codigo_verificador, status, exige_vistoria, fotos_padrao, contratante_nome, "
                    "contratante_cpf_cnpj, contratante_email, contratante_dados_json, evento_dados_json, "
                    "criado_em, criado_por) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (_novo_codigo(), AGUARDANDO_VISTORIA, d["exige_vistoria"], int(usa_padrao), d["contratante_nome"],
                     d["contratante_cpf_cnpj"], d["contratante_email"], contratante_json, evento_json,
                     iso(agora_utc()), current_user.id))
                db.commit()
                novo_id = cur.lastrowid
                if usa_padrao:
                    copiar_fotos_padrao(novo_id)
                    _liberar(novo_id)
                else:
                    flash("Contrato cadastrado. Ele aparece na fila de vistoria do caseiro; o link de assinatura "
                          "será enviado ao contratante quando a vistoria for concluída.", "ok")
                return redirect(url_for("parque.detalhe", contrato_id=novo_id))
            # edição: dados mudaram → o PDF de leitura será refeito
            db.execute("UPDATE contrato SET contratante_nome = ?, contratante_cpf_cnpj = ?, contratante_email = ?, "
                       "contratante_dados_json = ?, evento_dados_json = ?, pdf_pre_arquivo = NULL, "
                       "hash_pre_assinatura = NULL WHERE id = ?",
                       (d["contratante_nome"], d["contratante_cpf_cnpj"], d["contratante_email"], contratante_json,
                        evento_json, contrato_id))
            db.commit()
            apagar_arquivo(atual["pdf_pre_arquivo"])
            if usa_padrao and bool(atual["evento"].get("inclui_piscina")) != piscina:
                copiar_fotos_padrao(contrato_id)  # com/sem piscina muda as fotos exigidas
            flash("Contrato atualizado.", "ok")
            return redirect(url_for("parque.detalhe", contrato_id=contrato_id))
        flash("Corrija os campos destacados.", "erro")
        valores = d | d["evento"] | _valores_contratante(d["contratante"])
    elif atual:
        valores = atual | atual["evento"] | _valores_contratante(atual["contratante"])
        valores["valor_total"] = fmt_moeda(atual["evento"].get("valor_total"), simbolo=False)
    else:
        valores = {"registro": "padrao" if not padroes_faltando(False) else "vistoria",
                   "tipo_pessoa": "PF", "nacionalidade": "Brasileira",
                   "rep_nacionalidade": "Brasileira", "hora_inicio": HORARIO_PADRAO[0], "hora_fim": HORARIO_PADRAO[1],
                   "tolerancia_min": TOLERANCIAS[0], "formas_pagamento": ["Pix"], "condicoes_pagamento": "À vista"}
    if request.method == "POST" and isinstance(valores.get("valor_total"), int):
        valores["valor_total"] = fmt_moeda(valores["valor_total"], simbolo=False)
    if valores.get("contratante_cpf_cnpj"):
        valores["contratante_cpf_cnpj"] = fmt_cpf_cnpj(valores["contratante_cpf_cnpj"])
    if valores.get("rep_cpf"):
        valores["rep_cpf"] = fmt_cpf_cnpj(valores["rep_cpf"])
    return render_template("parque/form.html", v=valores, erros=erros, contrato=atual, UFS=UFS,
                           ESTADOS_CIVIS=ESTADOS_CIVIS, FORMAS_PAGAMENTO=FORMAS_PAGAMENTO, TOLERANCIAS=TOLERANCIAS,
                           faltam_sem_piscina=padroes_faltando(False), faltam_com_piscina=padroes_faltando(True))


def _valores_contratante(q: dict) -> dict:
    """Achata a qualificação para os campos do formulário (representante → rep_*)."""
    v = {k: val for k, val in (q or {}).items() if k != "representante"}
    v.setdefault("tipo_pessoa", "PF")
    for k, val in ((q or {}).get("representante") or {}).items():
        v[f"rep_{k}"] = val
    return v


def _liberar(contrato_id) -> bool:
    """Libera para assinatura avisando o resultado; com pendência da LOCADORA, explica o que falta."""
    try:
        _avisar_liberacao(contrato_id, *liberar_para_assinatura(contrato_id))
        return True
    except PendenciaLocadora as p:
        flash("O contrato não foi liberado. Falta " + "; ".join(p.pendencias) + ".", "erro")
        return False


def _avisar_liberacao(contrato_id, link, enviou, motivo):
    if enviou:
        flash("Link de assinatura enviado por e-mail ao contratante (válido por 7 dias).", "ok")
    else:
        flash(f"O link de assinatura foi gerado, mas o e-mail não foi enviado ({motivo}). "
              "Copie o link na tela do contrato e envie ao contratante.", "aviso")


@bp.route("/<int:contrato_id>")
@parque_required
def detalhe(contrato_id):
    c = detalhar(buscar(contrato_id))
    link = url_externa("assinatura.inicio", token=c["token_assinatura"]) \
        if c["status"] == AGUARDANDO_ASSINATURA and c["token_assinatura"] else None
    evid = get_db().execute("SELECT * FROM assinatura_evidencia WHERE contrato_id = ?", (contrato_id,)).fetchone()
    evento = c["evento"]
    return render_template("parque/detalhe.html", c=c, fotos=fotos_da_vistoria(contrato_id), link=link,
                           padroes_faltando=padroes_faltando(bool(evento.get("inclui_piscina"))),
                           evid=evid, email_ok=email_service.configurado(), pendencias=pendencias_liberacao(),
                           url_validacao=url_externa("assinatura.validar", codigo=c["codigo_verificador"]))


@bp.route("/<int:contrato_id>/reenviar", methods=["POST"])
@parque_required
def reenviar(contrato_id):
    c = buscar(contrato_id)
    if c["status"] != AGUARDANDO_ASSINATURA:
        flash("Só é possível reenviar o link de um contrato aguardando assinatura.", "erro")
    elif _liberar(contrato_id):
        flash("Um novo link foi gerado; o anterior deixou de valer.", "aviso")
    return redirect(url_for("parque.detalhe", contrato_id=contrato_id))


@bp.route("/<int:contrato_id>/liberar", methods=["POST"])
@parque_required
def liberar_sem_vistoria(contrato_id):
    """Libera para assinatura um contrato que aguardava vistoria: com as fotos padrão no lugar da vistoria,
    ou já com a vistoria concluída (quando ainda faltava algo da LOCADORA)."""
    c = buscar(contrato_id)
    if c["status"] != AGUARDANDO_VISTORIA:
        abort(400)
    if not c["vistoria_concluida_em"]:
        evento = json.loads(c["evento_dados_json"] or "{}")
        if (faltam := padroes_faltando(bool(evento.get("inclui_piscina")))):
            flash("Para usar as fotos padrão, cadastre antes a foto padrão de: " + ", ".join(faltam) + ".", "erro")
            return redirect(url_for("parque.detalhe", contrato_id=contrato_id))
        if pendencias_liberacao():
            _liberar(contrato_id)  # só explica o que falta da LOCADORA
            return redirect(url_for("parque.detalhe", contrato_id=contrato_id))
        get_db().execute("UPDATE contrato SET fotos_padrao = 1, exige_vistoria = 0 WHERE id = ?", (contrato_id,))
        get_db().commit()
        copiar_fotos_padrao(contrato_id)
    _liberar(contrato_id)
    return redirect(url_for("parque.detalhe", contrato_id=contrato_id))


@bp.route("/<int:contrato_id>/cancelar", methods=["POST"])
@parque_required
def cancelar(contrato_id):
    c = buscar(contrato_id)
    motivo = " ".join((request.form.get("motivo") or "").split())[:300]
    if c["status"] in (ASSINADO, CANCELADO):
        flash("Contrato assinado ou já cancelado.", "erro")
    elif not motivo:
        flash("Informe o motivo do cancelamento.", "erro")
    else:
        get_db().execute("UPDATE contrato SET status = ?, cancelado_em = ?, motivo_cancelamento = ?, "
                         "token_assinatura = NULL WHERE id = ?", (CANCELADO, iso(agora_utc()), motivo, contrato_id))
        get_db().commit()
        flash("Contrato cancelado. O link de assinatura deixou de valer.", "ok")
    return redirect(url_for("parque.detalhe", contrato_id=contrato_id))


@bp.route("/<int:contrato_id>/contrato-assinado.pdf")
@parque_required
def pdf_final(contrato_id):
    c = buscar(contrato_id)
    dados = ler_arquivo(c["pdf_final_arquivo"])
    if not dados:
        abort(404)
    import io
    return send_file(io.BytesIO(dados), mimetype="application/pdf", as_attachment=False,
                     download_name=f"contrato-{c['codigo_verificador']}.pdf")


@bp.route("/<int:contrato_id>/foto/<int:foto_id>")
@parque_required
def foto(contrato_id, foto_id):
    return enviar_foto(contrato_id, foto_id)


def enviar_foto(contrato_id, foto_id):
    import io
    f = get_db().execute("SELECT arquivo FROM vistoria_foto WHERE id = ? AND contrato_id = ?",
                         (foto_id, contrato_id)).fetchone()
    dados = ler_arquivo(f["arquivo"]) if f else None
    if not dados:
        abort(404)
    resp = send_file(io.BytesIO(dados), mimetype="image/jpeg")
    resp.headers["Cache-Control"] = "private, max-age=3600"
    return resp


def _ir_configuracao(secao: str = ""):
    return redirect(url_for("parque.configuracao") + (f"#{secao}" if secao else ""))


@bp.route("/configuracao", methods=["GET", "POST"])
@parque_required
def configuracao():
    if request.method == "POST":
        codigo = so_digitos(request.form.get("codigo"))
        if len(codigo) != 6:
            flash("O código do caseiro deve ter 6 números.", "erro")
        elif codigo != so_digitos(request.form.get("confirmacao")):
            flash("A confirmação não confere com o código.", "erro")
        else:
            definir_codigo_caseiro(codigo)
            flash("Código de acesso do caseiro atualizado. Informe o novo código a ele.", "ok")
            return _ir_configuracao("codigo")
    gestao, ven = veneravel_vigente()
    assinatura = assinatura_da_gestao(gestao["id"]) if gestao else None
    locadora, pendencias = representante_locadora()
    return render_template("parque/configuracao.html", codigo_definido=codigo_caseiro_definido(),
                           url_vistoria=url_externa("vistoria.entrar"), email_ok=email_service.configurado(),
                           tipos=tipos_vistoria(somente_ativos=False), gestao=gestao, ven=ven,
                           assinatura=assinatura, locadora=locadora, pendencias=pendencias,
                           sou_veneravel=bool(ven and ven["obreiro_id"] == current_user.id))


# ---------------------------------------------------------------- tipos de foto da vistoria

@bp.route("/configuracao/tipos", methods=["POST"])
@parque_required
def tipo_novo():
    nome = " ".join((request.form.get("nome") or "").split())[:60]
    db = get_db()
    if not nome:
        flash("Informe o nome do tipo de foto.", "erro")
    elif db.execute("SELECT 1 FROM vistoria_tipo WHERE lower(nome) = lower(?)", (nome,)).fetchone():
        flash(f"Já existe o tipo \"{nome}\".", "erro")
    else:
        ordem = (db.execute("SELECT MAX(ordem) FROM vistoria_tipo").fetchone()[0] or 0) + 1
        db.execute("INSERT INTO vistoria_tipo (nome, ordem) VALUES (?, ?)", (nome, ordem))
        db.commit()
        flash(f"Tipo \"{nome}\" incluído. Ele passa a ser exigido nas próximas vistorias.", "ok")
    return _ir_configuracao("tipos")


@bp.route("/configuracao/tipos/<int:tipo_id>", methods=["POST"])
@parque_required
def tipo_alterar(tipo_id):
    db = get_db()
    t = db.execute("SELECT * FROM vistoria_tipo WHERE id = ?", (tipo_id,)).fetchone()
    if t is None:
        abort(404)
    acao = request.form.get("acao")
    if acao in ("subir", "descer"):
        tipos = list(tipos_vistoria(somente_ativos=False))
        i = next(n for n, x in enumerate(tipos) if x["id"] == tipo_id)
        j = i - 1 if acao == "subir" else i + 1
        if 0 <= j < len(tipos):
            tipos[i], tipos[j] = tipos[j], tipos[i]
            db.executemany("UPDATE vistoria_tipo SET ordem = ? WHERE id = ?",
                           [(n, x["id"]) for n, x in enumerate(tipos, start=1)])
    elif acao in ("piscina_sim", "piscina_nao"):
        db.execute("UPDATE vistoria_tipo SET so_com_piscina = ? WHERE id = ?", (int(acao == "piscina_sim"), tipo_id))
        flash(f"\"{t['nome']}\" agora é exigido " + ("só nos contratos com piscina." if acao == "piscina_sim"
                                                       else "em todas as vistorias."), "ok")
    elif acao == "ativar":
        db.execute("UPDATE vistoria_tipo SET ativo = 1 WHERE id = ?", (tipo_id,))
        flash(f"\"{t['nome']}\" voltou a ser exigido nas vistorias.", "ok")
    elif acao == "desativar":
        db.execute("UPDATE vistoria_tipo SET ativo = 0 WHERE id = ?", (tipo_id,))
        flash(f"\"{t['nome']}\" deixou de ser exigido. As fotos já tiradas continuam nos contratos.", "ok")
    elif acao == "renomear":
        nome = " ".join((request.form.get("nome") or "").split())[:60]
        if not nome:
            flash("Informe o nome do tipo de foto.", "erro")
        elif db.execute("SELECT 1 FROM vistoria_tipo WHERE lower(nome) = lower(?) AND id <> ?",
                        (nome, tipo_id)).fetchone():
            flash(f"Já existe o tipo \"{nome}\".", "erro")
        else:
            db.execute("UPDATE vistoria_tipo SET nome = ? WHERE id = ?", (nome, tipo_id))
            flash("Nome do tipo atualizado.", "ok")
    db.commit()
    return _ir_configuracao("tipos")


@bp.route("/configuracao/tipos/<int:tipo_id>/foto", methods=["POST"])
@parque_required
def tipo_foto(tipo_id):
    """Cadastra, troca ou remove a foto padrão de um tipo."""
    from .vistoria import comprimir
    db = get_db()
    t = db.execute("SELECT * FROM vistoria_tipo WHERE id = ?", (tipo_id,)).fetchone()
    if t is None:
        abort(404)
    if request.form.get("acao") == "remover":
        db.execute("UPDATE vistoria_tipo SET foto_padrao = NULL, foto_padrao_em = ? WHERE id = ?",
                   (iso(agora_utc()), tipo_id))
        db.commit()
        apagar_arquivo(t["foto_padrao"])
        flash(f"Foto padrão de \"{t['nome']}\" removida.", "ok")
        return _ir_configuracao("tipos")
    arquivo = request.files.get("foto")
    if not arquivo or not arquivo.filename:
        flash("Escolha a foto.", "erro")
        return _ir_configuracao("tipos")
    try:
        definir_foto_padrao(tipo_id, comprimir(arquivo))
    except ValueError:
        flash("O arquivo enviado não é uma imagem.", "erro")
        return _ir_configuracao("tipos")
    flash(f"Foto padrão de \"{t['nome']}\" atualizada.", "ok")
    return _ir_configuracao("tipos")


@bp.route("/configuracao/tipos/<int:tipo_id>/foto.jpg")
@parque_required
def tipo_foto_ver(tipo_id):
    return enviar_foto_padrao(tipo_id)


def enviar_foto_padrao(tipo_id: int):
    import io
    t = get_db().execute("SELECT foto_padrao FROM vistoria_tipo WHERE id = ?", (tipo_id,)).fetchone()
    dados = ler_arquivo(t["foto_padrao"]) if t else None
    if not dados:
        abort(404)
    resp = send_file(io.BytesIO(dados), mimetype="image/jpeg")
    resp.headers["Cache-Control"] = "private, max-age=3600"
    return resp


# ---------------------------------------------------------------- assinatura padronizada da LOCADORA

@bp.route("/configuracao/assinatura", methods=["POST"])
@parque_required
def assinatura_locadora():
    """O Venerável da gestão vigente desenha a assinatura que vai nos contratos da gestão dele."""
    from .assinatura import _imagem_data_url, _rubrica_tem_traco
    gestao, ven = veneravel_vigente()
    if not (gestao and ven and ven["obreiro_id"] == current_user.id):
        flash("Somente o Venerável da gestão atual pode cadastrar a assinatura da LOCADORA.", "erro")
        return _ir_configuracao("assinatura")
    try:
        png = _imagem_data_url(request.form.get("assinatura"), "PNG")
        if not _rubrica_tem_traco(png):
            raise ValueError("vazia")
    except ValueError:
        flash("Faça a assinatura no quadro antes de salvar.", "erro")
        return _ir_configuracao("assinatura")
    db = get_db()
    anterior = assinatura_da_gestao(gestao["id"])
    rel, sha = salvar_arquivo("locadora", f"gestao_{gestao['id']}_{secrets.token_hex(4)}.png", png)
    db.execute("INSERT INTO assinatura_locadora (gestao_id, obreiro_id, nome, arquivo, sha256, criado_em) "
               "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(gestao_id) DO UPDATE SET obreiro_id = excluded.obreiro_id, "
               "nome = excluded.nome, arquivo = excluded.arquivo, sha256 = excluded.sha256, "
               "criado_em = excluded.criado_em",
               (gestao["id"], current_user.id, ven["nome"], rel, sha, iso(agora_utc())))
    db.commit()
    if anterior:
        # contratos já liberados guardam o caminho do arquivo deles; só apaga se nenhum usar
        em_uso = db.execute("SELECT 1 FROM contrato WHERE locadora_json LIKE ? LIMIT 1",
                            (f'%{anterior["arquivo"]}%',)).fetchone()
        if not em_uso:
            apagar_arquivo(anterior["arquivo"])
    flash("Assinatura da LOCADORA salva. Ela vai nos próximos contratos liberados para assinatura.", "ok")
    return _ir_configuracao("assinatura")


@bp.route("/configuracao/assinatura.png")
@parque_required
def assinatura_locadora_png():
    import io
    gestao, _ven = veneravel_vigente()
    a = assinatura_da_gestao(gestao["id"]) if gestao else None
    dados = ler_arquivo(a["arquivo"]) if a else None
    if not dados:
        abort(404)
    return send_file(io.BytesIO(dados), mimetype="image/png")
