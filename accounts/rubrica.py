"""Indirizzi email degli utenti, letti da LDAP (SPEC §5.10, Rev39).

L'attributo ``mail`` dell'AD è la fonte: si legge al momento dell'invio con l'account di
servizio del login, per nome utente (``sAMAccountName``), così vale anche per chi non ha mai
fatto accesso o ha cambiato indirizzo dopo l'ultimo login. Se LDAP è spento (sviluppo), non
risponde o non ha l'indirizzo, vale quello salvato nell'utente (aggiornato a ogni login e a
ogni lettura riuscita). Una sola connessione per gruppo di destinatari.
"""

import logging
from collections.abc import Iterable

import ldap
from django.conf import settings
from django.contrib.auth import get_user_model

log = logging.getLogger("accounts.rubrica")


def _connessione():
    conn = ldap.initialize(settings.AUTH_LDAP_SERVER_URI)
    # Le opzioni TLS (CA, nuovo contesto) vanno impostate prima di avviare StartTLS.
    for opzione, valore in settings.AUTH_LDAP_CONNECTION_OPTIONS.items():
        conn.set_option(opzione, valore)
    if settings.AUTH_LDAP_START_TLS:
        conn.start_tls_s()
    conn.simple_bind_s(settings.AUTH_LDAP_BIND_DN, settings.AUTH_LDAP_BIND_PASSWORD)
    return conn


def indirizzi_ldap(nomi_utente: Iterable[str]) -> dict[str, str]:
    """``{nome utente in minuscolo: indirizzo}`` per chi ha ``mail`` in LDAP; ``{}`` se LDAP
    è spento o non raggiungibile (l'errore va nel log, mai all'utente)."""
    nomi = sorted({n.strip().lower() for n in nomi_utente if n and n.strip()})
    if not nomi or not getattr(settings, "ACCOUNTS_LDAP_ENABLED", False):
        return {}
    trovati: dict[str, str] = {}
    try:
        conn = _connessione()
        try:
            for nome in nomi:
                # execute() protegge l'argomento dai caratteri speciali del filtro.
                risultati = settings.AUTH_LDAP_USER_SEARCH.execute(conn, {"user": nome})
                for _dn, attributi in risultati:
                    mail = (attributi or {}).get("mail") or []
                    if mail:
                        valore = mail[0]
                        trovati[nome] = (
                            valore.decode() if isinstance(valore, bytes) else str(valore)
                        ).strip()
                        break
        finally:
            conn.unbind_s()
    except ldap.LDAPError:
        log.exception("Indirizzi non letti da LDAP: si usano quelli salvati")
    return trovati


def indirizzi(utenti: Iterable) -> dict[int, str]:
    """``{pk dell'utente: indirizzo}``: prima LDAP, poi l'indirizzo salvato. Chi non ne ha è
    escluso. L'indirizzo letto da LDAP e diverso da quello salvato lo aggiorna."""
    utenti = list(utenti)
    da_ldap = indirizzi_ldap(u.get_username() for u in utenti)
    risultato: dict[int, str] = {}
    for u in utenti:
        letto = da_ldap.get(u.get_username().strip().lower(), "")
        salvato = (u.email or "").strip()
        if letto and letto != salvato:
            get_user_model().objects.filter(pk=u.pk).update(email=letto)
            u.email = letto
        if scelto := (letto or salvato):
            risultato[u.pk] = scelto
    return risultato
