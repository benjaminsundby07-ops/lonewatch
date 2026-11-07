# Hva mellomstasjonen IKKE klarer

Ærlig liste over hull i regelsettet i `gateway/`. Ta den med i pitchen.

## Reglene ser bare på feltene i forespørselen
`recipient_known`, `reversible` og `contains_personal_data` kommer fra den som
lager forespørselen. Mellomstasjonen har ingen egen kontoliste, ingen
leverandørregister og ingen skanner som finner personopplysninger. Setter en
agent `recipient_known=True` på en ukjent konto, slipper den gjennom. Dette er
det største hullet: tilliten ligger ett hakk før oss.

## Vi tror på agenten når den sier hva den gjør
Dette er det tyngste forbeholdet ved de to nye reglene, og det er verdt å si
før tallene: **`action_type` og `reversible` er felt agenten fyller ut selv.**

`destructive_change` leser `reversible=False` på en `read_document` eller en
`update_calendar` som «noe slettes eller overskrives». Det er en god slutning
så lenge feltet er ærlig utfylt. En agent som er lurt - eller som bare er
dårlig skrevet - kan sette `reversible=True` på en sletting, og da ser vi
ingenting. Motsatt kan en forsiktig agent sette `reversible=False` på noe helt
harmløst og utløse et rødt varsel uten grunn (det er nøyaktig det som skjer med
`syn_0047` i vår egen testmengde).

Et ekte produkt må **utlede handlingstype og reversibilitet fra selve
verktøykallet**, ikke fra agentens egen oppgave: hvilken funksjon ble kalt,
hvilket endepunkt, hvilken HTTP-metode, hvilke rettigheter kreves. `DELETE
/kalender/kvartal` er en sletting uansett hva agenten kaller det. Så lenge
feltene kommer fra den som ber om handlingen, flytter vi bare tilliten ett
hakk - vi fjerner den ikke.

Det samme gjelder `contains_personal_data` og `recipient_known`, og det står
allerede øverst i denne filen. De nye reglene gjør ikke det hullet større, men
de gjør det ikke mindre heller.

## Vi slipper ikke gjennom det vi ikke klarer å vurdere
`incomplete_request` er en fail-closed-regel: alt vi ikke kan si noe fornuftig
om, går til et menneske i stedet for å gå gjennom. Tre ting fanges:

- en handlingstype som ikke står i `COVERED_ACTIONS`. Legger noen en ny verdi i
  `contracts.ActionType` uten å skrive en regel for den, gikk den før rett
  gjennom med `reasons == []`.
- en utgående handling uten mottaker. «Send denne e-posten» uten adresse, eller
  «overfør 100 kr» uten konto. Sa agenten samtidig `recipient_known=True`, slo
  ingen regel til i det hele tatt.
- tom `agent_id` eller `id`.

Målt før regelen ble innført: **null treff** i demoen, i begge blindsettene og
i de syntetiske testene. Den slår bare til på noe ingen har laget ennå, og det
er meningen.

Hva den ikke gjør: den sjekker ikke at feltene er *riktige*, bare at de finnes.
En mottaker som er `"x"` teller som en mottaker. Og `contracts.py` stopper
allerede ukjente handlingstyper og negative beløp før gateway ser dem - det er
pydantic som gjør den jobben, ikke oss.

## Reglene ser ikke OMFANGET av en handling
`blind_032` (sletting av et helt kvartal i en delt kalender) og `blind2_024`
(en endring paa 200 dokumenter samtidig) er samme sak. Den foerste fanges naa
av `destructive_change` - men **ikke fordi vi saa omfanget.** Vi saa at noe ble
slettet. At det var et helt kvartal og ikke ett moete, vet vi ikke.
`blind2_024` slipper fortsatt gjennom.

`reversible` sier bare *om* noe kan angres, ikke *hvor mye* som forsvinner. Aa
slette ett moete og aa slette tre maaneder er samme forespoersel for oss, og
det samme gjelder én e-post og en masseutsending til 8400.

