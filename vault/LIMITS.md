# Hva vault IKKE klarer

Dette er en hackathon-simulering. Loggen er ekte kryptert og ekte hash-kjedet, men den
er ikke et revisjonssikkert arkiv. Her er de ærlige hullene, slik at ingen tror noe annet.

## 1. Ankeret hever listen, det lukker ikke hullet
Hash-kjeden oppdager at en linje er **endret** eller **fjernet fra midten**. Den oppdaget
ikke at noen kuttet bort de SISTE linjene: det som staar igjen er fortsatt en perfekt kjede
fra linje 0.

Det er nå delvis lukket. Ved siden av loggen ligger et **hale-anker** (`<logg>.head`) som
sier hvor mange linjer loggen hadde og hva siste hash var, signert med HMAC-SHA256 med en
nøkkel avledet fra loggnøkkelen (HKDF, egen `info`-streng - signering og kryptering deler
aldri nøkkelmateriale). Ankeret skrives atomisk etter hver linje: midlertidig fil, `fsync`,
`os.replace`. `verify()` feiler nå hvis loggen er kortere enn ankeret sier, hvis siste hash
ikke stemmer, hvis ankeret mangler mens loggen har linjer, eller hvis signaturen er ugyldig.

**Men:** den som har skrivetilgang til **begge** filene og nøkkelen kan skrive om begge.
Da er en kortere logg med et matchende anker like gyldig som den ekte. Ankeret tvinger en
angriper til å gjøre to ting i stedet for én, og det er alt. Det er ikke et bevis.

Fire ting ankeret heller ikke løser:

- **Hele mappen kan slettes.** Logg og anker forsvinner sammen, og det finnes ingen kopi.
- **Ankeret er like lokalt som loggen.** Samme disk, samme bruker, samme rettigheter.
- **Nøkkelen gir begge deler.** Den som kan dekryptere loggen kan også signere et anker,
  fordi signeringsnøkkelen er avledet fra den samme loggnøkkelen. Det er et bevisst
  kompromiss for en demo med én nøkkel; en ekte versjon ville hatt to nøkler i to hender.
- **Én linje uten anker godtas.** Krasjer prosessen mellom linjen og ankeret, er loggen én
  linje foran. Vi godtar det som gyldig, fordi alternativet er at et avbrudd ser ut som et
  angrep. Prisen er at nøyaktig én ekstra linje kan legges til uten at ankeret sier fra -
  men kjeden må fortsatt stemme, så linjen kan ikke være hva som helst.

**Hva som ville løst det:** et anker UTENFOR maskinen. Siste hash skrevet ned på papir,
sendt til en annen maskin, lagt i et objektlager med object lock, eller lest opp i et møte.
`run_demo.py` og «Sjekk loggen» i appen viser derfor de tolv første tegnene av siste hash:
noterer du dem, kan du siden se om loggen er den samme. Det er den eneste varianten som
faktisk fanger en som har alt lokalt.

## 2. Nøkkelen ligger i en miljøvariabel, bare for demo
`LONEWATCH_LOG_KEY` og `LONEWATCH_PSEUDONYM_KEY` leses fra miljøet. Det er bedre enn
hardkoding, men:
- hvem som helst med samme bruker paa maskinen kan lese miljøet til prosessen
- nøkkelen havner i shell-historikk og i `ps` hvis den settes paa feil maate
- det finnes ingen rotasjon: bytter du nøkkel, kan du ikke lenger lese gamle linjer
- den som har nøkkelen kan lese ALT. Det finnes ingen deling der én rolle bare ser deler.

**Hva som ville løst det:** en nøkkeltjeneste (KMS/HSM), nøkkel per dag, og at bare en
egen logg-prosess har nøkkelen.

## 3. Ingen ekte tidsstempel-garanti
`ts` er klokka paa maskinen som skrev linjen. Den kan settes bakover. Rekkefølgen i kjeden
er sikret (linje 5 kom etter linje 4), men *naar* noe skjedde er bare et paastand.
Ingen ekstern tidsstempel-tjeneste, ingen signatur fra noen utenfor.

## 4. Kryptering uten signatur = ingen avsender
Fernet gir konfidensialitet og integritet med én delt nøkkel. Alle som kan lese loggen kan
ogsaa skrive gyldige linjer i den. Loggen kan altsaa ikke bevise HVEM som skrev en linje.
En ekte løsning ville signert hver linje med en privat nøkkel som bare skriveren har.

## 5. Pseudonymene er svake mot gjetting
Pseudonymet er 4 hex-tegn = 65 536 muligheter. Det er nok til at loggen ikke inneholder navn,
men i et selskap med mange ansatte vil to ansatte før eller senere faa samme kode (kollisjon),
og den som har pseudonym-nøkkelen kan regne ut pseudonymet til en kjent ansatt-id og dermed
knytte linjer til person. 4 tegn er valgt fordi det skal vises paa en skjerm.
Navn-til-kode-tabellen er kryptert og `reveal()` krever `role == "admin"`, men rollen er bare
en streng som den som kaller funksjonen oppgir selv. Det er ingen innlogging bak.

