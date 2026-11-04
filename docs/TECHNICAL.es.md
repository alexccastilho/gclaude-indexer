**Léalo en su idioma:** Español, usted está aquí · **[Português (Brasil)](TECHNICAL.pt-BR.md)** · **[English](TECHNICAL.md)**

# GClaude Indexer: detalles técnicos

Este documento es para quien instala, mantiene o quiere entender el programa por dentro. El [README](README.es.md) explica para qué sirve; el manual dentro del programa (menú **Manual**) explica cada pantalla. Aquí están los requisitos, la instalación sin el instalador, lo que corre en cada etapa, lo que contiene cada archivo de salida y cómo resolver problemas. Todo lo que estaba en la sección "Detalles técnicos" del README anterior está aquí, revisado para la 1.8.0.

Índice:

- [Requisitos en detalle](#requisitos-en-detalle)
- [Instalación sin el instalador](#instalación-sin-el-instalador)
- [Uso diario](#uso-diario)
- [Los sensores de la CPU y los ventiladores](#los-sensores-de-la-cpu-y-los-ventiladores)
- [Desinstalación en detalle](#desinstalación-en-detalle)
- [Las pantallas del programa](#las-pantallas-del-programa)
- [Mantener un acervo actualizado](#mantener-un-acervo-actualizado)
- [Lograr una buena clasificación](#lograr-una-buena-clasificación)
- [Lo que garantiza el índice](#lo-que-garantiza-el-índice)
- [Ventanas, bloques y OCR](#ventanas-bloques-y-ocr)
- [Motores de clasificación](#motores-de-clasificación)
- [Archivos de salida](#archivos-de-salida)
- [Varios acervos en un Project: conjuntos](#varios-acervos-en-un-project-conjuntos)
- [Búsqueda por tema y LexML](#búsqueda-por-tema-y-lexml)
- [OCR e idioma de los documentos](#ocr-e-idioma-de-los-documentos)
- [Ejecutar la suite de pruebas](#ejecutar-la-suite-de-pruebas)
- [Solución de problemas](#solución-de-problemas)
- [Documentación](#documentación)

## Requisitos en detalle

- **Windows 10 u 11, obligatorio.** El programa habla directamente con interfaces de Windows: PowerShell, WMI (detección de hardware y recursos), el registro (datos de Tesseract e idioma de visualización) y Performance Counters (gráficos de CPU y GPU). No corre en Linux ni en macOS.
- **Python 3.12**, instalado por usted si falta. El proyecto fija versiones de dependencias que los Python más nuevos (3.13, 3.14) rompen. El instalador busca la 3.12 y, si la máquina no la tiene, descarga e instala la 3.12.10 oficial para el usuario actual: sin administrador, sin paso manual. Cualquier otro Python ya instalado queda donde está.
- **OCR** (documentos escaneados sin capa de texto) necesita Tesseract y Ghostscript. El instalador instala los dos cuando puede.
- **El motor `local`** necesita [Ollama](https://ollama.com), instalado por el instalador si usted acepta. El modelo predeterminado depende de la tarjeta de video: `qwen3.5:9b` (5,3 GB) en una tarjeta con 8 GB de VRAM o más, `qwen3.5:4b` (3,2 GB) en las menores. La tarjeta de video no es obligatoria: Ollama pone en la GPU lo que cabe y el resto va a la RAM, bastante más lento. Con poca memoria en los dos, el programa pasa solo al motor `rules` y dice el motivo en pantalla.
- **El motor `rules`** no necesita nada de eso: corre en cualquier Windows capaz de correr Python, sin GPU, sin descarga y sin software extra.
- Algunos gigabytes libres en disco para el entorno Python y, si lo usa, el modelo de Ollama. Los archivos intermedios (PDF con OCR y trozos de texto) quedan en la carpeta local de la máquina, en `%LOCALAPPDATA%\GClaudeIndexer\work\`, y no en la carpeta de salida: un acervo grande genera gigabytes allí.
- La interfaz está en portugués de Brasil, inglés y español, en un menú del encabezado. El valor predeterminado sigue el idioma de visualización de Windows.
- El instalador es una comodidad para la primera preparación. El programa no está compilado en un único `.exe`: sigue siendo script Python y PowerShell legible, y un acceso directo en el escritorio lo abre con doble clic.

## Instalación sin el instalador

Este camino funciona también en una máquina donde usted no puede instalar programas. En resumen: ejecute `Indexer.bat` y siga las instrucciones. Paso a paso:

**1. Ponga el código fuente en su máquina.** Si descargó el proyecto como `.zip`, haga clic con el botón derecho, elija "Extraer todo..." y elija una carpeta común (Documentos, o una carpeta de Google Drive montada con letra de unidad). Si lo clonó con Git, ya tiene una carpeta. Abajo se la llama "la carpeta del proyecto".

**2. Abra PowerShell en la carpeta del proyecto.** En el Explorador de archivos, abra la carpeta, mantenga **Shift**, haga clic con el botón derecho en un espacio vacío y elija "Abrir la ventana de PowerShell aquí" (o "Abrir en Terminal"). O haga clic en la barra de direcciones, escriba `powershell` y presione Enter.

**3. No necesita instalar Python.** El instalador del paso 4 necesita Python 3.12 y, si la máquina no lo tiene, descarga el 3.12 oficial de python.org (versión exacta, checksum verificado) dentro de su carpeta de usuario, sin pedir administrador. Queda al lado de cualquier otro Python: si hoy `python --version` muestra 3.13 o 3.14, lo sigue mostrando. Si prefiere instalarlo antes, es el mismo comando que usa el instalador:

```powershell
winget install --id Python.Python.3.12 -e --scope user --silent --accept-package-agreements --accept-source-agreements
```

**4. Ejecute el instalador una vez.** Instala Python 3.12 si falta, crea un entorno Python privado para este programa (fuera de la carpeta del proyecto, para sobrevivir a un cambio de carpeta o a una nueva sincronización del Drive), instala los paquetes, verifica Tesseract y Ghostscript (instalándolos si faltan y usted acepta) y ofrece un acceso directo en el escritorio.

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

Windows puede mostrar "Windows protegió su PC" la primera vez que usted ejecuta un script descargado de internet. La opción `-ExecutionPolicy Bypass` ejecuta solo este script, sin cambiar ninguna configuración permanente. El instalador muestra el progreso y pregunta antes de instalar cualquier cosa (Tesseract, Ghostscript y, opcionalmente, Ollama y el modelo, que es una descarga grande). Si un paso falla, muestra el comando manual. La primera ejecución lleva varios minutos, la mayor parte descargando paquetes.

**5. Acepte el acceso directo en el escritorio**, si quiere. Un segundo acceso directo, opcional, "GClaude Indexer (CPU sensor)", pide administrador cada vez que se abre, solo para el lector de sensores (vea la sección siguiente). Se puede cambiar de opinión después con `install.ps1 -CpuSensorShortcut`.

## Uso diario

Haga doble clic en el acceso directo del escritorio. Una ventana de consola aparece solo la primera vez, si el instalador todavía necesita correr; después el programa sube sin ventana visible y abre el navegador en:

```
http://127.0.0.1:8000
```

El servidor solo escucha en `127.0.0.1`, su propia máquina. Nunca queda accesible por la red ni desde otra computadora.

Sin el acceso directo, desde la carpeta del proyecto:

```powershell
python launcher.py
```

Eso verifica el entorno e instala lo que falte antes de subir el servidor, así que también funciona en una máquina donde usted todavía no ejecutó el instalador.

Para cerrar el programa, cierre la ventana de terminal que abrió (o, si corre oculto por el acceso directo, finalice `pythonw.exe` en el Administrador de tareas).

**Actualizar el programa.** Instale la versión nueva encima, sin desinstalar: el instalador cierra la versión anterior que esté corriendo y sus proyectos quedan donde están. Si un servidor de otra versión sigue en el aire cuando usted abre el programa, el nuevo lo reemplaza y avisa.

**Lo que el instalador graba para Ollama.** Para aprovechar la tarjeta de video por completo, el instalador graba variables de entorno del usuario que Ollama lee al subir. El programa pasa las mismas al servidor que él mismo levanta cuando no hay uno en el aire, y los dos tienen que coincidir:

| Variable | Valor | Por qué |
|---|---|---|
| `OLLAMA_MAX_LOADED_MODELS` | `1` | un modelo a la vez en la tarjeta |
| `OLLAMA_NUM_PARALLEL` | `1` | un pedido a la vez; el paralelismo no ayudó en las mediciones (02/11/2026) |
| `OLLAMA_FLASH_ATTENTION` | `1` (o `0` en Radeon RX 5000/6000) | en RDNA 1 y 2 vía Vulkan, la flash attention duplica el tiempo de lectura del fragmento; medido en una RX 6700 XT |
| `OLLAMA_KV_CACHE_TYPE` | `q8_0` (o `f16` con la flash attention apagada) | Ollama solo compacta la caché cuando la flash attention está encendida |
| `OLLAMA_GPU_OVERHEAD` | `0` | sin reserva artificial de VRAM |
| `OLLAMA_KEEP_ALIVE` | `30m` | el modelo queda cargado entre una ventana y la siguiente |
| `LLAMA_ARG_CACHE_RAM` | `0` | sin caché de prompts en la RAM: el runner reservaba 8 GB que nunca se reutilizaban aquí (cada ventana es un pedido nuevo) y parecían modelo desbordado |

Un valor que usted mismo haya cambiado se respeta y se dice en la consola; el desinstalador quita solo lo que el instalador grabó. El registro del servidor que el programa levanta queda en `%LOCALAPPDATA%\GClaudeIndexer\ollama-serve.log`, y el registro de la ejecución dice qué tarjeta y qué backend (CUDA, ROCm o Vulkan) está usando Ollama.

## Los sensores de la CPU y los ventiladores

Temperatura, consumo y rotación del ventilador de la CPU solo se pueden leer con privilegio de administrador: el ventilador está en el chip SuperIO de la placa madre, que Windows solo expone a un driver de kernel. Hay dos maneras de pedirlo, ambas opcionales. El botón **Leer sensores de la CPU y ventiladores**, en la pantalla Ejecución, lo pide bajo demanda, cuantas veces usted quiera, y explica en una línea lo que Windows va a preguntar. El acceso directo "GClaude Indexer (CPU sensor)" lo pide solo cada vez que usted abre el programa. Lo que sube con privilegio no es el programa: es un proceso auxiliar pequeño, cuya única función es leer los sensores y devolver los números. El servidor, la indexación y sus documentos corren sin privilegio, y el auxiliar se cierra junto con el programa.

Responder **No** es seguro y no cuesta nada: el programa abre como con el acceso directo común, mostrando temperatura, consumo, frecuencia, VRAM usada y el modelo cargado en la GPU, y "requiere administrador, haga clic en Leer sensores" en la temperatura, el consumo y el ventilador de la CPU. Nada falla y el botón sigue disponible.

Lo que la pantalla muestra y por qué:

- **"detenido"** es lectura real de 0 RPM. Las tarjetas de video modernas detienen el ventilador cuando están frías.
- **"requiere administrador, haga clic en Leer sensores"** quiere decir que el valor existe, pero no se puede leer sin el auxiliar.
- **"no medido"** quiere decir que la máquina no tiene un sensor que la biblioteca lea. En notebooks los ventiladores pertenecen al controlador embebido y solo el fabricante los expone; los notebooks Dell se leen por la interfaz de la propia Dell.
- **Temperatura y consumo de la CPU en procesadores recientes** pueden necesitar el driver PawnIO, que el instalador ofrece como ítem opcional (Windows pide administrador para instalarlo).
- **VRAM usada** y **Modelo en la tarjeta** aparecen cuando hay tarjeta de video: así ve si el modelo cupo entero en ella.

El ventilador de la CPU se elige por el nombre del sensor, cuando la placa da uno, o por el header fijo de CPU del chip; el programa nunca muestra "el primer ventilador que gira" como si fuera el de la CPU. El lector elevado se vuelve a lanzar cuando hace falta después de reiniciar la computadora.

## Desinstalación en detalle

Si instaló con el instalador de Windows, use Configuración > Aplicaciones.

Si no, haga doble clic en `Desinstalar.bat`, en la carpeta del proyecto (la misma de `Indexer.bat`), o desde el prompt:

```powershell
.\Desinstalar.bat
powershell -ExecutionPolicy Bypass -File uninstall.ps1
```

**¿Por qué no simplemente `.\uninstall.ps1`?** Google Drive marca todo archivo que sincroniza como venido de internet, y la política de ejecución predeterminada de Windows (RemoteSigned) se niega a correr un `.ps1` así sin firma digital. No hay nada malo con el script: `Desinstalar.bat` pasa `-ExecutionPolicy Bypass` en esa ejecución, como todos los lanzadores de este proyecto. Ejecutar `install.ps1` también limpia esa marca de los scripts de la carpeta.

Pregunta ítem por ítem, y la respuesta predeterminada es siempre **no**. Separa lo que esta instalación tiene como propio (el entorno virtual, los accesos directos, las bibliotecas de sensores, las configuraciones locales, las entradas de PATH y las variables de entorno que creó) de los programas comunes que solo instaló por usted: Tesseract, Ghostscript, Ollama, Python y los modelos descargados de Ollama. Otros programas pueden estar usándolos, así que cada uno se ofrece por separado.

**Nunca borra sus proyectos.** Las carpetas de salida, las bases de datos y los informes generados son sus documentos. El script lista dónde están, con el tamaño de cada uno, y deja la decisión en sus manos.

Tres opciones cubren los usos no interactivos:

```powershell
powershell -ExecutionPolicy Bypass -File uninstall.ps1 -WhatIfOnly        # muestra el plan, no quita nada
powershell -ExecutionPolicy Bypass -File uninstall.ps1 -KeepDependencies  # mantiene Tesseract, Ghostscript, Ollama, Python
powershell -ExecutionPolicy Bypass -File uninstall.ps1 -RemoveAll         # dice sí a todo (menos a sus proyectos)
```

La carpeta del propio proyecto, si está sincronizada por Google Drive, nunca se toca: bórrela allí si quiere que desaparezca de todas las computadoras.

## Las pantallas del programa

La interfaz tiene siete pantallas, más **Manual** y **Acerca de**:

1. **Proyectos**: todos los proyectos que esta computadora conoce, con fecha de creación y estado. Es donde el programa abre.
   - **Catálogo compartido**: apúntelo a una carpeta dentro de Google Drive y toda computadora conectada a ese Drive pasa a ver, abrir, editar y borrar los mismos proyectos. Sin él, la lista de proyectos queda solo en esta máquina, aunque los proyectos estén sincronizados. Los proyectos guardados en el disco local de otra computadora aparecen marcados como fuera de alcance.
   - **Abrir proyecto existente** recibe una carpeta que usted indica y reabre el proyecto que esté en ella: después de una reinstalación, en una máquina nueva, para una carpeta movida o que alguien le mandó. Nada se recrea; la carpeta de salida ya guarda el proyecto entero.
   - **Borrar** ofrece dos opciones: solo quitar el proyecto de la lista o también borrar los archivos generados. En ese caso el programa borra solo lo que él mismo creó (base, informes, `buscar.bat`, la carpeta de trabajo local). Sus archivos en la carpeta de salida quedan, y la carpeta solo desaparece si queda vacía. En `project_instructions.md` y `CLAUDE.md` sale solo el bloque generado. La carpeta de origen nunca se toca.
2. **Nuevo proyecto**: carpeta de origen, carpeta de salida, qué tipos de archivo incluir, cómo agrupar los documentos y qué motor usar. Al elegir la carpeta de origen, el programa propone una configuración a partir de lo que encuentra en ella (tipos de archivo, agrupamiento, idioma). Todo campo tiene un valor predeterminado y una ayuda "?".
3. **Ejecución**: una línea por etapa (recorrido, conversión, extracción por página, preparación de ventanas, clasificación), cada una con un botón para ejecutarla, una barra de progreso con estimación de tiempo y los botones **Pausar** y **Continuar**. Pausar responde al instante ("deteniendo") y la reanudación sigue desde donde quedó. Abajo, un registro en vivo en lenguaje simple y los gráficos de CPU, RAM y GPU, con los sensores. Mientras se recorre la carpeta, un contador muestra cuántos archivos ya se vieron. Un botón aparte, **Importar y generar informes**, transforma los ítems clasificados en los archivos de salida. Toda operación larga aparece en una barra de actividad con nombre y cronómetro, que sobrevive a un F5; pedir otra operación sobre un proyecto ocupado lleva a una página "en curso", sin perder nada. Si la carpeta de origen cambió desde la última ejecución, un aviso aparece arriba poco después de que la página carga.
4. **Actualizar acervo**: se llega desde ese aviso. Lista los documentos nuevos, editados y quitados, nombra los que se van a reprocesar e informa el costo: cuántos archivos pasan por el OCR de nuevo (incluidos aquellos cuyo OCR falló la última vez), cuántas ventanas se reclasifican, cuántas mantienen la clasificación, y qué documentos tendrán la numeración de folios alterada. Nada cambia hasta que usted confirma. Si la carpeta de origen no se puede leer (disco desconectado, carpeta movida), la pantalla avisa y no ofrece nada: una carpeta inaccesible nunca se confunde con un acervo cuyos documentos fueron borrados.
5. **Resultado**: la nota de calidad, los pendientes, una vista previa de cada archivo generado, el paquete para Claude con el presupuesto de tokens y la lista de lo que quedó fuera por tamaño, un botón para abrir la carpeta de salida y **Liberar espacio**, que borra los archivos intermedios de la carpeta de trabajo local (PDF con OCR y trozos de texto). La base, los informes y los registros nunca se tocan con eso.
6. **Buscar en el acervo**: búsqueda de texto completo en las páginas del proyecto, con el fragmento y la página de cada resultado. Una casilla opcional consulta también el LexML del Senado (vea [Búsqueda por tema y LexML](#búsqueda-por-tema-y-lexml)).
7. **Conjuntos**: varios acervos en un único Claude Project (vea [Varios acervos en un Project](#varios-acervos-en-un-project-conjuntos)).

El encabezado de toda pantalla tiene un selector de idioma, un selector de tema (Claro, Oscuro, Sepia, Alto contraste, Aurora, Toga, Grafito y Océano) y un selector de diseño (Estándar, Técnico, Editorial y Compacto). Las elecciones quedan guardadas en su navegador. El movimiento entre pantallas se apaga cuando Windows pide menos movimiento.

## Mantener un acervo actualizado

Un acervo cambia: llegan documentos, un escaneo se reemplaza por uno mejor, algo se retira. Nada de eso exige indexar todo de nuevo.

Abra el proyecto. Unos segundos después de que aparece la pantalla Ejecución, si algo cambió en la carpeta de origen, un aviso dice cuánto ("14 nuevos, 3 editados, 1 quitado"). Sígalo hasta **Actualizar acervo**, vea el plan y confirme. Después ejecute las etapas como de costumbre: encuentran solo el trabajo que la actualización dejó. Agregar un documento a un acervo de 500 páginas reclasifica una ventana en vez de treinta y seis: cerca de un minuto en vez de dieciocho y medio. Un segundo recorrido no vuelve a leer archivos iguales.

**Una etapa no forma parte de "Ejecutar todo".** Transformar los ítems clasificados en los archivos Markdown es un botón propio, **Importar y generar informes**, en la pantalla Ejecución. Que la clasificación termine no los graba. Si usted se salta esa etapa, los informes siguen describiendo el acervo como era antes. El programa se lo recuerda: cuando no queda nada por procesar, aparece un aviso con el botón, y la pantalla Resultado dice cuándo los archivos mostrados son anteriores al proyecto y qué cambió desde entonces. Después de actualizar, envíe los archivos nuevos a su Project de Claude.

**Por qué no es el acervo entero.** Los documentos se agrupan, y las páginas de un grupo se leen como una secuencia larga, cortada en ventanas superpuestas; las ventanas son lo que lee el motor de clasificación. Un cambio invalida el grupo a partir de la primera página que se desplazó. Todo lo anterior mantiene sus páginas y su clasificación. Un documento agregado al final de un grupo casi no cuesta; uno insertado al inicio desplaza toda página posterior y cuesta más. La pantalla dice en qué caso está usted antes de confirmar.

**Documentos quitados.** Las páginas y piezas salen del índice, la copia convertida se borra, y el nombre y el momento del retiro quedan registrados en `review.md`. Si la carpeta tenía una copia idéntica del documento quitado, esa copia pasa a indexarse en su lugar. Si un grupo desaparece por completo, su `index-<grupo>.md` se borra.

**Numeración de folios que cambia.** En un acervo del tipo expediente, la numeración de folios (f. 1, f. 2...) corre continua por el grupo. Agregar o quitar un documento en el medio cambia los números de los documentos siguientes. La pantalla de confirmación lista cuáles son y el registro avisa: conversaciones anteriores con Claude que citaban esos folios pueden quedar desactualizadas.

Los documentos que solo necesitan renumeración no pasan por el OCR de nuevo: los archivos convertidos siguen en la carpeta de trabajo local y se vuelven a leer. Solo un documento cuyo contenido cambió paga ese costo. Un archivo cuyo OCR falló se rehace en la próxima conversión, y la etapa queda "pendiente" mientras haya uno así.

**Si usted limpió los archivos intermedios** con Liberar espacio, los documentos que se volverían a leer necesitan convertirse de nuevo. La actualización lo maneja correctamente; solo tarda más.

**Si la carpeta de origen no se puede alcanzar** (el disco está desconectado, la carpeta fue movida o renombrada), nada se ofrece y nada se altera.

**Una computadora a la vez.** Mientras un proyecto está abierto, queda bloqueado para esa computadora. Otra computadora recibe el aviso de quién lo está usando. Cerrar el navegador libera el bloqueo en unos cinco minutos; el bloqueo de una máquina que se colgó vence solo a los diez.

## Lograr una buena clasificación

Dos cosas deciden más sobre el resultado que cualquier otra.

**Complete el Tema del acervo y el Tipo de acervo en Nuevo proyecto.** El motor `local` le muestra esos campos al modelo, y son ellos los que dicen qué tipo de documento está leyendo. Un acervo descrito solo con los valores predeterminados termina clasificado contra ejemplos genéricos, y el modelo responde "no sé" para casi todo tipo. Una frase sobre el acervo (qué es, de dónde vino, qué documentos tiene) es lo más eficaz que usted puede hacer por el resultado. **Rol en las instrucciones** y **Reglas extra** también se transmiten, como contexto.

**Qué modelo usar.** Medido en este proyecto, sobre las mismas ventanas de un mismo documento, con todos los modelos corriendo enteros en una tarjeta de 8 GB:

| Modelo | Tamaño | Tipo completado | s/ventana |
|---|---:|---:|---:|
| `qwen3.5:4b` | 3,0 GB | 100% | 30,8 |
| `gemma4:e4b` | 3,1 GB | 79,5% | 38,5 |
| `qwen3.5:9b` | 5,3 GB | 79,5% | 86,2 |
| `qwen3:8b` | 5,4 GB | 100% | 108,8 |
| `granite4.2:8b` | 5,7 GB | 100% | 116,9 |

En esa medición, `qwen3.5:4b` alcanzó la calidad del mejor en un cuarto del tiempo y con la mitad de la VRAM. Medido después contra una clave de respuestas, en el acervo de demostración (72 páginas, 41 piezas), `qwen3.5:9b` acertó más la fecha (88,6%) y el autor (84,4%) y tardó 4 min 12 s, contra 4 s del motor de reglas; los números completos y lo que no dicen están en [QUALITY.es.md](QUALITY.es.md). Por eso el valor predeterminado desde la 1.5.14 es `qwen3.5:9b` en una tarjeta de 8 GB o más y `qwen3.5:4b` en las menores. Describir una página es lectura y disciplina de formato; el tamaño no compra calidad por sí solo y cuesta tiempo.

**Elija un modelo que quepa en su tarjeta de video.** Lo que no cabe en la VRAM, Ollama lo corre en la CPU, y la diferencia es grande. En una tarjeta de 8 GB, un modelo de 9,1 GB corrió con el 17% de sí en la GPU; uno de 5 GB corrió entero en la GPU. La pantalla Ejecución muestra la VRAM de la tarjeta, la VRAM usada y el modelo cargado; la pantalla Acerca de lista los modelos instalados; el registro avisa cuando el modelo elegido no cabe y dice qué tarjeta y qué backend están en uso. Un modelo que cabe y termina vale más que uno mayor que pasa la ejecución entera desbordando.

**Contexto según el hardware.** El tamaño del contexto enviado al modelo (`num_ctx`) tiene un techo calculado por la VRAM de la tarjeta y por la RAM, para que el modelo y la caché queden enteros en la tarjeta. Un fragmento grande nunca se corta en silencio: el pedido va con `truncate: false`, y un fragmento que no cabe se divide en dos pedidos. Una respuesta que vuelve incompleta se pide de nuevo con contexto mayor o ventana menor.

Si la nota de calidad parece baja, abra el registro: informa cómo se está usando la GPU. En la pantalla Resultado, la nota viene descompuesta en confianza, llenado de campos y penalizaciones. La nota se basa en lo que el propio motor declaró; no es una medida de acierto real. Para medir el acierto, use el acervo de demostración y `tools/medir_acerto.py` ([QUALITY.es.md](QUALITY.es.md)), o revise algunas piezas de su acervo por muestreo.

## Lo que garantiza el índice

Tres propiedades valen sin importar qué tan bien haga el trabajo el modelo, porque el código las impone.

**Toda página llega al índice.** Una página que el modelo nunca mencionó igual recibe una entrada, con su referencia, el archivo y el propio texto como resumen, porque el agrupamiento recorre las páginas de la ventana, no la respuesta del modelo. Una pieza que no pasa la validación se descarta, pero sus páginas vuelven como entrada de confianza baja, en vez de desaparecer con ella. Un índice que omite una página en silencio es peor que ningún índice: lo que falta es invisible.

**Un documento entero es siempre una pieza propia.** Un archivo que es un solo documento (HTML, Word, correo, planilla) empieza una pieza nueva, aunque el modelo lo haya pegado al documento anterior. En una página de legislación, el epígrafe ("LEI Nº 8.078, DE 11 DE SETEMBRO DE 1990") se vuelve el tipo de la pieza. El autor de un acto se lee del texto completo, y cada autor y cada tipo tienen una sola grafía en todo el índice.

**Las fechas mantienen la precisión que el documento de hecho tiene.** Los documentos fechados por período ("competencia 01/2020", "ejercicio 2019") se guardan como `2020-01` y `2019`, y no se completan hasta un primer día del mes que la página nunca afirmó. La ISO 8601 admite la forma reducida, y sigue ordenando correctamente en `timeline.md`. Una fecha cuyo día no existe (`2021-09-31`) cae al mes; un texto que no es fecha deja el campo vacío, y la pieza mantiene todo lo demás.

## Ventanas, bloques y OCR

Una **ventana** es una secuencia de páginas seguidas que el clasificador lee de una vez para descubrir dónde empieza y termina cada pieza.

**Páginas por ventana** es lo que más afecta la calidad: es cuántas páginas van en cada pedido al modelo, que responde con una línea por página. El valor predeterminado del formulario es 16. Cuando se ajustó el motor local, 8 dio los mejores resultados: con 16, la respuesta pasaba de 3.500 tokens y se truncaba, y con 4 se triplica el número de pedidos sin ganancia. Desde la 1.3.2, el motor local nota cuando una respuesta vuelve incompleta y vuelve a intentar con un contexto mayor o dividiendo la ventana. Si la nota está baja con el modelo local, pruebe 8. Muchos documentos cortos mezclados salen mejor con ventanas menores; los documentos largos y estandarizados toleran ventanas mayores.

**Páginas por bloque** no afecta el índice. Solo corta PDF muy grandes en archivos auxiliares dentro de la carpeta de trabajo local, que nada más lee y que Liberar espacio borra. Déjelo en 80; redúzcalo solo si un PDF muy grande (500+ páginas) hace que la conversión se quede sin memoria.

**OCR** solo se aplica a páginas sin capa de texto; el programa revisa página por página y deja en paz las que ya tienen texto. Un PDF con texto nativo y algunas hojas escaneadas en el medio recibe OCR solo en esas hojas (desde la 1.5.2), y un PDF firmado digitalmente también recibe OCR. Un PDF escaneado entero pasa por una configuración propia del OCR (carpeta `configs/`), que mejoró el resultado en los escaneos del acervo de demostración. Ahí lo que importa es que el **Idioma del OCR** corresponda a sus documentos. La conversión corre en dos colas (OCR y el resto) y tiene plazo por archivo: un archivo que se cuelga no retiene a los otros, y un OCR que falló se rehace en la próxima conversión.

**Archivos leídos como texto.** HTML y las demás páginas web se leen como texto (el texto tachado se vuelve `~~así~~`, para que el clasificador sepa que fue tachado); la codificación de archivos de texto y correos se detecta (UTF-8, Windows-1252 y otras); los hipervínculos de Word se mantienen. Los archivos `.ini` nunca se indexan, y los archivos binarios sin texto aparecen en los pendientes con el motivo.

## Motores de clasificación

La clasificación (decidir qué es cada página, quién la escribió y cuándo) es la única etapa en la que usted elige cómo se hace el trabajo. Todas las otras (recorrido, OCR, extracción, búsqueda, generación de informes) son idénticas sin importar el motor, y corren siempre localmente.

| Motor | Costo | ¿Sale de la máquina? | Necesita |
|---|---|---|---|
| `rules` | gratuito | no | nada: corre en cualquier máquina Windows |
| `local` | gratuito | no | Ollama, instalado automáticamente; más rápido con GPU, funciona sin una |
| `claude_code` | su suscripción a Claude ya existente | **sí** | Claude Code ya instalado en esta máquina |
| `automatic` | | | elige `local` si el hardware aguanta, si no `rules`; nunca elige `claude_code` por sí solo |

**`claude_code` es enteramente opcional.** El programa funciona de principio a fin sin él. Elíjalo solo si ya usa Claude Code y quiere que él haga la clasificación. El programa entonces graba un `CLAUDE.md` en la carpeta de salida y muestra una frase para decirle a Claude Code (`procese las ventanas`); abra Claude Code en la carpeta de salida, diga la frase y, cuando termine, haga clic en **Comprobar de nuevo si las ventanas terminaron**. Ese `CLAUDE.md` le ordena a Claude Code tratar el texto de los documentos como dato no confiable, nunca como instrucción.

`rules` es determinista: busca marcadores conocidos de tipo de documento, patrones de fecha y bloques de firma, sin ningún modelo de aprendizaje automático, así que el resultado es reproducible y no necesita instalación. `local` usa un modelo abierto servido por [Ollama](https://ollama.com) en su propia máquina (`http://127.0.0.1:11434`, nunca una dirección remota, nunca por proxy) y en general da mejores resultados que `rules`, al costo del espacio en disco, la descarga y (opcionalmente) la GPU listados en Requisitos. Con tarjeta de video, el motor local espera a que Ollama vuelva en vez de caer a las reglas; sin tarjeta, cae y vuelve al modelo cuando este responda.

**Legislación del Planalto.** Las páginas `.htm`/`.html` guardadas del sitio del Planalto (leyes, decretos, medidas provisorias, portarias, resoluciones, actos del Imperio) se leen por la estructura de la propia página, sin modelo: tipo, número, fecha, autor y resumen salen del epígrafe y del encabezado. Ningún motor se consulta para ellas, y el resultado alimenta `normas-citadas.md`.

**Revisar confianza baja**, en Nuevo proyecto, corre `rules` en todo y manda solo las piezas de confianza baja a un segundo motor a su elección: un punto medio entre el costo cero de `rules` y la precisión de un motor más fuerte en las páginas que lo necesitan. La pantalla Resultado tiene una tabla para comparar motores y modelos corridos sobre el mismo acervo.

## Archivos de salida

Grabados en la carpeta de salida que usted eligió, en el idioma en que esté la interfaz cuando los genere:

- `index.md`: el sumario. Lista los grupos y dice qué archivo de índice abrir para cada uno; cuenta las páginas de legislación y apunta a `normas-citadas.md`.
- `index-<grupo>.md`: un índice por grupo. Cada pieza con folios o páginas, tipo, fecha, autor, archivo y página dentro del PDF, y un resumen. Un índice de grupo de más de 25 MB sale en partes `index-<grupo>-1.md`, `-2.md`..., cortando solo entre archivos de origen. Las líneas son compactas: el nombre del archivo no se repite en la columna Intervalo, y la columna Confianza solo aparece cuando hay alguna línea con duda.
- `normas-citadas.md`: una línea por norma reconocida en el acervo (ley, decreto, medida provisoria, portaria...), con tipo, número, fecha, resumen, en qué grupos y páginas aparece y un enlace al texto en LexML. Es lo que reemplaza al antiguo archivo de legislación por grupo (`legislacao-*.md`), que dejó de existir en la 1.8.0 (un proyecto anterior pierde ese archivo en la próxima generación). Solo existe cuando hay al menos una norma.
- `timeline.md`: las piezas fechadas en orden cronológico, sin los actos del Planalto. Un grupo con más de 2.000 piezas fechadas recibe su propio `timeline-<grupo>.md`, que queda fuera del paquete de Claude (repite el índice del grupo por fecha); la pantalla de resultado muestra su tamaño.
- `review.md`: un informe de revisión: qué se leyó, lagunas, fallas, qué sigue pendiente, y los documentos quitados de la carpeta de origen, con el momento en que salió cada uno. El índice y la cronología describen el acervo como está hoy; aquí es donde usted descubre lo que solía estar en él.
- `project_instructions.md`: instrucciones para un Project de Claude, armadas con los campos que usted completó en Nuevo proyecto, incluido cómo usar el índice, cómo encontrar una norma en `normas-citadas.md` y la regla de verificar siempre los valores en el documento original.
- `buscar.bat`: la búsqueda por tema para Claude Code, descrita en [Búsqueda por tema y LexML](#búsqueda-por-tema-y-lexml).
- `project.db`: la base del proyecto. Guarda todo, incluido el texto de cada página y el índice de búsqueda.
- `CLAUDE.md`: solo cuando usted usa el motor `claude_code` o graba un conjunto en una carpeta.

Los archivos intermedios (PDF con OCR en `converted/`, trozos de texto en `blocks/`) quedan en `%LOCALAPPDATA%\GClaudeIndexer\work\<proyecto>\`, fuera de la carpeta de salida, desde la 1.5.8: una carpeta de salida en el Drive no sincroniza gigabytes que solo esta máquina usa. Un proyecto anterior que todavía tenga esas carpetas en la salida se sigue leyendo desde allí.

**Su texto en esos archivos se preserva.** En `project_instructions.md` y `CLAUDE.md`, el contenido generado queda entre `<!-- GCLAUDE-INDEXER:BEGIN ... -->` y `<!-- GCLAUDE-INDEXER:END -->`. Generar los archivos de nuevo rehace solo ese bloque; lo que usted escribió fuera de él queda, y no se repite en cada generación. Si la carpeta de salida ya tenía un `CLAUDE.md` suyo, se mantiene y el bloque se le agrega, con una copia `.bak` del original la primera vez. El texto pegado en **Instrucciones que ya usa** va al inicio de `project_instructions.md`.

La pantalla Resultado también ofrece un paquete `.zip` con esos archivos y una guía corta. La guía dice que pegue `project_instructions.md` entero en las instrucciones del Project y que envíe `index.md`, los archivos `index-<grupo>.md`, `normas-citadas.md`, `timeline.md` y `review.md` como conocimiento del proyecto.

**Los límites de un Project de Claude, y cómo los maneja el programa.** Un Project acepta 30 MB por archivo de conocimiento y solo lee texto (un `.zip` no se lee). Todo lo que usted envía tiene que caber en la ventana de contexto; por encima de unos 500 mil tokens el Project pasa a usar búsqueda automática en los archivos, que funciona hasta algunos millones de tokens y empeora después. Por eso la pantalla Resultado muestra, antes del botón de descarga, cada archivo que va en el paquete con tamaño y tokens estimados, y avisa en esos dos niveles (el techo de tokens se ajusta por proyecto; el valor predeterminado es 2 millones). Un archivo de más de 30 MB nunca entra en el paquete, porque el Project lo rechazaría: la pantalla lista lo que quedó fuera. En la mayoría de los casos basta con generar los informes de nuevo para que el índice salga en partes de menos de 30 MB; la excepción es un único archivo de origen cuyo índice, por sí solo, pase de 30 MB, porque el índice solo se parte en la frontera entre archivos. El programa mantiene el paquete pequeño dejando fuera el texto de las normas (Claude las abre por el enlace de `normas-citadas.md`), sin repetir el índice en la cronología, cortando el índice de más de 25 MB y omitiendo lo que no informa.

## Varios acervos en un Project: conjuntos

La pantalla **Conjuntos** arma un paquete único a partir de dos o más proyectos, para un Claude Project que responda sobre todos ellos. Cada proyecto del conjunto recibe un alias corto (propuesto a partir del nombre: "Diretoria / Região Sul" se vuelve `diretoria-regiao-sul`), y en el paquete combinado cada archivo lleva el alias como prefijo: `diretoria-regiao-sul__index.md`, `contratos__index-Processo.md`. Los enlaces dentro de los sumarios y las cronologías se reescriben a los nombres con prefijo, así que ningún nombre choca aunque dos proyectos tengan el mismo grupo. Un único `project_instructions.md` sale con el texto personal del conjunto al inicio, una sección "En qué acervo buscar" y una sección por acervo. El presupuesto de tokens se suma y el techo es el menor entre los proyectos.

Un miembro cuya carpeta está fuera de alcance en esta computadora (Drive de otra máquina), cuya base no abre o que nunca generó informes queda fuera del paquete, con el motivo en pantalla, y sigue en el conjunto. Los conjuntos quedan en `%LOCALAPPDATA%\GClaudeIndexer\sets.json`, en esta máquina.

**Grabar en la carpeta** escribe los mismos archivos en una carpeta a su elección, más un `CLAUDE.md` combinado que le dice a Claude Code dónde está cada acervo y cómo buscar en cada uno. La carpeta no puede ser la carpeta de origen ni la de salida de un acervo. Volver a grabar actualiza solo lo que cambió, mantiene lo que usted escribió fuera de las marcas y borra los archivos de un alias que dejó de existir.

## Búsqueda por tema y LexML

Al final de la extracción, el texto de todas las páginas entra en un índice de búsqueda (SQLite FTS5) dentro de `project.db`; la etapa solo termina cuando la búsqueda está lista. La pantalla **Buscar en el acervo** consulta ese índice y muestra, para cada resultado, el archivo, la página y el fragmento.

**Para Claude Code**, la carpeta de salida recibe un `buscar.bat`: `buscar.bat saneamento` lista los archivos y páginas en que aparece el término, agrupados por archivo, con el enlace de la norma al lado de los fragmentos de legislación. El `CLAUDE.md` explica el comando. El `.bat` llama al Python del propio programa con rutas de esta máquina y se vuelve a grabar en cada generación. Opciones: `--grupo` restringe a un grupo, `--so-legislacao` muestra solo normas, `--limite` limita la cantidad, `--lexml` consulta también LexML.

**LexML.** [LexML](https://www.lexml.gov.br) es el portal del Senado brasileño que cataloga la legislación del país. Con la casilla "Buscar también en LexML" marcada en la pantalla de búsqueda (en `buscar.bat`, con `--lexml` o cuando ninguna norma del acervo cita el término), el programa le pregunta al servicio de búsqueda del portal (SRU) por las normas que tratan el término, sin enviar nada de su acervo más allá del término escrito. El 02/11/2026 el portal pasó a responder a las búsquedas de programas con una página de verificación de seguridad; en ese caso el programa lo dice y muestra el enlace para abrir la búsqueda en el navegador. El programa nunca intenta evitar la verificación. Los enlaces de cada norma (`https://www.lexml.gov.br/urn/...`) siguen abriendo normalmente.

## OCR e idioma de los documentos

Los proyectos nuevos usan OCR en portugués (`por`) de forma predeterminada, ya que el proyecto nació para acervos en portugués de Brasil.

El paquete de Tesseract para Windows trae solo `eng` y `osd`, así que `install.ps1` descarga los datos del idioma que el proyecto usa (`por`, de forma predeterminada), con el SHA-256 verificado. Cuando la carpeta `tessdata` de Tesseract exige administrador (el caso común), los datos van a la carpeta de esta máquina (`%LOCALAPPDATA%\GClaudeIndexer\tessdata`), y el programa apunta Tesseract a ella solo en su propio proceso, sin pedir administrador. El programa también lo hace al abrir, así que un idioma que falte se corrige apenas la máquina esté en internet.

Si su acervo está en otro idioma, cambie el **Idioma del OCR** en Nuevo proyecto al código de Tesseract (por ejemplo `eng` para inglés, `spa` para español, o `por+eng` para los dos en el mismo acervo) e instale los datos de ese idioma:

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1 -OcrLanguage spa
```

El instalador solo instala idiomas cuyo SHA-256 tiene fijado: hoy `por`, `eng`, `spa` y `osd`. Nunca descarga un archivo que no puede verificar; para cualquier otro idioma, muestra de dónde tomar el archivo y dónde ponerlo.

## Ejecutar la suite de pruebas

Si está contribuyendo con cambios, o quiere confirmar que todo funciona después de instalar, use el Python de dentro del entorno que creó el instalador (no el `python` que encuentre su PATH):

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -B -m pytest -q
```

Una ejecución correcta termina con una línea como `1197 passed, ... warnings in ...s` y ninguna falla. El número de pruebas crece con el tiempo; los avisos vienen de bibliotecas de terceros, y la cuenta puede variar entre máquinas. La suite no habla con el Ollama real ni con la red, y nunca detiene el Ollama de la máquina. Vea [CONTRIBUTING.es.md](CONTRIBUTING.es.md) (original en inglés: [CONTRIBUTING.md](../CONTRIBUTING.md)) para la preparación completa de un entorno de desarrollo. El CI de GitHub ejecuta la suite e indexa el acervo de demostración en cada push, adjuntando el informe de acierto a la corrida.

## Solución de problemas

- **Aparece un aviso que dice que el sistema se actualizó después de que se abrió la ventana.** El código en disco cambió mientras el servidor corría, y Python carga los módulos una vez, al iniciar. Cierre el programa y ábralo de nuevo con el acceso directo.
- **El navegador abre pero la página nunca carga.** Espere unos segundos en la primera ejecución. Si sigue así, revise si otro programa está usando el puerto 8000.
- **Aparece "Solicitud rechazada".** Algo que no son las pantallas del propio programa (en general un sitio) intentó mandar un comando y fue bloqueado. Abra siempre el programa con el acceso directo o en `http://127.0.0.1:8000`.
- **Aparece "base ocupada" u "operación en curso".** Otra operación está usando el proyecto (una conversión, una generación de informes). Nada se perdió: espere a que la barra de actividad termine e intente de nuevo.
- **"python no se reconoce..." en PowerShell.** Python no está en el PATH. Reinstálelo con el comando `winget` de *Instalación sin el instalador*, o use la ruta completa mostrada en *Ejecutar la suite de pruebas*.
- **El OCR falla o no produce texto.** Revise si Tesseract y Ghostscript están instalados (`install.ps1` lo verifica) y si el paquete de idioma de sus documentos está instalado (vea *OCR e idioma de los documentos*). Un archivo cuyo OCR falló se rehace en la próxima conversión.
- **El motor `local` cae a `rules`.** Solo pasa en una máquina sin tarjeta de video: Ollama no está corriendo, o la VRAM y la RAM sumadas no alcanzan para el modelo. No es un error: el programa se degrada a propósito en vez de fallar, y vuelve al modelo cuando Ollama responda. Con tarjeta de video, espera a Ollama en vez de caer. La pantalla Acerca de muestra el diagnóstico de la instalación y `ollama-serve.log` lo que dijo el servidor.
- **La tarjeta de video está casi vacía y la RAM llena durante la clasificación.** Vea en el registro qué backend está en uso y si el modelo cupo. En una Radeon RX 5000/6000, revise que `OLLAMA_FLASH_ATTENTION` esté en `0` (el instalador lo hace); en cualquier tarjeta, `LLAMA_ARG_CACHE_RAM=0` evita 8 GB de caché de prompts en la RAM.
- **Nada funciona hasta que reinicio después de instalar.** Corregido: el instalador anota dónde puso cada programa e `Indexer.bat` recarga el PATH del registro. En una instalación anterior, ejecute `install.ps1` una vez más.
- **Reinstalé (o formateé) y mis proyectos desaparecieron de la lista.** No desaparecieron: están en sus carpetas de salida, y solo la lista se recreó vacía. Use **Proyectos > Abrir proyecto existente** e indique la carpeta de salida. Nunca apunte **Nuevo proyecto** a una carpeta que ya tiene proyecto: el programa lo impide.
- **Mis proyectos no aparecen en la otra computadora.** Los proyectos se sincronizan por el Drive, pero la lista queda en cada máquina hasta que usted configure un catálogo compartido. Abra **Proyectos > Catálogo compartido**, elija una carpeta dentro de su Drive y guarde, en las dos computadoras, apuntando a la misma carpeta.
- **"Proyecto en uso en otra máquina".** Cierre el programa en la otra computadora. Si se colgó o se apagó, espere a que el bloqueo venza o elija **Asumir de todos modos**, solo si está seguro de que la otra no lo está usando.
- **"Señal de sincronización incompleta" al abrir un proyecto en una segunda máquina justo después de la primera.** Espere a que Google Drive termine antes de abrir en otro lugar. El programa detecta sincronizaciones incompletas y el bloqueo de otra máquina, pero no reemplaza la espera.
- **Archivos con falla en los pendientes.** En general son archivos protegidos con contraseña, corruptos o binarios sin texto. Guarde una copia sin protección en la carpeta de origen y actualice el acervo.
- **La búsqueda en LexML dice que el Senado pidió verificación.** El portal responde a los programas con una página de verificación; abra el enlace mostrado y haga la búsqueda en el navegador. El programa no evita la verificación.

## Documentación

- [README.es.md](README.es.md): para qué sirve el programa y cómo empezar.
- [QUALITY.es.md](QUALITY.es.md): el acierto medido contra una clave de respuestas en el acervo de demostración, y lo que los números no dicen.
- [CONTRIBUTING.es.md](CONTRIBUTING.es.md): preparación del entorno de desarrollo, cómo ejecutar una sola prueba y las convenciones del proyecto.
- [SPECIFICATION.md](SPECIFICATION.md): la especificación técnica, en inglés: modelo de datos, cada etapa de procesamiento, reglas de seguridad y decisiones de diseño.
- [CHANGELOG.es.md](CHANGELOG.es.md): lo que cambió, versión por versión. El original es [CHANGELOG.md](../CHANGELOG.md) en inglés; si difieren, vale el inglés.
- [SECURITY.md](../SECURITY.md): cómo reportar una vulnerabilidad (en inglés).
- [CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md): normas de convivencia para quien contribuye (en inglés).
- `demo/README.md` y `tools/README.md`: el acervo de demostración y las herramientas de línea de comandos.
