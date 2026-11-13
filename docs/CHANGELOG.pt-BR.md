# Registro de mudanças

Todas as mudanças relevantes deste projeto estão documentadas neste
arquivo. O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/).

> **Tradução.** O documento canônico é o
> [`CHANGELOG.md`](../CHANGELOG.md) em inglês. Se os dois divergirem, vale
> o inglês. Nomes de arquivo, identificadores de código, chaves de
> configuração e mensagens que o programa emite em inglês foram mantidos
> como estão.

As entradas mais antigas estão agrupadas por fase de desenvolvimento, e
não por versão semântica: a versão reportada pelo aplicativo
(`SYSTEM_VERSION`, em `web/app.py`) ficou em `1.0.0` da fase 1 até a fase
16. A `1.0.1` é o primeiro incremento, e publica tudo o que o bloco da fase
16, mais abaixo, vinha carregando como não lançado.

## [1.10.4] - 2026-11-13

### Corrigido

- Um documento que é sempre lido como uma página só (HTML, texto, arquivos
  do Office, imagens) e foi alterado no lugar não manda mais o resto do
  grupo de volta para a leitura e a classificação. Só as janelas que
  contêm a página dele são descartadas; os documentos seguintes mantêm a
  numeração de folhas. Na 1.10.3, alguns atos alterados numa pasta grande
  de legislação renumeravam todos os documentos seguintes do grupo e
  descartavam todas as janelas seguintes. PDFs, e documentos que entram ou
  saem do meio de um grupo, continuam seguindo a regra anterior, porque
  eles de fato deslocam as páginas seguintes.

## [1.10.3] - 2026-11-13

### Corrigido

- A leitura das páginas parava com `UNIQUE constraint failed:
  page.file_id, page.number` quando um documento mudava na pasta de origem
  e as etapas eram rodadas pela tela Execução sem passar antes por
  "Atualizar". A varredura devolvia o documento para a fila, mas mantinha
  as páginas, os trechos da busca e as janelas antigos. Agora a etapa de
  varredura aplica aos documentos novos e alterados a mesma limpeza do
  botão "Atualizar". Documentos removidos continuam saindo do índice só
  depois que você confirma na tela de atualização.
- Um projeto que já ficou nesse estado se conserta sozinho no próximo
  "Rodar tudo até a classificação" ou "Continuar": os documentos afetados são lidos de novo,
  com o conteúdo novo. Não é preciso fazer nada à mão.

## [1.10.2] - 2026-11-04

### Alterado

- Documentação, comentários e testes revisados: todos os exemplos passam
  a usar nomes e dados fictícios. Nenhuma mudança no funcionamento.

## [1.10.1] - 2026-11-04

### Alterado

- Autores: o mesmo nome escrito com e sem acento ("ANTONIO PEREIRA" e
  "ANTÔNIO PEREIRA") passa a ter uma grafia só em todo o índice, em qualquer
  motor, e não só nos atos do Planalto. A grafia com maiúsculas e
  minúsculas continua valendo mais que a toda em maiúsculas, e a grafia
  com acento vence quando aparece pelo menos metade das vezes da sem
  acento. Vale no próximo "Importar e gerar relatórios"; nada é
  classificado de novo.
- Imagem de prévia do repositório refeita com as cores do tema Estúdio
  escuro, as fontes que vão com o programa e uma captura do layout Área de
  trabalho.

### Segurança

- Varredura de código com o CodeQL (configuração avançada): Python,
  JavaScript e os workflows do GitHub Actions, com o conjunto de consultas
  `security-and-quality`, a cada envio, a cada pull request e uma vez por
  semana.
- Revisão de dependências nos pull requests: uma dependência nova com
  vulnerabilidade conhecida ou licença incompatível bloqueia a mudança.
- Todos os workflows passam a rodar com um token só de leitura.

### Removido

- Notas internas de planejamento das fases passadas (`docs/superpowers/`),
  funções e imports sem uso e marcas de versão e de fase que tinham
  ficado nos comentários do código. Nada muda no funcionamento.

## [1.10.0] - 2026-11-03

Um visual novo, escolhido entre três propostas: o layout Área de trabalho,
com uma paleta própria, o tema Estúdio.

### Adicionado

- Layout Área de trabalho, agora o padrão: uma barra lateral com as telas
  principais e todos os projetos (com uma bolinha de situação), uma barra no
  alto mostrando onde você está e abas para as cinco telas de um projeto
  (Execução, Resultado, Busca, Atualizar acervo, Instruções).
- Paleta de comandos: Ctrl+K (ou "Buscar ou executar", na barra lateral)
  encontra qualquer tela, as telas de cada projeto e as preferências de
  tema, layout e idioma digitando parte de uma palavra, com ou sem acento.
  Ela só navega e muda preferências; nunca começa um trabalho. Funciona pelo
  teclado e com leitor de tela (diálogo, lista, setas, Enter, Esc).
- Temas Estúdio e Estúdio escuro: cinzas neutros e quentes e uma única cor
  de destaque, verde-azulada. O Estúdio é o padrão para quem nunca escolheu
  um tema.
- Fontes Inter e JetBrains Mono junto com o programa (licença SIL Open
  Font, arquivos em `web/static/fonts`), para continuar funcionando sem
  internet.
- Na tela Execução, a etapa que está rodando fica em destaque.

### Alterado

- A preferência de layout ganhou um cookie novo: quem usava outro layout vê
  a Área de trabalho uma vez depois de atualizar e pode voltar em
  Preferências. O tema escolhido é mantido. Os layouts anteriores (Padrão,
  Técnico, Editorial, Compacto) e os oito temas anteriores continuam lá.
- A barra lateral nunca abre o banco de um projeto: as bolinhas de situação
  vêm do que a tela Projetos já calculou.
- Capturas de tela e GIFs do passeio no README refeitos com o visual novo,
  nos três idiomas.

## [1.9.2] - 2026-11-03

