# Lonewatch

**Summary in English.** Lonewatch is a control station between a company's AI agents and the
tools they use. Every action an agent wants to take is judged before it happens, and the answer
is `allow`, `red` (a human must look at it) or `block`. Everything is written to an encrypted,
hash-chained log, so no line can be changed unseen. The whole project is a simulation. No real
company, no real money, no real malware. One single connection is real, and section 5 says which.

Resten av denne filen er på norsk.

---

## 1. Hva Lonewatch er

Lonewatch er en kontrollstasjon som står mellom en bedrifts AI-agenter og verktøyene deres, og
vurderer hver handling før den skjer.

Det er laget for mellomstore bedrifter med omtrent 50 til 250 ansatte, som ikke har eget
sikkerhetsteam, og som setter AI-agenter til å jobbe med penger, e-post, dokumenter og tillegg.
De har agenter i drift, men ingen som følger med på hva agentene faktisk gjør.

Flyten er `agent -> ActionRequest -> gateway.evaluate() -> Decision`. Et `allow` går gjennom.
Et `red` legges i en kø og venter på et menneske. Et `block` avvises, og ingen kan godkjenne det.
Alt som skjer havner i loggen.

## 2. Problemet

En agent som behandler fakturaer leser et dokument. I dokumentet ligger en instruksjon et
menneske ikke ser, og den ber agenten bytte kontonummer og betale til en ny konto. Agenten gjør
som den blir bedt om, fordi den ikke kan skille en instruksjon fra innholdet den skal behandle.

Dokumentet finnes i demoen. `agents/traps.py` har fire oppdiktede dokumenter der det andre laget
er usynlig for mennesker, enten som hvit tekst på hvit bakgrunn, skriftstørrelse 1 px,
nullbredde-tegn eller et felt i metadata. Fakturaen `doc_invoice_8841` ber agenten bruke kontoen
`NO93 8601 1117 947` og ikke varsle noen.

Det hjelper ikke å spørre agenten hva den holder på med. Agentens egen forklaring er nettopp det
et dokument kan ha skrevet for den. I demodataene heter den farligste forespørselen «Betaler
samleoppgjør for takseringsoppdrag, haster før forfall», og den gjelder en overføring på
10 000 000 kr til en konto ingen har sett før.

Dette er et nytt problem som vokser. Det er ikke stort i dag. Det blir større for hver agent en
bedrift gir tilgang til penger, e-post og dokumenter.

## 3. Hvordan det virker

Tre steg, og bare det som faktisk er bygget.

### Før: tillegget prøves i en lukket boks (SIMULERT)

Skal et tillegg installeres, kjøres det i `sandbox/` før kontrollstasjonen bestemmer seg.
Tillegget kjøres i en egen Python-delprosess med et miljø bygget fra null. `socket` er byttet ut
med noe som skriver ned adressen og sier nei. `open` avviser lesing og skriving utenfor boksen.
`HOME` peker på en falsk hjemmemappe med ni oppdiktede filer. Fem av dem er agn, og blir ett av
dem lest, blir det skrevet ned.

Resultatet er en `SandboxReport` med `clean`, `blocked` eller `not_tested`, avgjort av en fast
regel på hva tillegget gjorde. Tidsgrensen er 6 sekunder. `not_tested` betyr at tillegget aldri
kom i gang, og skal aldri leses som en klarering.

Sandkassen kjører bare filer som alt ligger i `sandbox/packages/`. Et pakkenavn fra en
forespørsel fører aldri til at noe lastes ned. Dette er ikke ekte isolasjon, se seksjon 8.

### Under: reglene stopper det farlige, og et menneske må skrive beløpet

