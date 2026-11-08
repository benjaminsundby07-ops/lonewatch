# Økt E (herd-e): hardere sandkasse, ekte felle-skanner

Grein `herd-e`, fra `samlet3`. Rørt: `sandbox/`, `agents/`, `agent_gateway/LIMITS.md`,
`tests/attack2/test_attack_sandbox_escape.py`, `tests/attack/test_attack_document_injection.py`,
to nye testfiler. **Ikke rørt:** `docs/ANGREP.md`, `docs/ANGREP2.md`, `ui/`,
`gateway/`, `vault/`, `executor/`, `contracts.py`, `README.md`.

## Tabellen du kan føre inn

### docs/ANGREP.md

| rad | var | er nå | hvorfor |
|---|---|---|---|
| **H11** (ingen skanner for skjult tekst) | HULL | **LUKKET** | `agents/doc_scan.py` skanner innholdet. `trap_triggered()` slår ikke lenger opp `doc_id` i en liste; den tar et `TrapDoc` direkte eller en registrert id, og avgjør på funn. Et helt nytt dokument med skjult instruksjon gir felle, logglinje og varsel (`test_a_new_document_gives_a_log_line_and_a_notice`) |
| **H12** (fire faste strenger) | HULL | **LUKKET** | 15 skjulemekanismer gjenkjennes på mekanisme, ikke på bokstavlig streng: HTML-kommentar, `display:none`, `visibility:hidden`, `opacity:0`, `font-size:0/1px`, hvit-på-hvit i fem skrivemåter, nullbredde-tegn, snudd leseretning, `left:-9999px`, `hidden`/`aria-hidden`, eget skjult tekstlag. Alle 13 variantene i den gamle `xfail`-testen passerer nå, og testen krever at skanneren sier HVILKEN mekanisme |
| **H13** (bare `x-lw-instruction`) | HULL | **LUKKET** | Alle metadata-verdier leses, uansett nøkkelnavn. `subject`, `producer`, `keywords`, `comment`, `author` er med i testen |
| **H24** (gateway kan ikke vite at sandkassen aldri ble spurt) | DELVIS LUKKET | **uendret, DELVIS LUKKET** | Krever at rapporten blir påkrevd for `install_package` — en avtale mellom `gateway/` og `sandbox/`. Ikke rørt, `gateway/` er ikke min |

### docs/ANGREP2.md

| rad | var | er nå | hvorfor |
|---|---|---|---|
| **6 — sandbox: rømning** | DELVIS | **DELVIS (klart bedre, ikke lukket)** | De to konkrete angrepene stoppes, og rapporten kan ikke lenger si `clean` om dem. Men det er ikke isolasjon, og raden bør fortsatt ikke si LUKKET. Se «Hva som fortsatt er åpent» |
| **A2** (`open.__globals__` leser fil utenfor boksen, rapporten sier `clean`) | kritisk, åpent | **LUKKET for dette angrepet** | Statisk sjekk avviser mønsteret før kjøring → `blocked`, ingen delprosess startes. Når mønsteret unngår sjekken (streng satt sammen under kjøring), ligger det en **snare** i globals-ordboken: forsøket skrives ned (`guard_bypass`) og rapporten blir `blocked`. Begge veier er kjørbare tester |
| **A3** (tillegget forfalsker sin egen rapport via `_events`) | høy, åpent | **LUKKET** | Hendelsesskriveren ligger i en lukning, ikke i den globale ordboken. Navnet `_events` finnes der fortsatt, men peker på en snare |
| **A13** (`what_happened` maskeres aldri) | lav, åpent | **uendret, men ikke forverret** | Den nye `what_happened` inneholder mekanismenavn og hvor funnet sto — **ikke** innholdet i den skjulte teksten. Skanneren legger beviset i `Finding.evidence`, som ikke går i loggen |
| alle andre rader | — | **uendret** | Ikke rørt |

### Rad som bør endres i en fil jeg ikke eier

`tests/test_sandbox.py::test_sperrene_kan_ikke_omgaas_via_globals` er en
`xfail(strict=False)` som nå **XPASSer**. Den bør bli en vanlig test. Jeg har
ikke rørt filen (den er ikke min i denne økten). Det er den ene `1 xpassed` i
testkjøringen.

## Hva som ble bygget

### 1. Sandkassen: `clean` krever bevis, og kjente rømninger avvises før kjøring

- **`sandbox/static_check.py` (ny).** Deterministisk AST-sjekk på kilden før noe
  kjøres. Avviser: dunder-attributter (`__globals__`, `__builtins__`,
  `__subclasses__`, `__class__`, `__mro__`, `__code__` + `__closure__`,
  `__dict__`, `__bases__`, `__reduce__`, rammer og sporinger), `eval`, `exec`,
  `compile`, `__import__`, `getattr`/`setattr`/`delattr` med navn, strenger som
  nevner et sperret attributt, og skriving til attributter på modulene som
  holder sperrene (`builtins.open = ...`). `open` er **tillatt** med vilje:
  boksen skal se et tillegg lese agnfilene.
