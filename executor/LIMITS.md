# Hva utføreren IKKE klarer

Utføreren er det eneste stedet i Lonewatch som rører omverdenen. Den er med
vilje liten, og det er mye den ikke gjør. Her står hullene, slik at ingen tror
noe annet. Den ikke-tekniske versjonen står i `docs/UTFORER.md`.

## 1. Boka over hva som er forsøkt lever bare i minnet
`AttemptLedger` er et sett i RAM. Starter du prosessen på nytt, er boka tom, og
den samme forespørselen kan utføres en gang til. Kravet "aldri to ganger"
holder derfor bare innenfor én kjøring.

En ekte versjon ville lest svaret ut av den låste loggen ved oppstart, eller
hatt en egen fil ved siden av. Begge krever at utføringen faktisk LOGGES, og
det er den ikke - se punkt 2.

## 2. Utføringen logges ikke
`ExecutionResult` havner ingen steder. Den returneres til den som kalte
`execute()`, og der stopper den.

Grunnen er at `contracts.py` er låst. `LogKind` er i dag
`Literal["request", "decision", "human", "trap", "sandbox"]`, og det finnes
ingen verdi som passer for en utføring. Å presse resultatet inn i `"decision"`
ville gjort loggen løgnaktig: en avgjørelse og en utføring er to forskjellige
hendelser, og det er forskjellen mellom "vi sa ja" og "det skjedde".

Tre veier videre, ingen av dem valgt her:

- **Legg til `"execution"` i `LogKind`.** Én linje i den låste filen. Alt som
  leser loggen (`ui/`, `vault/after.py`, `eval/`) må tåle en ny art.
- **Legg til en `ExecutionResult`-type i contracts** i tillegg til arten. Mer
  å endre, men da er formen på linjen avtalt mellom modulene i stedet for
  bestemt av `executor/`.
- **Ikke endre contracts.** Utføringen logges som en vanlig `"decision"`- eller
  `"request"`-linje med et felt som sier at dette er en utføring. Loggen
  trenger ingen endring, men den blir vanskeligere å lese riktig, og en teller
  i `ui/` vil regne feil med mindre alle husker å se etter feltet.

Dette er eierens valg, ikke utførerens.

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

## 10. Utføreren er ikke koblet til noe ennå
Ingenting i `agent_gateway/` eller `ui/` kaller `execute()`. Koblingen gjøres
etter sammenslåingen. Hvor den skal gjøres står i `docs/UTFORER.md`.
