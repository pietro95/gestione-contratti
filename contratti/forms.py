"""Form dell'interfaccia operativa. Importi localizzati (1.234,56), date in formato ISO."""

from django import forms
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.forms import inlineformset_factory

from contratti import models as m
from contratti import permessi

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


def tendina_centro_costo(form, campo: str = "centro_costo", attuale: str = "", nuovo=False):
    """Centro di costo da tendina (tabella «Centri di costo»): si salva il codice.

    Un codice già registrato e assente dalla tabella resta tra le scelte, segnalato, così il
    form si salva senza cambiarlo. Per una voce o posizione nuova si propone il predefinito.
    Finché la tabella è vuota il campo resta di testo (prima del caricamento).
    """
    if campo not in form.fields:
        return
    attivi = list(m.CentroCosto.objects.filter(attivo=True))
    if not attivi:
        return
    codici = {c.codice for c in attivi}
    scelte = [("", "—"), *((c.codice, str(c)) for c in attivi)]
    if attuale and attuale not in codici:
        scelte.append((attuale, f"{attuale} (non in tabella: sceglierne uno)"))
    vecchio = form.fields[campo]
    form.fields[campo] = forms.ChoiceField(
        label=vecchio.label,
        choices=scelte,
        required=vecchio.required,
        help_text="Dalla tabella dei centri di costo (Gestione → Import «Tabelle SAP»).",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    if nuovo and not attuale:
        form.initial.setdefault(campo, m.CentroCosto.codice_predefinito())


def utenti_attivi():
    """Utenti dell'applicazione, per le tendine dei referenti."""
    return (
        get_user_model()
        .objects.filter(is_active=True)
        .order_by("last_name", "first_name", "username")
    )


def nome_utente(utente) -> str:
    """«Cognome Nome» se noto, altrimenti lo username."""
    nome = f"{utente.last_name} {utente.first_name}".strip()
    return nome or utente.get_username()


class FornitoreForm(ModelFormBootstrap):
    class Meta:
        model = m.Fornitore
        fields = ["ragione_sociale", "partita_iva", "codice_sap", "alias_sap", "note"]
        widgets = {"alias_sap": forms.Textarea(attrs={"rows": 3})}

    def clean_alias_sap(self):
        """Un alias non può essere anche un nome di un altro fornitore: l'import non saprebbe
        a chi assegnare la fattura."""
        from contratti.importer.normalizza import chiave_nome

        viste, righe = set(), []
        for alias in (self.cleaned_data.get("alias_sap") or "").splitlines():
            chiave = chiave_nome(alias)
            if alias.strip() and chiave and chiave not in viste:
                viste.add(chiave)
                righe.append(alias.strip())
        altri = m.Fornitore.objects.filter(archiviato=False).exclude(pk=self.instance.pk)
        for altro in altri:
            for nome in altro.nomi_riconosciuti:
                if chiave_nome(nome) in viste:
                    raise forms.ValidationError(
                        f"«{nome}» è già un nome del fornitore {altro}: "
                        "togli l'alias o correggi l'altro fornitore."
                    )
        return "\n".join(righe)


class FabbisognoForm(ModelFormBootstrap):
    sezioni = [
        (
            "Fabbisogno",
            [
                "descrizione",
                "cluster",
                "sottocluster",
                "fonte_finanziamento",
                "referente_utente",
            ],
        ),
        (
            "Motivazione e priorità",
            ["motivazione", "priorita", "tipo_acquisto", "fonte_stima"],
        ),
        (
            "Decisione sul rinnovo",
            ["decisione", "una_tantum", "stima_prossimo_importo", "note"],
        ),
        (
            "Previsto manuale (solo per fabbisogni nuovi, senza contratti)",
            [
                "previsto_data_avvio",
                "previsto_durata_mesi",
                "previsto_procedura",
                "previsto_modalita",
                "previsto_periodicita",
                "natura_previsti",
                "conto_previsti",
                "wbs_previsti",
            ],
        ),
    ]

    class Meta:
        model = m.Fabbisogno
        fields = [
            "descrizione",
            "cluster",
            "sottocluster",
            "fonte_finanziamento",
            "referente_utente",
            "motivazione",
            "priorita",
            "tipo_acquisto",
            "fonte_stima",
            "decisione",
            "una_tantum",
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
        ]

    def __init__(self, *args, utente=None, **kwargs):
        super().__init__(*args, **kwargs)
        cluster = m.Cluster.objects.filter(archiviato=False)
        if utente is not None and (ammessi := permessi.cluster_modificabili(utente)) is not None:
            cluster = cluster.filter(pk__in=ammessi)  # solo i propri cluster (F9.2)
        _solo_attivi(self, "cluster", cluster)
        self.utente = utente
        sottocluster = m.Sottocluster.objects.filter(archiviato=False)
        if utente is not None:  # solo i propri sottocluster (Rev25)
            sottocluster = permessi.sottocluster_modificabili(utente, sottocluster)
        _solo_attivi(self, "sottocluster", sottocluster)
        _solo_attivi(self, "fonte_finanziamento", m.FonteFinanziamento.objects.filter(attiva=True))
        # Nuovo: obbligatorio; un fabbisogno già classificato non perde il sottocluster; quelli
        # importati senza si completano quando conviene, senza bloccare altre modifiche.
        self.fields["sottocluster"].required = not self.instance.pk or bool(
            self.instance.sottocluster_id
        )
        self.fields["sottocluster"].empty_label = "— scegli il sottocluster —"
        self.fields["sottocluster"].queryset = self.fields["sottocluster"].queryset.select_related(
            "cluster"
        )
        self.fields[
            "sottocluster"
        ].help_text = (
            "Obbligatorio: classifica il fabbisogno nel cluster (deve essere del cluster scelto)."
        )
        referente = self.fields["referente_utente"]
        referente.queryset = utenti_attivi()
        referente.label = "Referente"
        referente.label_from_instance = nome_utente
        referente.empty_label = "— nessuno —"
        referente.widget.attrs["class"] = referente.widget.attrs.get("class", "") + " js-cerca"
        if self.instance.pk and self.instance.referente and not self.instance.referente_utente_id:
            referente.help_text = (
                f"Registrato come testo: «{self.instance.referente}». "
                "Sceglilo tra gli utenti per collegarlo."
            )
        # Procedura presunta: solo quelle del codice degli appalti; quella già scelta resta.
        procedure = Q(attiva=True, per_fabbisogni=True)
        if self.instance.previsto_procedura_id:
            procedure |= Q(pk=self.instance.previsto_procedura_id)
        _solo_attivi(self, "previsto_procedura", m.Procedura.objects.filter(procedure))
        # «Una tantum» è ridondante: l'acquisto unico è la periodicità «Intera durata».
        if "previsto_modalita" in self.fields:
            attuale = self.instance.previsto_modalita
            self.fields["previsto_modalita"].choices = [
                (valore, etichetta)
                for valore, etichetta in self.fields["previsto_modalita"].choices
                if valore != m.ModalitaFatturazione.UNA_TANTUM or valore == attuale
            ]
        _solo_attivi(self, "wbs_previsti", m.WBS.objects.filter(archiviato=False))

    def clean(self):
        dati = super().clean()
        cluster, sottocluster = dati.get("cluster"), dati.get("sottocluster")
        if (
            self.utente is not None
            and cluster is not None
            and not permessi.puo_modificare_in(
                self.utente, cluster.pk, sottocluster.pk if sottocluster else None
            )
        ):
            self.add_error("sottocluster", "Non hai il permesso su questo sottocluster.")
        avvio, durata = dati.get("previsto_data_avvio"), dati.get("previsto_durata_mesi")
        if bool(avvio) != bool(durata):
            raise forms.ValidationError(
                "Per il previsto manuale servono insieme avvio e durata, oppure nessuno dei due."
            )
        verifica_natura_wbs(
            self, dati.get("natura_previsti") or m.Natura.OPEX, "wbs_previsti", dati.get("cluster")
        )
        return dati

    def save(self, commit=True):
        fabbisogno = super().save(commit=False)
        utente = self.cleaned_data.get("referente_utente")
        if utente is not None:
            fabbisogno.referente = nome_utente(utente)[:150]
        elif "referente_utente" in self.changed_data:
            fabbisogno.referente = ""  # tolto il referente: non resta il nome di prima
        if commit:
            fabbisogno.save()
            self.save_m2m()
        return fabbisogno


class CompetenzaDichiarataForm(FormBase):
    """Competenza che il referente si aspetta per un anno e una natura (SPEC §4, Rev27)."""

    anno = forms.IntegerField(min_value=2000, max_value=2100)
    natura = forms.ChoiceField(choices=m.Natura.choices, initial=m.Natura.OPEX)
    importo = ImportoField(
        label="Importo dichiarato (imponibile)", max_digits=14, decimal_places=2, min_value=0
    )
    note = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)


