# Fase 21 — Contexto calibrado e nota honesta (design)

A Fase 20 atacou o mecanismo certo com o número errado. Este documento
corrige o número, fecha um modo de falha que ninguém tinha visto, e
conserta a nota de qualidade que declarava 89/100 numa corrida com 11%
do índice cego.

## 1. A corrida que motivou isto

Indexação real na v1.3.1 — a versão que já traz a correção da Fase 20:

- 15/09/2026 19:56 → 16/09 00:13, **4h17**
- 44 arquivos, 2904 páginas, 1449 janelas, 3 grupos
- `qwen3.5:4b`, RTX 3060 Laptop (6144 MB), 33 de 33 camadas na GPU
- resumo final: `5443 peça(s) (alta=4666, media=777, baixa=0), 0 inválida(s)`

Nenhuma etapa falhou. O log encerra com `baixa=0` e `0 inválida(s)`, e é
exatamente esse o problema: **153 janelas foram classificadas às cegas** e
nada no relatório diz isso.

| | janelas | páginas | peças | sem `type` |
|---|---|---|---|---|
| janelas que falharam | 153 | 320 | 612 | **100%** |
| janelas boas | 1296 | 2584 | 4831 | 3% |

As 612 peças cegas são 11,2% do índice. Cada uma entra com `type`, `date`
e `author` nulos e o campo `summary` carregando o OCR cru da página:

> `"OUTORGANTE sob o título de honorários e, podendo, enfim, praticar
> todos os atos necessários pata o bom e fiel cumprimento deste mandato..."`

Estão no índice e são inencontráveis. Numa ferramenta cuja razão de
existir é dizer em que página está a informação, isso é a falha central.

## 2. Por que a Fase 20 não bastou

A Fase 20 diagnosticou o contexto congelado na primeira janela e corrigiu:
`plan_gpu_use` passou a remedir quando uma janela precisa de mais que a
mais larga até ali. O mecanismo funciona. O que não funciona é a
estimativa que o alimenta.

`context_tokens_for` converte caracteres em tokens por uma constante:

```python
_CHARS_PER_TOKEN = 3.0
```

O comentário que a acompanha diz que ela é "deliberadamente baixa" porque
"as razões reais em prosa portuguesa ficam perto de 4". Medido no acervo,
contra o tokenizador do próprio modelo:

| conteúdo | razão real | janelas |
|---|---|---|
| prosa | 2,62 – 3,57 | todas passaram |
| tabelas contábeis, datas, valores | **1,45 – 1,65** | todas falharam |

A correlação não tem uma exceção em 14 amostras. Números e datas
tokenizam a menos da metade da prosa, e o acervo é um processo com
volumes inteiros de prestação de contas.

O efeito: o recálculo por janela roda, e chega curto toda vez.

| janela | tokens reais | v1.3.1 calculou | precisava |
|---|---|---|---|
| `Solstic::000417-000420` | 5091 | 4096 | 6144 |
| `Solstic::000849-000852` | 6362 | 5120 | 8192 |
| `Solstic::000427-000430` | 5573 | 4096 | 7168 |

Confere com o histórico: a corrida anterior à Fase 20 perdeu 72 de 484
janelas (14,9%); esta, 153 de 1449 (10,6%). Melhorou e não resolveu — a
assinatura de um conserto que acertou o mecanismo e errou o número.

## 3. Defeito 1 — a razão caracteres/token é uma constante chutada

### O sintoma

Prompt maior que o `num_ctx` pedido. O Ollama trunca em silêncio, o modelo
não recebe o bloco de instruções, inventa o próprio esquema JSON e
`_pages_json` devolve zero linhas.

Bancada, mesma janela, mesmo modelo, prompt real:

| `num_ctx` | `prompt_eval` | `eval` | páginas lidas | tempo |
|---|---|---|---|---|
| 4096 | 2050 de 5091 — **truncado** | 1588 | **0/4** | 28s |
| 6144 | 5091 — íntegro | 422 | **4/4** | 14s |

Em 4096 o modelo devolveu `{"document_type": "Financial Statement",
"sections": [...]}` — esquema que ele inventou por nunca ter visto o
gabarito. E gastou 1588 tokens divagando contra 422 úteis: a janela
truncada custa **o dobro do tempo** da janela que funciona.

