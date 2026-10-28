"""TC-18 sul database: import settimanale, presa in carico, referente proposto, convalida,
commento per PAC (SPEC Rev15 §4, §5.7, §5.8, §5.9, §7). Nomi e codici di fantasia."""

import datetime
from decimal import Decimal

import openpyxl
import pytest
from django.core.management import call_command

from accounts.roles import EDITOR, READER
from contratti import acquisti, fatture
from contratti import models as m
from contratti.engine.acquisti import PassoFattura
from contratti.importer.fatture import importa_fatture

from . import factories as f
from .engine.test_tc18_fatture import PAC_ATTESO

pytestmark = pytest.mark.django_db
D = datetime.date
OGGI = D(2026, 10, 7)
Passo = PassoFattura

RIGHE_FILE = [
    ["Rev. 00 del 05/10/2026"],
    ["#", "Fornitore", "Numero Documento", "Data", "Importo SAP", "Note"],
    [],
    [1, "Fornitore Prova A S.r.l.", "FA-1/2026", "04.09.2026", 1220, None],
    [2, "STUDIOP", "13/2026", "28.09.2026", "1679,83", None],
    [3, "Fornitore Sconosciuto", 99, "30.09.26", 10, None],
    [4, "Fornitore Prova A S.r.l.", "76 In attesa di nota credito", "22.09.2026", 78.9, None],
    [],
    [],
    [],
    [None, "Fatture in lavorazione"],
]


def file_tc18(tmp_path, righe=RIGHE_FILE, nome="estrazione.xlsx"):
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in righe:
        ws.append(r)
    percorso = tmp_path / nome
    wb.save(percorso)
    return percorso


@pytest.fixture
def registro(make_user):
    it, tlc = f.cluster("IT"), f.cluster("TLC")
    utenti = {
        "rossi": make_user("rossi", role=EDITOR),
        "bianchi": make_user("bianchi", role=EDITOR),
        "verdi": make_user("verdi", role=EDITOR),
        "neri": make_user("neri", role=READER),
        "gialli": make_user("gialli", role=EDITOR),
    }
    for nome, cluster in (("rossi", it), ("bianchi", it), ("verdi", tlc), ("gialli", None)):
        m.AssegnazioneCluster.objects.create(username=nome, cluster=cluster)
    m.FunzioneUtente.objects.create(
        username="gialli", funzione=m.FunzioneUtente.Funzione.AMMINISTRAZIONE_ACQUISTI
    )
    a = f.fornitore("Fornitore Prova A S.r.l.")
    s = f.fornitore("Studio Prova", nome_breve="STUDIOP")
    ca = f.contratto(
        fornitore=a,
        fabbisogno=f.fabbisogno("Servizio A", referente_utente=utenti["bianchi"]),
    )
    f.voce(ca)
    cs = f.contratto(
        fornitore=s,
        fabbisogno=f.fabbisogno("Consulenza S", referente_utente=utenti["bianchi"]),
        numero_contratto="5800000013",
    )
    conto = f.conto(
        codice="600010", descrizione="Conto di prova", valido_dal=D(2020, 1, 1), cluster=it
    )
    wbs = m.WBS.objects.create(codice_wbs="WBS-TEST-01", descrizione="WBS di prova", cluster=it)
    f.voce(
        cs, natura=m.Natura.CAPEX, conto=conto, centro_costo="C0001", wbs=wbs,
        importo_fisso=Decimal("5000.00"),
    )  # fmt: skip
    m.Fattura.objects.create(
        fornitore=s, contratto=cs, numero="12/2026", data=D(2026, 8, 31),
        importo_documento=Decimal("1000.00"), valore_base=Decimal("1000.00"),
        referente=utenti["rossi"], data_presa_in_carico=D(2026, 9, 1),
        esito_convalida="convalidabile", data_trasferimento=D(2026, 9, 20),
    )  # fmt: skip
    return {"ca": ca, "cs": cs, **utenti}


def _fattura(numero) -> m.Fattura:
    return fatture.QS_FATTURE.get(numero=numero)


