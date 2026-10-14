"""Processo d'acquisto: fase della RDA, stato della pratica, scheda SAP, esecuzione.

SPEC §5.7 (fase della RDA, stato della pratica ricavato, RDA e fatture ferme), §5.8
(fatturato, residuo, contratti da chiudere, anomalie), §5.9 (scheda SAP e testo della
richiesta). Casi: TC-15, TC-16, TC-17.

I fatti con una data successiva a ``oggi`` non contano: la fase è quella del giorno dato.
"""

import datetime
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from contratti.engine.importi import ZERO, arrotonda

# --- Fase della RDA (SPEC §5.7) ---------------------------------------------------------


class Fase(StrEnum):
    BOZZA = "bozza"
    INVIATA = "inviata"
    DA_CORREGGERE = "da_correggere"
    INSERITA = "inserita"
    RILASCIATA = "rilasciata"
    CONTRATTO_EMESSO = "contratto_emesso"
    IN_ESECUZIONE = "in_esecuzione"
    CHIUSA = "chiusa"
    ANNULLATA = "annullata"


ETICHETTE_FASE = {
    Fase.BOZZA: "Bozza",
    Fase.INVIATA: "Inviata",
    Fase.DA_CORREGGERE: "Da correggere",
    Fase.INSERITA: "Inserita",
    Fase.RILASCIATA: "Rilasciata",
    Fase.CONTRATTO_EMESSO: "Contratto emesso",
    Fase.IN_ESECUZIONE: "In esecuzione",
    Fase.CHIUSA: "Chiusa",
    Fase.ANNULLATA: "Annullata",
}


class TipoEvento(StrEnum):
    INVIO = "invio"
    RIMANDO = "rimando"
    ANNULLAMENTO = "annullamento"


@dataclass(frozen=True)
class EventoRDA:
    tipo: TipoEvento
    data: datetime.date


@dataclass(frozen=True)
class ContrattoGenerato:
    """Contratto nato dalla RDA, con le date che contano per la fase."""

    data_emissione: datetime.date | None = None
    data_inizio: datetime.date | None = None
    data_chiusura: datetime.date | None = None
    # Data del primo documento di esecuzione o della prima fattura, se ce ne sono.
    prima_esecuzione: datetime.date | None = None


@dataclass(frozen=True)
class DatiRDA:
    data_creazione: datetime.date
    numero: str | None = None
    data_inserimento: datetime.date | None = None
    data_rilascio: datetime.date | None = None
    eventi: tuple[EventoRDA, ...] = ()  # in ordine di registrazione
    contratti: tuple[ContrattoGenerato, ...] = ()


def _entro(data: datetime.date | None, oggi: datetime.date) -> bool:
    return data is None or data <= oggi


def _ultimo_evento(d: DatiRDA, oggi: datetime.date) -> EventoRDA | None:
    validi = [e for e in d.eventi if e.data <= oggi]
    return validi[-1] if validi else None


def _contratti(d: DatiRDA, oggi: datetime.date) -> list[ContrattoGenerato]:
    return [c for c in d.contratti if _entro(c.data_emissione, oggi)]


def _chiuso(c: ContrattoGenerato, oggi: datetime.date) -> bool:
    return c.data_chiusura is not None and c.data_chiusura <= oggi


def _in_esecuzione(c: ContrattoGenerato, oggi: datetime.date) -> bool:
    return c.prima_esecuzione is not None and c.prima_esecuzione <= oggi


def fase(d: DatiRDA, oggi: datetime.date) -> Fase:
    """Prima regola che si applica, dall'alto (SPEC §5.7)."""
    ultimo = _ultimo_evento(d, oggi)
    contratti = _contratti(d, oggi)
    if ultimo is not None and ultimo.tipo == TipoEvento.ANNULLAMENTO:
        return Fase.ANNULLATA
    if contratti and all(_chiuso(c, oggi) for c in contratti):
        return Fase.CHIUSA
    if any(_in_esecuzione(c, oggi) for c in contratti):
        return Fase.IN_ESECUZIONE
    if contratti:
        return Fase.CONTRATTO_EMESSO
    if d.data_rilascio is not None and d.data_rilascio <= oggi:
        return Fase.RILASCIATA
    if d.numero and _entro(d.data_inserimento, oggi):
        return Fase.INSERITA
    if ultimo is not None and ultimo.tipo == TipoEvento.RIMANDO:
        return Fase.DA_CORREGGERE
    if ultimo is not None and ultimo.tipo == TipoEvento.INVIO:
        return Fase.INVIATA
    return Fase.BOZZA