### A causa

Uma constante não descreve um acervo. O mesmo projeto tem prosa a 3,3 e
tabela a 1,45; qualquer valor fixo estará errado para metade dele.

### A decisão de projeto

**Calibrar durante a corrida, com o dado que o Ollama já devolve e o
código joga fora.** Toda resposta traz `prompt_eval_count`. Numa chamada
íntegra, isso é a contagem exata de tokens daquele prompt — verdade de
campo, do tokenizador real, sobre o conteúdo real.

O motor mantém `_chars_per_token` como o **mínimo observado** até ali:

- semente de 3,0 apenas para a primeira janela, quando não há dado;
- após cada janela íntegra, `observado = len(prompt) / prompt_eval_count`;
- `_chars_per_token = min(_chars_per_token, observado)`, com piso de 1,2
  para que um valor patológico não infle o contexto de tudo.

O mínimo, e não a média, porque o custo de superestimar é um pouco de
VRAM e o custo de subestimar é uma janela perdida. É a mesma assimetria
que o comentário original invocava; ele só resolveu com um palpite onde
cabia uma medição.

A monotonicidade da Fase 20 fica: o contexto só cresce, para o Ollama não
recarregar o modelo entre janelas.

## 4. Defeito 2 — a resposta sem orçamento

### O sintoma

Descoberto na bancada, varrendo a mesma janela por vários `num_ctx`:

| `num_ctx` | `prompt_eval` | `eval` | páginas |
|---|---|---|---|
| 2048 | 1026 | 1022 | 0/4 |
| 3072 | 1538 | 1534 | 0/4 |
| 4096 | 2050 | 1588 | 0/4 |
| **5120** | **5091 — íntegro** | **29** | **0/4** |
| 6144 | 5091 | 422 | 4/4 |

Em 5120 o prompt **coube inteiro** e sobraram 29 tokens para responder. O
JSON foi cortado na primeira linha. No log isso aparece como
`"o modelo não respondeu sobre 4 de 4 página(s)"` — mensagem idêntica à do
truncamento, causa oposta.

Uma correção que só olhasse o tamanho do prompt deixaria essa passar.

### A causa

Nada, no código. A fórmula `prompt + páginas × 220` está certa: 5091 + 880
= 5971 → 6144, que é exatamente o valor que funciona. Ela só nunca é
alimentada com o `prompt` verdadeiro. Este defeito é uma consequência do
anterior, e vale documentado porque exige que a detecção olhe os dois
lados, e não só o prompt.

### A decisão de projeto

A detecção passa a ler as duas grandezas da telemetria:

```
prompt_eval ≈ num_ctx / 2        → prompt cortado
prompt_eval + eval ≈ num_ctx     → resposta sem orçamento
```

A primeira assinatura é exata e estável — o Ollama trunca o prompt em
metade do contexto, medido em 1026/2048, 1538/3072 e 2050/4096, todos a
0,50. Não é heurística.

## 5. A escada de retentativa

O sintoma que dispara é um só: **`linhas devolvidas < páginas da janela`**.
A causa se lê na telemetria, e a ação é sempre a mesma — mais contexto.

| tentativa | `num_ctx` | origem do valor |
|---|---|---|
| 1 | estimativa calibrada | `_chars_per_token` corrente |
| 2 | corrigido | `prompt_eval` medido na 1ª + páginas × 220 |
| 3 | janela subdividida ao meio | cada metade classificada em separado |
| — | esgotou | **erro explícito**, não advertência |

Na janela medida, a tentativa 2 resolve: `prompt_eval` 2050 com razão 0,50
denuncia o corte, o motor sobe para 8192 e sai 4/4.

**Teto da placa.** `gpu_budget.plan` mantém 33 de 33 camadas na GPU até
8192; em 12288 já não planeja. O teto é medido uma vez por corrida, junto
com o plano de GPU, e o contexto nunca o ultrapassa. Uma janela que
precise de mais é subdividida, e não empurrada para a RAM: o acervo tem
1449 janelas, e uma janela seis vezes mais lenta multiplicada por algumas
centenas custa horas.

**Custo.** Uma chamada extra em 153 de 1449 janelas. Como as janelas
truncadas hoje já custam o dobro, a expectativa é empate ou ganho.

