"""Acesso ao banco SQLite (sem ORM)."""
import sqlite3
from pathlib import Path

import click
from flask import current_app, g


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")  # necessário para o ON DELETE CASCADE
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# Colunas acrescentadas depois da primeira versão: (tabela, coluna, tipo).
# Bancos antigos recebem as colunas automaticamente ao iniciar o sistema.
MIGRACOES = [
    ("obreiro", "email", "TEXT"),
    ("obreiro", "telefone", "TEXT"),
    ("obreiro", "foto", "TEXT"),
    ("familiar", "foto", "TEXT"),
    ("obreiro", "cadastro_confirmado", "TEXT"),
    ("obreiro", "data_emerito", "TEXT"),
    ("obreiro", "data_vm_honra", "TEXT"),
]


def migrar(conn: sqlite3.Connection):
    # Tabelas novas (CREATE TABLE IF NOT EXISTS não mexe nas existentes)
    conn.executescript((Path(__file__).parent / "schema.sql").read_text(encoding="utf-8"))
    for tabela, coluna, tipo in MIGRACOES:
        existentes = {r[1] for r in conn.execute(f"PRAGMA table_info({tabela})")}
        if existentes and coluna not in existentes:
            conn.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}")
    conn.commit()


def init_db():
    schema = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
    db = get_db()
    db.executescript(schema)
    migrar(db)


@click.command("init-db")
def init_db_command():
    """Cria as tabelas (não apaga dados existentes)."""
    init_db()
    click.echo(f"Banco pronto em {current_app.config['DATABASE']}")


def init_app(app):
    app.teardown_appcontext(close_db)
    if Path(app.config["DATABASE"]).exists():
        conn = sqlite3.connect(app.config["DATABASE"])
        try:
            migrar(conn)
        finally:
            conn.close()
    app.cli.add_command(init_db_command)