Åtte risikoregler gir poeng. Reglene står i `gateway/rules.py` og vektene i `gateway/config.py`.
`amount_over_limit` (2),
`recipient_total_over_limit` (2), `unknown_recipient` (2), `personal_data_external` (3),
`new_package` (2), `destructive_change` (2), `incomplete_request` (2) og `irreversible` (1).
0 til 1 poeng er `low` og gir `allow`, 2 til 3 er `medium`, 4 og over er `high`. Alt som ikke er
`low` blir `red`. To regler blokkerer helt, `package_on_blocklist` og
`transfer_over_hard_limit`, og i tillegg `sandbox_blocked` fra Før-steget. Grensene er 50 000 kr
(rødt fra og med) og 50 000 000 kr (blokk over). Tallene står i `gateway/config.py` fordi en
bedrift må kunne sette sine egne.

**Reglene er deterministiske.** Samme forespørsel gir samme svar hver gang. Ingen AI-modell er
involvert i å bestemme `allow`, `red` eller `block`, og ingen i å skrive varselteksten.

**Agentens egen forklaring brukes aldri.** `ActionRequest.summary` leses ikke av noen regel.
Den vises i kortet, slik at et menneske kan se hva agenten sa, men den kan ikke flytte en
avgjørelse. Hadde den kunnet det, ville et dokument kunnet skrive sin egen godkjenning.

Varselteksten lages av maler og felt i `gateway/consequence.py`, på vanlig norsk. «Overfører
10 000 000 kr til ukjent konto. Kan ikke angres.» For røde pengeoverføringer settes
`requires_typed_amount`, og da må mennesket skrive beløpet selv før Godkjenn blir aktiv. Feil
tall avvises av tjeneren også. Tallet tolkes som et beløp og ikke som en siffersekvens, så
`100000,00` er hundre tusen kroner og blir avvist mot ti millioner.

Godkjenningen krever en egen menneskenøkkel (`LONEWATCH_HUMAN_KEY`, et HTTP-hode mot
`/api/respond`). Agentens egen nøkkel duger ikke, og er menneskenøkkelen ikke satt, kan
ingenting godkjennes.

### Etter: loggen som sier fra hvis noen endrer den

Hver linje krypteres med Fernet før den skrives til disk, med nøkkel bare fra miljøvariabel.
Hver linje peker på den forrige med SHA-256. `verify()` leser og dekrypterer hele filen på nytt
fra disk og peker på `seq` til første linje som er endret, uleselig eller på feil plass. Ved
siden av loggen ligger et hale-anker (`<logg>.head`) som er signert med HMAC-SHA256, og som
fanger at de siste linjene er kuttet bort.

«Bryt loggen» viser det, og viser også hva det ikke klarer.

```bash
python -m vault.tamper_demo --attack alle
```

Den angriper en kopi av loggen og lar den samme verifiseringen svare. `endre` og `slett` blir
oppdaget og peker ut riktig linje. `kutt` fanges av hale-ankeret. `full`, der angriperen har
loggnøkkelen og regner kjeden og ankeret på nytt, blir **ikke** oppdaget, og det er riktig svar
på alt loggen kan se. Det eneste som fanger det, er siste hash skrevet ned utenfor maskinen.

`vault/after.py` bygger Etter-listen rett fra logglinjene, med en eier per linje. Ingen AI, ingen
gjetting.

## 4. Prøv det selv

Python 3.11 eller nyere. Kjørt og verifisert på macOS med Python 3.11.9.

### Oppsett

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Nøklene leses fra miljøvariabler og ligger aldri i koden. Det finnes ingen stille standardnøkkel.

```bash
export LONEWATCH_LOG_KEY=$(python -m vault.gen_key)
export LONEWATCH_PSEUDONYM_KEY=$(python -m vault.gen_key --pseudonym)
export LONEWATCH_HUMAN_KEY=$(python -m vault.gen_key --human)
```

`python -m vault.gen_key --both` skriver alle tre linjene ferdige til å lime inn. Loggfilen
havner i `lonewatch_log.jsonl` i prosjektmappen og kan flyttes med `LONEWATCH_LOG_PATH`.

### Nettsiden

```bash
python -m ui
```

