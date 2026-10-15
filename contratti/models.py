"""Modello dati del registro (SPEC §4).

Regole:
- importi in ``Decimal`` (max_digits=14, decimal_places=2), mai ``float``;
- date ``date``, estremi inclusi;
- i valori derivati (data di fine, data limite, alert, contratti previsti) non si salvano:
  li calcola il motore in ``contratti/engine/`` (F2). Si salvano solo i dati decisi,
  compresi gli override e le rate dello scadenzario;
- nessuna cancellazione fisica: si archivia (``archiviato``); la storia delle modifiche
  passa da django-simple-history.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.utils import timezone
from simple_history.models import HistoricalRecords

from contratti.engine.acquisti import importo_posizione


def importo(verbose_name, **kwargs):
    return models.DecimalField(verbose_name, max_digits=14, decimal_places=2, **kwargs)


class HttpsURLField(models.URLField):
    """Link senza schema interpretati come https (default di Django 6.0)."""

    def formfield(self, **kwargs):
        kwargs.setdefault("assume_scheme", "https")
        return super().formfield(**kwargs)


def percentuale(verbose_name, **kwargs):
    return models.DecimalField(verbose_name, max_digits=5, decimal_places=2, **kwargs)


class Archiviabile(models.Model):
    """Al posto della cancellazione fisica."""

    archiviato = models.BooleanField(default=False, db_index=True)

    class Meta:
        abstract = True


class ConfigurazioneProvvisoria(models.Model):
    """Parametri con valori iniziali da concordare (SPEC §9)."""

    provvisorio = models.BooleanField(
        default=True, help_text="Valore iniziale da confermare con Procurement."
    )
    note = models.TextField(blank=True)

    class Meta:
        abstract = True


# ---------------------------------------------------------------------------
# Tabelle di configurazione
# ---------------------------------------------------------------------------


class Procedura(ConfigurazioneProvvisoria):
    """Procedura di affidamento con il suo lead time (SPEC §5.1)."""

    codice = models.SlugField(max_length=40, unique=True)
    nome = models.CharField(max_length=100, unique=True)
    lead_time_mesi = models.PositiveSmallIntegerField("lead time (mesi)")
    ordine = models.PositiveSmallIntegerField(default=0)
    attiva = models.BooleanField(default=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "procedura di affidamento"
        verbose_name_plural = "procedure di affidamento"
        ordering = ["ordine", "nome"]

    def __str__(self):
        return self.nome


class Soglia(ConfigurazioneProvvisoria):
    """Soglia d'importo con validità temporale (SPEC §5.4)."""

    codice = models.SlugField(max_length=60)
    descrizione = models.CharField(max_length=200)
    importo = importo("importo")
    valida_dal = models.DateField()
    valida_al = models.DateField(null=True, blank=True)
    riferimento_normativo = models.CharField(max_length=200, blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "soglia"
        verbose_name_plural = "soglie"
        ordering = ["codice", "-valida_dal"]
        constraints = [
            models.UniqueConstraint(
                fields=["codice", "valida_dal"], name="contratti_soglia_codice_dal_unica"
            ),
            models.CheckConstraint(
                condition=Q(importo__gte=0), name="contratti_soglia_importo_non_negativo"
            ),
            models.CheckConstraint(
                condition=Q(valida_al__isnull=True) | Q(valida_al__gte=F("valida_dal")),
                name="contratti_soglia_validita_coerente",
            ),
        ]

    def __str__(self):
        return f"{self.descrizione} (dal {self.valida_dal:%d/%m/%Y})"


class AliquotaIVA(ConfigurazioneProvvisoria):
    """Aliquote IVA riconosciute nell'importo delle fatture (scorporo e quadratura)."""

    aliquota = percentuale("aliquota (%)", unique=True)
    descrizione = models.CharField(max_length=100, blank=True)
    attiva = models.BooleanField(default=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "aliquota IVA"
        verbose_name_plural = "aliquote IVA"
        ordering = ["-aliquota"]
        constraints = [
            models.CheckConstraint(
                condition=Q(aliquota__gt=0) & Q(aliquota__lt=100),
                name="contratti_aliquotaiva_tra_0_e_100",
            ),
        ]

    def __str__(self):
        return f"{self.aliquota.normalize():f}%"


class Parametro(ConfigurazioneProvvisoria):
    """Parametro numerico con validità temporale (giorni di pagamento, adeguamento dei previsti)."""

    class Chiave(models.TextChoices):
        GIORNI_PAGAMENTO = "giorni_pagamento", "giorni di pagamento di default"
        PAGAMENTO_FINE_MESE = "pagamento_fine_mese", "pagamento a fine mese (1 = sì)"
        ADEGUAMENTO_PCT = "adeguamento_pct", "adeguamento dei rinnovi previsti (%)"
        FINESTRA_ALERT_MESI = "finestra_alert_mesi", "finestra dell'alert giallo (mesi)"
        ORIZZONTE_ANNI = "orizzonte_anni", "orizzonte della previsione rinnovi (anni)"
        # Connettore MCP (SPEC_MCP §4.4, §6).
        MCP_GIORNI_LOGIN = "mcp_giorni_login", "connettore MCP: giorni dall'ultimo login (D3)"
        MCP_RICHIESTE_MINUTO = (
            "mcp_richieste_minuto",
            "connettore MCP: richieste al minuto per collegamento",
        )
        # Scrittura dal connettore (SPEC_MCP §8.1, F10.1).
        MCP_SCRITTURA_ATTIVA = (
            "mcp_scrittura_attiva",
            "connettore MCP: scrittura attiva (1 = sì, 0 = spenta)",
        )
        MCP_MINUTI_OPERAZIONE = (
            "mcp_minuti_operazione",
            "connettore MCP: validità dell'anteprima da confermare (minuti)",
        )
        # Processo d'acquisto (SPEC §5.7, F11).
        RDA_FERMA_GIORNI = "rda_ferma_giorni", "RDA ferma in una fase dell'addetto (giorni)"
        FATTURA_FERMA_GIORNI = "fattura_ferma_giorni", "fattura ferma da lavorare (giorni)"

    chiave = models.CharField(max_length=40, choices=Chiave.choices)
    valore = models.DecimalField(max_digits=10, decimal_places=4)
    valido_dal = models.DateField()
    history = HistoricalRecords()

    class Meta:
        verbose_name = "parametro"
        verbose_name_plural = "parametri"
        ordering = ["chiave", "-valido_dal"]
        constraints = [
            models.UniqueConstraint(
                fields=["chiave", "valido_dal"], name="contratti_parametro_chiave_dal_unico"
            ),
            models.CheckConstraint(
                condition=Q(valore__gte=0), name="contratti_parametro_non_negativo"
            ),
        ]

    def __str__(self):
        return f"{self.get_chiave_display()} = {self.valore} (dal {self.valido_dal:%d/%m/%Y})"


class Categoria(models.Model):
    nome = models.CharField(max_length=100, unique=True)
    attiva = models.BooleanField(default=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "categoria"
        verbose_name_plural = "categorie"
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class FonteFinanziamento(models.Model):
    """Fonte di finanziamento di una spesa (tabella di configurazione, SPEC §5.4).

    Si assegna al fabbisogno o alla WBS; il piano ordini la riporta sulla riga. Nessun valore
    iniziale: l'elenco lo decide l'ufficio.
    """

    nome = models.CharField(max_length=100, unique=True)
    attiva = models.BooleanField(default=True)
    note = models.TextField(blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "fonte di finanziamento"
        verbose_name_plural = "fonti di finanziamento"
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class Impianto(Archiviabile):
    """Impianto a cui si riferisce un fabbisogno (es. un dissalatore)."""

    nome = models.CharField(max_length=150, unique=True)
    note = models.TextField(blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "impianto"
        verbose_name_plural = "impianti"
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class WBS(Archiviabile):
    """Elemento WBS di SAP, su cui si imputano le spese CAPEX (F9.2).

    - Di cluster: CAPEX "generico" del cluster, entra nel suo budget CAPEX.
    - A progetto (es. nuovi dissalatori): fuori dai budget dei cluster; i contratti restano
      registrati e consultabili per WBS. I contratti finanziati stanno su WBS a progetto.
    """

    class Tipo(models.TextChoices):
        CLUSTER = "cluster", "Di cluster"
        PROGETTO = "progetto", "A progetto"

    codice_wbs = models.CharField("codice WBS", max_length=40, unique=True)
    descrizione = models.CharField(max_length=200)
    tipo = models.CharField(max_length=10, choices=Tipo.choices, default=Tipo.PROGETTO)
    cluster = models.ForeignKey(
        "Cluster", on_delete=models.PROTECT, null=True, blank=True, related_name="wbs"
    )
    fonte_finanziamento = models.ForeignKey(
        FonteFinanziamento,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="wbs",
        verbose_name="fonte di finanziamento",
        help_text="Vale per le voci della WBS se il fabbisogno non ha una fonte propria.",
    )
    note = models.TextField(blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "WBS"
        verbose_name_plural = "WBS"
        ordering = ["codice_wbs"]
        constraints = [
            models.CheckConstraint(
                condition=Q(tipo="progetto") | Q(cluster__isnull=False),
                name="contratti_wbs_cluster_se_di_cluster",
            ),
        ]

    def __str__(self):
        return f"{self.codice_wbs} — {self.descrizione}"

    @property
    def a_progetto(self) -> bool:
        return self.tipo == self.Tipo.PROGETTO


class AutorizzazioneExtraBudget(Archiviabile):
    """Attività spot autorizzata dall'AD fuori dal budget (Rev18).

    Come una WBS a progetto, ma logica (non è un elemento SAP) e valida per OPEX e CAPEX: le
    voci collegate sono fuori dai budget dei cluster e si consultano per autorizzazione.
    I contratti con voci extra budget sono una tantum (nessun rinnovo, fuori dal piano ordini).
    L'importo autorizzato si confronta con il massimo delle voci collegate: oltre, un avviso.
    """

    codice = models.CharField(max_length=40, unique=True)
    descrizione = models.CharField(max_length=200)
    cluster = models.ForeignKey(
        "Cluster", on_delete=models.PROTECT, related_name="autorizzazioni_extra_budget"
    )
    protocollo = models.CharField("protocollo dell'autorizzazione AD", max_length=60)
    data_autorizzazione = models.DateField("data dell'autorizzazione AD")
    importo_autorizzato = importo("importo autorizzato (imponibile)")
    percorso_documento = models.CharField("documento", max_length=500, blank=True)
    note = models.TextField(blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "autorizzazione extra budget"
        verbose_name_plural = "autorizzazioni extra budget"
        ordering = ["-data_autorizzazione", "codice"]
        constraints = [
            models.CheckConstraint(
                condition=Q(importo_autorizzato__gte=0),
                name="contratti_extra_budget_importo_non_negativo",
            ),
        ]

    def __str__(self):
        return f"{self.codice} — {self.descrizione}"

    def get_absolute_url(self):
        from django.urls import reverse

        return reverse("reports:extra_budget_spese", args=[self.pk])


class ContoCoge(models.Model):
    """Piano dei conti con validità temporale e mappatura vecchio → nuovo.

    I conti reali si caricano sulla VM da file, mai dal repository.
    """

    codice = models.CharField(max_length=20)
    descrizione = models.CharField(max_length=200)
    valido_dal = models.DateField()
    valido_al = models.DateField(null=True, blank=True)
    sostituito_da = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="sostituisce",
        help_text="Conto che lo sostituisce dalla fine della validità.",
    )
    # F9.2: ogni conto appartiene a un solo cluster. Vuoto finché non si carica la struttura
    # (import «Struttura ICTDINN»): i conti senza cluster sono segnalati.
    cluster = models.ForeignKey(
        "Cluster", on_delete=models.PROTECT, null=True, blank=True, related_name="conti"
    )
    history = HistoricalRecords()

    class Meta:
        verbose_name = "conto COGE"
        verbose_name_plural = "piano dei conti"
        ordering = ["codice", "-valido_dal"]
        constraints = [
            models.UniqueConstraint(
                fields=["codice", "valido_dal"], name="contratti_conto_codice_dal_unico"
            ),
            models.CheckConstraint(
                condition=Q(valido_al__isnull=True) | Q(valido_al__gte=F("valido_dal")),
                name="contratti_conto_validita_coerente",
            ),
            models.CheckConstraint(
                condition=~Q(sostituito_da=F("id")), name="contratti_conto_non_sostituisce_se"
            ),
        ]

    def __str__(self):
        return f"{self.codice} {self.descrizione}"


# ---------------------------------------------------------------------------
# Anagrafiche e dominio
# ---------------------------------------------------------------------------


class Cluster(Archiviabile):
    """Area dell'ufficio ICTDINN che raggruppa più conti (IT, TLC, OT, ...): F9.2.

    Il codice è breve e stabile: lo usano filtri, import e indirizzi (``?area=IT``).
    """

    codice = models.CharField(max_length=10, unique=True)
    nome = models.CharField(max_length=100)
    # Cartella base delle RDA sul file server (SPEC §5.9): il percorso proposto parte da qui.
    cartella_rda = models.CharField(
        "cartella base delle RDA",
        max_length=500,
        blank=True,
        help_text="Es. smb://<nas>/Share/ICTDINN/00_IT/RDA_Ordini",
    )
    note = models.TextField(blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "cluster"
        verbose_name_plural = "cluster"
        ordering = ["codice"]

    def __str__(self):
        return self.nome if self.nome == self.codice else f"{self.codice} — {self.nome}"


class Sottocluster(Archiviabile):
    """Sottocategoria di un cluster: raggruppa i fabbisogni nel piano ordini (SPEC §5.4)."""

    cluster = models.ForeignKey(Cluster, on_delete=models.PROTECT, related_name="sottocluster")
    nome = models.CharField(max_length=100)
    note = models.TextField(blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "sottocluster"
        verbose_name_plural = "sottocluster"
        ordering = ["cluster__codice", "nome"]
        constraints = [
            models.UniqueConstraint(
                fields=["cluster", "nome"], name="contratti_sottocluster_nome_unico_nel_cluster"
            ),
        ]

    def __str__(self):
        return f"{self.cluster.codice} · {self.nome}"


class AssegnazioneCluster(Archiviabile):
    """Cluster di cui un utente è responsabile (F9.2): l'Editor modifica solo questi.

    Per nome utente di dominio, anche prima del primo accesso. Cluster vuoto = TUTTI (es.
    addetto amministrativo). Il ruolo (Admin, Editor, Reader) resta quello dei gruppi AD.
    Un'assegnazione tolta si archivia (non vale più) e torna attiva se riassegnata.
    """

    username = models.CharField("utente", max_length=150, db_index=True)
    cluster = models.ForeignKey(
        Cluster,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="assegnazioni",
        help_text="Vuoto: tutti i cluster.",
    )
    note = models.CharField(max_length=200, blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "assegnazione di cluster"
        verbose_name_plural = "assegnazioni di cluster"
        ordering = ["username", "cluster__codice"]
        constraints = [
            models.UniqueConstraint(
                fields=["username", "cluster"], name="contratti_assegnazione_unica"
            ),
            models.UniqueConstraint(
                fields=["username"],
                condition=Q(cluster__isnull=True),
                name="contratti_assegnazione_tutti_unica",
            ),
        ]

    def __str__(self):
        return f"{self.username} → {self.cluster.codice if self.cluster else 'TUTTI'}"

    def save(self, *args, **kwargs):
        self.username = self.username.strip().lower()
        super().save(*args, **kwargs)


class FunzioneUtente(Archiviabile):
    """Funzione di un utente nel processo d'acquisto (SPEC §8.1, Rev13).

    Non è un ruolo e non dà permessi: decide cruscotto e viste di default. Per nome utente di
    dominio, come le assegnazioni di cluster; una funzione tolta si archivia.
    """

    class Funzione(models.TextChoices):
        AMMINISTRAZIONE_ACQUISTI = "amministrazione_acquisti", "Amministrazione acquisti"

    username = models.CharField("utente", max_length=150, db_index=True)
    funzione = models.CharField(max_length=40, choices=Funzione.choices)
    note = models.CharField(max_length=200, blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "funzione dell'utente"
        verbose_name_plural = "funzioni degli utenti"
        ordering = ["username", "funzione"]
        constraints = [
            models.UniqueConstraint(
                fields=["username", "funzione"], name="contratti_funzione_unica"
            ),
        ]

    def __str__(self):
        return f"{self.username} → {self.get_funzione_display()}"

    def save(self, *args, **kwargs):
        self.username = self.username.strip().lower()
        super().save(*args, **kwargs)


class TabellaSAP(models.Model):
    """Codici SAP caricati da Excel (SPEC §4, §7, Rev13): al più un predefinito per tabella."""

    codice = models.CharField(max_length=20, unique=True)
    descrizione = models.CharField(max_length=200, blank=True)
    attivo = models.BooleanField(default=True)
    predefinito = models.BooleanField(default=False)

    class Meta:
        abstract = True
        ordering = ["codice"]

    def __str__(self):
        return f"{self.codice} — {self.descrizione}" if self.descrizione else self.codice

    @classmethod
    def predefinito_attivo(cls):
        return cls.objects.filter(predefinito=True, attivo=True).first()


def _un_predefinito(nome: str) -> models.UniqueConstraint:
    return models.UniqueConstraint(
        fields=["predefinito"],
        condition=Q(predefinito=True),
        name=f"contratti_{nome}_predefinito",
    )


class GruppoAcquisti(TabellaSAP):
    """Gruppo acquisti SAP (codice e nome); il predefinito è quello dell'ufficio (Rev13)."""

    history = HistoricalRecords()

    class Meta(TabellaSAP.Meta):
        verbose_name = "gruppo acquisti"
        verbose_name_plural = "gruppi acquisti"
        constraints = [_un_predefinito("gruppo_acquisti")]


class RichiedenteSAP(TabellaSAP):
    """Codice del richiedente SAP; il predefinito è quello dell'ufficio (Rev13).

    Il gruppo acquisti dell'unità (dai codici di rilascio SAP) si propone quando si sceglie
    il richiedente.
    """

    gruppo_acquisti = models.ForeignKey(
        GruppoAcquisti,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="richiedenti",
        help_text="Gruppo acquisti della stessa unità: si propone con il richiedente.",
    )
    history = HistoricalRecords()

    class Meta(TabellaSAP.Meta):
        verbose_name = "richiedente SAP"
        verbose_name_plural = "richiedenti SAP"
        constraints = [_un_predefinito("richiedente")]


class CentroCosto(TabellaSAP):
    """Centro di costo SAP: voci e posizioni lo scelgono da qui; il predefinito si propone
    sulle voci e sulle posizioni nuove. Voci e posizioni conservano il codice (testo): un
    codice già registrato e assente dalla tabella resta e si segnala."""

    history = HistoricalRecords()

    class Meta(TabellaSAP.Meta):
        verbose_name = "centro di costo"
        verbose_name_plural = "centri di costo"
        constraints = [_un_predefinito("centro_costo")]

    @classmethod
    def codice_predefinito(cls) -> str:
        predefinito = cls.predefinito_attivo()
        return predefinito.codice if predefinito else ""


class GruppoMerci(TabellaSAP):
    """Gruppo merci SAP; facoltativa la categoria di fabbisogno a cui si propone (Rev13)."""

    categoria = models.ForeignKey(
        Categoria,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="gruppi_merci",
        help_text="Categoria dei fabbisogni a cui si propone questo gruppo merci.",
    )
    history = HistoricalRecords()

    class Meta(TabellaSAP.Meta):
        verbose_name = "gruppo merci"
        verbose_name_plural = "gruppi merci"
        constraints = [_un_predefinito("gruppo_merci")]


def scelte_cluster() -> list[tuple[str, str]]:
    """(codice, nome) dei cluster attivi, per filtri e tendine."""
    return [(c.codice, c.nome) for c in Cluster.objects.filter(archiviato=False)]


class Natura(models.TextChoices):
    """Natura di bilancio: OPEX e CAPEX sono budget distinti, mai sommati."""

    OPEX = "OPEX", "OPEX"
    CAPEX = "CAPEX", "CAPEX"


class BudgetSottocluster(Archiviabile):
    """Budget assegnato a un sottocluster per un anno e una natura (OPEX o CAPEX).

    È un dato deciso (non derivato): il report del budget lo mostra accanto al totale del
    sottocluster filtrato. OPEX e CAPEX restano budget distinti, mai sommati.
    """

    sottocluster = models.ForeignKey(
        Sottocluster, on_delete=models.PROTECT, related_name="budget_assegnati"
    )
    anno = models.PositiveSmallIntegerField(db_index=True)
    natura = models.CharField(max_length=5, choices=Natura.choices)
    importo = importo("budget assegnato (imponibile)")
    note = models.TextField(blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "budget assegnato al sottocluster"
        verbose_name_plural = "budget assegnati ai sottocluster"
        ordering = ["-anno", "sottocluster__cluster__codice", "sottocluster__nome", "natura"]
        constraints = [
            models.UniqueConstraint(
                fields=["sottocluster", "anno", "natura"],
                name="contratti_budget_sottocluster_unico",
            ),
            models.CheckConstraint(
                condition=Q(importo__gte=0), name="contratti_budget_sottocluster_non_negativo"
            ),
        ]

    def __str__(self):
        return f"{self.sottocluster} · {self.anno} · {self.natura}"


class Fornitore(Archiviabile):
    ragione_sociale = models.CharField(max_length=200)
    # NULL = assente (TC-08 normalizza i nulli a NULL); univoca solo se presente.
    partita_iva = models.CharField(  # noqa: DJ001
        "partita IVA", max_length=20, null=True, blank=True
    )
    # Non univoco: nei file attuali lo stesso codice è su più fornitori (SPEC §2.2).
    codice_sap = models.CharField("codice SAP", max_length=20, blank=True, db_index=True)
    # Per l'intestazione della RDA e il nome della cartella (SPEC §5.9, Rev13).
    nome_breve = models.CharField("nome breve", max_length=40, blank=True)
    note = models.TextField(blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "fornitore"
        verbose_name_plural = "fornitori"
        ordering = ["ragione_sociale"]
        constraints = [
            models.UniqueConstraint(
                fields=["partita_iva"],
                condition=Q(partita_iva__isnull=False) & ~Q(partita_iva=""),
                name="contratti_fornitore_piva_unica",
            ),
        ]

    def __str__(self):
        return self.ragione_sociale

    def get_absolute_url(self):
        from django.urls import reverse

        return reverse("contratti:fornitore", args=[self.pk])

    @property
    def nome_per_rda(self) -> str:
        """Nome breve se c'è, altrimenti la ragione sociale (intestazione e cartella)."""
        return self.nome_breve.strip() or self.ragione_sociale

    def fornitori_stesso_codice_sap(self):
        """Altri fornitori con lo stesso codice SAP: da verificare, non da bloccare."""
        if not self.codice_sap:
            return Fornitore.objects.none()
        return Fornitore.objects.filter(codice_sap=self.codice_sap).exclude(pk=self.pk)


class ModalitaFatturazione(models.TextChoices):
    ANTICIPATA = "anticipata", "Anticipata"
    POSTICIPATA = "posticipata", "Posticipata"
    UNA_TANTUM = "una_tantum", "Una tantum"
    SAL = "sal", "A SAL"
    CONSUMO = "consumo", "A consumo"
    # Migrazione (SPEC §7.6): piano non noto, la cassa usa il pro-rata e lo segnala.
    DA_VERIFICARE = "da_verificare", "Da verificare"


class Periodicita(models.TextChoices):
    MENSILE = "mensile", "Mensile"
    BIMESTRALE = "bimestrale", "Bimestrale"
    TRIMESTRALE = "trimestrale", "Trimestrale"
    SEMESTRALE = "semestrale", "Semestrale"
    ANNUALE = "annuale", "Annuale"
    INTERA_DURATA = "intera_durata", "Intera durata"


class Fabbisogno(Archiviabile):
    """Servizio ricorrente che vive per anni; i contratti ne sono le istanze."""

    class Decisione(models.TextChoices):
        RINNOVARE = "rinnovare", "Rinnovare"
        DA_VALUTARE = "da_valutare", "Da valutare"
        SOSTITUIRE = "sostituire", "Sostituire"
        DISMETTERE = "dismettere", "Dismettere"

    descrizione = models.CharField(max_length=250)
    cluster = models.ForeignKey(Cluster, on_delete=models.PROTECT, related_name="fabbisogni")
    categoria = models.ForeignKey(Categoria, on_delete=models.PROTECT, related_name="fabbisogni")
    sottocluster = models.ForeignKey(
        Sottocluster,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="fabbisogni",
        help_text="Sottocategoria del cluster, per raggruppare il piano ordini.",
    )
    fonte_finanziamento = models.ForeignKey(
        FonteFinanziamento,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="fabbisogni",
        verbose_name="fonte di finanziamento",
        help_text="Vuota: vale quella della WBS della voce, altrimenti «Ordinaria».",
    )
    impianto = models.ForeignKey(
        Impianto, on_delete=models.PROTECT, null=True, blank=True, related_name="fabbisogni"
    )
    referente = models.CharField(max_length=150, blank=True)
    referente_utente = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="fabbisogni_referente",
        verbose_name="referente (utente)",
    )
    decisione = models.CharField(
        "decisione di continuità",
        max_length=20,
        choices=Decisione.choices,
        default=Decisione.DA_VALUTARE,
    )
    stima_prossimo_importo = importo("stima del prossimo importo", null=True, blank=True)
    note = models.TextField(blank=True)

    # Dati decisi per un fabbisogno nuovo, senza contratto: il motore ne ricava il previsto.
    previsto_data_avvio = models.DateField("avvio previsto", null=True, blank=True)
    previsto_durata_mesi = models.PositiveSmallIntegerField(
        "durata prevista (mesi)", null=True, blank=True
    )
    previsto_procedura = models.ForeignKey(
        Procedura,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="procedura presunta",
    )
    previsto_modalita = models.CharField(
        "modalità di fatturazione prevista",
        max_length=20,
        choices=ModalitaFatturazione.choices,
        blank=True,
    )
    previsto_periodicita = models.CharField(
        "periodicità prevista", max_length=20, choices=Periodicita.choices, blank=True
    )

    # Rinnovi previsti con classificazione diversa dall'ultimo contratto (es. nato CAPEX
    # su WBS, rinnovi in OPEX): dati decisi, il previsto li usa al posto di quelli copiati.
    # Classificazione del previsto manuale (fabbisogno nuovo, senza contratti). Per i rinnovi
    # di un contratto la classificazione è sulle voci (F9.2).
    natura_previsti = models.CharField(
        "natura del previsto",
        max_length=5,
        choices=Natura.choices,
        blank=True,
        help_text="Vuoto: OPEX.",
    )
    conto_previsti = models.ForeignKey(
        ContoCoge,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="conto del previsto",
    )
    wbs_previsti = models.ForeignKey(
        WBS,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="WBS del previsto",
        help_text="Obbligatoria se il previsto è CAPEX.",
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = "fabbisogno"
        verbose_name_plural = "fabbisogni"
        ordering = ["cluster__codice", "descrizione"]
        constraints = [
            models.CheckConstraint(
                condition=Q(stima_prossimo_importo__isnull=True) | Q(stima_prossimo_importo__gte=0),
                name="contratti_fabbisogno_stima_non_negativa",
            ),
            models.CheckConstraint(
                condition=Q(previsto_durata_mesi__isnull=True) | Q(previsto_durata_mesi__gt=0),
                name="contratti_fabbisogno_durata_prevista_positiva",
            ),
            # Un previsto manuale ha avvio e durata insieme, oppure nessuno dei due.
            models.CheckConstraint(
                condition=Q(previsto_data_avvio__isnull=True, previsto_durata_mesi__isnull=True)
                | Q(previsto_data_avvio__isnull=False, previsto_durata_mesi__isnull=False),
                name="contratti_fabbisogno_previsto_completo",
            ),
        ]

    def __str__(self):
        return f"[{self.area}] {self.descrizione}"

    def get_absolute_url(self):
        from django.urls import reverse

        return reverse("contratti:fabbisogno", args=[self.pk])

    @property
    def area(self) -> str:
        """Codice del cluster (prima di F9.2 era l'area IT/TLC)."""
        return self.cluster.codice

    def clean(self):
        super().clean()
        if (
            self.sottocluster_id
            and self.cluster_id
            and self.sottocluster.cluster_id != self.cluster_id
        ):
            raise ValidationError(
                {"sottocluster": "Il sottocluster deve appartenere al cluster del fabbisogno."}
            )


class Contratto(Archiviabile):
    """Singola istanza contrattuale; un rinnovo è un nuovo contratto sullo stesso fabbisogno."""

    class Finanziamento(models.TextChoices):
        ORDINARIO = "ordinario", "Ordinario"
        FINANZIATO = "finanziato", "Finanziato"
        EXTRA_BUDGET = "extra_budget", "Extra budget (autorizzato AD)"

    Natura = Natura

    fabbisogno = models.ForeignKey(Fabbisogno, on_delete=models.PROTECT, related_name="contratti")
    predecessore = models.OneToOneField(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="successore",
        help_text="Contratto di cui questo è il rinnovo.",
    )
    # F9.3: un contratto che rinnova più contratti (es. SIM voce e SIM M2M in uno solo). Il
    # rinnovo principale resta ``predecessore``; gli altri contratti sostituiti puntano qui al
    # nuovo. Ogni contratto ha al massimo un successore: o è il predecessore di uno, o
    # confluisce in uno.
    confluito_in = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="confluiti",
        verbose_name="confluito in",
        help_text="Contratto nuovo che sostituisce anche questo (oltre al suo predecessore).",
    )
    fornitore = models.ForeignKey(Fornitore, on_delete=models.PROTECT, related_name="contratti")
    descrizione = models.CharField(max_length=250, blank=True)
    # F9.5.5: acquisto rinnovato senza documento contrattuale (es. fattura diretta). È un
    # anello della catena come un contratto: stesse scadenze, alert, pratica e previsti; solo
    # fuori dal piano ordini (SPEC §5.6).
    senza_contratto = models.BooleanField(
        "senza contratto",
        default=False,
        help_text="Acquisto senza documento contrattuale: scadenze e alert come un contratto, "
        "fuori dal piano ordini.",
    )

    # Riferimenti SAP e ANAC: conservati come arrivano, le anomalie vanno nel report d'import.
    # NULL e non stringa vuota: TC-08 normalizza n/a, n/d, vuoto a NULL.
    numero_contratto = models.CharField("numero contratto", max_length=20, null=True, blank=True)  # noqa: DJ001
    numero_rda = models.CharField("numero RDA", max_length=20, null=True, blank=True)  # noqa: DJ001
    cig = models.CharField("CIG", max_length=20, null=True, blank=True)  # noqa: DJ001
    data_emissione = models.DateField("data emissione contratto", null=True, blank=True)

    procedura = models.ForeignKey(Procedura, on_delete=models.PROTECT, related_name="contratti")
    lead_time_mesi_override = models.PositiveSmallIntegerField(
        "lead time (mesi), override", null=True, blank=True
    )

    data_stipula = models.DateField(null=True, blank=True)
    # Può mancare nei dati importati (TC-08): il contratto resta escluso dai calcoli.
    data_inizio = models.DateField(null=True, blank=True)
    durata_mesi = models.PositiveSmallIntegerField("durata (mesi)")
    data_fine_override = models.DateField(
        "data di fine, override",
        null=True,
        blank=True,
        help_text="Solo se la fine contrattuale non è inizio + durata − 1 giorno.",
    )

    tacito_rinnovo = models.BooleanField(default=False)
    preavviso_disdetta_giorni = models.PositiveSmallIntegerField(
        "preavviso di disdetta (giorni)", null=True, blank=True
    )

    link_documenti = HttpsURLField("link ai documenti", max_length=500, blank=True)
    note = models.TextField(blank=True)

    # Processo d'acquisto (F11, SPEC §4 Rev11–Rev13).
    rda = models.ForeignKey(
        "RichiestaAcquisto",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="contratti_generati",
        verbose_name="RDA d'origine",
    )
    una_tantum = models.BooleanField(
        "una tantum",
        default=False,
        help_text="Acquisto che non si rinnova: fuori dalla catena, dagli alert e dai previsti; "
        "dentro il budget.",
    )
    cup = models.CharField("CUP", max_length=20, blank=True)
    rup = models.CharField("RUP", max_length=150, blank=True)
    percorso_documenti = models.CharField(
        "percorso sul file server",
        max_length=500,
        blank=True,
        help_text=r"Es. X:\… oppure \\nas\Share\…",
    )

    class TipoAcquisto(models.TextChoices):
        SERVIZIO = "servizio", "Servizio"
        FORNITURA = "fornitura", "Fornitura"

    # Propone MAP (servizio) o MIGO (fornitura) nella lavorazione delle fatture (Rev14).
    tipo_acquisto = models.CharField(
        "tipo d'acquisto",
        max_length=10,
        choices=TipoAcquisto.choices,
        default=TipoAcquisto.SERVIZIO,
    )
    # Chiusura amministrativa: atto deciso, si salva; si può annullare (SPEC §4).
    data_chiusura = models.DateField("data di chiusura", null=True, blank=True)
    chiuso_da = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="chiuso da",
    )

    # Chiave stabile della riga Excel di provenienza: rende l'import idempotente.
    chiave_import = models.CharField(  # noqa: DJ001
        max_length=64, unique=True, null=True, blank=True, editable=False
    )
    history = HistoricalRecords()

    class Meta:
        verbose_name = "contratto"
        verbose_name_plural = "contratti"
        ordering = ["-data_inizio", "fabbisogno__descrizione"]
        constraints = [
            models.CheckConstraint(
                condition=Q(durata_mesi__gt=0), name="contratti_contratto_durata_positiva"
            ),
            models.CheckConstraint(
                condition=~Q(predecessore=F("id")), name="contratti_contratto_non_precede_se"
            ),
            models.CheckConstraint(
                condition=~Q(confluito_in=F("id")), name="contratti_contratto_non_confluisce_in_se"
            ),
            models.CheckConstraint(
                condition=Q(tacito_rinnovo=False) | Q(preavviso_disdetta_giorni__isnull=False),
                name="contratti_contratto_preavviso_se_tacito",
            ),
            models.CheckConstraint(
                condition=Q(data_fine_override__isnull=True)
                | Q(data_inizio__isnull=True)
                | Q(data_fine_override__gte=F("data_inizio")),
                name="contratti_contratto_fine_dopo_inizio",
            ),
            # Una tantum: fuori dalla catena dei rinnovi (Rev11).
            models.CheckConstraint(
                condition=Q(una_tantum=False)
                | Q(predecessore__isnull=True, confluito_in__isnull=True),
                name="contratti_contratto_una_tantum_fuori_catena",
            ),
        ]

    def __str__(self):
        riferimento = self.numero_contratto or self.cig or f"#{self.pk}"
        return f"{self.fabbisogno.descrizione} — {riferimento}"

    def get_absolute_url(self):
        from django.urls import reverse

        return reverse("contratti:contratto", args=[self.pk])

    MISTA = "OPEX e CAPEX"

    def _voci_attive(self):
        # .all() e filtro in Python: con le voci già caricate (prefetch) nessuna query.
        return [v for v in self.voci.all() if not v.archiviato]

    @property
    def natura(self) -> str:
        """Si ricava dalle voci (F9.2): OPEX, CAPEX, oppure "OPEX e CAPEX" se miste."""
        nature = {v.natura for v in self._voci_attive()}
        if len(nature) > 1:
            return self.MISTA
        return nature.pop() if nature else Natura.OPEX

    @property
    def finanziamento(self) -> str:
        """Extra budget se almeno una voce lo è; finanziato se una è su una WBS a progetto."""
        voci = self._voci_attive()
        if any(v.autorizzazione_extra_budget_id for v in voci):
            return self.Finanziamento.EXTRA_BUDGET
        for v in voci:
            if v.wbs_id and v.wbs.tipo == WBS.Tipo.PROGETTO:
                return self.Finanziamento.FINANZIATO
        return self.Finanziamento.ORDINARIO

    @property
    def chiuso(self) -> bool:
        return self.data_chiusura is not None

    def clean(self):
        super().clean()
        if self.una_tantum and (self.predecessore_id or self.confluito_in_id):
            raise ValidationError(
                {"una_tantum": "Un contratto una tantum non ha predecessore né confluenze."}
            )
        if (
            not self.una_tantum
            and self.pk
            and self.voci.filter(
                archiviato=False, autorizzazione_extra_budget__isnull=False
            ).exists()
        ):
            raise ValidationError(
                {"una_tantum": "Un contratto con voci extra budget è una tantum (Rev18)."}
            )
        if self.una_tantum and self.pk and self._ha_successori():
            raise ValidationError({"una_tantum": "Un contratto una tantum non ha successori."})
        if self.predecessore_id and self.predecessore.una_tantum:
            raise ValidationError({"predecessore": "Un contratto una tantum non si rinnova."})
        if self.confluito_in_id and self.confluito_in.una_tantum:
            raise ValidationError({"confluito_in": "Non si confluisce in un contratto una tantum."})
        if (
            self.predecessore_id
            and self.fabbisogno_id
            and self.predecessore.fabbisogno_id != self.fabbisogno_id
        ):
            raise ValidationError(
                {"predecessore": "Il predecessore deve appartenere allo stesso fabbisogno."}
            )
        if self.predecessore_id and self.predecessore.confluito_in_id:
            raise ValidationError(
                {"predecessore": "Il predecessore è già confluito in un altro contratto."}
            )
        if self.confluito_in_id:
            nuovo = self.confluito_in
            if self.fabbisogno_id and nuovo.fabbisogno_id != self.fabbisogno_id:
                raise ValidationError(
                    {"confluito_in": "Si confluisce in un contratto dello stesso fabbisogno."}
                )
            if self.data_inizio and nuovo.data_inizio and nuovo.data_inizio <= self.data_inizio:
                raise ValidationError(
                    {"confluito_in": "Il contratto nuovo deve iniziare dopo questo."}
                )
            if self.pk and Contratto.objects.filter(predecessore_id=self.pk).exists():
                raise ValidationError(
                    {"confluito_in": "Il contratto ha già un successore: un solo successore."}
                )

    def _ha_successori(self) -> bool:
        return Contratto.objects.filter(
            Q(predecessore_id=self.pk) | Q(confluito_in_id=self.pk)
        ).exists()


class OpzioneContratto(models.Model):
    """Opzione di rinnovo o proroga prevista dal contratto, non ancora esercitata."""

    class Tipo(models.TextChoices):
        RINNOVO = "rinnovo", "Rinnovo"
        PROROGA = "proroga", "Proroga"

    contratto = models.ForeignKey(Contratto, on_delete=models.PROTECT, related_name="opzioni")
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    mesi = models.PositiveSmallIntegerField()
    importo = importo("importo", null=True, blank=True)
    note = models.TextField(blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "opzione di rinnovo/proroga"
        verbose_name_plural = "opzioni di rinnovo/proroga"
        constraints = [
            models.CheckConstraint(condition=Q(mesi__gt=0), name="contratti_opzione_mesi_positivi"),
            models.CheckConstraint(
                condition=Q(importo__isnull=True) | Q(importo__gte=0),
                name="contratti_opzione_importo_non_negativo",
            ),
        ]

    def __str__(self):
        return f"{self.get_tipo_display()} {self.mesi} mesi"


class Proroga(models.Model):
    """Proroga esercitata: sposta la scadenza; l'eventuale importo sta nelle sue voci.

    Un contratto può avere più proroghe. La fine effettiva è la ``nuova_data_fine``
    più recente (la calcola il motore, non si salva sul contratto).
    """

    contratto = models.ForeignKey(Contratto, on_delete=models.PROTECT, related_name="proroghe")
    data_atto = models.DateField("data dell'atto")
    nuova_data_fine = models.DateField("nuova data di fine")
    riferimento = models.CharField(
        max_length=200, blank=True, help_text="Protocollo, contratto integrativo o atto aggiuntivo."
    )
    note = models.TextField(blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "proroga"
        verbose_name_plural = "proroghe"
        ordering = ["contratto", "nuova_data_fine"]
        constraints = [
            models.UniqueConstraint(
                fields=["contratto", "nuova_data_fine"], name="contratti_proroga_fine_unica"
            ),
        ]

    def __str__(self):
        return f"Proroga al {self.nuova_data_fine:%d/%m/%Y}"


class VoceContratto(Archiviabile):
    """Voce economica di un contratto (1..n); se è legata a una proroga ne è l'importo."""

    contratto = models.ForeignKey(Contratto, on_delete=models.PROTECT, related_name="voci")
    proroga = models.ForeignKey(
        Proroga, on_delete=models.PROTECT, null=True, blank=True, related_name="voci"
    )
    descrizione = models.CharField(max_length=250)
    conto = models.ForeignKey(
        ContoCoge,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="voci",
        verbose_name="conto COGE",
    )
    # Codice come arrivato dall'import, anche se non è nel piano dei conti (TC-08).
    codice_conto_importato = models.CharField(max_length=20, blank=True)
    centro_costo = models.CharField("centro di costo", max_length=20, blank=True)
    # F9.2: natura e WBS sono della voce (in SAP ogni posizione ha la sua imputazione):
    # un contratto può avere quote OPEX e quote CAPEX. CAPEX ⇔ WBS.
    natura = models.CharField(max_length=5, choices=Natura.choices, default=Natura.OPEX)
    wbs = models.ForeignKey(
        WBS, on_delete=models.PROTECT, null=True, blank=True, related_name="voci",
        verbose_name="WBS",
    )  # fmt: skip
    # Codice WBS come arrivato dall'import o scritto a mano prima di F9.2.
    codice_wbs_importato = models.CharField("WBS (testo importato)", max_length=40, blank=True)
    # Classificazione dei rinnovi previsti, se diversa da questa voce (es. nata CAPEX su WBS,
    # rinnovi in OPEX). Dati decisi: il previsto li usa al posto di quelli della voce.
    natura_rinnovi = models.CharField(
        "natura nei rinnovi",
        max_length=5,
        choices=Natura.choices,
        blank=True,
        help_text="Vuoto: come questa voce.",
    )
    conto_rinnovi = models.ForeignKey(
        ContoCoge, on_delete=models.PROTECT, null=True, blank=True, related_name="+",
        verbose_name="conto nei rinnovi", help_text="Vuoto: il conto di questa voce.",
    )  # fmt: skip
    wbs_rinnovi = models.ForeignKey(
        WBS, on_delete=models.PROTECT, null=True, blank=True, related_name="+",
        verbose_name="WBS nei rinnovi", help_text="Vuoto: la WBS di questa voce.",
    )  # fmt: skip
    # Rev18: attività spot autorizzata dall'AD, fuori dai budget dei cluster (OPEX o CAPEX).
    autorizzazione_extra_budget = models.ForeignKey(
        AutorizzazioneExtraBudget, on_delete=models.PROTECT, null=True, blank=True,
        related_name="voci", verbose_name="autorizzazione extra budget",
        help_text="Solo per attività spot autorizzate dall'AD: la voce esce dal budget.",
    )  # fmt: skip
    importo_fisso = importo("importo fisso (imponibile)", default=0)
    massimale_variabile = importo("massimale variabile", default=0)
    stima_consumo_pct = percentuale("stima di consumo (%)", null=True, blank=True)
    stima_consumo_importo = importo("stima di consumo (importo)", null=True, blank=True)
    chiave_import = models.CharField(  # noqa: DJ001
        max_length=64, unique=True, null=True, blank=True, editable=False
    )
    history = HistoricalRecords()

    class Meta:
        verbose_name = "voce di contratto"
        verbose_name_plural = "voci di contratto"
        ordering = ["contratto", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(importo_fisso__gte=0), name="contratti_voce_fisso_non_negativo"
            ),
            models.CheckConstraint(
                condition=Q(massimale_variabile__gte=0),
                name="contratti_voce_massimale_non_negativo",
            ),
            models.CheckConstraint(
                condition=Q(stima_consumo_pct__isnull=True)
                | Q(stima_consumo_pct__gte=0, stima_consumo_pct__lte=100),
                name="contratti_voce_stima_pct_0_100",
            ),
            models.CheckConstraint(
                condition=Q(stima_consumo_importo__isnull=True)
                | Q(
                    stima_consumo_importo__gte=0,
                    stima_consumo_importo__lte=F("massimale_variabile"),
                ),
                name="contratti_voce_stima_importo_entro_massimale",
            ),
            models.CheckConstraint(
                condition=Q(stima_consumo_pct__isnull=True) | Q(stima_consumo_importo__isnull=True),
                name="contratti_voce_una_sola_stima",
            ),
        ]

    def __str__(self):
        return self.descrizione

    def clean(self):
        super().clean()
        if self.proroga_id and self.contratto_id and self.proroga.contratto_id != self.contratto_id:
            raise ValidationError({"proroga": "La proroga deve essere dello stesso contratto."})
        aut = self.autorizzazione_extra_budget if self.autorizzazione_extra_budget_id else None
        if aut and self.contratto_id:
            if not self.contratto.una_tantum:
                raise ValidationError(
                    {
                        "autorizzazione_extra_budget": "Solo un contratto una tantum può avere "
                        "voci extra budget: non ha rinnovi."
                    }
                )
            if self.contratto.fabbisogno.cluster_id != aut.cluster_id:
                raise ValidationError(
                    {
                        "autorizzazione_extra_budget": f"L'autorizzazione {aut.codice} è del "
                        f"cluster {aut.cluster.codice}."
                    }
                )


class QuotaPeriodo(models.Model):
    """Importo fisso di una voce per un sotto-periodo (tipicamente un anno), facoltativo.

    Le quote di una voce devono essere contigue, coprire tutto il periodo di servizio e
    sommare all'importo fisso: il controllo è nel motore, che segnala le incoerenze.
    """

    voce = models.ForeignKey(VoceContratto, on_delete=models.PROTECT, related_name="quote")
    dal = models.DateField()
    al = models.DateField()
    importo = importo("importo fisso del periodo")
    history = HistoricalRecords()

    class Meta:
        verbose_name = "quota per periodo"
        verbose_name_plural = "quote per periodo"
        ordering = ["voce", "dal"]
        constraints = [
            models.UniqueConstraint(fields=["voce", "dal"], name="contratti_quota_dal_unica"),
            models.CheckConstraint(
                condition=Q(al__gte=F("dal")), name="contratti_quota_periodo_coerente"
            ),
            models.CheckConstraint(
                condition=Q(importo__gte=0), name="contratti_quota_importo_non_negativo"
            ),
        ]

    def __str__(self):
        return f"{self.dal:%d/%m/%Y}–{self.al:%d/%m/%Y}: {self.importo}"


class PianoFatturazione(models.Model):
    """Come e quando si fattura una voce; da qui si genera lo scadenzario (F2)."""

    voce = models.OneToOneField(
        VoceContratto, on_delete=models.PROTECT, related_name="piano_fatturazione"
    )
    modalita = models.CharField(max_length=20, choices=ModalitaFatturazione.choices)
    periodicita = models.CharField(max_length=20, choices=Periodicita.choices, blank=True)
    data_prima_fattura = models.DateField(
        null=True,
        blank=True,
        help_text=(
            "Vuota: inizio del servizio se anticipata, fine del primo periodo se posticipata."
        ),
    )
    giorni_pagamento = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="Vuoto: parametro di default."
    )
    pagamento_fine_mese = models.BooleanField(
        null=True, blank=True, help_text="Vuoto: parametro di default."
    )
    note = models.TextField(blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "piano di fatturazione"
        verbose_name_plural = "piani di fatturazione"
        constraints = [
            # Periodicità obbligatoria per le modalità a rate.
            models.CheckConstraint(
                condition=~Q(modalita__in=["anticipata", "posticipata"]) | ~Q(periodicita=""),
                name="contratti_piano_periodicita_se_a_rate",
            ),
        ]

    def __str__(self):
        return f"{self.get_modalita_display()} {self.get_periodicita_display()}".strip()


class Rata(models.Model):
    """Rata dello scadenzario: generata dal motore, poi modificabile a mano (tracciato)."""

    piano = models.ForeignKey(PianoFatturazione, on_delete=models.PROTECT, related_name="rate")
    numero = models.PositiveSmallIntegerField()
    data_fattura = models.DateField()
    data_pagamento_stimata = models.DateField()
    importo = importo("importo")
    modificata_manualmente = models.BooleanField(default=False)
    consuntivo = models.BooleanField(default=False, help_text="Rata effettivamente fatturata.")
    numero_fattura = models.CharField(max_length=40, blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "rata"
        verbose_name_plural = "rate"
        ordering = ["piano", "numero"]
        constraints = [
            models.UniqueConstraint(fields=["piano", "numero"], name="contratti_rata_numero_unico"),
            models.CheckConstraint(
                condition=Q(importo__gte=0), name="contratti_rata_importo_non_negativo"
            ),
            models.CheckConstraint(
                condition=Q(numero__gt=0), name="contratti_rata_numero_positivo"
            ),
            models.CheckConstraint(
                condition=Q(data_pagamento_stimata__gte=F("data_fattura")),
                name="contratti_rata_pagamento_dopo_fattura",
            ),
        ]

    def __str__(self):
        return f"Rata {self.numero} del {self.data_fattura:%d/%m/%Y}"


class StatoPratica(models.Model):
    """Passaggio della pratica di rinnovo (SPEC §4). Lo stato corrente è l'ultimo passaggio.

    La pratica riguarda il contratto in scadenza; per un fabbisogno nuovo, senza contratti,
    si lega al fabbisogno. Mai entrambi.
    """

    class Stato(models.TextChoices):
        NON_AVVIATA = "non_avviata", "Non avviata"
        OFFERTA_RICHIESTA = "offerta_richiesta", "Offerta richiesta"
        OFFERTA_RICEVUTA = "offerta_ricevuta", "Offerta ricevuta"
        # Chiesto l'inserimento della RDA in SAP; diventa "predisposta" quando è inserita.
        RDA_RICHIESTA = "rda_richiesta", "RDA richiesta"
        RDA_PREDISPOSTA = "rda_predisposta", "RDA predisposta"
        RDA_APPROVATA = "rda_approvata", "RDA approvata"
        CONTRATTO_EMESSO = "contratto_emesso", "Contratto emesso"
        CONTRATTO_ATTIVO = "contratto_attivo", "Contratto attivo"

    contratto = models.ForeignKey(
        Contratto, on_delete=models.PROTECT, null=True, blank=True, related_name="stati_pratica"
    )
    fabbisogno = models.ForeignKey(
        Fabbisogno, on_delete=models.PROTECT, null=True, blank=True, related_name="stati_pratica"
    )
    stato = models.CharField(max_length=20, choices=Stato.choices)
    data = models.DateField()
    note = models.TextField(blank=True)
    utente = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    registrato_il = models.DateTimeField(auto_now_add=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "passaggio della pratica"
        verbose_name_plural = "storico della pratica di rinnovo"
        ordering = ["-data", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(contratto__isnull=False, fabbisogno__isnull=True)
                | Q(contratto__isnull=True, fabbisogno__isnull=False),
                name="contratti_pratica_contratto_o_fabbisogno",
            ),
        ]

    def __str__(self):
        return f"{self.get_stato_display()} ({self.data:%d/%m/%Y})"


# ---------------------------------------------------------------------------
# Processo d'acquisto (F11, SPEC §4 Rev11–Rev13)
# ---------------------------------------------------------------------------


class RichiestaAcquisto(Archiviabile):
    """Richiesta d'acquisto (RDA).

    Nasce sul portale come richiesta compilata dal referente a partire dal fabbisogno;
    l'addetto amministrativo la inserisce in SAP e vi riporta i dati di SAP. La fase (bozza,
    inviata, inserita, ...) non si salva: la ricava il motore dai dati, dallo storico
    (``eventi``) e dai contratti generati (SPEC §5.7). In migrazione si registrano anche RDA
    già inserite in SAP, eventualmente senza legami, da collegare dopo.
    """

    class Origine(models.TextChoices):
        PORTALE = "portale", "Richiesta dal portale"
        MANUALE = "manuale", "Registrata a mano"
        IMPORT = "import", "Importata"

    class Scopo(models.TextChoices):
        RINNOVO = "rinnovo", "Rinnovo"
        PRIMO_ACQUISTO = "primo_acquisto", "Primo acquisto"
        AGGIUNTIVO = "aggiuntivo", "Acquisto aggiuntivo"

    origine = models.CharField(max_length=10, choices=Origine.choices, default=Origine.PORTALE)
    scopo = models.CharField(max_length=20, choices=Scopo.choices, blank=True)
    cluster = models.ForeignKey(
        Cluster, on_delete=models.PROTECT, related_name="richieste_acquisto"
    )
    # La pratica: il contratto in scadenza (rinnovo) oppure il fabbisogno. Mai entrambi.
    fabbisogno = models.ForeignKey(
        Fabbisogno,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="richieste_acquisto",
    )
    contratto_in_scadenza = models.ForeignKey(
        "Contratto",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="rda_pratica",
        verbose_name="contratto in scadenza",
    )
    referente_utente = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="richieste_acquisto",
        verbose_name="referente",
    )
    referente = models.CharField(
        "referente (testo)",
        max_length=150,
        blank=True,
        help_text="Per le RDA registrate a mano o importate.",
    )

    # Campi della richiesta, nell'ordine della scheda SAP (SPEC §5.9).
    descrizione = models.CharField(max_length=250)
    intestazione = models.CharField(max_length=250, blank=True)
    fornitore_proposto = models.ForeignKey(
        Fornitore, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    richiedente = models.ForeignKey(
        RichiedenteSAP,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="richiedente SAP",
    )
    gruppo_acquisti = models.ForeignKey(
        GruppoAcquisti,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="gruppo acquisti",
    )
    note_buyer = models.TextField("note al buyer", blank=True)
    allegati = models.TextField(blank=True, help_text="Cosa è allegato e dove si trova.")
    percorso_file_server = models.CharField("percorso sul file server", max_length=500, blank=True)
    rup = models.CharField("RUP", max_length=150, blank=True)
    cup = models.CharField("CUP", max_length=20, blank=True)
    note = models.TextField("note interne", blank=True)
    data_creazione = models.DateField("data di creazione", default=timezone.localdate)

    # Campi da SAP.
    numero_rda = models.CharField(  # noqa: DJ001
        "numero RDA", max_length=20, null=True, blank=True
    )
    data_inserimento = models.DateField("data di inserimento in SAP", null=True, blank=True)
    data_rilascio = models.DateField("data dell'ultimo rilascio", null=True, blank=True)

    chiave_import = models.CharField(  # noqa: DJ001
        max_length=64, unique=True, null=True, blank=True, editable=False
    )
    history = HistoricalRecords()

    class Meta:
        verbose_name = "richiesta d'acquisto (RDA)"
        verbose_name_plural = "richieste d'acquisto (RDA)"
        ordering = ["-data_creazione", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(fabbisogno__isnull=True) | Q(contratto_in_scadenza__isnull=True),
                name="contratti_rda_fabbisogno_o_contratto",
            ),
            models.CheckConstraint(
                condition=~Q(scopo="rinnovo") | Q(contratto_in_scadenza__isnull=False),
                name="contratti_rda_rinnovo_su_contratto",
            ),
            models.CheckConstraint(
                condition=~Q(scopo__in=["primo_acquisto", "aggiuntivo"])
                | Q(fabbisogno__isnull=False),
                name="contratti_rda_acquisto_su_fabbisogno",
            ),
            # La richiesta nata sul portale parte dal fabbisogno e ha un referente.
            models.CheckConstraint(
                condition=~Q(origine="portale")
                | (
                    Q(referente_utente__isnull=False)
                    & (Q(fabbisogno__isnull=False) | Q(contratto_in_scadenza__isnull=False))
                ),
                name="contratti_rda_portale_completa",
            ),
            models.UniqueConstraint(
                fields=["numero_rda"],
                condition=Q(numero_rda__isnull=False, archiviato=False) & ~Q(numero_rda=""),
                name="contratti_rda_numero_unico",
            ),
        ]

    def __str__(self):
        return f"RDA {self.numero_rda}" if self.numero_rda else f"Richiesta di RDA #{self.pk}"

    @property
    def nome_referente(self) -> str:
        if self.referente_utente_id:
            return str(self.referente_utente)
        return self.referente

    def fabbisogno_della_pratica(self) -> Fabbisogno | None:
        if self.contratto_in_scadenza_id:
            return self.contratto_in_scadenza.fabbisogno
        return self.fabbisogno

    def clean(self):
        super().clean()
        if self.contratto_in_scadenza_id and self.contratto_in_scadenza.una_tantum:
            raise ValidationError(
                {"contratto_in_scadenza": "Un contratto una tantum non si rinnova."}
            )
        fabbisogno = self.fabbisogno_della_pratica()
        if fabbisogno is not None and self.cluster_id and fabbisogno.cluster_id != self.cluster_id:
            raise ValidationError({"cluster": "Il cluster è quello del fabbisogno."})
        if (
            self.data_rilascio
            and self.data_inserimento
            and self.data_rilascio < self.data_inserimento
        ):
            raise ValidationError(
                {"data_rilascio": "Il rilascio non può precedere l'inserimento in SAP."}
            )


class PosizioneRDA(models.Model):
    """Posizione della RDA. L'importo (quantità × importo unitario) si calcola, non si salva.

    In SAP la RDA va per l'importo massimo: ``di_cui_variabile`` è la parte a consumo, da cui
    il contratto registrato ricava il massimale variabile.
    """

    rda = models.ForeignKey(RichiestaAcquisto, on_delete=models.PROTECT, related_name="posizioni")
    numero = models.PositiveSmallIntegerField()
    descrizione_breve = models.CharField("descrizione breve", max_length=250)
    gruppo_merci = models.ForeignKey(
        GruppoMerci, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    quantita = models.DecimalField("quantità", max_digits=12, decimal_places=3, default=1)
    importo_unitario = importo("importo unitario (imponibile)")
    di_cui_variabile = importo("di cui variabile", default=0)
    # Campi informativi: stesse regole della voce (CAPEX ⇔ WBS).
    natura = models.CharField(max_length=5, choices=Natura.choices, default=Natura.OPEX)
    conto = models.ForeignKey(
        ContoCoge,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="conto COGE",
    )
    centro_costo = models.CharField("centro di costo", max_length=20, blank=True)
    wbs = models.ForeignKey(
        WBS, on_delete=models.PROTECT, null=True, blank=True, related_name="+", verbose_name="WBS"
    )
    history = HistoricalRecords()

    class Meta:
        verbose_name = "posizione della RDA"
        verbose_name_plural = "posizioni della RDA"
        ordering = ["rda", "numero"]
        constraints = [
            models.UniqueConstraint(fields=["rda", "numero"], name="contratti_posizione_numero"),
            models.CheckConstraint(
                condition=Q(numero__gt=0), name="contratti_posizione_numero_positivo"
            ),
            models.CheckConstraint(
                condition=Q(quantita__gt=0), name="contratti_posizione_quantita_positiva"
            ),
            models.CheckConstraint(
                condition=Q(importo_unitario__gte=0),
                name="contratti_posizione_importo_non_negativo",
            ),
            models.CheckConstraint(
                condition=Q(di_cui_variabile__gte=0),
                name="contratti_posizione_variabile_non_negativo",
            ),
            models.CheckConstraint(
                condition=Q(natura="OPEX", wbs__isnull=True) | Q(natura="CAPEX", wbs__isnull=False),
                name="contratti_posizione_capex_se_wbs",
            ),
        ]

    def __str__(self):
        return f"{self.numero}. {self.descrizione_breve}"

    @property
    def importo(self):
        return importo_posizione(self.quantita, self.importo_unitario)

    def clean(self):
        super().clean()
        if (
            self.importo_unitario is not None
            and self.quantita
            and self.di_cui_variabile is not None
            and self.di_cui_variabile > self.importo
        ):
            raise ValidationError(
                {"di_cui_variabile": "Il variabile non può superare l'importo della posizione."}
            )


class EventoRDA(models.Model):
    """Storico della richiesta: invio all'addetto, rimando al referente, annullamento."""

    class Tipo(models.TextChoices):
        INVIO = "invio", "Inviata all'addetto"
        RIMANDO = "rimando", "Rimandata al referente"
        ANNULLAMENTO = "annullamento", "Annullata"

    rda = models.ForeignKey(RichiestaAcquisto, on_delete=models.PROTECT, related_name="eventi")
    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    data = models.DateField()
    nota = models.TextField(blank=True)
    utente = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    registrato_il = models.DateTimeField(auto_now_add=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "evento della RDA"
        verbose_name_plural = "storico della RDA"
        ordering = ["rda", "data", "id"]

    def __str__(self):
        return f"{self.get_tipo_display()} ({self.data:%d/%m/%Y})"


class Fattura(Archiviabile):
    """Fattura del fornitore (SPEC §4, Rev11–Rev15).

    Entra dall'import settimanale senza referente e senza contratto: la prende in carico un
    referente, la abbina al contratto e la convalida; poi RdC → MAP/MIGO → trasferimento.
    Se c'è il contratto, il fornitore è il suo.
    """

    class Esito(models.TextChoices):
        DA_VALUTARE = "da_valutare", "Da valutare"
        CONVALIDABILE = "convalidabile", "Convalidabile"
        NON_CONVALIDABILE = "non_convalidabile", "Non convalidabile"
        IN_ATTESA = "in_attesa", "In attesa"

    contratto = models.ForeignKey(
        Contratto, on_delete=models.PROTECT, null=True, blank=True, related_name="fatture"
    )
    fornitore = models.ForeignKey(Fornitore, on_delete=models.PROTECT, related_name="fatture")
    numero = models.CharField(max_length=60)
    data = models.DateField()
    # Rev15: l'«Importo SAP» dell'estrazione; il residuo del contratto usa il valore base.
    importo_documento = importo("importo del documento")
    valore_base = importo("valore base prelevato dal contratto", null=True, blank=True)
    oneri = importo("oneri previdenziali", null=True, blank=True)
    bollo = importo("bollo", null=True, blank=True)
    # IVA compresa nell'importo del documento (SAP lo riporta spesso con l'IVA).
    iva = importo("IVA compresa nell'importo", null=True, blank=True)
    # Imputazione propria della fattura, se diversa da quella della voce (es. acquisti vari
    # sullo stesso contratto): vale per le indicazioni di validazione e il commento per PAC.
    conto = models.ForeignKey(
        ContoCoge, on_delete=models.PROTECT, null=True, blank=True, related_name="+",
        verbose_name="conto COGE della fattura",
    )  # fmt: skip
    centro_costo = models.CharField("centro di costo della fattura", max_length=20, blank=True)
    wbs = models.ForeignKey(
        WBS, on_delete=models.PROTECT, null=True, blank=True, related_name="+",
        verbose_name="WBS della fattura",
    )  # fmt: skip
    voce = models.ForeignKey(
        VoceContratto, on_delete=models.PROTECT, null=True, blank=True, related_name="fatture"
    )
    rata = models.OneToOneField(
        Rata,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="fattura",
        help_text="Rata dello scadenzario a cui corrisponde.",
    )
    # Presa in carico (Rev15): chi la lavora come referente.
    referente = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="fatture_in_carico",
        verbose_name="in carico a",
    )
    data_presa_in_carico = models.DateField("presa in carico il", null=True, blank=True)
    # Convalida del referente (Rev15).
    esito_convalida = models.CharField(
        "esito della convalida", max_length=20, choices=Esito.choices, default=Esito.DA_VALUTARE
    )
    nota_convalida = models.TextField("nota della convalida", blank=True)
    bloccata_fino_al = models.DateField(null=True, blank=True)
    data_convalida = models.DateField("esito registrato il", null=True, blank=True)
    fuori_registro = models.BooleanField(
        default=False, help_text="Non riguarda il registro: resta fuori dalle viste di lavorazione."
    )
    data_registrazione = models.DateField("registrata il", default=timezone.localdate)
    # Ultimo passo della lavorazione (Rev14): solo la data, senza numero SAP.
    data_trasferimento = models.DateField("trasferita per il pagamento il", null=True, blank=True)
    trasferita_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    note = models.TextField(blank=True)
    chiave_import = models.CharField(  # noqa: DJ001
        max_length=64, unique=True, null=True, blank=True, editable=False
    )
    history = HistoricalRecords()

    class Meta:
        verbose_name = "fattura"
        verbose_name_plural = "fatture"
        ordering = ["data", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(importo_documento__gte=0),
                name="contratti_fattura_importo_non_negativo",
            ),
            models.CheckConstraint(
                condition=(Q(valore_base__isnull=True) | Q(valore_base__gte=0))
                & (Q(oneri__isnull=True) | Q(oneri__gte=0))
                & (Q(bollo__isnull=True) | Q(bollo__gte=0))
                & (Q(iva__isnull=True) | Q(iva__gte=0)),
                name="contratti_fattura_importi_non_negativi",
            ),
            models.UniqueConstraint(
                fields=["fornitore", "numero"],
                condition=Q(archiviato=False),
                name="contratti_fattura_numero_unico",
            ),
        ]

    def __str__(self):
        return f"Fattura {self.numero} del {self.data:%d/%m/%Y}"

    def save(self, *args, **kwargs):
        if self.contratto_id and not self.fornitore_id:
            self.fornitore_id = self.contratto.fornitore_id
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        from django.urls import reverse

        return reverse("contratti:fattura", args=[self.pk])

    def clean(self):
        super().clean()
        if (
            self.contratto_id
            and self.fornitore_id
            and self.contratto.fornitore_id != self.fornitore_id
        ):
            raise ValidationError({"contratto": "Il contratto è di un altro fornitore."})
        if self.voce_id and self.voce.contratto_id != self.contratto_id:
            raise ValidationError({"voce": "La voce deve essere dello stesso contratto."})
        if self.rata_id and self.rata.piano.voce.contratto_id != self.contratto_id:
            raise ValidationError({"rata": "La rata deve essere dello stesso contratto."})


class DocumentoEsecuzione(Archiviabile):
    """Documento dell'esecuzione del contratto (SPEC §4).

    ODA/RDC, DDT, MIGO, MAP, attestazione di regolare esecuzione, modello di ricezione
    materiale. Se è un documento SAP a supporto di una fattura (es. MAP o MIGO) si collega
    alla fattura.
    """

    class Tipo(models.TextChoices):
        ODA = "ODA_RDC", "ODA/RDC"
        DDT = "DDT", "DDT"
        MIGO = "MIGO", "MIGO"
        MAP = "MAP", "MAP"
        ATTESTAZIONE = "ATTESTAZIONE", "Attestazione di regolare esecuzione"
        RICEZIONE = "RICEZIONE", "Modello di ricezione materiale"

    contratto = models.ForeignKey(
        Contratto, on_delete=models.PROTECT, related_name="documenti_esecuzione"
    )
    tipo = models.CharField(max_length=15, choices=Tipo.choices)
    numero = models.CharField(max_length=40, blank=True)
    data = models.DateField()
    importo = importo("importo", null=True, blank=True)
    voce = models.ForeignKey(
        VoceContratto, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    finale = models.BooleanField(
        default=False, help_text="Attestazione o modello di ricezione finale (non parziale)."
    )
    fattura = models.ForeignKey(
        Fattura, on_delete=models.PROTECT, null=True, blank=True, related_name="documenti"
    )
    note = models.TextField(blank=True)
    chiave_import = models.CharField(  # noqa: DJ001
        max_length=64, unique=True, null=True, blank=True, editable=False
    )
    history = HistoricalRecords()

    class Meta:
        verbose_name = "documento di esecuzione"
        verbose_name_plural = "documenti di esecuzione"
        ordering = ["contratto", "data", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(importo__isnull=True) | Q(importo__gte=0),
                name="contratti_documento_importo_non_negativo",
            ),
            models.CheckConstraint(
                condition=Q(finale=False) | Q(tipo__in=["ATTESTAZIONE", "RICEZIONE"]),
                name="contratti_documento_finale_solo_attestazioni",
            ),
        ]

    def __str__(self):
        numero = f" {self.numero}" if self.numero else ""
        return f"{self.get_tipo_display()}{numero} ({self.data:%d/%m/%Y})"

    def clean(self):
        super().clean()
        if self.fattura_id and self.contratto_id and self.fattura.contratto_id != self.contratto_id:
            raise ValidationError({"fattura": "La fattura deve essere dello stesso contratto."})
        if self.voce_id and self.contratto_id and self.voce.contratto_id != self.contratto_id:
            raise ValidationError({"voce": "La voce deve essere dello stesso contratto."})


# ---------------------------------------------------------------------------
# Staging dell'import: proposte da confermare a mano, mai applicate in automatico
# ---------------------------------------------------------------------------


class StatoProposta(models.TextChoices):
    PROPOSTA = "proposta", "Da valutare"
    CONFERMATA = "confermata", "Confermata"
    SCARTATA = "scartata", "Scartata"


class PropostaRaggruppamento(models.Model):
    """Contratti che l'import ritiene istanze dello stesso fabbisogno."""

    contratti = models.ManyToManyField(Contratto, related_name="proposte_raggruppamento")
    motivazione = models.CharField(max_length=300)
    chiave = models.CharField(max_length=64, unique=True, editable=False)
    stato = models.CharField(
        max_length=12, choices=StatoProposta.choices, default=StatoProposta.PROPOSTA
    )
    creata_il = models.DateTimeField(auto_now_add=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "proposta di raggruppamento"
        verbose_name_plural = "proposte di raggruppamento"
        ordering = ["stato", "motivazione"]

    def __str__(self):
        return self.motivazione


class PropostaPredecessore(models.Model):
    """Coppia (predecessore → successore) proposta dall'import per la catena dei rinnovi."""

    predecessore = models.ForeignKey(
        Contratto, on_delete=models.PROTECT, related_name="proposte_come_predecessore"
    )
    successore = models.ForeignKey(
        Contratto, on_delete=models.PROTECT, related_name="proposte_come_successore"
    )
    motivazione = models.CharField(max_length=300)
    stato = models.CharField(
        max_length=12, choices=StatoProposta.choices, default=StatoProposta.PROPOSTA
    )
    creata_il = models.DateTimeField(auto_now_add=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "proposta di predecessore"
        verbose_name_plural = "proposte di predecessore"
        ordering = ["stato", "successore__data_inizio"]
        constraints = [
            models.UniqueConstraint(
                fields=["predecessore", "successore"], name="contratti_proposta_coppia_unica"
            ),
            models.CheckConstraint(
                condition=~Q(predecessore=F("successore")),
                name="contratti_proposta_non_se_stesso",
            ),
        ]

    def __str__(self):
        return self.motivazione


# ---------------------------------------------------------------------------
# Import da interfaccia (F9.1): ogni caricamento resta registrato
# ---------------------------------------------------------------------------


class Importazione(models.Model):
    """File caricato dall'interfaccia: anteprima (nessuna scrittura), poi conferma.

    Il file resta nel database con l'esito: chi ha importato cosa, quando e con che
    risultato. Nessuna cancellazione.
    """

    class Stato(models.TextChoices):
        ANTEPRIMA = "anteprima", "In anteprima"
        CONFERMATA = "confermata", "Importato"
        ANNULLATA = "annullata", "Annullato"
        SCADUTA = "scaduta", "Anteprima scaduta"
        ERRORE = "errore", "File non importabile"
        COMPLETATA = "completata", "Report pronto"  # tipi senza conferma (quadratura)

    tipo = models.CharField(max_length=30)
    nome_file = models.CharField(max_length=255)
    contenuto = models.BinaryField()
    sha256 = models.CharField(max_length=64)
    dimensione = models.PositiveIntegerField()
    opzioni = models.JSONField(default=dict, blank=True)
    stato = models.CharField(max_length=12, choices=Stato.choices, default=Stato.ANTEPRIMA)
    # Report serializzato: {"conteggi": {...}, "anomalie": [...], ...}
    anteprima = models.JSONField(default=dict, blank=True)
    esito = models.JSONField(default=dict, blank=True)
    messaggio = models.TextField(blank=True)
    # Report in XLSX prodotto dall'operazione (es. quadratura).
    risultato = models.BinaryField(null=True, blank=True)
    utente = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="importazioni"
    )
    caricata_il = models.DateTimeField(auto_now_add=True)
    confermata_il = models.DateTimeField(null=True, blank=True)
    confermata_da = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        verbose_name = "import"
        verbose_name_plural = "registro degli import"
        ordering = ["-caricata_il", "-id"]

    def __str__(self):
        return f"{self.nome_file} ({self.caricata_il:%d/%m/%Y %H:%M})"