def _minima(date: Iterable[datetime.date | None]) -> datetime.date | None:
    presenti = [x for x in date if x is not None]
    return min(presenti) if presenti else None


def data_fase(d: DatiRDA, oggi: datetime.date) -> datetime.date | None:
    """Data del fatto che ha portato la RDA nella fase in cui è."""
    f = fase(d, oggi)
    contratti = _contratti(d, oggi)
    if f in (Fase.ANNULLATA, Fase.DA_CORREGGERE, Fase.INVIATA):
        return _ultimo_evento(d, oggi).data
    if f == Fase.CHIUSA:
        return max(c.data_chiusura for c in contratti)
    if f == Fase.IN_ESECUZIONE:
        return _minima(c.prima_esecuzione for c in contratti if _in_esecuzione(c, oggi))
    if f == Fase.CONTRATTO_EMESSO:
        return _minima(c.data_emissione for c in contratti)
    if f == Fase.RILASCIATA:
        return d.data_rilascio
    if f == Fase.INSERITA:
        return d.data_inserimento
    return d.data_creazione


# --- Stato della pratica ricavato (SPEC §4, §5.7) --------------------------------------

# Ordine del workflow della pratica: vale il più avanzato tra passaggi e RDA.
ORDINE_PRATICA = (
    "non_avviata",
    "offerta_richiesta",
    "offerta_ricevuta",
    "rda_richiesta",
    "rda_predisposta",
    "rda_approvata",
    "contratto_emesso",
    "contratto_attivo",
)

StatoPratica = tuple[str, datetime.date | None]


def _posizione(stato: StatoPratica | None) -> int:
    return -1 if stato is None else ORDINE_PRATICA.index(stato[0])


def stato_da_rda(d: DatiRDA, oggi: datetime.date) -> StatoPratica | None:
    """Stato della pratica che una RDA determina; ``None`` se non conta (bozza, ecc.)."""
    f = fase(d, oggi)
    if f == Fase.INVIATA:
        return ("rda_richiesta", data_fase(d, oggi))
    if f == Fase.INSERITA:
        return ("rda_predisposta", data_fase(d, oggi))
    if f == Fase.RILASCIATA:
        return ("rda_approvata", data_fase(d, oggi))
    if f in (Fase.CONTRATTO_EMESSO, Fase.IN_ESECUZIONE, Fase.CHIUSA):
        contratti = _contratti(d, oggi)
        iniziati = [c.data_inizio for c in contratti if c.data_inizio and c.data_inizio <= oggi]
        if iniziati:
            return ("contratto_attivo", min(iniziati))
        return ("contratto_emesso", _minima(c.data_emissione for c in contratti))
    return None


def stato_pratica(
    ultimo_passaggio: StatoPratica | None, rda: Sequence[DatiRDA], oggi: datetime.date
) -> StatoPratica | None:
    """Il più avanzato tra l'ultimo passaggio registrato e gli stati delle RDA (TC-15).

    ``rda``: le RDA collegate alla pratica (quelle di acquisto aggiuntivo non ci sono).
    ``None`` = nessun passaggio e nessuna RDA che conti: la pratica è «Non avviata».
    """
    migliore = ultimo_passaggio
    for d in rda:
        stato = stato_da_rda(d, oggi)
        if _posizione(stato) > _posizione(migliore):
            migliore = stato
    return migliore


# --- Cruscotti: chi deve agire, RDA e fatture ferme (SPEC §5.7) -------------------------


class Azione(StrEnum):
    DA_INSERIRE = "da_inserire"
    SOLLECITO_RILASCIO = "sollecito_rilascio"
    SOLLECITO_PROCUREMENT = "sollecito_procurement"


