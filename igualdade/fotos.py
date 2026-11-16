"""Fotos de obreiros e familiares.

As fotos ficam em instance/fotos/ (fora de static/) e só são entregues a usuários
logados, pelas rotas /foto/obreiro/<id> e /foto/familiar/<id>, que conferem a permissão.

Toda foto enviada é reprocessada: corrige a rotação do celular, recorta em quadrado
(puxando para a parte de cima, onde costuma estar o rosto), reduz para 512 px e é
regravada em JPEG sem metadados (remove localização GPS, modelo do aparelho etc.).
"""
import secrets
from pathlib import Path

from flask import Blueprint, abort, current_app, send_from_directory
from flask_login import current_user, login_required
from PIL import Image, ImageOps, UnidentifiedImageError

from .db import get_db

bp = Blueprint("fotos", __name__)

TAMANHO = 512
Image.MAX_IMAGE_PIXELS = 60_000_000  # evita "bombas" de descompressão


def pasta() -> Path:
    p = Path(current_app.instance_path) / "fotos"
    p.mkdir(parents=True, exist_ok=True)
    return p


def salvar(arquivo) -> str:
    """Processa o upload e devolve o nome do arquivo gravado. Lança ValueError se não for imagem."""
    try:
        img = Image.open(arquivo.stream)
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValueError("o arquivo enviado não é uma imagem válida (use JPG ou PNG)")
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        fundo = Image.new("RGB", img.size, (255, 255, 255))
        fundo.paste(img, mask=img.split()[-1])
        img = fundo
    else:
        img = img.convert("RGB")
    img = ImageOps.fit(img, (TAMANHO, TAMANHO), Image.LANCZOS, centering=(0.5, 0.35))
    nome = f"{secrets.token_hex(12)}.jpg"
    img.save(pasta() / nome, "JPEG", quality=85, optimize=True, progressive=True)
    return nome


def apagar(nome: str | None):
    """Remove o arquivo antigo. Falha ao apagar não pode impedir o salvamento do cadastro."""
    if not nome:
        return
    try:
        (pasta() / Path(nome).name).unlink(missing_ok=True)
    except OSError as e:
        current_app.logger.warning("Não foi possível apagar a foto %s: %s", nome, e)


def processar_upload(form, files, atual: str | None):
    """Decide o novo valor da coluna foto a partir do formulário.

    Retorna (novo_nome, erro). Não apaga a foto antiga — quem chama apaga depois do commit.
    """
    arquivo = files.get("foto")
    if arquivo and arquivo.filename:
        try:
            return salvar(arquivo), None
        except ValueError as e:
            return atual, f"Foto: {e}."
    if form.get("remover_foto"):
        return None, None
    return atual, None


def _enviar(nome: str | None):
    if not nome:
        abort(404)
    resp = send_from_directory(pasta(), Path(nome).name, mimetype="image/jpeg")
    # O nome do arquivo muda a cada troca de foto, então o navegador pode guardar por muito tempo
    resp.headers["Cache-Control"] = "private, max-age=31536000, immutable"
    return resp


@bp.route("/foto/obreiro/<int:obreiro_id>")
@login_required
def obreiro(obreiro_id):
    row = get_db().execute("SELECT foto FROM obreiro WHERE id = ?", (obreiro_id,)).fetchone()
    return _enviar(row["foto"] if row else None)


@bp.route("/foto/familiar/<int:familiar_id>")
@login_required
def familiar(familiar_id):
    from .auth import pode_editar
    row = get_db().execute("SELECT obreiro_id, foto FROM familiar WHERE id = ?",
                           (familiar_id,)).fetchone()
    if row is None or not pode_editar(row["obreiro_id"]):
        abort(404)
    return _enviar(row["foto"])
