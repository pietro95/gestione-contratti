"""Form dell'interfaccia operativa. Importi localizzati (1.234,56), date in formato ISO."""

from django import forms
from django.db.models import Q
from django.forms import inlineformset_factory

from contratti import adapters, permessi
from contratti import models as m
from contratti.engine import scadenze

# Date scritte gg/mm/aaaa (calendario flatpickr nel browser); si accetta anche aaaa-mm-gg.
FORMATI_DATA = ["%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y"]


class DataInput(forms.DateInput):
    input_type = "text"

    def __init__(self, attrs=None, **kwargs):
        base = {"placeholder": "gg/mm/aaaa", "autocomplete": "off", "inputmode": "numeric"}
        attrs = {**base, **(attrs or {})}
        classi = set(attrs.get("class", "form-control").split()) | {"form-control", "js-data"}
        attrs["class"] = " ".join(sorted(classi))
        super().__init__(attrs=attrs, format="%d/%m/%Y", **kwargs)


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
    """Classi Bootstrap su tutti i widget; importi come testo all'italiana; date gg/mm/aaaa.

    ``sezioni``: [(titolo, [nomi dei campi])] per raggruppare i campi nel form; i campi non
    elencati finiscono in una sezione finale.
    """

    sezioni: list[tuple[str, list[str]]] = []

    def gruppi(self):
        visibili = {b.name: b for b in self.visible_fields()}
        if not self.sezioni:
            return [(None, list(visibili.values()))]
        risultato, usati = [], set()
        for titolo, nomi in self.sezioni:
            campi = [visibili[n] for n in nomi if n in visibili]
            usati.update(b.name for b in campi)
            if campi:
                risultato.append((titolo, campi))
        resto = [b for n, b in visibili.items() if n not in usati]
        if resto:
            risultato.append(("Altri dati", resto))
        return risultato

    def full_clean(self):
        super().full_clean()
        for nome in self.errors:
            if nome in self.fields:
                widget = self.fields[nome].widget
                classi = widget.attrs.get("class", "")
                if "is-invalid" not in classi:
                    widget.attrs["class"] = f"{classi} is-invalid".strip()

    def _stile(self):
        for nome, campo in list(self.fields.items()):
            if isinstance(campo, forms.DecimalField) and not isinstance(campo, ImportoField):
                campo = self.fields[nome] = _come_importo(campo)
            widget = campo.widget
            if isinstance(campo, forms.DateField):
                campo.widget = DataInput(attrs=widget.attrs)
                campo.input_formats = FORMATI_DATA
                widget = campo.widget
            if isinstance(widget, forms.Textarea) and str(widget.attrs.get("rows", "10")) == "10":
                widget.attrs["rows"] = 3  # il default di Django (10 righe) è troppo alto
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
    solo_spesa = False  # True nelle scorciatoie della spesa senza contratto (sotto)
    sezioni = [
        ("Fabbisogno", ["descrizione", "cluster", "categoria", "impianto", "referente"]),
        ("Decisione sul rinnovo", ["decisione", "stima_prossimo_importo", "note"]),
        (
            "Previsto manuale (solo per fabbisogni nuovi, senza contratti)",
            [
                "previsto_data_avvio",
                "previsto_durata_mesi",
                "previsto_procedura",
                "previsto_modalita",
                "previsto_periodicita",
            ],
        ),
        (
            "Spesa ricorrente senza contratto",
            [
                "senza_contratto",
                "spesa_fornitore",
                "spesa_importo",
                "spesa_periodicita",
                "spesa_dal",
                "spesa_al",
            ],
        ),
        (
            "Classificazione del previsto manuale o della spesa senza contratto",
            ["natura_previsti", "conto_previsti", "wbs_previsti"],
        ),
    ]

    class Meta:
        model = m.Fabbisogno
        fields = [
            "descrizione",
            "cluster",
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
            "natura_previsti",
            "conto_previsti",
            "wbs_previsti",
            "senza_contratto",
            "spesa_fornitore",
            "spesa_importo",
            "spesa_periodicita",
            "spesa_dal",
            "spesa_al",
        ]

    def __init__(self, *args, utente=None, **kwargs):
        super().__init__(*args, **kwargs)
        cluster = m.Cluster.objects.filter(archiviato=False)
        if utente is not None and (ammessi := permessi.cluster_modificabili(utente)) is not None:
            cluster = cluster.filter(pk__in=ammessi)  # solo i propri cluster (F9.2)
        _solo_attivi(self, "cluster", cluster)
        _solo_attivi(self, "categoria", m.Categoria.objects.filter(attiva=True))
        _solo_attivi(self, "impianto", m.Impianto.objects.filter(archiviato=False))
        _solo_attivi(self, "previsto_procedura", m.Procedura.objects.filter(attiva=True))
        _solo_attivi(self, "wbs_previsti", m.WBS.objects.filter(archiviato=False))
        _solo_attivi(self, "spesa_fornitore", m.Fornitore.objects.filter(archiviato=False))

    def clean(self):
        dati = super().clean()
        avvio, durata = dati.get("previsto_data_avvio"), dati.get("previsto_durata_mesi")
        if bool(avvio) != bool(durata):
            raise forms.ValidationError(
                "Per il previsto manuale servono insieme avvio e durata, oppure nessuno dei due."
            )
        cluster = dati.get("cluster")
        if cluster is None and self.instance.cluster_id:
            cluster = self.instance.cluster  # le scorciatoie della spesa non hanno il cluster
        verifica_natura_wbs(
            self, dati.get("natura_previsti") or m.Natura.OPEX, "wbs_previsti", cluster
        )
        if dati.get("senza_contratto") or self.solo_spesa:
            for campo in ("spesa_importo", "spesa_periodicita", "spesa_dal"):
                if dati.get(campo) in (None, ""):
                    self.add_error(campo, "Obbligatorio per una spesa senza contratto.")
            if avvio:
                self.add_error(
                    "previsto_data_avvio",
                    "Una spesa senza contratto non ha previsto manuale: lascia vuoto.",
                )
            if self.instance.pk and (dal := dati.get("spesa_dal")):
                for c in self.instance.contratti.filter(archiviato=False).prefetch_related(
                    "proroghe"
                ):
                    s = adapters.scadenza(c)
                    fine = scadenze.data_fine_effettiva(s) if s else None
                    if fine is None or fine >= dal:
                        self.add_error(
                            "spesa_dal",
                            f"Il contratto {c} finisce il "
                            f"{fine:%d/%m/%Y}: la prima spesa deve essere dopo."
                            if fine
                            else f"Il contratto {c} non ha date: completalo o archivialo.",
                        )
                        break
        return dati


