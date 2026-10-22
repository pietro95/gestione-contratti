"""Admin come strumento di back-office. Nessuna cancellazione fisica: si archivia."""

from django import forms
from django.contrib import admin, messages
from simple_history.admin import SimpleHistoryAdmin

from contratti import models as m


class SenzaCancellazione:
    """Niente delete, né dal dettaglio né dall'azione di massa."""

    def has_delete_permission(self, request, obj=None):
        return False

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions


@admin.action(description="Archivia i selezionati")
def archivia(modeladmin, request, queryset):
    # save() e non update(): la storia delle modifiche deve registrare l'archiviazione.
    count = 0
    for obj in queryset.filter(archiviato=False):
        obj.archiviato = True
        obj.save(update_fields=["archiviato"])
        count += 1
    modeladmin.message_user(request, f"Archiviati: {count}.", messages.SUCCESS)


@admin.action(description="Ripristina i selezionati")
def ripristina(modeladmin, request, queryset):
    count = 0
    for obj in queryset.filter(archiviato=True):
        obj.archiviato = False
        obj.save(update_fields=["archiviato"])
        count += 1
    modeladmin.message_user(request, f"Ripristinati: {count}.", messages.SUCCESS)


class BaseAdmin(SenzaCancellazione, SimpleHistoryAdmin):
    pass


class ArchiviabileAdmin(BaseAdmin):
    actions = [archivia, ripristina]


class InlineSenzaCancellazione(admin.TabularInline):
    extra = 0
    can_delete = False
    show_change_link = True


# --- Configurazione --------------------------------------------------------


@admin.register(m.Procedura)
class ProceduraAdmin(BaseAdmin):
    list_display = (
        "nome",
        "codice",
        "lead_time_mesi",
        "attiva",
        "per_fabbisogni",
        "provvisorio",
        "ordine",
    )
    list_editable = ("lead_time_mesi", "ordine")
    list_filter = ("attiva", "provvisorio")
    search_fields = ("nome", "codice")


@admin.register(m.Soglia)
class SogliaAdmin(BaseAdmin):
    list_display = ("descrizione", "codice", "importo", "valida_dal", "valida_al", "provvisorio")
    list_filter = ("codice", "provvisorio")


@admin.register(m.Parametro)
class ParametroAdmin(BaseAdmin):
    list_display = ("chiave", "valore", "valido_dal", "provvisorio")
    list_filter = ("chiave", "provvisorio")


@admin.register(m.AliquotaIVA)
class AliquotaIVAAdmin(BaseAdmin):
    list_display = ("aliquota", "descrizione", "attiva")
    list_filter = ("attiva",)


@admin.register(m.FonteFinanziamento)
class FonteFinanziamentoAdmin(BaseAdmin):
    list_display = ("nome", "attiva")
    list_filter = ("attiva",)
    search_fields = ("nome", "note")


@admin.register(m.Cluster)
class ClusterAdmin(ArchiviabileAdmin):
    list_display = ("codice", "nome", "archiviato")
    list_filter = ("archiviato",)
    search_fields = ("codice", "nome")


@admin.register(m.Sottocluster)
class SottoclusterAdmin(ArchiviabileAdmin):
    list_display = ("nome", "cluster", "owner", "archiviato")
    list_filter = ("cluster", "archiviato")
    search_fields = ("nome", "cluster__codice", "owner", "note")
    autocomplete_fields = ("cluster",)


@admin.register(m.BudgetSottocluster)
class BudgetSottoclusterAdmin(ArchiviabileAdmin):
    list_display = ("sottocluster", "anno", "natura", "importo", "archiviato")
    list_filter = ("anno", "natura", "sottocluster__cluster", "archiviato")
    search_fields = ("sottocluster__nome", "sottocluster__cluster__codice", "note")
    autocomplete_fields = ("sottocluster",)


