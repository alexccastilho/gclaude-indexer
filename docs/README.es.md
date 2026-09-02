*Lea esto en otros idiomas: [English](../README.md) · [Português (Brasil)](README.pt-BR.md)*

# GClaude Indexer

Una herramienta local y sin conexión que convierte una carpeta llena de
documentos en un índice consultable, una cronología y unas instrucciones
listas para un proyecto en Claude.

## Qué hace

Apunte GClaude Indexer a una carpeta de documentos — PDF escaneados, Word,
Excel, PowerPoint, imágenes, correos electrónicos, texto plano, casi
cualquier cosa — y él recorre la carpeta, aplica OCR a las páginas
escaneadas sin capa de texto, corta los PDF demasiado grandes en fragmentos
legibles y lee cada página. Después clasifica el contenido en elementos
individuales (cada uno con un tipo, una fecha cuando es posible
encontrarla, un autor y un resumen breve) y escribe cuatro archivos en
Markdown: un **índice** de cada elemento, una **cronología** ordenada por
fecha, un informe de **revisión** que enumera vacíos y fallos, y un
conjunto de **instrucciones de proyecto** listas para pegar en un nuevo
proyecto de Claude. Los documentos originales nunca se modifican — todo lo
que la herramienta produce son archivos nuevos, escritos junto a los
originales, en una carpeta de salida separada que usted elige.

La clasificación — el paso que decide qué es cada página, quién la escribió
y cuándo — puede hacerse de cuatro formas distintas, descritas abajo. Tres
de esas cuatro nunca salen de su máquina. El resto de los pasos (escaneo,
OCR, extracción por página, corte, generación de los cuatro informes) se
ejecuta siempre por completo en local, sin importar qué motor de
clasificación elija.

## Aspectos destacados

- **Sin conexión por diseño.** Salvo por el motor opcional `claude_code`
  (vea abajo), GClaude Indexer nunca envía un documento, una página de
  texto ni siquiera un nombre de archivo por la red. Esto importa
  especialmente a quien trabaja con colecciones sensibles o
  confidenciales — nada sale de la máquina, a menos que elija
  explícitamente el único motor que sí lo hace.
- **Solo Windows.** La aplicación habla directamente con interfaces
  específicas de Windows — PowerShell, WMI (para la detección de hardware y
  el monitoreo de recursos), el registro de Windows (para la ubicación de
  los datos de Tesseract y la detección de idioma) y el subsistema de
  Performance Counters (para los gráficos en vivo de CPU/GPU). No funciona
  en Linux ni en macOS.
- **Interfaz en tres idiomas** — español, inglés y portugués de Brasil,
  seleccionables en cualquier momento desde un menú en el encabezado de la
  página. El idioma por defecto se detecta automáticamente a partir del
  idioma de visualización de su Windows.
- **No necesita instalador para el uso diario.** Después de la
  configuración inicial de abajo, un acceso directo en el escritorio abre
  la aplicación con un doble clic. Nada se compila en un único `.exe`;
  sigue siendo scripts de Python y PowerShell simples y legibles.