CAMPI_SPESA = ["spesa_fornitore", "spesa_importo", "spesa_periodicita", "spesa_dal", "spesa_al"]
CAMPI_CLASSIFICAZIONE = ["natura_previsti", "conto_previsti", "wbs_previsti"]


class _SpesaMixin:
    """Scorciatoie per la spesa senza contratto: il fabbisogno si aggiorna da solo (§5.6).

    Il fabbisogno diventa «senza contratto» con decisione «Rinnovare» (la spesa prosegue);
    un previsto manuale si toglie, perché la spesa lo sostituisce.
    """

    solo_spesa = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in ("spesa_importo", "spesa_periodicita", "spesa_dal"):
            self.fields[campo].required = True
        self.fields["natura_previsti"].label = "Natura"
        self.fields["conto_previsti"].label = "Conto COGE"
        self.fields["wbs_previsti"].label = "WBS"
        self.fields["wbs_previsti"].help_text = "Obbligatoria se la spesa è CAPEX."

    def save(self, commit=True):
        f = super().save(commit=False)
        f.senza_contratto = True
        f.decisione = m.Fabbisogno.Decisione.RINNOVARE
        f.previsto_data_avvio = f.previsto_durata_mesi = None
        if commit:
            f.save()
        return f


class SpesaForm(_SpesaMixin, FabbisognoForm):
    """Spesa senza contratto su un fabbisogno esistente (anche «Rinnova senza contratto»)."""

    sezioni = [
        ("Spesa", CAMPI_SPESA),
        ("Classificazione", CAMPI_CLASSIFICAZIONE),
    ]

    class Meta(FabbisognoForm.Meta):
        fields = CAMPI_SPESA + CAMPI_CLASSIFICAZIONE


