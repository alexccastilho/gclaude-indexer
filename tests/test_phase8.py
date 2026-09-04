"""Phase 8 tests: the `local` and `claude_code` engines, and review mode."""

from __future__ import annotations

import http.server
import json
import threading

import fitz
import pytest

from gclaude_indexer import engine_local
from gclaude_indexer.classification import WindowPage, ClassifiedItem
from gclaude_indexer.config import load_config
from gclaude_indexer.conversion import convert
from gclaude_indexer.db import connect, init_schema
from gclaude_indexer.events import list_events
from gclaude_indexer.extraction import extract_pages
from gclaude_indexer.windows_prep import prepare_windows
from gclaude_indexer.engine_claude_code import finish, prepare, sync_progress
from gclaude_indexer.engine_local import LocalEngine, _dict_to_item, _extract_items_json, classify_pending, model_to_use
from gclaude_indexer.review import classify_with_review
from gclaude_indexer.scanning import scan


def _pdf(caminho, paginas_textos):
    documento = fitz.open()
    for texto in paginas_textos:
        pagina = documento.new_page()
        pagina.insert_textbox((50, 50, 550, 750), texto, fontsize=12)
    documento.save(caminho)
    documento.close()


def _projeto_pronto_para_classificar(tmp_path, paginas_textos, **extra_config):
    origem = tmp_path / "origem"
    (origem / "volume_1").mkdir(parents=True)
    saida = tmp_path / "origem_indexado"
    _pdf(origem / "volume_1" / "peca.pdf", paginas_textos)

    dados = {"name": "Fase 8", "source_folder": str(origem), "output_folder": str(saida)}
    dados.update(extra_config)
    config = load_config(dados)

    conn = connect(saida / "project.db")
    init_schema(conn)
    scan(conn, config)
    convert(conn, config)
    extract_pages(conn, config)
    prepare_windows(conn, config)
    return config, conn


TEXTO_LONGO_SEM_MARCADOR = (
    "Texto solto de teste, longo o bastante para não acionar OCR, sem "
    "nenhum marcador de tipo reconhecível nesta página específica aqui."
)


# --- servidor Ollama falso para os testes ----------------------------------


class _HandlerOllamaFake(http.server.BaseHTTPRequestHandler):
    respostas_generate: list[dict] = []

    def do_GET(self):
        if self.path == "/api/version":
            self._responder({"version": "0.0.0-fake"})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/api/generate":
            tamanho = int(self.headers.get("Content-Length", 0))
            self.rfile.read(tamanho)
            resposta = self.respostas_generate.pop(0) if self.respostas_generate else {"response": "{}"}
            self._responder(resposta)
        else:
            self.send_response(404)
            self.end_headers()

    def _responder(self, dados):
        corpo = json.dumps(dados).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def log_message(self, *args):
        pass


@pytest.fixture
def ollama_fake():
    classe_isolada = type("HandlerIsolado", (_HandlerOllamaFake,), {"respostas_generate": []})
    servidor = http.server.HTTPServer(("127.0.0.1", 0), classe_isolada)
    thread = threading.Thread(target=servidor.serve_forever, daemon=True)
    thread.start()
    try:
        yield servidor, classe_isolada
    finally:
        servidor.shutdown()
        thread.join(timeout=2)


# --- motor local: parsing e validação da resposta do modelo ----------------


def test_extract_items_json_aceita_objeto_com_chave_pecas():
    resultado = _extract_items_json(json.dumps({"items": [{"ref_start": "f. 1"}]}))
    assert resultado == [{"ref_start": "f. 1"}]


def test_extract_items_json_aceita_lista_direta():
    resultado = _extract_items_json(json.dumps([{"ref_start": "f. 1"}]))
    assert resultado == [{"ref_start": "f. 1"}]


def test_extract_items_json_tolera_resposta_quebrada():
    assert _extract_items_json("isto nao e json") == []
    assert _extract_items_json(json.dumps({"outra_coisa": 1})) == []


def test_dict_to_item_recusa_referencia_alucinada():
    paginas = [WindowPage("f. 1", "doc.pdf", "texto", False, 0)]
    bruto = {"ref_start": "f. 99", "ref_end": "f. 99", "confidence": "high"}
    assert _dict_to_item(bruto, paginas) is None


