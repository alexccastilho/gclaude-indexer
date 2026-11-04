# Acervo de demonstração

> **English.** A small, entirely fictional document collection (72 pages, 41
> pieces, 7 files: two bound PDF volumes of an administrative process, a
> contract, a Word memo, an Excel measurement sheet, a scanned PNG and an
> e-mail) with an answer key, `gabarito.csv`, that names the piece, type,
> date and author of every page. Index it with GClaude Indexer in about ten
> minutes and compare the result with the key; `docs/QUALITY.md` holds the
> reference numbers measured on a test machine. Texts are in Portuguese, which is
> what the program is built for.

Tudo aqui é inventado: o município "Vila Nova do Amparo", as pessoas, a
construtora, o CNPJ (dígitos verificadores inválidos de propósito) e o
número do processo. Nenhum texto foi copiado de documento real. O assunto é
um só, para o acervo se ler como um processo de verdade: a licitação e a
reforma da Escola Municipal Professora Aurora Lima, de janeiro a agosto de
2026.

## O que tem dentro

| Arquivo | O que é | Páginas | Peças |
|---|---|---|---|
| `acervo/Processo 2026-0001/volume_1.pdf` | Volume encadernado: da autuação à homologação da licitação | 35 | 17 |
| `acervo/Processo 2026-0001/volume_2.pdf` | Volume encadernado: do contrato ao recebimento provisório | 28 | 19 |
| `acervo/Contratos/contrato_reforma_escola.pdf` | O contrato, como cópia avulsa | 5 | 1 |
| `acervo/Contratos/memorando_fiscalizacao.docx` | Memorando do fiscal com a 1ª medição (Word) | 1 | 1 |
| `acervo/Contratos/medicao_obra.xlsx` | Boletim de medição nº 1 (Excel) | 1 | 1 |
| `acervo/Contratos/oficio_digitalizado.png` | Ofício digitalizado a 150 dpi, sem camada de texto (exige OCR) | 1 | 1 |
| `acervo/Contratos/pedido_prorrogacao.eml` | E-mail da construtora pedindo prorrogação | 1 | 1 |

Treze tipos do vocabulário do motor de regras (OFÍCIO, MEMORANDO, PARECER,
DESPACHO, ATA, CERTIDÃO, TERMO, EDITAL, NOTA FISCAL, RECURSO, DECISÃO,
PORTARIA, RESOLUÇÃO) e sete peças sem tipo nomeável (lista de presença,
descrição técnica, impressão de e-mail, registro fotográfico, lista de
verificação, a planilha e o e-mail), que no gabarito têm o tipo vazio. Há
peças com o tipo no cabeçalho e peças em que ele só se infere do corpo.

## `gabarito.csv`

UTF-8, uma linha por peça:

```
arquivo,pagina_inicial,pagina_final,tipo,data,autor
Processo 2026-0001/volume_1.pdf,2,3,OFÍCIO,2026-01-10,Maria Souza
```

- `arquivo`: caminho relativo a `acervo/`, com `/`.
- `pagina_inicial`, `pagina_final`: páginas dentro do arquivo, a partir de 1.
  Arquivos que não são PDF contam como uma página, que é como o programa os
  trata (o texto convertido vira uma página lógica).
- `tipo`: maiúsculas, com acento, do vocabulário de
  `config/classification_rules.json`; vazio quando a peça não tem tipo.
- `data`: ISO (`AAAA-MM-DD`) ou vazia.
- `autor`: nome ou órgão; na comparação vale o sobrenome ou a sigla entre
  parênteses, sem acento e sem caixa.

## Experimente em dez minutos

1. Instale o GClaude Indexer (`GClaude-Indexer-Setup-<versão>.exe` nas
   releases) ou rode do código-fonte. O instalador **não** traz esta pasta:
   baixe o repositório como ZIP ou clone-o.
2. Abra o programa, crie um projeto e aponte a pasta de origem para
   `demo/acervo`. Nos tipos de arquivo, marque "PDF", "Word (.docx)",
   "Excel (.xlsx)", "Imagens (foto/scan)" e "E-mail (.eml, .msg)"; o padrão
   deixa Excel e e-mail de fora, e a planilha e o e-mail ficariam sem indexar.
3. Escolha o motor: **Regras** roda em segundos sem nada instalado além do
   Tesseract (para o PNG); **Local** usa o Ollama e o modelo configurado, e
   leva alguns minutos conforme a placa de vídeo.
4. Rode a indexação. O resultado fica na pasta de saída do projeto:
   `index.md`, um `index-<grupo>.md` por grupo e `project.db`.
5. Meça o acerto contra o gabarito:

   ```
   python tools/medir_acerto.py "<pasta de saída do projeto>" demo/gabarito.csv --saida-md acerto.md
   ```

   Sem interface, do início ao fim, com o motor de regras:

   ```
   python tools/indexar_pasta.py demo/acervo <pasta de saída> --motor rules
   python tools/medir_acerto.py <pasta de saída> demo/gabarito.csv --saida-md acerto.md
   ```

O relatório diz, por grupo e no total, a cobertura das páginas, quantas
peças do gabarito foram encontradas (precisão, revocação, F1) e, entre as
encontradas, o acerto de tipo, data e autor, com a lista das divergências.
Os números desta máquina estão em `docs/QUALITY.pt-BR.md`.

## Regenerar

`python demo/gerar_acervo.py` reescreve `acervo/` e `gabarito.csv` a partir
da lista `PECAS` do próprio script. Só rode quando mudar uma peça: o PyMuPDF
grava um identificador novo a cada gravação e um PDF regravado sem mudança
de texto aparece como alterado no git. O teste
`test_gerador_reproduz_o_acervo_versionado` garante que o script e os
arquivos versionados dizem a mesma coisa, página por página.
