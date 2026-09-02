*Lea esto en otros idiomas: [English](../CONTRIBUTING.md) · [Português (Brasil)](CONTRIBUTING.pt-BR.md)*

# Cómo contribuir a GClaude Indexer

Gracias por considerar una contribución. Este documento explica cómo
preparar un entorno de desarrollo, ejecutar la suite de pruebas y las
convenciones que sigue el código.

## Solo funciona en Windows

GClaude Indexer funciona **solo en Windows**. No es una brecha de
portabilidad por corregir de forma incidental: el código habla
deliberadamente con superficies específicas de Windows: PowerShell
(scripts de instalación y arranque), WMI (sensores de hardware y
recursos) y el registro de Windows (detección de idioma/configuración
regional). Las contribuciones que agreguen una capa de abstracción
multiplataforma sin una necesidad concreta quedan fuera de alcance; las
que corrijan un error real de Windows, o amplíen funcionalidad específica
de Windows, son muy bienvenidas.

## No necesita Claude Code

El nombre del proyecto menciona Claude, pero **Claude Code es opcional**,
tanto para usar el software como para contribuir con él. La clasificación
de los elementos de la colección la realiza uno de tres motores
intercambiables (más un modo `automatic`, que elige entre los dos primeros
según el hardware de la máquina):

- `rules` — determinista, no requiere ninguna herramienta externa.
- `local` — usa un modelo de Ollama ejecutado localmente.
- `claude_code` — delega la clasificación a Claude Code, para quienes ya
  lo tienen instalado.

Los motores `rules` y `local` bastan para ejecutar el flujo completo, de
principio a fin, y para trabajar en casi cualquier parte de este
repositorio. Solo necesita Claude Code si está trabajando específicamente
en `gclaude_indexer/engine_claude_code.py` o
`gclaude_indexer/claude_package.py` — e incluso entonces la suite de
pruebas simula la llamada al subproceso: no necesita tener Claude Code
instalado para ejecutar las pruebas.

## Preparar el entorno

1. Instale Python 3.12. El entorno **no puede** vivir dentro de una carpeta
   sincronizada por Google Drive/OneDrive/etc. — el bloqueo de archivos
   durante la sincronización rompe SQLite y los entornos virtuales. La
   convención de este proyecto es un venv en
   `%LOCALAPPDATA%\GClaudeIndexer\venv`.

   ```powershell
   py -3.12 -m venv "$env:LOCALAPPDATA\GClaudeIndexer\venv"
   ```

2. Instale las dependencias:

   ```powershell
   & "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pip install -r requirements.txt
   ```

3. Alternativa: ejecute el script instalador, que hace lo anterior y
   además verifica Tesseract/Ghostscript y ofrece crear un acceso directo
   en el escritorio:

   ```powershell
   powershell -ExecutionPolicy Bypass -File install.ps1
   ```

## Ejecutar las pruebas

Use siempre el intérprete del venv, nunca el `python` que resuelva el
`PATH` por su cuenta (un Python más nuevo y sin versión fijada rompe las
versiones fijadas de las dependencias):

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -B -m pytest -q
```

La suite debe pasar por completo antes y después de su cambio. Si está
trabajando en un solo archivo de pruebas durante el desarrollo:

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -B -m pytest tests/test_something.py -v
```

El proyecto no usa repositorio git por el momento; donde un flujo normal
pediría un commit en cada paso, ejecute la suite completa en su lugar.

## Convenciones

### Todo el texto de la interfaz pasa por i18n, en los tres idiomas

Toda cadena que el usuario ve en la interfaz web debe ser una clave de
traducción resuelta por `gclaude_indexer/web/i18n.py`, con una entrada en
las **tres** tablas de idioma: `pt`, `en`, `es`. Una clave presente en un
solo idioma cae al valor por defecto en silencio y reintroduce una fuga de
idioma — ya ha sido una clase de error recurrente en este proyecto. Al
agregar una cadena nueva visible para el usuario, agréguela a los tres
diccionarios en el mismo cambio.

### La lógica devuelve claves estables en ASCII; la plantilla traduce

La lógica de negocio (rutas, tareas en segundo plano, cálculo de estado)
nunca debe devolver texto en un idioma específico ni un identificador
acentuado. Devuelve una clave estable, en ASCII, en minúsculas (p. ej.
`"done"`, `"scan"`, `"failed"`), con un único propósito: identificar un
estado. Esa clave se usa después, sin modificar, como:

- la búsqueda en `i18n.py` para el texto mostrado en pantalla, y
- el nombre de la clase CSS, cuando corresponde.

No permita que un mismo valor sirva a la vez de texto mostrado, clase CSS
y valor de comparación — esa sobrecarga causó varios defectos de interfaz
corregidos en la fase 12 (una cadena de estado acentuada que servía a la
vez de clase CSS y de valor comparado para decidir qué paso se ejecuta a
continuación). Si agrega un estado nuevo, cree primero la clave en ASCII y
después las tres traducciones.

### Los renombrados y las traducciones son mecánicos

El código (identificadores, comentarios, docstrings, esquema de la base de
datos) está hoy completamente en inglés — esa migración está terminada.
Si aún encuentra algún identificador olvidado en portugués, traducirlo es
bienvenido; mantenga el cambio mecánico: mismo comportamiento, mismas
pruebas (ajustadas solo donde comprueban un identificador o texto
renombrado). No combine una mejora de lógica en el mismo cambio: mezclar
refactorización con renombrado masivo es la forma en que una regresión se
esconde en un diff que, de otro modo, sería fácil de revisar.

### El proyecto es offline

Ninguna llamada de red en tiempo de ejecución, salvo a
`http://127.0.0.1:11434` (la instancia local de Ollama, siempre loopback,
nunca configurable hacia un host remoto). No agregue una dependencia que
requiera acceso a la red para funcionar.

## Estilo de código

- Python 3.12, sin formateador externo obligatorio todavía; siga el
  estilo del archivo en el que esté trabajando.
- `from __future__ import annotations` al inicio de los módulos que ya lo
  usan (después del encabezado de licencia y del docstring del módulo).
- Todo archivo `.py` dentro de `gclaude_indexer/` lleva un encabezado GPL
  breve al inicio (vea cualquier archivo existente para el texto exacto).
  Agréguelo también en los archivos nuevos.

## Licencia

Al contribuir, usted acepta que su contribución se licencia bajo la GNU
General Public License v3.0, la misma licencia del resto del proyecto
(vea `LICENSE`).
