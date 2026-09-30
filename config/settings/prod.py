"""Produzione (VM interna, dietro reverse proxy HTTPS). Tutto da variabili d'ambiente."""

import os

from accounts.ldap_config import configure_authentication

from .base import *

DEBUG = False

# HTTPS terminato dal reverse proxy con certificato della CA interna.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_HSTS_SECONDS = env.int("DJANGO_SECURE_HSTS_SECONDS", default=0)
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=False)

globals().update(configure_authentication(os.environ))
