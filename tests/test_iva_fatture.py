"""IVA compresa nell'importo delle fatture (SAP riporta spesso l'importo con l'IVA):
riconoscimento automatico, scorporo, nessun falso IMPORTO_NON_QUADRA. Dati di fantasia."""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from accounts.roles import EDITOR, READER
from connettore import protocollo
from connettore.strumenti import Contesto
from contratti import fatture
from contratti import models as m
from contratti.engine import acquisti as motore
from tests.connettore.conftest import chiama

from . import factories as f

D = Decimal
COMPETENZA = (datetime.date(2026, 1, 1), datetime.date(2026, 12, 31))
ALIQUOTE = [D("22"), D("10"), D("5"), D("4")]


# --- Motore -------------------------------------------------------------------------------


def test_quadra_con_l_iva():
    assert not motore.importo_quadra(D("1220.00"), D("1000.00"), None, None)
    assert motore.importo_quadra(D("1220.00"), D("1000.00"), None, None, D("220.00"))


@pytest.mark.parametrize(
    ("importo", "base", "oneri", "bollo", "atteso"),
    [
        ("1220.00", "1000.00", None, None, ("22", "220.00")),
        ("1104.00", "1000.00", None, "2.00", None),  # 10% sarebbe 1.102,00
        ("1102.00", "1000.00", None, "2.00", ("10", "100.00")),
        ("1270.80", "1000.00", "40.00", "2.00", ("22", "228.80")),  # IVA anche sugli oneri
        ("1220.01", "1000.00", None, None, ("22", "220.01")),  # un centesimo di arrotondamento
        ("1220.02", "1000.00", None, None, None),
        ("1000.00", "1000.00", None, None, None),  # niente IVA
    ],
)
def test_iva_riconosciuta(importo, base, oneri, bollo, atteso):
    risultato = motore.iva_riconosciuta(
        D(importo), D(base), oneri and D(oneri), bollo and D(bollo), ALIQUOTE
    )
    assert risultato == (atteso and (D(atteso[0]), D(atteso[1])))


@pytest.mark.parametrize(
    ("importo", "oneri", "bollo", "aliquota", "base", "iva"),
    [
        ("1220.00", None, None, "22", "1000.00", "220.00"),
        ("1270.80", "40.00", "2.00", "22", "1000.00", "228.80"),
        ("100.00", None, None, "22", "81.97", "18.03"),  # arrotondamento: quadra comunque
    ],
)
def test_scorporo(importo, oneri, bollo, aliquota, base, iva):
    o, b = oneri and D(oneri), bollo and D(bollo)
    valore_base, valore_iva = motore.scorporo_iva(D(importo), o, b, D(aliquota))
    assert (valore_base, valore_iva) == (D(base), D(iva))
    assert motore.importo_quadra(D(importo), valore_base, o, b, valore_iva)


# --- Servizi, pagina e connettore --------------------------------------------------------


@pytest.fixture
def fattura(db):
    c = f.contratto()
    return m.Fattura.objects.create(
        fornitore=c.fornitore, contratto=c, numero="FA-1", data=datetime.date(2026, 10, 1),
        importo_documento=D("1220.00"),
    )  # fmt: skip


def _ricarica(x):
    return fatture.QS_FATTURE.get(pk=x.pk)


def test_aliquote_iniziali(db):
    assert sorted(fatture.aliquote_iva()) == sorted(ALIQUOTE)


def test_iva_riconosciuta_al_salvataggio(fattura):
    fatture.aggiorna_importi(fattura, D("1000.00"), None, None, competenza=COMPETENZA)
    x = _ricarica(fattura)
    assert x.iva == D("220.00") and fatture.anomalie(x) == []
    # Senza IVA riconoscibile l'avviso resta; un'IVA indicata a mano vale.
    fatture.aggiorna_importi(x, D("900.00"), None, None, competenza=COMPETENZA)
    assert "IMPORTO_NON_QUADRA" in fatture.anomalie(_ricarica(fattura))
    fatture.aggiorna_importi(
        _ricarica(fattura), D("900.00"), None, None, iva=D("320.00"), competenza=COMPETENZA
    )
    assert fatture.anomalie(_ricarica(fattura)) == []


def test_fatturato_sul_valore_base(fattura):
    from contratti import acquisti

    fatture.scorpora_iva(fattura, D("22"), None, None, competenza=COMPETENZA)
    esecuzione = acquisti.riepilogo_esecuzione(fattura.contratto).esecuzione
    assert esecuzione.fatturato == D("1000.00")  # l'IVA non è fatturato del contratto


def test_scorporo_solo_con_aliquote_della_tabella(fattura):
    with pytest.raises(fatture.OperazioneNonAmmessa, match="non prevista"):
        fatture.scorpora_iva(fattura, D("21"), None, None)
    m.AliquotaIVA.objects.filter(aliquota=D("22")).update(attiva=False)
    with pytest.raises(fatture.OperazioneNonAmmessa):
        fatture.scorpora_iva(fattura, D("22"), None, None)


def test_pulsante_scorpora_e_reader(client, make_user, fattura):
    url = reverse("contratti:fattura_importi", args=[fattura.pk])
    client.force_login(make_user("lettore", role=READER))
    assert client.post(url, {"scorporo": "22"}).status_code == 403
    client.force_login(make_user("redattore", role=EDITOR))
    pagina = client.get(reverse("contratti:fattura", args=[fattura.pk])).content.decode()
    assert "Scorpora IVA 22%" in pagina and "Scorpora IVA 4%" in pagina
    client.post(url, {"scorporo": "22", "valore_base": "", "oneri": "", "bollo": "",
                      "iva": "", "competenza_dal": "01/01/2026",
                      "competenza_al": "31/12/2026"})  # fmt: skip
    x = _ricarica(fattura)
    assert (x.valore_base, x.iva) == (D("1000.00"), D("220.00"))


def test_dal_connettore(make_user, fattura):
    editor = make_user("redattore", role=EDITOR)
    ctx = Contesto(editor, datetime.date(2026, 10, 12), scrittura=True, client_id="prova")
    risposta, _ = protocollo.gestisci(
        chiama(
            "importi_fattura",
            {
                "id": fattura.pk,
                "scorpora_iva": "22",
                "competenza_dal": "2026-01-01",
                "competenza_al": "2026-12-31",
            },
        ),
        ctx,
    )
    anteprima = risposta["result"]["structuredContent"]
    dopo = anteprima["effetti"]["processo_acquisto"]["dopo"]["fatture"][0]
    assert dopo["anomalie"] == []
    risposta, _ = protocollo.gestisci(
        chiama("conferma_operazione", {"id_operazione": anteprima["id_operazione"]}), ctx
    )
    assert not risposta["result"].get("isError")
    risposta, _ = protocollo.gestisci(chiama("fattura", {"id": fattura.pk}), ctx)
    assert risposta["result"]["structuredContent"]["iva"] == "220.00"
