"""Assistente de primeiro acesso (passo a passo).

1. Conferir os dados que a Secretaria já cadastrou (e corrigir, se preciso)
2. Completar as informações que faltam
3. Informar os familiares
4. Criar a senha pessoal → painel

Aparece uma única vez: ao concluir, grava `cadastro_confirmado` e os próximos acessos
vão direto para o painel. O progresso fica na sessão; o que já foi salvo fica no banco.
"""
from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from werkzeug.datastructures import MultiDict

from . import fotos
from .auth import SENHA_MIN, hash_senha
from .db import get_db
from .util import DATAS_MACONICAS, MESES, PARENTESCOS, UFS, so_digitos
from .views import (CAMPOS_PESSOAIS, buscar_familiar, buscar_obreiro, gravar_familiar,
                    ler_form_obreiro, remover_familiar)

bp = Blueprint("assistente", __name__, url_prefix="/primeiro-acesso")

ETAPAS = [
    ("conferir", "Conferir dados"),
    ("completar", "Completar dados"),
    ("familiares", "Familiares"),
    ("senha", "Criar senha"),
]

GRUPOS = [
    ("Dados pessoais", "👤", ["nome", "data_nascimento"]),
    ("Contato", "📞", ["telefone", "email"]),
    ("Endereço", "🏠", ["cep", "logradouro", "numero", "bairro", "cidade", "estado"]),
    ("Vida maçônica", "🏛️", [c for c, _ in DATAS_MACONICAS]),
]

# rótulo e dica de cada campo, em linguagem simples
INFO = {
    "nome": ("Nome completo", None),
    "data_nascimento": ("Data de nascimento", None),
    "telefone": ("Telefone ou WhatsApp", "Com DDD. Exemplo: (68) 99999-9999"),
    "email": ("E-mail", "Se não tiver e-mail, deixe em branco."),
    "cep": ("CEP", "Digite o CEP e o endereço será preenchido sozinho."),
    "logradouro": ("Rua, avenida ou travessa", None),
    "numero": ("Número da casa", "Se não houver número, escreva S/N."),
    "bairro": ("Bairro", None),
    "cidade": ("Cidade", None),
    "estado": ("Estado", None),
    "data_iniciacao": ("Data de Iniciação", None),
    "data_elevacao": ("Data de Elevação", None),
    "data_exaltacao": ("Data de Exaltação", None),
    "data_filiacao": ("Data de Filiação", "Somente se veio de outra Loja."),
    "data_instalacao": ("Data de Instalação", "Somente se já foi Venerável Mestre."),
}


# ---------------------------------------------------------------- progresso

def _liberada() -> int:
    """Etapa mais adiantada que o obreiro já pode abrir (guardada por usuário)."""
    p = session.get("primeiro_acesso") or {}
    return p.get("etapa", 1) if p.get("id") == current_user.id else 1


def _liberar(n: int):
    session["primeiro_acesso"] = {"id": current_user.id, "etapa": max(_liberada(), n)}


def _ir(n: int):
    return redirect(url_for(f"assistente.{ETAPAS[n - 1][0]}"))


def _verificar(n: int):
    """Redireciona se o assistente já foi concluído ou se a etapa ainda não foi alcançada."""
    if not current_user.cadastro_pendente:
        return redirect(url_for("main.painel"))
    if n > _liberada():
        return _ir(_liberada())
    return None


def _render(modelo: str, etapa: int, **ctx):
    return render_template(f"assistente/{modelo}", etapa=etapa, ETAPAS=ETAPAS,
                           liberada=_liberada(), INFO=INFO, MESES=MESES, UFS=UFS,
                           PARENTESCOS=PARENTESCOS, **ctx)


def _grupos(campos):
    return [(titulo, ic, [c for c in cs if c in campos])
            for titulo, ic, cs in GRUPOS if any(c in campos for c in cs)]


# ---------------------------------------------------------------- gravação de dados

def _datas_do_form(form) -> MultiDict:
    """Junta dia/mês/ano das datas maçônicas no formato ISO que o validador espera."""
    form = MultiDict(form)
    for campo, _ in DATAS_MACONICAS:
        if f"{campo}_dia" not in form:
            continue
        dia, mes, ano = (so_digitos(form.get(f"{campo}_{p}")) for p in ("dia", "mes", "ano"))
        if not (dia or mes or ano):
            form[campo] = ""
        elif dia and mes and len(ano) == 4:
            form[campo] = f"{ano}-{int(mes):02d}-{int(dia):02d}"
        else:
            form[campo] = "incompleta"  # o validador acusa a data incompleta
    return form


def _salvar(obreiro, campos, com_foto: bool):
    """Valida e grava apenas `campos` (e a foto, se `com_foto`). Retorna (dados, erros)."""
    dados, erros = ler_form_obreiro(_datas_do_form(request.form), completo=False,
                                    obreiro_id=obreiro["id"], campos=campos, base=obreiro)
    if com_foto and not erros:
        dados["foto"], erro_foto = fotos.processar_upload(request.form, request.files, obreiro["foto"])
        if erro_foto:
            erros.append(erro_foto)
    if erros:
        if dados.get("foto") not in (None, obreiro["foto"]):
            fotos.apagar(dados["foto"])
        dados.pop("foto", None)
        return dados, erros
    if dados:
        sets = ", ".join(f"{c} = ?" for c in dados)
        get_db().execute(f"UPDATE obreiro SET {sets} WHERE id = ?", (*dados.values(), obreiro["id"]))
        get_db().commit()
        if "foto" in dados and dados["foto"] != obreiro["foto"]:
            fotos.apagar(obreiro["foto"])
    return dados, []


