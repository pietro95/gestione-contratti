"""Conformità con un client MCP reale: l'SDK ufficiale ``mcp`` (solo test, SPEC_MCP §7, D7).

Le richieste HTTP dell'SDK passano dal client di test di Django sulla URLconf del container
pubblico, nel thread del test (``async_to_sync`` fuori, ``sync_to_async`` dentro) e quindi
nella sua transazione: niente server in un altro thread, che a fine test svuoterebbe il
database (dati iniziali compresi).
"""

import json

import httpx
import pytest
from asgiref.sync import async_to_sync, sync_to_async
from django.test import Client
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from tests import factories as f
from tests.connettore.conftest import HOST_PUBBLICO

pytestmark = [pytest.mark.django_db, pytest.mark.urls("config.urls_mcp")]


class TrasportoDjango(httpx.AsyncBaseTransport):
    """Trasporto httpx che consegna ogni richiesta al client di test di Django."""

    def __init__(self):
        self.client = Client()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        corpo = await request.aread()
        return await sync_to_async(self._consegna, thread_sensitive=True)(request, corpo)

    def _consegna(self, request: httpx.Request, corpo: bytes) -> httpx.Response:
        intestazioni = {
            f"HTTP_{k.upper().replace('-', '_')}": v
            for k, v in request.headers.items()
            if k.lower() not in ("host", "content-type", "content-length")
        }
        r = self.client.generic(
            request.method,
            request.url.raw_path.decode(),
            data=corpo,
            content_type=request.headers.get("content-type", ""),
            HTTP_HOST=HOST_PUBBLICO,
            secure=True,
            **intestazioni,
        )
        return httpx.Response(r.status_code, headers=dict(r.items()), content=r.content)


async def _sessione(token, azione):
    headers = {"Authorization": f"Bearer {token}"}
    async with (
        httpx.AsyncClient(transport=TrasportoDjango(), headers=headers) as http,
        streamable_http_client(f"https://{HOST_PUBBLICO}/mcp", http_client=http) as (
            lettura,
            scrittura,
            _,
        ),
        ClientSession(lettura, scrittura) as sessione,
    ):
        iniziale = await sessione.initialize()
        return iniziale, await azione(sessione)


def test_initialize_list_e_call_con_l_sdk(utente_reader, crea_token):
    f.contratto(numero_contratto="4600000099")
    token = crea_token(utente_reader)

    async def azione(sessione):
        tools = await sessione.list_tools()
        trovati = await sessione.call_tool("cerca", {"testo": "4600000099"})
        errore = await sessione.call_tool("cerca", {"testo": "x"})
        await sessione.send_ping()
        return tools, trovati, errore

    iniziale, (tools, trovati, errore) = async_to_sync(_sessione)(token, azione)
    assert iniziale.protocolVersion == "2025-11-25"
    assert iniziale.serverInfo.name == "registro-contratti-ictdinn"
    assert {t.name for t in tools.tools} == {"riferimenti", "cerca", "scadenze"}
    assert all(t.annotations.readOnlyHint for t in tools.tools)
    assert trovati.isError is False
    contratti = trovati.structuredContent["contratti"]
    assert [c["numero_contratto"] for c in contratti] == ["4600000099"]
    assert contratti[0]["link"].startswith("https://contratti.esempio.test/contratti/")
    assert json.loads(trovati.content[0].text) == trovati.structuredContent
    assert errore.isError is True


def test_sdk_senza_token_valido():
    async def azione(sessione):
        return None

    with pytest.raises(BaseException):  # noqa: B017 - l'SDK incapsula il 401 in un ExceptionGroup
        async_to_sync(_sessione)("token-inventato", azione)
