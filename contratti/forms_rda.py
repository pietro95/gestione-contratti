"""Form del processo d'acquisto (F11.2): richiesta di RDA, posizioni, dati SAP, collegamenti,
contratto registrato dalla RDA."""

import json

from django import forms

from contratti import models as m
from contratti import permessi
from contratti.engine import acquisti as motore
from contratti.forms import (
    FormBase,
    ImportoField,
    ModelFormBootstrap,
    _solo_attivi,
    tendina_centro_costo,
    verifica_natura_wbs,
    wbs_ammesse,
)

CAMPI_RICHIESTA = [
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
]


def _campo_sap(etichetta: str, required: bool = False) -> forms.CharField:
    """Testo di un campo SAP da 40 caratteri (intestazione, descrizione breve)."""
    limite = motore.LUNGHEZZA_TESTO_SAP
    return forms.CharField(
        label=etichetta,
        max_length=limite,
        required=required,
        widget=forms.TextInput(attrs={"data-contatore": limite}),
    )


class RichiestaForm(ModelFormBootstrap):
    """Campi della richiesta di RDA, nell'ordine della scheda SAP (SPEC §5.9)."""

    intestazione = _campo_sap("Intestazione")

    sezioni = [
        ("Richiesta", ["descrizione", "intestazione", "fornitore_proposto"]),
        ("Campi SAP", ["richiedente", "gruppo_acquisti", "note_buyer", "allegati"]),
        ("Riferimenti", ["percorso_file_server", "rup", "cup", "note"]),
    ]

    class Meta:
        model = m.RichiestaAcquisto
        fields = CAMPI_RICHIESTA
        widgets = {
            "note_buyer": forms.Textarea(attrs={"rows": 2}),
            "allegati": forms.Textarea(attrs={"rows": 2}),
            "note": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _solo_attivi(self, "fornitore_proposto", m.Fornitore.objects.filter(archiviato=False))
        _solo_attivi(self, "richiedente", m.RichiedenteSAP.objects.filter(attivo=True))
        _solo_attivi(self, "gruppo_acquisti", m.GruppoAcquisti.objects.filter(attivo=True))
        # Il gruppo acquisti dell'unità del richiedente (codici di rilascio SAP): il browser
        # lo propone quando si cambia richiedente (app.js, «gruppiDalRichiedente»).
        coppie = {
            str(r.pk): r.gruppo_acquisti_id
            for r in m.RichiedenteSAP.objects.filter(attivo=True, gruppo_acquisti__attivo=True)
        }
        if coppie and "richiedente" in self.fields:
            self.fields["richiedente"].widget.attrs.update(
                {
                    "data-gruppi-acquisti": json.dumps(coppie),
                    "data-gruppo-target": self["gruppo_acquisti"].auto_id,
                }
            )
            self.fields[
                "gruppo_acquisti"
            ].help_text = "Proposto dal richiedente: il gruppo acquisti della sua unità."
        self.fields["intestazione"].help_text = (
            "Al massimo 40 caratteri (limite di SAP). Proposta: nome breve del fornitore − "
            "descrizione."
        )
        self.fields[
            "percorso_file_server"
        ].help_text = "Proposto dalla cartella base del cluster; crea la cartella con questo nome."

    def clean(self):
        dati = super().clean()
        richiedente = dati.get("richiedente")
        # Senza gruppo acquisti: quello dell'unità del richiedente, se c'è.
        if richiedente and not dati.get("gruppo_acquisti"):
            gruppo = richiedente.gruppo_acquisti
            if gruppo is not None and gruppo.attivo:
                dati["gruppo_acquisti"] = gruppo
        return dati


class RdaManualeForm(ModelFormBootstrap):
    """RDA già inserita in SAP, registrata a mano (migrazione): anche senza legami."""

    sezioni = [
        (
            "RDA",
            [
                "cluster",
                "sottocluster",
                "descrizione",
                "fornitore_proposto",
                "referente_utente",
                "referente",
            ],
        ),  # fmt: skip
        ("Dati SAP", ["numero_rda", "data_inserimento", "data_rilascio"]),
        ("Riferimenti", ["percorso_file_server", "rup", "cup", "note"]),
    ]

    class Meta:
        model = m.RichiestaAcquisto
        fields = [
            "cluster",
            "sottocluster",
            "descrizione",
            "fornitore_proposto",
            "referente_utente",
            "referente",
            "numero_rda",
            "data_inserimento",
            "data_rilascio",
            "percorso_file_server",
            "rup",
            "cup",
            "note",
        ]
        widgets = {"note": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, utente=None, **kwargs):
        super().__init__(*args, **kwargs)
        cluster = m.Cluster.objects.filter(archiviato=False)
        if utente is not None and (ammessi := permessi.cluster_modificabili(utente)) is not None:
            cluster = cluster.filter(pk__in=ammessi)
        _solo_attivi(self, "cluster", cluster)
        sottocluster = m.Sottocluster.objects.filter(archiviato=False).select_related("cluster")
        if utente is not None:
            sottocluster = permessi.sottocluster_modificabili(utente, sottocluster)
        _solo_attivi(self, "sottocluster", sottocluster)
        self.fields["sottocluster"].empty_label = "— nessuno —"
        _solo_attivi(self, "fornitore_proposto", m.Fornitore.objects.filter(archiviato=False))
        self.fields["numero_rda"].required = True


class PosizioneForm(FormBase):
    """Una posizione della RDA. Righe vuote ignorate; le posizioni salvate non si cancellano."""

    pk = forms.IntegerField(widget=forms.HiddenInput, required=False)
    descrizione_breve = _campo_sap("Descrizione breve")
    gruppo_merci = forms.ModelChoiceField(
        queryset=m.GruppoMerci.objects.none(), required=False, label="Gruppo merci"
    )
    quantita = forms.DecimalField(
        label="Quantità", max_digits=12, decimal_places=3, min_value=0, required=False
    )
    importo_unitario = ImportoField(
        label="Importo unitario", max_digits=14, decimal_places=2, min_value=0, required=False
    )
    di_cui_variabile = ImportoField(
        label="Di cui variabile", max_digits=14, decimal_places=2, min_value=0, required=False
    )
    natura = forms.ChoiceField(choices=m.Natura.choices, initial=m.Natura.OPEX)
    conto = forms.ModelChoiceField(queryset=m.ContoCoge.objects.none(), required=False)
    centro_costo = forms.CharField(label="Centro di costo", max_length=20, required=False)
    wbs = forms.ModelChoiceField(queryset=m.WBS.objects.none(), required=False, label="WBS")

    def __init__(self, *args, cluster=None, **kwargs):
        self.cluster = cluster
        super().__init__(*args, **kwargs)
        self.fields["gruppo_merci"].queryset = m.GruppoMerci.objects.filter(attivo=True)
        conti = m.ContoCoge.objects.all()
        if cluster is not None and permessi.conti_per_cluster():
            conti = conti.filter(clusters=cluster)
        self.fields["conto"].queryset = conti
        self.fields["wbs"].queryset = wbs_ammesse(cluster)
        self.fields["quantita"].widget.attrs["inputmode"] = "decimal"
        attuale = (self.initial or {}).get("centro_costo") or ""
        tendina_centro_costo(self, attuale=attuale, nuovo=not (self.initial or {}).get("pk"))

    def vuota(self) -> bool:
        d = getattr(self, "cleaned_data", {}) or {}
        return (
            not d.get("pk")
            and not d.get("descrizione_breve")
            and d.get("importo_unitario")
            in (
                None,
                "",
            )
        )

    def clean(self):
        dati = super().clean()
        if self.vuota():
            return dati
        if not dati.get("descrizione_breve"):
            self.add_error("descrizione_breve", "Obbligatoria.")
        if dati.get("importo_unitario") is None:
            self.add_error("importo_unitario", "Obbligatorio (anche 0).")
        if not dati.get("quantita"):
            self.add_error("quantita", "Maggiore di zero.")
        verifica_natura_wbs(self, dati.get("natura") or m.Natura.OPEX, "wbs", self.cluster)
        quantita, prezzo = dati.get("quantita"), dati.get("importo_unitario")
        variabile = dati.get("di_cui_variabile") or 0
        if quantita and prezzo is not None and variabile > quantita * prezzo:
            self.add_error("di_cui_variabile", "Non può superare l'importo della posizione.")
        return dati

    def come_dati(self) -> dict:
        d = self.cleaned_data
        return {
            "pk": d.get("pk"),
            "descrizione_breve": d["descrizione_breve"],
            "gruppo_merci": d.get("gruppo_merci"),
            "quantita": d["quantita"],
            "importo_unitario": d["importo_unitario"],
            "di_cui_variabile": d.get("di_cui_variabile") or 0,
            "natura": d.get("natura") or m.Natura.OPEX,
            "conto": d.get("conto"),
            "centro_costo": d.get("centro_costo") or "",
            "wbs": d.get("wbs"),
        }


class PosizioniBase(forms.BaseFormSet):
    def __init__(self, *args, cluster=None, **kwargs):
        self.cluster = cluster
        super().__init__(*args, **kwargs)

    def get_form_kwargs(self, index):
        return {**super().get_form_kwargs(index), "cluster": self.cluster}

    @property
    def empty_form(self):
        form = self.form(
            auto_id=self.auto_id,
            prefix=self.add_prefix("__prefix__"),
            empty_permitted=True,
            use_required_attribute=False,
            cluster=self.cluster,
        )
        self.add_fields(form, None)
        return form

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        if not self.posizioni():
            raise forms.ValidationError("Serve almeno una posizione.")

    def posizioni(self) -> list[dict]:
        return [f.come_dati() for f in self.forms if not f.vuota()]


PosizioniFormSet = forms.formset_factory(PosizioneForm, formset=PosizioniBase, extra=1)


def iniziali_posizioni(posizioni) -> list[dict]:
    """Posizioni salvate (o proposte) come valori iniziali del formset."""
    return [
        {
            "pk": getattr(p, "pk", None),
            "descrizione_breve": p.descrizione_breve,
            "gruppo_merci": p.gruppo_merci,
            "quantita": p.quantita,
            "importo_unitario": p.importo_unitario,
            "di_cui_variabile": p.di_cui_variabile,
            "natura": p.natura,
            "conto": p.conto,
            "centro_costo": p.centro_costo,
            "wbs": p.wbs,
        }
        for p in posizioni
    ]


class DatiSapForm(ModelFormBootstrap):
    class Meta:
        model = m.RichiestaAcquisto
        fields = ["numero_rda", "data_inserimento", "data_rilascio"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["numero_rda"].help_text = "10 cifre, di norma inizia con 51."
        self.fields["data_inserimento"].help_text = "Vuota: oggi, se c'è il numero."


class NotaForm(FormBase):
    nota = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), max_length=2000)


