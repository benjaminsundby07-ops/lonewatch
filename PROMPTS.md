# Lonewatch: oppsett og prompter

## 0. Oppsett (5 min, i terminal)

```bash
cd ~/lonewatch            # mappen du pakker ut zip-filen i
git init && git add -A && git commit -m "contracts and rules"
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -q                 # skal gi 6 passed
```

## 1. Skjelett (ÉN økt, først, ca. 30-45 min)

Lim inn i Claude Code i rotmappen:

```
Les CLAUDE.md og contracts.py først. Ikke endre contracts.py.

Bygg det tynnest mulige skjelettet som kjører fra start til slutt, med falske deler:
- agents/scenarios.py: all_scenarios() returnerer 3 hardkodede ActionRequest (en harmløs kalenderoppdatering,
  en rapport til kjent mottaker, og en overføring på 10 000 000 kr til ukjent konto som ikke kan angres).
- gateway/__init__.py: evaluate(req) -> Decision. Foreløpig: overføring til ukjent mottaker gir red, alt annet allow.
- vault/__init__.py: klassen Vault med append(), verify(), og funksjonen pseudonymize(). Foreløpig i minnet, ingen kryptering.
- run_demo.py: kjører scenarioene gjennom evaluate, logger alt i Vault, skriver resultatet i terminalen og kjører verify().
- tests/test_skeleton.py: en test som kjører hele flyten og sjekker at overføringen blir red og at verify() gir None.

Bruk NØYAKTIG grensesnittene i CLAUDE.md. Kjør pytest og python run_demo.py. Commit på main. Si ærlig hva som er falskt.
```

Når den er grønn: `git commit`, så gå videre.

## 2. Tre parallelle økter

```bash
git worktree add ../lw-a -b feat/agents-ui
git worktree add ../lw-b -b feat/gateway
git worktree add ../lw-c -b feat/vault
# åpne en terminal og Claude Code i hver mappe
```

Slå sammen én gren om gangen til main. Kjør `pytest -q` og `python run_demo.py` mellom hver.

### Økt B: mellomstasjonen (mappe lw-b, eier gateway/)

```
Les CLAUDE.md og contracts.py. Du eier KUN gateway/. Ikke endre contracts.py eller andre mapper.

Bygg ekte gateway.evaluate(req: ActionRequest) -> Decision med deterministiske regler (ingen AI):
- Regler som egne små funksjoner med navn som havner i Decision.reasons: amount_over_limit (grense i NOK i en konfig-konstant),
  unknown_recipient, irreversible, personal_data_external (contains_personal_data og ukjent mottaker), new_package.
- Risiko: low/medium/high ut fra hvilke regler som slo til. Verdikt: allow ved low, red ved medium/high,
  block for install_package med package_name på en liten blokkliste og for overføring over en hard grense.
- consequence_text lages av en mal på norsk fra feltene (beløp med mellomrom som tusenskille, "ukjent konto", "Kan ikke angres.").
  Eksempel: "Overfører 10 000 000 kr til ukjent konto. Kan ikke angres." Bruk ALDRI req.summary.
- requires_typed_amount = True når red og action_type er transfer_money.
- Hold rødt sjeldent: vanlige ting som kalender og rapport til kjent mottaker skal være allow.
- Skriv minst 15 tester i tests/test_gateway.py, inkludert grensetilfeller (beløp lik grensen, ukjent mottaker uten beløp, felt som mangler).
- Lag en liten målemodul gateway/evaluation.py som kjører regelsettet mot en testmengde på minst 40 ActionRequest du lager selv
  (både farlige og harmløse) og skriver: antall farlige fanget, antall falske alarmer. Merk testmengden som syntetisk.

Kjør pytest. Rapporter ærlig hva reglene ikke dekker.
```

### Økt C: loggen og sikkerheten (mappe lw-c, eier vault/)

