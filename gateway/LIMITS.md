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

## Tillegg vurderes bare på navn
`new_package` og blokklisten sammenligner tekststrenger. Et farlig tillegg som
heter `nordlys-core` (navn på et godkjent tillegg) slipper rett gjennom, og vi
sjekker verken versjon, utgiver eller hva tillegget faktisk gjør. Det finnes
ingen sandkasse her.

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
