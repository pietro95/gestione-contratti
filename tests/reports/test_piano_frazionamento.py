"""Avviso di frazionamento del piano ordini (SPEC §5.4): soglia sul livello massimo."""

import datetime
from decimal import Decimal

import pytest

from reports.piano_ordini import calcola_piano, soglie_valide

from .. import factories as f

pytestmark = pytest.mark.django_db
OGGI = datetime.date(2026, 10, 1)


def _in_scadenza(descrizione, fisso, massimale="0", *, sottocluster=None, fornitore=None):
    """Contratto annuale 2026, rinnovo previsto con avvio 01/01/2027."""
    fab = f.fabbisogno(
        descrizione, decisione="rinnovare", sottocluster=sottocluster or f.sottocluster()
    )
    c = f.contratto(
        fabbisogno=fab, fornitore=fornitore or f.fornitore(f"Fornitore di {descrizione}")
    )
    f.voce(c, importo_fisso=Decimal(fisso), massimale_variabile=Decimal(massimale))
    return c


def test_soglia_valida_alla_data():
    (soglia,) = soglie_valide(datetime.date(2027, 1, 1))
    assert soglia.importo == Decimal("140000.00")
    assert soglie_valide(datetime.date(2023, 6, 30)) == []


def test_somma_per_sottocluster_oltre_soglia():
    _in_scadenza("Licenza A", "80000.00")
    _in_scadenza("Licenza B", "50000.00", "10000.00")  # massimo 60.000
    piano = calcola_piano(2027, OGGI)
    (avviso,) = piano.avvisi
    assert (avviso.tipo, avviso.nome) == ("sottocluster", "IT · Licenze software")
    assert avviso.totale_massimo == Decimal("140000.00")  # limite escluso: scatta
    assert {r.fabbisogno.descrizione for r in avviso.righe} == {"Licenza A", "Licenza B"}
    assert all(not r.sopra_soglia for r in piano.righe)


def test_sotto_soglia_nessun_avviso():
    _in_scadenza("Licenza A", "80000.00")
    _in_scadenza("Licenza B", "59999.99")
    assert calcola_piano(2027, OGGI).avvisi == []


def test_somma_per_fornitore_e_singolo_oltre_soglia():
    fornitore = f.fornitore("Fornitore Unico S.r.l.")
    _in_scadenza("Servizio A", "100000.00", fornitore=fornitore)
    _in_scadenza(
        "Servizio B", "150000.00", sottocluster=f.sottocluster("Connettività"), fornitore=fornitore
    )
    piano = calcola_piano(2027, OGGI)
    assert [(a.tipo, a.nome) for a in piano.avvisi] == [("fornitore", "Fornitore Unico S.r.l.")]
    (grande,) = [r for r in piano.da_avviare if r.fabbisogno.descrizione == "Servizio B"]
    assert grande.sopra_soglia


def test_senza_sottocluster_e_non_indicato_non_si_raggruppano():
    anonimo = f.fornitore("(non indicato)")
    for nome in ("Riga import 1", "Riga import 2"):
        fab = f.fabbisogno(nome, decisione="rinnovare")
        c = f.contratto(fabbisogno=fab, fornitore=anonimo)
        f.voce(c, importo_fisso=Decimal("90000.00"))
    assert calcola_piano(2027, OGGI).avvisi == []


def test_filtri_area_e_sottocluster():
    _in_scadenza("Licenza A", "1000.00")
    c = _in_scadenza("Rete B", "1000.00", sottocluster=f.sottocluster("Connettività"))
    c.fabbisogno.cluster = f.cluster("TLC")
    c.fabbisogno.save()
    assert [r.fabbisogno.descrizione for r in calcola_piano(2027, OGGI, area="TLC").da_avviare] == [
        "Rete B"
    ]
    sottocluster = f.sottocluster().pk
    righe = calcola_piano(2027, OGGI, sottocluster=sottocluster).da_avviare
    assert [r.fabbisogno.descrizione for r in righe] == ["Licenza A"]
