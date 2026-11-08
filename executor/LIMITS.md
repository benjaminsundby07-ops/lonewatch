# Hva utføreren IKKE klarer

Utføreren er det eneste stedet i Lonewatch som rører omverdenen. Den er med
vilje liten, og det er mye den ikke gjør. Her står hullene, slik at ingen tror
noe annet. Den ikke-tekniske versjonen står i `docs/UTFORER.md`.

## 1. Boka over hva som er forsøkt leses fra loggen - men bare den loggen
**Rettet denne runden.** `AttemptLedger` er fortsatt et sett i RAM, men
`ui/state.py` fyller det fra loggen ved oppstart: hver `"execution"`-linje gjør
at den forespørselen er merket som forsøkt. En omstart lar derfor ikke den
samme forespørselen gå ut en gang til.

Det som FORTSATT ikke holder:

- Boka følger **loggfilen**. Trykker noen Nullstill, begynner en ny logg, og
  boka begynner på nytt sammen med den. Demodataene har faste IDer (`req_0001`
  …), så etter en nullstilling kan de samme forespørslene utføres igjen. Det er
  riktig for en demo og galt for et produkt.
- To prosesser mot samme logg deler ikke bok i sanntid. `vault.LogLock` hindrer
  at det skjer i det hele tatt, så i praksis er det ikke nåbart - men boka er
  ikke en lås, den er en avlesning gjort én gang ved oppstart.
- Alt som har stått i loggen regnes som forsøkt, også det som endte "ikke
  utført". Det er med vilje (se punkt 5), men det betyr at en handling som ble
  nektet av et feil oppsett ikke kan prøves om uten en ny forespørsel.

## 2. Utføringen logges nå - som arten `"execution"`
**Rettet denne runden.** `LogKind` i `contracts.py` har fått `"execution"` som
sjette verdi. Det var den ENE endringen i den låste filen, og den ble gjort med
eierens beslutning.

Hele `ExecutionResult` skrives til loggen: `request_id`, tidspunkt, `executed`,
`status`, den norske "utført / ikke utført"-setningen, hvilken utfører det var,
regelen som eventuelt sa nei, hvor det gikk (maskert) og avtrykket.

To ting er verdt å vite om den linjen:

- **Mottakeren er maskert før den kommer dit.** Teksten kommer fra
  `mail.mask_address()`, altså `o***@nordlys.no`. Det er ikke
  `vault/redaction.py` som rydder opp - den kjenner ikke arten `"execution"` og
  lar payloaden stå som den er. Maskeringen skjer i `executor/mail.py`, og hvis
  noen senere legger et nytt felt i `ExecutionResult`, går det RETT i loggen.
- **Avtrykket står i linjen, men sendes aldri til nettleseren.** Det er det som
  gjør at en `.eml`-fil på disk (den har avtrykket i et hode) kan holdes opp mot
  loggen og svare "ja, dette er den forespørselen som ble godkjent".

Alt som leser loggen tåler arten: `ui/state.py` (tellere, logg-tabell,
tidslinjer), `ui/after_view.py`, `vault/after.py`, loggsjekken og hale-ankeret.
`eval/` leser ikke loggen i det hele tatt. Det er målt i
`tests/test_executor_wiring.py`, som sammenligner Oversikt-tellerne og
Etter-fanen med og uten en `"execution"`-linje.

Hva den nye arten IKKE gir: linjen sier hva utføreren MENTE skjedde. Brekker et
SMTP-kall midtveis, står det "ikke utført" om en e-post som kanskje kom fram
(punkt 5). Loggen er like sann som utføreren, ikke sannere.

## 3. Forseglingen beviser ingenting mot den som kjører koden
Avtrykket (`Approval.request_fingerprint`) er en SHA-256 uten nøkkel. Den
stopper en agent som endrer forespørselen etter godkjenningen, og den stopper
et oppsett som sender feil sak videre. Den stopper ikke noen som kan kjøre
kode i samme prosess: den kan lage en ny `Approval` med det avtrykket den vil.

