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

Det går enda lenger: `/api/respond` er menneskets endepunkt i nettleseren, og
det spør ikke om agentnøkkelen. En agent med Bash kan altså godkjenne sitt eget
røde kort med ett `curl`-kall. MCP-tjeneren gir agenten ingen vei til å
godkjenne - det er testet - men det er ikke det samme som at veien ikke finnes.
`tests/test_agent_mcp_live.py::test_aerlig_hull_alt_som_kjoerer_lokalt_kan_godkjenne`
pinner hullet med vilje, slik at ingen tror det er lukket.

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

## 2. Ingenting utføres, heller ikke etter en godkjenning

`UTFØRT (simulert)` er en tekst MCP-tjeneren returnerer. Det flyttes ingen
penger, sendes ingen e-post, leses ingen dokumenter og installeres ingen
pakker. Et godkjent rødt kort fører til den samme teksten - bare med
`GODKJENT` foran. Ingen integrasjon finnes bak.

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
endepunktene av (503). Endepunktene svarer bare på kall fra 127.0.0.1.

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

## 12. Hva som er testet, og hva som ikke er

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
