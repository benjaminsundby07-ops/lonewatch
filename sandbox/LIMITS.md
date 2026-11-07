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

## Sperrene kan brytes fra innsiden (uløst)

Sperrene er vanlige Python-funksjoner, og en Python-funksjon bærer med seg
globals-ordboken sin. Der ligger de ekte funksjonene vi tok vare på. To linjer
er nok:

```python
ekte_open = open.__globals__["_REAL_BUILTINS_OPEN"]
ekte_open("/etc/passwd").read()      # leser den ekte filen
```

Vi har prøvd dette mot vår egen sandkasse, og det virker. Testen
`test_sperrene_kan_ikke_omgaas_via_globals` står i `tests/test_sandbox.py` som
`xfail` med denne begrunnelsen, slik at hullet er synlig i testkjøringen i
stedet for å være glemt. Samme vei gir også tilgang til agnlisten og til
hendelsesfilen, så et tillegg som bruker den kan både komme ut OG skrive falske
hendelser inn i rapporten om seg selv.

Vi stengte den enkleste varianten (`sys.modules["__main__"]`), men det er en bom,
ikke en vegg. Å flytte de ekte funksjonene inn i closures hjelper ikke:
`__closure__` er like lesbar. Dette kan ikke lukkes så lenge tillegget kjører i
samme Python-prosess.

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

`SandboxReport.verdict` er `clean` eller `blocked`, og én enkelt hendelse er nok
til `blocked`. Det gir noen rare utfall:

- et tillegg som leser `~/.env` fordi det *skal* lese konfigurasjon, blir
  `blocked`. Vi kan ikke se forskjell på god og dårlig grunn.
- et tillegg som trenger nettverket for å gjøre jobben sin (hente en kurs, slå
  opp en adresse) kan aldri bli `clean`. Sandkassen har ingen tillatelsesliste.
- et tillegg som krasjer med en gang blir `clean`, for det rakk ikke å gjøre noe
  galt. "Clean" betyr altså "vi så ingenting", ikke "dette er trygt".
  Dette hullet er stort nok til å stå for seg selv - se neste avsnitt.

## Et tillegg som krasjer blir `clean` (uløst)

Dette er verdt å si tydelig, fordi `clean` ser ut som et svar og ikke er det.

`report.build_report()` setter `blocked` når tillegget gjorde noe vi ikke
tillater, eller når delprosessen ikke ble ferdig. Et tillegg som *starter, feiler
og avslutter pent* har ikke gjort noe av delene. Da blir svaret `clean`.

Tre varianter vi har prøvd, alle `clean`:

| Tillegget | Hendelser | Notat i rapporten |
|---|---|---|
| `run()` kaster en feil | `start, plugin_error, done` | «Tillegget krasjet: RuntimeError: …» |
| krasjer allerede ved import | `start, plugin_error, done` | «Tillegget krasjet: RuntimeError: …» |
| har ingen `run()` i det hele tatt | `start, no_entry_point, done` | «Ingen forsøk på nettverk, ingen lesing av de falske hemmelighetene og ingenting utenfor boksen.» |

Den siste raden er den farligste. Notatet sier ordrett at vi ikke så noe
mistenkelig — og det er sant, men bare fordi **ingenting ble kjørt**. Leser du
den linjen uten å vite dette, ser det ut som tillegget ble undersøkt og
godkjent.

Hva det betyr i praksis:

- Et tillegg kan krasje med vilje hos oss og oppføre seg annerledes et sted
  hvor det ikke krasjer. Det er samme familie som sandkassegjenkjenning over,
  bare enklere: `if sandkasse(): raise`.
- `clean` sier aldri «tillegget virker». Det sier «vi så ingenting galt i det
  ene øyeblikket vi så».
- Mellomstasjonen gjør riktig med dette: en `clean`-rapport senker ikke
  risikoen. `new_package` gjelder fortsatt, og tillegget blir rødt uansett.
  Et krasjende tillegg slipper altså ikke gjennom *på grunn av* rapporten -
  men rapporten hjelper heller ikke mennesket som skal bestemme.

**Vi har ikke endret regelen.** Å gjøre `plugin_error` eller `no_entry_point`
blokkerende hadde vært lett, men da ville et tillegg med en vanlig bug blitt
behandlet som ondsinnet, og vi har ingen måte å skille dem på. Det riktige
svaret er en tredje verdi («kunne ikke vurderes»), og den finnes ikke:
`SandboxReport.verdict` er `Literal["clean", "blocked"]` og `contracts.py` er
låst.

**Hva som ville løst det:** en tredje verdi i `SandboxReport.verdict`, og at UI
viser «ikke vurdert» i stedet for «ingenting mistenkelig» når tillegget aldri
kom i gang.

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
