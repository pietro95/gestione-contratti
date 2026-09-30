# Risorse statiche di terze parti

Copiate dai pacchetti npm ufficiali (`registry.npmjs.org`), senza modifiche.
Integrità del tarball npm verificata contro il campo `dist.integrity` del registry.
Nessuna CDN: l'app gira in rete interna.

| Pacchetto | Versione | File | SHA-256 |
|---|---|---|---|
| `bootstrap` | 5.3.8 | `bootstrap-5.3.8/bootstrap.min.css` | `d85327d99c7a3ee1f9b5d0500d1370acea3ad2db39c163c2f51f232baedbdede` |
| `bootstrap` | 5.3.8 | `bootstrap-5.3.8/bootstrap.bundle.min.js` | `e4fd49181388c48ec5040bd3fe66f57c29c8e67fcd8502b3354b96ec7ab47cc7` |
| `htmx.org` | 2.0.11 | `htmx-2.0.11/htmx.min.js` | `d6fdc75f204e6bdefa99b69bf1e6d4ac69b8a364f77929f45c13476b4000f717` |

Integrità npm (sha512 del tarball):
- `bootstrap-5.3.8.tgz`: `HP1SZDqaLDPwsNiqRqi5NcP0SSXciX2s9E+RyqJIIqGo+vJeN5AJVM98CXmW/Wux0nQ5L7jeWUdplCEf0Ee+tg==`
- `htmx.org-2.0.11.tgz`: `Thx/WtpeOQqSrqBCw/A1cwGJGg4UrVa3+sW0GmrM3p4gJgO89ecH4qtbnyzDDWFvBTqjnIMCgELTNt636dtamA==`

Le source map sono escluse. Licenze (file `LICENSE` in ogni cartella): Bootstrap MIT, htmx Zero-Clause BSD.

Aggiornamento: scaricare il tarball da `https://registry.npmjs.org/<pkg>/-/<pkg>-<ver>.tgz`,
verificare `dist.integrity`, copiare i file `dist/` in una nuova cartella versionata, aggiornare
`templates/base.html` e questa tabella.
