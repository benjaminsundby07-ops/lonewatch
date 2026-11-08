# Hva sandkassen IKKE klarer

Ærlig liste over hva `sandbox/` ikke er. Ta den med i pitchen, for den viktigste
setningen her er den første.

## Dette er ikke ekte isolasjon

Sandkassen er en egen Python-**delprosess** med sperrer satt opp inne i selve
prosessen: `socket` er byttet ut, `open` er byttet ut, `HOME` peker på en falsk
mappe. Det er ikke en container, ikke en virtuell maskin og ikke seccomp. Det
finnes ingen vegg i operativsystemet rundt tillegget - bare funksjoner vi har
byttet ut i den samme Python-en som tillegget kjører i.

Et tillegg som kjører i samme prosess som sperrene sine, kan i prinsippet alltid
komme rundt dem. Det er ikke en feil vi har glemt å fikse. Det er en egenskap
ved å gjøre det på denne måten.

## Sperrene kan brytes fra innsiden (fortsatt uløst i prinsippet)

Sperrene er vanlige Python-funksjoner, og en Python-funksjon bærer med seg
globals-ordboken sin. Der lå de ekte funksjonene vi tok vare på. To linjer var
nok:

```python
ekte_open = open.__globals__["_REAL_BUILTINS_OPEN"]
ekte_open("/etc/passwd").read()      # leste den ekte filen
```

Vi prøvde dette mot vår egen sandkasse, og det virket - og rapporten sa
`clean` mens det skjedde. Det siste var det verste: boksen så ingenting.

**Hva vi gjorde med det (runde 3).** Tre ting, og ingen av dem er ekte
isolasjon:

1. **En statisk sjekk før kjøring** (`sandbox/static_check.py`). Kilden leses
   som et AST, og kjente rømningsmønstre avvises FØR noe kjøres: dunder-
   attributter (`__globals__`, `__builtins__`, `__subclasses__`, `__class__`,
   `__mro__`, `__code__`, `__closure__`, `__dict__`, rammer og sporinger),
   `eval`, `exec`, `compile`, `__import__`, `getattr`/`setattr`/`delattr` med
   et navn, en streng som nevner et sperret attributt, og skriving til et
   attributt på en modul som holder en sperre (`builtins.open = ...`). Et
   tillegg som avvises blir `blocked`, og det startes ingen delprosess.
   `open` står MED VILJE på den tillatte listen: hele poenget med boksen er å
   se et tillegg lese agnfilene.
2. **Sperrene er lukninger, og globals-ordboken er tømt.** Hver sperre holder
   de ekte funksjonene i sine egne celler. Etter at sperrene er satt opp byttes
   alt farlig i harness-ets globale ordbok ut med **snarer**: objekter som
   skriver ned at noen strakk seg etter dem (`guard_bypass`) og nekter. Et
   tillegg som likevel finner veien til ordboken får altså ikke de ekte
   funksjonene, og forsøket står i rapporten.
3. **`clean` krever et bevis.** Etter at tillegget er ferdig sjekker harness-et
   at sperrene fortsatt står der de ble satt (`builtins.open`,
   `builtins.__import__`, `os.open`, `socket.socket`, `sys.meta_path`) og
   skriver `guards_intact`. Mangler den hendelsen, sier rapporten `not_tested`
   og ikke `clean`. Står en sperre ikke igjen, blir det `guard_tampered` og
   `blocked`.

**Hva dette IKKE er.** Det er en bom og en snare, ikke en vegg:

- Den statiske sjekken avviser **mønstre vi kjenner**. En streng satt sammen
  under kjøringen går gjennom. `operator.attrgetter("__glob" + "als__")` er
  ikke avvist av sjekken - der er det snaren som fanger forsøket, og snaren
  *ser* det, den *stopper* det ikke på noe dypere nivå enn at den nekter.
  Base64, rot13, et navn lest fra en fil: samme sak.
- `open.__closure__` er fortsatt en vei til de ekte funksjonene. Den er bare
  avvist statisk, altså av punkt 1, som punkt over sier er omgåelig.
