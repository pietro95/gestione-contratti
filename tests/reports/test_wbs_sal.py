"""Spese per WBS delle voci a SAL (SPEC §5.2, Rev29): fatture e quote, mai ripartite sul tempo.

Caso di riferimento (anonimo): lavori a SAL, importo fisso 2.947.639,75, dal 15/10/2024 al
31/03/2027, quote ad anno solare e sei fatture del 2025 e 2026.
"""

import datetime
import io
from decimal import Decimal

import openpyxl
import pytest
from django.test import Client
from django.urls import reverse

from accounts.roles import READER
from contratti import models as m
from contratti.engine.tipi import Livello
from reports.wbs import spese_wbs

from .. import factories as f

pytestmark = pytest.mark.django_db
D = datetime.date
PASSWORD = "password-locale-di-prova"
FISSO = Decimal("2947639.75")
QUOTE = [
    (D(2024, 1, 1), D(2024, 12, 31), "0.00"),
    (D(2025, 1, 1), D(2025, 12, 31), "1486870.87"),
    (D(2026, 1, 1), D(2026, 12, 31), "1144060.62"),
    (D(2027, 1, 1), D(2027, 12, 31), "316708.26"),
]
FATTURE = [
    (D(2025, 2, 20), "467235.71"),
    (D(2025, 5, 12), "294836.45"),
    (D(2025, 9, 3), "356049.94"),
    (D(2025, 12, 18), "368748.77"),
    (D(2026, 4, 9), "622064.41"),
    (D(2026, 9, 24), "521996.21"),
]


@pytest.fixture
def lavori():
    """Contratto con una voce a SAL su una WBS a progetto."""
    wbs = m.WBS.objects.create(codice_wbs="P.0001.01.0001", descrizione="Automazione impianto")
    c = f.contratto(
        fabbisogno=f.fabbisogno("Lavori impianto"),
        data_inizio=D(2024, 10, 15),
        durata_mesi=29,
        data_fine_override=D(2027, 3, 31),
        numero_contratto="5800000230",
    )
    voce = f.voce(
        c,
        descrizione="Lavori",
        natura="CAPEX",
        wbs=wbs,
        importo_fisso=FISSO,
    )
    f.piano(voce, modalita="sal", periodicita="")
    return {"wbs": wbs, "contratto": c, "voce": voce}


def _quote(voce, quote=QUOTE):
    for dal, al, importo in quote:
        m.QuotaPeriodo.objects.create(voce=voce, dal=dal, al=al, importo=Decimal(importo))


def _fatture(contratto, voce=None, fatture=FATTURE, **kw):
    creata = []
    for i, (data, importo) in enumerate(fatture, start=1):
        creata.append(
            m.Fattura.objects.create(
                fornitore=contratto.fornitore,
                contratto=contratto,
                voce=voce,
                numero=f"F-{contratto.pk}-{i}-{data:%Y%m%d}",
                data=data,
                importo_documento=Decimal(importo) * Decimal("1.22"),
                valore_base=Decimal(importo),
                **kw,
            )
        )
    return creata


def _riga(spese, voce):
    (riga,) = [r for r in spese.righe if r.voce.pk == voce.pk]
    return riga


def _fatturato(wbs):
    return spese_wbs(wbs, "cassa", Livello.FISSO)


# --- Quote -----------------------------------------------------------------------------------


def test_con_quote_la_vista_fatturato_le_usa_per_anno_senza_pro_rata(lavori):
    _quote(lavori["voce"])
    riga = _riga(_fatturato(lavori["wbs"]), lavori["voce"])
    assert riga.per_anno == {
        2025: Decimal("1486870.87"),
        2026: Decimal("1144060.62"),
        2027: Decimal("316708.26"),
    }
    assert riga.per_anno.get(2024, Decimal(0)) == 0  # non i 254.217,84 della ripartizione sul tempo
    assert sum(riga.per_anno.values()) == FISSO
    # Sono quote, cioè previsto: nessuna fattura registrata.
    assert riga.consuntivo == {}
    assert riga.previsto == riga.per_anno
    assert riga.fonte == "SAL: quote per periodo"
    assert riga.non_pianificato == 0


