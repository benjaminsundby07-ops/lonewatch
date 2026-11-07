# Dashboard

Hele Lonewatch-oversikten, tegnet fra datasettet `Lonewatch.data` (konstanten `LONEWATCH_DATA` øverst i bundle.js). Utseendet er det samme som originaldesignet; bare tekst og tall er byttet.

**Du gir:** valgfritt `data` (samme form som `LONEWATCH_DATA`, f.eks. ekte tall fra backend), `lang` (`'no'` standard eller `'en'`), `onLangChange`, `onNavigate(tab)` og `bare`.

- Så lenge `data.isExample` er `true`, vises merkelappen «Eksempeldata» øverst til høyre.
- «Prøv selv» kaller `onNavigate('custom')`. Uten `onNavigate` sendes hendelsen `lonewatch:navigate` på `window`.
- Ingen tall står i komponentene. Mangler et tall, vises «–».