AZIONE_ADDETTO = {
    Fase.INVIATA: Azione.DA_INSERIRE,
    Fase.INSERITA: Azione.SOLLECITO_RILASCIO,
    Fase.RILASCIATA: Azione.SOLLECITO_PROCUREMENT,
}
FASI_REFERENTE = frozenset({Fase.BOZZA, Fase.DA_CORREGGERE})


def azione_addetto(f: Fase) -> Azione | None:
    """Cosa deve fare l'addetto amministrativo per una RDA in questa fase."""
    return AZIONE_ADDETTO.get(f)


def attende_referente(f: Fase) -> bool:
    return f in FASI_REFERENTE


def rda_ferma(d: DatiRDA, oggi: datetime.date, giorni: int) -> bool:
    """In una fase dell'addetto da più dei giorni del parametro."""
    if azione_addetto(fase(d, oggi)) is None:
        return False
    inizio = data_fase(d, oggi)
    return inizio is not None and (oggi - inizio).days > giorni


# Lavorazione della fattura (Rev14, Rev15): presa in carico → assegnazione al contratto →
# convalida del referente → RdC → MAP o MIGO → trasferimento per il pagamento.
class PassoFattura(StrEnum):
    PRESA_IN_CARICO = "presa_in_carico"
    ASSEGNAZIONE = "assegnazione"
    CONVALIDA = "convalida"
    BLOCCATA = "bloccata"
    RDC = "rdc"
    MAP_MIGO = "map_migo"
    TRASFERIMENTO = "trasferimento"


ETICHETTE_PASSO = {
    PassoFattura.PRESA_IN_CARICO: "Da prendere in carico",
    PassoFattura.ASSEGNAZIONE: "Da assegnare",
    PassoFattura.CONVALIDA: "Da convalidare",
    PassoFattura.BLOCCATA: "Bloccata",
    PassoFattura.RDC: "RdC da fare",
    PassoFattura.MAP_MIGO: "MAP/MIGO da fare",
    PassoFattura.TRASFERIMENTO: "Da trasferire",
}
TIPI_ACCETTAZIONE = frozenset({"MAP", "MIGO"})
CONVALIDABILE = "convalidabile"


@dataclass(frozen=True)
class LavorazioneFattura:
    """Fatti della fattura prima dei documenti SAP (Rev15).

    I default descrivono una fattura già presa in carico, assegnata e convalidata (TC-15 e).
    """

    in_carico_dal: datetime.date | None = datetime.date.min
    assegnata: bool = True
    esito: str = CONVALIDABILE
    convalidata_il: datetime.date | None = datetime.date.min
    bloccata_fino_al: datetime.date | None = None
    fuori_registro: bool = False


GIA_CONVALIDATA = LavorazioneFattura()


def convalidata(lav: LavorazioneFattura, oggi: datetime.date) -> bool:
    """Esito «Convalidabile» registrato entro oggi e nessun blocco ancora in corso."""
    if lav.esito != CONVALIDABILE:
        return False
    if lav.convalidata_il is not None and lav.convalidata_il > oggi:
        return False
    return lav.bloccata_fino_al is None or lav.bloccata_fino_al < oggi


def bloccata(lav: LavorazioneFattura, oggi: datetime.date) -> bool:
    """Stanziata e bloccata, qualunque sia l'esito: il blocco dura fino alla data indicata
    inclusa. Fino ad allora la fattura è «Bloccata», non «Da convalidare»."""
    return lav.bloccata_fino_al is not None and lav.bloccata_fino_al >= oggi


def passo_fattura(
    documenti: Iterable[tuple[str, datetime.date]],
    oggi: datetime.date,
    trasferita: datetime.date | None = None,
    lavorazione: LavorazioneFattura = GIA_CONVALIDATA,
) -> PassoFattura | None:
    """Il primo passo che manca, nell'ordine; ``None`` se la fattura è trasferita (TC-15 e,
    TC-18)."""
    if trasferita is not None and trasferita <= oggi:
        return None
    if lavorazione.in_carico_dal is None or lavorazione.in_carico_dal > oggi:
        return PassoFattura.PRESA_IN_CARICO
    if not lavorazione.assegnata:
        return PassoFattura.ASSEGNAZIONE
    if bloccata(lavorazione, oggi):
        return PassoFattura.BLOCCATA
    if not convalidata(lavorazione, oggi):
        return PassoFattura.CONVALIDA
    tipi = {tipo for tipo, data in documenti if data <= oggi}
    if "ODA_RDC" not in tipi:
        return PassoFattura.RDC
    if not tipi & TIPI_ACCETTAZIONE:
        return PassoFattura.MAP_MIGO
    return PassoFattura.TRASFERIMENTO


