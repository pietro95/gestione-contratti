"""Processo d'acquisto (F11.1) sul database: vincoli, stato della pratica dalle RDA,
contratti una tantum, proposte dal fabbisogno, scheda SAP, esecuzione (TC-15, TC-16, TC-17)."""

import datetime
import importlib
from decimal import Decimal

import pytest
from django.apps import apps
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from contratti import acquisti, adapters, selettori, servizi
from contratti import models as m
from contratti.engine.acquisti import Fase, MotivoChiusura
from contratti.engine.tipi import Alert, Livello
from reports.budget import Filtri, calcola_budget
from reports.piano_ordini import calcola_piano

from . import factories as f
from .engine.test_tc17_scheda_sap import TESTO_ATTESO

pytestmark = pytest.mark.django_db
D = datetime.date
EVENTO = m.EventoRDA.Tipo
BASE = "smb://nas.esempio.local/Share/ICTDINN/00_IT/RDA_Ordini"


@pytest.fixture
def referente(make_user):
    from accounts.roles import EDITOR

    return make_user("referente", role=EDITOR)


def _conto(codice, cluster=None):
    return m.ContoCoge.objects.create(
        codice=codice,
        descrizione=f"Conto {codice} (prova)",
        valido_dal=D(2020, 1, 1),
        cluster=cluster or f.cluster("IT"),
    )


def _rda(**kw):
    kw.setdefault("cluster", f.cluster("IT"))
    kw.setdefault("descrizione", "Richiesta di prova")
    kw.setdefault("origine", m.RichiestaAcquisto.Origine.MANUALE)
    return m.RichiestaAcquisto.objects.create(**kw)


def _integrity(crea):
    with pytest.raises(IntegrityError), transaction.atomic():
        crea()


# --- Vincoli ------------------------------------------------------------------------------


def test_vincoli_rda(referente):
    c = f.contratto()
    fab = c.fabbisogno
    _integrity(lambda: _rda(fabbisogno=fab, contratto_in_scadenza=c))
    _integrity(lambda: _rda(fabbisogno=fab, scopo="rinnovo"))
    _integrity(lambda: _rda(contratto_in_scadenza=c, scopo="aggiuntivo"))
    _integrity(lambda: _rda(origine="portale", fabbisogno=fab))  # senza referente
    _integrity(lambda: _rda(origine="portale", referente_utente=referente))  # senza legami
    _rda(numero_rda="5100000001")
    _integrity(lambda: _rda(numero_rda="5100000001"))
    _rda(numero_rda="5100000001", archiviato=True)  # archiviata: non conta


def test_vincoli_posizioni_fatture_documenti():
    rda = _rda()
    wbs = m.WBS.objects.create(codice_wbs="WBS-PROVA", descrizione="Prova")
    m.PosizioneRDA.objects.create(rda=rda, numero=1, descrizione_breve="A", importo_unitario=1)
    _integrity(
        lambda: m.PosizioneRDA.objects.create(
            rda=rda, numero=2, descrizione_breve="B", importo_unitario=1, natura="CAPEX"
        )
    )
    _integrity(
        lambda: m.PosizioneRDA.objects.create(
            rda=rda, numero=3, descrizione_breve="C", importo_unitario=1, wbs=wbs
        )
    )
    _integrity(
        lambda: m.PosizioneRDA.objects.create(
            rda=rda, numero=4, descrizione_breve="D", importo_unitario=1, quantita=0
        )
    )
    posizione = m.PosizioneRDA(
        rda=rda, numero=5, descrizione_breve="E", importo_unitario=10, di_cui_variabile=11
    )
    with pytest.raises(ValidationError):
        posizione.full_clean()
    c = f.contratto()
    m.Fattura.objects.create(contratto=c, numero="FA-1", data=D(2026, 3, 1), imponibile=1)
    altro = f.contratto(fornitore=c.fornitore, fabbisogno=c.fabbisogno)
    _integrity(
        lambda: m.Fattura.objects.create(
            contratto=altro, numero="FA-1", data=D(2026, 3, 2), imponibile=1
        )
    )
    _integrity(
        lambda: m.DocumentoEsecuzione.objects.create(
            contratto=c, tipo="DDT", data=D(2026, 3, 1), finale=True
        )
    )


