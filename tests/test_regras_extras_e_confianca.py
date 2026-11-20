"""2.0.0, tarefa 4: formulário enxuto.

"Revisar confiança baixa" deixou de existir e "Regras extras" saiu do
formulário de criação para a tela Instruções, sem perder o valor gravado."""

from __future__ import annotations

import json
import re

from gclaude_indexer.config import config_to_json, load_config
from gclaude_indexer.i18n import translate
from gclaude_indexer.project import load_project, save_project_config
from gclaude_indexer.managed_block import generated_part
from gclaude_indexer.web.app import EXTRA_RULES_MAX_LENGTH
from tests.test_phase42 import _web

HEADERS = {"Origin": "http://testserver"}


def _regras_gravadas(pasta):
    config, conn = load_project(pasta)
    conn.close()
    return config.extra_rules


def test_projeto_antigo_com_review_low_confidence_abre(tmp_path):
    origem = tmp_path / "origem"
    origem.mkdir()
    base = json.loads(config_to_json(load_config(
        {"name": "Antigo", "source_folder": str(origem), "output_folder": str(tmp_path / "saida")}
    )))
    base["review_low_confidence"] = True
    config = load_config(base)
    assert not hasattr(config, "review_low_confidence")
    assert "review_low_confidence" not in json.loads(config_to_json(config))


def test_formulario_de_criacao_nao_tem_mais_os_dois_campos(tmp_path, monkeypatch):
    cliente, _pid, _pasta = _web(tmp_path, monkeypatch)
    corpo = cliente.get("/projects/new").text
    assert 'name="review_low_confidence"' not in corpo
    assert 'name="extra_rules"' not in corpo


def test_post_forjado_com_campos_removidos_e_ignorado(tmp_path, monkeypatch):
    from tests.test_phase9 import _criar_projeto
    from gclaude_indexer.catalog import find_project

    cliente, _pid, _pasta = _web(tmp_path, monkeypatch)
    pid = _criar_projeto(
        cliente, tmp_path, nome="Forjado",
        extra_rules="regra forjada", review_low_confidence="on",
    )
    config, conn = load_project(find_project(pid).output_folder)
    conn.close()
    assert config.extra_rules == ""
    assert "review_low_confidence" not in json.loads(config_to_json(config))


def test_caixa_de_regras_extras_salva_e_aparece_nas_instrucoes(tmp_path, monkeypatch):
    cliente, pid, pasta = _web(tmp_path, monkeypatch)
    tela = cliente.get(f"/projects/{pid}/instructions")
    assert 'name="extra_rules"' in tela.text

    resposta = cliente.post(
        f"/projects/{pid}/instructions/extra-rules",
        data={"extra_rules": "Sempre cite o número do processo."}, headers=HEADERS,
    )
    assert resposta.status_code == 200
    assert translate("pt", "instructions.extra_rules.saved") in resposta.text
    assert "Sempre cite o número do processo." in resposta.text
    assert _regras_gravadas(pasta) == "Sempre cite o número do processo."



def test_endpoint_reescreve_o_arquivo_e_a_secao_some_ao_limpar(tmp_path, monkeypatch):
    """Confere o arquivo que o próprio endpoint regenera, sem objetos velhos."""
    from gclaude_indexer.artifacts import generate_project_instructions_md

    cliente, pid, pasta = _web(tmp_path, monkeypatch)
    config, conn = load_project(pasta)
    caminho = generate_project_instructions_md(conn, config, "pt")
    conn.close()
    titulo = translate("pt", "artifact.project_instructions.extra_rules_section")
    assert titulo not in generated_part(caminho)

    cliente.post(
        f"/projects/{pid}/instructions/extra-rules",
        data={"extra_rules": "Sempre cite o número do processo."}, headers=HEADERS,
    )
    bloco = generated_part(caminho)
    assert titulo in bloco and "Sempre cite o número do processo." in bloco

    cliente.post(f"/projects/{pid}/instructions/extra-rules", data={"extra_rules": "  "}, headers=HEADERS)
    assert _regras_gravadas(pasta) == ""
    bloco = generated_part(caminho)
    assert titulo not in bloco and "Sempre cite o número do processo." not in bloco


def test_regras_acima_do_teto_sao_recusadas_sem_cortar(tmp_path, monkeypatch):
    cliente, pid, pasta = _web(tmp_path, monkeypatch)
    cliente.post(f"/projects/{pid}/instructions/extra-rules", data={"extra_rules": "antes"}, headers=HEADERS)
    longo = "x" * (EXTRA_RULES_MAX_LENGTH + 1)
    resposta = cliente.post(f"/projects/{pid}/instructions/extra-rules", data={"extra_rules": longo}, headers=HEADERS)
    assert resposta.status_code == 422
    assert re.search(r"4001", resposta.text) and "4000" in resposta.text
    assert _regras_gravadas(pasta) == "antes"
    exato = "y" * EXTRA_RULES_MAX_LENGTH
    cliente.post(f"/projects/{pid}/instructions/extra-rules", data={"extra_rules": exato}, headers=HEADERS)
    assert _regras_gravadas(pasta) == exato


