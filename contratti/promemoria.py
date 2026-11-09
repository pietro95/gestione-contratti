"""Promemoria periodici per email (SPEC §5.10, Rev39): rilasci in attesa e contratti in scadenza.

Li lancia ``manage.py invia_promemoria`` (una volta al giorno lavorativo, dal container
``notifiche``). Ogni promemoria ha una ``chiave`` di periodo: rilasci, un messaggio al giorno;
scadenze, uno alla settimana. Rilanciare il comando nello stesso periodo non rimanda niente.
"""

import datetime
from collections import defaultdict
from dataclasses import dataclass

from contratti import acquisti, fatture, notifiche, selettori
from contratti.engine.tipi import Alert

TITOLI_ALERT = {
    Alert.ROSSO: "Scaduti senza rinnovo",
    Alert.ARANCIONE: "Data limite superata, pratica non avviata",
    Alert.GIALLO: "In avvicinamento o con la pratica in corso",
}


@dataclass
class Messaggio:
    tipo: str
    destinatari: list
    oggetto: str
    corpo: str
    chiave: str


def messaggi_rilasci(oggi: datetime.date) -> list[Messaggio]:
    """RDA, RdC e MAP in attesa di rilascio su SAP → addetto al rilascio (se c'è qualcosa)."""
    rda = acquisti.rda_da_rilasciare()
    documenti = fatture.documenti_da_rilasciare()
    if not rda and not documenti:
        return []
    righe = ["Ci sono rilasci su SAP in attesa:", ""]
    if rda:
        righe.append(f"RDA da rilasciare ({len(rda)}):")
        for r in rda:
            giorni = (oggi - (r.data_inserimento or oggi)).days
            righe.append(f"- {r.numero_rda} — {r.intestazione or r} (inserita da {giorni} giorni)")
        righe.append("")
    if documenti:
        righe.append(f"RdC e MAP da rilasciare ({len(documenti)}):")
        for d in documenti:
            giorni = (oggi - d.data).days
            righe.append(
                f"- {d.get_tipo_display()} {d.numero} — fattura {d.fattura.numero} "
                f"di {d.fattura.fornitore} (da {giorni} giorni)"
            )
        righe.append("")
    righe.append(f"Maschera dei rilasci: {notifiche.link('rilasci')}")
    totale = len(rda) + len(documenti)
    return [
        Messaggio(
            notifiche.Tipo.RILASCI_IN_ATTESA,
            notifiche.addetti_al_rilascio(),
            f"{totale} rilasci in attesa su SAP",
            "\n".join(righe),
            chiave=f"{oggi:%Y-%m-%d}",
        )
    ]


def messaggi_scadenze(oggi: datetime.date) -> list[Messaggio]:
    """Contratti in scadenza (alert rosso, arancione, giallo del cruscotto) → ai referenti
    dei fabbisogni, un messaggio ciascuno con i propri contratti."""
    gruppi = selettori.cruscotto(oggi, {})
    per_referente: dict[int, dict] = defaultdict(lambda: {"utente": None, "righe": {}})
    for alert in (Alert.ROSSO, Alert.ARANCIONE, Alert.GIALLO):
        for riga in gruppi[alert]:
            fabbisogno = riga.previsto_manuale or riga.contratto.fabbisogno
            referente = fabbisogno.referente_utente
            if referente is None:
                continue
            voce = per_referente[referente.pk]
            voce["utente"] = referente
            voce["righe"].setdefault(alert, []).append(riga)
    iso = oggi.isocalendar()
    messaggi = []
    for voce in per_referente.values():
        righe = ["Questi contratti, di cui sei il referente, hanno una scadenza da seguire:", ""]
        totale = 0
        for alert, titolo in TITOLI_ALERT.items():
            elenco = voce["righe"].get(alert, [])
            if not elenco:
                continue
            totale += len(elenco)
            righe.append(f"{titolo} ({len(elenco)}):")
            for r in elenco:
                righe.append(f"- {_descrivi(r)}")
            righe.append("")
        righe.append(f"Cruscotto: {notifiche.link('cruscotto')}")
        messaggi.append(
            Messaggio(
                notifiche.Tipo.CONTRATTI_IN_SCADENZA,
                [voce["utente"]],
                f"{totale} contratti in scadenza",
                "\n".join(righe),
                chiave=f"{iso.year}-W{iso.week:02d}",
            )
        )
    return messaggi


def _descrivi(riga) -> str:
    if riga.previsto_manuale is not None:
        base = f"{riga.previsto_manuale.descrizione} (previsto, senza contratto)"
    else:
        c = riga.contratto
        base = (
            f"{c.numero_contratto or 'senza numero'} — {c.fornitore} — {c.fabbisogno.descrizione}"
        )
    fine = f"fine {riga.fine:%d/%m/%Y}" if riga.fine else "senza data di fine"
    limite = f", da avviare entro il {riga.data_limite:%d/%m/%Y}" if riga.data_limite else ""
    return f"{base} · {fine}{limite}"


GENERATORI = {"rilasci": messaggi_rilasci, "scadenze": messaggi_scadenze}


def invia_promemoria(oggi: datetime.date, tipi=("rilasci", "scadenze"), simula=False):
    """Prepara e (se non ``simula``) spedisce i promemoria; restituisce i messaggi e le
    email partite."""
    messaggi: list[Messaggio] = []
    for tipo in tipi:
        messaggi += GENERATORI[tipo](oggi)
    partite = 0
    if not simula:
        for msg in messaggi:
            partite += notifiche.invia(
                msg.tipo, msg.destinatari, msg.oggetto, msg.corpo, chiave=msg.chiave
            )
    return messaggi, partite
