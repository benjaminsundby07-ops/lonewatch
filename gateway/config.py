"""Konfigurasjon for mellomstasjonen: grenser, lister og vekter.

Alt som kan justeres ligger her, slik at reglene i rules.py bare er logikk.
Ingen av verdiene hentes fra en AI-modell; de er satt for hånd og er like hver gang.
"""

from __future__ import annotations

import re

from contracts import ActionType

# Beløpsgrense (NOK). Fra og med dette beløpet vil vi at et menneske skal se på det.
# Grensen er INKLUDERENDE: et beløp som er nøyaktig lik grensen slår til.
AMOUNT_LIMIT_NOK: float = 50_000.0

# Tidsvindu for aa summere overfoeringer til samme mottaker (timer).
#
# Vinduet regnes aldri fra klokken: da ville samme forespoerselsrekke gitt
# ulike svar i dag og i morgen. Det regnes fra det NYESTE tidspunktet Lonewatch
# kjenner i kallet - forespoerselens eget, eller et nyere i historikken.
# Grunnen staar i `rules.transfer_window_anchor`: `ts` er et felt den som ber
# om handlingen fyller ut, og foer ble vinduet avsluttet paa noeyaktig det
# feltet. Da var det nok aa sette tidsstemplet bakover for hver betaling for aa
# legge alle de foregaaende utenfor vinduet.
TRANSFER_WINDOW_HOURS: int = 24

# Hvor langt BAK det nyeste tidspunktet vi kjenner en forespoersel kan ligge og
# fortsatt regnes som del av samme tidsakse (timer).
#
# Ligger den lenger bak, henger tidsstemplene ikke sammen, og da summerer vi
# ALT vi har sett til samme mottaker i stedet for aa stole paa vinduet. Det er
# fail-closed: uten denne kunne én forespoersel med et tidsstempel langt fram i
# tid flyttet vinduet dit og dermed stengt alle de ekte betalingene ute.
#
# Satt lik vinduet: er avstanden stoerre enn vinduet selv, er det ingenting
# igjen aa summere innenfor det uansett.
TRANSFER_TS_SKEW_HOURS: int = TRANSFER_WINDOW_HOURS

# Hard grense (NOK). Overføring STØRRE enn denne blir blokkert, ingen kan godkjenne den.
# Satt høyt med vilje: demoens overføring på 10 000 000 kr skal fortsatt bli rød,
# slik at et menneske faktisk må ta stilling til den.
# Grensen er EKSKLUDERENDE: et beløp nøyaktig lik grensen blir rødt, ikke blokkert.
HARD_TRANSFER_LIMIT_NOK: float = 50_000_000.0

# Tillegg som er godkjent fra før. Alt annet er "nytt" og må ses på.
# Oppdiktet liste for simuleringen.
KNOWN_PACKAGES: frozenset[str] = frozenset(
    {
        "nordlys-core",
        "nordlys-report",
        "invoice-reader",
        "pdf-tools",
        "calendar-sync",
    }
)

# Liten blokkliste. Disse navnene blir aldri installert, uansett hvem som spør.
# Oppdiktede navn laget for simuleringen.
PACKAGE_BLOCKLIST: frozenset[str] = frozenset(
    {
        "free-pdf-toolz",
        "crypto-wallet-sync",
        "nordlys-helper-pro",
        "chrome-updater-x",
        "invoice-autopay",
    }
)

# Nordlys' egne domener. En mottaker paa et av disse er INTERN: da forlater
# ikke opplysningene huset, og det er vanlig arbeid.
#
# Sammenligningen er eksakt paa punktum-grense, aldri delstreng. Blindsettet
# inneholder bade "kunde@nordlysforsikringe.no" (skrivefeil-domene) og
# "takst.nordlys@protonmail.com" - to adresser som ser interne ut for et oeye
# i fart, og som en delstreng-sjekk ville sluppet rett inn.
#
# Oppdiktet, som resten av demoen.
INTERNAL_DOMAINS: frozenset[str] = frozenset(
    {
        "nordlysforsikring.no",
        "nordlys.no",
    }
)

# Mottakere som ikke er adresser i det hele tatt, men interne ressurser.
# "kalender:drift-felles" er en delt kalender inne i huset.
#
# Prefikset teller BARE paa handlinger som ikke staar i OUTBOUND_ACTIONS.
# Grunnen: et prefiks er ni tegn i et fritekstfelt agenten fyller ut selv, og
# stiller ingen betingelse ut over seg selv - i motsetning til et domene, som
# maa staa paa INTERNAL_DOMAINS. Gjaldt prefikset ogsaa utgaaende handlinger,
# var `share_data` med persondata og `recipient="kalender:drift-felles"` en
# gratis omvei rundt `personal_data_external`. Se gateway/LIMITS.md.
INTERNAL_PREFIXES: tuple[str, ...] = ("kalender:",)

