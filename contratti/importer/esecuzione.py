"""Import dell'esecuzione dal modello XLSX dell'applicazione (SPEC §7, Rev11).

Un foglio per tipo, tutti facoltativi:
- ``RDA``: una riga per posizione; le righe con lo stesso numero RDA sono la stessa RDA;
- ``Documenti``: documenti di esecuzione (ODA/RDC, DDT, MIGO, MAP, attestazione, ricezione);
- ``Fatture``: fatture del fornitore.

Le righe si legano al contratto per numero di contratto SAP (o CIG) e alla RDA per numero SAP;
senza corrispondenza vanno nel report (``CONTRATTO_NON_TROVATO``, ``RDA_NON_TROVATA``).
Idempotente: RDA per numero, documenti per contratto, tipo, numero e data, fatture per
fornitore e numero. Una fattura per un contratto chiuso si scarta (``FATTURA_DOPO_CHIUSURA``).
"""

import datetime
import re
from decimal import Decimal
from pathlib import Path

import openpyxl
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from contratti import models as m
from contratti.importer import normalizza, tabelle
from contratti.importer.report import Report
from contratti.importer.riepilogo import data as leggi_data
from contratti.importer.tabelle import FileNonValido

Tipo = m.DocumentoEsecuzione.Tipo
TIPI = {
    "oda": Tipo.ODA, "rdc": Tipo.ODA, "oda/rdc": Tipo.ODA, "ddt": Tipo.DDT, "migo": Tipo.MIGO,
    "map": Tipo.MAP, "attestazione": Tipo.ATTESTAZIONE, "ricezione": Tipo.RICEZIONE,
    "modello di ricezione materiale": Tipo.RICEZIONE,
    "attestazione di regolare esecuzione": Tipo.ATTESTAZIONE,
}  # fmt: skip
SI = {"si", "sì", "s", "x", "1", "true", "vero"}

FOGLI = {
    "RDA": [
        "numero_rda", "cluster", "descrizione", "data_inserimento", "data_rilascio",
        "referente", "numero_contratto", "posizione", "quantita", "importo_unitario",
        "di_cui_variabile", "conto", "centro_costo", "wbs",
    ],
    "Documenti": [
        "numero_contratto", "tipo", "numero", "data", "importo", "finale", "numero_fattura",
    ],
    "Fatture": [
        "numero_contratto", "fornitore", "numero", "data", "importo_documento", "valore_base",
        "oneri", "bollo", "trasferita_il",
    ],
}  # fmt: skip
OBBLIGATORIE = {
    "RDA": {"numero_rda", "cluster", "descrizione", "posizione", "importo_unitario"},
    "Documenti": {"numero_contratto", "tipo", "data"},
    "Fatture": {"numero", "data", "importo_documento"},
}


class _Rollback(Exception):
    pass


def _testo(valore) -> str:
    return normalizza.testo(valore) or ""


def _importo(valore) -> Decimal | None:
    d, problemi = normalizza.importo(valore, "importo")
    return None if problemi else d


def leggi(percorso: Path) -> dict[str, list[dict]]:
    try:
        wb = openpyxl.load_workbook(percorso, read_only=True, data_only=True)
    except Exception as exc:
        raise FileNonValido(f"Il file non è un Excel leggibile ({exc}).") from exc
    nomi = {ws.title.strip().lower(): ws for ws in wb.worksheets}
    fogli = {}
    for nome in FOGLI:
        ws = nomi.get(nome.lower())
        if ws is None:
            continue
        righe = list(ws.iter_rows(values_only=True))
        if not righe:
            continue
        intestazione = [_testo(c).lower() for c in righe[0]]
        mancanti = OBBLIGATORIE[nome] - set(intestazione)
        if mancanti:
            raise FileNonValido(f"{nome}: colonne mancanti: {', '.join(sorted(mancanti))}.")
        fogli[nome] = [
            {"_riga": n, **dict(zip(intestazione, r, strict=False))}
            for n, r in enumerate(righe[1:], start=2)
            if any(v not in (None, "") for v in r)
        ]
    if not fogli:
        raise FileNonValido("Nessun foglio riconosciuto: servono «RDA», «Documenti» o «Fatture».")
    return fogli