- **Python-sandboxing i samme prosess kan ikke gjøres sikker.** Det er ikke en
  mangel i koden vår; det er en egenskap ved språket. Alt vi har gjort her er å
  flytte terskelen og å gjøre forsøkene synlige.

**Hva en ekte løsning er.** Prosessisolasjon: en container med `seccomp` eller
`landlock`, en gVisor/Firecracker-sandkasse, eller en etablert sandkasse som
`nsjail`/`bubblewrap`. Vi har bevisst valgt å ikke bygge en ekte sandkasse i
dette prosjektet - vi vil integrere en etablert en senere. Det som står her er
simuleringen gjort tettere og ærligere, ikke en sandkasse som holder.

Angrepene og grensene er kjørbare i
`tests/attack2/test_attack_sandbox_escape.py`, inkludert testen som viser
nøyaktig hvor den statiske sjekken slipper noe gjennom.

### Omveiene vi faktisk fant og stengte

Alle disse virket første gang vi prøvde dem mot vår egen sandkasse, og nummer 5
fikk en **ekte tilkobling ut på internett** mens vi trodde nettverket var
sperret:

1. `ctypes.CDLL(None).socket(...)` - kaller rett på operativsystemet og går rundt
   alt vi gjør i Python. Nå sperret ved import.
2. `import posix; posix.open(...)` - `os.open` ER `posix.open`. Vi hadde bare
   byttet navnet i `os`.
3. `import _io; _io.FileIO(...)` - `io` er bare et skall rundt C-modulen `_io`.
4. `import _io; _io.open(...)` - samme sak.
5. `del sys.modules["_socket"]; import _socket` - ga en fersk, usperret
   socket-modul.

De fire første står som tester i `tests/test_sandbox.py` under "kjente omveier".
Nummer 5 testes mot en ekte lytter på localhost i
`test_naar_aldri_det_ekte_nettverket`, sammen med fire andre måter å nå nettet
på - ingen test i prosjektet peker ut på internett, nettopp fordi en test som
gjorde det, ville sendt ekte trafikk hvis sperren falt ut.

At vi fant fem omveier på første forsøk er det sterkeste argumentet for at det
finnes flere vi ikke har funnet.

## Tillegget kan se at miljøet er falskt

Vi prøver ikke å skjule at dette er en sandkasse, og et tillegg som vil, ser det
med en gang:

- hjemmemappen heter noe med `lonewatch-boks-` og ligger i tmp
- den inneholder ni filer, og flere av dem sier `FALSK DEMOFIL` i første linje
- miljøet er nesten tomt: ingen `SHELL`, ingen `SSH_AUTH_SOCK`, `USER=demo`
- `socket.getaddrinfo` svarer aldri, uansett hva du spør om
- `import ctypes` feiler, noe som aldri skjer på en vanlig maskin

Et tillegg som er skrevet for å unngå sandkasser, oppfører seg altså pent hos
oss og stjeler først på en ekte maskin. Da sier rapporten `clean`, og vi tar
feil. Dette er den vanligste måten ekte skadevare slipper unna ekte sandkasser,
og vi har ingen forsvar mot det.

## Demoen er snillere mot oss enn virkeligheten

I hovedscenarioet ber fella agenten installere `nordlys-mail-connector-patch`,
og sandkassen har tilfeldigvis akkurat den filen liggende i `sandbox/packages/`.
Det er fordi vi har skrevet begge deler selv. I virkeligheten ville ikke
Lonewatch hatt tillegget på forhånd: det måtte vært hentet fra den kilden
angriperen peker på før det kunne kjøres, og det gjør vi ikke og vil ikke gjøre.
`scan()` kjører bare filer som ligger i `sandbox/packages/` fra før, nettopp
fordi et navn fra en forespørsel aldri skal kunne føre til at noe lastes ned
eller kjøres.

