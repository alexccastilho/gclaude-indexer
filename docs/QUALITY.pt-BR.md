**Leia no seu idioma:** Português (Brasil), você está aqui · **[English](QUALITY.md)** · **[Español](QUALITY.es.md)**

# Qualidade do índice: acerto medido contra um gabarito

Este documento publica o acerto do índice que o GClaude Indexer produz, medido
contra um gabarito conferido à mão, e diz o que cada número significa e o que
não significa. A tela "Qualidade" do programa resume a **autoconfiança** que
o motor declara; o número daqui é outro: **se a peça está certa**.

Atualizado à mão a cada versão que mexa no classificador. Última medição:
**02/11/2026, versão 1.7.5** (o classificador, o prompt e as regras são os
mesmos da 1.7.4; a fase 37 só acrescentou a medida).

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

## Confiança baixa e janela (2.0.0, 17/11/2026)

A 2.0.0 tirou a "revisão de confiança baixa" (uma segunda passada inteira) e
passou a melhorar durante a passada única: página em branco (sem texto e sem
imagem) vira "PÁGINA EM BRANCO" com confiança alta sem ir ao modelo; página
com imagem e OCR de menos de 100 caracteres é lida de novo, uma vez, com o
modelo da escrita; sem Tema, o perfil do acervo entra no contexto; página
sem resposta (com as vizinhas) e página respondida sem tipo (com o texto
inteiro, do índice) têm uma segunda tentativa, no máximo uma por página e 15%
de pedidos a mais por execução; nas regras, a continuação de uma peça aberta
por marcador deixou de rebaixá-la a `low`. O relatório (`medir_acerto.py`)
agora também divide peças e acerto **por nível de confiança**. Mesma máquina,
mesmo acervo, mesmos comandos (`--janela` e `--sobreposicao` são opções novas
de `indexar_pasta.py`).

| Execução | Peças (índice) | F1 | Tipo | Confiança alta / média / baixa (peças; tipo certo) |
|---|---|---|---|---|
| Regras, linha de base (1.10.4) | 42 | 86,7 % | 94,4 % | 23 (100,0 %; 17/17) / 2 (100,0 %; 2/2) / 17 (88,2 %; 15/17) |
| Regras, 2.0.0 | 42 | 86,7 % | 94,4 % | 23 (100,0 %; 17/17) / 19 (89,5 %; 17/19) / 0 |
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

**Por nível de confiança.** Nas regras, a continuação de uma peça aberta por
marcador passou a `medium`: as 17 peças que antes eram `low` acertavam o
tipo em 88,2 %, e as `medium` de agora (19) em 89,5 %, abaixo das `high`
(100 %), então a ordem alta > média > baixa se mantém e a mudança ficou. A
base é pequena (2 peças `medium` antes da mudança) e o acervo não tem peça
sem marcador de abertura, então a `low` das regras ficou vazia: não dá para
dizer, só com estes números, que `medium` continua acima de `low` onde `low`
existe. No motor local a confiança não separa nada: 75 % a 92 % das peças saem
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
  trecho ou outra placa dão números diferentes; o modelo local não é
  determinístico entre rodadas. Medido: uma segunda rodada em 2 de
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