def fattura_da_lavorare(
    documenti: Iterable[tuple[str, datetime.date]],
    oggi: datetime.date,
    trasferita: datetime.date | None = None,
    lavorazione: LavorazioneFattura = GIA_CONVALIDATA,
) -> bool:
    """Da lavorare finché non è trasferita, salvo se fuori registro (Rev15)."""
    if lavorazione.fuori_registro:
        return False
    return passo_fattura(documenti, oggi, trasferita, lavorazione) is not None


def fattura_ferma(
    registrata: datetime.date,
    documenti: Iterable[tuple[str, datetime.date]],
    oggi: datetime.date,
    giorni: int,
    trasferita: datetime.date | None = None,
    lavorazione: LavorazioneFattura = GIA_CONVALIDATA,
) -> bool:
    # Una fattura bloccata aspetta la data del blocco: non è ferma.
    return (
        fattura_da_lavorare(documenti, oggi, trasferita, lavorazione)
        and not bloccata(lavorazione, oggi)
        and (oggi - registrata).days > giorni
    )


def primo_referente(candidati: Iterable[object | None]) -> object | None:
    """Referente proposto (Rev15): il primo candidato presente, nell'ordine della SPEC §4
    (ultima fattura del contratto, referente del fabbisogno, referente della RDA d'origine,
    ultima fattura del fornitore)."""
    return next((c for c in candidati if c is not None), None)


def importo_quadra(
    importo_documento: Decimal,
    valore_base: Decimal | None,
    oneri: Decimal | None,
    bollo: Decimal | None,
    iva: Decimal | None = None,
) -> bool:
    """Valore base + oneri + bollo + IVA = importo del documento; senza valore base non si
    giudica. L'IVA c'è quando SAP riporta l'importo con l'IVA."""
    if valore_base is None:
        return True
    return valore_base + (oneri or ZERO) + (bollo or ZERO) + (iva or ZERO) == importo_documento


def valore_base_proposto(
    importo_documento: Decimal, oneri: Decimal | None, bollo: Decimal | None
) -> Decimal:
    """Proposta: importo del documento meno oneri e bollo (SPEC §4)."""
    return arrotonda(importo_documento - (oneri or ZERO) - (bollo or ZERO))


TOLLERANZA_IVA = Decimal("0.01")  # l'IVA della fattura può differire di un arrotondamento


def iva_riconosciuta(
    importo_documento: Decimal,
    valore_base: Decimal | None,
    oneri: Decimal | None,
    bollo: Decimal | None,
    aliquote: list[Decimal],
) -> tuple[Decimal, Decimal] | None:
    """(aliquota, IVA) se la differenza tra l'importo del documento e valore base + oneri +
    bollo è l'IVA di una delle aliquote su valore base + oneri, a meno di un centesimo.
    L'IVA restituita è la differenza esatta, così l'importo quadra."""
    if valore_base is None:
        return None
    imponibile = valore_base + (oneri or ZERO)
    differenza = importo_documento - imponibile - (bollo or ZERO)
    if differenza <= ZERO:
        return None
    for aliquota in sorted(aliquote, reverse=True):
        if abs(differenza - arrotonda(imponibile * aliquota / 100)) <= TOLLERANZA_IVA:
            return aliquota, differenza
    return None


def scorporo_iva(
    importo_documento: Decimal, oneri: Decimal | None, bollo: Decimal | None, aliquota: Decimal
) -> tuple[Decimal, Decimal]:
    """(valore base, IVA) di un importo con l'IVA: imponibile = (importo − bollo) / (1 +
    aliquota), arrotondato al centesimo; IVA = il resto, così l'importo quadra."""
    lordo = importo_documento - (bollo or ZERO)
    imponibile = arrotonda(lordo * 100 / (100 + aliquota))
    return imponibile - (oneri or ZERO), lordo - imponibile