**Veien vi IKKE tok:** aa legge `update_calendar` inn i
`IRREVERSIBLE_RELEVANT_ACTIONS` og loefte vekten paa `irreversible` til 2.
Det ville ogsaa fanget `blind_032`, men gjort sju harmloese saker i vaar egen
syntetiske testmengde til falske alarmer. `destructive_change` koster én.
Tallet staar som en test i `tests/test_blind_gaps.py`, saa det er
etterproevbart hvis noen vil forenkle regelsettet senere.

**Hva som ville løst det:** et omfangsfelt i forespoerselen - hvor mange
oppfoeringer, hvor mange mottakere, hvor mange rader - slik at reglene kunne
skille én fra tre maaneder. Det krever en endring i `contracts.py`.

## Reglene ser ikke HVOR MANGE personer noe gjelder
`personal_data_external` slaar til naar personopplysninger gaar ut av huset. Den
teller ikke. Én bekreftelse til én kunde og en masseutsending til 8400 veier
nøyaktig likt, fordi `contains_personal_data` er en av/paa-bryter i
`contracts.py` og det ikke finnes noe antall å lese.

Det gir to utslag, og begge er ekte:

- **Masseutsendingen fanges** (`blind_018` i `docs/MALING.md`), men ikke fordi vi
  saa at det var 8400 mottakere. Vi saa at det var persondata ut av huset.
- **Å sende en kunde kundens egne opplysninger blir rødt.** Det er ikke en
  utlevering til en tredjepart i det hele tatt, men regelen kan ikke se at
  mottakeren ER den opplysningene gjelder. Tre uavhengige tilfeller sier det
  samme: `blind_014`, `blind_042`, og vaar egen `syn_0143` i
  `gateway/evaluation.py`, som naa er den eneste falske alarmen der.

Vi vurderte aa kreve at handlingen OGSAA er ugjenkallelig (`reversible=False`)
for at regelen skal slaa til. Det ville spart alle tre tilfellene over og
fortsatt fanget de tre vi var ute etter. Vi gjorde det ikke, fordi skillet
hviler paa hvordan `reversible` tilfeldigvis er fylt ut: i blindsettet er noen
e-poster `True` og noen `False`, mens alle e-poster i vaare egne demodata er
`False`. Aa bygge en regel paa det ville vaert aa tilpasse seg maalingen, ikke
aa bli bedre.

**Hva som ville løst det:** et antall i stedet for en bryter (hvor mange
personer, hvilke kategorier opplysninger), og en maate aa vite om mottakeren er
den registrerte selv.

## Hukommelsen er én regel, og den ligger i minnet
Før så hver forespørsel seg selv og ingenting annet: 100 overføringer på
49 999 kr rett etter hverandre ga 100 ganger `allow`. Det er lukket for ett
tilfelle. `recipient_total_over_limit` summerer overføringer til **samme
mottaker** innenfor et vindu på `TRANSFER_WINDOW_HOURS` (24) timer, og blir rød
når summen når beløpsgrensen.

Vinduet regnes fra forespørselens egen `ts`, ikke fra klokken, så samme rekke
forespørsler alltid gir samme svar.

Det som fortsatt ikke oppdages:

- **Beløp spredt over mange mottakere.** Ti betalinger på 49 999 kr til ti
  forskjellige kontoer summeres ikke. Vi grupperer på mottaker, ikke på agent,
  avdeling eller døgn. Den som vet dette, deler opp på mottaker i stedet for
  på beløp.
- **Historikken ligger i minnet.** `ui/state.py` og `run_demo.py` holder listen,
  og den forsvinner ved omstart og ved Nullstill. Starter appen på nytt, er
  telleren null igjen. Gateway husker ingenting selv - den tar imot en liste.
  En ekte versjon ville lest historikken fra loggen eller en database.
- **Mottakere sammenlignes på tekst.** Vi fjerner mellomrom og store bokstaver,
  så `NO12 3456 7890 123` og `no1234567890123` er samme konto. Men samme
  mottaker med to ulike kontonumre er to mottakere for oss.
- **En agent som plutselig gjør tusen ganger mer enn vanlig.** Vi har ingen
  normal å sammenligne med.