class CollegaPraticaForm(FormBase):
    """La pratica della RDA: contratto in scadenza oppure fabbisogno (o nessuno, per le RDA
    registrate a mano)."""

    contratto = forms.ModelChoiceField(
        queryset=m.Contratto.objects.none(), required=False, label="Contratto in scadenza"
    )
    fabbisogno = forms.ModelChoiceField(
        queryset=m.Fabbisogno.objects.none(), required=False, label="oppure fabbisogno"
    )

    def __init__(self, *args, rda: m.RichiestaAcquisto, utente=None, **kwargs):
        super().__init__(*args, **kwargs)
        fabbisogni = m.Fabbisogno.objects.filter(archiviato=False)
        if utente is not None:
            fabbisogni = permessi.fabbisogni_modificabili(utente, fabbisogni)
        contratti = (
            m.Contratto.objects.filter(
                archiviato=False, una_tantum=False, fabbisogno__in=fabbisogni
            )
            .exclude(successore__archiviato=False)
            .exclude(confluito_in__archiviato=False)
            .select_related("fabbisogno", "fornitore")
            .order_by("fabbisogno__descrizione", "-data_inizio")
        )
        self.fields["contratto"].queryset = contratti
        self.fields["fabbisogno"].queryset = fabbisogni.order_by("cluster__codice", "descrizione")
        for campo in ("contratto", "fabbisogno"):
            self.fields[campo].widget.attrs["class"] += " js-cerca"

    def clean(self):
        dati = super().clean()
        if dati.get("contratto") and dati.get("fabbisogno"):
            raise forms.ValidationError("Scegli il contratto in scadenza oppure il fabbisogno.")
        return dati


