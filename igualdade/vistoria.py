"""Vistoria fotográfica pelo caseiro do Parque das Acácias.

Página separada do sistema dos obreiros: o caseiro entra com um código de 6 números (definido pelo
administrador do Parque). O acesso vale 12 horas neste aparelho; 5 erros seguidos bloqueiam por
15 minutos. Ele só vê a fila de vistorias e a tela de fotos.

Cada foto é corrigida (rotação do celular), reduzida para no máximo 1280 px de largura, gravada em
JPEG qualidade 78 e sem metadados (sem GPS).
"""
import io
from datetime import timedelta
from functools import wraps

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from PIL import Image, ImageOps, UnidentifiedImageError

from . import fotos as _fotos  # noqa: F401  (aplica o limite de pixels do Pillow)
from .db import get_db
from .parque import (AGUARDANDO_VISTORIA, PendenciaLocadora, agora_utc, apagar_arquivo, buscar,
                     atualizar_padroes_pela_vistoria, conferir_codigo_caseiro, codigo_caseiro_definido, detalhar,
                     enviar_foto, fotos_da_vistoria, gravar_foto_contrato, iso, liberar_para_assinatura,
                     preparar_vistoria, resposta_envio, tipos_exigidos, tipos_pendentes)

bp = Blueprint("vistoria", __name__, url_prefix="/vistoria")

LARGURA_MAX = 1280
QUALIDADE = 78
HORAS_ACESSO = 12
TENTATIVAS = 5
MINUTOS_BLOQUEIO = 15


def ip_cliente() -> str:
    return (request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.remote_addr or "")


def caseiro_logado() -> bool:
    ate = session.get("caseiro_ate")
    return bool(ate and ate > iso(agora_utc()))


def caseiro_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not caseiro_logado():
            return redirect(url_for("vistoria.entrar"))
        return view(*args, **kwargs)
    return wrapper


def _bloqueado(chave: str) -> str | None:
    row = get_db().execute("SELECT bloqueado_ate FROM acesso_tentativa WHERE chave = ?", (chave,)).fetchone()
    if row and row["bloqueado_ate"] and row["bloqueado_ate"] > iso(agora_utc()):
        return row["bloqueado_ate"]
    return None


def _registrar_falha(chave: str):
    db = get_db()
    row = db.execute("SELECT falhas FROM acesso_tentativa WHERE chave = ?", (chave,)).fetchone()
    falhas = (row["falhas"] if row else 0) + 1
    bloqueio = iso(agora_utc() + timedelta(minutes=MINUTOS_BLOQUEIO)) if falhas >= TENTATIVAS else None
    db.execute("INSERT INTO acesso_tentativa (chave, falhas, bloqueado_ate) VALUES (?, ?, ?) "
               "ON CONFLICT(chave) DO UPDATE SET falhas = excluded.falhas, bloqueado_ate = excluded.bloqueado_ate",
               (chave, 0 if bloqueio else falhas, bloqueio))
    db.commit()


def comprimir(arquivo) -> bytes:
    try:
        img = Image.open(arquivo.stream)
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValueError("arquivo não é uma imagem")
    img = ImageOps.exif_transpose(img).convert("RGB")
    if img.width > LARGURA_MAX:
        img = img.resize((LARGURA_MAX, round(img.height * LARGURA_MAX / img.width)), Image.LANCZOS)
    saida = io.BytesIO()
    img.save(saida, "JPEG", quality=QUALIDADE, optimize=True, progressive=True)
    return saida.getvalue()


def _contrato_em_vistoria(contrato_id: int):
    c = detalhar(buscar(contrato_id))
    if c["status"] != AGUARDANDO_VISTORIA or c["vistoria_concluida_em"]:
        flash("Este contrato não está mais aguardando vistoria.", "aviso")
        return None
    return c


# ---------------------------------------------------------------- telas

