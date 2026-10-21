"""Costruttori minimi di oggetti di dominio per i test. Dati fittizi."""

import datetime
from decimal import Decimal

from contratti import models as m


def procedura(codice="affidamento_diretto"):
    return m.Procedura.objects.get(codice=codice)


def sottocluster(nome="Licenze software", cluster_codice="IT"):
    return m.Sottocluster.objects.get_or_create(nome=nome, cluster=cluster(cluster_codice))[0]


def fornitore(ragione_sociale="Fornitore Esempio S.r.l.", **kw):
    return m.Fornitore.objects.create(ragione_sociale=ragione_sociale, **kw)


def cluster(codice="IT"):
    return m.Cluster.objects.get_or_create(codice=codice, defaults={"nome": codice})[0]


def fabbisogno(descrizione="Licenze gestionale di prova", **kw):
    if "area" in kw:  # codice del cluster, come prima di F9.2
        kw["cluster"] = cluster(kw.pop("area"))
    kw.setdefault("cluster", cluster())
    return m.Fabbisogno.objects.create(descrizione=descrizione, **kw)


def contratto(**kw):
    kw.setdefault("fabbisogno", fabbisogno())
    kw.setdefault("fornitore", fornitore())
    kw.setdefault("procedura", procedura())
    kw.setdefault("data_inizio", datetime.date(2026, 1, 1))
    kw.setdefault("durata_mesi", 12)
    return m.Contratto.objects.create(**kw)


def voce(contratto_=None, **kw):
    kw.setdefault("descrizione", "Canone")
    kw.setdefault("importo_fisso", Decimal("1000.00"))
    return m.VoceContratto.objects.create(contratto=contratto_ or contratto(), **kw)


def piano(voce_=None, **kw):
    kw.setdefault("modalita", m.ModalitaFatturazione.ANTICIPATA)
    kw.setdefault("periodicita", m.Periodicita.ANNUALE)
    return m.PianoFatturazione.objects.create(voce=voce_ or voce(), **kw)


def rata(piano_=None, **kw):
    kw.setdefault("numero", 1)
    kw.setdefault("data_fattura", datetime.date(2026, 1, 1))
    kw.setdefault("data_pagamento_stimata", datetime.date(2026, 3, 1))
    kw.setdefault("importo", Decimal("1000.00"))
    return m.Rata.objects.create(piano=piano_ or piano(), **kw)


def conto(codice, descrizione="Conto di prova", valido_dal=None, cluster=None, **kw):
    """Conto COGE di prova; ``cluster`` (uno o più) va sulla relazione ``clusters`` (Rev25)."""
    import datetime

    c = m.ContoCoge.objects.create(
        codice=codice,
        descrizione=descrizione,
        valido_dal=valido_dal or datetime.date(2020, 1, 1),
        **kw,
    )
    if cluster is not None:
        c.clusters.add(*(cluster if isinstance(cluster, list | tuple) else [cluster]))
    return c