```
Les CLAUDE.md og contracts.py. Du eier KUN vault/. Ikke endre contracts.py eller andre mapper.

Bygg ekte vault med disse egenskapene:
1. Vault.append(kind, payload, ts=None) -> LogEntry bruker make_log_entry fra contracts, slik at hver linje peker på forrige via hash.
2. Persistens til en JSONL-fil. Hver linje krypteres med Fernet fra cryptography-biblioteket FØR den skrives til disk.
   Nøkkelen leses fra miljøvariabelen LONEWATCH_LOG_KEY. Mangler den, avslutt med en tydelig feilmelding (ikke lag en stille standardnøkkel).
   Lag et skript vault/gen_key.py som skriver ut en ny nøkkel.
3. Vault.verify() -> int | None bruker verify_chain fra contracts, og leser fra disk (dekrypterer).
4. pseudonymize(employee_id) -> "emp_" + 4 hex fra HMAC-SHA256 med nøkkel fra LONEWATCH_PSEUDONYM_KEY. Samme input gir samme output.
   Navn-til-kode-tabellen ligger i en egen fil som bare lastes av en admin-funksjon reveal(pseudonym, role) som krever role == "admin".
5. Dataminimering: en hjelpefunksjon redact_payload(kind, payload) som for harmløse (allow) forespørsler bare beholder type, risiko og avgjørelse,
   og for røde/blokkerte beholder detaljer men maskerer mottaker (vis bare siste 4 tegn).
6. Etter-listen: vault/after.py med build_after_actions(entries) -> list[AfterAction] som lager en enkel liste ut fra loggen
   (f.eks. flaggede overføringer, utløste feller, blokkerte tillegg: hva er eksponert, hvem må varsles/bytte passord).
7. Tester i tests/test_vault.py: kryptert fil kan ikke leses uten nøkkel, endring av en linje på disk gjør at verify() peker på riktig seq,
   slettet linje oppdages, samme ansatt gir samme pseudonym, og pseudonym kan ikke reverseres uten admin.
8. Skriv vault/LIMITS.md med ærlige begrensninger (hele loggen kan slettes, nøkkel i miljøvariabel er kun for demo, ingen ekte tidsstempel-garanti).

Kjør pytest. Rapporter ærlig hva som ikke er løst.
```

### Økt A: agenter og grensesnitt (mappe lw-a, eier agents/ og ui/)

```
Les CLAUDE.md og contracts.py. Du eier KUN agents/ og ui/. Ikke endre contracts.py eller andre mapper.

Del 1: agents/
- agents/scenarios.py: all_scenarios() -> list[ActionRequest]. Lag ca. 40 realistiske forespørsler fra 5 simulerte agenter
  (customer_service, procurement, finance, hr, it_helper) for et oppdiktet selskap "Nordlys Forsikring". 90 % er harmløse
  (kalender, rapport til kjent mottaker, lesing av dokument). Noen få er farlige: overføring på 10 000 000 kr til ukjent konto,
  kundeliste til ukjent ekstern adresse, installasjon av et tillegg med mistenkelig navn.
- Ett hovedscenario "binance_inspired" i agents/story.py: en rekkefølge av forespørsler som viser hele kjeden på 90 sekunder
  (først installasjon av tillegg, så agent som leser et dokument med felle, så overføring). Det er en simulering og en
  ufarlig etterligning. Ingen ekte skadekode, ingen ekte nettverkskall.
- agents/traps.py: dokumenter med usynlig felle (marker i metadata/skjult tekst) og en funksjon som returnerer TrapEvent når en simulert agent leser/sender ut en felle-merket fil.
- Alt skal fungere uten internett og uten API-nøkkel (deterministisk reserve). Bruk fast tilfeldig frø.

Del 2: ui/ (start først når del 1 virker)
- En enkel FastAPI-app med én nettside (ingen byggesteg, ren HTML/CSS/JS) med:
  a) godkjenningskø: harmløse ting går gjennom i en rolig liste til siden, røde forespørsler lyser rødt med consequence_text i store bokstaver
  b) for requires_typed_amount: personen må skrive inn beløpet for å kunne trykke godkjenn
  c) en "Sjekk loggen"-knapp som kaller vault.verify() og viser grønt eller rødt med seq
  d) en "Etter"-fane som viser vault.after.build_after_actions
  e) en knapp "spill av hendelsen" som kjører binance_inspired steg for steg
- Design: rolig, lite tekst, rødt bare for det som betyr noe. Må se bra ut på projektor. Norsk tekst.
- Bruk bare grensesnittene i CLAUDE.md. Hvis gateway eller vault ikke er ferdig enda, bruk skjelettets versjoner og ikke lag egne.

Kjør pytest og start appen. Rapporter ærlig hva som ikke er testet.
```

## 3. Sammenslåing (du, ca. 2-3 timer)

1. Merge `feat/gateway`, kjør `pytest -q` og `python run_demo.py`.
2. Merge `feat/vault`, samme sjekk.
3. Merge `feat/agents-ui`, start appen og kjør hendelsen fra start til slutt.
4. Rett uoverensstemmelser i EN økt, ikke i alle samtidig.

## 4. Kutt-rekkefølge hvis tiden er knapp
Sandkasse først, så dokumentfeller. Behold: gateway med rødt varsel, kryptert logg med sjekk-knapp, Etter-listen.

## 5. Ikke glem
- Si i pitchen: simulering, oppdiktet selskap, loggen kan fortsatt slettes (se vault/LIMITS.md), nøkkelen ligger i miljøvariabel kun i demo.
- Alt skal bygges nytt under hackathonet. Ikke bruk kode fra tidligere prosjekter.