@admin.register(m.CompetenzaDichiarata)
class CompetenzaDichiarataAdmin(ArchiviabileAdmin):
    list_display = ("fabbisogno", "anno", "natura", "importo", "archiviato")
    list_filter = ("anno", "natura", "fabbisogno__cluster", "archiviato")
    search_fields = ("fabbisogno__descrizione", "note")
    autocomplete_fields = ("fabbisogno",)


@admin.register(m.WBS)
class WBSAdmin(ArchiviabileAdmin):
    list_display = (
        "codice_wbs", "descrizione", "tipo", "cluster", "fonte_finanziamento", "archiviato",
    )  # fmt: skip
    list_filter = ("tipo", "cluster", "fonte_finanziamento", "archiviato")
    search_fields = ("codice_wbs", "descrizione")
    autocomplete_fields = ("cluster", "fonte_finanziamento")


@admin.register(m.AutorizzazioneExtraBudget)
class AutorizzazioneExtraBudgetAdmin(ArchiviabileAdmin):
    list_display = (
        "codice", "descrizione", "cluster", "protocollo", "data_autorizzazione",
        "importo_autorizzato", "archiviato",
    )  # fmt: skip
    list_filter = ("cluster", "archiviato")
    search_fields = ("codice", "descrizione", "protocollo")
    autocomplete_fields = ("cluster",)


class ContoCogeForm(forms.ModelForm):
    """Ogni conto appartiene ad almeno un cluster (SPEC §4): obbligatorio in amministrazione."""

    class Meta:
        model = m.ContoCoge
        fields = ["codice", "descrizione", "clusters", "valido_dal", "valido_al", "sostituito_da"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["clusters"].required = True


@admin.register(m.ContoCoge)
class ContoCogeAdmin(BaseAdmin):
    form = ContoCogeForm
    list_display = ("codice", "descrizione", "cluster_elenco", "valido_dal", "valido_al")
    list_filter = ("clusters",)
    search_fields = ("codice", "descrizione")
    autocomplete_fields = ("sostituito_da", "clusters")

    @admin.display(description="cluster")
    def cluster_elenco(self, conto):
        return ", ".join(c.codice for c in conto.clusters.all())


@admin.register(m.AssegnazioneCluster)
class AssegnazioneClusterAdmin(ArchiviabileAdmin):
    """Responsabili: l'Editor modifica solo i cluster assegnati (cluster vuoto = TUTTI).

    Per togliere un'assegnazione si archivia.
    """

    list_display = ("username", "cluster", "sottocluster", "note", "archiviato")
    list_filter = ("cluster", "archiviato")
    search_fields = ("username", "note")
    autocomplete_fields = ("cluster", "sottocluster")


@admin.register(m.FunzioneUtente)
class FunzioneUtenteAdmin(ArchiviabileAdmin):
    """Funzioni nel processo d'acquisto (Rev13): non danno permessi, decidono il cruscotto.

    Per togliere una funzione si archivia.
    """

    list_display = ("username", "funzione", "note", "archiviato")
    list_filter = ("funzione", "archiviato")
    search_fields = ("username", "note")


class TabellaSAPAdmin(BaseAdmin):
    """Codici SAP caricati da Excel (Gestione → Import «Tabelle SAP»): al più un predefinito."""

    list_display = ("codice", "descrizione", "predefinito", "attivo")
    list_filter = ("attivo", "predefinito")
    list_editable = ("attivo",)
    search_fields = ("codice", "descrizione")


@admin.register(m.RichiedenteSAP)
class RichiedenteSAPAdmin(TabellaSAPAdmin):
    list_display = ("codice", "descrizione", "gruppo_acquisti", "predefinito", "attivo")


admin.site.register(m.GruppoAcquisti, TabellaSAPAdmin)
admin.site.register(m.CentroCosto, TabellaSAPAdmin)


@admin.register(m.GruppoMerci)
class GruppoMerciAdmin(TabellaSAPAdmin):
    list_display = ("codice", "descrizione", "predefinito", "attivo")
    list_filter = ("attivo", "predefinito")


# --- Dominio ---------------------------------------------------------------


@admin.register(m.Fornitore)
class FornitoreAdmin(ArchiviabileAdmin):
    list_display = ("ragione_sociale", "nome_breve", "partita_iva", "codice_sap", "archiviato")
    list_filter = ("archiviato",)
    search_fields = ("ragione_sociale", "nome_breve", "partita_iva", "codice_sap")

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        altri = obj.fornitori_stesso_codice_sap()
        if altri.exists():
            nomi = ", ".join(altri.values_list("ragione_sociale", flat=True)[:5])
            self.message_user(
                request,
                f"Codice SAP {obj.codice_sap} usato anche da: {nomi}. Da verificare.",
                messages.WARNING,
            )


class StatoPraticaFabbisognoInline(InlineSenzaCancellazione):
    model = m.StatoPratica
    fk_name = "fabbisogno"
    fields = ("stato", "data", "note", "utente")
    autocomplete_fields = ("utente",)


class ContrattoInline(InlineSenzaCancellazione):
    model = m.Contratto
    fields = ("numero_contratto", "cig", "fornitore", "data_inizio", "durata_mesi", "archiviato")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(m.Fabbisogno)
class FabbisognoAdmin(ArchiviabileAdmin):
    list_display = ("descrizione", "cluster", "sottocluster", "decisione", "archiviato")
    list_filter = ("cluster", "sottocluster", "decisione", "archiviato")
    search_fields = ("descrizione", "referente", "note")
    autocomplete_fields = (
        "sottocluster",
        "fonte_finanziamento",
        "referente_utente",
        "previsto_procedura",
    )
    inlines = [ContrattoInline, StatoPraticaFabbisognoInline]
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "descrizione",
                    "cluster",
                    "sottocluster",
                    "fonte_finanziamento",
                )
            },
        ),
        ("Responsabilità", {"fields": ("referente", "referente_utente")}),
        ("Motivazione", {"fields": ("motivazione", "priorita", "tipo_acquisto", "fonte_stima")}),
        (
            "Continuità",
            {"fields": ("decisione", "una_tantum", "stima_prossimo_importo", "note")},
        ),
        (
            "Previsto manuale (fabbisogno senza contratti)",
            {
                "classes": ("collapse",),
                "fields": (
                    "previsto_data_avvio",
                    "previsto_durata_mesi",
                    "previsto_procedura",
                    "previsto_modalita",
                    "previsto_periodicita",
                ),
            },
        ),
        ("Stato", {"fields": ("archiviato",)}),
    )


