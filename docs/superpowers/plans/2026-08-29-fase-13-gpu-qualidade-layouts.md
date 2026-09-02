# Fase 13 — GPU, Qualidade e Layouts: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer o sistema se instalar sozinho em qualquer computador, aproveitando o hardware que encontrar; monitorar a máquina inteira independentemente do fabricante da GPU; e permitir comparar motores e modelos por **tempo e qualidade**, com quatro layouts de interface genuinamente distintos.

**Princípio que atravessa a fase — "extrair o máximo do hardware disponível":**

| Etapa | Recurso que a limita | O que a acelera |
|---|---|---|
| Varredura | disco (hash de cada arquivo) | pouco a ganhar; I/O é o teto |
| **Conversão + OCR** | **CPU, hoje 1 núcleo de N** | **paralelismo (Tarefa 14) — o maior ganho da fase** |
| Extração | CPU e I/O | paralelismo (Tarefa 14) |
| Fatiamento / janelas | texto e SQLite | pouco a ganhar |
| **Classificação** | **GPU** | já usa 100% da GPU via Ollama |

GPU não acelera as quatro primeiras: não há cálculo paralelizável nelas. O que acelera é usar os núcleos que estão parados.

**Architecture:** Três frentes independentes. (1) **Telemetria**: um módulo novo por fonte de dado — `contadores_windows.py` (uso de GPU, VRAM e clocks via Performance Counters, agnóstico de fabricante) e `sensores.py` (temperatura e potência via LibreHardwareMonitor, com degradação explícita). (2) **Qualidade**: `modelo_para_usar` passa a respeitar a escolha do usuário — sem isso não há o que comparar — e um módulo `qualidade.py` resume cada execução a partir do que o banco já grava. (3) **Layouts**: um atributo `data-layout` no `<html>`, com quatro folhas de estilo estruturais sobre o mesmo conjunto de templates.

**Tech Stack:** Python 3.12, FastAPI 0.115, Jinja2 3.1, HTMX (vendorizado), SQLite, pytest 8.3, Windows Performance Counters (PDH), LibreHardwareMonitorLib (.NET, via pythonnet).

**Spec:** `ESPECIFICACAO.md` (seções 5 = motores, 6 = interface, 10.2 = hardware, 10.3 = dependências externas).

## Global Constraints

- **Python 3.12**, venv em `%LOCALAPPDATA%\GClaudeIndexer\venv`. Interpretador dos testes: `%LOCALAPPDATA%\GClaudeIndexer\venv\Scripts\python.exe`.
- **Sem framework de front-end e sem build de JavaScript.** Único script vendorizado: `static/htmx.min.js`. JS novo vai inline.
- **O sistema é OFFLINE.** Nenhuma requisição a host externo, em nenhuma circunstância — isso **inclui Google Fonts**. Os layouts usam apenas fontes já presentes no Windows.
- **Três idiomas obrigatórios**: `pt`, `en`, `es`. Toda chave nova entra nos três dicionários de `_TRADUCOES`. Existe teste de paridade (`test_os_tres_idiomas_tem_exatamente_as_mesmas_chaves`) que falha se você esquecer um.
- **Código e identificadores em português.**
- **A lógica devolve chaves ASCII estáveis; o template traduz.** Regra criada na Fase 12 (`estado_etapas.py`) depois de um defeito em que a mesma string servia de texto, classe CSS e valor de comparação. Não reintroduza o padrão antigo.
- **O projeto NÃO é um repositório git.** Onde o fluxo TDD pediria commit, rode a suíte inteira.
- **Baseline: 220 testes passando.** Nenhuma tarefa termina com regressão.
- **Comando de teste:** `& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest -q`
- **Arquivo de testes desta fase:** `tests/test_fase13.py`, criado na Tarefa 1. Segue o padrão de `tests/test_fase12.py`.
- **Nenhuma métrica pode ser inventada.** Quando um dado não estiver disponível (sensor ausente, sem privilégio, contador inexistente), o valor é `None` e a interface diz que não está disponível. **Nunca zero no lugar de desconhecido** — foi o erro que gerou "sem GPU NVIDIA detectada" numa máquina com GPU AMD funcionando.

---

## Fatos verificados nesta máquina (não reinvestigue)

Medidos antes de escrever este plano, no interpretador e no PowerShell do projeto:

| Fato | Situação |
|---|---|
| Ollama na GPU AMD | **Já funciona.** `gemma4:e4b` carrega com `100% GPU` via **Vulkan**, com `HSA_OVERRIDE_GFX_VERSION=10.3.0`. **Não instale ROCm nem mexa na configuração do Ollama.** |
| `\GPU Engine(*)\Utilization Percentage` | **Funciona** — 12,3% medidos na Radeon. Agnóstico de fabricante. |
| `\GPU Adapter Memory(*)\Dedicated Usage` | **Funciona** — 5017 MB medidos. |
| Clock de memória | **Funciona** via `Win32_PhysicalMemory.ConfiguredClockSpeed` (3600 MHz). |
| Clock de CPU em tempo real | **Funciona**, mas o nome do contador é **localizado** (`\Informações do Processador(_Total)\Frequência do Processador` nesta máquina). Use **índices numéricos**, não nomes. |
| `MSAcpi_ThermalZoneTemperature` | **Falha** nesta máquina ("Não há suporte à operação solicitada"). Não é caminho viável. |
| .NET 8 e .NET Framework 4.8 | Presentes. |
| pythonnet | **Não instalado** no venv. |
| Sessão como administrador | **Não.** LibreHardwareMonitor exige elevação para ler sensores. |
| OCR/fatiamento/extração em **GPU** | **Inaplicável.** Tesseract é CPU-only; as demais etapas são I/O e texto. Nenhuma tarefa tenta isso. |
| OCR/conversão/extração em **paralelo** | **Aplicável e é o maior ganho de tempo disponível.** `conversao.py:288` e `extracao.py:122` processam um arquivo por vez, e `_rodar_ocrmypdf` chama o `ocrmypdf` **sem `--jobs`** — 1 thread. Esta máquina tem 16 núcleos lógicos / 8 físicos. Ver Tarefa 14. |
| Medição de tempo por etapa | **Não existe.** Sem ela não há benchmark possível. Ver Tarefa 15. |
| Instalação em máquina nova | `instalar.ps1` hoje **só avisa** quando Tesseract/Ghostscript faltam, e não conhece Ollama nem runtime de GPU. Ver Tarefa 13. |

---

## File Structure

| Arquivo | Responsabilidade | Tarefas |
|---|---|---|
| `gclaude_indexer/contadores_windows.py` | **(novo)** Performance Counters por índice numérico: uso de GPU, VRAM, clocks | 1, 2 |
| `gclaude_indexer/sensores.py` | **(novo)** Temperatura e potência via LibreHardwareMonitor, com degradação | 3 |
| `gclaude_indexer/recursos.py` | Amostragem; passa a compor as fontes acima | 1, 2, 3, 4 |
| `gclaude_indexer/qualidade.py` | **(novo)** Resumo de qualidade de uma execução | 9 |
| `gclaude_indexer/motor_local.py` | `modelo_para_usar` passa a respeitar a escolha | 8 |
| `gclaude_indexer/config.py`, `classificacao.py`, `orquestrador.py` | Remoção do `openrouter` | 6 |
| `gclaude_indexer/varredura.py` | Correção do denominador com duplicatas | 10 |
| `gclaude_indexer/web/app.py` | Rotas e contexto | 4, 5, 6, 8, 9, 11 |
| `gclaude_indexer/web/layout.py` | **(novo)** Catálogo de layouts, espelhando `tema.py` | 11 |
| `gclaude_indexer/web/static/estilo.css` | Tokens e regras base | 4, 11 |
| `gclaude_indexer/web/static/layouts.css` | **(novo)** As quatro identidades estruturais | 11, 12 |
| `gclaude_indexer/web/templates/*.html` | Telas | 4, 5, 7, 9, 11 |
| `gclaude_indexer/web/i18n.py` | pt/en/es | quase todas |
| `tests/test_fase13.py` | **(novo)** | todas |

---

### Task 1: Uso de GPU e VRAM de qualquer fabricante

`recursos.py:_amostrar_gpu()` só sabe falar com `nvidia-smi`. Numa máquina com Radeon ele devolve `None` e a tela mostra "sem GPU NVIDIA detectada" — apesar de a GPU existir, estar em uso, e o Ollama estar rodando 100% nela.

Os Performance Counters do Windows expõem uso e memória de **qualquer** GPU com driver WDDM, sem SDK de fabricante.

**Files:**
- Create: `gclaude_indexer/contadores_windows.py`
- Create: `tests/test_fase13.py`
- Modify: `gclaude_indexer/recursos.py:40-61` (`_amostrar_gpu`)

**Interfaces:**
- Produces:
  - `uso_gpu_percentual() -> float | None` — soma das engines ativas, limitada a 100.
  - `vram_usada_mb() -> int | None`
  - `disponivel() -> bool` — se os contadores respondem nesta máquina.
  - Todas devolvem `None` em qualquer falha; **nunca levantam**.
- Consumes: `executar_oculto` de `subprocesso.py` (já existente, esconde a janela do console).

- [ ] **Step 1: Escrever o teste que falha**

Crie `tests/test_fase13.py`:

```python
"""Testes da Fase 13: telemetria de máquina, qualidade e layouts."""

from __future__ import annotations

import time

import fitz
import pytest
from fastapi.testclient import TestClient

import gclaude_indexer.catalogo as catalogo_mod
import gclaude_indexer.hardware as hardware_mod
from gclaude_indexer.web.app import app
from gclaude_indexer.web.execucao_bg import gerenciador_tarefas


@pytest.fixture(autouse=True)
def limpar_gerenciador():
    gerenciador_tarefas._tarefas.clear()
    yield
    gerenciador_tarefas._tarefas.clear()


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    pasta_local = tmp_path / "local_maquina"
    monkeypatch.setattr(catalogo_mod, "pasta_local_maquina", lambda: pasta_local)
    monkeypatch.setattr(hardware_mod, "pasta_local_maquina", lambda: pasta_local)
    return TestClient(app)


def _pdf(caminho, texto):
    documento = fitz.open()
    pagina = documento.new_page()
    pagina.insert_textbox((50, 50, 550, 750), texto, fontsize=12)
    documento.save(caminho)
    documento.close()


def _criar_projeto(cliente, tmp_path, nome="Projeto fase 13", **campos_extra):
    origem = tmp_path / "origem" / nome.replace(" ", "_")
    (origem / "volume_1").mkdir(parents=True)
    saida = tmp_path / f"{nome.replace(' ', '_')}_indexado"
    _pdf(origem / "volume_1" / "peca.pdf",
         "OFÍCIO No 1\nAssunto: teste da fase 13, com texto suficiente para não acionar OCR.\n10/01/2024")
    dados = {
        "nome": nome, "tema": "Acervo de teste", "pasta_origem": str(origem), "pasta_saida": str(saida),
        "tipo_acervo": "processo", "agrupador_modo": "subpasta", "agrupador_padrao": "",
        "extensoes": ["pdf", "docx", "imagens"], "paginas_por_bloco": "80", "paginas_por_janela": "16",
        "sobreposicao": "2", "caracteres_por_pagina": "2000", "idioma_ocr": "por",
        "motor_classificacao": "regras", "modelo_local": "gemma4:e4b", "papel_instrucoes": "", "regras_extras": "",
    }
    dados.update(campos_extra)
    resposta = cliente.post("/projetos/novo", data=dados, follow_redirects=False)
    assert resposta.status_code == 303, resposta.text
    return int(resposta.headers["location"].split("/")[2])


def _esperar_etapa_terminar(projeto_id: int, etapa: str, timeout: float = 30):
    fim = time.monotonic() + timeout
    while time.monotonic() < fim:
        tarefa = gerenciador_tarefas.obter(projeto_id, etapa)
        if tarefa is not None and not tarefa.rodando:
            return tarefa
        time.sleep(0.05)
    raise AssertionError(f"etapa '{etapa}' não terminou em {timeout}s")


# --- Tarefa 1: GPU de qualquer fabricante ----------------------------------


def test_contadores_nunca_levantam_mesmo_com_powershell_quebrado(monkeypatch):
    """A tela de Execução consulta isto a cada 500ms — uma exceção aqui
    derrubaria o gráfico inteiro."""
    from gclaude_indexer import contadores_windows

    def _explode(*_a, **_k):
        raise OSError("powershell sumiu")

    monkeypatch.setattr(contadores_windows, "executar_oculto", _explode)
    assert contadores_windows.uso_gpu_percentual() is None
    assert contadores_windows.vram_usada_mb() is None
    assert contadores_windows.disponivel() is False


def test_uso_de_gpu_e_percentual_valido_ou_none(monkeypatch):
    from gclaude_indexer import contadores_windows

    class _Resultado:
        returncode = 0
        stdout = "37.5\n"

    monkeypatch.setattr(contadores_windows, "executar_oculto", lambda *a, **k: _Resultado())
    assert contadores_windows.uso_gpu_percentual() == 37.5


def test_uso_de_gpu_nunca_passa_de_cem(monkeypatch):
    """A soma das engines pode estourar 100 (3D + Copy + Compute simultâneos)."""
    from gclaude_indexer import contadores_windows

    class _Resultado:
        returncode = 0
        stdout = "265.0\n"

    monkeypatch.setattr(contadores_windows, "executar_oculto", lambda *a, **k: _Resultado())
    assert contadores_windows.uso_gpu_percentual() == 100.0


def test_amostra_usa_contadores_quando_nao_ha_nvidia_smi(monkeypatch):
    """O caso desta máquina: GPU AMD, sem nvidia-smi. Antes devolvia None e a
    tela dizia 'sem GPU NVIDIA detectada' com a GPU em uso."""
    import gclaude_indexer.recursos as recursos_mod

    monkeypatch.setattr(recursos_mod.shutil, "which", lambda _nome: None)
    monkeypatch.setattr(recursos_mod, "uso_gpu_percentual", lambda: 42.0)
    monkeypatch.setattr(recursos_mod, "vram_usada_mb", lambda: 5017)

    amostra = recursos_mod.amostrar_recursos()
    assert amostra.gpu_percentual == 42.0
    assert amostra.gpu_vram_usada_mb == 5017
```

