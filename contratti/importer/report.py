"""Report dell'import: anomalie riga per riga (CSV) e riepilogo a video."""

import csv
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

INTESTAZIONE = ["file", "foglio", "riga", "codice", "campo", "valore", "messaggio"]


@dataclass(frozen=True)
class VoceReport:
    file: str
    foglio: str
    riga: int | None
    codice: str
    campo: str
    valore: str
    messaggio: str


@dataclass
class Report:
    file: str
    dry_run: bool = False
    anomalie: list[VoceReport] = field(default_factory=list)
    conteggi: Counter = field(default_factory=Counter)
    # Coppie conto vecchio → conto nuovo trovate nei file, per compilare la mappatura.
    mappature_conti: Counter = field(default_factory=Counter)

    def anomalia(self, foglio, riga, codice, campo="", valore="", messaggio=""):
        self.anomalie.append(
            VoceReport(self.file, foglio, riga, codice, campo, str(valore), messaggio)
        )

    def codici(self) -> Counter:
        return Counter(a.codice for a in self.anomalie)

    def scrivi_csv(self, percorso: str | Path) -> None:
        with open(percorso, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(INTESTAZIONE)
            for a in self.anomalie:
                w.writerow(
                    [a.file, a.foglio, a.riga or "", a.codice, a.campo, a.valore, a.messaggio]
                )
            for (vecchio, nuovo), volte in sorted(self.mappature_conti.items()):
                w.writerow(
                    [self.file, "", "", "MAPPATURA_CONTO", "conto", f"{vecchio} → {nuovo}",
                     f"Coppia trovata in {volte} righe."]
                )  # fmt: skip

    def riepilogo(self) -> str:
        righe = [
            f"Import di {self.file}" + (" (DRY-RUN: nessuna scrittura)" if self.dry_run else ""),
            "",
            "Esito:",
        ]
        for chiave in (
            "righe_lette",
            "contratti_creati",
            "contratti_gia_presenti",
            "voci_create",
            "fornitori_creati",
            "proposte_raggruppamento",
            "proposte_predecessore",
        ):
            righe.append(f"  {chiave.replace('_', ' ')}: {self.conteggi.get(chiave, 0)}")
        righe += ["", "Anomalie per codice:"]
        for codice, volte in sorted(self.codici().items()):
            righe.append(f"  {codice}: {volte}")
        if self.mappature_conti:
            righe += ["", "Coppie conto vecchio → nuovo trovate:"]
            for (vecchio, nuovo), volte in sorted(self.mappature_conti.items()):
                righe.append(f"  {vecchio} → {nuovo} ({volte} righe)")
        return "\n".join(righe)
