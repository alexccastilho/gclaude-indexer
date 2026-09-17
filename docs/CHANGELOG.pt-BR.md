# Registro de mudanças

Todas as mudanças relevantes deste projeto estão documentadas neste
arquivo. O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/).

> **Tradução.** O documento canônico é o
> [`CHANGELOG.md`](../CHANGELOG.md) em inglês. Se os dois divergirem, vale
> o inglês. Nomes de arquivo, identificadores de código, chaves de
> configuração e mensagens que o programa emite em inglês foram mantidos
> como estão.

As entradas estão agrupadas por fase de desenvolvimento, seguindo os
documentos de planejamento do próprio projeto em
`docs/superpowers/plans/`, e não por versão semântica — a versão
reportada pelo aplicativo (`SYSTEM_VERSION`, em `web/app.py`) ficou em
`1.0.0` da fase 1 até a fase 16. A `1.0.1` é o primeiro incremento, e
publica tudo o que o bloco da fase 16, mais abaixo, vinha carregando como
não lançado.

## [1.3.4] — 2026-09-17

### Manutenção — um diretório de ferramentas, e quatro versões adiante

Nenhum comportamento do aplicativo muda nesta versão. O que muda é o que o
repositório carrega ao lado dele, e quais versões uma instalação nova
baixa.

#### Adicionado

- **`tools/`, para operações que o produto não oferece.** Scripts de
  manutenção rodados à mão contra a pasta de saída de um projeto já
  indexado; o instalador não os distribui e a interface não os chama. O
  primeiro, `reprocessar_janelas_com_falha.py`, devolve para `pending`
  apenas as janelas que falharam numa corrida da etapa 6, para que uma
  nova classificação tente de novo só essas em vez de reindexar o acervo
  inteiro — a única transição de janela no código é `pending -> done`, e a
  atualização incremental (fase 17) reage a mudanças nos *arquivos de
  origem*, então com os PDFs intactos ela não invalida nada. Ele se recusa
  a reabrir uma janela que o acervo não tem mais, e a reabrir falhas que
  repetir não resolve. Coberto por `tests/test_tools_reprocessamento.py`.

#### Alterado

- **Quatro versões fixadas foram adiante**, cada uma mergeada com a suíte
  inteira verde: `pillow` 10.4.0 → 12.3.0, `jinja2` 3.1.4 → 3.1.6,
  `python-multipart` 0.0.12 → 0.0.31 e `pytest` 8.3.3 → 9.0.3. As ações do
  CI também: `actions/checkout` 5 → 7 e `actions/setup-python` 6 → 7.

  Isso pesa mais do que uma atualização de rotina porque o instalador
  empacota o `requirements.txt` e o `install.ps1` roda `pip install -r` a
  partir dele na máquina do usuário: até esta versão, uma instalação nova
  baixava as versões fixadas lá na 1.3.0. Os avisos do `jinja2` são sobre o
  ambiente com sandbox, que este projeto não usa — ele renderiza os
  próprios modelos via `Jinja2Templates` — então a atualização é higiene,
  não uma exposição sendo fechada. O `pillow` é o que mereceu conferência
  além da suíte: são dois majors de salto, e ele é alcançado por
  `_extract_text_image`, o caminho de OCR de arquivos de imagem soltos.

## [1.3.3] — 2026-09-17

### Fase 22 — "Importar e gerar relatórios" num drive de rede

A fase 21 corrigiu a classificação. Quem ficou de pé foi a etapa *depois*
dela: num acervo real de 2904 páginas cuja pasta de saída fica no Google
Drive, a classificação levou 5h18 e aí **"Importar e gerar relatórios"
levou mais 38 minutos sozinho**, sem barra de progresso e sem nenhum sinal
de que estava trabalhando em vez de travado. O trabalho nunca esteve em
risco — as 5230 peças eram todas válidas — mas a tela não dizia isso,
então o botão foi clicado de novo. E de novo.

#### Corrigido

- **A checagem de intervalo para de reler as mesmas páginas uma vez por
  peça.** `_validate_range_within_group` pede ao banco todas as páginas do
  agrupador da peça, para conferir que o intervalo dela existe. Pedia uma
  vez por peça: **5230 consultas onde 3 bastavam**, porque o acervo tem 3
  agrupadores — e um deles, com 2830 páginas, responde por 5093 dessas
  peças. O intervalo só depende do agrupador, então passa a ser lido uma
  vez por agrupador e guardado durante a corrida. Medido nesse acervo:
  **45,2s → 0,07s** em disco local, e **~41 min → 0,59s** com o banco no
  Drive, onde cada uma dessas consultas custava 488 ms em vez de 9,3 ms. A
  importação mais todos os relatórios agora leva 0,21s onde levava quase
  uma hora.

- **Um segundo clique não começa uma segunda importação.** Diferente das
  etapas do pipeline, essa rota faz o trabalho dentro da requisição HTTP,
  então não tem registro no `task_manager` e nada conferia se ela já
  estava rodando. Um dump da pilha do servidor em uso mostrou **4 threads
  `import_and_generate` simultâneas**, cada uma tomando o GIL por vez e
  cada uma prestes a rodar `DELETE FROM item` seguido de 4210 inserções no
  mesmo arquivo SQLite. Todas terminaram, e todas gravaram o mesmo
  resultado — mas levaram de 36 a 54 minutos cada. Um clique que cai sobre
  uma corrida já em andamento agora vai direto para a tela de Resultado.

640 testes passando, contra 638.


## [1.3.2] — 2026-09-16

### Fase 21 — contexto calibrado e nota honesta

A fase 20 corrigiu o mecanismo e manteve o número errado que o alimenta.
Numa indexação real de 2904 páginas na 1.3.1, **153 de 1449 janelas
entraram no índice sem classificação nenhuma** — 612 peças, 11% do
índice, com tipo, data e autor vazios e o OCR cru no lugar do resumo. O
log fechou em `baixa=0` e a nota deu 89/100.

#### Corrigido

- **A razão caracteres/token deixa de ser um palpite.** `_CHARS_PER_TOKEN`
  valia 3,0, medida em prosa portuguesa. O acervo é um processo com
  volumes de prestação de contas, e tabela contábil tokeniza a **1,45** —
  o recálculo por janela da fase 20 rodava e chegava curto toda vez. A
  razão passa a ser aprendida durante a corrida com o `prompt_eval_count`
  que o Ollama já devolve e o código descartava, guardando o mínimo
  observado, com piso de 1,2. Medido no acervo real: a razão converge para
  1,45 e as janelas que davam 0 de 4 páginas passam a sair com 4 de 4,
  todas de confiança alta.

- **Escada de retentativa.** O gatilho é "linhas devolvidas < páginas da
  janela", que não depende de comportamento interno do Ollama. A
  telemetria só escolhe o próximo contexto: prompt cortado dobra, prompt
  íntegro com resposta faminta usa `prompt_eval + páginas × 220`. Acima do
  teto da placa, medido por corrida, a janela é subdividida em vez de
  transbordar para a RAM.

- **A resposta sem orçamento.** Modo de falha que ninguém tinha visto: em
  `num_ctx` 5120 o prompt de 5091 tokens cabe inteiro e sobram 29 para
  responder. O JSON sai cortado e o log diz a mesma coisa do truncamento,
  por causa oposta. A detecção passa a olhar os dois lados.

- **A cobertura media coisa nenhuma.** A consulta comparava `page.number`,
  que é a página dentro do arquivo, com `item.start_order`, que é a folha
  do grupo, sem join por grupo. Prova direta: removendo 967 peças do
  índice — um buraco de 500 folhas — ela seguiu marcando 100,0% onde o
  valor real era 82,7%.

- **A nota deixa de se pagar sozinha.** Os 40 pontos de cobertura eram
  tautológicos: o agrupamento emite uma peça por página da janela, então a
  página está sempre dentro de alguma peça. Passam a medir cobertura
  *classificada* — páginas que o modelo descreveu. A mesma corrida que
  valia 89 vale **83**, e é sobre 83 que a correção mostra ganho.

- **A peça cega para de se passar por mediana.** A página sobre a qual o
  modelo não disse nada continua entrando no índice pelo agrupamento —
  essa garantia é o que impede a perda — mas agora com confiança `baixa`.
  É o que devolve sentido ao `baixa=` do resumo da etapa 6.

### Adicionado

- **A linha do índice leva à página física do PDF.** `f. 417` é a página
  145 do `Vol 2.pdf`, e o grupo tem 21 volumes; o índice nomeava o arquivo
  e parava aí.

- **Índice por grupo, com sumário.** O `index.md` saía com 5443 linhas e
  1,58 MB num arquivo só, demais para um Projeto do Claude consultar de
  forma confiável. Ele vira um sumário de poucos KB que aponta o grupo e o
  arquivo; a tabela de cada grupo vai para `index-<grupo>.md`, e o pacote
  do Projeto leva todos.

638 testes passando, contra 618.


## [1.3.1] — 2026-09-15

Fase 20. Três coisas que uma corrida real perdia em silêncio.

Achadas lendo o log de uma indexação de 2904 páginas (44 arquivos, 484
janelas, `qwen3.5:4b` numa RTX 3060 Laptop). Nada tinha quebrado — a
corrida reportou `0 falhou(aram)` em todas as etapas — e era esse o
problema: os três defeitos se reportavam como advertência, ou como nada.

### Corrigido