En signert godkjenning (HMAC med en nøkkel utføreren har og agenten ikke har)
ville hevet listen. Det er ikke gjort.

## 4. Uten forsegling fanger porten lite
Kaller du `execute()` uten en `Approval`, kan porten bare sjekke at
avgjørelsen gjelder samme `id` og samme tidspunkt. En endret mottaker går da
rett gjennom på en `allow`. Derfor skal integrasjonslaget ALLTID forsegle. At
det er lov å droppe forseglingen er en bekvemmelighet for testene, og den er
et hull.

## 5. En handling som feilet kan ha skjedd likevel
Når SMTP-kallet brekker midtveis, vet vi ikke om meldingen gikk ut. Svaret er
"ikke utført", og forespørselen prøves aldri igjen. Det betyr at svaret kan
være feil i den ene retningen: det kan stå "ikke utført" om en e-post som
faktisk kom frem. Vi valgte den feilen framfor to e-poster.

## 6. Localhost-sperren sjekker navnet, ikke hvor pakkene havner
`is_local()` ser på teksten i `LONEWATCH_SMTP_HOST`. Den slår ikke opp navnet
i DNS. Står det `localhost` i en `/etc/hosts` som peker et annet sted, går
trafikken dit, og sperren sier ingenting. Motsatt: et navn som peker på
127.0.0.1 blir avvist fordi navnet ikke ser lokalt ut.

Sperren er der for å hindre et uhell, ikke for å stoppe noen som vil forbi.

## 7. Ingen innlogging, og ingen kontroll på at linjen er kryptert
Det finnes ingen brukernavn og ingen passord i utføreren. En postserver som
krever innlogging kan den ikke snakke med.

`LONEWATCH_SMTP_STARTTLS=1` finnes og slår på STARTTLS med
`ssl.create_default_context()`. **Den er ikke testet mot en ekte server.** Vi
har ingen server som krever TLS å teste mot, og en test mot localhost ville
ikke bevist noe. Regn den som uprøvd kode.

## 8. Bare én handlingstype er ekte
`SmtpExecutor` gjør `send_email`. Alt annet - `transfer_money`, `share_data`,
`install_package`, `read_document`, `update_calendar` - er `SimulatedExecutor`,
som går gjennom samme port og så gjør ingenting. Porten er altså testet for
alle typer; utføringen er ekte for én.

## 9. Postfangeren er et demoverktøy, ikke en postserver
`MailCatcher` tar imot alt fra alle. Ingen innlogging, ingen sjekk av
avsender, ingen kø, ingen videresending. Den binder seg bare til loopback, og
det er den eneste beskyttelsen den har. Den skal aldri kjøre noe annet sted
enn på maskinen til den som holder demoen.

Meldinger over 1 MB avvises med 552 og lagres ikke. Mappen med `.eml`-filer
vokser til noen rydder den.

## 10. Utføreren er koblet inn i `ui/`, ikke i `run_demo.py`
**Endret denne runden.** `ui/state.py` forsegler ved `evaluate()` og utfører to
steder: ved `allow` med én gang, og ved `approved=True` i `respond()`. En rød
sak som venter, en avvist sak og en blokkert sak kommer aldri til utføreren.

Standard er `SimulatedExecutor`. `SmtpExecutor` brukes bare når
`LONEWATCH_EXECUTOR=smtp` er satt, og bare for `send_email`.

`agent_gateway/` kaller den fortsatt ikke direkte - den trenger det ikke:
agentens forespørsler går gjennom `ui/state.py` som alt annet, og blir utført
der. Teksten MCP-tjeneren gir agenten sier fortsatt "UTFØRT (simulert)" uten å
spørre hva utføreren faktisk svarte. Det er et hull i det agenten får vite, ikke
i det som skjer: loggen vet, og dashbordet viser det.

`run_demo.py` er ikke koblet til utføreren. Den er en ren regel- og
loggdemonstrasjon, og skriver fortsatt 88 linjer.
