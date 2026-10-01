"""Form dell'interfaccia operativa. Importi localizzati (1.234,56), date in formato ISO."""

from django import forms
from django.forms import inlineformset_factory

from contratti import models as m


class DataInput(forms.DateInput):
    input_type = "date"

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%d", **kwargs)


def interpreta_importo(testo: str) -> str:
    """Testo di un importo all'italiana o con il punto decimale → forma con il punto.

    "12.000,50" → "12000.50"; "12000,5" → "12000.5"; "12000.50" → "12000.50";
    "12.000" → "12000" (un solo punto seguito da 3 cifre = separatore delle migliaia).
    """
    s = testo.strip().replace(" ", "").replace("€", "").replace("\xa0", "")
    if "," in s:
        return s.replace(".", "").replace(",", ".")
    if s.count(".") > 1:
        return s.replace(".", "")
    if s.count(".") == 1 and len(s.split(".")[1]) == 3:
        return s.replace(".", "")
    return s


class ImportoField(forms.DecimalField):
    """Importo in campo di testo: accetta 1.234,56, 1234,56 e 1234.56; mostra 1.234,56."""

    widget = forms.TextInput

    def __init__(self, **kwargs):
        kwargs["localize"] = False
        super().__init__(**kwargs)
        self.widget.is_localized = True
        self.widget.attrs.setdefault("inputmode", "decimal")

    def widget_attrs(self, widget):
        attrs = super().widget_attrs(widget)
        for chiave in ("step", "min", "max"):
            attrs.pop(chiave, None)
        return attrs

    def to_python(self, value):
        if isinstance(value, str) and value.strip():
            value = interpreta_importo(value)
        return super().to_python(value)


def _come_importo(campo: forms.DecimalField) -> "ImportoField":
    return ImportoField(
        max_digits=campo.max_digits,
        decimal_places=campo.decimal_places,
        min_value=campo.min_value,
        max_value=campo.max_value,
        required=campo.required,
        label=campo.label,
        help_text=campo.help_text,
        initial=campo.initial,
    )


class FormBootstrap:
    """Classi Bootstrap su tutti i widget; importi come testo all'italiana."""

    def _stile(self):
        for nome, campo in list(self.fields.items()):
            if isinstance(campo, forms.DecimalField) and not isinstance(campo, ImportoField):
                campo = self.fields[nome] = _come_importo(campo)
            widget = campo.widget
            if isinstance(campo, forms.DateField):
                campo.widget = DataInput(attrs=widget.attrs)
                widget = campo.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", "form-check-input")
            elif isinstance(widget, forms.Select):
                widget.attrs.setdefault("class", "form-select")
            else:
                widget.attrs.setdefault("class", "form-control")