- **A peça não é mais jogada fora por causa da precisão da data.**
  Documentos contábeis e administrativos são datados por período —
  "competência 01/2020", "exercício 2019" — e o modelo devolve `2020-01`
  porque é o que a página diz. A validação exigia `AAAA-MM-DD` estrito e
  descartava a peça *inteira* — tipo, autor, resumo e tudo — por causa de
  um campo opcional. Eram as 20 de 20 peças recusadas da corrida.

  A precisão reduzida passa a ser guardada como veio. É ISO 8601
  legítima e, o que decide a questão aqui, ordena corretamente na
  ordenação lexicográfica que a linha do tempo em `artifacts.py` já usa
  (`2019-12` < `2020-01` < `2020-01-05`) — então não há nada a ganhar
  inventando um primeiro-dia-do-mês que o documento nunca afirmou. Uma
  data cuja precisão fina não se sustenta cai um degrau em vez de sumir:
  `2021-09-31`, um dia que não existe, vira `2021-09`, porque o mês
  continua bom. Texto que não é data nenhuma — um intervalo, uma data em
  formato brasileiro — limpa o campo, e a peça é gravada sem ele.

- **Uma peça recusada não leva mais as páginas dela junto.** A garantia
  de cobertura rodava *antes* da validação, então as páginas cobertas só
  por uma peça que a validação depois recusava acabavam em peça nenhuma —
  em silêncio, já que o aviso de cobertura tinha decidido que nada
  faltava. Na corrida observada, foram 20 faixas de páginas ausentes de
  um índice cujo propósito inteiro é dizer em que página está cada coisa.
  A cobertura passa a ser calculada a partir das peças que de fato
  sobreviveram à validação.

- **O contexto do Ollama é medido por janela, não uma vez por corrida.**
  Ele era dimensionado pelo prompt da primeira janela e congelava ali.
  Uma janela mais densa adiante o estourava, a resposta voltava
  truncada, o JSON nunca fechava e o parser recebia zero linhas — a
  janela chegava ao índice sem classificação nenhuma, só com um aviso
  dizendo que o modelo não havia respondido sobre nenhuma de suas
  páginas. Foram 72 das 484 janelas da corrida (~15%), que é a maior
  parte do que ela reportou como confiança média. O contexto agora é
  remedido sempre que uma janela precisa de mais que a mais larga até
  então, e só cresce — um `num_ctx` oscilante faria o Ollama recarregar o
  modelo entre janelas, que era justamente o que a medição única evitava.

## [1.3.0] — 2026-09-13

Fase 19. Um instalador para quem não abre terminal.

### Adicionado

- **Um instalador para Windows.** `GClaude-Indexer-Setup-1.3.0.exe`,
  compilado com o Inno Setup a partir de `installer/GClaudeIndexer.iss`.
  Ele pergunta onde instalar (só para você ou para a máquina toda),
  mostra o texto da GPL-3.0 — a licença que está sendo concedida, não
  termos sendo impostos — e põe todas as dependências numa página só, com
  uma caixa para cada: Tesseract e Ghostscript marcados e travados,
  porque sem OCR o programa não faz aquilo para que existe, e Ollama, o
  modelo de classificação, as bibliotecas de sensor e o atalho do sensor
  de CPU deixados a critério de quem instala. Tudo é baixado e instalado
  com barra de progresso e sem que nenhuma janela de terminal apareça em
  momento algum.

  Ele não é assinado digitalmente. Um certificado custa dinheiro que este
  projeto não tem, então o SmartScreen avisa antes de executá-lo; cada
  release publica o SHA-256 do arquivo.

- **Um desinstalador que pergunta o que deve sair.** Remover o programa
  em Configurações > Aplicativos abre um diálogo com uma caixa para cada
  dependência compartilhada — Tesseract, Ghostscript, Ollama, os modelos
  baixados, Python 3.12 — e remove o que estiver marcado e nada mais.
  Quem quer o Ollama fora pode muito bem continuar usando o Ghostscript.
  A lista de projetos nunca é tocada: ela fica atrás de um interruptor
  que nada no instalador aciona.

- **Um log para os dois.** `%LOCALAPPDATA%\\GClaudeIndexer\\install-log.txt`
  e `uninstall-log.txt`, em UTF-8. A primeira versão disso rodava oculta e
  silenciosa, e quando um usuário relatou que nada tinha sido instalado
  não havia como saber se o script tinha falhado, rodado pela metade, ou
  funcionado enquanto ele olhava cedo demais.

- **A página do projeto na tela Sobre.** O único link para fora do
  sistema, e ele não enfraquece a promessa de funcionamento offline: nada
  é buscado e nada é enviado — a página só abre se a pessoa clicar.

### Corrigido

- **O instalador não executava absolutamente nada na pasta padrão.** Ele
  montava uma linha de comando
  `cmd /c ""powershell.exe" -File ""<caminho>"" ..."`, e as aspas
  duplicadas de que o parsing do próprio cmd precisa não sobreviviam ao do
  PowerShell: em `C:\\Program Files\\GClaude Indexer` o caminho era cortado
  no espaço, o PowerShell recusava `-File 'C:\\Program'` e caía no prompt
  interativo — uma janela preta diante de uma instalação onde nenhuma
  dependência tinha sido instalada. A sentinela escondia isso: `& echo
  %ERRORLEVEL%` rodava tendo o PowerShell iniciado ou não, então o
  assistente lia um código e ia para a página final. O desinstalador usava
  a mesma linha de comando e falhava do mesmo jeito, sem nem deixar log,
  porque o redirecionamento fazia parte da linha que nunca rodava. Não
  existe mais `cmd.exe` no projeto: o instalador escreve um `.ps1` com os
  caminhos já embutidos e executa esse arquivo.

- **O modelo do Ollama nunca era baixado.** `ollama list` e `ollama pull`
  são ambos clientes de um servidor em 127.0.0.1:11434, e ter o binário
  em disco não é ter o servidor no ar — depois de uma instalação recente
  pelo winget, em geral não está. Isso produzia duas respostas erradas
  numa corrida só: o script concluía que o modelo faltava, e em seguida o
  download era recusado com "a máquina de destino recusou ativamente a
  conexão". O instalador agora sobe o `ollama serve` antes de perguntar
  qualquer coisa e espera até quarenta segundos pela porta.

- **Remover um pacote de escopo de usuário exige um winget sem
  elevação.** O desinstalador removia o Tesseract, que instala para a
  máquina toda, e deixava Ollama e Python, que instalam no perfil do
  próprio usuário. A remoção agora é tentada primeiro como usuário e
  elevada depois, só para o que ainda estiver instalado.

- **`--silent` interrompia a remoção em vez de silenciá-la.** Ele pede ao
  winget que rode o comando de desinstalação silenciosa do próprio
  pacote, e um pacote cujo manifesto não tem um recusa o pedido inteiro —
  três execuções reportaram "Ollama: ainda instalado" enquanto o mesmo
  comando sem a opção o removeu na primeira tentativa. As duas variantes
  são tentadas agora, e o veredito vem de perguntar à máquina, não do
  código de saída do winget, que reportou sucesso para uma desinstalação
  que não mudou nada.

- **O atalho do sensor de CPU nunca era criado.** O bloco inteiro dele em
  `install.ps1` fica atrás de `if (-not $NoShortcut)`, e `-NoShortcut` é
  o que o instalador sempre passa, para que desinstalar remova os atalhos.
  Marcar a caixa passava `-CpuSensorShortcut` para um script que já tinha
  decidido não criar nenhum, enquanto o aplicativo mandava o usuário abrir
  o atalho que não estava lá. Agora a seção `[Icons]` é a dona disso.

- **O atalho do sensor de CPU não fazia nada com o sistema já aberto** —
  que é exatamente quando alguém clica nele. Cada clique iniciava um
  segundo servidor, que pedia o auxiliar elevado, perdia a porta 8000
  para o servidor já em execução e morria; o tempo de vida do auxiliar
  está atrelado ao processo que o pediu, então ele morria junto, e o
  servidor que desenha as telas nunca ficava sabendo. O auxiliar agora é
  anexado ao servidor que já está rodando.

- **Um modelo baixado era reportado como ausente.** A lista de modelos vem
  do servidor do Ollama, e um servidor parado devolve uma lista vazia que
  é indistinguível de uma máquina vazia — então a tela Sobre oferecia
  rebaixar 3,2 GB que já estavam em disco. O repositório em disco passa a
  ser consultado quando o servidor não responde.

- **A tela Sobre mostrava um aviso de conexão na coluna Versão.** O
  `ollama --version` com o servidor fora do ar imprime duas linhas e as
  duas começam com "Warning:"; a primeira é sobre a conexão e a segunda
  traz a versão.

- **O `PSModulePath` do PowerShell 7 matava a instalação na etapa 3.**
  Instalar o PowerShell 7 antepõe os diretórios de módulo dele para a
  máquina toda, e o Windows PowerShell 5.1 — que roda o instalador —
  passava a carregar o `Microsoft.PowerShell.Utility` errado e perdia o
  `Get-FileHash`. Reproduzido no script anterior à fase 19: um defeito
  latente, não uma regressão.

- **O desinstalador apagava a lista de projetos.** `projects.json` é a
  lista de acervos que o usuário abriu; perdê-la não apaga documento
  nenhum, mas obriga a reencontrar cada acervo à mão. Agora ela é dado do
  usuário, que só `-RemoveUserData` remove — nem mesmo a opção "remover
  também as dependências" a toca.

- **O `review.md` não contava arquivos duplicados.** O laço de cobertura
  pulava o estado `duplicate`, então um acervo com documentos repetidos
  reportava menos arquivos do que tinha.

### Alterado

- **Logotipo novo, com transparência de verdade.** O anterior era um
  JPEG, formato sem canal alfa — a transparência não estava sendo perdida
  na conversão, ela nunca poderia existir. O ícone leva dez tamanhos, de
  16 a 256, cada um reamostrado aqui e não pelo shell do Windows na hora
  de exibir.

## [1.2.0] — 2026-09-13

Fase 18. Os relatórios avisam quando ficaram para trás.

### Adicionado

