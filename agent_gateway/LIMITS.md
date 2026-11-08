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

## 13. Hva som er testet, og hva som ikke er

Automatisk (`tests/test_agent_gateway.py`, `tests/test_agent_mcp_live.py`,
`tests/test_agent_scripted_demo.py`): allow, rødt, block, tidsavbrudd, mistet
kontakt, feil nøkkel, feil beløp, at agenten ikke kan oppgi de fire feltene, at
et blokkert kall ikke får regelnavnene, at agenten ikke har noe verktøy, felt
eller kall som godkjenner noe, at loggen og loggsjekken stemmer, at reserven
gir samme svar hver gang og ikke åpner en socket - og hele veien gjennom en
ekte MCP-klient mot `python -m agent_gateway` mot den kjørende appen.

**Ikke testet automatisk:** Claude Code selv. En ekte agent velger når og
hvordan den kaller verktøyene, og kan velge å ikke kalle dem i det hele tatt
(se punkt 1). Det må prøves for hånd - se `docs/EKTE_AGENT.md`.
