# Registro de cambios

Todos los cambios relevantes de este proyecto están documentados en este
archivo. El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).

> **Traducción.** El documento canónico es el
> [`CHANGELOG.md`](../CHANGELOG.md) en inglés. Si ambos divergen, vale el
> inglés. Los nombres de archivo, identificadores de código, claves de
> configuración y mensajes que el programa emite en inglés se han
> mantenido tal cual.

Las entradas más antiguas están agrupadas por fase de desarrollo, y no
por versión semántica: la versión que informa la aplicación
(`SYSTEM_VERSION`, en `web/app.py`) se mantuvo en `1.0.0` desde la fase 1
hasta la fase 16. La `1.0.1` es el primer incremento, y publica todo lo que
el bloque de la fase 16, más abajo, venía arrastrando como no publicado.

## [1.10.3] - 2026-11-13

### Corregido

- La lectura de las páginas se detenía con `UNIQUE constraint failed:
  page.file_id, page.number` cuando un documento cambiaba en la carpeta de
  origen y los pasos se ejecutaban desde la pantalla Ejecución sin pasar
  antes por "Actualizar". El escaneo devolvía el documento a la cola, pero
  conservaba sus páginas, fragmentos de búsqueda y ventanas antiguos. Ahora
  el paso de escaneo aplica a los documentos nuevos y modificados la misma
  limpieza del botón "Actualizar". Los documentos eliminados siguen
  saliendo del índice solo después de que usted lo confirma en la pantalla
  de actualización.
- Un proyecto que ya quedó en ese estado se repara solo en el próximo
  "Ejecutar todo hasta la clasificación" o "Continuar": los documentos afectados se leen de nuevo,
  con el contenido nuevo. No hace falta hacer nada a mano.

## [1.10.2] - 2026-11-04

### Cambiado

- Documentación, comentarios y pruebas revisados: todos los ejemplos pasan
  a usar nombres y datos ficticios. Ningún cambio en el funcionamiento.

## [1.10.1] - 2026-11-04

### Cambiado

- Autores: el mismo nombre escrito con y sin tilde ("ANTONIO PEREIRA" y
  "ANTÔNIO PEREIRA") pasa a tener una sola grafía en todo el índice, en
  cualquier motor, y no solo en los actos del Planalto. La grafía con
  mayúsculas y minúsculas sigue valiendo más que la toda en mayúsculas, y
  la grafía con tilde gana cuando aparece al menos la mitad de las veces
  que la sin tilde. Vale en el próximo "Importar y generar informes";
  nada se clasifica de nuevo.
- Imagen de vista previa del repositorio rehecha con los colores del tema
  Estudio oscuro, las fuentes que van con el programa y una captura del
  diseño Área de trabajo.

### Seguridad

- Análisis de código con CodeQL (configuración avanzada): Python,
  JavaScript y los workflows de GitHub Actions, con el conjunto de
  consultas `security-and-quality`, en cada envío, en cada pull request y
  una vez por semana.
- Revisión de dependencias en los pull requests: una dependencia nueva con
  vulnerabilidad conocida o licencia incompatible bloquea el cambio.
- Todos los workflows pasan a ejecutarse con un token de solo lectura.

### Eliminado

- Notas internas de planificación de las fases pasadas
  (`docs/superpowers/`), funciones e imports sin uso y marcas de versión y
  de fase que habían quedado en los comentarios del código. Nada cambia en
  el funcionamiento.

## [1.10.0] - 2026-11-03

Un aspecto nuevo, elegido entre tres propuestas: el diseño Área de trabajo,
con una paleta propia, el tema Estudio.

### Añadido

- Diseño Área de trabajo, ahora el predeterminado: una barra lateral con
  las pantallas principales y todos los proyectos (con un punto de
  situación), una barra superior que muestra dónde está usted y pestañas
  para las cinco pantallas de un proyecto (Ejecución, Resultado, Búsqueda,
  Actualizar acervo, Instrucciones).
- Paleta de comandos: Ctrl+K (o "Buscar o ejecutar", en la barra lateral)
  encuentra cualquier pantalla, las pantallas de cada proyecto y las
  preferencias de tema, diseño e idioma escribiendo parte de una palabra,
  con o sin acento. Solo navega y cambia preferencias; nunca inicia un
  trabajo. Funciona con el teclado y con lector de pantalla (diálogo,
  lista, flechas, Enter, Esc).
- Temas Estudio y Estudio oscuro: grises neutros y cálidos y un único color
  de acento, verde azulado. Estudio es el predeterminado para quien nunca
  eligió un tema.
- Fuentes Inter y JetBrains Mono incluidas con el programa (licencia SIL
  Open Font, archivos en `web/static/fonts`), para seguir funcionando sin
  internet.
- En la pantalla Ejecución, la etapa que está corriendo queda destacada.

### Cambiado

- La preferencia de diseño tiene una cookie nueva: quien usaba otro diseño
  ve el Área de trabajo una vez después de actualizar y puede volver en
  Preferencias. El tema elegido se mantiene. Los diseños anteriores
  (Predeterminado, Técnico, Editorial, Compacto) y los ocho temas
  anteriores siguen ahí.
- La barra lateral nunca abre la base de un proyecto: los puntos de
  situación vienen de lo que la pantalla Proyectos ya calculó.
- Capturas de pantalla y GIF del recorrido en el README rehechos con el
  aspecto nuevo, en los tres idiomas.

## [1.9.2] - 2026-11-03

Quien ya tenía instrucciones antes de que existiera el bloque automático a
menudo copió sus secciones a mano en su propia parte. El bloque se anexaba
debajo y Claude recibía todo dos veces, con los recuentos de la copia fijos
("120000 páginas") mientras los del bloque se actualizaban.

### Añadido

- La generación reconoce una copia del bloque en la parte del usuario de
  `project_instructions.md`: secciones cuyo texto es en su mayor parte el
  del bloque (comparado palabra por palabra, sin acentos, mayúsculas,
  rayas, dos puntos, numeración ni números), en cualquiera de los tres
  idiomas, y líneas con recuentos que cambian en cada indexación. El texto
  del usuario nunca se cambia ahí: un aviso va al inicio del bloque y al
  registro, y las pantallas Ejecución y Resultado muestran un enlace para
  revisarlo.
- En la pantalla Instrucciones del proyecto: las secciones repetidas, las
  líneas con recuentos, las referencias del tipo "sección 4" que pasarían
  a apuntar al bloque y los fragmentos del propio usuario que hablan del
  acervo. "Quitar las repeticiones" saca las copias (la versión anterior
  queda en un `.bak` con fecha), apunta esas referencias al bloque y mueve
  los fragmentos marcados a las Reglas extra del proyecto, que salen dentro
  del bloque. "Mantener como está" solo registra la elección. Ambas quedan
  en el registro.

### Corregido

- Un archivo sin marcas cuya parte del usuario tenía una copia a mano de la
  regla innegociable se tomaba por un archivo escrito entero por una
  versión antigua y se reemplazaba (quedaba solo en el `.bak`). Ahora cada
  sección del archivo tiene que ser una de las que escribe el programa.

La primera generación después de actualizar pone el aviso en el bloque de
un proyecto que tiene copia; el archivo cambia una vez y hay que pegarlo de
nuevo en el Proyecto de Claude.

## [1.9.1] - 2026-11-03

Lo que había quedado para después en la 1.9.0, hecho ahora: navegación más
rápida en los proyectos guardados en Google Drive y los defectos de autor
encontrados en un acervo grande.

### Cambió

- Las pantallas que solo leen (Ejecución, sus actualizaciones periódicas y
  Resultado) mantienen una conexión de solo lectura por proyecto abierto
  (`web/readers.py`), y la caché de páginas de SQLite sobrevive entre un
  pedido y otro. Se reabre siempre que `project.db` cambia en el disco
  (por ejemplo, cuando Google Drive trae la copia de la otra computadora),
  se cierra tras dos minutos sin uso y se cierra cuando el proyecto se
  cierra, se borra o se asume. Etapas, importación y actualización siguen
  con sus propias conexiones de escritura.
- La pantalla Proyectos ya no abre la base de cada proyecto en cada
  visita: el resumen de cada uno se guarda mientras `project.db` sea el
  mismo archivo (tamaño y fecha de modificación).
- La revisión de cambios en el acervo lee la tabla `file` una vez en lugar
  de dos, y un archivo nuevo solo se lee entero (para buscar duplicados)
  cuando hay otro archivo con exactamente el mismo tamaño.
- En la primera ejecución, antes de descargar el modelo, el registro
  estima `qwen3.5:9b` por su propio tamaño (unos 6,3 GB) y no por los
  3232 MB del 4b.

### Corregido

- Un autor, fecha, tipo o resumen que solo decía "null", "N/A", "-" o algo
  parecido salía como texto en el índice; ahora queda vacío.
- El mismo autor escrito con mayúsculas distintas por el modelo local
  ("LUIZ INÁCIO LULA DA SILVA" y "Luiz Inácio Lula da Silva") pasa a tener
  una sola grafía, la más frecuente entre las escritas con mayúsculas y
  minúsculas. Los nombres que solo aparecen en mayúsculas quedan como
  están.
