# Hva broen mot en ekte agent IKKE er

`agent_gateway/` lar Claude Code kalle fire oppdiktede verktøy, og hvert kall
går gjennom den ekte `gateway.evaluate()`, den ekte låste loggen og det ekte
røde varselet i dashbordet. Det er ekte nok til å være verdt å vise. Det er
ikke et produkt, og under står hvorfor - før noen spør.

## 1. Agenten har andre verktøy som går helt utenom Lonewatch

**Dette er det store hullet, og det er ikke mulig å lukke fra vår side.**

Claude Code har sine egne innebygde verktøy: Bash, lesing og skriving av filer,
nettverkskall, `git`. Ingen av dem går gjennom Lonewatch. Ber du agenten om å
«overføre penger», og den velger `lonewatch_transfer_money`, ser du hele flyten.
Ber du den om det samme, og den i stedet skriver et lite skript og kjører det
med Bash, ser du ingenting.

Det gikk enda lenger: `/api/respond` spurte ikke om noe som helst, så en agent
med Bash kunne godkjenne sitt eget røde kort med ett `curl`-kall.

**Det er strammet inn, men ikke lukket.** `/api/respond` krever nå en egen
menneskenøkkel (`X-Lonewatch-Human-Key`, se `ui/human_key.py`). Agentnøkkelen -
den som står i `.mcp.json`, altså i en fil Claude Code selv leser - duger ikke,
og menneskenøkkelen skrives aldri inn i MCP-oppsettet. Er de to satt til samme
verdi, slås godkjenningen helt av.

Men menneskenøkkelen er en tekst i et miljø og i `.lonewatch-agent-env` på
disken, og en agent med Bash kan lese begge. Hullet er altså smalere - agenten
må lete, og den må lete etter noe annet enn det den har fått utlevert - ikke
borte.
`tests/test_agent_mcp_live.py::test_aerlig_hull_menneskenoekkelen_ligger_paa_maskinen`
pinner det som står igjen, og
`test_agentnoekkelen_kan_ikke_godkjenne_men_menneskenoekkelen_kan` måler det
som er lukket. Les begge.

Det som ville lukket det helt: at godkjenningen krever noe som ikke finnes på
maskinen i det hele tatt - en egen enhet eller en egen konto, slik BankID er.

Demoen forutsetter altså at **agenten frivillig bruker Lonewatch-verktøyene.**
Det er en forutsetning, ikke en sikkerhetsmekanisme. En agent som er lurt av et
dokument - akkurat scenarioet Lonewatch handler om - er nettopp en agent som
kanskje ikke velger den pene veien.

Hva som måtte gjort det ekte: agenten måtte kjørt i et miljø der det **ikke
finnes** andre verktøy. Bash, filtilgang og nettverk må fjernes eller sperres,
og alt den kan gjøre må gå gjennom mellomstasjonen. Det er en innpakning av
kjøremiljøet, ikke en MCP-tjener. En MCP-tjener legger til en vei; den fjerner
ingen.

Si dette høyt i demoen. Det er mer interessant enn å skjule det.

### 1b. Det låste agentoppsettet: hva det gjør, og hva det ikke gjør

**Endret, men ikke lukket.** `python -m agent_gateway.oppsett` lager nå
`.claude/settings.json` i agent-mappen, og `python -m agent_gateway.start_agent`
starter `claude` med de samme listene som flagg. Begge gjør én ting: agenten
får som standard bare Lonewatch-verktøyene.

Målt mot Claude Code **2.1.241**. Flaggene står i `claude --help` i den
versjonen - vi bruker ikke flagg vi ikke har sett:

