*Leia em outros idiomas: [English](../CONTRIBUTING.md) (original) · [Español](CONTRIBUTING.es.md)*

# Contribuindo com o GClaude Indexer

Obrigado por considerar uma contribuição. Este documento explica como preparar um ambiente de desenvolvimento, rodar a suíte de testes e as convenções de que o código depende. A documentação para quem usa é o [README](README.pt-BR.md); a referência técnica é o [docs/TECHNICAL.pt-BR.md](TECHNICAL.pt-BR.md).

## Só Windows

O GClaude Indexer roda **só no Windows**. Não é uma lacuna de portabilidade a ser corrigida de passagem: o código conversa de propósito com interfaces específicas do Windows. PowerShell (instalador e lançadores), WMI (sensores de hardware e de recursos), o registro do Windows (idioma de exibição) e Performance Counters (os gráficos de CPU e GPU). Contribuições que acrescentem camadas de abstração multiplataforma sem uma necessidade concreta estão fora do escopo; contribuições que corrijam um defeito real no Windows, ou estendam uma função específica do Windows, são muito bem-vindas.

## Você não precisa do Claude Code

O nome do projeto menciona o Claude, mas **o Claude Code é opcional**, tanto para usar o programa quanto para contribuir. A classificação das peças é feita por um de três motores intercambiáveis (mais um modo `automatic`, que escolhe entre os dois primeiros pelo hardware da máquina):

- `rules`: determinístico, não exige nenhuma ferramenta externa.
- `local`: usa um modelo do Ollama rodando localmente.
- `claude_code`: delega a classificação ao Claude Code, para quem já o tem instalado.

Os motores `rules` e `local` bastam para rodar o fluxo inteiro e trabalhar em quase tudo deste repositório. Você só precisa do Claude Code se estiver mexendo em `gclaude_indexer/engine_claude_code.py` ou `gclaude_indexer/claude_package.py`, e mesmo assim a suíte de testes simula a chamada de subprocesso. Não é preciso ter o Claude Code instalado para rodar os testes.

## Preparando o ambiente

1. Instale o Python 3.12. O ambiente **não** pode ficar numa pasta sincronizada pelo Google Drive, OneDrive ou similar: a trava de arquivos durante a sincronização quebra o SQLite e os virtualenvs. A convenção do projeto é um venv em `%LOCALAPPDATA%\GClaudeIndexer\venv`.

   ```powershell
   py -3.12 -m venv "$env:LOCALAPPDATA\GClaudeIndexer\venv"
   ```

2. Instale as dependências:

   ```powershell
   & "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pip install -r requirements.txt
   ```

3. Ou rode o script de instalação, que faz o mesmo e ainda confere Tesseract e Ghostscript, baixa as bibliotecas de sensores e oferece um atalho na área de trabalho:

   ```powershell
   powershell -ExecutionPolicy Bypass -File install.ps1
   ```

## Rodando os testes

Use sempre o interpretador do venv, não o `python` que o `PATH` encontrar (um Python mais novo quebra as versões fixadas das dependências):

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -B -m pytest -q
```

A suíte precisa passar inteira antes e depois da sua mudança; leva uns cinco minutos e nunca fala com um Ollama real nem com a rede. Para trabalhar num único arquivo de teste durante o desenvolvimento:

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -B -m pytest tests/test_algo.py -v
```

A suíte grava os dados de idioma do OCR de que precisa na pasta real `%LOCALAPPDATA%\GClaudeIndexer\tessdata` da máquina; nada mais fora das pastas temporárias é tocado.

O trabalho é commitado por tarefa, um commit por mudança fechada, em `main`. O GitHub Actions roda a suíte e indexa o acervo de demonstração (`demo/acervo`) a cada push, anexando o relatório de acerto à rodada.

## Convenções

### Todo texto da interface passa pelo i18n, nos três idiomas

Toda string que uma pessoa vê na interface web precisa ser uma chave de tradução resolvida por `gclaude_indexer/i18n.py`, com entrada nas **três** tabelas de idioma: `pt`, `en`, `es`. Uma chave presente em só um idioma cai no padrão em silêncio e reintroduz um vazamento de idioma, que já foi uma classe recorrente de defeito neste projeto. Ao acrescentar uma string nova, acrescente-a aos três dicionários na mesma mudança. Um teste confere que as três tabelas têm as mesmas chaves e os mesmos marcadores.

### A lógica devolve chaves ASCII estáveis; o template traduz

A lógica de negócio (rotas, tarefas em segundo plano, cálculo de situação) nunca devolve texto de idioma nem identificadores acentuados. Devolve uma chave estável, ASCII, minúscula (por exemplo `"done"`, `"scan"`, `"failed"`), com uma única função: identificar um estado. Essa chave é usada, sem alteração, como índice em `i18n.py` para o texto da tela e como nome de classe CSS quando couber.

Não deixe um único valor servir ao mesmo tempo de texto exibido, classe CSS e valor de comparação. Essa sobrecarga foi a causa de vários defeitos de interface corrigidos na fase 12 (uma situação acentuada que era classe CSS e, ao mesmo tempo, o valor comparado para decidir a próxima etapa). Ao acrescentar um estado novo, crie primeiro a chave ASCII e depois as três traduções.

### Renomeações e traduções são mecânicas