def documento_accettazione(tipo_acquisto: str) -> str:
    """MAP per i servizi, MIGO per le forniture (Rev14)."""
    return "MIGO" if tipo_acquisto == "fornitura" else "MAP"


# --- Esecuzione, residuo, contratti da chiudere (SPEC §5.8) -----------------------------


class Documento(StrEnum):
    ODA = "ODA_RDC"
    DDT = "DDT"
    MIGO = "MIGO"
    MAP = "MAP"
    ATTESTAZIONE = "ATTESTAZIONE"
    RICEZIONE = "RICEZIONE"


# Documenti che, se finali, attestano la prestazione.
TIPI_ATTESTAZIONE = frozenset({Documento.ATTESTAZIONE, Documento.RICEZIONE})


@dataclass(frozen=True)
class DocumentoEseguito:
    tipo: str
    data: datetime.date
    finale: bool = False


@dataclass(frozen=True)
class FatturaRegistrata:
    """Fattura assegnata al contratto: conta il valore base (Rev15), non l'importo del
    documento; senza valore base non conta ed è segnalata."""

    data: datetime.date
    valore_base: Decimal | None
    numero: str = ""
    fornitore: object = None


@dataclass(frozen=True)
class Esecuzione:
    fatturato: Decimal
    residuo_fisso: Decimal
    residuo_massimo: Decimal
    avanzamento_pct: int | None