Konsekvensen er at demoens "Før"-steg viser det beste tilfellet: tillegget vi
allerede kjente. For et ekte, ukjent tillegg er svaret "ikke testet", og da står
`new_package`-regelen alene - akkurat som før sandkassen fantes.

**Hva som ville løst det:** en kjede der pakken hentes ned i et isolert miljø og
skannes der, med alt det medfører av tillit til kilden, nettverk og
versjonskontroll. Det er et helt annet system enn dette.

## Vi ser bare ett kort øyeblikk

Tillegget kjøres én gang, i noen sekunder, og `run()` kalles én gang. Vi fanger
derfor ikke:

- et tillegg som er pent de første 100 gangene og stjeler den 101.
- et tillegg som venter til en bestemt dato, eller til det er natt
- et tillegg som bare gjør noe når en ekte agent kaller en bestemt funksjon
- noe som helst som skjer ved *installasjon* (`pip install`, `setup.py`), for vi
  installerer ingenting - vi kjører bare filen
- nye versjoner. Vi skanner en gang. Versjon 1.4.1 kan være helt annerledes enn
  1.4.0, og vi ser den aldri igjen.

## Rapporten sier bare ja eller nei

`SandboxReport.verdict` er `clean`, `blocked` eller `not_tested`, og én enkelt
hendelse er nok til `blocked`. Det gir noen rare utfall:

- et tillegg som leser `~/.env` fordi det *skal* lese konfigurasjon, blir
  `blocked`. Vi kan ikke se forskjell på god og dårlig grunn.
- et tillegg som trenger nettverket for å gjøre jobben sin (hente en kurs, slå
  opp en adresse) kan aldri bli `clean`. Sandkassen har ingen tillatelsesliste.
- et tillegg som krasjer med en gang blir `not_tested`, ikke `clean`. Se neste
  avsnitt. "Clean" betyr "vi så etter og fant ingenting", og det skal bare stå
  når tillegget faktisk kjørte ferdig.
- `clean` krever i tillegg at harness-et BEKREFTET at sperrene sto igjen
  etterpå (`guards_intact`). Uten den bekreftelsen er svaret `not_tested`.
  Regelen er: alt vi ikke kan bevise, sier vi ikke `clean` om.
- et tillegg som avvises av den statiske sjekken blir `blocked` uten å ha blitt
  kjørt. Det er et funn på KILDEN, ikke på handlingen - rapporten sier det
  eksplisitt ("AVVIST FOER KJOERING"), slik at ingen tror vi så tillegget gjøre
  noe.

## Et tillegg som krasjer blir `not_tested`, ikke `clean`

Dette var lenge et uløst hull, og det er nå lukket.

`report.build_report()` setter `blocked` når tillegget gjorde noe vi ikke
tillater, eller når delprosessen ikke ble ferdig i tide. Et tillegg som
*starter, feiler og avslutter pent* har ikke gjort noe av delene — og før ble
svaret da `clean`. Det var feil: «clean» betyr «vi så etter og fant ingenting»,
og her fikk vi aldri sett etter.

Rapporten har nå tre utfall:

| verdict | betyr | eksempel |
|---|---|---|
| `blocked` | vi så noe vi ikke tillater | prøvde å nå nettet, leste et agn, hang |
| `clean` | vi så etter og fant ingenting | `pdf-helper`, `date-utils` |
| `not_tested` | vi fikk aldri sett etter | tillegget krasjet, eller mangler `run()` |

`not_tested` settes når hendelsene inneholder `plugin_error` eller
`no_entry_point` (`report.INCONCLUSIVE_EVENTS`). Notatet begynner med

> IKKE TESTET: sandkassen fikk ikke kjørt tillegget ferdig, så vi vet ikke hva
> det ville gjort. Dette er ikke det samme som at vi så etter og ikke fant noe.

Den gamle klareringen — «Ingen forsøk på nettverk, ingen lesing av de falske
hemmelighetene og ingenting utenfor boksen» — står nå **bare** når tillegget
faktisk kjørte ferdig. Det var den farligste varianten: setningen var sann,
men bare fordi ingenting ble kjørt, og den leste som en godkjenning.

