"""Fixture del connettore MCP: client OAuth, token, chiamate JSON-RPC a /mcp."""

import datetime
import secrets

import pytest
from django.utils import timezone
from oauth2_provider.models import AccessToken, get_application_model, set_token_value

from accounts.roles import ADMIN, EDITOR, READER

HOST_PUBBLICO = "mcp.esempio.test"
HOST_INTERNO = "contratti.esempio.test"
ROLES = {"admin": ADMIN, "editor": EDITOR, "reader": READER}


@pytest.fixture
def applicazione(db):
    Application = get_application_model()
    return Application.objects.create(
        name="Claude",
        client_type="confidential",
        authorization_grant_type="authorization-code",
        redirect_uris="https://claude.ai/api/mcp/auth_callback",
        client_secret="secret-di-prova-non-reale",
        algorithm="",
    )


@pytest.fixture
def utente_reader(make_user):
    user = make_user("lettore", role=READER)
    user.last_login = timezone.now()
    user.save(update_fields=["last_login"])
    return user


@pytest.fixture
def crea_token(applicazione):
    def _crea(user, scope="registro.lettura", scade_tra=3600):
        raw = secrets.token_urlsafe(30)
        token = AccessToken(
            user=user,
            application=applicazione,
            scope=scope,
            expires=timezone.now() + datetime.timedelta(seconds=scade_tra),
        )
        set_token_value(token, raw)
        token.save()
        return raw

    return _crea


@pytest.fixture
def mcp_post(client):
    """POST JSON-RPC a /mcp sull'host pubblico, con il token dato."""

    def _post(messaggio, token=None, **headers):
        if token:
            headers["HTTP_AUTHORIZATION"] = f"Bearer {token}"
        return client.post(
            "/mcp",
            data=messaggio,
            content_type="application/json",
            HTTP_HOST=HOST_PUBBLICO,
            HTTP_ACCEPT="application/json, text/event-stream",
            secure=True,
            **headers,
        )

    return _post


def chiama(nome, argomenti=None, id_=1):
    return {
        "jsonrpc": "2.0",
        "id": id_,
        "method": "tools/call",
        "params": {"name": nome, "arguments": argomenti or {}},
    }
