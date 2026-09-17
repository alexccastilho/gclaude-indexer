# `tools/` — operações que o produto não oferece

Scripts de manutenção, rodados à mão contra a pasta de saída de um
projeto já indexado. Não fazem parte do aplicativo: o instalador não os
distribui e a interface não os chama.

Um script só entra aqui quando resolve algo que a interface não resolve, e
sai daqui quando a interface passar a resolver.

## `reprocessar_janelas_com_falha.py`

Devolve para `status = 'pending'` apenas as janelas que registraram falha
numa corrida da etapa 6, para que uma nova classificação tente de novo só
essas — sem reindexar o acervo inteiro.

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
importação e os relatórios rodarem em seguida — senão o índice continua
mostrando o resultado antigo.

Duas recusas deliberadas, cobertas por `tests/test_tools_reprocessamento.py`:

- **janela que não existe mais** não é reaberta — uma atualização posterior
  pode tê-la descartado, e ressuscitá-la criaria uma posição que o acervo
  atual não tem;
- **rejeição que repetir não resolve** não conta como falha. De
  `window_rejection`, só entra o caso em que o modelo deixou páginas sem
  resposta; uma referência que o acervo não reconhece continuará não sendo
  reconhecida na segunda tentativa.