@bp.route("/", methods=["GET", "POST"])
def entrar():
    if caseiro_logado():
        return redirect(url_for("vistoria.fila"))
    chave = f"caseiro:{ip_cliente()}"
    bloqueio = _bloqueado(chave)
    if request.method == "POST" and not bloqueio:
        if not codigo_caseiro_definido():
            flash("O código de acesso ainda não foi definido pelo administrador do Parque.", "erro")
        elif conferir_codigo_caseiro(request.form.get("codigo", "")):
            get_db().execute("DELETE FROM acesso_tentativa WHERE chave = ?", (chave,))
            get_db().commit()
            session["caseiro_ate"] = iso(agora_utc() + timedelta(hours=HORAS_ACESSO))
            session.permanent = True
            return redirect(url_for("vistoria.fila"))
        else:
            _registrar_falha(chave)
            bloqueio = _bloqueado(chave)
            if not bloqueio:
                flash("Código incorreto.", "erro")
    if bloqueio:
        flash(f"Muitas tentativas erradas. Tente de novo em {MINUTOS_BLOQUEIO} minutos.", "erro")
    return render_template("vistoria/entrar.html", bloqueado=bool(bloqueio))


@bp.route("/sair", methods=["POST"])
def sair():
    session.pop("caseiro_ate", None)
    flash("Você saiu da área de vistoria.", "ok")
    return redirect(url_for("vistoria.entrar"))


@bp.route("/fila")
@caseiro_required
def fila():
    contratos = [detalhar(c) for c in get_db().execute(
        "SELECT * FROM contrato WHERE status = ? AND exige_vistoria = 1 AND vistoria_concluida_em IS NULL "
        "ORDER BY id", (AGUARDANDO_VISTORIA,))]
    contratos.sort(key=lambda c: c["evento"].get("data") or "")
    qtd = {r["contrato_id"]: r["n"] for r in get_db().execute(
        "SELECT contrato_id, COUNT(*) AS n FROM vistoria_foto GROUP BY contrato_id")}
    return render_template("vistoria/fila.html", contratos=contratos, qtd=qtd)


@bp.route("/<int:contrato_id>")
@caseiro_required
def contrato(contrato_id):
    c = _contrato_em_vistoria(contrato_id)
    if c is None:
        return redirect(url_for("vistoria.fila"))
    preparar_vistoria(contrato_id)
    fotos = fotos_da_vistoria(contrato_id)
    por_tipo: dict = {}
    for f in fotos:
        if f["tipo_id"]:
            por_tipo.setdefault(f["tipo_id"], []).append(f)
    return render_template("vistoria/fotos.html", c=c, tipos=tipos_exigidos(contrato_id), por_tipo=por_tipo,
                           outras=[f for f in fotos if not f["tipo_id"]],
                           pendentes=tipos_pendentes(contrato_id))


@bp.route("/<int:contrato_id>/fotos", methods=["POST"])
@caseiro_required
def enviar_fotos(contrato_id):
    c = _contrato_em_vistoria(contrato_id)
    destino = url_for("vistoria.contrato", contrato_id=contrato_id)
    if c is None:
        return resposta_envio(0, 0, "Este contrato não está mais aguardando vistoria.", url_for("vistoria.fila"))
    arquivos = [a for a in request.files.getlist("fotos") if a and a.filename]
    if not arquivos:
        return resposta_envio(0, 0, "Escolha ou tire ao menos uma foto.", destino)
    preparar_vistoria(contrato_id)
    tipo = None
    if request.form.get("tipo_id"):
        tipo = next((t for t in tipos_exigidos(contrato_id) if t["id"] == request.form.get("tipo_id", type=int)), None)
        if tipo is None:
            return resposta_envio(0, 0, "Este tipo de foto não é mais exigido. Atualize a página.", destino)
    gravadas = recusadas = 0
    for arquivo in arquivos:
        try:
            gravar_foto_contrato(contrato_id, tipo, comprimir(arquivo), "caseiro")
            gravadas += 1
        except ValueError:
            recusadas += 1
    get_db().commit()
    return resposta_envio(gravadas, recusadas, (f"{gravadas} foto(s) de {tipo['nome']} registrada(s)." if tipo
                                                else f"{gravadas} foto(s) adicionada(s)."), destino)