- **Um aviso quando os quatro arquivos gerados não descrevem mais o
  projeto.** Isto saiu de um acervo real: três documentos foram
  acrescentados, o pipeline varreu, converteu, extraiu 426 páginas,
  montou 71 janelas e classificou todas elas — e `index.md`,
  `timeline.md`, `review.md` e `project_instructions.md` seguiram
  reportando os 13 arquivos e 307 janelas anteriores, porque gerá-los é
  uma etapa separada, atrás do próprio botão, que não tinha sido
  executada. A tela de Resultado mostrava esses arquivos sem nada que
  dissesse que estavam desatualizados. O dono descobriu lendo os números
  à mão.

  O `generate_all_artifacts` agora registra, numa tabela de uma linha,
  as três contagens que os arquivos descrevem: documentos, janelas
  classificadas e peças. Quando elas deixam de bater com o banco, duas
  telas avisam, cada uma com o botão de regerar ao lado — a tela de
  Resultado sempre que diferirem, nomeando o que mudou desde que os
  arquivos foram escritos; a tela de Execução só quando não houver mais
  nada a processar.

  As duas telas usam condições diferentes de propósito. Com janelas ainda
  esperando pelo modelo, mandar alguém gerar os relatórios produziria
  relatórios incompletos no instante em que fossem escritos, então a tela
  de Execução fica quieta e o conselho honesto — siga rodando as etapas —
  é o que a tela já mostra. Na tela de Resultado, os arquivos em exibição
  genuinamente antecedem o projeto, aconteça o que acontecer, então o
  aviso é incondicional.

  Contagens, não datas de arquivo: a pasta de saída é sincronizada pelo
  Google Drive, e o cliente reescreve a data de modificação de arquivos
  cujos bytes nunca mudaram. Comparar datas aqui repetiria o erro que a
  própria detecção de atualização existe para evitar.

  Um projeto de qualquer versão anterior não carrega estado registrado e
  nunca é reportado como defasado — não há com o que comparar, e um aviso
  sem chão embaixo é pior que nenhum. A primeira geração nesta versão
  registra o estado; todas as seguintes são conferidas.

### Corrigido

- **O `review.md` contava cinco dos seis estados de arquivo.** A lista de
  cobertura percorria `discovered`, `converted`, `extracted`, `failed` e
  `skipped`, mas não `duplicate` — então um arquivo que entrou como cópia
  de outro já indexado sumia do relatório, e a cobertura simplesmente não
  fechava com o acervo, sem nada que explicasse a diferença. Um teste
  agora percorre todos os estados que `scanning.py` escreve, para que a
  mesma lacuna não possa reabrir por um estado acrescentado depois.

## [1.1.0] — 2026-09-13

Fase 17. Um acervo deixa de precisar ser reindexado do zero a cada
mudança.

### Adicionado

- **Atualização incremental.** Aponte o aplicativo para um projeto cuja
  pasta de origem mudou e ele agora detecta o que é novo, o que foi
  editado e o que foi removido, invalida só o que a mudança de fato
  afeta, e reprocessa isso. Acrescentar um documento a um acervo de 500
  páginas reclassifica **uma janela em vez de trinta e seis** — cerca de
  um minuto contra dezoito e meio.

  A razão de poder ser tão barato é o formato da invalidação. Documentos
  são agrupados, as páginas de um grupo são concatenadas, e a
  concatenação é fatiada em janelas sobrepostas de tamanho fixo. Uma
  mudança não invalida um arquivo; ela invalida o grupo *a partir da
  primeira página que se deslocou*, porque fora do modo biblioteca a
  referência de uma página (`f. N`) é contada correndo por todo o grupo,
  de modo que um arquivo que ganha ou perde páginas desloca a numeração
  de todos os arquivos depois dele. Tudo antes desse ponto mantém suas
  páginas, suas referências e sua classificação.

  Arquivos posteriores à divergência que não mudaram são devolvidos ao
  estado `converted`, não `discovered`: a extração os relê do artefato já
  convertido e **eles não pagam OCR de novo**.

- **Uma tela de confirmação, e um aviso na tela de Execução.** Abrir um
  projeto cuja pasta mudou mostra quantos documentos são novos, editados
  e removidos. A confirmação nomeia os arquivos que serão reprocessados e
  declara o custo: quantos passam por OCR de novo, quantas janelas são
  reclassificadas, quantas mantêm a classificação. Dois desses números
  são exatos; as janelas que um documento *novo* vai acrescentar dependem
  da contagem de páginas dele, que nada sabe antes da extração, então a
  tela diz isso em vez de estimar.

  O aviso é buscado depois que a página é renderizada, e não antes. Num
  acervo grande sincronizado pelo Drive, percorrer a pasta leva segundos,
  e pagá-los antes do primeiro pixel trocaria um problema por outro.

- **Documentos removidos são reportados.** Um documento tirado da pasta
  de origem deixa o `index.md` e o `timeline.md`, que descrevem o acervo
  como ele é hoje, e aparece no `review.md` — que já é o relatório de
  lacunas e falhas — com o momento em que saiu. Uma tabela nova,
  `removed_file`, guarda isso como estado e não como entrada de log, que
  sumiria se o log fosse limpo.

### Alterado

- **A detecção lê tamanho e data de modificação antes de ler bytes.** O
  diagnóstico roda toda vez que a tela de Execução abre, e calcular o
  hash de um acervo inteiro sincronizado pelo Drive a cada vez forçaria o
  cliente a baixar arquivos que ninguém pediu. O hash ainda tem a última
  palavra, porque o Drive reescreve datas de modificação de arquivos cujo
  conteúdo nunca mudou — sem esse desempate, o aplicativo reportaria
  "mudou" o tempo todo, que é o pior defeito que um aviso pode ter. Uma
  coluna nova, `file.mtime`, guarda o valor de comparação.

- **As páginas de um grupo são ordenadas de forma determinística**, por
  caminho natural e número de página, em vez de por ordem de inserção. Os
  dois coincidiam num projeto construído numa passada só; depois de uma
  atualização não coincidiriam, e um documento corrigido teria pulado
  para o fim do grupo.

### Corrigido

Quatro caminhos para um índice errado sem erro e sem aviso, três deles
alcançáveis em uso comum e todos achados antes do lançamento:

- **A geometria das páginas era derivada de duas fontes diferentes.** Um
  módulo somava `file.page_count`, outro contava linhas na tabela `page`.
  Um arquivo que converte com sucesso e depois falha na extração mantém
  uma contagem diferente de zero sem páginas — um PDF ilegível num acervo
  — e os dois discordavam, deixando uma janela classificada sobre páginas
  que tinham se deslocado debaixo dela.

- **Peças classificadas sobreviviam às suas janelas.** A invalidação
  apagava as linhas de janela, os arquivos de texto delas e suas páginas,
  mas nunca podava o `raw_items.jsonl`, ao qual o motor de classificação
  acrescenta e que a etapa de importação relê inteiro. Peças de janelas
  descartadas sobreviviam com referências velhas, passavam pela validação
  porque a faixa ainda cabia no grupo, e eram fundidas a peças vivas —
  então um `index.md` atualizado podia atribuir páginas a um documento
  que não estava mais no acervo.

- **Um documento renomeado era tratado como duplicata de si mesmo.** O
  conteúdo dele batia com a linha que a atualização estava prestes a
  apagar, então ele era retirado do plano; a varredura seguinte via um
  arquivo novo em folha e inseria páginas que o plano nunca tinha
  previsto.

- **O estado que uma atualização bem-sucedida deixa para trás era lido
  como layout corrompido**, porque a verificação comparava contagens de
  janela em vez de chaves de janela. A tela então convidava a uma segunda
  atualização que teria descartado tudo o que a primeira preservou.

Mais três defeitos, um deles uma regressão que esta fase teria
introduzido:

- **Limpar os arquivos intermediários não quebra mais a próxima
  atualização.** O botão "liberar espaço em disco" da tela de Resultado
  apaga a pasta `converted/`, e o caminho de renumeração presumia que ela
  ainda estava lá: todo documento inalterado depois da divergência teria
  sido marcado `failed` e desaparecido do índice permanentemente,
  irrecuperável, porque a conversão só pega arquivos `discovered` e uma
  nova varredura os pula. A atualização agora verifica se o artefato
  existe e paga o OCR de novo quando não existe.

- **Um arquivo não suportado não invalida mais um acervo inteiro.**
  Largar um `readme.txt` num projeto só de PDFs, ou uma cópia duplicada
  de um documento já indexado, fazia o plano invalidar o grupo inteiro
  por um arquivo que o pipeline nunca indexaria.

- **Uma janela recriada escreve o texto novo dela.** O nome do arquivo de
  texto deriva das posições da janela, então um documento corrigido sem
  mudança na contagem de páginas produzia o mesmo nome, e o texto antigo
  sobrevivia ao lado da classificação nova.

### Migração

Nada a fazer. Um projeto criado pela 1.0.1 abre na 1.1.0 sem nenhum passo
manual: `removed_file` é criada por `CREATE TABLE IF NOT EXISTS` e
`file.mtime` por um `ALTER TABLE` protegido por `PRAGMA table_info`, os
dois reexecutados toda vez que um projeto é aberto. A coluna começa
vazia, então a primeira atualização de um projeto existente calcula o
hash do acervo uma vez para preenchê-la; da segunda em diante vale o
caminho rápido.

### Testes

537 passando, contra 456. A fase acrescenta 81, dos quais o que mais
importa é um teste de equivalência: uma atualização incremental tem de
produzir artefatos indistinguíveis de uma reindexação completa sobre a
mesma pasta final. Todos os outros testes da fase existem para explicar
*por que* aquele falhou, quando falha. Foi ele que pegou o defeito do
`raw_items.jsonl` acima.

## [1.0.1] — 2026-09-03