def test_predefinito_unico_per_tabella():
    m.RichiedenteSAP.objects.create(codice="999901", predefinito=True)
    _integrity(lambda: m.RichiedenteSAP.objects.create(codice="999902", predefinito=True))
    m.GruppoAcquisti.objects.create(codice="G01", predefinito=True)
    m.GruppoMerci.objects.create(codice="GM-TEST01", predefinito=True)
    assert m.RichiedenteSAP.predefinito_attivo().codice == "999901"


def test_una_tantum_fuori_dalla_catena():
    c1 = f.contratto(una_tantum=True)
    _integrity(lambda: f.contratto(fabbisogno=c1.fabbisogno, una_tantum=True, predecessore=c1))
    rinnovo = m.Contratto(
        fabbisogno=c1.fabbisogno,
        fornitore=c1.fornitore,
        procedura=c1.procedura,
        predecessore=c1,
        data_inizio=D(2027, 1, 1),
        durata_mesi=12,
    )
    with pytest.raises(ValidationError):
        rinnovo.clean()
    with pytest.raises(servizi.OperazioneNonAmmessa):
        servizi.registra_rinnovo(c1, {"fornitore": c1.fornitore, "procedura": c1.procedura}, [])
    with pytest.raises(ValidationError):
        _rda(contratto_in_scadenza=c1).full_clean()


def test_cluster_della_rda_e_quello_del_fabbisogno():
    fab = f.fabbisogno(cluster=f.cluster("TLC"))
    with pytest.raises(ValidationError):
        m.RichiestaAcquisto(cluster=f.cluster("IT"), fabbisogno=fab, descrizione="x").full_clean()


def test_permessi_dei_ruoli():
    editor = set(Group.objects.get(name="Editor").permissions.values_list("codename", flat=True))
    reader = set(Group.objects.get(name="Reader").permissions.values_list("codename", flat=True))
    for modello in ("richiestaacquisto", "posizionerda", "eventorda", "fattura"):
        assert {f"add_{modello}", f"change_{modello}", f"view_{modello}"} <= editor
        assert f"view_{modello}" in reader and f"add_{modello}" not in reader
    for modello in ("richiedentesap", "gruppoacquisti", "gruppomerci", "funzioneutente"):
        assert f"view_{modello}" in editor and f"add_{modello}" not in editor
        assert not any(p.startswith("delete_") for p in editor | reader)


# --- TC-15: stato della pratica dalle RDA, sul database --------------------------------------


@pytest.fixture
def tc15(referente):
    """C1: fine 31/12/2026, lead time 4 mesi; Offerta ricevuta il 01/06/2026; R1 sulla pratica."""
    fab = f.fabbisogno("Servizio di prova", decisione="rinnovare")
    c1 = f.contratto(fabbisogno=fab, lead_time_mesi_override=4)
    f.voce(c1)
    servizi.avanza_pratica(c1, "offerta_ricevuta", D(2026, 6, 1))
    r1 = _rda(
        origine="portale",
        scopo="rinnovo",
        contratto_in_scadenza=c1,
        referente_utente=referente,
        data_creazione=D(2026, 6, 8),
    )
    m.PosizioneRDA.objects.create(rda=r1, numero=1, descrizione_breve="Canone", importo_unitario=1)
    return c1, r1