Åpne <http://127.0.0.1:8000>. Fanene er Oversikt, Før, Godkjenning, Etter og Prøv selv.
Gå til Godkjenning og lim menneskenøkkelen inn i feltet øverst, ellers finnes ikke
Godkjenn-knappen. Verdien står i terminalen din (`echo "$LONEWATCH_HUMAN_KEY"`). Vert og port kan
styres med `LONEWATCH_HOST` og `LONEWATCH_PORT`. Demofortellingen på rundt to minutter står i
[docs/DEMO.md](docs/DEMO.md).

### Hele flyten i terminalen

```bash
python run_demo.py
```

Spiller de 40 demoforespørslene gjennom kontrollstasjonen og skriver avgjørelse, regler og
konsekvenstekst for hver. Med nøklene satt gir den 33 `allow`, 6 `red` og 1 `block`, 88
logglinjer på en fersk logg, og til slutt «Sjekk av logg: OK, ingen linjer er endret.» pluss de
tolv første tegnene av siste hash. Menneskesvaret er hardkodet til avvis her, så beløpsporten
kan ikke vises i terminalen.

### Den skriptede agentdemoen

```bash
python -m agent_gateway.scripted_demo
```

Seks slag gjennom samme kode som den ekte agenten bruker, med samme regler og samme logg. Den
trenger ingen nøkler, ingen app som kjører og ingen nett, og skriver loggen sin i en midlertidig
mappe.

### Den ekte agenten

```bash
python -m agent_gateway.oppsett     # lager nøkler, .lonewatch-agent-env og .mcp.json, én gang
source .lonewatch-agent-env
python -m ui                        # la den stå
claude                              # i et annet vindu, fra samme mappe
```

Kobler en ekte Claude Code-agent til Lonewatch over MCP. Agenten får fire oppdiktede verktøy, og
hvert verktøykall går gjennom den ekte `gateway.evaluate()`, den ekte loggen og det ekte røde
varselet. Ingen API-nøkkel trengs. Oppskriften steg for steg står i
[docs/EKTE_AGENT.md](docs/EKTE_AGENT.md).

Det store forbeholdet står i seksjon 8. Claude Codes egne verktøy går utenom Lonewatch.

### Flere kommandoer

```bash
pytest -q                                      # hele testsuiten
python -m eval.measure                         # måling mot et blindsett
python -m gateway.evaluation                   # måling mot vår egen syntetiske mengde
python -m sandbox                              # kjører demotilleggene i boksen
python -m sandbox nordlys-mail-connector-patch # ett enkelt tillegg
python -m executor.mailcatcher --dir maildrop --port 8025   # lokal postfanger
python -m executor                             # fire forespørsler gjennom utføreren
```

## 5. Hva som er ekte og hva som er simulert

| Del | Status i demoen |
|---|---|
| Penger og overføringer | **Simulert.** Ingen betaling utføres, ingen bank er involvert |
| Selskapet Nordlys Forsikring, kunder, poliser, kontonumre, leverandører | **Simulert.** Alt er oppdiktet |
| Tillegg og «skadevare» | **Simulert.** Ufarlige etterligninger i `sandbox/packages/`. De leser demofiler sandkassen selv lager, og prøver adresser som slutter på `.invalid` |
| Sandkassen | **Simulert isolasjon.** Sperrene er funksjoner i samme Python-prosess som tillegget |
| Dokumentfellene | **Simulert.** Skjult tekst i oppdiktede dokumenter. Lonewatch leser den aldri som en instruksjon |
| Personopplysningene | **Simulert.** Ingen av dem gjelder en virkelig person |
| AI i avgjørelsene | **Finnes ikke.** `allow`, `red`, `block`, risiko og varseltekst lages av deterministiske regler |
| Reglene, loggen, hash-kjeden, hale-ankeret, pseudonymene, beløpsporten, menneskenøkkelen | **Ekte kode.** Samme kode i demo og i test |
| `send_email` | **Én ekte kobling.** Med `LONEWATCH_EXECUTOR=smtp` sendes e-posten over SMTP. Standardverten er `127.0.0.1:8025`, altså den lokale postfangeren, og sending til noe annet enn loopback krever `LONEWATCH_SMTP_ALLOW_REMOTE=1` satt med vilje |