CAMPI_CONTRATTO = [
    "fornitore",
    "descrizione",
    "tipo_acquisto",
    "senza_contratto",
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
        (
            "Oggetto e fornitore",
            ["fabbisogno", "fornitore", "descrizione", "tipo_acquisto", "senza_contratto"],
        ),
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
        if "tipo_acquisto" in self.fields:
            # Chi non lo indica (connettore, form di prima) tiene il valore registrato.
            self.fields["tipo_acquisto"].required = False
            self.fields[
                "tipo_acquisto"
            ].help_text = "Lavori/Servizi (propone MAP) o forniture (propone MIGO)."

    def clean_tipo_acquisto(self):
        valore = self.cleaned_data.get("tipo_acquisto")
        return valore or self.instance.tipo_acquisto or m.Contratto.TipoAcquisto.SERVIZIO


class ContrattoNuovoForm(ContrattoForm):
    """Creazione: il sottocluster del fabbisogno è obbligatorio e, se il fornitore non è in
    elenco, lo si apre qui (ragione sociale, partita IVA, codice SAP)."""

    sezioni = [
        (
            "Oggetto e fornitore",
            [
                "fabbisogno",
                "sottocluster",
                "fornitore",
                "descrizione",
                "tipo_acquisto",
                "senza_contratto",
            ],
        ),
        (
            "Nuovo fornitore (solo se non è in elenco)",
            ["nuovo_fornitore", "nuovo_fornitore_piva", "nuovo_fornitore_codice_sap"],
        ),
        *ContrattoForm.sezioni[1:],
    ]

    sottocluster = forms.ModelChoiceField(
        queryset=m.Sottocluster.objects.none(),
        label="Sottocluster",
        required=False,  # obbligatorio: lo impone clean(); il fabbisogno lo propone
        help_text="Obbligatorio. Vuoto: quello del fabbisogno (se diverso, lo si imposta).",
    )
    nuovo_fornitore = forms.CharField(
        label="Ragione sociale del nuovo fornitore", max_length=200, required=False
    )
    nuovo_fornitore_piva = forms.CharField(
        label="Partita IVA del nuovo fornitore", max_length=20, required=False
    )
    nuovo_fornitore_codice_sap = forms.CharField(
        label="Codice SAP del nuovo fornitore", max_length=20, required=False
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["sottocluster"].queryset = m.Sottocluster.objects.filter(
            archiviato=False
        ).select_related("cluster")
        self.fields["sottocluster"].empty_label = "— quello del fabbisogno —"
        self.fields["fornitore"].required = False
        self.fields["fornitore"].empty_label = "— scegli o apri un nuovo fornitore —"
        self.fields["tipo_acquisto"].choices = m.Contratto.TipoAcquisto.choices
        self._form_fornitore = None

    def clean(self):
        dati = super().clean()
        fabbisogno = dati.get("fabbisogno")
        sottocluster = dati.get("sottocluster") or (fabbisogno and fabbisogno.sottocluster)
        if fabbisogno is not None:
            if sottocluster is None:
                self.add_error("sottocluster", "Il sottocluster è obbligatorio.")
            elif sottocluster.cluster_id != fabbisogno.cluster_id:
                self.add_error(
                    "sottocluster",
                    f"Il sottocluster è del cluster {sottocluster.cluster.codice}, "
                    f"il fabbisogno è del cluster {fabbisogno.cluster.codice}.",
                )
            else:
                dati["sottocluster"] = sottocluster
        nome = (dati.get("nuovo_fornitore") or "").strip()
        altri = [dati.get("nuovo_fornitore_piva"), dati.get("nuovo_fornitore_codice_sap")]
        if dati.get("fornitore") and (nome or any(altri)):
            self.add_error(
                "nuovo_fornitore", "Scegli un fornitore dall'elenco oppure aprine uno nuovo."
            )
        elif not dati.get("fornitore") and not nome:
            self.add_error("fornitore", "Scegli il fornitore o indica quello nuovo.")
        elif nome:
            nuovo = FornitoreForm(
                {
                    "ragione_sociale": nome,
                    "partita_iva": dati.get("nuovo_fornitore_piva") or "",
                    "codice_sap": dati.get("nuovo_fornitore_codice_sap") or "",
                }
            )
            if nuovo.is_valid():
                self._form_fornitore = nuovo
            else:
                nomi = {
                    "ragione_sociale": "nuovo_fornitore",
                    "partita_iva": "nuovo_fornitore_piva",
                    "codice_sap": "nuovo_fornitore_codice_sap",
                }
                for campo, errori in nuovo.errors.items():
                    for errore in errori:
                        self.add_error(nomi.get(campo, "nuovo_fornitore_piva"), errore)
        return dati

    @transaction.atomic
    def save(self, commit=True):
        if self._form_fornitore is not None:
            fornitore = self._form_fornitore.instance
            fornitore._change_reason = "Aperto dalla creazione del contratto"
            fornitore.save()
            self.instance.fornitore = fornitore
        contratto = super().save(commit=False)
        sottocluster = self.cleaned_data.get("sottocluster")
        fabbisogno = contratto.fabbisogno
        if sottocluster is not None and fabbisogno.sottocluster_id != sottocluster.pk:
            fabbisogno.sottocluster = sottocluster
            fabbisogno._change_reason = "Sottocluster indicato alla creazione del contratto"
            fabbisogno.save()
        if commit:
            contratto.save()
            self.save_m2m()
        return contratto


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
            .select_related("cluster", "sottocluster")
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


# Dati del solo documento contrattuale: un rinnovo senza contratto non li ha (F9.5.5).
CAMPI_SOLO_CONTRATTO = (
    "senza_contratto",
    "numero_contratto",
    "data_emissione",
    "data_stipula",
    "data_fine_override",
    "tacito_rinnovo",
    "preavviso_disdetta_giorni",
)


class RinnovoSenzaContrattoForm(RinnovoForm):
    """Rinnovo senza contratto: stessa catena, scadenze e alert, senza dati del documento."""

    sezioni = [
        ("Oggetto e fornitore", ["fornitore", "descrizione"]),
        ("Periodo", ["data_inizio", "durata_mesi"]),
        ("Procedura", ["procedura", "lead_time_mesi_override", "numero_rda", "cig"]),
        ("Documenti e note", ["link_documenti", "note"]),
    ]

    class Meta(ContrattoForm.Meta):
        fields = [c for c in CAMPI_CONTRATTO if c not in CAMPI_SOLO_CONTRATTO]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["data_inizio"].required = True
        self.fields["durata_mesi"].help_text = (
            "12 = annuale. Scadenza = inizio + durata − 1 giorno; da qui data limite (scadenza "
            "− lead time della procedura) e alert, come per un contratto."
        )


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
        ("Extra budget (attività spot autorizzata dall'AD)", ["autorizzazione_extra_budget"]),
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
            "autorizzazione_extra_budget",
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
        self.contratto = contratto
        self.fields["autorizzazione_extra_budget"].queryset = (
            m.AutorizzazioneExtraBudget.objects.filter(archiviato=False, cluster=self.cluster)
            | m.AutorizzazioneExtraBudget.objects.filter(
                pk=self.instance.autorizzazione_extra_budget_id
            )
        ).distinct()
        tendina_centro_costo(
            self, attuale=self.instance.centro_costo, nuovo=self.instance.pk is None
        )

    def clean(self):
        dati = super().clean()
        natura = dati.get("natura") or m.Natura.OPEX
        verifica_natura_wbs(self, natura, "wbs", self.cluster)
        if dati.get("autorizzazione_extra_budget") and not self.contratto.una_tantum:
            self.add_error(
                "autorizzazione_extra_budget",
                "Solo un contratto una tantum può avere voci extra budget: non ha rinnovi.",
            )
        con_cluster = permessi.conti_per_cluster()
        for campo in ("conto", "conto_rinnovi"):
            conto = dati.get(campo)
            if conto is None:
                continue
            cluster_conto = list(conto.clusters.all())
            if cluster_conto and self.cluster and self.cluster not in cluster_conto:
                elenco = ", ".join(c.codice for c in cluster_conto)
                self.add_error(
                    campo,
                    f"Il conto {conto.codice} è "
                    + (
                        f"del cluster {elenco}."
                        if len(cluster_conto) == 1
                        else f"dei cluster {elenco}."
                    ),
                )
            elif not cluster_conto and con_cluster:
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
        if dati.get("modalita") == "consumo":
            # A consumo non c'è un calendario di rate: periodicità e prima fattura non servono.
            dati["periodicita"] = ""
            dati["data_prima_fattura"] = None
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


# Da Rev11 a mano si registrano solo i passaggi che precedono la RDA: da «RDA richiesta» in poi
# lo stato si ricava dalle RDA collegate alla pratica (SPEC §4, §5.7).
STATI_PRATICA_MANUALI = [
    (s.value, s.label)
    for s in (m.StatoPratica.Stato.OFFERTA_RICHIESTA, m.StatoPratica.Stato.OFFERTA_RICEVUTA)
]


class PassaggioPraticaForm(FormBase):
    stato = forms.ChoiceField(choices=STATI_PRATICA_MANUALI)
    data = forms.DateField()
    note = forms.CharField(widget=forms.TextInput, required=False)
