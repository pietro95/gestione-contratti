"""Extra budget (Rev18): attività spot autorizzate dall'AD, fuori dai budget dei cluster.

Dati fittizi. Contratto ordinario: canone OPEX 1.200,00. Contratto una tantum extra budget:
voce OPEX 3.000,00 e voce CAPEX 2.000,00 + massimale 500,00 su WBS di cluster, autorizzazione
AD per 5.000,00 → consumato (massimo) 5.500,00, sforamento di 500,00: avviso, non blocco.
"""

import datetime
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from contratti import forms
from contratti import models as m
from contratti.engine.tipi import Livello
from reports.budget import Filtri, calcola_budget
from reports.extra_budget import consumato, elenco_autorizzazioni, spese_extra_budget
from reports.piano_ordini import calcola_piano

from .. import factories as f

pytestmark = pytest.mark.django_db
D = datetime.date
OGGI = D(2026, 6, 1)
FISSO = Livello.FISSO


@pytest.fixture
def archivio():
    ordinario = f.contratto(fabbisogno=f.fabbisogno("Canone ordinario", decisione="rinnovare"))
    f.piano(f.voce(ordinario, importo_fisso=Decimal("1200.00")))
    aut = m.AutorizzazioneExtraBudget.objects.create(
        codice="EB-2026-01",
        descrizione="Intervento straordinario di prova",
        cluster=f.cluster("IT"),
        protocollo="PROT-0001",
        data_autorizzazione=D(2026, 3, 15),
        importo_autorizzato=Decimal("5000.00"),
    )
    spot = f.contratto(
        fabbisogno=f.fabbisogno("Attività spot", decisione="rinnovare"),
        una_tantum=True,
        durata_mesi=1,
        data_inizio=D(2026, 4, 1),
    )
    opex = f.voce(spot, importo_fisso=Decimal("3000.00"), autorizzazione_extra_budget=aut)
    f.piano(opex, modalita=m.ModalitaFatturazione.UNA_TANTUM, periodicita="")
    wbs = m.WBS.objects.create(
        codice_wbs="WBS-IT-09", descrizione="WBS di prova", tipo="cluster", cluster=f.cluster()
    )
    capex = f.voce(
        spot,
        descrizione="Apparati",
        importo_fisso=Decimal("2000.00"),
        massimale_variabile=Decimal("500.00"),
        natura=m.Natura.CAPEX,
        wbs=wbs,
        autorizzazione_extra_budget=aut,
    )
    f.piano(capex, modalita=m.ModalitaFatturazione.UNA_TANTUM, periodicita="")
    return {"aut": aut, "spot": spot, "ordinario": ordinario, "opex": opex}


def _cassa(filtri):
    return calcola_budget(filtri, OGGI).totali()["totale"]["cassa"][FISSO]


def test_le_voci_extra_budget_restano_fuori_dai_budget_opex_e_capex(archivio):
    assert _cassa(Filtri(anno=2026, natura="OPEX")) == Decimal("1200.00")
    assert _cassa(Filtri(anno=2026, natura="CAPEX")) == Decimal("0.00")
    assert _cassa(Filtri(anno=2026, natura="OPEX", extra_budget="includi")) == Decimal("4200.00")
    assert _cassa(Filtri(anno=2026, natura="OPEX", extra_budget="solo")) == Decimal("3000.00")
    assert _cassa(Filtri(anno=2026, natura="CAPEX", extra_budget="solo")) == Decimal("2000.00")


def test_il_contratto_si_dice_extra_budget(archivio):
    c = m.Contratto.objects.get(pk=archivio["spot"].pk)
    assert c.finanziamento == m.Contratto.Finanziamento.EXTRA_BUDGET
    assert archivio["ordinario"].finanziamento == m.Contratto.Finanziamento.ORDINARIO


def test_consumato_sul_massimo_e_avviso_oltre_l_autorizzato(archivio):
    aut = archivio["aut"]
    assert consumato(aut) == Decimal("5500.00")
    s = spese_extra_budget(aut, "cassa", FISSO)
    assert s.residuo == Decimal("-500.00")
    assert "500,00 €" in s.avviso
    assert s.totale == Decimal("5000.00")
    (riga,) = elenco_autorizzazioni(["IT"])
    assert riga.n_voci == 2
    assert riga.consumato == Decimal("5500.00")


def test_entro_l_autorizzato_nessun_avviso(archivio):
    aut = archivio["aut"]
    aut.importo_autorizzato = Decimal("5500.00")
    aut.save()
    assert spese_extra_budget(aut).avviso == ""


def test_fuori_dal_piano_ordini(archivio):
    piano = calcola_piano(2026, OGGI)
    contratti = {r.contratto for r in piano.righe} | {r.contratto_uscente for r in piano.righe}
    assert archivio["spot"] not in contratti
    assert archivio["ordinario"] in contratti


def test_solo_contratti_una_tantum(archivio):
    ordinario = archivio["ordinario"]
    voce = ordinario.voci.get()
    voce.autorizzazione_extra_budget = archivio["aut"]
    with pytest.raises(ValidationError, match="una tantum"):
        voce.full_clean()
    spot = archivio["spot"]
    spot.una_tantum = False
    with pytest.raises(ValidationError, match="una tantum"):
        spot.clean()


def test_autorizzazione_dello_stesso_cluster(archivio):
    aut = archivio["aut"]
    aut.cluster = f.cluster("TLC")
    aut.save()
    with pytest.raises(ValidationError, match="cluster TLC"):
        archivio["opex"].full_clean()


def test_il_form_della_voce_rifiuta_i_contratti_non_una_tantum(archivio):
    ordinario = archivio["ordinario"]
    voce = ordinario.voci.get()
    form = forms.VoceForm(
        {
            "descrizione": voce.descrizione,
            "natura": "OPEX",
            "importo_fisso": "1200,00",
            "massimale_variabile": "0,00",
            "autorizzazione_extra_budget": archivio["aut"].pk,
        },
        instance=voce,
        contratto=ordinario,
    )
    assert not form.is_valid()
    assert "autorizzazione_extra_budget" in form.errors


def _login(client, make_user, ruolo):
    from accounts import roles

    make_user("utente", role=getattr(roles, ruolo))
    client.login(username="utente", password="password-locale-di-prova")


def test_viste_extra_budget(archivio, client, make_user):
    _login(client, make_user, "READER")
    elenco = client.get(reverse("reports:extra_budget")).content.decode()
    assert "EB-2026-01" in elenco
    pagina = client.get(reverse("reports:extra_budget_spese", args=[archivio["aut"].pk]))
    assert "oltre l&#x27;importo autorizzato" in pagina.content.decode()
    dettaglio = client.get(reverse("contratti:contratto", args=[archivio["spot"].pk]))
    assert "PROT-0001" in dettaglio.content.decode()
    filtrati = client.get(reverse("contratti:contratti") + "?finanziamento=extra_budget")
    assert "Attività spot" in filtrati.content.decode()
    assert "Canone ordinario" not in filtrati.content.decode()


def test_il_reader_non_marca_le_voci(archivio, client, make_user):
    _login(client, make_user, "READER")
    url = reverse("contratti:voce_modifica", args=[archivio["spot"].pk, archivio["opex"].pk])
    assert client.post(url, {"autorizzazione_extra_budget": ""}).status_code == 403
    archivio["opex"].refresh_from_db()
    assert archivio["opex"].autorizzazione_extra_budget_id == archivio["aut"].pk
