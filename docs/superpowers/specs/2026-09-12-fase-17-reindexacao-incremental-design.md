# Fase 17 — Reindexação incremental (design)

Documento de design escrito antes da implementação, em 2026-09-12, para a
versão 1.1. Descreve o estado do projeto no momento em que foi escrito e
não é editado depois para acompanhar mudanças posteriores — a mesma
convenção dos planos em `../plans/`.

## 1. O problema

Um acervo não é estático. Chegam documentos novos, um arquivo é
substituído por uma versão corrigida, outro é retirado da pasta. Hoje,
para que o índice acompanhe qualquer uma dessas coisas com segurança, o
usuário precisa reindexar o acervo inteiro — pagando de novo o OCR e a
classificação de tudo o que não mudou.

A versão 1.1 entrega a atualização incremental: detectar o que mudou na
pasta de origem, invalidar exatamente o que a mudança afeta, e reprocessar
só isso.

## 2. O que já funciona hoje

Isto não estava documentado em lugar nenhum e é a base do design: **o
pipeline já é quase todo incremental**.

- `scanning.py` compara o `sha256` por caminho. Arquivo inalterado é
  pulado; novo entra como `discovered`; alterado é atualizado e volta para
  `discovered`; conteúdo repetido sob outro caminho entra como
  `duplicate`.
- `conversion.py` — a etapa do OCR, a mais cara — só seleciona
  `status = 'discovered'`.
- `extraction.py` pula os arquivos já `extracted`, lendo o `page_count`
  deles apenas para manter a numeração de folhas correta dentro do grupo.
- `windows_prep.py` não recria janela cuja chave já existe.
- Os engines de classificação só processam janelas com `status = 'pending'`.
- `import_items.py` e `artifacts.py` reconstroem tudo do zero, mas são
  baratos.

Acrescentar documentos que caiam no **fim** de um grupo, portanto, já
funciona — por acidente, sem nada na interface que o diga.

## 3. Onde quebra

1. **Arquivo alterado falha.** O scan devolve o arquivo para `discovered`,
   mas as `page` antigas dele nunca são apagadas. A reextração executa
   `INSERT INTO page` sobre as mesmas `(file_id, number)`, viola o
   `UNIQUE` e o arquivo termina marcado `failed`.

2. **Arquivo apagado nunca sai.** Nada remove a linha `file`. Suas páginas
   e itens continuam no índice apontando para um documento que não existe
   mais.

3. **Inserção no meio corrompe em silêncio.** A chave da janela é
   `f"{grupo}::{start+1:06d}-{end:06d}"` — posição dentro do grupo, não
   conteúdo. Inserir um documento no meio desloca todas as páginas
   seguintes, mas as chaves continuam iguais; o
   `SELECT 1 FROM window WHERE key = ?` encontra cada uma e a marca como
   existente. As janelas nunca são reclassificadas, e o índice passa a
   atribuir classificações antigas a páginas erradas, sem nenhum aviso.

4. **Renumeração de folhas.** Fora do modo biblioteca, a referência de uma
   página é `f. N`, contada correndo dentro do grupo inteiro. Um arquivo
   que ganha ou perde páginas desloca a numeração de todos os arquivos
   posteriores do grupo; as `reference` já gravadas ficam erradas e os
   itens as citam.

5. **Não há porta de entrada.** Nada informa que a pasta de origem mudou.

## 4. Escopo

**Dentro:** documentos novos, alterados e removidos.

**Fora:** mudança de configuração (troca de engine, de modelo, de tamanho
de janela) como gatilho de invalidação. Continua exigindo reindexação
completa.

## 5. Abordagem

Três opções foram consideradas.

**A — invalidar o grupo inteiro.** Qualquer mudança apaga janelas e itens
de todo o grupo do arquivo. Trivial de implementar, sem mudança de
esquema. Descartada porque com `group_mode = "all_together"` o grupo é o
acervo inteiro: acrescentar um documento reclassificaria tudo. A 30,8 s
por janela, um acervo de 500 páginas custaria horas para absorver uma
página nova — é a versão 1.1 que não entrega a versão 1.1.

