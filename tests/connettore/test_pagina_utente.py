"""Pagina «Connettore MCP» dell'utente: collegamenti propri, revoca, ultime chiamate."""

import datetime

import pytest
from django.utils import timezone
from oauth2_provider.models import AccessToken, RefreshToken, set_token_value

from accounts.roles import EDITOR
from connettore.models import RegistroChiamata

pytestmark = pytest.mark.django_db
HOST = "contratti.esempio.test"


@pytest.fixture
def collegamento(applicazione):
    def _crea(user):
        at = AccessToken(
            user=user,
            application=applicazione,
            scope="registro.lettura",
            expires=timezone.now() + datetime.timedelta(hours=1),
        )
        set_token_value(at, f"at-{user.pk}-{AccessToken.objects.count()}")
        at.save()
        rt = RefreshToken(user=user, application=applicazione, access_token=at)
        set_token_value(rt, f"rt-{user.pk}-{RefreshToken.objects.count()}")
        rt.save()
        return rt

    return _crea


def get(client, url="/connettore/"):
    return client.get(url, HTTP_HOST=HOST, secure=True)


def post(client, url):
    return client.post(url, HTTP_HOST=HOST, secure=True)


def test_richiede_login(client):
    r = get(client)
    assert r.status_code == 302 and "/accounts/login/" in r["Location"]


def test_mostra_solo_i_propri_collegamenti(client, utente_reader, make_user, collegamento):
    mio = collegamento(utente_reader)
    altro = collegamento(make_user("altro", role=EDITOR))
    RegistroChiamata.objects.create(utente=utente_reader, tool="cerca", esito="ok", metodo="x")
    client.force_login(utente_reader)
    r = get(client)
    assert r.status_code == 200
    righe = list(r.context["collegamenti"])
    assert righe == [mio] and altro not in righe
    testo = r.content.decode()
    assert "https://mcp.esempio.test/mcp" in testo
    assert "cerca" in testo  # ultime chiamate


def test_revoca_il_proprio_collegamento(client, utente_reader, collegamento):
    """Anche il Reader revoca i suoi collegamenti: non sono dati di dominio (D4)."""
    rt = collegamento(utente_reader)
    client.force_login(utente_reader)
    r = post(client, f"/connettore/{rt.pk}/revoca/")
    assert r.status_code == 302
    rt.refresh_from_db()
    assert rt.revoked is not None
    assert not AccessToken.objects.filter(pk=rt.access_token_id).exists()


def test_non_revoca_i_collegamenti_altrui(client, utente_reader, make_user, collegamento):
    altro = collegamento(make_user("altro", role=EDITOR))
    client.force_login(utente_reader)
    assert post(client, f"/connettore/{altro.pk}/revoca/").status_code == 404
    altro.refresh_from_db()
    assert altro.revoked is None


def test_revoca_tutti(client, utente_reader, make_user, collegamento):
    collegamento(utente_reader)
    collegamento(utente_reader)
    altro = collegamento(make_user("altro", role=EDITOR))
    client.force_login(utente_reader)
    assert post(client, "/connettore/revoca-tutti/").status_code == 302
    assert not RefreshToken.objects.filter(user=utente_reader, revoked__isnull=True).exists()
    altro.refresh_from_db()
    assert altro.revoked is None


def test_revoca_solo_con_post(client, utente_reader, collegamento):
    rt = collegamento(utente_reader)
    client.force_login(utente_reader)
    assert get(client, f"/connettore/{rt.pk}/revoca/").status_code == 405


def test_spenta_senza_connettore(client, utente_reader, settings):
    settings.MCP_URL_PUBBLICO = ""
    client.force_login(utente_reader)
    assert get(client).status_code == 404


def test_voce_di_menu(client, utente_reader):
    client.force_login(utente_reader)
    assert 'href="/connettore/"' in get(client, "/cruscotto/").content.decode()
