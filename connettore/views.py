"""Endpoint ``/mcp`` (SPEC_MCP §3, §4, §6): token OAuth, ruolo, limite, protocollo, registro."""

import datetime
import json
import logging
import time
from urllib.parse import urlparse

from django.conf import settings
from django.http import Http404, HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from oauth2_provider.oauth2_backends import get_oauthlib_core
from oauth2_provider.www_authenticate import build_bearer_challenge, challenge_status

from connettore import protocollo
from connettore.models import RegistroChiamata
from connettore.oauth import connettore_attivo, utente_ammesso
from connettore.strumenti import Contesto
from contratti import adapters
from contratti import models as m

logger = logging.getLogger("connettore")


def _origini_ammesse() -> set[str]:
    origini = set()
    for url in (settings.MCP_URL_PUBBLICO, settings.MCP_URL_INTERNO):
        if url:
            p = urlparse(url)
            origini.add(f"{p.scheme}://{p.netloc}")
    return origini


def _registra(request, inizio: float, esito: str, **campi) -> None:
    RegistroChiamata.objects.create(
        esito=esito,
        durata_ms=int((time.monotonic() - inizio) * 1000),
        ip=request.META.get("REMOTE_ADDR") or None,
        **campi,
    )


def _non_autorizzata(request, r) -> HttpResponse:
    errore = getattr(r, "oauth2_error", None) if r is not None else None
    metadati = f"{settings.MCP_URL_PUBBLICO}/.well-known/oauth-protected-resource"
    risposta = JsonResponse(
        {"error": "Token assente o non valido: collegare il connettore."},
        status=challenge_status(errore),
    )
    risposta["WWW-Authenticate"] = build_bearer_challenge(
        request, oauth2_error=errore, resource_metadata_url=metadati
    )
    return risposta


def _oltre_limite(token_hash: str, adesso: datetime.datetime) -> bool:
    limite = int(
        adapters.parametro(m.Parametro.Chiave.MCP_RICHIESTE_MINUTO, timezone.localdate(adesso))
    )
    recenti = RegistroChiamata.objects.filter(
        token_hash=token_hash, timestamp__gte=adesso - datetime.timedelta(minutes=1)
    ).count()
    return recenti >= limite


@csrf_exempt
def endpoint(request):
    if not connettore_attivo():
        raise Http404
    inizio = time.monotonic()
    if request.method != "POST":
        risposta = HttpResponse(status=405)
        risposta["Allow"] = "POST"
        return risposta
    # Protezione dal DNS rebinding (specifica MCP, trasporto HTTP): un Origin estraneo no.
    origine = request.headers.get("Origin")
    if origine and origine not in _origini_ammesse():
        return JsonResponse({"error": "Origin non ammessa."}, status=403)

    valido, r = get_oauthlib_core().verify_request(request, scopes=[settings.MCP_SCOPE_LETTURA])
    if not valido:
        _registra(request, inizio, RegistroChiamata.Esito.NON_AUTORIZZATA, messaggio="token")
        return _non_autorizzata(request, r)
    token = r.access_token
    utente = token.user
    comuni = {
        "utente": utente,
        "client_id": token.application.client_id if token.application_id else "",
        "token_hash": token.token_checksum,
    }
    if not utente_ammesso(utente):
        _registra(request, inizio, RegistroChiamata.Esito.NON_AUTORIZZATA, messaggio="ruolo")
        return JsonResponse({"error": "Utente senza un ruolo dell'applicazione."}, status=403)

    adesso = timezone.now()
    if _oltre_limite(token.token_checksum, adesso):
        _registra(request, inizio, RegistroChiamata.Esito.LIMITE, **comuni)
        risposta = JsonResponse({"error": "Troppe richieste: riprovare tra un minuto."}, status=429)
        risposta["Retry-After"] = "60"
        return risposta

    versione = request.headers.get("MCP-Protocol-Version")
    if versione and versione not in protocollo.VERSIONI_SUPPORTATE:
        _registra(request, inizio, RegistroChiamata.Esito.ERRORE_PROTOCOLLO, **comuni)
        return JsonResponse(
            {"error": f"Versione del protocollo non supportata: {versione}"}, status=400
        )

    try:
        messaggio = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        _registra(request, inizio, RegistroChiamata.Esito.ERRORE_PROTOCOLLO, **comuni)
        errore = protocollo._errore(None, protocollo.PARSE_ERROR, "JSON non valido.")
        return JsonResponse(errore, status=400)

    ctx = Contesto(
        utente=utente,
        oggi=timezone.localdate(adesso),
        scrittura=token.allow_scopes([settings.MCP_SCOPE_SCRITTURA]),
        client_id=comuni["client_id"],
    )
    try:
        risposta, esito = protocollo.gestisci(messaggio, ctx)
    except Exception:
        logger.exception("errore interno del connettore MCP")
        _registra(request, inizio, RegistroChiamata.Esito.ERRORE_PROTOCOLLO, **comuni)
        id_ = messaggio.get("id") if isinstance(messaggio, dict) else None
        return JsonResponse(protocollo._errore(id_, protocollo.INTERNAL_ERROR, "Errore interno."))
    _registra(
        request,
        inizio,
        esito.esito,
        metodo=esito.metodo,
        tool=esito.tool,
        argomenti=esito.argomenti,
        messaggio=esito.messaggio,
        elementi=esito.elementi,
        **comuni,
    )
    if risposta is None:
        return HttpResponse(status=202)
    return JsonResponse(risposta, json_dumps_params={"ensure_ascii": False})