### Rekkefølgen: et funn slår «ikke testet»

Prøver et tillegg å nå nettet og krasjer rett etterpå, blir svaret `blocked` —
ikke `not_tested`. Vi så noe, og det vi så var nok. `not_tested` er bare for
tilfellene der vi **ikke** så noe, fordi tillegget aldri kom i gang.

En **tidsgrense** er heller ikke `not_tested`. Et tillegg som henger har gjort
noe vi observerte: det nektet å gi seg. Det blir `blocked` som før.

### Hva det betyr videre

- **Mellomstasjonen** ser forskjellen. `sandbox_blocked` utløses bare av
  `blocked`; `not_tested` legger ingenting til. Men konsekvensteksten sier nå
  «Sandkassen fikk ikke testet tillegget: det kom aldri i gang», i stedet for
  «så ingenting mistenkelig». `new_package` gjelder uansett, så tillegget blir
  rødt.
- **«Før»-listen i UI** viser «ikke testet» som egen tilstand, og teller det
  ikke som `clean`. Dashbordets «{tested} testet» teller bare de vi faktisk
  fikk testet.
- **Gamle logger og `examples/`** leses fortsatt. Vi la til en verdi, vi
  fjernet ingen, så en linje med `clean` eller `blocked` validerer som før.

Dette krevde den eneste endringen som er gjort i `contracts.py`:
`verdict: Literal["clean", "blocked", "not_tested"]`.

### Hvorfor ikke bare gjøre krasj blokkerende

Da blir et tillegg med en helt vanlig bug behandlet som ondsinnet, og vi har
ingen måte å skille dem på. «Vi vet ikke» er et ærligere svar enn «nei».

Og hullet som gjenstår: **et tillegg kan krasje med vilje.** `if sandkasse():
raise` gir `not_tested` hos oss og vanlig oppførsel på en ekte maskin. Nå sier
rapporten i det minste at vi ikke vet — før sa den at alt så fint ut.
## Hva vi måler, og hva vi ikke måler

Vi måler hva tillegget *gjorde* - adresser det prøvde å nå, filer det leste.
Vi leser aldri koden i tillegget og vurderer den ikke. Det er med vilje, og det
følger regelen i CLAUDE.md om at ingen AI-modell bestemmer utfallet. Men det
betyr at et tillegg som er åpenbart ondsinnet å lese, men som ikke gjør noe
mens vi ser på, går gjennom.

## Tidsgrensen

Standard er 6 sekunder (`config.DEFAULT_TIMEOUT_S`), satt for å få en rask demo.
Tallet er en gjetning, ikke et resultat av måling. Et tungt, harmløst tillegg
kan bruke lengre tid og bli `blocked` fordi det er sent, ikke fordi det er
farlig. Vi har to grenser: klokka utenfor dreper prosessgruppen, og `RLIMIT_CPU`
inne i prosessen fanger en evig løkke. Minnebruk setter vi ingen grense på -
`RLIMIT_AS` er upålitelig på macOS, så et tillegg kan spise minne til maskinen
svetter.

## Mindre hull vi vet om

- **Hendelsesfilen kan bli halv.** Blir prosessen drept midt i et skriv, hopper
  vi over den siste linjen. Vi kan altså miste den siste hendelsen - for
  eksempel adressen tillegget prøvde helt på slutten.
- **`os.stat` er ikke sperret.** Et tillegg kan kartlegge hvilke filer som
  finnes utenfor boksen, selv om det ikke får lese dem. Vi skriver det ikke ned.
- **Trådere.** Et tillegg kan starte tråder. De dør når prosessen dør, men en
  tråd som starter rett før tidsgrensen kan gjøre noe vi ikke får skrevet ned.
- **`denied_import` fra standardbiblioteket teller ikke.** Vi skiller på hvem som
  importerte, basert på `__name__` i den som spør. Et tillegg som later som det
  er `uuid` (`globals()["__name__"] = "uuid"`) får importforsøkene sine regnet
  som ufarlige. Hullet er lite, fordi importen fortsatt blir avvist - men det
  blir ikke `blocked`.
