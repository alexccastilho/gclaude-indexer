# `tools/`: operações que o produto não oferece

Scripts de manutenção, rodados à mão contra a pasta de saída de um
projeto já indexado. Não fazem parte do aplicativo: o instalador não os
distribui e a interface não os chama.

Um script só entra aqui quando resolve algo que a interface não resolve, e
sai daqui quando a interface passar a resolver.

## `reprocessar_janelas_com_falha.py`

Devolve para `status = 'pending'` apenas as janelas que registraram falha
numa corrida da etapa 6, para que uma nova classificação tente de novo só
essas, sem reindexar o acervo inteiro.

Existe porque a única transição de estado de janela no código é
`pending -> done`, e a atualização incremental (fase 17) reage a mudanças
nos *arquivos de origem*: com os PDFs intactos, ela não invalida nada.

```
python tools/reprocessar_janelas_com_falha.py "<pasta de saída>"
python tools/reprocessar_janelas_com_falha.py "<pasta de saída>" --aplicar
```

Sem `--aplicar` ele não escreve nada: lista o que faria e para. Com
`--aplicar`, copia `project.db` e `raw_items.jsonl` com sufixo `.bak-<data>`
antes de tocar em qualquer um dos dois. A pasta de saída é a que termina em
`_indexado`.

Depois de rodar, é preciso rodar a etapa 6 pela interface e deixar a
importação e os relatórios rodarem em seguida. Senão o índice continua
mostrando o resultado antigo.

Duas recusas deliberadas, cobertas por `tests/test_tools_reprocessamento.py`:

- **janela que não existe mais** não é reaberta: uma atualização posterior
  pode tê-la descartado, e ressuscitá-la criaria uma posição que o acervo
  atual não tem;
- **rejeição que repetir não resolve** não conta como falha. De
  `window_rejection`, só entra o caso em que o modelo deixou páginas sem
  resposta; uma referência que o acervo não reconhece continuará não sendo
  reconhecida na segunda tentativa.

## `indexar_pasta.py`

Indexa uma pasta do início ao fim sem a interface: as cinco etapas na
ordem de `background_runs.STEP_ORDER`, a importação das peças e os
artefatos (`index.md` e um `index-<grupo>.md` por grupo). Grava ao lado do
`project.db` um `run_info.json` com motor, modelo, versão, máquina, início,
duração, número de trechos e de peças.

```
python tools/indexar_pasta.py demo/acervo <pasta de saída> --motor rules
python tools/indexar_pasta.py demo/acervo <pasta de saída> --motor local --modelo qwen3.5:9b
```

Existe porque o CI precisa indexar o acervo de demonstração numa máquina
sem ninguém na frente, e porque a medida de acerto precisa saber com que
motor e modelo o índice foi feito. Não toca em `projects.json`: o projeto
não aparece na interface. Os tipos de arquivo são fixos em PDF, Word,
Excel, imagens e e-mail, que é o que o acervo de demonstração tem.

## `medir_acerto.py`

Compara o `project.db` de uma pasta de saída com um gabarito em CSV
(formato de `demo/gabarito.csv`) e escreve o relatório em Markdown:
cobertura de páginas, peças encontradas (precisão, revocação, F1) e, entre
as encontradas, acerto de tipo, data e autor, por grupo e no total, com a
lista das divergências. A conta está em `gclaude_indexer/answer_key.py`.

```
python tools/medir_acerto.py <pasta de saída> demo/gabarito.csv --saida-md acerto.md
python tools/medir_acerto.py <pasta de saída> demo/gabarito.csv --exigir-cobertura 1.0
```

`--exigir-cobertura` faz o script sair com código 1 quando a cobertura de
páginas fica abaixo do valor; é o que o CI cobra do acervo de
demonstração. O acerto de tipo não é cobrado: é publicado em
`docs/QUALITY.md`.

## `buscar.py`

Busca por tema na pasta de saída de um projeto, com a saída em Markdown.
É o mesmo `gclaude_indexer.search_cli` que o `buscar.bat` gravado em cada
pasta de saída chama; este invólucro serve para quem roda a partir do
repositório.

```
python tools/buscar.py "<pasta de saída>" saneamento
python tools/buscar.py "<pasta de saída>" "segurança alimentar" --so-legislacao --limite 30
python tools/buscar.py "<pasta de saída>" saneamento --lexml
```

Usa a busca de texto completo do projeto (FTS5, a mesma da tela "Buscar no
acervo"). Para cada trecho: arquivo, localizador (folha, página ou artigo),
grupo, caminho e o trecho com o termo em negrito; para uma página de norma,
o link da norma. Sem nenhuma norma do acervo citando o termo, ou com
`--lexml`, consulta também o LexML e lista as normas federais encontradas
como "fora do acervo". Desde o fim de 2026 o LexML responde a programas com a
verificação de segurança do Senado: nesse caso a saída diz isso e dá o link
para abrir no navegador.
