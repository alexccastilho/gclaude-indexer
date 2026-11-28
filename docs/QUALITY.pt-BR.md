**Leia no seu idioma:** Português (Brasil), você está aqui · **[English](QUALITY.md)** · **[Español](QUALITY.es.md)**

# Qualidade do índice: acerto medido contra um gabarito

Este documento publica o acerto do índice que o GClaude Indexer produz, medido
contra um gabarito conferido à mão, e diz o que cada número significa e o que
não significa. O quadro de qualidade da tela "Resultado" resume a **autoconfiança** que
o motor declara; o número daqui é outro: **se a peça está certa**.

Atualizado à mão a cada versão que mexa no classificador. Cada medição fica
na sua seção, com a versão e a data: a primeira, logo abaixo, é da
**versão 1.7.5 (02/11/2026)**; as seguintes (2.0.0, 2.1.0 e posteriores)
vêm depois de "Como ler".

## O que foi medido

- **Acervo:** `demo/acervo`, inteiramente fictício: 72 páginas, 41 peças, 7
  arquivos (dois volumes encadernados de um processo em PDF, um contrato, um
  memorando em Word, uma planilha, um ofício digitalizado em PNG e um e-mail).
  Treze tipos do vocabulário do motor de regras e sete peças sem tipo.
- **Gabarito:** `demo/gabarito.csv`: peça, tipo, data e autor de cada página.
- **Máquina:** desktop com Radeon RX 6000 (12 GB), Ollama 0.40.13 via
  Vulkan com flash attention desligada, Windows 11.
- **Comando:** `tools/indexar_pasta.py` seguido de `tools/medir_acerto.py`
  (a conta está em `gclaude_indexer/answer_key.py`).

## Resultado

| Motor | Páginas cobertas | Peças (gabarito / índice) | Precisão | Revocação | F1 | Tipo | Data | Autor | Tempo |
|---|---|---|---|---|---|---|---|---|---|
| Regras | 72/72 (100 %) | 41 / 42 | 85,7 % | 87,8 % | 86,7 % | 94,4 % | 50,0 % | 19,4 % | 4 s |
| Local, `qwen3.5:9b` | 72/72 (100 %) | 41 / 65 | 53,8 % | 85,4 % | 66,0 % | 60,0 % | 88,6 % | 84,4 % | 4 min 12 s |

**O que cada coluna significa.** *Páginas cobertas*: páginas do gabarito que
estão em alguma peça do índice; nenhuma página se perdeu em nenhum dos dois.
*Peça encontrada*: existe no índice uma peça do mesmo arquivo com pelo menos
metade das páginas em comum (Jaccard ≥ 0,5); uma peça de três páginas devolvida
como duas mais uma é erro de limite, não ausência. *Precisão*: encontradas ÷
peças do índice (cai quando o motor fatia). *Revocação*: encontradas ÷ peças do
gabarito (cai quando o motor funde). *Tipo*, *data* e *autor* são medidos só
entre as peças encontradas, para não cobrar duas vezes o erro de limite; data
e autor só onde o gabarito os tem. O tipo é comparado em maiúsculas e sem
acento, exatamente; o autor vale pelo sobrenome ou pela sigla.

## Como ler

- **O motor de regras acerta limites e tipos** porque o acervo, como um
  processo real, tem a maioria das peças com o tipo no cabeçalho, e o
  vocabulário das regras cobre esses cabeçalhos. Erra **data** (18 das 36
  peças encontradas: pega a primeira data do texto, muitas vezes uma data
  citada no corpo, não a da peça) e quase não acha **autor** (7 de 36: só
  reconhece assinatura depois de marcadores como "Atenciosamente"). Seis
  "peças a mais" são páginas em que uma palavra do vocabulário abre a linha
  no meio de outra peça ("PORTARIA nº 55/2026" dentro do edital).
- **O modelo local acerta data e autor** (31 de 35 e 27 de 32) e perde em
  limites: devolve, em geral, **uma peça por página** (30 peças a mais, daí
  a precisão de 54 %), e seis peças longas (termo de referência, edital,
  ata, recurso, dois contratos) não alcançam metade das páginas numa única
  peça. O **tipo** de 60,0 % tem três leituras: 7 das 14 divergências são um
  nome mais específico do tipo certo ("PARECER JURÍDICO" por PARECER,
  "NFS-E" por NOTA FISCAL, "TERMO ADITIVO" por TERMO), que a comparação
  exata não aceita; 4 são peças que o gabarito deixa sem tipo e o modelo
  nomeou ("PLANILHA", "EMAIL", "ATA DE REUNIÃO"); 3 são peças com tipo claro
  (TERMO) que o modelo devolveu sem tipo.