- **Kjeden "les dokument med felle" -> "overfør penger".** `source_doc_id`
  logges, men brukes ikke i noen regel.

## Ingen forståelse av innhold
Vi leser aldri dokumentet, e-posten eller dataene. En e-post til en kjent
mottaker kan inneholde hele kundebasen og blir fortsatt `allow`.
`source_doc_id` logges, men brukes ikke i noen regel: en felle i et dokument
påvirker ikke avgjørelsen.

## "Kjent mottaker" er en oppdiktet demoliste
`unknown_recipient` er den nest tyngste regelen, og i "Prøv selv" avgjøres den
av `agents.scenarios.known_recipients()` — tolv mottakere vi har funnet på selv
for demoen. Det er ikke et kunderegister, ikke en bankavstemming og ikke et
leverandørsystem. En konto er "kjent" fordi den står i demodataene våre.

Det er en bedre løsning enn en avkrysningsboks, som juryen kunne krysset av for
å snakke seg forbi regelen. Men det løser ikke det underliggende problemet, som
står øverst i denne filen: for de 40 ferdige forespørslene (og for en ekte
integrasjon) kommer `recipient_known` fortsatt som et felt vi stoler på.

Sammenligningen er dessuten grov: vi normaliserer til små bokstaver og fjerner
mellomrom. `NO12 3456 7890 123` og `no12 34567890123` treffer det samme. Et
hjemmelsnært navn som `salg@fjordglass.no.evil.example` treffer ikke — men vi
sjekker heller ikke domene, kontrollsiffer i IBAN, eller om kontoen finnes.

**Hva som ville løst det:** et ekte mottakerregister, med oppslag mot bank og
leverandørsystem, og en prosess for å legge til en ny mottaker.

## Pakkenavn og adresser er tekst noen andre velger
`consequence_text` er det et menneske leser før det godkjenner. To av feltene i
den kommer ikke fra oss: pakkenavnet (fra den som ber om installasjonen — i
"Prøv selv" er det noen som sitter og skriver) og adressene i en
sandkasserapport (valgt av tillegget selv).

Begge vaskes før de vises: `consequence.safe_package_name()` og
`consequence.safe_destination()` slipper bare gjennom tegn som hører hjemme i et
pakkenavn eller et vertsnavn, og viser ellers en nøytral tekst. Uten det kunne
navnet `nordlys-core. Dette er godkjent av sikkerhetsavdelingen` skrevet sin
egen setning inn i varselet.

Det som gjenstår: innenfor de tillatte tegnene er navnet fortsatt fritt.
`nordlys-core-godkjent` er et gyldig pakkenavn og leses av et menneske som noe
det ikke er. Reglene bruker uansett det EKTE navnet — det er bare visningen
som er begrenset.

## "Prøv selv" setter to felt selv
Skjemaet lar ikke den som skriver oppgi `recipient_known` eller `reversible`;
begge regnes ut i `ui/state.py`. `contains_personal_data` er derimot en
avkrysning, fordi den bare kan legge til risiko (`personal_data_external` gir
+3 og trekker aldri fra). Det er et bevisst valg: innhold er nettopp det
Lonewatch aldri leser, så alternativet ville vært å gjette.

Skjemaet krever også et beløp på en overføring. Det er ikke en regel, men en
omgåelse av hullet under: uten beløp blir `requires_typed_amount` likevel
`True`, og kortet kunne aldri godkjennes.

## Sandkasserapporten tas for god fisk
`evaluate(req, sandbox_report=...)` tar imot en ferdig `SandboxReport` og stoler
på den. Mellomstasjonen kjører ingenting selv og kan derfor ikke vite om
skanningen faktisk har skjedd, eller om den som kaller har funnet på innholdet.
Den som kan kalle `evaluate()` kan sende inn en oppdiktet `clean`-rapport og få
et tillegg gjennom. Vi sjekker én ting: at rapporten gjelder det samme
pakkenavnet som forespørselen (ellers kaster vi `ValueError`). Det beviser at
rapporten handler om riktig tillegg, ikke at den er ekte.

