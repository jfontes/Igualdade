"""Assinatura eletrônica do contrato pelo contratante (link público) e validação pública (QR Code).

Fluxo do link /assinar/<token> (válido por 7 dias, de uso único):
  1. Qualificação (dados complementares do contratante)
  2. Leitura do contrato em PDF (com o Anexo I da vistoria); registra o SHA-256 pré-assinatura
  3. Selfie em tempo real (câmera frontal) + assinatura manuscrita na tela + telemetria
  → PDF consolidado (rubrica, anexo e manifesto com QR Code), SHA-256 final, e-mails.

A selfie não é guardada à parte: entra só no PDF assinado e é descartada (fica apenas o hash).
"""
import base64
import binascii
import hashlib
import io
import json

from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, url_for
from PIL import Image, UnidentifiedImageError

from . import contrato_pdf, email_service
from .config import LOJA, PARQUE
from .db import get_db
from .parque import (AGUARDANDO_ASSINATURA, ASSINADO, agora_utc, apagar_arquivo, detalhar, fotos_da_vistoria,
                     iso, ler_arquivo, resumo_evento, salvar_arquivo, url_externa)
from .util import (UFS, cpf_cnpj_valido, fmt_cpf_cnpj, fmt_moeda, ler_email, ler_telefone, mascarar_doc,
                   mascarar_nome, so_digitos)

UFS_CONTRATO = UFS
from .vistoria import ip_cliente

bp = Blueprint("assinatura", __name__)

ESTADOS_CIVIS = ["Solteiro(a)", "Casado(a)", "União estável", "Separado(a)", "Divorciado(a)", "Viúvo(a)"]
CAMPOS_OBRIGATORIOS = ["rg", "nacionalidade", "estado_civil", "profissao", "telefone", "cep", "logradouro",
                       "numero", "bairro", "cidade", "estado"]
MAX_IMAGEM = 3 * 1024 * 1024  # bytes de cada imagem recebida (selfie / rubrica)


# ---------------------------------------------------------------- acesso pelo token

def _contrato_do_token(token: str, permitir_assinado: bool = False):
    """Devolve (contrato, resposta). Se `resposta` não for None, a rota deve devolvê-la."""
    c = get_db().execute("SELECT * FROM contrato WHERE token_assinatura = ?", (token,)).fetchone() if token else None
    if c is None:
        return None, (render_template("assinar/indisponivel.html", motivo="invalido"), 404)
    c = detalhar(c)
    if c["status"] == ASSINADO:
        if permitir_assinado:
            return c, None
        return None, redirect(url_for("assinatura.concluido", token=token))
    if c["status"] != AGUARDANDO_ASSINATURA:
        return None, (render_template("assinar/indisponivel.html", motivo="cancelado"), 410)
    if c["link_expirado"]:
        return None, (render_template("assinar/indisponivel.html", motivo="expirado"), 410)
    return c, None


def _passos(c) -> int:
    """Último passo liberado: 1 qualificação, 2 leitura, 3 assinatura."""
    if not c["contratante"]:
        return 1
    return 3 if c["hash_pre_assinatura"] else 2


@bp.route("/assinar/<token>")
def inicio(token):
    c, resp = _contrato_do_token(token)
    if resp:
        return resp
    return redirect(url_for("assinatura.dados" if _passos(c) == 1 else "assinatura.leitura", token=token))


# ---------------------------------------------------------------- passo 1: qualificação

