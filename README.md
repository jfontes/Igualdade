# Sistema de Gestão de Obreiros e Familiares — Igualdade Acreana Nº 2

Aplicação web em **Flask + SQLite**. Funciona no navegador e no celular, onde pode ser instalada na tela inicial como aplicativo (PWA).

## Estrutura

```
igualdade/
  __init__.py      configuração da aplicação
  config.py        textos institucionais do painel (fundação, localização) ← editar
  schema.sql       tabelas obreiro e familiar
  db.py            conexão SQLite
  auth.py          login (CIM + senha), troca de senha, permissões
  tesouraria.py    percapitas, pagamentos e permissões do Tesoureiro
  relatorios.py    relatórios (tela, impressão e Excel)
  views.py         painel, minhas informações, familiares, aniversariantes, obreiros
  admin.py         funções da Secretaria + comando criar-admin
  fotos.py         upload e entrega protegida das fotos
  sessoes.py       agenda de sessões
  diretoria.py     gestões e quadro de oficiais (mesa do balaústre)
  balaustre.py     balaústre da sessão e geração do .docx
  templates/       páginas HTML
  static/          CSS, JS, brasão, manifest e service worker
secretaria/        modelo_balaustre.docx e gerar_balaustre.py (usados pelo sistema e pelo assistente do Claude)
instance/          igualdade.db, secret_key e fotos/ (criados automaticamente, fora do git)
wsgi.py            entrada para o PythonAnywhere
```

## Quem pode o quê

| Ação | Obreiro | Tesoureiro | Secretário | Venerável / Administrador |
|---|:-:|:-:|:-:|:-:|
| Painel, quadro de obreiros, agenda, aniversariantes e diretoria | ✔ | ✔ | ✔ | ✔ |
| Editar os próprios dados e familiares | ✔ | ✔ | ✔ | ✔ |
| Ver as próprias percapitas (Minha Tesouraria) | ✔ | ✔ | ✔ | ✔ |
| Funções de Secretaria: cadastrar, editar, afastar e excluir obreiros, redefinir senhas, ver CPF e endereço, diretoria e balaústres | — | — | ✔ | ✔ |
| Funções de Tesoureiro: lançar percapitas, registrar e estornar pagamentos | — | ✔ | — | ✔ |
| Relatórios (obreiros ativos e tesouraria) | — | ✔ | ✔ | ✔ |

- **Cargos:** Tesoureiro, Secretário e Venerável Mestre são reconhecidos pelo cargo na **gestão vigente** da Diretoria. Ao mudar a gestão, o acesso passa aos novos titulares. A lista de cargos com acesso de Secretaria fica em `config.py` (`CARGOS_SECRETARIA`).
- **Administrador:** marcação no cadastro do obreiro, independente de cargo. Tem o mesmo acesso do Venerável. Ninguém altera o próprio. Use para garantir acesso total permanente (por exemplo, entre uma gestão e outra). `flask --app igualdade criar-admin` liga a marcação pela linha de comando.

- **Login:** CIM + senha. Ao cadastrar um obreiro, a senha inicial é o **CPF (somente números)**, e o sistema exige a troca no primeiro acesso.
- **Afastado:** some da lista de ativos e dos aniversariantes e perde o acesso. O histórico é mantido.
- **Exclusão:** remove o obreiro e todos os seus familiares (RN02). Para preservar o histórico, prefira registrar o afastamento. Obreiros com percapitas ou pagamentos não podem ser excluídos.

## Diretoria e balaústre

1. **Diretoria** (*Obreiros → Diretoria → Nova gestão*): informe o período da gestão e o quadro de oficiais. Os nomes são sugeridos a partir dos obreiros ativos; uma nova gestão começa com os nomes da anterior. Venerável, Vigilantes, Orador e Secretário são obrigatórios, pois formam a mesa.
2. **Balaústre** (*Agenda → toque na sessão → Lavrar balaústre*): a mesa vem da diretoria vigente na data da sessão e pode ser alterada em caso de substituição. Data, grau e tipo vêm da agenda. Salve durante a sessão quantas vezes quiser; os botões *Agora* preenchem os horários.
3. **Documento:** *Salvar e gerar .docx* baixa o balaústre no modelo oficial. Sem Landmark, Ordem do dia ou Tronco, o sistema pede confirmação antes de gerar.

