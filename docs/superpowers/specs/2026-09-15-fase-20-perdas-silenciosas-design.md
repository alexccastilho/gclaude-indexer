# Fase 20 — Três perdas silenciosas na etapa 6 (design)

Documento escrito em 2026-09-15, junto com a implementação da versão
1.3.1. Descreve o estado do projeto no momento em que foi escrito e não é
editado depois para acompanhar mudanças posteriores — a mesma convenção
dos planos em `../plans/`.

Diferente das fases anteriores, esta não começou por um plano: começou por
um log. O dono do projeto trouxe a saída de uma indexação real e pediu que
as advertências e os erros fossem explicados. A análise virou a fase.

## 1. A corrida que motivou isto

Uma indexação de 15/09/2026, das 07:36 às 10:11 (2h35min):

| | |
|---|---|
| Acervo | 44 arquivos, 2904 páginas, 484 janelas |
| Modelo | `qwen3.5:4b`, 33 de 33 camadas na GPU |
| Placa | NVIDIA RTX 3060 Laptop, 6144 MB de VRAM |
| Resultado | 3542 peças (alta=2841, média=701, baixa=0), 20 inválidas |

**Nenhuma etapa falhou.** Varredura, conversão, extração e preparação de
janelas terminaram todas com `0 falhou(aram)`, e o motor local não caiu
para o motor de regras uma única vez (`0 via fallback 'regras'`). Era esse
o problema: os três defeitos abaixo não têm como se apresentar. Dois se
reportam como advertência no meio de centenas de linhas, e o terceiro se
reporta como nada.

## 2. Defeito 1 — a data descartava a peça inteira

### O sintoma

Vinte linhas de erro, todas da mesma forma:

```
raw_items.jsonl (motor local) janela Solstic::001075-001082:
    data fora do formato ISO (AAAA-MM-DD): '2020-01'
```

Os valores recusados foram `'2026-11'`, `'2026'`, `'2022-12'`, `'2020-01'`
(seis vezes), `'2019-12'` (duas), `'2020-12'`, `'2017-01'`, `'2021-08'`
(duas), `'2021-02'`, `'2025-05'`, `'2021-07-14 a 2021-07-15'` e
`'2021-09-31'`.

São exatamente 20, e o resumo final da corrida diz `20 inválida(s)`. Ou
seja: **toda peça recusada naquela corrida foi recusada por causa da
data.** Nenhuma por referência, tipo, faixa ou confiança.

### A causa

`classification.py` exigia `^\d{4}-\d{2}-\d{2}$`, e o chamador em
`engine_local.py` fazia `continue` — a peça não era escrita no
`raw_items.jsonl`. Resumo, tipo, autor e faixa de páginas iam junto, por
causa de um campo opcional.

O modelo não estava errando. Documentos contábeis e administrativos são
datados por período: a página diz "competência 01/2020" e ele devolve
`2020-01`, que é uma leitura fiel.

### A decisão de projeto

Três saídas foram consideradas:

1. **Anular o campo e manter a peça.** Não perde a peça, mas perde a
   informação de período, que estava correta e é útil.
2. **Completar para o primeiro dia** (`2020-01` → `2020-01-01`). Torna o
   campo uniforme, mas grava no índice um dia que o documento não afirma.
   Num acervo de prestação de contas lido para fins de auditoria, isso é
   fabricar um fato.
3. **Guardar a precisão reduzida como veio.**

A terceira foi escolhida, e o que decidiu foi um fato do código, não uma
preferência: `artifacts.py` ordena a linha do tempo com
`items.sort(key=lambda p: (p["date"], ...))` — ordenação lexicográfica de
texto. Datas ISO de precisão reduzida ordenam corretamente nesse esquema
(`2019-12` < `2020-01` < `2020-01-05`), que é uma propriedade da própria
ISO 8601. Não há, portanto, nada a ganhar completando a data: a única
função que o dia cumpriria já é cumprida sem ele.

`normalize_date` degrada um degrau por vez em vez de descartar:

| Entrada | Saída | Por quê |
|---|---|---|
| `2024-05-15` | `2024-05-15` | data completa e válida |
| `2020-01` | `2020-01` | competência; ISO 8601 de precisão reduzida |
| `2026` | `2026` | exercício |
| `2021-09-31` | `2021-09` | o dia não existe, o mês ainda é confiável |
| `2021-13` | `2021` | o mês não existe, o ano ainda é confiável |
| `2021-07-14 a 2021-07-15` | `None` | intervalo, não data |
| `15/05/2024` | `None` | não é ISO |

A normalização vive em `item_to_dict`, ao lado de `normalize_type`, que já
fazia o mesmo para o campo de tipo. É o ponto por onde todos os motores
passam antes da validação, então nenhum deles precisa saber disso.
`validate_item` continua existindo como rede de segurança e agora aceita
exatamente a forma canônica que `normalize_date` produziria.

## 3. Defeito 2 — a peça recusada levava as páginas junto

Este é o mais grave dos três, e só foi visível porque o primeiro existia.

O requisito central do sistema, declarado pelo dono e citado no próprio
código: o índice é lido para achar *em que PDF e em que página* está uma
informação. Uma página fora do índice é informação que ninguém mais
encontra.