@bp.route("/assinar/<token>/dados", methods=["GET", "POST"])
def dados(token):
    c, resp = _contrato_do_token(token)
    if resp:
        return resp
    erros = {}
    if request.method == "POST":
        f = request.form
        v = {k: " ".join((f.get(k) or "").split()) for k in
             ["nome", "rg", "nacionalidade", "estado_civil", "profissao", "telefone", "cep", "logradouro", "numero",
              "complemento", "bairro", "cidade", "estado"]}
        v["nome"] = v["nome"].upper()
        doc = so_digitos(f.get("cpf_cnpj"))
        if not v["nome"]:
            erros["nome"] = "Informe o nome completo ou a razão social."
        if not cpf_cnpj_valido(doc):
            erros["cpf_cnpj"] = "CPF ou CNPJ inválido."
        try:
            email = ler_email(f.get("email"))
            if not email:
                erros["email"] = "Informe o e-mail (a cópia do contrato assinado vai para ele)."
        except ValueError:
            email = (f.get("email") or "").strip()
            erros["email"] = "E-mail inválido."
        for campo in CAMPOS_OBRIGATORIOS:
            if not v[campo]:
                erros[campo] = "Campo obrigatório."
        if v["telefone"]:
            try:
                v["telefone"] = ler_telefone(v["telefone"])
            except ValueError:
                erros["telefone"] = "Telefone com DDD (ex.: 68 99999-9999)."
        if v["cep"] and len(so_digitos(v["cep"])) != 8:
            erros["cep"] = "CEP com 8 números."
        if v["estado"] and v["estado"].upper() not in UFS_CONTRATO:
            erros["estado"] = "UF inválida."
        if not erros:
            v["cep"] = so_digitos(v["cep"])
            v["estado"] = v["estado"].upper()
            db = get_db()
            db.execute("UPDATE contrato SET contratante_nome = ?, contratante_cpf_cnpj = ?, contratante_email = ?, "
                       "contratante_dados_json = ?, pdf_pre_arquivo = NULL, hash_pre_assinatura = NULL, "
                       "campo_assinatura_json = NULL WHERE id = ?",
                       (v["nome"], doc, email, json.dumps(v, ensure_ascii=False), c["id"]))
            db.commit()
            apagar_arquivo(c["pdf_pre_arquivo"])
            return redirect(url_for("assinatura.leitura", token=token))
        flash("Confira os campos destacados.", "erro")
        valores = v | {"cpf_cnpj": f.get("cpf_cnpj"), "email": email}
    else:
        valores = (c["contratante"] or {}) | {"nome": c["contratante_nome"],
                                              "cpf_cnpj": fmt_cpf_cnpj(c["contratante_cpf_cnpj"]),
                                              "email": c["contratante_email"]}
        valores.setdefault("nacionalidade", "Brasileira")
    return render_template("assinar/dados.html", c=c, v=valores, erros=erros, token=token, passo=1,
                           ESTADOS_CIVIS=ESTADOS_CIVIS, UFS=UFS_CONTRATO)


# ---------------------------------------------------------------- passo 2: leitura

def _garantir_pdf_leitura(c) -> dict:
    """Gera (se preciso) o PDF que o contratante lê e registra o SHA-256 pré-assinatura."""
    if c["pdf_pre_arquivo"] and c["hash_pre_assinatura"] and ler_arquivo(c["pdf_pre_arquivo"]):
        return c
    fotos = [ler_arquivo(f["arquivo"]) for f in fotos_da_vistoria(c["id"])]
    pdf, campo = contrato_pdf.pdf_para_leitura(c, c["contratante"], c["evento"], [f for f in fotos if f])
    rel, sha = salvar_arquivo(c["id"], "contrato_para_leitura.pdf", pdf)
    get_db().execute("UPDATE contrato SET pdf_pre_arquivo = ?, hash_pre_assinatura = ?, campo_assinatura_json = ? "
                     "WHERE id = ?", (rel, sha, json.dumps(campo), c["id"]))
    get_db().commit()
    return c | {"pdf_pre_arquivo": rel, "hash_pre_assinatura": sha, "campo_assinatura_json": json.dumps(campo)}


@bp.route("/assinar/<token>/leitura")
def leitura(token):
    c, resp = _contrato_do_token(token)
    if resp:
        return resp
    if _passos(c) == 1:
        return redirect(url_for("assinatura.dados", token=token))
    c = _garantir_pdf_leitura(c)
    return render_template("assinar/leitura.html", c=c, token=token, passo=2,
                           qtd_fotos=len(fotos_da_vistoria(c["id"])))


@bp.route("/assinar/<token>/contrato.pdf")
def pdf_leitura(token):
    c, resp = _contrato_do_token(token)
    if resp:
        return resp
    dados_pdf = ler_arquivo(c["pdf_pre_arquivo"])
    if not dados_pdf:
        return redirect(url_for("assinatura.leitura", token=token))
    return send_file(io.BytesIO(dados_pdf), mimetype="application/pdf",
                     download_name=f"contrato-{c['codigo_verificador']}-para-leitura.pdf")


