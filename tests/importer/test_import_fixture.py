"""Accettazione F3: import completo delle due fixture e report delle anomalie note (SPEC §2.2)."""

from decimal import Decimal

import pytest
from django.core.management import call_command

from contratti import models as m
from contratti.importer.carica import importa

from .conftest import IT, OGGI, TLC

pytestmark = pytest.mark.django_db


@pytest.fixture
def piano_dei_conti():
    # Conti fittizi presenti nelle fixture, tranne 62700 (TC-08).
    for codice in ("634935", "627020", "627021", "635220", "627029", "627030", "627031"):
        m.ContoCoge.objects.create(
            codice=codice, descrizione=f"Conto {codice}", valido_dal="2020-01-01"
        )


@pytest.fixture
def importati(piano_dei_conti):
    return importa(IT, area="IT", oggi=OGGI), importa(TLC, area="TLC", oggi=OGGI)


def anomalie(report, codice):
    return [a for a in report.anomalie if a.codice == codice]


def test_import_completo_senza_eccezioni(importati):
    it, tlc = importati
    assert it.conteggi["contratti_creati"] == 67
    assert tlc.conteggi["contratti_creati"] == 23
    assert m.Contratto.objects.filter(fabbisogno__cluster__codice="IT").count() == 67
    assert m.Contratto.objects.filter(fabbisogno__cluster__codice="TLC").count() == 23
    # Nessun nullo scritto come testo.
    for campo in ("numero_contratto", "cig"):
        valori = set(m.Contratto.objects.values_list(campo, flat=True))
        assert not valori & {"n/a", "N/A", "n/d", "", "0"}


def test_anomalie_note_del_file_it(importati):
    it, _ = importati
    righe = {codice: {a.riga for a in anomalie(it, codice)} for codice in it.codici()}
    assert righe["CARATTERI_INVISIBILI"] >= {42, 49, 50, 60, 61}  # BOM
    assert righe["CIG_LUNGHEZZA"] == {53}  # 9 caratteri
    assert 63 in righe["ODA_FORMATO"]  # 9 cifre
    assert righe["CONTO_SCONOSCIUTO"] == {62}  # 62700
    assert righe["MASSIMO_SOVRASCRITTO"] == {30, 39, 55}  # J30, J39, J55
    assert righe["MASSIMO_INCOERENTE"] == {30}
    assert {38, 39, 51} <= righe["IMPORTO_ZERO"]
    assert righe["IMPORTO_NON_LEGGIBILE"] == {49}
    assert {11, 46} <= righe["ODA_RIUSATO"]  # stesso OdA e CIG su due annualità
    assert righe["FORNITORE_MANCANTE"] == {5}  # foglio Dissalatori
    assert righe["WBS_MANCANTE"] == {5}
    (condiviso,) = anomalie(it, "CODICE_SAP_CONDIVISO")
    assert condiviso.valore == "350121" and "4 fornitori" in condiviso.messaggio


def test_anomalie_note_del_file_tlc(importati):
    _, tlc = importati
    assert {a.riga for a in anomalie(tlc, "DATA_MANCANTE")} == {5}
    assert [a.valore for a in anomalie(tlc, "FORNITORE_DUPLICATO")] == ["Fornitore 10 S.r.l."]
    # Codice SAP presente nel file IT ma non nel TLC (anagrafiche divergenti).
    assert "Fornitore 21 S.r.l." in {
        a.valore for a in anomalie(tlc, "CODICE_SAP_MANCANTE_NEL_FILE")
    }
    assert len(anomalie(tlc, "WBS_MANCANTE")) == 5


def test_valori_normalizzati(importati):
    bom = m.Contratto.objects.get(numero_contratto="5800593497")
    assert bom.cig == "B2HIBI36J2"
    rda = m.Contratto.objects.get(numero_contratto="7300456608")
    assert rda.numero_rda == "5100004438"
    assert rda.stati_pratica.get().stato == "rda_predisposta"
    assert m.Contratto.objects.get(numero_contratto="5800829771").numero_rda == "3563270716"
    voce = m.VoceContratto.objects.get(contratto__numero_contratto="SI002OA600")
    assert (voce.importo_fisso, voce.massimale_variabile) == (
        Decimal("17722.68"),
        Decimal("10303.89"),
    )
    assert voce.conto.codice == "627031"  # conto nuovo dal 01/01/26


def test_finanziati_e_dissalatori(importati):
    finanziati = m.Contratto.objects.filter(finanziamento="finanziato")
    assert finanziati.count() == 6  # 5 TLC finanziati + 1 dissalatori IT
    assert set(finanziati.values_list("progetto__codice_wbs", flat=True)) == {"WBS-DA-DEFINIRE"}
    assert m.Contratto.objects.filter(fornitore__ragione_sociale="(non indicato)").count() == 1


def test_proposte_generate(importati):
    proposta = m.PropostaRaggruppamento.objects.get(
        motivazione__startswith="Stessa descrizione e fornitore: Licenza software 01"
    )
    assert sorted(c.data_inizio.year for c in proposta.contratti.all()) == [2022, 2025, 2026]
    assert m.PropostaPredecessore.objects.filter(
        successore__numero_contratto="5800091127", predecessore__numero_contratto="OA1 197/22"
    ).exists()
    assert not m.Contratto.objects.exclude(predecessore=None).exists()  # niente di automatico


def test_reimport_delle_fixture_idempotente(importati):
    prima = (m.Contratto.objects.count(), m.PropostaRaggruppamento.objects.count())
    it = importa(IT, area="IT", oggi=OGGI)
    assert it.conteggi["contratti_creati"] == 0
    assert (m.Contratto.objects.count(), m.PropostaRaggruppamento.objects.count()) == prima


def test_comando_import_excel(piano_dei_conti, tmp_path, capsys):
    report = tmp_path / "anomalie.csv"
    call_command("import_excel", str(TLC), "--area", "TLC", "--dry-run", "--report", str(report))
    uscita = capsys.readouterr().out
    assert "DRY-RUN" in uscita and "DATA_MANCANTE: 1" in uscita
    assert not m.Contratto.objects.exists()
    testo = report.read_text(encoding="utf-8-sig")
    assert testo.splitlines()[0] == "file;foglio;riga;codice;campo;valore;messaggio"
    assert "MAPPATURA_CONTO" in testo
