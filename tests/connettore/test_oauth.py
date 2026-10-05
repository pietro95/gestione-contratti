"""Flusso OAuth completo del connettore (SPEC_MCP §4, §7): metadati, consenso, token, D3."""

import base64
import datetime
import hashlib
import secrets
from urllib.parse import parse_qs, urlencode, urlparse

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone
from oauth2_provider.models import get_application_model

from tests.connettore.conftest import HOST_INTERNO, HOST_PUBBLICO

pytestmark = pytest.mark.django_db

CALLBACK = "https://claude.ai/api/mcp/auth_callback"
RISORSA = "https://mcp.esempio.test/mcp"
SECRET = "secret-di-prova-non-reale"


def pkce():
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    return verifier, challenge


def autorizza(client, app, redirect_uri=CALLBACK, approva=True):
    """Consenso sull'host interno; restituisce (risposta, code_verifier)."""
    verifier, challenge = pkce()
    parametri = {
        "client_id": app.client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": "registro.lettura",
        "state": "stato-di-prova",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "resource": RISORSA,
    }
    url = "/oauth/authorize/?" + urlencode(parametri)
    pagina = client.get(url, HTTP_HOST=HOST_INTERNO, secure=True)
    if pagina.status_code != 200 or not approva:
        return pagina, verifier
    dati = {**parametri, "allow": "Autorizza"}
    dati.pop("response_type")
    dati["response_type"] = "code"
    r = client.post(url, data=dati, HTTP_HOST=HOST_INTERNO, secure=True)
    return r, verifier


def codice(risposta):
    assert risposta.status_code == 302, risposta.content[:500]
    query = parse_qs(urlparse(risposta["Location"]).query)
    assert query["state"] == ["stato-di-prova"]
    return query["code"][0]


def token(client, dati):
    with override_settings(ROOT_URLCONF="config.urls_mcp"):
        return client.post(
            "/oauth/token/",
            data=urlencode(dati),
            content_type="application/x-www-form-urlencoded",
            HTTP_HOST=HOST_PUBBLICO,
            secure=True,
        )


def scambia(client, app, code, verifier, redirect_uri=CALLBACK, secret=SECRET):
    dati = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": app.client_id,
        "code_verifier": verifier,
        "resource": RISORSA,
    }
    if secret:
        dati["client_secret"] = secret
    return token(client, dati)