Alt annet enn `send_email` går gjennom samme kontroll og gjør så ingenting. Ingen test i
prosjektet peker ut mot internett. Hele regnskapet for utføreren står i
[docs/UTFORER.md](docs/UTFORER.md).

## 6. Testing og måling

```bash
pytest -q
```

{{TESTS}}

Testene lager egne nøkler og skriver til en midlertidig mappe, så de krever ingen miljøvariabler
og rører ikke loggen din. Noen tester er merket `xfail` med vilje, fordi hullet de beskriver
ikke er lukket. Da står hullet synlig i testkjøringen i stedet for å være glemt.

Falske alarmer er målt, ikke anslått. En alarm som lyser for ofte blir slått av, så tallet
betyr noe.

{{FALSE_ALARMS}}

Målingen er gjort mot blindsett, altså forespørsler skrevet av noen som ikke hadde sett reglene,
med sin egen fasit på hva som burde stoppes. Settene ligger i `tests/data/` og kjøres med
`python -m eval.measure --set <fil>`.

**Blindsett 1, 2 og 3 er ikke uavhengige lenger.** Hvert sett var uavhengig én gang. Etterpå ble
reglene justert ut fra hva settet fanget, og da måler settet bare at vi har fjernet feil vi
kjenner. Tallene fra dem kan ikke svare på hva reglene gjør på saker de aldri har sett.

**Sett 4 er målt én gang, med reglene slik de står nå.** {{SET4}}

Hele målingen, med før- og ettertall, hva vi valgte å ikke rette og hvorfor, står i
[docs/MALING.md](docs/MALING.md). `python -m gateway.evaluation` måler i tillegg mot en syntetisk
mengde på 43 forespørsler, men den er skrevet av samme person som skrev reglene, så den måler at
koden gjør det vi mente og ikke at vi mente det riktige.

## 7. Angrepstesting

Vi lot en «etisk hacker» bryte Lonewatch i to runder. Jobben var å finne hull i koden slik den
sto, ikke å vise at den holdt. Hvert angrep er en kjørbar test i `tests/attack/` og
`tests/attack2/`. Holder forsvaret, består testen. Finnes det et hull, er testen merket
`xfail(strict=True)` med en begrunnelse. Lukkes hullet senere, feiler testen, og da må
dokumentasjonen oppdateres i samme slengen. Et hull skal ikke kunne bli borte i stillhet.

Begge rundene er skrevet ned åpent, med hva som slipper gjennom og hva som ville lukket det, i
[docs/ANGREP.md](docs/ANGREP.md) og [docs/ANGREP2.md](docs/ANGREP2.md). En tidligere runde står i
[docs/REDTEAM.md](docs/REDTEAM.md).

Dette er noe av det som er lukket. Godkjenning krever nå en egen menneskenøkkel, og agentens nøkkel
avvises. Betenkningstiden måles av tjeneren i stedet for å oppgis av klienten. Pseudonymet følger
nøkkelen som godkjente. Beløpstolkningen godtar ikke lenger `100000,00` som ti millioner.
Mottakerfeltet kan ikke lenger skrive sin egen setning inn i varselet mennesket leser.
Kontonumre normaliseres, så fire stavinger av samme konto er én mottaker. Tidsvinduet kan ikke
omgås ved å tilbakedatere en betaling. `evaluate()` svarer `block` i stedet for å kaste på noe
den ikke klarer å lese.

Dette er noe av det som står åpent. De tre feltene agenten fyller ut selv (`recipient_known`,
`contains_personal_data`, `reversible`) kan brukes til å snakke seg forbi regler. Et tillegg kan
bryte ut av sandkassen via `open.__globals__` og rapporten sier likevel `clean`. Flere
skriveruter i appen er uautentiserte, blant andre `/api/reset`, `/api/custom` og
`/api/feed/step`. `/api/state` viser full mottaker, agentens frie tekst og de interne regelnavnene
i klartekst, altså nettopp det loggen minimerer bort. Beløp spredt over mange mottakere summeres
ikke.