def test_primo_import(registro, tmp_path):
    report = importa_fatture(file_tc18(tmp_path), oggi=OGGI)
    c = report.conteggi
    assert (c["create"], c["non_importate"], c["gia_presenti"]) == (4, 0, 0)
    assert c["con_contratto_proposto"] == 3 and c["fornitori_creati"] == 1
    assert [(a.riga, a.codice) for a in report.anomalie] == [
        (6, "FORNITORE_CREATO"),
        (7, "NUMERO_DA_VERIFICARE"),
    ]
    nuove = [_fattura(n) for n in ("FA-1/2026", "13/2026", "76 In attesa di nota credito")]
    for fa in nuove:
        assert fa.referente is None and fa.esito_convalida == "da_valutare"
        assert fa.valore_base is None and fa.contratto is None
        assert fatture.passo_fattura(fa, OGGI) == Passo.PRESA_IN_CARICO
    fa1, f13, f76 = nuove
    assert (fa1.data, fa1.importo_documento) == (D(2026, 9, 4), Decimal("1220.00"))
    assert f13.importo_documento == Decimal("1679.83")
    assert f76.importo_documento == Decimal("78.90")
    # Rev22: competenza di default, il mese prima della data della fattura.
    assert (fa1.competenza_dal, fa1.competenza_al) == (D(2026, 8, 1), D(2026, 8, 31))
    assert all(fa.competenza_dal and fa.competenza_al for fa in nuove)
    proposti = fatture.contratti_proposti(nuove)
    assert [proposti[x.pk] for x in nuove] == [registro["ca"], registro["cs"], registro["ca"]]
    referenti = fatture.referenti_proposti(nuove)
    assert [referenti[x.pk].username for x in nuove] == ["bianchi", "rossi", "bianchi"]


def test_dry_run_non_scrive(registro, tmp_path):
    report = importa_fatture(file_tc18(tmp_path), dry_run=True, oggi=OGGI)
    assert report.conteggi["create"] == 4
    assert m.Fattura.objects.count() == 1
    assert not m.Fornitore.objects.filter(ragione_sociale="Fornitore Sconosciuto").exists()


def test_fornitore_sconosciuto_creato_una_volta(registro, tmp_path):
    importa_fatture(file_tc18(tmp_path), oggi=OGGI)
    nuovo = m.Fornitore.objects.get(ragione_sociale="Fornitore Sconosciuto")
    assert _fattura("99").fornitore == nuovo
    report = importa_fatture(file_tc18(tmp_path, nome="seconda.xlsx"), oggi=OGGI)
    assert report.conteggi["fornitori_creati"] == 0
    assert m.Fornitore.objects.filter(ragione_sociale="Fornitore Sconosciuto").count() == 1


def test_fornitore_non_creato_per_riga_scartata(registro, tmp_path):
    righe = [list(r) for r in RIGHE_FILE]
    righe[5][4] = -10  # nota di credito: la riga si scarta
    report = importa_fatture(file_tc18(tmp_path, righe), oggi=OGGI)
    assert report.conteggi["fornitori_creati"] == 0
    assert not m.Fornitore.objects.filter(ragione_sociale="Fornitore Sconosciuto").exists()


def test_colonne_annotate_si_ignorano(registro, tmp_path):
    righe = [list(r) for r in RIGHE_FILE]
    righe[1] = [*righe[1], "REFERENTE", "CONVALIDABILE ?"]
    righe[4] = [*righe[4], "Rossi", "SI"]
    importa_fatture(file_tc18(tmp_path, righe), oggi=OGGI)
    f13 = _fattura("13/2026")
    assert f13.referente is None and f13.esito_convalida == "da_valutare"
    assert f13.nota_convalida == ""


def test_secondo_import_idempotente(registro, tmp_path):
    importa_fatture(file_tc18(tmp_path), oggi=OGGI)
    righe = [list(r) for r in RIGHE_FILE]
    righe[3][4] = 1250
    report = importa_fatture(file_tc18(tmp_path, righe, "seconda.xlsx"), oggi=OGGI)
    c = report.conteggi
    assert (c["create"], c["gia_presenti"]) == (0, 4)
    assert ("IMPORTO_DIVERSO", 4) in [(a.codice, a.riga) for a in report.anomalie]
    assert _fattura("FA-1/2026").importo_documento == Decimal("1220.00")


def test_comando(registro, tmp_path, capsys):
    call_command("import_fatture", str(file_tc18(tmp_path)), "--dry-run")
    assert "create 4" in capsys.readouterr().out
    assert m.Fattura.objects.count() == 1