def test_dict_to_item_aceita_referencia_real_e_agrega_metadados():
    paginas = [
        WindowPage("f. 1", "doc.pdf", "texto 1", has_table=False, image_count=0),
        WindowPage("f. 2", "doc.pdf", "texto 2", has_table=True, image_count=1),
    ]
    bruto = {
        "ref_start": "f. 1", "ref_end": "f. 2", "type": "OFÍCIO", "date": "2024-03-15",
        "author": "Fulano", "summary": "resumo curto", "confidence": "high",
    }
    peca = _dict_to_item(bruto, paginas)
    assert peca is not None
    assert peca.engine == "local"
    assert peca.start_order == 1 and peca.end_order == 2
    assert peca.has_table is True  # herdado da página 2
    assert peca.has_image is True
    assert peca.files == ["doc.pdf"]


def test_dict_to_item_data_invalida_vira_none():
    paginas = [WindowPage("f. 1", "doc.pdf", "texto", False, 0)]
    bruto = {"ref_start": "f. 1", "ref_end": "f. 1", "date": "não é data", "confidence": "high"}
    peca = _dict_to_item(bruto, paginas)
    assert peca.date is None


def test_dict_to_item_confianca_ausente_vira_baixa():
    paginas = [WindowPage("f. 1", "doc.pdf", "texto", False, 0)]
    bruto = {"ref_start": "f. 1", "ref_end": "f. 1"}
    peca = _dict_to_item(bruto, paginas)
    assert peca.confidence == "low"


# --- motor local: conexão real com um Ollama falso -------------------------


def test_motor_local_disponivel_falso_sem_servidor():
    motor = LocalEngine(model="qualquer", url_base="http://127.0.0.1:9")
    assert motor.is_available() is False


def test_motor_local_disponivel_e_classifica_com_servidor_fake(ollama_fake):
    servidor, classe = ollama_fake
    porta = servidor.server_address[1]
    classe.respostas_generate = [
        {
            "response": json.dumps(
                {
                    "items": [
                        {
                            "ref_start": "f. 1", "ref_end": "f. 1", "type": "OFÍCIO",
                            "date": "2024-03-15", "author": None, "summary": "resumo de teste",
                            "has_table": False, "has_image": False, "confidence": "high",
                        }
                    ]
                }
            )
        }
    ]

    # `per_page=False`: este teste exercita o modo de FAIXAS, que continua
    # existindo e é o formato que o servidor falso responde acima. O modo
    # padrão passou a ser "uma linha por página" (fase 16), com prompt e
    # formato próprios — coberto pelos testes da fase 16.
    motor = LocalEngine(
        model="fake-model", url_base=f"http://127.0.0.1:{porta}", per_page=False
    )
    assert motor.is_available() is True

    paginas = [WindowPage("f. 1", "doc.pdf", "OFÍCIO texto de teste", False, 0)]
    pecas = motor.classify(paginas)

    assert len(pecas) == 1
    assert pecas[0].type == "OFÍCIO"
    assert pecas[0].engine == "local"
    assert pecas[0].confidence == "high"


def test_classificar_pendentes_com_ollama_disponivel(tmp_path, ollama_fake):
    servidor, classe = ollama_fake
    porta = servidor.server_address[1]
    classe.respostas_generate = [
        {
            "response": json.dumps(
                {"items": [{"ref_start": "f. 1", "ref_end": "f. 1", "type": "PARECER", "confidence": "medium"}]}
            )
        }
    ]

    config, conn = _projeto_pronto_para_classificar(tmp_path, [TEXTO_LONGO_SEM_MARCADOR])
    motor = LocalEngine(model="fake-model", url_base=f"http://127.0.0.1:{porta}")

    resultado = classify_pending(conn, config, local_engine=motor)

    assert resultado.windows_processed == 1
    assert resultado.windows_via_rules_fallback == 0
    assert resultado.items_generated == 1

    linhas = (config.output_folder and __import__("pathlib").Path(config.output_folder) / "raw_items.jsonl").read_text(encoding="utf-8").splitlines()
    peca = json.loads(linhas[0])
    assert peca["engine"] == "local"

    conn.close()


