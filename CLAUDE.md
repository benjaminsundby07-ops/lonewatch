# Lonewatch (hackathon-prosjekt, bygges fra scratch)

Lonewatch er en mellomstasjon mellom en bedrifts AI-agenter og verktøyene de bruker. Alt en agent vil gjøre,
går først gjennom Lonewatch, som svarer `allow`, `red` (menneske må se på det) eller `block`. Alt logges i en
logg som ikke kan endres i det skjulte. Dette er en SIMULERING: det finnes ingen ekte bedrift, ingen ekte penger
og ingen ekte skadevare.

## Spilleregler for alle Claude Code-økter
1. `contracts.py` er LÅST. Aldri endre den. Trenger du en endring: stopp og skriv hva du trenger, så avgjør jeg.
2. Rør bare mappen du eier (se prompten din). Aldri rediger andres mapper.
3. Importer alle typer fra `contracts`. Aldri lag egne varianter av ActionRequest, Decision, LogEntry osv.
4. Engelske navn uten æøå i kode. Tekst brukeren ser (UI, consequence_text) er norsk.
5. Ingen kode, filer eller pakker fra tidligere prosjekter. Alt skrives nytt her. Ikke koble til eller importer noe utenfor denne mappen.
6. Risikovurdering gjøres av vanlige, deterministiske regler. AI-modeller brukes aldri til å bestemme allow/red/block,
   og `ActionRequest.summary` (agentens egen forklaring) brukes aldri som grunnlag for risiko.
7. Før du sier noe er ferdig: kjør `pytest -q` og kjør modulen din. Si ærlig hva som ikke er testet.
8. Små commits på din gren. Ikke merge selv.
9. Hemmeligheter (nøkler) leses fra miljøvariabler, aldri hardkodet. Bruk `LONEWATCH_LOG_KEY` og `LONEWATCH_PSEUDONYM_KEY`.
10. Simulert "skadevare" i demoen er en ufarlig etterligning som bare logger at den PRØVER å sende data. Ingen ekte nettverkskall, ingen ekte ondsinnet kode.

## Mappeeierskap
- `agents/`   økt A: simulerte agenter, scenarioer og demodata
- `gateway/`  økt B: regler, risikovurdering, konsekvenstekst, mellomstasjon
- `vault/`    økt C: krypteret og låst logg, pseudonymisering, sjekk-av-logg
- `ui/`       økt A etter at agents/ er ferdig: godkjenningskø, rødt varsel, Etter-listen
- `tests/`    alle kan legge til egne testfiler, men rører ikke test_contracts.py

## Kjerneflyt
agent -> `ActionRequest` -> gateway.evaluate() -> `Decision`
  allow: gjennomfør (simulert) og logg
  red:   legg i køen, vent på `HumanResponse` (bruker må skrive inn beløpet), logg
  block: avvis, logg
Alt som skjer -> vault.append(kind, payload) -> `LogEntry`

## Grensesnitt mellom modulene (må følges nøyaktig)
- `gateway.evaluate(req: ActionRequest) -> Decision`
- `vault.Vault.append(kind: LogKind, payload: dict, ts: datetime | None = None) -> LogEntry`
- `vault.Vault.verify() -> int | None`   (seq til første ødelagte linje, ellers None)
- `vault.pseudonymize(employee_id: str) -> str`   (gir `emp_xxxx`)
- `agents.scenarios.all_scenarios() -> list[ActionRequest]`