- **Licenciado bajo la GNU GPL-3.0.** Vea [Licencia](#licencia) abajo para
  saber qué implica esto si piensa modificar o redistribuir este software.

> Una captura de pantalla de la interfaz ayudaría mucho aquí, pero todavía
> no se incluye ninguna — agregue una a esta sección cuando exista una
> captura real. No interprete la ausencia de una captura como señal de que
> la interfaz no existe: ejecute la aplicación usted mismo con los pasos de
> abajo para verla.

## Requisitos

- **Windows 10 u 11.** Obligatorio — vea [Aspectos destacados](#aspectos-destacados)
  arriba para el motivo.
- **Python 3.12**, específicamente. Se sabe que versiones más nuevas (3.13,
  3.14) rompen las versiones fijadas de las dependencias de este
  proyecto — si el `python` por defecto de su máquina es más nuevo, siga
  la nota en [Instalación](#instalación-primera-vez-en-una-máquina) abajo
  para seleccionar la 3.12 explícitamente.
- Para **OCR** (documentos escaneados sin capa de texto): Tesseract y
  Ghostscript. El instalador de abajo los instala automáticamente cuando
  es posible.
- Para el **motor de clasificación `local`** (el predeterminado
  recomendado): [Ollama](https://ollama.com), instalado automáticamente
  por el instalador de abajo si usted lo acepta. Una GPU con algunos
  gigabytes de VRAM libre acelera bastante este motor, pero no es
  obligatoria — Ollama usa toda la memoria de GPU que quepa y desborda el
  resto a la RAM del sistema por su cuenta. Como referencia aproximada, el
  modelo local predeterminado pesa cerca de 9,6 GB para descargar, y
  necesita algo más que eso sumando VRAM y RAM para ejecutarse; una máquina
  con poco de ambas cosas cae automáticamente al motor `rules` (vea
  [Motores de clasificación](#motores-de-clasificación) abajo), con una
  explicación mostrada en pantalla.
- El **motor `rules`** no necesita nada de lo anterior — funciona en
  cualquier máquina Windows capaz de ejecutar Python, sin GPU, sin
  descargas y sin software adicional.
- Unos pocos gigabytes de espacio libre en disco para el entorno de Python
  y, si lo usa, el modelo local de Ollama.

## Instalación (primera vez en una máquina)

No necesita Git, una cuenta de GitHub, ni experiencia de programación para
esto. Sí necesita poder abrir una carpeta en el Explorador de archivos y
ejecutar un comando en una terminal — ambos se explican paso a paso abajo.

**1. Ponga el código fuente en su máquina.** Si descargó este proyecto
como un archivo `.zip`, haga clic derecho sobre él y elija "Extraer
todo…", luego elija una carpeta común (por ejemplo, dentro de Documentos o
una carpeta sincronizada por Google Drive/OneDrive). Si ya lo clonó con
Git, ya tiene una carpeta — de cualquier forma, recuerde dónde está; el
resto de estas instrucciones la llama "la carpeta del proyecto".

**2. Abra PowerShell dentro de la carpeta del proyecto.** En el Explorador
de archivos, abra la carpeta del proyecto y luego:
- mantenga presionada **Shift**, haga clic derecho en un espacio vacío
  dentro de la carpeta y elija "Abrir ventana de PowerShell aquí" (o
  "Abrir en Terminal"), o
- haga clic en la barra de direcciones, escriba `powershell` y presione
  Enter.

Se abre una ventana azul u oscura — esta es PowerShell, ya "dentro" de la
carpeta del proyecto.

**3. No hace falta que instale Python usted mismo.** El instalador del
paso 4 lo hace: este proyecto necesita Python 3.12 en concreto (las
versiones de paquetes que fija no compilan en versiones más nuevas) y, si
su máquina no lo tiene, el instalador descarga el 3.12 oficial de
python.org — versión exacta, checksum verificado — y lo instala dentro de
su propia carpeta de usuario. Ese paso no pide administrador.

Se instala *al lado* de cualquier otro Python que tenga, no encima. Si hoy
`python --version` muestra 3.13 o 3.14, seguirá mostrando lo mismo
después: su comando `python`, las asociaciones de archivo y el menú Inicio
quedan exactamente como están.

Si prefiere instalarlo usted primero, es lo mismo que hace el instalador:

```powershell
winget install --id Python.Python.3.12 -e --scope user --silent --accept-package-agreements --accept-source-agreements
```

**4. Ejecute el instalador una vez.** Esto instala Python 3.12 si falta,
crea un entorno de Python privado para esta aplicación (fuera de la
carpeta del proyecto, para sobrevivir a un traslado de carpeta o a una
nueva sincronización de Google Drive/OneDrive), instala los paquetes de
Python necesarios, verifica Tesseract y Ghostscript (instalándolos si
faltan y usted acepta) y ofrece crear un acceso directo en el escritorio.

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

Windows puede mostrar un aviso de seguridad la primera vez que ejecute
cualquier script de PowerShell descargado de internet ("Windows protegió
su PC") — esto es normal; la opción `-ExecutionPolicy Bypass` de arriba ya
le indica a PowerShell que ejecute este script de todas formas, sin
cambiar ninguna configuración permanente en su máquina.

Mientras se ejecuta, el instalador muestra su progreso y pide confirmación
antes de instalar cualquier cosa (Tesseract, Ghostscript y, opcionalmente,
Ollama y su modelo predeterminado, que es una descarga grande). Si algún
paso falla, muestra el comando manual que puede ejecutar usted mismo como
alternativa. Esta primera ejecución puede tardar varios minutos, la
mayoría del tiempo descargando paquetes.

**5. Acepte la oferta del acceso directo en el escritorio** al final, si
quiere uno — es la forma más fácil de abrir la aplicación después.

A continuación el instalador ofrece un *segundo* acceso directo, opcional,
llamado "GClaude Indexer (CPU sensor)". Acéptelo solo si quiere ver la
temperatura y el consumo de la CPU en la pantalla de ejecución: esas dos
lecturas requieren privilegios de administrador, así que ese acceso directo
hace que Windows pida administrador cada vez que abre la aplicación. Todo
lo demás — incluidas la temperatura, el consumo y la frecuencia de la GPU —
funciona sin él. Rechazarlo es una respuesta perfectamente válida, y puede
cambiar de idea después ejecutando `install.ps1 -CpuSensorShortcut`.

## Uso diario

Una vez instalado, haga doble clic en el acceso directo del escritorio.
Abre una consola parecida al Símbolo del sistema solo la primera vez (si
el instalador todavía necesita ejecutarse); después de eso, inicia la
aplicación sin ninguna ventana visible y abre su navegador predeterminado
en:

```
http://127.0.0.1:8000
```

El servidor solo escucha en `127.0.0.1` — su propia máquina — y nunca es
accesible desde la red ni desde ninguna otra computadora.

Si prefiere no usar el acceso directo, desde la carpeta del proyecto:

```powershell
python launcher.py
```

Esto hace lo mismo que el instalador — verifica el entorno, instala lo que
falte — antes de iniciar el servidor, así que también funciona como un
comando "simplemente haz que funcione" en una máquina donde todavía no ha
ejecutado el instalador.

Para cerrar la aplicación, cierre la ventana de la terminal que abrió (o,
si se está ejecutando oculta a través del acceso directo, busque
`pythonw.exe` en el Administrador de tareas y finalícelo).

### El sensor de CPU, opcional

Si aceptó el acceso directo "GClaude Indexer (CPU sensor)", abrirlo hace
que Windows pida administrador. Lo que se eleva **no** es la aplicación: es
un proceso auxiliar pequeño cuya única tarea es leer los sensores y
devolver los números. El servidor, la indexación y sus documentos siguen
ejecutándose sin privilegios, y el auxiliar se cierra junto con la
aplicación.

Responder **No** a ese aviso es seguro y no cuesta nada más: el sistema
abre exactamente como lo haría con el acceso directo normal, mostrando la
temperatura, el consumo y la frecuencia de la GPU, y "no medido" en los dos
sensores de la CPU. Nada falla, y no aparece ningún error.

## Desinstalación

Haga doble clic en `Desinstalar.bat`, en la carpeta del proyecto — la misma
del `Indexer.bat`. Desde un símbolo del sistema, cualquiera de los dos:

```powershell
.\Desinstalar.bat
powershell -ExecutionPolicy Bypass -File uninstall.ps1
```

**¿Por qué no simplemente `.\uninstall.ps1`?** Google Drive marca todo
archivo que sincroniza como si viniera de internet, y la política de
ejecución predeterminada de Windows (RemoteSigned) se niega a ejecutar un
`.ps1` de esa zona sin firma digital — "el archivo no está firmado
digitalmente". El script no tiene nada malo: `Desinstalar.bat` solo pasa
`-ExecutionPolicy Bypass` en esa ejecución, que es lo que ya hacen todos
los demás lanzadores de este proyecto. Ejecutar `install.ps1` también quita
esa marca de los scripts de la carpeta, y entonces el comando directo
funciona.

Pregunta por cada elemento por separado, y la respuesta predeterminada es
siempre **no**. Distingue lo que esta instalación considera suyo — el
entorno virtual, los accesos directos, las bibliotecas de sensores, la
configuración local, las entradas de PATH y las variables de entorno que
creó — de los programas comunes que solo instaló para usted: Tesseract,
Ghostscript, Ollama, Python y los modelos descargados de Ollama. Otro
software de su máquina puede estar usándolos, así que cada uno se ofrece
por separado, diciéndolo con claridad.

**Nunca elimina sus proyectos.** Las carpetas de salida, sus bases de
datos, los PDF con OCR y los informes generados son sus documentos, no
restos de instalación. El script indica dónde están, con su tamaño, y
deja la decisión en sus manos.

Tres opciones cubren los usos no interactivos:

```powershell
powershell -ExecutionPolicy Bypass -File uninstall.ps1 -WhatIfOnly        # muestra el plan, no elimina nada
powershell -ExecutionPolicy Bypass -File uninstall.ps1 -KeepDependencies  # conserva Tesseract, Ghostscript, Ollama, Python
powershell -ExecutionPolicy Bypass -File uninstall.ps1 -RemoveAll         # dice sí a todo (menos a sus proyectos)
```

La carpeta del proyecto en sí la sincroniza Google Drive y nunca se toca:
elimínela allí si quiere que desaparezca de todas las computadoras.

## Uso de la aplicación

La interfaz tiene cuatro pantallas, más una página "Acerca de":

1. **Proyectos** — enumera todos los proyectos que ha abierto, con su fecha
   de creación y estado actual. Aquí es donde llega al abrir la
   aplicación. Al final está el **Catálogo compartido**: indíquele una
   carpeta dentro de su Google Drive y toda computadora con el mismo
   Drive verá, abrirá, editará y eliminará los mismos proyectos. Sin él,
   la *lista* de proyectos queda solo en esta máquina aunque los
   proyectos sí se sincronicen — por eso otra computadora mostraría la
   pantalla vacía. Los proyectos guardados en el disco local de otra
   computadora aparecen marcados como fuera de alcance. **Abrir proyecto
   existente**, junto a "Nuevo proyecto", recibe una carpeta que usted
   indica y reabre el proyecto que haya en ella — para una reinstalación,
   una máquina nueva, una carpeta que movió o que alguien le envió. No se
   recrea nada: la carpeta de salida ya guarda el proyecto completo, y se
   usa tal como está.
2. **Nuevo proyecto** — un formulario donde elige una carpeta de origen
   (los documentos), una carpeta de salida (a dónde van los resultados),
   qué tipos de archivo incluir, cómo deben agruparse los documentos y qué
   motor de clasificación usar. Cada campo ya tiene un valor por defecto
   sensato y una pista "?" junto a su etiqueta.
3. **Ejecución** — una fila por paso de procesamiento (escaneo,
   conversión, extracción por página, preparación de ventanas,
   clasificación), cada una con un botón "ejecutar este paso", una barra
   de progreso con una estimación de tiempo, y un botón de pausa. Debajo
   se muestran un registro en vivo y un gráfico de uso de CPU/RAM/GPU. Un
   botón aparte, "Importar y generar informes", ejecuta los dos últimos
   pasos (convirtiendo los elementos clasificados en los cuatro archivos
   de salida) una vez que termina la clasificación.
4. **Resultado** — una vista previa de los cuatro archivos generados, un
   botón para abrir la carpeta de salida directamente en el Explorador de
   archivos, un informe de lo que sigue pendiente, y un botón para
   liberar espacio en disco eliminando los archivos intermedios (los PDF
   con OCR y los fragmentos de texto) una vez que esté satisfecho con el
   resultado — la base de datos, los cuatro informes y los registros nunca
   se ven afectados por esto.

Un selector de idioma y un selector de tema (cuatro temas de color) están
en el encabezado de cada pantalla; ambas elecciones se recuerdan en su
navegador entre visitas.

## Obtener una buena clasificación

Dos campos deciden más sobre el resultado que cualquier otra cosa, y ambos
son fáciles de pasar por alto porque nada le obliga a pensarlos.

**Complete el Asunto y el Tipo de acervo en el formulario de Nuevo
proyecto.** No son adorno: el motor `local` los muestra al modelo, y son los
que le dicen *qué tipo de documento está leyendo*. Un acervo de material
didáctico descrito solo con los valores por defecto termina clasificado
contra ejemplos genéricos, y el modelo responde correctamente "no sé" para
casi todos los tipos. Escribir una frase sobre el acervo — qué es, de dónde
viene, qué documentos tiene — es lo más eficaz que puede hacer por el
resultado. Las "Instrucciones de rol" y las "Reglas adicionales" también se
transmiten, como contexto sobre el acervo.

**Qué modelo usar.** Medido en este proyecto, sobre las mismas ventanas de
un documento de 31 páginas, con todos los modelos ejecutándose enteramente
en una placa de 8 GB:

| Modelo | Tamaño | Tipo completado | s/ventana |
|---|---:|---:|---:|
| **`qwen3.5:4b`** | **3,0 GB** | **100%** | **30,8** |
| `gemma4:e4b` | 3,1 GB | 79,5% | 38,5 |
| `qwen3.5:9b` | 5,3 GB | 79,5% | 86,2 |
| `qwen3:8b` | 5,4 GB | 100% | 108,8 |
| `granite4.2:8b` | 5,7 GB | 100% | 116,9 |

`qwen3.5:4b` alcanza la misma calidad que el mejor de ellos en un cuarto del
tiempo y con la mitad de la VRAM, y cabe en una placa de 6 GB tan holgado
como en una de 8 GB. El modelo mayor de la misma familia perdió ante el
menor: describir una página es lectura y disciplina de formato, no
razonamiento profundo.

**Elija un modelo que quepa en su placa de video.** Lo que no cabe en la
VRAM, Ollama lo ejecuta en la CPU, y la diferencia no es sutil. En la
máquina donde se midió esto — placa de 8 GB — un modelo de 9,1 GB se
ejecutó con el 17% de sí mismo en la GPU; uno de 5 GB se ejecutó entero en
la GPU. La pantalla de Ejecución muestra la VRAM de su placa, la pantalla
"Acerca de" lista los modelos instalados, y el registro avisa cuando el
modelo elegido no cabe. Más pequeño suele ser el intercambio correcto.

Si la nota de calidad parece baja, abra el registro: ahora informa cómo se
está usando la GPU y, en la pantalla de Resultado, la nota viene desglosada
en confianza, completitud de campos y penalizaciones.

### Ventanas, bloques y OCR

**Páginas por ventana** es el campo que decide la calidad: es cuántas
páginas van en cada pedido al modelo, y él responde con una línea por
página. **8 es el valor recomendado.** Con 16, solo la respuesta supera los
3.500 tokens y empieza a truncarse — fue la causa de todos los malos
resultados medidos durante el ajuste. Con 4 se triplican los pedidos sin
ganancia.

**Páginas por bloque** *no* afecta al índice. Solo corta PDF muy grandes en
archivos auxiliares dentro de `salida/blocks/`, que nada más lee y que el
botón "liberar espacio" borra. Déjelo en 80.

**OCR** solo se aplica a PDF sin capa de texto — el sistema lo detecta por
archivo y lo omite cuando el texto ya existe.

## Motores de clasificación

La clasificación — decidir qué es cada página, quién la escribió y cuándo —
es el único paso de todo el flujo en el que usted elige *cómo* se hace el
trabajo. Todo lo demás en el flujo (escaneo, OCR, extracción, generación de
informes) es idéntico sin importar qué motor elija aquí.

| Motor | Costo | ¿Sale de la máquina? | Necesita |
|---|---|---|---|
| `rules` | gratis | no | nada — funciona en cualquier máquina Windows |
| `local` | gratis | no | Ollama, instalado automáticamente; más rápido con GPU, funciona sin ella |
| `claude_code` | su suscripción existente de Claude Code | **sí** | Claude Code ya instalado en esta máquina |
| `automatic` | — | — | elige `local` si el hardware lo permite, si no recurre a `rules`; nunca elige `claude_code` por su cuenta |

**`claude_code` es completamente opcional.** GClaude Indexer funciona de
principio a fin sin él, usando `rules` o `local` — ninguno de los dos
necesita nada más allá de lo que ya prepara el instalador. Elija
`claude_code` solo si ya usa Claude Code y quiere específicamente que la
clasificación se haga a través de él; en ese caso, la aplicación prepara
los archivos y le muestra un comando para pegar en Claude Code, y luego
importa el resultado en cuanto Claude Code termina.

`rules` es un motor determinista — busca marcadores conocidos de tipo de
documento, patrones de fecha y bloques de firma, sin ningún modelo de
aprendizaje automático involucrado, así que su salida es totalmente
reproducible y no necesita ninguna instalación. `local` usa un modelo
abierto servido por [Ollama](https://ollama.com) en su propia máquina
(`http://127.0.0.1:11434`, nunca una dirección remota) y por lo general
produce mejores resultados que `rules`, a costa del espacio en disco, la
descarga y (opcionalmente) la GPU listados en [Requisitos](#requisitos).

Una opción "revisar elementos de confianza baja" también está disponible
en el formulario de Nuevo proyecto: ejecuta `rules` sobre todo, y después
vuelve a procesar solo los elementos de confianza baja con un segundo
motor de su elección — un punto medio entre el costo cero de `rules` y la
mejor precisión de un motor más caro, solo en las páginas que realmente lo
necesitan.

## Archivos de salida

Escritos en la carpeta de salida que eligió, siempre en el idioma en el
que esté la interfaz en el momento en que los genere:

- `index.md` — un catálogo de cada elemento clasificado, con su origen,
  tipo, fecha, autor y resumen.
- `timeline.md` — los elementos con fecha en orden cronológico.
- `review.md` — un informe de cobertura: vacíos, fallos, lo que sigue
  pendiente.
- `project_instructions.md` — instrucciones listas para pegar en un nuevo
  proyecto de Claude, construidas a partir de una plantilla con los campos
  que completó en el formulario de Nuevo proyecto.

La pantalla Resultado también ofrece un paquete `.zip` que contiene estos
cuatro archivos más una guía breve, del tamaño adecuado para pegar
directamente en un proyecto nuevo de Claude.

## OCR e idioma de los documentos

El OCR de Tesseract usa portugués (`por`) por defecto en los proyectos
nuevos, ya que este proyecto nació para colecciones documentales en
portugués de Brasil.

El paquete de Tesseract para Windows trae solo `eng` y `osd`, así que
`install.ps1` descarga e instala el idioma para el que el proyecto está
configurado (`por`, por defecto) en la carpeta `tessdata` de Tesseract. Pide
elevación a Windows solo para esa copia de archivo, y verifica el SHA-256
antes de instalarlo.

Si su colección está en otro idioma, cambie el campo "Idioma del OCR" en el
formulario de Nuevo proyecto al código de idioma de Tesseract correspondiente
(por ejemplo, `eng` para inglés o `spa` para español) e instale el paquete de
datos de ese idioma ejecutando el instalador con el código que necesita:

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1 -OcrLanguage spa
```

El instalador solo instala idiomas cuyo SHA-256 tiene fijado — hoy `por`,
`eng`, `spa` y `osd`. Nunca descarga un archivo que no puede verificar; para
cualquier otro idioma muestra dónde conseguirlo y dónde ponerlo, y continúa.

## Ejecutar la suite de pruebas

Si está contribuyendo cambios, o solo quiere confirmar que todo funciona
después de instalar, usando el intérprete de Python dentro del entorno que
creó el instalador (no el `python` que resuelva su `PATH` por su cuenta —
vea [Requisitos](#requisitos)):

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -B -m pytest -q
```

Una ejecución correcta termina con una línea como:

```
317 passed, 6 warnings in 147.01s (0:02:27)
```

(El número de avisos puede variar ligeramente según la máquina; provienen
de bibliotecas de terceros, no del código propio de este proyecto.) Vea
[CONTRIBUTING.md](../CONTRIBUTING.md) (en inglés; vea también
[CONTRIBUTING.es.md](CONTRIBUTING.es.md)) para la configuración completa
de un entorno de desarrollo.

## Solución de problemas

- **Aparece un aviso de que el sistema se actualizó después de abrir la
  ventana.** El código en disco cambió mientras este servidor se ejecutaba, y
  Python carga los módulos una sola vez, al arrancar. Cierre el sistema y
  ábralo de nuevo con el acceso directo.
- **El navegador se abre pero la página nunca carga.** Espere unos
  segundos — el servidor puede tardar un momento en iniciar en la primera
  ejecución. Si sigue sin cargar, compruebe si otro programa ya está
  usando el puerto 8000.
- **"python no se reconoce…" en PowerShell.** Python no está en el `PATH`
  de su sistema. Reinstálelo con el comando `winget` en
  [Instalación](#instalación-primera-vez-en-una-máquina) e inténtelo de
  nuevo, o use la ruta completa al intérprete, como se muestra en
  [Ejecutar la suite de pruebas](#ejecutar-la-suite-de-pruebas).
- **El OCR falla o no produce texto.** Confirme que Tesseract y
  Ghostscript están instalados (`install.ps1` lo verifica
  automáticamente) y que el paquete de idioma correspondiente a sus
  documentos está instalado — vea
  [OCR e idioma de los documentos](#ocr-e-idioma-de-los-documentos).
- **El motor `local` recurre a `rules` con un aviso de memoria.** La suma
  de su VRAM de GPU y la RAM del sistema está por debajo de lo que
  necesita el modelo local — vea [Requisitos](#requisitos). Esto no es un
  error: la aplicación se degrada a propósito en lugar de fallar
  directamente.
- **Nada funciona hasta que reinicio después de instalar.** Esto se
  corrigió: el instalador ahora anota dónde puso cada programa y el
  `Indexer.bat` recarga el PATH desde el registro, de modo que ninguno de
  los dos depende de que el Explorador de Windows note el cambio. Si le
  ocurre en una instalación antigua, ejecute `install.ps1` una vez más —
  ya no hace falta cerrar la sesión.
- **Reinstalé (o formateé) y mis proyectos desaparecieron de la lista.**
  No desaparecieron — los proyectos están en sus carpetas de salida; lo
  que se recreó vacío fue la lista. Use **Proyectos → Abrir proyecto
  existente** e indique la carpeta de salida de un proyecto; se reabre con
  su configuración y con todo lo ya procesado. Nunca apunte "Nuevo
  proyecto" a una carpeta que ya tiene un proyecto: la aplicación ahora lo
  impide, pero la intención allí es *abrir*, no crear.
- **Mis proyectos no aparecen en la otra computadora.** Los proyectos se
  sincronizan por Drive, pero la lista es por máquina hasta que configure
  un catálogo compartido. Abra **Proyectos → Catálogo compartido**, elija
  una carpeta dentro de su Drive y guarde — en ambas computadoras,
  apuntando a la misma carpeta. Sus proyectos actuales se copian allí
  automáticamente.
- **Abrir el mismo proyecto en una segunda máquina justo después de la
  primera.** Espere a que Google Drive (o lo que sea que sincronice su
  carpeta de salida) termine de sincronizar antes de abrirlo en otro
  lugar — la aplicación detecta y avisa sobre sincronizaciones
  incompletas y sobre el bloqueo activo de otra máquina, pero no sustituye
  el hecho de esperar.

## Documentación

- [CONTRIBUTING.es.md](CONTRIBUTING.es.md) — configuración del entorno de
  desarrollo, cómo ejecutar una sola prueba, y las convenciones del
  proyecto.
- [SPECIFICATION.md](SPECIFICATION.md) — la especificación técnica
  completa, en inglés: modelo de datos, cada paso del procesamiento,
  reglas de seguridad y decisiones de diseño, con más detalle que este
  archivo.
- [CHANGELOG.md](../CHANGELOG.md) — qué cambió, versión por versión (en
  inglés, convención del formato).
- [SECURITY.md](../SECURITY.md) — cómo reportar una vulnerabilidad (en
  inglés).
- [CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md) — normas de convivencia para
  quienes contribuyen (en inglés).

## Licencia

GClaude Indexer está licenciado bajo la **GNU General Public License v3.0**
(GPL-3.0) — vea [LICENSE](../LICENSE) para el texto completo. En resumen:
usted es libre de usar, estudiar, modificar y redistribuir este software,
incluso comercialmente, pero cualquier versión modificada que distribuya
también debe licenciarse bajo la GPL-3.0, con su código fuente disponible.
No hay garantía de ningún tipo.
