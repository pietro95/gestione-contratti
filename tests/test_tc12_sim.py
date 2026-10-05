"""TC-12 (F9.3): un contratto che rinnova più contratti (SIM voce e SIM M2M)."""

import datetime
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from contratti import adapters, selettori, servizi
from contratti import models as m
from contratti.engine import budget as motore
from contratti.engine import scadenze
from contratti.engine.tipi import Alert, Livello

from . import factories as f

pytestmark = pytest.mark.django_db
D = datetime.date
OGGI = D(2026, 11, 15)


def _contratto(fabbisogno, numero, inizio, mesi, importo):
    c = f.contratto(
        fabbisogno=fabbisogno, numero_contratto=numero, data_inizio=inizio, durata_mesi=mesi
    )
    f.piano(f.voce(c, importo_fisso=Decimal(importo)))  # anticipata annuale
    return c


@pytest.fixture
def sim():
    # Parametri del caso (come TC-06 e TC-07): lead time dell'affidamento diretto 4 mesi,
    # adeguamento 3%.
    m.Procedura.objects.filter(codice="affidamento_diretto").update(lead_time_mesi=4)
    m.Parametro.objects.create(
        chiave="adeguamento_pct", valore=Decimal("3"), valido_dal=D(2025, 1, 1)
    )
    a = f.fabbisogno("SIM voce", decisione="rinnovare")
    b = f.fabbisogno("SIM M2M", decisione="rinnovare")
    v = _contratto(a, "V", D(2025, 1, 1), 24, "4800.00")
    mm = _contratto(b, "M", D(2025, 11, 1), 12, "1200.00")
    return {"a": a, "b": b, "v": v, "m": mm}


def _limite(c):
    return scadenze.data_riferimento_alert(adapters.scadenza(c))


def _previsti(fab, orizzonte):
    return [
        (p.inizio, p.fine, sum((v.importo_fisso for v in p.voci), Decimal("0.00")))
        for p in adapters.previsti_fabbisogno(fab, orizzonte)
    ]


def _rinnova(sim):
    """Operazioni del TC: accorpa B in A, poi rinnovo di V che sostituisce anche M."""
    servizi.accorpa_fabbisogni(sim["b"], sim["a"])
    sim["m"].refresh_from_db()
    origine = sim["v"].voci.get()
    n = servizi.registra_rinnovo(
        sim["v"],
        {
            "fornitore": sim["v"].fornitore,
            "procedura": sim["v"].procedura,
            "descrizione": "SIM voce e M2M",
            "numero_contratto": "N",
            "data_inizio": D(2027, 1, 1),
            "durata_mesi": 24,
        },
        [
            {
                "origine": origine.pk,
                "descrizione": "Canone",
                "importo_fisso": Decimal("9600.00"),
                "massimale_variabile": Decimal("0.00"),
            }
        ],  # fmt: skip
        sostituisce=[sim["m"]],
    )
    servizi.genera_scadenzario(n.voci.get())
    for c in (sim["v"], sim["m"]):
        c.refresh_from_db()
    return n


def test_prima(sim):
    v, mm = sim["v"], sim["m"]
    assert (_limite(v), _limite(mm)) == (D(2026, 8, 31), D(2026, 6, 30))
    assert adapters.alert_contratto(v, OGGI) == Alert.ARANCIONE
    assert adapters.alert_contratto(mm, OGGI) == Alert.ROSSO
    assert _previsti(sim["a"], D(2027, 12, 31)) == [
        (D(2027, 1, 1), D(2028, 12, 31), Decimal("4944.00"))
    ]
    assert _previsti(sim["b"], D(2027, 12, 31)) == [
        (D(2026, 11, 1), D(2027, 10, 31), Decimal("1236.00")),
        (D(2027, 11, 1), D(2028, 10, 31), Decimal("1273.08")),
    ]


