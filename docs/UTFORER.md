# Utføreren: fra «Lonewatch sa ja» til at det faktisk skjer

Alt annet i Lonewatch vurderer, viser og logger. **Utføreren er den delen som
gjør handlingen.** Den gjør den bare når én av to ting stemmer:

| Lonewatch sa | Hva utføreren gjør |
| --- | --- |
| **Grønt** (`allow`) | Handlingen utføres med én gang. |
| **Rødt** (`red`) som et menneske har godkjent | Handlingen utføres. |
| **Rødt** som venter på et menneske | Ingenting skjer. |
| **Rødt** som et menneske avviste | Ingenting skjer. |
| **Blokkert** (`block`) | Ingenting skjer. Heller ikke om noen godkjenner den. |

Og én sperre på toppen: **blir forespørselen endret etter godkjenningen,
utføres den ikke.** Godkjenner du en e-post til Oline, er det den e-posten som
sendes — ikke en til noen andre.

Den første ekte handlingen er **sending av e-post**. Alt annet er fortsatt
simulert.

---

## Del 1 — Prøv det på din egen maskin først

Her sendes ingen e-post ut av maskinen. En liten «postfanger» later som den er
en postserver og lagrer hver melding som en fil du kan åpne.

### Steg 1: Start postfangeren

Åpne et terminalvindu og skriv:

```bash
python3 -m executor.mailcatcher --dir maildrop --port 8025
```

Den svarer med noe slikt:

```
Postfangeren lytter på 127.0.0.1:8025
Meldinger lagres i /…/maildrop
Avslutt med Ctrl-C.
```

La vinduet stå åpent.

### Steg 2: Kjør en godkjent handling

Åpne et **nytt** terminalvindu og skriv:

```bash
python3 -m executor
```

Den kjører fire forespørsler gjennom utføreren og skriver ut hva som skjedde
med hver: én grønn blir sendt, én rød som venter blir ikke sendt, samme røde
sak blir sendt etter at et menneske godkjente den, og én der mottakeren ble
byttet etter godkjenningen blir ikke sendt.

### Steg 3: Se på filene

```bash
ls maildrop
```

Hver fil er en e-post. Åpne en av dem — i et e-postprogram, eller bare i en
tekstredigerer. Øverst står mottaker, emne og noen linjer som begynner på
`X-Lonewatch-`: hvilken agent som ba om det, hva Lonewatch svarte, og
saksnummeret. Nederst i meldingen står hva Lonewatch sa at konsekvensen var.

**Dette er hele poenget:** du kan ta en e-post som er kommet fram og spore den
tilbake til godkjenningen som slapp den gjennom.

---

## Del 2 — Peke utføreren mot bedriftens egen e-postserver

Nå sendes det på ekte. Les hele denne delen før du begynner.

### Steg 1: Finn fram fire opplysninger fra IT

Spør den som drifter e-posten hos dere om:

1. **Adressen til e-postserveren.** Et navn som `smtp.dittfirma.no`.
2. **Portnummeret.** Vanligvis `587`, noen ganger `25`.
3. **Om serveren krever innlogging.** Dette er viktig — se advarselen i steg 5.
4. **Hvilken avsenderadresse** agentene får bruke. For eksempel
   `ai-agent@dittfirma.no`.

### Steg 2: Be IT om å slippe maskinen gjennom

E-postservere pleier å nekte ukjente maskiner å sende. IT må enten slippe
gjennom maskinen Lonewatch kjører på, eller sette opp en egen konto. Det er
IT-arbeid, ikke noe du gjør i Lonewatch.

### Steg 3: Begynn med én adresse du eier selv

Ikke pek den mot kundene dine første dagen. Lag en testadresse, be en agent
sende til den, og se at meldingen kommer. Deretter utvider du.

### Steg 4: Sett de fire verdiene

I terminalen, før du starter Lonewatch:

```bash
export LONEWATCH_SMTP_HOST=smtp.dittfirma.no
export LONEWATCH_SMTP_PORT=587
export LONEWATCH_SMTP_FROM=ai-agent@dittfirma.no
export LONEWATCH_SMTP_STARTTLS=1
```

`STARTTLS` betyr at meldingen krypteres på veien til serveren. **Merk:** dette
er ikke prøvd mot en ekte server. Se «Hva som ikke er gjort» nedenfor.

### Steg 5: Åpne sperren — med vilje

Utføreren nekter å sende noe annet sted enn til din egen maskin, med mindre du
sier klart fra. Det er ikke til å glemme bort:

