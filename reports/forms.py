from django import forms

from contratti import models as m
from contratti import permessi
from contratti.engine.tipi import Livello
from contratti.forms import FormBase
from reports.budget import PROGETTI, RAGGRUPPAMENTI, Filtri

ENTRAMBE = "separate"
AUTOMATICO = "auto"


def _scelte_cluster(utente) -> list[tuple[str, str]]:
    if utente is None:
        return [("", "Tutti i cluster"), *m.scelte_cluster()]
    return permessi.scelte_filtro(utente)


def _valori(dati, chiave) -> list[str]:
    valori = dati.getlist(chiave) if hasattr(dati, "getlist") else dati.get(chiave) or []
    return [valori] if isinstance(valori, str) else list(valori)


def _cluster_default(dati, utente) -> None:
    """Di default ognuno vede i propri cluster (F9.2); la tendina lo mostra.

    Più cluster insieme: «area» si ripete (``?area=IT&area=TLC``).
    """
    valori = _valori(dati, "area")
    if utente is not None:
        valori = permessi.selezione_filtro(utente, valori)
    if hasattr(dati, "setlist"):
        dati.setlist("area", valori)
    else:
        dati["area"] = valori


def _codici(utente, valori) -> tuple[str, ...]:
    valori = [v for v in valori or [] if v]
    if utente is None:
        return tuple(valori)
    return tuple(permessi.codici_filtro(utente, valori))


def _campo_cluster():
    return forms.MultipleChoiceField(
        choices=[],
        required=False,
        label="Cluster",
        widget=forms.SelectMultiple(attrs={"class": "form-select js-cluster"}),
    )


class FiltriBudgetForm(FormBase):
    anno = forms.IntegerField(min_value=2000, max_value=2100)
    natura = forms.ChoiceField(
        choices=[*m.Natura.choices, (ENTRAMBE, "OPEX e CAPEX, separati")], required=False
    )
    area = _campo_cluster()
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

    def __init__(self, dati, *, anno_default: int, utente=None):
        dati = dati.copy()
        dati.setdefault("anno", str(anno_default))
        self.utente = utente
        _cluster_default(dati, utente)
        # I default si vedono anche nelle tendine: livello probabile, OPEX per conto e CAPEX per
        # WBS (come lo legge il Controllo di gestione), con i previsti.
        dati.setdefault("livello", Livello.PROBABILE.value)
        dati.setdefault("per", AUTOMATICO)
        dati.setdefault("previsti", "si")
        # OPEX e CAPEX sono budget distinti: di default si vede l'OPEX, mai la somma.
        dati.setdefault("natura", m.Natura.OPEX)
        super().__init__(dati)
        self.fields["area"].choices = _scelte_cluster(utente)

    def filtri(self) -> Filtri:
        d = self.cleaned_data
        return Filtri(
            anno=d["anno"],
            area=_codici(self.utente, d.get("area")),
            conto=d["conto"].pk if d.get("conto") else None,
            fornitore=d["fornitore"].pk if d.get("fornitore") else None,
            progetti=d.get("progetti") or "",
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
    def livello_scelto(self) -> Livello:
        return Livello(self.cleaned_data.get("livello") or Livello.PROBABILE)


class FiltriPianoForm(FormBase):
    anno = forms.IntegerField(min_value=2000, max_value=2100)
    area = _campo_cluster()
    categoria = forms.ModelChoiceField(
        queryset=m.Categoria.objects.all(), required=False, empty_label="Tutte le categorie"
    )
    natura = forms.ChoiceField(choices=[("", "OPEX e CAPEX"), *m.Natura.choices], required=False)

    def __init__(self, dati, *, anno_default: int, utente=None):
        dati = dati.copy()
        dati.setdefault("anno", str(anno_default))
        self.utente = utente
        _cluster_default(dati, utente)
        super().__init__(dati)
        self.fields["area"].choices = _scelte_cluster(utente)

    def codici_cluster(self) -> tuple[str, ...]:
        return _codici(self.utente, self.cleaned_data.get("area"))

    def voci(self) -> list[str]:
        d = self.cleaned_data
        return [
            f"Anno {d['anno']}",
            permessi.descrivi_filtro(self.codici_cluster()),
            f"categoria {d['categoria']}" if d.get("categoria") else "tutte le categorie",
            d["natura"] if d.get("natura") else "OPEX e CAPEX",
        ]

    def descrizione(self) -> str:
        return "; ".join(self.voci())


class FiltriClusterForm(FormBase):
    """Solo il cluster: contratti da chiudere, anomalie dell'esecuzione (F11.4)."""

    area = _campo_cluster()

    def __init__(self, dati, *, utente=None):
        dati = dati.copy()
        self.utente = utente
        _cluster_default(dati, utente)
        super().__init__(dati)
        self.fields["area"].choices = _scelte_cluster(utente)

    def codici_cluster(self) -> tuple[str, ...]:
        return _codici(self.utente, self.cleaned_data.get("area"))

    def voci(self) -> list[str]:
        return [permessi.descrivi_filtro(self.codici_cluster())]

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
            cluster=self.codici_cluster(),
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
        voci = [permessi.descrivi_filtro(self.codici_cluster())]
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