# ---------------------------------------------------------------- passo 3: selfie + assinatura

def _imagem_data_url(valor: str | None, formato: str) -> bytes:
    """'data:image/jpeg;base64,...' → bytes, validando o formato com o Pillow."""
    if not valor or "," not in valor:
        raise ValueError("ausente")
    try:
        dados_img = base64.b64decode(valor.split(",", 1)[1], validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("inválida")
    if not dados_img or len(dados_img) > MAX_IMAGEM:
        raise ValueError("tamanho inválido")
    try:
        img = Image.open(io.BytesIO(dados_img))
        img.load()
    except (UnidentifiedImageError, OSError):
        raise ValueError("inválida")
    if img.format != formato:
        raise ValueError("formato inválido")
    return dados_img


def _rubrica_tem_traco(png: bytes) -> bool:
    img = Image.open(io.BytesIO(png)).convert("RGBA")
    opacos = sum(1 for a in img.getchannel("A").getdata() if a > 40)
    return opacos > 150


@bp.route("/assinar/<token>/assinar", methods=["GET", "POST"])
def assinar(token):
    c, resp = _contrato_do_token(token)
    if resp:
        return resp
    if _passos(c) < 3:
        if request.method == "POST" and request.form.get("hash_pre"):
            flash("O contrato foi atualizado depois que você o abriu. Leia a versão atual antes de assinar.", "erro")
        return redirect(url_for("assinatura.inicio", token=token))
    if request.method == "GET":
        return render_template("assinar/assinar.html", c=c, token=token, passo=3)

    f = request.form
    erros = []
    if f.get("hash_pre") != c["hash_pre_assinatura"]:
        erros.append("O contrato foi atualizado depois que você o abriu. Leia a versão atual antes de assinar.")
    if not (f.get("li_contrato") and f.get("consentimento")):
        erros.append("Marque as duas confirmações (leitura do contrato e uso da foto).")
    try:
        selfie = _imagem_data_url(f.get("selfie"), "JPEG")
    except ValueError:
        selfie = None
        erros.append("Tire a foto do rosto (selfie) pela câmera do aparelho.")
    try:
        rubrica = _imagem_data_url(f.get("assinatura"), "PNG")
        if not _rubrica_tem_traco(rubrica):
            raise ValueError("vazia")
    except ValueError:
        rubrica = None
        erros.append("Faça a sua assinatura no quadro.")
    if erros:
        for e in erros:
            flash(e, "erro")
        return redirect(url_for("assinatura.leitura" if "atualizado" in erros[0] else "assinatura.assinar", token=token))

    agora = agora_utc()
    pdf_leitura_bytes = ler_arquivo(c["pdf_pre_arquivo"])
    if not pdf_leitura_bytes or contrato_pdf.sha256(pdf_leitura_bytes) != c["hash_pre_assinatura"]:
        abort(409)
    traco = (f.get("traco") or "")[:200_000]
    geo = " ".join((f.get("geolocalizacao") or "").split())[:120] or None
    dados_manifesto = {
        "codigo": c["codigo_verificador"],
        "url_validacao": url_externa("assinatura.validar", codigo=c["codigo_verificador"]),
        "contratante_nome": c["contratante_nome"], "contratante_doc": fmt_cpf_cnpj(c["contratante_cpf_cnpj"]),
        "contratante_email": c["contratante_email"], "evento_resumo": resumo_evento(c["evento"]),
        "hash_pre": c["hash_pre_assinatura"], "ip": ip_cliente(),
        "user_agent": (request.headers.get("User-Agent") or "")[:300], "geolocalizacao": geo,
        "timestamp_utc": iso(agora),
    }
    final = contrato_pdf.pdf_assinado(pdf_leitura_bytes, json.loads(c["campo_assinatura_json"]), rubrica, selfie,
                                      dados_manifesto)
    db = get_db()
    # grava só se o contrato ainda estiver aguardando (evita assinatura dupla por clique repetido)
    cur = db.execute("UPDATE contrato SET status = ?, assinado_em = ? WHERE id = ? AND status = ?",
                     (ASSINADO, iso(agora), c["id"], AGUARDANDO_ASSINATURA))
    if cur.rowcount != 1:
        db.rollback()
        return redirect(url_for("assinatura.concluido", token=token))
    rel_pdf, hash_final = salvar_arquivo(c["id"], f"contrato-{c['codigo_verificador']}-assinado.pdf", final)
    rel_png, hash_png = salvar_arquivo(c["id"], "assinatura.png", rubrica)
    db.execute("UPDATE contrato SET pdf_final_arquivo = ?, hash_final_sha256 = ?, tamanho_final_bytes = ? WHERE id = ?",
               (rel_pdf, hash_final, len(final), c["id"]))
    db.execute("INSERT INTO assinatura_evidencia (contrato_id, selfie_sha256, assinatura_arquivo, assinatura_sha256, "
               "traco_vetorial_json, ip_address, user_agent, geolocalizacao, timestamp_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
               (c["id"], hashlib.sha256(selfie).hexdigest(), rel_png, hash_png, traco, dados_manifesto["ip"],
                dados_manifesto["user_agent"], geo, iso(agora)))
    db.commit()
    del selfie  # a selfie só existe dentro do PDF assinado

    texto = (f"Contrato de locação assinado eletronicamente.\n\n"
             f"Contratante: {c['contratante_nome']}\nEvento: {resumo_evento(c['evento'])}\n"
             f"Valor: {fmt_moeda(c['evento'].get('valor_total'))}\n"
             f"Código verificador: {c['codigo_verificador']}\nSHA-256 do PDF: {hash_final}\n\n"
             f"Validação pública: {dados_manifesto['url_validacao']}\n\n"
             f"O contrato assinado segue em anexo.\n\n{LOJA['titulo']} {LOJA['nome']}\n{PARQUE['nome']}")
    email_service.enviar([c["contratante_email"], email_service.email_locador()],
                         f"Contrato assinado – {PARQUE['nome']} – {c['codigo_verificador']}", texto,
                         [(f"contrato-{c['codigo_verificador']}.pdf", final, "application/pdf")])
    return redirect(url_for("assinatura.concluido", token=token))


@bp.route("/assinar/<token>/concluido")
def concluido(token):
    c, resp = _contrato_do_token(token, permitir_assinado=True)
    if resp:
        return resp
    if c["status"] != ASSINADO:
        return redirect(url_for("assinatura.inicio", token=token))
    return render_template("assinar/concluido.html", c=c, token=token, email_ok=email_service.configurado(),
                           url_validacao=url_externa("assinatura.validar", codigo=c["codigo_verificador"]))


@bp.route("/assinar/<token>/contrato-assinado.pdf")
def pdf_assinado(token):
    c, resp = _contrato_do_token(token, permitir_assinado=True)
    if resp:
        return resp
    dados_pdf = ler_arquivo(c["pdf_final_arquivo"]) if c["status"] == ASSINADO else None
    if not dados_pdf:
        abort(404)
    return send_file(io.BytesIO(dados_pdf), mimetype="application/pdf", as_attachment=True,
                     download_name=f"contrato-{c['codigo_verificador']}-assinado.pdf")


# ---------------------------------------------------------------- validação pública

@bp.route("/validar", methods=["GET", "POST"])
@bp.route("/validar/<codigo>", methods=["GET", "POST"])
def validar(codigo=None):
    if codigo is None and request.values.get("codigo"):
        return redirect(url_for("assinatura.validar", codigo=request.values["codigo"].strip().upper()))
    c = None
    conferencia = None
    if codigo:
        row = get_db().execute("SELECT * FROM contrato WHERE codigo_verificador = ?", (codigo.upper(),)).fetchone()
        c = detalhar(row) if row else None
        if c and request.method == "POST":
            arquivo = request.files.get("pdf")
            if arquivo and arquivo.filename:
                hash_enviado = hashlib.sha256(arquivo.read()).hexdigest()  # não é gravado
                conferencia = {"hash": hash_enviado, "confere": hash_enviado == c["hash_final_sha256"]}
            else:
                flash("Escolha o arquivo PDF para conferir.", "erro")
    return render_template("validar.html", codigo=codigo, c=c, conferencia=conferencia,
                           nome=mascarar_nome(c["contratante_nome"]) if c else None,
                           doc=mascarar_doc(c["contratante_cpf_cnpj"]) if c else None)