O `classify_pending` cumpria isso com `_uncovered_pages` +
`_coverage_items` — para toda página que nenhuma peça cobrisse, uma peça
de cobertura de confiança baixa. Mas a ordem estava invertida:

```
1. classificar
2. calcular a cobertura e preencher os buracos   <- antes
3. validar cada peça e descartar as inválidas    <- depois
```

Na etapa 2 nada faltava, porque a peça inválida ainda estava lá. Na etapa
3 ela era descartada, e as páginas dela não eram cobertas por mais nada.
Não sobrava nem aviso: o log de cobertura já tinha decidido que estava
tudo certo.

Na corrida observada isso são as 20 faixas de páginas das 20 peças
recusadas. O `baixa=0` no resumo final confirma que nenhuma peça de
cobertura foi criada.

A correção é a troca de ordem — validar primeiro, calcular a cobertura
sobre o que sobreviveu. As duas correções são independentes, e esta
continua necessária mesmo com a primeira: qualquer motivo futuro de recusa
volta a produzir o mesmo buraco.

## 4. Defeito 3 — o contexto congelado na primeira janela

### O sintoma

Setenta e duas advertências assim, quase todas no mesmo documento:

```
janela Solstic::000391-000398: o modelo não respondeu sobre 8 de 8
    página(s) desta janela; elas entram no índice pelo agrupamento,
    com o texto da própria página.
```

72 de 484 janelas, ~15%. Como cada janela tem 8 páginas e avança de 6 em 6
(sobreposição de 2), são cerca de 430 páginas que chegaram ao índice sem
tipo, sem data e sem assunto — a maior parte das 701 peças de confiança
média.

### A causa

`plan_gpu_use` media a VRAM livre, escolhia o número de camadas e
calculava o `num_ctx`, tudo isso protegido por `if self._planned: return`.
A intenção era boa e está documentada no código: um `num_ctx` que muda faz
o Ollama recarregar o modelo entre janelas.

O efeito colateral é que a corrida inteira usava o contexto dimensionado
pela **primeira** janela. O log mostra isso numa linha só, às 07:39:37:
`contexto de 7168 tokens`, e nunca mais.

A conta em `context_tokens_for` reserva `8 × 220 = 1760` tokens para a
resposta. Sobram ~5400 tokens de prompt, ou ~16.200 caracteres — que é
exatamente o teto de 8 páginas × `chars_per_page` de 2000. Uma janela cujo
texto seja mais denso que o da primeira estoura isso; o Ollama trunca em
silêncio; o JSON não fecha; `_pages_json` devolve `[]`; e `faltantes`
vira 8 de 8.

Duas evidências sustentam o diagnóstico contra as alternativas:

- **Não era timeout.** O `GENERATION_TIMEOUT_S` é 120 s e um timeout
  levantaria `OllamaConnectionError`, caindo no motor de regras. O resumo
  diz `0 via fallback 'regras'`.
- **As janelas que falham demoram mais.** Cerca de 60 s cada, contra a
  média da corrida — geração correndo até o contexto acabar.

### A decisão de projeto

Manter a intenção original e remover só o congelamento: o contexto é
remedido quando uma janela precisa de mais que a mais larga até ali, e
**só cresce**. Janelas menores não o encolhem, então o modelo não
recarrega à toa; janelas maiores não são mais truncadas.

O replanejamento refaz também a contagem de camadas, e não só o
`num_ctx` — `gpu_budget.plan` calcula as camadas em função do contexto, e
aumentar um sem recalcular o outro é como se estoura a VRAM.

O modo CPU (`num_gpu == 0`) segue intocado: é o usuário pedindo a CPU de
propósito, e nenhuma medição passa por cima disso.

## 5. O que não foi alterado

- **O aviso de página não respondida continua.** Ele distingue um modelo
  que respondeu sobre tudo de um que respondeu sobre metade, e essa
  informação vale mesmo depois da correção.
- **O `_PROMPT`.** Nenhum dos três defeitos é do prompt, e mexer nele
  mudaria a qualidade da classificação junto com a correção, tornando as
  duas coisas impossíveis de avaliar em separado.
- **`chars_per_page` e `pages_per_window`.** Baixá-los seria um paliativo
  para o defeito 3 e mudaria o resultado de todo projeto existente.

## 6. Testes

18 testes novos em `tests/test_phase20.py`, escritos antes da
implementação. Os dois de integração reproduziam os defeitos com
precisão antes da correção:

- `test_pagina_de_peca_descartada_nao_fica_fora_do_indice` falhava com
  `assert set() == {1, 2}` — nenhuma página no índice.
- `test_janela_mais_densa_que_a_primeira_amplia_o_contexto` falhava com
  `assert 4096 > 4096` — o contexto congelado.

Suíte completa: 618 passando, contra 600.

## 7. Como verificar numa corrida real

Reprocessando a mesma coleção, no log da etapa 6:

- os erros `data fora do formato ISO` desaparecem, e o resumo final
  termina com `0 inválida(s)`;
- os avisos `o modelo não respondeu sobre 8 de 8 página(s)` ficam raros ou
  somem;
- `alta=` sobe e `media=` cai na mesma proporção, porque as janelas que
  antes não eram respondidas passam a ser classificadas.