**B — rechavear a janela por conteúdo.** Trocar a chave posicional por um
hash do texto das páginas cobertas. Descartada porque não economiza nada:
a janela tem tamanho fixo sobre as páginas concatenadas do grupo, então
inserir páginas no meio desloca a fronteira de todas as janelas seguintes
e o conteúdo de cada uma realmente muda. Pagar-se-ia uma migração de
esquema — rechavear as janelas concluídas de todos os projetos existentes
— para obter exatamente o mesmo custo da opção C.

**C — invalidar a partir do ponto de divergência.** ✅ **Escolhida.**
Mantém a chave posicional. Antes de reconstruir as janelas de um grupo,
compara-se a nova sequência de páginas com a armazenada e acha-se a
primeira posição em que elas divergem. Tudo antes dela é preservado; da
divergência em diante as janelas são apagadas e recriadas como `pending`.

Um documento acrescentado ao fim do grupo diverge só no fim: reclassifica-
se apenas a cauda. Um documento inserido no começo reclassifica tudo, mas
aí é inevitável, porque as janelas seguintes passam a cobrir páginas
genuinamente diferentes. O custo é o mínimo teórico para este formato de
janela.

Ao contrário da opção B, C **não toca nas janelas já gravadas**: nada é
rechaveado, nada do que os projetos existentes já classificaram precisa
ser reconstruído. As duas adições de esquema que a funcionalidade faz
(§7.3) servem a outras partes dela — relatar removidos e acelerar a
detecção — e ambas são aditivas, sem migração de dados.

## 6. Arquitetura

A atualização **não é uma sexta etapa** nem um modo paralelo do pipeline.
É uma operação de invalidação que roda antes das etapas existentes e
devolve o banco a um estado que elas já sabem tratar. A sequência das
cinco etapas (`scan`, `conversion`, `extraction`, `windows`,
`classification`), o contrato entre elas e os critérios pelos quais cada
uma escolhe o que processar permanecem exatamente como estão. As únicas
mudanças dentro de uma etapa são duas correções cirúrgicas em
`windows_prep` (§7.2 e §10), ambas defeitos que a atualização incremental
revela e que existem hoje.

**Fase 1 — plano (somente leitura).** Compara a pasta de origem com o
banco e produz um `UpdatePlan`. Não escreve nada, nem no banco nem no
disco. É por ser somente leitura que pode rodar ao abrir o projeto sem
consequência.

**Fase 2 — invalidação (transacional).** Aplica o plano aprovado. Ou o
banco termina íntegro no estado novo, ou continua íntegro no antigo.

**Fase 3 — reexecução.** O pipeline existente roda sem alteração.

A invalidação é "deste ponto do grupo em diante", e não "deste arquivo",
por causa da renumeração de folhas descrita em §3.4: não há como consertar
apenas o arquivo que mudou.

**A economia que isso permite:** os arquivos posteriores à divergência que
não mudaram precisam apenas ser renumerados, não reconvertidos. Eles
voltam para `converted`, não para `discovered`, e a extração os relê a
partir do artefato já gravado em `<saída>/converted/` — **o OCR não roda
de novo**. Só o arquivo que realmente mudou volta para `discovered` e paga
OCR.

## 7. Componentes

### 7.1 Módulos novos

**`gclaude_indexer/update_plan.py`** — somente leitura.

- `FileChange(relative_path, kind, name, size)`, com `kind` em
  `new | changed | removed`.
- `GroupInvalidation(group_key, first_divergent_page, windows_discarded,
  windows_kept, files_to_renumber)`.
- `UpdatePlan(new, changed, removed, groups, unchanged_count,
  fingerprint)`.
- `build_update_plan(conn, config) -> UpdatePlan`.

O cálculo da divergência: para cada grupo atingido, reconstrói-se a ordem
pretendida dos arquivos (ordenação natural por `relative_path`, a mesma de
`extraction._build_groups`) e compara-se posição a posição com a ordem
armazenada. A primeira posição em que a identidade do arquivo ou a
contagem de páginas dele difere é a divergência. Essa posição é convertida
em página e a página no índice da primeira janela afetada, pela mesma
aritmética que `windows_prep` usa.