def test_tc15_sul_database(tc15, referente):
    c1, r1 = tc15
    acquisti.invia(r1, referente, D(2026, 6, 10))
    acquisti.rimanda(r1, "Manca il preventivo", data=D(2026, 6, 11))
    acquisti.invia(r1, referente, D(2026, 6, 12))
    r1.numero_rda, r1.data_inserimento, r1.data_rilascio = "5100000001", D(2026, 6, 15), None
    r1.save()
    attesi = [
        (D(2026, 6, 5), "offerta_ricevuta"),
        (D(2026, 6, 11), "offerta_ricevuta"),
        (D(2026, 6, 13), "rda_richiesta"),
        (D(2026, 6, 20), "rda_predisposta"),
    ]
    for oggi, stato in attesi:
        assert adapters.stato_pratica_corrente(c1, oggi) == stato, oggi
        assert adapters.alert_contratto(c1, oggi) == Alert.GIALLO
    riga = selettori.righe_contratti(
        selettori.contratti_terminali().filter(pk=c1.pk), D(2026, 6, 20)
    )
    assert riga[0].stato_pratica == "rda_predisposta"

    # Rinnovo registrato dalla RDA: nessun passaggio «Contratto attivo» scritto a mano.
    r1.data_rilascio = D(2026, 7, 1)
    r1.save()
    c2 = servizi.registra_rinnovo(
        c1,
        {
            "fornitore": c1.fornitore,
            "procedura": c1.procedura,
            "data_inizio": D(2027, 1, 1),
            "durata_mesi": 12,
            "data_emissione": D(2026, 7, 20),
            "rda": r1,
        },
        [],
    )
    assert list(c1.stati_pratica.values_list("stato", flat=True)) == ["offerta_ricevuta"]
    assert acquisti.stato_pratica_con_data(c1, D(2026, 7, 25)) == (
        "contratto_emesso",
        D(2026, 7, 20),
    )
    assert acquisti.stato_pratica(c1, D(2027, 1, 5)) == "contratto_attivo"
    assert acquisti.fase(r1, D(2027, 1, 5)) == Fase.CONTRATTO_EMESSO
    assert adapters.alert_contratto(c1, D(2026, 9, 1)) is None
    assert c2.rda == r1


def test_tc15_invio_e_rimando_ammessi_solo_nella_fase_giusta(tc15, referente):
    _, r1 = tc15
    with pytest.raises(acquisti.OperazioneNonAmmessa):
        acquisti.rimanda(r1, "x", data=D(2026, 6, 9))  # ancora in bozza
    acquisti.invia(r1, referente, D(2026, 6, 10))
    with pytest.raises(acquisti.OperazioneNonAmmessa):
        acquisti.invia(r1, referente, D(2026, 6, 11))
    with pytest.raises(acquisti.OperazioneNonAmmessa):
        acquisti.rimanda(r1, "  ", data=D(2026, 6, 11))
    acquisti.annulla(r1, "Non serve più", data=D(2026, 6, 12))
    assert acquisti.fase(r1, D(2026, 6, 12)) == Fase.ANNULLATA


def test_tc15_f_rda_a_mano_collegata_dopo():
    c5 = f.contratto(lead_time_mesi_override=4)
    r3 = _rda(numero_rda="5100000003", data_inserimento=D(2026, 2, 2), data_creazione=D(2026, 2, 3))
    assert acquisti.fase(r3, D(2026, 2, 5)) == Fase.INSERITA
    assert acquisti.stato_pratica(c5, D(2026, 2, 10)) is None
    r3.contratto_in_scadenza = c5
    r3.save()
    assert acquisti.stato_pratica_con_data(c5, D(2026, 2, 10)) == ("rda_predisposta", D(2026, 2, 2))


def test_rda_del_fabbisogno_nuovo_e_acquisto_aggiuntivo(referente):
    nuovo = f.fabbisogno(
        "Fabbisogno nuovo", previsto_data_avvio=D(2027, 1, 1), previsto_durata_mesi=12
    )
    r = _rda(fabbisogno=nuovo, numero_rda="5100000010", data_inserimento=D(2026, 9, 1))
    assert acquisti.stato_pratica(nuovo, D(2026, 9, 2)) == "rda_predisposta"
    r.scopo = "aggiuntivo"
    r.save()
    assert acquisti.stato_pratica(nuovo, D(2026, 9, 2)) is None
    riga = selettori.righe_previsti_manuali(D(2026, 9, 2), {})
    assert [x.stato_pratica for x in riga if x.previsto_manuale == nuovo] == [None]


