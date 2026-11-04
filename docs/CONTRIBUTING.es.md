*Lea esto en otros idiomas: [English](../CONTRIBUTING.md) (original) · [Português (Brasil)](CONTRIBUTING.pt-BR.md)*

# Contribuir a GClaude Indexer

Gracias por considerar una contribución. Este documento explica cómo preparar un entorno de desarrollo, ejecutar la suite de pruebas y las convenciones de las que depende el código. La documentación para quien usa el programa es el [README](README.es.md); la referencia técnica es [docs/TECHNICAL.es.md](TECHNICAL.es.md).

## Solo Windows

GClaude Indexer funciona **solo en Windows**. No es una laguna de portabilidad que corregir de paso: el código habla a propósito con interfaces específicas de Windows. PowerShell (instalador y lanzadores), WMI (sensores de hardware y de recursos), el registro de Windows (idioma de la interfaz) y Performance Counters (los gráficos de CPU y GPU). Las contribuciones que agreguen capas de abstracción multiplataforma sin una necesidad concreta están fuera del alcance; las que corrijan un defecto real en Windows, o extiendan una función específica de Windows, son muy bienvenidas.

## No necesita Claude Code

El nombre del proyecto menciona a Claude, pero **Claude Code es opcional**, tanto para usar el programa como para contribuir. La clasificación de las piezas la hace uno de tres motores intercambiables (más un modo `automatic`, que elige entre los dos primeros según el hardware de la máquina):

- `rules`: determinista, no exige ninguna herramienta externa.
- `local`: usa un modelo de Ollama que corre localmente.
- `claude_code`: delega la clasificación a Claude Code, para quien ya lo tiene instalado.

Los motores `rules` y `local` bastan para ejecutar el flujo completo y trabajar en casi todo este repositorio. Solo necesita Claude Code si está tocando `gclaude_indexer/engine_claude_code.py` o `gclaude_indexer/claude_package.py`, y aun así la suite de pruebas simula la llamada al subproceso. No hace falta tener Claude Code instalado para ejecutar las pruebas.

## Preparar el entorno

1. Instale Python 3.12. El entorno **no** puede quedar en una carpeta sincronizada por Google Drive, OneDrive o similar: el bloqueo de archivos durante la sincronización rompe SQLite y los virtualenvs. La convención del proyecto es un venv en `%LOCALAPPDATA%\GClaudeIndexer\venv`.

   ```powershell
   py -3.12 -m venv "$env:LOCALAPPDATA\GClaudeIndexer\venv"
   ```

2. Instale las dependencias:

   ```powershell
   & "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pip install -r requirements.txt
   ```

3. O ejecute el script de instalación, que hace lo mismo y además comprueba Tesseract y Ghostscript, descarga las bibliotecas de sensores y ofrece un acceso directo en el escritorio:

   ```powershell
   powershell -ExecutionPolicy Bypass -File install.ps1
   ```

## Ejecutar las pruebas

Use siempre el intérprete del venv, no el `python` que encuentre el `PATH` (un Python más nuevo rompe las versiones fijadas de las dependencias):

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -B -m pytest -q
```

La suite tiene que pasar completa antes y después de su cambio; tarda unos cinco minutos y nunca habla con un Ollama real ni con la red. Para trabajar en un solo archivo de pruebas durante el desarrollo:

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -B -m pytest tests/test_algo.py -v
```

La suite escribe los datos de idioma del OCR que necesita en la carpeta real `%LOCALAPPDATA%\GClaudeIndexer\tessdata` de la máquina; nada más fuera de las carpetas temporales se toca.

El trabajo se confirma por tarea, un commit por cambio cerrado, en `main`. GitHub Actions ejecuta la suite e indexa el acervo de demostración (`demo/acervo`) en cada push, adjuntando el informe de acierto a la ejecución.

## Convenciones

### Todo texto de la interfaz pasa por i18n, en los tres idiomas

Toda cadena que una persona ve en la interfaz web tiene que ser una clave de traducción resuelta por `gclaude_indexer/i18n.py`, con entrada en las **tres** tablas de idioma: `pt`, `en`, `es`. Una clave presente en un solo idioma cae al valor por defecto en silencio y reintroduce una fuga de idioma, que ya fue una clase recurrente de defecto en este proyecto. Al agregar una cadena nueva, agréguela a los tres diccionarios en el mismo cambio. Una prueba comprueba que las tres tablas tienen las mismas claves y los mismos marcadores.

### La lógica devuelve claves ASCII estables; la plantilla traduce

La lógica de negocio (rutas, tareas en segundo plano, cálculo de estado) nunca devuelve texto de idioma ni identificadores acentuados. Devuelve una clave estable, ASCII, en minúsculas (por ejemplo `"done"`, `"scan"`, `"failed"`), con una sola función: identificar un estado. Esa clave se usa, sin cambios, como índice en `i18n.py` para el texto de la pantalla y como nombre de clase CSS cuando corresponde.

No deje que un solo valor sirva a la vez de texto mostrado, clase CSS y valor de comparación. Esa sobrecarga fue la causa de varios defectos de interfaz corregidos en la fase 12 (un estado acentuado que era clase CSS y, al mismo tiempo, el valor comparado para decidir el siguiente paso). Al agregar un estado nuevo, cree primero la clave ASCII y después las tres traducciones.

### Los renombres y traducciones son mecánicos