{{HULL_STATUS}}

## 8. Ærlige begrensninger

Dette er en hackathon-simulering. Listen under er hentet fra `LIMITS.md`-filene, og de er den
fulle versjonen. Det er `gateway/LIMITS.md`, `vault/LIMITS.md`, `sandbox/LIMITS.md`,
`ui/LIMITS.md`, `agent_gateway/LIMITS.md` og `executor/LIMITS.md`.

- **Sandkassen er simulert, ikke isolasjon.** Sperrene er funksjoner vi har byttet ut i den samme
  Python-prosessen som tillegget kjører i. Det er ikke en container, ikke en virtuell maskin og
  ikke `seccomp`. `open.__globals__["_REAL_BUILTINS_OPEN"]` gir den ekte funksjonen tilbake. Vi
  prøvde det mot vår egen sandkasse, og det virker. Fem andre omveier virket første gang vi
  prøvde dem, og alle er stengt nå. At vi fant fem på første forsøk er det sterkeste argumentet
  for at det finnes flere vi ikke har funnet. Et tillegg ser dessuten med en gang at miljøet er
  falskt, og kan oppføre seg pent hos oss og stjele først på en ekte maskin.
- **Reglene leser ikke innholdet i tekst.** En e-post til en kjent mottaker kan inneholde hele
  kundebasen og blir fortsatt `allow`. I blindsett 3 slapp fire farlige saker gjennom
  nettopp fordi det farlige sto i innholdet, blant annet et tjenestekontopassord og en skriftlig
  aksept av et forlik på 900 000 kr. Det er en konsekvens av at vi aldri leser innhold og aldri
  bruker `summary`, begge deler med vilje.
- **Reglene stoler på feltene de får.** `recipient_known`, `reversible` og
  `contains_personal_data` kommer fra den som lager forespørselen. Setter en agent
  `recipient_known=True` på en ukjent konto, slipper den gjennom. Det er det største hullet, og
  tilliten ligger ett hakk før oss.
- **Agenten kan gå utenom hvis den har egne verktøy.** Claude Code har Bash, filtilgang og
  nettverk, og ingen av dem går gjennom Lonewatch. Ber du agenten overføre penger og den velger
  Lonewatch-verktøyet, ser du hele flyten. Skriver den i stedet et skript og kjører det med Bash,
  ser du ingenting. En MCP-tjener legger til en vei, den fjerner ingen. **Produksjonsversjonen må
  tvinge all trafikk gjennom Lonewatch med et nettverkslag, og det laget er ikke bygget.** Demoen
  forutsetter at agenten frivillig bruker verktøyene, og det er en forutsetning, ikke en
  sikkerhetsmekanisme.
- **Menneskenøkkelen ligger på maskinen.** Den står i miljøet til terminalen som kjører appen og i
  `.lonewatch-agent-env` på disken. En agent med Bash kan lese begge, og da kan den godkjenne sitt
  eget røde kort mens loggen sier at et menneske gjorde det. En test gjør nøyaktig det en slik
  agent ville gjort, og den skal bestå. Det som ville lukket det, er noe som ikke finnes på
  maskinen i det hele tatt, en egen enhet eller konto slik BankID er.
- **Ingen ekte brukere har testet produktet.** Ingen i målgruppen har brukt det, og vi måler ikke
  hvor mange røde varsler et menneske faktisk tåler før det slutter å lese dem.
- **Ingen roller og ingen innlogging per person.** Hele nettappen er uautentisert. `reveal()` på
  pseudonymtabellen krever `role == "admin"`, men rollen er bare en streng den som kaller oppgir
  selv. Deler to mennesker én menneskenøkkel, kan loggen ikke skille dem.
