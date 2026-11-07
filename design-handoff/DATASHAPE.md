# LONEWATCH_DATA: formen på datasettet

Dashbordet tegnes bare fra ett objekt, `LONEWATCH_DATA`, som ligger øverst i `components/bundle.js`.
Det finnes også som `window.Lonewatch.data`. Ingen tall eller tekst er skrevet inn i komponentene.

## Slik startes det alene

- Åpne `index.html` i en nettleser (dobbeltklikk). Det trengs ingen server og ingen byggesteg.
- Språk og rammeverk: ren JavaScript (ES5, ett klassisk `<script>`, ingen import) med **React 18**
  (`React.createElement`, ingen JSX). CSS ligger i `components/bundle.css` og `tokens.css`, med farger og
  avstander som CSS-variabler.
- React lastes fra jsDelivr i `index.html`. Uten internett blir siden tom (se listen over eksterne adresser
  nederst).
- Filene `components/*/preview.html` er forhåndsvisninger for designsystemet. De forventer at designsystem-siden
  laster tokens, CSS, React og bundle.js for dem, og virker ikke alene. Det er `index.html` som viser dashbordet.

## Slik byttes dataene

- Send et eget objekt med samme form: `React.createElement(Lonewatch.Dashboard, { data: mittDatasett })`.
- Eller `Lonewatch.setData(mittDatasett)`. Den bytter innholdet i `LONEWATCH_DATA`, men tegner ikke på nytt
  av seg selv: dashbordet må tegnes (render) igjen etterpå.
- Andre props på `Dashboard`: `lang` (`"no"` | `"en"`), `onLangChange(lang)`, `onNavigate(tab)`, `bare`.
  `tab` er `"overview"`, `"before"`, `"under"`, `"after"` eller `"custom"`. Uten `onNavigate` sendes
  hendelsen `lonewatch:navigate` på `window` med `detail.tab`.

## Felter

Typer: `number | null` betyr at feltet kan mangle eller være `null`. Da vises «–». Alt som ikke er et
endelig tall (også `undefined`, tekst og `NaN`) regnes som manglende.

### Toppnivå

| Felt | Type | Brukes til | Når det mangler |
|---|---|---|---|
| `isExample` | boolean | `true` viser merkelappen «Eksempeldata» øverst til høyre | ingen merkelapp |
| `defaultLang` | `"no"` \| `"en"` | språket dashbordet starter på når `lang` ikke er gitt | `"no"` |
| `counts` | objekt | tallene i kortene og raden under | alle tall blir «–» |
| `agents` | liste | radene i tabellen «Agenter» | tom tabell (bare overskrifter) |
| `logChain` | objekt | ringen «Loggkjede» | tom ring med «–» og «Ikke sjekket ennå» |
| `sandbox` | objekt | raden «Sandkasse» | «– testet, – blokkert» |
| `log` | objekt | raden «Logg» | «–» |
| `chartShapes` | liste | formen på de tre kurvene (pynt, se under) | flat linje |
| `text` | objekt med `no` og `en` | all tekst på begge språk | se under |

### `counts` (bare tall)

| Felt | Type | Vises som | Når det mangler |
|---|---|---|---|
| `evaluated` | number \| null | kortet «Handlinger vurdert» | «–» |
| `red` | number \| null | kortet «Røde varsler», og nevneren i «x av y» i raden under | «–». Strekene i raden under blir tomme |
| `blocked` | number \| null | kortet «Blokkert» | «–» |
| `allowed` | number \| null | raden «Sluppet gjennom» i første kort | «–» |
| `waitingForHuman` | number \| null | «Røde varsler som venter på menneske»: «x av red», strek = x / red | «– av 7», tom strek |
| `followedUp` | number \| null | «Fulgt opp»: «x av red», strek = x / red | «– av 7», tom strek |

Strekene blir tomme når `red` er 0 eller mangler. Verdier over `red` gir full strek.

### `agents[]` (én rad per agent, i listens rekkefølge)

