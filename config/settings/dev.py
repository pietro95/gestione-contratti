"""Sviluppo locale. Legge ``.env`` se presente; senza LDAP_SERVER_URI vale il login locale."""

import os
from pathlib import Path

import environ

environ.Env.read_env(Path(__file__).resolve().parent.parent.parent / ".env")
os.environ.setdefault("DJANGO_SECRET_KEY", "dev-solo-locale-non-usare-in-produzione")
os.environ.setdefault("DATABASE_URL", "postgres://contratti:contratti@localhost:5432/contratti")

from accounts.ldap_config import configure_authentication

from .base import *

DEBUG = True
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1", "[::1]"])

globals().update(configure_authentication(os.environ))
