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

-- ================================================================ eventos da Loja
-- Previsão de eventos na agenda (ex.: Dia das Mães, Arraial). Não são sessões:
-- não têm grau, balaústre nem mesa, e podem cair no mesmo dia de uma sessão.
CREATE TABLE IF NOT EXISTS evento (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    data             TEXT    NOT NULL,                 -- AAAA-MM-DD
    hora             TEXT,                             -- HH:MM (opcional)
    titulo           TEXT    NOT NULL,
    local            TEXT,
    descricao        TEXT,                             -- não usado (o nome do evento já é autoexplicativo)
    cancelado        INTEGER NOT NULL DEFAULT 0,
    motivo_cancelamento TEXT
);

CREATE INDEX IF NOT EXISTS idx_evento_data ON evento(data);

-- ================================================================ Parque das Acácias: contratos de locação
-- Locação da área de eventos do Parque das Acácias (locador: a própria Loja).
-- Os arquivos (fotos da vistoria, rubrica e PDF assinado) ficam em instance/contratos/<id>/;
-- o banco guarda só o caminho e o hash SHA-256 de cada arquivo (integridade).

-- Configurações do Parque (ex.: código de acesso do caseiro, guardado como hash).
CREATE TABLE IF NOT EXISTS parque_config (
    chave            TEXT PRIMARY KEY,
    valor            TEXT,
    atualizado_em    TEXT
);

-- Tentativas de acesso à área do caseiro (bloqueio temporário após erros).
CREATE TABLE IF NOT EXISTS acesso_tentativa (
    chave            TEXT PRIMARY KEY,                 -- ex.: "caseiro:<ip>"
    falhas           INTEGER NOT NULL DEFAULT 0,
    bloqueado_ate    TEXT
);

CREATE TABLE IF NOT EXISTS contrato (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo_verificador   TEXT    NOT NULL UNIQUE,      -- impresso no PDF e no QR Code
    token_assinatura     TEXT    UNIQUE,               -- link público de assinatura
    token_expira_em      TEXT,                         -- ISO, 7 dias após o envio do link
    status               TEXT    NOT NULL,             -- AGUARDANDO_VISTORIA, AGUARDANDO_ASSINATURA, ASSINADO, CANCELADO
    exige_vistoria       INTEGER NOT NULL DEFAULT 0,
    contratante_nome     TEXT    NOT NULL,
    contratante_cpf_cnpj TEXT    NOT NULL,             -- somente dígitos
    contratante_email    TEXT    NOT NULL,
    contratante_dados_json TEXT,                       -- qualificação completa (preenchida pelo contratante)
    evento_dados_json    TEXT    NOT NULL,             -- data, horários, tipo, valor, pagamento, piscina, observações
    pdf_pre_arquivo      TEXT,                         -- PDF mostrado para leitura antes de assinar
    campo_assinatura_json TEXT,                        -- onde a rubrica é estampada nesse PDF
    hash_pre_assinatura  TEXT,
    pdf_final_arquivo    TEXT,
    hash_final_sha256    TEXT,
    tamanho_final_bytes  INTEGER,
    criado_em            TEXT    NOT NULL,
    criado_por           INTEGER REFERENCES obreiro(id) ON DELETE SET NULL,
    vistoria_concluida_em TEXT,
    link_enviado_em      TEXT,
    assinado_em          TEXT,
    cancelado_em         TEXT,
    motivo_cancelamento  TEXT,
    locadora_json        TEXT,                         -- representante da LOCADORA e assinatura, na liberação
    fotos_padrao         INTEGER NOT NULL DEFAULT 0    -- 1 = Anexo I com as fotos padrão (sem vistoria)
);

CREATE INDEX IF NOT EXISTS idx_contrato_status ON contrato(status);

