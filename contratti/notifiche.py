"""Notifiche per email (SPEC §5.10, Rev39).

Il portale non scrive mai a nome dell'utente: sono messaggi automatici, in sola informazione,
con il link alla pagina da cui lavorare. Regole:

- un'email per destinatario (nessun elenco in chiaro di colleghi), registrata in ``InvioEmail``;
- chi ha fatto l'azione non riceve l'email che ne parla;
- un errore di spedizione non blocca mai l'operazione: si registra e si scrive nel log;
- gli avvisi legati a un'azione partono dopo il commit della transazione;
- con ``NOTIFICHE_EMAIL_ATTIVE`` falso (nessun server SMTP) non parte niente.

Destinatari: l'addetto amministrativo e l'addetto al rilascio sono gli utenti con la funzione
(gruppo AD o assegnazione locale, ``contratti.permessi``); i referenti sono gli utenti dei
fabbisogni e delle RDA; «tutti» sono gli utenti che possono lavorare le fatture (Admin ed
Editor). Gli indirizzi si leggono da LDAP (``mail``) al momento dell'invio; chi non ne ha è saltato.
"""

import logging
from collections.abc import Callable, Iterable

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMessage
from django.db import transaction
from django.db.models import Q
from django.db.models.functions import Lower
from django.urls import reverse

from accounts import rubrica
from accounts.roles import ADDETTO_AMMINISTRATIVO, ADDETTO_RILASCIO, WRITE_ROLES, role_of
from contratti import models as m
from contratti.engine.acquisti import formato_euro

log = logging.getLogger("contratti.notifiche")

PREFISSO_OGGETTO = "[Registro contratti]"
FIRMA = "\n--\nMessaggio automatico del Registro contratti ICTDINN: non rispondere a questa email."


class Tipo:
    RDA_INVIATA = "rda_inviata"
    RDA_RIMANDATA = "rda_rimandata"
    RDA_DA_RILASCIARE = "rda_da_rilasciare"
    DOCUMENTO_DA_RILASCIARE = "documento_da_rilasciare"
    RILASCI_IN_ATTESA = "rilasci_in_attesa"
    CONTRATTI_IN_SCADENZA = "contratti_in_scadenza"
    FATTURE_NUOVE = "fatture_nuove"
    FATTURA_ASSEGNATA = "fattura_assegnata"
    FATTURA_CONVALIDATA = "fattura_convalidata"


# --- Destinatari ----------------------------------------------------------------------------


def _attivi(utenti: Iterable) -> list:
    """Utenti attivi, senza doppioni, nell'ordine di arrivo. L'indirizzo si legge da LDAP
    solo all'invio (``accounts.rubrica``): qui non si scarta nessuno."""
    visti: set[int] = set()
    risultato = []
    for u in utenti:
        if not u.is_active or u.pk in visti:
            continue
        visti.add(u.pk)
        risultato.append(u)
    return risultato


def utenti_operativi() -> list:
    """Chi può lavorare le fatture: Admin ed Editor attivi."""
    qs = get_user_model().objects.filter(is_active=True).order_by("pk")
    return _attivi(u for u in qs if role_of(u) in WRITE_ROLES)


def _con_funzione(funzione: str, gruppo: str) -> list:
    nomi = [
        n.strip().lower()
        for n in m.FunzioneUtente.objects.filter(funzione=funzione, archiviato=False).values_list(
            "username", flat=True
        )
    ]
    utenti = (
        get_user_model()
        .objects.filter(is_active=True)
        .annotate(nome_minuscolo=Lower("username"))
        .filter(Q(groups__name=gruppo) | Q(nome_minuscolo__in=nomi))
        .distinct()
        .order_by("pk")
    )
    return _attivi(u for u in utenti if role_of(u) in WRITE_ROLES)


def addetti_amministrativi() -> list:
    return _con_funzione(m.FunzioneUtente.Funzione.AMMINISTRAZIONE_ACQUISTI, ADDETTO_AMMINISTRATIVO)


def addetti_al_rilascio() -> list:
    return _con_funzione(m.FunzioneUtente.Funzione.RILASCIO_SAP, ADDETTO_RILASCIO)


