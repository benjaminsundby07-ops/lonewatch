# Personvern i Lonewatch

Dette dokumentet beskriver **hva koden faktisk gjør**, ikke hva vi skulle ønske
at den gjorde. Alt under er lest ut av `vault/`, `gateway/` og `ui/state.py`.

**Dette er en hackathon-prototype.** Nordlys Forsikring finnes ikke. Kundene,
polisene, kontonumrene og dokumentene er oppdiktet. Det er ikke brukt ekte
personopplysninger noe sted. Dokumentet er **ikke en juridisk vurdering**, det
er **ikke gjennomgått av jurist**, og vi påstår ikke GDPR-samsvar.

---

## Hva som lagres i loggen

Alt som skjer skrives til én fil som bare vokser (`lonewatch_log.jsonl`). Det
finnes fem slags linjer (`LogKind` i `contracts.py`):

| linje | når | innhold |
|---|---|---|
| `request` | en agent vil gjøre noe | handling, beløp, mottaker, flagg |
| `decision` | mellomstasjonen har bestemt seg | verdikt, risiko, hvilke regler som slo til |
| `human` | et menneske svarte på et rødt varsel | pseudonym, godkjent/avvist, beløpet som ble skrevet, sekunder brukt |
| `trap` | en felle i et dokument gikk av | dokument-id, agent-id, hva fella forsøkte |
| `sandbox` | et tillegg ble kjørt i den lukkede boksen | pakkenavn, adresser, clean/blocked/not_tested, notat |

**I hvilken form:**

- **Kryptert per linje** med Fernet (AES-128-CBC + HMAC). Nøkkelen leses bare fra
  miljøvariabelen `LONEWATCH_LOG_KEY`. Det finnes ingen innebygd standardnøkkel —
  uten nøkkel åpnes ikke loggen i det hele tatt.
- **Hash-kjedet.** Hver linje peker på forrige via SHA-256. En endret eller
  fjernet linje midt i kjeden oppdages av `verify()`.
- **Hale-anker.** En signert sidefil (`<logg>.head`) husker hvor lang loggen var,
  så kutting av de siste linjene også oppdages.
- **Pseudonymer.** Et menneske som godkjenner står som `emp_xxxx` — fire hex-tegn
  fra HMAC-SHA256 med `LONEWATCH_PSEUDONYM_KEY`. Navnet står aldri i loggen.
- **Dataminimering er på** i demoen (`LONEWATCH_REDACT`, av med `=0`).

### Hva dataminimeringen fjerner

- `summary` — agentens frie tekst — kastes helt.
- `recipient` maskeres til de fire siste tegnene: `NO93 8601 1117 947` → `**** 947`.
- `consequence_text` kastes fra avgjørelser, fordi den skriver ut mottakeren i
  klartekst når mottakeren er kjent.
- En `allow`-avgjørelse krympes til id, risiko og verdikt.

### Hva som IKKE anonymiseres

Dette er det viktigste avsnittet i dokumentet.

- **Beløpet** står i klartekst. `10 000 000` er ofte det mest identifiserende
  feltet i en overføring, og vi beholder det fordi Etter-listen og enhver
  gransking trenger det.
- **`agent_id`** står, også `jury` fra «Prøv selv».
- **`source_doc_id`** står, så et dokument kan spores.
- **`package_name`** står rått.
- **`recipient_known`, `reversible`, `contains_personal_data`, `action_type`** —
  alt reglene faktisk brukte.
- **Fellenes `what_happened`** maskeres ikke. Den kan inneholde en e-postadresse
  fra den skjulte teksten i dokumentet; den er selve funnet.
- **Sandkassens `notes`** har adressen i klartekst inne i setningen, selv om
  `destinations` er maskert.
- **Tidspunktet** står på hver linje.

**Fire siste sifre av et kontonummer, pluss beløp, pluss tidspunkt, pluss hvilken
agent — det peker ofte på én transaksjon.** Minimeringen gjør at loggen ikke er
en kopi av kundebasen. Den gjør den ikke anonym. Se `vault/LIMITS.md` punkt 7.

---

## Hvem kan lese loggen

Den som har `LONEWATCH_LOG_KEY`. Det er hele tilgangskontrollen.

- Nøkkelen ligger i en miljøvariabel. Hvem som helst med samme bruker på maskinen
  kan lese prosessens miljø.
- Det finnes ingen rollefordeling: den som har nøkkelen leser **alt**.
- Fernet gir konfidensialitet og integritet med én delt nøkkel, men ingen
  signatur. Loggen kan ikke bevise *hvem* som skrev en linje.
