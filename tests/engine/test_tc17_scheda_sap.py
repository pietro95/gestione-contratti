"""TC-17: scheda SAP, nome della cartella e testo della richiesta di RDA (parte del motore)."""

from decimal import Decimal

import pytest

from contratti.engine.acquisti import (
    PosizioneScheda,
    SchedaRDA,
    componi_testo_richiesta,
    formato_euro,
    formato_quantita,
    importo_posizione,
    intestazione,
    nome_cartella,
    percorso_cartella,
)

from .casi import D

BASE = "smb://nas.esempio.local/Share/ICTDINN/00_IT/RDA_Ordini"
OGGI = D(2026, 9, 29)
DESCRIZIONE = "Rinnovo licenza CAD (2 postazioni)"
CARTELLA = "2026_09_29_SWPROVA_Rinnovo_licenza_CAD_2_postazioni"


def test_importo_posizione_arrotondato():
    assert importo_posizione(Decimal("2"), Decimal("549.50")) == Decimal("1099.00")
    assert importo_posizione(Decimal("2.5"), Decimal("99.99")) == Decimal("249.98")


def test_intestazione():
    assert intestazione("SWPROVA", DESCRIZIONE) == f"SWPROVA - {DESCRIZIONE}"
    assert intestazione(None, DESCRIZIONE) == DESCRIZIONE
    assert (
        intestazione("Software Prova S.r.l.", DESCRIZIONE)
        == f"Software Prova S.r.l. - {DESCRIZIONE}"
    )


@pytest.mark.parametrize(
    ("fornitore", "descrizione", "cartella"),
    [
        ("SWPROVA", DESCRIZIONE, CARTELLA),
        (None, DESCRIZIONE, "2026_09_29_Rinnovo_licenza_CAD_2_postazioni"),
        (
            "Software Prova S.r.l.",
            DESCRIZIONE,
            "2026_09_29_Software_Prova_S_r_l_Rinnovo_licenza_CAD_2_postazioni",
        ),
        ("SWPROVA", "Manutenzione unità UPS", "2026_09_29_SWPROVA_Manutenzione_unita_UPS"),
    ],
)
def test_nome_cartella(fornitore, descrizione, cartella):
    assert nome_cartella(OGGI, fornitore, descrizione) == cartella


def test_percorso():
    assert percorso_cartella(BASE, OGGI, "SWPROVA", DESCRIZIONE) == f"{BASE}/2026/{CARTELLA}"
    assert percorso_cartella(BASE + "/", OGGI, "SWPROVA", DESCRIZIONE) == f"{BASE}/2026/{CARTELLA}"
    assert percorso_cartella("", OGGI, "SWPROVA", DESCRIZIONE) == ""
    assert (
        percorso_cartella("X:\\ICTDINN\\RDA", OGGI, None, "Prova")
        == "X:\\ICTDINN\\RDA\\2026\\2026_09_29_Prova"
    )


def test_formati():
    assert formato_euro(Decimal("1348.98")) == "1.348,98 €"
    assert formato_euro(Decimal("549.5")) == "549,50 €"
    assert formato_quantita(Decimal("2.000")) == "2"
    assert formato_quantita(Decimal("2.500")) == "2,5"


SCHEDA = SchedaRDA(
    intestazione=f"SWPROVA - {DESCRIZIONE}",
    posizioni=(
        PosizioneScheda(
            f"SWPROVA - {DESCRIZIONE}", "GM-TEST01", Decimal("2"), Decimal("549.50"),
            conto="600001", centro_costo="C0001",
        ),
        PosizioneScheda(
            "Supporto installazione", "GM-TEST02", Decimal("2.5"), Decimal("99.99"),
            conto="600002", centro_costo="C0001",
        ),
    ),
    richiedente="999901",
    gruppo_acquisti="G01",
    note_buyer="Si allega preventivo",
    allegati="preventivo nella cartella del file server",
    percorso=f"{BASE}/2026/{CARTELLA}",
)  # fmt: skip

TESTO_ATTESO = f"""Si deve predisporre la seguente RDA.

(Campo SAP) Intestazione: SWPROVA - Rinnovo licenza CAD (2 postazioni)

(Campo SAP) Descrizione breve 1: SWPROVA - Rinnovo licenza CAD (2 postazioni)
(Campo SAP) Gruppo merci 1: GM-TEST01
(Campo SAP) Quantità 1: 2
(Campo SAP) Importo unitario 1: 549,50 €
(Campo informativo) Codice WBS 1: --
(Campo informativo) Codice conto 1: 600001
(Campo informativo) Centro di costo 1: C0001

(Campo SAP) Descrizione breve 2: Supporto installazione
(Campo SAP) Gruppo merci 2: GM-TEST02
(Campo SAP) Quantità 2: 2,5
(Campo SAP) Importo unitario 2: 99,99 €
(Campo informativo) Codice WBS 2: --
(Campo informativo) Codice conto 2: 600002
(Campo informativo) Centro di costo 2: C0001

(Campo SAP) Richiedente: 999901
(Campo SAP) Gruppo Acquisti: G01

(Campo SAP) (Opzionale) Note al buyer: Si allega preventivo

(Campo SAP) Allegati: preventivo nella cartella del file server

(Campo informativo) Importo totale: 1.348,98 €
(Campo informativo) File server: {BASE}/2026/{CARTELLA}
"""


def test_testo_della_richiesta():
    assert SCHEDA.importo_totale == Decimal("1348.98")
    assert componi_testo_richiesta(SCHEDA) == TESTO_ATTESO


def test_senza_note_al_buyer_la_riga_non_compare():
    from dataclasses import replace

    testo = componi_testo_richiesta(replace(SCHEDA, note_buyer=""))
    assert "Note al buyer" not in testo
    assert "Allegati" in testo