class VoceInline(InlineSenzaCancellazione):
    model = m.VoceContratto
    fields = (
        "descrizione",
        "proroga",
        "natura",
        "conto",
        "wbs",
        "importo_fisso",
        "massimale_variabile",
        "stima_consumo_pct",
        "stima_consumo_importo",
        "archiviato",
    )
    autocomplete_fields = ("conto", "wbs")


class OpzioneInline(InlineSenzaCancellazione):
    model = m.OpzioneContratto
    fields = ("tipo", "mesi", "importo", "note")
    show_change_link = False


class ProrogaInline(InlineSenzaCancellazione):
    model = m.Proroga
    fields = ("data_atto", "nuova_data_fine", "riferimento", "note")


class StatoPraticaContrattoInline(InlineSenzaCancellazione):
    model = m.StatoPratica
    fk_name = "contratto"
    fields = ("stato", "data", "note", "utente")
    autocomplete_fields = ("utente",)


class FatturaInline(InlineSenzaCancellazione):
    model = m.Fattura
    fields = (
        "numero", "data", "importo_documento", "valore_base", "voce", "rata",
        "data_registrazione", "data_trasferimento", "archiviato",
    )  # fmt: skip
    raw_id_fields = ("voce", "rata")


class DocumentoEsecuzioneInline(InlineSenzaCancellazione):
    model = m.DocumentoEsecuzione
    fields = ("tipo", "numero", "data", "importo", "finale", "fattura", "archiviato")
    raw_id_fields = ("fattura",)


