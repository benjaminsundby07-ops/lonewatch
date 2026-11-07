Lonewatch er et kontrollpanel for AI-agenter: før (sandkasse for nye tillegg), under (feller og røde varsler på risikable godkjenninger) og etter (logg agenten ikke kan endre). Designet er mørkt, rolig og presist, med én lys lavendelblå farge som eneste aksent. Utgangspunktet er et eksisterende dashborddesign, gjenskapt 1:1 med Lonewatch-innhold.

## Datasettet

- Alle tall og all tekst ligger i én konstant, `LONEWATCH_DATA`, øverst i `components/bundle.js` (også tilgjengelig som `Lonewatch.data`). Komponentene tegner bare fra den. Skriv aldri tall eller tekst direkte inn i en komponent.
- Ekte data fra backend sendes inn som `data` på `Dashboard`, eller med `Lonewatch.setData(...)`, i samme form.
- Så lenge `isExample` er `true`, vises merkelappen «Eksempeldata» (`example-ink` på `example-bg`). Den skal stå til tallene er koblet til ekte data.
- Vis bare tall Lonewatch faktisk har. Ingen oppdiktede prosenter, poengsummer, mål eller snitt. Mangler et tall, vises «–».

## Innhold og tone

- To språk, alltid begge: norsk (standard) og engelsk. All tekst ligger i `LONEWATCH_DATA.text.no` / `.en` og byttes med `LanguageToggle`. Ingen tekst skal være hardkodet i bare ett språk.
- Korte, konkrete etiketter i vanlig setningsstil: «Agentaktivitet», «Handlinger vurdert», «Agenter».
- Tallformat følger språket: `12,450` på engelsk, `12 450` på norsk. Klokkeslett vises i norsk tid.
- Ingen emoji. Tonen er saklig og trygg, aldri alarmistisk, selv for varsler.

## Farger

- Lag på lag av nesten-svart: `shell` er skallet, `sidebar` ikonmenyen, `panel` hver hovedblokk, `card` (med `card-top` som glans øverst) kortene inni et panel. Hvert lag skal være litt lysere enn laget under.
- `accent` er den eneste fargen med kulør i grensesnittet. Bruk den på hovedknappen, fremdriftsstreker, statusringen for loggkjeden og logoflaten. Tekst på `accent` er alltid `on-accent`.
- `ink` for all hovedtekst og store tall. `ink-muted` for etiketter, undertitler og tabelloverskrifter. `ink-faint` er kun pynt (prikkede ledelinjer), aldri tekst.
- `track` er alltid den ufylte delen av en strek eller ring. `line` deler tabellrader.
- `positive` og `negative` er ikke i bruk på oversikten nå (trendkolonnen er fjernet).
- Grafene bruker `chart-1` (blågrå), `chart-2` (sand) og `chart-3` (salvie) i den rekkefølgen, med et svakt fargefall under linjen.
- `backdrop` er det mørkeblå feltet bak skallet, og `promo-top` → `promo-mid` → `promo-bottom` er fargefallet i promokortet.

## Typografi

- Én familie: `Plus Jakarta Sans` (`--font-sans`), lastet fra Google Fonts i `bundle.css`. Hold bokstavavstanden litt stram.
- `metric` for store tall i kortene, `gauge` for statusen i ringen, `promo-title` for overskriften i promokortet, `panel-title` for panelnavn, `card-title` for korttitler og tabellceller, `body` for løpende tekst, `label` og `micro` for små etiketter.
- Vekter: 400 for tekst, 500 for tall og celler, 600 for titler. Aldri fet (700).

## Avstand, hjørner og skygge

- Panelene har `space-5` innvendig og `space-4` mellom seg. Kort inni panel har `space-4` innvendig og `space-3` mellomrom. Skallet har `space-6` innvendig.
- Hjørner øker med størrelsen: `radius-sm` tabelloverskrift, `radius-md` ikonfliser, `radius-lg` kort, `radius-xl` paneler, `radius-2xl` skallet, `radius-pill` knapper og streker.
- Kun skallet har skygge (`shadow-shell`). Inni skallet skilles flater med lysstyrke, ikke rammer eller skygger.

## Layout

- Skallet: 76 px ikonmeny + innhold. Øverste rad: promokort (340 px) og en kolonne med Agentaktivitet og raden med røde varsler. Nederste rad: tabellen Agenter og en kolonne (376 px) med Loggkjede og statusradene Sandkasse og Logg.
- Layouten er bygget for skrivebord (ca. 1180 px). En mobilversjon er ikke laget ennå.

## Fokus og tilgjengelighet

- Fokusring: 2 px heltrukket `accent` med 2 px avstand, på knapper, menyikoner og språkknappen.
- Strekene har `role="progressbar"` med verdier, og statusringen har `role="status"`. Grafene i kortene er dekorative; tallene under bærer informasjonen.

## Ikoner og bilder

- Egne 24 px strektegnede ikoner (1,7 px strek, runde ender) i `Lonewatch.Icon`. Fylt hus-ikon kun for aktiv Oversikt, som i originalen.
- Logoen er en midlertidig bokstavlogo (L med prikk) på `accent`-flate. Lonewatch har ingen ferdig logo ennå; bytt den når den finnes.
- Den blå glassfiguren (`GlassObject`) er en SVG-tilnærming til 3D-renderen i originalen. Bytt den med en ekte render via `art` på `PromoCard` når den finnes.
