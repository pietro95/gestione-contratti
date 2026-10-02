"""Costruttori minimi di oggetti di dominio per i test. Dati fittizi."""

import datetime
from decimal import Decimal

from contratti import models as m


def procedura(codice="affidamento_diretto"):
    return m.Procedura.objects.get(codice=codice)


def categoria(nome="Licenze software"):
    return m.Categoria.objects.get(nome=nome)


def fornitore(ragione_sociale="Fornitore Esempio S.r.l.", **kw):
    return m.Fornitore.objects.create(ragione_sociale=ragione_sociale, **kw)


def cluster(codice="IT"):
    return m.Cluster.objects.get_or_create(codice=codice, defaults={"nome": codice})[0]


def fabbisogno(descrizione="Licenze gestionale di prova", **kw):
    if "area" in kw:  # codice del cluster, come prima di F9.2
        kw["cluster"] = cluster(kw.pop("area"))
    kw.setdefault("cluster", cluster())
    kw.setdefault("categoria", categoria())
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