# --- Fatture ---------------------------------------------------------------------------------


def test_senza_quote_la_vista_fatturato_e_la_somma_delle_fatture(lavori):
    _fatture(lavori["contratto"], lavori["voce"])
    s = _fatturato(lavori["wbs"])
    riga = _riga(s, lavori["voce"])
    assert riga.per_anno == {2025: Decimal("1486870.87"), 2026: Decimal("1144060.62")}
    assert 2024 not in riga.per_anno and 2027 not in riga.per_anno
    assert riga.consuntivo == riga.per_anno
    assert riga.previsto == {}
    assert riga.fonte == "SAL: fatture registrate"
    # Il residuo non è fatturato: non pianificato, fuori dai totali, con avviso.
    assert riga.non_pianificato == Decimal("316708.26")
    assert s.totale == Decimal("2630931.49")
    assert s.non_pianificato == Decimal("316708.26")
    assert any("SAL non pianificato" in a for a in riga.avvisi)


def test_fatture_assegnate_al_contratto_senza_voce_vanno_alla_voce(lavori):
    _fatture(lavori["contratto"], voce=None)
    riga = _riga(_fatturato(lavori["wbs"]), lavori["voce"])
    assert riga.per_anno == {2025: Decimal("1486870.87"), 2026: Decimal("1144060.62")}


def test_con_quote_e_fatture_valgono_le_fatture_e_la_quota_degli_anni_dopo(lavori):
    _quote(lavori["voce"])
    _fatture(lavori["contratto"], lavori["voce"])
    riga = _riga(_fatturato(lavori["wbs"]), lavori["voce"])
    assert riga.consuntivo == {2025: Decimal("1486870.87"), 2026: Decimal("1144060.62")}
    assert riga.previsto == {2027: Decimal("316708.26")}
    assert riga.per_anno == {
        2025: Decimal("1486870.87"),
        2026: Decimal("1144060.62"),
        2027: Decimal("316708.26"),
    }
    assert sum(riga.per_anno.values()) == FISSO  # mai oltre il fisso, mai due volte


def test_fatture_non_valide_non_contano(lavori):
    creata = _fatture(lavori["contratto"], lavori["voce"], FATTURE[:3])
    creata[0].archiviato = True
    creata[0].save()
    creata[1].fuori_registro = True
    creata[1].save()
    creata[2].valore_base = None
    creata[2].save()
    riga = _riga(_fatturato(lavori["wbs"]), lavori["voce"])
    assert riga.per_anno == {}
    assert riga.non_pianificato == FISSO


def test_sal_senza_quote_ne_fatture_non_ha_importi(lavori):
    s = _fatturato(lavori["wbs"])
    riga = _riga(s, lavori["voce"])
    assert riga.per_anno == {}
    assert s.totale == 0
    assert riga.non_pianificato == FISSO  # visibile, fuori dai totali
    assert any("SAL non pianificato" in a for a in riga.avvisi)


def test_fattura_con_data_fuori_dal_servizio_conta_nell_anno_del_documento_con_avviso(lavori):
    _fatture(lavori["contratto"], lavori["voce"], [(D(2024, 3, 1), "1000.00")])
    riga = _riga(_fatturato(lavori["wbs"]), lavori["voce"])
    assert riga.per_anno == {2024: Decimal("1000.00")}
    assert any("fuori dal periodo di servizio" in a for a in riga.avvisi)


def test_fattura_senza_competenza_conta_per_data_documento(lavori):
    # La cassa non guarda la competenza: nessun avviso di competenza mancante.
    _fatture(lavori["contratto"], lavori["voce"], [(D(2025, 6, 1), "1000.00")])
    riga = _riga(_fatturato(lavori["wbs"]), lavori["voce"])
    assert not any("competenza" in a.lower() for a in riga.avvisi)


# --- WBS della fattura -----------------------------------------------------------------------