@admin.register(m.Contratto)
class ContrattoAdmin(ArchiviabileAdmin):
    list_display = (
        "__str__",
        "fornitore",
        "procedura",
        "data_inizio",
        "durata_mesi",
        "natura",
        "archiviato",
    )
    list_filter = ("fabbisogno__cluster", "procedura", "voci__natura", "archiviato")
    search_fields = (
        "fabbisogno__descrizione",
        "descrizione",
        "numero_contratto",
        "numero_rda",
        "cig",
        "fornitore__ragione_sociale",
    )
    autocomplete_fields = (
        "fabbisogno", "predecessore", "fornitore", "procedura", "rda", "chiuso_da",
    )  # fmt: skip
    date_hierarchy = "data_inizio"
    inlines = [
        VoceInline,
        OpzioneInline,
        ProrogaInline,
        StatoPraticaContrattoInline,
        FatturaInline,
        DocumentoEsecuzioneInline,
    ]
    fieldsets = (
        (None, {"fields": ("fabbisogno", "predecessore", "fornitore", "descrizione")}),
        ("Riferimenti", {"fields": ("numero_contratto", "data_emissione", "numero_rda", "cig")}),
        ("Procedura", {"fields": ("procedura", "lead_time_mesi_override")}),
        (
            "Date",
            {"fields": ("data_stipula", "data_inizio", "durata_mesi", "data_fine_override")},
        ),
        (
            "Rinnovo",
            {
                "fields": (
                    "tacito_rinnovo",
                    "preavviso_disdetta_giorni",
                    "una_tantum",
                    "tipo_acquisto",
                )
            },
        ),
        ("Processo d'acquisto", {"fields": ("rda", "rup", "cup", "data_chiusura", "chiuso_da")}),
        (
            "Documenti e note",
            {"fields": ("link_documenti", "percorso_documenti", "note", "archiviato")},
        ),
    )


class PosizioneRDAInline(InlineSenzaCancellazione):
    model = m.PosizioneRDA
    fields = (
        "numero", "descrizione_breve", "gruppo_merci", "quantita", "importo_unitario",
        "di_cui_variabile", "natura", "conto", "centro_costo", "wbs",
    )  # fmt: skip
    autocomplete_fields = ("gruppo_merci", "conto", "wbs")
    show_change_link = False


class EventoRDAInline(InlineSenzaCancellazione):
    model = m.EventoRDA
    fields = ("tipo", "data", "nota", "utente")
    autocomplete_fields = ("utente",)
    show_change_link = False


@admin.register(m.RichiestaAcquisto)
class RichiestaAcquistoAdmin(ArchiviabileAdmin):
    """RDA: la fase non si salva, la ricava il motore (SPEC §5.7)."""

    list_display = (
        "__str__", "descrizione", "cluster", "nome_referente", "fase", "data_creazione",
        "archiviato",
    )  # fmt: skip
    list_filter = ("cluster", "origine", "scopo", "archiviato")
    search_fields = ("numero_rda", "descrizione", "intestazione", "referente")
    autocomplete_fields = (
        "cluster", "fabbisogno", "contratto_in_scadenza", "referente_utente",
        "fornitore_proposto", "richiedente", "gruppo_acquisti",
    )  # fmt: skip
    inlines = [PosizioneRDAInline, EventoRDAInline]
    fieldsets = (
        (None, {"fields": ("origine", "scopo", "cluster", "fabbisogno", "contratto_in_scadenza")}),
        ("Referente", {"fields": ("referente_utente", "referente")}),
        (
            "Richiesta",
            {
                "fields": (
                    "descrizione",
                    "intestazione",
                    "fornitore_proposto",
                    "richiedente",
                    "gruppo_acquisti",
                    "note_buyer",
                    "allegati",
                    "percorso_file_server",
                    "rup",
                    "cup",
                    "note",
                    "data_creazione",
                )  # fmt: skip
            },
        ),
        ("Da SAP", {"fields": ("numero_rda", "data_inserimento", "data_rilascio")}),
        (None, {"fields": ("archiviato",)}),
    )

    @admin.display(description="fase")
    def fase(self, obj):
        from contratti import acquisti
        from contratti.engine.acquisti import ETICHETTE_FASE

        return ETICHETTE_FASE[acquisti.fase(obj)]


