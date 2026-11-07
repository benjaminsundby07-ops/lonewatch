# Red team: angrep mot Lonewatch

Rolle: angriper. Jobben er å finne ekte svakheter før juryen (etisk hacker + jurist)
gjør det. Jeg har **ikke** endret kode eller tester — bare skrevet denne filen.

Alt er kjørt lokalt mot den simulerte demoen. Appen kjørte på `LONEWATCH_PORT=8150`
med egen loggsti (`LONEWATCH_LOG_PATH` i en scratchpad-mappe), så ingen ekte logg ble
rørt. Ingen test og ingen sonde pekte ut mot internett; nettverkssondene brukte bare
`192.0.2.0/24` (RFC 5737 TEST-NET, rutes ikke) og `.invalid`.

Oppsett jeg brukte:

```bash
export LONEWATCH_LOG_KEY=$(python -m vault.gen_key)
export LONEWATCH_PSEUDONYM_KEY=$(python -m vault.gen_key --pseudonym)
export LONEWATCH_LOG_PATH=<scratchpad>/redteam_log.jsonl
export LONEWATCH_PSEUDONYM_TABLE=<scratchpad>/redteam_pseudo.enc
export LONEWATCH_PORT=8150
python -m pytest -q        # 239 passed, 1 xfailed (se F8 om flakiness)
python -m ui               # appen
```

Prosjektets egne `LIMITS.md`-filer er uvanlig ærlige og grundige. Mange ting en
angriper normalt ville "funnet" står allerede der svart på hvitt (sandkasse-rømning,
loggens svakheter, at reglene stoler på feltene i forespørselen). Jeg skiller derfor
tydelig mellom **(a)** ting jeg faktisk reproduserte som IKKE står i LIMITS, **(b)**
ting som står i LIMITS og som jeg bekreftet holder/stemmer, og **(c)** ting som
holder bedre enn man skulle tro.

---

## Oppsummering (mest alvorlig først)