def test_presa_in_carico(registro, tmp_path):
    importa_fatture(file_tc18(tmp_path), oggi=OGGI)
    rossi, bianchi, verdi = registro["rossi"], registro["bianchi"], registro["verdi"]
    fa1, f13, f76 = (_fattura(n) for n in ("FA-1/2026", "13/2026", "76 In attesa di nota credito"))
    esito = fatture.prendi_in_carico([f13.pk, fa1.pk], rossi, OGGI)
    assert {x.pk for x in esito.fatte} == {f13.pk, fa1.pk} and not esito.rifiutate
    fa1 = _fattura("FA-1/2026")
    assert fatture.passo_fattura(fa1, OGGI) == Passo.ASSEGNAZIONE
    # La 76 ora è proposta a rossi: ultima fattura di CA (proposto) in carico.
    assert fatture.referente_proposto(_fattura(f76.numero)) == rossi
    esito = fatture.prendi_in_carico([fa1.pk], bianchi, OGGI)
    assert esito.rifiutate[0][1] == "già in carico a rossi"
    # verdi (TLC) prende la 76 ma non può lavorarla una volta abbinata a CA (IT).
    assert fatture.prendi_in_carico([f76.pk], verdi, OGGI).fatte
    f76 = _fattura(f76.numero)
    assert fatture.puo_lavorare(verdi, f76)
    f76.contratto = registro["ca"]
    assert not fatture.puo_lavorare(verdi, f76)
    with pytest.raises(acquisti.OperazioneNonAmmessa):
        fatture.prendi_in_carico([f13.pk], registro["neri"], OGGI)
    fatture.lascia(fa1, rossi)
    assert _fattura("FA-1/2026").referente is None
    assert fatture.prendi_in_carico([fa1.pk], rossi, OGGI).fatte


def test_assegna_ai_referenti_proposti(registro, tmp_path):
    importa_fatture(file_tc18(tmp_path), oggi=OGGI)
    # La 99 è di un fornitore nuovo, senza contratto: non ha un referente proposto.
    pks = list(
        m.Fattura.objects.filter(referente__isnull=True)
        .exclude(numero="99")
        .values_list("pk", flat=True)
    )
    with pytest.raises(acquisti.OperazioneNonAmmessa):
        fatture.assegna_ai_proposti(pks, registro["bianchi"], OGGI)
    esito = fatture.assegna_ai_proposti(pks, registro["gialli"], OGGI)
    assert not esito.rifiutate
    assert {x.numero: x.referente.username for x in esito.fatte} == {
        "FA-1/2026": "bianchi",
        "13/2026": "rossi",
        "76 In attesa di nota credito": "bianchi",
    }
    for x in esito.fatte:
        assert fatture.passo_fattura(_fattura(x.numero), OGGI) == Passo.ASSEGNAZIONE


def test_senza_referente_proposto(registro, tmp_path):
    ca = registro["ca"]
    ca.fabbisogno.referente_utente = None
    ca.fabbisogno.save()
    importa_fatture(file_tc18(tmp_path), oggi=OGGI)
    pks = list(m.Fattura.objects.filter(referente__isnull=True).values_list("pk", flat=True))
    esito = fatture.assegna_ai_proposti(pks, registro["gialli"], OGGI)
    assert [x.numero for x in esito.fatte] == ["13/2026"]
    assert sorted(r[0].numero for r in esito.rifiutate) == [
        "76 In attesa di nota credito", "99", "FA-1/2026",
    ]  # fmt: skip
    assert {r[1] for r in esito.rifiutate} == {"senza referente proposto"}


def test_lavorazione_13_2026_e_pac(registro, tmp_path):
    importa_fatture(file_tc18(tmp_path), oggi=OGGI)
    rossi, cs = registro["rossi"], registro["cs"]
    f13 = _fattura("13/2026")
    fatture.prendi_in_carico([f13.pk], rossi, OGGI)
    fatture.assegna_contratto(_fattura("13/2026"), cs)
    f13 = _fattura("13/2026")
    assert f13.voce == cs.voci.get()  # unica voce del contratto
    assert fatture.passo_fattura(f13, OGGI) == Passo.CONVALIDA
    fatture.convalida(f13, "convalidabile", data=OGGI)
    assert fatture.passo_fattura(_fattura("13/2026"), OGGI) == Passo.RDC
    fatture.aggiorna_importi(
        f13,
        Decimal("1504.17"),
        Decimal("173.66"),
        Decimal("2.00"),
        competenza=(datetime.date(2026, 1, 1), datetime.date(2026, 12, 31)),
    )
    f13 = _fattura("13/2026")
    assert fatture.anomalie(f13) == []
    assert fatture.indicazioni_validazione(f13) == (
        "Contratto 5800000013. Valore base da prelevare € 1.504,17. "
        "COGE: 600010, CDC: C0001, WBS: WBS-TEST-01"
    )
    f13.bollo = Decimal("3.00")
    assert fatture.anomalie(f13) == ["IMPORTO_NON_QUADRA"]
    f13 = _fattura("13/2026")
    fatture.registra_documento(f13, "ODA_RDC", "RDC-0001", OGGI)
    f13 = _fattura("13/2026")
    assert fatture.commento_pac(f13).splitlines()[2] == "MAP: (da registrare)"
    with pytest.raises(acquisti.OperazioneNonAmmessa):
        fatture.registra_documento(f13, "ODA_RDC", "RDC-0002", OGGI)  # una RdC per fattura
    fatture.registra_documento(f13, "MAP", "MAP-0001", OGGI)
    f13 = _fattura("13/2026")
    assert fatture.passo_fattura(f13, OGGI) == Passo.RDC_RILASCIO  # i documenti vanno rilasciati
    m.DocumentoEsecuzione.objects.filter(fattura=f13).update(data_rilascio=OGGI)
    f13 = _fattura("13/2026")
    assert fatture.passo_fattura(f13, OGGI) == Passo.TRASFERIMENTO
    assert fatture.commento_pac(f13) == PAC_ATTESO
    # Fatturato di CS: i valori base (1.000,00 della 12/2026 + 1.504,17), non 1.679,83.
    assert acquisti.riepilogo_esecuzione(cs, OGGI).esecuzione.fatturato == Decimal("2504.17")


