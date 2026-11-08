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
pytest tests/attack2/     # 51 passed, 13 xfailed (etter sammenslaaing med herd-gw og herd-ui)
pytest -q                 # 1364 passed, 47 xfailed (hele suiten)
```

Alt kjoerte lokalt mot simuleringen, paa `127.0.0.1` med ferske engangsnoekler og
loggfil i tmp (`tests/conftest.py` + en ekstra sperre i
`tests/attack2/conftest.py` som nekter aa kjoere hvis loggstien ikke er tmp).
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
| 6 | **sandbox: r0emning** | **DELVIS** | Noekler laekker ikke inn, import av vault/gateway er sperret, naive filskriv stoppes, nettet er sperret, tidsgrensen virker. Men `open.__globals__` bryter ut og leser filer utenfor boksen - og rapporten sier `clean`. |
| 7 | **kapploep** | **HOLDER** | RLock serialiserer respond() og submit. Et kort faar noeyaktig ett utfall, samtidige submits faar unike id-er, kjeden forblir hel. |
| 8 | **last / tjenestenekt** | **DELVIS** | Feltgrenser og dyp JSON haandteres uten krasj. Men ingen grense paa kroppsstoerrelse og ingen grense paa antall kort, mot et uautentisert endepunkt. |
| 9 | **de oevrige rutene** | **DELVIS** | Lese-ruter endrer ikke loggen og laekker ingen noekkel. /api/reset arkiverer (sletter ikke) - men er uautentisert (H4/LIMITS#10). |
| 10 | **kjeding ende-til-ende** | **LUKKET for staving og tilbakedatering** (herd-gw: H6, H7) | Rundet av runde 2 mot koden FOER rettelsene: H14 + H6 og H14 + H7 flyttet >100 000 kr til én konto uten ett roedt kort. Etter sammenslaaingen stoppes begge. H14 (loegn om `recipient_known`) og H9 (mange kontoer) staar igjen. |
| 11 | **informasjonslekkasje** | **HULL (nytt)** | /api/state er uautentisert og viser full mottaker, full summary og de interne regelnavnene i klartekst - akkurat det loggen minimerer bort. |

**15 hull ved runden, 13 aapne etter sammenslaaingen** (13 `xfail(strict=True)`; kjedehullene H6/H7 er lukket av `herd-gw`). Tre er helt nye (staar ikke i
`docs/ANGREP.md` og ikke i noen `LIMITS.md`): ingen kroppsgrense, ingen
kortgrense, og at `/api/state` laekker raa persondata og regelnavn. Resten er
forbehold prosjektet selv har skrevet ned i `vault/LIMITS.md` og
`sandbox/LIMITS.md` - her er de maalt og gjort kjoerbare for foerste gang, eller
satt sammen til et angrep ende-til-ende.

---

## De fem alvorligste

### 1. `/api/state` laekker raa persondata og regelnavn (nytt)
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

### 4. Full utsletting av loggen ser ut som en tom logg
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
| A1 | state-lekkasje | **hoey** | **Ny** | /api/state viser full mottaker, full summary og regelnavn i klartekst, uautentisert | Autentiser, eller send ut det minimerte synet |
| A2 | sandbox | **kritisk**\* | Dok. | `open.__globals__` leser fil utenfor boksen; rapporten sier `clean` | Ekte OS-isolasjon |
| A3 | sandbox | **hoey**\* | Dok. | Samme vei naar hendelsesfilen: tillegget forfalsker sin egen rapport | Samme |
| A4 | kjeding | **kritisk** | Dok. (H14+H6) | Loegn + staving: 147 000 kr til én konto, 3x allow | Normaliser + kontoregister |
| A5 | kjeding | **hoey** | Dok. (H14+H7) | Loegn + tilbakedatert ts: 245 000 kr, 5x allow | Summer paa mottakstid |
| A6 | vault-kjede | **hoey** | Dok. (LIMITS#1) | Slett logg+anker -> «Loggen er tom» | Anker utenfor maskinen |
| A7 | vault-kjede | **kritisk**\*\* | Dok. (LIMITS#1/12) | Med noekkelen: skriv om hale + signer nytt anker | To noekler, eksternt anker |
| A8 | vault-kjede | **kritisk**\*\* | Dok. (LIMITS#1/12) | Med noekkelen: bytt inn en HELT annen gyldig kjede | Samme |
| A9 | vault-laas | middels | Dok. (LIMITS#6) | To Vault paa samme fil knekker kjeden (verify ser det, hindrer det ikke) | Transaksjon / Vault tar laasen selv |
| A10 | last | middels | **Ny** | Ingen grense paa kroppsstoerrelse; MB-store kropper bufres og aksepteres | Max-body-size foran appen |
| A11 | last | middels | **Ny** | Ingen grense paa antall kort; uautentisert /api/custom fyller minne og logg | Tak paa aktive kort + rate |
| A12 | reset | middels | Dok. (H4/LIMITS#10) | /api/reset er uautentisert; spoler historien og toemmer koeen | Innlogging foran skrivende ruter |
| A13 | minimering | lav | Dok. (LIMITS#7) | Fellens `what_happened` maskeres aldri; kan baere e-post/konto i klartekst | Vask fri tekst / maskér moenstre |
| A14 | minimering | lav | Dok. (LIMITS#7) | Sandkassens `notes` har adressen i klartekst selv om `destinations` er maskert | Samme |
| A15 | pseudonym | lav | Dok. (LIMITS#5) | 4 hex = 16 bit: to ansatte faar samme kode (kollisjon) | Flere tegn / entydig tabell |

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
  lest fra JSON-svaret, ikke observert i en fane.
- **Dype kjoeringer av kroppsgrensen (A10).** Jeg sendte 3 MB i prosess; jeg
  proevde ikke gigabyte over socket, og maalte ikke naar appen faktisk faller.
- **`vault.tamper_demo` og `vault.after`.** Jeg angrep kjeden rett, ikke
  demo-verktoeyene rundt den.
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