| Felt | Type | Vises som | Når det mangler |
|---|---|---|---|
| `id` | string | brukes bare som nøkkel, og som navn hvis `name` mangler | |
| `name.no` / `name.en` | string (tekst på begge språk) | kolonnen Agent | faller tilbake til `name.no`, så til `id` |
| `actions` | number \| null | Handlinger | «–» |
| `red` | number \| null | Røde | «–» |
| `blocked` | number \| null | Blokkert | «–» |
| `allowed` | number \| null | Sluppet gjennom | «–» |

### `logChain`

| Felt | Type | Vises som | Når det mangler |
|---|---|---|---|
| `status` | `"ok"` \| `"broken"` \| null | `"ok"`: full ring og teksten `text.status.ok`. `"broken"`: tom ring og `text.status.broken`. `null`: tom ring og `text.status.none` («–») | som `null` |
| `checkedAt` | ISO 8601-tid (string) \| null | «Sist sjekket: hh:mm» i norsk tid | teksten `text.notChecked`. En ugyldig tid gir «–» |

### `sandbox` (bare tall)

| Felt | Type | Vises som | Når det mangler |
|---|---|---|---|
| `tested` | number \| null | `{tested}` i `text.sandboxStatus` | «–» |
| `blocked` | number \| null | `{blocked}` i `text.sandboxStatus` | «–» |

### `log`

| Felt | Type | Vises som | Når det mangler |
|---|---|---|---|
| `status` | `"ok"` \| `"broken"` \| null | raden «Logg»: `text.status.ok` / `.broken` / `.none` | «–» |

### `chartShapes[]` (tre elementer, ett per kort, i rekkefølgen Handlinger vurdert, Røde varsler, Blokkert)

| Felt | Type | Brukes til |
|---|---|---|
| `data` | number[] (minst 2) | hovedkurven. Bare formen brukes: kurven skaleres mellom minste og største verdi |
| `ghost` | number[] (valgfri) | den svake kurven bak |
| `marks` | number[] (valgfri) | indekser i `data` som får en liten sirkel. **Må være gyldige indekser**: en indeks utenfor `data` gir en feil, og dashbordet tegnes ikke |

Mangler et element, tegnes en flat linje.

### `text.no` og `text.en` (alt er tekst, på begge språk)

Begge språk må ha alle nøklene. Mangler `text[lang]`, brukes `text[defaultLang]`. Mangler en enkeltnøkkel,
blir teksten tom, og mangler `status`, `stats`, `cols` eller `nav`, tegnes ikke dashbordet.

| Nøkkel | Type | Vises som |
|---|---|---|
| `exampleTag` | string | merkelappen «Eksempeldata» |
| `nav` | string[5] | verktøytips på menyikonene: Oversikt, Før, Under, Etter, Prøv selv |
| `alerts`, `account`, `language` | string | verktøytips og skjermlesertekst i menyen |
| `promoTitle`, `promoText`, `promoCta` | string | promokortet og knappen «Prøv selv» |
| `activity` | string | tittelen «Agentaktivitet» |
| `range` | string | «I dag» oppe til høyre (bare tekst, ingen funksjon) |
| `stats` | string[3] | titlene på de tre kortene |
| `allowed` | string | «Sluppet gjennom» i første kort |
| `waiting`, `followed` | string | etikettene i raden under kortene |
| `of` | string | ordet i «x av y» |
| `table`, `viewAll` | string | «Agenter» og «Se alle» |
| `cols` | string[5] | kolonneoverskriftene |
| `logChain`, `logChainSub` | string | «Loggkjede» og «Sjekk av logg» |
| `lastChecked`, `notChecked` | string | «Sist sjekket:» og «Ikke sjekket ennå» |
| `status.ok`, `status.broken`, `status.none` | string | statusordene i ringen og raden «Logg» |
| `sandboxRow`, `logRow` | string | «Sandkasse» og «Logg» |
| `sandboxStatus` | string med plassholdere | «{tested} testet, {blocked} blokkert». `{tested}` og `{blocked}` byttes med tall fra `sandbox` |

