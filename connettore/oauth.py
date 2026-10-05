"""Server di autorizzazione OAuth 2.1 del connettore (SPEC_MCP §4), su django-oauth-toolkit.

- Login e consenso sull'host interno (``/oauth/authorize/``); metadati e token sull'host
  pubblico (§2.1). I metadati RFC 8414 indicano quindi un ``authorization_endpoint``
  interno.
- Un utente senza ruolo, disattivato o break-glass non autorizza e non rinnova.
- Regola D3: il refresh riesce solo se l'ultimo login interattivo è recente (parametro
  ``mcp_giorni_login``); altrimenti ``invalid_grant`` e l'utente ricollega il connettore.
"""

import datetime
import json
from urllib.parse import urlparse

from django.conf import settings
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from oauth2_provider import views as oauth_views
from oauth2_provider.oauth2_validators import OAuth2Validator

from accounts.roles import can_write, role_of
from contratti import adapters
from contratti import models as m


def utente_ammesso(user) -> bool:
    """Può usare il connettore: attivo, con un ruolo, non l'account di emergenza."""
    return bool(
        user is not None
        and user.is_active
        and not getattr(user, "is_breakglass", False)
        and role_of(user) is not None
    )


def login_recente(user, adesso: datetime.datetime | None = None) -> bool:
    """Ultimo login interattivo entro ``mcp_giorni_login`` giorni (D3)."""
    if user.last_login is None:
        return False
    adesso = adesso or timezone.now()
    giorni = adapters.parametro(m.Parametro.Chiave.MCP_GIORNI_LOGIN, timezone.localdate(adesso))
    return user.last_login >= adesso - datetime.timedelta(days=int(giorni))


class Validatore(OAuth2Validator):
    def validate_refresh_token(self, refresh_token, client, request, *args, **kwargs):
        if not super().validate_refresh_token(refresh_token, client, request, *args, **kwargs):
            return False
        return utente_ammesso(request.user) and login_recente(request.user)


# Stesso percorso nelle due URLconf: l'autorizzazione esiste solo su quella interna.
PERCORSO_AUTORIZZAZIONE = "/oauth/authorize/"


def connettore_attivo() -> bool:
    return bool(settings.MCP_URL_PUBBLICO)


class MetadatiServer(oauth_views.OAuthServerMetadataView):
    """RFC 8414, con l'autorizzazione sull'host interno e senza registrazione dinamica."""

    def get(self, request, *args, **kwargs):
        if not connettore_attivo():
            raise Http404
        risposta = super().get(request, *args, **kwargs)
        dati = json.loads(risposta.content)
        base = settings.MCP_URL_INTERNO or settings.MCP_URL_PUBBLICO
        dati["authorization_endpoint"] = base + PERCORSO_AUTORIZZAZIONE
        dati["code_challenge_methods_supported"] = ["S256"]
        dati["client_id_metadata_document_supported"] = False
        dati.pop("registration_endpoint", None)
        return JsonResponse(dati)


class MetadatiRisorsa(oauth_views.OAuthProtectedResourceMetadataView):
    """RFC 9728: la risorsa è ``<MCP_URL_PUBBLICO>/mcp``."""

    def get(self, request, *args, **kwargs):
        if not connettore_attivo():
            raise Http404
        return super().get(request, *args, **kwargs)


class Autorizza(oauth_views.AuthorizationView):
    """Pagina di consenso in italiano; solo utenti con un ruolo (D4: tutti i ruoli)."""

    template_name = "connettore/autorizza.html"

    def dispatch(self, request, *args, **kwargs):
        if not connettore_attivo():
            raise Http404
        if request.user.is_authenticated and not utente_ammesso(request.user):
            return render(request, "connettore/non_ammesso.html", status=403)
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        """La scrittura si concede a parte, solo ad Admin ed Editor (SPEC_MCP §8.1)."""
        scope = set((form.cleaned_data.get("scope") or "").split())
        consenti = self.request.POST.get("scrittura") == "1" and can_write(self.request.user)
        if not consenti:
            scope.discard(settings.MCP_SCOPE_SCRITTURA)
        form.cleaned_data["scope"] = " ".join(sorted(scope)) or settings.MCP_SCOPE_LETTURA
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        form = ctx.get("form")
        uri = form.initial.get("redirect_uri") if form is not None else None
        ctx["host_ritorno"] = urlparse(uri).hostname if uri else ""
        ctx["ritorno_locale"] = ctx["host_ritorno"] in ("localhost", "127.0.0.1", "::1")
        richiesti = set((form.initial.get("scope") or "").split()) if form is not None else set()
        ctx["chiede_scrittura"] = settings.MCP_SCOPE_SCRITTURA in richiesti
        ctx["puo_scrivere"] = can_write(self.request.user)
        ctx["giorni_login"] = int(
            adapters.parametro(m.Parametro.Chiave.MCP_GIORNI_LOGIN, timezone.localdate())
        )
        return ctx