| # | Alvorlighet | Funn | I LIMITS? | Fiks før pitch? |
|---|-------------|------|-----------|-----------------|
| F1 | **KRITISK** | Beløpsbekreftelsen kan omgås: "skriv beløpet" godtar et helt annet beløp (desimaler/øre/minus) | Nei | **Ja** |
| F2 | Middels | `gateway.evaluate()` krasjer på `amount=inf` (gyldig i contracts) | Nei | Ja (liten) |
| F3 | Lav | `/api/respond` gir 500 på ekstremt lang sifferstreng (uhåndtert `ValueError`) | Nei | Valgfritt |
| F4 | Lav | Å (prøve å) starte en app nr. 2 arkiverer den kjørende appens logg og knekker kjeden | Delvis (vault #6/#9) | Nevn ærlig |
| F5 | Lav | `network_bind` gir `attempted_network=True` men `verdict=clean` (inkonsistens) | Nei | Valgfritt |
| F6 | Lav | `/api/reset` er uten autentisering — hvem som helst kan starte ny logg | Delvis (vault #9) | Nevn ærlig |
| F7 | Info | Beløp vist avrundes opp til grensen, men vurderes under (49 999,50 → "50 000 kr", allow) | Nei | Nevn |
| F8 | Lav (test) | `test_boksen_ryddes_opp_etter_skanning` er ikke-hermetisk (flaky ved samtidig kjøring) | Nei | Valgfritt |

Bekreftet at HOLDER: XSS-forsvaret i UI (B1), hash-kjedens deteksjon av endring/midt-sletting
(B2), sandkassens navne-/stisjekk (B3), og alle de dokumenterte sandkasse-rømningene
oppfører seg akkurat som LIMITS beskriver (B4).

---

## F1 — KRITISK: Beløpsbekreftelsen kan omgås

**Hva:** Det sterkeste leddet i demoen er at et menneske må *skrive inn beløpet* for å
godkjenne en stor overføring (`requires_typed_amount`). Formålet står eksplisitt i koden:
*"Poenget med å skrive beløpet er at man skal se det."* Den sjekken kan omgås. Et menneske
(eller et skript som kaller API-et) kan "bekrefte" en overføring på **10 000 000 kr** ved å
skrive inn **`100000,00`** (hundre tusen kroner og 00 øre) — eller `-10000000`, eller
`1000000,0`. Loggen vil da vise at operatøren bekreftet **10 000 000**, selv om det de
faktisk skrev var et annet tall.

**Årsak:** `ui/state.py::amount_matches()` kaller `_digits()`, som fjerner **alle**
tegn som ikke er `0-9` — inkludert komma, punktum og minus — og sammenligner så
sifrene. `"100000,00"` → `"10000000"` → `10 000 000`. Desimalskilletegnet forsvinner,
så "hundre tusen og null øre" blir numerisk likt "ti millioner". Nøyaktig samme logikk
ligger i `ui/static/app.js` (`digits()` + `Number(...) === Math.round(amount)`), så
knappen blir aktiv i nettleseren også — dette er ikke bare et API-hull.

**Reprodusert (ekte API-kall mot kjørende app):**

```bash
# spol fram til den store overføringen (req_0037) ligger i køen
for i in $(seq 1 40); do curl -s -X POST localhost:8150/api/feed/step -o /dev/null; done

curl -s -X POST localhost:8150/api/respond -H 'Content-Type: application/json' \
  -d '{"request_id":"req_0037","approved":true,"typed_amount":"100000,00"}'
```

Svar:

```
ok = True
status = approved
konsekvenstekst = Overfører 10 000 000 kr til ukjent konto. Kan ikke angres.
forventet beloep = 10000000.0
LOGGET typed_amount = 10000000.0      <-- loggen "beviser" at operatøren skrev 10 mill
```

Flere verdier som alle blir godtatt mot forventet `10 000 000`:
`"100000,00"`, `"100000.00"`, `"1000000,0"`, `"-10000000"`, `"+10000000"`,
`"abc10000000xyz"`, `"0010000000"`. (Rene desimaltall som `"10000000.00000"` blir
derimot avvist, fordi det gir 13 sifre — inkonsistensen er vilkårlig.)

**Konsekvens:** Hele demoens kjernefortelling — "mennesket må se og skrive beløpet"
— er falsk i den formen den har nå. En uoppmerksom operatør som taster feil
skilletegn får likevel grønt lys, og i ettertid ser loggen ut som en korrekt,
bevisst godkjenning av riktig sum. For en jurist er dette verre enn ingen sjekk:
det produserer et villedende revisjonsspor.

**Bonus:** Desimalbeløp kan aldri bekreftes korrekt. Er forventet beløp `1234.56`,
blir `"1234.56"` avvist (gir 123456 sifre) mens `"1235"` godtas. Demoen bruker bare
runde beløp, så dette er skjult i dag, men det viser at hele parsingen er feil
modellert: den jobber på "sifre", ikke på "kroner".

**Forslag til fiks (ikke hack):** Tolk input som et beløp, ikke som en siffersekvens.
Fjern tusenskille (mellomrom/punktum som grupperer), tolk komma som desimalskille,
avvis minus, og sammenlign *tallverdien* mot forventet (gjerne med eksakt heltalls-
øre). Gjør samme tolkning begge steder (`state.py` og `app.js`) fra én felles regel.
Legg til tester for `"100000,00"`, `"-10000000"` og desimalbeløp.

**Bør fikses før pitchen:** JA. Dette er det eneste funnet jeg mener undergraver
selve budskapet. Alt annet kan nevnes ærlig; dette bør rettes.

---

## F2 — Middels: `evaluate()` krasjer på uendelig beløp

**Hva:** `contracts.ActionRequest.amount` har bare `ge=0`, så `float("inf")` er en
gyldig verdi. `gateway.evaluate()` krasjer da med `OverflowError` i konsekvensteksten.

**Reprodusert:**

```python
from gateway import evaluate
from contracts import ActionRequest, ActionType
from datetime import datetime, timezone
r = ActionRequest(id="x", ts=datetime.now(timezone.utc), agent_id="a",
                  action_type=ActionType.TRANSFER_MONEY, summary="s",
                  amount=float("inf"), recipient="NO1", recipient_known=False)
evaluate(r)
# OverflowError: cannot convert float infinity to integer
#   gateway/consequence.py:68  int(round(amount))
```

`amount=1e308` krasjer ikke, men lager en ~309-sifret konsekvenstekst
("Overfører 100 000 000 000 ... kr") — ufarlig, men stygt.

**Konsekvens:** En agent/klient som sender `inf` (eller bare en buggy integrasjon)
tar ned `evaluate()` for den forespørselen. Ikke naabar fra demo-UI-et (forespørslene
der er faste), men `evaluate()` er et dokumentert, offentlig grensesnitt
(`gateway.evaluate(req) -> Decision`) som andre deler kaller direkte.

**Forslag til fiks:** Avvis ikke-endelige beløp tidlig (f.eks. behandle
`not math.isfinite(amount)` som "over hard grense" → block), eller la
`format_amount()` håndtere det. `contracts.py` er låst, så dette må løses i gateway.

**Bør fikses før pitchen:** Ja, men liten jobb. Lav sannsynlighet for å dukke opp i
demoen, så ikke blokkerende.

---

## F3 — Lav: `/api/respond` svarer 500 på ekstremt lang sifferstreng

**Hva:** Sender man en `typed_amount` med flere enn 4300 sifre, krasjer
`amount_matches()` på Pythons `int()`-grense for strengkonvertering, og endepunktet
returnerer **HTTP 500** (uhåndtert unntak). Appen lever videre.

**Reprodusert:**

```bash
BIG=$(python -c "print('1'*5000)")
curl -s -o /dev/null -w "%{http_code}\n" -X POST localhost:8150/api/respond \
  -H 'Content-Type: application/json' \
  -d "{\"request_id\":\"req_0037\",\"approved\":true,\"typed_amount\":\"$BIG\"}"
# 500
# serverlogg: ValueError: Exceeds the limit (4300 digits) for integer string conversion
```

**Konsekvens:** Liten. Et stygt 500-svar, ingen tjenestenekt utover én forespørsel,
ingen lekkasje (FastAPI skjuler stacktrace i responsen). Mest et tegn på at
`respond()` ikke pakker inn beløpsparsingen.

**Forslag til fiks:** Løses sammen med F1 — tolk input robust og returner en pen
"beløpet stemmer ikke"-feil i stedet for å la unntaket boble opp. Eventuelt
lengdebegrens feltet.

**Bør fikses før pitchen:** Valgfritt. Blir borte gratis hvis F1 fikses riktig.

---

## F4 — Lav: Å starte en app nr. 2 arkiverer den kjørende loggen og knekker kjeden

**Hva:** `ui/app.py` lager `state = DemoState()` ved import, og `DemoState.reset()`
kaller `archive_log()`, som **gir nytt navn til** den eksisterende loggfilen. Starter
man en ny app-instans mot samme `LONEWATCH_LOG_PATH` — *selv om den feiler på
`bind()` fordi porten er opptatt* — rekker den å importere `ui.app` og dermed
arkivere loggen som den første, kjørende appen fortsatt skriver til. Den første
appen fortsetter å appende, men nå til en fersh fil som starter på `seq=12`
(ikke 0), uten `prev_hash`-peker til genesis. `verify()` slår ut riktig, men skaden
er skjedd.

**Reprodusert:**

```
A) app1 kjører, 12 linjer:        verify: True  "Loggen stemmer. 12 linjer"
B) forsøk å starte app2 (samme port -> bind-feil, men importerer ui.app):
   filer på disk: redteam_log.20261107T...jsonl   (app1 sin logg ble arkivert!)
C) app1 logger 2 nye steg -> ny fil med 4 linjer, seq starter på 12:
   verify: False "Første ødelagte linje er seq=12"
D) uavhengig leser: linjer=4, første seq=12, verify()=12
```

**Konsekvens:** `verify()` fanger det (bra), så det er ikke en stille forfalskning.
Men det er en lett utløst, utilsiktet måte å ødelegge et "ubrutt" loggspor midt i en
demo — f.eks. hvis noen åpner et nytt terminalvindu og kjører `python -m ui` en gang
til. Vault `LIMITS.md` #6 (ingen fillås ved samtidig skriving) og #9 (nullstilling
starter ny kjede) dekker mekanismen, men ikke denne konkrete, import-utløste
triggeren i UI-laget.

**Forslag til fiks:** Ikke arkiver/nullstill som bieffekt av import. Flytt
`reset()`/`archive_log()` ut av konstruktoren, eller ta en enkel fillås/PID-fil slik
at en andre instans nekter å starte i stedet for å røre loggen.

**Bør fikses før pitchen:** Nevn det ærlig. Eventuelt bare "ikke start to", som er
rimelig for en hackathon.

---

## F5 — Lav: `network_bind` teller som nettverk, men blokkerer ikke

**Hva:** `report.NETWORK_EVENTS` inneholder `network_bind`, men
`config.BLOCKING_EVENTS` gjør det **ikke**. Et tillegg som bare kaller `bind()` får
derfor en rapport med `attempted_network=True` **og** `verdict="clean"` samtidig —
en selvmotsigelse. `vault/after.py` bygger da en "Tillegget prøvde å sende data
ut"-oppgave fra en rapport som samtidig er merket `clean`.

**Reprodusert (sonde i boksen):**

```
bind_only:  verdict=clean  attempted_network=True  dest=['192.0.2.99:4444']
            kinds=['start','network_socket','network_bind','result','done']
            notes: "Tillegget prøvde å koble seg til 1 adresse ... Sandkassen svarte nei"
```

**Konsekvens:** Liten i praksis: ingen demo-tillegg binder, og `connect`/`sendto`/
`getaddrinfo` (de reelle exfil-veiene) er korrekt blokkerende. Men det er en logisk
inkonsistens: samme rapport sier både "prøvde nett" og "clean", og Etter-listen kan
peke på en "clean" linje. En oppmerksom jurymedlem vil se det.

**Forslag til fiks:** Enten ta `network_bind` inn i `BLOCKING_EVENTS`, eller ta det ut
av `NETWORK_EVENTS`, slik at `attempted_network` og `verdict` ikke kan være uenige.

**Bør fikses før pitchen:** Valgfritt.

---

## F6 — Lav: `/api/reset` er uten autentisering

**Hva:** `POST /api/reset` arkiverer loggen og starter en ny, tom logg. Det finnes
ingen innlogging eller token foran noen av endepunktene (hele appen er uautentisert).
Hvem som helst med nettverkstilgang til porten kan dermed "spole historien" ved å
starte en fersk logg.

**Konsekvens:** Begrenset, fordi (a) appen binder bare `127.0.0.1` som standard, og
(b) nullstilling er *synlig*: `verify()` på den nye loggen sier riktignok "stemmer",
men UI viser stien til den arkiverte loggen, og ingenting slettes. Dette er altså en
ærlig nullstilling, ikke en skjult forfalskning. Men i en ekte setting er en
uautentisert "start ny logg"-knapp et problem i seg selv.

**Forslag til fiks:** For demoen: dokumentér at alt kjører uautentisert på localhost.
For en ekte versjon: autentisering foran skrivende/nullstillende endepunkter, og
arkivfiler et sted Lonewatch ikke selv kan overskrive (som vault `LIMITS.md` #1/#9
allerede foreslår).

**Bør fikses før pitchen:** Bare nevnes.

---

## F7 — Info: Vist beløp avrundes opp til grensen, men vurderes under den

**Hva:** `amount_over_limit` sammenligner rå `amount >= 50000`, mens
`format_amount()` runder til hele kroner for visning. Et beløp på `49 999,50` blir
**allow** (49999.5 < 50000), men ville blitt vist som **"50 000 kr"** — nøyaktig
grensen. Visning og vurdering er ikke enige om samme tall.

**Reprodusert:**

```
amount=49999.5   vist="50 000 kr"   verdict=allow
amount=50000.0   vist="50 000 kr"   verdict=red
```

**Konsekvens:** Ubetydelig i demoen (alle beløp er runde), men prinsipielt: tallet et
menneske ser kan avvike fra tallet regelen brukte. Verdt én setning i en ærlig pitch.

**Forslag til fiks:** Rund (eller gulv/tak) beløpet på samme måte før både
sammenligning og visning, slik at "det du ser er det som ble vurdert".

**Bør fikses før pitchen:** Nevnes, ikke blokkerende.

---

## F8 — Lav (test): `test_boksen_ryddes_opp_etter_skanning` er ikke-hermetisk

**Hva:** Testen lister `lonewatch-*`-mapper i systemets temp-katalog før og etter en
skanning og krever at mengden ikke vokser. Den teller også mapper fra **andre**
prosesser. Kjører noe annet en sandkasse-skanning samtidig (en parallell testkjøring,
en annen Lonewatch-økt, en av mine sonder), feiler testen selv om `sandbox/` rydder
helt korrekt opp etter seg selv.

**Reprodusert:**

```bash
# bakgrunn: en løkke som skanner date-utils 30 ganger
python -c "import sandbox; [sandbox.scan('date-utils') for _ in range(30)]" &
python -m pytest -q tests/test_sandbox.py::test_boksen_ryddes_opp_etter_skanning
# FAILED: Extra items in the left set: 'lonewatch-boks-...', 'lonewatch-styring-...'
```

Alene er suiten grønn: `239 passed, 1 xfailed`. Selve opprydningen (`shutil.rmtree`
i `run_in_box`s `finally`) virker — jeg fant ingen lekkede mapper fra normale kjøringer.

**Konsekvens:** Falsk rødt. CLAUDE.md sier "kjør `pytest -q` før du sier noe er
ferdig". Hvis to økter kjører tester samtidig (sannsynlig på en hackathon), kan denne
testen feile uten at noe er galt, og stjele tid rett før pitch.

**Forslag til fiks:** Gjør testen hermetisk: skann i en egen `tempfile.mkdtemp()` og
sjekk bare at *den* mappen er tom, eller sammenlign bare mot mapper testen selv lagde
(f.eks. på PID i prefikset). Jeg rører ikke tester selv.

**Bør fikses før pitchen:** Valgfritt, men billig forsikring.

---

## Bekreftet at HOLDER (ikke overdriv — dette er solid)

**B1 — XSS i UI: tett.** Jeg testet `esc()` fra `app.js` mot de vanlige nyttelastene
(`<script>`, `"><img onerror>`, `' onmouseover`, `</p><svg onload>`,
attributt-utbrudd `" autofocus onfocus=`, `<iframe srcdoc>`, `<style>`). Alle fem
farlige tegnene (`& < > " '`) escapes. Jeg gikk gjennom alle 12 `innerHTML`-stedene:
hver eneste variabel fra data (agent-tekst, `summary`, `recipient`, `consequence_text`,
felle-tekst, `package_name`, destinasjoner, arkivsti, pseudonym) går gjennom `esc()`.
`textContent` brukes der det ikke escapes. **Ingen XSS funnet.** Dette er gjort riktig.

**B2 — Hash-kjeden fanger endring og midt-sletting.** Testet matrise mot loggen:

```
linje fjernet fra midten      -> verify()=41  (fanget)
to linjer byttet om           -> verify()=41  (fanget)
linje erstattet med søppel    -> verify()=40  (fanget)
linje erstattet med tom linje -> verify()=40  (fanget)
siste linje duplisert         -> verify()=87  (fanget)
hale kuttet (5 linjer)        -> verify()=None (IKKE fanget av en fersk leser)
erstattet med bare linje 0-9  -> verify()=None (IKKE fanget av en fersk leser)
tom/slettet logg              -> verify()=None (IKKE fanget av en fersk leser)
```

De tre siste (hale-kutt, kortere gyldig kjede, sletting) er **nøyaktig** det vault
`LIMITS.md` #1 sier systemet ikke fanger — og LIMITS har rett. Viktig nyanse i
**appens** favør: så lenge *samme kjørende app* fortsatt har linjene i minnet,
fanger `verify()` også hale-kutt (`_entries` i minnet vs. disk) — jeg bekreftet
"seq=83" mens appen kjørte. Svakheten gjelder en *fersk* leser som bare har filen.
Det er ærlig beskrevet.

**B3 — Sandkassens navne-/stisjekk holder.** `package_path()` avviser `../`-navn,
punktum og store bokstaver via `PACKAGE_NAME_PATTERN`, og dobbeltsjekker at den
resolverte stien ligger i `sandbox/packages/`. Et navn fra en forespørsel kan ikke få
sandkassen til å kjøre en fil utenfor pakkemappen. Gateway kjører aldri noe selv.

**B4 — De dokumenterte sandkasse-rømningene stemmer akkurat som beskrevet.** Jeg kjørte
sonder for hver omvei i `sandbox/LIMITS.md`:

- `open.__globals__["_REAL_BUILTINS_OPEN"]` leser `/etc/hosts` → `clean`. (Dokumentert,
  står som `xfail`-test. Samme vei gir skrivetilgang til hendelsesfilen og lar et
  tillegg tømme `_bait` og lese `.env` **uten** at `secret_read` registreres — begge
  dokumentert.)
- `__name__ = "uuid"` før `import ctypes` → importen avvises, men telles som
  `denied_import_internal` (ikke blokkerende). Dokumentert.
- Agn med ikke-listet navn (`.ssh/id_rsa.pub`) leses → `clean`. Dokumentert
  ("Agnlisten er hardkodet").
- `os.stat`/`os.path.exists` kartlegger `/etc/passwd`, `/Users` utenfra → `clean`.
  Dokumentert ("`os.stat` er ikke sperret").
- Tillegg som krasjer med én gang, eller som mangler `run()` → `clean`. Dokumentert
  ("et tillegg som krasjer blir clean").

Konklusjonen i `sandbox/LIMITS.md` — "en god detektor for et tillegg som ikke prøver
å skjule seg, ikke en vegg" — er en presis og ærlig beskrivelse. Jeg fant **ingen**
udokumentert rømningsvei; eneste nye lille inkonsistens er F5 (`bind`).

**B5 — Gateway stoler på feltene, ikke på teksten.** Bekreftet at `summary` aldri
påvirker avgjørelsen, at `recipient_known=True` på en ukjent konto slipper gjennom
(største hull — dokumentert øverst i `gateway/LIMITS.md`), at persondata til en
*kjent* mottaker aldri gir utslag, og at `nordlys-core`-navnetyveri slipper gjennom.
Alt dette står allerede i LIMITS. Blokklisten normaliserer `strip().lower()`, så
mellomrom/store bokstaver stoppes riktig; derimot omgås blokklisten trivielt av enhver
annen staving (zero-width space, kyrillisk `о`, punktum på slutten) — men da faller
tillegget uansett til `new_package` → rød, så det er ingen reell forverring.

---

## Hva jeg IKKE fikk til (ting som holdt mot angrep)

- **Dobbel godkjenning / godkjenne et avgjort kort:** blokkert av statussjekken
  ("Denne er allerede besvart"). Godkjenne et kort som ikke finnes, eller et som var
  `allow`/`block`: avvist pent.
- **Type-juks på `/api/respond`:** `typed_amount` som tall/liste → ren 422 fra
  Pydantic, ingen krasj. `approved` som streng → ingen godkjenning. Feil JSON,
  manglende felt → 422. (Eneste unntak: F3, lang sifferstreng → 500.)
- **Omgå beløpskravet med tom/null `typed_amount`:** avvist korrekt ("Beløpet
  stemmer ikke"). Hullet i F1 er *innholdet* i det man skriver, ikke at kravet kan
  droppes.
- **XSS gjennom noen datasti inn i UI:** se B1. Fant ingen.
- **Få en forfalsket logglinje forbi `verify()` ved endring midt i filen:** se B2.
  Fanges.

---

## Prioritert anbefaling til teamet

1. **Fiks F1 før pitchen.** Det er det eneste funnet som gjør selve budskapet usant.
   Fiksen er liten og rettet på ett sted (felles beløpstolkning i `state.py` + `app.js`).
2. Fiks F2 (uendelig beløp) samtidig — to linjer i gateway.
3. F3 forsvinner gratis hvis F1 gjøres riktig.
4. F4–F8: ta dem med som ærlige forbehold i pitchen. De fleste er allerede i ånden av
   de eksisterende `LIMITS.md`-filene, som juryen bør få høre er usedvanlig ærlige.
