"""Funções da Secretaria (administrador): cadastrar, editar, afastar, excluir e redefinir senha."""
import getpass
import sqlite3

import click
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user

from . import fotos, tesouraria
from .auth import SENHA_MIN, admin_required, hash_senha
from .db import get_db, init_db
from .util import cpf_valido, so_digitos
from .views import buscar_obreiro, contexto_form, ler_form_obreiro

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.route("/obreiros/novo", methods=["GET", "POST"])
@admin_required
def novo():
    dados = {}
    if request.method == "POST":
        dados, erros = ler_form_obreiro(request.form, completo=True)
        dados["admin"] = 1 if request.form.get("admin") else 0
        dados["admin_parque"] = 1 if request.form.get("admin_parque") else 0
        if not erros:
            dados["foto"], erro_foto = fotos.processar_upload(request.form, request.files, None)
            if erro_foto:
                erros.append(erro_foto)
        if not erros:
            # Senha inicial = CPF (somente dígitos); troca obrigatória no 1º acesso
            dados["senha_hash"] = hash_senha(dados["cpf"])
            colunas = ", ".join(dados)
            marcas = ", ".join("?" for _ in dados)
            db = get_db()
            try:
                cur = db.execute(f"INSERT INTO obreiro ({colunas}) VALUES ({marcas})",
                                 tuple(dados.values()))
                db.commit()
            except sqlite3.IntegrityError:
                erros = ["CIM ou CPF já cadastrado."]
                fotos.apagar(dados.pop("foto", None))
            else:
                flash(f"{dados['nome']} cadastrado. Senha inicial: o CPF (somente números).", "ok")
                return redirect(url_for("main.perfil", obreiro_id=cur.lastrowid))
        for e in erros:
            flash(e, "erro")
    return render_template("obreiro_form.html", o=dados, modo="novo", **contexto_form())


@bp.route("/obreiros/<int:obreiro_id>/editar", methods=["GET", "POST"])
@admin_required
def editar(obreiro_id):
    obreiro = buscar_obreiro(obreiro_id)
    if request.method == "POST":
        dados, erros = ler_form_obreiro(request.form, completo=True, obreiro_id=obreiro_id)
        dados["admin"] = 1 if request.form.get("admin") else 0
        dados["admin_parque"] = 1 if request.form.get("admin_parque") else 0
        if obreiro_id == current_user.id:
            # ninguém altera o próprio perfil de administrador (evita se trancar fora do sistema
            # e evita que o Secretário da gestão o mantenha depois que a gestão terminar)
            dados["admin"] = obreiro["admin"]
            if dados["data_afastamento"]:
                erros.append("Você não pode registrar o seu próprio afastamento.")
        if not erros:
            dados["foto"], erro_foto = fotos.processar_upload(request.form, request.files, obreiro["foto"])
            if erro_foto:
                erros.append(erro_foto)
        if not erros:
            sets = ", ".join(f"{c} = ?" for c in dados)
            db = get_db()
            try:
                db.execute(f"UPDATE obreiro SET {sets} WHERE id = ?", (*dados.values(), obreiro_id))
                db.commit()
            except sqlite3.IntegrityError:
                erros = ["CIM ou CPF já cadastrado."]
            else:
                if dados["foto"] != obreiro["foto"]:
                    fotos.apagar(obreiro["foto"])
                flash("Cadastro atualizado.", "ok")
                if dados.get("data_emerito") and dados["data_emerito"] != obreiro["data_emerito"]:
                    # Emérito fica isento a partir do semestre seguinte ao título
                    n = tesouraria.isentar_emerito(obreiro_id)
                    if n:
                        flash(f"Emérito registrado: {n} percapita{'s' if n > 1 else ''} em aberto "
                              f"isentada{'s' if n > 1 else ''} automaticamente.", "ok")
                return redirect(url_for("main.perfil", obreiro_id=obreiro_id))
        if dados.get("foto") not in (None, obreiro["foto"]):
            fotos.apagar(dados["foto"])
        for e in erros:
            flash(e, "erro")
        return render_template("obreiro_form.html", o=dados | {"id": obreiro_id, "foto": obreiro["foto"]},
                               modo="editar", **contexto_form())
    return render_template("obreiro_form.html", o=obreiro, modo="editar", **contexto_form())