| Flagg | Hva det gjør |
|---|---|
| `--tools ""` | tar bort HELE det innebygde verktøysettet |
| `--allowed-tools mcp__lonewatch__*` | bare de fire Lonewatch-verktøyene |
| `--disallowed-tools Bash,Edit,Write,…` | nekter de innebygde ved navn i tillegg |
| `--strict-mcp-config --mcp-config .mcp.json` | bare MCP-tjeneren vi genererte |
| `--settings .claude/settings.json` | den genererte innstillingsfilen |
| `--setting-sources project` | dine egne og lokale innstillinger leses ikke |
| `--permission-mode manual` | ingenting godkjennes automatisk |

De tre første er med vilje overlappende. Fjerner noen én av dem, står de to
andre igjen.

**Hva som er målt:** at `--tools ""` faktisk virker. Kjørt mot en ekte
Claude Code-prosess med spørsmålet «list the exact names of every tool you can
call»; svaret var `NONE`. Og at den genererte innstillingsfilen godtas:
`claude doctor` i mappen rapporterer ingen «Invalid settings».

**Hva som IKKE er målt, og som du ikke skal påstå:**

- At agenten ikke kan nå Bash på en annen vei. Vi har målt at verktøyet ikke
  er i settet den får, ikke at det ikke finnes noen vei.
- At en ekte oppgave faktisk nektes. Det må prøves for hånd, og prosedyren
  står i `docs/EKTE_AGENT.md`.

**Og dette er det viktigste avsnittet i hele filen:**

> Dette er **klientkonfigurasjon**, ikke en sikkerhetsgrense. En agent som alt
> kan kjøre kode på maskinen kan slette `.claude/settings.json`, droppe
> flaggene eller bare starte `claude` selv uten startskriptet. Oppsettet
> hjelper mot at agenten *velger* en annen vei fordi den er der. Det hjelper
> ikke mot noen som *vil* rundt.

Det eneste som ville lukket hullet er at all trafikk **tvinges** gjennom
Lonewatch på nettverksnivå - en innpakning av kjøremiljøet, der det ikke finnes
noen annen utgang. Det er ikke bygget, og det er ikke en MCP-tjener.

**Hva en bedrift måtte gjort for å bruke dette:** en lokal fil er feil sted.
Innstillingene måtte vært styrt sentralt (managed policy), slik at den som
kjører agenten ikke kan endre dem - og de måtte vært kombinert med et
kjøremiljø uten andre utganger. Claude Code sier selv at sentralt styrte
innstillinger gjelder uansett hva som står i prosjektmappen; vi kan altså bli
*strammere* enn en bedrift, aldri løsere.

**Tre ærlige bivirkninger av filen vi skriver:**

1. `.claude/settings.json` gjelder for ALLE Claude Code-økter som startes i
   mappen - også utvikler-økten din. Sletter du filen, virker startskriptet
   fortsatt, fordi flaggene sier det samme.
2. Allow-listen i filen ignoreres i en mappe Claude Code ikke har fått tillit
   til («this workspace has not been trusted»). Nekt-listen og flaggene virker
   fortsatt. Det er en av grunnene til at listene står på to steder.
3. `MultiEdit` står i nekt-listen, men finnes ikke i 2.1.241. Da skriver
   `claude` «Permission deny rule "MultiEdit" matches no known tool». Advarselen
   er riktig; vi lar navnet stå for en senere versjon.

Pinnet i `tests/test_agent_laas.py`. Testene der måler at VI sender det riktige
- ikke at Claude Code gjør det riktige med det. Det siste er en annen prosess.

## 2. Noe utføres nå - men agenten får ikke vite hva

**Endret.** `ui/state.py` kaller `executor/` når Lonewatch sier grønt, og når et
menneske godkjenner et rødt kort. Med `LONEWATCH_EXECUTOR=smtp` blir en
`send_email` faktisk sendt (til localhost med mindre noen har sagt noe annet).
Alt annet - penger, deling, pakker, dokumenter, kalender - går gjennom samme
port og gjør så ingenting.