def test_fa1_in_attesa_e_fuori_registro(registro, tmp_path):
    importa_fatture(file_tc18(tmp_path), oggi=OGGI)
    rossi = registro["rossi"]
    fa1 = _fattura("FA-1/2026")
    fatture.prendi_in_carico([fa1.pk], rossi, D(2026, 10, 1))
    fatture.assegna_contratto(_fattura("FA-1/2026"), registro["ca"])
    fa1 = _fattura("FA-1/2026")
    with pytest.raises(acquisti.OperazioneNonAmmessa):
        fatture.convalida(fa1, "in_attesa")  # serve la nota
    fatture.convalida(
        fa1, "in_attesa", "in attesa di prove di funzionamento in campo", D(2026, 10, 6),
        data=D(2026, 10, 2),
    )  # fmt: skip
    # Bloccata fino al 06/10 compreso (Rev20), poi di nuovo da convalidare.
    assert fatture.passo_fattura(_fattura("FA-1/2026"), D(2026, 10, 6)) == Passo.BLOCCATA
    assert fatture.passo_fattura(_fattura("FA-1/2026"), D(2026, 10, 7)) == Passo.CONVALIDA
    assert fatture.da_lavorare(fa1, OGGI)
    fatture.segna_fuori_registro([fa1.pk], rossi)
    assert not fatture.da_lavorare(_fattura("FA-1/2026"), OGGI)
    assert "VALORE_BASE_MANCANTE" not in fatture.anomalie(_fattura("FA-1/2026"))


def test_assegnazione_rifiutata(registro, tmp_path):
    importa_fatture(file_tc18(tmp_path), oggi=OGGI)
    fa1 = _fattura("FA-1/2026")
    with pytest.raises(acquisti.OperazioneNonAmmessa):
        fatture.assegna_contratto(fa1, registro["cs"])  # altro fornitore
    with pytest.raises(acquisti.OperazioneNonAmmessa):
        fatture.registra_documento(fa1, "ODA_RDC", "RDC-9", OGGI)  # prima il contratto
    acquisti.chiudi(registro["ca"], registro["rossi"], OGGI)
    with pytest.raises(acquisti.OperazioneNonAmmessa):
        fatture.assegna_contratto(fa1, registro["ca"])
    # Contratto chiuso: non è più proposto.
    assert fatture.contratto_proposto(fa1) is None


def test_import_riconosce_l_alias_sap(tmp_path):
    giusto = f.fornitore("Telecom Italia S.p.A.", alias_sap="TIM S.p.A.\nTIM SPA")
    righe = [
        ["#", "Fornitore", "Numero Documento", "Data", "Importo SAP", "Note"],
        [1, "TIM S.p.A.", "T-1", "04.09.2026", 100, None],
        [2, "Telecom Italia SPA", "T-2", "05.09.2026", 200, None],
    ]
    report = importa_fatture(file_tc18(tmp_path, righe), oggi=OGGI)
    assert report.conteggi["create"] == 2 and report.conteggi["fornitori_creati"] == 0
    assert set(m.Fattura.objects.values_list("fornitore", flat=True)) == {giusto.pk}
    assert m.Fornitore.objects.count() == 1


def test_form_fornitore_alias_in_conflitto(tmp_path):
    from contratti.forms import FornitoreForm

    f.fornitore("Telecom Italia S.p.A.")
    altro = f.fornitore("Altro Fornitore S.r.l.")
    form = FornitoreForm(
        {"ragione_sociale": altro.ragione_sociale, "alias_sap": "Telecom Italia SPA"},
        instance=altro,
    )
    assert not form.is_valid() and "alias_sap" in form.errors
    form = FornitoreForm(
        {"ragione_sociale": altro.ragione_sociale, "alias_sap": " TIM SPA \n\ntim s.p.a. "},
        instance=altro,
    )
    assert form.is_valid() and form.cleaned_data["alias_sap"] == "TIM SPA"
