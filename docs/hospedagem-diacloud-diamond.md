# Avaliar hospedagem na DiaCloud (plano Diamond)

> Anotação para avaliação futura. Ainda não decidido. Hoje o sistema roda no PythonAnywhere.

## Por que avaliar

- Domínio próprio `.com.br` (no PythonAnywhere exige plano pago).
- Possível ganho de desempenho e controle do servidor.

## O ponto crítico: dados em área persistente

Tudo o que não está no git fica na pasta `instance/` do projeto:

| Arquivo / pasta | O que é | Se perder |
|---|---|---|
| `instance/igualdade.db` | banco SQLite (obreiros, familiares, agenda, balaústres, tesouraria) | perde **todos** os dados |
| `instance/fotos/` | fotos de obreiros e familiares | perde as fotos |
| `instance/secret_key` | chave das sessões (se `SECRET_KEY` não estiver no ambiente) | todos precisam entrar de novo |

Em hospedagem com contêiner ou com disco efêmero, a pasta do código é recriada a cada
implantação. **A pasta `instance/` inteira precisa ficar num volume persistente**, montado
fora do diretório que é substituído no deploy. Exemplos:

- contêiner: montar o volume em `/app/instance` (caminho do projeto + `/instance`);
- VPS: manter o projeto em `/srv/igualdade` e nunca apagar `instance/` ao atualizar (`git pull`).

Hoje dá para apontar só o banco para outro lugar (`DATABASE=/dados/igualdade.db`), mas fotos e
`secret_key` continuam em `instance/`. **Pendência de código, se necessário:** aceitar uma variável
de ambiente para mover a pasta `instance/` inteira (ex.: `IGUALDADE_INSTANCE=/dados`).

### Tipo de disco

O sistema usa SQLite no modo padrão (não WAL). Num servidor com disco local ou volume em bloco,
o modo WAL poderia melhorar a concorrência — avaliar **e decidir antes** de ligar, nunca em sistema
de arquivos de rede.

## Confirmar com a DiaCloud antes de decidir

- [ ] O plano Diamond roda aplicação **Python 3.11+ com WSGI** (Flask)? Por contêiner (Docker), VPS ou painel próprio?
- [ ] Existe **volume / disco persistente**? Ele sobrevive a reinício, redeploy e troca de versão?
- [ ] O volume é **disco local / em bloco** ou de rede? (define se o SQLite poderia usar WAL no futuro)
- [ ] **Backup automático** do volume? Com que frequência e retenção? Dá para baixar?
- [ ] **HTTPS** com certificado gratuito (Let's Encrypt) e **domínio próprio**?
- [ ] Limites: memória, CPU, espaço em disco (fotos crescem ~60 KB cada), tráfego.
- [ ] Custo mensal e forma de cobrança; localização do servidor (Brasil = menor latência).
- [ ] Acesso por **SSH** ou console para rodar `git pull`, `pip install` e `flask criar-admin`.

## Roteiro de implantação (quando decidir)

1. Criar o volume persistente e montá-lo em `<projeto>/instance`.
2. Variáveis de ambiente: `SECRET_KEY` (fixa), `COOKIE_SEGURO=1`; opcional `SQLITE_TIMEOUT`.
3. `pip install -r requirements.txt` e servidor WSGI, por exemplo:
   `gunicorn -w 2 -b 0.0.0.0:8000 wsgi:application` (poucos processos bastam para o tamanho da Loja).
4. Servir `/static/` pelo servidor web (opcional; o Flask também serve).
5. Copiar os dados do PythonAnywhere com o sistema parado: `igualdade.db` + pasta `fotos/`.
6. Apontar o domínio, ativar HTTPS e testar login, fotos, relatórios em Excel e o `.docx` do balaústre.
7. Configurar backup diário do volume (banco + fotos) e testar uma restauração.