# --- Invio ----------------------------------------------------------------------------------


def link(nome: str, *args) -> str:
    """Indirizzo completo di una pagina dell'interfaccia; senza ``APP_URL`` solo il percorso."""
    return f"{settings.APP_URL}{reverse(f'contratti:{nome}', args=args)}"


def invia(
    tipo: str,
    destinatari: Iterable,
    oggetto: str,
    corpo: str,
    *,
    escludi=None,
    chiave: str = "",
) -> int:
    """Spedisce l'email a ciascun destinatario e la registra; restituisce quante sono partite.

    ``escludi`` è l'utente che ha fatto l'azione. Con una ``chiave`` il messaggio non si
    rimanda allo stesso destinatario (promemoria dello stesso giorno o della stessa settimana).
    """
    if not settings.NOTIFICHE_EMAIL_ATTIVE:
        return 0
    partite = 0
    candidati = [
        u for u in _attivi(destinatari) if escludi is None or u.pk != getattr(escludi, "pk", None)
    ]
    # Indirizzi da LDAP (con ripiego su quello salvato); chi non ne ha non riceve niente.
    indirizzi = rubrica.indirizzi(candidati)
    visti: set[str] = set()
    for utente in candidati:
        email = indirizzi.get(utente.pk, "")
        if not email or email.lower() in visti:
            continue
        visti.add(email.lower())
        if (
            chiave
            and m.InvioEmail.objects.filter(
                tipo=tipo, destinatario__iexact=email, chiave=chiave, esito="inviata"
            ).exists()
        ):
            continue
        soggetto = f"{PREFISSO_OGGETTO} {oggetto}"
        registro = m.InvioEmail(
            tipo=tipo, destinatario=email, oggetto=soggetto[:250], chiave=chiave
        )
        try:
            EmailMessage(subject=soggetto, body=corpo + FIRMA, to=[email]).send(fail_silently=False)
        except Exception as exc:  # noqa: BLE001 - la notifica non deve mai bloccare il lavoro
            log.exception("Email %s a %s non spedita", tipo, email)
            registro.esito, registro.errore = m.InvioEmail.Esito.ERRORE, str(exc)[:1000]
        else:
            registro.esito = m.InvioEmail.Esito.INVIATA
            partite += 1
        registro.save()
    return partite


def dopo_commit(funzione: Callable[[], object]) -> None:
    """Esegue la notifica a transazione conclusa, senza mai far fallire l'operazione."""

    def _esegui():
        try:
            funzione()
        except Exception:  # noqa: BLE001
            log.exception("Notifica non preparata")

    transaction.on_commit(_esegui)


# --- Testi ----------------------------------------------------------------------------------


def _euro(valore) -> str:
    return "—" if valore is None else formato_euro(valore)


def _importo_rda(rda: m.RichiestaAcquisto):
    from contratti import acquisti  # import locale: acquisti avvisa tramite questo modulo

    return acquisti.importo_rda(rda)


def _nome(utente) -> str:
    return str(utente) if utente is not None else "—"


def rda_inviata(rda: m.RichiestaAcquisto, utente=None) -> int:
    """Nuova richiesta di RDA (o corretta dopo un rimando) → addetto amministrativo."""
    corpo = (
        "C'è una richiesta di RDA da inserire in SAP.\n\n"
        f"Richiesta: {rda.intestazione or rda}\n"
        f"Referente: {rda.nome_referente or _nome(utente)}\n"
        f"Importo: {_euro(_importo_rda(rda))}\n\n"
        f"Apri la scheda SAP: {link('rda', rda.pk)}"
    )
    return invia(
        Tipo.RDA_INVIATA,
        addetti_amministrativi(),
        f"Nuova RDA da inserire: {rda.intestazione or rda}",
        corpo,
        escludi=utente,
    )


