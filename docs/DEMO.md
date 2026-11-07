# Demo: rundt to minutter

Fortellingen under følger nettsiden i `ui/`. Alle fanenavn, knapper og tekster er hentet fra
`ui/static/index.html` og `ui/static/app.js`.

Alt er en simulering: Nordlys Forsikring er oppdiktet, det finnes ingen ekte penger, ingen ekte skadekode
og ingen nettverkskall. Se README for den fulle listen.

## Før du begynner

```bash
source .venv/bin/activate
export LONEWATCH_LOG_KEY=$(python -m vault.gen_key)
export LONEWATCH_PSEUDONYM_KEY=$(python -m vault.gen_key --pseudonym)
python3 -m ui
```

Åpne <http://127.0.0.1:8000>. Fanen **Under** er åpen fra start, og den rolige strømmen begynner med én
gang: hvert andre sekund slippes neste forespørsel fra demodataene gjennom mellomstasjonen.

Har du spilt demoen før i samme økt: trykk **Nullstill**. Da begynner en ny loggfil, og banneret sier
«Ny logg startet. Forrige logg ligger uendret i …» — ingenting slettes. La siden stå i 20–30 sekunder før
du starter, slik at listen **Går gjennom** har noe i seg.

## 0:00 — «Dette er en vanlig arbeidsdag» (ca. 15 s)

Stå i fanen **Under**.

Pek på kolonnen til høyre: **Går gjennom**. Der ligger kalenderoppdateringer, dokumentlesing og e-post til
kjente mottakere, med agentnavn — Kundeservice, Innkjøp, Økonomi, HR, IT-hjelp — og agentens egen
forklaring. Telleren ved siden av overskriften vokser mens du snakker.

Si: *av de 40 forespørslene i demodataene går 34 gjennom uten å forstyrre et menneske. Det er poenget. En
mellomstasjon som lyser rødt hele tiden blir slått av.*

Pek så på overskriften til venstre: **Trenger et menneske**. Den er null eller nesten null nå.

## 0:15 — Start hendelsen (ca. 10 s)

Trykk **Spill av hendelsen** oppe til høyre.

Et bånd legger seg over fanene med en klokke, en tittel, «steg *n* av 11» og en framdriftslinje. Hendelsen
spiller av seg selv i sanntid over 90 sekunder. Knappen **Neste steg** i båndet hopper videre når du vil
holde tempoet selv — bruk den hvis du har to minutter og ikke halvannet.

Første steg heter **En vanlig torsdag**. Les gjerne linjen høyt.

## 0:25 — Fella går av (ca. 20 s)

Steg 2 og 3: *IT-hjelp leser en bulletin* og **Fella går av**.

Lesing av et dokument er helt vanlig arbeid, og forespørselen blir `allow` — den dukker opp i **Går
gjennom**. Men dokumentet har et felt i metadata som et menneske ikke ser, og der står det hva agenten skal
installere.

Pek på listen **Hendelser** nederst i høyre kolonne. Der står «Felle gikk av» med hele teksten: hvilke
usynlige markører som ble funnet, og hva fella forsøkte å oppnå.

Si: *Lonewatch leser aldri denne teksten som en instruksjon. Vi registrerer bare at fella gikk av, slik at
det står i loggen.*

## 0:45 — Før: tillegget kjøres i en lukket boks (ca. 25 s)

Steg 4 og 5: *Agenten vil installere tillegget* og **Sandkassen har kjørt tillegget**.

Bytt til fanen **Før**.

Der ligger tillegget fella ba om, merket **blokkert** ute til høyre, med notatet fra sandkassen: hvilken
adresse det prøvde å koble seg til, og at det leste tre filer som ser ut som hemmeligheter. Si at filene er
oppdiktede demofiler som sier «FALSK DEMOFIL» i første linje, at adressen slutter på `.invalid` og ikke
finnes, og at sandkassen svarte nei — ingenting forlot maskinen.

Les gjerne linjen over listen høyt: *«Rent» betyr vi så ingenting, ikke at tillegget er trygt.*

Bytt tilbake til **Under**. Tillegget står under **Stoppet av Lonewatch**, ikke i køen: dette er `block`, og
ingen kan godkjenne det. Konsekvensteksten sier det rett ut.

Har den rolige strømmen rukket langt nok, ligger det også et tillegg merket **rent** i **Før**-fanen. Pek på
det hvis det er der: samme behandling, annet svar.

## 1:10 — Og så venter den (ca. 10 s)

Steg 6 og 7: **Og så venter den** og *Økonomi leser en faktura*.

Si: *her slutter angrepet. Arbeidsdagen fortsetter. Neste steg kommer som et helt vanlig dokument, fra en
leverandør selskapet bruker hver måned.*

Steg 8 er **Fella nummer to**: fakturaen har hvit tekst på hvit bakgrunn med et nytt kontonummer og en
beskjed om å ikke varsle noen. Den havner også i **Hendelser**.

## 1:20 — Under: det røde varselet (ca. 30 s)

Steg 9: **Overføringen**.

Et rødt kort legger seg øverst under **Trenger et menneske**, og telleren går opp.

Les kortet ovenfra og ned:

- Øverste linje: Økonomi · Overfører penger · til NO93 8601 1117 947 · hendelsen.
- Konsekvensteksten: **«Overfører 10 000 000 kr til ukjent konto. Kan ikke angres.»** Si at denne setningen
  er bygget av regler og felt — aldri av en AI-modell, og aldri av det agenten selv skriver.