Hullet som står igjen er i det **agenten får vite**: `UTFØRT (simulert)` er
fortsatt en fast tekst MCP-tjeneren returnerer. Den spør ikke hva utføreren
svarte. Ble handlingen nektet av utføreren - feil oppsett, innhold endret etter
godkjenningen, alt forsøkt før - står det likevel `UTFØRT (simulert)` i
agentens svar.

Loggen vet det riktige, og dashbordet viser det riktige. Agenten gjør ikke det.
Et ekte produkt måtte sendt utførerens svar tilbake gjennom
`/api/agent/status/{id}`.

## 3. Agenten kan ikke velge sine egne felt, men den eier `summary`

Agenten kan ikke oppgi `recipient_known`, `reversible`, `agent_id` eller `id`.
Feltene finnes ikke i verktøyene, og endepunktet svarer 422 hvis de sendes
likevel (`AgentSubmitIn` har `extra="forbid"`). `recipient_known` regnes ut mot
demoens liste, og `reversible` kommer fra handlingstypen - akkurat som i «Prøv
selv».

Men `summary` er agentens egen tekst, og `contains_personal_data` er en bryter
agenten setter. `summary` brukes aldri i vurderingen (det er en regel i hele
prosjektet), og `contains_personal_data` kan bare gjøre vurderingen strengere.
Likevel: det agenten velger å KALLE verktøyet med - hvilket beløp, hvilken
mottaker - er fortsatt agentens påstand. Hullet fra `gateway/LIMITS.md` punkt 1
gjelder uendret: tilliten ligger ett hakk før oss.

## 4. Den delte hemmeligheten beskytter mot uhell, ikke mot en angriper

`LONEWATCH_AGENT_KEY` må være satt i terminalen som kjører appen, ellers er
endepunktene av (503). Endepunktene svarer bare på kall fra 127.0.0.1. Den
åpner `/api/agent/*` og ingenting annet - godkjenning krever menneskenøkkelen
(punkt 1).

Det stopper at en annen prosess ved et uhell legger noe i godkjenningskøen. Det
stopper ikke noen som alt kjører kode som din bruker på din maskin: nøkkelen
står i et miljø de kan lese. Det finnes ingen signering, ingen rotasjon, ingen
utløpstid, og ingenting hindrer at samme nøkkel brukes om igjen.

Og den som kan kalle endepunktet, kan kalle det så ofte de vil. Det er ingen
grense på antall forespørsler: en agent i en løkke kan fylle godkjenningskøen.

## 5. Når agenten gir opp, er det ikke et nei fra et menneske

Venter agenten lenger enn `LONEWATCH_AGENT_WAIT_SECONDS` (120 s), slutter den å
vente og behandler det som et nei. Da skjer tre ting - og det tredje er viktig:

1. Agenten får beskjed om at ingen svarte, og utfører ingenting.
2. Det kommer en notis i dashbordet om at agenten ga opp.
3. **Kortet blir liggende i godkjenningskøen, og det skrives INGENTING i
   loggen.**

Grunnen til at loggen holdes stille: ingen `HumanResponse` har skjedd. En linje
som sa «avvist» ville vært en påstand om at et menneske svarte. `LogKind` i
`contracts.py` har heller ingen verdi for «agenten ga opp», og `contracts.py` er
låst.

Konsekvensen er ærlig, men rar: godkjenner et menneske kortet to minutter
senere, står det `godkjent` i loggen - men agenten er borte og utfører ingenting.
Loggen sier hva mennesket gjorde, ikke hva som skjedde etterpå. Et ekte produkt
måtte hatt en utløpstid på selve forespørselen, slik at et kort ikke kan
godkjennes etter at den som spurte har gått.

## 6. Historikken ligger fortsatt i minnet

`recipient_total_over_limit` summerer overføringer til samme mottaker, og
historikken ligger i `ui/state.py`. Starter appen på nytt, eller trykker noen
Nullstill, er telleren null igjen - også for den ekte agenten. Se
`gateway/LIMITS.md`.

