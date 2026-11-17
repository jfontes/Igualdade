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

| Ação | Obreiro | Secretaria (admin) |
|---|---|---|
| Ver painel, quadro de obreiros e aniversariantes | ✔ | ✔ |
| Editar os próprios dados (exceto CIM, CPF e afastamento) | ✔ | ✔ |
| Gerenciar os próprios familiares | ✔ | ✔ |
| Ver CPF e endereço de outros obreiros | — | ✔ |
| Cadastrar, editar, afastar ou excluir obreiros e redefinir senhas | — | ✔ |
| Consultar a diretoria | ✔ | ✔ |
| Cadastrar a diretoria e lavrar balaústres | — | ✔ |

- **Login:** CIM + senha. Ao cadastrar um obreiro, a senha inicial é o **CPF (somente números)**, e o sistema exige a troca no primeiro acesso.
- **Afastado:** some da lista de ativos e dos aniversariantes e perde o acesso. O histórico é mantido.
- **Exclusão:** remove o obreiro e todos os seus familiares (RN02). Para preservar o histórico, prefira registrar o afastamento.

## Diretoria e balaústre

1. **Diretoria** (*Obreiros → Diretoria → Nova gestão*): informe o período da gestão e o quadro de oficiais. Os nomes são sugeridos a partir dos obreiros ativos; uma nova gestão começa com os nomes da anterior. Venerável, Vigilantes, Orador e Secretário são obrigatórios, pois formam a mesa.
2. **Balaústre** (*Agenda → toque na sessão → Lavrar balaústre*): a mesa vem da diretoria vigente na data da sessão e pode ser alterada em caso de substituição. Data, grau e tipo vêm da agenda. Salve durante a sessão quantas vezes quiser; os botões *Agora* preenchem os horários.
3. **Documento:** *Salvar e gerar .docx* baixa o balaústre no modelo oficial. Sem Landmark, Ordem do dia ou Tronco, o sistema pede confirmação antes de gerar.

Sem diretoria cadastrada para a data, o sistema leva primeiro ao cadastro da diretoria. As tabelas novas (`gestao`, `diretoria`, `balaustre`) são criadas automaticamente em bancos existentes.

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

## Backup

Os dados ficam em dois lugares: o banco `instance/igualdade.db` e a pasta de fotos `instance/fotos/`. Para automatizar, crie uma *Scheduled Task* diária:

```bash
cd ~/Igualdade/instance && tar czf ~/backups/igualdade-$(date +%F).tar.gz igualdade.db fotos
```

Novas colunas (como e-mail, telefone e foto) são acrescentadas automaticamente a bancos antigos quando o sistema inicia — basta atualizar o código e recarregar o site.

(crie antes a pasta com `mkdir ~/backups`)

## Instalar no celular

Abra o endereço do sistema no navegador do celular:
- **Android (Chrome):** menu ⋮ → *Adicionar à tela inicial* / *Instalar app*.
- **iPhone (Safari):** botão Compartilhar → *Adicionar à Tela de Início*.
