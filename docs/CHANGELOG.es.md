# Registro de cambios

Todos los cambios relevantes de este proyecto están documentados en este
archivo. El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).

> **Traducción.** El documento canónico es el
> [`CHANGELOG.md`](../CHANGELOG.md) en inglés. Si ambos divergen, vale el
> inglés. Los nombres de archivo, identificadores de código, claves de
> configuración y mensajes que el programa emite en inglés se han
> mantenido tal cual.

Las entradas están agrupadas por fase de desarrollo, siguiendo los
documentos de planificación del propio proyecto en
`docs/superpowers/plans/`, y no por versión semántica — la versión que
informa la aplicación (`SYSTEM_VERSION`, en `web/app.py`) se mantuvo en
`1.0.0` desde la fase 1 hasta la fase 16. La `1.0.1` es el primer
incremento, y publica todo lo que el bloque de la fase 16, más abajo,
venía arrastrando como no publicado.

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
*posterior*: en un acervo real de 2904 páginas cuya carpeta de salida está
en Google Drive, la clasificación tardó 5h18 y entonces **"Importar y
generar informes" tardó 38 minutos más por su cuenta**, sin barra de
progreso y sin ninguna señal de que estuviera trabajando en vez de
colgada. El trabajo nunca estuvo en riesgo — las 5230 piezas eran todas
válidas — pero la pantalla no lo decía, así que se volvió a pulsar el
botón. Y otra vez.

#### Corregido

- **La comprobación de rango deja de releer las mismas páginas una vez por
  pieza.** `_validate_range_within_group` le pide a la base de datos todas
  las páginas del agrupador de la pieza, para comprobar que su rango
  existe. Lo pedía una vez por pieza: **5230 consultas donde bastaban 3**,
  porque el acervo tiene 3 agrupadores — y uno de ellos, con 2830 páginas,
  concentra 5093 de esas piezas. El rango solo depende del agrupador, así
  que ahora se lee una vez por agrupador y se guarda durante la corrida.
  Medido en ese acervo: **45,2s → 0,07s** en disco local, y **~41 min →
  0,59s** con la base en la unidad de Drive, donde cada una de esas
  consultas costaba 488 ms en lugar de 9,3 ms. La importación más todos
  los informes ahora tarda 0,21s donde tardaba casi una hora.

- **Un segundo clic ya no inicia una segunda importación.** A diferencia
  de las etapas del pipeline, esta ruta hace su trabajo dentro de la
  petición HTTP, por lo que no tiene entrada en `task_manager` y nada
  comprobaba si ya estaba en marcha. Un volcado de pila del servidor en
  uso mostró **4 hilos `import_and_generate` simultáneos**, cada uno
  tomando el GIL por turnos y cada uno a punto de ejecutar
  `DELETE FROM item` seguido de 4210 inserciones sobre el mismo archivo
  SQLite. Todos terminaron, y todos escribieron el mismo resultado — pero
  tardaron entre 36 y 54 minutos cada uno. Un clic que cae sobre una
  corrida ya en marcha ahora va directo a la pantalla de Resultado.

640 pruebas pasando, frente a 638.


## [1.3.2] — 2026-09-16

### Fase 21 — contexto calibrado y nota honesta

La fase 20 corrigió el mecanismo y mantuvo el número equivocado que lo
alimenta. En una indexación real de 2904 páginas en la 1.3.1, **153 de
1449 ventanas entraron en el índice sin clasificación alguna** — 612
piezas, el 11% del índice, con tipo, fecha y autor vacíos y el OCR en
bruto en lugar del resumen. El registro cerró en `baixa=0` y la nota dio
89/100.

#### Corregido

- **La razón caracteres/token deja de ser una conjetura.**
  `_CHARS_PER_TOKEN` valía 3,0, medida en prosa portuguesa. El acervo es
  un expediente con volúmenes de rendición de cuentas, y una tabla
  contable tokeniza a **1,45** — el recálculo por ventana de la fase 20 se
  ejecutaba y se quedaba corto siempre. La razón pasa a aprenderse durante
  la corrida con el `prompt_eval_count` que Ollama ya devuelve y el código
  descartaba, guardando el mínimo observado, con un suelo de 1,2. Medido
  en el acervo real: la razón converge a 1,45 y las ventanas que daban 0
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
  del grupo, sin join por grupo. Prueba directa: quitando 967 piezas del
  índice — un hueco de 500 folios — siguió marcando 100,0% donde el valor
  real era 82,7%.

- **La nota deja de pagarse sola.** Los 40 puntos de cobertura eran
  tautológicos: la agrupación emite una pieza por página de la ventana, así
  que la página siempre está dentro de alguna pieza. Pasan a medir
  cobertura *clasificada* — páginas que el modelo describió. La misma
  corrida que valía 89 vale **83**, y es sobre 83 que la corrección muestra
  su ganancia.

- **La pieza ciega deja de pasar por mediana.** La página sobre la que el
  modelo no dijo nada sigue entrando en el índice por la agrupación — esa
  garantía es lo que impide la pérdida — pero ahora con confianza `baixa`.
  Es lo que le devuelve sentido al `baixa=` del resumen de la etapa 6.

### Añadido

- **La fila del índice lleva a la página física del PDF.** `f. 417` es la
  página 145 de `Vol 2.pdf`, y el grupo tiene 21 volúmenes; el índice
  nombraba el archivo y se detenía ahí.