## 7. Dashbordet henter, det får ikke beskjed

`ui/static/agent_live.js` spør `/api/state` hvert 1,5 sekund. Det er ikke en
hendelsesstrøm: et kort kan altså stå opptil halvannet sekund i køen før det
vises. Vi tegner heller ikke om mens noen skriver inn et beløp - avgjørelsen
deres er viktigere enn at listen er helt fersk.

## 8. Fire verktøy, seks handlingstyper

`contracts.ActionType` har seks verdier. Vi har verktøy for fire:
`read_document`, `send_email`, `transfer_money`, `install_package`.
`share_data` og `update_calendar` har ingen verktøy - ikke fordi de ikke virker
i gateway, men fordi vi ikke har prøvd dem gjennom en ekte agent, og et verktøy
vi ikke har prøvd er en påstand om dekning vi ikke har.

## 9. Tjeneren kan bare snakke med denne maskinen

`LONEWATCH_AGENT_URL` må peke på 127.0.0.1 (`agent_gateway/config.py`). Det er
ikke appen som beskyttes av det - det er deg: en MCP-tjener som kunne pekt hvor
som helst, ville vært en kanal ut av maskinen som agenten selv kontrollerte.

## 10. Nøkkelen i to filer er praktisk, ikke trygg

`python -m agent_gateway.oppsett` skriver nøklene i `.lonewatch-agent-env` og
agentnøkkelen i `.mcp.json`. Begge er `chmod 600` og begge står i `.gitignore`.
Det er det samme nivået som en `.env`-fil: det hindrer et uhell, og ingenting
annet. Nøkkelen står i klartekst på disken, den har ingen utløpstid, og
`.mcp.json` leses av Claude Code - altså av et program som også kan lese den og
sende den videre. Grunnen til at oppsettet likevel finnes: alternativet var at
nøkkelen ble limt inn for hånd, og en nøkkel som limes inn havner i et
chatlogg, et skjermbilde eller en commit.

## 11. Reserven er ikke et bevis på at en agent virker

`python -m agent_gateway.scripted_demo` kjører samme `run_action`, samme
endepunkter, samme regler og samme logg som den ekte agenten. Det den IKKE
viser: at MCP-protokollen virker (det gjør `tests/test_agent_mcp_live.py`), og
at en ekte agent velger å bruke verktøyene. Manuset kaller dem alltid. En agent
gjør ikke nødvendigvis det, og det er nettopp punkt 1.

Reserven skriver dessuten loggen i en midlertidig mappe som slettes etterpå.
Den er til for å vises, ikke til å etterforske noe i.

## 12. Hva angrepene fant i de to skriverutene agenten eier

`/api/agent/submit` og `/api/agent/abandon/{id}` ble angrepet i
`tests/attack/test_attack_agent_tools.py`. To hull ble funnet og lukket:

- **`abandon` svarte på alle kort, ikke bare agentens egne.** Agenten kunne
  kalle `abandon` på et vilkårlig `req_0012` og få dashbordet til å skrive «Den
  ekte agenten ventet 120 s på svar på req_0012» om en sak agenten aldri hadde
  sendt. Nå kreves `source == "agent"`, og et fremmed kort svarer det samme som
  et kort som ikke finnes.
- **`abandon` kunne skrive samme notis så mange ganger den ville.** Dashbordet
  viser de tolv siste notisene, så en løkke kunne skjøvet sandkasserapporter og
  feller ut av listen. Nå er det én notis per kort.

Samme sjekk er lagt på `/api/agent/status/{id}`: et kort i menneskets
godkjenningskø inneholder beløp, mottaker og konsekvenstekst, og agenten fikk
lese alt det på saker den ikke hadde sendt.

Det `submit` ble prøvd mot, uten å gi etter: alle fire utfall (grønt, rødt,
blokkert, ikke gyldig), seksten felt som ville avgjort noe (alle gir 422, ikke
stille ignorering), egen `agent_id`/`id`, regelnavnene på et blokkert kall, og
forseglingen.