def test_vale_la_wbs_della_fattura_e_la_differenza_e_un_anomalia(lavori):
    altra = m.WBS.objects.create(codice_wbs="P.0002.01.0001", descrizione="Altro progetto")
    prime, ultime = FATTURE[:4], FATTURE[4:]
    _fatture(lavori["contratto"], lavori["voce"], prime)
    spostate = _fatture(lavori["contratto"], lavori["voce"], ultime)
    for fattura in spostate:
        fattura.wbs = altra
        fattura.save()

    # Sulla WBS della voce: le fatture non spostate, il residuo, e le anomalie.
    s = _fatturato(lavori["wbs"])
    riga = _riga(s, lavori["voce"])
    assert riga.per_anno == {2025: Decimal("1486870.87")}
    assert riga.non_pianificato == Decimal("316708.26")  # il residuo sta sulla WBS della voce
    assert len(s.anomalie) == 2
    assert all("P.0002.01.0001" in a and "P.0001.01.0001" in a for a in s.anomalie)

    # Sull'altra WBS: il costo reale, senza residuo e con le stesse anomalie.
    s2 = _fatturato(altra)
    riga2 = _riga(s2, lavori["voce"])
    assert riga2.per_anno == {2026: Decimal("1144060.62")}
    assert riga2.non_pianificato == 0
    assert riga2.previsto == {}
    assert len(s2.anomalie) == 2


def test_wbs_della_fattura_uguale_a_quella_della_voce_non_e_un_anomalia(lavori):
    for fattura in _fatture(lavori["contratto"], lavori["voce"]):
        fattura.wbs = lavori["wbs"]
        fattura.save()
    assert _fatturato(lavori["wbs"]).anomalie == []


def test_la_wbs_della_fattura_conta_solo_per_le_viste_con_le_fatture(lavori):
    altra = m.WBS.objects.create(codice_wbs="P.0002.01.0001", descrizione="Altro progetto")
    for fattura in _fatture(lavori["contratto"], lavori["voce"]):
        fattura.wbs = altra
        fattura.save()
    assert spese_wbs(altra, "cassa", Livello.FISSO).righe
    assert spese_wbs(altra, "impegno", Livello.FISSO).righe == []


# --- Contratti con più voci ------------------------------------------------------------------


def test_contratto_con_piu_voci_le_fatture_vanno_alla_voce_indicata(lavori):
    canone = f.voce(
        lavori["contratto"], descrizione="Manutenzione", natura="CAPEX", wbs=lavori["wbs"],
        importo_fisso=Decimal("1000.00"),
    )  # fmt: skip
    f.piano(canone, modalita="posticipata", periodicita="annuale")
    _fatture(lavori["contratto"], lavori["voce"], FATTURE[:2])
    _fatture(lavori["contratto"], canone, [(D(2025, 5, 5), "999.00")])
    s = _fatturato(lavori["wbs"])
    sal = _riga(s, lavori["voce"])
    assert sal.per_anno == {2025: Decimal("762072.16")}  # 467.235,71 + 294.836,45
    # La voce non a SAL resta sulle rate del piano, come prima.
    rate = _riga(s, canone)
    assert not rate.a_sal and sum(rate.per_anno.values()) == Decimal("1000.00")


def test_fattura_senza_voce_in_contratto_con_piu_voci_va_alla_principale_con_avviso(lavori):
    canone = f.voce(
        lavori["contratto"], descrizione="Manutenzione", natura="CAPEX", wbs=lavori["wbs"],
        importo_fisso=Decimal("1000.00"),
    )  # fmt: skip
    f.piano(canone, modalita="posticipata", periodicita="annuale")
    _fatture(lavori["contratto"], None, FATTURE[:1])
    riga = _riga(_fatturato(lavori["wbs"]), lavori["voce"])  # principale: la prima voce
    assert riga.per_anno == {2025: Decimal("467235.71")}
    assert any("voce principale" in a for a in riga.avvisi)


# --- Altre viste e altre modalità -------------------------------------------------------------


