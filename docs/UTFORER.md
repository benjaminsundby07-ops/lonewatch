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

### Steg 4: Hele veien, med nettsiden

`python3 -m executor` kjører utføreren alene. Vil du se den i selve Lonewatch —
rødt kort, menneske som godkjenner, e-post som kommer fram — gjør du dette i
stedet, med postfangeren fortsatt kjørende i det første vinduet:

```bash
source .lonewatch-agent-env          # nøklene, inkludert menneskenøkkelen
export LONEWATCH_EXECUTOR=smtp       # ellers simuleres alt
export LONEWATCH_SMTP_PORT=8025      # samme port som postfangeren
python3 -m ui
```

Åpne <http://127.0.0.1:8000>, gå til **Godkjenning**, og lås opp med
menneskenøkkelen:

```bash
grep LONEWATCH_HUMAN_KEY .lonewatch-agent-env
```

Lim verdien inn i feltet «Menneskenøkkel». Uten den kan ingenting godkjennes —
heller ikke av en agent.

Prøv så fire ting i **Prøv selv**, og se i `maildrop` etter hver:

| Du gjør | Forventet |
|---|---|
| E-post til `alle@nordlysforsikring.no` | grønt → **én ny `.eml`** |
| E-post til en ukjent adresse, la den ligge | rødt → **ingen fil** |
| Samme kort, trykk **Avvis** | **ingen fil**, og kortet sier «Ikke utført» |
| Samme type kort, trykk **Godkjenn** | **én ny `.eml`** |
| Overføring på 99 000 000 kr | blokkert → **ingen fil**, og ingen kan godkjenne den |

Åpne den siste filen: `X-Lonewatch-Fingerprint` øverst er det samme avtrykket
som står i `"execution"`-linjen i loggen. Det er den tråden som binder en
e-post i en innboks til mennesket som slapp den gjennom.

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

### Lonewatch husker hva som er utført — så lenge loggen er den samme
**Dette er rettet.** Utføringen står nå i loggen, og listen over hva som er
forsøkt leses derfra når Lonewatch starter. Starter du på nytt, blir ikke den
samme forespørselen utført en gang til.

Det som fortsatt gjelder: trykker du **Nullstill**, begynner en ny logg — og da
begynner listen på nytt sammen med den. Demodataene har faste saksnummer, så
etter en nullstilling kan de samme forespørslene utføres igjen. Det er riktig
for en demo og galt for et produkt.

### Utføringen står i loggen
**Dette er rettet.** Loggen vet nå fire ting om en sak: at en agent spurte, hva
Lonewatch svarte, hva mennesket svarte, og **om handlingen faktisk ble gjort**.

Hver utføring er én linje med saksnummer, tidspunkt, om den ble utført, en
norsk setning som sier hva som skjedde, og hvem som gjorde den. Mottakeren står
maskert (`o***@nordlys.no`), aldri hel.

Det krevde én endring i `contracts.py` — den felles avtalen mellom modulene,
som ellers er låst: `"execution"` som en sjette art i loggen. Det var eierens
beslutning, og det er den eneste linjen som ble endret der.

Nå kan du ta en e-post som er kommet fram, lese saksnummeret og avtrykket
øverst i filen, og finne nøyaktig den linjen i loggen som sier at den gikk ut —
og linjen over, som sier hvem som godkjente den.

Det den **ikke** sier: linjen forteller hva utføreren mente skjedde. Brekker et
SMTP-kall midtveis, står det «ikke utført» om en e-post som kanskje kom fram.
Se neste avsnitt.

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

### Utføreren er koblet til nettsiden, ikke til terminaldemoen
**Dette er rettet.** Nettsiden kaller utføreren to steder: når Lonewatch sier
grønt, og når et menneske godkjenner et rødt kort. Kortet i dashbordet viser
etterpå om handlingen ble gjort eller ikke.

`python run_demo.py` — demoen som kjører alle førti forespørslene i terminalen
— er med vilje ikke koblet til. Den viser regler og logg, ikke handlinger, og
skriver fortsatt 88 linjer.