Tall formateres etter språket (`nb-NO`: `12 450`, `en-US`: `12,450`).

## Hva som er rent dekorativt

| Del av designet | Bruker data? | Kan tegnes fra |
|---|---|---|
| Kurvene i de tre kortene | Ja, men bare formen fra `chartShapes`, ingen akser eller verdier. Formen nå er oppdiktet eksempeldata | Et ekte forløp over tid, f.eks. antall vurderte, røde og blokkerte per minutt fra loggen. Finnes ikke i backend i dag |
| Sirklene på kurvene | `chartShapes[].marks` | Tidspunkter for røde varsler, hvis forløpet over finnes |
| Den blå glassfiguren i promokortet | Nei | Ingenting. Ren pynt |
| Logoen (L med prikk) | Nei | Midlertidig. Lonewatch har ingen logo |
| «I dag» med pil | Bare teksten `text.range` | Har ingen funksjon. Et ekte tidsfilter finnes ikke |
| Menyikonene (hus, kalender, liste, graf, tannhjul) | Bare verktøytipsene fra `text.nav` | Ikonene er fra originaldesignet og passer ikke helt til Før/Under/Etter |
| Varselklokken og profilbildet i menyen | Nei | Ingenting |
| Strekene i raden under kortene | Ja: `waitingForHuman / red` og `followedUp / red` | |
| Ringen | Ja: full ved `logChain.status === "ok"`, ellers tom | |

## Fullt eksempel (dagens eksempeldata)

