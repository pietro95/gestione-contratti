"""Form delle fatture (F11.3, SPEC Rev14–Rev15): registrazione, contratto, convalida,
importi, documenti SAP, trasferimento, documenti di esecuzione del contratto."""

import json

from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q

from accounts.roles import WRITE_ROLES
from contratti import models as m
from contratti import permessi
from contratti.forms import (
    FormBase,
    ImportoField,
    ModelFormBootstrap,
    tendina_centro_costo,
    wbs_ammesse,
)

Tipo = m.DocumentoEsecuzione.Tipo


def _contratti_del_fornitore(fornitore_id):
    return (
        m.Contratto.objects.filter(
            fornitore_id=fornitore_id, archiviato=False, data_chiusura__isnull=True
        )
        .select_related("fabbisogno", "fornitore")
        .order_by("-data_inizio", "pk")
    )


class FatturaForm(ModelFormBootstrap):
    """Fattura registrata a mano (di norma arriva dall'import settimanale)."""

    class Meta:
        model = m.Fattura
        fields = ["fornitore", "numero", "data", "importo_documento", "note"]
        widgets = {"note": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, contratto: m.Contratto | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.contratto = contratto
        if contratto is not None:
            del self.fields["fornitore"]
        else:
            self.fields["fornitore"].queryset = m.Fornitore.objects.filter(archiviato=False)
            self.fields["fornitore"].widget.attrs["class"] += " js-cerca"
        self.fields["importo_documento"].help_text = "L'importo del documento (Importo SAP)."

    def clean(self):
        dati = super().clean()
        fornitore = self.contratto.fornitore if self.contratto else dati.get("fornitore")
        numero = (dati.get("numero") or "").strip()
        if fornitore and numero:
            doppia = m.Fattura.objects.filter(fornitore=fornitore, numero=numero, archiviato=False)
            if doppia.exists():
                self.add_error("numero", "Fattura già registrata per questo fornitore.")
        return dati


class ContrattoFatturaForm(FormBase):
    contratto = forms.ModelChoiceField(queryset=m.Contratto.objects.none(), label="Contratto")
    voce = forms.ModelChoiceField(
        queryset=m.VoceContratto.objects.none(),
        required=False,
        label="Voce",
        help_text="Vuota: l'unica voce del contratto, se ce n'è una sola.",
    )

    def __init__(self, *args, fattura: m.Fattura, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["contratto"].queryset = _contratti_del_fornitore(fattura.fornitore_id)
        self.fields["contratto"].widget.attrs["class"] += " js-cerca"
        voci = m.VoceContratto.objects.filter(
            contratto__fornitore_id=fattura.fornitore_id, archiviato=False
        ).select_related("contratto")
        self.fields["voce"].queryset = voci
        # La tendina «Voce» mostra solo le voci del contratto scelto (app.js,
        # «vociDelContratto»); per il contratto iniziale già alla prima visualizzazione.
        per_contratto: dict[str, list] = {}
        for v in voci.order_by("contratto_id", "pk"):
            per_contratto.setdefault(str(v.contratto_id), []).append([v.pk, str(v)])
        self.fields["contratto"].widget.attrs.update(
            {"data-voci": json.dumps(per_contratto), "data-voci-target": self["voce"].auto_id}
        )
        if not self.is_bound:
            iniziale = self.initial.get("contratto")
            iniziale = getattr(iniziale, "pk", iniziale)
            self.fields["voce"].queryset = (
                voci.filter(contratto_id=iniziale) if iniziale else (voci.none())
            )

    def clean(self):
        dati = super().clean()
        voce, contratto = dati.get("voce"), dati.get("contratto")
        if voce and contratto and voce.contratto_id != contratto.pk:
            self.add_error("voce", "La voce è di un altro contratto.")
        return dati


class ConvalidaForm(ModelFormBootstrap):
    class Meta:
        model = m.Fattura
        fields = ["esito_convalida", "nota_convalida", "bloccata_fino_al"]
        widgets = {"nota_convalida": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["nota_convalida"].help_text = (
            "Obbligatoria per «Non convalidabile» e «In attesa» (es. in attesa di prove di "
            "funzionamento in campo)."
        )
        self.fields["bloccata_fino_al"].help_text = "Stanziata e bloccata fino a questa data."


class ImportiForm(FormBase):
    valore_base = ImportoField(
        max_digits=14, decimal_places=2, min_value=0, required=False,
        label="Valore base prelevato dal contratto",
    )  # fmt: skip
    oneri = ImportoField(
        max_digits=14, decimal_places=2, min_value=0, required=False, label="Oneri previdenziali"
    )
    bollo = ImportoField(max_digits=14, decimal_places=2, min_value=0, required=False)
    iva = ImportoField(
        max_digits=14, decimal_places=2, min_value=0, required=False,
        label="IVA compresa nell'importo",
        help_text="Vuota: si riconosce da sola se la differenza è l'IVA di un'aliquota.",
    )  # fmt: skip
    competenza_dal = forms.DateField(
        required=False,
        label="Competenza dal",
        help_text="Periodo di competenza della fattura: decide l'anno di budget. "
        "Obbligatorio con il valore base.",
    )
    competenza_al = forms.DateField(required=False, label="Competenza al")
    voce = forms.ModelChoiceField(queryset=m.VoceContratto.objects.none(), required=False)
    rata = forms.ModelChoiceField(
        queryset=m.Rata.objects.none(),
        required=False,
        label="Rata dello scadenzario",
        help_text="La rata diventa consuntivo e riceve il numero di fattura.",
    )

    conto = forms.ModelChoiceField(
        queryset=m.ContoCoge.objects.none(), required=False, label="Conto COGE della fattura"
    )
    centro_costo = forms.CharField(
        label="Centro di costo della fattura", max_length=20, required=False
    )
    wbs = forms.ModelChoiceField(
        queryset=m.WBS.objects.none(), required=False, label="WBS della fattura"
    )

    def __init__(self, *args, fattura: m.Fattura, **kwargs):
        super().__init__(*args, **kwargs)
        # Imputazione propria della fattura (vuota: quella della voce), del cluster del
        # contratto come per le voci.
        cluster = fattura.contratto.fabbisogno.cluster if fattura.contratto_id else None
        conti = m.ContoCoge.objects.all()
        if cluster is not None and permessi.conti_per_cluster():
            conti = conti.filter(cluster=cluster)
        self.fields["conto"].queryset = conti
        self.fields["wbs"].queryset = wbs_ammesse(cluster)
        tendina_centro_costo(self, attuale=fattura.centro_costo)
        if fattura.contratto_id:
            self.fields["voce"].queryset = fattura.contratto.voci.filter(archiviato=False)
            self.fields["rata"].queryset = (
                m.Rata.objects.filter(piano__voce__contratto_id=fattura.contratto_id)
                .filter(Q(fattura__isnull=True) | Q(fattura=fattura))
                .select_related("piano__voce")
                .order_by("data_fattura", "pk")
            )
        else:
            del self.fields["voce"]
            del self.fields["rata"]

    def clean(self):
        dati = super().clean()
        dal, al = dati.get("competenza_dal"), dati.get("competenza_al")
        if dal and al and al < dal:
            self.add_error("competenza_al", "La fine precede l'inizio della competenza.")
        elif dati.get("valore_base") is not None and not (dal and al):
            self.add_error(
                "competenza_dal" if not dal else "competenza_al",
                "Indica il periodo di competenza (dal e al): decide l'anno di budget.",
            )
        elif bool(dal) != bool(al):
            self.add_error(
                "competenza_dal" if not dal else "competenza_al",
                "Indica sia l'inizio sia la fine della competenza.",
            )
        return dati


class DocumentoFatturaForm(FormBase):
    tipo = forms.ChoiceField(
        choices=[(Tipo.ODA, "RdC (ODA/RDC)"), (Tipo.MAP, "MAP"), (Tipo.MIGO, "MIGO")]
    )
    numero = forms.CharField(max_length=40)
    data = forms.DateField()


class TrasferimentoForm(FormBase):
    data = forms.DateField(label="Trasferita per il pagamento il")


class RiassegnaForm(FormBase):
    utente = forms.ModelChoiceField(queryset=get_user_model().objects.none(), label="Assegna a")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        utenti = (
            get_user_model()
            .objects.filter(is_active=True)
            .filter(Q(is_superuser=True) | Q(groups__name__in=WRITE_ROLES))
        )
        self.fields["utente"].queryset = utenti.distinct().order_by(
            "last_name", "first_name", "username"
        )
        self.fields["utente"].widget.attrs["class"] += " js-cerca"


class DocumentoEsecuzioneForm(ModelFormBootstrap):
    """Documenti di esecuzione del contratto (DDT, attestazione, ricezione, ...)."""

    class Meta:
        model = m.DocumentoEsecuzione
        fields = ["tipo", "numero", "data", "importo", "voce", "finale", "note"]
        widgets = {"note": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, contratto: m.Contratto, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.contratto = contratto
        self.fields["voce"].queryset = contratto.voci.filter(archiviato=False)
        self.fields["finale"].help_text = "Solo per attestazione e modello di ricezione."

    def clean(self):
        dati = super().clean()
        if dati.get("finale") and dati.get("tipo") not in (Tipo.ATTESTAZIONE, Tipo.RICEZIONE):
            self.add_error("finale", "Solo un'attestazione o un modello di ricezione è finale.")
        return dati


class StanziamentoForm(ModelFormBootstrap):
    """Stanziamento di un costo di competenza non ancora fatturato (SPEC §5.2, Rev21)."""

    class Meta:
        model = m.Stanziamento
        fields = ["voce", "rata", "importo", "competenza_dal", "competenza_al", "note"]
        widgets = {"note": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, contratto: m.Contratto, **kwargs):
        super().__init__(*args, **kwargs)
        self.contratto = contratto
        self.fields["voce"].queryset = contratto.voci.filter(archiviato=False)
        self.fields["rata"].queryset = (
            m.Rata.objects.filter(piano__voce__contratto=contratto, fattura__isnull=True)
            .select_related("piano__voce")
            .order_by("data_fattura", "pk")
        )
        self.fields["importo"].help_text = "Imponibile, IVA esclusa."
        self.fields[
            "rata"
        ].help_text = "Rata dello scadenzario che lo stanziamento sostituisce nel budget, se c'è."

    def clean(self):
        dati = super().clean()
        voce, rata = dati.get("voce"), dati.get("rata")
        if rata and voce and rata.piano.voce_id != voce.pk:
            self.add_error("rata", "La rata è di un'altra voce.")
        dal, al = dati.get("competenza_dal"), dati.get("competenza_al")
        if dal and al and al < dal:
            self.add_error("competenza_al", "La fine precede l'inizio della competenza.")
        return dati


class ChiudiStanziamentoForm(FormBase):
    fattura = forms.ModelChoiceField(
        queryset=m.Fattura.objects.none(),
        label="Fattura arrivata",
        help_text="La fattura sostituisce lo stanziamento nel budget.",
    )

    def __init__(self, *args, contratto: m.Contratto, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["fattura"].queryset = contratto.fatture.filter(archiviato=False)