@bp.route("/<int:contrato_id>/fotos/<int:foto_id>/remover", methods=["POST"])
@caseiro_required
def remover_foto(contrato_id, foto_id):
    if _contrato_em_vistoria(contrato_id) is None:
        return redirect(url_for("vistoria.fila"))
    db = get_db()
    f = db.execute("SELECT arquivo FROM vistoria_foto WHERE id = ? AND contrato_id = ?",
                   (foto_id, contrato_id)).fetchone()
    if f:
        db.execute("DELETE FROM vistoria_foto WHERE id = ?", (foto_id,))
        db.commit()
        apagar_arquivo(f["arquivo"])
        flash("Foto removida.", "ok")
    return redirect(url_for("vistoria.contrato", contrato_id=contrato_id))


@bp.route("/<int:contrato_id>/fotos/remover-todas", methods=["POST"])
@caseiro_required
def remover_todas(contrato_id):
    """Remove todas as fotos da vistoria, ou só as de um tipo (tipo_id) ou só as "Outras fotos" (tipo=outras)."""
    if _contrato_em_vistoria(contrato_id) is None:
        return redirect(url_for("vistoria.fila"))
    db = get_db()
    sql, args, alvo = "SELECT id, arquivo FROM vistoria_foto WHERE contrato_id = ?", [contrato_id], "da vistoria"
    if request.form.get("tipo") == "outras":
        sql, alvo = sql + " AND tipo_id IS NULL", "de Outras fotos"
    elif request.form.get("tipo_id", type=int):
        tipo = next((t for t in tipos_exigidos(contrato_id) if t["id"] == request.form.get("tipo_id", type=int)), None)
        if tipo is None:
            abort(400)
        sql, alvo = sql + " AND tipo_id = ?", f"de {tipo['nome']}"
        args.append(tipo["id"])
    fotos = db.execute(sql, args).fetchall()
    db.executemany("DELETE FROM vistoria_foto WHERE id = ?", [(f["id"],) for f in fotos])
    db.commit()
    for f in fotos:
        apagar_arquivo(f["arquivo"])
    flash(f"{len(fotos)} foto(s) {alvo} removida(s)." if fotos else "Não havia fotos para remover.", "ok")
    return redirect(url_for("vistoria.contrato", contrato_id=contrato_id))


@bp.route("/<int:contrato_id>/foto/<int:foto_id>")
@caseiro_required
def foto(contrato_id, foto_id):
    return enviar_foto(contrato_id, foto_id)


@bp.route("/<int:contrato_id>/concluir", methods=["POST"])
@caseiro_required
def concluir(contrato_id):
    if _contrato_em_vistoria(contrato_id) is None:
        return redirect(url_for("vistoria.fila"))
    faltam = tipos_pendentes(contrato_id)
    if faltam:
        flash("Ainda falta a foto de: " + ", ".join(faltam) + ".", "erro")
        return redirect(url_for("vistoria.contrato", contrato_id=contrato_id))
    if not fotos_da_vistoria(contrato_id):
        flash("Adicione ao menos uma foto antes de concluir a vistoria.", "erro")
        return redirect(url_for("vistoria.contrato", contrato_id=contrato_id))
    atualizar_padroes_pela_vistoria(contrato_id)  # o conjunto de fotos de cada tipo passa a ser o padrão
    get_db().execute("UPDATE contrato SET vistoria_concluida_em = ? WHERE id = ?", (iso(agora_utc()), contrato_id))
    get_db().commit()
    try:
        _link, enviou, _motivo = liberar_para_assinatura(contrato_id)
    except PendenciaLocadora:
        # a vistoria fica registrada; a gestão do Parque libera quando resolver o que falta
        flash("Vistoria concluída! O administrador do Parque vai liberar o contrato para assinatura.", "ok")
        return redirect(url_for("vistoria.fila"))
    flash("Vistoria concluída! O contrato foi liberado para assinatura"
          + (" e o contratante recebeu o link por e-mail." if enviou
             else ". O administrador do Parque vai enviar o link ao contratante."), "ok")
    return redirect(url_for("vistoria.fila"))