Quem já tinha instruções antes de o bloco automático existir muitas vezes
copiou as seções dele à mão na própria parte. O bloco era anexado abaixo e o
Claude recebia tudo em dobro, com as contagens da cópia paradas ("120000
páginas") enquanto as do bloco eram atualizadas.

### Adicionado

- A geração reconhece uma cópia do bloco na parte do usuário de
  `project_instructions.md`: seções cujo texto é na maior parte o do bloco
  (comparado palavra por palavra, sem acento, maiúsculas, travessão, dois
  pontos, numeração e números), em qualquer um dos três idiomas, e linhas
  com contagens que mudam a cada indexação. O texto do usuário nunca é
  mudado ali: um aviso vai para o início do bloco e para o log, e as telas
  Execução e Resultado mostram um link para revisar.
- Na tela Instruções do projeto: as seções repetidas, as linhas com
  contagens, as referências do tipo "seção 4" que passariam a apontar para
  o bloco e os trechos do próprio usuário que falam do acervo. "Remover as
  repetições" tira as cópias (a versão anterior fica num `.bak` datado),
  aponta essas referências para o bloco e move os trechos marcados para as
  Regras extras do projeto, que saem dentro do bloco. "Manter como está" só
  registra a escolha. As duas ficam no log.

### Corrigido

- Um arquivo sem marcas cuja parte do usuário tinha uma cópia à mão da
  regra inegociável era tomado por um arquivo escrito inteiro por uma
  versão antiga e substituído (ficava só no `.bak`). Agora toda seção do
  arquivo precisa ser uma das que o programa escreve.

A primeira geração depois de atualizar põe o aviso no bloco de um projeto
que tem cópia; o arquivo muda uma vez e precisa ser colado de novo no
Projeto do Claude.

## [1.9.1] - 2026-11-03

O que tinha ficado para depois na 1.9.0, feito agora: navegação mais rápida
nos projetos guardados no Google Drive e os defeitos de autor achados num
acervo grande.

### Mudou

- As telas que só leem (Execução, as atualizações periódicas dela e
  Resultado) mantêm uma conexão só de leitura por projeto aberto
  (`web/readers.py`), e o cache de páginas do SQLite sobrevive entre um
  pedido e outro. Ela é reaberta sempre que o `project.db` muda no disco
  (por exemplo, quando o Google Drive traz a cópia do outro computador),
  fechada depois de dois minutos sem uso e fechada quando o projeto é
  fechado, apagado ou assumido. Etapas, importação e atualização continuam
  com as suas próprias conexões de gravação.
- A tela Projetos não abre mais o banco de cada projeto a cada visita: o
  resumo de cada um é guardado enquanto o `project.db` for o mesmo arquivo
  (tamanho e data de modificação).
- A conferência de mudanças no acervo lê a tabela `file` uma vez em vez de
  duas, e um arquivo novo só é lido inteiro (para procurar duplicata)
  quando existe outro arquivo com exatamente o mesmo tamanho.
- Na primeira execução, antes de o modelo ser baixado, o log estima o
  `qwen3.5:9b` pelo tamanho dele (cerca de 6,3 GB), e não pelos 3232 MB do
  4b.

### Corrigido

- Autor, data, tipo ou resumo que só dizia "null", "N/A", "-" ou parecido
  saía como texto no índice; agora fica vazio.
- O mesmo autor escrito com maiúsculas diferentes pelo modelo local ("LUIZ
  INÁCIO LULA DA SILVA" e "Luiz Inácio Lula da Silva") passa a ter uma
  grafia só, a mais frequente entre as escritas com maiúsculas e
  minúsculas. Nomes que só aparecem em maiúsculas ficam como estão.
- Uma norma citada como autor ("Lei nº 9.394/1996", "Decreto 7.892 de
  2013") deixou de aparecer como autor.
- Uma peça que avançava sobre a primeira página da seguinte (uma "PÁGINA EM
  BRANCO" f. 14-15 seguida de uma peça que começa na f. 15) agora termina
  na página anterior. Uma peça inteira dentro de outra fica como está.

As correções valem na próxima vez que "Importar e gerar relatórios" rodar;
nada é classificado de novo.

## [1.9.0] - 2026-11-03

Um usuário confirmou uma atualização do acervo sem colar as instruções e não
conseguiu parar: o botão Parar do navegador só largava a resposta, o servidor
seguia trabalhando e o clique seguinte dizia "ocupado com: Atualizar". No fim,
a tela não voltou sozinha para a Execução. Ele também relatou que abrir um
projeto grande ou gerar relatórios deixava a tela parada sem aviso, que a barra
de andamento ficava ilegível em temas escuros, que trocar de tema no meio
apagava a barra, que a navegação era lenta e que o Sobre não mostrava a versão
do driver de vídeo.

### Corrigido

- **Parar qualquer operação longa.** "Atualizar" e "Importar e gerar relatórios"
  rodam em segundo plano, e um painel no meio da tela mostra o que está rodando,
  o tempo decorrido e o botão Parar. Parar não grava nada pela metade: a
  atualização volta ao estado de antes do clique, e na geração de relatórios
  cada arquivo fica o antigo ou o novo, com o log dizendo quais mudaram. A
  página de "projeto ocupado" também tem o botão Parar.
- **Volta sozinha para a próxima tela.** Quando a operação termina, a tela vai
  para a Execução (depois de atualizar) ou para o Resultado (depois de gerar),
  mesmo que você tenha recarregado a página ou trocado de aba no meio.
- **Aviso de "aguarde" legível em todos os temas.** A barra amarela do alto usava
  uma cor de fundo que nenhum tema definia, com o texto branco do tema por cima.
  O painel novo usa as cores de superfície e de texto do próprio tema.
- **Trocar de tema ou de layout não recarrega a página** e não apaga o painel.
  Trocar de idioma recarrega, e o painel volta com o tempo certo, porque é o
  servidor que diz o que está rodando.
- **Telas lentas avisam.** Ao abrir um projeto grande ou qualquer tela que
  demore, aparece "Carregando, aguarde" com um relógio, em vez da tela parada.
- **Sobre** mostra o driver de vídeo instalado com a data de publicação, por
  exemplo "driver 621.01 (32.0.16.2101), publicado em 18/10/2026". Nas placas
  NVIDIA aparece também o número que a NVIDIA divulga.
- **Sem travessões nas telas e no manual.** Os textos foram reescritos com
  vírgula, dois-pontos, ponto ou parênteses. Os arquivos de índice e de
  cronologia não mudam por causa disso.

### Adicionado

- **Tela "Instruções do projeto"**, nas telas Execução e Resultado: mostra a sua
  parte de `project_instructions.md` para corrigir ou colar a versão atual do
  Projeto do Claude a qualquer momento, sem precisar atualizar o acervo. A parte
  gerada pelo programa aparece embaixo, só para leitura, e cada gravação guarda
  a anterior numa cópia `.bak` datada.
- Acabamento visual: fontes do próprio Windows 11, títulos com mais presença,
  seções sem caixa alta, campos e botões com resposta ao foco e ao clique,
  sombras na cor do tema, indicação da tela atual no menu e atalho "Pular para
  o conteúdo". A entrada de cada tela ficou mais curta, para não parecer demora.

### Desempenho

Medido num projeto grande guardado no Google Drive:

- **Resultado**: levava dezenas de segundos em toda abertura. Agora só a primeira
  abertura depois de uma mudança faz as contas, e as seguintes são quase
  imediatas. A qualidade, as pendências e a comparação de execuções só são
  recalculadas quando as peças, as janelas ou as páginas mudam, e as
  pendências são calculadas uma vez só. O tamanho dos arquivos intermediários
  vem da própria listagem da pasta.
- **Execução parada não lê mais o banco a cada 2 s.** Sem nada rodando, a tabela
  de etapas e a caixa de andamento são reaproveitadas por até 30 s; qualquer
  coisa que comece ou termine renova as duas na hora. Com algo rodando, nada
  muda. As cinco contagens de arquivos viraram uma só.
- **Conferência da pasta de origem**: o cálculo do caminho relativo, que era a
  maior parte do tempo da varredura, virou um corte de texto com o mesmo resultado. A
  atualização confirmada deixou de percorrer a pasta uma terceira vez.
- **Sobre** guarda o diagnóstico da instalação por 5 minutos.
- A renovação da trava de uso, uma gravação no Drive a cada minuto, não segura
  mais as outras telas enquanto grava.

### Não mudou

- O `project_instructions.md` muda uma vez na primeira geração na 1.9.0 (o
  título da seção gerada e a marca do bloco ficaram sem travessão): cole-o de
  novo no Projeto do Claude. Os índices e as cronologias não mudam.
- As etapas de "Rodar tudo" continuam com o próprio quadro de andamento e o
  botão Pausar.

## [1.8.1] — 2026-11-03

Um usuário incluiu documentos num acervo grande, abriu o projeto e não viu
sinal de que o programa tinha percebido. Ele tinha como perceber: a tela
"Atualizar acervo" lista documentos novos, alterados e removidos desde a
fase 17. A conferência por trás do aviso levou minutos num acervo desse
tamanho no Google Drive, e a tela de Execução não mostrava nada
enquanto isso. O mesmo pedido incluiu que as instruções do Projeto do
usuário sejam atualizadas, não substituídas, e que só a indexação nova mude
os arquivos de saída.

### Corrigido

- **A conferência "a pasta de origem mudou" leva segundos, não minutos**
  (`scanning.walk_source_stats`, `update_plan.detect_changes`). No Windows,
  a listagem da pasta já traz o tamanho e a data de cada arquivo; a
  conferência descartava esses dados e perguntava de novo ao disco, arquivo
  por arquivo. Num acervo grande: segundos em vez de minutos, com as datas
  da listagem idênticas às gravadas em todos os arquivos sem mudança, então
  nada é relido. A etapa de varredura usa os mesmos valores e fica mais
  rápida pelo mesmo motivo.
- **A tela de Execução avisa que está conferindo.** Enquanto a conferência
  roda, a área do aviso mostra "Conferindo a pasta de origem: documentos
  novos, alterados e removidos…" em vez de ficar em branco.
- **As instruções geradas não contradizem mais as do usuário.** Quando
  `project_instructions.md` tem instruções do próprio usuário, a parte
  gerada passa a ser uma seção do documento dele ("Acervo indexado pelo
  GClaude Indexer"), um nível de título abaixo, com os números, os
  arquivos, as colunas e as regras do acervo, sem um segundo título nem o
  "Papel" genérico. Um projeto podia ter centenas de linhas de instruções
  próprias seguidas de "você é um assistente de pesquisa". Sem instruções do
  usuário, o arquivo continua como antes.

### Adicionado

- **A tela de atualização pede as instruções atuais do Projeto.** Um campo
  vem preenchido com a parte do usuário de `project_instructions.md`; se as
  instruções foram mudadas no Projeto do Claude, o usuário cola ali a versão
  atual. Ela substitui só a parte do usuário, mantida exatamente como foi
  colada, com todas as personalizações; a seção gerada continua e é
  atualizada na geração seguinte. Um texto colado que traga a seção gerada
  fica só com o que está fora dela. O arquivo anterior fica guardado como
  `project_instructions.md.<data-hora>.bak`. Campo vazio ou sem mudança não
  altera nada.
- **Só os arquivos de saída que mudaram são regravados.** Cada geração
  compara o que escreveria com o que está no disco, ignorando a data de
  geração, e não toca nos arquivos iguais. O log então diz quais arquivos
  mudaram (os que devem ir de novo para o Projeto do Claude) ou que nenhum
  mudou. Incluir um documento num grupo regrava o índice desse grupo, o
  resumo e a cronologia, não os índices dos outros grupos. O índice de um
  grupo que saiu do acervo é apagado, e o log também diz qual foi, para
  ser tirado do Projeto do Claude.

### Sem mudança

- A detecção de documentos removidos, de pastas removidas e de pastas novas
  já existia e não mudou; a 1.8.1 acrescenta testes para uma pasta nova
  inteira e uma pasta removida inteira, comparados com indexar o mesmo
  acervo do zero.

## [1.8.0] — 2026-11-02

Fase 38. Dois pedidos do usuário, mais dois achados do mesmo dia. Os
pedidos: vários acervos dentro de um único Project do Claude sem colisão
de nomes, e uma documentação que uma pessoa fora da TI consiga ler. Os
achados: o pacote de um projeto grande levava arquivos `legislacao-<grupo>.md`
de dezenas de megabytes (milhões de tokens) que nenhum Project aceita,
enquanto o orçamento "só informava, nunca bloqueava"; e uma pergunta como
"quais leis tratam de saneamento" precisa de busca no texto inteiro, não de uma lista
de links. Classificador, prompt, regras e pipeline não mudaram.

### Adicionado

- **Conjuntos** (tela `/sets`, `gclaude_indexer/sets.py`,
  `gclaude_indexer/combined_package.py`): uma seleção nomeada de dois ou
  mais projetos, mais as instruções que o usuário já usa no Project,
  guardada no catálogo local da máquina. O pacote combinado prefixa cada
  arquivo com o apelido do projeto (`<apelido>__index.md`,
  `<apelido>__index-<grupo>.md`, `<apelido>__timeline.md`,
  `<apelido>__review.md`), reescreve os links entre sumários e índices de
  grupo para os nomes prefixados, inclusive rótulos entre crases e índices
  divididos em partes, e grava um único `project_instructions.md`: o texto
  pessoal no topo, fora das marcas; dentro delas, o papel uma vez, uma
  seção por acervo e a regra "em qual acervo procurar". "Gravar numa pasta"
  produz os mesmos arquivos mais um `CLAUDE.md` combinado para o Claude
  Code, recusa a pasta de origem ou de saída de um projeto e apaga os
  arquivos prefixados dos projetos que saíram do conjunto. As pastas de
  saída de cada projeto não mudam, então Projects e `CLAUDE.md` existentes
  continuam valendo.
- **`normas-citadas.md`** na pasta de saída e no pacote: uma linha por ato
  federal reconhecido no acervo (tipo, número, ano, ementa curta quando
  houver, link para o texto no LexML, grupo e páginas em que aparece).
  Poucos KB mesmo num acervo com espelho completo do Planalto. As
  instruções geradas passam a dizer que a legislação não está no
  conhecimento do Project: leia este arquivo para saber o que existe, siga
  o link para ler o texto, peça ao usuário uma busca por tema.
- **Busca por tema para o Claude Code**: `tools/buscar.py`, e um
  `buscar.bat` gravado na pasta de saída, consultam a base do projeto com o
  mesmo motor FTS5 da tela "Buscar no acervo" e imprimem, em Markdown, as
  normas e páginas que citam um termo, com trecho, arquivo de origem e
  link do LexML; opções `--grupo`, `--so-legislacao`, `--limite`,
  `--lexml`. O `CLAUDE.md` da pasta de saída manda o Claude Code usá-la
  nas perguntas temáticas.
- **LexML** (`gclaude_indexer/lexml.py`): quando um termo não aparece em
  norma nenhuma do acervo, ou a pedido, a busca consulta o serviço público
  SRU do LexML e lista as normas encontradas como "fora do acervo". É a
  única chamada que sai da máquina, envia só o termo digitado e nunca roda
  durante a indexação. Conferido: o serviço responde a programas
  com a página "Verificação de segurança" do Senado; o cliente reconhece
  essa página (um documento HTML, ou a marca dentro de `<title>`, nunca uma
  ementa que por acaso contenha as palavras), avisa e dá o link para abrir
  no navegador. Contornar a verificação não é opção. A tela "Buscar no
  acervo" ganhou a mesma caixa "Também procurar no LexML".
- **Orçamento que protege** (`gclaude_indexer/claude_package.py`):
  `MAX_FILE_BYTES` (30 MB, o limite por arquivo do Project na época
  desta versão) e `RAG_THRESHOLD_TOKENS`. Um arquivo acima do teto por
  arquivo nunca entra no pacote, simples ou combinado; a tela o mostra em
  vermelho, com tamanho e o que fazer. Acima do total, a tela lista o que
  cabe e o que sobra, e o botão de baixar avisa antes de gerar. O índice
  de grupo já sai em partes de até 25 MB desde a 1.6.0 (`INDEX_PART_BYTES`);
  o que muda é que um único arquivo de origem cujo índice sozinho passe de
  30 MB fica fora do pacote, e a tela diz qual.
- **Mídia refeita na 1.8.0**: `docs/media/demo-{pt,en,es}.gif` e 21 telas
  sobre `demo/acervo` com o motor de regras, janela de 1366 px, tema claro,
  com temperatura, ventoinha e consumo da CPU lidos pelo ajudante elevado
  visíveis na tela Execução; novas `search-*.png` e `sets-*.png`.
- **Teste de linguagem** (`tests/test_phase38_docs.py`) sobre README ×3,
  manual ×3, `demo/README.md`, `tools/README.md` e `docs/TECHNICAL` ×3:
  nenhum travessão ou meia-risca como aparte, aspas retas, nenhum caractere
  de reticências, nenhuma palavra das listas de vocabulário inflado (pt,
  en, es).

### Alterado

- **README ×3 reescritos para quem não é de TI**: uma frase do que o
  programa é, três pessoas que usam, o que você recebe (com as telas), o
  que precisa ter, dez minutos para experimentar, quanto acerta (os números
  do `docs/QUALITY.md`, uma frase cada), privacidade, vários acervos,
  legislação e busca, equipe. Cada README ficou menor do que antes. Todo
  detalhe técnico foi para os novos **`docs/TECHNICAL.md`**,
  **`docs/TECHNICAL.pt-BR.md`** e **`docs/TECHNICAL.es.md`**, que mantêm os
  dezesseis tópicos da antiga seção "Detalhes técnicos" e acrescentam
  conjuntos e busca.
- **Manual ×3 reescrito** com as mesmas regras, 22 seções, com seções novas
  sobre o acervo de demonstração, o que esperar de acerto, conjuntos,
  normas citadas e busca, os sensores e o pedido de administrador, pausar e
  continuar, e atualizar o programa. A lista de campos de Novo projeto
  bate com a tela (o teto de tokens do pacote não é um campo).
- **CONTRIBUTING ×3** (um commit por tarefa, o CI indexa o acervo de
  demonstração, a regra da documentação, como o instalador do Windows é
  gerado), **SECURITY**, **CODE_OF_CONDUCT**, **QUALITY ×3**,
  **SPECIFICATION** (`normas-citadas.md`, `buscar.bat`, conjuntos, as sete
  telas), os modelos de issue e pull request do GitHub, a descrição e os
  tópicos do repositório e a imagem social
  (`docs/media/social-preview*.png`, gerada por `docs/social-preview.py`).

### Removido

- **`legislacao-<grupo>.md` e a opção "Legislação do Planalto no pacote"**
  (`planalto_in_package`, fases 31 a 37). O arquivo copiava o texto de cada
  ato reconhecido; num acervo com espelho do Planalto chegava a dezenas de
  megabytes que nenhum Project aceita, e o mesmo texto está a um link de
  distância. Projetos que ainda tenham o arquivo na pasta de saída o perdem
  na próxima geração, como qualquer órfão. A chave continua gravada no
  `config_json` de todo projeto criado até a 1.7.5 e é ignorada na leitura,
  para esses projetos continuarem abrindo. O reconhecimento de atos
  federais (`planalto.py`) e a indexação das páginas `.htm` como páginas do
  acervo não mudaram.

### Corrigido

A tarefa de fundo de uma etapa era marcada como terminada antes de a linha de
`run` receber `finished_at` e `ok`: quem lia o banco naquele instante (a
tabela "Comparar motores e modelos" da tela Resultado, o teste da fase 13)
via a execução ainda aberta e a comparação saía vazia. Visto uma vez no runner
do GitHub (1 falha em 1204, suíte a 9 min) e uma vez localmente
sob carga. A marca só vira depois do commit.

Seis correções da revisão independente da parte A: a reescrita de links do
pacote combinado alcança rótulos entre crases e o índice em partes; salvar
um conjunto mantém o membro que está fora do ar em vez de descartá-lo em
silêncio; gravar um conjunto na pasta de um projeto é recusado com
mensagem; regravar um conjunto numa pasta apaga os arquivos prefixados que
saíram do conjunto; o cliente do LexML não confunde mais uma ementa que
contém as palavras da verificação com a página de verificação; o resumo de
um ato revogado sem ementa volta às suas partes em vez de uma linha vazia.

## [1.7.5] — 2026-11-02

Fase 37. Depois de uma avaliação honesta do projeto, o usuário pediu três
provas que qualquer pessoa que abra o repositório possa conferir: "CI,
medida de qualidade e acervo de demonstração". Nada no classificador, no
prompt ou nas regras mudou nesta fase; ela mede o que existe.

### Adicionado

- **Acervo de demonstração** (`demo/acervo`, 72 páginas, 41 peças, 7
  arquivos): dois volumes encadernados de um processo administrativo
  fictício em PDF, um contrato, um memorando em Word, uma planilha, um
  ofício digitalizado em PNG e um e-mail, gerados por `demo/gerar_acervo.py`
  a partir de uma única lista de peças e versionados com o gabarito,
  `demo/gabarito.csv` (peça, tipo, data e autor de cada página). Tudo
  inventado: município, pessoas, empresa, CNPJ e número de processo (os dois
  inválidos de propósito). `demo/README.md` e a seção "Experimente em dez
  minutos" nos três READMEs.
- **Acerto contra gabarito** (`gclaude_indexer/answer_key.py`,
  `tools/medir_acerto.py`): cobertura de páginas, peças encontradas por
  Jaccard ≥ 0,5 sobre conjuntos de páginas (precisão, revocação, F1) e
  tipo, data e autor entre as encontradas, por grupo e no total, com a
  lista das divergências em relatório Markdown. A tela "Qualidade" media a
  autoconfiança declarada; isto mede o acerto.
- **`docs/QUALITY.md` ×3** com os números desta máquina (RX 6700 XT,
  Ollama 0.40.13). Motor de regras: cobertura 100 %, limites F1 86,7 %,
  tipo 94,4 %, data 50,0 %, autor 19,4 %, 4 s. `qwen3.5:9b`: cobertura
  100 %, F1 66,0 % (devolve em geral uma peça por página), tipo 60,0 % na
  comparação exata (80 % aceitando nomes mais específicos como
  "PARECER JURÍDICO"), data 88,6 %, autor 84,4 %, 4 min 12 s. O documento
  diz o que cada número significa e o que não significa.
- **CI prova o produto**: `tools/indexar_pasta.py` roda as cinco etapas, a
  importação e os artefatos sem interface; a rodada do GitHub indexa o
  acervo de demonstração com o motor de regras a cada push, falha se alguma
  página do gabarito ficar fora do índice e anexa o relatório de acerto e o
  índice à execução. Selo dos testes no topo dos três READMEs.

### Corrigido

- **A suíte de testes não alcança mais o Ollama real do desenvolvedor.**
  Ela mandava centenas de 404 com modelos falsos a `127.0.0.1:11434`, o
  `ollama --version` da tela Sobre perguntava a versão ao servidor real e,
  com a porta fechada, o caminho de reinício subia um `ollama serve` de
  verdade, que ficava órfão atendendo os modelos falsos. A suíte agora
  aponta o motor, o CLI (`OLLAMA_HOST`) e o lançador para uma porta
  fechada, no processo inteiro; provado com o servidor no ar: 339 testes,
  zero linhas novas em `ollama-serve.log`, nenhum processo a mais.
- **A suíte de testes parava o Ollama real da máquina.** Um teste da fase
  19 provava que a `Stop-OllamaProcesses` do desinstalador sobrevive a um
  Ollama ausente chamando a função de verdade — e ela para todo processo
  chamado `ollama` da máquina. O servidor do modelo morreu
  duas vezes no meio de uma classificação e mais uma durante a suíte; um
  canário que conferia o processo após cada teste achou o culpado numa
  rodada. O teste agora esconde os processos da função, e um teste de
  guarda mantém um sósia de `ollama.exe` vivo durante ele.

## [1.7.4] — 2026-11-02

Fase 36. O usuário pediu que o programa use tudo o que a máquina tem,
automaticamente, em qualquer hardware — "o resultado mais rápido que
ainda garante a melhor informação no índice". Medido no mesmo hardware
da 1.7.3 (RX 6700 XT 12 GB, Ollama 0.40.13, qwen3.5:9b).

### Corrigido

- **Trechos maiores que o contexto não são mais cortados em silêncio.**
  Alguns pedidos da rodada eram trechos de mais de 20 mil tokens que o
  Ollama cortava a 8194 antes de o modelo os ver; a guarda `linhas <
  páginas` dividia o trecho em seguida, então o índice não perdeu nada,
  mas cada um tinha pagado uma tentativa de ~70 s que não podia dar
  certo. O pedido agora leva `truncate: false` (o Ollama 0.40 responde
  HTTP 400 com a contagem exata de tokens em vez de cortar), a recusa ou
  a assinatura antiga do corte contam como tentativa falha — nunca como
  resposta —, o contexto sobe até o que o trecho precisa e o trecho
  inteiro é enviado de novo; só quando nem o teto basta ele é dividido,
  e um trecho cuja estimativa já passa do teto é dividido antes de
  qualquer pedido.
- **Modo "cpu" e máquinas sem placa passam a enviar `num_ctx`.** Esse
  caminho retornava antes de dimensionar o contexto, e o padrão de 4096
  do Ollama cortava todo trecho cheio.

### Adicionado

- **Teto de contexto calculado pelo hardware.** Em vez de uma lista fixa
  que parava em 16384, o teto é o maior múltiplo de 4096 cujo cache KV
  cabe na placa ao lado do modelo inteiro, da margem de segurança e dos
  buffers de cálculo do runner (medidos em ~400 MiB), limitado a 131072
  e ao limite do próprio modelo; na CPU, a mesma conta sobre a RAM
  livre, limitada a 32768. O custo do KV conta só as camadas que mantêm
  cache (qwen3.5: 8 de 32 — a conta antiga por todas as camadas era 4×
  maior: 1 GiB calculado contra 272 MiB alocados). Aqui vai de 16384 a
  131072, e os trechos de 26 mil tokens cabem inteiros (`size_vram ==
  size` medido até 49152). Um modelo cujos metadados não dão o custo do
  KV mantém os 16384 antigos na placa. O tipo de cache para o qual o
  teto é dimensionado é o que o servidor realmente usa: com a flash
  attention desligada, f16, diga o que disser a variável.
- **O log diz qual backend está em uso e por que não um melhor**: "Placa
  de vídeo em uso: AMD Radeon RX 6700 XT (12.0 GiB), via Vulkan", que o
  Ollama atende esta família de modelo um pedido por vez e — em AMD RX
  5000/6000 — que o ROCm está fora de alcance porque o driver não traz
  `amdhip64_7.dll` (qualquer outra placa AMD com driver antigo recebe o
  aviso de atualizá-lo, o que nela traz o ROCm). Lido só dos logs do
  servidor; nada é forçado.
- **Flash attention desligada em Vulkan sobre AMD RX 5000/6000.** Medido
  nos mesmos dois trechos: leitura do prompt a 735 contra 373 tokens/s
  (2×), geração −5 %, trecho 23–28 % mais curto; com a flash attention
  ligada e cache f16 a velocidade não mudou, logo a causa é a própria
  flash attention nesta placa. O servidor que o programa sobe, e o
  instalador nessas placas, gravam `OLLAMA_FLASH_ATTENTION=0` e
  `OLLAMA_KV_CACHE_TYPE=f16` (o Ollama só quantiza o cache com a flash
  attention ligada). Valor definido à mão pelo usuário continua
  vencendo; valor que o próprio instalador gravou cede; o desinstalador
  remove qualquer um dos dois. Dois limites dessa regra: um valor
  digitado à mão que coincida com o do instalador é indistinguível
  dele; e um tipo de cache quantizado fixado pelo usuário fica no
  ambiente, mas, com a flash attention desligada, o servidor roda f16 —
  o teto é dimensionado para f16. Em qualquer outra placa um
  `OLLAMA_FLASH_ATTENTION=0` definido à mão é deixado em paz.
- **Registro por trecho** quando um trecho precisou de mais contexto que
  o inicial ou foi dividido por tamanho, e um resumo da etapa com o teto.

### Medido e deixado de fora

- Trechos em paralelo: 0,81× com dois, 1,00× com três — o Ollama fixa a
  família `qwen35` em um pedido. Adiado para uma fase própria, com
  medição própria; o desenho está em `docs/superpowers/specs/`.
- `num_batch` 2048 contra 1024: −2 %.
- ROCm na RX 6700 XT: impossível com o driver AMD atual.

## [1.7.3] — 2026-11-02

Duas constatações da primeira rodada da 1.7.2 num acervo grande, ambas
sobre memória que parecia errada e não estava.

### Corrigido

- **O runner do Ollama não guarda mais um cache de prompts de 8 GB na
  RAM.** O modelo estava inteiro na placa (33 de 33 camadas, 52
  tokens/s), e mesmo assim o `llama-server` segurava 16 GB de memória do
  sistema, o que se leu como modelo transbordando da placa. Oito deles
  eram o cache de prompts que o llama.cpp mantém na RAM por padrão (8192
  MiB), feito para retomar uma conversa anterior — e nunca usado aqui:
  cada janela é um prompt novo, e toda janela começou sem nada
  reaproveitado (o resto é o arquivo do modelo mapeado em memória, que o
  Windows recupera quando precisa). O servidor que este programa sobe, e
  as variáveis de usuário que o instalador grava, agora o desligam
  (`LLAMA_ARG_CACHE_RAM=0` — variável do usuário inteiro, então um
  servidor llama.cpp rodado à mão também fica sem esse cache; o
  desinstalador a remove). Ao trocar
  essas variáveis o instalador também derruba o `llama-server` do próprio
  Ollama, que pode sobreviver ao servidor parado e seguir segurando a
  placa.

### Adicionado

- **"Modelo na placa" entre os sensores da GPU.** O número da VRAM é o
  da área de trabalho inteira (2,4 GB dos 9,2 GB medidos eram o
  navegador, o compositor e outros programas); a linha nova vem do
  próprio Ollama e diz o que importa: "qwen3.5:9b: 100% (5638 / 5638
  MB)".

## [1.7.2] — 2026-11-02

Tudo abaixo saiu de uma rodada de um acervo na 1.7.1, e
cada correção foi conferida contra a regra de que o programa tem de
funcionar em qualquer computador — com qualquer placa de vídeo, ou sem.

### Corrigido

- **O OCR de páginas escaneadas de PDF voltou a funcionar.** A pasta
  privada de dados do Tesseract (`%LOCALAPPDATA%\GClaudeIndexer\tessdata`,
  desde a 1.5.19) tinha os idiomas mas não a pasta `configs/`, e o ocrmypdf
  pede ao Tesseract as saídas `hocr` e `txt` por esses nomes de
  configuração: toda página escaneada falhava com código 15 (alguns PDFs sem
  preparar e outros parciais; as imagens passavam porque o
  pytesseract não pede configuração nenhuma). A pasta agora recebe também
  `configs/` e `tessconfigs/` — copiados da pasta do próprio Tesseract, ou
  os quatro essenciais escritos quando nenhuma fonte os tem — e uma pasta
  já existente é reparada na primeira conversão após atualizar. Uma pasta
  sem eles nunca é tomada como pronta. As páginas afetadas já estão
  marcadas para nova tentativa; a próxima conversão as refaz.
- **"Atualizar" refaz os arquivos cujo OCR falhou.** Quando o projeto já
  tem janelas de classificação, a nova tentativa da própria conversão
  segura esses arquivos (refazê-los sozinhos deixaria as janelas com as
  páginas em branco antigas) e aponta para a atualização do projeto — que
  só olhava bytes alterados. A atualização agora trata um arquivo com OCR
  falho como alterado: as janelas do grupo dele são descartadas e ele
  passa pelo OCR de novo.
- **O OCR de imagens não depende mais de como o programa foi iniciado.** A
  própria conversão põe a pasta do Tesseract no `PATH` deste processo;
  antes só o servidor fazia isso no arranque, e uma conversão iniciada de
  outro jeito falhava toda imagem com "tesseract is not installed".
- **Pausar responde na hora, e existe um Continuar.** Clicar em Pausar
  durante a carga do modelo deixava a tela igual por mais de um minuto (o
  pedido só é lido entre janelas) e, parada a etapa, o botão simplesmente
  sumia. O quadro de progresso agora diz "parando" no instante do clique e
  mostra um botão **Continuar** quando a etapa parou — ele retoma de onde
  parou. Uma pausa que cai no instante entre duas etapas do "Rodar tudo"
  também alcança a cadeia, em vez de ser ignorada.
- **A VRAM total é a da placa instalada.** O Windows guarda a chave de
  driver de uma placa que foi removida; somar todas as chaves dava
  20448 MB para uma placa de 12 GB, e a "VRAM livre" da classificação
  vinha inflada no mesmo tanto. O total agora segue os controladores de
  vídeo realmente presentes, então trocar de placa, ou não ter nenhuma, é
  lido certo a cada arranque. Numa máquina com integrada e dedicada, o
  diagnóstico nomeia a de mais memória, e a VRAM com que ele conta é só a
  dessa placa — o modelo roda numa placa só, e somar as duas chegava a
  recomendar um modelo que a dedicada não comporta.
- **Frequência da CPU em Windows de qualquer idioma.** O contador era
  procurado pelo nome traduzido do conjunto, que só casava em inglês e
  português; num Windows em espanhol ela nunca aparecia. Agora vem de uma
  classe WMI cujo nome não é traduzido.

### Adicionado

- **VRAM usada entre os sensores da placa de vídeo** na tela de Execução
  (pedido do usuário), lida da própria placa — o mesmo número da linha
  sob o gráfico da GPU.

## [1.7.1] — 2026-11-02

### Corrigido

- **A barra de atividade sobrevive ao F5 em toda operação longa.**
  Atualizar, excluir, indexar busca e limpar intermediários passam a
  ocupar o slot do projeto como "importar e gerar", com o mesmo nome do
  botão que as disparou — uma página recarregada no meio retoma a barra
  com o tempo real. Qualquer uma dessas quatro, acionada com o projeto
  ocupado, recebe uma página dizendo qual operação está em andamento
  (HTTP 409) em vez de correr junto — "importar e gerar" e a opção do
  pacote continuam levando ao resultado, como desde a 1.6.0. Na prática
  elas são sempre sequenciais; "excluir projeto" durante uma geração
  apagaria arquivos sendo escritos.
- **O slot nunca fica preso.** Liberado em qualquer saída da operação
  (retorno, exceção, interrupção) e vazio no arranque do servidor — o
  slot vive em memória, então isso protege contra um módulo recarregado
  ou um futuro registro em disco, não contra uma falha vista em uso.
- **O tempo decorrido usa o relógio monotônico.** Acertar o relógio do
  Windows no meio de uma geração não distorce mais a barra.
- Um token malformado no pedido "Ler sensores da CPU e ventoinhas"
  responde 403 em vez de erro interno com traceback no log.
- Só o chip SuperIO da placa-mãe decide a ventoinha da CPU; outro
  sub-hardware com um header chamado "CPU…" em 0 RPM não aparece mais
  como "parada".

## [1.7.0] — 2026-11-02

### Adicionado

- **Rotação das ventoinhas em qualquer máquina que a biblioteca leia.** A
  ventoinha da CPU não é um sensor da CPU: é um header do chip SuperIO da
  placa-mãe, que o leitor de sensores nunca abria. Num Nuvoton NCT6798D, por exemplo, a ventoinha da CPU é o `Fan #2`,
  invisível antes. O helper elevado agora lê o
  SuperIO e escolhe a ventoinha da CPU pelo nome do sensor ou, quando a
  placa não nomeia, pelo header fixo de CPU do chip; header adivinhado em
  0 fica "não medido" em vez de mostrar número errado. Ventoinha da GPU em
  0 RPM aparece como **"parada"** (modo zero-RPM com a placa fria), e um
  valor da CPU que falta só por privilégio diz isso em vez do traço.
- **Botão "Ler sensores da CPU e ventoinhas" na tela Executar.** Pede o
  leitor elevado sob demanda, com uma linha explicando o que o Windows vai
  pedir e por quê; o atalho da área de trabalho continua para quem prefere
  automático. A rota por trás do botão só aceita o pedido com quatro
  guardas independentes — um token gerado a cada abertura do servidor e
  embutido só nessa página, `Sec-Fetch-Site: same-origin`, um cabeçalho
  próprio no pedido e `Host` igual ao do próprio servidor —, e toda página
  passa a recusar ser embutida em frame de outro site (`X-Frame-Options:
  DENY`), de modo que nenhum outro site aberto no navegador consegue fazer
  o prompt aparecer, nem por pedido nem por clique sequestrado. Um segundo
  clique enquanto o Windows ainda pergunta não abre segundo prompt.
- **Barra de atividade em toda operação longa.** Mostra o nome do que está
  rodando e um cronômetro, não um spinner: importar e gerar relatórios,
  salvar e gerar de novo, baixar pacote, limpar intermediários, indexar
  busca, atualizar, excluir. O servidor registra qual operação ocupa o
  projeto e desde quando, e toda página do projeto pergunta ao carregar —
  recarregar no meio da geração retoma a barra com o tempo real, com o
  mesmo nome que tinha no clique. Leitores de tela ouvem o início, cada
  minuto cheio e o fim, não o relógio a cada segundo.

### Corrigido

- O arquivo de status do leitor de sensores de uma sessão anterior
  (`started`, sem leitor vivo) fazia um servidor recém-aberto dizer "o
  leitor não respondeu" antes de qualquer pedido. É apagado no arranque.

## [1.6.1] — 2026-11-01

### Corrigido

- **As "instruções que você já usa" eram copiadas de novo a cada
  geração.** O texto colado no formulário chega com quebras de linha do
  Windows, e o `project_instructions.md` é lido de volta com quebras
  simples; a pergunta "já está no arquivo?" comparava duas grafias do mesmo
  texto e acrescentava mais uma cópia a cada "Salvar e gerar de novo" e a
  cada "Importar e gerar relatórios", até o arquivo ter várias cópias. O
  `merge_managed` agora normaliza as quebras e só
  insere o texto colado quando o arquivo não tem nada fora do bloco
  gerenciado; o que já está fora do bloco é preservado como está. Gerar
  três vezes seguidas produz arquivo idêntico (teste acrescentado).

## [1.6.0] — 2026-11-01

### Alterado

- **O pacote cabe num Projeto do Claude.** Um Projeto no claude.ai aceita
  30 MB por arquivo de conhecimento, e as respostas pioram quando os
  arquivos somam mais do que alguns milhões de tokens (acima de uns 500
  mil ele já passa a usar busca automática nos arquivos). Num acervo
  grande com um espelho completo do Planalto, o `index-<grupo>.md` do grupo
  principal chegava a dezenas de megabytes e a mais de cem mil linhas,
  quase todas de atos federais reconhecidos pelo leitor do Planalto, e o
  `timeline.md` era quase do mesmo tamanho: o mesmo índice reordenado por
  data. Nenhum fatiamento resolve
  isso; o limite é a capacidade do Projeto. Quatro coisas mudam nos
  arquivos gerados, e por isso esta é a 1.6.0:
  - **A legislação do Planalto vai para `legislacao-<grupo>.md`**, com as
    mesmas colunas do índice, gerado sempre mas **fora do pacote por
    padrão**. Legislação são os atos que o leitor do Planalto reconheceu
    e também qualquer página `.htm`/`.html` da mesma pasta desses atos que
    o leitor não leu (retificações, mensagens presidenciais, decretos em
    forma fora do padrão; num acervo grande, só elas quase dobravam o
    índice do pacote): leis, decretos e medidas provisórias o Claude consulta
    melhor direto em planalto.gov.br, e o `project_instructions.md` agora
    diz isso a ele, com a instrução de citar sempre o número e a data do
    ato. O sumário em `index.md` conta documentos do acervo e atos do
    Planalto em separado. A opção **Legislação do Planalto no pacote**
    (formulário de projeto novo e tela de resultado, que gera os
    relatórios de novo) os põe de volta.
  - **A cronologia não repete mais o índice.** Os atos do Planalto ficam
    fora dela (salvo com a opção acima ligada), e um grupo com mais de
    2.000 peças datadas (`timeline_split_items`) ganha o seu
    `timeline-<grupo>.md`, com o `timeline.md` apontando para ele. Esse
    arquivo fica fora do pacote (num acervo grande chega a centenas de
    milhares de tokens, o índice do grupo reordenado por data); a tela de resultado o lista como gerado
    mas não empacotado. A coluna Origem saiu: arquivo e página vão na
    Referência.
  - **Índice de grupo acima de 25 MB sai em partes** `index-<grupo>-1.md`,
    `-2.md`…, quebrando só entre arquivos de origem — as peças de um mesmo
    PDF ficam juntas. O sumário lista as partes com a faixa de folhas de
    cada uma. O mesmo vale para `legislacao-<grupo>.md`.
  - **Linhas mais enxutas.** A coluna Intervalo traz só `(p. N)` quando o
    arquivo é o mesmo da coluna Origem, e a coluna Confiança só aparece
    quando o projeto revisa confiança baixa ou alguma peça está abaixo de
    `high` (era `high` em quase todas as linhas). Uma seção nova do
    `project_instructions.md`, "Colunas dos arquivos", descreve as
    colunas como ficaram.

### Adicionado

- **Orçamento de tokens antes do download.** A tela de resultado lista
  cada arquivo que vai no `.zip` com tamanho e tokens estimados (3
  caracteres por token, estimativa conservadora para o Claude em Markdown
  tabular em português), o total e um aviso em dois níveis: acima de 500
  mil tokens o Projeto depende de busca automática; acima de
  `package_token_limit` (padrão 2.000.000) deixa de responder bem. Arquivo
  acima de 30 MB é marcado, com os dois remédios. Nada é bloqueado — o
  botão de download continua ativo.
- O `HOW_TO_USE.md` do pacote e os três READMEs explicam os limites do
  Projeto e como o programa lida com eles.
- Ainda por fazer, anotado no plano da fase: um servidor MCP local sobre
  o índice de texto integral (`fulltext.py`), para o Claude Desktop
  pesquisar o acervo inteiro sob demanda sem subir arquivo nenhum — a
  resposta definitiva para acervos acima de alguns milhões de tokens.

## [1.5.19] — 2026-11-01

### Corrigido

- **O idioma do OCR é instalado sem precisar de administrador.** O
  Tesseract vem só com inglês, e a pasta de dados dele (`C:\Program
  Files\Tesseract-OCR\tessdata`) exige administrador; o instalador pedia
  elevação ao Windows para copiar o `por.traineddata` para lá e, quando
  essa aprovação não acontecia, o idioma ficava faltando e a tela "Sobre"
  mandava o usuário baixá-lo à mão. Agora os dados de idioma vão para a
  pasta desta máquina (`%LOCALAPPDATA%\GClaudeIndexer\tessdata`), junto
  com os idiomas que o Tesseract já tem, baixados do commit fixado do
  `tessdata_fast` com o SHA-256 conferido, e o GClaude Indexer aponta o
  Tesseract para essa pasta só no próprio processo — nada muda no resto
  da máquina. O instalador faz isso, e o próprio programa também, ao
  abrir, antes do OCR e ao abrir a tela "Sobre": uma máquina cuja
  instalação não conseguiu se corrige sozinha assim que estiver na
  internet. Um Tesseract que já tem o idioma é usado como está.

## [1.5.18] — 2026-11-01

### Corrigido

- **Fechar o navegador libera o projeto para outro computador.** O
  servidor não tem janela e continua rodando depois que a última aba é
  fechada, e renovava a trava do projeto a cada minuto enquanto estivesse
  no ar: o outro computador recebia "em uso, última atividade há 1
  minuto" e nunca conseguia abrir o projeto. Agora a trava só é renovada
  enquanto o projeto está em uso — uma tela dele aberta no navegador (cada
  uma avisa o servidor a cada minuto), um pedido sendo atendido ou uma
  etapa rodando em segundo plano, de modo que uma classificação deixada
  rodando de madrugada com o navegador fechado mantém a trava. Cerca de 5
  minutos depois de fechada a última aba, sem nada rodando, a trava é
  removida; abrir uma tela de novo a retoma, com a verificação de sempre.
  A mensagem mostrada no outro computador agora explica isso.

## [1.5.17] — 2026-11-01

### Alterado

- **Os atos do Planalto ganham o autor pelo texto completo.** A página que
  a classificação vê para no tamanho de página do projeto (4.000
  caracteres por padrão), e uma lei longa é assinada depois desse ponto,
  então muitos atos de um acervo grande ficavam sem autor. Agora
  "Importar e gerar relatórios" lê a assinatura na busca de texto
  completo, que guarda o texto inteiro; os atos do Congresso, que fecham
  com "Congresso Nacional, em …" em vez da linha do Presidente, também
  são lidos, e as emendas constitucionais (assinadas pelas duas Mesas)
  recebem as Mesas como autor. Quase todos os autores que faltavam são
  encontrados em cerca de um minuto, sem classificar nada de novo; os
  poucos que restam são quase todos retificações, que não têm assinatura.
- **Uma grafia por assinatura.** "ERNESTO GEISEL", "Ernesto Geisel" e
  "ernesto geisel", ou "Getulio Vargas" e "Getúlio Vargas", viraram um
  autor só cada no índice.
- **Uma grafia por tipo de documento.** Tipos que diferem só no acento
  ("INDICE"/"ÍNDICE", "SESSAO"/"SESSÃO") passam a usar a forma acentuada
  quando ela é comum o bastante, e a peça sem tipo cujo resumo diz que a
  página está em branco recebe "PÁGINA EM BRANCO". Nomes diferentes nunca
  são juntados: "LEI FEDERAL" continua separado de "LEI".
- **O resumo do hardware não se repete mais no log.** Cada etapa de "Rodar
  tudo até a classificação" diagnosticava a máquina de novo e gravava as
  mesmas duas linhas de quatro a oito vezes por execução; agora a
  repetição dentro de 15 minutos fica de fora. Avisos são sempre gravados.

## [1.5.16] — 2026-11-01

### Alterado

- **O leitor do Planalto reconhece mais atos.** Portarias, resoluções e
  instruções normativas de ministérios (o acervo da Covid-19), atos
  declaratórios do Congresso, alvarás e atos do Império (confirmados pelo
  cabeçalho do próprio site, já que não têm cláusula de promulgação),
  datas escritas sem "de" entre o dia e o mês ("De 23 janeiro DE 1948") e
  títulos precedidos de "(*)". Num acervo grande, a parcela das páginas
  do Planalto lidas assim subiu alguns pontos, e os trechos que ainda
  mandam páginas ao modelo caíram cerca de um terço. Sem cláusula de promulgação, o resumo
  é a linha logo abaixo do título, e os links de navegação do site ("Não
  remover", "Down", "Up") não entram mais nele.

## [1.5.15] — 2026-10-31

### Corrigido

- **Um trecho que o modelo recusa é dividido, em vez de ficar pendente
  para sempre.** Quando o Ollama responde com erro sobre o próprio pedido
  ("prediction aborted, token repeat limit reached"), o trecho é
  classificado em metades até isolar a página ilegível, que entra no
  índice pelo nome do arquivo. Antes isso contava como Ollama fora do ar:
  tentativas de religar, três reenvios iguais e o trecho pendente de novo
  a cada execução.
- **Páginas com os bytes crus de um arquivo binário são lidas como
  vazias.** Arquivos zip, de fonte, de áudio e de CAD convertidos antes da
  1.5.9 guardavam uma página de caracteres de controle, que fazia o modelo
  entrar em repetição.
- A mensagem "o modelo local parou de responder" não diz mais que a
  execução vai passar para o motor Regras; com placa de vídeo isso nunca
  acontece.

## [1.5.14] — 2026-10-31

### Adicionado

- **A legislação federal do site do Planalto é lida pela própria
  estrutura, não pelo modelo.** Todo ato traz as mesmas partes: título com
  tipo, número e data, a ementa oficial, a cláusula de promulgação, a
  linha de local e data e as assinaturas. Tipo, número, data, quem assina
  e resumo (a ementa oficial, mais a nota de revogação quando houver) saem
  delas ao pé da letra. Num acervo grande, a imensa maioria das páginas
  do Planalto é lida assim em segundos, e a fila do modelo cai de muitos
  milhares de trechos (dias numa placa de notebook de 6 GB) para algumas
  centenas. Páginas fora do formato continuam indo ao
  modelo. A busca não muda: o texto completo de toda página é indexado,
  seja quem for que a classifique. Vale para o modelo local e para o motor
  Regras; um trecho só de atos não espera mais o Ollama.

### Alterado

- **O instalador leva o Ollama à versão mais nova** a cada instalação,
  parando antes o servidor em execução (um `ollama.exe` aberto fazia a
  atualização falhar). Um Ollama antigo recusa formatos novos de modelo.
- **O modelo local automático segue a placa de vídeo.** O instalador e
  o programa leem a VRAM da placa: 8 GB ou mais usa `qwen3.5:9b`, 6 GB ou
  menos mantém `qwen3.5:4b`. Uma máquina atualizada de versão anterior
  sem o modelo de 9B baixado segue usando o de 4B.
- Em placas de 6 GB o modelo continua `qwen3.5:4b`. Comparado no mesmo conjunto de
  trechos, a variante `-mtp` deu as mesmas respostas e não foi mais
  rápida (162 s contra 145 s em quatro trechos); `bonsai-2:9b` e
  `ornith-1.5:9b` foram mais lentos (2x e 9x) e cada um falhou um trecho; `qwen3-vl:8b` não cabe numa placa de 6 GB e
  estourou o tempo de carga.

## [1.5.13] — 2026-10-31

### Corrigido

- **A rotação das ventoinhas nunca aparecia no programa instalado.** O
  leitor de sensores elevado roda de uma cópia local de alguns módulos, e
  o leitor térmico da Dell não estava entre eles: a importação falhava ali
  sem aviso. Um teste agora confere que a cópia leva todo módulo que o
  leitor importa.

## [1.5.12] — 2026-10-31

### Corrigido

- **Com placa de vídeo, a classificação nunca cai para o motor Regras.**
  Uma janela lenta estourou o tempo limite, foi reenviada enquanto o Ollama
  ainda trabalhava nela, e a execução entregou os milhares de janelas
  restantes ao motor Regras em minutos, sem nenhuma palavra no log (o resumo
  ainda dizia "modelo local"). Agora, com placa de vídeo, um modelo que
  para de responder é religado e esperado, e a execução continua do mesmo
  trecho. Um trecho que falha três vezes enquanto o modelo responde os
  outros fica pendente para a próxima execução. Sem placa de vídeo o motor
  Regras ainda cobre a falta, mas os trechos dele ficam marcados e voltam
  ao modelo na próxima execução.
- **Os trechos que o motor Regras classificou só porque o modelo estava
  fora do ar voltam ao modelo** no início da próxima classificação; os que
  o modelo já fez são mantidos.
- **Tempo limite de uma resposta do modelo de 120 s para 300 s.** Uma
  janela de 16 páginas responde ~1.800 tokens; numa placa de notebook de
  6 GB quente isso levou 40 s em média e passou de 120 s nas pesadas. Um
  servidor que ainda responde não é mais religado depois de estourar o
  tempo: o mesmo trecho é enviado de novo.
- **O que um servidor do Ollama iniciado pelo programa imprime fica
  guardado** em `%LOCALAPPDATA%\GClaudeIndexer\ollama-serve.log`, para que
  uma queda possa ser explicada depois.
- **"Extração por página" ficava pendente sem nada a extrair.** Com todos
  os arquivos já extraídos, a etapa se dava por pausada e pulava o índice
  da busca de texto completo, e nenhum arquivo do projeto chegava a ser
  indexado para a busca.
- **A classificação mostra o tempo estimado depois de cinco trechos**, em
  vez de depois de 0,5% deles (mais de meia hora numa execução grande).
- Inclui a 1.5.11 (rotação das ventoinhas depois de reiniciar o Windows),
  que não teve instalador próprio.

## [1.5.11] — 2026-10-31

### Corrigido

- **A rotação das ventoinhas ficava vazia depois de reiniciar o Windows.**
  O leitor de sensores elevado sobe antes de o serviço térmico da Dell
  estar pronto, e a primeira leitura com falha desligava as ventoinhas a
  sessão inteira. Agora ele tenta de novo a cada 30 segundos e só desiste
  depois de dez falhas seguidas (máquina sem a interface da Dell).

## [1.5.10] — 2026-10-31

### Rotação das ventoinhas em notebooks Dell; driver PawnIO para os sensores da CPU

#### Adicionado

- **Rotação das ventoinhas da CPU e da GPU em notebooks gamer da Dell**
  (série G, Alienware), lida pela interface térmica da própria Dell (a que
  o Alienware Command Center usa). Num notebook as ventoinhas pertencem ao
  controlador embarcado: nem a biblioteca de sensores nem o driver de
  vídeo as enxergam (o `nvidia-smi` informa `N/A`). A mesma interface dá a
  temperatura da CPU, que aparece mesmo sem o driver PawnIO. Só operações
  de leitura são usadas; o controle das ventoinhas nunca é tocado. Depende
  do atalho do sensor de CPU (o leitor de sensores elevado); nas outras
  máquinas nada muda.
- **O instalador oferece o driver PawnIO, já marcado.** A biblioteca de
  sensores lê a temperatura e a potência da CPU por ele; sem ele as duas
  ficavam vazias mesmo com o atalho do sensor de CPU. É um driver de kernel
  de terceiros (https://pawnio.eu/), instalado pelo winget, e o Windows
  pede administrador para instalá-lo. Pode ser desmarcado; todo o resto
  funciona sem ele.

## [1.5.9] — 2026-10-31

### A busca de texto completo não trava mais a extração; tela de execução ágil

Os tempos abaixo foram medidos numa cópia local do banco de um projeto grande
(bem mais de cem mil páginas). Com o banco no Google Drive eles são
maiores, mas não em ordens de grandeza.

#### Corrigido

- **Incluir os arquivos na busca de texto completo ficava mais lento a
  cada arquivo.** Antes de gravar um arquivo, os trechos antigos dele eram
  apagados por uma coluna que a tabela de busca não indexa, então cada
  arquivo lia a tabela inteira — até os novos, que não tinham nada a
  apagar. Num acervo grande a extração chegava a 100% e ficava "rodando"
  pelo que seriam mais de 100 horas. Agora os trechos de cada arquivo têm
  uma faixa registrada e são removidos por ela, e os textos são lidos em
  paralelo: ~0,35 arquivo/s antes, ~800–1.000 arquivos HTML/s agora.
- **A etapa de extração ficava "concluída" com a busca ainda em
  construção.** Uma pausa nessa fase deixava a busca incompleta e "Executar
  próxima etapa" seguia adiante. Agora a etapa só termina quando todos os
  arquivos estão na busca, e a barra de progresso mostra essa fase à parte
  em vez de ficar parada em 100%.
- **A tela de execução levava cerca de 90 segundos para abrir** durante um
  processamento grande, e a tabela de etapas o mesmo para se atualizar. O
  resumo de qualidade lia o texto de todas as páginas só para contá-las, a
  cada dois segundos. Agora conta sem ler o texto, calcula a cobertura numa
  passada só e é recalculado apenas quando algo muda: 5,6 s → 0,2 s
  localmente.
- **O log ao vivo se enchia de "O banco de dados do projeto está ocupado"
  e parava de atualizar.** Esse aviso é feito para uma página inteira, e o
  log o colava na lista sempre que o banco estava ocupado. Agora o log pula
  aquele ciclo e tenta de novo, como o resto da tela.
- **Peças classificadas se perdiam quando o resumo tinha o caractere
  U+0085.** Comum em HTML lido como Latin-1, ele partia a linha da peça no
  `raw_items.jsonl` em duas, e a importação descartava as duas metades como
  corrompidas.
- **A revisão retomada depois de uma pausa reenviava ao modelo todas as
  janelas de baixa confiança**, inclusive as que já tinha revisado. Agora
  elas são puladas.

#### Alterado

- **A classificação grava em lotes** (motores de regras e local): um
  commit a cada dois segundos em vez de um por janela e mais um por evento
  registrado. Com o banco no Google Drive cada commit custa segundos e
  bloqueia a tela. A etapa de janelas lê as páginas sem o texto quando não
  grava os arquivos das janelas, confere as janelas existentes com uma
  consulta por grupo e lista a pasta das janelas uma vez só. Localmente, no
  mesmo banco: a etapa de janelas leva segundos e a classificação por
  regras cerca de um minuto.
- **As etapas gravam com menos frequência**: a cada dois segundos ou 500
  operações (eram um segundo ou 200), então as telas encontram o banco
  livre mais vezes.
- **A conversão com OCR começa pelo maior arquivo.** Na ordem dos caminhos
  um PDF de centenas de páginas podia começar por último e rodar sozinho
  por minutos depois que todos os outros já tinham terminado.
- **Arquivos binários não são mais lidos como texto.** Com "todas as
  extensões" marcado, um arquivo sem extrator cujos primeiros bytes têm um
  NUL (zip, áudio, fonte, desenho CAD) fica no índice pelo nome, sem texto,
  em vez de uma página de caracteres de controle que ia para a busca e para
  os resumos. Vale para os arquivos convertidos daqui em diante; os já
  convertidos mudam quando reprocessados (atualização do projeto).
- **Um arquivo cujo texto não pode ser lido para a busca** é registrado no
  log e gravado sem trechos, para a etapa poder terminar, em vez de ser
  tentado de novo a cada execução. Reprocessar o arquivo (atualização do
  projeto) o traz de volta.
- **O instalador já vem com o download do modelo de classificação e o
  atalho do sensor de CPU marcados.** Os dois continuam podendo ser
  desmarcados; numa atualização o modelo já baixado não é baixado de novo.

## [1.5.8] — 2026-10-31

### Processamento muito mais rápido no Google Drive; a atualização encerra a versão antiga

#### Alterado

- **Os arquivos intermediários ficam no disco local.** Os PDFs com OCR, o
  texto extraído de cada arquivo e as fatias de PDF (`converted/`,
  `blocks/`) agora vão para `%LOCALAPPDATA%\GClaudeIndexer\work\`, não para
  a pasta de saída. No Google Drive cada arquivo pequeno novo levava ~800 ms
  para ser criado, contra 0,3 ms no disco local, e a conversão de um acervo
  grande ficava esperando o Drive com o processador parado. Nada do que se
  usa do projeto depois precisa desses arquivos: as páginas e a busca de
  texto completo estão no `project.db`, e os índices e as janelas continuam
  na pasta de saída. Projetos convertidos antes continuam lendo as cópias
  que já estão lá. Em outro computador, um arquivo cuja cópia não existe
  volta para a conversão em vez de dar falha.
- **A conversão roda em duas filas.** Arquivos que não precisam de OCR
  (HTML, texto, DOCX, e-mail) passam o tempo esperando o disco, então
  ganham um grupo bem maior de processos (até 4 por núcleo físico no modo
  "máximo"). O OCR mantém um processo por núcleo. Medido em arquivos HTML
  do Drive: poucos arquivos por segundo antes, centenas por segundo agora.
- **Etapa de janelas:** os `.txt` das janelas só são gravados para o motor
  Claude Code, o único que os lê, em paralelo; os que faltarem são gravados
  quando esse motor for escolhido depois. Um commit por grupo em vez de um
  por janela.
- **A indexação da busca de texto completo** grava em lotes em vez de um
  commit por arquivo.

#### Corrigido

- **A classificação relia o grupo inteiro a cada janela.** Num grupo de
  mais de cem mil páginas, isso dava centenas de megabytes lidos por
  janela, para milhares de janelas. Agora cada janela carrega só as próprias páginas, e
  a coluna do grupo ganhou índice. Vale para os motores de regras, local e
  de revisão.
- **Instalar uma atualização deixava a versão antiga rodando.** Ao abrir o
  programa de novo, o servidor antigo ainda ocupava a porta e a versão
  antiga aparecia. O instalador (e o desinstalador) agora encerra os
  processos do programa antes, inclusive o servidor que o lançador do
  ambiente virtual inicia como processo filho. Abrir o programa também
  substitui um servidor de outra versão que ainda esteja rodando, e o
  atalho espera o servidor responder antes de abrir o navegador.

## [1.5.7] — 2026-10-31

### O OCR não falha mais em PDF com cores incomuns, e o OCR que falhou é refeito

#### Corrigido

- **O OCR falhava em PDF com espaço de cor incomum** (comum em PDF de
  gráfica), com `ColorConversionNeededError`. O reconhecimento de texto em
  si funcionava; o que falhava era a conversão do resultado para PDF/A, o
  formato de arquivamento, e o OCR do arquivo inteiro era descartado junto.
  A cópia com OCR só é lida para extrair o texto, então agora ela é um PDF
  comum (`--output-type pdf`). Também fica um pouco mais rápido.
- **Um arquivo cujo OCR falhou ficava assim para sempre.** Um PDF com texto
  nativo mantinha as páginas escaneadas em branco, e um PDF todo escaneado
  continuava com falha; rodar as etapas de novo não revisitava nenhum dos
  dois. Agora o arquivo cujo OCR falhou fica marcado e volta à fila no
  começo da conversão seguinte, até o OCR dar certo. Só as falhas de OCR:
  um arquivo corrompido ou protegido por senha não é tentado de novo. A
  tela de Execução mostra a conversão como pendente enquanto houver arquivo
  nessa situação.
- **Os arquivos que falharam antes desta versão são recuperados.** Na
  primeira vez que a 1.5.7 abre um projeto, ela marca os arquivos cujo OCR
  falhou antes, encontrados pelo erro guardado no arquivo e pelos avisos do
  log, e a conversão seguinte os refaz. Um arquivo que já está nas janelas
  de classificação não volta, porque as janelas ficariam desatualizadas; o
  log diz o nome dele.

## [1.5.6] — 2026-10-31

### O modo econômico e a varredura também não travam mais; atualizações de segurança

#### Corrigido

- **O modo econômico (paralelismo 1) ainda podia travar num arquivo do
  Google Drive.** Um arquivo por vez rodava na própria thread da etapa,
  que nada conseguia destravar. Agora ele roda sob a mesma proteção do
  caminho paralelo, numa thread que a etapa abandona quando o arquivo
  passa do prazo. O OCR continua rodando no próprio processo do programa,
  como antes.
- **A varredura podia travar num arquivo ou numa pasta que o Drive nunca
  responde.** Ler o tamanho de cada arquivo e calcular o hash agora têm
  prazo. Um arquivo que passa do prazo fica de fora desta varredura, com
  um aviso no log, e é conferido de novo na próxima. Três seguidos
  interrompem a varredura com uma mensagem clara. Uma pasta cuja
  listagem nunca responde interrompe a varredura em vez de ser pulada,
  porque uma pasta pulada pareceria ter tido os arquivos removidos.
- **A verificação de atualização nunca lê uma pasta travada como
  "arquivos removidos".** Ela informa a pasta de origem como
  indisponível, igual a um drive desconectado, e não oferece apagar nada.

#### Segurança

- **Pillow 13.0.0** (era 12.3.0), que corrige os 41 alertas do Dependabot
  contra a 12.x, entre eles estouros de memória ao decodificar imagens
  JPEG, TIFF e FlashPix e injeção de argumento na chamada ao Ghostscript.
  O programa abre imagens de terceiros para o OCR, então esses alertas
  eram alcançáveis.
- **Starlette 1.3.1** (era 0.52.1), que corrige o roubo de credencial NTLM
  por caminho UNC no `StaticFiles` do Windows, limites de formulário que
  eram ignorados e a validação do cabeçalho Host. Exigiu a **FastAPI
  0.162.0** (era 0.128.8), a primeira série que aceita o Starlette 1.x.

## [1.5.5] — 2026-10-31

### O processamento não trava mais, seja qual for o tamanho do acervo

#### Corrigido

- **A conversão podia travar de vez, e a tela de Execução passava a
  mostrar "Internal Server Error" a cada dois segundos.** Numa pasta
  muito grande no Google Drive, o Drive parou de responder a algumas
  aberturas de arquivo. Os processos auxiliares esperaram por elas para
  sempre, e a etapa, que esperava os auxiliares antes de sair, esperou
  junto, mantendo o banco de dados travado. Agora cada arquivo tem um
  prazo que cresce com o tamanho (10 minutos mais 2 por MB). Um auxiliar
  que passa do prazo é encerrado e reiniciado, e o trabalho continua. Um
  arquivo que trava duas vezes enquanto os outros andam é marcado como
  falha, com "tempo esgotado". Quando nada anda (o Drive ou o disco
  travou, não um arquivo), a etapa para com uma mensagem clara e deixa
  todos os arquivos para a próxima execução.
- **Um banco de dados ocupado derrubava a etapa em vez de esperar.** Um
  instante de `database is locked` encerrava a etapa com a transação
  aberta. Agora a etapa grava em lotes e, com o banco ocupado, desfaz o
  lote e o aplica de novo logo depois, por até dez minutos.
- **Um banco ocupado aparecia na tela como "Internal Server Error".** A
  tela de Execução mantém o que já mostra e pergunta de novo no ciclo
  seguinte. Uma página inteira explica que o banco está ocupado e que nada
  se perdeu.
- **Um processo auxiliar que morria (falta de memória) encerrava a
  etapa.** Agora o conjunto de auxiliares é refeito e o trabalho continua.
  Arquivos presos em duas quedas ficam para a próxima execução, como
  antes.

#### Alterado

- **Conversão e extração ficaram muito mais rápidas numa pasta do Google
  Drive.** O modo de journal do banco passou de `DELETE` para `TRUNCATE`:
  um commit numa pasta do Drive caiu de cerca de 0,3 s para menos de
  0,01 s, porque o Drive não precisa mais criar e apagar o arquivo de
  journal a cada vez. Continua sendo um journal de reversão, com a mesma
  segurança, nunca WAL. As etapas também gravam em lotes (pelo menos uma
  vez por segundo) em vez de uma vez por arquivo.
- **As consultas da tela esperam no máximo 5 segundos por um banco
  ocupado**, em vez de 30.

## [1.5.4] — 2026-10-31

### A segunda varredura não relê todos os arquivos, e a barra anda

#### Corrigido

- **"Rodar tudo até a classificação" passava horas varrendo de novo uma
  pasta já varrida.** O botão sempre começa pela varredura, e a varredura
  recalculava o hash de cada arquivo só para descobrir que nada tinha
  mudado — numa pasta muito grande no Google Drive, isso
  significava reabrir os arquivos um por um. Agora, um arquivo com o mesmo
  tamanho e a mesma data de modificação registrados no inventário é
  considerado sem mudança, sem ler o conteúdo — a mesma regra que a
  verificação de atualização já seguia. O que mudou continua sendo
  confirmado pelo hash.
- **A barra de progresso de uma segunda varredura ficava em "0 / N" até o
  fim.** Ela contava linhas novas no inventário, e a varredura de uma
  pasta sem mudanças não acrescenta nenhuma. Agora a barra acompanha os
  arquivos que a varredura já conferiu.
- **Um tamanho errado gravado para um arquivo fazia ele ser relido em toda
  varredura.** O Google Drive pode informar 16.384 bytes logo depois de
  gravar um arquivo; quando o conteúdo se mostra igual, o tamanho real
  passa a ser gravado.

## [1.5.3] — 2026-10-30

### Os botões de execução respondem na hora em pastas grandes, com contador ao vivo

#### Corrigido

- **"Rodar etapa seguinte" e "Rodar tudo até a classificação" pareciam
  mortos numa pasta de origem grande.** Antes de registrar a varredura, a
  requisição percorria a pasta inteira duas vezes para dimensionar a barra
  de progresso — minutos numa pasta muito grande no Google Drive.
  Enquanto isso o primeiro botão ficava pendurado e a tela dizia "Nenhuma
  etapa rodando". Agora a tarefa é registrada na hora e mede o trabalho em
  segundo plano.
- **Cada clique a mais abria outra varredura no mesmo banco.** A checagem
  de "já está rodando" não enxergava uma tarefa que ainda estava sendo
  medida. Checagem e registro agora acontecem sob a mesma trava: um
  segundo clique devolve a tarefa que já roda.
- **A barra da varredura podia parar antes dos 100%.** O total contava
  `desktop.ini` e outros arquivos de sistema que a varredura nunca
  registra; a contagem agora usa o mesmo critério da varredura.

#### Alterado

- **Enquanto a pasta de origem é percorrida, a tela Execução mostra um
  contador ao vivo** ("Contando os arquivos da pasta de origem: N
  arquivo(s) encontrado(s)"), o tempo decorrido, uma barra em movimento e o
  botão de pausa, para que uma caminhada longa nunca pareça travada.
- **A pasta de origem é percorrida uma vez por varredura, não três.** A
  contagem entrega a lista à varredura, e a caminhada usa `os.scandir`, que
  no Windows lê o tamanho de cada arquivo da própria listagem da pasta em
  vez de perguntar arquivo por arquivo.
- **Arquivos `.ini` nunca são indexados**, nem com "todas as extensões": o
  Windows e o Google Drive gravam um em cada pasta, e nenhum é documento.

## [1.5.2] — 2026-10-30

### OCR página a página: folhas escaneadas dentro de PDFs nativos não se perdem mais

#### Corrigido

- **Páginas escaneadas dentro de um PDF com texto nativo chegavam em branco
  ao índice.** O OCR era decidido pela média do arquivo — menos de 100
  caracteres por página —, então um PDF nativo com algumas folhas
  escaneadas no meio (uma ata assinada, um anexo) passava na média e essas
  folhas ficavam sem texto. Agora a decisão é por página: as páginas com
  menos de 100 caracteres que têm imagem ou desenho vetorial vão para
  `ocrmypdf --force-ocr --pages …`, e as outras passam intocadas.
  `--force-ocr` em vez de `--skip-text` porque uma folha escaneada com um
  carimbo ou um "fl. 2" em texto era pulada. Num acervo de algumas centenas
  de PDFs, dezenas se revelaram mistos; as folhas escaneadas deles
  passaram de poucas dezenas de caracteres para milhares cada, e as
  páginas nativas saíram idênticas.
- **PDFs assinados digitalmente recebem OCR**
  (`--invalidate-digital-signatures`). Só a cópia interna, na pasta de
  saída, perde a assinatura; o original nunca é tocado.

#### Alterado

- Página com pouco texto e nada desenhado (verso em branco, divisória de
  capítulo) não manda um livro nativo para o OCR.
- Se o OCR falhar num PDF que também tem texto nativo, o arquivo segue com
  esse texto e um aviso diz quantas páginas ficaram em branco; um PDF todo
  escaneado continua falhando, como antes. O log diz quantas páginas, de
  quantas, receberam OCR.
- Projetos já indexados mantêm a conversão: um PDF misto só é relido quando
  muda ou é reprocessado.

## [1.5.1] — 2026-10-28

### Acervos mistos: uma peça por documento, configuração proposta pela pasta, toda palavra localizável

#### Corrigido

- **O motor de regras juntava leis inteiras numa peça só.** Num acervo de
  uma lei por arquivo HTML, toda página começa por "Presidência da
  República", nenhum marcador de tipo casava com "LEI Nº" e trocar de
  arquivo não era sinal — leis seguidas viravam uma peça. Agora um arquivo
  de documento inteiro (HTML, DOCX, XLSX, PPTX, TXT, MD, e-mail… tudo
  menos PDF e imagem) sempre começa a própria peça, nos motores de
  regras, local e `claude_code`. Páginas de PDF e sequências de imagens
  escaneadas continuam podendo formar uma peça, como antes.
- **Epígrafes legislativas viram tipo** (`heading_types` em
  `classification_rules.json`): EMENDA CONSTITUCIONAL, LEI, LEI
  COMPLEMENTAR, DECRETO-LEI, DECRETO, MEDIDA PROVISÓRIA, PORTARIA,
  RESOLUÇÃO, INSTRUÇÃO NORMATIVA, SÚMULA, ACÓRDÃO e outras — só no começo
  de linha, nos primeiros 600 caracteres, para que uma lei citada no meio
  do texto não vire o tipo do documento. Datas como "1º DE JANEIRO DE
  2023" são lidas. Medido em 354 leis do Planalto: 354 peças, 97% com
  tipo, todas com data.
- **Acervos "biblioteca" com vários arquivos num grupo fundiam as peças.**
  Ali a referência recomeça em "p. 1" a cada arquivo, e a posição da
  página no grupo saía desse número — toda peça de todo arquivo tinha
  posição 1 e a consolidação as fundia. A posição agora é o lugar da
  página no grupo (`group_page_positions`), usado na importação, no mapa
  de página física do índice, no relatório de lacunas e na cobertura da
  qualidade. As janelas do `claude_code` mostram essa posição como `[#N]`
  no cabeçalho de cada página, e o `CLAUDE.md` manda usá-la em
  `order_start` / `order_end`. Acervos "processo" não eram afetados.
- **Um decreto de 1962 era lido como báltico (cp1257).** Quando a
  detecção estatística acha Windows-1252 tão plausível quanto o melhor
  palpite, fica Windows-1252 — a codificação de quase todo texto
  brasileiro mais antigo.

#### Adicionado

- **Configuração proposta a partir da pasta de origem.** Ao escolher a
  pasta de origem de um projeto novo, o programa a examina — até 6
  segundos, numa amostra de PDFs e arquivos de texto — e propõe páginas
  por bloco, páginas por janela, sobreposição, caracteres por página e
  idioma do OCR, cada um com o motivo, além da composição da pasta.
  "Aplicar" preenche o formulário; nada muda sem isso. Idiomas de OCR só
  são propostos se o Tesseract os tiver instalados.
- **Busca de texto completo** ("Buscar no acervo", nas telas de execução e
  de resultado). A classificação lê só os primeiros "caracteres por
  página" de cada página; a busca guarda o texto inteiro de todo arquivo,
  sem corte, numa tabela SQLite FTS5 dentro do projeto. Os resultados
  dizem onde está o texto — a página do PDF (`f. 12` / `p. 5`) ou, num
  documento inteiro, o artigo ou título e a linha ("p. 1 · Art. 40") —,
  destacam as palavras achadas, marcam o que estava tachado no original e
  abrem o arquivo original. Acentos e maiúsculas não importam; "aspas"
  para uma frase, `*` para o começo de palavra. A indexação roda no fim
  da extração e retoma de onde parou; arquivos extraídos por uma versão
  anterior entram com "Incluir os que faltam".

#### Observações

- Um projeto "biblioteca" com vários arquivos por grupo já classificado
  pela 1.5.0 ou anterior tem peças fundidas: crie-o de novo.
- A busca cobre os arquivos extraídos daqui em diante; num projeto que já
  existe, abra "Buscar no acervo" e use "Incluir os que faltam".

## [1.5.0] — 2026-10-28

### Páginas web lidas como texto, com o tachado preservado; toda codificação lida certo

#### Adicionado

- **HTML é lido, não despejado.** `.htm`/`.html` entravam no índice como
  marcação crua: `<head>`, CSS e JavaScript ocupavam os caracteres por
  página antes do primeiro artigo. Agora viram texto limpo
  (`html_text.py`): sem tags, um bloco por linha, títulos como `#`, itens
  de lista como `- `, células de tabela unidas por ` | `, `N<sup>o</sup>`
  como `Nº`. Marcação dos anos 1990, sem fechamento ou mal aninhada, é
  tolerada; se o leitor ainda falhar, o texto é recuperado tirando as tags
  — nunca falhando o arquivo. Medido no acervo do Planalto: 0,4 s para o
  Código de Processo Civil de 1,7 MB, ~22 ms por lei em média.
- **Tachado preservado como `~~texto~~`.** No site do Planalto, artigo,
  parágrafo ou inciso riscado é dispositivo revogado, suprimido ou
  substituído, mantido na página ao lado do texto em vigor. Formas
  reconhecidas: `<strike>`, `<s>`, `<del>`, `text-decoration: line-through`
  no `style` e classes CSS declaradas com ele — e trechos riscados em DOCX,
  PPTX e XLSX. O motor de regras ignora o texto tachado ao procurar tipo,
  data, autor e resumo; o prompt do motor local (só quando a janela tem a
  marca), o `CLAUDE.md` do motor `claude_code` e o
  `project_instructions.md` (só quando o acervo tem a marca) explicam o
  que ela significa, nos três idiomas.
- **Mais formatos web:** `.xhtml`, `.xht`, `.shtml` e `.mht`/`.mhtml`
  (página salva pelo navegador num arquivo só). Um `.xml` cuja raiz é
  `<html>` passa pelo leitor de HTML; outros XML e JSON ficam literais.

#### Corrigido

- **A codificação é descoberta, nunca suposta.** Todo arquivo de texto era
  lido como UTF-8 com `errors="replace"`, e um arquivo em Windows-1252 — a
  legislação inteira do Planalto, a maior parte dos documentos brasileiros
  mais antigos — saía como "Presid�ncia da Rep�blica". O
  `text_decoding.py` agora tenta, nesta ordem: a marca de ordem de bytes
  (BOM), a codificação declarada (`<meta>` do HTML, declaração XML,
  `charset` do MIME) se os bytes concordarem, UTF-8, detecção estatística
  (`charset-normalizer`, agora fixado) e, por fim, Windows-1252/Latin-1.
  Os rótulos `iso-8859-1` e `ascii` são lidos como Windows-1252, como
  fazem os navegadores. Nunca levanta exceção. Vale para `.txt`, `.md`,
  `.log`, `.csv`, `.xml`, `.json`, páginas web, corpo de e-mail e a
  categoria TODOS.
- **E-mail com rótulo de charset desconhecido não falha mais o arquivo**,
  e o corpo de e-mail só em HTML vira texto em vez de ficar como marcação.
  `.msg` sem corpo em texto simples usa o corpo HTML.
- **DOCX não perde mais o texto dos hiperlinks** (remissões a outras leis,
  por exemplo).

#### Observações

- Cada arquivo HTML continua sendo uma página, cortada em "Caracteres por
  página" para a classificação; o texto limpo completo fica em
  `converted/`. Os primeiros 3000 caracteres de uma lei trazem epígrafe,
  ementa e primeiros artigos.
- Arquivos convertidos por versão anterior mantêm o texto antigo: para
  reler um acervo, crie o projeto de novo (ou exclua com "tudo" e recrie).
- Tachado em PDF não é detectado — é uma linha desenhada, não um atributo
  do texto.

## [1.4.0] — 2026-10-16

### Suas instruções preservadas, remoções sem perda, um manual de verdade, mais seguro por padrão

#### Adicionado

- **As instruções complementam as suas em vez de substituí-las.**
  `project_instructions.md` e o `CLAUDE.md` da pasta de saída eram
  reescritos do zero a cada execução: um `CLAUDE.md` que você já tinha
  nessa pasta, ou uma regra acrescentada ao arquivo gerado, sumia na
  atualização seguinte. O que o sistema escreve agora fica entre
  `<!-- GCLAUDE-INDEXER:BEGIN … -->` e `<!-- GCLAUDE-INDEXER:END -->`;
  tudo fora das marcas é seu e é mantido. Na primeira vez que um arquivo
  sem marcas é tocado, o original é guardado como `<nome>.bak`. Campo novo
  **"Instruções que você já usa"** no Novo projeto, que leva as instruções
  atuais do seu Project para o topo do arquivo. O guia do pacote agora diz
  para colar o arquivo inteiro.
- **Manual completo dentro do programa** (menu **Manual**, `/help`), em
  português, inglês e espanhol: começo rápido, cada campo, comparação dos
  motores (velocidade, qualidade, requisitos), as etapas, os arquivos
  gerados, uso com o Claude, atualização, uso em equipe, dicas e problemas
  comuns. A Ajuda de cada tela leva à sua seção.
- **Quatro temas novos** — Aurora, Toga, Grafite e Oceano — e uma camada
  de movimento para todos os temas (`motion.css`): troca de tela suave,
  entrada escalonada, cartões que sobem, botões que afundam, diálogos
  animados, brilho na barra de progresso. Só `transform`/`opacity`
  animam, e tudo se desliga quando o Windows pede menos movimento.

#### Alterado

- **O log ao vivo fala a língua de quem usa.** 57 mensagens reescritas nos
  três idiomas, dizendo o que aconteceu e o que fazer; detalhes técnicos
  só entre parênteses no fim. A coluna de etapa mostra "Atualização" em vez
  de `update`.
- **Remover um documento do acervo** agora: indexa uma cópia idêntica que
  continua na pasta (antes o conteúdo sumia em silêncio), registra a
  remoção uma vez só e a esquece quando o arquivo volta, apaga a cópia com
  OCR em `converted/`, apaga os índices de grupos que deixaram de existir
  (iam para o Claude), separa grupos cujos nomes seguros colidiam e avisa
  — na tela do plano e no log — quais documentos têm as folhas (`f. N`)
  renumeradas.
- **Excluir um projeto "com os arquivos"** apaga só o que o programa criou
  (banco, cópias convertidas, janelas, log, relatórios), mantém seus
  arquivos na pasta de saída, tira só o bloco gerado dos arquivos de
  instruções e remove a pasta apenas se ela ficar vazia. Sem `project.db`
  na pasta, nada é apagado.
- **Um projeto recém-criado** não mostra mais "a pasta de origem mudou: N
  novos" antes da primeira execução.
- **Tela Resultado** mostra o nome traduzido do motor, e o modelo só quando
  o motor local usou um; relatórios muito grandes aparecem em prévia, não
  inteiros.
- **FastAPI 0.128.8 com Starlette 0.52.1 fixado**, fora da faixa afetada
  pelos CVE-2024-47874 e CVE-2025-62727.

#### Corrigido

- As barras de confiança da tela Resultado estavam sem cor desde a fase
  14: o template usava um nome de classe que a folha de estilo não define.

#### Segurança

- **Só as telas do programa dão ordens a ele.** O servidor confere o
  `Host` (DNS rebinding), recusa pedidos que o navegador marca como vindos
  de outro site (exceto um link simples sem parâmetros) e recusa POST com
  `Origin` estranho (CSRF). Isso também fecha o vazamento de hash NTLM que
  um site podia provocar fazendo o programa olhar um caminho
  `\\atacante\pasta`. Caminhos UNC digitados nos formulários do próprio
  programa continuam funcionando.
- O `CLAUDE.md` do motor `claude_code` avisa que o texto das janelas é dado
  não confiável e que só se pode acrescentar linhas a `raw_items.jsonl`.
- As chamadas ao Ollama local nunca passam por proxy do sistema: numa rede
  corporativa, o texto dos documentos não sai da máquina.
- Sem redirecionamento aberto pelo `Referer`; o nome do pacote vai no
  formato RFC 5987.

#### Desempenho

- A verificação de "código mudou desde que o servidor subiu" usa `stat` em
  vez de reler e calcular o hash do pacote a cada tela (várias vezes a cada
  dois segundos na tela Execução).
- O log ao vivo lê só as linhas novas, em SQL.
- Rotas bloqueantes (seletor de pasta, atualização, exclusão, criação) não
  congelam mais o servidor.
- Índices em `window(status)` e `event(level)`.

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
dela: num acervo de milhares de páginas cuja pasta de saída fica no
Google Drive, a classificação levou horas e aí **"Importar e gerar
relatórios" levou mais de meia hora sozinho**, sem barra de progresso e sem
nenhum sinal de que estava trabalhando em vez de travado. O trabalho nunca
esteve em risco — as peças eram todas válidas — mas a tela não dizia isso,
então o botão foi clicado de novo. E de novo.

#### Corrigido

- **A checagem de intervalo para de reler as mesmas páginas uma vez por
  peça.** `_validate_range_within_group` pede ao banco todas as páginas do
  agrupador da peça, para conferir que o intervalo dela existe. Pedia uma
  vez por peça: **milhares de consultas onde uma por agrupador bastava**,
  porque o acervo tem poucos agrupadores, e um deles concentra quase todas
  as peças. O intervalo só depende do agrupador, então passa a ser lido uma
  vez por agrupador e guardado durante a corrida. Nesse acervo: **de
  dezenas de segundos para menos de um décimo de segundo** em disco local,
  e **de quase uma hora para menos de um segundo** com o banco no Drive,
  onde cada uma dessas consultas custava dezenas de vezes mais que no disco
  local. A importação mais todos os relatórios agora leva menos de um
  segundo onde levava quase uma hora.

- **Um segundo clique não começa uma segunda importação.** Diferente das
  etapas do pipeline, essa rota faz o trabalho dentro da requisição HTTP,
  então não tem registro no `task_manager` e nada conferia se ela já
  estava rodando. Um dump da pilha do servidor em uso mostrou **várias threads
  `import_and_generate` simultâneas**, cada uma tomando o GIL por vez e
  cada uma prestes a rodar `DELETE FROM item` seguido de milhares de
  inserções no mesmo arquivo SQLite. Todas terminaram, e todas gravaram o
  mesmo resultado — mas cada uma levou quase uma hora. Um clique que cai sobre
  uma corrida já em andamento agora vai direto para a tela de Resultado.

640 testes passando, contra 638.


## [1.3.2] — 2026-09-16

### Fase 21 — contexto calibrado e nota honesta

A fase 20 corrigiu o mecanismo e manteve o número errado que o alimenta.
Numa indexação longa na 1.3.1, **cerca de uma janela em cada dez entrou
no índice sem classificação nenhuma**: centenas de peças com tipo, data e
autor vazios e o OCR cru no lugar do resumo. O log fechou em `baixa=0` e
a nota ainda parecia alta.

#### Corrigido

- **A razão caracteres/token deixa de ser um palpite.** `_CHARS_PER_TOKEN`
  valia 3,0, medida em prosa portuguesa. O acervo tinha tabelas
  contábeis, e tabela contábil tokeniza a **1,45** —
  o recálculo por janela da fase 20 rodava e chegava curto toda vez. A
  razão passa a ser aprendida durante a corrida com o `prompt_eval_count`
  que o Ollama já devolve e o código descartava, guardando o mínimo
  observado, com piso de 1,2. Nesse acervo a razão converge para
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
  do grupo, sem join por grupo. Prova direta: removendo centenas de
  peças do índice, um buraco de centenas de folhas, ela seguiu marcando
  100,0%.

- **A nota deixa de se pagar sozinha.** Os 40 pontos de cobertura eram
  tautológicos: o agrupamento emite uma peça por página da janela, então a
  página está sempre dentro de alguma peça. Passam a medir cobertura
  *classificada* — páginas que o modelo descreveu. A mesma corrida passa
  a valer **menos**, e é sobre essa nota honesta que a correção mostra
  ganho.

- **A peça cega para de se passar por mediana.** A página sobre a qual o
  modelo não disse nada continua entrando no índice pelo agrupamento —
  essa garantia é o que impede a perda — mas agora com confiança `baixa`.
  É o que devolve sentido ao `baixa=` do resumo da etapa 6.

### Adicionado

- **A linha do índice leva à página física do PDF.** `f. 417` pode ser a
  página 145 do `Vol 2.pdf` num grupo de muitos volumes; o índice nomeava o arquivo
  e parava aí.

- **Índice por grupo, com sumário.** O `index.md` saía com milhares de
  linhas e mais de um megabyte num arquivo só, demais para um Projeto do Claude consultar de
  forma confiável. Ele vira um sumário de poucos KB que aponta o grupo e o
  arquivo; a tabela de cada grupo vai para `index-<grupo>.md`, e o pacote
  do Projeto leva todos.

638 testes passando, contra 618.


## [1.3.1] — 2026-09-15

Fase 20. Três coisas que uma corrida de indexação perdia em silêncio.

Achadas lendo o log de uma indexação longa (`qwen3.5:4b` numa GPU de notebook). Nada tinha quebrado — a
corrida reportou `0 falhou(aram)` em todas as etapas — e era esse o
problema: os três defeitos se reportavam como advertência, ou como nada.

### Corrigido

- **A peça não é mais jogada fora por causa da precisão da data.**
  Documentos contábeis e administrativos são datados por período —
  "competência 01/2020", "exercício 2019" — e o modelo devolve `2020-01`
  porque é o que a página diz. A validação exigia `AAAA-MM-DD` estrito e
  descartava a peça *inteira* — tipo, autor, resumo e tudo — por causa de
  um campo opcional. Eram todas as peças recusadas da corrida.

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
  faltava. Na corrida observada, isso deixou faixas inteiras de páginas ausentes de
  um índice cujo propósito inteiro é dizer em que página está cada coisa.
  A cobertura passa a ser calculada a partir das peças que de fato
  sobreviveram à validação.

- **O contexto do Ollama é medido por janela, não uma vez por corrida.**
  Ele era dimensionado pelo prompt da primeira janela e congelava ali.
  Uma janela mais densa adiante o estourava, a resposta voltava
  truncada, o JSON nunca fechava e o parser recebia zero linhas — a
  janela chegava ao índice sem classificação nenhuma, só com um aviso
  dizendo que o modelo não havia respondido sobre nenhuma de suas
  páginas. Foi cerca de uma janela em cada sete, que é a maior
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
  projeto.** Isto saiu de uma atualização de verdade: alguns documentos
  foram acrescentados, o pipeline varreu, converteu, extraiu as páginas
  deles, montou as janelas e classificou todas elas — e `index.md`,
  `timeline.md`, `review.md` e `project_instructions.md` seguiram
  reportando as contagens anteriores de arquivos e janelas, porque gerá-los é
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
  execução. Observado aqui do pior jeito: um servidor deixado rodando de
  madrugada manteve o código velho por horas depois de a correção ser
  gravada, passando essas
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
  ninguém consegue encontrar de novo. Avaliado sobre um documento de 31
  páginas, cinco modelos de três famílias — `gemma4:e4b`,
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
  * O modelo marcou `continues: true` em oito seções consecutivas do
    mesmo relatório que ele mesmo tinha nomeado corretamente — ele leu
    "continua o mesmo *relatório*" onde o prompt queria dizer "o mesmo
    *assunto*". O agrupamento agora é decidido em código, comparando
    assuntos; o `continues` só desempata quando a redação de um assunto
    muda sem que o documento mude (duas partes de uma seção com títulos
    um pouco diferentes).

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
  classificação. Nenhum motor os mostrava ao modelo. O custo apareceu
  num acervo de material didático: classificado por um prompt cujos
  únicos exemplos trabalhados eram "OFÍCIO, MEMORANDO, PARECER", quase
  toda peça voltou sem tipo nenhum. O modelo não estava falhando; estava
  respondendo a pergunta que lhe foi feita. O motor `local` agora monta um
  bloco de contexto a partir desses campos, enquadrado como *o que este
  acervo é*, e não como a tarefa — uma entrada de `extra_rules` pode ser
  uma instrução para o uso posterior do índice em pesquisa, e não algo que
  um classificador deva tentar executar.
- **O prompt pedia documentos e aceitava páginas.** A mesma corrida
  produziu quase uma peça por página, fatiando de uma ou duas páginas
  direto através de documentos que corriam por dezenas. O prompt agora declara a regra explicitamente, junto com a
  falha que ela pretende evitar.
- **`ÍNDICE` e `Índice` eram dois tipos de documento diferentes.** Os
  tipos são normalizados (maiúsculas, espaços colapsados) na entrada, e as
  palavras que um modelo devolve em vez de deixar o campo vazio (`null`,
  `N/A`, `desconhecido`) são tratadas como vazio, em vez de guardadas como
  tipos próprios.
- **Um `desktop.ini` era a peça número um de um índice**, resumido como "arquivo de configuração do sistema
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
  campo vazio respondia pela maior parte dos pontos que faltavam tinha exigido
  consultar o banco à mão.
- **O planejador de VRAM piorava as coisas quando o modelo não cabia.**
  Medido na mesma máquina: com menos VRAM livre do que o modelo precisava,
  ele pedia menos da metade das camadas, e o Ollama acabava pondo na placa
  menos do modelo do que a divisão dele mesmo punha — a estimativa substituía a divisão do escalonador por
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
  Encontrado na máquina que motivou este trabalho: uma RX 5700 XT de 8 GB
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