def rda_rimandata(rda: m.RichiestaAcquisto, nota: str, utente=None) -> int:
    """L'addetto rimanda la richiesta al referente → referente della RDA."""
    if rda.referente_utente_id is None:
        return 0
    corpo = (
        "La tua richiesta di RDA è stata rimandata: va corretta e inviata di nuovo.\n\n"
        f"Richiesta: {rda.intestazione or rda}\n"
        f"Cosa correggere: {nota.strip()}\n\n"
        f"Apri la richiesta: {link('rda', rda.pk)}"
    )
    return invia(
        Tipo.RDA_RIMANDATA,
        [rda.referente_utente],
        f"RDA rimandata: {rda.intestazione or rda}",
        corpo,
        escludi=utente,
    )


def rda_da_rilasciare(rda: m.RichiestaAcquisto, utente=None) -> int:
    """RDA inserita in SAP, in attesa di rilascio → addetto al rilascio."""
    corpo = (
        "Una RDA inserita in SAP aspetta il rilascio.\n\n"
        f"RDA: {rda.numero_rda} — {rda.intestazione or rda}\n"
        f"Importo: {_euro(_importo_rda(rda))}\n\n"
        f"Maschera dei rilasci: {link('rilasci')}"
    )
    return invia(
        Tipo.RDA_DA_RILASCIARE,
        addetti_al_rilascio(),
        f"RDA {rda.numero_rda} da rilasciare",
        corpo,
        escludi=utente,
    )


def documento_da_rilasciare(documento: m.DocumentoEsecuzione, utente=None) -> int:
    """RdC o MAP registrato dalla fattura, in attesa di rilascio → addetto al rilascio."""
    fattura = documento.fattura
    corpo = (
        f"{documento.get_tipo_display()} {documento.numero} da rilasciare su SAP.\n\n"
        f"Fattura: {fattura.numero} di {fattura.fornitore}\n\n"
        f"Maschera dei rilasci: {link('rilasci')}"
    )
    return invia(
        Tipo.DOCUMENTO_DA_RILASCIARE,
        addetti_al_rilascio(),
        f"{documento.get_tipo_display()} {documento.numero} da rilasciare",
        corpo,
        escludi=utente,
    )


def fatture_nuove(quante: int, utente=None) -> int:
    """Nuove fatture da prendere in carico (dopo un caricamento) → tutti gli utenti operativi."""
    if quante <= 0:
        return 0
    una = quante == 1
    corpo = (
        f"{'È arrivata 1 nuova fattura' if una else f'Sono arrivate {quante} nuove fatture'} "
        "da prendere in carico.\n\n"
        f"Apri l'elenco: {link('fatture')}?vista=da_prendere"
    )
    return invia(
        Tipo.FATTURE_NUOVE,
        utenti_operativi(),
        "1 nuova fattura da prendere in carico"
        if una
        else f"{quante} nuove fatture da prendere in carico",
        corpo,
        escludi=utente,
    )


def fattura_assegnata(fattura: m.Fattura, referente, utente=None) -> int:
    """Fattura assegnata o riassegnata a un referente → quel referente."""
    corpo = (
        "Ti è stata assegnata una fattura da lavorare.\n\n"
        f"Fattura: {fattura.numero} di {fattura.fornitore}\n"
        f"Importo del documento: {_euro(fattura.importo_documento)}\n\n"
        f"Apri la fattura: {link('fattura', fattura.pk)}"
    )
    return invia(
        Tipo.FATTURA_ASSEGNATA,
        [referente],
        f"Fattura {fattura.numero} assegnata a te",
        corpo,
        escludi=utente,
    )


def fattura_convalidata(fattura: m.Fattura, utente=None) -> int:
    """Fattura convalidabile → addetto amministrativo (RdC e MAP/MIGO da fare)."""
    corpo = (
        "Una fattura è stata convalidata dal referente: tocca all'amministrazione.\n\n"
        f"Fattura: {fattura.numero} di {fattura.fornitore}\n"
        f"Referente: {_nome(fattura.referente)}\n\n"
        f"Apri la fattura: {link('fattura', fattura.pk)}"
    )
    return invia(
        Tipo.FATTURA_CONVALIDATA,
        addetti_amministrativi(),
        f"Fattura {fattura.numero} convalidata: RdC da fare",
        corpo,
        escludi=utente,
    )
