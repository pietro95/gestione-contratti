from django import forms
from django.template.loader import render_to_string

from contratti import models as m
from contratti import permessi
from contratti.engine.tipi import Livello
from contratti.forms import FormBase
from reports.budget import (
    EXTRA_BUDGET,
    PROGETTI,
    RAGGRUPPAMENTI,
    VISTA_DEFAULT,
    VISTE,
    Filtri,
    nomi_viste,
)

ENTRAMBE = "separate"
AUTOMATICO = "auto"


def _valori(dati, chiave) -> list[str]:
    valori = dati.getlist(chiave) if hasattr(dati, "getlist") else dati.get(chiave) or []
    return [valori] if isinstance(valori, str) else list(valori)


class AlberoSottoclusterWidget(forms.Widget):
    """Tendina a selezione multipla: cluster espandibili in sottocluster (Rev36).

    Il form le passa l'albero già calcolato (``filtro``); i valori sono gli id dei sottocluster.
    """

    template = "contratti/_albero_sottocluster.html"

    def __init__(self, attrs=None):
        super().__init__(attrs)
        self.filtro: dict = {"albero": [], "etichetta": "Tutti i sottocluster"}

    def render(self, name, value, attrs=None, renderer=None):
        identificativo = (attrs or {}).get("id") or f"id_{name}"
        return render_to_string(
            self.template, {"filtro": self.filtro, "nome": name, "identificativo": identificativo}
        )

    def value_from_datadict(self, data, files, name):
        return data.getlist(name) if hasattr(data, "getlist") else (data.get(name) or [])


def _campo_sottocluster():
    return forms.MultipleChoiceField(
        choices=[], required=False, label="Sottocluster", widget=AlberoSottoclusterWidget()
    )


def _prepara_sottocluster(form, dati, utente) -> None:
    """Di default ognuno vede i propri sottocluster; la tendina lo mostra (Rev36).

    La selezione si ripete (``?sottocluster=3&sottocluster=7``); «tutti» li sceglie tutti.
    """
    scelti = [
        str(i) for i in permessi.selezione_sottocluster(utente, _valori(dati, "sottocluster"))
    ]
    if hasattr(dati, "setlist"):
        dati.setlist("sottocluster", scelti)
    else:
        dati["sottocluster"] = scelti
    campo = form.fields["sottocluster"]
    campo.choices = [(str(s.pk), str(s)) for s in m.Sottocluster.objects.all()]
    campo.widget.filtro = permessi.contesto_filtro_sottocluster(utente, scelti)


class SottoclusterFiltroMixin:
    """Metodi comuni dei form con la tendina dei sottocluster."""

    utente = None

    def sottocluster_ids(self) -> tuple[int, ...]:
        """Id da filtrare; vuoto = nessuna restrizione (sono scelti tutti i sottocluster)."""
        return permessi.filtro_sottocluster(self.utente, self.cleaned_data.get("sottocluster"))

    def descrizione_sottocluster(self) -> str:
        return permessi.descrivi_sottocluster_scelti(self.sottocluster_ids())


class FiltriBudgetForm(SottoclusterFiltroMixin, FormBase):
    anno = forms.IntegerField(min_value=2000, max_value=2100)
    natura = forms.ChoiceField(
        choices=[*m.Natura.choices, (ENTRAMBE, "OPEX e CAPEX, separati")], required=False
    )
    sottocluster = _campo_sottocluster()
    conto = forms.ModelChoiceField(
        queryset=m.ContoCoge.objects.order_by("codice"), required=False, empty_label="Tutti i conti"
    )
    fornitore = forms.ModelChoiceField(
        queryset=m.Fornitore.objects.filter(archiviato=False).order_by("ragione_sociale"),
        required=False,
        empty_label="Tutti i fornitori",
    )
    progetti = forms.ChoiceField(
        choices=list(PROGETTI.items()), required=False, label="WBS a progetto"
    )
    extra_budget = forms.ChoiceField(
        choices=list(EXTRA_BUDGET.items()), required=False, label="Extra budget (AD)"
    )
    previsti = forms.ChoiceField(
        choices=[("si", "Con i previsti"), ("no", "Solo consolidato")], required=False
    )
    per = forms.ChoiceField(
        choices=[(AUTOMATICO, "Conto (OPEX), WBS (CAPEX)"), *RAGGRUPPAMENTI.items()],
        required=False,
        label="Per",
    )
    livello = forms.ChoiceField(
        choices=[(liv.value, liv.value.capitalize()) for liv in Livello], required=False
    )
    viste = forms.MultipleChoiceField(
        choices=list(nomi_viste().items()),
        required=False,
        label="Viste",
        widget=forms.SelectMultiple(attrs={"class": "form-select js-cluster"}),
    )

    def __init__(self, dati, *, anno_default: int, utente=None):
        dati = dati.copy()
        dati.setdefault("anno", str(anno_default))
        self.utente = utente
        # Il budget si legge sul fatturato e stanziato (competenza): le altre viste si scelgono.
        if not _valori(dati, "viste"):
            if hasattr(dati, "setlist"):
                dati.setlist("viste", [VISTA_DEFAULT])
            else:
                dati["viste"] = [VISTA_DEFAULT]
        # I default si vedono anche nelle tendine: livello probabile, OPEX per conto e CAPEX per
        # WBS (come lo legge il Controllo di gestione), con i previsti.
        dati.setdefault("livello", Livello.PROBABILE.value)
        dati.setdefault("per", AUTOMATICO)
        dati.setdefault("previsti", "si")
        # OPEX e CAPEX sono budget distinti: di default si vede l'OPEX, mai la somma.
        dati.setdefault("natura", m.Natura.OPEX)
        super().__init__(dati)
        _prepara_sottocluster(self, dati, utente)

    def filtri(self) -> Filtri:
        d = self.cleaned_data
        return Filtri(
            anno=d["anno"],
            conto=d["conto"].pk if d.get("conto") else None,
            fornitore=d["fornitore"].pk if d.get("fornitore") else None,
            sottocluster=self.sottocluster_ids(),
            progetti=d.get("progetti") or "",
            extra_budget=d.get("extra_budget") or "",
            previsionali=d.get("previsti") != "no",
            natura=d["natura"] if d.get("natura") in m.Natura.values else "",
        )

    def criterio(self, natura: str = "") -> str:
        """Raggruppamento scelto; in automatico OPEX per conto e CAPEX per WBS."""
        per = self.cleaned_data.get("per") or AUTOMATICO
        if per != AUTOMATICO:
            return per
        return "wbs" if natura == m.Natura.CAPEX else "conto"

    @property
    def viste_scelte(self) -> tuple[str, ...]:
        """Viste da mostrare, nell'ordine canonico; di default solo il riferimento del budget."""
        scelte = set(self.cleaned_data.get("viste") or ())
        return tuple(v for v in VISTE if v in scelte) or (VISTA_DEFAULT,)

    @property
    def livello_scelto(self) -> Livello:
        return Livello(self.cleaned_data.get("livello") or Livello.PROBABILE)