O lançamento que sai com o primeiro anúncio público do projeto.

### Alterado

- **O modelo local padrão agora é `qwen3.5:4b`, no lugar de
  `gemma4:e4b`.** É a medição do próprio projeto finalmente chegando ao
  padrão: sobre as mesmas janelas de um documento de 31 páginas, com todo
  modelo inteiramente residente numa placa de 8 GB, o `qwen3.5:4b`
  preencheu o campo de tipo em 100% das peças a 30,8 s/janela, contra
  79,5% a 38,5 s/janela do `gemma4:e4b` — melhor e mais rápido ao mesmo
  tempo, o que não é o formato usual dessa troca. O README recomendava
  esse modelo desde a fase 15; o `DEFAULT_LOCAL_MODEL` não tinha
  acompanhado. O `gemma4:e4b` continua selecionável no formulário de novo
  projeto para quem quiser comparar, mas não é mais o que o instalador
  baixa.

  O efeito prático é no primeiro uso, não na qualidade: o `gemma4:e4b`
  puxa ~9,6 GB do Ollama embora só ~3,1 GB fiquem residentes, então uma
  primeira execução agora baixa cerca de um terço do que baixava, e cabe
  numa placa de 6 GB tão confortavelmente quanto numa de 8 GB. O
  `install.ps1` lê `DEFAULT_LOCAL_MODEL` do Python em vez de fixar um
  nome, então acompanhou a mudança sozinho.

### Corrigido

- **A verificação de hardware dizia a toda máquina que ela precisava de
  ~9,6 GB de que não precisava.** `ESTIMATED_MODEL_SIZE_MB` estava
  calibrado para o `gemma4:e4b` e é o número ao qual `choose_model`
  recorre antes que o Ollama possa reportar um tamanho real — ou seja,
  exatamente na primeira execução, quando nada foi baixado ainda. Deixado
  em 9_600 ao lado de um padrão de 3,2 GB, teria empurrado máquinas no
  limite para o motor `rules` por uma memória que elas nunca precisaram
  ter. Agora 3_232, o tamanho que o Ollama desta máquina reporta para o
  `qwen3.5:4b`.

### Documentação

- **Um GIF demonstrativo (`demo.gif`) no topo dos três READMEs**,
  percorrendo as quatro telas em ordem — projetos, novo projeto,
  execução, resultado.
- **O requisito do Python 3.12 não se lê mais como um passo manual.** O
  instalador baixa e instala o Python 3.12.10 para o usuário atual desde
  a tarefa 4 da fase 15, e a seção "Instalando" dizia isso, mas o item de
  "Requisitos" acima dela ainda mandava o leitor ir selecionar o 3.12
  sozinho — a primeira coisa que um recém-chegado lê, descrevendo uma
  barreira que não existe mais.
- **Os links de idioma agora encabeçam cada README**, com os outros dois
  idiomas nomeados na própria língua deles, em vez de dobrados numa linha
  de letra miúda.
- A captura `new.png` foi refeita: ela mostrava `gemma4:e4b` selecionado
  no seletor de modelos, que não é mais o que uma instalação nova mostra.

## Fase 16: Relatório da Segunda Máquina — lançada na 1.0.1

Tudo nesta fase vem de uma fonte só: o mantenedor instalou o sistema num
segundo computador e anotou as oito coisas que estavam erradas nele. Cada
entrada abaixo nomeia o defeito como ele foi vivido, não como foi
implementado.

### Corrigido

- **Janelas de console piscavam por cima da área de trabalho durante todo
  o OCR e a conversão do Ghostscript.** O `subprocess_utils.run_hidden` já
  escondia todo comando que este código roda; ele não podia esconder os
  que as bibliotecas rodam. O `pytesseract` inicia o `tesseract.exe` pelo
  próprio `Popen`, e o `ocrmypdf` inicia Tesseract, Ghostscript,
  `pngquant` e `jbig2` de dentro do pipeline dele — nenhum com
  `CREATE_NO_WINDOW`, e nenhum sob nosso controle. O servidor não ter
  janela é exatamente o que tornava cada um deles visível: um processo sem
  console que inicia um filho de console faz o Windows alocar um console
  novo **e mostrá-lo**. A supressão agora é propriedade do processo, e não
  de pontos de chamada individuais (`no_window.install()` embrulha o
  `subprocess.Popen.__init__`), aplicada no servidor, em cada worker do
  pool de conversão (`initializer`), no novo `_ocr_runner` que faz frente
  à linha de comando do ocrmypdf e — por um `sitecustomize.py` no
  `PYTHONPATH` do subprocesso de OCR — nos workers do pool `--jobs` do
  próprio ocrmypdf, que são os pais diretos do Tesseract.
- **Os sensores de CPU continuavam vazios mesmo usando o atalho
  elevado.** A pasta do projeto é uma unidade virtual do Google Drive,
  montada sob o token de sessão do usuário conectado. Um processo elevado
  roda sob a metade administrador do mesmo token dividido, e o Windows não
  carrega mapeamentos de unidade através dessa fronteira — `H:\...` não
  existe para o filho elevado, então `python -m
  gclaude_indexer.sensor_service` falhava com "No module named" antes de
  executar uma linha nossa, em silêncio, porque o auxiliar roda sob
  `pythonw.exe` com `SW_HIDE`. Os quatro módulos de que o auxiliar precisa
  agora são espelhados em `%LOCALAPPDATA%` e ele roda de lá. A pasta local
  do próprio servidor também é passada na linha de comando, para que
  elevar com uma conta de administrador *diferente* não possa publicar a
  leitura num perfil que o servidor nunca lê. Um estado novo,
  `helper_sem_resposta`, distingue "o auxiliar iniciou e não respondeu" de
  "você nunca o pediu" — os dois pareciam idênticos na tela, então o
  conselho exibido era fazer o que o usuário já tinha feito.
- **A VRAM da GPU nunca era preenchida antes de o trabalho transbordar
  para a RAM.** `options.num_gpu = -1` se lê como "use o máximo de GPU
  possível" e não faz isso: entrega a decisão ao escalonador do Ollama,
  que dimensiona o cache KV para `OLLAMA_NUM_PARALLEL` requisições
  simultâneas (quatro, por padrão, onde este classificador envia uma),
  mantém a própria margem por cima, e arredonda para baixo. Duas mudanças
  independentes: as configurações que decidem o que cabe agora são
  escritas como variáveis de ambiente do usuário pelo instalador e
  passadas a qualquer servidor Ollama que este programa inicie por conta
  própria (um modelo carregado, uma vaga paralela, flash attention, um
  cache KV quantizado); e o `gpu_budget.py` mede a VRAM livre, lê a forma
  real do modelo e pede um número **específico** de camadas em vez de
  "quantas couberem". O `num_ctx` também passa a ser enviado
  explicitamente — o padrão de 4096 tokens do Ollama é menor que uma
  janela cheia nos padrões deste projeto, e um prompt mais longo estava
  sendo truncado em silêncio.
- **Era preciso reiniciar antes de o sistema funcionar numa máquina
  nova.** A instalação estava completa; a mudança no `PATH` não tinha
  chegado aos processos que já estavam rodando. O `install.ps1` a escreve
  no registro e transmite `WM_SETTINGCHANGE`, que o Explorer frequentemente
  ignora, então todo processo que o Explorer inicia — o atalho, o
  `Indexer.vbs`, o `Indexer.bat`, o servidor, tudo o que o servidor gera —
  mantinha o ambiente de antes da instalação, e só sair da sessão (o que
  reinicia o Explorer) resolvia. Duas correções independentes, qualquer
  uma delas suficiente: o instalador registra o caminho absoluto de tudo
  o que instalou num `tools.json` no momento em que instala, e o
  `tools.py` consulta isso antes do `PATH`; e o `Indexer.bat` reconstrói o
  `PATH` a partir do registro antes de iniciar qualquer coisa.
- **O log ao vivo não podia ser rolado, lido, selecionado nem copiado.**
  Três causas distintas, todas reais. `.log` e `.log-box` tinham
  `overflow-y: auto`, então a lista interna é que rolava de fato enquanto
  o script movia a caixa externa. As linhas eram renderizadas da mais nova
  para a mais antiga, enquanto o comportamento de "seguir" rolava para o
  *fim*, então acompanhar uma execução arrastava o leitor para a linha
  visível mais antiga a cada dois segundos. E o HTMX substituía todo o
  conteúdo do painel a cada consulta, o que apagava qualquer texto que o
  usuário tivesse selecionado. O log agora é cronológico, a caixa externa
  é o único contêiner que rola (e pode ser arrastada para ficar mais
  alta), e linhas novas são **acrescentadas** por `/run/log?since=<id>` em
  vez de o painel ser reconstruído. A atualização pausa enquanto houver
  uma seleção ativa, e há botões de "ir para o fim" e "copiar".
- **O tempo estimado para terminar cada etapa estava errado.** Ele dividia
  itens concluídos por segundos decorridos. Isso contava a coisa errada
  (um PDF digitalizado de 900 páginas e uma nota de 3 KB são ambos "um
  arquivo"), fazia a média sobre a janela errada (incluindo custos de
  partida que ocorrem uma vez só, e sem conseguir reagir quando o ritmo
  real mudava), e saltava a cada consulta. O `web/eta.py` agora pondera o
  progresso por bytes nas etapas que processam arquivos, faz a média da
  taxa exponencialmente para que o ritmo recente domine, suaviza o que
  chega à tela, e descarta a estimativa por completo — em vez de fazer
  contagem regressiva rumo a um instante que não vai chegar — quando uma
  etapa empaca.