- [ ] **Step 2: Rodar para confirmar que falha**

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest tests/test_fase13.py -v
```

Esperado: FAIL com `ModuleNotFoundError: No module named 'gclaude_indexer.contadores_windows'`.

- [ ] **Step 3: Criar `gclaude_indexer/contadores_windows.py`**

```python
"""Telemetria de máquina pelos Performance Counters do Windows.

Escolhido em vez de `nvidia-smi` porque funciona com **qualquer** GPU que
tenha driver WDDM — AMD, Intel e NVIDIA — sem SDK de fabricante. Foi o que
resolveu a tela dizer "sem GPU NVIDIA detectada" numa máquina com Radeon
rodando o modelo local a 100% de GPU.

Os contadores são referenciados por **índice numérico**, nunca por nome: os
nomes são traduzidos conforme o idioma do Windows (nesta máquina o de
frequência de CPU é "Informações do Processador(_Total)\\Frequência do
Processador"), e código que dependa do nome quebra em qualquer máquina com
outro idioma instalado.

Toda função devolve `None` quando o dado não está disponível — nunca `0`,
que seria indistinguível de "ocioso", e nunca uma exceção, porque a tela de
Execução consulta isto a cada 500ms.
"""

from __future__ import annotations

import subprocess

from .subprocesso import executar_oculto

# Índices dos contadores (universais, independentes do idioma do Windows):
#   1740 = GPU Engine / Utilization Percentage
#   1752 = GPU Adapter Memory / Dedicated Usage
# O nome localizado é resolvido pelo próprio PowerShell a partir do índice.
_PS_USO_GPU = (
    "$ErrorActionPreference='Stop';"
    "$c=(Get-Counter '\\GPU Engine(*)\\Utilization Percentage').CounterSamples;"
    "[math]::Round((($c | Measure-Object CookedValue -Sum).Sum),1)"
)

_PS_VRAM = (
    "$ErrorActionPreference='Stop';"
    "$c=(Get-Counter '\\GPU Adapter Memory(*)\\Dedicated Usage').CounterSamples;"
    "[math]::Round((($c | Measure-Object CookedValue -Sum).Sum)/1MB,0)"
)

_TIMEOUT_S = 6