@bp.route("/obreiros/<int:obreiro_id>/excluir", methods=["POST"])
@admin_required
def excluir(obreiro_id):
    obreiro = buscar_obreiro(obreiro_id)
    if obreiro_id == current_user.id:
        flash("Você não pode excluir o seu próprio cadastro.", "erro")
        return redirect(url_for("main.perfil", obreiro_id=obreiro_id))
    if tesouraria.tem_movimento_financeiro(obreiro_id):
        flash(f"{obreiro['nome']} tem percapitas ou pagamentos registrados na Tesouraria e não pode ser "
              "excluído. Registre o Afastamento: o cadastro e o histórico financeiro são preservados.", "erro")
        return redirect(url_for("main.perfil", obreiro_id=obreiro_id))
    db = get_db()
    arquivos = [obreiro["foto"]] + [r["foto"] for r in db.execute(
        "SELECT foto FROM familiar WHERE obreiro_id = ?", (obreiro_id,))]
    db.execute("DELETE FROM obreiro WHERE id = ?", (obreiro_id,))  # familiares saem em cascata (RN02)
    db.commit()
    for nome in arquivos:
        fotos.apagar(nome)
    flash(f"{obreiro['nome']} e seus familiares foram excluídos.", "ok")
    return redirect(url_for("main.obreiros"))


@bp.route("/obreiros/<int:obreiro_id>/redefinir-senha", methods=["POST"])
@admin_required
def redefinir_senha(obreiro_id):
    obreiro = buscar_obreiro(obreiro_id)
    db = get_db()
    db.execute("UPDATE obreiro SET senha_hash = ?, trocar_senha = 1 WHERE id = ?",
               (hash_senha(obreiro["cpf"]), obreiro_id))
    db.commit()
    flash(f"Senha de {obreiro['nome']} redefinida para o CPF (somente números).", "ok")
    return redirect(url_for("main.perfil", obreiro_id=obreiro_id))


# ---------------------------------------------------------------- linha de comando

@click.command("criar-admin")
def criar_admin_command():
    """Cria o primeiro administrador (ou promove um obreiro existente)."""
    init_db()
    db = get_db()
    cim = so_digitos(click.prompt("CIM"))
    existente = db.execute("SELECT id, nome FROM obreiro WHERE cim = ?", (cim,)).fetchone()
    if existente:
        db.execute("UPDATE obreiro SET admin = 1, data_afastamento = NULL WHERE id = ?",
                   (existente["id"],))
        db.commit()
        click.echo(f"{existente['nome']} agora é administrador.")
        return
    nome = " ".join(click.prompt("Nome completo").upper().split())
    cpf = so_digitos(click.prompt("CPF"))
    if not cpf_valido(cpf):
        raise click.ClickException("CPF inválido.")
    senha = getpass.getpass(f"Senha (mín. {SENHA_MIN} caracteres): ")
    if len(senha) < SENHA_MIN or senha != getpass.getpass("Repita a senha: "):
        raise click.ClickException("Senha curta ou as senhas não conferem.")
    try:
        db.execute("INSERT INTO obreiro (nome, cim, cpf, senha_hash, trocar_senha, admin) "
                   "VALUES (?, ?, ?, ?, 0, 1)", (nome, cim, cpf, hash_senha(senha)))
        db.commit()
    except sqlite3.IntegrityError:
        raise click.ClickException("Já existe obreiro com este CPF.")
    click.echo(f"Administrador {nome} criado. Entre com o CIM {cim}.")
