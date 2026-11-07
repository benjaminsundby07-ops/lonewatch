# Hva mellomstasjonen IKKE klarer

Ærlig liste over hull i regelsettet i `gateway/`. Ta den med i pitchen.

## Reglene ser bare på feltene i forespørselen
`recipient_known`, `reversible` og `contains_personal_data` kommer fra den som
lager forespørselen. Mellomstasjonen har ingen egen kontoliste, ingen
leverandørregister og ingen skanner som finner personopplysninger. Setter en
agent `recipient_known=True` på en ukjent konto, slipper den gjennom. Dette er
det største hullet: tilliten ligger ett hakk før oss.

## Ingen hukommelse mellom forespørsler
Hver forespørsel vurderes helt alene. 100 overføringer på 49 999 kr rett etter
hverandre gir 100 ganger `allow`. Vi oppdager ikke:
- oppdeling av et stort beløp i mange små (under beløpsgrensen)
- en agent som plutselig gjør tusen ganger mer enn vanlig
- samme ukjente konto som dukker opp igjen og igjen
- rekkefølgen "les dokument med felle" -> "overfør penger" som kjede

## Ingen forståelse av innhold
Vi leser aldri dokumentet, e-posten eller dataene. En e-post til en kjent
mottaker kan inneholde hele kundebasen og blir fortsatt `allow`.
`source_doc_id` logges, men brukes ikke i noen regel: en felle i et dokument
påvirker ikke avgjørelsen.

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