class FiltriPianoForm(SottoclusterFiltroMixin, FormBase):
    anno = forms.IntegerField(min_value=2000, max_value=2100)
    sottocluster = _campo_sottocluster()
    natura = forms.ChoiceField(choices=[("", "OPEX e CAPEX"), *m.Natura.choices], required=False)

    def __init__(self, dati, *, anno_default: int, utente=None):
        dati = dati.copy()
        dati.setdefault("anno", str(anno_default))
        self.utente = utente
        super().__init__(dati)
        _prepara_sottocluster(self, dati, utente)

    def voci(self) -> list[str]:
        d = self.cleaned_data
        return [
            f"Anno {d['anno']}",
            self.descrizione_sottocluster().replace("Sottocluster: ", "sottocluster ", 1),
            d["natura"] if d.get("natura") else "OPEX e CAPEX",
        ]

    def descrizione(self) -> str:
        return "; ".join(self.voci())


class FiltriClusterForm(SottoclusterFiltroMixin, FormBase):
    """Sottocluster: contratti da chiudere, anomalie dell'esecuzione (F11.4)."""

    sottocluster = _campo_sottocluster()

    def __init__(self, dati, *, utente=None):
        dati = dati.copy()
        self.utente = utente
        super().__init__(dati)
        _prepara_sottocluster(self, dati, utente)

    def voci(self) -> list[str]:
        return [self.descrizione_sottocluster()]

    def descrizione(self) -> str:
        return "; ".join(self.voci())


class FiltriRdaForm(FiltriClusterForm):
    """Stato delle RDA (SPEC §5.7): cluster, referente, fase, anno, fornitore, WBS."""

    fase = forms.MultipleChoiceField(
        choices=[],
        required=False,
        widget=forms.SelectMultiple(attrs={"class": "form-select js-cluster"}),
    )
    anno = forms.IntegerField(min_value=2000, max_value=2100, required=False)
    referente = forms.ModelChoiceField(
        queryset=None, required=False, empty_label="Tutti i referenti"
    )
    fornitore = forms.ModelChoiceField(
        queryset=m.Fornitore.objects.filter(archiviato=False).order_by("ragione_sociale"),
        required=False,
        empty_label="Tutti i fornitori",
    )
    wbs = forms.CharField(required=False, label="WBS")
    q = forms.CharField(required=False, label="Cerca")

    def __init__(self, dati, *, utente=None):
        from django.contrib.auth import get_user_model

        from contratti.engine.acquisti import ETICHETTE_FASE

        super().__init__(dati, utente=utente)
        self.fields["fase"].choices = list(ETICHETTE_FASE.items())
        self.fields["referente"].queryset = (
            get_user_model()
            .objects.filter(richieste_acquisto__isnull=False)
            .distinct()
            .order_by("last_name", "first_name", "username")
        )
        self.fields["fornitore"].widget.attrs["class"] += " js-cerca"
        self.fields["q"].widget.attrs["placeholder"] = "N. RDA, descrizione, referente"

    def filtri(self):
        from reports.acquisti import FiltriRDA

        d = self.cleaned_data
        return FiltriRDA(
            sottocluster=self.sottocluster_ids(),
            referente=d["referente"].pk if d.get("referente") else None,
            fasi=tuple(d.get("fase") or ()),
            anno=d.get("anno"),
            fornitore=d["fornitore"].pk if d.get("fornitore") else None,
            wbs=(d.get("wbs") or "").strip(),
            testo=(d.get("q") or "").strip(),
        )

    def voci(self) -> list[str]:
        from contratti.engine.acquisti import ETICHETTE_FASE

        d = self.cleaned_data
        voci = super().voci()
        if d.get("fase"):
            voci.append("fase " + ", ".join(ETICHETTE_FASE[f].lower() for f in d["fase"]))
        if d.get("anno"):
            voci.append(f"anno {d['anno']}")
        if d.get("referente"):
            voci.append(f"referente {d['referente']}")
        if d.get("fornitore"):
            voci.append(f"fornitore {d['fornitore']}")
        if d.get("wbs"):
            voci.append(f"WBS {d['wbs']}")
        if d.get("q"):
            voci.append(f"testo «{d['q']}»")
        return voci
