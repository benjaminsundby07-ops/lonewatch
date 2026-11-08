# Hva nettsiden og menneskenøkkelen IKKE klarer

`ui/` er nettsiden og tilstanden bak den. Den eier ingen regler. Men siden
denne runden eier den to ting som betyr noe: **menneskenøkkelen** (hvem som får
godkjenne et rødt kort) og **koblingen til utføreren** (at en godkjenning
faktisk fører til at noe skjer). Her står hullene i begge, slik at ingen tror
noe annet.

Den ikke-tekniske versjonen av utføreren står i `docs/UTFORER.md`. Angrepene
som ble kjørt mot dette står i `docs/ANGREP.md`.

---

## 1. Menneskenøkkelen er en streng på maskinen, ikke en BankID

`LONEWATCH_HUMAN_KEY` ligger i klartekst to steder:

* i miljøet til terminalen som kjører appen
* i filen `.lonewatch-agent-env` (`chmod 600`, i `.gitignore`)

**En agent med fri tilgang til maskinen kan lese begge.** Claude Code har Bash
og filtilgang; `cat .lonewatch-agent-env` er ett kall. Da kan den godkjenne sitt
eget røde kort, og loggen vil si at et menneske gjorde det.

Nøkkelen gjør hullet smalere, og det er verdt noe:

| Før | Nå |
|---|---|
| Ett `curl` mot `/api/respond` godkjente 10 000 000 kr | Samme kall svarer 403 |
| Agentnøkkelen (som står i `.mcp.json`, en fil agenten selv leser) var nok | Agentnøkkelen avvises med 403 |
| En nettside operatøren besøkte ble avvist ved et uhell (kroppsformat) | Avvises fordi et egendefinert hode krever CORS-forhåndssjekk appen ikke svarer på |

Men den lukker det ikke. **Produksjonsversjonen må kreve noe som ikke finnes på
maskinen i det hele tatt:** en egen enhet eller en egen konto, slik BankID er -
en kode som kommer fra noe agenten ikke kan lese, og som er knyttet til en
person og ikke til en fil. Det er forskjellen mellom «agenten må lete» og
«agenten kan ikke».

Testen `test_aerlig_hull_menneskenoekkelen_ligger_paa_maskinen` i
`tests/test_agent_mcp_live.py` pinner dette med vilje: den gjør nøyaktig det en
agent med Bash ville gjort, og den SKAL bestå.

## 2. Loggen vet hvilken nøkkel som godkjente, ikke hvilken person

`employee_pseudonym` regnes ut av nøkkelen som kom inn
(`ui/human_key.py::operator_id` → `vault.pseudonymize`), ikke av en fast
konstant og ikke av et navn den som kaller skriver selv. To ulike nøkler gir to
ulike `emp_xxxx`.

Det betyr:

* **Én nøkkel per person** gir en logg som kan svare på hvem. Det er sånn
  `LONEWATCH_HUMAN_KEY` er ment brukt: flere nøkler skilt med komma.
* **Én delt nøkkel** - som i demoen, og som i oppsettet
  `python -m agent_gateway.oppsett` lager - gir én `emp_xxxx` for alle som har
  den. Da vet loggen **hva** som ble godkjent, men ikke **hvem** som gjorde det.
  Deler to mennesker en nøkkel, kan loggen ikke skille dem.

Det finnes ingen utløpstid, ingen rotasjon, ingen sperre etter mange feil
forsøk, og ingen måte å trekke tilbake én nøkkel uten å starte appen på nytt.

## 3. Nøkkelen ligger i nettleserens `sessionStorage`

Valget sto mellom to:

| | `sessionStorage` + eget HTTP-hode (valgt) | httpOnly-informasjonskapsel |
|---|---|---|
| CSRF | Umulig: en fremmed side kan ikke sette et egendefinert hode uten en CORS-forhåndssjekk appen ikke svarer på | Mulig: kapselen sendes automatisk. Måtte hatt et CSRF-token i tillegg |
| Lesbar for JS på siden | **Ja** | Nei |
| Overlever at fanen lukkes | Nei (med vilje: ingen blir stående innlogget på en projektor) | Ja, til den utløper |

Vi valgte det første fordi CSRF er den angrepsveien som ikke krever at noen
alt kjører kode på maskinen din - og fordi en kapsel ville krevd et CSRF-token
vi da måtte bygget og testet.

**Hva det ikke løser:** kjører det fremmed JavaScript på siden, kan det lese
nøkkelen ut av `sessionStorage`. Siden henter ingenting utenfra (ingen CDN,
ingen skrifter fra nettet, ingen sporing), og alt brukeren skriver escapes før
det vises - men det er et forsvar mot XSS, ikke en garanti.