def _mostrar_erros(erros):
    for e in erros:
        flash(e, "erro")


# ---------------------------------------------------------------- rotas

@bp.route("/")
@login_required
def inicio():
    if not current_user.cadastro_pendente:
        return redirect(url_for("main.painel"))
    return _ir(_liberada())


@bp.route("/1", methods=["GET", "POST"])
@login_required
def conferir():
    if (r := _verificar(1)):
        return r
    obreiro = buscar_obreiro(current_user.id)
    preenchidos = [c for c in CAMPOS_PESSOAIS if obreiro[c]]
    corrigir = bool(request.args.get("corrigir"))
    o = obreiro
    if request.method == "POST":
        if request.form.get("acao") == "confirmar":
            _liberar(2)
            return _ir(2)
        dados, erros = _salvar(obreiro, preenchidos, com_foto=bool(obreiro["foto"]))
        if not erros:
            flash("Correções salvas.", "ok")
            _liberar(2)
            return _ir(2)
        _mostrar_erros(erros)
        o, corrigir = dict(obreiro) | dados, True
    return _render("conferir.html", 1, o=o, corrigir=corrigir, grupos=_grupos(preenchidos),
                   primeiro_nome=current_user.primeiro_nome)


@bp.route("/2", methods=["GET", "POST"])
@login_required
def completar():
    if (r := _verificar(2)):
        return r
    obreiro = buscar_obreiro(current_user.id)
    ausentes = [c for c in CAMPOS_PESSOAIS if not obreiro[c]]
    o = obreiro
    if request.method == "POST":
        dados, erros = _salvar(obreiro, ausentes, com_foto=not obreiro["foto"])
        if not erros:
            if any(v for v in dados.values()):
                flash("Informações salvas.", "ok")
            _liberar(3)
            return _ir(3)
        _mostrar_erros(erros)
        o = dict(obreiro) | dados
    return _render("completar.html", 2, o=o, grupos=_grupos(ausentes),
                   pedir_foto=not obreiro["foto"])


@bp.route("/3")
@login_required
def familiares():
    if (r := _verificar(3)):
        return r
    return _tela_familiares()


def _tela_familiares(f=None, familiar_id=None, mostrar_form=False):
    obreiro = buscar_obreiro(current_user.id)
    if not mostrar_form:
        familiar_id = request.args.get("editar", type=int)
        if familiar_id:
            f, mostrar_form = buscar_familiar(obreiro["id"], familiar_id), True
        else:
            mostrar_form = bool(request.args.get("novo"))
    lista = get_db().execute("SELECT * FROM familiar WHERE obreiro_id = ? ORDER BY nome",
                             (obreiro["id"],)).fetchall()
    return _render("familiares.html", 3, familiares=lista, f=f, familiar_id=familiar_id,
                   mostrar_form=mostrar_form)


@bp.route("/3/familiar", methods=["POST"])
@bp.route("/3/familiar/<int:familiar_id>", methods=["POST"])
@login_required
def familiar_salvar(familiar_id=None):
    if (r := _verificar(3)):
        return r
    familiar = buscar_familiar(current_user.id, familiar_id) if familiar_id else None
    dados, erros = gravar_familiar(current_user.id, familiar)
    if erros:
        _mostrar_erros(erros)
        return _tela_familiares(f=dados, familiar_id=familiar_id, mostrar_form=True)
    flash(f"{dados['nome']} foi {'incluído(a)' if familiar is None else 'atualizado(a)'}.", "ok")
    return redirect(url_for("assistente.familiares"))


@bp.route("/3/familiar/<int:familiar_id>/remover", methods=["POST"])
@login_required
def familiar_remover(familiar_id):
    if (r := _verificar(3)):
        return r
    remover_familiar(current_user.id, familiar_id)
    flash("Familiar removido.", "ok")
    return redirect(url_for("assistente.familiares"))


@bp.route("/3/continuar", methods=["POST"])
@login_required
def familiares_continuar():
    if (r := _verificar(3)):
        return r
    _liberar(4)
    return _ir(4)


@bp.route("/4", methods=["GET", "POST"])
@login_required
def senha():
    if (r := _verificar(4)):
        return r
    obreiro = buscar_obreiro(current_user.id)
    if request.method == "POST":
        nova = request.form.get("nova", "")
        confirma = request.form.get("confirma", "")
        if len(nova) < SENHA_MIN:
            flash(f"A senha precisa ter pelo menos {SENHA_MIN} letras ou números.", "erro")
        elif nova != confirma:
            flash("As duas senhas digitadas não são iguais. Digite novamente.", "erro")
        elif nova == obreiro["cpf"] or nova.replace(".", "").replace("-", "").strip() == obreiro["cpf"]:
            flash("A senha não pode ser o seu CPF. Escolha outra.", "erro")
        else:
            db = get_db()
            db.execute("UPDATE obreiro SET senha_hash = ?, trocar_senha = 0, cadastro_confirmado = ? "
                       "WHERE id = ?", (hash_senha(nova), datetime.now().isoformat(timespec="seconds"),
                                        obreiro["id"]))
            db.commit()
            session.pop("primeiro_acesso", None)
            flash(f"Pronto, Ir∴ {current_user.primeiro_nome}! Seu cadastro foi concluído. "
                  f"Nos próximos acessos, entre com o CIM {obreiro['cim']} e a sua nova senha.", "ok")
            return redirect(url_for("main.painel"))
    return _render("senha.html", 4, cim=obreiro["cim"])
