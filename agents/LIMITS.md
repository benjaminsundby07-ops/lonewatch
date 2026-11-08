# Hva agentene og felle-skanneren IKKE er

Alt i `agents/` er en SIMULERING. Det finnes ingen Nordlys Forsikring, ingen
ekte agenter, ingen ekte penger og ingen ekte skadevare. Et "dokument" er en
dataklasse med litt tekst i, og en "felle" er skjult tekst i den teksten.

Denne filen handler mest om `agents/doc_scan.py`, som er det eneste i mappen
som påstår å *oppdage* noe.

## Hva skanneren gjør

`doc_scan.scan_document()` leser innholdet i et dokument - synlig tekst, skjult
tekst og alle metadata-verdier - og rapporterer hvilke **skjulemekanismer** den
kjente igjen, og hvor:

- HTML-kommentar (`<!-- ... -->`)
- `display:none`, `visibility:hidden`, `opacity:0`
- `font-size:0` og `font-size:1px` (med eller uten mellomrom, enhet valgfri)
- hvit på hvitt (`#fff`, `#ffffff`, `white`, `rgb(255,255,255)`, `rgba(...)`)
- nullbredde-tegn og myk bindestrek
- tegn som snur leseretningen (`U+202E` og slekten)
- `left:-9999px` og venner
- `hidden`- og `aria-hidden`-attributtet
- et eget skjult tekstlag (agenten leser mer enn mennesket ser)
- en metadata-nøkkel som *heter* noe med instruksjon/prompt/system

og i tillegg **instruksjonsfraser** (norsk og engelsk) - men bare der mennesket
ikke ser dem: inne i en skjulemekanisme, i det skjulte laget, eller i en
metadata-verdi.

Alt er deterministisk: faste uttrykk og en fast fraseliste. Ingen AI-modell er
involvert, og `ActionRequest.summary` - agentens egen forklaring - leses aldri.

## Hva skanneren IKKE fanger

Dette er en detektor med kjente grenser, ikke en garanti.

- **Tekst i bilder.** Et skjermbilde eller en skannet PDF-side med en
  instruksjon er bare piksler for oss. Dette er den største, og den som er
  mest sannsynlig i virkeligheten: en faktura er ofte et bilde.
- **Kodede strenger.** base64, rot13, hex, HTML-entiteter (`&#101;`), URL-
  koding, eller en streng satt sammen av biter. `test_an_encoded_instruction_is_not_caught`
  i `tests/attack/test_attack_document_injection.py` viser det.
- **Språk fraselisten ikke kjenner.** Listen er norsk og engelsk. Den samme
  instruksjonen på polsk, tysk, arabisk eller kinesisk gir ingen frasetreff.
  Skjulemekanismen fanges fortsatt - en HTML-kommentar er en HTML-kommentar på
  alle språk - men vi kan ikke si at det *står en instruksjon* der.
- **Omskrivinger.** «oppdater betalingsdetaljene til», «vennligst benytt
  følgende konto», «as agreed, remit to» står ikke i listen. Fraselisten er
  frasene vi kom på, ikke frasene som finnes.
- **Skjuling vi ikke har tenkt på.** `clip-path`, `transform:scale(0)`,
  `height:0;overflow:hidden`, tekst bak et bilde med `z-index`, en
  skriftstørrelse i `pt` vi ikke dekker. Listen over er mekanismene vi kjenner.
- **Instruksjoner i helt synlig tekst.** Med vilje. «Send til regnskap innen
  fredag» i et møtereferat er et vanlig dokument, ikke en felle. Det er dette
  skillet som holder falske positiver nede - og det betyr at en angriper som
  *ikke bryr seg om å skjule noe* ikke blir fanget av skanneren. Da er det
  reglene i `gateway/` som må stoppe handlingen.
- **Sammensatte dokumenter.** Vi har ingen HTML-parser og ingen PDF-leser. Et
  ekte dokumentformat (vedlegg, lag, innebygde objekter, revisjonshistorikk)
  har gjemmesteder vi ikke ser i det hele tatt.

## En felle stopper ingenting

Dette er viktigere enn det ser ut. En felle som går av gir:

- en linje i den låste loggen (`kind="trap"`)
- et varsel i dashbordet

Den gir **ikke** `block`, og den endrer **ikke** risikovurderingen. Det er med
vilje: Lonewatch skal ikke tolke tekst, og en avgjørelse som kunne flyttes av
tekst i et dokument ville vært en ny angrepsflate. Handlingen som FULGTE av
dokumentet må stoppes av reglene på egne felt (beløp, ukjent mottaker,
personopplysninger) - ellers blir den ikke stoppet.

Oppdagelsen er altså etterpå-informasjon: «dette dokumentet prøvde å lure
agenten». Den er verdt å ha, men den er ikke et forsvar.

## Dokumentlisten er ikke lenger fasiten, men den finnes

Demodokumentene i `agents/traps.py` er faste, med vilje: demoen skal være lik
hver gang. Men `trap_triggered()` slår ikke lenger opp `doc_id` i den listen
for å avgjøre om noe er en felle - den skanner innholdet. Et dokument som
kommer inn under kjøringen kan registreres med `traps.register_doc()` slik at
`doc_id` kan slås opp senere; det gjør det ikke til en felle.

`trap_triggered()` tar også et `TrapDoc` direkte, og det er den veien en ekte
dokumentkilde burde gå: skann det du faktisk leste.

## Det som ikke er koblet opp ennå

Broen mot en ekte agent (`agent_gateway/`) sender ikke `source_doc_id` videre
til appen: `lonewatch_read_document` legger dokumentnavnet i `recipient`, og
`AgentSubmitIn` i `ui/app.py` har ikke noe felt for dokumentet. En ekte agent
som leser et felle-merket dokument får derfor **ingen felle, ingen logglinje og
ingen varsellampe** - fellene virker bare i demostrømmen og i historien.

Det krever en endring i `ui/` (ett nytt felt i `AgentSubmitIn` og i
`DemoState.submit_agent`), som eies av en annen økt. Se `docs/E_RAPPORT.md`.

## Scenarioene og historien

- **40 scenarioer, håndskrevet.** De er valgt for å vise fram reglene, ikke for
  å være et representativt utvalg av hva agenter gjør.
- **Ingen tilfeldighet, ingen klokke.** Tidsstemplene er faste, slik at loggen
  blir lik hver gang. Det betyr også at ingenting her tester hvordan systemet
  oppfører seg over ekte tid.
- **Agentene er ikke agenter.** De er `ActionRequest`-objekter. Ingen modell
  bestemmer hva som skjer. Se `agent_gateway/LIMITS.md` for det som er koblet
  til en ekte agent.