def _consultar(comando: str) -> str | None:
    """Roda um comando PowerShell oculto e devolve a primeira linha, ou
    `None` em qualquer falha."""
    try:
        resultado = executar_oculto(
            ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", comando],
            timeout=_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if resultado.returncode != 0 or not resultado.stdout.strip():
        return None
    return resultado.stdout.strip().splitlines()[0].strip()


def uso_gpu_percentual() -> float | None:
    """Uso somado das engines da GPU, em porcentagem.

    A soma pode passar de 100 quando várias engines (3D, Copy, Compute)
    trabalham ao mesmo tempo — o valor é limitado a 100 para caber na escala
    do gráfico.
    """
    bruto = _consultar(_PS_USO_GPU)
    if bruto is None:
        return None
    try:
        return min(100.0, max(0.0, float(bruto.replace(",", "."))))
    except ValueError:
        return None


def vram_usada_mb() -> int | None:
    bruto = _consultar(_PS_VRAM)
    if bruto is None:
        return None
    try:
        return max(0, int(float(bruto.replace(",", "."))))
    except ValueError:
        return None


def disponivel() -> bool:
    """Se os contadores de GPU respondem nesta máquina."""
    return uso_gpu_percentual() is not None
```

- [ ] **Step 4: Ligar em `recursos.py`**

Acrescente ao topo de `recursos.py`:

```python
from .contadores_windows import uso_gpu_percentual, vram_usada_mb
```

E reescreva `_amostrar_gpu` para tentar o `nvidia-smi` primeiro (mais preciso quando existe) e cair nos contadores:

```python
def _amostrar_gpu() -> tuple[float | None, int | None, int | None]:
    """Uso e VRAM da GPU. Prefere `nvidia-smi` quando existe (dá o total de
    VRAM com precisão); senão usa os Performance Counters, que funcionam com
    qualquer fabricante. `None` significa "não medido" — nunca 0."""
    caminho = shutil.which("nvidia-smi")
    if caminho:
        medida = _amostrar_gpu_nvidia(caminho)
        if medida != (None, None, None):
            return medida

    uso = uso_gpu_percentual()
    if uso is None:
        return None, None, None
    return uso, vram_usada_mb(), _vram_total_mb()
```

Mova o corpo atual de `_amostrar_gpu` para uma função `_amostrar_gpu_nvidia(caminho)` com a mesma lógica, e acrescente `_vram_total_mb()`, que lê o total pelo diagnóstico de hardware já existente:

```python
@functools.lru_cache(maxsize=1)
def _vram_total_mb() -> int | None:
    """Total de VRAM, cacheado (não muda em execução). Vem do mesmo caminho
    do diagnóstico da fase 7, que já detecta AMD/Intel por WMI."""
    from .hardware import _detectar_gpu_nvidia, _detectar_gpu_wmi

    gpu = _detectar_gpu_nvidia() or _detectar_gpu_wmi()
    return getattr(gpu, "vram_mb", None) if gpu else None
```

> Confira o nome real do campo de VRAM em `hardware.InfoGpu` antes de usar `vram_mb` — se for outro, ajuste. Não invente o nome.

- [ ] **Step 5: Rodar os testes desta tarefa**

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest tests/test_fase13.py -v
```

Esperado: PASS nos quatro.

- [ ] **Step 6: Conferir na máquina real**

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -c "from gclaude_indexer.recursos import amostrar_recursos; a=amostrar_recursos(); print(a.gpu_nome, a.gpu_percentual, a.gpu_vram_usada_mb, a.gpu_vram_total_mb)"
```

Esta máquina tem Radeon RX 5700 XT e **não** tem `nvidia-smi`. Esperado: nome da Radeon e um percentual numérico, **não** `None`. Se vier `None`, a tarefa não cumpriu seu objetivo — investigue antes de seguir.

- [ ] **Step 7: Rodar a suíte inteira**

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest -q
```

Esperado: `224 passed` (220 + 4).

---

### Task 2: Clocks de CPU, memória e GPU

O painel mostra uso, mas não a velocidade real. Num acervo grande, saber que a CPU está em 4,4 GHz ou caiu para 2,1 GHz por temperatura explica lentidão que o percentual de uso não explica.

**Files:**
- Modify: `gclaude_indexer/contadores_windows.py`
- Modify: `gclaude_indexer/recursos.py` (dataclass `AmostraRecursos` e `amostrar_recursos`)
- Modify: `tests/test_fase13.py`

**Interfaces:**
- Produces:
  - `clock_cpu_mhz() -> int | None` — frequência atual, via contador por índice.
  - `clock_memoria_mhz() -> int | None` — cacheado, não muda em execução.
  - `clock_gpu_mhz() -> int | None` — **pode devolver `None` sempre**; ver Step 4.
  - Campos novos em `AmostraRecursos`: `clock_cpu_mhz`, `clock_memoria_mhz`, `clock_gpu_mhz`, todos `int | None`.

- [ ] **Step 1: Escrever o teste que falha**

```python
# --- Tarefa 2: clocks -------------------------------------------------------


def test_clock_de_memoria_e_cacheado_e_inteiro(monkeypatch):
    from gclaude_indexer import contadores_windows

    class _R:
        returncode = 0
        stdout = "3600\n"

    chamadas = []
    def _fake(*a, **k):
        chamadas.append(1)
        return _R()

    contadores_windows.clock_memoria_mhz.cache_clear()
    monkeypatch.setattr(contadores_windows, "executar_oculto", _fake)
    assert contadores_windows.clock_memoria_mhz() == 3600
    assert contadores_windows.clock_memoria_mhz() == 3600
    assert len(chamadas) == 1, "clock de memória não muda: deve ser consultado uma vez só"


def test_clocks_devolvem_none_em_falha(monkeypatch):
    from gclaude_indexer import contadores_windows

    contadores_windows.clock_memoria_mhz.cache_clear()
    monkeypatch.setattr(contadores_windows, "executar_oculto",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("sem powershell")))
    assert contadores_windows.clock_cpu_mhz() is None
    assert contadores_windows.clock_memoria_mhz() is None
    assert contadores_windows.clock_gpu_mhz() is None


def test_amostra_expoe_os_tres_clocks(monkeypatch):
    import gclaude_indexer.recursos as recursos_mod

    monkeypatch.setattr(recursos_mod, "clock_cpu_mhz", lambda: 4400)
    monkeypatch.setattr(recursos_mod, "clock_memoria_mhz", lambda: 3600)
    monkeypatch.setattr(recursos_mod, "clock_gpu_mhz", lambda: None)

    a = recursos_mod.amostrar_recursos()
    assert a.clock_cpu_mhz == 4400
    assert a.clock_memoria_mhz == 3600
    assert a.clock_gpu_mhz is None, "clock de GPU indisponível vira None, nunca 0"
```

- [ ] **Step 2: Rodar para confirmar que falha**

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest tests/test_fase13.py -k clock -v
```

Esperado: FAIL com `AttributeError: module ... has no attribute 'clock_memoria_mhz'`.

- [ ] **Step 3: Acrescentar os clocks a `contadores_windows.py`**

```python
import functools

# `Get-Counter` aceita o índice numérico traduzido pelo próprio PowerShell.
# 328 = Informações do Processador / Frequência do Processador.
_PS_CLOCK_CPU = (
    "$ErrorActionPreference='Stop';"
    "$n=(Get-Counter -ListSet * | Where-Object {$_.CounterSetName -match 'Processor Information|Informações do Processador'} | "
    "Select-Object -First 1 -ExpandProperty Paths | Where-Object {$_ -match 'Frequ'} | Select-Object -First 1);"
    "if(-not $n){throw 'sem contador'};"
    "$p=$n -replace '\\(\\*\\)','(_Total)';"
    "[math]::Round((Get-Counter $p).CounterSamples[0].CookedValue,0)"
)

_PS_CLOCK_MEMORIA = (
    "$ErrorActionPreference='Stop';"
    "(Get-CimInstance Win32_PhysicalMemory | Select-Object -First 1 -ExpandProperty ConfiguredClockSpeed)"
)


def clock_cpu_mhz() -> int | None:
    """Frequência atual da CPU. O contador tem nome localizado, por isso ele
    é descoberto em tempo de execução em vez de escrito literalmente."""
    bruto = _consultar(_PS_CLOCK_CPU)
    if bruto is None:
        return None
    try:
        return max(0, int(float(bruto.replace(",", "."))))
    except ValueError:
        return None


@functools.lru_cache(maxsize=1)
def clock_memoria_mhz() -> int | None:
    """Frequência configurada da memória. Não muda durante a execução, então
    é consultada uma vez só (WMI custa ~0,5s por chamada)."""
    bruto = _consultar(_PS_CLOCK_MEMORIA)
    if bruto is None:
        return None
    try:
        return max(0, int(float(bruto.replace(",", "."))))
    except ValueError:
        return None


def clock_gpu_mhz() -> int | None:
    """Frequência do núcleo da GPU.

    O Windows **não** expõe isso por Performance Counter nem por WMI para
    nenhum fabricante. Fica como `None` aqui e é preenchido pelo módulo de
    sensores (Tarefa 3) quando o LibreHardwareMonitor estiver disponível.
    Existe como função para que a interface tenha um lugar só para consultar.
    """
    return None
```

- [ ] **Step 4: Acrescentar os campos à amostra**

Em `recursos.py`, importe as três funções e acrescente ao dataclass `AmostraRecursos`:

```python
    clock_cpu_mhz: int | None = None
    clock_memoria_mhz: int | None = None
    clock_gpu_mhz: int | None = None
```

E preencha em `amostrar_recursos()` chamando as três.

> Os campos têm default `None` de propósito: assim os testes existentes que constroem `AmostraRecursos` sem eles continuam válidos.

- [ ] **Step 5: Rodar os testes desta tarefa e a suíte**

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest tests/test_fase13.py -k clock -v
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest -q
```

Esperado: `227 passed`.

---

### Task 3: Temperatura e potência via LibreHardwareMonitor

Nenhuma API nativa do Windows entrega temperatura ou consumo. O caminho é a `LibreHardwareMonitorLib.dll` (MPL-2.0), lida por `pythonnet`.

**Duas consequências que o usuário já aceitou explicitamente, mas que precisam estar visíveis no código e na tela:**

1. **Exige privilégio de administrador.** A biblioteca carrega um driver de kernel para ler sensores. Sem elevação, a lista de sensores volta vazia.
2. **É dependência externa binária**, contrariando o princípio do projeto. Por isso a integração é isolada num módulo só, com degradação explícita: sem DLL, sem .NET, sem pythonnet ou sem elevação, tudo devolve `None` e a tela diz "não disponível".

**Files:**
- Create: `gclaude_indexer/sensores.py`
- Modify: `requirements.txt` (acrescentar `pythonnet`)
- Modify: `gclaude_indexer/recursos.py`
- Modify: `tests/test_fase13.py`

**Interfaces:**
- Produces:
  - `SENSORES_DISPONIVEIS: bool` — resultado da sondagem, calculado uma vez.
  - `motivo_indisponivel() -> str | None` — chave de i18n explicando por quê (`"sem_dll"`, `"sem_pythonnet"`, `"sem_privilegio"`, `None` se disponível).
  - `ler_sensores() -> dict` — `{"cpu_temp_c", "gpu_temp_c", "cpu_potencia_w", "gpu_potencia_w", "clock_gpu_mhz"}`, cada um `float | int | None`.
  - **Nunca levanta.**

- [ ] **Step 1: Escrever o teste que falha**

```python
# --- Tarefa 3: sensores -----------------------------------------------------


def test_sensores_degradam_sem_pythonnet(monkeypatch):
    """Sem a dependência, tudo vira None e o motivo é nomeável — a tela nunca
    mostra 0 °C como se fosse medição."""
    from gclaude_indexer import sensores

    monkeypatch.setattr(sensores, "_importar_biblioteca", lambda: None)
    sensores._estado.cache_clear()

    leitura = sensores.ler_sensores()
    assert set(leitura) == {"cpu_temp_c", "gpu_temp_c", "cpu_potencia_w", "gpu_potencia_w", "clock_gpu_mhz"}
    assert all(v is None for v in leitura.values())
    assert sensores.motivo_indisponivel() in ("sem_dll", "sem_pythonnet", "sem_privilegio")


def test_sensores_nunca_levantam(monkeypatch):
    from gclaude_indexer import sensores

    def _explode():
        raise RuntimeError("driver recusou")

    monkeypatch.setattr(sensores, "_importar_biblioteca", _explode)
    sensores._estado.cache_clear()
    assert ler := sensores.ler_sensores()
    assert all(v is None for v in ler.values())


def test_amostra_inclui_temperatura_e_potencia(monkeypatch):
    import gclaude_indexer.recursos as recursos_mod

    monkeypatch.setattr(recursos_mod, "ler_sensores", lambda: {
        "cpu_temp_c": 61.5, "gpu_temp_c": 48.0,
        "cpu_potencia_w": 88.2, "gpu_potencia_w": 130.0, "clock_gpu_mhz": 1750,
    })
    a = recursos_mod.amostrar_recursos()
    assert a.cpu_temp_c == 61.5
    assert a.gpu_temp_c == 48.0
    assert a.cpu_potencia_w == 88.2
    assert a.gpu_potencia_w == 130.0
    assert a.clock_gpu_mhz == 1750, "o clock de GPU vem dos sensores, não dos contadores"
```

- [ ] **Step 2: Rodar para confirmar que falha**

Esperado: `ModuleNotFoundError: No module named 'gclaude_indexer.sensores'`.

- [ ] **Step 3: Instalar a dependência**

Acrescente a `requirements.txt`, na seção de monitoramento:

```
# Ponte .NET para ler sensores de temperatura/potência via LibreHardwareMonitor
# (nenhuma API nativa do Windows expõe esses dados). Degradação explícita em
# `sensores.py` quando a DLL, o .NET ou o privilégio de admin faltarem.
pythonnet==3.0.5
```

E instale:

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pip install pythonnet==3.0.5
```

> Se `pythonnet==3.0.5` não tiver wheel para Python 3.12, use a versão estável mais recente que tenha e **anote qual** no relatório. Não compile do fonte.

- [ ] **Step 4: Obter a DLL**

A `LibreHardwareMonitorLib.dll` não vem por pip. Baixe o release oficial e coloque a DLL em `%LOCALAPPDATA%\GClaudeIndexer\lib\`:

```powershell
$destino = "$env:LOCALAPPDATA\GClaudeIndexer\lib"
New-Item -ItemType Directory -Force -Path $destino | Out-Null
# baixe o zip de release de github.com/LibreHardwareMonitor/LibreHardwareMonitor
# e extraia LibreHardwareMonitorLib.dll e HidSharp.dll para $destino
```

**Regras:**
- A DLL vai na pasta **local da máquina** (`%LOCALAPPDATA%\GClaudeIndexer\lib`), nunca na pasta do projeto sincronizada pelo Drive — mesmo princípio do venv (seção 11.1 da especificação).
- Se você não conseguir baixá-la no ambiente em que está rodando, **não invente**: implemente o módulo com a degradação completa, deixe os testes passando pelo caminho "indisponível", e **relate que a DLL precisa ser instalada à mão**. O módulo tem de funcionar (devolvendo `None`) sem ela.

- [ ] **Step 5: Criar `gclaude_indexer/sensores.py`**

```python
"""Temperatura, potência e clock de GPU via LibreHardwareMonitor.

Nenhuma API nativa do Windows expõe esses dados: `MSAcpi_ThermalZoneTemperature`
falha na maioria dos desktops, e os Performance Counters não têm sensores
térmicos. A alternativa é a `LibreHardwareMonitorLib.dll` (MPL-2.0), lida por
`pythonnet`.

Isso traz duas dependências que o resto do projeto evita — um binário de
terceiros e privilégio de administrador (a biblioteca carrega um driver de
kernel para falar com os sensores). Por isso tudo está isolado aqui, com
degradação explícita: faltando qualquer peça, as leituras viram `None` e a
interface diz que não estão disponíveis. **Nunca devolva 0 no lugar de
desconhecido** — zero grau é uma medição, "não sei" não é.
"""

from __future__ import annotations

import ctypes
import functools
import os
from pathlib import Path

from .paths import pasta_local_maquina

NOME_DLL = "LibreHardwareMonitorLib.dll"

CHAVES = ("cpu_temp_c", "gpu_temp_c", "cpu_potencia_w", "gpu_potencia_w", "clock_gpu_mhz")

_VAZIO = {chave: None for chave in CHAVES}


def caminho_dll() -> Path:
    return pasta_local_maquina() / "lib" / NOME_DLL


def _e_administrador() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _importar_biblioteca():
    """Carrega a DLL via pythonnet. Devolve o módulo `Hardware` ou `None`.

    Separado numa função própria para o teste poder substituí-lo sem mexer
    em import de verdade.
    """
    if not caminho_dll().is_file():
        return None
    try:
        import clr  # noqa: F401  (pythonnet)
    except ImportError:
        return None
    try:
        import clr
        clr.AddReference(str(caminho_dll()))
        from LibreHardwareMonitor import Hardware  # type: ignore
        return Hardware
    except Exception:
        return None


@functools.lru_cache(maxsize=1)
def _estado() -> tuple[object | None, str | None]:
    """`(computador, motivo)`. `computador` é o objeto do LHM já aberto, ou
    `None`; `motivo` é a chave de i18n do porquê, ou `None` se está tudo bem."""
    if not caminho_dll().is_file():
        return None, "sem_dll"
    try:
        import clr  # noqa: F401
    except ImportError:
        return None, "sem_pythonnet"

    try:
        Hardware = _importar_biblioteca()
        if Hardware is None:
            return None, "sem_dll"
        computador = Hardware.Computer()
        computador.IsCpuEnabled = True
        computador.IsGpuEnabled = True
        computador.IsMemoryEnabled = True
        computador.Open()
    except Exception:
        return None, "sem_privilegio"

    if not _e_administrador():
        # A biblioteca abre, mas sem elevação os sensores vêm vazios.
        return computador, "sem_privilegio"
    return computador, None


def motivo_indisponivel() -> str | None:
    return _estado()[1]


SENSORES_DISPONIVEIS = property(lambda _self: _estado()[1] is None)


def ler_sensores() -> dict:
    """Leitura atual dos sensores. Chaves sempre presentes; valores `None`
    quando não medidos. **Nunca levanta.**"""
    try:
        computador, motivo = _estado()
    except Exception:
        return dict(_VAZIO)
    if computador is None:
        return dict(_VAZIO)

    leitura = dict(_VAZIO)
    try:
        for componente in computador.Hardware:
            componente.Update()
            tipo = str(componente.HardwareType)
            for sensor in componente.Sensors:
                if sensor.Value is None:
                    continue
                nome_tipo = str(sensor.SensorType)
                valor = float(sensor.Value)
                if nome_tipo == "Temperature":
                    if "Cpu" in tipo and leitura["cpu_temp_c"] is None:
                        leitura["cpu_temp_c"] = round(valor, 1)
                    elif "Gpu" in tipo and leitura["gpu_temp_c"] is None:
                        leitura["gpu_temp_c"] = round(valor, 1)
                elif nome_tipo == "Power":
                    if "Cpu" in tipo and leitura["cpu_potencia_w"] is None:
                        leitura["cpu_potencia_w"] = round(valor, 1)
                    elif "Gpu" in tipo and leitura["gpu_potencia_w"] is None:
                        leitura["gpu_potencia_w"] = round(valor, 1)
                elif nome_tipo == "Clock" and "Gpu" in tipo and "Core" in str(sensor.Name):
                    leitura["clock_gpu_mhz"] = int(valor)
    except Exception:
        return dict(_VAZIO)
    return leitura
```

> **Atenção ao `SENSORES_DISPONIVEIS`**: escrito como `property` num módulo, ele não funciona — `property` só se comporta assim dentro de classe. Troque por uma função `sensores_disponiveis() -> bool` e ajuste os chamadores. Este é um erro deliberado do plano que o implementador deve corrigir; se você o copiou sem notar, a revisão vai pegar.

- [ ] **Step 6: Ligar em `recursos.py`**

Importe `ler_sensores` e acrescente ao dataclass os campos `cpu_temp_c`, `gpu_temp_c`, `cpu_potencia_w`, `gpu_potencia_w` (todos `float | None = None`), preenchendo-os em `amostrar_recursos()`. O `clock_gpu_mhz` da amostra passa a vir dos sensores quando disponível, caindo para `contadores_windows.clock_gpu_mhz()` (que devolve `None`) quando não.

**Cuidado com o custo:** `ler_sensores()` faz `Update()` em todos os componentes, o que leva dezenas de milissegundos. A tela consulta a cada 500ms. Meça: se passar de ~150ms, coloque um cache com validade de 2 segundos e **documente** a decisão.

- [ ] **Step 7: Rodar os testes e a suíte**

Esperado: `230 passed`.

- [ ] **Step 8: Conferir na máquina real**

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -c "from gclaude_indexer.sensores import ler_sensores, motivo_indisponivel; print(motivo_indisponivel()); print(ler_sensores())"
```

Rode **duas vezes**: uma normal e uma em PowerShell elevado. Sem elevação o esperado é `sem_privilegio` e tudo `None`; com elevação e a DLL no lugar, valores reais. **Relate os dois resultados** — é o que diz se a dependência entrega o que promete nesta máquina.

---

### Task 4: Painel de recursos mostrando tudo

Com os dados coletados, a tela de Execução precisa exibi-los — e dizer com todas as letras quando um dado não está disponível, em vez de mostrar zero.

**Files:**
- Modify: `gclaude_indexer/web/app.py` (`recursos_json`)
- Modify: `gclaude_indexer/web/templates/execucao.html` (bloco de recursos e o script)
- Modify: `gclaude_indexer/web/static/estilo.css`
- Modify: `gclaude_indexer/web/i18n.py`
- Modify: `tests/test_fase13.py`

- [ ] **Step 1: Escrever o teste que falha**

```python
# --- Tarefa 4: painel -------------------------------------------------------


def test_json_de_recursos_traz_clocks_temperatura_e_potencia(cliente, tmp_path):
    projeto_id = _criar_projeto(cliente, tmp_path)
    dados = cliente.get(f"/projetos/{projeto_id}/execucao/recursos").json()
    for campo in ("clock_cpu_mhz", "clock_memoria_mhz", "clock_gpu_mhz",
                  "cpu_temp_c", "gpu_temp_c", "cpu_potencia_w", "gpu_potencia_w",
                  "sensores_indisponiveis_motivo"):
        assert campo in dados, f"faltou {campo} no JSON de recursos"


def test_painel_tem_lugar_para_temperatura_e_clocks(cliente, tmp_path):
    projeto_id = _criar_projeto(cliente, tmp_path)
    corpo = cliente.get(f"/projetos/{projeto_id}/execucao").text
    for marcador in ('id="temp-cpu"', 'id="temp-gpu"', 'id="pot-cpu"', 'id="pot-gpu"',
                     'id="clock-cpu"', 'id="clock-ram"', 'id="clock-gpu"'):
        assert marcador in corpo, marcador
```

- [ ] **Step 2: Rodar para confirmar que falha**

- [ ] **Step 3: Expor no JSON**

Em `recursos_json` (`app.py`), acrescente os campos novos da amostra, mais o motivo:

```python
        "clock_cpu_mhz": amostra.clock_cpu_mhz,
        "clock_memoria_mhz": amostra.clock_memoria_mhz,
        "clock_gpu_mhz": amostra.clock_gpu_mhz,
        "cpu_temp_c": amostra.cpu_temp_c,
        "gpu_temp_c": amostra.gpu_temp_c,
        "cpu_potencia_w": amostra.cpu_potencia_w,
        "gpu_potencia_w": amostra.gpu_potencia_w,
        "sensores_indisponiveis_motivo": motivo_indisponivel(),
```

- [ ] **Step 4: Exibir na tela**

Em `execucao.html`, acrescente aos cartões de CPU e GPU as linhas de temperatura, potência e clock, e um cartão/linha para o clock da memória. Use `id` exatamente como no teste.

No JavaScript já existente, ao preencher cada valor:

```javascript
  function mostrarOuTraco(id, valor, sufixo) {
    // null = não medido. Nunca escreva 0 aqui: zero é uma medição válida
    // e mentiria sobre o estado da máquina.
    var el = document.getElementById(id);
    if (!el) return;
    el.textContent = (valor === null || valor === undefined) ? INDISPONIVEL_TEXTO : (valor + (sufixo || ""));
  }
```

Quando `sensores_indisponiveis_motivo` não for nulo, mostre uma linha discreta abaixo do painel com a explicação traduzida (`t('recursos.sensores.' + motivo)`).

- [ ] **Step 5: Chaves de tradução**

```python
# pt
        "recursos.temperatura": "Temperatura",
        "recursos.potencia": "Consumo",
        "recursos.clock": "Frequência",
        "recursos.indisponivel": "não medido",
        "recursos.sensores.sem_dll": "Temperatura e consumo precisam da biblioteca LibreHardwareMonitor, que não está instalada nesta máquina.",
        "recursos.sensores.sem_pythonnet": "Temperatura e consumo precisam do pacote pythonnet, que não está instalado no ambiente.",
        "recursos.sensores.sem_privilegio": "Temperatura e consumo exigem executar o sistema como administrador — os sensores da placa não abrem sem isso.",
# en
        "recursos.temperatura": "Temperature",
        "recursos.potencia": "Power draw",
        "recursos.clock": "Clock",
        "recursos.indisponivel": "not measured",
        "recursos.sensores.sem_dll": "Temperature and power need the LibreHardwareMonitor library, which is not installed on this machine.",
        "recursos.sensores.sem_pythonnet": "Temperature and power need the pythonnet package, which is not installed in this environment.",
        "recursos.sensores.sem_privilegio": "Temperature and power require running the system as administrator — the board sensors do not open otherwise.",
# es
        "recursos.temperatura": "Temperatura",
        "recursos.potencia": "Consumo",
        "recursos.clock": "Frecuencia",
        "recursos.indisponivel": "no medido",
        "recursos.sensores.sem_dll": "La temperatura y el consumo necesitan la biblioteca LibreHardwareMonitor, que no está instalada en esta máquina.",
        "recursos.sensores.sem_pythonnet": "La temperatura y el consumo necesitan el paquete pythonnet, que no está instalado en este entorno.",
        "recursos.sensores.sem_privilegio": "La temperatura y el consumo requieren ejecutar el sistema como administrador — los sensores de la placa no se abren sin eso.",
```

- [ ] **Step 6: Rodar testes e suíte**

Esperado: `232 passed`.

---

### Task 5: "Todos" exclusivo nas extensões

Marcar "todos" com "pdf" já marcado é contraditório: `extensao_permitida` ignora as demais categorias quando `todos` está presente, então a interface mostra um estado que o motor não respeita.

**Files:**
- Modify: `gclaude_indexer/web/templates/novo_projeto.html`
- Modify: `tests/test_fase13.py`

- [ ] **Step 1: Escrever o teste que falha**

```python
# --- Tarefa 5: "todos" exclusivo -------------------------------------------


def test_formulario_traz_o_script_de_exclusividade_do_todos(cliente):
    corpo = cliente.get("/projetos/novo").text
    assert 'data-categoria-todos' in corpo
    assert 'name="extensoes"' in corpo
```

> Comportamento de clique é JavaScript e não dá para assertar em HTML servido. Este teste garante que o gancho existe; a verificação real é o Step 4, no navegador.

- [ ] **Step 2: Rodar para confirmar que falha**

- [ ] **Step 3: Implementar**

No `novo_projeto.html`, marque o checkbox de "todos" com `data-categoria-todos` e acrescente, ao fim do bloco de extensões:

```html
<script>
(function () {
  // "todos" e as categorias específicas são mutuamente exclusivos:
  // `extensao_permitida` ignora as demais quando "todos" está marcado, então
  // deixá-las marcadas mostraria um estado que a varredura não respeita.
  var todos = document.querySelector('input[data-categoria-todos]');
  if (!todos) return;
  var especificas = [].slice.call(
    document.querySelectorAll('input[name="extensoes"]:not([data-categoria-todos])')
  );
  todos.addEventListener('change', function () {
    if (todos.checked) especificas.forEach(function (c) { c.checked = false; });
  });
  especificas.forEach(function (c) {
    c.addEventListener('change', function () {
      if (c.checked) todos.checked = false;
    });
  });
})();
</script>
```

- [ ] **Step 4: Conferir no navegador**

Suba o servidor, abra `/projetos/novo`: marcar "todos" desmarca as demais; marcar qualquer específica desmarca "todos". Confirme que ainda é possível submeter com nenhuma marcada e receber o erro de validação normal.

- [ ] **Step 5: Rodar a suíte**

Esperado: `233 passed`.

---

### Task 6: Remover o OpenRouter por completo

O motor nunca foi implementado. Escolhê-lo faz a classificação cair silenciosamente em `regras`. A Fase 12 corrigiu o texto; agora a opção sai.

**Files:**
- Modify: `gclaude_indexer/config.py:13`, `gclaude_indexer/classificacao.py:17`, `gclaude_indexer/orquestrador.py:32` (docstring)
- Modify: `gclaude_indexer/web/app.py:66` (`MOTORES_ORDENADOS`)
- Modify: `gclaude_indexer/web/i18n.py` (remover 2 chaves × 3 idiomas)
- Modify: `tests/test_fase12.py:329` (o teste cita openrouter)
- Modify: `ESPECIFICACAO.md` (seção 5)
- Modify: `tests/test_fase13.py`

- [ ] **Step 1: Escrever o teste que falha**

```python
# --- Tarefa 6: openrouter removido -----------------------------------------


def test_openrouter_nao_existe_mais_em_lugar_nenhum():
    from gclaude_indexer.classificacao import MOTORES_VALIDOS
    from gclaude_indexer.config import MOTORES_CLASSIFICACAO
    from gclaude_indexer.web.app import MOTORES_ORDENADOS
    from gclaude_indexer.web.i18n import _TRADUCOES

    assert "openrouter" not in MOTORES_CLASSIFICACAO
    assert "openrouter" not in MOTORES_VALIDOS
    assert "openrouter" not in MOTORES_ORDENADOS
    for idioma, tabela in _TRADUCOES.items():
        sobrando = [c for c in tabela if "openrouter" in c]
        assert not sobrando, f"{idioma} ainda tem chaves de openrouter: {sobrando}"


def test_projeto_com_openrouter_e_recusado_na_validacao(tmp_path):
    from gclaude_indexer.config import ErroConfig, carregar_config

    with pytest.raises(ErroConfig):
        carregar_config({
            "nome": "x", "pasta_origem": str(tmp_path), "pasta_saida": str(tmp_path / "s"),
            "motor_classificacao": "openrouter",
        })
```

- [ ] **Step 2: Rodar para confirmar que falha**

- [ ] **Step 3: Remover**

Tire `"openrouter"` dos três conjuntos e da tupla, apague as 6 chaves de i18n, e corrija o docstring de `rodar_classificacao` em `orquestrador.py`, que hoje diz "`claude_code` e `openrouter` não passam por aqui".

**Atenção ao teste da Fase 12** (`test_descricoes_dos_motores_nao_afirmam_o_que_o_codigo_nao_faz`): ele assere `"ainda não implementado" in corpo`, texto que some junto com a opção. Ajuste-o para não depender mais disso — **sem enfraquecer o resto das asserções**, que continuam válidas (`"hardware" in corpo`, `"Ollama estiver respondendo" not in corpo`).

- [ ] **Step 4: Verificar projetos existentes**

Um projeto gravado antes desta mudança pode ter `motor_classificacao: "openrouter"` no `config_json`. Abrir esse projeto passará a dar `ErroConfig`. **Decida e documente:** ou a validação converte silenciosamente para `"regras"` com um evento de aviso, ou o usuário vê o erro e corrige. Prefira a conversão com aviso — o projeto do usuário não deve virar inacessível por causa de uma limpeza nossa. Escreva um teste para o caminho escolhido.

- [ ] **Step 5: Rodar a suíte**

Esperado: `235 passed`.

---

### Task 7: O log não rola sozinho quando o usuário está lendo

Hoje a rolagem é presa no fim sempre que "acompanhar o fim" está marcado — e ele vem marcado por padrão. Rolar para cima para ler algo que passou é inútil: dois segundos depois o HTMX troca o conteúdo e o script joga tudo para baixo de novo.

O comportamento correto é o de qualquer terminal ou app de chat: **rolar para cima desliga o acompanhamento automaticamente**; voltar ao fim religa.

**Files:**
- Modify: `gclaude_indexer/web/templates/execucao.html` (script)
- Modify: `tests/test_fase13.py`

- [ ] **Step 1: Escrever o teste que falha**

```python
# --- Tarefa 7: rolagem do log ----------------------------------------------


def test_script_do_log_desliga_o_seguir_ao_rolar_para_cima(cliente, tmp_path):
    projeto_id = _criar_projeto(cliente, tmp_path)
    corpo = cliente.get(f"/projetos/{projeto_id}/execucao").text
    assert 'addEventListener("scroll"' in corpo or "addEventListener('scroll'" in corpo
    assert "PERTO_DO_FIM" in corpo
```

> De novo: comportamento de rolagem não é testável no HTML servido. Isto garante o gancho; o Step 4 verifica de verdade.

- [ ] **Step 2: Rodar para confirmar que falha**

- [ ] **Step 3: Implementar**

No script de `execucao.html`, substitua a lógica de rolagem:

```javascript
  var PERTO_DO_FIM = 40; // px de tolerância para considerar "está no fim"

  function estaNoFim() {
    return (caixaLog.scrollHeight - caixaLog.clientHeight - caixaLog.scrollTop) <= PERTO_DO_FIM;
  }

  // Rolar para cima desliga o acompanhamento; voltar ao fim religa. Sem isto
  // o usuário não consegue ler nada que passou: o poll de 2s puxa a rolagem
  // de volta para baixo a cada ciclo.
  var rolagemPropria = false;
  caixaLog.addEventListener("scroll", function () {
    if (rolagemPropria) return;
    seguirLog.checked = estaNoFim();
  });

  function rolarLogParaOFim() {
    if (!seguirLog.checked) return;
    rolagemPropria = true;
    caixaLog.scrollTop = caixaLog.scrollHeight;
    // libera no próximo quadro, para não capturar o scroll que acabamos de causar
    requestAnimationFrame(function () { rolagemPropria = false; });
  }
```

Mantenha a reaplicação no `htmx:afterSwap` (Fase 12), que continua necessária.

- [ ] **Step 4: Conferir no navegador — este passo não é opcional**

Suba o servidor, rode um projeto com bastante log, e:
1. Role para cima no meio da execução → a caixa **não** pode voltar sozinha para baixo, e "acompanhar o fim" deve desmarcar.
2. Role de volta até o fim → deve remarcar sozinho e voltar a acompanhar.
3. Confirme que o filtro por nível continua funcionando depois disso.

Um teste de HTML não pega nada disso. A Fase 12 teve um defeito exatamente assim: funcionalidade quebrada com teste verde.

- [ ] **Step 5: Rodar a suíte**

Esperado: `236 passed`.

---

### Task 8: O seletor de modelos passa a valer

`motor_local.modelo_para_usar` ignora `config.modelo_local` e devolve sempre `MODELO_LOCAL_PADRAO`. O seletor construído na Fase 12 é cosmético.

**Isto é pré-requisito da Tarefa 9:** comparar a qualidade de modelos diferentes é impossível se todas as execuções usam o mesmo modelo.

> **Nota ao implementador:** o docstring atual diz "por decisão explícita do usuário, nenhum outro modelo é permitido". Essa decisão foi **revista pelo usuário** ao pedir a comparação entre modelos. Substitua o docstring pela nova regra; não deixe os dois textos convivendo.

**Files:**
- Modify: `gclaude_indexer/motor_local.py:136-141`
- Modify: `gclaude_indexer/web/i18n.py` (os textos da Fase 12 dizem que a escolha *não* muda o modelo — passam a mentir)
- Modify: `tests/test_fase12.py` (`test_ajuda_do_modelo_local_diz_a_verdade_sobre_o_modelo_usado` trava a frase antiga)
- Modify: `tests/test_fase13.py`

- [ ] **Step 1: Escrever o teste que falha**

```python
# --- Tarefa 8: o modelo escolhido é o usado --------------------------------


def test_modelo_para_usar_respeita_a_escolha(tmp_path):
    from gclaude_indexer.config import ConfigProjeto
    from gclaude_indexer.motor_local import MODELO_LOCAL_PADRAO, modelo_para_usar

    base = dict(nome="x", pasta_origem=str(tmp_path), pasta_saida=str(tmp_path / "s"))
    assert modelo_para_usar(None, ConfigProjeto(**base, modelo_local="qwen3:8b")) == "qwen3:8b"
    assert modelo_para_usar(None, ConfigProjeto(**base, modelo_local="automatico")) == MODELO_LOCAL_PADRAO
    assert modelo_para_usar(None, ConfigProjeto(**base, modelo_local="")) == MODELO_LOCAL_PADRAO
```

- [ ] **Step 2: Rodar para confirmar que falha**

- [ ] **Step 3: Implementar**

```python
def modelo_para_usar(conn, config: ConfigProjeto) -> str:
    """Modelo que o motor 'local' vai usar.

    A escolha do usuário no formulário vale; `MODELO_LOCAL_PADRAO` é só o
    default. Antes esta função ignorava `config.modelo_local` e devolvia
    sempre o padrão — o seletor da tela era decorativo. Passou a valer quando
    o usuário pediu para comparar a qualidade de modelos diferentes, o que é
    impossível se toda execução usa o mesmo.
    """
    escolhido = (config.modelo_local or "").strip()
    if escolhido and escolhido != "automatico":
        return escolhido
    return MODELO_LOCAL_PADRAO
```

- [ ] **Step 4: Corrigir os textos que passam a mentir**

`novo_projeto.ajuda_modelo_local`, `dica.modelo_local` e `novo_projeto.modelo_local_sem_ollama` dizem hoje que a escolha **não** altera o modelo usado. Reescreva os três, nos três idiomas, dizendo o que passa a ser verdade: a escolha é usada; o padrão é `gemma4:e4b`; com o Ollama parado o sistema cai no motor de regras com aviso.

**Atualize também** `test_ajuda_do_modelo_local_diz_a_verdade_sobre_o_modelo_usado` (Fase 12), que trava a frase antiga. Mantenha o espírito do teste: ele deve continuar impedindo que os textos afirmem o que o código não faz — só muda o que o código faz.

- [ ] **Step 5: Rodar a suíte**

Esperado: `237 passed`.

---

### Task 9: Relatório de qualidade ao fim da execução

Hoje, terminada a classificação, não há nenhum resumo. Para comparar motores e modelos, o usuário precisa ver, numa tela só: o que rodou, quanto demorou, e como ficou a qualidade.

Tudo que o relatório precisa **já está no banco**: `peca.confianca` (`alta`/`media`/`baixa`), tipo, data, `arquivo.status`, lacunas de folhas. Nada de modelo de dados novo.

**Files:**
- Create: `gclaude_indexer/qualidade.py`
- Modify: `gclaude_indexer/web/app.py` (contexto de `tela_resultado` + rota de fragmento)
- Modify: `gclaude_indexer/web/templates/resultado.html`
- Modify: `gclaude_indexer/web/templates/execucao.html` (aviso ao concluir)
- Modify: `gclaude_indexer/web/static/estilo.css`
- Modify: `gclaude_indexer/web/i18n.py`
- Modify: `tests/test_fase13.py`

**Interfaces:**
- Produces: `resumo_qualidade(conn, config) -> dict` com chaves:
  `motor`, `modelo`, `total_pecas`, `confianca` (`{"alta": int, "media": int, "baixa": int}`), `sem_tipo`, `sem_data`, `sem_resumo`, `arquivos_falhados`, `janelas_pendentes`, `lacunas`, `pontuacao` (0-100).

- [ ] **Step 1: Escrever o teste que falha**

```python
# --- Tarefa 9: relatório de qualidade --------------------------------------


def test_resumo_de_qualidade_conta_confianca_e_lacunas(cliente, tmp_path):
    from gclaude_indexer.catalogo import buscar_projeto
    from gclaude_indexer.projeto import carregar_projeto
    from gclaude_indexer.qualidade import resumo_qualidade

    projeto_id = _criar_projeto(cliente, tmp_path)
    cliente.post(f"/projetos/{projeto_id}/executar-tudo")
    for etapa in ("varredura", "conversao", "extracao", "janelas", "classificacao"):
        _esperar_etapa_terminar(projeto_id, etapa, timeout=60)

    config, conn = carregar_projeto(buscar_projeto(projeto_id).pasta_saida)
    try:
        resumo = resumo_qualidade(conn, config)
    finally:
        conn.close()

    assert resumo["total_pecas"] >= 1
    assert set(resumo["confianca"]) == {"alta", "media", "baixa"}
    assert sum(resumo["confianca"].values()) == resumo["total_pecas"]
    assert resumo["motor"] == "regras"
    assert 0 <= resumo["pontuacao"] <= 100


def test_resumo_de_qualidade_em_projeto_vazio_nao_quebra(cliente, tmp_path):
    from gclaude_indexer.catalogo import buscar_projeto
    from gclaude_indexer.projeto import carregar_projeto
    from gclaude_indexer.qualidade import resumo_qualidade

    projeto_id = _criar_projeto(cliente, tmp_path)
    config, conn = carregar_projeto(buscar_projeto(projeto_id).pasta_saida)
    try:
        resumo = resumo_qualidade(conn, config)
    finally:
        conn.close()

    assert resumo["total_pecas"] == 0
    assert resumo["pontuacao"] == 0, "sem peças não há qualidade a pontuar"


def test_tela_de_resultado_mostra_o_relatorio_de_qualidade(cliente, tmp_path):
    projeto_id = _criar_projeto(cliente, tmp_path)
    cliente.post(f"/projetos/{projeto_id}/executar-tudo")
    for etapa in ("varredura", "conversao", "extracao", "janelas", "classificacao"):
        _esperar_etapa_terminar(projeto_id, etapa, timeout=60)

    corpo = cliente.get(f"/projetos/{projeto_id}/resultado").text
    assert 'class="qualidade-caixa"' in corpo
    assert "regras" in corpo
```

- [ ] **Step 2: Rodar para confirmar que falha**

- [ ] **Step 3: Criar `gclaude_indexer/qualidade.py`**

```python
"""Resumo de qualidade de uma execução, para comparar motores e modelos.

Tudo vem do que o pipeline já grava — `peca.confianca`, tipo, data, status de
arquivo e lacunas de folhas. Não há modelo de dados novo: o objetivo é
permitir rodar o mesmo acervo com motores diferentes e comparar os números
lado a lado.

**Sobre a pontuação:** é uma síntese das medições abaixo, útil para comparar
execuções do mesmo acervo entre si. Ela mede a *autoconfiança declarada* do
motor e o quanto ele preencheu os campos — não mede acerto real, que exigiria
um gabarito conferido à mão. Um motor pode ir bem aqui e classificar errado.
"""

from __future__ import annotations

from .config import ConfigProjeto

_PESOS = {"alta": 1.0, "media": 0.6, "baixa": 0.2}


def resumo_qualidade(conn, config: ConfigProjeto) -> dict:
    total_pecas = conn.execute("SELECT COUNT(*) FROM peca").fetchone()[0]

    confianca = {"alta": 0, "media": 0, "baixa": 0}
    for nivel, quantidade in conn.execute(
        "SELECT confianca, COUNT(*) FROM peca GROUP BY confianca"
    ):
        if nivel in confianca:
            confianca[nivel] = quantidade

    def _contar_nulos(coluna: str) -> int:
        return conn.execute(
            f"SELECT COUNT(*) FROM peca WHERE {coluna} IS NULL OR TRIM({coluna}) = ''"
        ).fetchone()[0]

    sem_tipo = _contar_nulos("tipo")
    sem_data = _contar_nulos("data")
    sem_resumo = _contar_nulos("resumo")

    arquivos_falhados = conn.execute(
        "SELECT COUNT(*) FROM arquivo WHERE status = 'falhou'"
    ).fetchone()[0]
    janelas_pendentes = conn.execute(
        "SELECT COUNT(*) FROM janela WHERE status = 'pendente'"
    ).fetchone()[0]

    from .artefatos import pendencias
    lacunas = len(pendencias(conn).get("lacunas", {}) or {})

    if total_pecas == 0:
        pontuacao = 0
    else:
        peso_confianca = sum(_PESOS[n] * q for n, q in confianca.items()) / total_pecas
        preenchimento = 1 - ((sem_tipo + sem_data) / (2 * total_pecas))
        penalidade = 0.1 if (janelas_pendentes or arquivos_falhados or lacunas) else 0.0
        pontuacao = int(round(max(0.0, min(1.0, 0.7 * peso_confianca + 0.3 * preenchimento - penalidade)) * 100))

    return {
        "motor": config.motor_classificacao,
        "modelo": config.modelo_local,
        "total_pecas": total_pecas,
        "confianca": confianca,
        "sem_tipo": sem_tipo,
        "sem_data": sem_data,
        "sem_resumo": sem_resumo,
        "arquivos_falhados": arquivos_falhados,
        "janelas_pendentes": janelas_pendentes,
        "lacunas": lacunas,
        "pontuacao": pontuacao,
    }
```

> **Confirme os nomes reais das colunas de `peca`** (`tipo`, `data`, `resumo`, `confianca`) no schema antes de rodar. Se algum for diferente, ajuste — não presuma.

- [ ] **Step 4: Exibir na tela de Resultado**

Acrescente `"qualidade": resumo_qualidade(conn, config)` ao contexto de `tela_resultado` e um bloco `.qualidade-caixa` no `resultado.html`, com: motor e modelo usados, total de peças, a distribuição de confiança em três barras, os campos não preenchidos, e a pontuação em destaque.

**Inclua na tela, em texto:** que a pontuação mede autoconfiança e preenchimento, não acerto real. Sem isso o número vira uma promessa que ele não cumpre — o erro que a Fase 12 cometeu quatro vezes.

- [ ] **Step 5: Avisar ao concluir**

Na tela de Execução, quando todas as etapas estiverem concluídas, mostre um aviso com o resumo curto (peças, pontuação) e um link para o Resultado. O fragmento de etapas já é recarregado a cada 2s — acrescente o aviso a esse fragmento quando `proxima_etapa_pendente(...)` for `None` e houver peças.

- [ ] **Step 6: Chaves de tradução, testes e suíte**

Esperado: `240 passed`.

---

### Task 10: A barra da varredura fecha em 100% com arquivos duplicados

Defeito medido na Fase 12 e deixado pendente: arquivos com conteúdo idêntico são pulados por hash em `varredura.py` e nunca entram na tabela, então o numerador fica abaixo do denominador. Medido: 3 PDFs + 1 cópia → **75%**.

**Files:**
- Modify: `gclaude_indexer/varredura.py`
- Modify: `tests/test_fase13.py`

- [ ] **Step 1: Escrever o teste que falha**

```python
# --- Tarefa 10: duplicatas não travam a barra ------------------------------


def test_varredura_registra_duplicata_em_vez_de_sumir_com_ela(cliente, tmp_path):
    import shutil
    from gclaude_indexer.catalogo import buscar_projeto
    from gclaude_indexer.projeto import carregar_projeto

    nome = "Com duplicata"
    origem = tmp_path / "origem" / nome.replace(" ", "_")
    (origem / "volume_1").mkdir(parents=True)
    _pdf(origem / "volume_1" / "a.pdf", "OFÍCIO No 1\nTexto suficiente para não acionar OCR.\n10/01/2024")
    shutil.copy(origem / "volume_1" / "a.pdf", origem / "volume_1" / "copia_de_a.pdf")

    projeto_id = _criar_projeto(cliente, tmp_path, nome=nome)
    cliente.post(f"/projetos/{projeto_id}/executar-proxima")
    _esperar_etapa_terminar(projeto_id, "varredura")

    _config, conn = carregar_projeto(buscar_projeto(projeto_id).pasta_saida)
    try:
        total = conn.execute("SELECT COUNT(*) FROM arquivo").fetchone()[0]
        duplicatas = conn.execute("SELECT COUNT(*) FROM arquivo WHERE status = 'duplicado'").fetchone()[0]
    finally:
        conn.close()

    assert total == 2, "a duplicata precisa existir na tabela para a barra fechar em 100%"
    assert duplicatas == 1
```

- [ ] **Step 2: Rodar para confirmar que falha**

Esperado: FAIL — `assert 1 == 2`.

- [ ] **Step 3: Implementar**

Em `varredura.py`, no ramo que hoje faz `resultado.pulados += 1; continue` para conteúdo já conhecido sob outro caminho, **insira a linha com `status = 'duplicado'`** em vez de descartá-la, mantendo o contador de pulados. Assim o inventário reflete a pasta, o numerador alcança o denominador, e o usuário passa a ver quais arquivos eram cópias.

**Confirme que `'duplicado'` não quebra nada a jusante:** `conversao.py` seleciona `status = 'descoberto'` e `extracao.py` seleciona `('convertido','extraido')` — nenhum dos dois pega `'duplicado'`, que é o comportamento desejado. Verifique também `_status_etapas` em `estado_etapas.py`, que conta `total_arquivos` sem filtrar status: decida se a contagem exibida deve incluir as duplicatas e **documente**.

- [ ] **Step 4: Rodar a suíte inteira e conferir a barra**

Esperado: `241 passed`. Depois, no navegador, rode um projeto com uma cópia idêntica e confirme que a barra da varredura chega a 100%.

---

### Task 11: Infraestrutura dos quatro layouts

O sistema tem quatro **paletas** (Fase 12), não quatro **designs**. Esta tarefa cria a estrutura; a seguinte desenha as identidades.

**Decisão de arquitetura, e o porquê:** os quatro layouts compartilham **os mesmos templates**. Duplicar `execucao.html` em quatro versões significaria aplicar toda correção futura quatro vezes — e esta é a segunda fase seguida a corrigir a mesma tela. A variação vem de um atributo `data-layout` no `<html>` e de uma folha `layouts.css` que reorganiza grade, densidade, tipografia e ornamento. Isso limita o que é possível (não dá para mover um bloco para outra tela), mas o que é possível cobre identidades genuinamente distintas.

**Files:**
- Create: `gclaude_indexer/web/layout.py`
- Create: `gclaude_indexer/web/static/layouts.css`
- Modify: `gclaude_indexer/web/app.py` (`render`, rota de preferência)
- Modify: `gclaude_indexer/web/templates/base.html`
- Modify: `gclaude_indexer/web/i18n.py`
- Modify: `tests/test_fase13.py`

**Interfaces:**
- Produces: `LAYOUTS_DISPONIVEIS: tuple[str, ...]` = `("padrao", "tecnico", "editorial", "compacto")`; `LAYOUT_PADRAO = "padrao"`; `layout_valido(v) -> str`; cookie `layout`.
- Espelha `tema.py` de propósito: quem entender um entende o outro.

- [ ] **Step 1: Escrever o teste que falha**

```python
# --- Tarefa 11: infraestrutura de layouts ----------------------------------


def test_layout_valido_aceita_os_quatro_e_recusa_desconhecido():
    from gclaude_indexer.web.layout import LAYOUTS_DISPONIVEIS, LAYOUT_PADRAO, layout_valido

    assert LAYOUTS_DISPONIVEIS == ("padrao", "tecnico", "editorial", "compacto")
    for nome in LAYOUTS_DISPONIVEIS:
        assert layout_valido(nome) == nome
    assert layout_valido("inexistente") == LAYOUT_PADRAO
    assert layout_valido(None) == LAYOUT_PADRAO


def test_cabecalho_traz_seletor_de_layout(cliente):
    corpo = cliente.get("/projetos").text
    assert 'name="layout"' in corpo
    for nome in ("padrao", "tecnico", "editorial", "compacto"):
        assert f'<option value="{nome}"' in corpo


def test_escolher_layout_aplica_no_html(cliente):
    resposta = cliente.post("/preferencias/layout", data={"layout": "editorial"}, follow_redirects=False)
    assert resposta.status_code in (302, 303)
    assert 'data-layout="editorial"' in cliente.get("/projetos").text


def test_layout_e_tema_sao_independentes(cliente):
    cliente.post("/preferencias/layout", data={"layout": "tecnico"}, follow_redirects=False)
    cliente.post("/preferencias/tema", data={"tema": "sepia"}, follow_redirects=False)
    corpo = cliente.get("/projetos").text
    assert 'data-layout="tecnico"' in corpo
    assert 'data-tema="sepia"' in corpo
```

- [ ] **Step 2: Rodar para confirmar que falha**

- [ ] **Step 3: Criar `gclaude_indexer/web/layout.py`**

```python
"""Layout da interface — a estrutura, separada da paleta (`tema.py`).

Quatro identidades sobre os **mesmos templates**: a variação vem de
`data-layout` no `<html>` e das regras em `static/layouts.css`. Duplicar os
templates por layout multiplicaria por quatro o custo de toda correção
futura, e a interface já passou por duas fases seguidas de correção.

Ortogonal ao tema: 4 layouts × 4 paletas, escolhidos em seletores separados.
"""

from __future__ import annotations

LAYOUT_PADRAO = "padrao"
LAYOUTS_DISPONIVEIS: tuple[str, ...] = ("padrao", "tecnico", "editorial", "compacto")
NOME_COOKIE_LAYOUT = "layout"


def layout_valido(layout: str | None) -> str:
    return layout if layout in LAYOUTS_DISPONIVEIS else LAYOUT_PADRAO
```

- [ ] **Step 4: Ligar no `render` e no `base.html`**

Em `app.py`, no `render()`, leia o cookie e injete `layout_atual` e `layouts_disponiveis`. Acrescente a rota `POST /preferencias/layout`, espelhando `escolher_tema` (que já normaliza com `tema_valido`).

Em `base.html`: `data-layout="{{ layout_atual }}"` no `<html>`, `<link rel="stylesheet" href="/static/layouts.css">` depois do `estilo.css`, e um `<select name="layout">` ao lado do de tema.

- [ ] **Step 5: Criar `layouts.css` com o esqueleto**

Só a estrutura nesta tarefa — as identidades vêm na Tarefa 12:

```css
/* Layouts: variam estrutura, densidade e tipografia sobre os mesmos
   templates. A cor fica com os temas (`estilo.css`) — um layout nunca
   define `--cor-*`, senão as 16 combinações deixam de ser previsíveis. */

html[data-layout="padrao"] { /* identidade atual, sem alteração */ }
html[data-layout="tecnico"] { }
html[data-layout="editorial"] { }
html[data-layout="compacto"] { }
```

- [ ] **Step 6: Rodar testes e suíte**

Esperado: `245 passed`.

---

### Task 12: As quatro identidades visuais

Agora o desenho. Referência: `prompting_for_frontend_aesthetics.ipynb` do cookbook, cujo princípio central é fugir do genérico — tipografia distintiva, comprometimento com uma estética, profundidade em vez de fundo chapado.

**Restrição que a referência não prevê:** o sistema é **offline**. Google Fonts está fora. O caráter tipográfico tem de sair de fontes já presentes no Windows — e há boas: **Georgia**, **Constantia**, **Cambria** (serifadas), **Corbel**, **Candara**, **Segoe UI Variable** (sem serifa), **Cascadia Mono**, **Consolas** (monoespaçadas). Nenhum layout pode usar Arial, Inter ou Roboto.

**Files:**
- Modify: `gclaude_indexer/web/static/layouts.css`
- Modify: `tests/test_fase13.py`

**As quatro identidades:**

| Layout | Caráter | Tipografia | Estrutura |
|---|---|---|---|
| `padrao` | O atual, intocado — quem gosta não perde | herda | herda |
| `tecnico` | Painel de instrumentos, denso, para acompanhar execução longa | Cascadia Mono / Consolas em números e tabelas; Segoe UI no texto | linhas compactas, tabelas com listras, números tabulares alinhados, cartões de recurso lado a lado |
| `editorial` | Leitura longa de acervo, espaçoso e calmo | Constantia / Georgia nos títulos e no corpo | coluna de leitura com largura máxima, entrelinha generosa, títulos com hierarquia forte, tabelas sem grade |
| `compacto` | Máximo de informação por tela, para acervo grande | Corbel / Candara, tamanhos menores | tudo em uma tela sem rolagem quando possível, cartões em grade densa, ornamento mínimo |

- [ ] **Step 1: Escrever o teste que falha**

```python
# --- Tarefa 12: identidades visuais ----------------------------------------


def test_cada_layout_define_regras_proprias():
    from pathlib import Path
    import gclaude_indexer.web.app as app_mod

    css = (Path(app_mod.RAIZ_WEB) / "static" / "layouts.css").read_text(encoding="utf-8")
    for nome in ("tecnico", "editorial", "compacto"):
        bloco = css.split(f'html[data-layout="{nome}"]', 1)
        assert len(bloco) > 1, f"layout {nome} sem regra"
    # cada um precisa de identidade própria, não só um seletor vazio
    assert css.count("font-family") >= 3, "os layouts precisam variar tipografia, não só espaçamento"


def test_layouts_nao_redefinem_cores():
    """Cor é responsabilidade do tema. Um layout que defina --cor-* quebra a
    previsibilidade das 16 combinações layout × paleta."""
    import re
    from pathlib import Path
    import gclaude_indexer.web.app as app_mod

    css = (Path(app_mod.RAIZ_WEB) / "static" / "layouts.css").read_text(encoding="utf-8")
    definicoes = re.findall(r"(--cor-[a-z0-9-]+)\s*:", css)
    assert not definicoes, f"layouts.css não pode definir cores: {definicoes}"


def test_nenhum_layout_usa_fonte_generica_ou_remota():
    from pathlib import Path
    import gclaude_indexer.web.app as app_mod

    css = (Path(app_mod.RAIZ_WEB) / "static" / "layouts.css").read_text(encoding="utf-8")
    baixo = css.lower()
    for proibida in ("inter", "roboto", "arial", "fonts.googleapis", "fonts.gstatic", "@import url("):
        assert proibida not in baixo, f"proibido no sistema offline: {proibida}"
```

- [ ] **Step 2: Rodar para confirmar que falha**

- [ ] **Step 3: Desenhar os três layouts novos**

Escreva as regras em `layouts.css`. Diretrizes obrigatórias:

- **Só estrutura, densidade, tipografia e ornamento.** Nenhum `--cor-*`.
- **Nada de `@import` nem host externo.** Fontes só do sistema, com pilha de fallback: `font-family: "Cascadia Mono", Consolas, ui-monospace, monospace;`.
- Use os tokens de cor existentes (`var(--cor-borda)` etc.) para bordas e fundos — assim cada layout funciona nas quatro paletas.
- **Movimento com parcimônia:** uma transição suave no carregamento da tabela de etapas é bem-vinda; animação em elemento que atualiza a cada 2s (log, gráficos) causa tremulação — não faça.
- Cuide de `.log-caixa`, `.recursos-grade`, `.tabela`, `.familia-extensoes` e `.progresso-caixa`: são os blocos que mais mudam de caráter entre os layouts.

- [ ] **Step 4: Conferir os quatro layouts nas quatro paletas — 16 combinações**

Suba o servidor e percorra as combinações na tela de Execução, que é a mais densa. Procure por: texto ilegível, tabela estourando a largura, gráfico de canvas cortado, log sem contraste. **Capture ao menos uma tela de cada layout** e anexe ao relatório.

Isto não é opcional: nenhum teste verifica aparência, e a Fase 12 entregou uma funcionalidade quebrada com teste verde justamente por pular a conferência visual.

- [ ] **Step 5: Rodar a suíte**

Esperado: `248 passed`.

---

## Self-Review

**1. Cobertura dos sete pedidos.** (1) GPU para IA local → **nenhuma tarefa: já funciona**, verificado e documentado na tabela de fatos. (2) GPU nas demais etapas → **nenhuma tarefa: inaplicável**, com o porquê registrado. (3) Monitor universal + temperatura + potência + clocks → Tarefas 1, 2, 3 e 4. (4) "Todos" exclusivo e OpenRouter fora → Tarefas 5 e 6. (5) Rolagem do log → Tarefa 7. (6) Relatório de qualidade → Tarefa 9, com a 8 como pré-requisito. (7) Quatro designs → Tarefas 11 e 12. Mais a Tarefa 10, que fecha o defeito das duplicatas herdado da Fase 12.

**2. Placeholders.** Nenhum. Há **um erro deliberado** no Step 5 da Tarefa 3 (`SENSORES_DISPONIVEIS` como `property` de módulo, que não funciona), sinalizado no próprio texto — se passar despercebido, a revisão pega.

**3. Consistência.** `layout.py` espelha `tema.py`; `contadores_windows.py` e `sensores.py` seguem a mesma regra de nunca levantar e nunca devolver zero por desconhecido; `qualidade.py` só lê o que já existe. A Tarefa 8 muda o comportamento que a 9 depende, e vem antes.

**4. Ordem e dependências.** 1 → 2 → 3 → 4 (telemetria, encadeada). 8 → 9 (o modelo precisa valer antes de comparar). 11 → 12 (infraestrutura antes do desenho). As Tarefas 5, 6, 7 e 10 são independentes e podem entrar em qualquer ponto.

**5. Riscos assumidos.** A Tarefa 3 depende de uma DLL de terceiros e de privilégio de administrador; o plano exige que o módulo funcione degradando quando faltarem, e que o implementador **relate** o resultado nos dois modos em vez de presumir. A Tarefa 12 é a única sem verificação automatizável de qualidade — por isso o Step 4 dela é obrigatório e pede capturas.

**6. Contagens de teste.** Os totais (`224`, `227`, …, `248`) supõem que nenhum teste existente seja removido. Se a Tarefa 6 ou a 8 exigirem reescrever testes da Fase 12, recalcule — o que não pode variar é o número de falhas: sempre zero.

---

# Adendo — tarefas 13 a 15

Acrescentadas depois que o usuário esclareceu o objetivo: **o sistema será instalado em qualquer computador e deve extrair o máximo do hardware que encontrar, entregando a melhor qualidade no menor tempo — e o relatório precisa servir de benchmark entre modelos, medindo tempo e qualidade.**

Isso reposiciona dois pedidos que o plano original havia descartado:

- O item "GPU independente de fabricante" **não** era sobre esta máquina (onde já funciona), e sim sobre **a próxima**. Vira trabalho de instalador — Tarefa 13.
- O item "priorizar GPU em todas as etapas" continua inaplicável **como GPU**, mas o que ele quer — velocidade — é alcançável por **paralelismo**, que hoje não existe. Tarefa 14.

---

### Task 13: Instalador que prepara qualquer máquina sozinho

Hoje `instalar.ps1` cria o venv, instala os pacotes Python e **apenas avisa** quando Tesseract ou Ghostscript faltam, imprimindo o comando `winget` para o usuário rodar à mão. Não sabe nada sobre Ollama, sobre modelo, nem sobre runtime de GPU.

Numa máquina nova isso significa: o usuário instala, abre, e o sistema não classifica — sem dizer o que falta nem resolver.

**Files:**
- Modify: `instalar.ps1`
- Create: `gclaude_indexer/diagnostico_instalacao.py`
- Modify: `gclaude_indexer/web/app.py` (tela "Sobre" mostra o diagnóstico)
- Modify: `gclaude_indexer/web/templates/sobre.html`
- Modify: `gclaude_indexer/web/i18n.py`
- Modify: `tests/test_fase13.py`

**Interfaces:**
- Produces: `verificar_instalacao() -> list[dict]` — um item por dependência, com `{"chave", "presente": bool, "versao": str | None, "obrigatoria": bool, "comando_instalar": str | None}`. Cobre: `python`, `tesseract`, `tessdata_por`, `ghostscript`, `ollama`, `modelo_padrao`, `runtime_gpu`. **Nunca levanta.**

- [ ] **Step 1: Escrever o teste que falha**

```python
# --- Tarefa 13: instalacao em maquina nova ---------------------------------


def test_diagnostico_lista_todas_as_dependencias():
    from gclaude_indexer.diagnostico_instalacao import verificar_instalacao

    itens = {i["chave"]: i for i in verificar_instalacao()}
    for chave in ("python", "tesseract", "ghostscript", "ollama", "modelo_padrao", "runtime_gpu"):
        assert chave in itens, f"faltou diagnosticar {chave}"
    for item in itens.values():
        assert isinstance(item["presente"], bool)
        assert "obrigatoria" in item
        if not item["presente"] and item["obrigatoria"]:
            assert item["comando_instalar"], f"{item['chave']} ausente sem comando de instalacao"


def test_diagnostico_nunca_levanta(monkeypatch):
    import gclaude_indexer.diagnostico_instalacao as dm

    monkeypatch.setattr(dm.shutil, "which", lambda _n: (_ for _ in ()).throw(OSError("boom")))
    itens = dm.verificar_instalacao()
    assert isinstance(itens, list) and itens, "o diagnostico tem de degradar, nao explodir"


def test_tela_sobre_mostra_o_diagnostico(cliente):
    corpo = cliente.get("/sobre").text
    assert 'class="diagnostico-instalacao"' in corpo
    assert "tesseract" in corpo.lower()
```

- [ ] **Step 2: Rodar para confirmar que falha**

- [ ] **Step 3: Criar `gclaude_indexer/diagnostico_instalacao.py`**

Um item por dependência. Regras:

- `tesseract` — `shutil.which`; obrigatória. Verifique também **`tessdata_por`**: ter o binário sem o idioma português não serve. Use `tesseract --list-langs`.
- `ghostscript` — `gswin64c`/`gswin32c`/`gs`; obrigatória para OCR.
- `ollama` — `shutil.which`; **não obrigatória** (sem ela o sistema cai no motor de regras, que funciona).
- `modelo_padrao` — consulta `/api/tags` e procura `MODELO_LOCAL_PADRAO`. Reaproveite `modelos_ollama.listar_modelos_instalados()`, não escreva outra consulta.
- `runtime_gpu` — ver Step 5.

Cada item ausente traz o `comando_instalar` correspondente (`winget install --id ...`, `ollama pull ...`), para a tela poder exibi-lo e o instalador executá-lo.

- [ ] **Step 4: Instalador passa a instalar, não só avisar**

Em `instalar.ps1`, troque os blocos que só imprimem o comando por instalação de fato, **com confirmação**:

```powershell
function Instalar-SeAusente {
    param(
        [Parameter(Mandatory)][string]$Nome,
        [Parameter(Mandatory)][string[]]$Binarios,
        [Parameter(Mandatory)][string]$IdWinget,
        [switch]$Obrigatoria
    )
    if (Find-Comando $Binarios) { Write-Host "$Nome OK." -ForegroundColor Green; return $true }

    Write-Host "$Nome nao encontrado." -ForegroundColor Yellow
    if (-not $AutoInstalar) {
        $r = Read-Host "Instalar agora com winget? (S/N)"
        if ($r -notmatch '^[SsYy]') { Write-Host "  pulado." ; return $false }
    }
    winget install --id $IdWinget -e --silent --accept-package-agreements --accept-source-agreements
    return [bool](Find-Comando $Binarios)
}
```

Acrescente o parâmetro `-AutoInstalar` (sem pergunta, para instalação desassistida) ao `param()` do script. Instale Tesseract, Ghostscript e — **perguntando à parte, porque é download grande** — Ollama e o modelo padrão.

**Regras inegociáveis deste passo:**
- Nunca instalar nada **sem confirmação**, exceto com `-AutoInstalar` explícito.
- Se o `winget` não existir na máquina, **não tente outro caminho de download**: informe o comando e siga. Baixar binário de URL arbitrária não entra neste projeto.
- O instalador continua **idempotente**: rodar duas vezes não pode quebrar nada.

- [ ] **Step 5: Runtime de GPU — detectar e configurar, não "instalar mods"**

Esta é a parte que exige critério. O que o Ollama precisa para usar cada GPU:

| GPU | Situação |
|---|---|
| NVIDIA | driver recente basta; o Ollama traz o runtime CUDA |
| AMD RDNA2+ | driver recente basta |
| **AMD RDNA1** (RX 5700 XT) | precisa `HSA_OVERRIDE_GFX_VERSION=10.3.0`, ou Vulkan |
| Intel Arc / iGPU | Vulkan |
| sem GPU | CPU, funciona |

O instalador **detecta** a GPU (por `Win32_VideoController`, que já é usado em `hardware.py`) e, quando for AMD RDNA1, grava a variável de ambiente de usuário:

```powershell
[Environment]::SetEnvironmentVariable("HSA_OVERRIDE_GFX_VERSION", "10.3.0", "User")
```

**Não** instale ROCm, não baixe "mods", não troque runtime do Ollama. Nesta máquina o caminho Vulkan já entrega 100% de GPU, e o log mostra a via ROCm falhando por timeout e caindo para CPU — mexer nisso seria regressão. Se a GPU não for reconhecida, o diagnóstico diz isso e o sistema roda em CPU, que funciona.

Registre no diagnóstico o que foi detectado e o que foi configurado.

- [ ] **Step 6: Mostrar o diagnóstico na tela "Sobre"**

Uma tabela com cada dependência, presente ou não, versão, e — para as ausentes — o comando de instalação em campo selecionável. É o que permite ao usuário resolver sozinho numa máquina nova sem abrir o terminal às cegas.

- [ ] **Step 7: Testes, suíte e verificação real**

Rode `instalar.ps1` nesta máquina (onde tudo já está presente) e confirme que ele **não reinstala nada** e termina relatando tudo OK. Esperado: `251 passed`.

---

### Task 14: Paralelismo — o maior ganho de tempo da fase

`conversao.py:288` e `extracao.py:122` processam **um arquivo por vez**, e `_rodar_ocrmypdf` invoca o `ocrmypdf` **sem `--jobs`**. Numa máquina de 16 núcleos lógicos, o OCR de um acervo usa essencialmente um.

**Files:**
- Create: `gclaude_indexer/paralelismo.py`
- Modify: `gclaude_indexer/conversao.py`, `gclaude_indexer/extracao.py`
- Modify: `gclaude_indexer/config.py` (campo novo)
- Modify: `gclaude_indexer/web/templates/novo_projeto.html`, `i18n.py`
- Modify: `tests/test_fase13.py`

**Interfaces:**
- Produces: `trabalhadores_para(modo: str) -> int`. `"automatico"` devolve `max(1, fisicos - 1)`, deixando um núcleo para a interface; `"maximo"` devolve `fisicos`; `"economico"` devolve 1 (comportamento atual).
- Campo novo em `ConfigProjeto`: `paralelismo: str = "automatico"`.

- [ ] **Step 1: Escrever o teste que falha**

```python
# --- Tarefa 14: paralelismo -------------------------------------------------


def test_trabalhadores_respeitam_o_modo(monkeypatch):
    from gclaude_indexer import paralelismo

    monkeypatch.setattr(paralelismo, "_nucleos_fisicos", lambda: 8)
    assert paralelismo.trabalhadores_para("economico") == 1
    assert paralelismo.trabalhadores_para("automatico") == 7, "deixa um nucleo para a interface"
    assert paralelismo.trabalhadores_para("maximo") == 8
    assert paralelismo.trabalhadores_para("desconhecido") == 7


def test_trabalhadores_nunca_menor_que_um(monkeypatch):
    from gclaude_indexer import paralelismo

    monkeypatch.setattr(paralelismo, "_nucleos_fisicos", lambda: 1)
    for modo in ("economico", "automatico", "maximo"):
        assert paralelismo.trabalhadores_para(modo) >= 1


def test_conversao_paralela_processa_todos_os_arquivos(cliente, tmp_path):
    """O ganho e de tempo, mas o resultado tem de ser identico ao sequencial."""
    from gclaude_indexer.catalogo import buscar_projeto
    from gclaude_indexer.projeto import carregar_projeto

    nome = "Paralelo"
    origem = tmp_path / "origem" / nome
    (origem / "volume_1").mkdir(parents=True)
    for i in range(1, 6):
        _pdf(origem / "volume_1" / f"p{i}.pdf", f"OFICIO No {i}\nTexto suficiente.\n1{i}/01/2024")

    projeto_id = _criar_projeto(cliente, tmp_path, nome=nome, paralelismo="maximo")
    cliente.post(f"/projetos/{projeto_id}/executar-tudo")
    for etapa in ("varredura", "conversao", "extracao"):
        _esperar_etapa_terminar(projeto_id, etapa, timeout=180)

    _config, conn = carregar_projeto(buscar_projeto(projeto_id).pasta_saida)
    try:
        convertidos = conn.execute(
            "SELECT COUNT(*) FROM arquivo WHERE status IN ('convertido','extraido')"
        ).fetchone()[0]
        falhas = conn.execute("SELECT COUNT(*) FROM arquivo WHERE status='falhou'").fetchone()[0]
    finally:
        conn.close()

    assert convertidos == 5, "paralelizar nao pode perder arquivo"
    assert falhas == 0
```

- [ ] **Step 2: Rodar para confirmar que falha**

- [ ] **Step 3: Criar `gclaude_indexer/paralelismo.py`**

```python
"""Quantos trabalhadores usar nas etapas limitadas por CPU.

A conversao (com OCR) e a extracao processavam um arquivo por vez, e o
`ocrmypdf` era chamado sem `--jobs` — numa maquina de 8 nucleos fisicos, o
OCR de um acervo inteiro usava um. E onde esta o maior ganho de tempo do
sistema.

Nucleos **fisicos**, nao logicos: OCR e renderizacao de PDF saturam a unidade
de execucao, e contar hyperthreads leva a disputa em vez de ganho.
"""

from __future__ import annotations

MODOS = ("economico", "automatico", "maximo")
MODO_PADRAO = "automatico"


def _nucleos_fisicos() -> int:
    try:
        import psutil
        return psutil.cpu_count(logical=False) or 1
    except Exception:
        import os
        return max(1, (os.cpu_count() or 2) // 2)


def trabalhadores_para(modo: str) -> int:
    fisicos = max(1, _nucleos_fisicos())
    if modo == "economico":
        return 1
    if modo == "maximo":
        return fisicos
    # automatico (e qualquer valor desconhecido): deixa um nucleo livre para a
    # interface continuar respondendo enquanto o acervo processa.
    return max(1, fisicos - 1)
```

- [ ] **Step 4: Paralelizar a conversão**

Duas mudanças, e a segunda é a mais barata:

**(a) `--jobs` no ocrmypdf.** Acrescente `"--jobs", str(jobs)` ao comando em `_rodar_ocrmypdf`, com `jobs` vindo do modo configurado. Sozinho isso já acelera cada arquivo.

**(b) Arquivos em paralelo.** Troque o `for linha in linhas` por um `concurrent.futures.ProcessPoolExecutor` com `trabalhadores_para(config.paralelismo)`.

**Cuidados obrigatórios — leia antes de escrever:**

- **Uma conexão SQLite por processo.** `sqlite3.Connection` não atravessa processo. O padrão que funciona: o pool devolve o **resultado** de cada arquivo (caminho, status, erro, páginas), e o **processo principal** grava no banco. Nunca passe `conn` para um worker.
- **`deve_parar` continua funcionando.** O botão de pausa não pode deixar de responder: verifique o sinal entre submissões e cancele os futuros pendentes.
- **Ordem de gravação não importa**, mas o commit por arquivo (Fase 11) precisa ser mantido, senão a barra de progresso volta a travar.
- Se `trabalhadores_para(...)` devolver 1, **use o caminho sequencial atual** — não pague o custo de criar processos para nada.
- No Windows o `ProcessPoolExecutor` usa `spawn`: a função do worker precisa ser de módulo (não lambda, não closure) e os argumentos precisam ser serializáveis.

Aplique o mesmo padrão em `extracao.py`.

- [ ] **Step 5: Expor a escolha no formulário**

Campo `paralelismo` em `ConfigProjeto` com default `"automatico"`, validado contra `MODOS`, e um `<select>` em `novo_projeto.html` com os três modos e descrições nos três idiomas — explicando que "máximo" deixa a máquina menos responsiva durante a execução.

- [ ] **Step 6: Medir o ganho — este passo é o ponto da tarefa**

Antes e depois, no mesmo acervo de teste (use ao menos 10 PDFs que exijam OCR). **Relate os dois tempos.** Se o paralelo não for mais rápido que o sequencial, a tarefa falhou — investigue antes de dar por concluída. Ganho esperado nesta máquina (8 físicos): substancial, mas sublinear, porque o disco também limita.

- [ ] **Step 7: Rodar a suíte**

Esperado: `254 passed`.

---

### Task 15: Benchmark — tempo e qualidade lado a lado

O relatório da Tarefa 9 responde "quão bem", mas o usuário quer comparar modelos também por **tempo**, e hoje nenhuma duração é registrada.

**Files:**
- Modify: `gclaude_indexer/db.py` (tabela `execucao`)
- Modify: `gclaude_indexer/web/execucao_bg.py` (gravar início e fim)
- Modify: `gclaude_indexer/qualidade.py` (incorporar tempo)
- Create: rota e template de comparação
- Modify: `tests/test_fase13.py`

**Interfaces:**
- Tabela nova `execucao`: `id`, `etapa`, `motor`, `modelo`, `iniciado_em`, `terminado_em`, `itens`, `ok`.
- Produces: `historico_execucoes(conn) -> list[dict]` e `comparar_execucoes(conn) -> list[dict]` — uma linha por (motor, modelo) com tempo total, itens/minuto, pontuação de qualidade e distribuição de confiança.

- [ ] **Step 1: Escrever o teste que falha**

```python
# --- Tarefa 15: benchmark ---------------------------------------------------


def test_execucao_registra_tempo_por_etapa(cliente, tmp_path):
    from gclaude_indexer.catalogo import buscar_projeto
    from gclaude_indexer.projeto import carregar_projeto

    projeto_id = _criar_projeto(cliente, tmp_path)
    cliente.post(f"/projetos/{projeto_id}/executar-proxima")
    _esperar_etapa_terminar(projeto_id, "varredura")

    _config, conn = carregar_projeto(buscar_projeto(projeto_id).pasta_saida)
    try:
        linhas = conn.execute(
            "SELECT etapa, iniciado_em, terminado_em, itens FROM execucao"
        ).fetchall()
    finally:
        conn.close()

    assert linhas, "nenhuma execucao registrada — sem isso nao ha benchmark"
    etapa, inicio, fim, itens = linhas[0]
    assert etapa == "varredura"
    assert fim is not None and fim >= inicio
    assert itens >= 1


def test_comparacao_agrupa_por_motor_e_modelo(cliente, tmp_path):
    from gclaude_indexer.catalogo import buscar_projeto
    from gclaude_indexer.projeto import carregar_projeto
    from gclaude_indexer.qualidade import comparar_execucoes

    projeto_id = _criar_projeto(cliente, tmp_path)
    cliente.post(f"/projetos/{projeto_id}/executar-tudo")
    for etapa in ("varredura", "conversao", "extracao", "janelas", "classificacao"):
        _esperar_etapa_terminar(projeto_id, etapa, timeout=120)

    _config, conn = carregar_projeto(buscar_projeto(projeto_id).pasta_saida)
    try:
        linhas = comparar_execucoes(conn)
    finally:
        conn.close()

    assert linhas
    for linha in linhas:
        for campo in ("motor", "modelo", "segundos_total", "itens_por_minuto", "pontuacao"):
            assert campo in linha, f"faltou {campo} na comparacao"
```

- [ ] **Step 2: Rodar para confirmar que falha**

- [ ] **Step 3: Tabela `execucao`**

Acrescente ao schema, em `db.py`, seguindo o estilo das tabelas existentes:

```sql
CREATE TABLE IF NOT EXISTS execucao (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    etapa         TEXT NOT NULL,
    motor         TEXT,
    modelo        TEXT,
    iniciado_em   TEXT NOT NULL,
    terminado_em  TEXT,
    itens         INTEGER NOT NULL DEFAULT 0,
    ok            INTEGER NOT NULL DEFAULT 0
);
```

**Bancos existentes precisam continuar abrindo.** O schema já usa `IF NOT EXISTS`; confirme que `inicializar_schema` é chamado ao carregar projeto antigo, e não só ao criar. Se não for, acrescente — e escreva um teste que abra um banco sem a tabela e confirme que ele passa a ter.

- [ ] **Step 4: Gravar tempo em `execucao_bg.py`**

No `corpo()` de `iniciar_etapa`, insira a linha ao começar e complete `terminado_em`, `itens` e `ok` no `finally` — junto de `terminado_em` da `TarefaEtapa`, que já existe desde a Fase 12. Grave `motor` e `modelo` a partir da config, para a comparação poder agrupar. Use uma **conexão própria**, como o resto do `corpo()` já faz.

- [ ] **Step 5: Comparação em `qualidade.py`**

`comparar_execucoes(conn)` agrupa por `(motor, modelo)` e devolve, para cada: tempo total, itens por minuto, pontuação de qualidade e distribuição de confiança.

**O que a tela precisa deixar explícito**, e é a diferença entre um benchmark honesto e um número enganoso:

- O tempo só é comparável **no mesmo acervo e na mesma máquina** — comparar acervos diferentes não significa nada.
- A pontuação mede **autoconfiança declarada e preenchimento**, não acerto real.
- Se o modo de paralelismo mudou entre execuções, os tempos **não** são comparáveis; registre o modo junto e avise quando diferirem.

- [ ] **Step 6: Tela de comparação**

Uma tabela na tela de Resultado, ordenável, uma linha por (motor, modelo), com as colunas acima. É isso que permite responder "o qwen3:8b vale o tempo a mais que o gemma4:e4b?".

- [ ] **Step 7: Testes, suíte e uma comparação real**

Rode o mesmo acervo com `regras`, depois com `local`+`gemma4:e4b`, depois com `local`+`qwen3:8b`, e **anexe a tabela resultante ao relatório**. É a prova de que o benchmark serve para o que foi pedido.

Esperado: `257 passed`.

---

## Ordem revisada

1 → 2 → 3 → 4 (telemetria) · 13 (instalador) · 14 (paralelismo) · 5, 6, 7, 10 (correções independentes) · 8 → 9 → 15 (qualidade e benchmark, nesta ordem) · 11 → 12 (layouts).

A Tarefa 15 depende da 9, que depende da 8. A 14 é independente de todas, mas quanto antes entrar, mais rápido ficam os testes das seguintes.