@admin.register(m.Fattura)
class FatturaAdmin(ArchiviabileAdmin):
    list_display = (
        "numero", "data", "importo_documento", "valore_base", "fornitore", "contratto",
        "referente", "esito_convalida", "fuori_registro", "archiviato",
    )  # fmt: skip
    list_filter = ("esito_convalida", "fuori_registro", "archiviato")
    search_fields = ("numero", "contratto__numero_contratto", "fornitore__ragione_sociale")
    autocomplete_fields = ("contratto", "fornitore", "referente")
    raw_id_fields = ("voce", "rata")
    date_hierarchy = "data"


@admin.register(m.Stanziamento)
class StanziamentoAdmin(ArchiviabileAdmin):
    list_display = (
        "voce", "competenza_dal", "competenza_al", "importo", "rata", "fattura", "archiviato",
    )  # fmt: skip
    list_filter = ("archiviato",)
    search_fields = ("voce__contratto__numero_contratto", "voce__descrizione")
    raw_id_fields = ("voce", "rata", "fattura")


@admin.register(m.DocumentoEsecuzione)
class DocumentoEsecuzioneAdmin(ArchiviabileAdmin):
    list_display = ("tipo", "numero", "data", "contratto", "fattura", "finale", "archiviato")
    list_filter = ("tipo", "finale", "archiviato")
    search_fields = ("numero", "contratto__numero_contratto")
    autocomplete_fields = ("contratto",)
    raw_id_fields = ("voce", "fattura")


@admin.register(m.Proroga)
class ProrogaAdmin(BaseAdmin):
    list_display = ("contratto", "data_atto", "nuova_data_fine", "riferimento")
    search_fields = ("contratto__numero_contratto", "contratto__cig", "riferimento")
    autocomplete_fields = ("contratto",)


class QuotaInline(InlineSenzaCancellazione):
    model = m.QuotaPeriodo
    fields = ("dal", "al", "importo")
    show_change_link = False


class PianoInline(admin.StackedInline):
    model = m.PianoFatturazione
    extra = 0
    can_delete = False


@admin.register(m.VoceContratto)
class VoceContrattoAdmin(ArchiviabileAdmin):
    list_display = (
        "descrizione", "contratto", "natura", "conto", "wbs", "importo_fisso",
        "massimale_variabile",
    )  # fmt: skip
    list_filter = ("archiviato", "natura", "piano_fatturazione__modalita")
    search_fields = ("descrizione", "contratto__numero_contratto", "contratto__cig")
    autocomplete_fields = (
        "contratto", "proroga", "conto", "wbs", "conto_rinnovi", "wbs_rinnovi",
    )  # fmt: skip
    inlines = [QuotaInline, PianoInline]


class RataInline(InlineSenzaCancellazione):
    model = m.Rata
    fields = (
        "numero",
        "data_fattura",
        "data_pagamento_stimata",
        "importo",
        "consuntivo",
        "numero_fattura",
        "modificata_manualmente",
    )
    readonly_fields = ("modificata_manualmente",)
    show_change_link = False


def marca_rate_modificate(formset):
    """Una rata aggiunta o cambiata a mano dall'admin è marcata come modificata."""
    for form in formset.forms:
        if form.has_changed():
            form.instance.modificata_manualmente = True


@admin.register(m.PianoFatturazione)
class PianoFatturazioneAdmin(BaseAdmin):
    list_display = ("voce", "modalita", "periodicita", "data_prima_fattura")
    list_filter = ("modalita", "periodicita")
    search_fields = ("voce__descrizione", "voce__contratto__numero_contratto")
    autocomplete_fields = ("voce",)
    inlines = [RataInline]

    def save_formset(self, request, form, formset, change):
        if formset.model is m.Rata:
            marca_rate_modificate(formset)
        super().save_formset(request, form, formset, change)