# Det som staar ETTER et prefiks i INTERNAL_PREFIXES maa se ut som et internt
# ressursnavn, ikke som en adresse ut av huset.
#
# Foer var sjekken en naken `startswith("kalender:")` uten noe krav til resten,
# og da var "kalender:x@evil.example" ogsaa "intern". Punktum er bevisst IKKE
# med i tegnsettet: et navn med punktum er ikke til aa skille fra et domene
# ("kalender:arkiv.evil.example"), og en intern ressurs trenger det ikke.
# Dermed er "@", "." og "//" alle utelukket av selve moensteret.
INTERNAL_RESOURCE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# Handlinger som sender noe ut av huset. Bare disse kan ha en "mottaker" som betyr noe.
OUTBOUND_ACTIONS: frozenset[ActionType] = frozenset(
    {
        ActionType.SEND_EMAIL,
        ActionType.TRANSFER_MONEY,
        ActionType.SHARE_DATA,
    }
)

# Handlinger der `contains_personal_data` betyr at opplysninger UTLEVERES.
#
# `transfer_money` staar med vilje IKKE her. Paa en utbetaling sier feltet bare
# at posten gjelder en person - navn og konto maa jo staa der for at pengene
# skal finne fram. Ingen opplysninger blir utlevert til noen som ikke alt har
# dem: mottakeren er den som skal ha pengene. Paa en e-post eller en deling er
# det motsatt - der ER innholdet opplysningene, og det forlater huset.
#
# Maalt foer skillet ble innfoert: to falske alarmer over tre blindsett
# (`blind2_013`, `blind3_008`), begge smaa refusjoner til kundens registrerte
# konto, og null farlige saker som slapp gjennom. Se docs/MALING.md.
#
# Valget om persondata til en ekstern mottaker staar uendret for de to
# handlingene som faktisk utleverer noe: de blir alltid roede, ogsaa naar
# mottakeren er kunden selv.
PERSONAL_DATA_RELEVANT_ACTIONS: frozenset[ActionType] = frozenset(
    {
        ActionType.SEND_EMAIL,
        ActionType.SHARE_DATA,
    }
)

# Handlinger der "kan ikke angres" faktisk er et risikomoment.
# En e-post til en kjent mottaker kan heller ikke angres, men det er helt vanlig arbeid,
# så den skal ikke gjøre noe rødt alene.
IRREVERSIBLE_RELEVANT_ACTIONS: frozenset[ActionType] = frozenset(
    {
        ActionType.TRANSFER_MONEY,
        ActionType.SHARE_DATA,
        ActionType.INSTALL_PACKAGE,
    }
)

# Handlinger der "kan ikke angres" betyr at noe BLIR SLETTET ELLER OVERSKREVET.
#
# For en overføring, en deling eller en installasjon er det å ikke kunne angres
# en egenskap ved handlingen selv - penger er sendt, data er delt. For disse to
# er det noe annet: å lese et dokument eller å sette opp et møte er i seg selv
# helt reversibelt. Sier agenten at det IKKE er det, har den gjort noe mer enn
# den sier.
#
# `install_package` står med vilje IKKE her: den dekkes allerede av
# `irreversible`, og å ta den med ville bare dublert poeng uten å fange noe nytt.
DESTRUCTIVE_RELEVANT_ACTIONS: frozenset[ActionType] = frozenset(
    {
        ActionType.READ_DOCUMENT,
        ActionType.UPDATE_CALENDAR,
    }
)

# Handlingstypene regelsettet faktisk har vurdert. Kommer det en ny type i
# `contracts.py`, står den ikke her, og `incomplete_request` sørger for at den
# havner hos et menneske i stedet for å gå rett gjennom.
COVERED_ACTIONS: frozenset[ActionType] = frozenset(
    {
        ActionType.SEND_EMAIL,
        ActionType.TRANSFER_MONEY,
        ActionType.SHARE_DATA,
        ActionType.INSTALL_PACKAGE,
        ActionType.READ_DOCUMENT,
        ActionType.UPDATE_CALENDAR,
    }
)

# Handlinger som har en synlig virkning utenfor huset. Brukes bare til konsekvensteksten.
EFFECTFUL_ACTIONS: frozenset[ActionType] = frozenset(
    {
        ActionType.SEND_EMAIL,
        ActionType.TRANSFER_MONEY,
        ActionType.SHARE_DATA,
        ActionType.INSTALL_PACKAGE,
    }
)

