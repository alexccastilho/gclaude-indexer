"""2.1.0: o formulário do projeto oferece "Mais rápido" e "Melhor qualidade"."""

from __future__ import annotations

import gclaude_indexer.web.rendering as rendering
from tests.test_phase9 import cliente  # noqa: F401
from gclaude_indexer.web import routes_projects


def test_formulario_mostra_os_dois_perfis_e_os_outros_modelos(cliente, monkeypatch):  # noqa: F811
    monkeypatch.setattr(routes_projects, "list_installed_models", lambda: ["gemma4:e4b", "ornith-1.5:9b", "qwen3.5:4b"])
    monkeypatch.setattr(routes_projects, "default_local_profile", lambda: "quality")
    corpo = cliente.get("/projects/new").text
    assert "Mais rápido (qwen3.5:4b)" in corpo and 'value="fast"' in corpo
    assert 'value="quality" selected' in corpo
    assert "Melhor qualidade, mais lento (ornith-1.5:9b)" in corpo
    # os modelos dos perfis não se repetem na lista dos outros
    assert corpo.count('value="qwen3.5:4b"') == 0 and corpo.count('value="ornith-1.5:9b"') == 0
    assert 'value="gemma4:e4b"' in corpo


def test_modelo_antigo_escolhido_continua_selecionado(monkeypatch):
    """Um projeto de antes da 2.1.0 com um nome de modelo não perde a escolha,
    mesmo que o modelo não esteja mais instalado."""
    import re

    fonte = (rendering.WEB_ROOT / "templates" / "new_project.html").read_text(encoding="utf-8")
    trecho = fonte[fonte.index("{% set chosen_model"):fonte.index("</select>", fonte.index("{% set chosen_model")) + 9]
    ambiente = rendering.templates.env
    html = ambiente.from_string(trecho).render(
        values={"local_model": "qwen3.5:9b"}, default_local_model="quality",
        local_model_profiles={"fast": "qwen3.5:4b", "quality": "ornith-1.5:9b"},
        local_models=[], t=lambda chave, **k: chave,
    )
    assert re.search(r'value="qwen3.5:9b"\s+selected', html)
    assert 'value="quality" selected' not in html


def test_execucao_pela_interface_leva_o_projeto_ao_motor(monkeypatch):
    """2.1.0: `run_classification` criava o `LocalEngine` sem `config` e sem
    `num_gpu`: o Tema, o tipo de acervo e as regras extras nunca chegavam ao
    prompt de uma execução da interface, e o modo "cpu" carregava o modelo
    inteiro na placa. Agora quem monta o motor é `classify_pending`."""
    from gclaude_indexer import engine_local, orchestrator
    from gclaude_indexer.config import ProjectConfig

    criados = []

    class MotorFalso:
        def __init__(self, **kw):
            criados.append(kw)
            raise RuntimeError("parar aqui")

    monkeypatch.setattr(
        orchestrator, "decide_engine", lambda *a, **k: orchestrator.EngineDecision("local", "qwen3.5:4b")
    )
    monkeypatch.setattr(engine_local, "LocalEngine", MotorFalso)
    config = ProjectConfig(name="x", source_folder=".", output_folder=".", processing_mode="cpu",
                           subject="Obras da escola municipal")
    try:
        orchestrator.run_classification(None, config)
    except RuntimeError:
        pass
    assert criados, "o motor não foi criado"
    assert criados[0]["config"] is config
    assert criados[0]["num_gpu"] == 0