- Nettappen er **uautentisert**. Den binder `127.0.0.1` som standard, men
  `POST /api/reset` krever ingen innlogging.

**Mistes nøkkelen, er loggen borte.** Linjene ligger der, men ingen kan
dekryptere dem — heller ikke vi. Det finnes ingen gjenoppretting, ingen
nøkkelrotasjon og ingen reservenøkkel. Bytter du nøkkel, blir alt som er
skrevet med den gamle uleselig.

Navn-til-kode-tabellen (`lonewatch_pseudonyms.enc`) er kryptert for seg, og
`reveal()` krever `role == "admin"`. Men rollen er bare en streng den som
kaller funksjonen oppgir selv. Det er ingen innlogging bak.

---

## Personopplysninger i en forespørsel

`contains_personal_data` er en av/på-bryter satt av den som lager forespørselen.
Lonewatch leser aldri innholdet og kan ikke selv avgjøre om noe er persondata.

Regelen `personal_data_external` slår til når opplysningene går **ut av huset**:
mottakeren er ikke på Nordlys' eget domene og ikke en intern ressurs. Da blir
forespørselen rød og et menneske må se på den.

**Et kjent kompromiss:** å sende en kunde kundens *egne* opplysninger gir også
rødt varsel. Det er ikke en utlevering til en tredjepart i det hele tatt, men
regelen kan ikke se at mottakeren **er** den opplysningene gjelder. Vi valgte
det bevisst (A-valget i `docs/MALING.md`): alternativet krevde at handlingen
også var ugjenkallelig, og det skillet viste seg å hvile på hvordan et felt
tilfeldigvis var fylt ut.

Prisen er målt: **sju falske alarmer over tre uavhengige sett.** Et ekte
produkt måtte la koblingen mot kunderegisteret avgjøre om mottakeren er kunden
selv — det er et oppslag, ikke en regel.

Reglene teller heller ikke: **én bekreftelse til én kunde og en masseutsending
til 8400 veier likt.** Det finnes ikke noe antall å lese.

---

## Oppbevaring og sletting

Her trekker to ting i hver sin retning, og vi har ikke løst det.

En hash-kjedet logg som bare vokser kan **ikke** rette seg etter et krav om
sletting (GDPR art. 17) uten å knekke kjeden. Sletter du én linje, slutter
`verify()` å stemme fra det punktet. Det er en reell konflikt, ikke en
implementasjonsdetalj.

**Hva som finnes i dag:**

- «Nullstill» i appen arkiverer hele loggen under nytt navn og starter en ny,
  tom. Ingenting slettes, og UI viser hvor den gamle ble lagt.
- Dataminimering reduserer hva som havner i loggen i utgangspunktet.
- Loggen kan slettes manuelt som fil — da er alt borte, og `verify()` kan ikke
  si fra om det.

**Hva som ikke finnes:**

- Ingen oppbevaringstid. Ingenting utløper, og ingenting slettes automatisk.
- Ingen sletting av én person fra loggen.
- Ingen rutine for innsyn, retting eller dataportabilitet.
- Ingen logg over hvem som har *lest* loggen.

---

## Rolle

I en ekte bruk ville Lonewatch vært **databehandler** for kunden som bruker det:
vi behandler opplysninger på deres vegne, etter deres instruks. Det ville krevd
en databehandleravtale, en oversikt over behandlingen, og en avklaring av
overføring til tredjeland.

Ingenting av det finnes her. Dette er en prototype bygget på en hackathon, med
oppdiktede data, og dokumentet er skrevet av utviklerne — ikke av en jurist.

---

## Ikke gjort ennå

- **Oppbevaringstid** og automatisk sletting.
- **Innsyn, retting og sletting** for den registrerte.
- **DPIA** (vurdering av personvernkonsekvenser).
- **Behandlingsprotokoll** (GDPR art. 30).
- **Databehandleravtale** og avklaring av underleverandører.
- **Autentisering** foran appen, og roller for hvem som kan lese hva.
- **Nøkkelhåndtering**: rotasjon, oppdeling, og nøkler ute av miljøvariabler.
- **Logg over innsyn** i loggen.
- **Juridisk gjennomgang** av alt det over.

Les også `vault/LIMITS.md` (hva loggen ikke klarer), `gateway/LIMITS.md` (hva
reglene ikke ser) og `sandbox/LIMITS.md` (hvorfor sandkassen ikke er isolasjon).