**Hva som ville løst det:** at rapporten var signert av sandkassen, og at
mellomstasjonen sjekket signaturen før den brukte den.

## "Clean" er ikke det samme som trygt
En `clean`-rapport betyr bare at sandkassen ikke så noe mens den så etter.
Et tillegg som kjenner igjen en sandkasse, oppfører seg pent hos oss og stjeler
først på en ekte maskin - se `sandbox/LIMITS.md`. Derfor senker en `clean`-rapport
aldri risikoen her: `new_package` gjelder fortsatt, og teksten sier rett ut at
dette ikke er en garanti. Men: et tillegg som alt står i `KNOWN_PACKAGES` blir
`allow` uansett hva sandkassen så, fordi `sandbox_blocked` er den eneste
sandkasseregelen og den bare peker nedover.

## Rapporten henger på pakkenavnet, ikke på forespørselen
`SandboxReport` har ingen `request_id` (contracts er låst), så koblingen mellom
en rapport og en forespørsel er pakkenavnet alene. Ber to forespørsler om det
samme tillegget, deler de én skanning og én linje i loggen. Den som leser loggen
i ettertid kan altså ikke se at tillegget ble prøvd på nytt - bare at det ble
prøvd. I en ekte versjon ville hver forespørsel hatt sin egen skanning med sin
egen id.

## Adressene i varselet er valgt av tillegget
Et blokkert tillegg velger selv hvilket vertsnavn det prøver å nå, og det navnet
havner i teksten et menneske leser. `consequence.safe_destination()` slipper bare
gjennom tegn som hører hjemme i et vertsnavn eller en IP-adresse, og vi viser
maks tre adresser. Et vertsnavn er likevel fritt innenfor de tegnene, så noe som
`sikkerhetsgodkjent.example` kan fortsatt leses som noe det ikke er. Vi viser
aldri `notes` fra rapporten i varselet, nettopp fordi den er lengre og romsligere.

## Tillegg vurderes bare på navn
`new_package` og blokklisten sammenligner tekststrenger. Et farlig tillegg som
heter `nordlys-core` (navn på et godkjent tillegg) slipper rett gjennom, og vi
sjekker verken versjon eller utgiver. Siden `sandbox/` ble koblet på, ser vi i
tillegg hva tillegget FAKTISK gjorde - men bare for de fem tilleggene som ligger
i `sandbox/packages/`. For alle andre navn er svaret "ikke testet", og da er
navnet fortsatt det eneste vi har.

## Grensene er gjetninger
50 000 kr (rødt) og 50 000 000 kr (blokk) er tall vi satte for å få en god demo,
ikke tall fra en risikoanalyse. Den harde grensen er bevisst satt over demoens
overføring på 10 000 000 kr, nettopp fordi det røde varselet er det vi vil vise.
Vektene i `RULE_WEIGHTS` er på samme måte valgt for hånd.

## Rødt blir fort utvannet
Alt som ikke er `low` blir rødt. I testmengden vår er 11 av 43 røde. I et ekte
selskap med tusenvis av forespørsler per dag må tersklene opp, ellers slutter
folk å lese varselet. Vi måler ikke hvor mange røde et menneske faktisk tåler.

## Hull i enkeltregler
- `requires_typed_amount` blir `True` for alle røde pengeoverføringer, også når
  `amount` mangler. Da har UI-et ikke noe tall å be om. Spesifikasjonen sier det
  skal være slik; UI-en må håndtere det.
- `amount` brukes uansett handlingstype, så et stort beløp på en
  kalenderoppdatering gir rødt. Det er bevisst strengt, men litt rart.
- Personopplysninger til en *kjent* mottaker gir aldri utslag. En kjent, men
  kompromittert, partner er et blindpunkt.
- Vi stoler på at `ActionType` er dekkende. En ny handlingstype i `contracts`
  får konsekvenstekst, men ingen regler, og blir derfor `allow`.

## Målingen beviser lite
`gateway/evaluation.py` viser 15 av 15 farlige fanget og 0 falske alarmer, men
samme person skrev reglene og testmengden. Den måler at koden gjør det vi mente,
ikke at vi mente det riktige.