- **Loggen er ekte kryptert, men ikke et revisjonssikkert arkiv.** Den som har både loggen,
  hale-ankeret og nøkkelen kan skrive om begge, og hele mappen kan slettes. Det finnes ingen kopi
  et annet sted og ingen ekstern vitne-tjeneste. Nøkkelen i en miljøvariabel kan leses av hvem som
  helst med samme bruker på maskinen, og det finnes ingen rotasjon. En logg som bare vokser kan
  heller ikke rette seg etter et krav om sletting av persondata uten å knekke kjeden. Hva loggen
  faktisk inneholder om folk står i [docs/PERSONVERN.md](docs/PERSONVERN.md).
- **Dataminimering er ikke anonymisering.** Agentens frie tekst kastes og mottakeren maskeres til
  siste fire tegn, men beløpet, agent-id, dokument-id og pakkenavn blir stående. Siste fire sifre
  pluss beløp pluss tidspunkt peker ofte på én transaksjon.
- **Grensene er valgt for hånd.** 50 000 kr og 50 000 000 kr er satt for å få en god demo, ikke ut
  fra en risikoanalyse. Vektene i regelsettet er valgt på samme måte.

## 9. Hva som kommer videre

**Ingenting i denne seksjonen er bygget.** Det er listen over hva som måtte til for at Lonewatch
skulle vært et produkt.

- **Nettverkslag eller proxy** som tvinger all agenttrafikk gjennom Lonewatch, slik at det ikke
  finnes en annen vei. Det er en innpakning av kjøremiljøet til agenten, ikke en MCP-tjener.
- **En etablert sandkasse** i stedet for vår egen. Ekte isolasjon i operativsystemet, uten
  nettverkskort, og flere kjøringer over tid. Vi bør integrere noe som finnes, ikke bygge det
  selv.
- **Kontoregister og innholdsklassifisering.** Et oppslag mot bank og leverandørsystem, slik at
  «kjent mottaker» er et svar fra et register og ikke en påstand i et felt. Og en klassifisering
  som kan se at innholdet er en hemmelighet eller en forpliktelse, som er det de fire farlige
  sakene i blindsett 3 trengte.
- **Innlogging og roller.** Autentisering foran alt som skriver eller nullstiller, én identitet
  per person, og en godkjenning som krever noe som ikke ligger på maskinen.

## 10. Bygget under

Oslo Sprint Hackathon, 6. til 8. november 2026, BI Startup Village. Alt er bygget under
hackathonet, solo av Benjamin Sundby.

## 11. Hvordan prosjektet er organisert

```
contracts.py        Felles typer, låst. ActionRequest, Decision, HumanResponse,
                    TrapEvent, SandboxReport, AfterAction, LogEntry og hash-kjeden
gateway/            Kontrollstasjonen. Regler, risikopoeng, grenser, norsk konsekvenstekst
vault/              Den låste loggen. Fernet per linje, hash-kjede, hale-anker,
                    pseudonymer, Etter-listen, «Bryt loggen»
sandbox/            Den lukkede boksen. Kjører et tillegg i en delprosess og skriver ned
                    hva det gjorde. Demotilleggene ligger i sandbox/packages/
agents/             Simulerte agenter, de 40 demoforespørslene, hovedscenarioet og
                    dokumentene med skjult tekst
agent_gateway/      MCP-broen mot en ekte Claude Code-agent, og den skriptede reserven
executor/           Det eneste som rører omverdenen. send_email over SMTP, resten simulert.
                    Inneholder også den lokale postfangeren
ui/                 Nettsiden. Oversikt, godkjenningskø med beløpsport og menneskenøkkel,
                    Før, Etter og Prøv selv
eval/               Måling mot blindsettene
docs/               DEMO, MALING, ANGREP, ANGREP2, REDTEAM, EKTE_AGENT, UTFORER, PERSONVERN
tests/              Testsuiten, inkludert angrepstestene i attack/ og attack2/
```

Alle typer importeres fra `contracts.py`. Grensesnittene mellom modulene står i
[CLAUDE.md](CLAUDE.md), og promptene prosjektet ble bygget med står i [PROMPTS.md](PROMPTS.md).