def test_classificar_pendentes_cai_para_regras_sem_ollama_e_nao_derruba(tmp_path, monkeypatch):
    config, conn = _projeto_pronto_para_classificar(tmp_path, [TEXTO_LONGO_SEM_MARCADOR])
    motor = LocalEngine(model="qualquer", url_base="http://127.0.0.1:9")

    # Simula "ollama não está nem instalado nesta máquina" — sem isso, a
    # tentativa de religar sozinho (pedido do usuário) rodaria de verdade
    # aqui, tornando o teste lento e dependente do que houver instalado.
    # `find_tool` (fase 16, item 5) substituiu o `shutil.which` direto:
    # a busca agora consulta primeiro o `tools.json` que o instalador
    # grava, para não depender do PATH ainda não propagado.
    monkeypatch.setattr(engine_local, "find_tool", lambda nome: None)

    resultado = classify_pending(conn, config, local_engine=motor)

    assert resultado.windows_processed == 1
    assert resultado.windows_via_rules_fallback == 1
    assert resultado.items_generated >= 1

    from pathlib import Path

    linhas = (Path(config.output_folder) / "raw_items.jsonl").read_text(encoding="utf-8").splitlines()
    peca = json.loads(linhas[0])
    assert peca["engine"] == "rules"

    avisos = [e for e in list_events(conn, step="classification") if e["level"] == "warning"]
    assert any("Ollama" in a["message"] for a in avisos)

    conn.close()


def test_modelo_para_usar_respeita_valor_manual(tmp_path):
    """Decisão revista na Fase 13 (Tarefa 8): o usuário pediu para comparar a
    qualidade de modelos diferentes, o que exige que a escolha em
    `modelo_local` seja de fato usada, e não substituída pelo padrão."""
    config, conn = _projeto_pronto_para_classificar(
        tmp_path, [TEXTO_LONGO_SEM_MARCADOR], local_model="qwen2.5:7b-instruct-q4_K_M"
    )
    assert model_to_use(conn, config) == "qwen2.5:7b-instruct-q4_K_M"
    conn.close()


def test_modelo_para_usar_automatico_e_sempre_o_padrao_fixo(tmp_path):
    """Por pedido explícito do usuário: em qualquer hardware, 'automatic'
    resolve sempre para o mesmo modelo — não consulta mais o diagnóstico."""
    config, conn = _projeto_pronto_para_classificar(tmp_path, [TEXTO_LONGO_SEM_MARCADOR])
    assert model_to_use(conn, config) == engine_local.DEFAULT_LOCAL_MODEL
    assert engine_local.DEFAULT_LOCAL_MODEL == "qwen3.5:4b"
    conn.close()


# --- motor claude_code -----------------------------------------------------


def test_preparar_claude_code_garante_arquivo_e_conta_janelas(tmp_path):
    config, conn = _projeto_pronto_para_classificar(tmp_path, [TEXTO_LONGO_SEM_MARCADOR])

    status = prepare(conn, config, "pt")

    assert status.command == "processe as janelas"
    assert status.claude_md_path.exists()
    assert status.windows_pending == 1
    assert status.windows_done == 0
    conn.close()


def test_sincronizar_progresso_marca_janela_feita_quando_jsonl_tem_peca(tmp_path):
    config, conn = _projeto_pronto_para_classificar(tmp_path, [TEXTO_LONGO_SEM_MARCADOR])
    chave = conn.execute("SELECT key FROM window").fetchone()["key"]

    from pathlib import Path

    peca = {
        "window": chave, "group": "volume_1", "ref_start": "f. 1", "ref_end": "f. 1",
        "order_start": 1, "order_end": 1, "type": "OFÍCIO", "date": None, "author": None,
        "summary": "resumo", "has_table": False, "has_image": False, "engine": "claude_code",
        "confidence": "high", "files": "peca.pdf",
    }
    (Path(config.output_folder) / "raw_items.jsonl").write_text(json.dumps(peca) + "\n", encoding="utf-8")

    status = sync_progress(conn, config, "pt")

    assert status.windows_done == 1
    assert status.windows_pending == 0
    assert conn.execute("SELECT status FROM window WHERE key = ?", (chave,)).fetchone()["status"] == "done"
    conn.close()


