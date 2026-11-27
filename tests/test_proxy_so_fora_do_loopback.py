"""2.1.6: o proxy do sistema volta a valer para a internet, nunca para o Ollama.

Até a 2.1.5 o pacote instalava um opener global sem proxy nenhum, para que o
texto dos documentos enviado ao Ollama em 127.0.0.1 não passasse pelo proxy
de uma rede corporativa. Só que a consulta ao LexML (internet) usa o mesmo
`urlopen` global e falhava atrás desse proxy. Agora o endereço local nunca
passa pelo proxy, e o resto segue a configuração do sistema."""

from __future__ import annotations

import http.server
import threading
import urllib.request

import pytest

import gclaude_indexer


class _Registro(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - nome exigido pelo http.server
        self.server.vistos.append(self.path)
        corpo = self.server.nome.encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def log_message(self, *args):
        pass


@pytest.fixture
def servidor():
    criados = []

    def criar(nome):
        srv = http.server.HTTPServer(("127.0.0.1", 0), _Registro)
        srv.nome, srv.vistos = nome, []
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        criados.append(srv)
        return srv

    yield criar
    for srv in criados:
        srv.shutdown()
        srv.server_close()


def test_endereco_local_nunca_passa_pelo_proxy_e_a_internet_passa(servidor):
    proxy = servidor("proxy")
    ollama = servidor("ollama")
    opener = gclaude_indexer.build_opener_without_loopback_proxy(
        {"http": f"http://127.0.0.1:{proxy.server_port}"}
    )

    with opener.open(f"http://127.0.0.1:{ollama.server_port}/api/version", timeout=5) as resposta:
        assert resposta.read() == b"ollama"
    with opener.open(f"http://localhost:{ollama.server_port}/api/tags", timeout=5) as resposta:
        assert resposta.read() == b"ollama"
    assert proxy.vistos == []

    with opener.open("http://www.lexml.gov.br/busca/SRU?x=1", timeout=5) as resposta:
        assert resposta.read() == b"proxy"
    assert proxy.vistos == ["http://www.lexml.gov.br/busca/SRU?x=1"]


def test_sem_argumento_vale_o_proxy_configurado_no_sistema(servidor, monkeypatch):
    """O opener que o pacote instala é montado sem argumento: lê o proxy do
    sistema (variáveis de ambiente e registro do Windows) e só dispensa o
    endereço local."""
    proxy = servidor("proxy")
    ollama = servidor("ollama")
    monkeypatch.setattr(urllib.request, "getproxies", lambda: {"http": f"http://127.0.0.1:{proxy.server_port}"})
    opener = gclaude_indexer.build_opener_without_loopback_proxy()

    with opener.open(f"http://127.0.0.1:{ollama.server_port}/api/version", timeout=5) as resposta:
        assert resposta.read() == b"ollama"
    with opener.open("http://www.lexml.gov.br/x", timeout=5) as resposta:
        assert resposta.read() == b"proxy"
