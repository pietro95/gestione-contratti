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


def alert(
    s: Scadenza,
    oggi: datetime.date,
    *,
    decisione: str,
    stato_pratica: str | None,
    ha_successore: bool,
    finestra_mesi: int,
) -> Alert | None:
    """Colore dell'alert; le regole si valutano in ordine e vale la prima (TC-06)."""
    if decisione in DECISIONI_SENZA_ALERT or ha_successore:
        return None
    if oggi > data_fine_effettiva(s):
        return Alert.ROSSO
    riferimento = data_riferimento_alert(s)
    stato = stato_pratica or "non_avviata"
    if oggi > riferimento:
        return Alert.ARANCIONE if stato in STATI_NON_AVANZATI else Alert.GIALLO
    if oggi >= aggiungi_mesi(riferimento, -finestra_mesi):
        return Alert.GIALLO
    return Alert.VERDE
