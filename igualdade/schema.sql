-- Banco de dados do Sistema de Gestão de Obreiros e Familiares
-- Igualdade Acreana Nº 2 — SQLite
-- Datas gravadas como texto ISO (AAAA-MM-DD).
-- Data de nascimento pode vir sem ano: --MM-DD (forma ISO 8601 para dia/mês).

CREATE TABLE IF NOT EXISTS obreiro (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    nome             TEXT    NOT NULL,
    cim              TEXT    NOT NULL UNIQUE,          -- RN01
    cpf              TEXT    NOT NULL UNIQUE,          -- RN01 (somente dígitos)
    data_nascimento  TEXT,
    data_iniciacao   TEXT,
    data_elevacao    TEXT,
    data_exaltacao   TEXT,
    data_filiacao    TEXT,
    data_instalacao  TEXT,
    data_emerito     TEXT,                             -- título concedido (registrado pela Secretaria)
    data_vm_honra    TEXT,                             -- Venerável Mestre de Honra (idem)
    data_afastamento TEXT,                             -- nulo = ativo (RF05)
    cep              TEXT,
    logradouro       TEXT,
    numero           TEXT,
    bairro           TEXT,
    cidade           TEXT,
    estado           TEXT,
    email            TEXT,
    telefone         TEXT,                             -- somente dígitos, com DDD
    foto             TEXT,                             -- arquivo em instance/fotos/
    -- Acesso ao sistema
    senha_hash       TEXT    NOT NULL,
    trocar_senha     INTEGER NOT NULL DEFAULT 1,       -- 1 = obrigar troca no próximo login
    admin            INTEGER NOT NULL DEFAULT 0,       -- 1 = Secretaria / administrador
    cadastro_confirmado TEXT                           -- quando concluiu o assistente de primeiro acesso
);

CREATE TABLE IF NOT EXISTS familiar (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    obreiro_id       INTEGER NOT NULL
                     REFERENCES obreiro(id) ON DELETE CASCADE,  -- RN02
    nome             TEXT    NOT NULL,
    parentesco       TEXT    NOT NULL,
    data_nascimento  TEXT,
    foto             TEXT                              -- arquivo em instance/fotos/
);

CREATE INDEX IF NOT EXISTS idx_familiar_obreiro ON familiar(obreiro_id);

-- Arquivo histórico: ex-obreiros importados de cadastros antigos (GLEAC 2012, relatórios).
-- Somente consulta; não tem acesso ao sistema nem aparece no quadro de ativos.
CREATE TABLE IF NOT EXISTS obreiro_historico (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    cim              TEXT,
    nome             TEXT    NOT NULL,
    cpf              TEXT,
    data_nascimento  TEXT,
    data_iniciacao   TEXT,
    data_elevacao    TEXT,
    data_exaltacao   TEXT,
    data_filiacao    TEXT,
    situacao         TEXT,      -- situação no cadastro de origem (ex.: Falecido, Emérito)
    observacao       TEXT,
    fonte            TEXT    NOT NULL   -- de onde veio o registro
);

CREATE INDEX IF NOT EXISTS idx_historico_cim ON obreiro_historico(cim);

-- Agenda: sessões da Loja (sempre às segundas, 20h)
CREATE TABLE IF NOT EXISTS sessao (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    data             TEXT    NOT NULL,                 -- AAAA-MM-DD
    tipo             TEXT    NOT NULL DEFAULT 'Ordinária',  -- Ordinária, Magna, Extraordinária
    grau             TEXT,                             -- Aprendiz, Companheiro, Mestre (nulo se cancelada)
    ordem_do_dia     TEXT,
    cancelada        INTEGER NOT NULL DEFAULT 0,
    motivo_cancelamento TEXT
);

CREATE INDEX IF NOT EXISTS idx_sessao_data ON sessao(data);

-- Diretoria: cada gestão (período) tem um quadro de oficiais.
-- A diretoria vigente na data da sessão compõe a mesa do balaústre.
CREATE TABLE IF NOT EXISTS gestao (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    inicio           TEXT    NOT NULL,                 -- AAAA-MM-DD (posse)
    fim              TEXT    NOT NULL,                 -- AAAA-MM-DD
    observacao       TEXT
);

CREATE TABLE IF NOT EXISTS diretoria (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    gestao_id        INTEGER NOT NULL REFERENCES gestao(id) ON DELETE CASCADE,
    cargo            TEXT    NOT NULL,                 -- chave de config.CARGOS
    obreiro_id       INTEGER REFERENCES obreiro(id) ON DELETE SET NULL,  -- nulo = nome fora do quadro
    nome             TEXT    NOT NULL,                 -- nome gravado (preserva o histórico)
    UNIQUE (gestao_id, cargo)
);

-- Balaústre (ata) de cada sessão. "dados" guarda o JSON lido por secretaria/gerar_balaustre.py.
CREATE TABLE IF NOT EXISTS balaustre (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    sessao_id        INTEGER NOT NULL UNIQUE REFERENCES sessao(id) ON DELETE CASCADE,
    dados            TEXT    NOT NULL,
    atualizado_em    TEXT    NOT NULL,
    atualizado_por   INTEGER REFERENCES obreiro(id) ON DELETE SET NULL
);