- **Nenhum dos dois é "melhor"** nesta tabela: um acerta onde o outro erra.
  É isso que a medida serve para mostrar, e é por onde as próximas fases
  podem começar (a data pelo motor de regras e a fragmentação pelo modelo são
  os dois maiores ganhos à vista).

## Sobreposição e teto de resposta (2.1.6, 27/11/2026)

A 2.1.6 baixou o teto da resposta do modelo (de 3 para 1,8 vez a reserva
por página; 3.168 tokens numa janela de 8 páginas) e remediu a sobreposição
entre janelas com o Melhor qualidade (`ornith-1.5:9b`), com a saída
estruturada. Máquina diferente das seções anteriores: um notebook com placa
de vídeo de 6 GB, em que o modelo roda parte na CPU (Ollama 0.40.16), por
isso os tempos são maiores e só valem para comparar as linhas entre si.
Uma rodada por linha (temperatura 0: as rodadas repetidas da 2.0.0 saíram
idênticas).

| Janela / sobreposição | Janelas | Peças (41) | F1 | Tipo | Data | Autor | Classificação |
|---|---|---|---|---|---|---|---|
| **8 / 2** (padrão) | 13 | 47 | **93,2 %** | 41,5 % | 87,8 % | 89,5 % | 28 min 27 s |
| 8 / 1 | 11 | 49 | 88,9 % | 50,0 % | 80,0 % | 81,1 % | 23 min 57 s |
| 10 / 1 | 8 | 41 | 100 % | 41,5 % | 85,4 % | 92,1 % | 25 min 26 s |
| 8 / 2, código da 2.1.5 | 13 | 47 | 93,2 % | 41,5 % | 87,8 % | 89,5 % | 29 min 39 s |

- **O padrão continua 8 / 2.** A sobreposição 1 economiza 16 % do tempo,
  mas o F1 caiu 4,3 pontos (duas peças fatiadas a mais e uma peça perdida),
  como na medição da 2.0.0. A regra era só trocar se o F1 não caísse.
- **10 / 1 acertou todas as peças e foi 11 % mais rápida**, com o mesmo tipo
  do padrão. É uma rodada num acervo de 72 páginas: fica como candidata a
  medir num processo real antes de virar padrão.
- **O teto menor não cortou nenhuma resposta**: nenhuma janela dividida,
  nenhuma página sem resposta, nos quatro casos. A última linha (o código
  anterior às mudanças do classificador da 2.1.6, mesma máquina) deu as
  mesmas peças e os mesmos campos.

## Perfis, saída estruturada e agrupamento (2.1.0, 18/11/2026)

A versão 2.1.0 oferece dois perfis para o modelo local, restringe a
resposta do modelo com um JSON Schema (saída estruturada do Ollama), mantém
numa peça só as páginas do mesmo tipo que o modelo marca como continuação
(mesmo arquivo, e não quando o tipo nomeia uma seção) e não manda ao modelo
bloco do projeto. Mesma máquina (Ollama 0.40.16), medido no
acervo de demonstração e num **processo real** (83 páginas, 15 PDFs, 16
documentos, gabarito feito à mão). O processo real é privado e não está no
repositório; os números dele não podem ser repetidos por terceiros, e por
isso o demo continua sendo a referência publicada.

| Perfil, placa de vídeo | Demo: F1 / peças (41) / tempo | Real: F1 / peças (16) / inícios achados / documentos exatos / fusões / tempo |
|---|---|---|
| Mais rápido (`qwen3.5:4b`) | 87,5% / 39 / 2 min 23 s | 46,2% / 36 / 14 de 16 / 9 / 2 / 3 min 26 s |
| Melhor qualidade (`ornith-1.5:9b`) | 100% / 41 / 5 min 38 s | 73,7% / 22 / 15 de 16 / 11 / 1 / 7 min 38 s |

Antes da regra de agrupamento, já com a saída estruturada: F1 no demo de
57,6% (Mais rápido) e 96,5% (Melhor qualidade); no processo real, 71 e 57
peças para 16 documentos, com 15 de 16 inícios e uma fusão nos dois. A regra
custou ao Mais rápido um início de documento e uma fusão no processo real, e
não custou nada ao Melhor qualidade. O `qwen3.5:9b`, padrão anterior para
placas de 8 GB ou mais, achou 12 de 16 inícios de documento no processo real
e juntou dois documentos.