**Det som fortsatt står åpent:** det finnes ingen grense på hvor mange
forespørsler en agent kan sende. 40 kall fyller godkjenningskøen, og den som
sitter i dashbordet må gå gjennom alle for å finne den ene som betyr noe. Det
er en tjenestenekt mot MENNESKET, ikke mot appen. Pinnet som
`xfail(strict=True)`.

## 12b. Formsjekk av det agenten sender - og det den ikke fanger

`agent_gateway/validering.py` avviser input som ikke har en form Lonewatch kan
behandle, FØR det når gateway: tekstfelt over en lengdegrense, kontrolltegn og
usynlige tegn i `recipient` og `package_name`, ukjente felt, og beløp som er
negative, ikke endelige eller absurd store.

Hvorfor det finnes: `recipient` vises til et menneske i et rødt kort. Et
linjeskift i den teksten er det billigste trikset som finnes for å få et kort
til å se ut som noe annet enn det er, og en tekst på 50 000 tegn er det
billigste trikset for at mennesket ikke leser kortet i det hele tatt.

Hva det IKKE er:

- **Det er ikke en risikovurdering.** Ingenting her avgjør allow, rødt eller
  block. Et beløp som slipper formsjekken er fortsatt uvurdert, og gateway
  eier avgjørelsen alene.
- **Feilmeldingen nevner ingen regel og ingen grense.** Den sier hvilket felt
  som ikke holder. Alt annet ville vært en oppskrift.
- **`summary` sjekkes bare på lengde.** Et linjeskift der slipper gjennom, med
  vilje: det er agentens egen forklaring, og den kan ha flere setninger. Men
  det betyr at `summary` er det ene feltet der agenten kan legge inn tekst som
  ser ut som noe annet i dashbordet. Hvordan den vises er `ui/`-sin sak.
- **Lengdegrensene er form, ikke risiko.** De står i klartekst i koden. En
  agent som leser filen lærer ingenting om hva som blir stoppet.

Pinnet i `tests/test_agent_laas_input.py`: 43 tester, der 30 måler at noe skal
avvises UTEN at det sendes, og resten at vanlig input slipper gjennom
(inkludert æøå i en e-postadresse, 0 kroner, øre og nøyaktig maks lengde).

## 13. Hva som er testet, og hva som ikke er

Automatisk (`tests/test_agent_gateway.py`, `tests/test_agent_mcp_live.py`,
`tests/test_agent_scripted_demo.py`): allow, rødt, block, tidsavbrudd, mistet
kontakt, feil nøkkel, feil beløp, at agenten ikke kan oppgi de fire feltene, at
et blokkert kall ikke får regelnavnene, at agenten ikke har noe verktøy, felt
eller kall som godkjenner noe, at loggen og loggsjekken stemmer, at reserven
gir samme svar hver gang og ikke åpner en socket - og hele veien gjennom en
ekte MCP-klient mot `python -m agent_gateway` mot den kjørende appen.

Det låste oppsettet (`tests/test_agent_laas.py`): at tillat- og nekt-listene
står i den genererte filen, at filen er gitignorert, ikke sjekket inn og får
0600, at ingen nøkkel står i den, at startskriptet bygger den kommandolinjen vi
tror, at `--vis` ikke starter noe, og at meldingen sier hva som IKKE er låst.

Formsjekken (`tests/test_agent_laas_input.py`): se punkt 12b.

**Ikke testet automatisk:** Claude Code selv. En ekte agent velger når og
hvordan den kaller verktøyene, og kan velge å ikke kalle dem i det hele tatt
(se punkt 1). At det låste oppsettet faktisk nekter en Bash-kommando er også
en annen prosess enn testene våre. Begge må prøves for hånd - prosedyren står i
`docs/EKTE_AGENT.md` under «Manuell test: virker låsen?».