# --- TC-16: contratto una tantum sul database -----------------------------------------------


@pytest.fixture
def f1():
    fab = f.fabbisogno("Forniture di prova", decisione="rinnovare")
    r1 = _rda(fabbisogno=fab, numero_rda="5100000016", data_creazione=D(2026, 2, 20))
    c = f.contratto(
        fabbisogno=fab,
        una_tantum=True,
        rda=r1,
        data_emissione=D(2026, 3, 2),
        data_inizio=D(2026, 3, 2),
        durata_mesi=1,
    )
    voce = f.voce(c, importo_fisso=Decimal("10000.00"), massimale_variabile=Decimal("2000.00"))
    piano = f.piano(voce, modalita="una_tantum", periodicita="")
    servizi.genera_scadenzario(voce)
    assert [(r.data_fattura, r.importo) for r in piano.rate.all()] == [
        (D(2026, 3, 2), Decimal("10000.00"))
    ]
    return c, r1


def test_tc16_una_tantum_fuori_da_alert_previsti_piano(f1):
    c, _ = f1
    for oggi in (D(2026, 3, 5), D(2026, 4, 2), D(2027, 1, 1)):
        assert adapters.alert_contratto(c, oggi) is None
    assert not selettori.contratti_terminali().filter(pk=c.pk).exists()
    assert adapters.previsti_fabbisogno(c.fabbisogno, D(2029, 12, 31)) == []
    for anno in (2026, 2027):
        assert calcola_piano(anno, D(2026, 3, 5)).righe == []
    # Un contratto normale precedente: nessuna catena con il contratto una tantum.
    vecchio = f.contratto(fabbisogno=c.fabbisogno, data_inizio=D(2025, 1, 1), durata_mesi=12)
    assert servizi.collegamenti_del_fabbisogno(c.fabbisogno) == []
    assert c not in servizi.candidati_rinnovo(vecchio)
    assert c.pk not in {x.pk for x in servizi.candidati_sostituiti(vecchio)}


def test_tc16_budget_invariato(f1):
    totali = calcola_budget(Filtri(anno=2026), D(2026, 6, 1)).totali()["totale"]
    for vista in ("cassa", "impegno", "competenza"):
        assert totali[vista][Livello.FISSO] == Decimal("10000.00"), vista


def test_tc16_esecuzione_e_chiusura(f1, referente):
    c, r1 = f1
    voce = c.voci.get()
    rata = voce.piano_fatturazione.rate.get()
    m.DocumentoEsecuzione.objects.create(contratto=c, tipo="DDT", data=D(2026, 3, 10))
    m.Fattura.objects.create(contratto=c, numero="FA-1", data=D(2026, 3, 15), imponibile=4000)
    fa2 = m.Fattura.objects.create(
        contratto=c, numero="FA-2", data=D(2026, 4, 20), imponibile=5000, rata=rata
    )
    fa2.full_clean()
    riepilogo = acquisti.riepilogo_esecuzione(c, D(2026, 4, 25))
    assert riepilogo.esecuzione.fatturato == Decimal("9000.00")
    assert riepilogo.esecuzione.residuo_massimo == Decimal("3000.00")
    assert riepilogo.esecuzione.avanzamento_pct == 90
    assert riepilogo.motivo_da_chiudere == MotivoChiusura.ATTESTAZIONE_MANCANTE
    m.DocumentoEsecuzione.objects.create(
        contratto=c, tipo="RICEZIONE", data=D(2026, 4, 28), finale=True
    )
    assert acquisti.riepilogo_esecuzione(c, D(2026, 4, 30)).motivo_da_chiudere == (
        MotivoChiusura.FATTURE_MANCANTI
    )
    m.Fattura.objects.create(contratto=c, numero="FA-3", data=D(2026, 5, 5), imponibile=3500)
    riepilogo = acquisti.riepilogo_esecuzione(c, D(2026, 5, 6))
    assert riepilogo.motivo_da_chiudere == MotivoChiusura.PRONTO
    assert riepilogo.anomalie == ["FATTURATO_OLTRE_MASSIMO"]
    assert acquisti.fase(r1, D(2026, 5, 6)) == Fase.IN_ESECUZIONE
    acquisti.chiudi(c, referente, D(2026, 5, 10))
    assert acquisti.fase(r1, D(2026, 5, 11)) == Fase.CHIUSA
    assert acquisti.riepilogo_esecuzione(c, D(2026, 5, 11)).motivo_da_chiudere is None
    with pytest.raises(acquisti.OperazioneNonAmmessa):
        acquisti.chiudi(c, referente)
    acquisti.annulla_chiusura(c)
    assert acquisti.fase(r1, D(2026, 5, 11)) == Fase.IN_ESECUZIONE
    # Il budget resta quello dello scadenzario (la rata, non le fatture).
    rata.refresh_from_db()
    assert rata.importo == Decimal("10000.00")


