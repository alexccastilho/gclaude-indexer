# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""GClaude Indexer — indexação local de acervos documentais para uso com o Claude."""

import urllib.request as _urllib_request

# Every HTTP call this package makes goes to the local Ollama on 127.0.0.1,
# and the local engine sends it the text of the user's documents. urllib
# would otherwise honor the Windows proxy settings, and on a corporate
# network whose proxy does not exempt loopback that text would travel to
# the proxy — personal data leaving the machine (LGPD) for no reason at all.
# No proxy, ever: nothing here legitimately needs one.
_urllib_request.install_opener(_urllib_request.build_opener(_urllib_request.ProxyHandler({})))
