# Hva vault IKKE klarer

Dette er en hackathon-simulering. Loggen er ekte kryptert og ekte hash-kjedet, men den
er ikke et revisjonssikkert arkiv. Her er de ærlige hullene, slik at ingen tror noe annet.

## 1. Hele loggen kan slettes
Hash-kjeden oppdager at en linje er **endret** eller **fjernet fra midten**. Den oppdager
ikke at hele filen er borte, eller at noen har kuttet den siste delen av filen og beholdt
en gyldig kjede fra linje 0. Det finnes ingen kopi noe annet sted, ingen ekstern vitne-tjeneste
og ingen "append only"-rettighet paa filsystemet. Den som har skrivetilgang til filen og
nøkkelen kan lage en ny, kortere, helt gyldig logg.

**Hva som ville løst det:** skrive hver linje (eller hashen av siste linje) til et sted
Lonewatch ikke selv kan skrive over: en annen maskin, et objektlager med object lock,
eller en utskrift.

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

## 6. Ingen laas naar flere skriver samtidig
`Vault` holder linjene i minnet og regner `seq` ut fra det. Starter du to prosesser mot samme
fil, vil de overskrive hverandres `seq` og kjeden knekker (verify() vil si fra, men skaden er
gjort). Det er ingen fillaas og ingen transaksjon.

## 7. Dataminimering er valgfri og ufullstendig
`redact_payload()` finnes, men `Vault(redact=True)` maa slaas paa av den som logger. I demoen
logges full payload. Og naar en forespørsel logges, vet vi ennaa ikke avgjørelsen, saa en
forespørsel kan ikke minimeres like hardt som en `allow`-avgjørelse: vi beholder feltene
reglene trenger, maskerer mottakeren og kaster agentens frie tekst (`summary`).
Beløp, agent-id og dokument-id blir staaende.

## 8. Loggen er ikke slettbar paa forespørsel
En logg som bare vokser og som er hash-kjedet, kan ikke rette seg etter et krav om sletting
av persondata uten aa knekke kjeden. Det er en reell konflikt med personvern som denne
versjonen ikke løser.

## 9. Nullstilling av demoen starter en ny logg
`archive_log()` gir den gamle loggfilen et nytt navn (`lonewatch_log.<tidsstempel>.jsonl`)
og lar neste `Vault()` begynne paa linje 0. Den sletter ingenting, og UI viser hvor den
gamle loggen ble lagt. Men: den nye kjeden har ingen peker tilbake til den forrige, saa
rekkefølgen MELLOM to logger er ikke sikret av hashene. Noen med skrivetilgang kan fjerne
en arkivfil uten at `verify()` merker det (samme hull som punkt 1).

**Hva som ville løst det:** skrive hashen av siste linje i den gamle loggen som første
linje i den nye, og legge arkivfilene et sted Lonewatch ikke kan skrive over.

## 10. Det som ER ekte her
- Fernet-kryptering per linje, nøkkel kun fra miljøvariabel, ingen stille standardnøkkel.
- Hash-kjede fra `contracts.make_log_entry` / `verify_chain`, verifisert ved aa lese og
  dekryptere filen paa nytt fra disk.
- `verify()` peker paa `seq` til første linje som er endret, uleselig eller paa feil plass.
- HMAC-SHA256-pseudonymer: samme ansatt gir samme kode, og koden kan ikke regnes tilbake
  uten nøkkelen.
- Etter-listen bygges bare fra logglinjer, aldri av en AI-modell.