Sem diretoria cadastrada para a data, o sistema leva primeiro ao cadastro da diretoria. As tabelas novas (`gestao`, `diretoria`, `balaustre`) são criadas automaticamente em bancos existentes.

## Eventos na agenda

Além das sessões e dos aniversários, a agenda mostra a **previsão de eventos** (ex.: Dia das Mães, Arraial), em **amarelo**. Eventos não são sessões: não têm grau nem balaústre e podem cair no mesmo dia de uma sessão. A Secretaria inclui pelo botão **＋ Evento** de cada mês em *Agenda → Gerenciar* (ou edita tocando no evento na agenda); há data, hora, local, descrição e cancelamento com motivo. O próximo evento aparece na página inicial.

Eventos que tinham sido cadastrados como "sessão extraordinária" com a ordem do dia `Evento: <nome>` são movidos automaticamente para a tabela de eventos quando o sistema inicia (só os que não têm balaústre).

## Tesouraria (percapitas)

Percapita é a contribuição semestral. Valores ficam em centavos no banco.

- **Lançamento anual** (*Tesouraria → Gestão → Lançar percapitas*): o Tesoureiro informa o valor do semestre (o mesmo nos dois; o sistema sugere o do ano anterior). Uma prévia mostra quem recebe e quem fica de fora; o lançamento geral é feito **uma vez por ano** e pode ser desfeito enquanto não houver pagamento no ano.
- **Quem deve:** obreiros ativos. Afastados não geram percapita. Iniciado ou filiado passa a dever **no semestre seguinte** ao ingresso. **Emérito (= Remido)** fica isento a partir do semestre seguinte ao título; ao gravar a data de Emérito, a Secretaria dispara a **isenção automática** do saldo em aberto desses semestres.
- **Vencimento:** 5º dia útil de fevereiro (1º semestre) e de julho (2º), sem contar fins de semana e feriados (lista em `config.py`).
- **Ingresso depois do lançamento:** lançamento individual, pelo perfil do obreiro (*Tesouraria → Lançar percapita*); os semestres devidos já vêm marcados.
- **Pagamento** (perfil do obreiro → *Registrar pagamento*): vem com a data de hoje e PIX; formas: PIX, Dinheiro, Cartão, Abatimento em crédito e Isenção. O valor é distribuído no ano: primeiro o 1º semestre, o excedente vai para o 2º; nunca pode passar do saldo do ano. Parcelas são pagamentos sucessivos.
- **Correções:** nada é apagado. Percapitas sem pagamento podem ser **canceladas** e pagamentos **estornados**, sempre com motivo, autor e data. Obreiro com movimento financeiro não pode ser excluído (use o afastamento).
- **Caixa:** Abatimento em crédito e Isenção quitam a percapita, mas não entram no total recebido em caixa.

## Relatórios

*Início → Relatórios*. Cada relatório pode ser impresso ou salvo em PDF (layout A4 com cabeçalho da Loja) e baixado em Excel: Obreiros ativos (grau, Mestre Instalado, Emérito, VM de Honra), Situação do ano, Inadimplentes, Recebimentos por período, Resumo anual e Extrato individual.

## Rodar no computador

```bash
pip install -r requirements.txt
python scripts/importar_dados.py      # cria o banco com os dados da pasta data/ (ver abaixo)
flask --app igualdade criar-admin     # informe o seu CIM: você vira administrador
flask --app igualdade run --debug     # abre em http://127.0.0.1:5000
```

Para começar com o banco vazio, troque a importação por `flask --app igualdade init-db`.

## Importação inicial dos dados

O script `scripts/importar_dados.py` lê os arquivos da pasta `data/` e cria o `instance/igualdade.db`. O script e a pasta `data/` ficam fora do git (só no computador da Secretaria) porque contêm dados pessoais. No servidor não é preciso importar nada: basta enviar o `instance/igualdade.db` pela aba *Files*.

| Arquivo | Uso |
|---|---|
| `database.json` | fonte principal: obreiros ativos |
| `aniversarios.json` | aniversários de obreiros e familiares (só dia e mês) |
| `Cadastro Novembro de 2012.xlsx` | ex-obreiros (tabela `obreiro_historico`) e ano de nascimento de familiares |
| `Relatório Igualdade Acreana.pdf` | CPFs e ex-obreiros de 2019 |
| `QUADRO DE OBREIROS - LOJA 02.pdf` | conferência do quadro de jan/2025 (não é lido pelo script) |