def test_caixa_exige_origem_como_as_demais_gravacoes(tmp_path, monkeypatch):
    cliente, pid, pasta = _web(tmp_path, monkeypatch)
    resposta = cliente.post(
        f"/projects/{pid}/instructions/extra-rules", data={"extra_rules": "x"},
        headers={"Origin": "http://outro-site.example"},
    )
    assert resposta.status_code == 403
    assert _regras_gravadas(pasta) == ""


def test_limpeza_de_repeticao_ainda_move_regras_para_a_config(tmp_path, monkeypatch):
    from gclaude_indexer.instructions_dedup import detect
    from tests.test_phase42 import _bloco, _escrever_com_copia, _secoes_copiadas

    cliente, pid, pasta = _web(tmp_path, monkeypatch)
    caminho = _escrever_com_copia(tmp_path, pasta, "")
    tela = cliente.get(f"/projects/{pid}/instructions").text
    impressao = re.search(r'name="fingerprint" value="([0-9a-f]+)"', tela).group(1)
    candidatos = [int(v) for v in re.findall(r'name="move" value="(\d+)"', tela)]
    resposta = cliente.post(
        f"/projects/{pid}/instructions/dedup",
        data={"action": "remove", "fingerprint": impressao, "move": candidatos}, headers=HEADERS,
    )
    assert resposta.status_code == 200
    assert candidatos, "a cópia da fixture deveria oferecer ao menos uma regra para mover"
    assert _regras_gravadas(pasta).strip()


def test_limpeza_de_repeticao_nao_passa_do_teto_das_regras(tmp_path, monkeypatch):
    """O teto das regras extras valia só na caixa; mover regras da limpeza
    de repetição passava dele em silêncio. Agora nada muda: nem as regras,
    nem a parte do usuário."""
    from tests.test_phase42 import _escrever_com_copia

    cliente, pid, pasta = _web(tmp_path, monkeypatch)
    cheio = "z" * EXTRA_RULES_MAX_LENGTH
    cliente.post(f"/projects/{pid}/instructions/extra-rules", data={"extra_rules": cheio}, headers=HEADERS)
    caminho = _escrever_com_copia(tmp_path, pasta, "")
    antes = caminho.read_text(encoding="utf-8")
    tela = cliente.get(f"/projects/{pid}/instructions").text
    impressao = re.search(r'name="fingerprint" value="([0-9a-f]+)"', tela).group(1)
    candidatos = [int(v) for v in re.findall(r'name="move" value="(\d+)"', tela)]
    assert candidatos
    resposta = cliente.post(
        f"/projects/{pid}/instructions/dedup",
        data={"action": "remove", "fingerprint": impressao, "move": candidatos}, headers=HEADERS,
    )
    assert resposta.status_code == 422
    assert str(EXTRA_RULES_MAX_LENGTH) in resposta.text
    assert _regras_gravadas(pasta) == cheio
    assert caminho.read_text(encoding="utf-8") == antes


def test_teto_das_regras_vale_em_toda_gravacao_que_as_muda(tmp_path):
    import pytest

    from gclaude_indexer.config import ConfigError
    from gclaude_indexer.project import create_project, merge_project_config

    origem = tmp_path / "origem"
    origem.mkdir()
    config = load_config({"name": "X", "source_folder": str(origem), "output_folder": str(tmp_path / "saida")})
    conn, _ = create_project(config)
    config.extra_rules = "x" * (EXTRA_RULES_MAX_LENGTH + 1)
    with pytest.raises(ConfigError):
        save_project_config(conn, config)
    with pytest.raises(ConfigError):
        merge_project_config(conn, {"extra_rules": config.extra_rules})
    conn.close()

    # Um projeto que já ficou acima do teto continua abrindo e sendo regravado.
    banco = tmp_path / "saida" / "project.db"
    import sqlite3

    direto = sqlite3.connect(banco)
    dados = json.loads(direto.execute("SELECT config_json FROM project").fetchone()[0])
    dados["extra_rules"] = config.extra_rules
    direto.execute("UPDATE project SET config_json = ?", (json.dumps(dados, ensure_ascii=False),))
    direto.commit()
    direto.close()
    aberto, conn = load_project(tmp_path / "saida")
    aberto.subject = "novo assunto"
    save_project_config(conn, aberto)
    merge_project_config(conn, {"overlap": 1})
    conn.close()
    assert _regras_gravadas(tmp_path / "saida") == config.extra_rules
