# Hva nettsiden og menneskenøkkelen IKKE klarer

`ui/` er nettsiden og tilstanden bak den. Den eier ingen regler. Men siden
denne runden eier den to ting som betyr noe: **menneskenøkkelen** (hvem som får
godkjenne et rødt kort) og **koblingen til utføreren** (at en godkjenning
faktisk fører til at noe skjer). Her står hullene i begge, slik at ingen tror
noe annet.

Den ikke-tekniske versjonen av utføreren står i `docs/UTFORER.md`. Angrepene
som ble kjørt mot dette står i `docs/ANGREP.md`.

---

## 1. Menneskenøkkelen er en streng på maskinen, ikke en BankID

`LONEWATCH_HUMAN_KEY` ligger i klartekst to steder:

* i miljøet til terminalen som kjører appen
* i filen `.lonewatch-agent-env` (`chmod 600`, i `.gitignore`)

**En agent med fri tilgang til maskinen kan lese begge.** Claude Code har Bash
og filtilgang; `cat .lonewatch-agent-env` er ett kall. Da kan den godkjenne sitt
eget røde kort, og loggen vil si at et menneske gjorde det.

Nøkkelen gjør hullet smalere, og det er verdt noe:

| Før | Nå |
|---|---|
| Ett `curl` mot `/api/respond` godkjente 10 000 000 kr | Samme kall svarer 403 |
| Agentnøkkelen (som står i `.mcp.json`, en fil agenten selv leser) var nok | Agentnøkkelen avvises med 403 |
| En nettside operatøren besøkte ble avvist ved et uhell (kroppsformat) | Avvises fordi et egendefinert hode krever CORS-forhåndssjekk appen ikke svarer på |

Men den lukker det ikke. **Produksjonsversjonen må kreve noe som ikke finnes på
maskinen i det hele tatt:** en egen enhet eller en egen konto, slik BankID er -
en kode som kommer fra noe agenten ikke kan lese, og som er knyttet til en
person og ikke til en fil. Det er forskjellen mellom «agenten må lete» og
«agenten kan ikke».

Testen `test_aerlig_hull_menneskenoekkelen_ligger_paa_maskinen` i
`tests/test_agent_mcp_live.py` pinner dette med vilje: den gjør nøyaktig det en
agent med Bash ville gjort, og den SKAL bestå.

## 2. Loggen vet hvilken nøkkel som godkjente, ikke hvilken person

`employee_pseudonym` regnes ut av nøkkelen som kom inn
(`ui/human_key.py::operator_id` → `vault.pseudonymize`), ikke av en fast
konstant og ikke av et navn den som kaller skriver selv. To ulike nøkler gir to
ulike `emp_xxxx`.

Det betyr:

* **Én nøkkel per person** gir en logg som kan svare på hvem. Det er sånn
  `LONEWATCH_HUMAN_KEY` er ment brukt: flere nøkler skilt med komma.
* **Én delt nøkkel** - som i demoen, og som i oppsettet
  `python -m agent_gateway.oppsett` lager - gir én `emp_xxxx` for alle som har
  den. Da vet loggen **hva** som ble godkjent, men ikke **hvem** som gjorde det.
  Deler to mennesker en nøkkel, kan loggen ikke skille dem.

Det finnes ingen utløpstid, ingen rotasjon, ingen sperre etter mange feil
forsøk, og ingen måte å trekke tilbake én nøkkel uten å starte appen på nytt.

## 3. Nøkkelen ligger i nettleserens `sessionStorage`

Valget sto mellom to:

| | `sessionStorage` + eget HTTP-hode (valgt) | httpOnly-informasjonskapsel |
|---|---|---|
| CSRF | Umulig: en fremmed side kan ikke sette et egendefinert hode uten en CORS-forhåndssjekk appen ikke svarer på | Mulig: kapselen sendes automatisk. Måtte hatt et CSRF-token i tillegg |
| Lesbar for JS på siden | **Ja** | Nei |
| Overlever at fanen lukkes | Nei (med vilje: ingen blir stående innlogget på en projektor) | Ja, til den utløper |

Vi valgte det første fordi CSRF er den angrepsveien som ikke krever at noen
alt kjører kode på maskinen din - og fordi en kapsel ville krevd et CSRF-token
vi da måtte bygget og testet.

**Hva det ikke løser:** kjører det fremmed JavaScript på siden, kan det lese
nøkkelen ut av `sessionStorage`. Siden henter ingenting utenfra (ingen CDN,
ingen skrifter fra nettet, ingen sporing), og alt brukeren skriver escapes før
det vises - men det er et forsvar mot XSS, ikke en garanti.