O contexto do projeto no prompt, medido com o Melhor qualidade (F1, real /
demo): nenhum 73,7% / 100%; só o tipo de acervo 68,8% / 93,0%; só o perfil
do acervo 50,0% / 84,0%; os dois 60,6% / 94,1%. As duas linhas automáticas
saíram. Com o Tema preenchido (uma frase descrevendo cada acervo): 50,0% / 96,5%, 15 → 11
de 16 inícios e 1 → 3 fusões no real, embora o tipo tenha ido de 73% para
91% ali. Por isso o prompt por página não manda bloco do projeto; o Tema
vai para as instruções escritas para o Claude.

Sem placa de vídeo (só CPU e RAM, amostra de 9 páginas do demo, o grupo
Contratos): as mesmas peças e os mesmos campos da placa, em 136 s contra
40 s (Mais rápido) e 590 s contra 66 s (Melhor qualidade). Uns 15 s de cada
execução são as etapas anteriores à classificação, então a classificação em
si fica umas 5 vezes (Mais rápido) e 11 vezes (Melhor qualidade) mais lenta
na CPU. Uma execução inteira do Melhor qualidade na CPU sobre o processo de
83 páginas não terminou uma janela de 16 páginas em 30 minutos.

## Confiança baixa e janela (2.0.0, 17/11/2026)

A 2.0.0 tirou a "revisão de confiança baixa" (uma segunda passada inteira) e
passou a melhorar durante a passada única: página em branco (sem texto e sem
imagem) vira "PÁGINA EM BRANCO" com confiança alta sem ir ao modelo; página
com imagem e OCR de menos de 100 caracteres é lida de novo, uma vez, com o
modelo da escrita; sem Tema, o perfil do acervo entra no contexto; página
sem resposta (com as vizinhas) e página respondida sem tipo (com o texto
inteiro, do índice) têm uma segunda tentativa, no máximo uma por página e 15%
de pedidos a mais por execução; nas regras, a continuação de uma peça aberta
por marcador como `medium` foi medida, mas **não adotada**. O relatório (`medir_acerto.py`)
agora também divide peças e acerto **por nível de confiança**. Mesma máquina,
mesmo acervo, mesmos comandos (`--janela` e `--sobreposicao` são opções novas
de `indexar_pasta.py`).

| Execução | Peças (índice) | F1 | Tipo | Confiança alta / média / baixa (peças; tipo certo) |
|---|---|---|---|---|
| Regras, linha de base (1.10.4) | 42 | 86,7 % | 94,4 % | 23 (100,0 %; 17/17) / 2 (100,0 %; 2/2) / 17 (88,2 %; 15/17) |
| Regras, 2.0.0 (igual à base: a mudança não foi adotada) | 42 | 86,7 % | 94,4 % | 23 (100,0 %; 17/17) / 2 (100,0 %; 2/2) / 17 (88,2 %; 15/17) |
| Regras, continuação em `medium` (medido, não adotado) | 42 | 86,7 % | 94,4 % | 23 (100,0 %; 17/17) / 19 (89,5 %; 17/19) / 0 |
| Local `qwen3.5:9b`, linha de base (1.10.4, janela 16, sobreposição 2) | 71 | 62,5 % | 57,1 % | 53 (60,0 %; 18/30) / 18 (40,0 %; 2/5) / 0 |
| Local `qwen3.5:9b`, 2.0.0, janela 16, sobreposição 2 | 71 | 62,5 % | 57,1 % | 53 (60,0 %; 18/30) / 18 (40,0 %; 2/5) / 0 |
| Local `qwen3.5:9b`, 2.0.0, janela 8, sobreposição 2 (padrão novo) | 64 | 68,6 % | 44,4 % | 59 (44,4 %; 16/36) / 5 (sem peça encontrada) / 0 |

Comandos: `python tools/indexar_pasta.py demo/acervo <pasta> --motor rules` e
`... --motor local --modelo qwen3.5:9b [--janela 8 --sobreposicao 2]`, depois
`python tools/medir_acerto.py <pasta> demo/gabarito.csv`. A linha de base foi
indexada com o código do commit `a9a17e8` (antes de qualquer mudança da
2.0.0) e medida com a ferramenta nova, que só lê o `project.db`.

**Matriz janela × sobreposição (motor local, 3 rodadas por célula).** As três
rodadas de cada célula saíram **idênticas** (temperatura 0): a variação que
a seção abaixo descreve vem de mudar o texto, não de repetir a rodada.