class Importatore:
    def __init__(self, report: Report, oggi: datetime.date):
        self.report = report
        self.oggi = oggi

    def anomalia(self, foglio, riga, codice, campo="", valore="", messaggio=""):
        self.report.anomalia(foglio, riga, codice, campo, valore or "", messaggio)

    def contratto(self, foglio, r) -> m.Contratto | None:
        chiave = _testo(r.get("numero_contratto"))
        if not chiave:
            return None
        qs = m.Contratto.objects.filter(archiviato=False)
        c = qs.filter(numero_contratto=chiave).first() or qs.filter(cig=chiave.upper()).first()
        if c is None:
            self.anomalia(
                foglio,
                r["_riga"],
                "CONTRATTO_NON_TROVATO",
                "numero_contratto",
                chiave,
                "Nessun contratto con questo numero SAP o CIG.",
            )
        return c

    # --- RDA -------------------------------------------------------------------------------

    def rda(self, righe: list[dict]) -> None:
        gruppi: dict[str, list[dict]] = {}
        for r in righe:
            numero = re.sub(r"\D", "", _testo(r.get("numero_rda")))
            gruppi.setdefault(numero, []).append(r)
        utenti = get_user_model().objects
        for numero, gruppo in gruppi.items():
            primo = gruppo[0]
            n = primo["_riga"]
            if not re.fullmatch(r"51\d{8}", numero):
                self.anomalia(
                    "RDA",
                    n,
                    "NUMERO_RDA_NON_VALIDO",
                    "numero_rda",
                    _testo(primo.get("numero_rda")),
                    "10 cifre, inizia con 51.",
                )
                continue
            if m.RichiestaAcquisto.objects.filter(numero_rda=numero, archiviato=False).exists():
                self.report.conteggi["rda_gia_presenti"] += 1
                continue
            cluster = m.Cluster.objects.filter(codice=_testo(primo.get("cluster")).upper()).first()
            if cluster is None:
                self.anomalia(
                    "RDA",
                    n,
                    "CLUSTER_NON_TROVATO",
                    "cluster",
                    _testo(primo.get("cluster")),
                    "Cluster inesistente.",
                )
                continue
            referente = _testo(primo.get("referente"))
            utente = utenti.filter(username__iexact=referente).first() if referente else None
            rda = m.RichiestaAcquisto(
                origine=m.RichiestaAcquisto.Origine.IMPORT,
                cluster=cluster,
                descrizione=_testo(primo.get("descrizione"))[:250],
                numero_rda=numero,
                data_inserimento=leggi_data(primo.get("data_inserimento")),
                data_rilascio=leggi_data(primo.get("data_rilascio")),
                referente_utente=utente,
                referente="" if utente else referente[:150],
                note="Importata dal modello dell'esecuzione.",
            )
            rda._change_reason = "Import dell'esecuzione"
            rda.save()
            for i, r in enumerate(gruppo, start=1):
                self._posizione(rda, i, r)
            self.report.conteggi["rda_create"] += 1
            if (c := self.contratto("RDA", primo)) is not None:
                if c.rda_id is None:
                    c.rda = rda
                    c._change_reason = "RDA d'origine dall'import dell'esecuzione"
                    c.save(update_fields=["rda"])
                else:
                    self.anomalia(
                        "RDA",
                        n,
                        "CONTRATTO_GIA_COLLEGATO",
                        "numero_contratto",
                        c.numero_contratto or "",
                        "Ha già un'RDA d'origine.",
                    )

    def _posizione(self, rda, numero, r) -> bool:
        importo = _importo(r.get("importo_unitario"))
        if importo is None or importo < 0:
            self.anomalia(
                "RDA",
                r["_riga"],
                "IMPORTO_NON_LEGGIBILE",
                "importo_unitario",
                _testo(r.get("importo_unitario")),
                "Posizione non importata.",
            )
            return False
        conto = m.ContoCoge.objects.filter(codice=_testo(r.get("conto"))).last()
        wbs = m.WBS.objects.filter(codice_wbs=_testo(r.get("wbs"))).first()
        centro = _testo(r.get("centro_costo"))[:20]
        if tabelle.centro_costo_da_segnalare(centro):
            self.anomalia("RDA", r["_riga"], "CENTRO_COSTO_NON_IN_TABELLA", "centro_costo",
                          centro, tabelle.MESSAGGIO_CENTRO_COSTO)  # fmt: skip
        quantita = _importo(r.get("quantita")) or Decimal(1)
        m.PosizioneRDA.objects.create(
            rda=rda,
            numero=numero,
            descrizione_breve=(_testo(r.get("posizione")) or rda.descrizione)[:250],
            quantita=quantita if quantita > 0 else Decimal(1),
            importo_unitario=importo,
            di_cui_variabile=_importo(r.get("di_cui_variabile")) or Decimal(0),
            natura=m.Natura.CAPEX if wbs else m.Natura.OPEX,
            conto=conto,
            centro_costo=centro,
            wbs=wbs,
        )
        return True

    # --- Documenti -------------------------------------------------------------------------

    def documenti(self, righe: list[dict]) -> None:
        for r in righe:
            n = r["_riga"]
            tipo = TIPI.get(_testo(r.get("tipo")).lower())
            if tipo is None:
                self.anomalia(
                    "Documenti",
                    n,
                    "TIPO_NON_VALIDO",
                    "tipo",
                    _testo(r.get("tipo")),
                    "Tipi: ODA/RDC, DDT, MIGO, MAP, attestazione, ricezione.",
                )
                continue
            d = leggi_data(r.get("data"))
            if d is None:
                self.anomalia(
                    "Documenti",
                    n,
                    "DATA_NON_LEGGIBILE",
                    "data",
                    _testo(r.get("data")),
                    "Documento non importato.",
                )
                continue
            contratto = self.contratto("Documenti", r)
            if contratto is None:
                continue
            numero = _testo(r.get("numero"))[:40]
            if m.DocumentoEsecuzione.objects.filter(
                contratto=contratto, tipo=tipo, numero=numero, data=d, archiviato=False
            ).exists():
                self.report.conteggi["documenti_gia_presenti"] += 1
                continue
            fattura = None
            if numero_fattura := _testo(r.get("numero_fattura")):
                fattura = contratto.fatture.filter(numero=numero_fattura, archiviato=False).first()
                if fattura is None:
                    self.anomalia(
                        "Documenti",
                        n,
                        "FATTURA_NON_TROVATA",
                        "numero_fattura",
                        numero_fattura,
                        "Documento importato senza fattura.",
                    )
            finale = _testo(r.get("finale")).lower() in SI and tipo in (
                Tipo.ATTESTAZIONE,
                Tipo.RICEZIONE,
            )
            doc = m.DocumentoEsecuzione(
                contratto=contratto,
                tipo=tipo,
                numero=numero,
                data=d,
                importo=_importo(r.get("importo")),
                finale=finale,
                fattura=fattura,
            )
            doc._change_reason = "Import dell'esecuzione"
            doc.save()
            self.report.conteggi["documenti_creati"] += 1

    # --- Fatture ---------------------------------------------------------------------------

    def fatture(self, righe: list[dict]) -> None:
        for r in righe:
            n = r["_riga"]
            numero = _testo(r.get("numero"))[:60]
            d = leggi_data(r.get("data"))
            importo = _importo(r.get("importo_documento"))
            if not numero or d is None or importo is None or importo < 0:
                self.anomalia(
                    "Fatture",
                    n,
                    "RIGA_INCOMPLETA",
                    "numero",
                    numero,
                    "Numero, data o importo mancanti o illeggibili.",
                )
                continue
            contratto = self.contratto("Fatture", r)
            if contratto is None and _testo(r.get("numero_contratto")):
                continue
            fornitore = contratto.fornitore if contratto else None
            if fornitore is None:
                nome = normalizza.chiave_nome(_testo(r.get("fornitore")))
                fornitore = next(
                    (
                        f
                        for f in m.Fornitore.objects.filter(archiviato=False)
                        if nome
                        and nome
                        in (
                            normalizza.chiave_nome(f.ragione_sociale),
                            normalizza.chiave_nome(f.nome_breve),
                        )
                    ),
                    None,
                )
                if fornitore is None:
                    self.anomalia(
                        "Fatture",
                        n,
                        "FORNITORE_NON_TROVATO",
                        "fornitore",
                        _testo(r.get("fornitore")),
                        "Fattura non importata.",
                    )
                    continue
            if m.Fattura.objects.filter(
                fornitore=fornitore, numero=numero, archiviato=False
            ).exists():
                self.report.conteggi["fatture_gia_presenti"] += 1
                continue
            if contratto is not None and contratto.data_chiusura is not None:
                self.anomalia(
                    "Fatture",
                    n,
                    "FATTURA_DOPO_CHIUSURA",
                    "numero",
                    numero,
                    "Fattura per un contratto chiuso: scartata.",
                )
                continue
            fattura = m.Fattura(
                contratto=contratto,
                fornitore=fornitore,
                numero=numero,
                data=d,
                importo_documento=importo,
                valore_base=_importo(r.get("valore_base")),
                oneri=_importo(r.get("oneri")),
                bollo=_importo(r.get("bollo")),
                data_trasferimento=leggi_data(r.get("trasferita_il")),
                data_registrazione=self.oggi,
            )
            if contratto is not None:
                voci = list(contratto.voci.filter(archiviato=False))
                fattura.voce = voci[0] if len(voci) == 1 else None
            fattura._change_reason = "Import dell'esecuzione"
            fattura.save()
            self.report.conteggi["fatture_create"] += 1


def importa_esecuzione(
    percorso: str | Path, *, dry_run: bool = False, oggi: datetime.date | None = None
) -> Report:
    percorso = Path(percorso)
    report = Report(file=percorso.name, dry_run=dry_run)
    for chiave in (
        "rda_create",
        "rda_gia_presenti",
        "documenti_creati",
        "documenti_gia_presenti",
        "fatture_create",
        "fatture_gia_presenti",
    ):
        report.conteggi[chiave] = 0
    fogli = leggi(percorso)
    try:
        with transaction.atomic():
            imp = Importatore(report, oggi or timezone.localdate())
            # Prima le fatture: i documenti possono riferirsi a una fattura dello stesso file.
            if "RDA" in fogli:
                imp.rda(fogli["RDA"])
            if "Fatture" in fogli:
                imp.fatture(fogli["Fatture"])
            if "Documenti" in fogli:
                imp.documenti(fogli["Documenti"])
            if dry_run:
                raise _Rollback
    except _Rollback:
        pass
    return report