def chiama_mcp(client, access_token):
    with override_settings(ROOT_URLCONF="config.urls_mcp"):
        return client.post(
            "/mcp",
            data={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            content_type="application/json",
            HTTP_HOST=HOST_PUBBLICO,
            HTTP_AUTHORIZATION=f"Bearer {access_token}",
            secure=True,
        )


@pytest.fixture
def collegato(client, applicazione, utente_reader):
    client.force_login(utente_reader)
    r, verifier = autorizza(client, applicazione)
    risposta = scambia(client, applicazione, codice(r), verifier)
    assert risposta.status_code == 200, risposta.content
    return risposta.json()


# --- Metadati --------------------------------------------------------------------------


@override_settings(ROOT_URLCONF="config.urls_mcp")
def test_metadati_della_risorsa(client):
    for percorso in (
        "/.well-known/oauth-protected-resource",
        "/.well-known/oauth-protected-resource/mcp",
    ):
        dati = client.get(percorso, HTTP_HOST=HOST_PUBBLICO, secure=True).json()
        assert dati["resource"] == RISORSA
        assert dati["authorization_servers"] == ["https://mcp.esempio.test"]
        assert dati["scopes_supported"] == ["registro.lettura"]


@override_settings(ROOT_URLCONF="config.urls_mcp")
def test_metadati_del_server_di_autorizzazione(client):
    dati = client.get(
        "/.well-known/oauth-authorization-server", HTTP_HOST=HOST_PUBBLICO, secure=True
    ).json()
    assert dati["issuer"] == "https://mcp.esempio.test"
    # Login e consenso sull'host interno; token sull'host pubblico (SPEC_MCP §2.1).
    assert dati["authorization_endpoint"] == "https://contratti.esempio.test/oauth/authorize/"
    assert dati["token_endpoint"] == "https://mcp.esempio.test/oauth/token/"
    assert dati["code_challenge_methods_supported"] == ["S256"]
    assert dati["response_types_supported"] == ["code"]
    assert dati["grant_types_supported"] == ["authorization_code", "refresh_token"]
    assert "none" in dati["token_endpoint_auth_methods_supported"]
    assert "registration_endpoint" not in dati
    assert dati["client_id_metadata_document_supported"] is False


def test_metadati_spenti_senza_url_pubblico(client, settings):
    settings.ROOT_URLCONF = "config.urls_mcp"
    settings.MCP_URL_PUBBLICO = ""
    for percorso in (
        "/.well-known/oauth-protected-resource",
        "/.well-known/oauth-authorization-server",
    ):
        assert client.get(percorso, HTTP_HOST=HOST_PUBBLICO, secure=True).status_code == 404


# --- Consenso --------------------------------------------------------------------------


def test_autorizzazione_richiede_login(client, applicazione):
    r, _ = autorizza(client, applicazione)
    assert r.status_code == 302
    assert r["Location"].startswith("/accounts/login/")


def test_pagina_di_consenso(client, applicazione, utente_reader):
    client.force_login(utente_reader)
    r, _ = autorizza(client, applicazione, approva=False)
    assert r.status_code == 200
    testo = r.content.decode()
    assert "Collega il connettore MCP" in testo
    assert "Lettura del registro contratti" in testo
    assert "claude.ai" in testo  # host di ritorno ben visibile
    assert "7 giorni" in testo


def test_annulla_non_rilascia_codici(client, applicazione, utente_reader):
    from oauth2_provider.models import Grant

    client.force_login(utente_reader)
    _, challenge = pkce()
    parametri = {
        "client_id": applicazione.client_id,
        "response_type": "code",
        "redirect_uri": CALLBACK,
        "scope": "registro.lettura",
        "state": "stato-di-prova",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    url = "/oauth/authorize/?" + urlencode(parametri)
    r = client.post(url, data=parametri, HTTP_HOST=HOST_INTERNO, secure=True)  # senza «allow»
    assert r.status_code == 302
    assert "error=access_denied" in r["Location"]
    assert not Grant.objects.exists()


@pytest.mark.parametrize("ruolo", [None, "breakglass"])
def test_senza_ruolo_o_breakglass_non_autorizza(client, applicazione, make_user, ruolo):
    if ruolo == "breakglass":
        user = make_user("emergenza", role="Admin", is_breakglass=True)
    else:
        user = make_user("senza-ruolo")
    client.force_login(user)
    r, _ = autorizza(client, applicazione)
    assert r.status_code == 403
    assert "non può collegare il connettore" in r.content.decode()


def test_redirect_non_registrato_rifiutato(client, applicazione, utente_reader):
    client.force_login(utente_reader)
    r, _ = autorizza(client, applicazione, redirect_uri="https://attaccante.example/cb")
    # Nessun redirect verso un indirizzo non registrato: errore mostrato sulla pagina.
    assert r.status_code == 400
    assert not r.has_header("Location")
    assert "Richiesta non valida" in r.content.decode()


def test_autorizzazione_non_esiste_sull_host_pubblico(client, applicazione, utente_reader):
    client.force_login(utente_reader)
    with override_settings(ROOT_URLCONF="config.urls_mcp"):
        r = client.get("/oauth/authorize/", HTTP_HOST=HOST_PUBBLICO, secure=True)
    assert r.status_code == 404


# --- Token e chiamate ------------------------------------------------------------------


def test_flusso_completo_reader(client, collegato):
    # D4: tutti i ruoli collegano il connettore, Reader compreso.
    assert collegato["token_type"] == "Bearer"
    assert collegato["expires_in"] == 3600
    assert collegato["scope"] == "registro.lettura"
    r = chiama_mcp(client, collegato["access_token"])
    assert r.status_code == 200
    nomi = {t["name"] for t in r.json()["result"]["tools"]}
    assert {"riferimenti", "cerca", "scadenze"} <= nomi


def test_codice_senza_verifier_corretto_rifiutato(client, applicazione, utente_reader):
    client.force_login(utente_reader)
    r, _ = autorizza(client, applicazione)
    altro_verifier, _ = pkce()
    risposta = scambia(client, applicazione, codice(r), altro_verifier)
    assert risposta.status_code == 400
    assert risposta.json()["error"] == "invalid_grant"


def test_codice_usabile_una_volta(client, applicazione, utente_reader):
    client.force_login(utente_reader)
    r, verifier = autorizza(client, applicazione)
    code = codice(r)
    assert scambia(client, applicazione, code, verifier).status_code == 200
    assert scambia(client, applicazione, code, verifier).status_code == 400


def test_secret_sbagliato_rifiutato(client, applicazione, utente_reader):
    client.force_login(utente_reader)
    r, verifier = autorizza(client, applicazione)
    risposta = scambia(client, applicazione, codice(r), verifier, secret="sbagliato")
    assert risposta.status_code == 401


def refresh(client, app, refresh_token):
    return token(
        client,
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": app.client_id,
            "client_secret": SECRET,
        },
    )


def test_refresh_ruota_il_token(client, applicazione, collegato):
    r = refresh(client, applicazione, collegato["refresh_token"])
    assert r.status_code == 200
    nuovo = r.json()
    assert nuovo["refresh_token"] != collegato["refresh_token"]
    assert chiama_mcp(client, nuovo["access_token"]).status_code == 200


@pytest.mark.parametrize(("giorni", "atteso"), [(6, 200), (8, 400)])
def test_regola_d3_refresh_solo_con_login_recente(
    client, applicazione, utente_reader, collegato, giorni, atteso
):
    utente_reader.last_login = timezone.now() - datetime.timedelta(days=giorni)
    utente_reader.save(update_fields=["last_login"])
    r = refresh(client, applicazione, collegato["refresh_token"])
    assert r.status_code == atteso
    if atteso == 400:
        assert r.json()["error"] == "invalid_grant"


def test_refresh_rifiutato_se_perde_il_ruolo(client, applicazione, utente_reader, collegato):
    utente_reader.groups.clear()
    r = refresh(client, applicazione, collegato["refresh_token"])
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_grant"


# --- Claude Code: client pubblico, loopback su qualunque porta -------------------------


@pytest.fixture
def claude_code(db, capsys):
    call_command("crea_client_mcp", "claude-code")
    return get_application_model().objects.get(name="Claude Code")


@pytest.mark.parametrize(
    "redirect", ["http://127.0.0.1:53111/callback", "http://localhost:4127/callback"]
)
def test_claude_code_loopback_su_qualunque_porta(client, claude_code, utente_reader, redirect):
    client.force_login(utente_reader)
    r, verifier = autorizza(client, claude_code, redirect_uri=redirect)
    assert r["Location"].startswith(redirect)
    risposta = scambia(client, claude_code, codice(r), verifier, redirect_uri=redirect, secret="")
    assert risposta.status_code == 200, risposta.content
    pagina, _ = autorizza(client, claude_code, redirect_uri=redirect, approva=False)
    assert "Claude Code" in pagina.content.decode()  # avviso del ritorno su questo computer


def test_crea_client_claude_mostra_il_secret_una_volta(db, capsys):
    call_command("crea_client_mcp", "claude")
    uscita = capsys.readouterr().out
    secret = uscita.split("client secret:")[1].split()[0]
    app = get_application_model().objects.get(name="Claude")
    assert app.client_type == "confidential"
    assert app.client_secret != secret  # nel database solo l'hash
    assert app.redirect_uris.split() == [
        "https://claude.ai/api/mcp/auth_callback",
        "https://claude.com/api/mcp/auth_callback",
    ]