## 6. Defeito 3 — a cobertura não mede cobertura

### O sintoma

A nota desta corrida seria **89/100**, com a maior fatia — 40 pontos de
cobertura — paga por inteiro:

```
cobertura      40 × 1.000 = 40.0
confiança      35 × 0.943 = 33.0
preenchimento  25 × 0.653 = 16.3
                        89/100
```

### A causa

São duas, independentes.

**A consulta compara numerações diferentes.** Em `quality.py`:

```sql
SELECT COUNT(*) FROM page
WHERE EXISTS (
    SELECT 1 FROM item
    WHERE page.number BETWEEN item.start_order AND item.end_order
)
```

`page.number` é a página **dentro do arquivo** (1..391 no maior PDF do
acervo). `item.start_order` é a folha **global do grupo** (1..2830). Não há
join por grupo nem por arquivo: a consulta cruza dois sistemas de
numeração de arquivos sem relação entre si.

Medido, removendo do índice 967 peças — um buraco real de 500 folhas:

| | consulta atual | consulta correta |
|---|---|---|
| índice completo | 100,0% | 100,0% |
| índice mutilado | **100,0%** | **82,7%** |

A métrica é cega ao buraco que ela existe para detectar. O comentário no
código diz que ela foi criada porque "a nota não olhava para o buraco".
Ela continua não olhando.

**E a métrica é tautológica.** Mesmo consertada, ela sempre daria 100%
para o motor local: `_group_pages_into_items` percorre as páginas da
janela, não as linhas do modelo, e emite uma peça para cada página
aconteça o que acontecer. A página está sempre dentro de alguma peça. A
métrica pergunta *"a página está no índice?"* quando a pergunta que
importa é *"o índice diz algo útil sobre esta página?"*.

Essa garantia de cobertura é boa e não será mexida — foi ela que impediu a
perda das 320 páginas. O defeito é a nota ter confundido a rede de
segurança com sucesso.

### A decisão de projeto

1. **Corrigir a consulta**: casar folha com folha, dentro do mesmo grupo.
2. **Cobertura vira cobertura classificada**: os 40 pontos passam a medir
   páginas que o modelo descreveu, não páginas que ocupam uma linha.

```
                    antes         depois
cobertura      40 × 1.000 = 40.0   40 × 0.890 = 35.6
confiança      35 × 0.943 = 33.0   35 × 0.898 = 31.4
preenchimento  25 × 0.653 = 16.3   25 × 0.653 = 16.3
                        89/100              83/100
```

## 7. Defeito 4 — a peça cega entra como `medium`

Em `engine_local.py`, hoje:

```python
confianca = "high" if dados.get("type") and dados.get("detail") else "medium"
```

`dados` é a linha que o modelo devolveu para aquela página — ou um
dicionário vazio, quando ele não disse nada. Os dois casos caem no mesmo
`medium`.

Por isso o log fecha com `baixa=0` e o aviso `coverage_filled` nunca
dispara: `_uncovered_pages` não encontra página descoberta, porque
nenhuma está descoberta. As 612 peças cegas ficam indistinguíveis das 166
legitimamente medianas.

Passa a distinguir três casos:

```
linha do modelo, com tipo e detalhe  → high
linha do modelo, incompleta          → medium
nenhuma linha para esta página       → low     ← hoje não existe
```

Sem migração de esquema: `low` já é um valor válido da coluna. É o que
devolve sentido ao `baixa=` do resumo e o que alimenta a cobertura
classificada da seção anterior.

## 8. Defeito 5 — do índice não se chega à página

O `index.md` é colado num Projeto do Claude, e é dele que sai a resposta a
"em que página está tal coisa". Três lacunas:

**A folha não leva à página física.** A linha diz
`f. 417 | … | Conselho Federal de Odontologia Vol 2.pdf`. Mas `f. 417` é a
**página 145** daquele PDF, e o grupo Solstic são 21 arquivos. O dado
existe em `page.number` e não é exposto. A coluna de faixa passa a trazer
a origem física: `f. 417 (Vol 2.pdf, p. 145)`.

**A linha cega não se anuncia.** Com as seções anteriores elas ficam
raras; quando existirem, a confiança `baixa` na linha diz ao consumidor
que ali se abre o PDF em vez de confiar no resumo.