- **Projetos salvos num computador não apareciam em outro.** Os projetos
  em si sincronizam pelo Drive; a *lista* deles vivia em
  `%LOCALAPPDATA%`, então um segundo computador abria numa tela de
  Projetos vazia com todos os projetos ali mesmo no disco. O catálogo
  agora pode viver numa pasta do Drive escolhida na tela de Projetos. Os
  caminhos são guardados relativos a essa pasta além de absolutos, e o
  relativo vence na leitura, porque a letra da unidade difere entre
  máquinas (`H:` aqui, `G:` lá — seção 11.5). Definir a pasta também copia
  para ela os projetos existentes da máquina. Projetos que vivem no disco
  local de outro computador são listados e marcados como fora de alcance,
  em vez de escondidos.

- **Apontar "Novo projeto" para uma pasta que já continha um destruía a
  configuração daquele projeto, em silêncio.** Esse era o único gesto
  disponível para reabrir, e ele era aceito sem uma palavra: o
  `create_project` INSERIA uma *segunda* linha na tabela `project` do
  próprio projeto, e o `load_project` lia `ORDER BY id DESC` — a mais nova
  — então os valores do formulário viravam os do projeto. Todo arquivo
  varrido, página e peça sobrevivia, que é o que tornava isso invisível:
  parecia ter funcionado. O assunto salvo tinha sumido e as configurações
  estruturais iam junto, então um projeto cujas janelas tinham sido
  montadas com 8 páginas cada seguia com 16. Medido, não inferido. O
  formulário agora detecta o projeto existente, para com um 409 e oferece
  abri-lo; e o `load_project` lê a *primeira* linha, restaurando a
  configuração original em todo banco onde isso já aconteceu. As linhas
  extras deliberadamente não são apagadas — elas são o único registro
  remanescente da segunda tentativa, e um reparo que destrói evidência
  para arrumar a casa não é um reparo — e um aviso é registrado uma vez
  por banco dizendo qual configuração está em vigor.