```bash
export LONEWATCH_SMTP_ALLOW_REMOTE=1
```

Nøyaktig `1`. Ikke `ja`, ikke `true`. En sperre som kan slås av ved et uhell er
ingen sperre.

**Stopp her hvis serveren krever innlogging.** Utføreren har ingen plass til
brukernavn og passord. Det er ikke glemt, det er ikke bygget. Vil du videre,
må enten IT slippe gjennom maskinen uten innlogging (steg 2), eller noen må
bygge innlogging inn i `executor/smtp.py`. Prøv aldri å løse det ved å legge
et passord inn i en fil i dette prosjektet.

### Steg 6: Send én e-post, til deg selv

Kjør én forespørsel gjennom. Kom meldingen? Da virker det. Kom den ikke, sier
utføreren hva som gikk galt — og den sier det på norsk, uten å gjette.

### Steg 7: Hvis noe går galt

Utføreren svarer alltid én av to ting, aldri noe i mellom:

- **«Ikke utført: …»** — handlingen ble ikke gjort, og grunnen står der.
- **«Sendt til o\*\*\*@dittfirma.no via …»** — meldingen gikk.

En handling som feilet blir **ikke** forsøkt igjen automatisk. Det er med
vilje: når et kall brekker halvveis, vet ingen om e-posten gikk ut eller ikke,
og to e-poster er verre enn null. Vil du prøve igjen, må handlingen gjennom
Lonewatch på nytt — og godkjennes på nytt.

---

## Hva som ikke er gjort

Dette er en hackathon-simulering. Sendingen av e-post er ekte, resten er ikke.
Her er de ærlige hullene. Den tekniske versjonen står i `executor/LIMITS.md`.

### Innlogging finnes ikke
Ingen brukernavn, ingen passord, ingen nøkler — verken i koden eller i
oppsettet. De fleste e-postservere i bedrifter krever innlogging. Da virker
ikke utføreren uten at IT slipper maskinen gjennom på annen måte.

Det var et valg: et passord som skal leses av et program må ligge et sted, og
vi ville ikke bygge «et sted» i en hackathon-demo uten å kunne gjøre det
ordentlig.

### Krypteringen på linjen er ikke prøvd
`LONEWATCH_SMTP_STARTTLS=1` finnes og slår på kryptering. Den er **aldri
testet mot en ekte server** — vi hadde ingen å teste mot. Regn den som uprøvd.
Fungerer sending bare når du slår den av, er det kryptering du har mistet, og
det bør noen se på før dette brukes på noe som betyr noe.

### Bare e-post er ekte
`send_email` skjer på ekte. Alt annet Lonewatch kan vurdere — overføre penger,
dele data, installere et tillegg, lese et dokument, oppdatere en kalender —
går gjennom den samme kontrollen og gjør så ingenting. Du får altså det samme
røde varselet for en betaling, men ingen penger flytter seg.

### Sperren mot ekstern sending er en bremse, ikke en vegg
Utføreren leser adressen du skrev inn og ser om den ser lokal ut. Den slår den
ikke opp. Har noen rotet til navneoppslaget på maskinen, kan `localhost` peke
et annet sted, og utføreren vil ikke merke det. Sperren er der for å hindre et
uhell under en demo.

### Lonewatch glemmer hva som er utført når programmet stoppes
Utføreren holder styr på hvilke forespørsler som er forsøkt, slik at ingen
handling skjer to ganger. Den listen lever i minnet. Starter du Lonewatch på
nytt, er den tom, og den samme forespørselen kan utføres en gang til.

Grunnen henger sammen med den neste: for å huske på tvers av omstart måtte
utføringen stått i loggen.

### Utføringen står ikke i loggen
Loggen vet at en agent spurte, hva Lonewatch svarte, og hva mennesket svarte.
Den vet **ikke** om handlingen faktisk ble gjort. Svaret fra utføreren går
tilbake til den som kalte den, og der stopper det.

Grunnen er at `contracts.py` — den felles avtalen mellom modulene — er låst, og
den har ingen plass for «en utføring» i dag. Å endre den er et valg eieren av
prosjektet må ta. Alternativene står i `executor/LIMITS.md` punkt 2.

Dette er det viktigste hullet i denne runden. En logg som ikke vet om det
skjedde, kan ikke svare på spørsmålet «gikk den e-posten ut?».