Nøkkelen står aldri i en statisk fil nettleseren laster ned, aldri i en URL, og
aldri i et svar fra tjeneren.

## 4. Bare `/api/respond` er låst

| Rute | Låst? |
|---|---|
| `POST /api/respond` | **ja**, menneskenøkkel |
| `POST /api/human/check` | ja, samme nøkkel (den gjør ingenting annet enn å svare om nøkkelen holdt) |
| `POST /api/agent/*` | ja, men med AGENTnøkkelen, og bare fra 127.0.0.1 |
| `POST /api/custom`, `/api/feed/step`, `/api/story/*`, `/api/reset` | **nei** |

`/api/reset` er H4 i `docs/ANGREP.md` og er fortsatt åpen: ett kall arkiverer
loggen og tømmer køen. Det er Nullstill-knappen den som holder demoen bruker, og
en lås der ville stengt demoen uten å stoppe en godkjenning.

`/api/custom` og `/api/feed/step` kan ikke godkjenne noe. Men siden utføreren nå
er koblet inn, betyr en `allow` at noe **faktisk skjer**: med
`LONEWATCH_EXECUTOR=smtp` kan et uautentisert lokalt kall utløse en ekte e-post
til én av demoens tolv kjente (oppdiktede) mottakere. Alt annet enn de tolv blir
`unknown_recipient` → rødt → krever menneskenøkkelen. Begge er pinnet som
`xfail(strict=True)` i `tests/attack/test_attack_self_approval.py`.

## 5. Feiler lukket - og det merkes

Er `LONEWATCH_HUMAN_KEY` ikke satt, svarer `/api/respond` **503**, og ingenting
kan godkjennes. Det samme skjer hvis noen setter menneskenøkkelen til samme
verdi som agentnøkkelen: da er skillet borte, og vi svarer nei til alle i
stedet for ja til agenten.

Prisen er at demoen ikke virker uten oppsettet. Det er med vilje: en port som
åpner seg når oppsettet mangler er ingen port.

## 6. Betenkningstiden er ekte, men den måler skjermtid - ikke oppmerksomhet

`seconds_to_decide` måles av tjeneren, fra kortet ble lagt i køen til svaret
kom, med `time.monotonic()`. Den kan ikke oppgis av klienten lenger (et forsøk
gir 422).

Det den IKKE sier: at noen så på kortet. Et kort som sto i køen i to timer mens
operatøren var på lunsj får 7200 sekunder. Tallet er en nedre grense for hvor
lenge saken var tilgjengelig, ikke et mål på hvor lenge noen tenkte.

## 7. Forseglingen stopper en agent, ikke noen som kjører kode i appen

`Approval.request_fingerprint` er en SHA-256 uten nøkkel. Den ligger på kortet
inne i `DemoState` og sendes **aldri** til nettleseren - `_public()` tar den
bort, og `tests/test_executor_wiring.py` går gjennom hele API-flaten og sjekker
det.

Den stopper at en forespørsel endres mellom avgjørelsen og godkjenningen. Den
stopper ikke noen som kan kjøre kode i samme prosess: de kan lage en `Approval`
med det avtrykket de vil. Se `executor/LIMITS.md` punkt 3.

## 8. Utføreren er koblet inn to steder, og bare to

`allow` utføres i `_handle()`, og en godkjent `red` i `respond()`. En rød sak
som venter, en avvist sak og en blokkert sak kommer aldri til utføreren -
porten i `executor/gate.py` ville nektet dem uansett, men vi kaller den heller
ikke.

Standard er `SimulatedExecutor`, som gjør ingenting. `SmtpExecutor` må slås på
med `LONEWATCH_EXECUTOR=smtp`, og sender bare til loopback med mindre
`LONEWATCH_SMTP_ALLOW_REMOTE=1` er satt med vilje. Resten av hullene i
sendingen står i `executor/LIMITS.md`.

`run_demo.py` er IKKE koblet til utføreren. Den er en ren regel- og
loggdemonstrasjon i terminalen, og den skriver fortsatt 88 linjer.

## 9. «Oversikt», «Godkjenning» og «Etter» kan bli høyere enn skjermen

Målt i nettleseren på 1440×900 og 1920×1080: **ingen vannrett rulling noe
sted**. Loddrett er Før og Prøv selv innenfor på 1920×1080; Oversikt,
Godkjenning og Etter blir høyere enn skjermen når demoen har kjørt en stund.

Det er innholdet som vokser - detaljpanelet på et kort, logg-tabellen på Etter -
ikke en ramme som er for stor. Menneskenøkkel-stripen på Godkjenning koster
71-92 px av det, og resten var der før den.
