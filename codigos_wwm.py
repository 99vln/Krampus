# codigos_wwm.py
# Busca os códigos de resgate (freebies) de Where Winds Meet no site
# codes.yar.gg, que mantém a lista dos códigos ativos.
#
# De propósito usa SÓ a biblioteca padrão: o bot roda na Discloud e este
# módulo não adiciona nenhuma dependência nova ao requirements.txt.
#
# A API JSON é a fonte principal; se ela sair do ar, o módulo cai para a
# lista que o site embute no HTML da própria página. Se as duas falharem,
# devolve None (o cog trata como "site fora do ar" e tenta de novo depois,
# sem apagar nada do que já foi anunciado).
#
# Este arquivo é só o buscador: quem decide o que é novo e o que anunciar
# é o cogs/freebies.py.

import json
import re
import time
import urllib.error
import urllib.request

URL_SITE = "https://codes.yar.gg/"
URL_API = "https://codes.yar.gg/api/codes"

# O site limita requisições repetidas: em HTTP 429 esperamos bem mais que
# nos outros erros antes de tentar de novo
ESPERA_429 = 60
ESPERA_PADRAO = 8


def _http_get(url: str, tentativas: int = 3) -> str | None:
    """Baixa uma URL e devolve o corpo como texto, ou None se não der."""
    for tentativa in range(tentativas):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            espera = ESPERA_429 if e.code == 429 else ESPERA_PADRAO
            if tentativa < tentativas - 1:
                time.sleep(espera)
        except (urllib.error.URLError, OSError):
            if tentativa < tentativas - 1:
                time.sleep(ESPERA_PADRAO)
    return None


def buscar_codigos() -> list | None:
    """
    Devolve a lista de códigos ATIVOS, cada um como {"code": ..., "addedAt": ...}.

    Devolve None quando o site está inacessível ou respondeu algo que não dá
    para ler. None significa "não sei", e é diferente de lista vazia: quem
    chama NÃO deve tratar None como "não tem código nenhum".

    Atenção: faz requisição de rede e dorme entre as tentativas, então precisa
    ser chamada fora do event loop (asyncio.to_thread), nunca direto no cog.
    """
    corpo = _http_get(URL_API)
    if corpo is not None:
        try:
            ativos = json.loads(corpo).get("active") or []
            if ativos:
                return ativos
        except (json.JSONDecodeError, AttributeError):
            pass  # API ilegível: cai para o HTML da página

    html = _http_get(URL_SITE)
    if html is None:
        return None

    # A página embute a lista assim: let codeEntries = [ {...}, ... ];
    achado = re.search(r"(?:const|let|var)\s+codeEntries\s*=\s*(\[[\s\S]*?\]);", html)
    if not achado:
        return None
    try:
        return json.loads(achado.group(1)) or None
    except json.JSONDecodeError:
        return None