- **Índice por grupo, con sumario.** El `index.md` salía con 5443 filas y
  1,58 MB en un solo archivo, demasiado para que un Proyecto de Claude lo
  consulte de forma fiable. Pasa a ser un sumario de pocos KB que apunta al
  grupo y al archivo; la tabla de cada grupo va a `index-<grupo>.md`, y el
  paquete del Proyecto los lleva todos.

638 pruebas pasando, frente a 618.


## [1.3.1] — 2026-09-15

Fase 20. Tres cosas que una ejecución real perdía en silencio.

Encontradas leyendo el registro de una indexación de 2904 páginas (44
archivos, 484 ventanas, `qwen3.5:4b` en una RTX 3060 Laptop). Nada se
había roto — la ejecución informó `0 falhou(aram)` en todos los pasos — y
ese era el problema: los tres defectos se informaban como advertencia, o
como nada.

### Corregido

- **Una pieza ya no se descarta por la precisión de su fecha.** Los
  documentos contables y administrativos se fechan por período —
  "competência 01/2020", "exercício 2019" — y el modelo devuelve
  `2020-01` porque es lo que dice la página. La validación exigía
  `AAAA-MM-DD` estricto y descartaba la pieza *entera* — tipo, autor,
  resumen y todo — por un campo opcional. Eran las 20 de 20 piezas
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
  fueron 20 tramos de páginas ausentes de un índice cuyo propósito entero
  es decir en qué página está cada cosa. La cobertura ahora se calcula a
  partir de las piezas que realmente sobrevivieron a la validación.

- **El contexto de Ollama se mide por ventana, no una vez por ejecución.**
  Se dimensionaba con el prompt de la primera ventana y quedaba congelado
  ahí. Una ventana más densa más adelante lo desbordaba, la respuesta
  volvía truncada, el JSON nunca cerraba y el analizador recibía cero
  filas — la ventana llegaba al índice sin clasificación alguna, solo con
  una advertencia diciendo que el modelo no había respondido sobre
  ninguna de sus páginas. Fueron 72 de las 484 ventanas de la ejecución
  (~15%), que es la mayor parte de lo que informó como confianza media. El
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
  proyecto.** Esto salió de un acervo real: se añadieron tres documentos,
  la tubería exploró, convirtió, extrajo 426 páginas, construyó 71
  ventanas y clasificó todas ellas — y `index.md`, `timeline.md`,
  `review.md` y `project_instructions.md` siguieron informando los 13
  archivos y 307 ventanas anteriores, porque generarlos es un paso
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
  marcha. Observado aquí de la peor manera: un servidor arrancado a las
  02:09 seguía en marcha a las 08:03 con código corregido a las 05:40,
  pasando esas horas produciendo un índice con un defecto que ya se había
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
  informe de laboratorio de 31 páginas, cinco modelos de tres familias —
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
  * El modelo marcó `continues: true` en ocho pruebas de laboratorio
    consecutivas que él mismo había nombrado correctamente (Hemograma,
    Ferritina, Metabolismo do Ferro, Vitamina B-12, Protrombina, Ureia,
    Creatinina) — leyó "continúa el mismo *informe*" donde el prompt
    quería decir "el mismo *tema*". La agrupación ahora se decide en
    código, comparando temas; `continues` solo desempata cuando la
    redacción de un tema cambia sin que cambie el documento ("Hemograma —
    série vermelha" / "— série branca").

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
  coste se midió en un acervo real: material de curso de posgrado
  clasificado por un prompt cuyos únicos ejemplos trabajados eran "OFÍCIO,
  MEMORANDO, PARECER" volvió con 1432 de 1445 piezas sin tipo alguno. El
  modelo no estaba fallando; estaba respondiendo la pregunta que se le
  había hecho. El motor `local` ahora construye un bloque de contexto a
  partir de esos campos, enmarcado como *qué es este acervo* y no como la
  tarea — el `extra_rules` de aquel acervo decía "debe observarse toda la
  legislación vigente", una instrucción para el uso posterior del índice
  en investigación, y no algo que un clasificador deba intentar ejecutar.
- **El prompt pedía documentos y aceptaba páginas.** La misma ejecución
  produjo 1445 piezas para 1844 páginas — 1,28 páginas por pieza, cortando
  de dos en dos páginas a través de documentos que corrían por decenas. El
  prompt ahora declara la regla explícitamente, junto con el fallo que
  pretende evitar.
- **`ÍNDICE` e `Índice` eran dos tipos de documento distintos.** Los tipos
  se normalizan (mayúsculas, espacios colapsados) a la entrada, y las
  palabras que un modelo devuelve en lugar de dejar el campo vacío
  (`null`, `N/A`, `desconhecido`) se tratan como vacío, en lugar de
  guardarse como tipos propios.
- **Un `desktop.ini` era la pieza número uno de un índice de material de
  curso**, resumido como "archivo de configuración del sistema
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
  que un campo vacío respondía por 30 de los 40 puntos que faltaban había
  exigido consultar la base de datos a mano.
- **El planificador de VRAM empeoraba las cosas cuando el modelo no
  cabía.** Medido en la misma máquina: con 4712 MB disponibles pedía 18 de
  43 capas, y Ollama pasaba de colocar 3108 MB del modelo en la tarjeta a
  colocar 1849 MB — la estimación sustituía el reparto del planificador
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
  modelo más pequeño. Encontrado en el acervo que motivó este trabajo: una
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