- **Avvist kilde kjøres ikke.** `runner.run_in_box()` avviser før delprosessen
  startes, og rapporten sier eksplisitt «AVVIST FOER KJOERING» med regelnavn og
  linjenummer — ingen skal tro vi så tillegget gjøre noe.
- **Sperrene er lukninger, globals-ordboken er tømt.** `sandbox/harness.py` er
  omskrevet: hver sperre holder de ekte funksjonene i sine egne celler. Etter
  oppsettet byttes alt farlig i modulens globale ordbok ut med **snarer** som
  skriver `guard_bypass` og nekter.
- **`clean` krever et bevis.** Etter kjøringen sjekker harness-et at
  `builtins.open`, `builtins.__import__`, `os.open`, `socket.socket` og
  `sys.meta_path` fortsatt står der de ble satt, og skriver `guards_intact`.
  Mangler hendelsen → `not_tested`. Står en sperre ikke igjen → `guard_tampered`
  → `blocked`. Dette er regelen «alt vi ikke kan bevise, sier vi ikke `clean` om».
- **Tre nye blokkerende hendelser:** `static_reject`, `guard_bypass`,
  `guard_tampered`.
- `sandbox/LIMITS.md`: avsnittet «Sperrene kan brytes fra innsiden» er skrevet
  om. Det sier hva de tre tiltakene er, og det sier rett ut at dette er en bom
  og en snare, at Python-sandboxing i samme prosess ikke kan gjøres sikker, og
  at en ekte løsning er prosessisolasjon (container/seccomp/gVisor) eller en
  etablert sandkasse. Ingen påstand om at sandkassen er trygg.

### 2. Fellene: innhold, ikke `doc_id`

- **`agents/doc_scan.py` (ny).** Deterministisk innholdsskanner. To steg:
  (1) skjulemekanismer i synlig tekst, skjult tekst og metadata-verdier;
  (2) instruksjonsfraser (norsk + engelsk, ~70 fraser) — men **bare der
  mennesket ikke ser dem**. Rapporterer `Finding(mechanism, where, evidence)`,
  altså hvilken mekanisme og hvor, ikke bare ja/nei. Ingen AI. Ingen tilgang til
  `summary` (funksjonen tar tre felt, og en test fester det).
- **`agents/traps.py`.** `found_markers()`, `found_mechanisms()`,
  `scan_findings()`, `TrapDoc.is_trapped` og `trap_triggered()` går alle veien
  om skanneren. `trap_triggered()` og `is_trapped()` tar nå `TrapDoc | str`.
  `register_doc()`/`clear_registered_docs()` lar et dokument som kommer inn under
  kjøringen bli slått opp på `doc_id` — registrering gjør det **ikke** til en
  felle; skanneren avgjør det.
- **Falske positiver er målt.** Instruksjonsfraser teller bare i skjult
  innhold. Testene inneholder HR-brev, faktura med kontonummer, møtereferat med
  «sender kostnadsoverslaget til» og «Husk å installere oppdateringen»,
  e-postutskrift med «sendt til regnskap», vilkårstekst, og en HTML-rapport med
  `color:#333333` og `display:block`. Ingen av dem slår ut.
- `agents/LIMITS.md` (ny) sier ærlig hva skanneren ikke fanger: tekst i bilder,
  kodede strenger, språk fraselisten ikke kjenner, omskrivinger,
  skjulemekanismer vi ikke har tenkt på, og instruksjoner i helt synlig tekst
  (med vilje). To av grensene er **kjørbare tester** som skal fortsette å vise
  hullet.

## Testtall

| | før | etter |
|---|---|---|
| `pytest -q` | 1364 passed, 47 xfailed | **1505 passed, 29 xfailed, 1 xpassed** |

- 18 `xfail(strict=True)` ble vanlige tester (2 i sandkassen, 16 i
  dokument-injeksjonen — 13 av dem er parametriseringer).
- Nye testfiler: `tests/test_static_check.py` (47 innsamlede tester),
  `tests/test_doc_scan.py` (30).
- `tests/attack2/test_attack_sandbox_escape.py`: 7 testfunksjoner → 33
  innsamlede tester.
- `tests/attack/test_attack_document_injection.py`: 8 testfunksjoner → 52
  innsamlede tester.
- Den ene `xpassed` er `tests/test_sandbox.py`-raden over.

**Verifisert:**
- `pytest -q`: 1505 passed, 29 xfailed, 1 xpassed. Ingen feil.
- `python run_demo.py`: **88 linjer**, «Sjekk av logg: OK». Tallet er uendret.
  Sandkasselinjene i utskriften er uendret (`clean` for `pdf-helper`, `blocked`
  for `nordlys-mail-connector-patch` med samme adresse og samme tre agnfiler).