El código (identificadores, comentarios, docstrings, esquema de la base) está en inglés; esa migración está terminada. Si todavía encuentra un identificador en portugués, traducirlo es bienvenido; mantenga el cambio mecánico: mismo comportamiento, mismas pruebas (ajustadas solo donde afirman sobre el identificador renombrado). No mezcle una mejora de lógica en el mismo cambio. Mezclar refactorización con renombres masivos es como las regresiones se esconden en un diff que de otro modo sería revisable.

### Los comentarios dicen por qué, con números y fechas

Un comentario que explica una decisión no obvia dice qué se midió, dónde y cuándo ("flash attention duplicó el tiempo de lectura del prompt en la RX 6700 XT vía Vulkan, 02/11/2026"). Quien lea dos versiones después puede medir de nuevo en vez de adivinar si el motivo sigue valiendo.

### El proyecto es offline

Ninguna llamada de red en tiempo de ejecución, salvo a `http://127.0.0.1:11434` (el Ollama local, siempre loopback, nunca configurable hacia un servidor remoto) y el servicio de búsqueda de LexML (en la pantalla, solo con la casilla marcada; en `buscar.bat`, también cuando ninguna norma del acervo cita el término), que envía solo el término escrito y nunca nada del acervo. No agregue dependencias que necesiten red para funcionar. El prompt del clasificador, el vocabulario de las reglas y el lector del Planalto son perillas de comportamiento: cambiarlos exige una nueva medición contra `demo/gabarito.csv` y la actualización de `docs/QUALITY.md`.

### La documentación se lee como escrita por una persona

README, manual y documentos técnicos siguen la misma regla en los tres idiomas: ninguna raya ni semirraya como inciso, comillas rectas, tres puntos en vez del carácter de puntos suspensivos, ningún vocabulario inflado, ningún "no es X, es Y". Una prueba en `tests/test_phase38_docs.py` falla en la primera violación.

## Generar el instalador de Windows

El instalador es un script de Inno Setup, `installer/GClaudeIndexer.iss`, generado por `installer/build.ps1` con Inno Setup 6 (`ISCC.exe`, buscado en `Program Files` o en `%LOCALAPPDATA%\Programs`). Lee la versión de `SYSTEM_VERSION` en `gclaude_indexer/web/app.py` y escribe `dist/GClaude-Indexer-Setup-<versión>.exe`. El paquete lleva el código, la documentación e `install.ps1`; al instalar ejecuta `install.ps1` con los componentes que la persona marcó. Lo que el instalador incluye y lo que descarga en el momento:

- **Python 3.12.** Las versiones fijadas en `requirements.txt` no se instalan en intérpretes más nuevos, así que `install.ps1` busca la 3.12 y, cuando la máquina no la tiene, descarga la 3.12.10 oficial para el usuario actual (versión exacta, checksum comprobado), sin administrador y sin tocar ningún otro Python.
- **Tesseract OCR y Ghostscript.** Descargados de las URLs oficiales de release, versión fijada y hash comprobado. El instalador de Ghostscript no corre sin interacción (`requireAdministrator`, y `/S` dejó de silenciarlo en la 10.01.0), así que `install.ps1` desempaqueta el contenido en vez de ejecutarlo. Los datos de idioma del OCR (`por`, `eng`, `spa`, `osd`, cada uno con SHA-256 fijado) van a `%LOCALAPPDATA%\GClaudeIndexer\tessdata` cuando la carpeta de Tesseract exige administrador.
- **Las bibliotecas de sensores.** `LibreHardwareMonitorLib.dll`, `HidSharp.dll` y las cinco DLL de compatibilidad de .NET que necesitan (el layout exacto está en `gclaude_indexer/install_diagnostics.py`), copiadas a `%LOCALAPPDATA%\GClaudeIndexer\lib\`. El controlador opcional PawnIO, para temperatura y consumo de la CPU en procesadores recientes, es un componente aparte que pide administrador.
- **Ollama y el modelo** siguen siendo una descarga opcional y separada: solo el modelo pesa varios gigabytes, y la persona tiene que poder rechazarlo sin rechazar el resto. El instalador también escribe las variables de entorno del usuario que el servidor de Ollama necesita (`OLLAMA_*` y `LLAMA_ARG_CACHE_RAM`; vea `docs/TECHNICAL.es.md`, "Uso diario") y respeta un valor que la persona haya definido a mano.
- **Accesos directos.** El acceso directo del escritorio ejecuta `Indexer.vbs` (sin ventana de consola); el acceso directo opcional "CPU sensor" pide administrador al abrir, solo para el lector de sensores.

Instalar una versión nueva sobre una antigua cierra el servidor que esté corriendo; el desinstalador pregunta, elemento por elemento, qué programas compartidos quitar, y nunca toca los proyectos de la persona.

## Estilo de código

- Python 3.12, sin formateador externo obligatorio; siga el estilo del archivo alrededor.
- `from __future__ import annotations` al inicio de los módulos que ya lo usan (después del encabezado de licencia y del docstring del módulo).
- Todo `.py` en `gclaude_indexer/` lleva un encabezado corto de la GPL al inicio (vea cualquier archivo existente para el texto exacto). Agréguelo también a los archivos nuevos.

## Licencia

Al contribuir, usted acepta que su contribución queda licenciada bajo la GNU General Public License v3.0, la misma licencia que el resto del proyecto (vea `LICENSE`).