class CollegaContrattoForm(FormBase):
    contratto = forms.ModelChoiceField(
        queryset=m.Contratto.objects.none(), label="Contratto nato da questa RDA"
    )

    def __init__(self, *args, rda: m.RichiestaAcquisto, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["contratto"].queryset = (
            m.Contratto.objects.filter(
                archiviato=False, rda__isnull=True, fabbisogno__cluster_id=rda.cluster_id
            )
            .select_related("fabbisogno", "fornitore")
            .order_by("fabbisogno__descrizione", "-data_inizio")
        )
        self.fields["contratto"].widget.attrs["class"] += " js-cerca"


class CollegaRdaForm(FormBase):
    """Dal contratto: la sua RDA d'origine."""

    rda = forms.ModelChoiceField(queryset=m.RichiestaAcquisto.objects.none(), label="RDA")

    def __init__(self, *args, contratto: m.Contratto, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["rda"].queryset = m.RichiestaAcquisto.objects.filter(
            archiviato=False, cluster_id=contratto.fabbisogno.cluster_id
        ).order_by("-data_creazione", "-pk")
        self.fields["rda"].widget.attrs["class"] += " js-cerca"


CAMPI_CONTRATTO_DA_RDA = [
    "fornitore",
    "descrizione",
    "numero_contratto",
    "data_emissione",
    "cig",
    "procedura",
    "lead_time_mesi_override",
    "data_inizio",
    "durata_mesi",
    "una_tantum",
    "tipo_acquisto",
    "senza_contratto",
    "rup",
    "cup",
    "percorso_documenti",
    "note",
]


class ContrattoDaRdaForm(ModelFormBootstrap):
    sezioni = [
        ("Contratto emesso", ["fabbisogno", "fornitore", "descrizione", "numero_contratto",
                              "data_emissione", "cig"]),
        ("Procedura e durata", ["procedura", "lead_time_mesi_override", "data_inizio",
                                "durata_mesi", "una_tantum", "tipo_acquisto",
                                "senza_contratto"]),
        ("Fatturazione delle voci", ["modalita", "periodicita"]),
        ("Riferimenti", ["rup", "cup", "percorso_documenti", "note"]),
    ]  # fmt: skip

    fabbisogno = forms.ModelChoiceField(queryset=m.Fabbisogno.objects.none(), required=False)
    modalita = forms.ChoiceField(
        label="Fatturazione", choices=m.ModalitaFatturazione.choices, initial="da_verificare"
    )
    periodicita = forms.ChoiceField(
        label="Periodicità", choices=[("", "—"), *m.Periodicita.choices], required=False
    )

    class Meta:
        model = m.Contratto
        fields = CAMPI_CONTRATTO_DA_RDA
        widgets = {"note": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, rda: m.RichiestaAcquisto, utente=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.rda = rda
        if rda.fabbisogno_della_pratica() is not None:
            del self.fields["fabbisogno"]
        else:
            fabbisogni = m.Fabbisogno.objects.filter(archiviato=False, cluster_id=rda.cluster_id)
            if utente is not None:
                fabbisogni = permessi.fabbisogni_modificabili(utente, fabbisogni)
            self.fields["fabbisogno"].queryset = fabbisogni
            self.fields["fabbisogno"].required = True
        _solo_attivi(self, "fornitore", m.Fornitore.objects.filter(archiviato=False))
        _solo_attivi(self, "procedura", m.Procedura.objects.filter(attiva=True))
        self.fields[
            "una_tantum"
        ].help_text = "Acquisto che non si rinnova: niente alert né previsti, nessun predecessore."

    def clean(self):
        dati = super().clean()
        if dati.get("modalita") in ("anticipata", "posticipata") and not dati.get("periodicita"):
            self.add_error(
                "periodicita", "Obbligatoria per la fatturazione anticipata o posticipata."
            )
        return dati

    def dati_contratto(self) -> dict:
        return {c: self.cleaned_data[c] for c in CAMPI_CONTRATTO_DA_RDA if c in self.cleaned_data}


class VoceDaRdaForm(FormBase):
    posizione = forms.IntegerField(widget=forms.HiddenInput, required=False)
    descrizione = forms.CharField(max_length=250)
    importo_fisso = ImportoField(max_digits=14, decimal_places=2, min_value=0)
    massimale_variabile = ImportoField(max_digits=14, decimal_places=2, min_value=0, required=False)


VociDaRdaFormSet = forms.formset_factory(VoceDaRdaForm, extra=0, min_num=1, validate_min=True)
