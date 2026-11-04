# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Fase 35 — a RAM que o Ollama segurava e a parcela do modelo na placa.

Na 1.7.2, rodando um projeto, o usuário viu "VRAM usada:
9180 de 12272" e o llama-server com 8 GB de RAM, e leu isso como modelo
transbordando para a memória. Medido: 33/33 camadas na placa, 52 tokens/s,
e os 8 GB eram o *cache de prompts* que o llama-server mantém na RAM por
padrão (limite 8192 MiB), nunca reaproveitado aqui (16 de 16 janelas
começaram com `cached n_tokens = 0`). Duas correções: desligar esse cache
no servidor que este programa sobe (e no instalador), e mostrar na tela
quanto do modelo está na placa, para que o número da VRAM tenha contexto.
"""

from __future__ import annotations

from pathlib import Path

from tests.test_phase13 import _criar_projeto, cliente  # noqa: F401 — fixture

_RAIZ = Path(__file__).resolve().parent.parent

# --- Task 1: o cache de prompts na RAM fica desligado ------------------------


def test_o_servidor_do_ollama_nao_guarda_cache_de_prompts_na_ram():
    from gclaude_indexer.gpu_budget import SERVER_ENVIRONMENT, server_environment

    ambiente = server_environment({})
    assert ambiente["LLAMA_ARG_CACHE_RAM"] == "0"
    assert SERVER_ENVIRONMENT["LLAMA_ARG_CACHE_RAM"] == "0"

    # Quem definiu a variável na mão continua mandando nela.
    escolhido = server_environment({"LLAMA_ARG_CACHE_RAM": "4096"})
    assert escolhido["LLAMA_ARG_CACHE_RAM"] == "4096"


def _bloco_de_variaveis(script: str) -> str:
    inicio = script.index("$OllamaSettings = [ordered]@{")
    return script[inicio: script.index("}", inicio)]


def test_o_instalador_grava_a_mesma_variavel_e_para_o_runner_do_ollama():
    """`install.ps1` escreve as mesmas variáveis como ambiente do usuário
    (para o servidor que o Windows sobe sozinho), e ao trocá-las derruba o
    Ollama para que valham. O llama-server é filho do Ollama e pode
    sobreviver a um `Stop-Process -Force` do pai, segurando a VRAM do
    modelo e os 8 GB de cache: entra na lista, mas só o do próprio Ollama
    (outros programas também trazem um `llama-server.exe`), e cada
    processo é parado por si — numa pipeline só, a primeira falha pulava
    os demais."""
    script = (_RAIZ / "install.ps1").read_text(encoding="utf-8")
    bloco = _bloco_de_variaveis(script)
    assert '"LLAMA_ARG_CACHE_RAM"' in bloco and '"0"' in bloco.split("LLAMA_ARG_CACHE_RAM", 1)[1]

    marco = script.index("restarting Ollama so it picks the new values up")
    reinicio = script[marco - 1500: marco + 1500]
    assert '"llama-server"' in reinicio
    assert "lib\\ollama" in reinicio, "o runner é derrubado pelo caminho do executável, nunca só pelo nome"
    assert "foreach ($process in ($OllamaRunners + $OllamaProcesses))" in reinicio, \
        "um por vez, runner antes do servidor"

    # O desinstalador remove as variáveis que o instalador gravou — pela
    # mesma lista, senão a nova ficaria para trás na máquina do usuário.
    desinstalador = (_RAIZ / "uninstall.ps1").read_text(encoding="utf-8")
    assert '"LLAMA_ARG_CACHE_RAM"' in _bloco_de_variaveis(desinstalador)


# --- Task 2: a tela diz quanto do modelo está na placa -----------------------


def _ps(models):
    return {"models": models}


def test_parcela_do_modelo_na_placa_vem_do_api_ps(monkeypatch):
    from gclaude_indexer import gpu_budget

    inteiro = {"name": "qwen3.5:9b", "size": 5912815205, "size_vram": 5912815205}
    monkeypatch.setattr(gpu_budget, "_get_json", lambda url, payload=None, timeout=5.0: _ps([inteiro]))
    assert gpu_budget.loaded_model_share("http://x") == {
        "model": "qwen3.5:9b", "size_mb": 5638, "vram_mb": 5638,
    }

    dividido = {"name": "gemma4:12b-it-qat", "size": 8 * 1024**3, "size_vram": 6 * 1024**3}
    monkeypatch.setattr(gpu_budget, "_get_json", lambda url, payload=None, timeout=5.0: _ps([dividido]))
    assert gpu_budget.loaded_model_share("http://x") == {
        "model": "gemma4:12b-it-qat", "size_mb": 8192, "vram_mb": 6144,
    }

    # Ollama respondeu que não há nada carregado: é um fato (máquina no
    # motor de regras, ou antes da primeira janela), não leitura ausente.
    monkeypatch.setattr(gpu_budget, "_get_json", lambda url, payload=None, timeout=5.0: _ps([]))
    assert gpu_budget.loaded_model_share("http://x") == {"model": None, "size_mb": 0, "vram_mb": 0}

    monkeypatch.setattr(gpu_budget, "_get_json", lambda url, payload=None, timeout=5.0: None)
    assert gpu_budget.loaded_model_share("http://x") is None, "Ollama fora do ar = não medido"


def test_parcela_do_modelo_ignora_entrada_mal_formada(monkeypatch):
    from gclaude_indexer import gpu_budget

    torta = {"name": "x", "size": "muito", "size_vram": None}
    monkeypatch.setattr(gpu_budget, "_get_json", lambda url, payload=None, timeout=5.0: _ps([torta, "lixo"]))
    assert gpu_budget.loaded_model_share("http://x") == {"model": None, "size_mb": 0, "vram_mb": 0}


def test_a_leitura_do_modelo_e_curta_para_nao_atrasar_o_amostrador(monkeypatch):
    """O amostrador roda a cada 2 s; uma chamada que esperasse os 5 s
    padrão num Ollama travado atrasaria todo o painel."""
    from gclaude_indexer import gpu_budget

    prazos = []

    def finge(url, payload=None, timeout=5.0):
        prazos.append(timeout)
        return _ps([])

    monkeypatch.setattr(gpu_budget, "_get_json", finge)
    gpu_budget.loaded_model_share("http://x")
    assert prazos and max(prazos) <= 1.0


def test_amostra_de_recursos_traz_o_modelo_na_placa(monkeypatch):
    from gclaude_indexer import resources as resources_mod

    monkeypatch.setattr(resources_mod, "_sample_cpu_ram", lambda: (1.0, 2.0, 3, 4))
    monkeypatch.setattr(resources_mod, "_sample_gpu", lambda: (None, None, None))
    monkeypatch.setattr(
        resources_mod, "loaded_model_share",
        lambda url_base: {"model": "qwen3.5:9b", "size_mb": 5638, "vram_mb": 5638},
    )
    amostra = resources_mod.sample_resources()
    assert (amostra.model_name, amostra.model_size_mb, amostra.model_vram_mb) == ("qwen3.5:9b", 5638, 5638)

    monkeypatch.setattr(resources_mod, "loaded_model_share", lambda url_base: {"model": None, "size_mb": 0, "vram_mb": 0})
    amostra = resources_mod.sample_resources()
    assert (amostra.model_name, amostra.model_size_mb, amostra.model_vram_mb) == (None, 0, 0)

    monkeypatch.setattr(resources_mod, "loaded_model_share", lambda url_base: None)
    amostra = resources_mod.sample_resources()
    assert (amostra.model_name, amostra.model_size_mb, amostra.model_vram_mb) == (None, None, None)


def test_amostra_nao_cai_se_a_leitura_do_modelo_falhar(monkeypatch):
    from gclaude_indexer import resources as resources_mod

    def explode(url_base):
        raise RuntimeError("Ollama respondeu lixo")

    monkeypatch.setattr(resources_mod, "_sample_cpu_ram", lambda: (1.0, 2.0, 3, 4))
    monkeypatch.setattr(resources_mod, "_sample_gpu", lambda: (None, None, None))
    monkeypatch.setattr(resources_mod, "loaded_model_share", explode)
    amostra = resources_mod.sample_resources()
    assert amostra.model_vram_mb is None


def test_json_de_recursos_traz_o_modelo_na_placa(cliente, tmp_path):
    projeto_id = _criar_projeto(cliente, tmp_path)
    dados = cliente.get(f"/projects/{projeto_id}/run/resources").json()
    for campo in ("model_name", "model_size_mb", "model_vram_mb"):
        assert campo in dados, f"faltou {campo} no JSON de recursos"


def test_tela_mostra_o_modelo_na_placa_em_tres_idiomas():
    from gclaude_indexer.i18n import translate

    html = (_RAIZ / "gclaude_indexer/web/templates/run.html").read_text(encoding="utf-8")
    assert 'id="model-gpu"' in html and "t('resources.model_on_gpu')" in html
    depois = html.split('id="model-gpu"', 1)[1]
    assert "model_vram_mb" in depois and "model_size_mb" in depois, "o script preenche a linha nova"
    # 8151 de 8192 MB é um modelo dividido: arredondar diria "100%".
    assert "Math.floor(data.model_vram_mb" in depois
    # Tamanho 0 = "nenhum carregado", que não é "não medido".
    assert "t('resources.model_none')" in html and "MODEL_NONE_TEXT" in depois

    for chave in ("resources.model_on_gpu", "resources.model_none"):
        textos = {idioma: translate(idioma, chave) for idioma in ("pt", "en", "es")}
        assert len(set(textos.values())) == 3 and chave not in textos.values()