## 6. Svak laas naar flere skriver samtidig
`Vault` holder linjene i minnet og regner `seq` ut fra det. Starter du to prosesser mot samme
fil, vil de overskrive hverandres `seq` og kjeden knekker (verify() vil si fra, men skaden er
gjort).

Nettappen tar nå `vault.acquire_log_lock()` (flock på en egen `<logg>.lock`-fil)
og nekter å starte hvis en annen Lonewatch holder loggen. Det stopper det
vanlige uhellet - å kjøre `python -m ui` to ganger - men det er en frivillig
laas, ikke en transaksjon:

- `Vault` selv tar den ikke. `run_demo.py`, testene og alt annet som lager en
  `Vault` direkte kan fortsatt skrive samtidig uten å bli stoppet.
- `flock` virker ikke pålitelig over nettverksdisker (NFS/SMB).
- Finnes ikke `fcntl` (Windows), er det ingen laas i det hele tatt.
- Laasen dør med prosessen, så den beskytter ikke en fil som ligger igjen.

Det finnes fortsatt ingen transaksjon: to skrivere som kommer forbi laasen,
knekker kjeden på samme måte som før.

## 7. Dataminimering er paa i demoen, men det er ikke anonymisering
Demoen (`ui/` og `run_demo.py`) logger med `Vault(redact=True)`. `Vault()` selv har den
fortsatt av som standard, saa den som lager en Vault direkte faar full payload.
Bryteren er `LONEWATCH_REDACT`; den er paa med mindre den settes til `0`/`false`/`nei`/`av`.

**Hva som faktisk fjernes:**
- `summary` (agentens frie tekst) kastes helt. Den brukes aldri til noe, og kan
  inneholde hva som helst et dokument har skrevet for agenten.
- `recipient` maskeres til siste fire tegn: `NO93 8601 1117 947` blir `**** 947`.
  Det samme gjelder `destinations` i en sandkasserapport.
- `consequence_text` kastes fra avgjørelser. Den skriver ut mottakeren i klartekst
  naar mottakeren er kjent («Overfører 112 500 kr til NO55 1122 3344 556»), og uten
  dette ville vi maskert kontoen i forespørselen og lagt den tilbake to linjer senere.
- En `allow`-avgjørelse krympes til `request_id`, `risk` og `verdict`. Ingen mottaker,
  ingen beløp, ingen begrunnelse.

**Hva som blir staaende, med vilje:**
- **beløpet** i klartekst. `10 000 000` staar der. Det er ofte det mest identifiserende
  feltet i en overføring, og vi beholder det fordi Etter-listen og enhver gransking
  trenger det.
- **`agent_id`**, ogsaa `jury` fra «Prøv selv».
- **`source_doc_id`**, saa et dokument kan spores.
- **`package_name`** raatt, fordi reglene og Etter-listen bruker det.
- **`recipient_known`, `reversible`, `contains_personal_data`, `action_type`** - alt
  reglene faktisk brukte.
- **fellenes `what_happened`**, som kan inneholde en e-postadresse fra den skjulte
  teksten i dokumentet. Den maskeres ikke: den er selve funnet.
- **sandkassens `notes`**, der adressen staar i klartekst inne i setningen selv om
  `destinations` er maskert.
- **pseudonymet** (`emp_xxxx`), som punkt 5 allerede sier er svakt.

**Dette er altsaa ikke anonymisering.** Siste fire sifre av et kontonummer, pluss
beløp, pluss tidspunkt, pluss hvilken agent - det peker ofte paa én transaksjon.
Minimeringen gjoer at loggen ikke er en kopi av kundebasen; den gjoer den ikke anonym.

**Prisen vi betaler:** med minimering husker ikke loggen den eksakte setningen
mennesket ble vist foer det godkjente. Reglene som slo til (`reasons`), risikoen,
beløpet og den maskerte mottakeren staar fortsatt, saa det gaar an aa granske hva
som skjedde - men ikke aa sitere ordrett hva skjermen sa.

**Og naar en forespørsel logges, vet vi ennaa ikke avgjørelsen**, saa den kan ikke
minimeres like hardt som en `allow`-avgjørelse. Vi beholder feltene reglene trenger.

## 8. Loggen er ikke slettbar paa forespørsel
En logg som bare vokser og som er hash-kjedet, kan ikke rette seg etter et krav om sletting
av persondata uten aa knekke kjeden. Det er en reell konflikt med personvern som denne
versjonen ikke løser.

## 9. Nullstilling av demoen starter en ny logg
`archive_log()` gir den gamle loggfilen et nytt navn (`lonewatch_log.<tidsstempel>.jsonl`)
og lar neste `Vault()` begynne paa linje 0. Den sletter ingenting, og UI viser hvor den
gamle loggen ble lagt. Dette skjer BARE naar noen trykker Nullstill: aa starte appen
arkiverer ingenting, og en app som ikke faar loggen (punkt 6) roerer ingen fil.
Men: den nye kjeden har ingen peker tilbake til den forrige, saa
rekkefølgen MELLOM to logger er ikke sikret av hashene. Noen med skrivetilgang kan fjerne
en arkivfil uten at `verify()` merker det (samme hull som punkt 1).