# --- TC-17: scheda SAP e proposte dal fabbisogno -----------------------------------------------


@pytest.fixture
def tabelle_sap():
    m.RichiedenteSAP.objects.create(
        codice="999901", descrizione="Ufficio di prova", predefinito=True
    )
    m.RichiedenteSAP.objects.create(codice="999902", descrizione="Altro ufficio")
    m.GruppoAcquisti.objects.create(codice="G01", descrizione="Gruppo di prova", predefinito=True)
    m.GruppoAcquisti.objects.create(codice="G02")
    m.GruppoMerci.objects.create(codice="GM-TEST01", predefinito=True)
    m.GruppoMerci.objects.create(codice="GM-TEST02")
    it = f.cluster("IT")
    it.cartella_rda = BASE
    it.save()
    fornitore = f.fornitore("Software Prova S.r.l.", nome_breve="SWPROVA")
    conti = {c: _conto(c, it) for c in ("600001", "600002", "600003")}
    return fornitore, conti


def test_tc17_scheda_e_testo_dal_database(tabelle_sap):
    fornitore, conti = tabelle_sap
    rda = _rda(
        intestazione="SWPROVA - Rinnovo licenza CAD (2 postazioni)",
        descrizione="Rinnovo licenza CAD (2 postazioni)",
        fornitore_proposto=fornitore,
        richiedente=m.RichiedenteSAP.objects.get(codice="999901"),
        gruppo_acquisti=m.GruppoAcquisti.objects.get(codice="G01"),
        note_buyer="Si allega preventivo",
        allegati="preventivo nella cartella del file server",
        percorso_file_server=f"{BASE}/2026/2026_09_29_SWPROVA_Rinnovo_licenza_CAD_2_postazioni",
    )
    for numero, (descrizione, gm, q, prezzo, conto) in enumerate(
        [
            ("SWPROVA - Rinnovo licenza CAD (2 postazioni)", "GM-TEST01", "2", "549.50", "600001"),
            ("Supporto installazione", "GM-TEST02", "2.5", "99.99", "600002"),
        ],
        start=1,
    ):
        m.PosizioneRDA.objects.create(
            rda=rda,
            numero=numero,
            descrizione_breve=descrizione,
            gruppo_merci=m.GruppoMerci.objects.get(codice=gm),
            quantita=Decimal(q),
            importo_unitario=Decimal(prezzo),
            conto=conti[conto],
            centro_costo="C0001",
        )
    assert acquisti.testo_della_richiesta(rda) == TESTO_ATTESO
    assert acquisti.importo_rda(rda) == Decimal("1348.98")
    # Contratto emesso per 1.300,00: la differenza si mostra, la RDA non cambia.
    c = f.contratto(fornitore=fornitore, rda=rda)
    f.voce(c, importo_fisso=Decimal("1060.00"))
    f.voce(c, importo_fisso=Decimal("240.00"))
    assert acquisti.differenza_da_rda(c) == Decimal("-48.98")