- Cada correção de dados e cada associação de nome do `aniversarios.json` está escrita no próprio script (`CORRECOES`, `ANIVERSARIOS`).
- O resultado, com as pendências para conferir, fica em `data/relatorio_importacao.md`.
- Para refazer a importação: `python scripts/importar_dados.py --substituir`. Isso apaga obreiros e familiares, mas preserva quem é administrador e a senha dele. Use só antes de os obreiros começarem a usar o sistema; depois disso, as alterações feitas por eles se perderiam.

Para testar no celular na mesma rede Wi-Fi: `flask --app igualdade run --host 0.0.0.0` e acesse `http://IP-DO-PC:5000`.

## Publicar no PythonAnywhere

1. **Enviar o código.** Abra um console *Bash* no PythonAnywhere e rode:
   ```bash
   git clone <url-do-repositorio> ~/Igualdade
   ```
   Sem repositório, envie os arquivos pela aba *Files* para `/home/SEU_USUARIO/Igualdade`.
2. **Criar o ambiente virtual** (no mesmo console):
   ```bash
   cd ~/Igualdade
   python3.12 -m venv ~/.venvs/igualdade
   source ~/.venvs/igualdade/bin/activate
   pip install -r requirements.txt
   ```
   Depois, pela aba *Files*, envie o banco já importado no seu computador (`instance/igualdade.db`) para `/home/SEU_USUARIO/Igualdade/instance/`. Ele já inclui o administrador criado com `criar-admin`.
3. **Criar o site** na aba *Web*: *Add a new web app* → *Manual configuration* → Python 3.12.
4. **Ajustar o site**, ainda na aba *Web*:
   - *Source code*: `/home/SEU_USUARIO/Igualdade`
   - *Virtualenv*: `/home/SEU_USUARIO/.venvs/igualdade`
   - *Static files*: URL `/static/` → diretório `/home/SEU_USUARIO/Igualdade/igualdade/static`
   - *Force HTTPS*: **Enabled**
5. **Configurar o WSGI.** Clique no arquivo WSGI (link na aba *Web*), apague todo o conteúdo e coloque:
   ```python
   import os, sys
   caminho = "/home/SEU_USUARIO/Igualdade"
   if caminho not in sys.path:
       sys.path.insert(0, caminho)
   os.environ["COOKIE_SEGURO"] = "1"
   from wsgi import application
   ```
6. Clique em **Reload**. O sistema fica disponível em `https://SEU_USUARIO.pythonanywhere.com`.

**Atualizar depois de mudanças:** `cd ~/Igualdade && git pull` e depois **Reload**.

> No plano gratuito, o PythonAnywhere desativa o site se você não clicar em *Run until 3 months from today* (aba *Web*) a cada 3 meses.

## Banco de dados: tempo de espera de gravação

- **5 segundos.** Se duas gravações coincidirem, a segunda espera até 5 s antes de desistir com "database is locked". Ajustável com a variável `SQLITE_TIMEOUT` (em segundos).
- O banco usa o modo padrão do SQLite (não WAL), adequado ao sistema de arquivos do PythonAnywhere.

## Backup

Os dados ficam em dois lugares: o banco `instance/igualdade.db` e a pasta de fotos `instance/fotos/`. Para automatizar, crie uma *Scheduled Task* diária:

```bash
cd ~/Igualdade/instance && tar czf ~/backups/igualdade-$(date +%F).tar.gz igualdade.db fotos
```

(crie antes a pasta com `mkdir ~/backups`)

Novas colunas e tabelas são acrescentadas automaticamente a bancos antigos quando o sistema inicia — basta atualizar o código e recarregar o site.

## Outras hospedagens

Avaliação da DiaCloud (plano Diamond), com os cuidados para manter banco e fotos em área persistente: [docs/hospedagem-diacloud-diamond.md](docs/hospedagem-diacloud-diamond.md).

## Instalar no celular

Abra o endereço do sistema no navegador do celular:
- **Android (Chrome):** menu ⋮ → *Adicionar à tela inicial* / *Instalar app*.
- **iPhone (Safari):** botão Compartilhar → *Adicionar à Tela de Início*.