@admin.register(m.Rata)
class RataAdmin(BaseAdmin):
    list_display = (
        "piano",
        "numero",
        "data_fattura",
        "data_pagamento_stimata",
        "importo",
        "consuntivo",
        "modificata_manualmente",
    )
    list_filter = ("consuntivo", "modificata_manualmente")
    readonly_fields = ("modificata_manualmente",)
    autocomplete_fields = ("piano",)
    date_hierarchy = "data_fattura"

    def save_model(self, request, obj, form, change):
        if form.has_changed():
            obj.modificata_manualmente = True
        super().save_model(request, obj, form, change)


# --- Proposte dell'import (si confermano a mano) ---------------------------------


def _applica(modeladmin, request, queryset, funzione, etichetta):
    from contratti.importer.proposte import PropostaNonApplicabile

    ok = 0
    for proposta in queryset:
        try:
            funzione(proposta)
            ok += 1
        except PropostaNonApplicabile as exc:
            modeladmin.message_user(request, f"{proposta}: {exc}", messages.ERROR)
    if ok:
        modeladmin.message_user(request, f"{etichetta}: {ok}.", messages.SUCCESS)


@admin.action(description="Conferma le proposte selezionate")
def conferma_raggruppamenti(modeladmin, request, queryset):
    from contratti.importer.proposte import conferma_raggruppamento

    _applica(modeladmin, request, queryset, conferma_raggruppamento, "Confermate")


@admin.action(description="Conferma le proposte selezionate")
def conferma_predecessori(modeladmin, request, queryset):
    from contratti.importer.proposte import conferma_predecessore

    _applica(modeladmin, request, queryset, conferma_predecessore, "Confermate")


@admin.action(description="Scarta le proposte selezionate")
def scarta_proposte(modeladmin, request, queryset):
    from contratti.importer.proposte import scarta

    _applica(modeladmin, request, queryset, scarta, "Scartate")


@admin.register(m.PropostaRaggruppamento)
class PropostaRaggruppamentoAdmin(BaseAdmin):
    list_display = ("motivazione", "stato", "creata_il")
    list_filter = ("stato",)
    search_fields = ("motivazione",)
    readonly_fields = ("motivazione", "contratti", "stato", "creata_il")
    actions = [conferma_raggruppamenti, scarta_proposte]

    def has_add_permission(self, request):
        return False


@admin.register(m.PropostaPredecessore)
class PropostaPredecessoreAdmin(BaseAdmin):
    list_display = ("motivazione", "predecessore", "successore", "stato")
    list_filter = ("stato",)
    search_fields = ("motivazione",)
    readonly_fields = ("predecessore", "successore", "motivazione", "stato", "creata_il")
    actions = [conferma_predecessori, scarta_proposte]

    def has_add_permission(self, request):
        return False


@admin.register(m.StatoPratica)
class StatoPraticaAdmin(BaseAdmin):
    list_display = ("__str__", "contratto", "fabbisogno", "utente", "registrato_il")
    list_filter = ("stato",)
    autocomplete_fields = ("contratto", "fabbisogno", "utente")

    def save_model(self, request, obj, form, change):
        if not change and obj.utente_id is None:
            obj.utente = request.user
        super().save_model(request, obj, form, change)


@admin.register(m.Importazione)
class ImportazioneAdmin(admin.ModelAdmin):
    """Registro degli import: in sola lettura, il file e l'esito restano come sono."""

    list_display = ("caricata_il", "tipo", "nome_file", "utente", "stato")
    list_filter = ("tipo", "stato")
    search_fields = ("nome_file", "utente__username")
    exclude = ("contenuto", "risultato")
    readonly_fields = (
        "tipo", "nome_file", "sha256", "dimensione", "opzioni", "stato", "anteprima", "esito",
        "messaggio", "utente", "caricata_il", "confermata_il", "confermata_da",
    )  # fmt: skip

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