**`gclaude_indexer/invalidation.py`** — transacional.

`apply_update_plan(conn, config, plan, language) -> InvalidationResult`,
nesta ordem:

1. Apaga as `window` do índice de divergência em diante, por grupo, e
   remove os `.txt` correspondentes.
2. Apaga as `page` dos arquivos removidos e depois suas linhas `file`;
   registra cada um em `removed_file`.
3. Apaga as `page` dos arquivos alterados e dos que só precisam renumerar.
4. Repõe o `status`: `discovered` para quem mudou de verdade,
   `converted` para quem só é renumerado.

Não mexe em `item`: `import_items` já apaga e reconstrói.

### 7.2 Módulos alterados

- **`db.py`** — tabela `removed_file`; coluna `file.mtime`.
- **`scanning.py`** — o caminhamento da pasta e as regras de exclusão
  (`desktop.ini` e afins) saem para uma função reutilizável, usada também
  pelo plano. Se o plano e o scan andarem por critérios diferentes, o
  plano mente. Sem mudança de comportamento.
- **`windows_prep.py`** — a aritmética de janela (`start`, `step`, formato
  da chave) sai para uma função pura compartilhada com o plano, pelo mesmo
  motivo. `pages_for_group` passa a ordenar deterministicamente por
  caminho natural e número de página, em vez de `ORDER BY page.id`: hoje
  os dois coincidem, mas depois de uma atualização não coincidiriam, e um
  documento corrigido saltaria para o fim do índice. A ordenação natural
  não se exprime em SQL, então a ordem final é aplicada em Python com o
  mesmo `_natural_sort_key` que `extraction` já usa — a função sai de lá
  para um lugar comum, em vez de ser reescrita. E o `.txt` da janela
  passa a ser gravado incondicionalmente quando é `windows_prep` quem cria
  a linha (ver §10).
- **`artifacts.py::generate_review_md`** — seção de documentos removidos,
  lida de `removed_file`.
- **`web/app.py`** — duas rotas novas (§9).

### 7.3 Esquema

Aditivo, sem migração de dados.

```sql
CREATE TABLE IF NOT EXISTS removed_file (
    id            INTEGER PRIMARY KEY,
    relative_path TEXT NOT NULL,
    name          TEXT NOT NULL,
    removed_at    TEXT NOT NULL
);
```

`db.py` usa `CREATE TABLE IF NOT EXISTS` e o schema é reexecutado a cada
abertura de projeto, então projetos vindos da 1.0.1 ganham a tabela
sozinhos na primeira abertura.

A coluna `file.mtime` entra por `_ensure_file_mtime_column`, no molde do
`_ensure_event_message_columns` já existente: `ALTER TABLE` guardado por
`PRAGMA table_info`, para que chamar `init_schema` duas vezes nunca
levante "duplicate column name".

## 8. Fluxo dos dados

### 8.1 Detecção

O plano caminha a pasta e faz um `stat` por arquivo — tamanho e data de
modificação:

- Caminho conhecido, tamanho **e** mtime iguais → inalterado, não calcula
  hash. É o caso da grande maioria dos arquivos e o que torna a detecção
  viável.
- Caminho conhecido, tamanho **ou** mtime diferentes → candidato: calcula
  o `sha256` e compara. Se o hash bate, está inalterado. O Google Drive
  reescreve mtime em arquivo cujo conteúdo não mudou, e sem essa segunda
  checagem o plano gritaria "mudou" o tempo todo — que é o pior defeito
  que um aviso pode ter. É a mesma lição já registrada em `staleness.py`.
- Caminho desconhecido → novo, ou duplicata se o hash já existir sob outro
  caminho.
- Caminho no banco e ausente do disco → removido.

Em projeto vindo da 1.0.1 a coluna `mtime` nasce nula, então a **primeira**
atualização calcula o hash de tudo uma vez e grava os mtimes; da segunda
em diante a detecção é rápida.

