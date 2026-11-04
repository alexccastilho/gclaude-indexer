**Leia no seu idioma:** Português (Brasil), você está aqui · **[English](TECHNICAL.md)** · **[Español](TECHNICAL.es.md)**

# GClaude Indexer: detalhes técnicos

Este documento é para quem instala, mantém ou quer entender o programa por dentro. O [README](README.pt-BR.md) explica para que ele serve; o manual dentro do programa (menu **Manual**) explica cada tela. Aqui estão os requisitos, a instalação sem o instalador, o que roda em cada etapa, o que cada arquivo de saída contém e como resolver problemas. Tudo o que estava na seção "Detalhes técnicos" do README antigo está aqui, revisado para a 1.8.0.

Sumário:

- [Requisitos em detalhe](#requisitos-em-detalhe)
- [Instalando sem o instalador](#instalando-sem-o-instalador)
- [Rodando no dia a dia](#rodando-no-dia-a-dia)
- [Os sensores da CPU e as ventoinhas](#os-sensores-da-cpu-e-as-ventoinhas)
- [Desinstalando em detalhe](#desinstalando-em-detalhe)
- [As telas do programa](#as-telas-do-programa)
- [Mantendo um acervo atualizado](#mantendo-um-acervo-atualizado)
- [Conseguindo uma boa classificação](#conseguindo-uma-boa-classificação)
- [O que o índice garante](#o-que-o-índice-garante)
- [Janelas, blocos e OCR](#janelas-blocos-e-ocr)
- [Motores de classificação](#motores-de-classificação)
- [Arquivos de saída](#arquivos-de-saída)
- [Vários acervos num Project: conjuntos](#vários-acervos-num-project-conjuntos)
- [Busca por tema e LexML](#busca-por-tema-e-lexml)
- [OCR e idioma dos documentos](#ocr-e-idioma-dos-documentos)
- [Rodando a suíte de testes](#rodando-a-suíte-de-testes)
- [Solução de problemas](#solução-de-problemas)
- [Documentação](#documentação)

## Requisitos em detalhe

- **Windows 10 ou 11, obrigatório.** O programa conversa diretamente com interfaces do Windows: PowerShell, WMI (detecção de hardware e recursos), o registro (dados do Tesseract e idioma de exibição) e Performance Counters (gráficos de CPU e GPU). Não roda em Linux nem macOS.
- **Python 3.12**, instalado para você se estiver faltando. O projeto fixa versões de dependências que os Python mais novos (3.13, 3.14) quebram. O instalador procura a 3.12 e, se a máquina não tiver, baixa e instala a 3.12.10 oficial para o usuário atual: sem administrador, sem passo manual. Qualquer outro Python já instalado fica onde está.
- **OCR** (documentos escaneados sem camada de texto) precisa de Tesseract e Ghostscript. O instalador instala os dois quando possível.
- **O motor `local`** precisa do [Ollama](https://ollama.com), instalado pelo instalador se você aceitar. O modelo padrão segue a placa de vídeo: `qwen3.5:9b` (5,3 GB) numa placa com 8 GB de VRAM ou mais, `qwen3.5:4b` (3,2 GB) nas menores. Uma placa de vídeo não é obrigatória: o Ollama põe na GPU o que couber e o resto vai para a RAM, bem mais devagar. Com pouca memória nos dois, o programa passa sozinho para o motor `rules` e diz o motivo na tela.
- **O motor `rules`** não precisa de nada disso: roda em qualquer Windows capaz de rodar Python, sem GPU, sem download e sem software extra.
- Alguns gigabytes livres em disco para o ambiente Python e, se você usar, o modelo do Ollama. Os arquivos intermediários (PDFs com OCR e fatias de texto) ficam na pasta local da máquina, em `%LOCALAPPDATA%\GClaudeIndexer\work\`, e não na pasta de saída: um acervo grande gera gigabytes ali.
- A interface está em português do Brasil, inglês e espanhol, num menu no cabeçalho. O padrão segue o idioma de exibição do Windows.
- O instalador é uma comodidade para a primeira preparação. O programa não é compilado num único `.exe`: continua sendo script Python e PowerShell legível, e um atalho na área de trabalho o abre com um duplo clique.

## Instalando sem o instalador

Este caminho funciona também numa máquina onde você não pode instalar programas. Em resumo: execute o `Indexer.bat` e siga as instruções. Passo a passo:

**1. Coloque o código-fonte na sua máquina.** Se baixou o projeto como `.zip`, clique com o botão direito, escolha "Extrair tudo..." e escolha uma pasta comum (Documentos, ou uma pasta do Google Drive montado com letra de unidade). Se clonou com Git, já tem uma pasta. Abaixo ela se chama "a pasta do projeto".

**2. Abra o PowerShell na pasta do projeto.** No Explorador de Arquivos, abra a pasta, segure **Shift**, clique com o botão direito num espaço vazio e escolha "Abrir janela do PowerShell aqui" (ou "Abrir no Terminal"). Ou clique na barra de endereço, digite `powershell` e pressione Enter.

**3. Você não precisa instalar o Python.** O instalador do passo 4 precisa do Python 3.12 e, se a máquina não tiver, baixa o 3.12 oficial do python.org (versão exata, checksum conferido) para dentro da sua pasta de usuário, sem pedir administrador. Ele fica ao lado de qualquer outro Python: se hoje `python --version` mostra 3.13 ou 3.14, continua mostrando. Se preferir instalar antes, é o mesmo comando que o instalador usa:

```powershell
winget install --id Python.Python.3.12 -e --scope user --silent --accept-package-agreements --accept-source-agreements
```

**4. Rode o instalador uma vez.** Ele instala o Python 3.12 se faltar, cria um ambiente Python privado para este programa (fora da pasta do projeto, para sobreviver a uma mudança de pasta ou a uma nova sincronização do Drive), instala os pacotes, confere Tesseract e Ghostscript (instalando se faltarem e você concordar) e oferece um atalho na área de trabalho.

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

O Windows pode mostrar "O Windows protegeu o computador" na primeira vez que você roda um script baixado da internet. A opção `-ExecutionPolicy Bypass` roda só este script, sem mudar nenhuma configuração permanente. O instalador mostra o progresso e pergunta antes de instalar qualquer coisa (Tesseract, Ghostscript e, opcionalmente, o Ollama e o modelo, que é um download grande). Se um passo falhar, ele mostra o comando manual. A primeira execução leva vários minutos, a maior parte baixando pacotes.

**5. Aceite o atalho na área de trabalho**, se quiser. Um segundo atalho, opcional, "GClaude Indexer (CPU sensor)", pede administrador toda vez que abre, só para o leitor de sensores (veja a seção seguinte). Dá para mudar de ideia depois com `install.ps1 -CpuSensorShortcut`.

## Rodando no dia a dia

Dê duplo clique no atalho da área de trabalho. Uma janela de console aparece só na primeira vez, se o instalador ainda precisar rodar; depois o programa sobe sem janela visível e abre o navegador em:

```
http://127.0.0.1:8000
```

O servidor só escuta em `127.0.0.1`, a sua própria máquina. Nunca fica acessível pela rede nem por outro computador.

Sem o atalho, a partir da pasta do projeto:

```powershell
python launcher.py
```

Isso confere o ambiente e instala o que faltar antes de subir o servidor, então também funciona numa máquina onde você ainda não rodou o instalador.

Para fechar o programa, feche a janela do terminal que ele abriu (ou, se estiver rodando oculto pelo atalho, finalize o `pythonw.exe` no Gerenciador de Tarefas).

**Atualizar o programa.** Instale a versão nova por cima, sem desinstalar: o instalador encerra a versão antiga que estiver rodando e os seus projetos ficam onde estão. Se um servidor de outra versão ainda estiver no ar quando você abrir o programa, o novo o substitui e avisa.

**O que o instalador grava para o Ollama.** Para a placa de vídeo ser aproveitada por inteiro, o instalador grava variáveis de ambiente do usuário que o Ollama lê ao subir. O programa passa as mesmas para o servidor que ele mesmo sobe quando não há um no ar, e os dois precisam concordar:

| Variável | Valor | Por quê |
|---|---|---|
| `OLLAMA_MAX_LOADED_MODELS` | `1` | um modelo de cada vez na placa |
| `OLLAMA_NUM_PARALLEL` | `1` | um pedido por vez; paralelismo não ajudou nas medições (02/11/2026) |
| `OLLAMA_FLASH_ATTENTION` | `1` (ou `0` em Radeon RX 5000/6000) | em RDNA 1 e 2 via Vulkan, a flash attention dobra o tempo de leitura do trecho; medido numa RX 6700 XT |
| `OLLAMA_KV_CACHE_TYPE` | `q8_0` (ou `f16` com a flash attention desligada) | o Ollama só compacta o cache quando a flash attention está ligada |
| `OLLAMA_GPU_OVERHEAD` | `0` | sem reserva artificial de VRAM |
| `OLLAMA_KEEP_ALIVE` | `30m` | o modelo fica carregado entre uma janela e a próxima |
| `LLAMA_ARG_CACHE_RAM` | `0` | sem cache de prompts na RAM: o runner reservava 8 GB que nunca eram reaproveitados aqui (cada janela é um pedido novo) e pareciam modelo transbordado |

Um valor que você mesmo tenha mudado é respeitado e dito no console; o desinstalador remove só o que o instalador gravou. O log do servidor que o programa sobe fica em `%LOCALAPPDATA%\GClaudeIndexer\ollama-serve.log`, e o log da execução diz qual placa e qual backend (CUDA, ROCm ou Vulkan) o Ollama está usando.

## Os sensores da CPU e as ventoinhas

Temperatura, consumo e rotação da ventoinha da CPU só podem ser lidos com privilégio de administrador: a ventoinha fica no chip SuperIO da placa-mãe, que o Windows só expõe a um driver de kernel. Há dois jeitos de pedir, ambos opcionais. O botão **Ler sensores da CPU e ventoinhas**, na tela Execução, pede sob demanda, quantas vezes você quiser, e explica numa linha o que o Windows vai perguntar. O atalho "GClaude Indexer (CPU sensor)" pede sozinho toda vez que você abre o programa. O que sobe com privilégio não é o programa: é um processo auxiliar pequeno, cuja única função é ler os sensores e devolver os números. O servidor, a indexação e os seus documentos rodam sem privilégio, e o auxiliar fecha junto com o programa.

Responder **Não** é seguro e não custa nada: o programa abre como pelo atalho comum, mostrando temperatura, consumo, frequência, VRAM usada e o modelo carregado na GPU, e "requer administrador, clique em Ler sensores" na temperatura, no consumo e na ventoinha da CPU. Nada falha e o botão continua disponível.

O que a tela mostra e por quê:

- **"parada"** é leitura real de 0 RPM. Placas de vídeo modernas param a ventoinha quando estão frias.
- **"requer administrador, clique em Ler sensores"** quer dizer que o valor existe, mas não pode ser lido sem o auxiliar.
- **"não medido"** quer dizer que a máquina não tem sensor que a biblioteca leia. Em notebooks as ventoinhas pertencem ao controlador embarcado e só o fabricante as expõe; notebooks Dell são lidos pela interface da própria Dell.
- **Temperatura e consumo da CPU em processadores recentes** podem precisar do driver PawnIO, que o instalador oferece como item opcional (o Windows pede administrador para instalá-lo).
- **VRAM usada** e **Modelo na placa** aparecem quando há placa de vídeo: é como você vê se o modelo coube inteiro nela.

A ventoinha da CPU é escolhida pelo nome do sensor, quando a placa dá um, ou pelo header fixo de CPU do chip; o programa nunca mostra "a primeira ventoinha que gira" como se fosse a da CPU. O leitor elevado é relançado quando necessário depois de reiniciar o computador.

## Desinstalando em detalhe

Se você instalou com o instalador do Windows, use Configurações > Aplicativos.

Caso contrário, dê um duplo clique no `Desinstalar.bat`, na pasta do projeto (a mesma do `Indexer.bat`), ou pelo prompt:

```powershell
.\Desinstalar.bat
powershell -ExecutionPolicy Bypass -File uninstall.ps1
```

**Por que não simplesmente `.\uninstall.ps1`?** O Google Drive marca todo arquivo que sincroniza como vindo da internet, e a política de execução padrão do Windows (RemoteSigned) recusa rodar um `.ps1` assim sem assinatura digital. Não há nada errado com o script: o `Desinstalar.bat` passa `-ExecutionPolicy Bypass` naquela execução, como todos os lançadores deste projeto. Rodar o `install.ps1` também limpa essa marca dos scripts da pasta.

Ele pergunta item por item, e a resposta padrão é sempre **não**. Separa o que esta instalação tem como seu (o ambiente virtual, os atalhos, as bibliotecas de sensores, as configurações locais, as entradas de PATH e as variáveis de ambiente que ele criou) dos programas comuns que ele apenas instalou para você: Tesseract, Ghostscript, Ollama, Python e os modelos baixados do Ollama. Outros programas podem estar usando esses, então cada um é oferecido separadamente.

**Ele nunca apaga os seus projetos.** As pastas de saída, os bancos de dados e os relatórios gerados são seus documentos. O script lista onde eles estão, com o tamanho de cada um, e deixa a decisão com você.

Três opções cobrem os usos não interativos:

```powershell
powershell -ExecutionPolicy Bypass -File uninstall.ps1 -WhatIfOnly        # mostra o plano, não remove nada
powershell -ExecutionPolicy Bypass -File uninstall.ps1 -KeepDependencies  # mantém Tesseract, Ghostscript, Ollama, Python
powershell -ExecutionPolicy Bypass -File uninstall.ps1 -RemoveAll         # diz sim a tudo (menos aos seus projetos)
```

A pasta do próprio projeto, se for sincronizada pelo Google Drive, nunca é tocada: apague-a por lá se quiser que ela suma de todos os computadores.

## As telas do programa

A interface tem sete telas, mais **Manual** e **Sobre**:

1. **Projetos**: todos os projetos que este computador conhece, com data de criação e situação. É onde o programa abre.
   - **Catálogo compartilhado**: aponte-o para uma pasta dentro do Google Drive e todo computador conectado a esse Drive passa a ver, abrir, editar e excluir os mesmos projetos. Sem ele, a lista de projetos fica só nesta máquina, mesmo com os projetos sincronizados. Projetos guardados no disco local de outro computador aparecem marcados como fora de alcance.
   - **Abrir projeto existente** recebe uma pasta que você aponta e reabre o projeto que estiver nela: depois de uma reinstalação, numa máquina nova, para uma pasta movida ou que alguém lhe mandou. Nada é recriado; a pasta de saída já guarda o projeto inteiro.
   - **Excluir** oferece duas escolhas: só tirar o projeto da lista ou também apagar os arquivos gerados. Nesse caso o programa apaga só o que ele mesmo criou (banco, relatórios, `buscar.bat`, a pasta de trabalho local). Os seus arquivos na pasta de saída ficam, e a pasta só some se ficar vazia. Em `project_instructions.md` e `CLAUDE.md` sai só o bloco gerado. A pasta de origem nunca é tocada.
2. **Novo projeto**: pasta de origem, pasta de saída, quais tipos de arquivo incluir, como agrupar os documentos e qual motor usar. Ao escolher a pasta de origem, o programa propõe uma configuração a partir do que encontra nela (tipos de arquivo, agrupamento, idioma). Todo campo tem um padrão e uma dica "?".
3. **Execução**: uma linha por etapa (varredura, conversão, extração por página, preparação de janelas, classificação), cada uma com um botão para rodá-la, uma barra de progresso com estimativa de tempo e os botões **Pausar** e **Continuar**. Pausar responde na hora ("parando") e a retomada continua de onde parou. Abaixo, um log ao vivo em linguagem simples e os gráficos de CPU, RAM e GPU, com os sensores. Enquanto a pasta é percorrida, um contador mostra quantos arquivos já foram vistos. Um botão separado, **Importar e gerar relatórios**, transforma os itens classificados nos arquivos de saída. Toda operação longa aparece numa barra de atividade com nome e cronômetro, que sobrevive a um F5; pedir outra operação sobre um projeto ocupado leva a uma página "em andamento", sem perder nada. Se a pasta de origem mudou desde a última execução, um aviso aparece no topo pouco depois que a página carrega.
4. **Atualizar acervo**: alcançada a partir desse aviso. Lista os documentos novos, editados e removidos, nomeia os que serão reprocessados e informa o custo: quantos arquivos passam pelo OCR de novo (inclusive os cujo OCR falhou da última vez), quantas janelas são reclassificadas, quantas mantêm a classificação, e quais documentos terão a numeração das folhas alterada. Nada muda até você confirmar. Se a pasta de origem não puder ser lida (disco desconectado, pasta movida), a tela avisa e não oferece nada: uma pasta inacessível nunca é confundida com um acervo cujos documentos foram apagados.
5. **Resultado**: a nota de qualidade, as pendências, uma prévia de cada arquivo gerado, o pacote para o Claude com o orçamento de tokens e a lista do que ficou de fora por tamanho, um botão para abrir a pasta de saída e **Liberar espaço**, que apaga os arquivos intermediários da pasta de trabalho local (PDFs com OCR e fatias de texto). O banco, os relatórios e os logs nunca são tocados por isso.
6. **Buscar no acervo**: busca de texto completo nas páginas do projeto, com o trecho e a página de cada resultado. Uma caixa opcional consulta também o LexML do Senado (veja [Busca por tema e LexML](#busca-por-tema-e-lexml)).
7. **Conjuntos**: vários acervos num único Claude Project (veja [Vários acervos num Project](#vários-acervos-num-project-conjuntos)).

O cabeçalho de toda tela tem um seletor de idioma, um seletor de tema (Claro, Escuro, Sépia, Alto contraste, Aurora, Toga, Grafite e Oceano) e um seletor de layout (Padrão, Técnico, Editorial e Compacto). As escolhas ficam guardadas no seu navegador. O movimento entre as telas é desligado quando o Windows pede menos movimento.

## Mantendo um acervo atualizado

Um acervo muda: chegam documentos, um escaneamento é trocado por um melhor, algo é retirado. Nada disso exige indexar tudo de novo.

Abra o projeto. Alguns segundos depois que a tela Execução aparece, se algo mudou na pasta de origem, um aviso diz o quanto ("14 novos, 3 editados, 1 removido"). Siga-o até **Atualizar acervo**, veja o plano e confirme. Depois rode as etapas como de costume: elas encontram só o trabalho que a atualização deixou. Acrescentar um documento a um acervo de 500 páginas reclassifica uma janela em vez de trinta e seis: cerca de um minuto em vez de dezoito e meio. Uma segunda varredura não relê arquivos iguais.

**Uma etapa não faz parte de "Rodar tudo".** Transformar os itens classificados nos arquivos Markdown é um botão próprio, **Importar e gerar relatórios**, na tela Execução. A classificação terminar não os grava. Se você pular essa etapa, os relatórios continuam descrevendo o acervo como ele era antes. O programa lembra você: quando não sobra nada para processar, aparece um aviso com o botão, e a tela Resultado diz quando os arquivos exibidos são anteriores ao projeto e o que mudou desde então. Depois de atualizar, envie os arquivos novos ao seu Project do Claude.

**Por que não é o acervo inteiro.** Os documentos são agrupados, e as páginas de um grupo são lidas como uma sequência longa, fatiada em janelas sobrepostas; as janelas são o que o motor de classificação lê. Uma mudança invalida o grupo a partir da primeira página que se deslocou. Tudo antes disso mantém suas páginas e sua classificação. Um documento acrescentado no fim de um grupo custa quase nada; um inserido no início desloca toda página depois dele e custa mais. A tela diz em qual caso você está antes de confirmar.

**Documentos removidos.** As páginas e peças saem do índice, a cópia convertida é apagada, e o nome e o momento da remoção ficam registrados no `review.md`. Se a pasta tinha uma cópia idêntica do documento removido, essa cópia passa a ser indexada no lugar dele. Se um grupo some por inteiro, o `index-<grupo>.md` dele é apagado.

**Numeração de folhas que muda.** Num acervo do tipo processo, a numeração das folhas (f. 1, f. 2...) corre contínua pelo grupo. Acrescentar ou retirar um documento no meio muda os números dos documentos seguintes. A tela de confirmação lista quais são e o log avisa: conversas antigas com o Claude que citavam essas folhas podem ficar desatualizadas.

Documentos que só precisam de renumeração não passam pelo OCR de novo: os arquivos convertidos ainda estão na pasta de trabalho local e são relidos. Só um documento cujo conteúdo mudou paga esse custo. Um arquivo cujo OCR falhou é refeito na próxima conversão, e a etapa fica "pendente" enquanto houver um assim.

**Se você limpou os arquivos intermediários** com Liberar espaço, os documentos que seriam relidos precisam ser convertidos de novo. A atualização trata isso corretamente; só demora mais.

**Se a pasta de origem não puder ser alcançada** (o disco está desconectado, a pasta foi movida ou renomeada), nada é oferecido e nada é alterado.

**Um computador por vez.** Enquanto um projeto está aberto, ele fica travado para aquele computador. Outro computador é avisado de quem está usando. Fechar o navegador libera a trava em cerca de cinco minutos; uma trava de uma máquina que travou expira sozinha em dez.

## Conseguindo uma boa classificação

Duas coisas decidem mais sobre o resultado do que qualquer outra.

**Preencha o Tema do acervo e o Tipo de acervo no Novo projeto.** O motor `local` mostra esses campos ao modelo, e são eles que dizem que tipo de documento ele está lendo. Um acervo descrito só com os padrões acaba classificado contra exemplos genéricos, e o modelo responde "não sei" para quase todo tipo. Uma frase sobre o acervo (o que é, de onde veio, que documentos tem) é a coisa mais eficaz que você pode fazer pelo resultado. **Papel nas instruções** e **Regras extras** também são repassados, como contexto.

**Qual modelo usar.** Medido neste projeto, sobre as mesmas janelas de um mesmo documento, com todos os modelos rodando inteiramente numa placa de 8 GB:

| Modelo | Tamanho | Tipo preenchido | s/janela |
|---|---:|---:|---:|
| `qwen3.5:4b` | 3,0 GB | 100% | 30,8 |
| `gemma4:e4b` | 3,1 GB | 79,5% | 38,5 |
| `qwen3.5:9b` | 5,3 GB | 79,5% | 86,2 |
| `qwen3:8b` | 5,4 GB | 100% | 108,8 |
| `granite4.2:8b` | 5,7 GB | 100% | 116,9 |

Nessa medição, o `qwen3.5:4b` alcançou a qualidade do melhor em um quarto do tempo e com metade da VRAM. Medido depois contra um gabarito, no acervo de demonstração (72 páginas, 41 peças), o `qwen3.5:9b` acertou mais a data (88,6%) e o autor (84,4%) e levou 4 min 12 s, contra 4 s do motor de regras; os números completos e o que eles não dizem estão em [QUALITY.pt-BR.md](QUALITY.pt-BR.md). Por isso o padrão desde a 1.5.14 é `qwen3.5:9b` numa placa de 8 GB ou mais e `qwen3.5:4b` nas menores. Descrever uma página é leitura e disciplina de formato; tamanho não compra qualidade sozinho e custa tempo.

**Escolha um modelo que caiba na sua placa de vídeo.** O que não cabe na VRAM o Ollama roda na CPU, e a diferença é grande. Numa placa de 8 GB, um modelo de 9,1 GB rodou com 17% de si na GPU; um de 5 GB rodou inteiro na GPU. A tela Execução mostra a VRAM da placa, a VRAM usada e o modelo carregado; a tela Sobre lista os modelos instalados; o log avisa quando o modelo escolhido não cabe e diz qual placa e qual backend estão em uso. Um modelo que cabe e termina vale mais que um maior que passa a execução inteira transbordando.

**Contexto pelo hardware.** O tamanho do contexto enviado ao modelo (`num_ctx`) tem um teto calculado pela VRAM da placa e pela RAM, para que o modelo e o cache fiquem inteiros na placa. Um trecho grande nunca é cortado em silêncio: o pedido vai com `truncate: false`, e um trecho que não caiba é dividido em dois pedidos. Uma resposta que volta incompleta é pedida de novo com contexto maior ou janela menor.

Se a nota de qualidade parecer baixa, abra o log: ele informa como a GPU está sendo usada. Na tela Resultado, a nota vem decomposta em confiança, preenchimento de campos e penalidades. A nota se baseia no que o próprio motor declarou; não é uma medida de acerto real. Para medir acerto, use o acervo de demonstração e o `tools/medir_acerto.py` ([QUALITY.pt-BR.md](QUALITY.pt-BR.md)), ou confira algumas peças do seu acervo por amostragem.

## O que o índice garante

Três propriedades valem não importa quão bem o modelo faça o trabalho, porque o código as impõe.

**Toda página chega ao índice.** Uma página que o modelo nunca mencionou ainda assim ganha uma entrada, com a referência dela, o arquivo e o próprio texto como resumo, porque o agrupamento percorre as páginas da janela, não a resposta do modelo. Uma peça que não passa na validação é descartada, mas as páginas dela voltam como entrada de confiança baixa, em vez de sumirem junto. Um índice que omite uma página em silêncio é pior que índice nenhum: o que falta é invisível.

**Um documento inteiro é sempre uma peça própria.** Um arquivo que é um documento só (HTML, Word, e-mail, planilha) começa uma peça nova, mesmo que o modelo o tenha emendado ao documento anterior. Numa página de legislação, a epígrafe ("LEI Nº 8.078, DE 11 DE SETEMBRO DE 1990") vira o tipo da peça. O autor de um ato é lido do texto completo, e cada autor e cada tipo têm uma grafia só em todo o índice.

**As datas mantêm a precisão que o documento de fato tem.** Documentos datados por período ("competência 01/2020", "exercício 2019") são guardados como `2020-01` e `2019`, e não completados até um primeiro dia do mês que a página nunca afirmou. A ISO 8601 admite a forma reduzida, e ela continua ordenando corretamente no `timeline.md`. Uma data cujo dia não existe (`2021-09-31`) cai para o mês; texto que não é data deixa o campo vazio, e a peça mantém todo o resto.

## Janelas, blocos e OCR

Uma **janela** é uma sequência de páginas seguidas que o classificador lê de uma vez para descobrir onde cada peça começa e termina.

**Páginas por janela** é o que mais afeta a qualidade: é quantas páginas vão em cada pedido ao modelo, que responde com uma linha por página. O padrão do formulário é 16. Quando o motor local foi ajustado, 8 deu os melhores resultados: com 16, a resposta passava de 3.500 tokens e era truncada, e com 4 você triplica o número de pedidos sem ganho. Desde a 1.3.2, o motor local percebe quando uma resposta volta incompleta e tenta de novo com um contexto maior ou dividindo a janela. Se a nota estiver baixa com o modelo local, experimente 8. Muitos documentos curtos misturados se saem melhor com janelas menores; documentos longos e padronizados toleram janelas maiores.

**Páginas por bloco** não afeta o índice. Só corta PDFs muito grandes em arquivos auxiliares dentro da pasta de trabalho local, que nada mais lê e que o Liberar espaço apaga. Deixe em 80; reduza só se um PDF muito grande (500+ páginas) fizer a conversão ficar sem memória.

**OCR** só se aplica a páginas sem camada de texto; o programa confere página a página e deixa em paz as que já têm texto. Um PDF com texto nativo e algumas folhas escaneadas no meio recebe OCR só nessas folhas (desde a 1.5.2), e um PDF assinado digitalmente também recebe OCR. Um PDF escaneado inteiro passa por uma configuração própria do OCR (pasta `configs/`), que melhorou o resultado nas digitalizações do acervo de demonstração. Aí o que importa é o **Idioma do OCR** corresponder aos seus documentos. A conversão roda em duas filas (OCR e o resto) e tem prazo por arquivo: um arquivo que trava não segura os outros, e um OCR que falhou é refeito na próxima conversão.

**Arquivos lidos como texto.** HTML e as demais páginas da web são lidas como texto (texto tachado vira `~~assim~~`, para o classificador saber que foi riscado); a codificação de arquivos de texto e e-mails é descoberta (UTF-8, Windows-1252 e outras); hiperlinks do Word são mantidos. Arquivos `.ini` nunca são indexados, e arquivos binários sem texto aparecem nas pendências com o motivo.

## Motores de classificação

A classificação (decidir o que cada página é, quem escreveu e quando) é a única etapa em que você escolhe como o trabalho é feito. Todas as outras (varredura, OCR, extração, busca, geração dos relatórios) são idênticas não importa o motor, e rodam sempre localmente.

| Motor | Custo | Sai da máquina? | Precisa de |
|---|---|---|---|
| `rules` | gratuito | não | nada: roda em qualquer máquina Windows |
| `local` | gratuito | não | Ollama, instalado automaticamente; mais rápido com GPU, funciona sem uma |
| `claude_code` | sua assinatura do Claude já existente | **sim** | Claude Code já instalado nesta máquina |
| `automatic` | | | escolhe `local` se o hardware aguentar, senão `rules`; nunca escolhe `claude_code` sozinho |

**O `claude_code` é inteiramente opcional.** O programa funciona do início ao fim sem ele. Escolha-o só se você já usa o Claude Code e quer que ele faça a classificação. O programa então grava um `CLAUDE.md` na pasta de saída e mostra uma frase para dizer ao Claude Code (`processe as janelas`); abra o Claude Code na pasta de saída, diga a frase e, quando ele terminar, clique em **Reverificar se as janelas acabaram**. Esse `CLAUDE.md` manda o Claude Code tratar o texto dos documentos como dado não confiável, nunca como instrução.

O `rules` é determinístico: procura marcadores conhecidos de tipo de documento, padrões de data e blocos de assinatura, sem nenhum modelo de aprendizado de máquina, então o resultado é reproduzível e não precisa de instalação. O `local` usa um modelo aberto servido pelo [Ollama](https://ollama.com) na sua própria máquina (`http://127.0.0.1:11434`, nunca um endereço remoto, nunca por proxy) e em geral dá resultados melhores que o `rules`, ao custo do espaço em disco, do download e (opcionalmente) da GPU listados em Requisitos. Com placa de vídeo, o motor local espera o Ollama voltar em vez de cair para as regras; sem placa, cai e volta ao modelo quando ele responder.

**Legislação do Planalto.** Páginas `.htm`/`.html` salvas do site do Planalto (leis, decretos, medidas provisórias, portarias, resoluções, atos do Império) são lidas pela estrutura da própria página, sem modelo: tipo, número, data, autor e ementa saem da epígrafe e do cabeçalho. Nenhum motor é consultado para elas, e o resultado alimenta o `normas-citadas.md`.

**Revisar confiança baixa**, no Novo projeto, roda o `rules` em tudo e manda só as peças de confiança baixa para um segundo motor à sua escolha: um meio-termo entre o custo zero do `rules` e a precisão de um motor mais forte nas páginas que precisam. A tela Resultado tem uma tabela para comparar motores e modelos rodados sobre o mesmo acervo.

## Arquivos de saída

Gravados na pasta de saída que você escolheu, no idioma em que a interface estiver quando você os gerar:

- `index.md`: o sumário. Lista os grupos e diz qual arquivo de índice abrir para cada um; conta as páginas de legislação e aponta para o `normas-citadas.md`.
- `index-<grupo>.md`: um índice por grupo. Cada peça com folhas ou páginas, tipo, data, autor, arquivo e página dentro do PDF, e um resumo. Índice de grupo acima de 25 MB sai em partes `index-<grupo>-1.md`, `-2.md`..., quebrando só entre arquivos de origem. As linhas são enxutas: o nome do arquivo não se repete na coluna Intervalo, e a coluna Confiança só aparece quando há alguma linha com dúvida.
- `normas-citadas.md`: uma linha por norma reconhecida no acervo (lei, decreto, medida provisória, portaria...), com tipo, número, data, ementa, em que grupos e páginas ela aparece e um link para o texto no LexML. É o que substitui o antigo arquivo de legislação por grupo (`legislacao-*.md`), que deixou de existir na 1.8.0 (um projeto antigo perde o arquivo na próxima geração). Só existe quando há ao menos uma norma.
- `timeline.md`: as peças datadas em ordem cronológica, sem os atos do Planalto. Grupo com mais de 2.000 peças datadas ganha o seu `timeline-<grupo>.md`, que fica fora do pacote do Claude (repete o índice do grupo por data); a tela de resultado mostra o tamanho dele.
- `review.md`: um relatório de conferência: o que foi lido, lacunas, falhas, o que ainda está pendente, e os documentos removidos da pasta de origem, com o momento em que cada um saiu. O índice e a cronologia descrevem o acervo como ele está hoje; é aqui que você descobre o que costumava estar nele.
- `project_instructions.md`: instruções para um Project do Claude, montadas com os campos que você preencheu no Novo projeto, incluindo como usar o índice, como achar uma norma no `normas-citadas.md` e a regra de sempre conferir valores no documento original.
- `buscar.bat`: a busca por tema para o Claude Code, descrita em [Busca por tema e LexML](#busca-por-tema-e-lexml).
- `project.db`: o banco do projeto. Guarda tudo, inclusive o texto de cada página e o índice da busca.
- `CLAUDE.md`: só quando você usa o motor `claude_code` ou grava um conjunto numa pasta.

Os arquivos intermediários (PDFs com OCR em `converted/`, fatias de texto em `blocks/`) ficam em `%LOCALAPPDATA%\GClaudeIndexer\work\<projeto>\`, fora da pasta de saída, desde a 1.5.8: uma pasta de saída no Drive não sincroniza gigabytes que só esta máquina usa. Um projeto antigo que ainda tenha essas pastas na saída continua sendo lido de lá.

**O seu texto nesses arquivos é preservado.** Em `project_instructions.md` e `CLAUDE.md`, o conteúdo gerado fica entre `<!-- GCLAUDE-INDEXER:BEGIN ... -->` e `<!-- GCLAUDE-INDEXER:END -->`. Gerar os arquivos de novo refaz só esse bloco; o que você escreveu fora dele fica, e não se repete a cada geração. Se a pasta de saída já tinha um `CLAUDE.md` seu, ele é mantido e o bloco é acrescentado, com uma cópia `.bak` do original na primeira vez. O texto colado em **Instruções que você já usa** vai para o topo do `project_instructions.md`.

A tela Resultado também oferece um pacote `.zip` com esses arquivos e um guia curto. O guia diz para colar o `project_instructions.md` inteiro nas instruções do Project e enviar `index.md`, os arquivos `index-<grupo>.md`, `normas-citadas.md`, `timeline.md` e `review.md` como conhecimento do projeto.

**Os limites de um Project do Claude, e como o programa lida com eles.** Um Project aceita 30 MB por arquivo de conhecimento e só lê texto (um `.zip` não é lido). Tudo o que você envia precisa caber na janela de contexto; acima de uns 500 mil tokens o Project passa a usar busca automática nos arquivos, que funciona até alguns milhões de tokens e piora depois. Por isso a tela Resultado mostra, antes do botão de download, cada arquivo que vai no pacote com tamanho e tokens estimados, e avisa nesses dois níveis (o teto de tokens é ajustável por projeto; o padrão é 2 milhões). Um arquivo acima de 30 MB nunca entra no pacote, porque o Project o recusaria: a tela lista o que ficou de fora. Na maioria dos casos basta gerar os relatórios de novo para o índice sair em partes abaixo de 30 MB; a exceção é um único arquivo de origem cujo índice, sozinho, passe de 30 MB, porque o índice só é partido na fronteira entre arquivos. O programa mantém o pacote pequeno deixando o texto das normas de fora (o Claude as abre pelo link do `normas-citadas.md`), não repetindo o índice na cronologia, fatiando índice acima de 25 MB e omitindo o que não informa.

## Vários acervos num Project: conjuntos

A tela **Conjuntos** monta um pacote único a partir de dois ou mais projetos, para um Claude Project que responda sobre todos eles. Cada projeto do conjunto recebe um apelido curto (proposto a partir do nome: "Diretoria / Região Sul" vira `diretoria-regiao-sul`), e no pacote combinado cada arquivo leva o apelido como prefixo: `diretoria-regiao-sul__index.md`, `contratos__index-Processo.md`. Os links dentro dos sumários e das cronologias são reescritos para os nomes prefixados, então nenhum nome colide mesmo quando dois projetos têm o mesmo grupo. Um único `project_instructions.md` sai com o texto pessoal do conjunto no topo, uma seção "Em qual acervo procurar" e uma seção por acervo. O orçamento de tokens é somado e o teto é o menor entre os projetos.

Um membro cuja pasta está fora do ar neste computador (Drive de outra máquina), cujo banco não abre ou que nunca gerou relatórios fica fora do pacote, com o motivo na tela, e continua no conjunto. Os conjuntos ficam em `%LOCALAPPDATA%\GClaudeIndexer\sets.json`, nesta máquina.

**Gravar numa pasta** escreve os mesmos arquivos numa pasta à sua escolha, mais um `CLAUDE.md` combinado que diz ao Claude Code onde está cada acervo e como buscar em cada um. A pasta não pode ser a pasta de origem nem a de saída de um acervo. Regravar atualiza só o que mudou, mantém o que você escreveu fora das marcas e apaga os arquivos de um apelido que deixou de existir.

## Busca por tema e LexML

Ao fim da extração, o texto de todas as páginas entra num índice de busca (SQLite FTS5) dentro do `project.db`; a etapa só termina quando a busca está pronta. A tela **Buscar no acervo** consulta esse índice e mostra, para cada resultado, o arquivo, a página e o trecho.

**Para o Claude Code**, a pasta de saída ganha um `buscar.bat`: `buscar.bat saneamento` lista os arquivos e páginas em que o termo aparece, agrupados por arquivo, com o link da norma ao lado dos trechos de legislação. O `CLAUDE.md` explica o comando. O `.bat` chama o Python do próprio programa com caminhos desta máquina e é regravado a cada geração. Opções: `--grupo` restringe a um grupo, `--so-legislacao` mostra só normas, `--limite` limita a quantidade, `--lexml` consulta também o LexML.

**LexML.** O [LexML](https://www.lexml.gov.br) é o portal do Senado que cataloga a legislação brasileira. Com a caixa "Também procurar no LexML" marcada na tela de busca (no `buscar.bat`, com `--lexml` ou quando nenhuma norma do acervo cita o termo), o programa pergunta ao serviço de busca do portal (SRU) pelas normas que tratam do termo, sem enviar nada do seu acervo além do termo digitado. Em 02/11/2026 o portal passou a responder às buscas de programas com uma página de verificação de segurança; nesse caso o programa diz isso e mostra o link para abrir a busca no navegador. O programa nunca tenta contornar a verificação. Os links de cada norma (`https://www.lexml.gov.br/urn/...`) continuam abrindo normalmente.

## OCR e idioma dos documentos

Projetos novos usam OCR em português (`por`) por padrão, já que o projeto nasceu para acervos em português do Brasil.

O pacote do Tesseract para Windows traz apenas `eng` e `osd`, então o `install.ps1` baixa os dados do idioma que o projeto usa (`por`, por padrão), com o SHA-256 conferido. Quando a pasta `tessdata` do Tesseract exige administrador (o caso comum), os dados vão para a pasta desta máquina (`%LOCALAPPDATA%\GClaudeIndexer\tessdata`), e o programa aponta o Tesseract para ela só no próprio processo, sem pedir administrador. O programa também faz isso ao abrir, então um idioma que falte é corrigido assim que a máquina estiver na internet.

Se o seu acervo estiver em outro idioma, mude o **Idioma do OCR** no Novo projeto para o código do Tesseract (por exemplo `eng` para inglês, `spa` para espanhol, ou `por+eng` para os dois no mesmo acervo) e instale os dados desse idioma:

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1 -OcrLanguage spa
```

O instalador só instala idiomas cujo SHA-256 ele tem fixado: hoje `por`, `eng`, `spa` e `osd`. Ele nunca baixa um arquivo que não consegue conferir; para qualquer outro idioma, mostra onde pegar o arquivo e onde colocá-lo.

## Rodando a suíte de testes

Se você está contribuindo com mudanças, ou quer confirmar que tudo funciona depois de instalar, use o Python de dentro do ambiente que o instalador criou (não o `python` que o seu PATH encontrar):

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -B -m pytest -q
```

Uma execução correta termina com uma linha como `1197 passed, ... warnings in ...s` e nenhuma falha. O número de testes cresce com o tempo; os avisos vêm de bibliotecas de terceiros, e a contagem pode variar entre máquinas. A suíte não fala com o Ollama real nem com a rede, e nunca para o Ollama da máquina. Veja [CONTRIBUTING.pt-BR.md](CONTRIBUTING.pt-BR.md) (original em inglês: [CONTRIBUTING.md](../CONTRIBUTING.md)) para a preparação completa de um ambiente de desenvolvimento. O CI do GitHub roda a suíte e indexa o acervo de demonstração a cada push, anexando o relatório de acerto à rodada.

## Solução de problemas

- **Aparece um aviso dizendo que o sistema foi atualizado depois que a janela abriu.** O código no disco mudou enquanto o servidor rodava, e o Python carrega os módulos uma vez, ao iniciar. Feche o programa e abra de novo pelo atalho.
- **O navegador abre mas a página nunca carrega.** Espere alguns segundos na primeira execução. Se continuar, confira se outro programa está usando a porta 8000.
- **Aparece "Pedido recusado".** Algo que não são as telas do próprio programa (em geral um site) tentou mandar um comando e foi bloqueado. Abra sempre o programa pelo atalho ou em `http://127.0.0.1:8000`.
- **Aparece "banco ocupado" ou "operação em andamento".** Outra operação está usando o projeto (uma conversão, uma geração de relatórios). Nada se perdeu: espere a barra de atividade terminar e tente de novo.
- **"python não é reconhecido..." no PowerShell.** O Python não está no PATH. Reinstale-o com o comando `winget` em *Instalando sem o instalador*, ou use o caminho completo mostrado em *Rodando a suíte de testes*.
- **O OCR falha ou não produz texto.** Confira se o Tesseract e o Ghostscript estão instalados (o `install.ps1` confere) e se o pacote de idioma dos seus documentos está instalado (veja *OCR e idioma dos documentos*). Um arquivo cujo OCR falhou é refeito na próxima conversão.
- **O motor `local` cai para `rules`.** Só acontece numa máquina sem placa de vídeo: o Ollama não está rodando, ou a VRAM e a RAM somadas não bastam para o modelo. Não é um erro: o programa degrada de propósito em vez de falhar, e volta ao modelo quando o Ollama responder. Com placa de vídeo, ele espera o Ollama em vez de cair. A tela Sobre mostra o diagnóstico da instalação e o `ollama-serve.log` o que o servidor disse.
- **A placa de vídeo está quase vazia e a RAM cheia durante a classificação.** Veja no log qual backend está em uso e se o modelo coube. Numa Radeon RX 5000/6000, confira se `OLLAMA_FLASH_ATTENTION` está em `0` (o instalador faz isso); em qualquer placa, `LLAMA_ARG_CACHE_RAM=0` evita 8 GB de cache de prompts na RAM.
- **Nada funciona até eu reiniciar depois de instalar.** Corrigido: o instalador anota onde colocou cada programa e o `Indexer.bat` recarrega o PATH do registro. Numa instalação antiga, rode o `install.ps1` mais uma vez.
- **Reinstalei (ou formatei) e meus projetos sumiram da lista.** Não sumiram: estão nas pastas de saída deles, e só a lista foi recriada vazia. Use **Projetos > Abrir projeto existente** e aponte a pasta de saída. Nunca aponte o **Novo projeto** para uma pasta que já tem projeto: o programa impede.
- **Meus projetos não aparecem no outro computador.** Os projetos sincronizam pelo Drive, mas a lista fica em cada máquina até você configurar um catálogo compartilhado. Abra **Projetos > Catálogo compartilhado**, escolha uma pasta dentro do seu Drive e salve, nos dois computadores, apontando para a mesma pasta.
- **"Projeto em uso em outra máquina".** Feche o programa no outro computador. Se ele travou ou foi desligado, espere a trava expirar ou escolha **Assumir mesmo assim**, só se tiver certeza de que o outro não está usando.
- **"Sinal de sincronização incompleta" ao abrir um projeto numa segunda máquina logo depois da primeira.** Espere o Google Drive terminar antes de abrir em outro lugar. O programa detecta sincronizações incompletas e a trava de outra máquina, mas não substitui a espera.
- **Arquivos com falha nas pendências.** Em geral são arquivos protegidos por senha, corrompidos ou binários sem texto. Salve uma cópia sem proteção na pasta de origem e atualize o acervo.
- **A busca no LexML diz que o Senado pediu verificação.** O portal responde a programas com uma página de verificação; abra o link mostrado e faça a busca no navegador. O programa não contorna a verificação.

## Documentação

- [README.pt-BR.md](README.pt-BR.md): para que o programa serve e como começar.
- [QUALITY.pt-BR.md](QUALITY.pt-BR.md): o acerto medido contra um gabarito no acervo de demonstração, e o que os números não dizem.
- [CONTRIBUTING.pt-BR.md](CONTRIBUTING.pt-BR.md): preparação do ambiente de desenvolvimento, como rodar um único teste e as convenções do projeto.
- [SPECIFICATION.md](SPECIFICATION.md): a especificação técnica, em inglês: modelo de dados, cada etapa de processamento, regras de segurança e decisões de projeto.
- [CHANGELOG.pt-BR.md](CHANGELOG.pt-BR.md): o que mudou, versão por versão. O original é o [CHANGELOG.md](../CHANGELOG.md) em inglês; se divergirem, vale o inglês.
- [SECURITY.md](../SECURITY.md): como relatar uma vulnerabilidade (em inglês).
- [CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md): normas de convivência para quem contribui (em inglês).
- `demo/README.md` e `tools/README.md`: o acervo de demonstração e as ferramentas de linha de comando.