| Janela / sobreposição | Janelas | Peças | F1 | Tipo | Data | Autor | Tempo |
|---|---|---|---|---|---|---|---|
| 8 / 1 | 11 | 67 | 64,8 % | 45,7 % | 94,3 % | 87,5 % | 4 min 0 s |
| **8 / 2** | 13 | 64 | **68,6 %** | 44,4 % | 86,1 % | 81,8 % | 4 min 32 s |
| 12 / 1 | 7 | 64 | **68,6 %** | 33,3 % | 83,3 % | 78,8 % | 3 min 42 s |
| 12 / 2 | 8 | 71 | 62,5 % | 34,3 % | 85,7 % | 78,1 % | 4 min 12 s |
| 16 / 1 | 6 | 71 | 62,5 % | 45,7 % | 80,0 % | 87,5 % | 3 min 50 s |
| 16 / 2 | 6 | 71 | 62,5 % | 57,1 % | 91,4 % | 84,4 % | 4 min 2 s |

A regra era ficar em 8 páginas, salvo se a janela 12 terminasse a menos de 1
ponto percentual do melhor F1 **e** acertasse o tipo com menos pedidos. A 12
empata no melhor F1 (12/1), mas acerta menos o tipo (33,3 % contra 44,4 %),
então a janela do motor local continua **8** (`auto_settings.WINDOW_LOCAL`),
com a sobreposição 2 que a 2.0.0 já usava para acervos de PDF. A janela 16
(a das versões 1.x) tem o pior F1. O tipo é o número que mais oscila com a
janela (de 33 % a 57 %): é o ponto fraco do modelo neste acervo, não da
janela.

**Por nível de confiança.** Nas regras, testamos deixar a continuação de uma
peça aberta por marcador em `medium`, em vez de rebaixar a peça inteira a
`low`. Antes da mudança, as 2 peças `medium` acertavam o tipo em 100 % e as 17
`low` em 88,2 %; com a mudança, as 19 `medium` ficaram em 89,5 % e a `low`
ficou vazia. **A mudança não foi adotada**: com 2 peças `medium` contra 17
`low` e um acervo sem nenhuma peça sem marcador de abertura, a amostra é
pequena demais para dizer que `medium` acerta mais que `low`, e a regra era só
mudar se a medição sustentasse (`engine_rules.CONTINUATION_KEEPS_MEDIUM`
fica `False`). No motor local a confiança não separa nada: 75 % a 92 % das peças saem
`high` e o tipo certo nelas (44 % a 60 %) é quase o mesmo das `medium`.

**A segunda tentativa não apareceu neste acervo.** Com 6 a 13 janelas, o
teto de 15 % de pedidos extras só libera o primeiro pedido extra depois do
sétimo pedido normal, e nenhuma rodada teve página sem resposta (todas as
páginas tinham texto, nenhuma estava em branco) nem peça sem tipo cujo texto
inteiro fosse maior que o da janela. Por isso as linhas 1.10.4 e 2.0.0 (16/2)
saíram iguais. O que a medida mostra aqui é o efeito da janela e do relatório
por confiança; o efeito da segunda tentativa só aparece em acervos maiores,
com páginas longas ou escaneadas.

## O que isto não diz

- **Acervo sintético.** Foi escrito para ter cabeçalhos limpos, texto
  digital legível e uma só digitalização de boa qualidade. Um acervo de verdade
  tem carimbos, páginas tortas, OCR ruim e tipos fora do vocabulário; o
  acerto lá é menor, e não se sabe quanto.
- **Uma máquina, um modelo, uma rodada.** Outro modelo, outro tamanho de
  trecho ou outra placa dão números diferentes; o modelo local pode variar
  com a versão do Ollama ou do modelo (na mesma máquina e com a mesma entrada,
  as rodadas de 2.0.0 saíram idênticas, a 0 de temperatura). Medido: uma segunda rodada em 2 de
  novembro, depois de trocar uma palavra nos textos, levou o tipo de 45,7 %
  a 60,0 %, a data de 91,4 % a 88,6 % e o autor de 78,1 % a 84,4 %, com os
  mesmos limites (F1 66,0 %). A tabela mostra a rodada sobre o acervo como
  está versionado.
- **A comparação de tipo é estrita de propósito.** Aceitar "PARECER
  JURÍDICO" como PARECER subiria o número do modelo para 80 %, mas
  esconderia que o índice sai com dois nomes para o mesmo tipo.
- **O classificador não foi ajustado para o acervo.** A regra da fase 37 foi
  medir primeiro, intocado; melhorar é outra fase, e a medida fica para dizer
  se melhorou.

## Como repetir

```
python tools/indexar_pasta.py demo/acervo <pasta> --motor rules
python tools/medir_acerto.py <pasta> demo/gabarito.csv --saida-md acerto.md

python tools/indexar_pasta.py demo/acervo <pasta2> --motor local --modelo qwen3.5:9b
python tools/medir_acerto.py <pasta2> demo/gabarito.csv --saida-md acerto2.md
```

O CI faz a primeira rodada a cada push e anexa `acerto.md` à execução; cobra
só a cobertura (100 %), não o acerto.