Nøkkelen står aldri i en statisk fil nettleseren laster ned, aldri i en URL, og
aldri i et svar fra tjeneren.

## 4. Alle skriverutene er låst nå - men låsen er den samme strengen

Dette punktet sa til og med forrige runde «bare `/api/respond` er låst». Det er
rettet. Alle rutene som skriver i loggen eller endrer køen krever nå
menneskenøkkelen:

| Rute | Låst? | Nøkkel |
|---|---|---|
| `POST /api/respond` | **ja** | menneskenøkkel |
| `POST /api/human/check` | ja | samme (svarer bare om nøkkelen holdt) |
| `POST /api/reset` | **ja** (var åpen: H4 / A12) | menneskenøkkel |
| `POST /api/custom` | **ja** (var åpen: H25) | menneskenøkkel |
| `POST /api/feed/step` | **ja** (var åpen: H25) | menneskenøkkel |
| `POST /api/story/start`, `/api/story/step` | **ja** (var åpne) | menneskenøkkel |
| `POST /api/tamper` | **ja** (ny rute) | menneskenøkkel |
| `POST /api/agent/*` | ja | AGENTnøkkelen, og bare fra 127.0.0.1 |
| `GET /api/state` | **to nivåer** | se punkt 10 |
| alle andre `GET` | nei | - |

Det lukker H25: med `LONEWATCH_EXECUTOR=smtp` kunne et uautentisert lokalt kall
mot `/api/custom` utløse en ekte e-post til én av demoens tolv oppdiktede kjente
mottakere. Nå kreves nøkkelen først.

**Hva det ikke løser, og det er det viktige:** låsen er den samme strengen som i
punkt 1. En agent med Bash kan lese `.lonewatch-agent-env` og dermed gjøre
*alt* på listen over - godkjenne, nullstille, spille av hendelsen, bryte
loggen. Vi har gjort det vanskeligere for en prosess som bare når porten; vi har
ikke gjort det vanskeligere for en agent som eier maskinen. Testen
`test_aerlig_hull_menneskenoekkelen_ligger_paa_maskinen` i
`tests/test_agent_mcp_live.py` gjør nøyaktig det en agent med Bash ville gjort,
og den SKAL bestå.

Det er også et valg at demoknappene ligger bak samme nøkkel som godkjenningen
og ikke bak en egen, svakere «demonøkkel». To nøkler ville betydd at den som
holder demoen må skrive inn to strenger, og at den svakeste av dem ville blitt
den som faktisk ble brukt.

## 5. Feiler lukket - og det merkes

Er `LONEWATCH_HUMAN_KEY` ikke satt, svarer `/api/respond` **503**, og ingenting
kan godkjennes. Det samme skjer hvis noen setter menneskenøkkelen til samme
verdi som agentnøkkelen: da er skillet borte, og vi svarer nei til alle i
stedet for ja til agenten.

Prisen er at demoen ikke virker uten oppsettet. Det er med vilje: en port som
åpner seg når oppsettet mangler er ingen port.

## 6. Betenkningstiden er ekte, men den måler skjermtid - ikke oppmerksomhet

`seconds_to_decide` måles av tjeneren, fra kortet ble lagt i køen til svaret
kom, med `time.monotonic()`. Den kan ikke oppgis av klienten lenger (et forsøk
gir 422).

Det den IKKE sier: at noen så på kortet. Et kort som sto i køen i to timer mens
operatøren var på lunsj får 7200 sekunder. Tallet er en nedre grense for hvor
lenge saken var tilgjengelig, ikke et mål på hvor lenge noen tenkte.

## 7. Forseglingen stopper en agent, ikke noen som kjører kode i appen

`Approval.request_fingerprint` er en SHA-256 uten nøkkel. Den ligger på kortet
inne i `DemoState` og sendes **aldri** til nettleseren - `_public()` tar den
bort, og `tests/test_executor_wiring.py` går gjennom hele API-flaten og sjekker
det.

Den stopper at en forespørsel endres mellom avgjørelsen og godkjenningen. Den
stopper ikke noen som kan kjøre kode i samme prosess: de kan lage en `Approval`
med det avtrykket de vil. Se `executor/LIMITS.md` punkt 3.

## 8. Utføreren er koblet inn to steder, og bare to

`allow` utføres i `_handle()`, og en godkjent `red` i `respond()`. En rød sak
som venter, en avvist sak og en blokkert sak kommer aldri til utføreren -
porten i `executor/gate.py` ville nektet dem uansett, men vi kaller den heller
ikke.