### Bare et menneske kan godkjenne, og det kan bevises — nesten
Et rødt kort kan ikke lenger godkjennes av hvem som helst som når porten. Du må
låse opp **Godkjenning** med en egen menneskenøkkel først, og agentens nøkkel
duger ikke til det.

Det store forbeholdet: nøkkelen er en tekst i en fil på maskinen din. En agent
med tilgang til å kjøre kommandoer kan lese den. Hele den ærlige regningen står
i `ui/LIMITS.md`.

---

## Hvor koblingen ER gjort (for utvikleren)

Utføreren kalles fra **to steder**, og ingen andre. Begge ligger i
`ui/state.py`.

### 1. `DemoState._handle()`, rett etter `evaluate()`

Forseglingen lages i samme øyeblikk som avgjørelsen faller:

```python
approval = seal(req, decision)
card["approval"] = approval          # kortet bærer forseglingen videre
```

`Approval` er ikke JSON. Den ligger på kortet som objekt, og `_public()` tar den
bort før kortet forlater tjeneren — den skal **aldri** til nettleseren.
`PRIVATE_CARD_KEYS` er listen, og `tests/test_executor_wiring.py` går gjennom
hele API-flaten og sjekker at verken forseglingen eller avtrykket er der.

Er avgjørelsen `allow`, utføres handlingen med én gang:

```python
if decision.verdict is Verdict.ALLOW:
    card["execution"] = self._execute(req, decision, approval)
```

En `red` gjør ingenting her. Den venter på steg 2.

### 2. `DemoState.respond()`, rett etter `approved=True`

```python
godkjenning = approval.with_human(human)
req = ActionRequest(**card["request"])
decision = Decision(**card["decision"])
card["execution"] = self._execute(req, decision, godkjenning)
```

`with_human()` — ikke `seal()` på nytt. Det er forskjellen som gjør hele sperren
verdt noe: `with_human()` beholder avtrykket fra da avgjørelsen falt, mens et
nytt `seal()` ville regnet ut avtrykket av forespørselen slik den ser ut **nå**,
og dermed sluppet gjennom en endring som skjedde mens mennesket tenkte.

At `req` og `decision` bygges opp igjen fra dict-ene på kortet er trygt nettopp
fordi avtrykket sjekkes: en forespørsel som har vært gjennom JSON og tilbake gir
samme avtrykk, en som er endret gjør det ikke.
(`test_a_request_changed_after_the_decision_is_not_executed`.)

### 3. Hvilken utfører

`DemoState` lager **én** bok (`AttemptLedger`) og deler den mellom alle
utførerne, slik at to utførere ikke kan gjøre samme handling hver sin gang:

```python
self._ledger = AttemptLedger()
self._default_executor = SimulatedExecutor(ledger=self._ledger)   # standard
# bare når LONEWATCH_EXECUTOR=smtp:
self._executors[ActionType.SEND_EMAIL] = SmtpExecutor(ledger=self._ledger)
```

Alt annet enn nøyaktig `smtp` (etter at luft er klippet og bokstaver senket) gir
den simulerte. En utfører som rører omverdenen skal ikke kunne slås på ved en
skrivefeil.

### 4. Loggingen

`vault.append("execution", resultat.model_dump(mode="json"))`. Arten
`"execution"` ble lagt til i `LogKind` i `contracts.py` — én linje, og den
eneste endringen i den låste filen.

Ved oppstart leser `_seed_ledger_from_log()` alle `"execution"`-linjene og
merker dem som forsøkt. Det er grunnen til at utføringen MÅTTE logges: uten det
levde boka bare i minnet, og en omstart lot den samme forespørselen gå ut en
gang til.

Avtrykket logges, men sendes ikke til nettleseren (`PRIVATE_EXECUTION_KEYS`).
Det er det som binder en `.eml`-fil på disk til godkjenningen som slapp den
gjennom.

### 5. `agent_gateway/`

Trenger ingen egen kobling. Agentens forespørsler går gjennom `ui/state.py`
som alt annet, og utføres der. Det MCP-tjeneren sier til agenten
(«UTFØRT (simulert)») er fortsatt en fast tekst som ikke spør hva utføreren
svarte — se `executor/LIMITS.md` punkt 10.
