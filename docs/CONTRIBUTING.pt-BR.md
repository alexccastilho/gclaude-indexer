*Leia isto em outros idiomas: [English](../CONTRIBUTING.md) · [Español](CONTRIBUTING.es.md)*

# Contribuindo com o GClaude Indexer

Obrigado por considerar contribuir. Este documento cobre como preparar um
ambiente de desenvolvimento, rodar a suíte de testes e as convenções que o
código segue.

## Só roda no Windows

O GClaude Indexer roda **só no Windows**. Não é uma lacuna de portabilidade
a ser corrigida incidentalmente — o código conversa de propósito com
superfícies específicas do Windows: PowerShell (scripts de instalação e
inicialização), WMI (sensores de hardware e recursos) e o registro do
Windows (detecção de idioma/localidade). Contribuições que adicionem uma
camada de abstração multiplataforma sem uma necessidade concreta estão fora
de escopo; contribuições que corrijam um bug real do Windows, ou ampliem
funcionalidade específica dele, são muito bem-vindas.

## Você não precisa do Claude Code

O nome do projeto menciona Claude, mas **o Claude Code é opcional**, tanto
para usar o software quanto para contribuir com ele. A classificação dos
itens do acervo é feita por um de três motores intercambiáveis (mais um
modo `automatic`, que escolhe entre os dois primeiros conforme o hardware
da máquina):

- `rules` — determinístico, não exige nenhuma ferramenta externa.
- `local` — usa um modelo do Ollama rodando localmente.
- `claude_code` — delega a classificação ao Claude Code, para quem já o
  tem instalado.

Os motores `rules` e `local` bastam para rodar o pipeline inteiro, de ponta
a ponta, e para trabalhar em quase tudo neste repositório. Você só precisa
do Claude Code se estiver mexendo especificamente em
`gclaude_indexer/engine_claude_code.py` ou `gclaude_indexer/claude_package.py`
— e mesmo assim a suíte de testes simula a chamada de subprocesso: não é
preciso ter o Claude Code instalado para rodar os testes.

## Preparando o ambiente

1. Instale o Python 3.12. O ambiente **não pode** morar dentro de uma pasta
   sincronizada pelo Google Drive/OneDrive/etc — a trava de arquivo durante
   a sincronização quebra SQLite e ambientes virtuais. A convenção usada
   neste projeto é um venv em `%LOCALAPPDATA%\GClaudeIndexer\venv`.

   ```powershell
   py -3.12 -m venv "$env:LOCALAPPDATA\GClaudeIndexer\venv"
   ```

2. Instale as dependências:

   ```powershell
   & "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pip install -r requirements.txt
   ```

3. Alternativa: rode o script instalador, que faz o mesmo acima e ainda
   confere Tesseract/Ghostscript e oferece criar um atalho na área de
   trabalho:

   ```powershell
   powershell -ExecutionPolicy Bypass -File install.ps1
   ```

## Rodando os testes

Sempre use o interpretador do venv, nunca o `python` que o `PATH` resolver
sozinho (um Python mais novo e sem versão fixada quebra as versões fixadas
das dependências):

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -B -m pytest -q
```

A suíte precisa passar por inteiro antes e depois da sua mudança. Se você
estiver trabalhando num único arquivo de teste durante o desenvolvimento:

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -B -m pytest tests/test_something.py -v
```

O projeto não usa repositório git no momento; onde um fluxo normal pediria
um commit a cada passo, rode a suíte completa em vez disso.

## Convenções

### Todo texto de interface passa pelo i18n, nos três idiomas

Toda string que o usuário vê na interface web precisa ser uma chave de
tradução resolvida por `gclaude_indexer/web/i18n.py`, com uma entrada nas
**três** tabelas de idioma: `pt`, `en`, `es`. Uma chave presente em só um
idioma cai no padrão silenciosamente e reintroduz um vazamento de idioma —
já foi uma classe de bug recorrente neste projeto. Ao acrescentar uma nova
string visível ao usuário, acrescente-a aos três dicionários na mesma
mudança.

### A lógica devolve chaves estáveis em ASCII; o template traduz

A lógica de negócio (rotas, tarefas em segundo plano, cálculo de situação)
nunca deve devolver texto num idioma específico nem identificador
acentuado. Ela devolve uma chave estável, em ASCII, minúscula (ex.:
`"done"`, `"scan"`, `"failed"`), com um único papel: identificar um
estado. Essa chave é então usada, sem modificação, como:

- a busca em `i18n.py` para o texto mostrado na tela, e
- o nome da classe CSS, quando aplicável.

Não deixe um único valor servir ao mesmo tempo de texto exibido, classe CSS
e valor de comparação — essa sobrecarga foi a causa de vários defeitos de
interface corrigidos na fase 12 (uma string de situação acentuada servindo
ao mesmo tempo de classe CSS e de valor comparado para decidir qual etapa
roda a seguir). Se você acrescentar um novo estado, crie primeiro a chave
em ASCII, depois as três traduções.

### Renomeações e traduções são mecânicas

O código (identificadores, comentários, docstrings, esquema do banco) está
hoje inteiramente em inglês — essa migração está concluída. Se você ainda
encontrar algum identificador em português esquecido, traduzi-lo é
bem-vindo; mantenha a mudança mecânica: mesmo comportamento, mesmos testes
(ajustados só onde afirmam sobre identificador/texto renomeado). Não
misture uma melhoria de lógica na mesma mudança — misturar refatoração com
renomeação em massa é como uma regressão se esconde num diff que, de outro
modo, seria fácil de revisar.

### O projeto é offline

Nenhuma chamada de rede em tempo de execução, exceto para
`http://127.0.0.1:11434` (a instância local do Ollama, sempre loopback,
nunca configurável para um host remoto). Não acrescente uma dependência
que exija acesso à rede para funcionar.

## Estilo de código

- Python 3.12, sem formatador externo obrigatório ainda; siga o estilo do
  arquivo em que estiver mexendo.
- `from __future__ import annotations` no topo dos módulos que já o usam
  (depois do cabeçalho de licença e do docstring do módulo).
- Todo arquivo `.py` dentro de `gclaude_indexer/` traz um cabeçalho GPL
  curto no topo (veja qualquer arquivo existente para o texto exato).
  Acrescente-o também em arquivos novos.

## Licença

Ao contribuir, você concorda que sua contribuição é licenciada sob a GNU
General Public License v3.0, a mesma licença do restante do projeto (veja
`LICENSE`).