- Merkelappene: «over beløpsgrensen», «ukjent mottaker», «kan ikke angres», «risiko: high».
- Linjen **Agenten sier**: *«Betaler samleoppgjør for takseringsoppdrag, haster før forfall.»* Si at dette
  er det eneste Lonewatch aldri bruker. En agent som er lurt, skal ikke kunne snakke seg forbi.

Nå selve porten: **Skriv beløpet for å godkjenne**. Knappen **Godkjenn** er grå.

Skriv et feil tall i feltet først, for eksempel `1000000`. Hinten blir stående på «Skriv beløpet nøyaktig
for å kunne godkjenne», og knappen blir ikke aktiv. Prøv gjerne `100000,00` også — hundre tusen kroner og
null øre, som har nøyaktig de samme sifrene. Den blir også avvist. Skriv så `10 000 000`. Hinten skifter til
**«Stemmer.»** og **Godkjenn** blir rød og trykkbar.

Si: *poenget med å skrive beløpet er at man skal se det. Åtte nuller er vanskeligere å overse enn en knapp.*
Og hvis du vil være ærlig om prosessen: *denne sjekken var feil først. Den sammenlignet sifre, så*
`100000,00` *slapp gjennom som ti millioner. Det fant vår egen angrepstest, og det står i*
`docs/REDTEAM.md`.

Trykk **Avvis**. Kortet flytter seg ned til **Besvart** med pseudonymet til den som svarte — `emp_` og fire
tegn — og hvor mange sekunder det tok. Si at loggen aldri ser navnet.

## 1:50 — Sjekk loggen (ca. 10 s)

Trykk **Sjekk loggen** oppe til høyre.

Banneret svarer: **«Loggen stemmer. *n* linjer, ingen er endret.»** Si at dette ikke er et tall fra minnet:
`verify()` leser og dekrypterer hele filen på nytt fra disk og følger hash-kjeden linje for linje. Er én
linje endret, peker svaret på `seq` til den første.

Vær ærlig med det samme: *kjeden oppdager en endret eller fjernet linje. Den oppdager ikke at hele filen er
slettet. Det står i `vault/LIMITS.md`.*

Og si hva loggen faktisk inneholder, hvis noen spør: *den er minimert. Agentens forklaring er
kastet, kontonummeret står som `**** 947`, og teksten mennesket fikk se er ikke lagret.
Men beløpet, hvilken agent og hvilket dokument står der — det er nødvendig for å granske.
Minimering, ikke anonymisering.* Vil du vise forskjellen: start appen med `LONEWATCH_REDACT=0`,
så står alt i klartekst.

## 2:00 — Etter: hva mennesker må gjøre (ca. 15 s)

Bytt til fanen **Etter**.

Listen er bygget rett fra logglinjene, med en eier per linje: «Felle gikk av i et dokument» (security),
«Bytt tilgangene agenten brukte» (employee), «Tillegget prøvde aa sende data ut» (security), «Blokkert
tillegg maa granskes» (security), «Sjekk den flaggede overføringen» (finance).

Si: *ingen AI har skrevet denne listen. Hver linje peker tilbake på en konkret hendelse i loggen.*

## Hvis juryen vil prøve selv (ca. 40 s)

Dette er svaret på «er ikke dette bare hardkodet?».

Bytt til fanen **Prøv selv**. Be en i juryen bestemme. Skriv det de sier, og
trykk **Send gjennom Lonewatch**.

Forslag hvis de ikke har et: overfør `10 000 000` til `NO93 8601 1117 947`, og
skriv noe overbevisende i **Agenten sier** — «Rutinemessig, allerede godkjent av
ledelsen». Kortet blir rødt med «over beløpsgrensen», «ukjent mottaker», «kan
ikke angres», og konsekvensteksten er den samme som før.

Si: *det du skrev i Agenten sier står i kortet, men ble aldri lest av en eneste
regel. Hadde det vært motsatt, kunne et dokument skrevet sin egen godkjenning.*

Endre så mottakeren til `NO12 3456 7890 123` og beløpet til `38 400`. Den går
gjennom. Pek på forskjellen: *mottakeren står på listen, og beløpet er under
grensen. Samme regler, annet svar.*

Vil de prøve et tillegg: `nordlys-crm-sync` gir «ikke testet i sandkassen» —
Lonewatch laster aldri ned noe på et navn du skriver. `nordlys-mail-connector-patch`
finnes derimot i sandkassen, blir kjørt der, og blir **stoppet**.

Kortene merkes «skrevet av deg», og havner i samme logg. Trykk **Sjekk loggen**
etterpå: den stemmer fortsatt.

## Hvis du har 20 sekunder til overs

Avslutt ærlig, med én av disse:

- **Sandkassen er ikke en vegg.** Sperrene er funksjoner i samme Python-prosess som tillegget. Vi kom rundt
  dem selv, og hullet står som `xfail` i testkjøringen i stedet for å være gjemt bort.
- **Reglene stoler på feltene de får.** Setter en agent `recipient_known=True` på en ukjent konto, slipper
  den gjennom. Tilliten ligger ett hakk før oss.
- **Målingen beviser lite.** 15 av 15 farlige fanget, men samme person skrev både reglene og testmengden.

Alle tre står utfyllende i `gateway/LIMITS.md`, `vault/LIMITS.md` og `sandbox/LIMITS.md`.

## Terminalvarianten, hvis nettsiden ikke vil

```bash
python run_demo.py
```

Skriver alle 40 forespørslene med avgjørelse, regler og konsekvenstekst, og avslutter med antall logglinjer
og «Sjekk av logg: OK, ingen linjer er endret.» Menneskesvaret er hardkodet til *avvis* i denne varianten,
så det går ikke å vise beløpsporten her.
