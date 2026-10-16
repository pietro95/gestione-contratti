"""Rev22: stanziamenti dal connettore: lettura (proposti e registrati) e scrittura in due passi."""

import datetime
from decimal import Decimal

import pytest

from accounts.roles import EDITOR
from contratti import models as m
from contratti.servizi import genera_scadenzario
from tests import factories as f
from tests.connettore.test_scrittura_acquisti import conferma, errore, ok

pytestmark = pytest.mark.django_db
D = datetime.date


@pytest.fixture
def mensile():
    c = f.contratto(data_inizio=D(2026, 1, 1), durata_mesi=12, numero_contratto="5800000050")
    v = f.voce(c, importo_fisso=Decimal("12000.00"))
    f.piano(v, modalita="posticipata", periodicita="mensile")
    genera_scadenzario(v)
    return {"contratto": c, "voce": v, "rate": list(m.Rata.objects.filter(piano__voce=v))}


def test_lettura_di_proposti_e_registrati(editor, mensile):
    dati = ok(editor, "stanziamenti", {"contratto_id": mensile["contratto"].pk})
    proposti = [r for r in dati["righe"] if r["tipo"] == "proposto"]
    assert len(proposti) >= 3 and dati["giorni_di_tolleranza"] == 15
    assert proposti[0]["importo"] == "1000.00" and proposti[0]["competenza_dal"] == "2026-01-01"
    assert dati["totale_proposto"] == str(Decimal("1000.00") * len(proposti))
    assert dati["totale_stanziato"] == "0.00"
    # Dopo la conferma la rata passa da «proposto» a «registrato».
    conferma(editor, ok(editor, "stanzia_rate", {"rate_ids": [proposti[0]["rata_id"]]}))
    dati = ok(editor, "stanziamenti", {"contratto_id": mensile["contratto"].pk})
    assert [r["tipo"] for r in dati["righe"]].count("registrato") == 1
    assert dati["totale_stanziato"] == "1000.00"


def test_stanzia_rate_anteprima_e_conferma(editor, mensile):
    rata = mensile["rate"][0]
    anteprima = ok(editor, "stanzia_rate", {"rate_ids": [rata.pk]})
    assert not m.Stanziamento.objects.exists()  # l'anteprima non scrive
    assert anteprima["modifiche"][0]["tipo"] == "creato"
    conferma(editor, anteprima)
    s = m.Stanziamento.objects.get()
    assert (s.rata, s.importo, s.competenza_dal, s.competenza_al) == (
        rata, Decimal("1000.00"), D(2026, 1, 1), D(2026, 1, 31),
    )  # fmt: skip
    # Una rata già stanziata non si stanzia di nuovo.
    assert "non è da stanziare" in errore(editor, "stanzia_rate", {"rate_ids": [rata.pk]})
    assert "inesistenti" in errore(editor, "stanzia_rate", {"rate_ids": [999999]})


def test_registra_chiudi_e_annulla(editor, mensile):
    c, v = mensile["contratto"], mensile["voce"]
    argomenti = {
        "contratto_id": c.pk, "voce_id": v.pk, "importo": "750.00",
        "competenza_dal": "2026-05-01", "competenza_al": "2026-05-31",
    }  # fmt: skip
    anteprima = ok(editor, "registra_stanziamento", argomenti)
    assert not m.Stanziamento.objects.exists()
    conferma(editor, anteprima)
    s = m.Stanziamento.objects.get()
    assert (s.importo, s.rata) == (Decimal("750.00"), None)

    fa = m.Fattura.objects.create(
        fornitore=c.fornitore, contratto=c, numero="F9", data=D(2026, 6, 3),
        importo_documento=Decimal("760.00"),
    )  # fmt: skip
    conferma(editor, ok(editor, "chiudi_stanziamento", {"id": s.pk, "fattura_id": fa.pk}))
    s.refresh_from_db()
    assert s.fattura_id == fa.pk and s.chiuso

    conferma(editor, ok(editor, "annulla_stanziamento", {"id": s.pk}))
    s.refresh_from_db()
    assert s.archiviato


def test_dati_non_validi_e_contratto_chiuso(editor, mensile):
    c, v = mensile["contratto"], mensile["voce"]
    base = {
        "contratto_id": c.pk, "voce_id": v.pk, "importo": "10.00",
        "competenza_dal": "2026-05-31", "competenza_al": "2026-05-01",
    }  # fmt: skip
    assert "Dati non validi" in errore(editor, "registra_stanziamento", base)
    c.data_chiusura = D(2026, 6, 1)
    c.save()
    base["competenza_dal"], base["competenza_al"] = "2026-05-01", "2026-05-31"
    assert "chiuso" in errore(editor, "registra_stanziamento", base)
    # La fattura di un altro contratto non chiude lo stanziamento.
    altro = f.contratto(numero_contratto="5800000051")
    fa = m.Fattura.objects.create(
        fornitore=altro.fornitore, contratto=altro, numero="X", data=D(2026, 6, 3),
        importo_documento=Decimal("1.00"),
    )  # fmt: skip
    s = m.Stanziamento.objects.create(
        voce=v, importo=Decimal("5.00"), competenza_dal=D(2026, 5, 1), competenza_al=D(2026, 5, 31)
    )
    assert "Dati non validi" in errore(
        editor, "chiudi_stanziamento", {"id": s.pk, "fattura_id": fa.pk}
    )


def test_permessi_per_cluster(make_user, mensile):
    m.AssegnazioneCluster.objects.create(username="altro", cluster=f.cluster("TLC"))
    altro = make_user("altro", role=EDITOR)
    c, v = mensile["contratto"], mensile["voce"]
    msg = errore(
        altro, "registra_stanziamento",
        {"contratto_id": c.pk, "voce_id": v.pk, "importo": "1.00",
         "competenza_dal": "2026-05-01", "competenza_al": "2026-05-31"},
    )  # fmt: skip
    assert "Non autorizzato" in msg
    assert "Non autorizzato" in errore(altro, "stanzia_rate", {"rate_ids": [mensile["rate"][0].pk]})
    s = m.Stanziamento.objects.create(
        voce=v, importo=Decimal("5.00"), competenza_dal=D(2026, 5, 1), competenza_al=D(2026, 5, 31)
    )
    assert "Non autorizzato" in errore(altro, "annulla_stanziamento", {"id": s.pk})
    s.refresh_from_db()
    assert not s.archiviato