class ModelFormBootstrap(FormBootstrap, forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._stile()


class FormBase(FormBootstrap, forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._stile()


def _solo_attivi(form, campo, queryset):
    if campo in form.fields:
        form.fields[campo].queryset = queryset


class FornitoreForm(ModelFormBootstrap):
    class Meta:
        model = m.Fornitore
        fields = ["ragione_sociale", "partita_iva", "codice_sap", "note"]


class FabbisognoForm(ModelFormBootstrap):
    class Meta:
        model = m.Fabbisogno
        fields = [
            "descrizione",
            "area",
            "categoria",
            "impianto",
            "referente",
            "decisione",
            "stima_prossimo_importo",
            "note",
            "previsto_data_avvio",
            "previsto_durata_mesi",
            "previsto_procedura",
            "previsto_modalita",
            "previsto_periodicita",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _solo_attivi(self, "categoria", m.Categoria.objects.filter(attiva=True))
        _solo_attivi(self, "impianto", m.Impianto.objects.filter(archiviato=False))
        _solo_attivi(self, "previsto_procedura", m.Procedura.objects.filter(attiva=True))

    def clean(self):
        dati = super().clean()
        avvio, durata = dati.get("previsto_data_avvio"), dati.get("previsto_durata_mesi")
        if bool(avvio) != bool(durata):
            raise forms.ValidationError(
                "Per il previsto manuale servono insieme avvio e durata, oppure nessuno dei due."
            )
        return dati


CAMPI_CONTRATTO = [
    "fornitore",
    "descrizione",
    "numero_oda",
    "data_oda",
    "numero_rda",
    "cig",
    "procedura",
    "lead_time_mesi_override",
    "data_stipula",
    "data_inizio",
    "durata_mesi",
    "data_fine_override",
    "tacito_rinnovo",
    "preavviso_disdetta_giorni",
    "finanziamento",
    "progetto",
    "natura",
    "link_documenti",
    "note",
]


class ContrattoForm(ModelFormBootstrap):
    class Meta:
        model = m.Contratto
        fields = ["fabbisogno", *CAMPI_CONTRATTO]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _solo_attivi(self, "fabbisogno", m.Fabbisogno.objects.filter(archiviato=False))
        _solo_attivi(self, "fornitore", m.Fornitore.objects.filter(archiviato=False))
        _solo_attivi(self, "procedura", m.Procedura.objects.filter(attiva=True))
        _solo_attivi(self, "progetto", m.Progetto.objects.filter(archiviato=False))


class RinnovoForm(ContrattoForm):
    """Contratto successore: il fabbisogno e il predecessore li fissa la vista."""

    class Meta(ContrattoForm.Meta):
        fields = CAMPI_CONTRATTO


class VoceRinnovoForm(FormBase):
    origine = forms.IntegerField(widget=forms.HiddenInput)
    riporta = forms.BooleanField(required=False, initial=True, label="Riporta")
    descrizione = forms.CharField(max_length=250)
    importo_fisso = ImportoField(max_digits=14, decimal_places=2, min_value=0)
    massimale_variabile = ImportoField(max_digits=14, decimal_places=2, min_value=0, required=False)


VociRinnovoFormSet = forms.formset_factory(VoceRinnovoForm, extra=0)


class VoceForm(ModelFormBootstrap):
    class Meta:
        model = m.VoceContratto
        fields = [
            "descrizione",
            "proroga",
            "conto",
            "centro_costo",
            "wbs",
            "importo_fisso",
            "massimale_variabile",
            "stima_consumo_pct",
            "stima_consumo_importo",
        ]

    def __init__(self, *args, contratto, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["proroga"].queryset = contratto.proroghe.all()
        self.fields["conto"].queryset = m.ContoCoge.objects.all()

    def clean(self):
        dati = super().clean()
        if (
            dati.get("stima_consumo_pct") is not None
            and dati.get("stima_consumo_importo") is not None
        ):
            raise forms.ValidationError(
                "Indica la stima di consumo in % oppure in importo, non entrambe."
            )
        stima, massimale = dati.get("stima_consumo_importo"), dati.get("massimale_variabile")
        if stima is not None and massimale is not None and stima > massimale:
            self.add_error("stima_consumo_importo", "La stima non può superare il massimale.")
        return dati


class SceltaConDefault(forms.NullBooleanSelect):
    """Sì / No / vuoto = parametro di default."""

    def __init__(self, attrs=None):
        super().__init__(attrs)
        self.choices = [("unknown", "Default (parametro)"), ("true", "Sì"), ("false", "No")]


class PianoForm(ModelFormBootstrap):
    class Meta:
        model = m.PianoFatturazione
        fields = [
            "modalita",
            "periodicita",
            "data_prima_fattura",
            "giorni_pagamento",
            "pagamento_fine_mese",
            "note",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["pagamento_fine_mese"] = forms.NullBooleanField(
            required=False,
            label="Pagamento a fine mese",
            widget=SceltaConDefault(attrs={"class": "form-select"}),
        )

    def clean(self):
        dati = super().clean()
        if dati.get("modalita") in ("anticipata", "posticipata") and not dati.get("periodicita"):
            self.add_error(
                "periodicita", "Obbligatoria per la fatturazione anticipata o posticipata."
            )
        return dati


QuoteFormSet = inlineformset_factory(
    m.VoceContratto,
    m.QuotaPeriodo,
    fields=["dal", "al", "importo"],
    extra=1,
    can_delete=False,
    form=ModelFormBootstrap,
)


class RataForm(ModelFormBootstrap):
    class Meta:
        model = m.Rata
        fields = [
            "data_fattura",
            "data_pagamento_stimata",
            "importo",
            "consuntivo",
            "numero_fattura",
        ]


class ProrogaForm(FormBase):
    data_atto = forms.DateField(label="Data dell'atto")
    nuova_data_fine = forms.DateField(label="Nuova data di fine")
    riferimento = forms.CharField(max_length=200, required=False)
    note = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)
    importo_fisso = ImportoField(
        label="Importo della proroga (facoltativo)",
        max_digits=14,
        decimal_places=2,
        min_value=0,
        required=False,
    )
    descrizione_voce = forms.CharField(
        label="Descrizione della voce", max_length=250, required=False
    )
    modalita = forms.ChoiceField(
        label="Fatturazione", choices=m.ModalitaFatturazione.choices, initial="una_tantum"
    )
    periodicita = forms.ChoiceField(
        label="Periodicità", choices=[("", "—"), *m.Periodicita.choices], required=False
    )

    def clean(self):
        dati = super().clean()
        if dati.get("modalita") in ("anticipata", "posticipata") and not dati.get("periodicita"):
            self.add_error(
                "periodicita", "Obbligatoria per la fatturazione anticipata o posticipata."
            )
        return dati


class PassaggioPraticaForm(FormBase):
    stato = forms.ChoiceField(choices=m.StatoPratica.Stato.choices)
    data = forms.DateField()
    note = forms.CharField(widget=forms.TextInput, required=False)
