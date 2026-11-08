# Angrep mot Lonewatch, runde to

Rolle: etisk hacker. Dette er runden **etter** `docs/ANGREP.md`. Den forrige
dekket selvgodkjenning, beloepsporten, oppdeling, gjenbruk av godkjenning, skjult
tekst i dokumenter, agentens loegnaktige felt, svikt og agentverktoeyene. Runde to
tar det runde en IKKE rakk: `vault/` i dybden, `sandbox/`, kapploep, last og
tjenestenekt, de oevrige rutene, kjeding av hull, og informasjonslekkasje.

Hvert angrep er en kjoerbar test i `tests/attack2/` (egen `conftest.py` og egen
`attack_lib2.py`, laaner ingenting fra `tests/attack/`). Holder forsvaret,
bestaar testen. Finnes det et hull, er testen merket `xfail(strict=True)` med en
begrunnelse som sier hva angrepet gjoer og hva som slipper gjennom. Ingen kode er
endret for aa faa noe til aa bestaa.

`strict=True` er med vilje: lukkes et hull senere, feiler testen med XPASS, og da
maa denne filen oppdateres i samme slengen. **Et hull skal ikke kunne bli borte i
stillhet.**

```bash
pytest tests/attack2/     # 152 passed, 7 xfailed, 1 feil (miljøavhengig, se H28 i ANGREP.md) (samlet4)
pytest -q                 # 1578 passed, 25 xfailed, 1 xpassed, 1 feil (samlet4)
```

**Oppdatert etter runde tre.** Fem av hullene under er lukket (A1, A10, A11,
A12 og H27 fra `docs/ANGREP.md`), og to nye angrepsfiler er lagt til:
`test_attack_tamper_route.py` (den nye «Bryt loggen»-ruten) og
`test_attack_executor_gate.py` (kan noe bli utfoert uten en beskyttet rute?).
Testene som var `xfail(strict=True)` paa de lukkede hullene er naa vanlige
tester - de passerte med XPASS, og et hull som blir borte skal ikke bli borte i
stillhet, heller ikke naar det blir borte fordi noen fikset det.

Alt kjoerte lokalt mot simuleringen, paa `127.0.0.1` med ferske engangsnoekler og
loggfil i tmp (`tests/conftest.py` + en ekstra sperre, autouse-fiksturen
`refuse_to_touch_real_log` i `tests/attack2/attack_lib2.py`, som nekter aa kjoere
hvis loggstien ikke er tmp).
Ingen noekkel staar i noen test eller i denne filen. Ingen sonde peker ut mot
internett: oppdiktede adresser bruker `.example`/`.invalid` eller RFC 5737-nettet
`192.0.2.0/24`. Alle servere angrepene starter blir stoppet igjen.

---

## Oppsummering per angrepsomraade

