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

-- ================================================================ tesouraria
-- Percapita: contribuição semestral. Valores em centavos (inteiro) para que a soma
-- de parcelas nunca tenha diferença de arredondamento.

-- Lançamento anual feito pelo Tesoureiro: guarda o valor do semestre no ano
-- e impede um segundo lançamento geral no mesmo ano.
CREATE TABLE IF NOT EXISTS lancamento_anual (
    ano              INTEGER PRIMARY KEY,
    valor            INTEGER NOT NULL CHECK (valor > 0),   -- centavos, por semestre
    lancado_em       TEXT    NOT NULL,
    lancado_por      INTEGER REFERENCES obreiro(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS percapita (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    obreiro_id       INTEGER NOT NULL REFERENCES obreiro(id) ON DELETE RESTRICT,  -- preserva o histórico financeiro
    ano              INTEGER NOT NULL,
    semestre         INTEGER NOT NULL CHECK (semestre IN (1, 2)),
    valor            INTEGER NOT NULL CHECK (valor > 0),   -- centavos
    vencimento       TEXT    NOT NULL,                     -- 5º dia útil de fevereiro / de julho
    cancelada        INTEGER NOT NULL DEFAULT 0,
    motivo_cancelamento TEXT,
    cancelada_em     TEXT,
    cancelada_por    INTEGER REFERENCES obreiro(id) ON DELETE SET NULL,
    lancada_em       TEXT    NOT NULL,
    lancada_por      INTEGER REFERENCES obreiro(id) ON DELETE SET NULL,
    UNIQUE (obreiro_id, ano, semestre)
);

CREATE INDEX IF NOT EXISTS idx_percapita_ano ON percapita(ano, semestre);

-- Pagamento registrado para um obreiro em um ano. O sistema distribui o valor entre os
-- semestres em aberto (1º, depois 2º) e grava a distribuição em pagamento_parte.
CREATE TABLE IF NOT EXISTS pagamento (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    obreiro_id       INTEGER NOT NULL REFERENCES obreiro(id) ON DELETE RESTRICT,
    ano              INTEGER NOT NULL,
    data             TEXT    NOT NULL,                     -- quando o pagamento ocorreu
    valor            INTEGER NOT NULL CHECK (valor > 0),   -- centavos
    forma            TEXT    NOT NULL,                     -- PIX, Dinheiro, Cartão, Abatimento em crédito, Isenção
    observacao       TEXT,
    automatico       INTEGER NOT NULL DEFAULT 0,           -- 1 = isenção gerada ao registrar o Emérito
    registrado_em    TEXT    NOT NULL,
    registrado_por   INTEGER REFERENCES obreiro(id) ON DELETE SET NULL,
    estornado        INTEGER NOT NULL DEFAULT 0,
    motivo_estorno   TEXT,
    estornado_em     TEXT,
    estornado_por    INTEGER REFERENCES obreiro(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_pagamento_obreiro ON pagamento(obreiro_id, ano);
CREATE INDEX IF NOT EXISTS idx_pagamento_data ON pagamento(data);

CREATE TABLE IF NOT EXISTS pagamento_parte (
    pagamento_id     INTEGER NOT NULL REFERENCES pagamento(id) ON DELETE CASCADE,
    percapita_id     INTEGER NOT NULL REFERENCES percapita(id) ON DELETE RESTRICT,
    valor            INTEGER NOT NULL CHECK (valor > 0),   -- centavos
    PRIMARY KEY (pagamento_id, percapita_id)
);

CREATE INDEX IF NOT EXISTS idx_parte_percapita ON pagamento_parte(percapita_id);