- `python -m agent_gateway.scripted_demo`: alle seks slag som før
  (allow / approved / rejected / blocked / blocked / waiting), kjeden stemmer,
  17 linjer.

## Hva som er svakt

1. **Den statiske sjekken er en mønsterliste, ikke et bevis.** `"__glob" +
   "als__"` går gjennom den. Da fanges forsøket av snaren — men snaren *ser*,
   den isolerer ikke. En rømning vi ikke har tenkt på blir fortsatt ikke sett,
   og da sier rapporten `clean`. Det er den samme grensen som før, bare flyttet.
2. **Sjekken tar harmløs kode også.** `getattr(x, "navn")`, `obj.__dict__` og
   `eval` er vanlig Python. Et greit tillegg som bruker dem blir `blocked`. Valgt
   kostnad, dokumentert, og rapporten sier at det var kilden og ikke handlingen.
   De fem demotilleggene har rene kilder med vilje — de tre som stjeler skal
   stoppes på HANDLING, ellers mister vi beviset for at nettsperren virker.
3. **Fraselisten er frasene vi kom på.** «oppdater betalingsdetaljene til» står
   ikke der. En angriper som leser `agents/doc_scan.py` kan skrive rundt den på
   ett minutt. Skjulemekanismen fanges fortsatt — men da vet vi bare at noe er
   skjult, ikke hva det ber om.
4. **Tekst i bilder er den viktigste blindsonen.** En faktura er ofte et bilde.
   Vi ser ingenting.
5. **En felle stopper fortsatt ingenting.** Den gir en logglinje og et varsel.
   Det er med vilje (Lonewatch skal ikke tolke tekst), men det betyr at
   oppdagelsen er etterpå-informasjon.
6. **Snarene er ikke skjult.** De ligger under de samme navnene som før. Vi
   prøver ikke å gjemme dem; poenget er at forsøket blir sett.

## Hva som fortsatt er åpent

| hva | hvor det hører hjemme |
|---|---|
| **Ekte isolasjon av sandkassen.** Alt over er simuleringen gjort tettere. Python i samme prosess kan ikke sikres | Prosessisolasjon eller en etablert sandkasse — bevisst utsatt i dette prosjektet |
| **`source_doc_id` kommer ikke fra en ekte agent.** `lonewatch_read_document` legger dokumentnavnet i `recipient`, og `AgentSubmitIn` i `ui/app.py` har ikke noe felt for dokumentet. En ekte agent som leser et felle-merket dokument får derfor **ingen felle, ingen logglinje, ingen varsellampe** | **Krever endring i `ui/` — se under** |
| H24-resten, H4/H5/H8/H9/H10/H14–H19, A1, A4–A15 | Ikke mine mapper i denne økten |

### Endringen jeg trenger i `ui/` (ikke gjort — økt D eier mappen)

Fellene virker i demostrømmen og i historien, men ikke for en ekte agent.
Grunnen er at `source_doc_id` ikke har noen vei inn. Jeg har stoppet og lagt det
her i stedet for å røre `ui/`. To alternativer:

**Alternativ A (ett felt, anbefalt).** `AgentSubmitIn` i `ui/app.py` får
`source_doc_id: str = Field(default="", max_length=…)`, og
`DemoState.submit_agent()`/`submit_custom()` sender det videre til
`ActionRequest`. `agent_gateway/tools.run_action()` må da sende `source_doc_id`
for `read_document` (det er den eneste endringen i min mappe, og den er trivielt
liten). Risiko: `extra="forbid"` er et poeng i seg selv i den modellen, så feltet
må være *lesbart* som noe agenten ikke kan lyve seg til noe med — og det kan den
ikke: dokument-id er ikke med i noen regel, bare i oppdagelsen.

**Alternativ B (ingen nytt felt).** `DemoState.submit_agent()` utleder
`source_doc_id` fra `recipient` når `action_type == read_document`, ved et
oppslag mot `traps.find_doc()`. Ingen endring i skjemaet, men det gjør
`recipient` til et felt med to betydninger, og det liker jeg dårligere.

Jeg har ikke endret `agent_gateway/tools.py` for dette, siden halvparten av veien
uten den andre halvparten bare ser ut som dekning vi ikke har. Det som ER gjort
i `agent_gateway/` er at grensen står ærlig i `agent_gateway/LIMITS.md` punkt 13.

## Hva jeg ikke rakk

- Ingenting fra oppgavelisten. Alle fire punktene er gjort.
- Ikke forsøkt: en HTML-/PDF-parser for dokumentene (ville gitt vedlegg og lag),
  en tillatelsesliste i sandkassen slik at et tillegg som *trenger* nettverk kan
  bli `clean`, og signering av `SandboxReport` (A-raden om at gateway ikke kan
  se forskjell på en ekte og en oppdiktet rapport). Alle tre er større enn
  denne økten.