@pytest.fixture
def licenze_cad(tabelle_sap):
    fornitore, conti = tabelle_sap
    m.Parametro.objects.create(
        chiave="adeguamento_pct", valore=Decimal("3"), valido_dal=D(2026, 1, 1)
    )
    fab = f.fabbisogno("Licenze CAD di prova", decisione="rinnovare")
    c1 = f.contratto(fabbisogno=fab, fornitore=fornitore, rup="Rossi")
    f.voce(c1, descrizione="Canone licenze", conto=conti["600001"], centro_costo="C0001")
    f.voce(
        c1,
        descrizione="Assistenza a consumo",
        importo_fisso=Decimal("200.00"),
        massimale_variabile=Decimal("500.00"),
        conto=conti["600002"],
        conto_rinnovi=conti["600003"],
        centro_costo="C0001",
    )
    return fab, c1, conti


def test_tc17_a_rinnovo_dal_fabbisogno(licenze_cad, referente):
    fab, c1, conti = licenze_cad
    p = acquisti.proposta_richiesta(fab, D(2026, 9, 29))
    assert (p.scopo, p.contratto_in_scadenza, p.alternative) == ("rinnovo", c1, [])
    assert p.descrizione == "Licenze CAD di prova"
    assert p.intestazione == "SWPROVA - Licenze CAD di prova"
    assert p.fornitore_proposto == c1.fornitore and p.rup == "Rossi"
    assert (p.richiedente.codice, p.gruppo_acquisti.codice) == ("999901", "G01")
    assert p.percorso_file_server == f"{BASE}/2026/2026_09_29_SWPROVA_Licenze_CAD_di_prova"
    righe = [
        (x.descrizione_breve, x.importo_unitario, x.di_cui_variabile, x.conto, x.gruppo_merci)
        for x in p.posizioni
    ]
    gm = m.GruppoMerci.objects.get(codice="GM-TEST01")
    assert righe == [
        (
            "SWPROVA - Licenze CAD di prova",
            Decimal("1030.00"),
            Decimal("0.00"),
            conti["600001"],
            gm,
        ),
        ("Assistenza a consumo", Decimal("721.00"), Decimal("515.00"), conti["600003"], gm),
    ]
    assert p.importo == Decimal("1751.00")

    rda = acquisti.crea_richiesta(p, referente)
    assert acquisti.fase(rda, D(2026, 9, 29)) == Fase.BOZZA
    assert acquisti.stato_pratica(c1, D(2026, 9, 29)) is None
    acquisti.invia(rda, referente, D(2026, 9, 30))
    assert acquisti.stato_pratica(c1, D(2026, 9, 30)) == "rda_richiesta"

    voci = acquisti.voci_da_rda(rda)
    assert [(v["importo_fisso"], v["massimale_variabile"]) for v in voci] == [
        (Decimal("1030.00"), Decimal("0.00")),
        (Decimal("206.00"), Decimal("515.00")),
    ]
    c2 = f.contratto(fabbisogno=fab, fornitore=c1.fornitore, rda=rda, data_inizio=D(2027, 1, 1))
    for v in voci:
        f.voce(c2, **v)
    assert acquisti.differenza_da_rda(c2) == Decimal("0.00")


def test_tc17_b_acquisto_aggiuntivo(licenze_cad, referente):
    fab, c1, conti = licenze_cad
    p = acquisti.proposta_richiesta(fab, D(2026, 9, 29), aggiuntivo=True)
    assert (p.scopo, p.contratto_in_scadenza, p.fornitore_proposto) == ("aggiuntivo", None, None)
    assert len(p.posizioni) == 1
    posizione = p.posizioni[0]
    assert (posizione.importo_unitario, posizione.conto, posizione.centro_costo) == (
        None,
        conti["600001"],
        "C0001",
    )
    rda = acquisti.crea_richiesta(p, referente)
    assert rda.fabbisogno == fab and rda.contratto_in_scadenza is None
    acquisti.invia(rda, referente, D(2026, 9, 30))
    assert acquisti.stato_pratica(c1, D(2026, 9, 30)) is None
    assert acquisti.stato_pratica(fab, D(2026, 9, 30)) is None