### 8.2 Exemplo

Acervo de 500 páginas num único grupo, janela de 16 com sobreposição de 2
— 36 janelas, cerca de 18,5 min de classificação a 30,8 s por janela. O
usuário acrescenta um documento de 10 páginas ao fim.

Pela invalidação por grupo (opção A), as 36 janelas voltam para a fila:
18,5 min.

Pela divergência (opção C), muda a página 501 em diante. Com passo de 14,
as 35 primeiras janelas cobrem exatamente as mesmas páginas de antes e são
preservadas com o `done` que já tinham. A trigésima sexta ia de 491 a 500
e passa a ir de 491 a 506: é a única descartada. Ela é recriada e ganha
uma sucessora de 505 a 510, no total de 37 janelas.

**Uma janela descartada, 35 preservadas, duas classificadas** — cerca de
1 minuto contra 18,5.

### 8.3 Depois da invalidação

A transação termina e o usuário cai na tela de execução já conhecida.
Conversão pega os `discovered`; extração pega quem perdeu páginas e
renumera o grupo corretamente; `windows_prep` recria só as janelas
faltantes como `pending`; a classificação processa só essas;
`import_items` apaga e reconstrói os itens; os quatro Markdown são
regravados, agora com a seção de removidos no `review.md`. Pausa, ETA e
gráficos de recursos funcionam sem adaptação, porque são as mesmas etapas
de sempre.

## 9. Interface

- `GET /projects/{id}/update` — monta o plano e renderiza a confirmação.
- `POST /projects/{id}/update` — aplica e redireciona para a execução.
- `templates/update_project.html` — a tela de confirmação, que mostra
  quantos arquivos são novos, alterados e removidos, **nomeia os que serão
  reprocessados**, e antecipa o custo: quantos arquivos passarão por OCR,
  quantas janelas serão reclassificadas e quantas preservadas.
- A detecção ao abrir entra na tela de execução existente e **não bloqueia
  a renderização**: o plano é buscado por HTMX depois que a página
  aparece, como o app já faz com progresso e recursos. Num acervo grande
  no Drive a varredura leva segundos, e pagá-los antes do primeiro pixel
  seria trocar um problema por outro.
- Todas as chaves novas em `i18n.py`, nos três idiomas.

## 10. Tratamento de erro

**Pasta de origem inacessível — o risco mais grave da funcionalidade.**
Drive desconectado, pasta movida, letra de unidade trocada: o plano
ingênuo concluiria que todos os documentos foram removidos e ofereceria
apagar o acervo inteiro. Guarda intransigente: se a pasta de origem não
existe, ou existe e está vazia enquanto o banco tem arquivos, o resultado
é um erro dizendo que a origem está inacessível, e nenhuma ação é
oferecida. Nenhuma remoção em massa chega à tela de confirmação por essa
via.

**A pasta muda entre o diagnóstico e a confirmação.** O plano é uma
fotografia, e o Drive sincroniza enquanto o usuário lê a tela. O plano
carrega uma impressão digital — a lista ordenada de
`(caminho, tamanho, mtime)` resumida em um hash — e a aplicação a
reconfere antes de escrever. Se divergiu, nada é aplicado e a tela pede um
novo diagnóstico.

**A invalidação é atômica, mas o disco não.** As linhas saem numa
transação; os `.txt` das janelas são arquivos. Há aqui um defeito latente
a corrigir: `windows_prep` só grava o `.txt` `if not file_path.exists()`,
e o nome do arquivo deriva das posições. Um documento corrigido **sem
mudar de número de páginas** produz janelas com as mesmas posições e o
mesmo nome de arquivo — o texto velho sobreviveria ao lado da
classificação nova. Correção em dois pontos: a invalidação apaga o `.txt`
de toda janela descartada, e `windows_prep` grava incondicionalmente
quando é ele quem cria a linha, mantendo o desvio apenas para a janela que
já existia. Com os dois, uma interrupção entre o banco e o disco não deixa
resíduo.