- **O `uninstall.ps1` não rodava de jeito nenhum a partir de um prompt do
  PowerShell.** Não era defeito do script: o Google Drive marca todo
  arquivo que sincroniza com `Zone.Identifier`/`ZoneId=3` — "veio da
  internet" — e a política de execução padrão do Windows, RemoteSigned,
  recusa rodar um `.ps1` dessa zona sem assinatura digital. A mensagem ("o
  arquivo não está assinado digitalmente") se lê como se o script
  estivesse quebrado. Isso valia igualmente para o `install.ps1`, e só
  nunca apareceu porque esse é sempre iniciado pelo `Indexer.bat`, que
  passa `-ExecutionPolicy Bypass`; o desinstalador era o único script sem
  lançador próprio. Foi acrescentado o `Desinstalar.bat` — o atalho da
  área de trabalho agora aponta para ele, e ele repassa
  `-WhatIfOnly`/`-KeepDependencies`/`-RemoveAll` — e o `install.ps1` agora
  roda `Unblock-File` sobre os scripts desta pasta, para que o comando
  direto também funcione. A política de execução em si fica intocada: é
  uma configuração de segurança da máquina toda, e não cabe a um
  instalador mudá-la.
- **Um servidor pode rodar código mais velho que os arquivos em disco, e
  nada dizia isso.** O Python carrega um módulo na memória uma vez, na
  partida; editar o arquivo depois não muda nada para um processo já em
  execução. Observado aqui do pior jeito: um servidor iniciado às 02:09
  ainda rodava às 08:03 com código corrigido às 05:40, passando essas
  horas produzindo um índice com um defeito que já tinha sido corrigido. A
  única pista era uma linha de log que o usuário por acaso leu e achou
  estranha. Toda tela agora exibe um aviso quando o código em disco
  difere do que o processo carregou.

  Comparado por **hash de conteúdo, não por data de modificação**: a pasta
  do projeto é sincronizada pelo Google Drive, e um cliente de
  sincronização reescreve datas de arquivos cujos bytes nunca mudaram. Uma
  comparação por data gritaria lobo com frequência suficiente para ser
  ignorada, que é a pior coisa que um aviso pode ser. Calcular o hash de
  todo `.py` do pacote custa alguns milissegundos e nunca reporta uma
  mudança que não seja real.

- **O desinstalador não ganha mais atalho na área de trabalho** (decisão
  explícita do usuário). A área de trabalho é para o que você abre todo
  dia, e um desinstalador é o oposto disso — um botão que ninguém pretende
  apertar, ao lado do que aperta diariamente, usando o mesmo ícone. Ele
  fica a dois cliques de distância no `Desinstalar.bat`, na pasta do
  projeto ao lado do `Indexer.bat`. O `uninstall.ps1` ainda remove o
  atalho de máquinas que já tenham um.

- **Uma recomendação de modelo medida, e as configurações que a
  acompanham.** Cinco modelos avaliados sobre janelas idênticas de um
  documento de 31 páginas, todos rodando inteiramente numa placa de 8 GB:
  o `qwen3.5:4b` (3,0 GB) chega a 100% das peças com tipo e data em 30,8 s
  por janela, contra 116,9 s do `granite4.2:8b` na mesma qualidade, e cabe
  numa placa de 6 GB com o mesmo conforto — uma configuração para toda
  máquina. O modelo maior da mesma família perdeu para o menor
  (`qwen3.5:9b`: 79,5% em 86,2 s), o que decorre do que a tarefa agora é:
  descrever uma página é leitura e disciplina de formato, não raciocínio
  profundo. O `pages_per_window` de 8 fica documentado como o valor a
  usar, e o `pages_per_block` fica documentado pelo que é — uma
  configuração que produz arquivos auxiliares e que **não** afeta o índice
  em nada.

- **Nada no acervo pode faltar do índice — e faltava.** O propósito deste
  sistema, declarado pelo dono: o índice é lido para achar *em que PDF, em
  que página* está uma resposta, sem carregar os PDFs em si para dentro de
  um projeto do Claude. Uma página ausente do índice é informação que
  ninguém consegue encontrar de novo. Avaliado sobre um laudo laboratorial
  de 31 páginas, cinco modelos de três famílias — `gemma4:e4b`,
  `qwen3:8b`, `qwen3.5:9b`, `qwen3.5:4b`, `granite4.2:8b` — cobriram entre
  0% e 9,7% das páginas, todos eles reportando confiança "high".
  Acrescentar uma regra explícita de "cubra todas as páginas" ao prompt
  levou dois modelos a 22,6% — *o mesmo número para os dois*, que foi o
  que fechou o diagnóstico: quando modelos independentes falham de forma
  idêntica, quem está errada é a tarefa, não o modelo.

  A tarefa estava pedindo aritmética. "Devolva as peças, cada uma de
  ref_start a ref_end" faz o modelo enumerar faixas que precisam somar
  exatamente a janela, sem buraco e sem sobreposição. Um modelo pequeno lê
  uma página bem e fecha essa contabilidade mal.

  Então a pergunta foi invertida: **uma linha por página**. O modelo diz o
  que há em cada página e nada mais; o agrupamento em peças virou trabalho
  do código, que sabe contar. A cobertura agora é uma propriedade, não uma
  esperança — o `_group_pages_into_items` percorre as páginas da janela,
  não a resposta do modelo, então uma página que ele nunca mencionou ainda
  assim chega ao índice com o próprio texto.

  Mais dois defeitos foram achados e corrigidos durante essa medição:

  * Pedir ao modelo que devolvesse a referência citável da página
    ("copiada exatamente como aparece") fez o `qwen3.5:4b` copiar o texto
    INTEIRO da página para dentro do campo `ref`; o JSON passou do limite
    antes de fechar e o parser recebeu zero linhas. As páginas agora são
    numeradas de 1 a N e o modelo devolve o número — um inteiro não pode
    ser confundido com o conteúdo, e o código já sabe qual referência
    corresponde a cada posição.
  * O modelo marcou `continues: true` em oito exames laboratoriais
    consecutivos que ele mesmo tinha nomeado corretamente (Hemograma,
    Ferritina, Metabolismo do Ferro, Vitamina B-12, Protrombina, Ureia,
    Creatinina) — ele leu "continua o mesmo *laudo*" onde o prompt queria
    dizer "o mesmo *assunto*". O agrupamento agora é decidido em código,
    comparando assuntos; o `continues` só desempata quando a redação de um
    assunto muda sem que o documento mude ("Hemograma — série vermelha" /
    "— série branca").

- **A cobertura agora tem o maior peso na nota de qualidade (40 de 100).**
  Ela não era medida de jeito nenhum, e essa era a lacuna que o benchmark
  expôs: o resultado de 9,7% de cobertura acima tirava nota perto de 100,
  porque o punhado de peças que existia tinha confiança perfeita e
  preenchimento de campos perfeito. A cobertura é a única falha sem
  remédio depois: um tipo vazio pode ser reclassificado, uma página
  ausente do índice simplesmente nunca é encontrada. A confiança caiu para
  35 e o preenchimento de campos para 25 para abrir espaço.

- **Um limite de tamanho para o resumo (600 caracteres por peça).** O
  índice inteiro tem de caber no contexto de um projeto do Claude; é a
  soma desses resumos que o preenche. Sem um limite, o índice cresceria
  até virar uma segunda cópia do acervo, que é precisamente o que ele
  existe para evitar.

- **Os campos do próprio formulário de projeto nunca chegavam ao modelo.**
  `subject`, `collection_type`, `role_instructions` e `extra_rules` eram
  coletados, validados e guardados, e depois usados só para escrever o
  `instrucoes-do-projeto.md` — um artefato produzido *depois* da
  classificação. Nenhum motor os mostrava ao modelo. O custo foi medido
  num acervo real: material de curso de pós-graduação classificado por um
  prompt cujos únicos exemplos trabalhados eram "OFÍCIO, MEMORANDO,
  PARECER" voltou com 1432 de 1445 peças sem tipo nenhum. O modelo não
  estava falhando; estava respondendo a pergunta que lhe foi feita. O
  motor `local` agora monta um bloco de contexto a partir desses campos,
  enquadrado como *o que este acervo é*, e não como a tarefa — o
  `extra_rules` daquele acervo dizia "deve-se observar toda a legislação
  vigente", uma instrução para o uso posterior do índice em pesquisa, e
  não algo que um classificador deva tentar executar.
- **O prompt pedia documentos e aceitava páginas.** A mesma corrida
  produziu 1445 peças para 1844 páginas — 1,28 página por peça, fatiando
  de duas em duas páginas direto através de documentos que corriam por
  dezenas. O prompt agora declara a regra explicitamente, junto com a
  falha que ela pretende evitar.
- **`ÍNDICE` e `Índice` eram dois tipos de documento diferentes.** Os
  tipos são normalizados (maiúsculas, espaços colapsados) na entrada, e as
  palavras que um modelo devolve em vez de deixar o campo vazio (`null`,
  `N/A`, `desconhecido`) são tratadas como vazio, em vez de guardadas como
  tipos próprios.
- **Um `desktop.ini` era a peça número um de um índice de material de
  curso**, resumido como "arquivo de configuração do sistema
  operacional". Arquivos que o sistema operacional e os clientes de
  sincronização deixam para trás passam a ser pulados, por uma lista
  explícita e não por uma regra como "arquivos ocultos" — um acervo pode
  legitimamente conter um documento cujo nome começa com ponto.
- **A nota de qualidade punia o motor por estar certo.** A taxa de
  preenchimento cobrava por um `date` vazio em toda peça, e notas de aula
  não são documentos datados: 15 dos 30 pontos de preenchimento se perdiam
  pela resposta correta, e 100 era inalcançável por melhor que a
  classificação ficasse. O `date` agora só conta para acervos que de fato
  têm datas (limiar de 5%, para que uma data inventada não possa jogar um
  acervo inteiro para dentro de uma avaliação sobre um campo que ele não
  tem). O `type` conta sempre. O resumo também passa a devolver a nota
  quebrada em confiança, preenchimento e penalidade — descobrir que um
  campo vazio respondia por 30 dos 40 pontos que faltavam tinha exigido
  consultar o banco à mão.
- **O planejador de VRAM piorava as coisas quando o modelo não cabia.**
  Medido na mesma máquina: com 4712 MB disponíveis ele pedia 18 de 43
  camadas, e o Ollama passava de colocar 3108 MB do modelo na placa para
  colocar 1849 MB — a estimativa substituía a divisão do escalonador por
  uma pior e deixava a corrida mais lenta. O custo por camada aqui é o
  tamanho do arquivo dividido pelo número de camadas, um número grosseiro,
  enquanto o Ollama sabe o tamanho real de cada tensor. A regra agora é
  assimétrica: o plano só passa por cima do `-1` quando pode afirmar com
  certeza que *tudo* cabe, e uma divisão fica a cargo do escalonador. À
  parte disso, a VRAM já ocupada pelo modelo que está sendo dimensionado
  agora conta como disponível para ele — sem isso, cada corrida
  orçava a partir de um número que excluía justamente o modelo que estava
  carregando, pedia menos camadas, e se empurrava para fora da GPU a cada
  vez.

### Adicionado

- Um aviso quando o modelo escolhido não cabe na placa de jeito nenhum —
  o caso em que nenhuma configuração ajuda e a resposta é um modelo menor.
  Encontrado no acervo que motivou este trabalho: uma RX 5700 XT de 8 GB
  rodando um modelo de 9,1 GB com 17% dele na GPU.


- **"Abrir projeto existente"** — não havia como reabrir um projeto cuja
  pasta o catálogo desta máquina não listasse, que é todo caso que o
  catálogo compartilhado não cobre: uma reinstalação, uma formatação, uma
  conta diferente, uma pasta que mudou de lugar, uma pasta recebida de
  outra pessoa. A pasta de saída já *é* o projeto — o `project.db` dela
  guarda a configuração, todo arquivo varrido, toda página e toda peça
  classificada — então a tela nova lê essa pasta (com o banco aberto em
  `mode=ro`, para que inspecionar uma pasta nunca possa ser o que cria
  algo dentro dela), mostra o que encontrou, e a adota sem alterações.

- **`uninstall.ps1`** — o sistema não tinha desinstalador nenhum. Ele
  pergunta sobre cada item separadamente e traça uma distinção o tempo
  todo: o que esta instalação *possui* (o ambiente virtual, os atalhos, as
  DLLs de sensor, o Ghostscript descompactado, as configurações locais, as
  entradas de `PATH` e as variáveis de ambiente que ela acrescentou) é
  removido quando pedido; o que ela meramente *instalou* (Tesseract,
  Ghostscript, Ollama, Python, o repositório de modelos baixados) é um
  programa compartilhado do qual outro software pode depender, e é
  oferecido um a um, com isso dito claramente. `-RemoveAll`,
  `-KeepDependencies` e `-WhatIfOnly` cobrem os casos não interativos. Ele
  nunca apaga a pasta de saída de um projeto, sob nenhuma opção — ele as
  lista, com tamanhos, e deixa a decisão para o usuário. O `install.ps1`
  cria um atalho na área de trabalho para ele.
- Uma seção "Catálogo compartilhado" na tela de Projetos, com o seletor
  de pastas nativo, para apontar a lista de projetos a uma pasta do Drive.
- Um evento de log reportando como a GPU está sendo usada numa corrida de
  classificação (`N de M camadas na GPU, X MB de VRAM livre medidos`) — o
  número por trás do medidor de VRAM, que o Ollama não reporta e a tela
  não conseguia explicar.
- 49 testes cobrindo os oito itens, o caminho de reabertura e o lançador
  (`tests/test_phase16.py`), incluindo uma regressão para um defeito
  achado ao validar este trabalho contra um Ollama real: um modelo
  multimodal publica `gemma4.audio.block_count = 12` ao lado de
  `gemma4.block_count = 42`, e o de áudio vem primeiro — casar por sufixo
  apenas lia a contagem de camadas da torre de áudio e deixava todo número
  por camada errado em mais de três vezes.

## [Não lançado] — Fase 15: Instalador Ciente do Hardware e Elevação Opcional

Objetivo desta fase: fazer o instalador analisar a máquina e instalar o
que aquela máquina de fato precisa, e dar ao sensor de CPU uma forma de
rodar com o privilégio de que ele precisa — sem exigi-lo.

A fase começou com o mantenedor limpando a máquina (Python 3.12, o
ambiente virtual, Tesseract, Ghostscript, Ollama, a variável de ambiente
da GPU e o atalho da área de trabalho) para que o instalador pudesse ser
testado do zero pela primeira vez. Esse teste achou mais do que devia.

### Adicionado

- O instalador baixa as sete bibliotecas de sensor
  (`LibreHardwareMonitorLib` 0.9.6, `HidSharp` 2.6.4 e cinco shims da BCL
  do .NET) do nuget.org para `%LOCALAPPDATA%\GClaudeIndexer\lib`, com
  versões fixadas e **SHA-256 verificado antes de instalar**. Nada nunca
  tinha instalado essas bibliotecas: elas eram colocadas à mão, então quem
  clonasse o repositório não tinha leitura de temperatura, potência ou
  clock, nem como obtê-las.
- **O instalador instala o Python 3.12 ele mesmo**, e continua na mesma
  execução. Ele vinha detectando o interpretador ausente e imprimindo um
  comando `winget` para o usuário rodar à mão — o que não é instalar.
  Agora ele tenta o winget em escopo de *usuário* (sem administrador, e a
  PATH da máquina fica intocada, de modo que um `python` existente
  continua vencendo), depois o instalador fixado do python.org com o
  SHA-256 conferido, depois uma instalação elevada para todos os
  usuários, e só então recorre à orientação impressa. Enxergar o
  interpretador recém-instalado no mesmo processo deu trabalho próprio: o
  `PATH` e o registro do lançador `py` são lidos quando um processo
  inicia, então o instalador recarrega a PATH do registro, lê o
  `Software\Python\PythonCore\3.12\InstallPath` da PEP 514 e verifica as
  pastas de instalação conhecidas — executando cada candidato e
  perguntando a versão dele, em vez de confiar numa chave ou num nome de
  pasta. Esta máquina tinha uma chave de registro velha apontando para
  uma pasta `Python312` sem `python.exe`, que teria respondido
  "encontrado" para um interpretador que não existe.
- Dados de idioma do OCR em português. O projeto tem
  `ocr_language="por"` como padrão, mas o pacote do Tesseract traz só
  `eng` e `osd` — o `ocrmypdf` falhava com "does not have language data
  for: por". O instalador agora instala o idioma configurado (commit
  fixado, hash verificado) no `tessdata` do próprio Tesseract. O
  `-OcrLanguage` aceita outros.
- Ghostscript, que nada vinha instalando: o pacote do winget
  (`ArtifexSoftware.GhostScript`) **não existe mais**. A versão é fixada e
  o SHA-512 é conferido contra o arquivo `SHA512SUMS` que a Artifex
  publica com o lançamento. Como ele é posto no lugar mudou depois, nesta
  mesma fase — veja "Ghostscript é descompactado, não instalado" abaixo.
- Uma verificação de GPU pós-instalação: o instalador carrega um modelo e
  reporta o que o `ollama ps` diz. Quando a GPU não está sendo usada, ele
  imprime orientações para placas AMD mais antigas — só links, nunca um
  download automático de terceiros.
- Elevação opcional para o sensor de CPU: um segundo atalho,
  `GClaude Indexer (sensor de CPU)`, passando `--cpu-sensor` para os
  lançadores existentes. Só o `gclaude_indexer.sensor_service` roda
  elevado; o servidor não. O instalador oferece esse atalho perguntando,
  declarando tanto o que se ganha (temperatura e potência da CPU) quanto o
  que custa (um prompt do UAC a cada abertura). O `-AutoInstall` sozinho
  não o cria.