def test_tc17_c_primo_acquisto(tabelle_sap, referente):
    _, conti = tabelle_sap
    fab = f.fabbisogno(
        "Licenze CAD di prova",
        stima_prossimo_importo=Decimal("5000.00"),
        conto_previsti=conti["600001"],
    )
    p = acquisti.proposta_richiesta(fab, D(2026, 9, 29))
    assert (p.scopo, p.contratto_in_scadenza, p.fornitore_proposto) == (
        "primo_acquisto",
        None,
        None,
    )
    assert [(x.descrizione_breve, x.importo_unitario, x.conto) for x in p.posizioni] == [
        ("Licenze CAD di prova", Decimal("5000.00"), conti["600001"])
    ]
    with pytest.raises(acquisti.OperazioneNonAmmessa):
        acquisti.proposta_richiesta(fab, aggiuntivo=True)
    rda = acquisti.crea_richiesta(p, referente)
    acquisti.invia(rda, referente, D(2026, 9, 30))
    assert acquisti.stato_pratica(fab, D(2026, 9, 30)) == "rda_richiesta"


def test_tc17_d_catena_interrotta(licenze_cad):
    fab, c1, _ = licenze_cad
    c0 = f.contratto(fabbisogno=fab, data_inizio=D(2025, 7, 1), durata_mesi=12)
    f.voce(c0)
    p = acquisti.proposta_richiesta(fab, D(2026, 9, 29))
    assert (p.contratto_in_scadenza, p.alternative) == (c1, [c0])
    scelto = acquisti.proposta_richiesta(fab, D(2026, 9, 29), contratto_in_scadenza=c0)
    assert scelto.contratto_in_scadenza == c0
    c3 = f.contratto(fabbisogno=fab, predecessore=c1, data_inizio=D(2027, 1, 1))
    with pytest.raises(acquisti.OperazioneNonAmmessa):
        acquisti.proposta_richiesta(fab, contratto_in_scadenza=c1)
    assert acquisti.proposta_richiesta(fab, D(2026, 9, 29)).contratto_in_scadenza == c3


def test_gruppo_merci_dalla_categoria(tabelle_sap):
    fab = f.fabbisogno()
    m.GruppoMerci.objects.create(codice="GM-CAT", categoria=fab.categoria)
    assert acquisti.gruppo_merci_proposto(fab).codice == "GM-CAT"


# --- Migration: il n. RDA dei contratti diventa una RDA -----------------------------------------


def test_migrazione_rda_dai_contratti():
    migrazione = importlib.import_module("contratti.migrations.0026_processo_acquisto_dati")
    a = f.contratto(numero_rda="5100000099", data_emissione=D(2025, 12, 15))
    b = f.contratto(fabbisogno=a.fabbisogno, numero_rda=" 5100000099")
    vecchio = f.contratto(fabbisogno=a.fabbisogno, numero_rda="RDA 12/21")
    migrazione.rda_dai_contratti(apps, None)
    for c in (a, b, vecchio):
        c.refresh_from_db()
    assert a.rda == b.rda and a.rda.numero_rda == "5100000099"
    assert a.rda.cluster == a.fabbisogno.cluster and a.rda.referente_utente is None
    assert a.rda.data_creazione == D(2025, 12, 15)
    assert acquisti.fase(a.rda, D(2026, 1, 1)) == Fase.CONTRATTO_EMESSO
    assert vecchio.rda is None and vecchio.numero_rda == "RDA 12/21"
    migrazione.rda_dai_contratti(apps, None)  # idempotente
    assert m.RichiestaAcquisto.objects.filter(numero_rda="5100000099").count() == 1