class SpesaNuovaForm(_SpesaMixin, FabbisognoForm):
    """Nuova spesa senza contratto: crea il fabbisogno con i soli dati necessari."""

    sezioni = [
        ("Fabbisogno", ["descrizione", "cluster", "categoria", "impianto", "referente"]),
        ("Spesa", CAMPI_SPESA),
        ("Classificazione", CAMPI_CLASSIFICAZIONE),
    ]

    class Meta(FabbisognoForm.Meta):
        fields = (
            ["descrizione", "cluster", "categoria", "impianto", "referente"]
            + CAMPI_SPESA
            + CAMPI_CLASSIFICAZIONE
        )


CAMPI_CONTRATTO = [
    "fornitore",
    "descrizione",
    "numero_contratto",
    "data_emissione",
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
    "link_documenti",
    "note",
]


class ContrattoForm(ModelFormBootstrap):
    sezioni = [
        ("Oggetto e fornitore", ["fabbisogno", "fornitore", "descrizione"]),
        (
            "Ordine e procedura",
            [
                "numero_contratto",
                "data_emissione",
                "numero_rda",
                "cig",
                "procedura",
                "lead_time_mesi_override",
            ],
        ),
        (
            "Durata",
            [
                "data_stipula",
                "data_inizio",
                "durata_mesi",
                "data_fine_override",
                "tacito_rinnovo",
                "preavviso_disdetta_giorni",
            ],
        ),
        ("Documenti e note", ["link_documenti", "note"]),
    ]

    class Meta:
        model = m.Contratto
        fields = ["fabbisogno", *CAMPI_CONTRATTO]

    def __init__(self, *args, utente=None, **kwargs):
        super().__init__(*args, **kwargs)
        fabbisogni = m.Fabbisogno.objects.filter(archiviato=False)
        if utente is not None:
            fabbisogni = permessi.fabbisogni_modificabili(utente, fabbisogni)
        _solo_attivi(self, "fabbisogno", fabbisogni)
        _solo_attivi(self, "fornitore", m.Fornitore.objects.filter(archiviato=False))
        _solo_attivi(self, "procedura", m.Procedura.objects.filter(attiva=True))


class ContrattoModificaForm(ContrattoForm):
    """Modifica: il fabbisogno si cambia solo con "Sposta", che tiene coerente la catena."""

    class Meta(ContrattoForm.Meta):
        fields = CAMPI_CONTRATTO


class SceltaFabbisognoForm(FormBase):
    """Fabbisogno di destinazione per spostare un contratto o accorpare un fabbisogno."""

    destinazione = forms.ModelChoiceField(
        queryset=m.Fabbisogno.objects.none(), label="Fabbisogno di destinazione"
    )

    def __init__(self, *args, escludi: m.Fabbisogno, utente=None, **kwargs):
        super().__init__(*args, **kwargs)
        campo = self.fields["destinazione"]
        destinazioni = m.Fabbisogno.objects.filter(archiviato=False)
        if utente is not None:  # tra cluster diversi serve il permesso su entrambi
            destinazioni = permessi.fabbisogni_modificabili(utente, destinazioni)
        campo.queryset = (
            destinazioni.exclude(pk=escludi.pk)
            .select_related("categoria")
            .order_by("cluster__codice", "descrizione")
        )
        campo.widget.attrs["class"] = campo.widget.attrs.get("class", "") + " js-cerca"


class SpostaContrattoForm(SceltaFabbisognoForm):
    con_successivi = forms.BooleanField(required=False)

    def __init__(self, *args, contratto: m.Contratto, n_successivi: int, utente=None, **kwargs):
        super().__init__(*args, escludi=contratto.fabbisogno, utente=utente, **kwargs)
        if n_successivi:
            self.fields[
                "con_successivi"
            ].label = f"Sposta anche i rinnovi successivi ({n_successivi})"
        else:
            del self.fields["con_successivi"]


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


def wbs_ammesse(cluster: m.Cluster | None):
    """WBS selezionabili: quelle del cluster e quelle a progetto (attive)."""
    qs = m.WBS.objects.filter(archiviato=False).select_related("cluster")
    if cluster is None:
        return qs
    return qs.filter(Q(tipo=m.WBS.Tipo.PROGETTO) | Q(cluster=cluster))