**Hva som ville løst det:** skrive hashen av siste linje i den gamle loggen som første
linje i den nye, og legge arkivfilene et sted Lonewatch ikke kan skrive over.

## 10. Ingenting i appen krever innlogging
Hele nettappen er uautentisert, og det gjelder også `POST /api/reset`, som
arkiverer loggen og starter en ny, tom. Hvem som helst med nettverkstilgang til
porten kan altså "spole historien". Vi har ikke rettet dette (F6 i
`docs/REDTEAM.md`), og det er verdt å si høyt.

To ting demper det, men fjerner det ikke:
- appen binder bare `127.0.0.1` som standard, så den er ikke åpen utover maskinen
- nullstilling er *synlig*: ingenting slettes, UI viser stien til den arkiverte
  loggen, og den nye loggen starter på `seq=0`

Det gjør dette til en ærlig nullstilling, ikke en skjult forfalskning. Men en
uautentisert "start ny logg"-knapp er et problem i seg selv, og i en ekte
versjon ville den ikke stått der.

**Hva som ville løst det:** innlogging foran alt som skriver eller nullstiller,
og arkivfiler et sted Lonewatch ikke selv kan skrive over (samme svar som
punkt 1 og 9).

## 11. Det som ER ekte her
- Fernet-kryptering per linje, nøkkel kun fra miljøvariabel, ingen stille standardnøkkel.
- Hash-kjede fra `contracts.make_log_entry` / `verify_chain`, verifisert ved aa lese og
  dekryptere filen paa nytt fra disk.
- `verify()` peker paa `seq` til første linje som er endret, uleselig eller paa feil plass.
- HMAC-SHA256-pseudonymer: samme ansatt gir samme kode, og koden kan ikke regnes tilbake
  uten nøkkelen.
- Etter-listen bygges bare fra logglinjer, aldri av en AI-modell.
- `vault/tamper_demo.py` angriper en KOPI av loggen og lar den samme verifiseringen
  svare. Tre angrep oppdages, det fjerde gjør ærlig ikke det. Se punkt 12.

## 12. Hva «Bryt loggen»-demoen viser, og hva den ikke viser
`vault/tamper_demo.py` (`python -m vault.tamper_demo --attack {endre,slett,kutt,full}`)
angriper en **kopi** av loggen og lar den eksisterende verifiseringen svare. Loggen og
hale-ankeret kopieres til en midlertidig mappe, angrepet skjer der, og mappen slettes
etterpå. Vi tar sha256 og filstørrelse av den ekte loggen og ankeret før og etter, og
stopper med en feil hvis noe har flyttet seg. Modulen skriver aldri en ny, lettere
sjekk - den kaller `Vault.verify_detail()`, den samme koden som kjøres ellers.

**Dette viser den:**
- `endre` - én linje midt i loggen dekrypteres, utfallet skrives om fra «rød» til
  «tillatt», og linjen krypteres på nytt. Hash-kjeden peker ut nøyaktig den linjen.
- `slett` - én linje midt i loggen fjernes. Neste linje står på feil plass, og kjeden
  peker ut gapet.
- `kutt` - de to siste linjene kuttes bort. Dette ser hash-kjeden **ikke**: det som står
  igjen er fortsatt en perfekt kjede fra linje 0. Hale-ankeret fanger det.

**Dette viser den også, og det er med vilje:**
- `full` - angriperen har loggnøkkelen, regner hash-kjeden på nytt fra linjen han endret
  og helt ut, og signerer et nytt hale-anker. Verifiseringen svarer at loggen er i orden,
  og **det er riktig svar**: alt den kan se, stemmer. Loggen kan ikke oppdage dette alene.
  Det er ikke en feil som venter på å bli rettet, det er punkt 1 i denne filen, utført.
  Det eneste som fanger det, er siste hash skrevet ned **utenfor maskinen** - på papir, i
  en annen maskin, i et objektlager med object lock, eller lest opp i et møte. Demoen
  viser siste hash før og etter nettopp derfor: de er forskjellige, og forskjellen er
  synlig med øyet hvis du hadde notert den første.

**Dette viser den ikke:**
- Ingenting om hvem som endret loggen. Punkt 4 står: alle som kan lese den kan skrive
  gyldige linjer i den, og loggen kan ikke bevise avsender.
- Ingenting om en slettet mappe eller en fjernet arkivfil. Angrepene forutsetter at det
  finnes en logg å verifisere. Punkt 1 og 9 dekker det som er borte.
- Ingenting om *når* noe skjedde. `full`-angrepet kan også skrive om `ts` uten at noe
  sier fra - punkt 3.
- Ingen sannsynlighet. At `endre` og `slett` oppdages betyr at de oppdages av
  **verifiseringen**, ikke at noen faktisk kjører den. En logg ingen sjekker er en logg
  ingen beskytter.

Demoen feiler lukket: finnes ikke loggen, er den tom, er den for kort for angrepet, eller
verifiserer den ikke **før** vi gjør noe, så stopper den med en feilmelding i stedet for
å vise noe halvveis. Den tar heller ikke æren for et avvik den ikke selv laget.
