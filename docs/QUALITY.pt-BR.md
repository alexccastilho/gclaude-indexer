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
- **Máquina:** desktop com Radeon RX 6700 XT (12 GB), Ollama 0.40.13 via
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
