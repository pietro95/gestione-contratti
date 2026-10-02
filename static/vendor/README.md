# Risorse statiche di terze parti

Copiate dai pacchetti npm ufficiali (`registry.npmjs.org`), senza modifiche.
Integrità del tarball npm verificata contro il campo `dist.integrity` del registry.
Nessuna CDN: l'app gira in rete interna.

| Pacchetto | Versione | File | SHA-256 |
|---|---|---|---|
| `bootstrap` | 5.3.8 | `bootstrap-5.3.8/bootstrap.min.css` | `d85327d99c7a3ee1f9b5d0500d1370acea3ad2db39c163c2f51f232baedbdede` |
| `bootstrap` | 5.3.8 | `bootstrap-5.3.8/bootstrap.bundle.min.js` | `e4fd49181388c48ec5040bd3fe66f57c29c8e67fcd8502b3354b96ec7ab47cc7` |
| `htmx.org` | 2.0.11 | `htmx-2.0.11/htmx.min.js` | `d6fdc75f204e6bdefa99b69bf1e6d4ac69b8a364f77929f45c13476b4000f717` |
| `bootstrap-icons` | 1.13.1 | `bootstrap-icons-1.13.1/bootstrap-icons.min.css` | `a5d6387a32ca3baec4d02336b5b3edab50c9dd518355576a011ea3dd9c1d884e` |
| `bootstrap-icons` | 1.13.1 | `bootstrap-icons-1.13.1/fonts/bootstrap-icons.woff2` | `6c75710364a1ca5604267716f6d28997b26319fdb078cf11e0b42ab66ff2ea61` |
| `tom-select` | 2.6.2 | `tom-select-2.6.2/tom-select.complete.min.js` | `8f9d7d3420e938c2c9817818b56df43ea46feae5bf1f5a2e828863c034df0e37` |
| `tom-select` | 2.6.2 | `tom-select-2.6.2/tom-select.bootstrap5.min.css` | `ce467598f8953044ddfc0ff9fd4b7e2f6cced549001737d6b712a14f8b9a6599` |
| `flatpickr` | 4.6.13 | `flatpickr-4.6.13/flatpickr.min.js` | `1eeab1cb779471a0b0aaa93dd91c2eb1aa537d696f01ab05ea9dabc55e8525a1` |
| `flatpickr` | 4.6.13 | `flatpickr-4.6.13/flatpickr.min.css` | `1b34a42552c96f10e4dfaaa4a367276b03868aacff63c1ac42ffe331352bc754` |
| `flatpickr` | 4.6.13 | `flatpickr-4.6.13/it.js` (da `dist/l10n/it.js`) | `81a595a9f9082bab542e85364f5298ae0cdbbadc64d97bd0d2b5634d646dfe61` |
| `@fontsource/maven-pro` | 5.3.0 | `maven-pro-5.3.0/maven-pro-latin-400-normal.woff2` | `a8b66cd692819d6b627b31d2fac6faf4634ba46a906ce65f3ec9ce89dbb942ec` |
| `@fontsource/maven-pro` | 5.3.0 | `maven-pro-5.3.0/maven-pro-latin-500-normal.woff2` | `2160b2e8b70ce254222c6be5b740f0f3768c41fdc8f0abb84729e8a5bfc43772` |
| `@fontsource/maven-pro` | 5.3.0 | `maven-pro-5.3.0/maven-pro-latin-600-normal.woff2` | `272899d201ef84142fda960b4eef309493ef77bb308c2c7f622ad673c521e58b` |
| `@fontsource/maven-pro` | 5.3.0 | `maven-pro-5.3.0/maven-pro-latin-700-normal.woff2` | `f8c88308dd1e84b68baa0adf164d88a85f0e1819b97895f1e58874473d76f304` |

Integrità npm (sha512 del tarball):
- `bootstrap-5.3.8.tgz`: `HP1SZDqaLDPwsNiqRqi5NcP0SSXciX2s9E+RyqJIIqGo+vJeN5AJVM98CXmW/Wux0nQ5L7jeWUdplCEf0Ee+tg==`
- `htmx.org-2.0.11.tgz`: `Thx/WtpeOQqSrqBCw/A1cwGJGg4UrVa3+sW0GmrM3p4gJgO89ecH4qtbnyzDDWFvBTqjnIMCgELTNt636dtamA==`
- `bootstrap-icons-1.13.1.tgz`: `ijombt4v6bv5CLeXvRWKy7CuM3TRTuPEuGaGKvTV5cz65rQSY8RQ2JcHt6b90cBBAC7s8fsf2EkQDldzCoXUjw==`
- `tom-select-2.6.2.tgz`: `eiXIkk82XzzUTOVQDFpy+ZGejuqdTvMukyUyeZBQaKnqW42UoTiTZnrod/eX0rkqJEc4rZY9DZ3zdjV07i29wQ==`
- `flatpickr-4.6.13.tgz`: `97PMG/aywoYpB4IvbvUJi0RQi8vearvU0oov1WW3k0WZPBMrTQVqekSX5CjSG/M4Q3i6A/0FKXC7RyAoAUUSPw==`
- `@fontsource/maven-pro-5.3.0.tgz`: `W7z2U3t0XHUzAAFhx/rQTw8ga2OZkiwwEiNq1G1vJzE4shOs9d2Oj5kGmt+noaEKQR4jPB29upw9b61KFX4yXg==`
- `axe-core-4.13.0.tgz` (solo test, in `tests/e2e/vendor/`): `UzGt8zg7Ny8djbYMhxl2zuEevVa7r2gJjYY5Lwr1xM7+XU2nd6CkIWFTVcCIbAP63vSz71NaVyyuSk9lHKcy0A==`

Le source map sono escluse. Licenze (file `LICENSE` in ogni cartella): Bootstrap MIT, htmx Zero-Clause BSD,
Bootstrap Icons MIT, Tom Select Apache-2.0, flatpickr MIT, Maven Pro SIL Open Font License 1.1 (solo il
sottoinsieme latin, pesi 400–700), axe-core MPL-2.0 (solo nei test, mai servito dall'app).

Aggiornamento: scaricare il tarball da `https://registry.npmjs.org/<pkg>/-/<pkg>-<ver>.tgz`,
verificare `dist.integrity`, copiare i file `dist/` in una nuova cartella versionata, aggiornare
`templates/base.html` e questa tabella.
