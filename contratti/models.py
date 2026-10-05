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
from simple_history.models import HistoricalRecords


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


class Parametro(ConfigurazioneProvvisoria):
    """Parametro numerico con validità temporale (giorni di pagamento, adeguamento dei previsti)."""

    class Chiave(models.TextChoices):
        GIORNI_PAGAMENTO = "giorni_pagamento", "giorni di pagamento di default"
        PAGAMENTO_FINE_MESE = "pagamento_fine_mese", "pagamento a fine mese (1 = sì)"
        ADEGUAMENTO_PCT = "adeguamento_pct", "adeguamento dei rinnovi previsti (%)"
        FINESTRA_ALERT_MESI = "finestra_alert_mesi", "finestra dell'alert giallo (mesi)"
        ORIZZONTE_ANNI = "orizzonte_anni", "orizzonte della previsione rinnovi (anni)"

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
    note = models.TextField(blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "cluster"
        verbose_name_plural = "cluster"
        ordering = ["codice"]

    def __str__(self):
        return self.nome if self.nome == self.codice else f"{self.codice} — {self.nome}"


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


def scelte_cluster() -> list[tuple[str, str]]:
    """(codice, nome) dei cluster attivi, per filtri e tendine."""
    return [(c.codice, c.nome) for c in Cluster.objects.filter(archiviato=False)]


class Natura(models.TextChoices):
    """Natura di bilancio: OPEX e CAPEX sono budget distinti, mai sommati."""

    OPEX = "OPEX", "OPEX"
    CAPEX = "CAPEX", "CAPEX"


class Fornitore(Archiviabile):
    ragione_sociale = models.CharField(max_length=200)
    # NULL = assente (TC-08 normalizza i nulli a NULL); univoca solo se presente.
    partita_iva = models.CharField(  # noqa: DJ001
        "partita IVA", max_length=20, null=True, blank=True
    )
    # Non univoco: nei file attuali lo stesso codice è su più fornitori (SPEC §2.2).
    codice_sap = models.CharField("codice SAP", max_length=20, blank=True, db_index=True)
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

    # F9.5: fabbisogno soddisfatto senza contratto (es. dominio DNS pagato ogni anno con una
    # fattura diretta). Dati decisi; le spese di ogni periodo si calcolano (SPEC §5.6).
    # Natura, conto e WBS sono quelli «del previsto» qui sopra.
    senza_contratto = models.BooleanField(
        "spesa ricorrente senza contratto",
        default=False,
        help_text="Si paga senza contratto: il budget conta la spesa ogni periodo da sola.",
    )
    spesa_fornitore = models.ForeignKey(
        "Fornitore",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="spese_ricorrenti",
        verbose_name="fornitore",
    )
    spesa_importo = importo("importo per periodo", null=True, blank=True)
    spesa_periodicita = models.CharField(
        "periodicità",
        max_length=20,
        choices=[c for c in Periodicita.choices if c[0] != Periodicita.INTERA_DURATA],
        blank=True,
    )
    spesa_dal = models.DateField(
        "prima spesa", null=True, blank=True, help_text="Data della prima spesa (o fattura)."
    )
    spesa_al = models.DateField(
        "fino al",
        null=True,
        blank=True,
        help_text="Vuoto: continua finché la decisione non è «Dismettere».",
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
            # Spesa ricorrente: importo, periodicità e prima spesa obbligatori.
            models.CheckConstraint(
                condition=Q(senza_contratto=False)
                | (
                    Q(spesa_importo__isnull=False, spesa_dal__isnull=False)
                    & ~Q(spesa_periodicita="")
                ),
                name="contratti_fabbisogno_spesa_completa",
            ),
            models.CheckConstraint(
                condition=Q(spesa_importo__isnull=True) | Q(spesa_importo__gte=0),
                name="contratti_fabbisogno_spesa_non_negativa",
            ),
            models.CheckConstraint(
                condition=Q(spesa_al__isnull=True)
                | Q(spesa_dal__isnull=True)
                | Q(spesa_al__gte=F("spesa_dal")),
                name="contratti_fabbisogno_spesa_periodo_coerente",
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


class Contratto(Archiviabile):
    """Singola istanza contrattuale; un rinnovo è un nuovo contratto sullo stesso fabbisogno."""

    class Finanziamento(models.TextChoices):
        ORDINARIO = "ordinario", "Ordinario"
        FINANZIATO = "finanziato", "Finanziato"

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
        """Finanziato se almeno una voce è su una WBS a progetto."""
        for v in self._voci_attive():
            if v.wbs_id and v.wbs.tipo == WBS.Tipo.PROGETTO:
                return self.Finanziamento.FINANZIATO
        return self.Finanziamento.ORDINARIO

    def clean(self):
        super().clean()
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