### Removido

- `gclaude_indexer/installer.py` e os dez testes que o cobriam. Era uma
  segunda implementação da instalação de dependências, em Python,
  alcançada só a partir do `launcher.py` — então o mesmo trabalho existia
  duas vezes, e a cópia que ninguém olhava era a que ainda rodava o
  instalador do Ghostscript com `/S` e uma espera de 900 segundos. O
  `install.ps1` agora é o caminho único: o `Indexer.bat` já o executa
  quando o ambiente está faltando. O `launcher.py` perdeu o
  `_garantir_dependencias_externas()` junto, e as chaves `log.installer.*`
  (27 delas, nos três idiomas) foram embora com o código que as usava.

  Contrapartida aceita: o aplicativo não reinstala mais em silêncio uma
  dependência que suma depois da instalação. A tela Sobre continua
  reportando a ausência, e rodar o instalador de novo resolve.

### Alterado

- **Ghostscript é descompactado, não instalado.** Ele agora vai parar em
  `%LOCALAPPDATA%\GClaudeIndexer\gs` — ao lado do ambiente virtual e do
  catálogo — e a pasta `bin` dele é acrescentada à PATH do *usuário*. O
  instalador do fornecedor não conseguia rodar de forma desassistida: ele
  é manifestado como `requireAdministrator` (então todo destino,
  `%LOCALAPPDATA%` incluído, levanta um prompt do UAC), o `/S` não
  silencia mais esta build, e o que ele deixa na tela é uma página de
  "Concluir" esperando um clique. Descompactá-lo, em vez disso, não exige
  administrador, janela nem clique: medido em 2,1 s para 649 arquivos, com
  o `gswin64c --version` respondendo 0,2 s depois, contra ~93 s mais um
  prompt mais um clique. O extrator é o próprio MSI do 7-Zip,
  descompactado com `msiexec /a` (uma instalação administrativa, que não
  instala nada) e fixado e conferido por SHA-256 como todo download daqui.
  Rodar o instalador do fornecedor sobrevive como alternativa, e lá a
  espera é pelo binário responder `--version` — não por um processo que
  nunca termina — depois do que a janela remanescente é fechada
  encerrando-o. Limitado por um timeout que degrada com um aviso.
- A análise de hardware agora percorre todo adaptador de vídeo em vez do
  primeiro, e reporta o que fez para NVIDIA e Intel em vez de inventar um
  ajuste: nenhuma das duas precisa de um além do que o Ollama já faz.
- O instalador não escreve mais `HSA_OVERRIDE_GFX_VERSION`, e a remove se
  estiver presente. Medido numa RX 5700 XT com Ollama 0.33.2: o modelo
  roda a **100% de GPU, 66,9 tokens/s, pelo backend Vulkan**, sem o ROCm
  nunca ser tentado. A substituição não oficial da biblioteca ROCm que
  circula para essa placa trata de um Ollama mais antigo que só tinha CUDA
  e ROCm; aplicá-la agora sobrescreveria arquivos do Ollama com binários
  de terceiros para substituir um caminho que já funciona.

### Corrigido

- `$ErrorActionPreference = "Stop"` transformava o stderr de qualquer
  comando nativo num erro terminante. Isso quebrava o instalador em dois
  pontos: a verificação de versão do Python morria antes de imprimir a
  orientação escrita exatamente para esse caso, e o `ollama list` — rodado
  segundos depois de instalar o Ollama, enquanto o serviço dele ainda
  subia — matava o script depois de instalar tudo e antes da análise de
  hardware, das bibliotecas de sensor e do atalho. **Uma instalação do
  zero não conseguia terminar.** Os dois resolvidos pelo
  `Invoke-NativeCommand`.
