# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""GClaude Indexer — indexação local de acervos documentais para uso com o Claude."""

import ipaddress as _ipaddress
import urllib.parse as _urllib_parse
import urllib.request as _urllib_request


def _is_loopback(host: str) -> bool:
    name = (_urllib_parse.urlsplit("//" + host).hostname or "").lower()
    if name == "localhost" or name.endswith(".localhost"):
        return True
    try:
        return _ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


class LoopbackDirectProxyHandler(_urllib_request.ProxyHandler):
    """The system proxy, except for this machine itself.

    The local engine sends the text of the user's documents to Ollama on
    127.0.0.1. On a corporate network whose proxy does not exempt loopback,
    urllib would hand that text to the proxy — personal data leaving the
    machine (LGPD) for no reason at all. So a loopback address never goes
    through a proxy. Everything else (the LexML lookup, downloads) follows
    the system settings: until 2.1.5 the package removed the proxy for
    every call, and LexML failed behind a corporate proxy."""

    def proxy_open(self, req, proxy, type):
        if _is_loopback(req.host):
            return None  # straight to the machine itself
        return super().proxy_open(req, proxy, type)


def build_opener_without_loopback_proxy(proxies=None):
    return _urllib_request.build_opener(LoopbackDirectProxyHandler(proxies))


_urllib_request.install_opener(build_opener_without_loopback_proxy())
