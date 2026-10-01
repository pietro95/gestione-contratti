"""Il motore è puro: nessun import di Django, dell'ORM o di I/O (CLAUDE.md, regola 5)."""

import ast
from pathlib import Path

import contratti.engine

VIETATI = ("django", "contratti.models", "contratti.adapters", "os", "pathlib", "requests")


def test_motore_senza_orm_ne_io():
    cartella = Path(contratti.engine.__file__).parent
    for file in cartella.glob("*.py"):
        albero = ast.parse(file.read_text(encoding="utf-8"))
        for nodo in ast.walk(albero):
            if isinstance(nodo, ast.Import):
                nomi = [a.name for a in nodo.names]
            elif isinstance(nodo, ast.ImportFrom):
                nomi = [nodo.module or ""]
            else:
                continue
            for nome in nomi:
                assert not nome.startswith(VIETATI), f"{file.name} importa {nome}"
        nomi_usati = {n.id for n in ast.walk(albero) if isinstance(n, ast.Name)}
        assert "open" not in nomi_usati, f"{file.name} usa open()"