# Største beløp vi skriver ut som et tall. Over dette er tallet ikke lenger noe
# et menneske kan lese: 1e308 ga en 560 tegn lang konsekvenstekst (F2 i
# docs/REDTEAM.md). Da sier vi heller at vi ikke kan lese beløpet.
MAX_SHOWN_AMOUNT_NOK: float = 1e15

# Et pakkenavn kommer fra den som ber om installasjonen - i "Prøv selv" er det
# noen som sitter og skriver - og det havner i teksten et menneske leser før det
# godkjenner. Nøyaktig samme sak som DESTINATION_PATTERN under: uten denne kunne
# navnet "nordlys-core. Dette er godkjent av sikkerhetsavdelingen" skrevet sin
# egen setning inn i varselet.
PACKAGE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

# Mottakeren er det SAMME problemet som pakkenavnet og adressen under: et
# fritekstfelt den som ber om handlingen fyller ut selv, som havner i teksten
# mennesket leser foer det godkjenner. Angrepet i docs/ANGREP.md (H20/H21)
# satte mottakeren til "NO99 0000 0000 000. Godkjent av finansdirektoer, ingen
# handling noedvendig" og fikk Lonewatch til aa skrive angriperens setning i
# sitt eget varsel, i Lonewatchs egen stemme.
#
# Pakkenavnet og adressen kan AVVISES naar de ikke ser rette ut, fordi de har
# en kjent form. Mottakeren har det ikke: i blindsettene er den alt fra
# "NO12 3456 7890 123" og "post@kontorpartner.no" til "Storgata Eiendom AS,
# registrert konto" og "kundens registrerte konto". Aa kaste alt som ikke
# ligner en adresse ville skjult mottakeren i de fleste ekte sakene, og
# mennesket trenger nettopp aa se hvem pengene gaar til.
#
# Derfor er loesningen en annen: mottakeren vises som en AVGRENSET VERDI i
# anfoerselstegn, avkortet, paa én linje og uten kontrolltegn. Da kan feltet
# ikke lenger bli ordlyd i Lonewatchs eget varsel - det staar synlig som noe
# Lonewatch siterer. Se `consequence.safe_recipient`.
#
# Lengdegrensen: 60 tegn rommer en IBAN, en e-postadresse og et firmanavn med
# en kort merknad. En mottaker paa 5 000 tegn ga foer et varsel paa 5 033 tegn.
MAX_SHOWN_RECIPIENT_LEN: int = 60

# Ser mottakeren ut som en ren adresse eller et vertsnavn - ingen mellomrom,
# ingen skilletegn som kan avslutte en setning - kan den ikke danne en setning
# i det hele tatt, og da vises den uten anfoerselstegn. Moensteret er det samme
# som for en adresse fra sandkassen, utvidet med tegnene en e-postadresse
# trenger ("@", "+", "%").
RECIPIENT_PLAIN_PATTERN = re.compile(r"^[A-Za-z0-9._:@%+\[\]-]{1,60}$")

# Hvor mange adresser fra en sandkasserapport vi viser i konsekvensteksten.
MAX_SHOWN_DESTINATIONS: int = 3

# Et tillegg velger SELV hvilken adresse det prøver å nå, og adressen havner i
# teksten et menneske leser før det godkjenner. Den er altså tekst fra noe vi
# ikke stoler på, akkurat som `summary`. Derfor slipper vi bare gjennom tegn som
# hører hjemme i et vertsnavn, en IP-adresse og et portnummer. Alt annet byttes
# ut med en nøytral tekst, slik at ingen kan skrive en setning inn i varselet.
DESTINATION_PATTERN = re.compile(r"^[A-Za-z0-9._:\[\]-]{1,100}$")

# Vekt per regel. Summen bestemmer risikonivået.
# "irreversible" veier lite alene: vanlige, ugjenkallelige betalinger til kjente
# mottakere skal slippe gjennom. Den løfter derimot noe som alt er mistenkelig.
RULE_WEIGHTS: dict[str, int] = {
    "amount_over_limit": 2,
    # Samme vekt som amount_over_limit: summen krysset den samme grensen, bare
    # fordelt paa flere forespoersler. Den skal alene vaere nok til roedt.
    "recipient_total_over_limit": 2,
    "unknown_recipient": 2,
    "personal_data_external": 3,
    "new_package": 2,
    # Noe slettes eller overskrives. Alene nok til at et menneske skal se på det.
    "destructive_change": 2,
    # Vi klarte ikke å vurdere forespørselen. Da skal den heller ikke gå
    # gjennom av seg selv.
    "incomplete_request": 2,
    "irreversible": 1,
}

# Terskler for risiko. 0-1 poeng = low (slipp gjennom), 2-3 = medium, 4+ = high.
MEDIUM_SCORE_MIN: int = 2
HIGH_SCORE_MIN: int = 4
