**Léalo en su idioma:** Español, usted está aquí · **[Português (Brasil)](QUALITY.pt-BR.md)** · **[English](QUALITY.md)**

# Calidad del índice: acierto medido contra una clave de respuestas

Este documento publica el acierto del índice que produce GClaude Indexer,
medido contra una clave de respuestas revisada a mano, y dice qué significa y
qué no significa cada número. La pantalla "Calidad" del programa resume la
**autoconfianza** que declara el motor; el número de aquí es otro: **si la
pieza está bien**.

Se actualiza a mano en cada versión que toque el clasificador. Última
medición: **2 de noviembre de 2026, versión 1.7.5** (el clasificador, el
prompt y las reglas son los mismos de la 1.7.4; la fase 37 solo agregó la
medición).

## Qué se midió

- **Colección:** `demo/acervo`, enteramente ficticia: 72 páginas, 41 piezas,
  7 archivos (dos volúmenes encuadernados de un expediente en PDF, un
  contrato, un memorando en Word, una planilla, un oficio escaneado en PNG y
  un correo). Trece tipos del vocabulario del motor de reglas y siete piezas
  sin tipo.
- **Clave:** `demo/gabarito.csv`: pieza, tipo, fecha y autor de cada página.
- **Máquina:** escritorio con Radeon RX 6700 XT (12 GB), Ollama 0.40.13 vía
  Vulkan con flash attention apagada, Windows 11.
- **Comando:** `tools/indexar_pasta.py` seguido de `tools/medir_acerto.py`
  (la cuenta está en `gclaude_indexer/answer_key.py`).

## Resultado

| Motor | Páginas cubiertas | Piezas (clave / índice) | Precisión | Exhaustividad | F1 | Tipo | Fecha | Autor | Tiempo |
|---|---|---|---|---|---|---|---|---|---|
| Reglas | 72/72 (100 %) | 41 / 42 | 85,7 % | 87,8 % | 86,7 % | 94,4 % | 50,0 % | 19,4 % | 4 s |
| Local, `qwen3.5:9b` | 72/72 (100 %) | 41 / 65 | 53,8 % | 85,4 % | 66,0 % | 60,0 % | 88,6 % | 84,4 % | 4 min 12 s |

**Qué significa cada columna.** *Páginas cubiertas*: páginas de la clave que
están en alguna pieza del índice; ninguna página se perdió con ninguno de los
dos. *Pieza encontrada*: el índice tiene una pieza del mismo archivo con al
menos la mitad de las páginas en común (Jaccard ≥ 0,5); una pieza de tres
páginas devuelta como dos más una es un error de límite, no una ausencia.
*Precisión*: encontradas ÷ piezas del índice (baja cuando el motor fragmenta).
*Exhaustividad*: encontradas ÷ piezas de la clave (baja cuando el motor
fusiona). *Tipo*, *fecha* y *autor* se miden solo entre las piezas
encontradas, para no cobrar dos veces el error de límite; fecha y autor solo
donde la clave los tiene. El tipo se compara en mayúsculas, sin acentos y de
forma exacta; el autor vale por el apellido o la sigla.

## Cómo leerlo

- **El motor de reglas acierta límites y tipos** porque la colección, como
  un expediente real, tiene la mayoría de las piezas con el tipo en el
  encabezado, y el vocabulario de las reglas cubre esos encabezados. Falla en
  **fecha** (18 de 36 piezas encontradas: toma la primera fecha del texto,
  muchas veces una fecha citada en el cuerpo, no la de la pieza) y casi no
  encuentra el **autor** (7 de 36: solo reconoce la firma después de
  marcadores como "Atenciosamente"). Seis "piezas de más" son páginas donde
  una palabra del vocabulario abre la línea en medio de otra pieza ("PORTARIA
  nº 55/2026" dentro del pliego).
- **El modelo local acierta fecha y autor** (31 de 35 y 27 de 32) y pierde
  en límites: devuelve, en general, **una pieza por página** (30 piezas de
  más, de ahí la precisión del 54 %), y seis piezas largas (términos de
  referencia, pliego, acta, recurso, dos contratos) no alcanzan la mitad de
  sus páginas en una sola pieza. El **tipo** del 60,0 % tiene tres lecturas:
  7 de las 14 divergencias son un nombre más específico del tipo correcto
  ("PARECER JURÍDICO" por PARECER, "NFS-E" por NOTA FISCAL, "TERMO ADITIVO"
  por TERMO), que la comparación exacta no acepta; 4 son piezas que la clave
  deja sin tipo y el modelo nombró ("PLANILHA", "EMAIL", "ATA DE REUNIÃO");
  3 son piezas con tipo claro (TERMO) que el modelo devolvió sin tipo.
- **Ninguno de los dos es "mejor"** en esta tabla: uno acierta donde el otro
  falla. Para eso sirve la medida, y por ahí pueden empezar las próximas
  fases (la fecha en el motor de reglas y la fragmentación en el modelo son
  las dos mayores ganancias a la vista).

## Qué no dice esto

- **Colección sintética.** Fue escrita con encabezados limpios, texto
  digital legible y un solo escaneo de buena calidad. Una colección de verdad
  tiene sellos, páginas torcidas, OCR malo y tipos fuera del vocabulario; el
  acierto allí es menor, y no se sabe cuánto.
- **Una máquina, un modelo, una corrida.** Otro modelo, otro tamaño de
  fragmento u otra tarjeta dan números distintos; el modelo local no es
  determinista entre corridas. Medido: una segunda corrida el 2 de
  noviembre, tras cambiar una palabra en los textos, llevó el tipo del
  45,7 % al 60,0 %, la fecha del 91,4 % al 88,6 % y el autor del 78,1 % al
  84,4 %, con los mismos límites (F1 66,0 %). La tabla muestra la corrida
  sobre la colección tal como está versionada.
- **La comparación de tipo es estricta a propósito.** Aceptar "PARECER
  JURÍDICO" como PARECER subiría el número del modelo al 80 %, pero
  escondería que el índice sale con dos nombres para el mismo tipo.
- **El clasificador no se ajustó a la colección.** La regla de la fase 37
  fue medir primero, sin tocarlo; mejorar es otra fase, y la medida queda
  para decir si mejoró.

## Cómo repetirlo

```
python tools/indexar_pasta.py demo/acervo <carpeta> --motor rules
python tools/medir_acerto.py <carpeta> demo/gabarito.csv --saida-md acerto.md

python tools/indexar_pasta.py demo/acervo <carpeta2> --motor local --modelo qwen3.5:9b
python tools/medir_acerto.py <carpeta2> demo/gabarito.csv --saida-md acerto2.md
```

El CI hace la primera corrida en cada push y adjunta `acerto.md` a la
ejecución; exige solo la cobertura (100 %), no el acierto.