def verifica_natura_wbs(form, natura: str, campo_wbs: str, cluster=None) -> None:
    """CAPEX ⇔ WBS; una WBS di cluster deve essere del cluster del fabbisogno (F9.2)."""
    wbs = form.cleaned_data.get(campo_wbs)
    if natura == m.Natura.CAPEX and wbs is None:
        form.add_error(campo_wbs, "Una spesa CAPEX sta sempre su una WBS.")
    elif natura == m.Natura.OPEX and wbs is not None:
        form.add_error(campo_wbs, "Una spesa OPEX non ha WBS: lascia vuoto o scegli CAPEX.")
    elif (
        wbs is not None
        and cluster is not None
        and wbs.tipo == m.WBS.Tipo.CLUSTER
        and wbs.cluster_id != cluster.pk
    ):
        form.add_error(campo_wbs, f"La WBS {wbs.codice_wbs} è di un altro cluster.")


class VoceForm(ModelFormBootstrap):
    sezioni = [
        ("Voce", ["descrizione", "proroga"]),
        ("Contabilità", ["natura", "conto", "centro_costo", "wbs"]),
        (
            "Importi",
            ["importo_fisso", "massimale_variabile", "stima_consumo_pct", "stima_consumo_importo"],
        ),
        (
            "Nei rinnovi previsti (solo se cambia, es. nata CAPEX e rinnovata in OPEX)",
            ["natura_rinnovi", "conto_rinnovi", "wbs_rinnovi"],
        ),
    ]

    class Meta:
        model = m.VoceContratto
        fields = [
            "descrizione",
            "proroga",
            "natura",
            "conto",
            "centro_costo",
            "wbs",
            "importo_fisso",
            "massimale_variabile",
            "stima_consumo_pct",
            "stima_consumo_importo",
            "natura_rinnovi",
            "conto_rinnovi",
            "wbs_rinnovi",
        ]

    def __init__(self, *args, contratto, **kwargs):
        super().__init__(*args, **kwargs)
        self.cluster = contratto.fabbisogno.cluster
        self.fields["proroga"].queryset = contratto.proroghe.all()
        self.fields["conto"].queryset = m.ContoCoge.objects.all()
        self.fields["conto_rinnovi"].queryset = m.ContoCoge.objects.all()
        for campo in ("wbs", "wbs_rinnovi"):
            self.fields[campo].queryset = wbs_ammesse(self.cluster)
        self.fields["natura_rinnovi"].choices = [("", "Come questa voce"), *m.Natura.choices]

    def clean(self):
        dati = super().clean()
        natura = dati.get("natura") or m.Natura.OPEX
        verifica_natura_wbs(self, natura, "wbs", self.cluster)
        con_cluster = permessi.conti_per_cluster()
        for campo in ("conto", "conto_rinnovi"):
            conto = dati.get(campo)
            if conto is None:
                continue
            if conto.cluster_id and self.cluster and conto.cluster_id != self.cluster.pk:
                self.add_error(
                    campo, f"Il conto {conto.codice} è del cluster {conto.cluster.codice}."
                )
            elif conto.cluster_id is None and con_cluster:
                self.add_error(
                    campo,
                    f"Il conto {conto.codice} non ha un cluster: completalo con l'import "
                    "della struttura o in amministrazione.",
                )
        rinnovi = dati.get("natura_rinnovi") or natura
        wbs_rinnovi = dati.get("wbs_rinnovi")
        if rinnovi == m.Natura.OPEX and wbs_rinnovi is not None:
            self.add_error("wbs_rinnovi", "Rinnovi in OPEX: nessuna WBS.")
        elif rinnovi == m.Natura.CAPEX and natura == m.Natura.OPEX and wbs_rinnovi is None:
            self.add_error("wbs_rinnovi", "Rinnovi in CAPEX: indica la WBS su cui andranno.")
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
    sezioni = [
        (
            "Piano di fatturazione",
            [
                "modalita",
                "periodicita",
                "data_prima_fattura",
                "giorni_pagamento",
                "pagamento_fine_mese",
                "note",
            ],
        )
    ]

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
