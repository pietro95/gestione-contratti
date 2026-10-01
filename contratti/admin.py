"""Admin come strumento di back-office. Nessuna cancellazione fisica: si archivia."""

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
    list_display = ("nome", "codice", "lead_time_mesi", "attiva", "provvisorio", "ordine")
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


@admin.register(m.Categoria)
class CategoriaAdmin(BaseAdmin):
    list_display = ("nome", "attiva")
    list_filter = ("attiva",)
    search_fields = ("nome",)


@admin.register(m.Impianto)
class ImpiantoAdmin(ArchiviabileAdmin):
    list_display = ("nome", "archiviato")
    list_filter = ("archiviato",)
    search_fields = ("nome",)


@admin.register(m.Progetto)
class ProgettoAdmin(ArchiviabileAdmin):
    list_display = ("codice_wbs", "descrizione", "archiviato")
    list_filter = ("archiviato",)
    search_fields = ("codice_wbs", "descrizione")


@admin.register(m.ContoCoge)
class ContoCogeAdmin(BaseAdmin):
    list_display = ("codice", "descrizione", "valido_dal", "valido_al", "sostituito_da")
    search_fields = ("codice", "descrizione")
    autocomplete_fields = ("sostituito_da",)


# --- Dominio ---------------------------------------------------------------


@admin.register(m.Fornitore)
class FornitoreAdmin(ArchiviabileAdmin):
    list_display = ("ragione_sociale", "partita_iva", "codice_sap", "archiviato")
    list_filter = ("archiviato",)
    search_fields = ("ragione_sociale", "partita_iva", "codice_sap")

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
    fields = ("numero_oda", "cig", "fornitore", "data_inizio", "durata_mesi", "archiviato")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(m.Fabbisogno)
class FabbisognoAdmin(ArchiviabileAdmin):
    list_display = ("descrizione", "area", "categoria", "decisione", "impianto", "archiviato")
    list_filter = ("area", "categoria", "decisione", "impianto", "archiviato")
    search_fields = ("descrizione", "referente", "note")
    autocomplete_fields = ("categoria", "impianto", "referente_utente", "previsto_procedura")
    inlines = [ContrattoInline, StatoPraticaFabbisognoInline]
    fieldsets = (
        (None, {"fields": ("descrizione", "area", "categoria", "impianto")}),
        ("Responsabilità", {"fields": ("referente", "referente_utente")}),
        ("Continuità", {"fields": ("decisione", "stima_prossimo_importo", "note")}),
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
        "conto",
        "importo_fisso",
        "massimale_variabile",
        "stima_consumo_pct",
        "stima_consumo_importo",
        "archiviato",
    )
    autocomplete_fields = ("conto",)


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


@admin.register(m.Contratto)
class ContrattoAdmin(ArchiviabileAdmin):
    list_display = (
        "__str__",
        "fornitore",
        "procedura",
        "data_inizio",
        "durata_mesi",
        "finanziamento",
        "natura",
        "archiviato",
    )
    list_filter = ("fabbisogno__area", "procedura", "finanziamento", "natura", "archiviato")
    search_fields = (
        "fabbisogno__descrizione",
        "descrizione",
        "numero_oda",
        "numero_rda",
        "cig",
        "fornitore__ragione_sociale",
    )
    autocomplete_fields = ("fabbisogno", "predecessore", "fornitore", "procedura", "progetto")
    date_hierarchy = "data_inizio"
    inlines = [VoceInline, OpzioneInline, ProrogaInline, StatoPraticaContrattoInline]
    fieldsets = (
        (None, {"fields": ("fabbisogno", "predecessore", "fornitore", "descrizione")}),
        ("Riferimenti", {"fields": ("numero_oda", "data_oda", "numero_rda", "cig")}),
        ("Procedura", {"fields": ("procedura", "lead_time_mesi_override")}),
        (
            "Date",
            {"fields": ("data_stipula", "data_inizio", "durata_mesi", "data_fine_override")},
        ),
        ("Rinnovo", {"fields": ("tacito_rinnovo", "preavviso_disdetta_giorni")}),
        ("Classificazione", {"fields": ("finanziamento", "progetto", "natura")}),
        ("Documenti e note", {"fields": ("link_documenti", "note", "archiviato")}),
    )


@admin.register(m.Proroga)
class ProrogaAdmin(BaseAdmin):
    list_display = ("contratto", "data_atto", "nuova_data_fine", "riferimento")
    search_fields = ("contratto__numero_oda", "contratto__cig", "riferimento")
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
    list_display = ("descrizione", "contratto", "conto", "importo_fisso", "massimale_variabile")
    list_filter = ("archiviato", "piano_fatturazione__modalita")
    search_fields = ("descrizione", "contratto__numero_oda", "contratto__cig")
    autocomplete_fields = ("contratto", "proroga", "conto")
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
    search_fields = ("voce__descrizione", "voce__contratto__numero_oda")
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


@admin.register(m.StatoPratica)
class StatoPraticaAdmin(BaseAdmin):
    list_display = ("__str__", "contratto", "fabbisogno", "utente", "registrato_il")
    list_filter = ("stato",)
    autocomplete_fields = ("contratto", "fabbisogno", "utente")

    def save_model(self, request, obj, form, change):
        if not change and obj.utente_id is None:
            obj.utente = request.user
        super().save_model(request, obj, form, change)