**Arquivo alterado que falha no OCR perde o conteúdo antigo.** Suas
páginas já foram apagadas — sem isso a renumeração do grupo não fecha —
então ele sai do índice e reaparece como falha no `review.md` e na tela de
execução, que é o tratamento que o projeto já dá a arquivo ilegível. É uma
consequência real e assumida: a tela de confirmação nomeia os arquivos que
serão reprocessados justamente para que o usuário saiba o que está em jogo
antes de confirmar.

**Concorrência.** A atualização escreve, logo toma o mesmo bloqueio de
projeto que uma execução toma; o mecanismo de `lock.py` e a tela de
bloqueio existente valem sem adaptação.

**Plano vazio** não é erro: nada aparece na tela de execução, e o
diagnóstico sob demanda responde que a pasta está igual ao índice.

**Interrupção durante a reexecução** não precisa de nada novo: depois da
invalidação o banco está num estado que o pipeline entende, e pausar ou
fechar no meio deixa a situação que hoje já se resolve continuando.

## 11. Testes

Em `tests/test_phase17.py`, teste primeiro, nomes em português
descrevendo o comportamento, como no resto do projeto.

**O oráculo que prova a funcionalidade inteira.** Montar um acervo
pequeno, rodar o pipeline completo com o engine `rules` — determinístico,
sem LLM, sem custo —, guardar os quatro Markdown; então acrescentar,
alterar e remover documentos, atualizar, rodar de novo; e em paralelo
construir um projeto novo do zero sobre a pasta já modificada. Os dois
conjuntos de artefatos têm de ser iguais, descontado o carimbo de data.

Uma atualização incremental é correta se, e somente se, o resultado dela
não se distingue de uma reindexação completa. Todo o resto são testes de
unidade que explicam por que falhou quando esse falhar.

**Plano.** Pasta inalterada produz plano vazio. Novo, alterado e removido
são detectados. Arquivo cujo mtime o Drive reescreveu sem mudar o conteúdo
não aparece como alterado. Duplicata continua tratada como hoje. Pasta de
origem inacessível produz erro, nunca um plano propondo remover tudo —
este é o primeiro teste a escrever, porque é o que protege o acervo.

**Divergência.** O exemplo de §8.2 com os números exatos: documento de 10
páginas ao fim descarta 1 janela, preserva 35 e manda 2 para a
classificação. Documento inserido no começo invalida tudo, e isso é o
esperado. Documento alterado sem mudar de
número de páginas invalida a partir dele. E um teste de acoplamento que
vale por vários: a contagem de janelas que o plano prevê tem de bater com
o número que `windows_prep` realmente cria.

**Invalidação.** Falha no meio deixa o banco exatamente como estava. O
`.txt` da janela descartada some, inclusive no caso do documento corrigido
com o mesmo número de páginas. O removido sai de `file` e `page` e entra
em `removed_file`. Quem só renumera volta para `converted` e quem mudou
volta para `discovered` — teste explícito, porque é aí que mora a economia
de OCR.

**Regressão.** Reexecutar um projeto sem mudança nenhuma continua sem
reprocessar nada: a incrementalidade que hoje existe por acidente passa a
existir por contrato.

**Interface.** O `GET` do diagnóstico não escreve, verificado comparando o
banco antes e depois. O `POST` com plano vencido é recusado. Toda chave
nova tem texto nos três idiomas, no molde do teste que o projeto já tem
para os motivos de sensor.

## 12. Critério de aceitação

1. Acrescentar, alterar e remover documentos e atualizar produz artefatos
   indistinguíveis dos de uma reindexação completa sobre a pasta final.
2. Acrescentar um documento ao fim de um grupo de 500 páginas reclassifica
   2 janelas, não 36.
3. Um arquivo alterado é reprocessado sem violar o `UNIQUE` de `page`.
4. Um arquivo removido sai do `index.md` e do `timeline.md` e aparece no
   `review.md`.
5. Pasta de origem inacessível nunca resulta em proposta de remoção.
6. Projeto criado na 1.0.1 abre na 1.1 sem passo de migração manual.
7. Nenhuma regressão na suíte existente.
