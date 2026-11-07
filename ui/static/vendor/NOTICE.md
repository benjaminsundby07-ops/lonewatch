# Tredjepartsfiler i ui/static/vendor/

Disse ligger lokalt fordi **hele appen skal virke uten internett**. Lonewatch er
en demo som skal kunne kjøres i et rom uten nett, og en pitch som blir tom fordi
et CDN ikke svarer er ingen pitch. De er lastet ned én gang og endres aldri.

## React 18.3.1 og React DOM 18.3.1

| fil | hentet fra |
|---|---|
| `react.production.min.js` | `https://cdn.jsdelivr.net/npm/react@18.3.1/umd/react.production.min.js` |
| `react-dom.production.min.js` | `https://cdn.jsdelivr.net/npm/react-dom@18.3.1/umd/react-dom.production.min.js` |

Nøyaktig versjon 18.3.1, UMD-bygget for produksjon — det samme
`design-handoff/index.html` hentet fra jsDelivr.

**Lisens: MIT.** Opphavsrett Meta Platforms, Inc. og tilknyttede selskaper.
Lisensteksten står i `LICENSE-react.txt` og i toppen av hver fil.

Filene er ikke endret. Vil du bekrefte det, sammenlign dem med adressene over.

## Skriften

Plus Jakarta Sans ligger i `../dashboard/fonts/` med sin egen lisensfil
(SIL Open Font License 1.1). Se `../dashboard/fonts/LICENSE-plus-jakarta-sans.txt`.