O código (identificadores, comentários, docstrings, esquema do banco) está em inglês; essa migração está concluída. Se ainda encontrar um identificador em português, traduzi-lo é bem-vindo; mantenha a mudança mecânica: mesmo comportamento, mesmos testes (ajustados só onde afirmam sobre o identificador renomeado). Não misture uma melhoria de lógica na mesma mudança. Misturar refatoração com renomeação em massa é como regressões se escondem num diff que de outro modo seria revisável.

### Comentários dizem por quê, com números e datas

Um comentário que explica uma decisão não óbvia diz o que foi medido, onde e quando ("a flash attention dobrou o tempo de leitura do prompt na RX 6700 XT via Vulkan, 02/11/2026"). Quem ler duas versões depois pode medir de novo em vez de adivinhar se o motivo ainda vale.

### O projeto é offline

Nenhuma chamada de rede em tempo de execução, exceto para `http://127.0.0.1:11434` (o Ollama local, sempre loopback, nunca configurável para um servidor remoto) e o serviço de busca do LexML (na tela, só com a caixa marcada; no `buscar.bat`, também quando nenhuma norma do acervo cita o termo), que envia só o termo digitado e nunca nada do acervo. Não acrescente dependência que precise de rede para funcionar. O prompt do classificador, o vocabulário das regras e o leitor do Planalto são botões de comportamento: mudanças neles exigem uma nova medição contra `demo/gabarito.csv` e a atualização de `docs/QUALITY.md`.

### A documentação se lê como escrita por uma pessoa

README, manual e documentos técnicos seguem a mesma regra nos três idiomas: nenhum travessão ou meia-risca como aparte, aspas retas, três pontos em vez do caractere de reticências, nenhum vocabulário inflado, nenhum "não é X, é Y". Um teste em `tests/test_phase38_docs.py` falha na primeira violação.

## Gerando o instalador do Windows

O instalador é um script do Inno Setup, `installer/GClaudeIndexer.iss`, gerado por `installer/build.ps1` com o Inno Setup 6 (`ISCC.exe`, procurado em `Program Files` ou em `%LOCALAPPDATA%\Programs`). Ele lê a versão de `SYSTEM_VERSION` em `gclaude_indexer/web/app.py` e grava `dist/GClaude-Indexer-Setup-<versão>.exe`. O pacote leva o código, a documentação e o `install.ps1`; na instalação roda o `install.ps1` com os componentes que a pessoa marcou. O que o instalador embute e o que baixa na hora:

- **Python 3.12.** As versões fixadas em `requirements.txt` não instalam em interpretadores mais novos, então o `install.ps1` procura a 3.12 e, quando a máquina não tem, baixa a 3.12.10 oficial para o usuário atual (versão exata, checksum conferido), sem administrador e sem tocar em nenhum outro Python.
- **Tesseract OCR e Ghostscript.** Baixados das URLs oficiais de release, versão fixada e hash conferido. O instalador do Ghostscript não roda sem interação (`requireAdministrator`, e o `/S` deixou de silenciá-lo na 10.01.0), então o `install.ps1` desempacota o conteúdo em vez de executá-lo. Os dados de idioma do OCR (`por`, `eng`, `spa`, `osd`, cada um com SHA-256 fixado) vão para `%LOCALAPPDATA%\GClaudeIndexer\tessdata` quando a pasta do Tesseract exige administrador.
- **As bibliotecas de sensores.** `LibreHardwareMonitorLib.dll`, `HidSharp.dll` e as cinco DLLs de compatibilidade do .NET de que elas precisam (o layout exato está em `gclaude_indexer/install_diagnostics.py`), copiadas para `%LOCALAPPDATA%\GClaudeIndexer\lib\`. O driver opcional PawnIO, para temperatura e consumo da CPU em processadores recentes, é um componente à parte que pede administrador.
- **O Ollama e o modelo** continuam um download opcional e separado: só o modelo tem vários gigabytes, e a pessoa precisa poder recusá-lo sem recusar o resto. O instalador também grava as variáveis de ambiente do usuário de que o servidor do Ollama precisa (`OLLAMA_*` e `LLAMA_ARG_CACHE_RAM`; veja `docs/TECHNICAL.pt-BR.md`, "Rodando no dia a dia") e respeita um valor que a pessoa tenha definido à mão.
- **Atalhos.** O atalho da área de trabalho roda o `Indexer.vbs` (sem janela de console); o atalho opcional "CPU sensor" pede administrador ao abrir, só para o leitor de sensores.

Instalar uma versão nova por cima de uma antiga encerra o servidor que estiver rodando; o desinstalador pergunta, item por item, quais programas compartilhados remover, e nunca toca nos projetos da pessoa.

## Estilo de código

- Python 3.12, sem formatador externo obrigatório; siga o estilo do arquivo ao redor.
- `from __future__ import annotations` no topo dos módulos que já o usam (depois do cabeçalho de licença e da docstring do módulo).
- Todo `.py` em `gclaude_indexer/` leva um cabeçalho curto da GPL no topo (veja qualquer arquivo existente para o texto exato). Acrescente-o aos arquivos novos.

## Licença

Ao contribuir, você concorda que a sua contribuição é licenciada sob a GNU General Public License v3.0, a mesma licença do resto do projeto (veja `LICENSE`).