```json
{
  "isExample": true,
  "defaultLang": "no",
  "counts": {
    "evaluated": 40,
    "red": 7,
    "blocked": 1,
    "allowed": 32,
    "waitingForHuman": 1,
    "followedUp": 6
  },
  "agents": [
    {
      "id": "customer_service",
      "name": {
        "no": "Kundeservice",
        "en": "Customer service"
      },
      "actions": 9,
      "red": 2,
      "blocked": 0,
      "allowed": 7
    },
    {
      "id": "procurement",
      "name": {
        "no": "Innkjøp",
        "en": "Procurement"
      },
      "actions": 8,
      "red": 1,
      "blocked": 0,
      "allowed": 7
    },
    {
      "id": "finance",
      "name": {
        "no": "Økonomi",
        "en": "Finance"
      },
      "actions": 9,
      "red": 2,
      "blocked": 0,
      "allowed": 7
    },
    {
      "id": "hr",
      "name": {
        "no": "HR",
        "en": "HR"
      },
      "actions": 7,
      "red": 1,
      "blocked": 0,
      "allowed": 6
    },
    {
      "id": "it_helper",
      "name": {
        "no": "IT-hjelp",
        "en": "IT help"
      },
      "actions": 7,
      "red": 1,
      "blocked": 1,
      "allowed": 5
    }
  ],
  "logChain": {
    "status": "ok",
    "checkedAt": "2026-11-07T09:10:00Z"
  },
  "sandbox": {
    "tested": 2,
    "blocked": 1
  },
  "log": {
    "status": "ok"
  },
  "chartShapes": [
    {
      "data": [
        52,
        60,
        66,
        58,
        63,
        44,
        40,
        52,
        36,
        48,
        58,
        66,
        54,
        62
      ],
      "ghost": [
        40,
        46,
        50,
        56,
        50,
        44,
        50,
        56,
        60,
        52,
        48,
        54,
        58,
        50
      ],
      "marks": [
        5,
        8
      ]
    },
    {
      "data": [
        30,
        64,
        50,
        44,
        52,
        40,
        38,
        48,
        36,
        30,
        42,
        34,
        46,
        54
      ],
      "ghost": [
        24,
        40,
        56,
        48,
        36,
        44,
        52,
        42,
        34,
        40,
        46,
        40,
        36,
        44
      ],
      "marks": [
        4,
        8
      ]
    },
    {
      "data": [
        44,
        52,
        60,
        54,
        50,
        62,
        54,
        46,
        40,
        34,
        44,
        50,
        42,
        36
      ],
      "ghost": [
        36,
        44,
        46,
        50,
        56,
        52,
        46,
        50,
        42,
        40,
        46,
        40,
        48,
        52
      ],
      "marks": [
        5,
        9
      ]
    }
  ],
  "text": {
    "no": {
      "exampleTag": "Eksempeldata",
      "nav": [
        "Oversikt",
        "Før",
        "Under",
        "Etter",
        "Prøv selv"
      ],
      "alerts": "Varsler",
      "account": "Konto",
      "language": "Språk",
      "promoTitle": "Send din egen forespørsel",
      "promoText": "Skriv en forespørsel og se den gå gjennom de samme reglene som demoen. Ingenting er avgjort på forhånd.",
      "promoCta": "Prøv selv",
      "activity": "Agentaktivitet",
      "range": "I dag",
      "stats": [
        "Handlinger vurdert",
        "Røde varsler",
        "Blokkert"
      ],
      "allowed": "Sluppet gjennom",
      "waiting": "Røde varsler som venter på menneske",
      "followed": "Fulgt opp",
      "of": "av",
      "table": "Agenter",
      "viewAll": "Se alle",
      "cols": [
        "Agent",
        "Handlinger",
        "Røde",
        "Blokkert",
        "Sluppet gjennom"
      ],
      "logChain": "Loggkjede",
      "logChainSub": "Sjekk av logg",
      "lastChecked": "Sist sjekket:",
      "notChecked": "Ikke sjekket ennå",
      "status": {
        "ok": "OK",
        "broken": "Feil",
        "none": "–"
      },
      "sandboxRow": "Sandkasse",
      "logRow": "Logg",
      "sandboxStatus": "{tested} testet, {blocked} blokkert"
    },
    "en": {
      "exampleTag": "Example data",
      "nav": [
        "Overview",
        "Before",
        "During",
        "After",
        "Try it yourself"
      ],
      "alerts": "Alerts",
      "account": "Account",
      "language": "Language",
      "promoTitle": "Send your own request",
      "promoText": "Write a request and watch it go through the same rules as the demo. Nothing is decided in advance.",
      "promoCta": "Try it yourself",
      "activity": "Agent activity",
      "range": "Today",
      "stats": [
        "Actions evaluated",
        "Red alerts",
        "Blocked"
      ],
      "allowed": "Let through",
      "waiting": "Red alerts waiting for a human",
      "followed": "Followed up",
      "of": "of",
      "table": "Agents",
      "viewAll": "View all",
      "cols": [
        "Agent",
        "Actions",
        "Red",
        "Blocked",
        "Let through"
      ],
      "logChain": "Log chain",
      "logChainSub": "Log check",
      "lastChecked": "Last checked:",
      "notChecked": "Not checked yet",
      "status": {
        "ok": "OK",
        "broken": "Broken",
        "none": "–"
      },
      "sandboxRow": "Sandbox",
      "logRow": "Log",
      "sandboxStatus": "{tested} tested, {blocked} blocked"
    }
  }
}
```

## Eksterne adresser

| Adresse | Hentes av | Hva skjer hvis den ikke svarer |
|---|---|---|
| `https://cdn.jsdelivr.net/npm/react@18.3.1/umd/react.production.min.js` | `index.html` | Siden blir helt tom. Testet: `React` og `ReactDOM` finnes ikke, og bundle.js stopper |
| `https://cdn.jsdelivr.net/npm/react-dom@18.3.1/umd/react-dom.production.min.js` | `index.html` | Som over |
| `https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600&display=swap` | `@import` øverst i `components/bundle.css` | Alt vises, men med reservefonten (Helvetica Neue / Arial). Tekst blir litt bredere eller smalere. Testet |
| `https://fonts.gstatic.com/…` | stilarket fra Google Fonts over | Som over |

Ingen bilder, ikoner eller fonter ligger som filer. Ikonene og glassfiguren er SVG tegnet i `bundle.js`.
