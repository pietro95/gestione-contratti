"""Data di fine, data limite, data ultima di disdetta e alert (SPEC §5.1)."""

import datetime

from contratti.engine.date import UN_GIORNO, aggiungi_mesi
from contratti.engine.tipi import Alert, Scadenza

# Stati della pratica che a data limite superata danno l'arancione (SPEC §5.1, regola 3).
STATI_NON_AVANZATI = frozenset({"non_avviata", "offerta_richiesta"})
DECISIONI_SENZA_ALERT = frozenset({"dismettere"})


def data_fine_contrattuale(s: Scadenza) -> datetime.date:
    """Inizio + durata − 1 giorno, salvo override."""
    return s.fine_override or aggiungi_mesi(s.inizio, s.durata_mesi) - UN_GIORNO


def data_fine_effettiva(s: Scadenza) -> datetime.date:
    """Con proroghe: la nuova data di fine più lontana (TC-10)."""
    return max((data_fine_contrattuale(s), *s.nuove_date_fine))


def data_limite_avvio(s: Scadenza) -> datetime.date:
    return aggiungi_mesi(data_fine_effettiva(s), -s.lead_time_mesi)


def data_ultima_disdetta(s: Scadenza) -> datetime.date | None:
    if not s.tacito_rinnovo or s.preavviso_disdetta_giorni is None:
        return None
    return data_fine_effettiva(s) - datetime.timedelta(days=s.preavviso_disdetta_giorni)


def data_riferimento_alert(s: Scadenza) -> datetime.date:
    """Data limite; col tacito rinnovo, la più vicina tra data limite e ultima disdetta."""
    disdetta = data_ultima_disdetta(s)
    limite = data_limite_avvio(s)
    return min(limite, disdetta) if disdetta else limite


def alert_date(
    fine: datetime.date,
    riferimento: datetime.date,
    oggi: datetime.date,
    *,
    decisione: str,
    stato_pratica: str | None,
    ha_successore: bool,
    finestra_mesi: int,
    una_tantum: bool = False,
) -> Alert | None:
    """Regole di SPEC §5.1 su date già calcolate; vale la prima che si applica.

    Un contratto una tantum non si rinnova e non va mai in alert (Rev13).
    """
    if decisione in DECISIONI_SENZA_ALERT or ha_successore or una_tantum:
        return None
    if oggi > fine:
        return Alert.ROSSO
    stato = stato_pratica or "non_avviata"
    if oggi > riferimento:
        return Alert.ARANCIONE if stato in STATI_NON_AVANZATI else Alert.GIALLO
    if oggi >= aggiungi_mesi(riferimento, -finestra_mesi):
        return Alert.GIALLO
    return Alert.VERDE


def alert(
    s: Scadenza,
    oggi: datetime.date,
    *,
    decisione: str,
    stato_pratica: str | None,
    ha_successore: bool,
    finestra_mesi: int,
    una_tantum: bool = False,
) -> Alert | None:
    """Colore dell'alert di un contratto (TC-06, TC-10, TC-16)."""
    return alert_date(
        data_fine_effettiva(s),
        data_riferimento_alert(s),
        oggi,
        decisione=decisione,
        stato_pratica=stato_pratica,
        ha_successore=ha_successore,
        finestra_mesi=finestra_mesi,
        una_tantum=una_tantum,
    )


def alert_previsto_manuale(
    avvio: datetime.date,
    lead_time_mesi: int,
    oggi: datetime.date,
    *,
    decisione: str,
    stato_pratica: str | None,
    finestra_mesi: int,
) -> Alert | None:
    """Fabbisogno nuovo: il servizio deve partire all'avvio previsto.

    Data limite = avvio − lead time; rosso se l'avvio è passato senza contratto.
    """
    return alert_date(
        avvio - UN_GIORNO,
        aggiungi_mesi(avvio, -lead_time_mesi),
        oggi,
        decisione=decisione,
        stato_pratica=stato_pratica,
        ha_successore=False,
        finestra_mesi=finestra_mesi,
    )