def test_dopo(sim):
    n = _rinnova(sim)
    v, mm, a = sim["v"], sim["m"], sim["a"]
    # Predecessori di N: V (rinnovo) e M (confluito); successore di entrambi: N.
    assert n.predecessore == v and list(n.confluiti.all()) == [mm]
    assert mm.confluito_in == n and mm.fabbisogno == a
    assert adapters.ha_successore(v) and adapters.ha_successore(mm)
    assert adapters.alert_contratto(v, OGGI) is None
    assert adapters.alert_contratto(mm, OGGI) is None
    assert adapters.alert_contratto(n, OGGI) == Alert.VERDE
    assert _limite(n) == D(2028, 8, 31)
    rossi = selettori.cruscotto(OGGI, {})[Alert.ROSSO]
    assert mm not in [r.contratto for r in rossi]
    # Previsti: solo da N.
    assert adapters.contratto_base_previsti(a) == n
    assert _previsti(a, D(2029, 12, 31)) == [(D(2029, 1, 1), D(2030, 12, 31), Decimal("9888.00"))]
    (p1,) = adapters.previsti_fabbisogno(a, D(2029, 12, 31))
    assert p1.voci[0].piano.data_prima_fattura in (None, D(2029, 1, 1))
    # Scadenzario e impegno di N.
    rate = list(n.voci.get().piano_fatturazione.rate.order_by("numero"))
    assert [(r.data_fattura, r.importo) for r in rate] == [
        (D(2027, 1, 1), Decimal("4800.00")),
        (D(2028, 1, 1), Decimal("4800.00")),
    ]
    viste, _ = motore.calcola(adapters.voci_contratto(n)[0])
    assert viste["impegno"].per_anno == {2027: {liv: Decimal("9600.00") for liv in Livello}}


def test_cassa_per_anno_del_fabbisogno(sim):
    n = _rinnova(sim)
    attesa = {
        "V": {2025: Decimal("2400.00"), 2026: Decimal("2400.00")},
        "M": {2025: Decimal("1200.00")},
        "N": {2027: Decimal("4800.00"), 2028: Decimal("4800.00")},
    }
    for c in (sim["v"], sim["m"], n):
        viste, _ = motore.calcola(adapters.voci_contratto(c)[0])
        cassa = {a: liv[Livello.FISSO] for a, liv in viste["cassa"].per_anno.items()}
        assert cassa == attesa[c.numero_contratto], c.numero_contratto


def test_un_solo_successore_e_stesso_fabbisogno(sim):
    n = _rinnova(sim)
    v, mm = sim["v"], sim["m"]
    altro = _contratto(sim["a"], "X", D(2027, 6, 1), 12, "100.00")
    # M è già confluito in N: non confluisce in un secondo, né può avere un rinnovo.
    with pytest.raises(servizi.OperazioneNonAmmessa):
        servizi.confluisci(mm, altro)
    with pytest.raises(servizi.OperazioneNonAmmessa):
        servizi.registra_rinnovo(mm, {}, [])
    mm.predecessore = None
    altro.predecessore = mm
    with pytest.raises(ValidationError, match="già confluito"):
        altro.clean()
    # V ha già N come successore: non può confluire altrove.
    v.confluito_in = altro
    with pytest.raises(ValidationError, match="già un successore"):
        v.clean()
    # Solo nello stesso fabbisogno, e verso un contratto che inizia dopo.
    fuori = _contratto(f.fabbisogno("Altro"), "Y", D(2024, 1, 1), 12, "100.00")
    with pytest.raises(servizi.OperazioneNonAmmessa):
        servizi.confluisci(fuori, n)
    prima = _contratto(sim["a"], "Z", D(2028, 1, 1), 12, "100.00")
    with pytest.raises(servizi.OperazioneNonAmmessa):
        servizi.confluisci(prima, n)


def test_togliere_il_collegamento_riporta_il_rosso(sim):
    n = _rinnova(sim)
    mm = sim["m"]
    assert servizi.togli_confluenza(mm) == n
    mm.refresh_from_db()
    assert mm.confluito_in is None
    assert adapters.alert_contratto(mm, OGGI) == Alert.ROSSO
    assert mm.history.first().history_change_reason == f"Non più confluito nel contratto #{n.pk}"
    # E si ricollega dalla scheda del contratto nuovo.
    assert servizi.candidati_confluenza(n) == [mm]
    servizi.confluisci(mm, n)
    mm.refresh_from_db()
    assert mm.confluito_in == n


def test_sostituisce_solo_contratti_del_fabbisogno_senza_successore(sim):
    fuori = _contratto(f.fabbisogno("Altro"), "Y", D(2025, 6, 1), 12, "100.00")
    assert servizi.candidati_sostituiti(sim["v"]) == []  # M è ancora in B
    with pytest.raises(servizi.OperazioneNonAmmessa):
        servizi.registra_rinnovo(sim["v"], {}, [], sostituisce=[fuori])
    servizi.accorpa_fabbisogni(sim["b"], sim["a"])
    assert servizi.candidati_sostituiti(sim["v"]) == [sim["m"]]


def test_sposta_rifiutato_con_confluenze(sim):
    n = _rinnova(sim)
    with pytest.raises(servizi.OperazioneNonAmmessa, match="confluito"):
        servizi.anteprima_spostamento(sim["m"], f.fabbisogno("Dest"), con_successivi=False)
    assert n.pk