Standard er `SimulatedExecutor`, som gjør ingenting. `SmtpExecutor` må slås på
med `LONEWATCH_EXECUTOR=smtp`, og sender bare til loopback med mindre
`LONEWATCH_SMTP_ALLOW_REMOTE=1` er satt med vilje. Resten av hullene i
sendingen står i `executor/LIMITS.md`.

`run_demo.py` er IKKE koblet til utføreren. Den er en ren regel- og
loggdemonstrasjon i terminalen, og den skriver fortsatt 88 linjer.

## 9. «Oversikt», «Godkjenning» og «Etter» kan bli høyere enn skjermen

Målt i nettleseren (Playwright, Chromium) på 1440×900 og 1920×1080, både låst
og opplåst side, gjennom alle fem fanene: **ingen vannrett rulling noe sted**,
og **null forespørsler ut av maskinen**.

Loddrett, slik det ble målt denne runden:

| Fane | 1440×900 | 1920×1080 |
|---|---|---|
| Oversikt, Før, Godkjenning | innenfor | innenfor |
| **Etter** (med «Bryt loggen») | innenfor | innenfor |
| **Prøv selv** | **922 px, altså 22 px for høy** | innenfor |

«Prøv selv» var 22 px for høy FØR denne runden også - det er skjemaet med ni
felt som er høyt, og ingenting her gjorde det høyere. Den står igjen.

«Bryt loggen» kom inn på Etter denne runden, og det kostet noe: logg-tabellen
ruller nå innvendig fra 200 px i stedet for 520 px, og «Oppfølging» og
resultatkortet fikk også innvendig rulling. Det er et bevisst bytte - «Bryt
loggen» skal kunne leses ved siden av «Sjekk loggen» rett over, og det kan den
ikke hvis den ene er utenfor skjermen. Resultatet viser dessuten **ett** angrep
av gangen og ikke fire under hverandre; knappene viser hvilke som er kjørt.

Låst-banneret vises ikke på «Prøv selv». Der står beskjeden i skjemaet, rett
under knappen man trykket - og tre linjer banner i tillegg hadde gjort den
høyeste fanen høyere.

## 10. `/api/state` har to nivåer, og det laveste er en allowliste

A1 i `docs/ANGREP2.md` var det alvorligste nye hullet i runde to: `/api/state`
var uautentisert og returnerte kortene fra **minnet**, ikke den minimerte
loggen. Full mottaker, agentens frie `summary` og de interne regelnavnene
(`unknown_recipient`, `personal_data_external`) sto der i klartekst. Loggen
maskerer akkurat de feltene, så den som leste HTTP-flaten fikk **mer** enn den
som leste loggen.

Nå:

| | Uten menneskenøkkel | Med |
|---|---|---|
| Tellere, status, risiko, utfall | ja | ja |
| Mottaker | maskert (`****1234`) | hele |
| `summary` (agentens frie tekst) | **nei** | ja |
| `decision.reasons` (regelnavn) | **nei** | ja |
| `consequence_text` | **nei** | ja |
| Sandkasserapporter («Før») | **nei** | ja |
| Notiser (fri tekst) | **nei** | ja |
| `log.archived` (filsti) | **nei** | ja |

Tre ting om valget:

1. **To nivåer og ikke 403.** Et `/api/state` som nekter ville gjort nettsiden
   tom før noen hadde logget inn, og da ser ingen at det *er* en mellomstasjon
   her. Demoen begynner med at juryen ser køen og deretter låser opp.
2. **Allowliste, ikke denyliste.** `ui.state.minimized_snapshot()` bygger et
   nytt svar av navngitte felt. Legger noen et nytt felt i `snapshot()`, mangler
   det på den låste siden - en synlig feil. Med en denyliste ville det lekket i
   stillhet, og det er samme feil om igjen.
3. **Samme maskering som loggen.** Mottakeren maskeres med
   `vault.redaction.mask_recipient`, altså funksjonen loggen selv bruker. Da kan
   den låste siden per konstruksjon ikke vise mer av en konto enn loggen gjør.

**Hva det ikke løser:** nivået er bundet til nøkkelen, ikke til en person eller
en rolle. Den som har nøkkelen får alt. Og `GET /api/log`, `/api/overview`,
`/api/after`, `/api/verify` og `/api/trail` er fortsatt åpne - de leser
**loggen**, som alt er minimert, og de ble angrepet i
`tests/attack2/test_attack_routes.py`. `/api/trail` tar en `request_id` og
svarer fra minnet; den er ikke delt i to nivåer, og det står igjen.

## 11. Grensene er tak, ikke et forsvar mot noen som har nøkkelen

Tre tall, og hvert av dem er valgt av demoen:

| Grense | Verdi | Hvorfor tallet | Svar |
|---|---|---|---|
| Kroppsstørrelse | 64 KB | Største lovlige skjema er under 1 KB. 64 KB er ~110× det, og under én TCP-vindusfylling | 413 |
| Antall kort | 200 | Hele demoen er 44 kort (40 i strømmen + 4 i hendelsen). 200 gir plass til demoen pluss 156 egne | `ok: false` med forklaring |
| `/api/agent/submit` | 30 per minutt per agentnøkkel | Manusdemoen er 6 kall. 30 er langt over alt legitimt, og fortsatt raskere enn et menneske kan lese kort | 429 + `Retry-After` |

Hva de IKKE gjør:

* **Kroppsgrensen svarer 413 først når klienten rakk å bli ferdig med å sende.**
  Appen avviser på `Content-Length` *uten å lese kroppen* - det er hele poenget -
  så en klient som fortsatt skriver 3 MB når svaret kommer, ser et avbrutt
  samband og ikke en pen 413. Å kreve en pen 413 der ville tvunget appen til å
  lese de 3 MB først, og da er grensen pynt.
* **Fartsgrensen gjelder bare over HTTP.** Den teller i `ui/app.py`, fordi
  agentnøkkelen er et HTTP-begrep. En kaller i samme prosess (manusdemoen kaller
  `api_agent_submit()` rett) telles ikke. Den som kan kalle funksjonen direkte
  har allerede kjøringsrett i prosessen, og da er ikke fartsgrensen det som
  beskytter noe. Kort-taket gjelder også der, fordi det står i `ui/state.py`.
* **Kort-taket er ikke et tak på logglinjer over tid.** 200 er hvor mange kort
  som finnes samtidig. Den som nullstiller og fyller på nytt kan gjenta det -
  men det krever nøkkelen hver gang, og hver nullstilling *arkiverer* den gamle
  loggen i stedet for å slette den.
* **Fartsgrensen ligger i minnet** og nullstilles når appen startes på nytt
  (og av «Nullstill»). Den er ikke en kvote over tid.
* **Ingen av dem hjelper mot den som har menneskenøkkelen.** De stopper støy og
  uhell, ikke en angriper som eier maskinen.

## 12. «Bryt loggen» gjør noe destruktivt med vilje - her er hva den ikke gjør

De fire knappene i Etter kaller `vault.tamper_demo.run_attack()`, som kopierer
loggen til en midlertidig mappe, angriper **kopien**, og lar den vanlige
`Vault.verify_detail()` svare. Den ekte loggen og det ekte ankeret åpnes bare
for lesing, og `run_attack` tar fingeravtrykk (navn, sha256, størrelse) før og
etter og **kaster** hvis de ikke er like.

Forbeholdene:

* **`full` blir ikke oppdaget, og det er sant.** Angriperen har loggnøkkelen,
  regner hash-kjeden på nytt og signerer et nytt hale-anker (signeringsnøkkelen
  er avledet fra loggnøkkelen). Verifiseringen svarer «i orden», og det er
  riktig svar på alt den kan se. Knappen viser den som «grensen, sagt ærlig» -
  ikke i rødt, ikke som en feil - med begge hashene ved siden av hverandre,
  fordi det er sammenligningen med en hash du skrev ned **utenfor maskinen** som
  faktisk avslører det. Står i `vault/LIMITS.md` punkt 1 og 12.
* **Ruten leser loggnøkkelen.** Den krever menneskenøkkelen, men den er ikke
  et «trygt» endepunkt: den dekrypterer hele loggen i prosessen.
* **Kroppen eier ingenting annet enn hvilket angrep.** `extra="forbid"` og ett
  felt. Kunne kroppen oppgi `path`, ville knappen vært en vilkårlig fil-leser
  bak ett HTTP-kall; kunne den oppgi `detected`, kunne et angrep fortalt
  nettsiden at det ble oppdaget.
* **409-meldingen fra `tamper_demo` navngir loggfilen med full sti.** Det er
  riktig i en terminal, der den som leser eier filen, og galt i et HTTP-svar.
  Funnet av `tests/attack2/test_attack_tamper_route.py` mens ruten ble skrevet.
  `vault/tamper_demo.py` eies ikke herfra, så stien kuttes til filnavnet på vei
  ut (`ui.app._no_paths`). Terminalversjonen er uendret.
* **Angrepet er på en kopi, så det beviser ikke noe om disken.** Det beviser at
  hash-kjeden fanger en endret, slettet eller kuttet linje. Det sier ingenting
  om filsystemrettigheter, backup eller hvem som kan nå loggmappen.
