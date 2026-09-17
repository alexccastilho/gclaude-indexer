# Fase 22 — "Importar e gerar relatórios" num drive de rede

Data: 2026-09-17 · Versão: 1.3.3 · Base: v1.3.2 (`2a516d8`)

## O relato

> "Instalei a versão 1.3.2, rodou o projeto, demorou 5h 18min, cliquei em
> 'Importar e gerar relatórios' e a janela fica só carregando e não abre a
> janela do resultado."

Pasta de saída: `H:\.shortcut-targets-by-id\...\CM\IA` — um drive virtual
do Google Drive.

## O que os dados diziam

A classificação **tinha terminado bem**. O log fechou às 22:00:57 com 1449
janelas, 5230 peças (alta=5059, media=171, **baixa=0**), 0 inválidas e 0
via fallback de regras — exatamente o que a fase 21 prometeu. O
`raw_items.jsonl` estava completo, com 2,9 MB.

Depois disso, nada. Nem uma linha de log, nem um `run` de `import` na
tabela, e `item` vazia. O `project.db` não era escrito desde as 22:00 e
não havia journal nem WAL: a importação estava presa **em leitura**, sem
ter gravado nada.

## A medição

O acervo tem 2904 páginas em 3 agrupadores. A distribuição é o que
importa:

| agrupador | páginas | peças |
|---|---|---|
| Solstic | 2830 | 5093 |
| Prestação de Contas - CFO | 44 | ~100 |
| TCU Nazareno 09-2026 | 30 | ~37 |

`_validate_range_within_group` pede ao banco **todas as páginas do
agrupador** para conferir que o intervalo da peça existe, e fazia isso
**uma vez por peça**. São 5230 consultas onde 3 bastariam, e 5093 delas
devolvem 2830 linhas cada — cerca de 14,8 milhões de conversões de
referência por importação.

Custo medido da mesma consulta, lado a lado:

| | por peça | importação inteira |
|---|---|---|
| SSD local | 9,3 ms | 45,2 s |
| Drive `H:` | 488 ms | ~41 min |

O drive de rede multiplica por **52**. Foi ele que transformou um defeito
de desempenho tolerável num travamento aparente.

## O segundo defeito, que o primeiro revelou

Um dump da pilha do servidor em produção (`py-spy dump`) mostrou **quatro**
threads em `import_and_generate` ao mesmo tempo.

```
Thread 30400 (idle): "AnyIO worker thread"
    _validate_range_within_group (gclaude_indexer\import_items.py:78)
    _read_and_validate_lines (gclaude_indexer\import_items.py:123)
    import_and_consolidate (gclaude_indexer\import_items.py:244)
    import_and_generate (gclaude_indexer\web\app.py:972)
```

…repetido para as threads 13428, 14552 e 26944.

A rota faz o trabalho **dentro do handler HTTP**, diferente das etapas do
pipeline, que passam pelo `task_manager`. Sem registro de tarefa, nada
conferia se já havia uma importação em andamento; sem barra de progresso,
nada dizia ao usuário que havia. Cada clique empilhou uma execução
completa, cada uma prestes a rodar `DELETE FROM item` seguido de 4210
inserções no mesmo arquivo SQLite.

As quatro terminaram sozinhas, entre 22:38 e 22:56, e todas gravaram o
mesmo resultado: 5230 linhas lidas, 0 inválidas, 4210 peças após
consolidação. Levaram de 36 a 54 minutos cada.

## As correções

**1. Cache do intervalo por agrupador.** O intervalo de páginas só depende
do agrupador, então é lido uma vez por agrupador e guardado durante a
corrida (`_group_page_range`). O cache vive no escopo de uma importação —
não é estado global, e não sobrevive a mudanças no acervo entre corridas.

Medido no mesmo acervo: **45,2s → 0,07s** em disco local e **~41 min →
0,59s** no Drive. Importação mais todos os relatórios: **0,21s**.

**2. Guarda de concorrência na rota.** Um clique que cai sobre uma
importação já em andamento vai direto para a tela de Resultado, em vez de
começar outra. É a proteção mínima equivalente à que o `task_manager` dá
às demais etapas.

## O que ficou de fora, deliberadamente

A rota continua síncrona, sem barra de progresso. Com 0,21s isso deixou de
ser um problema neste acervo, mas a causa do relato original — *a tela não
diz se está trabalhando* — só some de vez movendo a etapa para o
`task_manager`, com progresso próprio como as outras seis. Isso muda a UI
e o `step_state`, e fica para uma fase própria.

## Testes

`tests/test_phase22.py`, dois testes, ambos vistos falhando antes da
correção:

- `test_validacao_de_intervalo_consulta_as_paginas_uma_vez_por_agrupador`
  conta as consultas que chegam ao SQLite via `set_trace_callback` — conta
  o que o banco recebe, não a chamada de um helper que um refactor poderia
  renomear. Falhava com 6 consultas para 6 peças do mesmo agrupador.

- `test_importar_e_gerar_nao_roda_duas_vezes_ao_mesmo_tempo` prende a
  primeira importação e dispara a segunda pela rota real. Falhava com 2
  execuções, reproduzindo as 4 do servidor em produção.

640 testes passando, contra 638.