def _percentuale(parte: Decimal, totale: Decimal) -> int:
    return int((parte * 100 / totale).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _fatturato(fatture: Iterable[FatturaRegistrata]) -> Decimal:
    return sum((f.valore_base for f in fatture if f.valore_base is not None), ZERO)


def esecuzione(
    fisso: Decimal,
    massimale: Decimal,
    fatture: Iterable[FatturaRegistrata],
    oggi: datetime.date,
) -> Esecuzione:
    """Fatturato, residui e avanzamento (fisso e massimale delle voci, proroghe comprese)."""
    fatturato = _fatturato(f for f in fatture if f.data <= oggi)
    if fisso > 0:
        avanzamento = _percentuale(fatturato, fisso)
    elif massimale > 0:
        avanzamento = _percentuale(fatturato, massimale)
    else:
        avanzamento = None
    return Esecuzione(
        fatturato=arrotonda(fatturato),
        residuo_fisso=arrotonda(fisso - fatturato),
        residuo_massimo=arrotonda(fisso + massimale - fatturato),
        avanzamento_pct=avanzamento,
    )


class MotivoChiusura(StrEnum):
    ATTESTAZIONE_MANCANTE = "attestazione_mancante"
    FATTURE_MANCANTI = "fatture_mancanti"
    PRONTO = "pronto_da_chiudere"


ETICHETTE_MOTIVO = {
    MotivoChiusura.ATTESTAZIONE_MANCANTE: "Attestazione mancante",
    MotivoChiusura.FATTURE_MANCANTI: "Fatture mancanti",
    MotivoChiusura.PRONTO: "Pronto da chiudere",
}


def attestato(documenti: Iterable[DocumentoEseguito], oggi: datetime.date) -> bool:
    return any(d.tipo in TIPI_ATTESTAZIONE and d.finale and d.data <= oggi for d in documenti)


def motivo_da_chiudere(
    fine: datetime.date | None,
    data_chiusura: datetime.date | None,
    documenti: Sequence[DocumentoEseguito],
    residuo_fisso: Decimal,
    oggi: datetime.date,
) -> MotivoChiusura | None:
    """Contratto non chiuso con la prestazione finita: perché non è ancora chiuso."""
    if fine is None or fine >= oggi:
        return None
    if data_chiusura is not None and data_chiusura <= oggi:
        return None
    if not attestato(documenti, oggi):
        return MotivoChiusura.ATTESTAZIONE_MANCANTE
    if residuo_fisso > 0:
        return MotivoChiusura.FATTURE_MANCANTI
    return MotivoChiusura.PRONTO


def anomalie_esecuzione(
    fisso: Decimal,
    massimale: Decimal,
    fatture: Sequence[FatturaRegistrata],
    documenti: Sequence[DocumentoEseguito],
    data_chiusura: datetime.date | None,
    oggi: datetime.date,
) -> list[str]:
    """Codici di SPEC §5.8 (``FATTURA_DOPO_CHIUSURA`` è dell'import)."""
    codici = []
    valide = [f for f in fatture if f.data <= oggi]
    if _fatturato(valide) > fisso + massimale:
        codici.append("FATTURATO_OLTRE_MASSIMO")
    if any(f.valore_base is None for f in valide):
        codici.append("VALORE_BASE_MANCANTE")
    if data_chiusura is not None and data_chiusura <= oggi and not attestato(documenti, oggi):
        codici.append("CHIUSO_SENZA_ATTESTAZIONE")
    chiavi = [(f.fornitore, f.numero.strip().upper()) for f in valide if f.numero.strip()]
    if len(chiavi) != len(set(chiavi)):
        codici.append("FATTURA_DUPLICATA")
    return codici


# --- Scheda SAP e testo della richiesta (SPEC §5.9) -------------------------------------


def importo_posizione(quantita: Decimal, importo_unitario: Decimal) -> Decimal:
    """Quantità × importo unitario, ``ROUND_HALF_UP`` al centesimo (TC-17)."""
    return arrotonda(Decimal(quantita) * Decimal(importo_unitario))


# Intestazione e descrizione breve delle posizioni: in SAP al massimo 40 caratteri.
LUNGHEZZA_TESTO_SAP = 40


def taglia_sap(testo: str) -> str:
    """Testo proposto per un campo SAP da 40 caratteri: tagliato, senza spazi in coda."""
    return (testo or "").strip()[:LUNGHEZZA_TESTO_SAP].rstrip()


def oltre_limite_sap(testo: str | None) -> bool:
    return len(testo or "") > LUNGHEZZA_TESTO_SAP


def intestazione(fornitore: str | None, descrizione: str) -> str:
    """«Nome breve del fornitore - descrizione»; senza fornitore la sola descrizione."""
    descrizione = descrizione.strip()
    fornitore = (fornitore or "").strip()
    return f"{fornitore} - {descrizione}" if fornitore else descrizione


def _pulisci(testo: str) -> str:
    senza_accenti = "".join(
        c for c in unicodedata.normalize("NFKD", testo) if not unicodedata.combining(c)
    )
    sostituito = re.sub(r"[^A-Za-z0-9_-]", "_", senza_accenti)
    return re.sub(r"_+", "_", sostituito).strip("_")


def nome_cartella(data: datetime.date, fornitore: str | None, descrizione: str) -> str:
    """``AAAA_MM_GG_<Fornitore>_<Descrizione>`` con i caratteri ripuliti (TC-17)."""
    parti = [f"{data:%Y_%m_%d}", fornitore or "", descrizione]
    return _pulisci("_".join(p for p in parti if p))


def percorso_cartella(
    base: str, data: datetime.date, fornitore: str | None, descrizione: str
) -> str:
    """Cartella base del cluster / anno / nome della cartella; vuoto senza cartella base."""
    base = base.strip()
    if not base:
        return ""
    separatore = "\\" if "\\" in base and "/" not in base else "/"
    return separatore.join(
        [base.rstrip("/\\"), str(data.year), nome_cartella(data, fornitore, descrizione)]
    )


def formato_euro(valore: Decimal) -> str:
    """1348.98 → «1.348,98 €»."""
    testo = f"{arrotonda(Decimal(valore)):,.2f}"
    return testo.replace(",", "§").replace(".", ",").replace("§", ".") + " €"


def formato_numero(valore: Decimal) -> str:
    """1504.17 → «1.504,17» (senza simbolo)."""
    return formato_euro(valore).removesuffix(" €")


def formato_quantita(valore: Decimal) -> str:
    """2.000 → «2», 2.500 → «2,5»."""
    testo = format(Decimal(valore).normalize(), "f")
    if "." in testo:
        testo = testo.rstrip("0").rstrip(".")
    return testo.replace(".", ",")


@dataclass(frozen=True)
class PosizioneScheda:
    descrizione_breve: str
    gruppo_merci: str
    quantita: Decimal
    importo_unitario: Decimal
    wbs: str = ""
    conto: str = ""
    centro_costo: str = ""
    di_cui_variabile: Decimal = ZERO

    @property
    def importo(self) -> Decimal:
        return importo_posizione(self.quantita, self.importo_unitario)


@dataclass(frozen=True)
class SchedaRDA:
    intestazione: str
    posizioni: tuple[PosizioneScheda, ...]
    richiedente: str
    gruppo_acquisti: str
    note_buyer: str = ""
    allegati: str = ""
    percorso: str = ""

    @property
    def importo_totale(self) -> Decimal:
        return sum((p.importo for p in self.posizioni), ZERO)


def componi_testo_richiesta(s: SchedaRDA) -> str:
    """Il testo della mail usata finora, con gli stessi campi (TC-17)."""
    righe = ["Si deve predisporre la seguente RDA.", ""]
    righe += [f"(Campo SAP) Intestazione: {s.intestazione}", ""]
    for n, p in enumerate(s.posizioni, start=1):
        righe += [
            f"(Campo SAP) Descrizione breve {n}: {p.descrizione_breve}",
            f"(Campo SAP) Gruppo merci {n}: {p.gruppo_merci}",
            f"(Campo SAP) Quantità {n}: {formato_quantita(p.quantita)}",
            f"(Campo SAP) Importo unitario {n}: {formato_euro(p.importo_unitario)}",
            f"(Campo informativo) Codice WBS {n}: {p.wbs or '--'}",
            f"(Campo informativo) Codice conto {n}: {p.conto or '--'}",
            f"(Campo informativo) Centro di costo {n}: {p.centro_costo or '--'}",
            "",
        ]
    righe += [
        f"(Campo SAP) Richiedente: {s.richiedente}",
        f"(Campo SAP) Gruppo Acquisti: {s.gruppo_acquisti}",
        "",
    ]
    if s.note_buyer.strip():
        righe += [f"(Campo SAP) (Opzionale) Note al buyer: {s.note_buyer.strip()}", ""]
    if s.allegati.strip():
        righe += [f"(Campo SAP) Allegati: {s.allegati.strip()}", ""]
    righe.append(f"(Campo informativo) Importo totale: {formato_euro(s.importo_totale)}")
    if s.percorso:
        righe.append(f"(Campo informativo) File server: {s.percorso}")
    return "\n".join(righe) + "\n"


# --- Indicazioni per la validazione e commento per PAC (SPEC §5.9, Rev15) ---------------

DA_REGISTRARE = "(da registrare)"
NESSUNO = "--"


@dataclass(frozen=True)
class DatiPAC:
    numero_rdc: str | None
    accettazione: str  # «MAP» o «MIGO»
    numero_accettazione: str | None
    centro_costo: str | None
    conto: str | None
    wbs: str | None
    valore_base: Decimal | None
    oneri: Decimal | None = None
    bollo: Decimal | None = None


def _euro(valore: Decimal | None) -> str:
    return DA_REGISTRARE if valore is None else "€ " + formato_numero(valore)


def indicazioni_validazione(d: DatiPAC) -> str:
    """«Valore base da prelevare € …. COGE: …, CDC: …, WBS: …» (TC-18)."""
    return (
        f"Valore base da prelevare {_euro(d.valore_base)}. "
        f"COGE: {d.conto or NESSUNO}, CDC: {d.centro_costo or NESSUNO}, WBS: {d.wbs or NESSUNO}"
    )


def commento_pac(d: DatiPAC) -> str:
    """Il commento per PAC nel formato usato finora (TC-18)."""
    righe = [
        f"ODA : {d.numero_rdc or DA_REGISTRARE}",
        f"{d.accettazione}: {d.numero_accettazione or DA_REGISTRARE}",
        f"CDC: {d.centro_costo or NESSUNO}",
        f"COGE: {d.conto or NESSUNO}",
        f"WBS: {d.wbs or NESSUNO}",
        "",
        f"Valore base prelevato da contratto: {_euro(d.valore_base)}",
    ]
    if d.oneri:
        righe.append(f"Oneri previdenziali: {_euro(d.oneri)}")
    if d.bollo:
        righe.append(f"Bollo: {_euro(d.bollo)}")
    return "\n".join(righe)