### Ingen kontroll på hva som er lov å kontakte
Utføreren sjekker at mottakeradressen er en adresse. Den har ingen liste over
hvilke domener agenter får sende til, ingen begrensning på hvor mange
e-poster per time, og ingen sjekk mot at det samme går ut mange ganger. Alt det
ligger hos reglene i `gateway/` eller er ikke bygget.

### Forseglingen stopper en agent, ikke en angriper
Låsen som sier «dette er det samme som ble godkjent» er en vanlig sjekksum
uten nøkkel. Den stopper at en agent endrer en forespørsel etter at mennesket
trykket Godkjenn. Den stopper ikke noen som kan kjøre egen kode inne i
Lonewatch — de kan lage en godkjenning som ser riktig ut.

### Utføreren er ikke koblet til resten ennå
Ingenting kaller den. Mellomstasjonen og nettsiden vet ikke at den finnes.
Koblingen gjøres etter at grenene slås sammen, og stedet er beskrevet under.

---

## Hvor koblingen skal gjøres (for utvikleren)

Utføreren er ferdig og testet, men **ingenting kaller `execute()` ennå**. Her
er de to stedene den skal inn.

### 1. `ui/state.py` — `DemoState._handle()`, rett etter `evaluate()`

`_handle()` kaller `gateway.evaluate()`, logger avgjørelsen og legger et kort i
`self.cards`. **Forseglingen må skje her**, i samme øyeblikk som avgjørelsen —
ikke senere:

```python
godkjenning = executor.seal(req, decision)
card["approval"] = godkjenning          # kortet bærer forseglingen videre
```

Kortet lagrer `request` og `decision` som dict (`model_dump(mode="json")`).
`Approval` er ikke JSON, så den må ligge som objekt på kortet, eller i en egen
oppslagstabell ved siden av — den skal aldri sendes til nettleseren.

Der avgjørelsen er `allow`, utføres handlingen med én gang:

```python
if decision.verdict is Verdict.ALLOW:
    resultat = self._executor.execute(req, decision, godkjenning)
```

En `red` gjør ingenting her. Den venter på steg 2.

### 2. `ui/state.py` — `DemoState.respond()`, rett etter `approved=True`

`respond()` bygger allerede en `HumanResponse` og setter
`card["status"] = STATUS_APPROVED`. Rett etter den linjen:

```python
godkjenning = card["approval"].with_human(human)
req = ActionRequest(**card["request"])
decision = Decision(**card["decision"])
resultat = self._executor.execute(req, decision, godkjenning)
```

`with_human()` — ikke `seal()` på nytt. Det er forskjellen som gjør hele
sperren verdt noe: `with_human()` beholder avtrykket fra da avgjørelsen falt,
mens et nytt `seal()` ville regnet ut avtrykket av forespørselen slik den ser
ut **nå**, og dermed sluppet gjennom en endring som skjedde mens mennesket
tenkte.

At `req` og `decision` bygges opp igjen fra dict-ene på kortet er trygt
nettopp fordi avtrykket sjekkes: en forespørsel som har vært gjennom JSON og
tilbake gir samme avtrykk, en som er endret gjør det ikke.

### 3. Hvilken utfører

`DemoState` bør lage **én** utfører ved oppstart og bruke den hele veien, slik
at boka over hva som er forsøkt er den samme:

```python
self._executor = SimulatedExecutor()        # standard, trygg i demoen
# eller, når postfangeren kjører:
self._executor = SmtpExecutor()             # leser oppsettet fra miljøet
```

En `SmtpExecutor` som får en forespørsel som ikke er `send_email` svarer «ikke
utført». Skal begge virke, trengs en liten ruting på `action_type` — og den
bør dele `AttemptLedger` mellom utførerne:

```python
bok = AttemptLedger()
self._executors = {
    ActionType.SEND_EMAIL: SmtpExecutor(ledger=bok),
}
self._default_executor = SimulatedExecutor(ledger=bok)
```

### 4. Loggingen — stopp og spør først

Det naturlige neste steget er `vault.append("execution", resultat.model_dump())`.
**Det virker ikke i dag:** `LogKind` i den låste `contracts.py` har ingen
`"execution"`. Ikke press resultatet inn i en av de fem artene som finnes —
loggen blir løgnaktig. Alternativene står i `executor/LIMITS.md` punkt 2, og
valget er eierens.

### 5. `agent_gateway/`

Samme to steder, samme rekkefølge: forsegl når avgjørelsen faller, utfør når
godkjenningen finnes. Utføreren er helt uavhengig av `agent_gateway/` og
`ui/` — den importerer bare `contracts`.
