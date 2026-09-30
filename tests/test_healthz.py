from unittest.mock import patch

import pytest
from django.db import OperationalError
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_healthz_senza_autenticazione(client):
    response = client.get(reverse("healthz"))
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "no-cache" in response["Cache-Control"]


def test_healthz_503_se_database_non_raggiungibile(client):
    with patch("accounts.views.connection.cursor", side_effect=OperationalError("giù")):
        response = client.get(reverse("healthz"))
    assert response.status_code == 503
    assert response.json() == {"status": "error"}  # nessun dettaglio tecnico


def test_healthz_solo_get(client):
    assert client.post(reverse("healthz")).status_code == 405