def test_le_viste_impegno_e_competenza_non_cambiano(lavori):
    _quote(lavori["voce"])
    _fatture(lavori["contratto"], lavori["voce"])
    impegno = _riga(spese_wbs(lavori["wbs"], "impegno", Livello.FISSO), lavori["voce"])
    assert impegno.per_anno == {2024: FISSO}
    assert not impegno.a_sal
    competenza = _riga(spese_wbs(lavori["wbs"], "competenza", Livello.FISSO), lavori["voce"])
    assert sum(competenza.per_anno.values()) == FISSO
    assert competenza.per_anno[2024] == Decimal("254217.84")  # mesi frazionati: è la competenza


def test_posticipata_annuale_e_una_tantum_restano_sulle_rate(lavori):
    c = f.contratto(fabbisogno=f.fabbisogno("Altro"), data_inizio=D(2026, 1, 1), durata_mesi=24)
    annuale = f.voce(c, descrizione="Canone", natura="CAPEX", wbs=lavori["wbs"],
                     importo_fisso=Decimal("2400.00"))  # fmt: skip
    f.piano(annuale, modalita="posticipata", periodicita="annuale")
    una = f.voce(c, descrizione="Una tantum", natura="CAPEX", wbs=lavori["wbs"],
                 importo_fisso=Decimal("500.00"))  # fmt: skip
    f.piano(una, modalita="una_tantum", periodicita="")
    s = _fatturato(lavori["wbs"])
    assert _riga(s, annuale).per_anno == {2026: Decimal("1200.00"), 2027: Decimal("1200.00")}
    assert _riga(s, una).per_anno == {2026: Decimal("500.00")}
    assert not _riga(s, annuale).a_sal and not _riga(s, una).a_sal


# --- Vista «Fatturato e stanziato» e pagine ----------------------------------------------------


def test_consuntivo_non_somma_pro_rata_e_fatture(lavori):
    _fatture(lavori["contratto"], lavori["voce"])
    riga = _riga(spese_wbs(lavori["wbs"], "consuntivo", Livello.FISSO), lavori["voce"])
    assert sum(riga.per_anno.values()) == Decimal("2630931.49")
    assert 2024 not in riga.per_anno and 2027 not in riga.per_anno


def _client(make_user):
    make_user("u_lettore", role=READER)
    c = Client()
    c.login(username="u_lettore", password=PASSWORD)
    return c


def test_pagina_ed_export_mostrano_consuntivo_e_previsto_separati(lavori, make_user):
    _quote(lavori["voce"])
    _fatture(lavori["contratto"], lavori["voce"])
    client = _client(make_user)
    url = reverse("reports:wbs_spese", args=[lavori["wbs"].pk]) + "?vista=cassa&livello=fisso"
    html = client.get(url).content.decode()
    assert "Fonte degli importi" in html and "SAL: fatture registrate, quote per periodo" in html
    assert "di cui fatture registrate" in html and "di cui previsto" in html
    assert "1.486.870,87" in html and "316.708,26" in html
    assert "256.031,07" not in html and "1.198.094,11" not in html

    risposta = client.get(url + "&formato=xlsx")
    ws = openpyxl.load_workbook(io.BytesIO(risposta.content))["Spese per anno"]
    valori = [c for riga in ws.iter_rows(values_only=True) for c in riga]
    assert "  di cui fatture registrate" in valori
    assert "  di cui previsto (rate a mano o quote)" in valori
    assert 316708.26 in valori


def test_pagina_mostra_l_anomalia_della_wbs_della_fattura(lavori, make_user):
    altra = m.WBS.objects.create(codice_wbs="P.0002.01.0001", descrizione="Altro progetto")
    (fattura,) = _fatture(lavori["contratto"], lavori["voce"], FATTURE[:1])
    fattura.wbs = altra
    fattura.save()
    html = (
        _client(make_user)
        .get(reverse("reports:wbs_spese", args=[lavori["wbs"].pk]) + "?vista=cassa")
        .content.decode()
    )
    assert "diversa da quella della voce" in html
