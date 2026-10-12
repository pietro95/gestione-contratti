"""Accettazione F5: i totali dei report coincidono con il motore sulle stesse voci."""

import datetime
from decimal import Decimal

import pytest

from contratti.engine.tipi import Livello
from reports.budget import LIVELLI, VISTE, Filtri, calcola_budget
from reports.piano_ordini import calcola_piano

from .conftest import ANNI, OGGI, totali_motore, voci_motore

pytestmark = pytest.mark.django_db
ZERO = Decimal("0.00")


def test_budget_coincide_con_il_motore(archivio):
    """Per ogni anno, parte, vista e livello: report = motore sulle stesse voci, al centesimo."""
    for anno in ANNI:
        totali = calcola_budget(Filtri(anno=anno, progetti="includi"), OGGI).totali()
        consolidate, previste = voci_motore(anno)
        attesi = {
            "consolidato": totali_motore(consolidate, anno),
            "previsionale": totali_motore(previste, anno),
            "totale": totali_motore(consolidate + previste, anno),
        }
        for parte, per_vista in attesi.items():
            for vista in VISTE:
                for livello in LIVELLI:
                    atteso = per_vista[vista].get(livello, ZERO)
                    assert totali[parte][vista][livello] == atteso, (anno, parte, vista, livello)


def test_ci_sono_importi_in_tutte_le_parti(archivio):
    totali = calcola_budget(Filtri(anno=2027, progetti="includi"), OGGI).totali()
    for parte in ("consolidato", "previsionale"):
        for vista in VISTE:
            assert totali[parte][vista][Livello.FISSO] > 0, (parte, vista)
    # Il variabile stimato al 50% separa i livelli.
    impegno = totali["totale"]["impegno"]
    assert impegno[Livello.FISSO] <= impegno[Livello.PROBABILE] <= impegno[Livello.MASSIMO]


def test_i_gruppi_sommano_al_totale(archivio):
    b = calcola_budget(Filtri(anno=2026, progetti="includi"), OGGI)
    totali = b.totali()
    for criterio in ("conto", "area", "fornitore", "wbs", "fabbisogno"):
        gruppi = b.gruppi(criterio)
        for vista in VISTE:
            for livello in LIVELLI:
                somma = sum((g.totali["totale"][vista][livello] for g in gruppi), ZERO)
                assert somma == totali["totale"][vista][livello], criterio


def test_filtri_partizionano_il_totale(archivio):
    tutto = calcola_budget(Filtri(anno=2026, progetti="includi"), OGGI).totali()["totale"]
    for campo, valori in (
        ("area", ["IT", "TLC"]),
        ("progetti", ["", "solo"]),  # senza WBS a progetto + solo WBS a progetto
        ("natura", ["OPEX", "CAPEX"]),
    ):
        parti = [
            calcola_budget(
                Filtri(anno=2026, **({"progetti": "includi"} | {campo: v})), OGGI
            ).totali()["totale"]
            for v in valori
        ]
        for vista in VISTE:
            assert sum(p[vista][Livello.MASSIMO] for p in parti) == tutto[vista][Livello.MASSIMO]


def test_filtro_conto_e_fornitore(archivio, conti):
    b = calcola_budget(Filtri(anno=2026, conto=conti["627020"].pk), OGGI)
    assert b.voci and all(v.conto == conti["627020"] for v in b.voci)
    fornitore = archivio.fornitore
    b = calcola_budget(Filtri(anno=2027, fornitore=fornitore.pk, progetti="includi"), OGGI)
    assert b.voci and all(v.fornitore == fornitore for v in b.voci)
    # Il contratto è su una WBS a progetto: fuori dal budget del cluster (F9.2).
    assert not calcola_budget(Filtri(anno=2027, fornitore=fornitore.pk), OGGI).voci


def test_solo_consolidato_esclude_i_previsti(archivio):
    b = calcola_budget(Filtri(anno=2027, previsionali=False, progetti="includi"), OGGI)
    assert b.voci and not any(v.previsionale for v in b.voci)
    assert b.totali()["previsionale"]["impegno"][Livello.MASSIMO] == ZERO


