"""Vista «Da gestire (dopo la convalida)» per l'addetto amministrativo (SPEC §5.7, Rev39)."""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from accounts.roles import EDITOR, READER
from contratti import models as m
from contratti.engine.acquisti import PassoFattura

from . import factories as f

pytestmark = pytest.mark.django_db
D = datetime.date
Tipo = m.DocumentoEsecuzione.Tipo


@pytest.fixture
def archivio(make_user):
    amm = make_user("amm", role=EDITOR)
    m.FunzioneUtente.objects.create(
        username="amm", funzione=m.FunzioneUtente.Funzione.AMMINISTRAZIONE_ACQUISTI
    )
    ref = make_user("ref", role=EDITOR)
    lettore = make_user("lettore", role=READER)
    contratto = f.contratto(fornitore=f.fornitore("Fornitore Prova S.r.l."))
    f.voce(contratto)

    def fattura(numero, **kw):
        base = {
            "fornitore": contratto.fornitore,
            "contratto": contratto,
            "numero": numero,
            "data": D(2026, 10, 20),
            "importo_documento": Decimal("100.00"),
            "referente": ref,
            "data_presa_in_carico": D(2026, 10, 21),
            "esito_convalida": "convalidabile",
            "data_convalida": D(2026, 10, 22),
        }
        return m.Fattura.objects.create(**{**base, **kw})

    def documento(fa, tipo, numero, rilasciato=True):
        m.DocumentoEsecuzione.objects.create(
            contratto=contratto, fattura=fa, tipo=tipo, numero=numero, data=D(2026, 10, 23),
            data_rilascio=D(2026, 10, 24) if rilasciato else None,
        )  # fmt: skip

    da_prendere = fattura("DA-PRENDERE", referente=None, data_presa_in_carico=None,
                          esito_convalida="da_valutare", data_convalida=None)  # fmt: skip
    da_convalidare = fattura("DA-CONVALIDARE", esito_convalida="da_valutare", data_convalida=None)
    rdc = fattura("RDC-DA-FARE")
    rilascio = fattura("RDC-DA-RILASCIARE")
    documento(rilascio, Tipo.ODA, "4600000001", rilasciato=False)
    da_trasferire = fattura("DA-TRASFERIRE")
    documento(da_trasferire, Tipo.ODA, "4600000002")
    documento(da_trasferire, Tipo.MIGO, "5000000002")
    trasferita = fattura("TRASFERITA", data_trasferimento=D(2026, 11, 2))
    fuori = fattura("FUORI-REGISTRO", fuori_registro=True)
    return {
        "amm": amm, "ref": ref, "lettore": lettore,
        "attese": {"RDC-DA-FARE", "RDC-DA-RILASCIARE", "DA-TRASFERIRE"},
        "escluse": {da_prendere.numero, da_convalidare.numero, trasferita.numero, fuori.numero},
        "rdc": rdc,
    }  # fmt: skip


def numeri(risposta):
    return {r["f"].numero for r in risposta.context["pagina"]}


def test_la_vista_mostra_solo_le_fatture_convalidate_da_gestire(client, archivio):
    client.force_login(archivio["amm"])
    risposta = client.get(reverse("contratti:fatture"), {"vista": "addetto"})
    assert risposta.status_code == 200
    assert numeri(risposta) == archivio["attese"]
    passi = {r["f"].numero: r["passo"] for r in risposta.context["pagina"]}
    assert passi["RDC-DA-FARE"] == PassoFattura.RDC
    assert passi["RDC-DA-RILASCIARE"] == PassoFattura.RDC_RILASCIO
    assert passi["DA-TRASFERIRE"] == PassoFattura.TRASFERIMENTO
    assert not numeri(risposta) & archivio["escluse"]


def test_l_addetto_apre_la_vista_di_default_gli_altri_no(client, archivio):
    client.force_login(archivio["amm"])
    risposta = client.get(reverse("contratti:fatture"))
    assert risposta.context["vista"] == "addetto"
    assert "Da gestire (dopo la convalida)" in risposta.content.decode()
    client.force_login(archivio["ref"])
    risposta = client.get(reverse("contratti:fatture"))
    assert risposta.context["vista"] != "addetto"
    # Il referente non ha la scheda nel menu delle viste, ma può aprirla (lettura per tutti).
    assert "Da gestire (dopo la convalida)" not in risposta.content.decode()
    assert client.get(reverse("contratti:fatture"), {"vista": "addetto"}).status_code == 200


def test_filtro_per_passo_nella_vista_dell_addetto(client, archivio):
    client.force_login(archivio["amm"])
    risposta = client.get(
        reverse("contratti:fatture"), {"vista": "addetto", "passo": PassoFattura.RDC_RILASCIO.value}
    )
    assert numeri(risposta) == {"RDC-DA-RILASCIARE"}
    # Le opzioni del filtro sono solo i passi dopo la convalida.
    assert [v for v, _ in risposta.context["passi_vista"]] == [
        "rdc", "rdc_rilascio", "map_migo", "map_migo_rilascio", "trasferimento",
    ]  # fmt: skip


def test_il_reader_legge_la_vista(client, archivio):
    client.force_login(archivio["lettore"])
    assert client.get(reverse("contratti:fatture"), {"vista": "addetto"}).status_code == 200