- Una norma citada como autor ("Lei nº 9.394/1996", "Decreto 7.892 de
  2013") dejó de aparecer como autor.
- Una pieza que avanzaba sobre la primera página de la siguiente (una
  "PÁGINA EM BRANCO" f. 14-15 seguida de una pieza que empieza en la f. 15)
  ahora termina en la página anterior. Una pieza entera dentro de otra
  queda como está.

Las correcciones valen la próxima vez que se ejecute "Importar y generar
informes"; no se clasifica nada de nuevo.

## [1.9.0] - 2026-11-03

Un usuario confirmó una actualización del acervo sin pegar las instrucciones y
no pudo detenerla: el botón Detener del navegador solo soltaba la respuesta, el
servidor seguía trabajando y el clic siguiente decía "ocupado con: Actualizar".
Al final, la pantalla no volvió sola a la Ejecución. También informó que abrir
un proyecto grande o generar informes dejaba la pantalla quieta sin aviso, que
la barra de avance quedaba ilegible en los temas oscuros, que cambiar de tema en
medio la borraba, que la navegación era lenta y que Acerca de no mostraba la
versión del controlador de video.

### Corregido

- **Detener cualquier operación larga.** "Actualizar" e "Importar y generar
  informes" funcionan en segundo plano, y un panel en el centro de la pantalla
  muestra lo que está en curso, el tiempo transcurrido y el botón Detener.
  Detener no graba nada a medias: la actualización vuelve al estado anterior al
  clic, y en la generación de informes cada archivo queda el antiguo o el nuevo,
  con el registro diciendo cuáles cambiaron. La página de "proyecto ocupado"
  también tiene el botón Detener.
- **Pasa sola a la pantalla siguiente.** Cuando la operación termina, la pantalla
  va a Ejecución (después de actualizar) o a Resultado (después de generar),
  aunque haya recargado la página o cambiado de pestaña en medio.
- **Aviso de "espere" legible en todos los temas.** La barra amarilla de arriba
  usaba un color de fondo que ningún tema definía, con el texto blanco del tema
  encima. El panel nuevo usa los colores de superficie y de texto del propio
  tema.
- **Cambiar de tema o de diseño ya no recarga la página** ni borra el panel.
  Cambiar de idioma recarga, y el panel vuelve con el tiempo correcto, porque es
  el servidor el que dice qué está en curso.
- **Las pantallas lentas avisan.** Al abrir un proyecto grande o cualquier
  pantalla que tarde, aparece "Cargando, espere" con un reloj, en lugar de la
  pantalla quieta.
- **Acerca de** muestra el controlador de video instalado con la fecha de
  publicación, por ejemplo "controlador 621.01 (32.0.16.2101), publicado el
  18/10/2026". En las tarjetas NVIDIA aparece también el número que NVIDIA
  divulga.
- **Sin rayas en las pantallas ni en el manual.** Los textos se reescribieron
  con coma, dos puntos, punto o paréntesis. Los archivos de índice y de
  cronología no cambian por esto.

### Agregado

- **Pantalla "Instrucciones del proyecto"**, en Ejecución y Resultado: muestra
  su parte de `project_instructions.md` para corregirla o pegar la versión
  actual del Proyecto de Claude en cualquier momento, sin actualizar el acervo.
  La parte que genera el programa aparece debajo, solo para lectura, y cada
  guardado conserva la anterior en una copia `.bak` con fecha.
- Acabado visual: fuentes propias de Windows 11, títulos con más presencia,
  secciones sin mayúsculas, campos y botones que responden al foco y al clic,
  sombras del color del tema, la pantalla actual marcada en el menú y un enlace
  "Saltar al contenido". La entrada de cada pantalla es más corta, para que no
  parezca una demora.

### Rendimiento

Medido en un proyecto grande guardado en Google Drive:

- **Resultado**: tardaba decenas de segundos en cada apertura. Ahora solo la primera
  apertura después de un cambio hace las cuentas, y las siguientes son casi
  inmediatas. La calidad, los pendientes y la comparación de ejecuciones solo
  se recalculan cuando cambian las piezas, las ventanas o las páginas, y los
  pendientes se calculan una sola vez. El tamaño de los archivos intermedios
  sale del propio listado de la carpeta.
- **La Ejecución en reposo ya no lee la base cada 2 s.** Sin nada en curso, la
  tabla de etapas y el cuadro de avance se reutilizan hasta 30 s; cualquier cosa
  que empiece o termine renueva ambos al instante. Con algo en curso, nada
  cambia. Los cinco conteos de archivos pasaron a ser uno.
- **Revisión de la carpeta de origen**: el cálculo de la ruta relativa, la mayor
  parte del tiempo del recorrido, pasó a ser un corte de texto con el mismo resultado. La
  actualización confirmada dejó de recorrer la carpeta una tercera vez.
- **Acerca de** guarda el diagnóstico de la instalación durante 5 minutos.
- La renovación del bloqueo de uso, una escritura en Drive cada minuto, ya no
  frena las otras pantallas mientras escribe.

### Sin cambios

- `project_instructions.md` cambia una vez en la primera generación con la
  1.9.0 (el título de la sección generada y la marca del bloque quedaron sin
  raya): péguelo de nuevo en el Proyecto de Claude. Los índices y las
  cronologías no cambian.
- Las etapas de "Ejecutar todo" siguen con su propio cuadro de avance y el
  botón Pausar.

## [1.8.1] — 2026-11-03

Un usuario agregó documentos a un acervo grande, abrió el proyecto y no vio
señal de que el programa los hubiera notado. Tenía cómo notarlo: la
pantalla "Actualizar acervo" lista documentos nuevos, modificados y
eliminados desde la fase 17. La revisión detrás del aviso tardó minutos en
un acervo de ese tamaño en Google Drive, y la pantalla de
Ejecución no mostraba nada mientras tanto. El mismo pedido incluyó que las
instrucciones del Proyecto del usuario se actualicen, no se reemplacen, y
que solo la indexación nueva cambie los archivos de salida.

### Corregido

- **La revisión "la carpeta de origen cambió" tarda segundos, no minutos**
  (`scanning.walk_source_stats`, `update_plan.detect_changes`). En Windows,
  el listado de la carpeta ya trae el tamaño y la fecha de cada archivo; la
  revisión los descartaba y volvía a preguntar al disco, archivo por
  archivo. En un acervo grande: segundos en lugar de minutos, con las fechas
  del listado idénticas a las guardadas en todos los archivos sin cambios, así
  que nada se vuelve a leer. La etapa de escaneo usa los mismos valores y es
  más rápida por el mismo motivo.
- **La pantalla de Ejecución avisa que está revisando.** Mientras la
  revisión corre, el área del aviso muestra "Revisando la carpeta de origen:
  documentos nuevos, modificados y eliminados…" en lugar de quedar en
  blanco.
- **Las instrucciones generadas ya no contradicen las del usuario.** Cuando
  `project_instructions.md` tiene instrucciones propias del usuario, la
  parte generada pasa a ser una sección de su documento ("Acervo indexado
  por GClaude Indexer"), un nivel de título más abajo, con las cifras, los
  archivos, las columnas y las reglas del acervo, sin un segundo título ni
  el "Rol" genérico. Un proyecto podía tener cientos de líneas de
  instrucciones propias seguidas de "usted es un asistente de investigación". Sin
  instrucciones del usuario, el archivo sigue como antes.

### Agregado

- **La pantalla de actualización pide las instrucciones actuales del
  Proyecto.** Un campo viene lleno con la parte del usuario de
  `project_instructions.md`; si las instrucciones se cambiaron en el
  Proyecto de Claude, el usuario pega allí la versión actual. Reemplaza solo
  la parte del usuario, mantenida exactamente como se pegó, con todas las
  personalizaciones; la sección generada sigue y se actualiza en la
  generación siguiente. Un texto pegado que traiga la sección generada se
  queda solo con lo que está fuera de ella. El archivo anterior queda
  guardado como `project_instructions.md.<fecha-hora>.bak`. Un campo vacío
  o sin cambios no altera nada.
- **Solo se vuelven a escribir los archivos de salida que cambiaron.** Cada
  generación compara lo que escribiría con lo que está en el disco,
  ignorando la fecha de generación, y no toca los archivos iguales. El
  registro dice entonces qué archivos cambiaron (los que deben volver al
  Proyecto de Claude) o que ninguno cambió. Agregar un documento a un grupo
  reescribe el índice de ese grupo, el resumen y la cronología, no los
  índices de los otros grupos. El índice de un grupo que salió del acervo
  se borra, y el registro también dice cuál fue, para quitarlo del
  Proyecto de Claude.

### Sin cambios

- La detección de documentos eliminados, de carpetas eliminadas y de
  carpetas nuevas ya existía y no cambió; la 1.8.1 agrega pruebas para una
  carpeta nueva entera y una carpeta eliminada entera, comparadas con
  indexar el mismo acervo desde cero.

## [1.8.0] — 2026-11-02

Fase 38. Dos pedidos del usuario, más dos hallazgos del mismo día. Los
pedidos: varios acervos dentro de un único Project de Claude sin colisión
de nombres, y una documentación que una persona ajena a TI pueda leer. Los
hallazgos: el paquete de un proyecto grande llevaba archivos
`legislacao-<grupo>.md` de decenas de megabytes (millones de tokens) que
ningún Project acepta, mientras el presupuesto "solo informaba, nunca
bloqueaba"; y una pregunta como "qué leyes tratan del saneamiento" necesita búsqueda en
el texto completo, no una lista de enlaces. Clasificador, prompt, reglas y
pipeline no cambiaron.

### Añadido

- **Conjuntos** (pantalla `/sets`, `gclaude_indexer/sets.py`,
  `gclaude_indexer/combined_package.py`): una selección con nombre de dos o
  más proyectos, más las instrucciones que el usuario ya usa en el Project,
  guardada en el catálogo local de la máquina. El paquete combinado
  prefija cada archivo con el alias del proyecto (`<alias>__index.md`,
  `<alias>__index-<grupo>.md`, `<alias>__timeline.md`,
  `<alias>__review.md`), reescribe los enlaces entre resúmenes e índices de
  grupo hacia los nombres prefijados, incluidos los rótulos entre comillas
  invertidas y los índices divididos en partes, y escribe un único
  `project_instructions.md`: el texto personal arriba, fuera de las marcas;
  dentro de ellas, el papel una vez, una sección por acervo y la regla "en
  qué acervo buscar". "Grabar en la carpeta" produce los mismos archivos
  más un `CLAUDE.md` combinado para Claude Code, rechaza la carpeta de
  origen o de salida de un proyecto y borra los archivos prefijados de los
  proyectos que salieron del conjunto. Las carpetas de salida de cada
  proyecto no cambian, así que los Projects y `CLAUDE.md` existentes siguen
  valiendo.
- **`normas-citadas.md`** en la carpeta de salida y en el paquete: una
  línea por acto federal reconocido en el acervo (tipo, número, año,
  ementa corta cuando la hay, enlace al texto en LexML, grupo y páginas
  donde aparece). Pocos KB incluso en un acervo con espejo completo del
  Planalto. Las instrucciones generadas pasan a decir que la legislación no
  está en el conocimiento del Project: lea este archivo para saber qué
  existe, siga el enlace para leer el texto, pida al usuario una búsqueda
  por tema.
- **Búsqueda por tema para Claude Code**: `tools/buscar.py`, y un
  `buscar.bat` escrito en la carpeta de salida, consultan la base del
  proyecto con el mismo motor FTS5 de la pantalla "Buscar en el acervo" e
  imprimen, en Markdown, las normas y páginas que citan un término, con
  fragmento, archivo de origen y enlace de LexML; opciones `--grupo`,
  `--so-legislacao`, `--limite`, `--lexml`. El `CLAUDE.md` de la carpeta de
  salida manda a Claude Code usarla en las preguntas temáticas.
- **LexML** (`gclaude_indexer/lexml.py`): cuando un término no aparece en
  ninguna norma del acervo, o a pedido, la búsqueda consulta el servicio
  público SRU de LexML y lista las normas encontradas como "fuera del
  acervo". Es la única llamada que sale de la máquina, envía solo el
  término escrito y nunca corre durante la indexación. Comprobado:
  el servicio responde a los programas con la página
  "Verificación de seguridad" del Senado; el cliente reconoce esa página
  (un documento HTML, o la marca dentro de `<title>`, nunca una ementa que
  por casualidad contenga las palabras), avisa y da el enlace para abrir en
  el navegador. Sortear la verificación no es una opción. La pantalla
  "Buscar en el acervo" ganó la misma casilla "Buscar también en LexML".
- **Presupuesto que protege** (`gclaude_indexer/claude_package.py`):
  `MAX_FILE_BYTES` (30 MB, el límite por archivo del Project en el momento
  de esta versión) y `RAG_THRESHOLD_TOKENS`. Un archivo por encima del tope por
  archivo nunca entra en el paquete, simple o combinado; la pantalla lo
  muestra en rojo, con tamaño y qué hacer. Por encima del total, la
  pantalla lista lo que cabe y lo que sobra, y el botón de descarga avisa
  antes de generar. El índice de grupo ya sale en partes de hasta 25 MB desde la
  1.6.0 (`INDEX_PART_BYTES`); lo que cambia es que un único archivo de
  origen cuyo índice por sí solo pase de 30 MB queda fuera del paquete, y
  la pantalla dice cuál.
- **Medios rehechos en la 1.8.0**: `docs/media/demo-{pt,en,es}.gif` y 21
  pantallas sobre `demo/acervo` con el motor de reglas, ventana de 1366 px,
  tema claro, con temperatura, ventilador y consumo de la CPU leídos por el
  ayudante elevado visibles en la pantalla Ejecución; nuevas `search-*.png`
  y `sets-*.png`.
- **Prueba de lenguaje** (`tests/test_phase38_docs.py`) sobre README ×3,
  manual ×3, `demo/README.md`, `tools/README.md` y `docs/TECHNICAL` ×3:
  ninguna raya ni semirraya como inciso, comillas rectas, ningún carácter
  de puntos suspensivos, ninguna palabra de las listas de vocabulario
  inflado (pt, en, es).

### Cambiado

- **README ×3 reescritos para quien no es de TI**: una frase de qué es el
  programa, tres personas que lo usan, qué recibe (con las pantallas), qué
  necesita tener, diez minutos para probar, cuánto acierta (los números de
  `docs/QUALITY.md`, una frase cada uno), privacidad, varios acervos,
  legislación y búsqueda, equipo. Cada README quedó más corto que antes.
  Todo detalle técnico pasó a los nuevos **`docs/TECHNICAL.md`**,
  **`docs/TECHNICAL.pt-BR.md`** y **`docs/TECHNICAL.es.md`**, que conservan
  los dieciséis temas de la antigua sección "Detalles técnicos" y agregan
  conjuntos y búsqueda.
- **Manual ×3 reescrito** con las mismas reglas, 22 secciones, con
  secciones nuevas sobre el acervo de demostración, qué esperar de acierto,
  conjuntos, normas citadas y búsqueda, los sensores y la solicitud de
  administrador, pausar y continuar, y actualizar el programa. La lista de
  campos de Nuevo proyecto coincide con la pantalla (el tope de tokens del
  paquete no es un campo).
- **CONTRIBUTING ×3** (un commit por tarea, el CI indexa el acervo de
  demostración, la regla de la documentación, cómo se genera el instalador
  de Windows), **SECURITY**, **CODE_OF_CONDUCT**, **QUALITY ×3**,
  **SPECIFICATION** (`normas-citadas.md`, `buscar.bat`, conjuntos, las
  siete pantallas), las plantillas de issue y pull request de GitHub, la
  descripción y los temas del repositorio y la imagen social
  (`docs/media/social-preview*.png`, generada por `docs/social-preview.py`).

### Eliminado

- **`legislacao-<grupo>.md` y la opción "Legislación del Planalto en el
  paquete"** (`planalto_in_package`, fases 31 a 37). El archivo copiaba el
  texto de cada acto reconocido; en un acervo con espejo del Planalto
  llegaba a decenas de megabytes que ningún Project acepta, y el mismo
  texto está a un enlace de distancia. Los proyectos que todavía tengan el
  archivo en la carpeta de salida lo pierden en la siguiente generación,
  como cualquier huérfano. La clave sigue grabada en el `config_json` de
  todo proyecto creado hasta la 1.7.5 y se ignora al leer, para que esos
  proyectos sigan abriendo. El reconocimiento de actos federales
  (`planalto.py`) y la indexación de las páginas `.htm` como páginas del
  acervo no cambiaron.

### Corregido

La tarea de fondo de una etapa se marcaba como terminada antes de que la fila
de `run` recibiera `finished_at` y `ok`: quien leía la base en ese instante (la
tabla "Comparar motores y modelos" de la pantalla Resultado, la prueba de la
fase 13) veía la ejecución todavía abierta y la comparación salía vacía. Visto
una vez en el runner de GitHub (1 fallo en 1204, suite a 9 min) y
una vez localmente bajo carga. La marca solo cambia después del commit.

Seis correcciones de la revisión independiente de la parte A: la
reescritura de enlaces del paquete combinado alcanza los rótulos entre
comillas invertidas y el índice en partes; guardar un conjunto conserva el
miembro que está fuera de servicio en vez de descartarlo en silencio;
escribir un conjunto en la carpeta de un proyecto se rechaza con mensaje;
regenerar un conjunto en una carpeta borra los archivos prefijados que
salieron del conjunto; el cliente de LexML ya no confunde una ementa que
contiene las palabras de la verificación con la página de verificación; el
resumen de un acto revocado sin ementa vuelve a sus partes en vez de una
línea vacía.

## [1.7.5] — 2026-11-02

Fase 37. Tras una evaluación honesta del proyecto, el usuario pidió tres
pruebas que cualquiera que abra el repositorio pueda verificar: "CI, medida
de calidad y colección de demostración". Nada en el clasificador, el prompt
ni las reglas cambió en esta fase; mide lo que existe.

### Agregado

- **Colección de demostración** (`demo/acervo`, 72 páginas, 41 piezas, 7
  archivos): dos volúmenes encuadernados de un expediente administrativo
  ficticio en PDF, un contrato, un memorando en Word, una planilla, un
  oficio escaneado en PNG y un correo, generados por `demo/gerar_acervo.py`
  a partir de una única lista de piezas y versionados con su clave,
  `demo/gabarito.csv` (pieza, tipo, fecha y autor de cada página). Todo
  inventado: municipio, personas, empresa, CNPJ y número de expediente
  (ambos inválidos a propósito). `demo/README.md` y la sección "Pruébelo en
  diez minutos" en los tres README.
- **Acierto contra clave de respuestas** (`gclaude_indexer/answer_key.py`,
  `tools/medir_acerto.py`): cobertura de páginas, piezas encontradas por
  Jaccard ≥ 0,5 sobre conjuntos de páginas (precisión, exhaustividad, F1) y
  tipo, fecha y autor entre las encontradas, por grupo y en total, con la
  lista de divergencias en un informe Markdown. La pantalla "Calidad" medía
  la autoconfianza declarada; esto mide el acierto.
- **`docs/QUALITY.md` ×3** con los números de esta máquina (RX 6700 XT,
  Ollama 0.40.13). Motor de reglas: cobertura 100 %, límites F1 86,7 %,
  tipo 94,4 %, fecha 50,0 %, autor 19,4 %, 4 s. `qwen3.5:9b`: cobertura
  100 %, F1 66,0 % (devuelve en general una pieza por página), tipo 60,0 %
  en comparación exacta (80 % aceptando nombres más específicos
  como "PARECER JURÍDICO"), fecha 88,6 %, autor 84,4 %, 4 min 12 s. El
  documento dice qué significa y qué no significa cada número.
- **El CI prueba el producto**: `tools/indexar_pasta.py` ejecuta las cinco
  etapas, la importación y los artefactos sin interfaz; la corrida de GitHub
  indexa la colección de demostración con el motor de reglas en cada push,
  falla si alguna página de la clave queda fuera del índice y adjunta el
  informe de acierto y el índice a la ejecución. Insignia de los tests al
  inicio de los tres README.

### Corregido

- **La suite de tests ya no alcanza el Ollama real del desarrollador.**
  Enviaba cientos de 404 con modelos falsos a `127.0.0.1:11434`, el
  `ollama --version` de la pantalla Acerca de preguntaba la versión al
  servidor real y, con el puerto cerrado, el camino de reinicio levantaba un
  `ollama serve` de verdad, que quedaba huérfano atendiendo los modelos
  falsos. La suite ahora apunta el motor, el CLI (`OLLAMA_HOST`) y el
  lanzador a un puerto cerrado, en todo el proceso; probado con el servidor
  activo: 339 tests, cero líneas nuevas en `ollama-serve.log`, ningún
  proceso de más.
- **La suite de tests detenía el Ollama real de la máquina.** Un test de
  la fase 19 probaba que `Stop-OllamaProcesses` del desinstalador sobrevive
  a un Ollama ausente llamando a la función de verdad — y ella detiene todo
  proceso llamado `ollama` de la máquina. El servidor del
  modelo murió dos veces en medio de una clasificación y una más mientras
  corría la suite; un canario que verificaba el proceso tras cada test halló al
  culpable en una sola corrida. El test ahora oculta los procesos a la
  función, y un test de guarda mantiene vivo un doble de `ollama.exe`.

## [1.7.4] — 2026-11-02

Fase 36. El usuario pidió que el programa use todo lo que la máquina
tiene, automáticamente, en cualquier hardware — "el resultado más rápido
que aún garantiza la mejor información en el índice". Medido en el mismo
hardware que la 1.7.3 (RX 6700 XT 12 GB, Ollama 0.40.13, qwen3.5:9b).

### Corregido

- **Los tramos mayores que el contexto ya no se cortan en silencio.** Algunas
  solicitudes de la ejecución eran tramos de más de 20 mil tokens que
  Ollama cortaba a 8194 antes de que el modelo los viera; la guarda
  `líneas < páginas` dividía el tramo después, así que el índice no
  perdió nada, pero cada uno había pagado un intento de ~70 s que no
  podía salir bien. La solicitud ahora lleva `truncate: false` (Ollama
  0.40 responde HTTP 400 con el conteo exacto de tokens en vez de
  cortar), el rechazo o la firma antigua del corte cuentan como intento
  fallido — nunca como respuesta —, el contexto sube hasta lo que el
  tramo necesita y el tramo entero se envía de nuevo; solo cuando ni el
  techo alcanza se divide, y un tramo cuya estimación ya supera el techo
  se divide antes de cualquier solicitud.
- **El modo "cpu" y las máquinas sin tarjeta pasan a enviar `num_ctx`.**
  Ese camino retornaba antes de dimensionar el contexto, y el valor
  predeterminado de 4096 de Ollama cortaba todo tramo lleno.

### Agregado

- **Techo de contexto calculado por el hardware.** En vez de una lista
  fija que paraba en 16384, el techo es el mayor múltiplo de 4096 cuya
  caché KV cabe en la tarjeta junto al modelo entero, el margen de
  seguridad y los búferes de cálculo del runner (medidos en ~400 MiB),
  limitado a 131072 y al límite del propio modelo; en la CPU, la misma
  cuenta sobre la RAM libre, limitada a 32768. El costo de la KV cuenta
  solo las capas que mantienen caché (qwen3.5: 8 de 32 — la cuenta
  antigua por todas las capas era 4× mayor: 1 GiB calculado contra 272
  MiB asignados). Aquí pasa de 16384 a 131072, y los tramos de 26 mil
  tokens caben enteros (`size_vram == size` medido hasta 49152). Un
  modelo cuyos metadatos no dan el costo de la KV conserva los 16384
  antiguos en la tarjeta. El tipo de caché para el que se dimensiona el
  techo es el que el servidor realmente usa: con la flash attention
  desactivada, f16, diga lo que diga la variable.
- **El log dice qué backend está en uso y por qué no uno mejor**:
  "Tarjeta de video en uso: AMD Radeon RX 6700 XT (12.0 GiB), vía
  Vulkan", que Ollama atiende esta familia de modelo una solicitud a la
  vez y — en AMD RX 5000/6000 — que ROCm está fuera de alcance porque el
  controlador no trae `amdhip64_7.dll` (cualquier otra tarjeta AMD con
  controlador antiguo recibe el aviso de actualizarlo, lo que en ella
  trae ROCm). Leído solo de los logs del servidor; nada se fuerza.
- **Flash attention desactivada en Vulkan sobre AMD RX 5000/6000.**
  Medido en los mismos dos tramos: lectura del prompt a 735 contra 373
  tokens/s (2×), generación −5 %, tramo 23–28 % más corto; con la flash
  attention activada y caché f16 la velocidad no cambió, así que la
  causa es la propia flash attention en esta tarjeta. El servidor que el
  programa levanta, y el instalador en esas tarjetas, escriben
  `OLLAMA_FLASH_ATTENTION=0` y `OLLAMA_KV_CACHE_TYPE=f16` (Ollama solo
  cuantiza la caché con la flash attention activada). Un valor definido
  a mano por el usuario sigue ganando; un valor que el propio instalador
  escribió cede; el desinstalador elimina cualquiera de los dos. Dos
  límites de esa regla: un valor escrito a mano que coincida con el del
  instalador es indistinguible de él; y un tipo de caché cuantizado
  fijado por el usuario queda en el entorno, pero, con la flash
  attention desactivada, el servidor corre f16 — el techo se dimensiona
  para f16. En cualquier otra tarjeta un `OLLAMA_FLASH_ATTENTION=0`
  definido a mano se deja en paz.
- **Registro por tramo** cuando un tramo necesitó más contexto que el
  inicial o se dividió por tamaño, y un resumen de la etapa con el techo.

### Medido y dejado fuera

- Tramos en paralelo: 0,81× con dos, 1,00× con tres — Ollama fija la
  familia `qwen35` en una solicitud. Pospuesto a una fase propia, con
  medición propia; el diseño está en `docs/superpowers/specs/`.
- `num_batch` 2048 contra 1024: −2 %.
- ROCm en la RX 6700 XT: imposible con el controlador AMD actual.

## [1.7.3] — 2026-11-02

Dos constataciones de la primera ejecución de la 1.7.2 en un acervo grande,
ambas sobre memoria que parecía mal y no lo estaba.

### Corregido

- **El runner de Ollama ya no guarda una caché de prompts de 8 GB en la
  RAM.** El modelo estaba entero en la tarjeta (33 de 33 capas, 52
  tokens/s) y aun así `llama-server` retenía 16 GB de memoria del
  sistema, lo que se leyó como el modelo desbordando la tarjeta. Ocho de
  ellos eran la caché de prompts que llama.cpp mantiene en RAM por defecto
  (8192 MiB), pensada para retomar una conversación anterior — y nunca
  usada aquí: cada ventana es un prompt nuevo, y todas las ventanas
  empezaron sin nada reutilizado (el resto es el archivo del modelo
  mapeado en memoria, que Windows recupera cuando hace falta). El
  servidor que este programa levanta, y las variables de usuario que
  escribe el instalador, ahora la desactivan (`LLAMA_ARG_CACHE_RAM=0` —
  variable de todo el usuario, así que un servidor llama.cpp ejecutado a
  mano también se queda sin esa caché; el desinstalador la quita). Al
  cambiar esas variables el instalador
  también detiene el `llama-server` del propio Ollama, que puede
  sobrevivir al servidor detenido y seguir reteniendo la tarjeta.

### Añadido

- **"Modelo en la tarjeta" entre los sensores de la GPU.** La cifra de
  VRAM es la del escritorio entero (2,4 GB de los 9,2 GB medidos eran el
  navegador, el compositor y otros programas); la línea nueva viene del
  propio Ollama y dice lo que importa: "qwen3.5:9b: 100% (5638 / 5638
  MB)".

## [1.7.2] — 2026-11-02

Todo lo de abajo salió de una ejecución de un acervo en la 1.7.1, y cada corrección se comprobó contra la regla de que el programa
tiene que funcionar en cualquier computadora — con cualquier tarjeta
gráfica, o sin ella.

### Corregido

- **El OCR de páginas escaneadas de PDF vuelve a funcionar.** La carpeta
  privada de datos de Tesseract (`%LOCALAPPDATA%\GClaudeIndexer\tessdata`,
  desde la 1.5.19) tenía los idiomas pero no la carpeta `configs/`, y
  ocrmypdf le pide a Tesseract las salidas `hocr` y `txt` por esos nombres
  de configuración: toda página escaneada fallaba con código 15 (algunos PDF sin
  preparar y otros parciales; las imágenes pasaban porque
  pytesseract no pide configuración alguna). La carpeta ahora recibe
  también `configs/` y `tessconfigs/` — copiados de la carpeta del propio
  Tesseract, o los cuatro esenciales escritos cuando ninguna fuente los
  tiene — y una carpeta ya existente se repara en la primera conversión
  tras actualizar. Una carpeta sin ellos nunca se toma como lista. Las
  páginas afectadas ya están marcadas para un nuevo intento; la próxima
  conversión las rehace.
- **"Actualizar" rehace los archivos cuyo OCR falló.** Cuando el proyecto
  ya tiene ventanas de clasificación, el reintento de la propia
  conversión retiene esos archivos (rehacerlos solos dejaría las ventanas
  con las páginas en blanco antiguas) y apunta a la actualización del
  proyecto — que solo miraba bytes cambiados. La actualización ahora trata
  un archivo con OCR fallido como cambiado: las ventanas de su grupo se
  descartan y vuelve a pasar por el OCR.
- **El OCR de imágenes ya no depende de cómo se inició el programa.** La
  propia conversión pone la carpeta de Tesseract en el `PATH` de este
  proceso; antes solo lo hacía el servidor al arrancar, y una conversión
  iniciada de otro modo fallaba toda imagen con "tesseract is not
  installed".
- **Pausar responde al instante, y existe un Continuar.** Hacer clic en
  Pausar durante la carga del modelo dejaba la pantalla igual por más de un
  minuto (la solicitud solo se lee entre ventanas) y, detenida la etapa, el
  botón simplemente desaparecía. El cuadro de progreso ahora dice
  "deteniéndose" en el instante del clic y muestra un botón **Continuar**
  cuando la etapa se detuvo — retoma donde quedó. Una pausa que cae en el
  instante entre dos etapas de "Ejecutar todo" también alcanza la cadena,
  en vez de ignorarse.
- **La VRAM total es la de la tarjeta instalada.** Windows conserva la
  clave del controlador de una tarjeta retirada; sumar todas las claves
  daba 20448 MB para una tarjeta de 12 GB, y la "VRAM libre" de la
  clasificación venía inflada en lo mismo. El total ahora sigue los
  controladores de video realmente presentes, así que cambiar de tarjeta,
  o no tener ninguna, se lee bien en cada arranque. En una máquina con
  integrada y dedicada, el diagnóstico nombra la de más memoria, y la VRAM
  con la que cuenta es solo la de esa tarjeta — el modelo corre en una
  sola, y sumar ambas llegaba a recomendar un modelo que la dedicada no
  soporta.
- **Frecuencia de la CPU en un Windows de cualquier idioma.** El contador
  se buscaba por el nombre traducido del conjunto, que solo coincidía en
  inglés y portugués; en un Windows en español nunca aparecía. Ahora viene
  de una clase WMI cuyo nombre no se traduce.

### Añadido

- **VRAM en uso entre los sensores de la tarjeta gráfica** en la pantalla
  de Ejecución (pedido del usuario), leída de la propia tarjeta — el mismo
  número de la línea bajo el gráfico de la GPU.

## [1.7.1] — 2026-11-02

### Corregido

- **La barra de actividad sobrevive a la recarga en toda operación
  larga.** Actualizar, eliminar, indexar la búsqueda y limpiar intermedios
  pasan a ocupar el slot del proyecto como "importar y generar", con el
  mismo nombre del botón que las inició: una página recargada a mitad
  retoma la barra con el tiempo real. Cualquiera de estas cuatro, iniciada
  con el proyecto ocupado, recibe una página que dice qué operación está
  en curso (HTTP 409) en lugar de correr en paralelo; "importar y generar"
  y la opción del paquete siguen llevando al resultado, como desde la
  1.6.0. En la práctica son siempre secuenciales; "eliminar proyecto"
  durante una generación borraría archivos que se están escribiendo.
- **El slot nunca se queda atascado.** Se libera en cualquier salida de la
  operación (retorno, excepción, interrupción) y está vacío al arrancar
  el servidor: el slot vive en memoria, así que esto protege contra un
  módulo recargado o un futuro registro en disco, no contra un fallo visto
  en uso.
- **El tiempo transcurrido usa el reloj monotónico.** Ajustar el reloj de
  Windows a mitad de una generación ya no distorsiona la barra.
- Un token malformado en la solicitud "Leer sensores de la CPU y
  ventiladores" responde 403 en lugar de un error interno con traceback en
  el registro.
- Solo el chip SuperIO de la placa base decide el ventilador de la CPU;
  otro subhardware con un conector llamado "CPU…" a 0 RPM ya no aparece
  como "detenido".

## [1.7.0] — 2026-11-02

### Añadido

- **Velocidad de los ventiladores en cualquier máquina que la biblioteca
  pueda leer.** El ventilador de la CPU no es un sensor de la CPU: es un
  conector del chip SuperIO de la placa base, que el lector de sensores
  nunca abría. En un Nuvoton NCT6798D, por ejemplo, el ventilador de la CPU es el
  `Fan #2`, invisible antes. El auxiliar elevado ahora lee el SuperIO y elige el
  ventilador de la CPU por el nombre del sensor o, cuando la placa no lo
  nombra, por el conector fijo de CPU del chip; un conector supuesto que
  lee 0 queda "no medido" en vez de mostrar un número erróneo. El
  ventilador de la GPU en 0 RPM aparece como **"detenido"** (modo cero RPM
  con la tarjeta fría), y un valor de la CPU que falta solo por privilegio
  lo dice en lugar del guion.
- **Botón "Leer sensores de la CPU y ventiladores" en la pantalla
  Ejecutar.** Pide el lector elevado bajo demanda, con una línea que
  explica qué pedirá Windows y por qué; el acceso directo del escritorio
  sigue para quien lo prefiera automático. La ruta detrás del botón solo
  acepta la solicitud con cuatro guardas independientes — un token
  generado en cada inicio del servidor e incrustado solo en esa página,
  `Sec-Fetch-Site: same-origin`, una cabecera propia en la solicitud y un
  `Host` igual al del propio servidor —, y toda página pasa a rechazar ser
  incrustada en un frame de otro sitio (`X-Frame-Options: DENY`), de modo
  que ningún otro sitio abierto en el navegador puede hacer aparecer el
  aviso, ni por solicitud ni por clic secuestrado. Un segundo clic mientras
  Windows todavía pregunta no abre un segundo aviso.
- **Barra de actividad en toda operación larga.** Muestra el nombre de lo
  que se ejecuta y un cronómetro, no un spinner: importar y generar
  informes, guardar y generar de nuevo, descargar paquete, limpiar
  intermedios, indexar búsqueda, actualizar, eliminar. El servidor
  registra qué operación ocupa el proyecto y desde cuándo, y toda página
  del proyecto pregunta al cargar: recargar en medio de la generación
  retoma la barra con el tiempo real, con el mismo nombre que tenía al
  hacer clic. Los lectores de pantalla oyen el inicio, cada minuto
  completo y el final, no el reloj a cada segundo.

### Corregido

- El archivo de estado del lector de sensores de una sesión anterior
  (`started`, sin lector vivo) hacía que un servidor recién abierto dijera
  "el lector no respondió" antes de cualquier solicitud. Se borra al
  arrancar.

## [1.6.1] — 2026-11-01

### Corregido

- **Las "instrucciones que ya usa" se copiaban de nuevo en cada
  generación.** El texto pegado en el formulario llega con saltos de línea
  de Windows, y `project_instructions.md` se lee de vuelta con saltos
  simples; la pregunta "¿ya está en el archivo?" comparaba dos grafías del
  mismo texto y añadía otra copia en cada "Guardar y generar de nuevo" y en
  cada "Importar y generar informes", hasta que el archivo tenía varias
  copias. `merge_managed` ahora normaliza los saltos y solo
  inserta el texto pegado cuando el archivo no tiene nada fuera del bloque
  gestionado; lo que ya está fuera del bloque se conserva tal cual. Generar
  tres veces seguidas produce un archivo idéntico (prueba añadida).

## [1.6.0] — 2026-11-01

### Cambiado

- **El paquete cabe en un Project de Claude.** Un Project en claude.ai
  acepta 30 MB por archivo de conocimiento, y sus respuestas empeoran
  cuando los archivos suman más de unos millones de tokens (por encima de
  unos 500 mil ya pasa a usar búsqueda automática en los archivos). En una
  colección grande con un espejo completo del Planalto, el
  `index-<grupo>.md` del grupo principal llegaba a decenas de megabytes y a
  más de cien mil líneas, casi todas de actos federales reconocidos por el
  lector del Planalto, y el `timeline.md` era casi igual de grande: el
  mismo índice reordenado por fecha. Ningún
  troceado lo resuelve; el límite es la capacidad del Project. Cuatro
  cosas cambian en los archivos generados, y por eso esta es la 1.6.0:
  - **La legislación del Planalto va a `legislacao-<grupo>.md`**, con las
    mismas columnas del índice, generado siempre pero **fuera del paquete
    por defecto**. Legislación son los actos que el lector del Planalto
    reconoció y también cualquier página `.htm`/`.html` de la misma carpeta
    de esos actos que el lector no leyó (rectificaciones, mensajes
    presidenciales, decretos con formato inusual; en una colección grande,
    solo ellas casi duplicaban el índice del paquete): leyes, decretos y medidas provisionales Claude los
    consulta mejor directamente en planalto.gov.br, y el
    `project_instructions.md` ahora se lo dice, con la instrucción de citar
    siempre el número y la fecha del acto. El sumario en `index.md` cuenta
    documentos de la colección y actos del Planalto por separado. La opción
    **Legislación del Planalto en el paquete** (formulario de proyecto nuevo
    y pantalla de resultado, que genera los informes de nuevo) los vuelve a
    incluir.
  - **La cronología ya no repite el índice.** Los actos del Planalto quedan
    fuera (salvo con la opción anterior activada), y un grupo con más de
    2.000 piezas fechadas (`timeline_split_items`) obtiene su propio
    `timeline-<grupo>.md`, con el `timeline.md` apuntando a él. Ese archivo
    queda fuera del paquete (en una colección grande llega a cientos de
    miles de tokens, el índice del grupo reordenado por fecha); la pantalla de resultado lo enumera como
    generado pero no empaquetado. La columna Origen desapareció: archivo y
    página van en la Referencia.
  - **Un índice de grupo por encima de 25 MB sale en partes**
    `index-<grupo>-1.md`, `-2.md`…, cortando solo entre archivos de origen
    — las piezas de un mismo PDF quedan juntas. El sumario enumera las
    partes con el rango de folios de cada una. Lo mismo vale para
    `legislacao-<grupo>.md`.
  - **Líneas más compactas.** La columna Intervalo trae solo `(p. N)`
    cuando el archivo es el mismo de la columna Origen, y la columna
    Confianza solo aparece cuando el proyecto revisa confianza baja o
    alguna pieza está por debajo de `high` (era `high` en casi todas
    las líneas). Una sección nueva del `project_instructions.md`,
    "Columnas de los archivos", describe las columnas tal como quedaron.

### Añadido

- **Presupuesto de tokens antes de la descarga.** La pantalla de resultado
  enumera cada archivo que va en el `.zip` con su tamaño y tokens estimados
  (3 caracteres por token, estimación conservadora para Claude en Markdown
  tabular en portugués), el total y un aviso en dos niveles: por encima de
  500 mil tokens el Project depende de la búsqueda automática; por encima
  de `package_token_limit` (por defecto 2.000.000) deja de responder bien.
  Un archivo de más de 30 MB se marca, con los dos remedios. Nada se
  bloquea — el botón de descarga sigue activo.
- El `HOW_TO_USE.md` del paquete y los tres README explican los límites
  del Project y cómo los maneja el programa.
- Pendiente, anotado en el plan de la fase: un servidor MCP local sobre el
  índice de texto completo (`fulltext.py`), para que Claude Desktop busque
  en toda la colección bajo demanda sin subir ningún archivo — la respuesta
  definitiva para colecciones de más de unos millones de tokens.

## [1.5.19] — 2026-11-01

### Corregido

- **El idioma del OCR se instala sin derechos de administrador.**
  Tesseract trae solo inglés, y su carpeta de datos (`C:\Program
  Files\Tesseract-OCR\tessdata`) exige administrador; el instalador pedía
  elevación a Windows para copiar `por.traineddata` allí y, cuando esa
  aprobación no ocurría, el idioma faltaba y la pantalla "Acerca de"
  mandaba descargarlo a mano. Ahora los datos de idioma van a la carpeta
  de esta máquina (`%LOCALAPPDATA%\GClaudeIndexer\tessdata`), junto con
  los idiomas que Tesseract ya tiene, descargados del commit fijado de
  `tessdata_fast` con el SHA-256 verificado, y GClaude Indexer apunta
  Tesseract a esa carpeta solo en su propio proceso — nada cambia en el
  resto de la máquina. Lo hace el instalador y también el propio programa,
  al abrirse, antes del OCR y al abrir la pantalla "Acerca de": una
  máquina cuya instalación no pudo hacerlo se corrige sola en cuanto
  tenga internet. Un Tesseract que ya tiene el idioma se usa tal cual.

## [1.5.18] — 2026-11-01

### Corregido

- **Cerrar el navegador libera el proyecto para otra computadora.** El
  servidor no tiene ventana y sigue en marcha después de cerrar la última
  pestaña, y renovaba el bloqueo del proyecto cada minuto mientras
  existiera: la otra computadora recibía "en uso, última actividad hace 1
  minuto" y nunca podía abrir el proyecto. Ahora el bloqueo solo se renueva
  mientras el proyecto está en uso — una pantalla suya abierta en el
  navegador (cada una avisa al servidor cada minuto), una solicitud en
  curso o una etapa en segundo plano, de modo que una clasificación dejada
  en marcha de madrugada con el navegador cerrado conserva el bloqueo.
  Unos 5 minutos después de cerrar la última pestaña, sin nada en marcha,
  el bloqueo se elimina; abrir una pantalla de nuevo lo retoma, con la
  verificación de siempre. El mensaje que se muestra en la otra
  computadora ahora lo explica.

## [1.5.17] — 2026-11-01

### Cambiado

- **Los actos del Planalto obtienen el autor del texto completo.** La
  página que ve la clasificación se corta en el tamaño de página del
  proyecto (4.000 caracteres por defecto), y una ley larga se firma
  después de ese punto, así que muchos actos de un acervo grande quedaban
  sin autor. Ahora "Importar e gerar relatórios" lee la
  firma en la búsqueda de texto completo, que guarda el texto entero; los
  actos del Congreso, que cierran con "Congresso Nacional, em …" en lugar
  de la línea del Presidente, también se leen, y las enmiendas
  constitucionales (firmadas por las dos Mesas) reciben a las Mesas como
  autor. Casi todos los autores que faltaban se encuentran en cerca de un
  minuto, sin clasificar nada de nuevo; los pocos que quedan son casi todos
  rectificaciones, que no llevan firma.
- **Una grafía por firma.** "ERNESTO GEISEL", "Ernesto Geisel" y "ernesto
  geisel", o "Getulio Vargas" y "Getúlio Vargas", pasaron a ser un solo
  autor cada uno en el índice.
- **Una grafía por tipo de documento.** Los tipos que solo difieren en el
  acento ("INDICE"/"ÍNDICE", "SESSAO"/"SESSÃO") pasan a la forma acentuada
  cuando es lo bastante común, y la pieza sin tipo cuyo resumen dice que
  la página está en blanco recibe "PÁGINA EM BRANCO". Nombres distintos
  nunca se unen: "LEI FEDERAL" sigue separado de "LEI".
- **El resumen del hardware ya no se repite en el registro.** Cada etapa
  de "Rodar tudo até a classificação" volvía a diagnosticar la máquina y
  escribía las mismas dos líneas de cuatro a ocho veces por ejecución;
  ahora la repetición dentro de 15 minutos se omite. Los avisos siempre se
  escriben.

## [1.5.16] — 2026-11-01

### Cambiado

- **El lector del Planalto reconoce más actos.** Ordenanzas, resoluciones
  e instrucciones normativas de ministerios (el acervo de la Covid-19),
  actos declaratorios del Congreso, alvarás y actos del Imperio
  (confirmados por el encabezado del propio sitio, ya que no tienen
  cláusula de promulgación), fechas escritas sin "de" entre el día y el mes
  ("De 23 janeiro DE 1948") y títulos precedidos de "(*)". En un acervo
  grande, la proporción de páginas del Planalto leídas así subió algunos
  puntos, y los tramos que todavía envían páginas al modelo bajaron cerca
  de un tercio. Sin
  cláusula de promulgación, el resumen es la línea debajo del título, y los
  enlaces de navegación del sitio ("Não remover", "Down", "Up") ya no
  entran en él.

## [1.5.15] — 2026-10-31

### Corregido

- **Un tramo que el modelo rechaza se divide, en vez de quedar pendiente
  para siempre.** Cuando Ollama responde con un error sobre la propia
  solicitud ("prediction aborted, token repeat limit reached"), el tramo se
  clasifica en mitades hasta aislar la página ilegible, que entra en el
  índice por el nombre del archivo. Antes eso contaba como Ollama caído:
  intentos de reinicio, tres reenvíos iguales y el tramo pendiente otra vez
  en cada ejecución.
- **Las páginas con los bytes crudos de un archivo binario se leen como
  vacías.** Archivos zip, de fuentes, de audio y de CAD convertidos antes
  de la 1.5.9 guardaban una página de caracteres de control que hacía
  entrar al modelo en repetición.
- El mensaje "el modelo local dejó de responder" ya no dice que la
  ejecución pasará al motor Reglas; con tarjeta de video nunca ocurre.

## [1.5.14] — 2026-10-31

### Añadido

- **La legislación federal del sitio del Planalto se lee por su propia
  estructura, no con el modelo.** Todo acto trae las mismas partes: título
  con tipo, número y fecha, la ementa oficial, la cláusula de
  promulgación, la línea de lugar y fecha y las firmas. Tipo, número,
  fecha, firmante y resumen (la ementa oficial, más la nota de derogación
  cuando la hay) salen de ellas al pie de la letra. En un acervo grande, la
  inmensa mayoría de las páginas del Planalto se lee así en segundos, y la
  cola del modelo baja de muchos miles de tramos (días en una tarjeta de
  portátil de 6 GB) a unos cientos. Las páginas fuera
  del formato siguen yendo al modelo. La búsqueda no cambia: el texto
  completo de toda página se indexa, sea quien sea que la clasifique.
  Vale para el modelo local y para el motor Reglas; un tramo solo de actos
  ya no espera a Ollama.

### Cambiado

- **El instalador lleva Ollama a su versión más nueva** en cada
  instalación, deteniendo antes el servidor en ejecución (un `ollama.exe`
  abierto hacía fallar la actualización). Un Ollama antiguo rechaza los
  formatos nuevos de modelo.
- **El modelo local automático sigue a la tarjeta de video.** El
  instalador y el programa leen la VRAM de la tarjeta: 8 GB o más usa
  `qwen3.5:9b`, 6 GB o menos mantiene `qwen3.5:4b`. Una máquina
  actualizada desde una versión anterior sin el modelo de 9B descargado
  sigue usando el de 4B.
- En tarjetas de 6 GB el modelo sigue siendo `qwen3.5:4b`. Comparado en el mismo
  conjunto de tramos, su variante `-mtp` dio las mismas respuestas y no fue
  más rápida (162 s contra 145 s en cuatro tramos); `bonsai-2:9b` y
  `ornith-1.5:9b` fueron más lentos (2x y 9x) y cada uno falló un tramo; `qwen3-vl:8b` no cabe en una tarjeta de 6 GB y
  agotó el tiempo de carga.

## [1.5.13] — 2026-10-31

### Corregido

- **La velocidad de los ventiladores nunca aparecía en el programa
  instalado.** El lector de sensores elevado se ejecuta desde una copia
  local de algunos módulos, y el lector térmico de Dell no estaba entre
  ellos: su importación fallaba allí sin aviso. Una prueba comprueba ahora
  que la copia lleva todo módulo que el lector importa.

## [1.5.12] — 2026-10-31

### Corregido

- **Con tarjeta gráfica, la clasificación nunca recurre al motor Reglas.**
  Una ventana lenta agotó el tiempo límite, se reenvió mientras Ollama aún
  trabajaba en ella, y la ejecución entregó los miles de ventanas
  restantes al motor Reglas en minutos, sin una palabra en el registro (el
  resumen aún decía "modelo local"). Ahora, con tarjeta gráfica, un modelo
  que deja de responder se reinicia y se espera, y la ejecución sigue desde
  el mismo tramo. Un tramo que falla tres veces mientras el modelo responde
  los demás queda pendiente para la próxima ejecución. Sin tarjeta gráfica
  el motor Reglas aún cubre la falta, pero sus tramos quedan marcados y
  vuelven al modelo en la próxima ejecución.
- **Los tramos que el motor Reglas clasificó solo porque el modelo estaba
  caído vuelven al modelo** al inicio de la próxima clasificación; los que
  el modelo ya hizo se conservan.
- **Tiempo límite de una respuesta del modelo de 120 s a 300 s.** Una
  ventana de 16 páginas responde ~1.800 tokens; en una tarjeta de portátil
  de 6 GB caliente eso tomó 40 s de media y pasó de 120 s en las pesadas.
  Un servidor que aún responde ya no se reinicia tras agotar el tiempo: se
  envía de nuevo el mismo tramo.
- **Lo que imprime un servidor de Ollama iniciado por el programa se
  guarda** en `%LOCALAPPDATA%\GClaudeIndexer\ollama-serve.log`, para poder
  explicar una caída después.
- **"Extracción por página" quedaba pendiente sin nada que extraer.** Con
  todos los archivos ya extraídos, la etapa se daba por pausada y omitía el
  índice de la búsqueda de texto completo, y ningún archivo del proyecto
  llegaba a indexarse para la búsqueda.
- **La clasificación muestra el tiempo estimado tras cinco tramos**, en vez
  de tras el 0,5% de ellos (más de media hora en una ejecución grande).
- Incluye la 1.5.11 (velocidad de los ventiladores tras reiniciar Windows),
  que no tuvo instalador propio.

## [1.5.11] — 2026-10-31

### Corregido

- **La velocidad de los ventiladores quedaba vacía después de reiniciar
  Windows.** El lector de sensores elevado arranca antes de que el
  servicio térmico de Dell esté listo, y la primera lectura fallida
  apagaba los ventiladores durante toda la sesión. Ahora vuelve a intentar
  cada 30 segundos y solo desiste tras diez fallos seguidos (equipo sin la
  interfaz de Dell).

## [1.5.10] — 2026-10-31

### Velocidad de los ventiladores en portátiles Dell; controlador PawnIO para los sensores de la CPU

#### Añadido

- **Velocidad de los ventiladores de la CPU y de la GPU en portátiles gamer
  de Dell** (serie G, Alienware), leída por la interfaz térmica de la
  propia Dell (la que usa Alienware Command Center). En un portátil los
  ventiladores pertenecen al controlador embebido: ni la biblioteca de
  sensores ni el controlador de vídeo los ven (`nvidia-smi` informa
  `N/A`). La misma interfaz da la temperatura de la CPU, que aparece
  incluso sin el controlador PawnIO. Solo se usan operaciones de lectura;
  el control de los ventiladores nunca se toca. Depende del acceso
  directo del sensor de CPU (el lector de sensores elevado); en las demás
  máquinas nada cambia.
- **El instalador ofrece el controlador PawnIO, ya marcado.** La
  biblioteca de sensores lee la temperatura y la potencia de la CPU a
  través de él; sin él ambas quedaban vacías incluso con el acceso directo
  del sensor de CPU. Es un controlador de kernel de terceros
  (https://pawnio.eu/), instalado con winget, y Windows pide administrador
  para instalarlo. Se puede desmarcar; todo lo demás funciona sin él.

## [1.5.9] — 2026-10-31

### La búsqueda de texto completo ya no traba la extracción; pantalla de ejecución ágil

Los tiempos de abajo se midieron en una copia local de la base de datos de
un proyecto grande (bastante más de cien mil páginas). Con la base en Google
Drive son mayores, aunque no en órdenes de magnitud.

#### Corregido

- **Incluir los archivos en la búsqueda de texto completo se volvía más
  lento con cada archivo.** Antes de grabar un archivo, sus fragmentos
  anteriores se borraban por una columna que la tabla de búsqueda no
  indexa, así que cada archivo leía la tabla entera — incluso los nuevos,
  que no tenían nada que borrar. En un acervo grande la extracción llegaba
  al 100% y quedaba "en ejecución" por lo que habrían sido más de 100
  horas. Ahora los fragmentos de cada archivo tienen un rango registrado y
  se eliminan por él, y los textos se leen en paralelo: ~0,35 archivo/s
  antes, ~800–1.000 archivos HTML/s ahora.
- **La etapa de extracción quedaba "concluida" con la búsqueda aún en
  construcción.** Una pausa en esa fase dejaba la búsqueda incompleta y
  "Ejecutar siguiente etapa" seguía adelante. Ahora la etapa termina solo
  cuando todos los archivos están en la búsqueda, y la barra de progreso
  muestra esa fase aparte en lugar de quedarse en 100%.
- **La pantalla de ejecución tardaba unos 90 segundos en abrir** durante un
  procesamiento grande, y la tabla de etapas lo mismo en actualizarse. El
  resumen de calidad leía el texto de todas las páginas solo para
  contarlas, cada dos segundos. Ahora cuenta sin leer el texto, calcula la
  cobertura en una sola pasada y se recalcula solo cuando algo cambia:
  5,6 s → 0,2 s localmente.
- **El registro en vivo se llenaba de "La base de datos del proyecto está
  ocupada" y dejaba de actualizarse.** Ese aviso es para una página entera,
  y el registro lo pegaba en la lista cada vez que la base estaba ocupada.
  Ahora el registro salta ese ciclo y vuelve a intentar, como el resto de
  la pantalla.
- **Se perdían piezas clasificadas cuando el resumen tenía el carácter
  U+0085.** Común en HTML leído como Latin-1, partía la línea de la pieza
  en `raw_items.jsonl` en dos, y la importación descartaba ambas mitades
  como corruptas.
- **La revisión reanudada tras una pausa reenviaba al modelo todas las
  ventanas de baja confianza**, incluso las que ya había revisado. Ahora se
  omiten.

#### Cambiado

- **La clasificación graba por lotes** (motores de reglas y local): un
  commit cada dos segundos en lugar de uno por ventana y otro por evento
  registrado. Con la base en Google Drive cada commit cuesta segundos y
  bloquea la pantalla. La etapa de ventanas lee las páginas sin su texto
  cuando no escribe los archivos de las ventanas, comprueba las ventanas
  existentes con una consulta por grupo y lista la carpeta de ventanas una
  sola vez. Localmente, en la misma base: la etapa de ventanas tarda
  segundos y la clasificación por reglas cerca de un minuto.
- **Las etapas graban con menos frecuencia**: cada dos segundos o 500
  operaciones (eran un segundo o 200), así las pantallas encuentran la base
  libre más veces.
- **La conversión con OCR empieza por el archivo más grande.** En el orden
  de las rutas un PDF de cientos de páginas podía empezar último y correr
  solo durante minutos después de que todos los demás habían terminado.
- **Los archivos binarios ya no se leen como texto.** Con "todas las
  extensiones" marcado, un archivo sin extractor cuyos primeros bytes
  contienen un NUL (zip, audio, fuente, dibujo CAD) queda en el índice por
  su nombre, sin texto, en lugar de una página de caracteres de control que
  iba a la búsqueda y a los resúmenes. Vale para los archivos convertidos
  de ahora en adelante; los ya convertidos cambian al reprocesarse
  (actualización del proyecto).
- **Un archivo cuyo texto no se puede leer para la búsqueda** se registra
  en el log y se graba sin fragmentos, para que la etapa pueda terminar, en
  lugar de reintentarse en cada ejecución. Reprocesar el archivo
  (actualización del proyecto) lo trae de vuelta.
- **El instalador trae marcados la descarga del modelo de clasificación y
  el acceso directo del sensor de CPU.** Ambos se pueden desmarcar; en una
  actualización el modelo ya descargado no se descarga de nuevo.

## [1.5.8] — 2026-10-31

### Procesamiento mucho más rápido en Google Drive; la actualización detiene la versión anterior

#### Cambiado

- **Los archivos intermedios quedan en el disco local.** Los PDF con OCR,
  el texto extraído de cada archivo y los fragmentos de PDF (`converted/`,
  `blocks/`) ahora van a `%LOCALAPPDATA%\GClaudeIndexer\work\`, no a la
  carpeta de salida. En Google Drive cada archivo pequeño nuevo tardaba
  ~800 ms en crearse, frente a 0,3 ms en el disco local, y la conversión de
  un acervo grande esperaba a Drive con el procesador inactivo. Nada de lo
  que se usa del proyecto después necesita estos archivos: las páginas y la
  búsqueda de texto completo están en `project.db`, y los índices y las
  ventanas siguen en la carpeta de salida. Los proyectos convertidos antes
  siguen leyendo las copias que ya están allí. En otro equipo, un archivo
  cuya copia no existe vuelve a la conversión en lugar de fallar.
- **La conversión usa dos colas.** Los archivos que no necesitan OCR (HTML,
  texto, DOCX, correo) pasan el tiempo esperando el disco, así que reciben
  un grupo mucho mayor de procesos (hasta 4 por núcleo físico en el modo
  "máximo"). El OCR mantiene un proceso por núcleo. Medido en archivos
  HTML de Drive: pocos archivos por segundo antes, cientos por segundo
  ahora.
- **Etapa de ventanas:** los `.txt` de las ventanas solo se escriben para
  el motor Claude Code, el único que los lee, en paralelo; los que falten se
  escriben cuando ese motor se elija después. Un commit por grupo en lugar
  de uno por ventana.
- **La indexación de la búsqueda de texto completo** graba por lotes en
  lugar de un commit por archivo.

#### Corregido

- **La clasificación releía el grupo entero en cada ventana.** En un grupo
  de más de cien mil páginas eso eran cientos de megabytes leídos por
  ventana, para miles de ventanas. Ahora cada ventana carga solo sus propias
  páginas, y la columna del grupo tiene índice. Vale para los motores de
  reglas, local y de revisión.
- **Instalar una actualización dejaba la versión anterior en ejecución.**
  Al abrir el programa de nuevo, el servidor anterior aún ocupaba el puerto
  y aparecía la versión anterior. El instalador (y el desinstalador) ahora
  detiene primero los procesos del programa, incluido el servidor que el
  lanzador del entorno virtual inicia como proceso hijo. Abrir el programa
  también reemplaza un servidor de otra versión que siga en ejecución, y el
  acceso directo espera a que el servidor responda antes de abrir el
  navegador.

## [1.5.7] — 2026-10-31

### El OCR ya no falla en PDF con colores inusuales, y el OCR que falló se rehace

#### Corregido

- **El OCR fallaba en PDF con un espacio de color inusual** (común en PDF
  de imprenta), con `ColorConversionNeededError`. El reconocimiento de
  texto en sí funcionaba; lo que fallaba era la conversión del resultado a
  PDF/A, el formato de archivo, y el OCR de todo el archivo se descartaba
  con ella. La copia con OCR solo se lee para extraer el texto, así que
  ahora es un PDF común (`--output-type pdf`). También es un poco más
  rápido.
- **Un archivo cuyo OCR falló quedaba así para siempre.** Un PDF con texto
  nativo mantenía en blanco las páginas escaneadas, y un PDF todo
  escaneado seguía con error; volver a ejecutar las etapas no revisaba
  ninguno de los dos. Ahora el archivo cuyo OCR falló queda marcado y
  vuelve a la cola al comienzo de la conversión siguiente, hasta que el OCR
  funcione. Solo los errores de OCR: un archivo dañado o protegido con
  contraseña no se reintenta. La pantalla de Ejecución muestra la
  conversión como pendiente mientras haya archivos en esa situación.
- **Se recuperan los archivos que fallaron antes de esta versión.** La
  primera vez que la 1.5.7 abre un proyecto, marca los archivos cuyo OCR
  falló antes, encontrados por el error guardado en el archivo y por los
  avisos del registro, y la conversión siguiente los rehace. Un archivo que
  ya está en las ventanas de clasificación no vuelve, porque las ventanas
  quedarían desactualizadas; el registro indica su nombre.

## [1.5.6] — 2026-10-31

### El modo económico y el escaneo tampoco se bloquean; actualizaciones de seguridad

#### Corregido

- **El modo económico (paralelismo 1) todavía podía bloquearse en un
  archivo de Google Drive.** Un archivo a la vez se ejecutaba en el propio
  hilo de la etapa, que nada podía desbloquear. Ahora se ejecuta bajo la
  misma protección que el camino paralelo, en un hilo que la etapa
  abandona cuando el archivo supera su plazo. El OCR sigue ejecutándose en
  el propio proceso del programa, como antes.
- **El escaneo podía bloquearse en un archivo o una carpeta que Drive
  nunca responde.** Leer el tamaño de cada archivo y calcular su hash
  ahora tienen plazo. Un archivo que lo supera queda fuera de este
  escaneo, con un aviso en el registro, y se revisa de nuevo en el
  próximo. Tres seguidos detienen el escaneo con un mensaje claro. Una
  carpeta cuyo listado nunca responde detiene el escaneo en lugar de
  omitirse, porque una carpeta omitida parecería haber perdido sus
  archivos.
- **La verificación de actualización nunca lee una carpeta bloqueada como
  "archivos eliminados".** Informa la carpeta de origen como no
  disponible, igual que una unidad desconectada, y no ofrece borrar nada.

#### Seguridad

- **Pillow 13.0.0** (era 12.3.0), que corrige las 41 alertas de
  Dependabot contra la 12.x, entre ellas desbordamientos de memoria al
  decodificar imágenes JPEG, TIFF y FlashPix e inyección de argumentos en
  la llamada a Ghostscript. El programa abre imágenes de terceros para el
  OCR, así que esas alertas eran alcanzables.
- **Starlette 1.3.1** (era 0.52.1), que corrige el robo de credenciales
  NTLM mediante rutas UNC en `StaticFiles` en Windows, límites de
  formulario que se ignoraban y la validación de la cabecera Host. Exigió
  **FastAPI 0.162.0** (era 0.128.8), la primera serie que acepta
  Starlette 1.x.

## [1.5.5] — 2026-10-31

### El procesamiento ya no se bloquea, sea cual sea el tamaño del acervo

#### Corregido

- **La conversión podía bloquearse para siempre, y la pantalla de
  Ejecución pasaba a mostrar "Internal Server Error" cada dos segundos.**
  En una carpeta muy grande en Google Drive, Drive dejó de
  responder a algunas aperturas de archivo. Los procesos auxiliares las
  esperaron para siempre, y la etapa, que esperaba a sus auxiliares antes
  de salir, esperó con ellos manteniendo la base de datos bloqueada. Ahora
  cada archivo tiene un plazo que crece con su tamaño (10 minutos más 2
  por MB). Un auxiliar que lo supera se detiene y se reinicia, y el
  trabajo continúa. Un archivo que se bloquea dos veces mientras los demás
  avanzan se marca como fallido, con "tiempo agotado". Cuando nada avanza
  (Drive o el disco se bloqueó, no un archivo), la etapa se detiene con un
  mensaje claro y deja todos los archivos para la próxima ejecución.
- **Una base de datos ocupada tumbaba la etapa en lugar de esperar.** Un
  instante de `database is locked` terminaba la etapa con la transacción
  abierta. Ahora la etapa graba por lotes y, con la base ocupada, deshace
  el lote y lo vuelve a aplicar poco después, durante hasta diez minutos.
- **Una base ocupada aparecía en pantalla como "Internal Server Error".**
  La pantalla de Ejecución conserva lo que ya muestra y vuelve a consultar
  en el ciclo siguiente. Una página completa explica que la base está
  ocupada y que no se perdió nada.
- **Un proceso auxiliar que moría (falta de memoria) terminaba la
  etapa.** Ahora el conjunto de auxiliares se rehace y el trabajo
  continúa. Los archivos atrapados en dos caídas quedan para la próxima
  ejecución, como antes.

#### Cambiado

- **La conversión y la extracción son mucho más rápidas en una carpeta de
  Google Drive.** El modo de journal de la base pasó de `DELETE` a
  `TRUNCATE`: un commit en una carpeta de Drive bajó de unos 0,3 s a menos
  de 0,01 s, porque Drive ya no tiene que crear y borrar el archivo de
  journal cada vez. Sigue siendo un journal de reversión, con la misma
  seguridad, nunca WAL. Las etapas también graban por lotes (al menos una
  vez por segundo) en lugar de una vez por archivo.
- **Las consultas de la pantalla esperan como máximo 5 segundos a una base
  ocupada**, en lugar de 30.

## [1.5.4] — 2026-10-31

### El segundo escaneo ya no vuelve a leer todos los archivos, y su barra avanza

#### Corregido

- **"Ejecutar todo hasta la clasificación" pasaba horas escaneando de
  nuevo una carpeta ya escaneada.** El botón siempre empieza por el
  escaneo, y el escaneo recalculaba el hash de cada archivo solo para
  descubrir que nada había cambiado — en una carpeta muy grande en
  Google Drive, eso significaba reabrir los archivos uno por uno. Ahora,
  un archivo con el mismo tamaño y la misma fecha de modificación
  registrados en el inventario se considera sin cambios, sin leer su
  contenido — la misma regla que ya seguía la verificación de
  actualización. Lo que cambió se sigue confirmando por el hash.
- **La barra de progreso de un segundo escaneo se quedaba en "0 / N" hasta
  el final.** Contaba filas nuevas en el inventario, y el escaneo de una
  carpeta sin cambios no agrega ninguna. Ahora la barra sigue los archivos
  que el escaneo ya revisó.
- **Un tamaño erróneo guardado para un archivo hacía que se volviera a leer
  en cada escaneo.** Google Drive puede informar 16 384 bytes justo después
  de grabar un archivo; cuando el contenido resulta igual, ahora se guarda
  el tamaño real.

## [1.5.3] — 2026-10-30

### Los botones de ejecución responden al instante en carpetas grandes, con contador en vivo

#### Corregido

- **"Ejecutar siguiente etapa" y "Ejecutar todo hasta la clasificación"
  parecían muertos en una carpeta de origen grande.** Antes de registrar el
  escaneo, la solicitud recorría toda la carpeta dos veces para dimensionar
  la barra de progreso — minutos en una carpeta muy grande en Google
  Drive. Mientras tanto el primer botón quedaba colgado y la
  pantalla decía que no había ninguna etapa en ejecución. Ahora la tarea se
  registra al instante y mide su trabajo en segundo plano.
- **Cada clic de más abría otro escaneo sobre la misma base.** La
  comprobación de "ya está en ejecución" no veía una tarea que todavía se
  estaba midiendo. Comprobación y registro ocurren ahora bajo el mismo
  candado: un segundo clic devuelve la tarea que ya corre.
- **La barra del escaneo podía detenerse antes del 100%.** El total
  contaba `desktop.ini` y otros archivos de sistema que el escaneo nunca
  registra; el conteo usa ahora el mismo criterio del escaneo.

#### Cambiado

- **Mientras se recorre la carpeta de origen, la pantalla Ejecución
  muestra un contador en vivo** ("Contando los archivos de la carpeta de
  origen: N archivo(s) encontrado(s)"), el tiempo transcurrido, una barra
  en movimiento y el botón de pausa, para que un recorrido largo nunca
  parezca colgado.
- **La carpeta de origen se recorre una vez por escaneo, no tres.** El
  conteo entrega su lista al escaneo, y el recorrido usa `os.scandir`, que
  en Windows lee el tamaño de cada archivo del propio listado de la carpeta
  en lugar de preguntarlo archivo por archivo.
- **Los archivos `.ini` nunca se indexan**, ni con "todas las
  extensiones": Windows y Google Drive escriben uno en cada carpeta, y
  ninguno es un documento.

## [1.5.2] — 2026-10-30

### OCR página por página: las hojas escaneadas dentro de PDF nativos ya no se pierden

#### Corregido

- **Las páginas escaneadas dentro de un PDF con texto nativo llegaban en
  blanco al índice.** El OCR se decidía por el promedio del archivo —
  menos de 100 caracteres por página—, así que un PDF nativo con algunas
  hojas escaneadas en medio (un acta firmada, un anexo) pasaba el promedio
  y esas hojas quedaban sin texto. Ahora la decisión es por página: las
  páginas con menos de 100 caracteres que tienen imagen o dibujo vectorial
  van a `ocrmypdf --force-ocr --pages …`, y las demás pasan intactas.
  `--force-ocr` en lugar de `--skip-text` porque una hoja escaneada con un
  sello o un "fl. 2" como texto se omitía. En un acervo de unos cientos de
  PDF, decenas resultaron mixtos; sus hojas escaneadas pasaron de unas
  pocas decenas de caracteres a miles cada una, y las páginas nativas
  salieron idénticas.
- **Los PDF firmados digitalmente reciben OCR**
  (`--invalidate-digital-signatures`). Solo la copia interna, en la
  carpeta de salida, pierde la firma; el original nunca se toca.

#### Cambiado

- Una página con poco texto y nada dibujado (un reverso en blanco, una
  separata de capítulo) no manda un libro nativo al OCR.
- Si el OCR falla en un PDF que también tiene texto nativo, el archivo
  sigue con ese texto y un aviso indica cuántas páginas quedaron en
  blanco; un PDF totalmente escaneado sigue fallando, como antes. El
  registro dice cuántas páginas, de cuántas, recibieron OCR.
- Los proyectos ya indexados conservan su conversión: un PDF mixto solo se
  vuelve a leer cuando cambia o se reprocesa.

## [1.5.1] — 2026-10-28

### Acervos mixtos: una pieza por documento, configuración propuesta por la carpeta, toda palabra localizable

#### Corregido

- **El motor de reglas juntaba leyes enteras en una sola pieza.** En un
  acervo de una ley por archivo HTML, toda página comienza con
  "Presidência da República", ningún marcador de tipo coincidía con "LEI
  Nº" y cambiar de archivo no era señal — leyes consecutivas se volvían
  una pieza. Ahora un archivo de documento entero (HTML, DOCX, XLSX, PPTX,
  TXT, MD, correo… todo salvo PDF e imagen) siempre comienza su propia
  pieza, en los motores de reglas, local y `claude_code`. Las páginas de
  PDF y las secuencias de imágenes escaneadas siguen pudiendo formar una
  pieza, como antes.
- **Los encabezados legislativos se reconocen como tipo**
  (`heading_types` en `classification_rules.json`): EMENDA
  CONSTITUCIONAL, LEI, LEI COMPLEMENTAR, DECRETO-LEI, DECRETO, MEDIDA
  PROVISÓRIA, PORTARIA, RESOLUÇÃO, INSTRUÇÃO NORMATIVA, SÚMULA, ACÓRDÃO y
  otros — solo al comienzo de línea, en los primeros 600 caracteres, para
  que una ley citada en medio del texto no se vuelva el tipo del
  documento. Se leen fechas como "1º DE JANEIRO DE 2023". Medido en 354
  leyes del Planalto: 354 piezas, 97% con tipo, todas con fecha.
- **Los acervos "biblioteca" con varios archivos en un grupo fusionaban
  las piezas.** Allí la referencia vuelve a "p. 1" en cada archivo, y la
  posición de la página en el grupo salía de ese número — toda pieza de
  todo archivo tenía posición 1 y la consolidación las fusionaba. La
  posición ahora es el lugar de la página en el grupo
  (`group_page_positions`), usado en la importación, el mapa de página
  física del índice, el informe de lagunas y la cobertura de la calidad.
  Las ventanas de `claude_code` muestran esa posición como `[#N]` en el
  encabezado de cada página, y el `CLAUDE.md` indica usarla en
  `order_start` / `order_end`. Los acervos "processo" no estaban
  afectados.
- **Un decreto de 1962 se leía como báltico (cp1257).** Cuando la
  detección estadística encuentra Windows-1252 tan plausible como su mejor
  opción, queda Windows-1252 — la codificación de casi todo texto
  brasileño antiguo.

#### Agregado

- **Configuración propuesta a partir de la carpeta de origen.** Al elegir
  la carpeta de origen de un proyecto nuevo, el programa la examina —
  hasta 6 segundos, en una muestra de PDF y archivos de texto — y propone
  páginas por bloque, páginas por ventana, superposición, caracteres por
  página e idioma del OCR, cada uno con el motivo, además de la
  composición de la carpeta. "Aplicar" completa el formulario; nada cambia
  sin eso. Los idiomas de OCR solo se proponen si Tesseract los tiene
  instalados.
- **Búsqueda de texto completo** ("Buscar en el acervo", en las pantallas
  de ejecución y de resultado). La clasificación lee solo los primeros
  "caracteres por página" de cada página; la búsqueda guarda el texto
  entero de todo archivo, sin corte, en una tabla SQLite FTS5 dentro del
  proyecto. Los resultados dicen dónde está el texto — la página del PDF
  (`f. 12` / `p. 5`) o, en un documento entero, el artículo o título y la
  línea ("p. 1 · Art. 40") —, resaltan las palabras encontradas, marcan lo
  que estaba tachado en el original y abren el archivo original. Los
  acentos y las mayúsculas no importan; "comillas" para una frase, `*`
  para el comienzo de una palabra. La indexación corre al final de la
  extracción y retoma donde se detuvo; los archivos extraídos por una
  versión anterior entran con "Incluir los que faltan".

#### Notas

- Un proyecto "biblioteca" con varios archivos por grupo ya clasificado
  por la 1.5.0 o anterior tiene piezas fusionadas: créelo de nuevo.
- La búsqueda cubre los archivos extraídos de aquí en adelante; en un
  proyecto existente, abra "Buscar en el acervo" y use "Incluir los que
  faltan".

## [1.5.0] — 2026-10-28

### Páginas web leídas como texto, con el tachado preservado; toda codificación leída bien

#### Añadido

- **El HTML se lee, no se vuelca.** `.htm`/`.html` entraban en el índice
  como marcado crudo: `<head>`, CSS y JavaScript ocupaban los caracteres
  por página antes del primer artículo. Ahora se convierten en texto
  limpio (`html_text.py`): sin etiquetas, un bloque por línea, títulos
  como `#`, ítems de lista como `- `, celdas de tabla unidas por ` | `,
  `N<sup>o</sup>` como `Nº`. Se tolera el marcado de los años 1990, sin
  cerrar o mal anidado; si el lector aun así falla, el texto se recupera
  quitando las etiquetas — nunca fallando el archivo. Medido en el acervo
  del Planalto: 0,4 s para el Código de Proceso Civil de 1,7 MB, ~22 ms
  por ley en promedio.
- **Tachado preservado como `~~texto~~`.** En el sitio del Planalto, un
  artículo, párrafo o inciso tachado es una disposición derogada,
  suprimida o sustituida, que se mantiene en la página junto al texto
  vigente. Formas reconocidas: `<strike>`, `<s>`, `<del>`,
  `text-decoration: line-through` en el `style` y clases CSS declaradas
  con él — y fragmentos tachados en DOCX, PPTX y XLSX. El motor de reglas
  ignora el texto tachado al buscar tipo, fecha, autor y resumen; el
  prompt del motor local (solo cuando la ventana tiene la marca), el
  `CLAUDE.md` del motor `claude_code` y el `project_instructions.md` (solo
  cuando el acervo tiene la marca) explican lo que significa, en los tres
  idiomas.
- **Más formatos web:** `.xhtml`, `.xht`, `.shtml` y `.mht`/`.mhtml`
  (página guardada por el navegador en un solo archivo). Un `.xml` cuya
  raíz es `<html>` pasa por el lector de HTML; los demás XML y JSON quedan
  literales.

#### Corregido

- **La codificación se descubre, nunca se supone.** Todo archivo de texto
  se leía como UTF-8 con `errors="replace"`, y un archivo en Windows-1252 —
  toda la legislación del Planalto, la mayoría de los documentos
  brasileños más antiguos — salía como "Presid�ncia da Rep�blica".
  `text_decoding.py` ahora intenta, en este orden: la marca de orden de
  bytes (BOM), la codificación declarada (`<meta>` del HTML, declaración
  XML, `charset` del MIME) si los bytes concuerdan, UTF-8, detección
  estadística (`charset-normalizer`, ahora fijado) y, por último,
  Windows-1252/Latin-1. Las etiquetas `iso-8859-1` y `ascii` se leen como
  Windows-1252, como hacen los navegadores. Nunca lanza excepción. Vale
  para `.txt`, `.md`, `.log`, `.csv`, `.xml`, `.json`, páginas web, cuerpo
  de correo y la categoría TODOS.
- **Un correo con una etiqueta de charset desconocida ya no hace fallar el
  archivo**, y el cuerpo de correo solo en HTML se convierte en texto en
  lugar de quedar como marcado. Un `.msg` sin cuerpo en texto plano usa el
  cuerpo HTML.
- **DOCX ya no pierde el texto de los hipervínculos** (remisiones a otras
  leyes, por ejemplo).

#### Notas

- Cada archivo HTML sigue siendo una página, cortada en "Caracteres por
  página" para la clasificación; el texto limpio completo queda en
  `converted/`. Los primeros 3000 caracteres de una ley traen epígrafe,
  sumario y primeros artículos.
- Los archivos convertidos por una versión anterior mantienen el texto
  antiguo: para releer un acervo, cree el proyecto de nuevo (o elimínelo
  con "todo" y vuelva a crearlo).
- El tachado en PDF no se detecta — es una línea dibujada, no un atributo
  del texto.

## [1.4.0] — 2026-10-16

### Sus instrucciones conservadas, eliminaciones sin pérdida, un manual de verdad, más seguro por defecto

#### Añadido

- **Las instrucciones complementan las suyas en lugar de reemplazarlas.**
  `project_instructions.md` y el `CLAUDE.md` de la carpeta de salida se
  reescribían desde cero en cada ejecución: un `CLAUDE.md` que usted ya
  tenía en esa carpeta, o una regla añadida al archivo generado,
  desaparecía en la siguiente actualización. Lo que escribe el sistema
  ahora queda entre `<!-- GCLAUDE-INDEXER:BEGIN … -->` y
  `<!-- GCLAUDE-INDEXER:END -->`; todo lo que está fuera de las marcas es
  suyo y se conserva. La primera vez que se toca un archivo sin marcas, el
  original se guarda como `<nombre>.bak`. Campo nuevo **"Instrucciones que
  ya usa"** en Nuevo proyecto, que lleva las instrucciones actuales de su
  Project al inicio del archivo. La guía del paquete ahora indica pegar el
  archivo completo.
- **Manual completo dentro del programa** (menú **Manual**, `/help`), en
  portugués, inglés y español: inicio rápido, cada campo, comparación de
  motores (velocidad, calidad, requisitos), las etapas, los archivos
  generados, uso con Claude, actualización, trabajo en equipo, consejos y
  problemas comunes. La Ayuda de cada pantalla lleva a su sección.
- **Cuatro temas nuevos** — Aurora, Toga, Grafito y Océano — y una capa de
  movimiento para todos los temas (`motion.css`): cambio de pantalla suave,
  entrada escalonada, tarjetas que se elevan, botones que se hunden,
  diálogos animados, brillo en la barra de progreso. Solo se animan
  `transform`/`opacity`, y todo se desactiva cuando Windows pide menos
  movimiento.

#### Cambiado

- **El registro en vivo habla claro.** 57 mensajes reescritos en los tres
  idiomas, diciendo qué pasó y qué hacer; los detalles técnicos solo entre
  paréntesis al final. La columna de etapa muestra "Actualización" en vez
  de `update`.
- **Eliminar un documento de la colección** ahora: indexa una copia
  idéntica que sigue en la carpeta (antes el contenido desaparecía en
  silencio), registra la eliminación una sola vez y la olvida cuando el
  archivo vuelve, borra la copia con OCR en `converted/`, borra los índices
  de grupos que ya no existen (se enviaban a Claude), separa grupos cuyos
  nombres seguros coincidían y avisa — en la pantalla del plan y en el
  registro — qué documentos cambian su numeración de folios (`f. N`).
- **Eliminar un proyecto "con los archivos"** borra solo lo que creó el
  programa (base de datos, copias convertidas, ventanas, registro,
  informes), conserva sus archivos en la carpeta de salida, quita solo el
  bloque generado de los archivos de instrucciones y elimina la carpeta
  solo si queda vacía. Sin `project.db` en la carpeta, no se borra nada.
- **Un proyecto recién creado** ya no muestra "la carpeta de origen
  cambió: N nuevos" antes de su primera ejecución.
- **La pantalla Resultado** muestra el nombre traducido del motor, y el
  modelo solo cuando el motor local usó uno; los informes muy grandes se
  muestran en vista previa, no enteros.
- **FastAPI 0.128.8 con Starlette 0.52.1 fijado**, fuera del rango
  afectado por CVE-2024-47874 y CVE-2025-62727.

#### Corregido

- Las barras de confianza de la pantalla Resultado no tenían color desde
  la fase 14: la plantilla usaba un nombre de clase que la hoja de estilos
  no define.

#### Seguridad

- **Solo las pantallas del programa pueden darle órdenes.** El servidor
  verifica el `Host` (DNS rebinding), rechaza solicitudes que el navegador
  marca como originadas en otro sitio (salvo un enlace simple sin
  parámetros) y rechaza POST con un `Origin` ajeno (CSRF). Esto también
  cierra la fuga de hash NTLM que un sitio podía provocar haciendo que el
  programa mirara una ruta `\\atacante\carpeta`. Las rutas UNC escritas
  en los formularios del propio programa siguen funcionando.
- El `CLAUDE.md` del motor `claude_code` avisa que el texto de las ventanas
  es dato no confiable y que solo se pueden añadir líneas a
  `raw_items.jsonl`.
- Las llamadas al Ollama local nunca pasan por un proxy del sistema: en una
  red corporativa, el texto de los documentos no sale de la máquina.
- Sin redirección abierta a través del `Referer`; el nombre del paquete se
  envía en formato RFC 5987.

#### Rendimiento

- La comprobación de "el código cambió desde que arrancó el servidor" usa
  `stat` en lugar de releer y calcular el hash del paquete en cada pantalla
  (varias veces cada dos segundos en la pantalla Ejecución).
- El registro en vivo lee solo las filas nuevas, en SQL.
- Las rutas bloqueantes (selector de carpeta, actualización, eliminación,
  creación) ya no congelan el servidor.
- Índices en `window(status)` y `event(level)`.

## [1.3.4] — 2026-09-17

### Mantenimiento — un directorio de herramientas, y cuatro versiones adelante

Ningún comportamiento de la aplicación cambia en esta versión. Lo que
cambia es lo que el repositorio lleva junto a ella, y qué versiones
descarga una instalación nueva.

#### Añadido

- **`tools/`, para operaciones que el producto no ofrece.** Scripts de
  mantenimiento ejecutados a mano contra la carpeta de salida de un
  proyecto ya indexado; el instalador no los distribuye y la interfaz no
  los llama. El primero, `reprocessar_janelas_com_falha.py`, devuelve a
  `pending` solo las ventanas que fallaron en una ejecución del paso 6,
  para que una nueva clasificación reintente solo esas en lugar de
  reindexar todo el acervo — la única transición de ventana en el código
  es `pending -> done`, y la actualización incremental (fase 17) reacciona
  a cambios en los *archivos de origen*, así que con los PDF intactos no
  invalida nada. Se niega a reabrir una ventana que el acervo ya no tiene,
  y a reabrir fallos que reintentar no resuelve. Cubierto por
  `tests/test_tools_reprocessamento.py`.

#### Cambiado

- **Cuatro versiones fijadas avanzaron**, cada una fusionada con la suite
  entera en verde: `pillow` 10.4.0 → 12.3.0, `jinja2` 3.1.4 → 3.1.6,
  `python-multipart` 0.0.12 → 0.0.31 y `pytest` 8.3.3 → 9.0.3. Las acciones
  del CI también: `actions/checkout` 5 → 7 y `actions/setup-python` 6 → 7.

  Esto pesa más que una actualización de rutina porque el instalador
  empaqueta el `requirements.txt` y el `install.ps1` ejecuta
  `pip install -r` desde él en la máquina del usuario: hasta esta versión,
  una instalación nueva descargaba las versiones fijadas allá en la 1.3.0.
  Los avisos de `jinja2` son sobre el entorno con sandbox, que este
  proyecto no usa — renderiza sus propias plantillas vía
  `Jinja2Templates` — así que la actualización es higiene, no una
  exposición que se cierra. `pillow` es el que mereció comprobación más
  allá de la suite: son dos majors de salto, y se alcanza desde
  `_extract_text_image`, la ruta de OCR de archivos de imagen sueltos.

## [1.3.3] — 2026-09-17

### Fase 22 — "Importar y generar informes" en una unidad de red

La fase 21 corrigió la clasificación. La que quedó en pie fue la etapa
*posterior*: en un acervo de miles de páginas cuya carpeta de salida está
en Google Drive, la clasificación tardó horas y entonces **"Importar y
generar informes" tardó más de media hora por su cuenta**, sin barra de
progreso y sin ninguna señal de que estuviera trabajando en vez de
colgada. El trabajo nunca estuvo en riesgo — las piezas eran todas
válidas — pero la pantalla no lo decía, así que se volvió a pulsar el
botón. Y otra vez.

#### Corregido

- **La comprobación de rango deja de releer las mismas páginas una vez por
  pieza.** `_validate_range_within_group` le pide a la base de datos todas
  las páginas del agrupador de la pieza, para comprobar que su rango
  existe. Lo pedía una vez por pieza: **miles de consultas donde bastaba una
  por agrupador**, porque el acervo tiene pocos agrupadores, y uno de ellos
  concentra casi todas las piezas. El rango solo depende del agrupador, así
  que ahora se lee una vez por agrupador y se guarda durante la corrida.
  En ese acervo: **de decenas de segundos a menos de una décima de
  segundo** en disco local, y **de casi una hora a menos de un segundo**
  con la base en la unidad de Drive, donde cada una de esas consultas
  costaba decenas de veces más que en el disco local. La importación más
  todos los informes ahora tarda menos de un segundo donde tardaba casi
  una hora.

- **Un segundo clic ya no inicia una segunda importación.** A diferencia
  de las etapas del pipeline, esta ruta hace su trabajo dentro de la
  petición HTTP, por lo que no tiene entrada en `task_manager` y nada
  comprobaba si ya estaba en marcha. Un volcado de pila del servidor en
  uso mostró **varios hilos `import_and_generate` simultáneos**, cada uno
  tomando el GIL por turnos y cada uno a punto de ejecutar
  `DELETE FROM item` seguido de miles de inserciones sobre el mismo archivo
  SQLite. Todos terminaron, y todos escribieron el mismo resultado — pero
  cada uno tardó casi una hora. Un clic que cae sobre una
  corrida ya en marcha ahora va directo a la pantalla de Resultado.

640 pruebas pasando, frente a 638.


## [1.3.2] — 2026-09-16

### Fase 21 — contexto calibrado y nota honesta

La fase 20 corrigió el mecanismo y mantuvo el número equivocado que lo
alimenta. En una indexación larga en la 1.3.1, **cerca de una de cada
diez ventanas entró en el índice sin clasificación alguna**: cientos de
piezas con tipo, fecha y autor vacíos y el OCR en bruto en lugar del
resumen. El registro cerró en `baixa=0` y la nota todavía parecía alta.

#### Corregido

- **La razón caracteres/token deja de ser una conjetura.**
  `_CHARS_PER_TOKEN` valía 3,0, medida en prosa portuguesa. El acervo
  tenía tablas contables, y una tabla contable tokeniza a **1,45** — el recálculo por ventana de la fase 20 se
  ejecutaba y se quedaba corto siempre. La razón pasa a aprenderse durante
  la corrida con el `prompt_eval_count` que Ollama ya devuelve y el código
  descartaba, guardando el mínimo observado, con un suelo de 1,2. En ese
  acervo la razón converge a 1,45 y las ventanas que daban 0
  de 4 páginas pasan a salir con 4 de 4, todas de confianza alta.

- **Escalera de reintento.** El disparador es "filas devueltas < páginas
  de la ventana", que no depende del comportamiento interno de Ollama. La
  telemetría solo elige el siguiente contexto: un prompt truncado lo
  duplica; un prompt íntegro con respuesta hambrienta usa
  `prompt_eval + páginas × 220`. Por encima del techo de la tarjeta,
  medido por corrida, la ventana se subdivide en vez de desbordar a la
  RAM.

- **La respuesta sin presupuesto.** Un modo de fallo que nadie había
  visto: con `num_ctx` 5120 el prompt de 5091 tokens cabe entero y sobran
  29 para responder. El JSON sale cortado y el registro dice lo mismo que
  para el truncamiento, por la causa opuesta. La detección pasa a mirar
  ambos lados.

- **La cobertura no medía nada.** La consulta comparaba `page.number`, que
  es la página dentro del archivo, con `item.start_order`, que es el folio
  del grupo, sin join por grupo. Prueba directa: quitando cientos de
  piezas del índice, un hueco de cientos de folios, siguió marcando
  100,0%.

- **La nota deja de pagarse sola.** Los 40 puntos de cobertura eran
  tautológicos: la agrupación emite una pieza por página de la ventana, así
  que la página siempre está dentro de alguna pieza. Pasan a medir
  cobertura *clasificada* — páginas que el modelo describió. La misma
  corrida pasa a valer **menos**, y es sobre esa nota honesta que la
  corrección muestra su ganancia.

- **La pieza ciega deja de pasar por mediana.** La página sobre la que el
  modelo no dijo nada sigue entrando en el índice por la agrupación — esa
  garantía es lo que impide la pérdida — pero ahora con confianza `baixa`.
  Es lo que le devuelve sentido al `baixa=` del resumen de la etapa 6.

### Añadido

- **La fila del índice lleva a la página física del PDF.** `f. 417` puede ser
  la página 145 de `Vol 2.pdf` en un grupo de muchos volúmenes; el índice
  nombraba el archivo y se detenía ahí.

- **Índice por grupo, con sumario.** El `index.md` salía con miles de
  filas y más de un megabyte en un solo archivo, demasiado para que un Proyecto de Claude lo
  consulte de forma fiable. Pasa a ser un sumario de pocos KB que apunta al
  grupo y al archivo; la tabla de cada grupo va a `index-<grupo>.md`, y el
  paquete del Proyecto los lleva todos.

638 pruebas pasando, frente a 618.


## [1.3.1] — 2026-09-15

Fase 20. Tres cosas que una ejecución de indexación perdía en silencio.

Encontradas leyendo el registro de una indexación larga (`qwen3.5:4b` en una GPU de portátil). Nada se
había roto — la ejecución informó `0 falhou(aram)` en todos los pasos — y
ese era el problema: los tres defectos se informaban como advertencia, o
como nada.

### Corregido

- **Una pieza ya no se descarta por la precisión de su fecha.** Los
  documentos contables y administrativos se fechan por período —
  "competência 01/2020", "exercício 2019" — y el modelo devuelve
  `2020-01` porque es lo que dice la página. La validación exigía
  `AAAA-MM-DD` estricto y descartaba la pieza *entera* — tipo, autor,
  resumen y todo — por un campo opcional. Eran todas las piezas
  rechazadas de esa ejecución.

  La precisión reducida ahora se conserva tal como llegó. Es ISO 8601
  legítima y, lo que zanja la cuestión aquí, ordena correctamente bajo la
  ordenación lexicográfica que la línea de tiempo de `artifacts.py` ya usa
  (`2019-12` < `2020-01` < `2020-01-05`) — así que no hay nada que ganar
  inventando un primer día del mes que el documento nunca afirmó. Una
  fecha cuya precisión fina no se sostiene baja un escalón en lugar de
  desaparecer: `2021-09-31`, un día que no existe, pasa a `2021-09`,
  porque el mes sigue siendo bueno. El texto que no es fecha en absoluto —
  un intervalo, una fecha en formato brasileño — limpia el campo, y la
  pieza se escribe sin él.

- **Una pieza rechazada ya no se lleva sus páginas consigo.** La garantía
  de cobertura se ejecutaba *antes* de la validación, de modo que las
  páginas cubiertas solo por una pieza que la validación luego rechazaba
  terminaban sin pieza alguna — en silencio, ya que la advertencia de
  cobertura había decidido que no faltaba nada. En la ejecución observada
  eso dejó tramos enteros de páginas ausentes de un índice cuyo propósito entero
  es decir en qué página está cada cosa. La cobertura ahora se calcula a
  partir de las piezas que realmente sobrevivieron a la validación.

- **El contexto de Ollama se mide por ventana, no una vez por ejecución.**
  Se dimensionaba con el prompt de la primera ventana y quedaba congelado
  ahí. Una ventana más densa más adelante lo desbordaba, la respuesta
  volvía truncada, el JSON nunca cerraba y el analizador recibía cero
  filas — la ventana llegaba al índice sin clasificación alguna, solo con
  una advertencia diciendo que el modelo no había respondido sobre
  ninguna de sus páginas. Fue cerca de una de cada siete ventanas, que
  es la mayor parte de lo que informó como confianza media. El
  contexto ahora se vuelve a medir cada vez que una ventana necesita más
  que la más ancha hasta el momento, y solo crece — un `num_ctx`
  oscilante haría que Ollama recargara el modelo entre ventanas, que era
  precisamente lo que la medición única evitaba.

## [1.3.0] — 2026-09-13

Fase 19. Un instalador para quien no abre una terminal.

### Añadido

- **Un instalador para Windows.** `GClaude-Indexer-Setup-1.3.0.exe`,
  compilado con Inno Setup a partir de `installer/GClaudeIndexer.iss`.
  Pregunta dónde instalar (solo para ti o para toda la máquina), muestra
  el texto de la GPL-3.0 — la licencia que se está concediendo, no
  términos que se imponen — y pone todas las dependencias en una sola
  página, con una casilla para cada una: Tesseract y Ghostscript marcados
  y bloqueados, porque sin OCR el programa no hace aquello para lo que
  existe, y Ollama, el modelo de clasificación, las bibliotecas de sensor
  y el acceso directo del sensor de CPU a criterio de quien instala. Todo
  se descarga e instala con barra de progreso y sin que aparezca ninguna
  ventana de terminal en ningún momento.

  No está firmado digitalmente. Un certificado cuesta dinero que este
  proyecto no tiene, así que SmartScreen advierte antes de ejecutarlo;
  cada publicación incluye el SHA-256 del archivo.

- **Un desinstalador que pregunta qué debe irse.** Quitar el programa
  desde Configuración > Aplicaciones abre un diálogo con una casilla por
  cada dependencia compartida — Tesseract, Ghostscript, Ollama, los
  modelos descargados, Python 3.12 — y elimina lo que esté marcado y nada
  más. Quien quiere que Ollama se vaya puede muy bien seguir usando
  Ghostscript. La lista de proyectos nunca se toca: vive detrás de un
  interruptor que nada en el instalador acciona.

- **Un registro para ambos.** `%LOCALAPPDATA%\\GClaudeIndexer\\install-log.txt`
  y `uninstall-log.txt`, en UTF-8. La primera versión de esto se ejecutaba
  oculta y en silencio, y cuando un usuario informó que no se había
  instalado nada no había forma de saber si el script había fallado, se
  había ejecutado a medias, o había funcionado mientras él miraba
  demasiado pronto.

- **La página del proyecto en la pantalla Acerca de.** El único enlace
  hacia fuera del sistema, y no debilita la promesa de funcionamiento sin
  conexión: nada se descarga y nada se envía — la página solo se abre si
  la persona hace clic.

### Corregido

- **El instalador no ejecutaba absolutamente nada en la carpeta
  predeterminada.** Construía una línea de comandos
  `cmd /c ""powershell.exe" -File ""<ruta>"" ..."`, y las comillas
  duplicadas que necesita el análisis del propio cmd no sobrevivían al de
  PowerShell: en `C:\\Program Files\\GClaude Indexer` la ruta se cortaba en
  el espacio, PowerShell rechazaba `-File 'C:\\Program'` y caía en su
  prompt interactivo — una ventana negra ante una instalación donde no se
  había instalado ni una dependencia. El centinela lo ocultaba: `& echo
  %ERRORLEVEL%` se ejecutaba hubiera arrancado PowerShell o no, así que el
  asistente leía un código y pasaba a su página final. El desinstalador
  usaba la misma línea de comandos y fallaba igual, sin dejar siquiera un
  registro, porque la redirección formaba parte de la línea que nunca se
  ejecutaba. Ya no hay `cmd.exe` en el proyecto: el instalador escribe un
  `.ps1` con las rutas ya incrustadas y ejecuta ese archivo.

- **El modelo de Ollama nunca se descargaba.** `ollama list` y `ollama
  pull` son ambos clientes de un servidor en 127.0.0.1:11434, y tener el
  binario en disco no es tener el servidor en marcha — tras una
  instalación reciente por winget, normalmente no lo está. Eso producía
  dos respuestas erróneas en una sola ejecución: el script concluía que
  faltaba el modelo, y luego la descarga era rechazada con "la máquina de
  destino rechazó activamente la conexión". El instalador ahora arranca
  `ollama serve` antes de preguntar nada y espera hasta cuarenta segundos
  por el puerto.

- **Quitar un paquete de ámbito de usuario exige un winget sin
  elevación.** El desinstalador quitaba Tesseract, que se instala para
  toda la máquina, y dejaba Ollama y Python, que se instalan en el perfil
  del propio usuario. La eliminación ahora se intenta primero como
  usuario y elevada después, solo para lo que siga instalado.

- **`--silent` detenía la eliminación en lugar de silenciarla.** Le pide a
  winget que ejecute el comando de desinstalación silenciosa del propio
  paquete, y un paquete cuyo manifiesto no tiene ninguno rechaza la
  petición entera — tres ejecuciones informaron "Ollama: sigue instalado"
  mientras el mismo comando sin la opción lo quitó al primer intento.
  Ahora se intentan ambas variantes, y el veredicto viene de preguntarle a
  la máquina, no del código de salida de winget, que informó éxito para
  una desinstalación que no cambió nada.

- **El acceso directo del sensor de CPU nunca se creaba.** Todo su bloque
  en `install.ps1` está detrás de `if (-not $NoShortcut)`, y `-NoShortcut`
  es lo que el instalador siempre pasa, para que desinstalar elimine los
  accesos directos. Marcar la casilla pasaba `-CpuSensorShortcut` a un
  script que ya había decidido no crear ninguno, mientras la aplicación le
  decía al usuario que abriera el acceso directo que no estaba ahí. Ahora
  la sección `[Icons]` es la dueña de eso.

- **El acceso directo del sensor de CPU no hacía nada con el sistema ya
  abierto** — que es exactamente cuando alguien hace clic en él. Cada clic
  arrancaba un segundo servidor que pedía el ayudante elevado, perdía el
  puerto 8000 frente al servidor que ya estaba en marcha y moría; la vida
  del ayudante está atada al proceso que lo pidió, así que moría también,
  y al servidor que dibuja las pantallas nunca se le decía nada. El
  ayudante ahora se conecta al servidor que ya está en marcha.

- **Un modelo descargado se informaba como ausente.** La lista de modelos
  viene del servidor de Ollama, y un servidor detenido devuelve una lista
  vacía indistinguible de una máquina vacía — así que la pantalla Acerca
  de ofrecía volver a descargar 3,2 GB que ya estaban en disco. El
  almacén en disco se consulta cuando el servidor no responde.

- **La pantalla Acerca de mostraba una advertencia de conexión en la
  columna Versión.** `ollama --version` con el servidor caído imprime dos
  líneas y ambas empiezan con "Warning:"; la primera es sobre la conexión
  y la segunda lleva la versión.

- **El `PSModulePath` de PowerShell 7 mataba la instalación en el paso
  3.** Instalar PowerShell 7 antepone sus directorios de módulos para toda
  la máquina, y Windows PowerShell 5.1 — que ejecuta el instalador —
  pasaba a cargar el `Microsoft.PowerShell.Utility` equivocado y perdía
  `Get-FileHash`. Reproducido en el script anterior a la fase 19: un
  defecto latente, no una regresión.

- **El desinstalador borraba la lista de proyectos.** `projects.json` es
  la lista de acervos que el usuario ha abierto; perderla no borra ningún
  documento, pero obliga a volver a encontrar cada acervo a mano. Ahora es
  dato del usuario, que solo `-RemoveUserData` elimina — ni siquiera la
  opción de "quitar también las dependencias" la toca.

- **`review.md` no contaba los archivos duplicados.** El bucle de
  cobertura se saltaba el estado `duplicate`, de modo que un acervo con
  documentos repetidos informaba menos archivos de los que tenía.

### Cambiado

- **Nuevo logotipo, con transparencia de verdad.** El anterior era un
  JPEG, un formato sin canal alfa — la transparencia no se estaba
  perdiendo en la conversión, nunca pudo existir. El icono lleva diez
  tamaños, de 16 a 256, cada uno remuestreado aquí y no por el shell de
  Windows en el momento de mostrarlo.

## [1.2.0] — 2026-09-13

Fase 18. Los informes avisan cuando se han quedado atrás.

### Añadido

- **Un aviso cuando los cuatro archivos generados ya no describen el
  proyecto.** Esto salió de una actualización de verdad: se añadieron
  algunos documentos, la tubería exploró, convirtió, extrajo sus páginas,
  construyó las ventanas y clasificó todas ellas — y `index.md`,
  `timeline.md`, `review.md` y `project_instructions.md` siguieron
  informando los recuentos anteriores de archivos y ventanas, porque generarlos es un paso
  separado, detrás de su propio botón, que no se había ejecutado. La
  pantalla de Resultado mostraba esos archivos sin nada que dijera que
  estaban desactualizados. El dueño se enteró leyendo los números a mano.

  `generate_all_artifacts` ahora registra, en una tabla de una fila, los
  tres recuentos que describen los archivos: documentos, ventanas
  clasificadas y piezas. Cuando dejan de coincidir con la base de datos,
  dos pantallas lo dicen, cada una con el botón de regenerar al lado — la
  pantalla de Resultado siempre que difieran, nombrando qué cambió desde
  que se escribieron los archivos; la pantalla de Ejecución solo cuando ya
  no quede nada por procesar.

  Las dos pantallas usan condiciones distintas a propósito. Con ventanas
  aún esperando al modelo, decirle a alguien que genere los informes
  produciría informes incompletos en el instante en que se escriben, así
  que la pantalla de Ejecución se calla y el consejo honesto — sigue
  ejecutando los pasos — es lo que la pantalla ya muestra. En la pantalla
  de Resultado, los archivos en exhibición genuinamente son anteriores al
  proyecto pase lo que pase, así que el aviso es incondicional.

  Recuentos, no fechas de archivo: la carpeta de salida la sincroniza
  Google Drive, y el cliente reescribe la fecha de modificación de
  archivos cuyos bytes nunca cambiaron. Comparar fechas aquí repetiría el
  error que la propia detección de actualización existe para evitar.

  Un proyecto de cualquier versión anterior no lleva estado registrado y
  nunca se informa como desfasado — no hay con qué comparar, y una
  advertencia sin suelo debajo es peor que ninguna. La primera generación
  en esta versión registra el estado; todas las siguientes se comprueban.

### Corregido

- **`review.md` contaba cinco de los seis estados de archivo.** La lista
  de cobertura recorría `discovered`, `converted`, `extracted`, `failed` y
  `skipped`, pero no `duplicate` — de modo que un archivo que entró como
  copia de otro ya indexado desaparecía del informe, y la cobertura
  simplemente no cuadraba con el acervo, sin nada que explicara la
  diferencia. Ahora una prueba recorre todos los estados que escribe
  `scanning.py`, para que la misma brecha no pueda reabrirse por un estado
  añadido más tarde.

## [1.1.0] — 2026-09-13

Fase 17. Un acervo deja de tener que reindexarse desde cero cada vez que
cambia.

### Añadido

- **Actualización incremental.** Apunta la aplicación a un proyecto cuya
  carpeta de origen ha cambiado y ahora detecta qué es nuevo, qué se ha
  editado y qué se ha quitado, invalida solo lo que el cambio realmente
  afecta, y reprocesa eso. Añadir un documento a un acervo de 500 páginas
  reclasifica **una ventana en lugar de treinta y seis** — alrededor de un
  minuto frente a dieciocho y medio.

  La razón de que pueda ser tan barato es la forma de la invalidación. Los
  documentos se agrupan, las páginas de un grupo se concatenan, y la
  concatenación se corta en ventanas solapadas de tamaño fijo. Un cambio
  no invalida un archivo; invalida el grupo *desde la primera página que
  se desplazó en adelante*, porque fuera del modo biblioteca la referencia
  de una página (`f. N`) se cuenta corriendo por todo el grupo, de modo
  que un archivo que gana o pierde páginas desplaza la numeración de todos
  los archivos posteriores. Todo lo anterior a ese punto conserva sus
  páginas, sus referencias y su clasificación.

  Los archivos posteriores a la divergencia que no cambiaron vuelven al
  estado `converted`, no `discovered`: la extracción los relee del
  artefacto ya convertido y **no vuelven a pagar OCR**.

- **Una pantalla de confirmación, y un aviso en la pantalla de
  Ejecución.** Abrir un proyecto cuya carpeta ha cambiado muestra cuántos
  documentos son nuevos, editados y eliminados. La confirmación nombra los
  archivos que se reprocesarán y declara el coste: cuántos pasan por OCR
  de nuevo, cuántas ventanas se reclasifican, cuántas conservan su
  clasificación. Dos de esos números son exactos; las ventanas que añadirá
  un documento *nuevo* dependen de su número de páginas, que nadie conoce
  antes de la extracción, así que la pantalla lo dice en lugar de estimar.

  El aviso se solicita después de renderizar la página, no antes. En un
  acervo grande sincronizado por Drive, recorrer la carpeta lleva
  segundos, y pagarlos antes del primer píxel cambiaría un problema por
  otro.

- **Los documentos eliminados se informan.** Un documento sacado de la
  carpeta de origen sale de `index.md` y `timeline.md`, que describen el
  acervo tal como es hoy, y aparece en `review.md` — que ya es el informe
  de huecos y fallos — con el momento en que se fue. Una tabla nueva,
  `removed_file`, guarda eso como estado y no como entrada de registro,
  que desaparecería si se limpiara el registro.

### Cambiado

- **La detección lee tamaño y fecha de modificación antes de leer
  bytes.** El diagnóstico se ejecuta cada vez que se abre la pantalla de
  Ejecución, y calcular el hash de un acervo entero sincronizado por Drive
  cada vez obligaría al cliente a descargar archivos que nadie pidió. El
  hash sigue teniendo la última palabra, porque Drive reescribe fechas de
  modificación de archivos cuyo contenido nunca cambió — sin ese
  desempate, la aplicación informaría "cambió" constantemente, que es el
  peor defecto que puede tener una advertencia. Una columna nueva,
  `file.mtime`, guarda el valor de comparación.

- **Las páginas de un grupo se ordenan de forma determinista**, por ruta
  natural y número de página, en lugar de por orden de inserción. Ambas
  coincidían en un proyecto construido de una sola pasada; tras una
  actualización no coincidirían, y un documento corregido habría saltado
  al final de su grupo.

### Corregido

Cuatro caminos hacia un índice equivocado sin error y sin advertencia,
tres de ellos alcanzables en uso corriente y todos hallados antes de
publicar:

- **La geometría de las páginas se derivaba de dos fuentes distintas.** Un
  módulo sumaba `file.page_count`, otro contaba filas en la tabla `page`.
  Un archivo que convierte con éxito y luego falla en la extracción
  conserva un recuento distinto de cero sin páginas — un PDF ilegible en
  un acervo — y los dos discrepaban, dejando una ventana clasificada sobre
  páginas que se habían movido bajo ella.

- **Las piezas clasificadas sobrevivían a sus ventanas.** La invalidación
  borraba las filas de ventana, sus archivos de texto y sus páginas, pero
  nunca podaba `raw_items.jsonl`, al que el motor de clasificación añade y
  que el paso de importación relee entero. Piezas de ventanas descartadas
  sobrevivían con referencias obsoletas, pasaban la validación porque el
  rango todavía cabía en el grupo, y se fusionaban con piezas vivas — de
  modo que un `index.md` actualizado podía atribuir páginas a un documento
  que ya no estaba en el acervo.

- **Un documento renombrado se trataba como duplicado de sí mismo.** Su
  contenido coincidía con la fila que la actualización estaba a punto de
  borrar, así que se quitaba del plan; la exploración siguiente veía un
  archivo completamente nuevo e insertaba páginas que el plan nunca había
  previsto.

- **El estado que deja tras de sí una actualización exitosa se leía como
  una disposición corrupta**, porque la comprobación comparaba recuentos
  de ventana en lugar de claves de ventana. La pantalla entonces invitaba
  a una segunda actualización que habría descartado todo lo que la primera
  preservó.

Tres defectos más, uno de ellos una regresión que esta fase habría
introducido:

- **Limpiar los archivos intermedios ya no rompe la siguiente
  actualización.** El botón de "liberar espacio en disco" de la pantalla
  de Resultado borra la carpeta `converted/`, y la ruta de renumeración
  suponía que seguía ahí: todo documento sin cambios posterior a la
  divergencia habría quedado marcado como `failed` y habría desaparecido
  del índice de forma permanente, irrecuperable, porque la conversión solo
  recoge archivos `discovered` y una nueva exploración los salta. La
  actualización ahora comprueba que el artefacto existe y vuelve a pagar
  OCR cuando no existe.

- **Un archivo no soportado ya no invalida un acervo entero.** Soltar un
  `readme.txt` en un proyecto solo de PDF, o una copia duplicada de un
  documento ya indexado, hacía que el plan invalidara el grupo entero por
  un archivo que la tubería nunca indexaría.

- **Una ventana recreada escribe su texto nuevo.** El nombre del archivo
  de texto deriva de las posiciones de la ventana, así que un documento
  corregido sin cambiar su número de páginas producía el mismo nombre, y
  el texto viejo sobrevivía junto a la clasificación nueva.

### Migración

Nada que hacer. Un proyecto creado por la 1.0.1 abre en la 1.1.0 sin
ningún paso manual: `removed_file` la crea `CREATE TABLE IF NOT EXISTS` y
`file.mtime` un `ALTER TABLE` protegido por `PRAGMA table_info`, ambos
reejecutados cada vez que se abre un proyecto. La columna empieza vacía,
así que la primera actualización de un proyecto existente calcula el hash
del acervo una vez para rellenarla; de la segunda en adelante se aplica la
ruta rápida.

### Pruebas

537 pasando, frente a 456. La fase añade 81, de las cuales la que más
importa es una prueba de equivalencia: una actualización incremental debe
producir artefactos indistinguibles de una reindexación completa sobre la
misma carpeta final. Todas las demás pruebas de la fase existen para
explicar *por qué* aquella falló, cuando falla. Fue la que atrapó el
defecto de `raw_items.jsonl` de arriba.

## [1.0.1] — 2026-09-03

La publicación que sale con el primer anuncio público del proyecto.

### Cambiado

- **El modelo local predeterminado ahora es `qwen3.5:4b`, en lugar de
  `gemma4:e4b`.** Es la medición del propio proyecto llegando por fin al
  valor predeterminado: sobre las mismas ventanas de un documento de 31
  páginas, con cada modelo enteramente residente en una tarjeta de 8 GB,
  `qwen3.5:4b` rellenó el campo de tipo en el 100% de las piezas a 30,8
  s/ventana, frente al 79,5% a 38,5 s/ventana de `gemma4:e4b` — mejor y
  más rápido a la vez, que no es la forma habitual de ese intercambio. El
  README lo recomendaba desde la fase 15; `DEFAULT_LOCAL_MODEL` no había
  seguido. `gemma4:e4b` sigue siendo seleccionable en el formulario de
  nuevo proyecto para quien quiera comparar, pero ya no es lo que descarga
  el instalador.

  El efecto práctico está en el primer uso, no en la calidad:
  `gemma4:e4b` tira ~9,6 GB de Ollama aunque solo ~3,1 GB queden
  residentes, así que una primera ejecución ahora descarga alrededor de un
  tercio de lo que descargaba, y cabe en una tarjeta de 6 GB tan
  cómodamente como en una de 8 GB. `install.ps1` lee `DEFAULT_LOCAL_MODEL`
  desde Python en lugar de fijar un nombre, así que siguió el cambio por
  sí solo.

### Corregido

- **La comprobación de hardware le decía a toda máquina que necesitaba
  ~9,6 GB que no necesitaba.** `ESTIMATED_MODEL_SIZE_MB` estaba calibrado
  para `gemma4:e4b` y es el número al que recurre `choose_model` antes de
  que Ollama pueda informar un tamaño real — es decir, exactamente en la
  primera ejecución, cuando no se ha descargado nada todavía. Dejado en
  9_600 junto a un valor predeterminado de 3,2 GB, habría empujado a
  máquinas en el límite hacia el motor `rules` por una memoria que nunca
  tuvieron que tener. Ahora 3_232, el tamaño que el Ollama de esta máquina
  informa para `qwen3.5:4b`.

### Documentación

- **Un GIF de demostración (`demo.gif`) al principio de los tres
  READMEs**, recorriendo las cuatro pantallas en orden — proyectos, nuevo
  proyecto, ejecución, resultado.
- **El requisito de Python 3.12 ya no se lee como un paso manual.** El
  instalador descarga e instala Python 3.12.10 para el usuario actual
  desde la tarea 4 de la fase 15, y la sección "Instalación" lo decía,
  pero el punto de "Requisitos" encima todavía le decía al lector que
  fuera a seleccionar el 3.12 por su cuenta — lo primero que lee un
  recién llegado, describiendo una barrera que ya no existe.
- **Los enlaces de idioma ahora encabezan cada README**, con los otros dos
  idiomas nombrados en su propia lengua, en lugar de plegados en una línea
  de letra pequeña.
- La captura `new.png` se rehízo: mostraba `gemma4:e4b` seleccionado en el
  desplegable de modelos, que ya no es lo que muestra una instalación
  nueva.

## Fase 16: Informe de la Segunda Máquina — publicada en la 1.0.1

Todo en esta fase viene de una sola fuente: el mantenedor instaló el
sistema en un segundo ordenador y anotó las ocho cosas que estaban mal en
él. Cada entrada de abajo nombra el defecto tal como se vivió, no como se
implementó.

### Corregido

- **Ventanas de consola parpadeaban sobre el escritorio durante todo el
  OCR y la conversión de Ghostscript.** `subprocess_utils.run_hidden` ya
  ocultaba todo comando que ejecuta este código; no podía ocultar los que
  ejecutan las bibliotecas. `pytesseract` arranca `tesseract.exe` con su
  propio `Popen`, y `ocrmypdf` arranca Tesseract, Ghostscript, `pngquant`
  y `jbig2` desde dentro de su tubería — ninguno con `CREATE_NO_WINDOW`, y
  ninguno bajo nuestro control. Que el servidor no tenga ventana es
  exactamente lo que hacía visible a cada uno de ellos: un proceso sin
  consola que arranca un hijo de consola hace que Windows asigne una
  consola nueva **y la muestre**. La supresión ahora es una propiedad del
  proceso y no de puntos de llamada individuales (`no_window.install()`
  envuelve `subprocess.Popen.__init__`), aplicada en el servidor, en cada
  trabajador del grupo de conversión (`initializer`), en el nuevo
  `_ocr_runner` que hace de frente a la línea de comandos de ocrmypdf y —
  mediante un `sitecustomize.py` en el `PYTHONPATH` del subproceso de OCR
  — en los trabajadores del grupo `--jobs` del propio ocrmypdf, que son
  los padres directos de Tesseract.
- **Los sensores de CPU seguían vacíos incluso usando el acceso directo
  elevado.** La carpeta del proyecto es una unidad virtual de Google
  Drive, montada bajo el token de sesión del usuario conectado. Un proceso
  elevado corre bajo la mitad de administrador del mismo token dividido, y
  Windows no traslada las asignaciones de unidad a través de esa frontera
  — `H:\...` no existe para el hijo elevado, así que `python -m
  gclaude_indexer.sensor_service` fallaba con "No module named" antes de
  ejecutar una línea nuestra, en silencio, porque el ayudante corre bajo
  `pythonw.exe` con `SW_HIDE`. Los cuatro módulos que necesita el ayudante
  ahora se replican en `%LOCALAPPDATA%` y se ejecuta desde ahí. La carpeta
  local del propio servidor también se pasa por la línea de comandos, para
  que elevar con una cuenta de administrador *distinta* no pueda publicar
  la lectura en un perfil que el servidor nunca lee. Un estado nuevo,
  `helper_sem_resposta`, distingue "el ayudante arrancó y no respondió" de
  "nunca lo pediste" — ambos se veían idénticos en pantalla, así que el
  consejo mostrado era hacer lo que el usuario ya había hecho.
- **La VRAM de la GPU nunca se llenaba antes de que el trabajo se
  desbordara a la RAM.** `options.num_gpu = -1` se lee como "usa toda la
  GPU posible" y no lo hace: entrega la decisión al planificador de
  Ollama, que dimensiona la caché KV para `OLLAMA_NUM_PARALLEL`
  peticiones simultáneas (cuatro por defecto, donde este clasificador
  envía una), guarda su propio margen encima, y redondea hacia abajo. Dos
  cambios independientes: los ajustes que deciden qué cabe ahora los
  escribe el instalador como variables de entorno del usuario y se pasan a
  cualquier servidor Ollama que este programa arranque por su cuenta (un
  modelo cargado, una plaza paralela, flash attention, una caché KV
  cuantizada); y `gpu_budget.py` mide la VRAM libre, lee la forma real del
  modelo y pide un número **específico** de capas en lugar de "tantas como
  quepan". `num_ctx` también se envía ahora explícitamente — el valor
  predeterminado de 4096 tokens de Ollama es menor que una ventana
  completa con los ajustes predeterminados de este proyecto, y un prompt
  más largo se estaba truncando en silencio.
- **Hacía falta reiniciar antes de que el sistema funcionara en una
  máquina nueva.** La instalación estaba completa; el cambio del `PATH` no
  había llegado a los procesos que ya estaban en marcha. `install.ps1` lo
  escribe en el registro y difunde `WM_SETTINGCHANGE`, que el Explorador
  ignora con frecuencia, así que todo proceso que arranca el Explorador —
  el acceso directo, `Indexer.vbs`, `Indexer.bat`, el servidor, todo lo
  que el servidor engendra — conservaba el entorno anterior a la
  instalación, y solo cerrar sesión (lo que reinicia el Explorador) lo
  arreglaba. Dos correcciones independientes, cualquiera de ellas
  suficiente: el instalador registra la ruta absoluta de todo lo que
  instaló en `tools.json` en el momento en que lo instala, y `tools.py`
  consulta eso antes que el `PATH`; y `Indexer.bat` reconstruye el `PATH`
  desde el registro antes de arrancar nada.
- **El registro en vivo no se podía desplazar, leer, seleccionar ni
  copiar.** Tres causas distintas, todas reales. `.log` y `.log-box`
  tenían ambos `overflow-y: auto`, así que la lista interna era la que
  realmente se desplazaba mientras el script movía la caja externa. Las
  líneas se renderizaban de la más nueva a la más vieja, mientras el
  comportamiento de "seguir" se desplazaba al *final*, así que acompañar
  una ejecución arrastraba al lector a la línea visible más antigua cada
  dos segundos. Y HTMX reemplazaba todo el contenido del panel en cada
  consulta, lo que borraba cualquier texto que el usuario hubiera
  seleccionado. El registro ahora es cronológico, la caja externa es el
  único contenedor que se desplaza (y se puede arrastrar para hacerla más
  alta), y las líneas nuevas se **añaden** mediante `/run/log?since=<id>`
  en lugar de reconstruir el panel. La actualización se pausa mientras hay
  una selección activa, y hay botones de "ir al final" y "copiar".
- **El tiempo estimado para terminar cada paso estaba mal.** Dividía
  elementos terminados entre segundos transcurridos. Eso contaba lo
  equivocado (un PDF escaneado de 900 páginas y una nota de 3 KB son ambos
  "un archivo"), promediaba sobre la ventana equivocada (incluyendo costes
  de arranque que ocurren una sola vez, y sin poder reaccionar cuando el
  ritmo real cambiaba), y saltaba en cada consulta. `web/eta.py` ahora
  pondera el progreso por bytes en los pasos que procesan archivos,
  promedia la tasa exponencialmente para que domine el ritmo reciente,
  suaviza lo que llega a la pantalla, y descarta la estimación por
  completo — en lugar de hacer cuenta atrás hacia un momento que no va a
  llegar — cuando un paso se atasca.
- **Los proyectos guardados en un ordenador no aparecían en otro.** Los
  proyectos en sí se sincronizan por Drive; la *lista* de ellos vivía en
  `%LOCALAPPDATA%`, así que un segundo ordenador abría con una pantalla de
  Proyectos vacía teniendo todos los proyectos ahí mismo en disco. El
  catálogo ahora puede vivir en una carpeta de Drive elegida en la
  pantalla de Proyectos. Las rutas se guardan relativas a esa carpeta
  además de absolutas, y la relativa gana al leer, porque la letra de
  unidad difiere entre máquinas (`H:` aquí, `G:` allí — sección 11.5).
  Fijar la carpeta también copia en ella los proyectos existentes de la
  máquina. Los proyectos que viven en el disco local de otro ordenador se
  listan y se marcan como fuera de alcance, en lugar de ocultarse.

- **Apuntar "Nuevo proyecto" a una carpeta que ya contenía uno destruía la
  configuración de aquel proyecto, en silencio.** Ese era el único gesto
  disponible para reabrir, y se aceptaba sin una palabra: `create_project`
  INSERTABA una *segunda* fila en la tabla `project` del propio proyecto,
  y `load_project` leía `ORDER BY id DESC` — la más nueva — así que los
  valores del formulario pasaban a ser los del proyecto. Todo archivo
  explorado, página y pieza sobrevivía, que es lo que lo hacía invisible:
  parecía haber funcionado. El tema guardado había desaparecido y los
  ajustes estructurales se iban con él, así que un proyecto cuyas ventanas
  se habían construido con 8 páginas cada una seguía con 16. Medido, no
  inferido. El formulario ahora detecta el proyecto existente, se detiene
  con un 409 y ofrece abrirlo; y `load_project` lee la *primera* fila,
  restaurando la configuración original en toda base de datos donde esto
  ya ocurrió. Las filas extra deliberadamente no se borran — son el único
  registro que queda del segundo intento, y una reparación que destruye
  evidencia para ordenar no es una reparación — y se registra una
  advertencia una vez por base de datos diciendo qué configuración está en
  vigor.

- **`uninstall.ps1` no se ejecutaba en absoluto desde un prompt de
  PowerShell.** No era un defecto del script: Google Drive marca todo
  archivo que sincroniza con `Zone.Identifier`/`ZoneId=3` — "vino de
  internet" — y la directiva de ejecución predeterminada de Windows,
  RemoteSigned, se niega a ejecutar un `.ps1` de esa zona sin firma
  digital. El mensaje ("el archivo no está firmado digitalmente") se lee
  como si el script estuviera roto. Se aplicaba igualmente a
  `install.ps1`, y solo nunca apareció porque ese siempre se arranca
  mediante `Indexer.bat`, que pasa `-ExecutionPolicy Bypass`; el
  desinstalador era el único script sin lanzador propio. Se añadió
  `Desinstalar.bat` — el acceso directo del escritorio ahora apunta a él,
  y reenvía `-WhatIfOnly`/`-KeepDependencies`/`-RemoveAll` — y
  `install.ps1` ahora ejecuta `Unblock-File` sobre los scripts de esta
  carpeta, para que el comando directo también funcione. La directiva de
  ejecución en sí se deja en paz: es un ajuste de seguridad de toda la
  máquina, y no le corresponde a un instalador cambiarlo.
- **Un servidor puede ejecutar código más viejo que los archivos en disco,
  y nada lo decía.** Python carga un módulo en memoria una vez, al
  arrancar; editar el archivo después no cambia nada para un proceso ya en
  marcha. Observado aquí de la peor manera: un servidor dejado en marcha
  de madrugada mantuvo el código viejo durante horas después de guardada la
  corrección, pasando esas horas produciendo un índice con un defecto que ya se había
  arreglado. La única pista era una línea de registro que el usuario leyó
  por casualidad y le pareció rara. Ahora todas las pantallas llevan un
  banner cuando el código fuente en disco difiere del que cargó el
  proceso.

  Comparado por **hash de contenido, no por fecha de modificación**: la
  carpeta del proyecto la sincroniza Google Drive, y un cliente de
  sincronización reescribe marcas de tiempo de archivos cuyos bytes nunca
  cambiaron. Una comparación por fecha gritaría que viene el lobo con
  frecuencia suficiente para ser ignorada, que es lo peor que puede ser
  una advertencia. Calcular el hash de cada `.py` del paquete cuesta unos
  milisegundos y nunca informa un cambio que no sea real.

- **El desinstalador ya no recibe un acceso directo en el escritorio**
  (decisión explícita del usuario). El escritorio es para lo que abres
  todos los días, y un desinstalador es lo contrario de eso — un botón que
  nadie pretende pulsar, junto al que pulsa a diario, con el mismo icono.
  Queda a dos clics de distancia en `Desinstalar.bat`, en la carpeta del
  proyecto junto a `Indexer.bat`. `uninstall.ps1` sigue quitando el acceso
  directo de las máquinas que ya tengan uno.

- **Una recomendación de modelo medida, y los ajustes que la acompañan.**
  Cinco modelos evaluados sobre ventanas idénticas de un documento de 31
  páginas, todos ejecutándose enteramente en una tarjeta de 8 GB:
  `qwen3.5:4b` (3,0 GB) alcanza el 100% de las piezas con tipo y fecha en
  30,8 s por ventana, frente a 116,9 s de `granite4.2:8b` con la misma
  calidad, y cabe en una tarjeta de 6 GB con la misma comodidad — un solo
  ajuste para toda máquina. El modelo mayor de la misma familia perdió
  frente al menor (`qwen3.5:9b`: 79,5% en 86,2 s), lo que se deriva de lo
  que la tarea es ahora: describir una página es lectura y disciplina de
  formato, no razonamiento profundo. `pages_per_window` de 8 queda
  documentado como el valor a usar, y `pages_per_block` queda documentado
  por lo que es — un ajuste que produce archivos auxiliares y que **no**
  afecta al índice en absoluto.

- **Nada del acervo puede faltar en el índice — y faltaba.** El propósito
  de este sistema, declarado por su dueño: el índice se lee para encontrar
  *en qué PDF, en qué página* está una respuesta, sin cargar los PDF
  mismos dentro de un proyecto de Claude. Una página ausente del índice es
  información que nadie puede volver a encontrar. Evaluado sobre un
  documento de 31 páginas, cinco modelos de tres familias —
  `gemma4:e4b`, `qwen3:8b`, `qwen3.5:9b`, `qwen3.5:4b`, `granite4.2:8b` —
  cubrieron entre el 0% y el 9,7% de las páginas, todos ellos informando
  confianza "high". Añadir una regla explícita de "cubre todas las
  páginas" al prompt llevó a dos modelos al 22,6% — *la misma cifra para
  ambos*, que fue lo que cerró el diagnóstico: cuando modelos
  independientes fallan de forma idéntica, la equivocada es la tarea, no
  el modelo.

  La tarea estaba pidiendo aritmética. "Devuelve las piezas, cada una de
  ref_start a ref_end" hace que el modelo enumere rangos que deben sumar
  exactamente la ventana, sin hueco y sin solapamiento. Un modelo pequeño
  lee bien una página y cierra mal esa contabilidad.

  Así que la pregunta se invirtió: **una línea por página**. El modelo dice
  qué hay en cada página y nada más; la agrupación en piezas pasó a ser
  trabajo del código, que sabe contar. La cobertura ahora es una
  propiedad, no una esperanza — `_group_pages_into_items` recorre las
  páginas de la ventana, no la respuesta del modelo, así que una página
  que nunca mencionó llega igualmente al índice con su propio texto.

  Se encontraron y corrigieron dos defectos más durante esa medición:

  * Pedirle al modelo que devolviera la referencia citable de la página
    ("copiada exactamente como aparece") hizo que `qwen3.5:4b` copiara el
    texto ENTERO de la página dentro del campo `ref`; el JSON se pasó de
    su límite antes de cerrar y el analizador recibió cero filas. Las
    páginas ahora se numeran de 1 a N y el modelo devuelve el número — un
    entero no puede confundirse con el contenido, y el código ya sabe qué
    referencia corresponde a cada posición.
  * El modelo marcó `continues: true` en ocho secciones consecutivas del
    mismo informe que él mismo había nombrado correctamente — leyó
    "continúa el mismo *informe*" donde el prompt quería decir "el mismo
    *tema*". La agrupación ahora se decide en código, comparando temas;
    `continues` solo desempata cuando la redacción de un tema cambia sin
    que cambie el documento (dos partes de una sección con títulos un poco
    distintos).

- **La cobertura ahora tiene el mayor peso en la puntuación de calidad (40
  de 100).** No se medía en absoluto, y esa era la brecha que expuso el
  benchmark: el resultado del 9,7% de cobertura de arriba puntuaba cerca
  de 100, porque el puñado de piezas que existía tenía confianza perfecta
  y relleno de campos perfecto. La cobertura es el único fallo sin remedio
  más adelante: un tipo vacío puede reclasificarse, una página ausente del
  índice simplemente no se encuentra nunca. La confianza bajó a 35 y el
  relleno de campos a 25 para hacer sitio.

- **Un límite de longitud para el resumen (600 caracteres por pieza).** El
  índice entero tiene que caber en el contexto de un proyecto de Claude;
  es la suma de esos resúmenes la que lo llena. Sin un límite, el índice
  crecería hasta convertirse en una segunda copia del acervo, que es
  precisamente lo que existe para evitar.

- **Los campos del propio formulario de proyecto nunca llegaban al
  modelo.** `subject`, `collection_type`, `role_instructions` y
  `extra_rules` se recogían, validaban y guardaban, y luego se usaban solo
  para escribir `instrucoes-do-projeto.md` — un artefacto producido
  *después* de la clasificación. Ningún motor se los mostraba al modelo. El
  coste apareció en un acervo de material didáctico: clasificado por un
  prompt cuyos únicos ejemplos trabajados eran "OFÍCIO, MEMORANDO,
  PARECER", casi toda pieza volvió sin tipo alguno. El modelo no estaba
  fallando; estaba respondiendo la pregunta que se le había hecho. El
  motor `local` ahora construye un bloque de contexto a partir de esos
  campos, enmarcado como *qué es este acervo* y no como la tarea — una
  entrada de `extra_rules` puede ser una instrucción para el uso posterior
  del índice en investigación, y no algo que un clasificador deba intentar
  ejecutar.
- **El prompt pedía documentos y aceptaba páginas.** La misma ejecución
  produjo casi una pieza por página, cortando de una o dos páginas a
  través de documentos que corrían por decenas. El
  prompt ahora declara la regla explícitamente, junto con el fallo que
  pretende evitar.
- **`ÍNDICE` e `Índice` eran dos tipos de documento distintos.** Los tipos
  se normalizan (mayúsculas, espacios colapsados) a la entrada, y las
  palabras que un modelo devuelve en lugar de dejar el campo vacío
  (`null`, `N/A`, `desconhecido`) se tratan como vacío, en lugar de
  guardarse como tipos propios.
- **Un `desktop.ini` era la pieza número uno de un índice**, resumido como "archivo de configuración del sistema
  operativo". Los archivos que el sistema operativo y los clientes de
  sincronización dejan atrás ahora se saltan, mediante una lista explícita
  y no mediante una regla como "archivos ocultos" — un acervo puede
  contener legítimamente un documento cuyo nombre empieza por punto.
- **La puntuación de calidad castigaba al motor por acertar.** La tasa de
  relleno cobraba por un `date` vacío en cada pieza, y los apuntes de
  clase no son documentos fechados: 15 de los 30 puntos de relleno se
  perdían por la respuesta correcta, y 100 era inalcanzable por buena que
  fuera la clasificación. `date` ahora solo cuenta para acervos que
  realmente tienen fechas (umbral del 5%, para que una fecha inventada no
  pueda meter un acervo entero en una evaluación sobre un campo que no
  tiene). `type` cuenta siempre. El resumen también devuelve ahora la
  puntuación desglosada en confianza, relleno y penalización — descubrir
  que un campo vacío respondía por la mayor parte de los puntos que faltaban había
  exigido consultar la base de datos a mano.
- **El planificador de VRAM empeoraba las cosas cuando el modelo no
  cabía.** Medido en la misma máquina: con menos VRAM libre de la que el
  modelo necesitaba, pedía menos de la mitad de las capas, y Ollama
  terminaba colocando en la tarjeta menos del modelo que su propio
  reparto — la estimación sustituía el reparto del planificador
  por uno peor y ralentizaba la ejecución. El coste por capa aquí es el
  tamaño del archivo dividido entre el número de capas, una cifra
  aproximada, mientras que Ollama conoce el tamaño real de cada tensor. La
  regla ahora es asimétrica: el plan solo pasa por encima del `-1` cuando
  puede afirmar con certeza que cabe *todo*, y un reparto se deja al
  planificador. Aparte de eso, la VRAM que ya ocupa el modelo que se está
  dimensionando ahora cuenta como disponible para él — sin eso, cada
  ejecución presupuestaba a partir de un número que excluía justamente el
  modelo que estaba cargando, pedía menos capas, y se empujaba fuera de la
  GPU cada vez.

### Añadido

- Una advertencia cuando el modelo elegido no cabe en la tarjeta en
  absoluto — el caso en que ningún ajuste ayuda y la respuesta es un
  modelo más pequeño. Encontrado en la máquina que motivó este trabajo: una
  RX 5700 XT de 8 GB ejecutando un modelo de 9,1 GB con el 17% de él en la
  GPU.


- **"Abrir proyecto existente"** — no había forma de reabrir un proyecto
  cuya carpeta no listara el catálogo de esta máquina, que es todo caso
  que el catálogo compartido no cubre: una reinstalación, un formateo, una
  cuenta distinta, una carpeta que se movió, una carpeta recibida de otra
  persona. La carpeta de salida ya *es* el proyecto — su `project.db`
  guarda la configuración, todo archivo explorado, toda página y toda
  pieza clasificada — así que la pantalla nueva lee esa carpeta (con la
  base de datos abierta en `mode=ro`, para que inspeccionar una carpeta
  nunca pueda ser lo que cree algo dentro de ella), muestra lo que
  encontró, y la adopta sin cambios.

- **`uninstall.ps1`** — el sistema no tenía desinstalador alguno.
  Pregunta por cada elemento por separado y traza una distinción todo el
  tiempo: lo que esta instalación *posee* (el entorno virtual, los accesos
  directos, las DLL de sensor, el Ghostscript descomprimido, los ajustes
  locales, las entradas de `PATH` y las variables de entorno que añadió) se
  elimina cuando se pide; lo que meramente *instaló* (Tesseract,
  Ghostscript, Ollama, Python, el almacén de modelos descargados) es un
  programa compartido del que otro software puede depender, y se ofrece de
  uno en uno, diciéndolo con claridad. `-RemoveAll`, `-KeepDependencies` y
  `-WhatIfOnly` cubren los casos no interactivos. Nunca borra la carpeta de
  salida de un proyecto bajo ninguna opción — las lista, con tamaños, y
  deja la decisión al usuario. `install.ps1` crea un acceso directo en el
  escritorio para él.
- Una sección "Catálogo compartido" en la pantalla de Proyectos, con el
  selector de carpetas nativo, para apuntar la lista de proyectos a una
  carpeta de Drive.
- Un evento de registro que informa cómo se está usando la GPU en una
  ejecución de clasificación (`N de M capas en la GPU, X MB de VRAM libre
  medidos`) — el número detrás del medidor de VRAM, que Ollama no informa
  y la pantalla no podía explicar.
- 49 pruebas que cubren los ocho elementos, la ruta de reapertura y el
  lanzador (`tests/test_phase16.py`), incluyendo una regresión para un
  defecto hallado al validar este trabajo contra un Ollama real: un modelo
  multimodal publica `gemma4.audio.block_count = 12` junto a
  `gemma4.block_count = 42`, y el de audio viene primero — emparejar solo
  por sufijo leía el número de capas de la torre de audio y dejaba toda
  cifra por capa equivocada en más del triple.

## [No publicado] — Fase 15: Instalador Consciente del Hardware y Elevación Opcional

Objetivo de esta fase: hacer que el instalador analice la máquina e
instale lo que esa máquina realmente necesita, y darle al sensor de CPU
una forma de ejecutarse con el privilegio que requiere — sin exigirlo.

La fase empezó con el mantenedor limpiando la máquina (Python 3.12, el
entorno virtual, Tesseract, Ghostscript, Ollama, la variable de entorno de
la GPU y el acceso directo del escritorio) para que el instalador pudiera
probarse desde cero por primera vez. Esa prueba encontró más de lo que
debía.

### Añadido

- El instalador descarga las siete bibliotecas de sensor
  (`LibreHardwareMonitorLib` 0.9.6, `HidSharp` 2.6.4 y cinco shims de la
  BCL de .NET) de nuget.org a `%LOCALAPPDATA%\GClaudeIndexer\lib`, con
  versiones fijadas y **SHA-256 verificado antes de instalar**. Nada las
  había instalado nunca: se colocaban a mano, así que quien clonara el
  repositorio no obtenía lecturas de temperatura, potencia ni reloj, ni
  forma de obtenerlas.
- **El instalador instala Python 3.12 él mismo**, y continúa en la misma
  ejecución. Venía detectando el intérprete ausente e imprimiendo un
  comando `winget` para que el usuario lo ejecutara a mano — lo cual no es
  instalar. Ahora intenta winget en ámbito de *usuario* (sin
  administrador, y el PATH de la máquina se deja en paz para que un
  `python` existente siga ganando), luego el instalador fijado de
  python.org con su SHA-256 comprobado, luego una instalación elevada para
  todos los usuarios, y solo entonces recurre a la orientación impresa.
  Ver el intérprete recién instalado en el mismo proceso requirió trabajo
  propio: el `PATH` y el registro del lanzador `py` se leen cuando arranca
  un proceso, así que el instalador recarga el PATH desde el registro, lee
  el `Software\Python\PythonCore\3.12\InstallPath` de la PEP 514 y
  comprueba las carpetas de instalación conocidas — ejecutando cada
  candidato y preguntándole su propia versión, en lugar de fiarse de una
  clave o del nombre de una carpeta. Esta máquina tenía una clave de
  registro obsoleta apuntando a una carpeta `Python312` sin `python.exe`,
  que habría respondido "encontrado" para un intérprete que no existe.
- Datos de idioma de OCR en portugués. El proyecto tiene
  `ocr_language="por"` por defecto, pero el paquete de Tesseract solo trae
  `eng` y `osd` — `ocrmypdf` fallaba con "does not have language data for:
  por". El instalador ahora instala el idioma configurado (commit fijado,
  hash verificado) en el propio `tessdata` de Tesseract. `-OcrLanguage`
  acepta otros.
- Ghostscript, que nada había estado instalando en absoluto: el paquete de
  winget (`ArtifexSoftware.GhostScript`) **ya no existe**. La versión está
  fijada y el SHA-512 se contrasta con el archivo `SHA512SUMS` que Artifex
  publica con la versión. Cómo se pone en su sitio cambió más adelante en
  esta misma fase — véase "Ghostscript se descomprime, no se instala"
  abajo.
- Una comprobación de GPU posterior a la instalación: el instalador carga
  un modelo e informa lo que dice `ollama ps`. Cuando la GPU no se está
  usando, imprime orientaciones para tarjetas AMD más antiguas — solo
  enlaces, nunca una descarga automática de terceros.
- Elevación opcional para el sensor de CPU: un segundo acceso directo,
  `GClaude Indexer (sensor de CPU)`, que pasa `--cpu-sensor` a los
  lanzadores existentes. Solo `gclaude_indexer.sensor_service` se ejecuta
  elevado; el servidor no. El instalador ofrece ese acceso directo
  preguntando, declarando tanto lo que se gana (temperatura y potencia de
  la CPU) como lo que cuesta (un aviso de UAC en cada arranque).
  `-AutoInstall` por sí solo no lo crea.

### Eliminado

- `gclaude_indexer/installer.py` y las diez pruebas que lo cubrían. Era una
  segunda implementación de la instalación de dependencias, en Python,
  alcanzada solo desde `launcher.py` — así que el mismo trabajo existía
  dos veces, y la copia que nadie miraba era la que todavía ejecutaba el
  instalador de Ghostscript con `/S` y una espera de 900 segundos.
  `install.ps1` es ahora el camino único: `Indexer.bat` ya lo ejecuta
  cuando falta el entorno. `launcher.py` perdió
  `_garantir_dependencias_externas()` con él, y `log.installer.*` (27
  claves en los tres idiomas) se fue con el código que las usaba.

  Contrapartida aceptada: la aplicación ya no reinstala en silencio una
  dependencia que desaparezca tras la instalación. La pantalla Acerca de
  sigue informando de su ausencia, y volver a ejecutar el instalador lo
  arregla.

### Cambiado

- **Ghostscript se descomprime, no se instala.** Ahora aterriza en
  `%LOCALAPPDATA%\GClaudeIndexer\gs` — junto al entorno virtual y el
  catálogo — y su carpeta `bin` se añade al PATH del *usuario*. El
  instalador del proveedor no podía ejecutarse desatendido: está
  manifestado como `requireAdministrator` (así que todo destino,
  `%LOCALAPPDATA%` incluido, levanta un aviso de UAC), `/S` ya no silencia
  esta compilación, y lo que deja en pantalla es una página de "Finalizar"
  esperando un clic. Descomprimirlo, en cambio, no requiere administrador,
  ni ventana, ni clic: medido en 2,1 s para 649 archivos, con `gswin64c
  --version` respondiendo 0,2 s después, frente a ~93 s más un aviso más
  un clic. El extractor es el propio MSI de 7-Zip, descomprimido con
  `msiexec /a` (una instalación administrativa, que no instala nada) y
  fijado y comprobado por SHA-256 como toda descarga de aquí. Ejecutar el
  instalador del proveedor sobrevive como alternativa, y ahí la espera es
  a que el binario responda `--version` — no a un proceso que nunca
  termina — tras lo cual la ventana que queda se cierra matándolo.
  Acotado por un tiempo límite que degrada con una advertencia.
- El análisis de hardware ahora recorre todos los adaptadores de pantalla
  en lugar del primero, e informa de lo que hizo para NVIDIA e Intel en
  lugar de inventarse un ajuste: ninguna de las dos necesita uno más allá
  de lo que Ollama ya hace.
- El instalador ya no escribe `HSA_OVERRIDE_GFX_VERSION`, y la elimina si
  está presente. Medido en una RX 5700 XT con Ollama 0.33.2: el modelo se
  ejecuta al **100% de GPU, 66,9 tokens/s, por el backend Vulkan**, sin
  que ROCm se intente nunca. El reemplazo no oficial de la biblioteca ROCm
  que circula para esa tarjeta se dirige a un Ollama más antiguo que solo
  tenía CUDA y ROCm; aplicarlo ahora sobrescribiría archivos de Ollama con
  binarios de terceros para sustituir una ruta que ya funciona.

### Corregido

- `$ErrorActionPreference = "Stop"` convertía el stderr de cualquier
  comando nativo en un error terminante. Esto rompía el instalador en dos
  puntos: la comprobación de la versión de Python moría antes de imprimir
  la orientación escrita exactamente para ese caso, y `ollama list` —
  ejecutado segundos después de instalar Ollama, mientras su servicio
  todavía arrancaba — mataba el script tras instalarlo todo y antes del
  análisis de hardware, las bibliotecas de sensor y el acceso directo.
  **Una instalación desde cero no podía terminar.** Ambos arreglados
  mediante `Invoke-NativeCommand`.
- `installer.py` pasaba opciones de Inno Setup (`/VERYSILENT /NORESTART
  /SUPPRESSMSGBOXES`) al instalador NSIS de Ghostscript, que ignora lo que
  no reconoce y habría abierto una ventana esperando a un humano en medio
  de una instalación desatendida. Cambiado a `/S` — que luego se midió y
  tampoco silencia esta compilación, así que `install.ps1` dejó de
  ejecutar aquel instalador por completo (véase "Ghostscript se
  descomprime, no se instala"). `installer.py` todavía lleva el enfoque
  antiguo; está listado en "Limitaciones conocidas" abajo.
- `Install-IfMissing` devolvía la salida de winget junto a su booleano,
  así que `$GhostscriptOk` era siempre verdadero y sus advertencias nunca
  aparecían.
- Toda advertencia de "el instalador devolvió el código N" en
  `install.ps1` era código muerto: `Start-Process -PassThru` devuelve un
  objeto `Process` cuyo `ExitCode` se queda en `$null` para siempre a
  menos que se mantenga abierto su identificador. Leer el `.Handle` una
  vez, justo después de lanzar, hace legible el código de salida — medido
  antes y después.
- El instalador escribía `__pycache__` en la carpeta del proyecto, que la
  sincroniza Google Drive, contra la regla de la propia especificación.
  Arreglado con `-B`; el `conftest.py` raíz resultó no cubrir ni su propia
  compilación, así que `PYTHONDONTWRITEBYTECODE` ahora se define en CI y
  `-B` queda documentado en las guías de contribución.
- La pantalla Acerca de habría ofrecido restaurar justamente la variable
  de entorno que el instalador acababa de eliminar.

### Limitaciones conocidas

- **El rechazo del UAC nunca se ha ejercitado.** La elevación está
  probada, rechazarla no, y tampoco el caso de cuenta estándar en el que
  Windows pide credenciales. (La nota anterior aquí decía que esta máquina
  tiene `ConsentPromptBehaviorAdmin = 0` y nunca muestra un diálogo;
  medido de nuevo en la Tarea 5, es **5** — la máquina sí pregunta.)
- No verificados en la práctica: GPU NVIDIA e Intel, tarjetas AMD distintas
  de RDNA1, máquinas sin GPU, fallo de red durante las descargas, y
  Ghostscript vía winget (el paquete ha desaparecido).
- La alternativa de Ghostscript — el instalador del proveedor, ejecutado
  elevado — se probó contra un sustituto que se comporta como él (escribe
  el árbol, luego se cuelga), no contra el instalador en sí: ejercitarlo de
  verdad requiere que alguien apruebe un aviso de UAC en el teclado.
- `expected_sha256` para las descargas de Tesseract y Ollama sigue sin
  fijar en `install.ps1` — no se escribió ningún hash que no se hubiera
  medido antes.

## [Fase 14] - 2026-08-30 — Internacionalización y Preparación para Código Abierto

Objetivo de esta fase (del plan): traducir todo el proyecto al inglés —
identificadores, docstrings, esquema de base de datos, claves de
traducción y pruebas —, quitar restos de desarrollo, y preparar el
repositorio para su publicación abierta bajo la GPL-3.0 y para un
instalador distribuible de Windows.

### Añadido

- `LICENSE` con el texto íntegro y literal de la GNU General Public
  License v3.0.
- Cabecera de licencia GPL al principio de cada módulo de
  `gclaude_indexer/`.
- `CONTRIBUTING.md`, con traducciones al portugués de Brasil y al español
  bajo `docs/`, y este `CHANGELOG.md` — solo en inglés, versión única,
  siguiendo la convención de Keep a Changelog.
- `README.md` reescrito como la puerta de entrada del repositorio en
  inglés (con `docs/README.pt-BR.md` y `docs/README.es.md`), sustituyendo
  el `README.md` solo en portugués con el que empezó esta fase —
  corregido contra el código actual allí donde se había desviado (véase
  "Corregido" abajo).
- `docs/SPECIFICATION.md`, la referencia técnica traducida al inglés desde
  el antiguo `ESPECIFICACAO.md` y corregida contra el código actual
  (mantenida como documento único, solo en inglés — es una referencia
  interna, no orientada al usuario).
- `.gitignore` (el proyecto no había usado control de versiones hasta esta
  fase).

### Eliminado

- Restos de desarrollo: un archivo `INSERT_PATH` vacío creado por
  accidente, la carpeta vacía `_tmp_task7_check/`, y todos los directorios
  `__pycache__/`.

### Cambiado

- Toda la base de código de `gclaude_indexer/` — identificadores,
  comentarios, docstrings — y el esquema de SQLite (`project`, `file`,
  `page`, `window`, `item`, `event`, `run`) traducidos al inglés,
  incluyendo cada ruta HTTP, variable de contexto de plantilla, clase y
  variable CSS, y el formato de transmisión JSON de los motores de
  clasificación (`raw_items.jsonl`). La interfaz en tres idiomas
  (`pt`/`en`/`es`) mediante `i18n.py` no se ve afectada — solo las
  *claves* pasaron al inglés; el texto de cada idioma no cambia.
- El idioma predeterminado de la interfaz ahora se detecta del idioma de
  visualización de Windows, y puede sobrescribirse con la variable de
  entorno `GCLAUDE_INDEXER_LANGUAGE`.
- Los cuatro artefactos de salida (`index.md`, `timeline.md`, `review.md`,
  `project_instructions.md`) y los mensajes del propio registro de
  ejecución ahora se generan en el idioma actual de la interfaz,
  retraducibles tanto al leer como al escribir.
- La suite de pruebas renombró `test_fase1.py`…`test_fase13.py` a
  `test_phase1.py`…`test_phase13.py`, más un `test_phase14.py` nuevo para
  la cobertura de esta fase.
- El instalador, traducido y renombrado de `instalar.ps1` a `install.ps1`
  (mensajes, comentarios y nombres de función y variable incluidos; el
  parámetro `-AutoInstalar` ahora es `-AutoInstall`), junto con
  `Indexador.bat`/`Indexador.vbs` renombrados a `Indexer.bat`/`Indexer.vbs`
  y `iniciador.py`/`executar_servidor.py` renombrados a
  `launcher.py`/`run_server.py`. La lógica del instalador (detección de
  Python/venv, la comprobación de hash de `requirements.txt`, las llamadas
  a winget, la detección de GPU, la idempotencia) no cambia — solo los
  nombres y el texto orientado al usuario pasaron al inglés.

### Corregido (documentación)

- `README.md` y `ESPECIFICACAO.md` se habían desviado del código antes
  incluso de que esta fase renombrara nada: todavía nombraban
  `pecas_brutas.jsonl` (ahora `raw_items.jsonl`), `indice.md` (ahora
  `index.md`), `janelas/` (ahora `windows/`), `estilo.css` (ahora
  `style.css`), `projetos.json` (ahora `projects.json`), y varios nombres
  de módulo y ruta anteriores al trabajo de traducción de esta fase.
  Corregidos por completo, junto con el requisito de versión de Python
  (`3.11+` estaba documentado; las dependencias fijadas requieren en
  realidad el **3.12** específicamente — los intérpretes más nuevos las
  rompen).

### Seguridad

- Lista de columnas SQL permitidas (`_NULLABLE_COLUMNS`) en los dos
  auxiliares `_count_nulls` de `quality.py`. No había inyección — los
  argumentos son literales de código — pero un nombre de columna no puede
  ser un parámetro de SQL, así que la interpolación es inevitable y la
  validación es lo que impide que la entrada del usuario llegue jamás a
  ella.
- Revisión de `requirements.txt` con `pip-audit`: **46 vulnerabilidades
  conocidas en 6 paquetes**, informadas sin cambiar ninguna fijación.
  Cuatro son actualizaciones directas (jinja2 3.1.4 a 3.1.6,
  python-multipart 0.0.12 a 0.0.31, pillow 10.4.0 a 12.3.0, pytest 8.3.3 a
  9.0.3); starlette 0.38.6 no tiene corrección compatible con
  `fastapi==0.115.0`, así que necesita una actualización de FastAPI y no
  un cambio de fijación. Dejado como decisión del mantenedor, ya que
  actualizar sin probar es como se rompe un sistema que funciona.
- `SECURITY.md` y `CODE_OF_CONDUCT.md`, más las plantillas de issue y pull
  request de GitHub.

### Integración continua

- `.github/workflows/tests.yml`: la suite en `windows-latest` con Python
  3.12, con un comentario que explica por qué no hay trabajo de Linux (el
  proyecto usa PowerShell, WMI y el registro). Instala Tesseract y
  Ghostscript vía Chocolatey y descarga `por.traineddata` aparte —
  ninguno de los dos paquetes lo trae, y las tres pruebas de OCR real lo
  necesitan. **Nada de la suite queda excluido del CI.** El propio
  workflow no se ha ejecutado en un runner real: el proyecto no tenía
  repositorio git cuando se escribió.

### Corregido (verificación final)

La verificación de extremo a extremo ejecutó el sistema entero en lugar de
la suite, y encontró cinco defectos que 319 pruebas en verde no
encontraron:

- `projeto.lock` persistía claves JSON en portugués (`maquina`, `usuario`,
  `criado_em`, `atualizado_em`) en la carpeta de salida de cada proyecto —
  el único fragmento de estado persistido que el mandato de traducción
  había pasado por alto. Ahora es `project.lock`, con claves en inglés.
- La etiqueta de paso `importacao` nunca se añadió a `STEPS` ni a la tabla
  de traducción, así que se filtraba en crudo al registro en vivo en cada
  ejecución real, en los tres idiomas. Lo mismo ocurría con `diagnostico`,
  encontrada mientras se buscaban hermanas. Ambas se renderizan ahora
  traducidas, mediante una lista de visualización `LOG_KNOWN_STEPS`
  mantenida aparte de `STEPS`.
- Los errores de validación de configuración se construían como cadenas
  fijas en portugués y se mostraban independientemente del idioma de la
  interfaz. `ConfigError` ahora lleva `ConfigErrorMessage(key, params)`,
  renderizado por la capa de visualización.
- Los diagnósticos de GPU y sensores de la pantalla Acerca de eran frases
  en portugués incrustadas en el código, y el código crudo de
  `sensors.unavailable_reason()` se filtraba sin traducir a la página.
- Las pantallas de bloqueo y sincronización mostraban mensajes construidos
  en portugués en `lock.py` y `sync.py`. Ambos resultados llevan ahora
  `message_key` y `message_params`.
- 45 de 64 atributos `id=` de las plantillas, la mayoría de los
  identificadores de JavaScript en línea, y los nombres de bloque y macro
  de Jinja seguían en portugués — invisibles porque el texto visible ya
  estaba correctamente traducido.

### Verificado

- Tubería completa sobre un acervo de 6 PDF (uno solo de imagen, que
  requería OCR): 7 etapas, 7 piezas clasificadas con confianza alta, 4
  artefactos generados con contenido real.
- Las 16 combinaciones de tema x disposición más los tres idiomas, sin
  claves de traducción en crudo, títulos vacíos, tablas desbordadas ni
  errores de consola.
- La suite se ejecutó dos veces sin inestabilidad.

### Limitaciones conocidas

- Los proyectos creados antes de esta fase no abren: su `processing_mode` y
  `group_mode` guardados tienen valores en portugués, y la validación
  rechaza valores desconocidos en lugar de recurrir al predeterminado, así
  que la pantalla devuelve HTTP 500. No se escribió ninguna capa de
  compatibilidad — el mantenedor había confirmado que los acervos
  existentes eran datos de prueba desechables.
- El `_PROMPT` enviado al modelo local y el `CLAUDE.md` generado siguen en
  portugués a propósito. Las claves JSON que piden se fijaron al inglés y
  se validaron contra un modelo real, así que el formato de transmisión ya
  no varía con el idioma de la interfaz; la prosa no se ha traducido, lo
  que todavía ata la calidad del motor `local` a acervos en lengua
  portuguesa.

## [Fase 13] - 2026-08-29 — GPU, Calidad y Disposiciones

Objetivo (del plan): hacer que el sistema se instale en cualquier máquina
usando el hardware que encuentre; monitorizar la máquina entera con
independencia del fabricante de la GPU; y permitir comparar motores y
modelos por tiempo y calidad, con cuatro disposiciones de interfaz
genuinamente distintas.

### Añadido

- Detección de uso de GPU y VRAM para cualquier fabricante (no solo
  NVIDIA).
- Monitorización de reloj de CPU, memoria y GPU.
- Sensores de temperatura y potencia vía LibreHardwareMonitor.
- Un informe de calidad generado al final de una ejecución.
- Cuatro disposiciones visuales seleccionables y genuinamente distintas,
  con la infraestructura para sostenerlas.
- Un instalador que prepara una máquina nueva de forma desatendida,
  adaptándose al hardware que detecta.
- Paralelismo en la conversión/OCR y la extracción — la mayor mejora
  aislada de rendimiento de esta fase.
- Un benchmark que compara motores y modelos lado a lado por tiempo y
  calidad.

### Cambiado

- El panel de recursos ahora expone todas las métricas recogidas de la
  máquina (CPU, RAM, GPU, temperatura, potencia, relojes) en un solo
  lugar.
- La vista del registro en vivo ya no se desplaza sola mientras el usuario
  haya subido para leer entradas anteriores.
- El selector de modelos (para el motor `local`) ahora surte efecto de
  verdad.
- La barra de progreso de la exploración llega al 100% correctamente
  incluso habiendo archivos duplicados.

### Corregido

- La opción "Todas" de extensiones de archivo ahora es mutuamente
  excluyente con las categorías específicas de extensión en el formulario
  de nuevo proyecto (antes ambas podían seleccionarse a la vez, con
  "Todas" imponiéndose en silencio).

### Eliminado

- El motor de clasificación `openrouter`, eliminado por completo.

## [Fase 12] - 2026-08-28 — Correcciones de Interfaz

Objetivo (del plan): corregir los 12 defectos de interfaz encontrados
durante el primer uso real de GClaude Indexer v1.0 — internacionalización
del estado, comportamiento de la barra de progreso, legibilidad de
formularios y temas, y limpieza de archivos intermedios.

### Añadido

- Un paso de descubrimiento de modelos de Ollama instalados, que alimenta
  el selector de modelos.
- Cuatro temas visuales seleccionables.
- Limpieza de los archivos intermedios que quedan en la carpeta de salida.

### Cambiado

- El estado de paso/ejecución ahora se representa mediante claves
  estables, en ASCII y neutras respecto al idioma (`estado_etapas.py`), en
  lugar de texto en portugués acentuado usado simultáneamente como texto
  de visualización, clase CSS y valor de comparación — la causa raíz de
  varios de los 12 defectos, incluido uno en el que traducir el texto de
  estado rompía el botón de "ejecutar el siguiente paso".
- La barra de progreso mantiene el último estado conocido ("hecho",
  "pausado", "error") en lugar de desaparecer en el instante en que
  termina un paso.
- El total de progreso del paso de exploración ahora respeta las
  extensiones de archivo seleccionadas para el proyecto, en lugar de
  contar todos los archivos de la carpeta de origen.
- La barra de progreso muestra el título traducido del paso en lugar de la
  clave interna en crudo.
- La vista del registro en vivo muestra hasta 200 líneas (frente a 50),
  añade un filtro por nivel (info/advertencia/error), y mantiene la vista
  fijada a la última línea mientras "seguir el final" esté marcado.
- Las extensiones de archivo en el formulario de nuevo proyecto se agrupan
  por familia (documentos, imágenes, texto/datos, mensajes), mostrando qué
  extensiones cubre cada categoría, en lugar de una única fila ordenada
  alfabéticamente.
- Las descripciones de los motores de clasificación en el formulario de
  nuevo proyecto se hicieron legibles.

### Eliminado

- El prescindible banner de "cambio de máquina".

### Corregido

- Fugas de idioma restantes en la interfaz (cadenas sin traducir que
  todavía llegaban a la pantalla en idiomas distintos del portugués).