- O `installer.py` passava opções do Inno Setup (`/VERYSILENT /NORESTART
  /SUPPRESSMSGBOXES`) para o instalador NSIS do Ghostscript, que ignora o
  que não reconhece e teria aberto uma janela esperando por um humano no
  meio de uma instalação desassistida. Mudado para `/S` — que depois foi
  medido e também não silencia esta build, então o `install.ps1` parou de
  rodar aquele instalador por completo (veja "Ghostscript é
  descompactado, não instalado"). O `installer.py` ainda carrega a
  abordagem antiga; ele está listado em "Limitações conhecidas" abaixo.
- O `Install-IfMissing` devolvia a saída do winget junto com o booleano,
  então `$GhostscriptOk` era sempre verdadeiro e os avisos dele nunca
  apareciam.
- Todo aviso de "o instalador retornou o código N" no `install.ps1` era
  código morto: o `Start-Process -PassThru` devolve um objeto `Process`
  cujo `ExitCode` fica `$null` para sempre, a menos que o handle dele
  seja mantido aberto. Ler o `.Handle` uma vez, logo depois de lançar,
  torna o código de saída legível — medido antes e depois.
- O instalador escrevia `__pycache__` na pasta do projeto, que é
  sincronizada pelo Google Drive, contra a regra da própria especificação.
  Corrigido com `-B`; o `conftest.py` da raiz acabou não cobrindo nem a
  compilação dele mesmo, então o `PYTHONDONTWRITEBYTECODE` agora é
  definido no CI e o `-B` documentado nos guias de contribuição.
- A tela Sobre teria oferecido restaurar justamente a variável de
  ambiente que o instalador tinha acabado de remover.

### Limitações conhecidas

- **A recusa do UAC nunca foi exercitada.** A elevação está comprovada,
  recusá-la não está, e o caso de conta padrão, em que o Windows pede
  credenciais, também não. (A nota anterior aqui dizia que esta máquina
  tem `ConsentPromptBehaviorAdmin = 0` e nunca mostra diálogo; medido de
  novo na Tarefa 5, ele é **5** — a máquina pergunta sim.)
- Não verificados na prática: GPUs NVIDIA e Intel, placas AMD que não
  RDNA1, máquinas sem GPU, falha de rede durante os downloads, e o
  Ghostscript pelo winget (o pacote sumiu).
- A alternativa do Ghostscript — o instalador do fornecedor, rodado
  elevado — foi testada contra um substituto que se comporta como ele
  (escreve a árvore, depois trava), não contra o instalador em si:
  exercitá-lo de verdade exige alguém no teclado para aprovar um prompt
  do UAC.
- O `expected_sha256` dos downloads do Tesseract e do Ollama continua sem
  fixação no `install.ps1` — nenhum hash foi escrito sem ter sido medido
  antes.

## [Fase 14] - 2026-08-30 — Internacionalização e Preparação para Código Aberto

Objetivo desta fase (do plano): traduzir o projeto inteiro para o inglês —
identificadores, docstrings, esquema do banco, chaves de tradução e testes
—, remover sobras de desenvolvimento, e preparar o repositório para
publicação aberta sob a GPL-3.0 e para um instalador distribuível do
Windows.

### Adicionado

- `LICENSE` com o texto integral e literal da GNU General Public License
  v3.0.
- Cabeçalho de licença GPL no topo de todo módulo em `gclaude_indexer/`.
- `CONTRIBUTING.md`, com traduções para português do Brasil e espanhol em
  `docs/`, e este `CHANGELOG.md` — só em inglês, versão única, seguindo a
  convenção do Keep a Changelog.
- `README.md` reescrito como a porta de entrada do repositório em inglês
  (com `docs/README.pt-BR.md` e `docs/README.es.md`), substituindo o
  `README.md` só em português com que esta fase começou — corrigido contra
  o código atual onde quer que tivesse se desviado (veja "Corrigido"
  abaixo).
- `docs/SPECIFICATION.md`, a referência técnica traduzida para o inglês a
  partir do antigo `ESPECIFICACAO.md` e corrigida contra o código atual
  (mantida como documento único, só em inglês — é referência interna, não
  voltada ao usuário).
- `.gitignore` (o projeto não usava controle de versão até esta fase).

### Removido

- Sobras de desenvolvimento: um arquivo `INSERT_PATH` vazio criado por
  acidente, a pasta vazia `_tmp_task7_check/`, e todos os diretórios
  `__pycache__/`.

### Alterado

- Toda a base de código de `gclaude_indexer/` — identificadores,
  comentários, docstrings — e o esquema do SQLite (`project`, `file`,
  `page`, `window`, `item`, `event`, `run`) traduzidos para o inglês,
  incluindo cada rota HTTP, variável de contexto de template, classe e
  variável CSS, e o formato de transmissão JSON dos motores de
  classificação (`raw_items.jsonl`). A interface em três idiomas
  (`pt`/`en`/`es`) via `i18n.py` não é afetada — só as *chaves* passaram
  para o inglês; o texto de cada idioma continua o mesmo.
- O idioma padrão da interface agora é detectado do idioma de exibição do
  Windows, e pode ser sobreposto pela variável de ambiente
  `GCLAUDE_INDEXER_LANGUAGE`.
- Os quatro artefatos de saída (`index.md`, `timeline.md`, `review.md`,
  `project_instructions.md`) e as mensagens do próprio log de execução
  agora são gerados no idioma atual da interface, retraduzíveis tanto na
  leitura quanto na escrita.
- A suíte de testes renomeou `test_fase1.py`…`test_fase13.py` para
  `test_phase1.py`…`test_phase13.py`, mais um `test_phase14.py` novo para
  a cobertura desta fase.
- O instalador, traduzido e renomeado de `instalar.ps1` para
  `install.ps1` (mensagens, comentários e nomes de função e variável
  incluídos; o parâmetro `-AutoInstalar` agora é `-AutoInstall`), junto
  com `Indexador.bat`/`Indexador.vbs` renomeados para
  `Indexer.bat`/`Indexer.vbs` e `iniciador.py`/`executar_servidor.py`
  renomeados para `launcher.py`/`run_server.py`. A lógica do instalador
  (detecção de Python/venv, a verificação de hash do `requirements.txt`,
  as chamadas ao winget, a detecção de GPU, a idempotência) não mudou — só
  os nomes e o texto voltado ao usuário passaram para o inglês.

### Corrigido (documentação)

- O `README.md` e o `ESPECIFICACAO.md` tinham se desviado do código antes
  mesmo de esta fase renomear qualquer coisa: eles ainda citavam
  `pecas_brutas.jsonl` (agora `raw_items.jsonl`), `indice.md` (agora
  `index.md`), `janelas/` (agora `windows/`), `estilo.css` (agora
  `style.css`), `projetos.json` (agora `projects.json`), e vários nomes de
  módulo e rota anteriores ao trabalho de tradução desta fase. Corrigidos
  por inteiro, junto com o requisito de versão do Python (`3.11+` estava
  documentado; as dependências fixadas exigem de fato o **3.12**
  especificamente — interpretadores mais novos as quebram).

### Segurança

- Lista de colunas SQL permitidas (`_NULLABLE_COLUMNS`) nos dois
  auxiliares `_count_nulls` de `quality.py`. Não havia injeção — os
  argumentos são literais de código — mas um nome de coluna não pode ser
  parâmetro de SQL, então a interpolação é inevitável e a validação é o
  que impede a entrada do usuário de chegar até ela.
- Revisão do `requirements.txt` com o `pip-audit`: **46 vulnerabilidades
  conhecidas em 6 pacotes**, reportadas sem alterar nenhuma fixação.
  Quatro são atualizações diretas (jinja2 3.1.4 para 3.1.6,
  python-multipart 0.0.12 para 0.0.31, pillow 10.4.0 para 12.3.0, pytest
  8.3.3 para 9.0.3); o starlette 0.38.6 não tem correção compatível com
  `fastapi==0.115.0`, então precisa de uma atualização do FastAPI e não de
  uma mudança de fixação. Deixado como decisão do mantenedor, já que
  atualizar sem testar é como um sistema que funciona quebra.
- `SECURITY.md` e `CODE_OF_CONDUCT.md`, mais os modelos de issue e de pull
  request do GitHub.

### Integração contínua

- `.github/workflows/tests.yml`: a suíte no `windows-latest` com Python
  3.12, com um comentário explicando por que não há job de Linux (o
  projeto usa PowerShell, WMI e o registro). Instala Tesseract e
  Ghostscript pelo Chocolatey e baixa o `por.traineddata` à parte —
  nenhum dos dois pacotes o traz, e os três testes de OCR real precisam
  dele. **Nada na suíte fica de fora do CI.** O workflow em si não foi
  executado num runner de verdade: o projeto não tinha repositório git
  quando ele foi escrito.

### Corrigido (verificação final)

A verificação de ponta a ponta rodou o sistema inteiro em vez da suíte, e
achou cinco defeitos que 319 testes passando não acharam:

- O `projeto.lock` persistia chaves JSON em português (`maquina`,
  `usuario`, `criado_em`, `atualizado_em`) na pasta de saída de todo
  projeto — o único pedaço de estado persistido que o mandato de tradução
  tinha deixado escapar. Agora é `project.lock`, com chaves em inglês.
- A etiqueta de etapa `importacao` nunca foi acrescentada a `STEPS` nem à
  tabela de tradução, então vazava crua para o log ao vivo em toda
  execução real, nos três idiomas. O mesmo valia para `diagnostico`,
  achada enquanto se procuravam irmãs. As duas agora são renderizadas
  traduzidas, por uma lista de exibição `LOG_KNOWN_STEPS` mantida separada
  de `STEPS`.
- Erros de validação de configuração eram montados como strings fixas em
  português e exibidos independentemente do idioma da interface. O
  `ConfigError` agora carrega `ConfigErrorMessage(key, params)`,
  renderizado pela camada de exibição.
- Os diagnósticos de GPU e sensores da tela Sobre eram frases em português
  embutidas no código, e o código cru de `sensors.unavailable_reason()`
  vazava sem tradução para a página.
- As telas de trava e de sincronização mostravam mensagens montadas em
  português em `lock.py` e `sync.py`. Os dois resultados agora carregam
  `message_key` e `message_params`.
- 45 de 64 atributos `id=` dos templates, a maior parte dos
  identificadores de JavaScript embutido, e os nomes de bloco e macro do
  Jinja ainda estavam em português — invisíveis porque o texto visível já
  estava corretamente traduzido.

### Verificado

- Pipeline completo sobre um acervo de 6 PDFs (um só de imagem, exigindo
  OCR): 7 etapas, 7 peças classificadas com confiança alta, 4 artefatos
  gerados com conteúdo real.
- Todas as 16 combinações de tema x layout mais os três idiomas, sem
  chaves de tradução cruas, títulos vazios, tabelas transbordando ou erros
  de console.
- A suíte rodou duas vezes sem instabilidade.

### Limitações conhecidas

- Projetos criados antes desta fase não abrem: o `processing_mode` e o
  `group_mode` guardados neles têm valores em português, e a validação
  rejeita valores desconhecidos em vez de recorrer ao padrão, então a tela
  retorna HTTP 500. Nenhuma camada de compatibilidade foi escrita — o
  mantenedor tinha confirmado que os acervos existentes eram dados de
  teste descartáveis.
- O `_PROMPT` enviado ao modelo local e o `CLAUDE.md` gerado continuam em
  português de propósito. As chaves JSON que eles pedem foram fixadas em
  inglês e validadas contra um modelo real, então o formato de transmissão
  não varia mais com o idioma da interface; a prosa não foi traduzida, o
  que ainda amarra a qualidade do motor `local` a acervos em português.

## [Fase 13] - 2026-08-29 — GPU, Qualidade e Layouts

Objetivo (do plano): fazer o sistema se instalar em qualquer máquina
usando o hardware que encontrar; monitorar a máquina inteira independente
do fabricante da GPU; e permitir comparar motores e modelos por tempo e
qualidade, com quatro layouts de interface genuinamente distintos.

### Adicionado

- Detecção de uso de GPU e VRAM para qualquer fabricante (não só NVIDIA).
- Monitoramento de clock de CPU, memória e GPU.
- Sensores de temperatura e potência via LibreHardwareMonitor.
- Um relatório de qualidade gerado ao fim de uma execução.
- Quatro layouts visuais selecionáveis e genuinamente distintos, com a
  infraestrutura para sustentá-los.
- Um instalador que prepara uma máquina nova de forma desassistida,
  adaptando-se ao hardware que detecta.
- Paralelismo na conversão/OCR e na extração — a maior melhoria isolada de
  desempenho desta fase.
- Um benchmark comparando motores e modelos lado a lado por tempo e
  qualidade.

### Alterado

- O painel de recursos agora expõe todas as métricas coletadas da máquina
  (CPU, RAM, GPU, temperatura, potência, clocks) num lugar só.
- A visão do log ao vivo não rola mais sozinha enquanto o usuário tiver
  subido para ler entradas anteriores.
- O seletor de modelos (para o motor `local`) agora faz efeito de verdade.
- A barra de progresso da varredura chega a 100% corretamente mesmo
  havendo arquivos duplicados.

### Corrigido

- A opção "Todas" de extensões de arquivo agora é mutuamente exclusiva com
  as categorias específicas de extensão no formulário de novo projeto
  (antes as duas podiam ser selecionadas ao mesmo tempo, com a "Todas"
  assumindo em silêncio).

### Removido

- O motor de classificação `openrouter`, removido por completo.

## [Fase 12] - 2026-08-28 — Correções de Interface

Objetivo (do plano): corrigir os 12 defeitos de interface achados durante
o primeiro uso real do GClaude Indexer v1.0 — internacionalização de
estado, comportamento da barra de progresso, legibilidade de formulários e
temas, e limpeza de arquivos intermediários.

### Adicionado

- Uma etapa de descoberta de modelos do Ollama instalados, alimentando o
  seletor de modelos.
- Quatro temas visuais selecionáveis.
- Limpeza dos arquivos intermediários deixados na pasta de saída.

### Alterado

- O estado de etapa/execução agora é representado por chaves estáveis, em
  ASCII e neutras de idioma (`estado_etapas.py`), em vez de texto em
  português acentuado usado simultaneamente como texto de exibição, classe
  CSS e valor de comparação — a causa raiz de vários dos 12 defeitos,
  incluindo um em que traduzir o texto de estado quebrava o botão de
  "rodar a próxima etapa".
- A barra de progresso mantém o último estado conhecido ("concluído",
  "pausado", "erro") em vez de sumir no instante em que uma etapa termina.
- O total de progresso da etapa de varredura agora respeita as extensões
  de arquivo selecionadas para o projeto, em vez de contar todo arquivo da
  pasta de origem.
- A barra de progresso mostra o título traduzido da etapa em vez da chave
  interna crua.
- A visão do log ao vivo mostra até 200 linhas (contra 50), acrescenta um
  filtro por nível (info/aviso/erro), e mantém a visão presa à última
  linha enquanto "seguir o fim" estiver marcado.
- As extensões de arquivo no formulário de novo projeto são agrupadas por
  família (documentos, imagens, texto/dados, mensagens), mostrando quais
  extensões cada categoria cobre, em vez de uma única fileira ordenada
  alfabeticamente.
- As descrições dos motores de classificação no formulário de novo projeto
  foram tornadas legíveis.

### Removido

- O banner dispensável de "troca de máquina".

### Corrigido

- Vazamentos de idioma remanescentes na interface (strings sem tradução
  ainda chegando à tela em idiomas que não o português).