def test_cassa_usa_lo_scadenzario_salvato(archivio):
    """Posticipato trimestrale 12.000 € su 24 mesi: 4 rate nel 2026 (l'ultima il 31/12)."""
    b = calcola_budget(Filtri(anno=2026, previsionali=False, progetti="includi"), OGGI)
    (voce,) = [v for v in b.voci if v.contratto == archivio and v.voce.proroga is None]
    assert voce.importi["cassa"][Livello.FISSO] == Decimal("6000.00")
    assert voce.importi["impegno"][Livello.FISSO] == ZERO  # OdA del 2025
    assert voce.importi["competenza"][Livello.FISSO] == Decimal("6000.00")  # 365/730 giorni
    assert voce.importi["impegno"][Livello.PROBABILE] == ZERO


def test_proroga_nell_anno_dell_atto(archivio):
    b = calcola_budget(Filtri(anno=2027, previsionali=False, progetti="includi"), OGGI)
    (proroga,) = [v for v in b.voci if v.voce and v.voce.proroga_id]
    assert proroga.importi["impegno"][Livello.FISSO] == Decimal("3000.00")
    assert proroga.inizio == datetime.date(2028, 1, 1)


def test_rinnovi_mancanti(db):
    from .. import factories as f

    vecchio = f.contratto(
        fabbisogno=f.fabbisogno("Servizio scaduto da tempo", decisione="rinnovare"),
        data_inizio=datetime.date(2022, 1, 1),
        durata_mesi=12,
    )
    f.voce(vecchio, importo_fisso=Decimal("1200.00"))
    b = calcola_budget(Filtri(anno=2026), OGGI)
    (mancante,) = b.rinnovi_mancanti
    assert mancante.fabbisogno == vecchio.fabbisogno
    assert mancante.previsti_esclusi == 3  # 2023, 2024, 2025
    assert mancante.dal == datetime.date(2023, 1, 1)
    # Il previsto 2026 entra nel budget.
    assert b.totali()["previsionale"]["impegno"][Livello.FISSO] == Decimal("1200.00")
    # In un anno futuro i previsti non ancora conclusi non sono "mancanti".
    b = calcola_budget(Filtri(anno=2028), OGGI)
    assert b.rinnovi_mancanti[0].previsti_esclusi == 3


def test_piano_ordini_per_anno_della_data_limite(archivio):
    """SPEC §5.4 Rev16-17: da avviare nell'anno della data limite, poi da concludere."""
    for anno in (2026, 2027, 2028):
        piano = calcola_piano(anno, OGGI)
        assert piano.da_avviare
        assert all(r.data_limite.year == anno for r in piano.da_avviare)
        assert all(r.data_limite.year < anno for r in piano.da_concludere)
        assert all(not r.in_ritardo for r in piano.righe) or anno == OGGI.year
        date_limite = [r.data_limite for r in piano.righe]
        assert date_limite == sorted(date_limite)


def test_piano_ordini_previsto_manuale(archivio):
    piano = calcola_piano(2026, OGGI)  # data limite 01/09/2026 (SPEC §5.4 Rev16)
    (riga,) = [
        r for r in piano.righe if r.fabbisogno.descrizione == "Nuovo servizio previsto a mano"
    ]
    assert riga.contratto_uscente is None
    assert riga.procedura.codice == "da_verificare"
    assert riga.lead_time_mesi == 6
    assert riga.data_limite == datetime.date(2026, 9, 1)
    assert riga.importi[Livello.MASSIMO] == Decimal("50000.00")
    assert riga.stato_pratica_label == "Non avviata"


def test_piano_ordini_rinnovo_con_stato_pratica(archivio):
    from contratti import servizi

    servizi.avanza_pratica(archivio, "offerta_richiesta", datetime.date(2026, 9, 1))
    piano = calcola_piano(2028, OGGI)
    (riga,) = [r for r in piano.righe if r.contratto_uscente == archivio]
    assert riga.avvio == datetime.date(2028, 7, 1)  # dopo la proroga al 30/06/2028
    assert riga.durata_mesi == 24
    assert riga.data_limite == datetime.date(2028, 4, 30)  # 30/06/2028 − 2 mesi di lead time
    assert riga.stato_pratica == "offerta_richiesta"
    # Le voci delle proroghe non si replicano nel previsto.
    assert riga.importi[Livello.FISSO] == Decimal("12000.00")
    assert riga.importi[Livello.MASSIMO] == Decimal("15000.00")