- **Etter-listen skiller ikke bind fra connect.** `vault/after.py` lager
  oppgaven "Tillegget prøvde å sende data ut" av `attempted_network`, og det
  feltet er sant også for et tillegg som bare prøvde å *åpne en port*. Et slikt
  tillegg blir riktig blokkert og beskrevet riktig i `notes`, men overskriften
  på Etter-listen sier "sende ut" når det egentlig var "slippe inn".
  `SandboxReport` har ikke noe felt å skille dem på, og `contracts.py` er låst.
- **Den statiske sjekken tar også harmløs kode.** `getattr(x, "navn")`,
  `obj.__dict__` og `eval` er helt vanlig i ekte Python, og et tillegg som
  bruker dem blir `blocked` selv om det ikke prøvde noe. Vi har valgt den
  kostnaden med vilje: vi vil heller avvise et greit tillegg enn å si `clean`
  om et vi ikke forstår. Rapporten sier eksplisitt at det var kilden og ikke
  handlingen som ble avvist. De fem demotilleggene (også de tre som stjeler)
  har rene kilder, nettopp fordi de skal stoppes på HANDLING - ellers mister vi
  beviset for at nettsperren og agnfilene virker.
- **Den statiske sjekken ser ikke en streng satt sammen under kjøringen.**
  `"__glob" + "als__"` går gjennom. Da er det snaren i globals-ordboken som
  fanger forsøket. Se "Sperrene kan brytes fra innsiden" over.
- **Snarene er navngitt, ikke skjult.** De ligger under de samme navnene som
  før. Vi gjør ikke noe forsøk på å skjule hvor de ligger: et tillegg som leser
  ordboken vil se snarer. Det er greit - poenget er at forsøket blir SETT, ikke
  at det blir umulig.
- **Agnlisten er hardkodet.** Et tillegg som leser `~/.ssh/id_ed25519` i stedet
  for `id_rsa` treffer ikke et agn. Vi skriver det ned som vanlig fillesing, og
  rapporten blir `clean`.
- **Krever Python 3.11.** `import sandbox` stopper med en tydelig melding på
  eldre tolkere. Før gikk importen gjennom, og delprosessen døde først senere
  uten hendelser, slik at rapporten bare sa «Delprosessen stoppet før tillegget
  var ferdig» — altså `blocked` av feil grunn.
- **Rapporten er ikke signert.** `scan()` returnerer et vanlig objekt. Den som
  kaller mellomstasjonen kan finne på en `clean`-rapport selv, og gateway kan
  ikke se forskjell. Se `gateway/LIMITS.md`.
- **Vi skanner én gang per kjøring.** `scan_cached()` husker resultatet per
  pakkenavn så lenge prosessen lever, slik at demoen ikke starter en ny
  delprosess for hvert kort. Det betyr at to forespørsler om det samme tillegget
  deler ett resultat og én linje i loggen - også hvis tillegget hadde oppført
  seg annerledes andre gangen. Det gjør det synlige hullet i "Vi ser bare ett
  kort øyeblikk" over enda litt større.

## Hva som måtte til for at dette var ekte

En sandkasse man kan stole på, kjører tillegget bak en vegg i
operativsystemet, ikke bak funksjoner i samme prosess:

- egen container eller virtuell maskin, uten nettverkskort i det hele tatt
- `seccomp` (Linux) eller `sandbox-exec` (macOS), så syscall-ene er borte, ikke
  bare Python-navnene
- egen bruker uten tilgang til noe, og et filsystem som bare finnes for
  skanningen
- flere kjøringer over tid, og på nytt for hver versjon av tillegget

Det vi har bygget, er en god **detektor for et tillegg som ikke prøver å skjule
seg** - og det er faktisk de fleste. Det er ikke en **vegg**, og rapporten skal
leses som "her er hva vi så", aldri som "dette er trygt å slippe inn".
