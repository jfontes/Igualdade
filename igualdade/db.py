"""Acesso ao banco SQLite (sem ORM).

O banco usa o modo de journal padrão do SQLite (não WAL): o PythonAnywhere guarda os arquivos
em sistema de arquivos de rede, onde o WAL não é confiável.
"""
import os
import sqlite3
from pathlib import Path

import click
from flask import current_app, g

# Tempo máximo que uma gravação espera o banco ser liberado por outra gravação antes de
# desistir com "database is locked". As gravações deste sistema levam milissegundos;
# 5 segundos cobrem picos (vários usuários salvando juntos) sem prender a página do usuário.
TIMEOUT_ESCRITA = float(os.environ.get("SQLITE_TIMEOUT", "5"))


def conectar(caminho: str) -> sqlite3.Connection:
    conn = sqlite3.connect(caminho, timeout=TIMEOUT_ESCRITA)
    conn.execute(f"PRAGMA busy_timeout = {int(TIMEOUT_ESCRITA * 1000)}")
    conn.execute("PRAGMA foreign_keys = ON")  # necessário para o ON DELETE CASCADE
    return conn


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = conectar(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
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
    ("obreiro", "admin_parque", "INTEGER NOT NULL DEFAULT 0"),
]


def migrar(conn: sqlite3.Connection):
    # Tabelas novas (CREATE TABLE IF NOT EXISTS não mexe nas existentes)
    conn.executescript((Path(__file__).parent / "schema.sql").read_text(encoding="utf-8"))
    for tabela, coluna, tipo in MIGRACOES:
        existentes = {r[1] for r in conn.execute(f"PRAGMA table_info({tabela})")}
        if existentes and coluna not in existentes:
            conn.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}")
    mover_eventos_cadastrados_como_sessao(conn)
    conn.commit()


def mover_eventos_cadastrados_como_sessao(conn: sqlite3.Connection) -> int:
    """Correção de dados: eventos que foram cadastrados como "sessão extraordinária" com a
    ordem do dia "Evento: <nome>" passam para a tabela de eventos. Só move as que não têm
    balaústre. Pode rodar sempre: depois de movidas, não sobra nada para mover."""
    linhas = conn.execute(
        "SELECT id, data, ordem_do_dia, cancelada, motivo_cancelamento FROM sessao s "
        "WHERE tipo = 'Extraordinária' AND ordem_do_dia LIKE 'Evento:%' "
        "AND NOT EXISTS (SELECT 1 FROM balaustre b WHERE b.sessao_id = s.id)").fetchall()
    for sid, data, ordem, cancelada, motivo in linhas:
        titulo = ordem.split(":", 1)[1].strip() or "Evento"
        conn.execute("INSERT INTO evento (data, titulo, cancelado, motivo_cancelamento) VALUES (?, ?, ?, ?)",
                     (data, titulo, cancelada, motivo))
        conn.execute("DELETE FROM sessao WHERE id = ?", (sid,))
    return len(linhas)


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
        conn = conectar(app.config["DATABASE"])
        try:
            migrar(conn)
        finally:
            conn.close()
    app.cli.add_command(init_db_command)