**O arquivo é grande demais.** 5443 linhas, **1,58 MB**. O `index.md`
passa a ser um sumário dos grupos, e cada grupo ganha o seu
`index-<grupo>.md`:

```
index.md              sumário, ~5 KB
  Solstic               f. 1–2830   21 PDFs
  Prestação de Contas   f. 1–44      1 PDF
  TCU Nazareno          f. 1–30      1 PDF

index-Solstic.md      ~1,5 MB
index-Prestacao.md    ~15 KB
index-TCU.md          ~10 KB
```

O `claude_package.py` passa a incluir os arquivos por grupo, e o
`project_instructions.md` a explicar o caminho: ler o sumário, escolher o
grupo, abrir o índice daquele grupo.

## 9. O que não será alterado

- **O `_PAGE_PROMPT`.** Nenhum destes defeitos é do prompt, e mexer nele
  misturaria mudança de qualidade com correção de defeito, tornando as
  duas impossíveis de avaliar em separado. Mesma razão da Fase 20.
- **A garantia de cobertura em `_group_pages_into_items`.** É ela que
  impediu a perda das 320 páginas. O que muda é a nota parar de tratá-la
  como sucesso.
- **`chars_per_page` e `pages_per_window`.** Baixá-los seria paliativo e
  mudaria o resultado de todo projeto existente.
- **O modo CPU (`num_gpu == 0`).** O usuário pediu a CPU de propósito.
- **O aviso de página não respondida.** Continua, e agora acompanhado da
  ação que foi tomada.

## 10. Ordem de implementação

Os cinco defeitos são independentes no código, mas não na avaliação. A
ordem é parte do projeto:

**Primeiro a medição, depois a correção.** Defeitos 3 e 4 — a consulta de
cobertura e a peça cega como `medium` — entram antes dos demais. Sem eles
não há linha de base honesta: a corrida atual vale 89 por uma métrica
quebrada, e qualquer ganho medido contra 89 é ficção. Corrigida a
medição, a mesma corrida vale 83, e é sobre 83 que o resto precisa
mostrar resultado.

**Depois a classificação.** Defeitos 1 e 2 mais a escada de retentativa,
que é o que de fato recupera as 320 páginas.

**Por último o índice.** Defeito 5 não altera o que é classificado, só
como o resultado é consultado — pode entrar sem interferir na aferição
dos outros quatro.

Cada parte fecha com a suíte verde antes da seguinte começar.

## 11. Testes

Escritos antes da implementação, em `tests/test_phase21.py`. Os que
reproduzem defeito devem falhar antes da correção:

| teste | falha esperada antes |
|---|---|
| `test_razao_calibra_com_prompt_eval_count` | razão fica em 3,0 |
| `test_janela_tabular_recebe_contexto_suficiente` | `assert 4096 >= 6144` |
| `test_resposta_sem_orcamento_dispara_retentativa` | nenhuma retentativa |
| `test_prompt_truncado_detectado_por_metade_do_contexto` | não detecta |
| `test_janela_acima_do_teto_e_subdividida` | estoura o teto |
| `test_pagina_sem_linha_do_modelo_recebe_confianca_baixa` | vem `medium` |
| `test_cobertura_casa_folha_com_folha_do_mesmo_grupo` | 100% no mutilado |
| `test_cobertura_classificada_ignora_pecas_cegas` | 100% com peça cega |
| `test_indice_traz_pagina_fisica_do_pdf` | só o nome do arquivo |
| `test_indice_por_grupo_com_sumario` | arquivo único |

Suíte completa: 618 passando hoje.

## 12. Como verificar numa corrida real

Reprocessando o mesmo acervo na 1.3.2:

- o aviso `o modelo não respondeu sobre N de N página(s)` some, ou vem
  seguido da retentativa que o resolveu;
- o resumo da etapa 6 deixa de terminar em `baixa=0` quando houver página
  cega, e `baixa=0` volta a significar o que diz;
- `alta=` sobe das 4666 atuais, `media=` cai das 777;
- a nota de qualidade cai antes de subir — 89 era falso, 83 é o valor
  honesto do resultado atual, e é sobre 83 que a correção precisa mostrar
  ganho;
- `index.md` abre como sumário, e `f. 417` leva a `Vol 2.pdf, p. 145`.