| # | Omraade | Resultat | Hva som ville fikset det |
|---|---------|----------|--------------------------|
| 1 | **vault: noekkelhaandtering** | **HOLDER** | Manglende, tom, kort og ugyldig noekkel avvises alltid. En feil (men gyldig) noekkel gir aldri en stille "ok". Fail closed. |
| 2 | **vault: pseudonymer** | **HOLDER** (ett dokumentert hull) | Kan ikke reverseres eller gjettes uten noekkelen. Men 4 hex = 16 bit gir kollisjoner (LIMITS#5). Flere tegn, eller en entydig tabell. |
| 3 | **vault: redigering/minimering** | **DELVIS** | Summary og full mottaker fjernes. Men `what_happened` og sandkassens `notes` maskeres aldri, og mottakeren maskeres bare til siste fire tegn (LIMITS#7). |
| 4 | **vault: kjede + hale-anker** | **DELVIS** | Endring midt i, kuttet hale med anker, halv linje: alt fanges. Men full utsletting (logg+anker) ser tom ut, og med noekkelen kan alt skrives om eller byttes (LIMITS#1/12). |
| 5 | **vault: fil-laasing** | **DELVIS** | Flock stopper to apper. Men Vault selv tar ingen laas: to Vault-objekter mot samme fil knekker kjeden (LIMITS#6). verify() ser det, men hindrer det ikke. |
| 6 | **sandbox: r0emning** | **DELVIS** (klart bedre, ikke lukket) | De to konkrete angrepene (`open.__globals__` og aa forfalske hendelsesfilen) stoppes: en statisk sjekk avviser kjente moenstre foer kjoering, sperrene ligger i lukninger, og globals er byttet ut med snarer som skriver `guard_bypass`. Rapporten sier bare `clean` naar sperrene bevisst staar igjen (`guards_intact`), ellers `not_tested`/`blocked`. Men Python i samme prosess kan ikke sikres: en rommingsmetode vi ikke har tenkt paa gir fortsatt `clean`. Ekte isolasjon er ikke bygget (`sandbox/LIMITS.md`). |
| 7 | **kapploep** | **HOLDER** | RLock serialiserer respond() og submit. Et kort faar noeyaktig ett utfall, samtidige submits faar unike id-er, kjeden forblir hel. |
| 8 | **last / tjenestenekt** | **LUKKET** (runde 3) | Feltgrenser og dyp JSON haandteres uten krasj. Og naa: 64 KB kroppsgrense (413), 200 aktive kort, 30 kall per minutt per agentnoekkel (429). Endepunktet er dessuten ikke uautentisert lenger. |
| 9 | **de oevrige rutene** | **LUKKET for skriverutene** (runde 3) | Lese-ruter endrer ikke loggen og laekker ingen noekkel. /api/reset arkiverer (sletter ikke) OG krever naa menneskenoekkelen - sammen med /api/custom, /api/feed/step, /api/story/* og den nye /api/tamper. Igjen: /api/trail er ikke delt i to nivaaer. |
| 10 | **kjeding ende-til-ende** | **LUKKET for staving og tilbakedatering** (herd-gw: H6, H7) | Rundet av runde 2 mot koden FOER rettelsene: H14 + H6 og H14 + H7 flyttet >100 000 kr til én konto uten ett roedt kort. Etter sammenslaaingen stoppes begge. H14 (loegn om `recipient_known`) og H9 (mange kontoer) staar igjen. |
| 11 | **informasjonslekkasje** | **LUKKET** (runde 3) | Var: /api/state uautentisert med full mottaker, full summary og interne regelnavn. Naa to nivaaer - uten noekkel en allowliste med tellere, status, risiko og en mottaker maskert med samme funksjon loggen bruker. |

**15 hull ved runden. 9 aapne etter runde tre.** Kjedehullene H6/H7 ble lukket av
`herd-gw`; A1, A10, A11 og A12 er lukket av runde tre. De tre som var HELT nye i
runde to (ingen kroppsgrense, ingen kortgrense, og at `/api/state` laekket raa
persondata og regelnavn) er alle tre lukket. Det som staar igjen er
`sandbox/`-utbruddet (A2/A3), de to kjedehullene som hviler paa bryterne agenten
setter selv (A4/A5), de tre vault-hullene som krever et anker eller en noekkel
utenfor maskinen (A6/A7/A8), laasen (A9) og de tre smaa
minimerings-/pseudonymhullene (A13/A14/A15) - altsaa forbehold prosjektet selv
har skrevet ned i `vault/LIMITS.md` og `sandbox/LIMITS.md`, pluss ett i
`gateway/LIMITS.md`. Ingen av dem ligger i `ui/`.

---

## De fem alvorligste

### 1. `/api/state` laekker raa persondata og regelnavn (nytt) - **LUKKET i runde tre**
`tests/attack2/test_attack_infoleak.py`

Loggen er omhyggelig minimert: full mottaker maskeres, agentens frie `summary`
kastes. Men `/api/state` - uautentisert, samme aapne endepunkt som alt annet -
viser kortene fra **minnet**, ikke loggen. Der staar `ukjent@evil.example` fullt
ut, `summary` ordrett (og den kan inneholde persondata et dokument skrev for
agenten), og `decision.reasons` med de interne regelnavnene
(`unknown_recipient`, `personal_data_external`). En angriper paa porten faar baade
personopplysningene loggen gjemmer, og en oppskrift paa hvilke regler som slo
til. **Saa lett aa utnytte som ett `GET /api/state`.**
**Fiks:** autentiser, eller send ut det samme minimerte synet som loggen.

**Gjort i runde tre, og det ble det andre.** Ruten har naa to nivaaer. Uten
menneskenoekkelen bygges svaret av `ui.state.minimized_snapshot()`, en
ALLOWLISTE: tellere, status, risiko, utfall, og en mottaker maskert med
`vault.redaction.mask_recipient` - noeyaktig funksjonen loggen bruker, saa den
laaste siden kan per konstruksjon ikke vise mer av en konto enn loggen gjoer.
`summary`, `decision.reasons`, konsekvensteksten, sandkasserapportene, notisene
og arkivstien er ikke med. Med noekkelen: alt, som foer.

Hvorfor allowliste og ikke «fjern de tre feltene»: et nytt felt i `snapshot()`
skal som standard IKKE naa en uinnlogget leser. Glemmer noen aa legge det til i
listen, mangler det paa den laaste siden - en synlig feil. Med en denyliste ville
det lekket i stillhet, og det er samme feil om igjen.

Hvorfor to nivaaer og ikke 403: et `/api/state` som nekter, gjoer nettsiden tom
foer noen har logget inn - og da ser ingen at det ER en mellomstasjon her. Hele
begrunnelsen staar i `ui/LIMITS.md` punkt 10, med hva den IKKE loeser
(nivaaet foelger noekkelen, ikke en person; `/api/trail` er ikke delt).

### 2. Sandkassen bryter ut via `open.__globals__` og sier likevel «clean»
`tests/attack2/test_attack_sandbox_escape.py`

Sperrene er Python-funksjoner i samme prosess som tillegget. Tre linjer i et
tillegg - `open.__globals__["_REAL_BUILTINS_OPEN"]("/etc/passwd").read()` - leser
en vilkaarlig fil utenfor boksen, og rapporten sier `clean`. Samme vei naar
hendelsesfilen, saa tillegget kan skrive falske hendelser inn i rapporten om seg
selv. Dette er ærlig dokumentert i `sandbox/LIMITS.md` («en bom, ikke en vegg»),
men runde en kjoerte det aldri. Det er **trivielt** for et tillegg som vil.
**Fiks:** ekte OS-isolasjon (container/VM/seccomp) - det kan ikke lukkes saa lenge
tillegget kjoerer i samme Python-prosess.

### 3. Kjeding: loegn + oppdeling tapper en konto uten ett roedt kort
`tests/attack2/test_attack_chain_endtoend.py`

`recipient_known=True` (H14) fjerner `unknown_recipient` paa en ukjent konto, og
fordi `normalize_recipient()` bare fjerner mellomrom, teller `NO93 8601 1117 947`,
`NO93.8601.1117.947` og `NO93-8601-1117-947` som tre ulike mottakere (H6). Tre
betalinger paa 49 000 kr, hver under grensen, hver `allow`: 147 000 kr til én
faktisk konto, ingen summering, ingen roedt kort. Samme med tilbakedatert `ts`
(H7): fem betalinger utenfor hverandres tidsvindu, 245 000 kr. Krever at den som
kaller eier `recipient_known`/`ts` - altsaa `gateway.evaluate()`-grensesnittet
eller agentens verktoeylag, ikke HTTP-skjemaet (der regnes `recipient_known` ut).
**Fiks:** normaliser bort alt som ikke er bokstav/siffer, summer paa mottakstid,
og slaa mottakeren opp i et kontoregister i stedet for aa tro paa feltet.

### 4. Full utsletting av loggen ser ut som en tom logg (staar igjen)
`tests/attack2/test_attack_vault_chain_anchor.py`

Hale-ankeret fanger en kuttet hale - men bare saa lenge ankeret staar. Sletter
angriperen baade loggfilen OG `.head`-ankeret, ser en fersk leser bare
`ok_empty`: «Loggen er tom.» En full utsletting er ikke til aa skille fra en logg
som aldri ble skrevet. Ankeret tvinger angriperen til aa fjerne to filer i stedet
for én, og det er alt (LIMITS#1). **Krever skrivetilgang til loggmappen.**
**Fiks:** siste hash notert UTENFOR maskinen - det eneste som faktisk lukker det.

### 5. Med noekkelen kan hele loggen skrives om eller byttes
`tests/attack2/test_attack_vault_chain_anchor.py`

Ankerets signeringsnoekkel er avledet fra loggnoekkelen (HKDF). Den som kan
dekryptere loggen kan derfor ogsaa signere et nytt anker: skrive om de to siste
linjene med riktig hash-kjede, eller legge inn en HELT annen gyldig kjede med
andre beloep og mottakere. `verify()` svarer «ok», og det er «riktig» svar paa
alt den kan se. En hash-kjede beviser at ingen linje er endret etterpaa, ikke at
innholdet er ekte (LIMITS#1/11/12). **Krever noekkelen** - det bevisste
kompromisset for én delt noekkel. **Fiks:** to noekler i to hender, og et anker
utenfor maskinen.

---

## Alle 15 hull

«Dok.» = staar alt i en `LIMITS.md` eller i `docs/ANGREP.md`; her gjort kjoerbart.
«Ny» = ikke beskrevet noe sted foer.

| id | Omraade | Alvor | Kilde | Hva slipper gjennom | Fiks |
|---|---|---|---|---|---|
| A1 | state-lekkasje | **hoey** | **Ny** | **LUKKET (runde 3).** Var: /api/state viste full mottaker, full summary og regelnavn i klartekst, uautentisert | Gjort: to nivaaer, allowliste uten noekkel, samme maskering som loggen |
| A2 | sandbox | **kritisk**\* | Lukket for dette angrepet | `open.__globals__` leser fil utenfor boksen; rapporten sa `clean`. Naa: statisk sjekk avviser moensteret, og snare i globals skriver `guard_bypass` -> `blocked` | Ekte OS-isolasjon for resten |
| A3 | sandbox | **hoey**\* | Lukket | Tillegget forfalsket sin egen rapport via `_events`. Naa ligger hendelsesskriveren i en lukning; navnet peker paa en snare | Samme |
| A4 | kjeding | **kritisk** | Dok. (H14+H6) | Loegn + staving: 147 000 kr til én konto, 3x allow | Normaliser + kontoregister |
| A5 | kjeding | **hoey** | Dok. (H14+H7) | Loegn + tilbakedatert ts: 245 000 kr, 5x allow | Summer paa mottakstid |
| A6 | vault-kjede | **hoey** | Dok. (LIMITS#1) | Slett logg+anker -> «Loggen er tom» | Anker utenfor maskinen |
| A7 | vault-kjede | **kritisk**\*\* | Dok. (LIMITS#1/12) | Med noekkelen: skriv om hale + signer nytt anker | To noekler, eksternt anker |
| A8 | vault-kjede | **kritisk**\*\* | Dok. (LIMITS#1/12) | Med noekkelen: bytt inn en HELT annen gyldig kjede | Samme |
| A9 | vault-laas | middels | Dok. (LIMITS#6) | To Vault paa samme fil knekker kjeden (verify ser det, hindrer det ikke) | Transaksjon / Vault tar laasen selv |
| A10 | last | middels | **Ny** | **LUKKET (runde 3).** Var: ingen grense paa kroppsstoerrelse; MB-store kropper bufres og aksepteres | Gjort: 64 KB (`MAX_BODY_BYTES`), ren ASGI-middleware som ogsaa teller byte naar `Content-Length` mangler eller juger |
| A11 | last | middels | **Ny** | **LUKKET (runde 3).** Var: ingen grense paa antall kort; uautentisert /api/custom fylte minne og logg | Gjort: 200 aktive kort (`MAX_CARDS`, nekter - kaster aldri et gammelt kort), 30/min per agentnoekkel, og /api/custom krever noekkelen |
| A12 | reset | middels | Dok. (H4/LIMITS#10) | **LUKKET (runde 3).** Var: /api/reset uautentisert; spolte historien og toemte koeen | Gjort: menneskenoekkelen foran alle skrivende ruter. Agentnoekkelen avvises paa alle |
| A13 | minimering | lav | Dok. (LIMITS#7) | Fellens `what_happened` maskeres aldri; kan baere e-post/konto i klartekst | Vask fri tekst / maskér moenstre |
| A14 | minimering | lav | Dok. (LIMITS#7) | Sandkassens `notes` har adressen i klartekst selv om `destinations` er maskert | Samme |
| A15 | pseudonym | lav | Dok. (LIMITS#5) | 4 hex = 16 bit: to ansatte faar samme kode (kollisjon) | Flere tegn / entydig tabell |

**Etter runde tre:** A1, A10, A11 og A12 er lukket. **9 staar igjen**: A2, A3
(sandkassen), A4, A5 (kjeding paa bryterne agenten setter selv), A6, A7, A8
(vault-kjeden, krever et anker eller en noekkel utenfor maskinen), A9 (laasen) og
A13, A14, A15 (minimering og pseudonymkollisjoner). Ingen av dem ligger i `ui/`.

\* Alvor gjelder en ekte sandkasse. I denne demoen sier `sandbox/LIMITS.md` hoeyt
at dette ikke er isolasjon, saa det er et ærlig forbehold, ikke en skjult feil.
\*\* Forutsetter at angriperen har loggnoekkelen. Da er alt tapt uansett; dette
er den bevisste prisen for én delt noekkel.

---

## Hva som HOLDER - og hvorfor det er verdt aa si

**Noekkelhaandteringen svikter lukket** (`test_attack_vault_keys.py`, 12 tester).
Manglende, tom, bare-mellomrom, for kort og ugyldig Fernet-noekkel avvises alltid
med `VaultKeyError`. En pseudonym-noekkel paa under 16 tegn avvises; noeyaktig 16
godtas. Og det viktigste: en feil, men gyldig, noekkel leser INGEN linjer og
svarer aldri `verify() == None` - en gal noekkel gir aldri en stille klarering.

**Pseudonymet kan ikke reverseres uten noekkelen**
(`test_attack_vault_pseudonym.py`). 2 000 egne noekkelgjetninger treffer ikke den
ekte koden til en kjent ansatt-id, fordi det er en HMAC og ikke en hash av bare
id-en. `reveal()` avviser enhver rolle som ikke er noeyaktig `"admin"`. Det
gjenstaaende hullet er kollisjoner (A15), ikke reversering.

**Kjeden fanger alt annet enn full utsletting og noekkel-forfalskning**
(`test_attack_vault_chain_anchor.py`). En endret linje midt i loggen peker
verify() ut noeyaktig; en kuttet hale med anker gir `log_truncated`.

**Kapploep gir aldri to utfall** (`test_attack_race.py`, 3 tester). 20 samtidige
godkjenn/avvis mot samme kort gir noeyaktig ett utfall; 12 samtidige
godkjenninger skriver bare én menneske-linje; 25 samtidige agent-submits faar
unike id-er. RLock-en rundt respond() og submit holder, og kjeden forblir hel.

**Noeklene laekker ikke inn i sandkassen** (`test_attack_sandbox_escape.py`).
Miljoeet bygges fra null: ingen `LONEWATCH_*` i delprosessen. `import vault`,
`import gateway` og `import contracts` naar ikke fram. Naive filskriv utenfor
boksen, prosess-spawn og et tillegg som henger stoppes alle. Utbruddet (A2) er
det eneste som kommer forbi - og det krever at tillegget vet om `__globals__`.

**Lese-rutene roerer ikke loggen og laekker ingen noekkel**
(`test_attack_routes.py`). Sju GET-ruter endrer ikke linjeantallet, og ingen av
dem inneholder et noekkelnavn med verdi. `/api/reset` ARKIVERER (den gamle loggen
beholdes under nytt navn, med innhold) - den sletter ingenting i det skjulte. Det
som gjenstaar er at reset er uautentisert (A12).

---

## Hva jeg IKKE rakk aa teste

Like viktig som funnene. Alt under er **uproevd denne runden** - ikke «trygt».

- **Minnebruk (RLIMIT_AS).** `sandbox/LIMITS.md` sier at minne ikke begrenses paa
  macOS. Jeg kjoerte ingen minnebombe (med vilje - den kunne tatt ned maskinen).
- **Ekte samtidige prosesser mot sandkassen.** Jeg testet traader i samme
  prosess, ikke to kjoerende Lonewatch som konkurrerer forbi flock-laasen.
- **Nettverksdisk (NFS/SMB).** `flock` er upaalitelig der; jeg testet bare lokal
  disk.
- **Den ekte agenten / MCP (`agent_gateway/`).** Broen finnes naa i denne grenen
  (den gjorde ikke det i runde en), men jeg angrep den ikke ut over
  noekkel-/loopback-porten paa `/api/agent/*`. `agent_gateway/`-tjeneren selv,
  MCP-verktoeyene og `executor/` er uproevd.
- **Ekte nettleser.** Alt over HTTP ble gjort fra skript. A1 (state-lekkasjen) er
  lest fra JSON-svaret, ikke observert i en fane. *Runde tre maalte til gjengjeld
  siden i Chromium (Playwright) paa 1440x900 og 1920x1080, baade laast og
  opplaast: ingen vannrett rulling, null forespoersler ut av maskinen, ingen
  konsollfeil. Det er ikke det samme som et angrep fra en fane.*
- **Dype kjoeringer av kroppsgrensen (A10).** Jeg sendte 3 MB i prosess; jeg
  proevde ikke gigabyte over socket, og maalte ikke naar appen faktisk faller.
  *Runde tre satte grensen og maalte den baade med `Content-Length` og med
  `Transfer-Encoding: chunked` over en ekte socket - men fortsatt ikke
  gigabyte, og fortsatt ikke hvor appen knekker.*
- **`vault.tamper_demo` og `vault.after`.** Jeg angrep kjeden rett, ikke
  demo-verktoeyene rundt den. *Runde tre angrep `/api/tamper`-ruten
  (`tests/attack2/test_attack_tamper_route.py`): kroppen kan ikke peke demoen
  paa en annen fil eller sende inn sin egen noekkel, den ekte loggen staar
  uendret etter alle fire angrepene, og svaret laekker ingen noekkel. `vault.after`
  er fortsatt uproevd.*
- **Fartsgrense paa menneskerutene.** Runde tre satte en fartsgrense paa
  `/api/agent/submit`, ikke paa `/api/respond` eller de andre menneskerutene.
  Det finnes ingen forsoeksgrense der, og et mislykket forsoek logges ikke.
- **`GET /api/trail/{id}`.** Den er IKKE delt i to nivaaer som `/api/state`: den
  svarer fra minnet uten menneskenoekkel. Den gir «hva samme agent gjorde rett
  foer» for en id man alt kjenner, og den gaar gjennom samme `_public()`-kort -
  men den er ikke minimert, og den ble ikke angrepet paa nytt i runde tre.
- **Om A2-utbruddet kan re-aapne nettet.** Via `__globals__` naar man ogsaa
  `_REAL_IMPORT`; jeg bekreftet fil-lesing og hendelse-forfalskning, men bygget
  ikke en full nettverks-reaktivering (den ville kunne sende ekte trafikk hvis
  den lyktes).

---

## Om de 6 roede i `tests/attack/` (historisk)

Da runde to ble skrevet mot `samlet2`, viste hele suiten 6 failed i `tests/attack/`.
De var ikke fra runde to. Etter sammenslaaingen (`samlet3`) er alle rettet i
`herd-gw` og `herd-ui`, og hele suiten er groenn: `1364 passed, 47 xfailed`.
`tests/attack2/` kjoerer for seg med `51 passed, 13 xfailed`.

## Runde 5: oversiktssiden (F2)

Ny visning (`/api/overview`) ga én lekkasje, og live-siden for agenten hadde en feil. Begge ble funnet
og lukket før levering.

| | funn | status |
|---|---|---|
| F2-1 | `GET /api/overview` uten nøkkel viste mottaker i klartekst, regelnavn og konsekvenstekst | **LUKKET.** `minimized_overview()` gir bare tellere, status og maskert mottaker uten menneskenøkkel. Testet i `tests/test_overview_locked.py` (11 tester) |
| F2-2 | Live-siden for agenten hentet `/api/state` uten menneskenøkkelen og fikk det minimerte svaret. En side som var låst opp falt tilbake til «Låst side» hvert andre sekund | **LUKKET.** Bruker nå samme hjelpefunksjon som resten av appen, som sender nøkkelen. Det var en feil, ikke en lekkasje |

Sjekket for hånd mot et kjørende UI: uten nøkkel og med agentnøkkel gir alle seks skriveruter 403, og uten
nøkkel finnes verken kontonummer, regelnavn, dokument-id eller konsekvenstekst i svaret.

Åpne, kjente feil: `GET /api/trail/{id}` er fortsatt ikke delt i to nivåer (se over). Én test feiler i
Python 3.13 (H28, `RecursionError` på dypt nøstet JSON). Menneskenøkkelen ligger fortsatt på maskinen.