-- Contratos assinados que foram excluídos (assinatura equivocada): fica o registro para a página de
-- validação responder "excluído" a quem tiver o PDF. Arquivos e dados pessoais completos são apagados.
CREATE TABLE IF NOT EXISTS contrato_excluido (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    contrato_id          INTEGER NOT NULL,
    codigo_verificador   TEXT    NOT NULL UNIQUE,
    contratante_nome     TEXT    NOT NULL,
    contratante_cpf_cnpj TEXT    NOT NULL,
    evento_data          TEXT,
    assinado_em          TEXT,
    hash_final_sha256    TEXT,
    motivo               TEXT    NOT NULL,
    excluido_em          TEXT    NOT NULL,
    excluido_por         INTEGER REFERENCES obreiro(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS vistoria_foto (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    contrato_id      INTEGER NOT NULL REFERENCES contrato(id) ON DELETE CASCADE,
    tipo_id          INTEGER REFERENCES vistoria_tipo(id) ON DELETE SET NULL,  -- nulo = outras fotos
    tipo_nome        TEXT,                             -- nome do tipo quando a foto foi tirada
    arquivo          TEXT    NOT NULL,                 -- relativo a instance/contratos/
    sha256           TEXT    NOT NULL,
    enviado_por      TEXT,
    criado_em        TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_vistoria_contrato ON vistoria_foto(contrato_id);

-- Tipos de foto exigidos na vistoria (Salão, Banheiros, Palco…). Cada tipo ativo exige uma foto;
-- desativado, some das próximas vistorias e continua nas antigas. vistoria_foto.tipo_id nulo = "Outras fotos".
CREATE TABLE IF NOT EXISTS vistoria_tipo (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    nome             TEXT    NOT NULL,
    ordem            INTEGER NOT NULL DEFAULT 0,
    ativo            INTEGER NOT NULL DEFAULT 1,
    so_com_piscina   INTEGER NOT NULL DEFAULT 0,      -- 1 = exigido só se o contrato incluir a piscina
    foto_padrao      TEXT,                             -- (antigo: foto padrão única; passou para vistoria_tipo_foto)
    foto_padrao_em   TEXT
);

-- Fotos padrão de cada tipo (quantas forem necessárias). O contrato sem vistoria usa todas; a vistoria
-- começa com cópias delas e, ao ser concluída, o conjunto do dia substitui o conjunto padrão do tipo.
CREATE TABLE IF NOT EXISTS vistoria_tipo_foto (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo_id          INTEGER NOT NULL REFERENCES vistoria_tipo(id) ON DELETE CASCADE,
    arquivo          TEXT    NOT NULL,                 -- relativo a instance/contratos/
    sha256           TEXT    NOT NULL,
    ordem            INTEGER NOT NULL DEFAULT 0,
    criado_em        TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tipo_foto ON vistoria_tipo_foto(tipo_id, ordem);

-- Assinatura padronizada da LOCADORA: desenhada pelo Venerável, uma por gestão da diretoria.
-- É estampada no contrato quando ele é liberado para o contratante assinar.
CREATE TABLE IF NOT EXISTS assinatura_locadora (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    gestao_id        INTEGER NOT NULL UNIQUE REFERENCES gestao(id) ON DELETE CASCADE,
    obreiro_id       INTEGER REFERENCES obreiro(id) ON DELETE SET NULL,
    nome             TEXT    NOT NULL,
    arquivo          TEXT    NOT NULL,                 -- PNG, relativo a instance/contratos/
    sha256           TEXT    NOT NULL,
    criado_em        TEXT    NOT NULL
);

-- Evidências da assinatura. A selfie NÃO é guardada à parte: entra só no PDF assinado
-- (manifesto) e é descartada; aqui fica apenas o hash dela.
CREATE TABLE IF NOT EXISTS assinatura_evidencia (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    contrato_id          INTEGER NOT NULL UNIQUE REFERENCES contrato(id) ON DELETE CASCADE,
    selfie_sha256        TEXT,
    assinatura_arquivo   TEXT,                         -- PNG da rubrica
    assinatura_sha256    TEXT,
    traco_vetorial_json  TEXT,
    ip_address           TEXT,
    user_agent           TEXT,
    geolocalizacao       TEXT,
    timestamp_utc        TEXT    NOT NULL
);
