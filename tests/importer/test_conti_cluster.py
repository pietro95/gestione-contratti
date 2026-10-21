"""F9.2 chiusa: il cluster del conto nell'import del piano dei conti e dei contratti."""

import datetime

import pytest
from django.contrib import admin

from contratti import models as m
from contratti.importer import tabelle
from contratti.importer.carica import importa
from contratti.importer.conti import importa_conti

from .. import factories as f
from .conftest import IT, OGGI

pytestmark = pytest.mark.django_db
D = datetime.date


def _csv(tmp_path, righe):
    p = tmp_path / "conti.csv"
    p.write_text("codice;descrizione;valido_dal;valido_al;cluster\n" + "\n".join(righe) + "\n")
    return p


def test_import_conti_con_la_colonna_cluster(tmp_path):
    f.cluster("IT")
    importa_conti(_csv(tmp_path, ["60000001;Canoni (prova);01/01/2026;;IT"]))
    conto = m.ContoCoge.objects.get(codice="60000001")
    assert [c.codice for c in conto.clusters.all()] == ["IT"]
    # Colonna vuota: il cluster registrato resta; reimport invariato.
    r = importa_conti(_csv(tmp_path, ["60000001;Canoni (prova);01/01/2026;;"]))
    assert r.conteggi["invariati"] == 1
    assert [c.codice for c in conto.clusters.all()] == ["IT"]
    with pytest.raises(tabelle.FileNonValido, match="cluster inesistente: ZZ"):
        importa_conti(_csv(tmp_path, ["60000009;Altro (prova);01/01/2026;;ZZ"]))


def test_import_contratti_segnala_conto_senza_cluster():
    for codice in ("634935", "627020", "627021", "635220", "627029", "627030", "627031"):
        m.ContoCoge.objects.create(codice=codice, descrizione="x", valido_dal=D(2020, 1, 1))
    m.ContoCoge.objects.get(codice="634935").clusters.add(f.cluster("IT"))
    r = importa(IT, area="IT", oggi=OGGI, dry_run=True)
    codici = {a.codice for a in r.anomalie}
    assert "CONTO_SENZA_CLUSTER" in codici


def test_admin_conto_richiede_il_cluster():
    form = admin.site._registry[m.ContoCoge].form(
        data={"codice": "60000001", "descrizione": "x", "valido_dal": "2026-01-01"}
    )
    assert not form.is_valid() and "clusters" in form.errors


def test_import_conti_con_piu_cluster_e_modifica_dell_insieme(tmp_path):
    f.cluster("IT")
    f.cluster("TLC")
    importa_conti(_csv(tmp_path, ["60000001;Generico (prova);01/01/2026;;IT, TLC"]))
    conto = m.ContoCoge.objects.get(codice="60000001")
    assert {c.codice for c in conto.clusters.all()} == {"IT", "TLC"}
    r = importa_conti(_csv(tmp_path, ["60000001;Generico (prova);01/01/2026;;TLC/IT"]))
    assert r.conteggi["invariati"] == 1  # stesso insieme, ordine diverso: invariato
    importa_conti(_csv(tmp_path, ["60000001;Generico (prova);01/01/2026;;TLC"]))
    assert [c.codice for c in conto.clusters.all()] == ["TLC"]