def test_finalizar_claude_code_importa_e_consolida(tmp_path):
    config, conn = _projeto_pronto_para_classificar(tmp_path, [TEXTO_LONGO_SEM_MARCADOR])
    chave = conn.execute("SELECT key FROM window").fetchone()["key"]

    from pathlib import Path

    peca = {
        "window": chave, "group": "volume_1", "ref_start": "f. 1", "ref_end": "f. 1",
        "order_start": 1, "order_end": 1, "type": "OFÍCIO", "date": "2024-03-15", "author": None,
        "summary": "resumo", "has_table": False, "has_image": False, "engine": "claude_code",
        "confidence": "high", "files": "peca.pdf",
    }
    (Path(config.output_folder) / "raw_items.jsonl").write_text(json.dumps(peca) + "\n", encoding="utf-8")

    resultado = finish(conn, config, "pt")

    assert resultado.consolidated_items == 1
    linha_peca = conn.execute("SELECT * FROM item").fetchone()
    assert linha_peca["engine"] == "claude_code"
    assert conn.execute("SELECT status FROM window").fetchone()["status"] == "done"
    conn.close()


# --- modo revisão ----------------------------------------------------------


class _MotorSegundoFake:
    def __init__(self, pecas: list[ClassifiedItem]):
        self._pecas = pecas
        self.chamadas = 0

    def classify(self, paginas):
        self.chamadas += 1
        return self._pecas


def test_revisao_submete_ao_segundo_motor_so_janelas_com_confianca_baixa(tmp_path):
    # duas janelas pequenas em agrupadores separados: uma com marcador claro
    # (regras deve dar alta), outra sem marcador nenhum (regras dá baixa)
    origem = tmp_path / "origem"
    (origem / "volume_1").mkdir(parents=True)
    (origem / "volume_2").mkdir(parents=True)
    saida = tmp_path / "origem_indexado"

    _pdf(
        origem / "volume_1" / "boa.pdf",
        ["OFÍCIO No 1\nAssunto: solicitação de informações ao setor competente.\n10/01/2024"],
    )
    _pdf(origem / "volume_2" / "ruim.pdf", [TEXTO_LONGO_SEM_MARCADOR])

    config = load_config({"name": "Revisão", "source_folder": str(origem), "output_folder": str(saida)})
    conn = connect(saida / "project.db")
    init_schema(conn)
    scan(conn, config)
    convert(conn, config)
    extract_pages(conn, config)
    prepare_windows(conn, config)

    peca_do_segundo_motor = ClassifiedItem(
        start_ref="f. 1", end_ref="f. 1", start_order=1, end_order=1,
        type="MEMORANDO", date="2024-02-02", author="Fulano", summary="resumo do segundo motor",
        has_table=False, has_image=False, engine="local", confidence="high", files=["ruim.pdf"],
    )
    motor_segundo = _MotorSegundoFake([peca_do_segundo_motor])

    resultado = classify_with_review(conn, config, motor_segundo, "local")

    assert resultado.windows_classified_by_rules == 2
    assert resultado.windows_reviewed == 1  # só a janela de "volume_2" tinha confiança baixa
    assert motor_segundo.chamadas == 1
    assert resultado.items_from_second_engine == 1

    from gclaude_indexer.import_items import import_and_consolidate

    resultado_importacao = import_and_consolidate(conn, config)
    pecas_finais = {p["group_key"]: p for p in conn.execute("SELECT * FROM item").fetchall()}
    assert pecas_finais["volume_2"]["engine"] == "local"  # o resultado do segundo motor prevaleceu
    assert pecas_finais["volume_2"]["confidence"] == "high"
    assert pecas_finais["volume_1"]["engine"] == "rules"  # essa nem precisou de revisão

    conn.close()


def test_revisao_nao_chama_segundo_motor_quando_tudo_e_confianca_alta(tmp_path):
    config, conn = _projeto_pronto_para_classificar(
        tmp_path,
        ["OFÍCIO No 1\nAssunto: solicitação de informações ao setor competente.\n10/01/2024"],
    )
    motor_segundo = _MotorSegundoFake([])

    resultado = classify_with_review(conn, config, motor_segundo, "local")

    assert resultado.windows_reviewed == 0
    assert motor_segundo.chamadas == 0
    conn.close()
